"""REST API service: one Autology deployment, shared by many users and applications.

    python -m autology serve server.json [--host 127.0.0.1] [--port 8800]
    python -m autology token          # new API token + the hash to put in server.json

Standard library only (``http.server``). Configuration (paths relative to the config file)::

    {
      "ontology": "ontology.json",
      "store": "autology.db",                # SQLite store (created on first start)
      "data": "data.json",                   # optional: imported into an empty store
      "agents": {
        "fulfilment": {"roles": ["ops", "eu_ops", "finance"], "tools": "tools.json",
                       "goals": ["fulfil_contract"], "delegates": [], "approver": "inbox"}
      },
      "users": [
        {"name": "olivia", "token_sha256": "<hash>", "permissions": ["read", "run"], "roles": ["ops"]},
        {"name": "ci-bot", "token_env": "AUTOLOGY_TOKEN_CI", "permissions": ["read"]},
        {"name": "lena", "token_sha256": "<hash>", "permissions": ["read", "review"],
         "roles": ["ops", "eu_ops"], "reviewer_roles": ["logistics_manager"]}
      ],
      "automations": {...},                  # optional: see autology.automation
      "automation_interval": 60,             # seconds between scheduled ticks (serve only)
      "webhooks": [{"url": "https://hooks.example.com/autology", "kinds": ["review", "automation"]}],
      "chat": {"model": "claude-opus-5-5", "effort": "medium"},  # optional: governed assistant (autology.chat)
      "tracing": {"endpoint": "http://localhost:4318/v1/traces"}  # optional: OpenTelemetry export of final runs
    }

Permissions: ``read`` (ontology, objects, runs, reports), ``run`` (start / resume runs), ``review``
(decide reviews for the user's ``reviewer_roles``), ``audit`` (raw audit entries), ``admin`` (everything,
including data upload). A user's ``roles`` are ontology roles: row and field access rules apply to
everything the API returns to them. Agent ``approver`` ``"inbox"`` (default) parks reviews for people
to decide through the API / web inbox; any other value is an approver spec (``auto``, policy file...).

Security notes: tokens are random, only their SHA-256 hashes are stored, comparison is constant-time.
Bind to localhost or put the service behind TLS. Request bodies are limited to 1 MB.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .agent import DeferredApprover, ReviewDecision, WorkAgent
from .automation import Automation, Automator, Firing, load_automations
from .governance import REDACTED, GovernanceLayer, Principal

JUSTIFY = "***justification required***"
from .graph import Instance, KnowledgeGraph, build_case, snapshot, write_back
from .ontology import Ontology, OntologyError
from .store import Store, StoreError

log = logging.getLogger("autology.server")
PERMISSIONS = frozenset({"read", "run", "review", "audit", "ingest", "admin"})
FINAL_STATUSES = frozenset({"completed", "blocked", "escalated", "suspended"})
MAX_BODY = 1_000_000
STATIC = Path(__file__).resolve().parent / "static"


class ApiError(Exception):
    def __init__(self, status: int, message: str, extra: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = dict(extra or {})


@dataclass(frozen=True)
class User:
    name: str
    token_sha256: str
    permissions: FrozenSet[str]
    roles: FrozenSet[str] = frozenset()
    reviewer_roles: FrozenSet[str] = frozenset()

    def can(self, permission: str) -> bool:
        return "admin" in self.permissions or permission in self.permissions

    @property
    def principal(self) -> Principal:
        return Principal(self.name, self.roles)


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> Tuple[str, str]:
    token = "atl_" + secrets.token_urlsafe(32)
    return token, hash_token(token)


@dataclass
class AgentConfig:
    name: str
    agent: WorkAgent
    goals: List[str]
    lock: threading.Lock = field(default_factory=threading.Lock)


class AutologyService:
    """The API's behaviour, independent of HTTP (so it can be tested and embedded directly)."""

    def __init__(self, config: Dict[str, Any], base_dir: Path = Path(".")):
        from .adapters import load_approver, load_reasoner, load_tools

        base = Path(base_dir)
        rel = lambda p: str((base / p).resolve())  # noqa: E731
        self.ontology = Ontology.load(rel(config["ontology"]))
        self.store = Store(rel(config["store"]) if config.get("store", ":memory:") != ":memory:" else ":memory:")
        if config.get("data") and self.store.count_instances() == 0:
            data = json.loads(Path(rel(config["data"])).read_text(encoding="utf-8"))
            self.store.save_graph(KnowledgeGraph.from_dict(self.ontology, data))
        self.graph = self.store.load_graph(self.ontology)
        self.graph_lock = threading.RLock()
        self.access = GovernanceLayer(self.ontology, max_violations=0)  # row/field rules for API callers
        # simulation mode: requesters may supply case data, and automatic approvers may decide reviews.
        # It is shown in /api/health and in every report and score.
        self.simulation = bool(config.get("simulation", False))
        self.scheduler_status: Dict[str, Any] = {"last_tick": None, "last_error": None}
        if config.get("log_file"):  # the server log: failures with tracebacks (also on stderr under serve)
            path = str((base / config["log_file"]).resolve())
            root = logging.getLogger("autology")
            if not any(getattr(h, "baseFilename", None) == path for h in root.handlers):
                handler = logging.FileHandler(path, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
                root.addHandler(handler)
            root.setLevel(min(root.level or logging.INFO, logging.INFO))
        from .audit import KEY_ENV, audit_key

        if audit_key() is None and not self.simulation:
            raise ValueError(f"set {KEY_ENV} to a secret so the audit chain is keyed (HMAC); without it anyone who "
                             "can edit the store can rewrite the log undetected")
        self.agents: Dict[str, AgentConfig] = {}
        for name, spec in (config.get("agents") or {}).items():
            delegates = [WorkAgent(d["name"], self.ontology, load_tools(rel(d["tools"])), roles=d.get("roles", []))
                         for d in spec.get("delegates", [])]
            approver_spec = spec.get("approver", "inbox")
            approver = DeferredApprover() if approver_spec == "inbox" else load_approver(
                rel(approver_spec) if str(approver_spec).endswith(".json") else approver_spec)
            if getattr(approver, "can_approve", False) and not self.simulation:
                raise ValueError(f"agent {name}: approver {approver_spec!r} approves human reviews without a "
                                 "person; use \"inbox\", or set \"simulation\": true for a test server")
            agent = WorkAgent(name, self.ontology, load_tools(rel(spec["tools"])), roles=spec.get("roles", []),
                              delegates=delegates, approver=approver,
                              reasoner=load_reasoner(spec.get("reasoner"), (str(base),)))
            goals = list(spec.get("goals") or self.ontology.goals)
            unknown = [g for g in goals if g not in self.ontology.goals]
            if unknown:
                raise OntologyError(f"agent {name}: unknown goals {unknown}")
            self.agents[name] = AgentConfig(name, agent, goals)
            held = self.store.active_suspension(name)
            if held:  # a suspension outlives restarts: only an admin reinstates the agent
                agent.governance.suspended[agent.principal.name] = held["reason"]
        self.users: List[User] = []
        for u in config.get("users", []):
            perms = frozenset(u.get("permissions", ["read"]))
            if perms - PERMISSIONS:
                raise ValueError(f"user {u['name']}: unknown permissions {sorted(perms - PERMISSIONS)}")
            digest = u.get("token_sha256", "")
            if u.get("token_env"):  # token supplied through the environment at start-up, never stored in the file
                import os

                token = os.environ.get(u["token_env"])
                if not token:
                    raise ValueError(f"user {u['name']}: environment variable {u['token_env']} is not set")
                digest = hash_token(token)
            if len(digest) != 64:
                raise ValueError(f"user {u['name']}: token_sha256 must be a SHA-256 hex digest (see `autology token`)")
            self.users.append(User(u["name"], digest.lower(), perms, frozenset(u.get("roles", [])),
                                   frozenset(u.get("reviewer_roles", []))))
        self._token_user_names = frozenset(u.name for u in self.users)
        self.oidc = None
        if config.get("oidc"):
            from .oidc import OidcProvider

            self.oidc = OidcProvider(config["oidc"])
            unknown = self.oidc.permissions_in_mappings() - PERMISSIONS
            if unknown:
                raise ValueError(f"oidc.mappings: unknown permissions {sorted(unknown)}")
        self.automations = load_automations(config.get("automations") or {}, self.ontology,
                                            {n: a.goals for n, a in self.agents.items()})
        self.automation_interval = float(config.get("automation_interval", 60))
        from .ingest import load_pipelines

        self.pipelines = load_pipelines(config.get("pipelines") or {}, self.ontology, base)
        self.ingest_lock = threading.Lock()  # one load at a time: plans are computed against the current graph
        self.reporting = dict(config.get("reporting") or {})
        if self.reporting:
            target = self.reporting.get("target")
            if isinstance(target, str):
                self.reporting["target"] = str((base / target).resolve())
            elif not (isinstance(target, dict) and target.get("driver") and target.get("dsn_env")):
                raise ValueError("reporting.target must be a SQLite path or {\"driver\", \"dsn_env\"}")
            for ref in self.reporting.get("include_fields", []):
                self.ontology._check_field(ref, "reporting include_fields")
        self._last_report: Optional[float] = None
        self._verified: Tuple[float, int] = (0.0, 0)
        self.webhooks: List[Dict[str, Any]] = []
        for hook in config.get("webhooks", []):
            if urlparse(str(hook.get("url", ""))).scheme not in ("http", "https"):
                raise ValueError(f"webhook {hook.get('url')!r}: url must be http or https")
            self.webhooks.append({"url": hook["url"], "kinds": set(hook.get("kinds") or [])})
        self.deliveries: List[threading.Thread] = []  # webhook deliveries in flight (joined by tests)
        self.automator = Automator(self.automations, self.store, self._graph_instances, self._fire)
        from .views import ViewPolicy

        self.views = ViewPolicy(self)  # what each user may see of runs and reviews
        from .chat import GovernedChat, load_backend

        self.tracing = dict(config.get("tracing") or {})
        if self.tracing and urlparse(str(self.tracing.get("endpoint", ""))).scheme not in ("http", "https"):
            raise ValueError("tracing endpoint must be an http or https URL")
        redact = dict(config.get("chat_redact") or {})
        # never sent to the model provider by the assistant, whatever the user may see (default: confidential)
        self.chat_redact_sensitivities = set(redact.get("sensitivities", ["confidential"]))
        self.chat_redact_fields = set(redact.get("fields", []))
        for ref in self.chat_redact_fields:
            self.ontology._check_field(ref, "chat_redact")
        backend = load_backend(config.get("chat"), (str(base),))
        self.chat = GovernedChat(self, backend) if backend else None

    @classmethod
    def from_file(cls, path: str, store: Optional[str] = None) -> "AutologyService":
        """Load a server config; ``store`` overrides its store path (e.g. a volume in a container)."""
        p = Path(path).resolve()
        config = json.loads(p.read_text(encoding="utf-8"))
        if store:
            config["store"] = str(Path(store).resolve())
        return cls(config, p.parent)

    # -- auth ---------------------------------------------------------------
    def authenticate(self, header: Optional[str]) -> User:
        if not header or not header.startswith("Bearer "):
            raise ApiError(401, "missing bearer token")
        token = header[7:].strip()
        if self.oidc is not None and token.count(".") == 2:  # a JWT from the identity provider
            return self._sso_user(token)
        digest = hash_token(token)
        found = None
        for user in self.users:  # compare against every user: constant time per user, no early exit
            if hmac.compare_digest(digest, user.token_sha256):
                found = user
        if found is None:
            raise ApiError(401, "invalid token")
        return found

    def _sso_user(self, token: str) -> User:
        from .oidc import OidcError

        try:
            claims = self.oidc.verify(token)
            name = self.oidc.username(claims)
        except OidcError as exc:
            raise ApiError(exc.status, str(exc)) from None
        if name in self._token_user_names:
            raise ApiError(401, f"the identity provider's user {name!r} has the name of an API-token user; "
                                "use another username_claim")
        grants = self.oidc.grants(claims)
        if not grants["permissions"]:
            raise ApiError(403, f"{name} signed in, but no oidc mapping grants them access to Autology")
        return User(name, "", grants["permissions"], grants["roles"], grants["reviewer_roles"])

    def sso_config(self) -> Dict[str, Any]:
        from .oidc import OidcError

        if self.oidc is None:
            return {"oidc": False}
        try:
            return self.oidc.login_config()
        except OidcError as exc:
            raise ApiError(exc.status, str(exc)) from None

    def sso_token(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """The inbox's sign-in: exchange an authorization code (PKCE) for a verified ID token."""
        from .oidc import OidcError

        if self.oidc is None:
            raise ApiError(404, "single sign-on is not configured")
        try:
            out = self.oidc.exchange(body.get("code"), body.get("code_verifier"), body.get("redirect_uri"),
                                     body.get("nonce"))
        except OidcError as exc:
            raise ApiError(exc.status, str(exc)) from None
        user = self._sso_user(out["token"])  # same checks as every later request: collisions, no access
        return {**out, "name": user.name}

    @staticmethod
    def require(user: User, permission: str) -> None:
        if not user.can(permission):
            raise ApiError(403, f"{user.name} lacks the {permission!r} permission")

    # -- data access for API callers ----------------------------------------
    def _rule_applies(self, rule, inst: Instance) -> bool:
        if rule.when is None:
            return True
        if {e for e, _ in rule.when.references} - {inst.type}:
            return True  # depends on other entities: be conservative and apply it
        return rule.check(lambda e, a: inst.get(a) if e == inst.type else None)[0]  # unknown facts: applies

    def visible(self, inst: Instance, user: User) -> bool:
        if "admin" in user.permissions:
            return True
        for rule in self.ontology.rules_of("row_access"):
            if rule.params["entity"] == inst.type and self._rule_applies(rule, inst) and \
                    not user.roles & set(rule.params["roles"]):
                return False
        return True

    def field_hidden(self, inst: Instance, attr: str, user: User) -> bool:
        """Does a data_access rule hide this field of this record from the user?"""
        ref = f"{inst.type}.{attr}"
        return "admin" not in user.permissions and any(
            r.params["field"] == ref and self._rule_applies(r, inst) and not user.roles & set(r.params["roles"])
            for r in self.ontology.rules_of("data_access"))

    def field_value(self, inst: Instance, attr: str, user: User, justified: bool = False) -> Any:
        if self.field_hidden(inst, attr, user):
            return REDACTED
        if f"{inst.type}.{attr}" in self.views.gated and not justified:
            return JUSTIFY
        return inst.attributes.get(attr)

    def object_view(self, inst: Instance, user: User, justified: bool = False) -> Dict[str, Any]:
        attrs = {attr: self.field_value(inst, attr, user, justified) for attr in inst.attributes}
        out = {"id": inst.id, "type": inst.type, "attributes": attrs}
        computed = {}
        for fn in self.ontology.functions.values():
            if fn.entity != inst.type or {e for e, _ in fn.expr.references} - {inst.type}:
                continue  # functions that need other objects are computed within a case, not on one object
            if any(attrs.get(a) in (REDACTED, JUSTIFY) for _, a in fn.expr.references):
                computed[fn.name] = REDACTED  # never computed from fields the caller may not see
            else:
                computed[fn.name] = fn.expr.value(lambda e, a: inst.get(a))
        if computed:
            out["functions"] = computed
        return out

    # -- checkpoints: a written justification before sensitive operations ------------------
    def _checkpoints(self, op: str, **context: Any) -> List[Any]:
        out = []
        for rule in self.ontology.rules_of("checkpoint"):
            p = rule.params
            if p["on"] != op:
                continue
            if any(p.get(k) is not None and p[k] != v for k, v in context.items() if k != "fields"):
                continue
            if op == "read_field" and p["field"] not in context.get("fields", ()):
                continue
            out.append(rule)
        return out

    def checkpoint(self, user: User, op: str, target: str, justification: Any, **context: Any) -> bool:
        """Enforce the checkpoint rules for an operation. Raises 428 with what to provide when the
        justification is missing or too short; records it (append-only) when given. Returns whether
        any checkpoint applied."""
        rules = self._checkpoints(op, **context)
        if not rules:
            return False
        text = str(justification or "").strip()
        need = max(int(r.params.get("min_length", 10)) for r in rules)
        if len(text) < need:
            raise ApiError(428, f"{op} needs a justification of at least {need} characters", {"checkpoint": {
                "rules": [r.id for r in rules], "prompt": " ".join(r.description for r in rules if r.description)
                or "Why is this needed?", "min_length": need}})
        for r in rules:
            self.store.add_justification(user.name, r.id, op, target, text)
        return True

    # -- endpoints --------------------------------------------------------------
    def me(self, user: User) -> Dict[str, Any]:
        return {"name": user.name, "permissions": sorted(user.permissions), "roles": sorted(user.roles),
                "reviewer_roles": sorted(user.reviewer_roles)}

    def ontology_summary(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        o = self.ontology
        return {"ref": o.ref, "fingerprint": o.fingerprint, "description": o.description, "modules": list(o.modules),
                "free_form_cases": self.simulation or "admin" in user.permissions,
                "case_templates": {t.name: {"root": t.root} for t in o.case_templates.values()},
                "entities": {e.name: {"states": list(e.states), "multiple": e.multiple, "aliases": list(e.aliases),
                                      "attributes": {a.name: a.type for a in e.attributes.values()}}
                             for e in o.entities.values()},
                "actions": {a.name: {"description": a.description, "for_each": a.for_each} for a in o.actions.values()},
                "goals": {g.name: {"description": g.description, "target": str(g.target)} for g in o.goals.values()},
                "functions": {k: {"returns": f.returns, "expr": f.source, "description": f.description}
                              for k, f in o.functions.items()},
                "interfaces": {i.name: {"attributes": {a.name: a.type for a in i.attributes.values()},
                                        "implementers": list(o.implementers(i.name))} for i in o.interfaces.values()},
                "rules": [{"id": r.id, "kind": r.kind, "description": r.description} for r in o.rules],
                "questions": [{"id": q.id, "question": q.question} for q in o.questions],
                "assistant": self.chat is not None,
                "agents": {n: {"goals": a.goals, "roles": sorted(a.agent.principal.roles)} for n, a in self.agents.items()}}

    def _gated_fields(self, insts: List[Instance]) -> List[str]:
        return sorted({f"{i.type}.{a}" for i in insts for a in i.attributes})

    def _justified(self, user: User, insts: List[Instance], justification: Optional[str]) -> bool:
        """Reveal checkpoint-gated fields only with a justification (otherwise they read JUSTIFY)."""
        if not justification or not insts:
            return False
        return self.checkpoint(user, "read_field", ",".join(i.id for i in insts)[:400], justification,
                               fields=self._gated_fields(insts))

    def list_objects(self, user: User, entity_type: Optional[str], limit: int, offset: int,
                     justification: Optional[str] = None) -> Dict[str, Any]:
        self.require(user, "read")
        entity_type = self.ontology.canonical(entity_type) if entity_type else entity_type
        if entity_type and entity_type not in self.ontology.entities and entity_type not in self.ontology.interfaces:
            raise ApiError(404, f"unknown entity type {entity_type!r}")
        with self.graph_lock:
            found = [i for i in self.graph.instances(entity_type) if self.visible(i, user)]
            found.sort(key=lambda i: i.id)
            page = found[offset:offset + limit]
            justified = self._justified(user, page, justification)
            return {"total": len(found), "items": [self.object_view(i, user, justified) for i in page]}

    def get_object(self, user: User, iid: str, justification: Optional[str] = None) -> Dict[str, Any]:
        self.require(user, "read")
        with self.graph_lock:
            try:
                inst = self.graph.get(iid)
            except KeyError:
                raise ApiError(404, f"no object {iid!r}") from None
            if not self.visible(inst, user):
                raise ApiError(404, f"no object {iid!r}")  # don't reveal that a hidden row exists
            out = self.object_view(inst, user, self._justified(user, [inst], justification))
            links = []
            for s, k, t in self.graph._links:
                other = t if s == iid else s if t == iid else None
                if other is not None and self.visible(self.graph.get(other), user):
                    links.append({"kind": k, "direction": "out" if s == iid else "in", "id": other,
                                  "type": self.graph.get(other).type})
            out["links"] = links
            return out

    def upsert_object(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "admin")
        etype, iid, attrs = self.ontology.canonical(body.get("type")), body.get("id"), dict(body.get("attributes") or {})
        if not etype or not iid:
            raise ApiError(400, "type and id are required")
        self.checkpoint(user, "upsert_object", str(iid), body.get("justification"), entity=etype)
        with self.graph_lock:
            candidate = KnowledgeGraph(self.ontology)
            try:
                inst = candidate.add(etype, iid, **attrs)  # validates type, attributes and state
            except OntologyError as exc:
                raise ApiError(400, str(exc)) from None
            self.graph._instances[iid] = inst
            self.store.upsert_instance(etype, iid, inst.attributes)
            for link in body.get("links", []):
                try:
                    self.graph.link(iid, link["kind"], link["target"])
                except (OntologyError, KeyError) as exc:
                    raise ApiError(400, f"invalid link {link}: {exc}") from None
                self.store.add_link(iid, link["kind"], link["target"])
        out = self.object_view(inst, user)
        fired = self._changed([iid])
        if fired:
            out["triggered"] = [f.as_dict() for f in fired]
        return out

    def answer(self, user: User, qid: str, params: Dict[str, Any],
               justification: Optional[str] = None) -> Dict[str, Any]:
        self.require(user, "read")
        question = next((q for q in self.ontology.questions if q.id == qid), None)
        if question is None:
            raise ApiError(404, f"unknown competency question {qid!r}")
        with self.graph_lock:
            # filters and aggregates reveal the fields they use: those fields must be readable on every record
            refs = set()
            for expr in (question.where, question.result_where):
                refs |= {(e, a) for e, a in (expr.references if expr else ()) if e != "Params"}
            if question.aggregate and question.aggregate[1]:
                refs.add(tuple(question.aggregate[1].split(".", 1)))
            gated = set()
            for entity, attr in refs:
                for inst in self.graph.instances(entity):
                    if self.field_hidden(inst, attr, user):
                        raise ApiError(403, f"the answer depends on {entity}.{attr}, which you may not read")
                    if f"{inst.type}.{attr}" in self.views.gated:
                        gated.add(f"{inst.type}.{attr}")
            if gated:
                self.checkpoint(user, "read_field", qid, justification, fields=sorted(gated))
            try:
                result = self.graph.ask(qid, **params)
            except OntologyError as exc:
                raise ApiError(404, str(exc)) from None
            ids = [i.id for i in result.instances if self.visible(i, user)]
            if result.value is not None and len(ids) != len(result.instances):
                raise ApiError(403, "the answer aggregates rows you may not see")
            return {"question": qid, "answer": result.value if result.value is not None else ids}

    def _summary(self, result, run_id: str, user: User, receipt: bool = False) -> Dict[str, Any]:
        """The run as this user may see it (see :mod:`autology.views`). A run over records the user may not
        see is 404 for them; the person who just started or resumed it gets a bare receipt instead."""
        view = self.views.run_view(user, result, run_id)
        if view is None:
            if receipt:
                return {"run_id": run_id, "case_id": result.case_id, "status": result.status, "hidden": True,
                        "detail": "this run involves records you may not see"}
            raise ApiError(404, f"no run {run_id!r}")
        return view

    def _store_result(self, result, agent_name: str, run_id: Optional[str] = None,
                      sources: Optional[Tuple[str, str, Dict[str, Any], bool]] = None,
                      started_by: Optional[str] = None) -> Tuple[str, List[str]]:
        """Save a run, open its review (and notify reviewers), write results back to the graph.

        Returns ``(run_id, changed instance ids)``. Callers pass the changed ids to :meth:`_changed`
        once they have released the agent's lock, so automations never wait on a running agent.
        """
        run_id = self.store.save_run(result, run_id, agent_name, started_by)
        cfg = self.agents.get(agent_name)
        if cfg is not None and cfg.agent.principal.name in cfg.agent.governance.suspended:
            self.store.suspend(agent_name, cfg.agent.governance.suspended[cfg.agent.principal.name], run_id)
        if sources:
            self.store.link_run_sources(run_id, *sources)
        if result.status == "awaiting_review" and result.run and result.run.pending_review:
            from .agent import ReviewRequest

            req = ReviewRequest(**{k: v for k, v in result.run.pending_review.items()
                                   if k in ReviewRequest.__dataclass_fields__})
            review_id = self.store.create_review(run_id, req)
            self._notify("review", req.reviewers, f"Review needed: {req.action} in run {run_id} ({', '.join(req.rule_ids) or 'policy'})",
                         {"review_id": review_id, "run_id": run_id, "action": req.action})
        linked = self.store.run_sources(run_id)
        changed = self._write_back(run_id, result, linked) if linked and linked["write_back"] else []
        if self.tracing and result.status in FINAL_STATUSES:
            self._export_trace(run_id, result)
        return run_id, changed

    def _export_trace(self, run_id: str, result) -> None:
        from .tracing import export, resolve_headers, to_otlp

        payload = to_otlp([(run_id, result)], self.tracing.get("service_name", "autology"), self.ontology.ref)

        def send():
            try:
                export(payload, self.tracing["endpoint"], resolve_headers(self.tracing.get("headers")))
            except Exception:  # best effort: the audit log in the store stays the record of truth
                log.warning("trace export of run %s to %s failed", run_id,
                            urlparse(self.tracing["endpoint"]).netloc, exc_info=True)

        t = threading.Thread(target=send, daemon=True)
        t.start()
        self.deliveries.append(t)

    def run_trace(self, user: User, run_id: str) -> Dict[str, Any]:
        from .tracing import to_otlp

        self.require(user, "audit")
        try:
            result = self.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        return to_otlp([(run_id, result)], "autology", self.ontology.ref)

    def _write_back(self, run_id: str, result, linked: Dict[str, Any]) -> List[str]:
        """Write the fields the run changed back to the graph; flag fields that moved meanwhile as conflicts."""
        base = linked["base"] or {}
        with self.graph_lock:
            changed, conflicts = write_back(self.graph, result.state, linked["sources"], base)
            for iid in changed:
                inst = self.graph.get(iid)
                self.store.upsert_instance(inst.type, iid, inst.attributes)
        known = linked["conflicts"]
        new = [c for c in conflicts if c not in known]
        self.store.update_write_back(run_id, base, known + new)
        if new:  # kept the live values: a person decides which is right
            fields = ", ".join(f"{c['id']}.{c['attribute']}" if c["attribute"] else c["id"] for c in new)
            self._notify("conflict", [], f"Run {run_id} could not write back {fields}: the live data changed "
                                         f"while the run was in progress", {"run_id": run_id})
        return changed

    def _changed(self, instance_ids: List[str]) -> List[Firing]:
        return self.automator.on_change(instance_ids) if instance_ids and self.automations else []

    # -- automations and notifications ------------------------------------------
    def _graph_instances(self, entity: Optional[str]) -> List[Instance]:
        with self.graph_lock:
            return list(self.graph.instances(entity))

    def _notify(self, kind: str, roles, message: str, ref: Dict[str, Any]) -> Dict[str, Any]:
        note = self.store.add_notification(kind, roles, message, ref)
        for hook in self.webhooks:
            if not hook["kinds"] or kind in hook["kinds"]:
                t = threading.Thread(target=self._deliver, args=(hook["url"], note), daemon=True)
                t.start()
                self.deliveries.append(t)
        self.deliveries = [t for t in self.deliveries if t.is_alive()]
        return note

    @staticmethod
    def _deliver(url: str, note: Dict[str, Any]) -> None:
        import urllib.request

        req = urllib.request.Request(url, json.dumps({"autology": note}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "Autology"})
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:  # best effort: the notification stays in the store either way
            log.warning("webhook delivery to %s failed", urlparse(url).netloc, exc_info=True)  # no path: may hold tokens

    def _fire(self, auto: Automation, inst: Instance, trigger: str) -> Firing:
        firing = Firing(auto.name, inst.id, trigger)
        if auto.run:
            cfg = self.agents[auto.run["agent"]]
            template = auto.run["case_template"]
            with self.graph_lock:
                case, sources = build_case(self.graph, template, inst.id)
                base = snapshot(self.graph, sources)
            with cfg.lock:
                result = cfg.agent.run(auto.run["goal"], case, f"{auto.name}:{inst.id}",
                                       started_by=f"automation:{auto.name}")
                firing.run_id, changed = self._store_result(
                    result, cfg.name, sources=(template, inst.id, sources, bool(auto.run["write_back"]), base),
                    started_by=f"automation:{auto.name}")
            firing.status = result.status
            firing.detail = result.escalation.reason if result.escalation else ""
            self._changed(changed)
        if auto.notify:
            ref = {"automation": auto.name, "instance": inst.id, "run_id": firing.run_id, "status": firing.status}
            firing.notification_id = self._notify("automation", auto.notify["roles"], auto.message(inst),
                                                  ref)["notification_id"]
            if not auto.run:
                firing.status = "notified"
        return firing

    def tick(self) -> Dict[str, Any]:
        """One scheduler pass: resume deferred runs whose retry time has come, then evaluate automations."""
        resumed = []
        for row in self.store.list_runs("deferred", limit=10 ** 9):
            cfg = self.agents.get(row["agent"])
            if cfg is None:
                continue
            with cfg.lock:
                result = self.store.load_run(row["run_id"])
                if result.status != "deferred" or (result.resume_at and cfg.agent.clock() < result.resume_at):
                    continue
                result = cfg.agent.resume(result)
                _, changed = self._store_result(result, cfg.name, row["run_id"])
            resumed.append({"run_id": row["run_id"], "status": result.status})
            self._changed(changed)
        loads = self._due_pipelines()
        firings = self.automator.tick() if self.automations else []
        out = {"resumed": resumed, "firings": [f.as_dict() for f in firings]}
        if self.pipelines:
            out["ingested"] = loads
        every = self.reporting.get("every")
        if every and (self._last_report is None or time.monotonic() - self._last_report >= float(every)):
            out["reporting"] = self.refresh_reporting()["rows"]
        return out

    # -- reporting and metrics ---------------------------------------------------------
    def refresh_reporting(self) -> Dict[str, Any]:
        """Rewrite the reporting database for BI tools (see :mod:`autology.warehouse`)."""
        from .warehouse import DEFAULT_EXCLUDED, export_reporting

        if not self.reporting:
            raise ApiError(400, "no reporting target configured (\"reporting\": {\"target\": \"reporting.db\"})")
        cfg = self.reporting
        meta = export_reporting(self, cfg["target"], cfg.get("roles", []),
                                cfg.get("exclude_sensitivities", DEFAULT_EXCLUDED), cfg.get("include_fields", []))
        self._last_report = time.monotonic()
        return meta

    def unverified_runs(self) -> int:
        """How many stored runs fail audit verification (cached for a minute: it reads every chain)."""
        checked_at, count = self._verified
        if time.monotonic() - checked_at > 60 or not checked_at:
            count = sum(1 for r in self.store.list_runs(limit=10 ** 9) if not self.store.verify_audit(r["run_id"]))
            self._verified = (time.monotonic(), count)
        return count

    def metrics(self, user: User) -> str:
        self.require(user, "audit")
        from .warehouse import metrics_text

        return metrics_text(self)

    # -- ingestion ------------------------------------------------------------------
    def ingest(self, name: str, triggered_by: str, dry_run: bool = False,
               pushed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run one pipeline: read its sources, check every row, write the accepted ones, fire automations."""
        from .ingest import PipelineError, apply_to_graph

        pipe = self.pipelines.get(name)
        if pipe is None:
            raise ApiError(404, f"no pipeline {name!r}")
        with self.ingest_lock:
            try:
                plan = pipe.read(self.store.ingest_watermarks(name), pushed)
            except PipelineError as exc:
                batch = self.store.record_ingest_failure(name, triggered_by, str(exc))
                log.warning("pipeline %s failed: %s", name, exc)
                raise ApiError(502 if not pushed else 400, str(exc), {"batch_id": batch}) from None
            with self.graph_lock:
                plan = pipe.plan(self.graph, plan)
                batch = self.store.apply_ingest(plan, triggered_by, dry_run)
                if not dry_run:
                    apply_to_graph(self.graph, plan)
        out = {"batch_id": batch, "dry_run": dry_run, **plan.summary()}
        if not dry_run:
            fired = self._changed(plan.changed_ids)
            if fired:
                out["triggered"] = [f.as_dict() for f in fired]
        return out

    def _due_pipelines(self) -> List[Dict[str, Any]]:
        from datetime import datetime, timezone

        loads = []
        for name, pipe in self.pipelines.items():
            if not pipe.every or all(s["type"] == "push" for s in pipe.sources.values()):
                continue
            last = self.store.ingest_batches(name, limit=1)
            if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last[0]["started_at"])
                         ).total_seconds() < pipe.every:
                continue
            try:
                out = self.ingest(name, "schedule")
                loads.append({k: out[k] for k in ("batch_id", "created", "updated", "rejected")})
            except ApiError as exc:
                loads.append({"pipeline": name, "error": exc.message})
        return loads

    def list_pipelines(self, user: User) -> Dict[str, Any]:
        self.require(user, "ingest")
        items = []
        for name, pipe in self.pipelines.items():
            last = self.store.ingest_batches(name, limit=1)
            items.append({"name": name, "every": pipe.every,
                          "sources": {s: src["type"] for s, src in pipe.sources.items()},
                          "entities": sorted({m.entity for m in pipe.mappings}),
                          "watermarks": self.store.ingest_watermarks(name),
                          "last_batch": last[0] if last else None})
        return {"items": items}

    def run_pipeline(self, user: User, name: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "ingest")
        rows = body.get("rows")
        if rows is not None and (not isinstance(rows, dict) or
                                 not all(isinstance(v, list) for v in rows.values())):
            raise ApiError(400, "rows must map each push source to a list of records")
        return self.ingest(name, user.name, bool(body.get("dry_run")), rows)

    def ingest_batch(self, user: User, batch_id: str) -> Dict[str, Any]:
        """A load and its quarantined rows. The rows hold raw source data, so only ingesters see them."""
        self.require(user, "ingest")
        rows = [b for b in self.store.ingest_batches(limit=10 ** 6) if b["batch_id"] == batch_id]
        if not rows:
            raise ApiError(404, f"no batch {batch_id!r}")
        return {**rows[0], "rejects": self.store.ingest_rejects(batch_id)}

    def object_lineage(self, user: User, iid: str) -> Dict[str, Any]:
        """Where an object came from: every load that created or changed it (attribute names, not values)."""
        self.require(user, "read")
        with self.graph_lock:
            inst = self.graph._instances.get(iid)
            if inst is None or not self.visible(inst, user):
                raise ApiError(404, f"no object {iid!r}")
        return {"id": iid, "type": inst.type, "loads": self.store.lineage(iid)}

    def start_background(self, interval: Optional[float] = None) -> threading.Event:
        """Tick every ``interval`` seconds in a daemon thread; set the returned event to stop."""
        stop = threading.Event()
        every = interval or self.automation_interval

        def loop():
            while not stop.wait(every):
                try:
                    self.tick()
                    self.scheduler_status["last_tick"] = _utcnow()
                except Exception as exc:  # keep the scheduler alive, but never silently
                    self.log_error("scheduler tick")
                    self.scheduler_status["last_error"] = {"at": _utcnow(), "error": f"{type(exc).__name__}: {exc}"}

        threading.Thread(target=loop, daemon=True, name="autology-scheduler").start()
        return stop

    def list_automations(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        items = []
        for a in self.automations.values():
            recent = self.store.list_firings(a.name, limit=10)
            for f in recent:  # the firing recorded the run's status then; show where it stands now
                rows = self.store._query("SELECT status FROM runs WHERE run_id=?", (f["run_id"],)) if f["run_id"] else []
                f["run_status"] = rows[0]["status"] if rows else None
            items.append({**a.describe(), "recent": recent})
        return {"items": items}

    def run_automation(self, user: User, name: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "run")
        if name not in self.automations:
            raise ApiError(404, f"no automation {name!r}")
        instance = body.get("instance")
        if instance:
            with self.graph_lock:
                inst = self.graph._instances.get(instance)
                if inst is None or not self.visible(inst, user):
                    raise ApiError(404, f"no object {instance!r}")
        try:
            firings = self.automator.run_now(name, instance)
        except KeyError:
            raise ApiError(400, f"{instance!r} is not a {self.automations[name].entity}") from None
        return {"firings": [f.as_dict() for f in firings]}

    def list_notifications(self, user: User, since: Optional[str], limit: int) -> Dict[str, Any]:
        self.require(user, "read")
        roles = None if "admin" in user.permissions else user.roles | user.reviewer_roles
        items = []
        for note in self.store.list_notifications(roles, since, limit=10 ** 9):
            if len(items) >= limit:
                break
            iid = note["ref"].get("instance")
            with self.graph_lock:
                inst = self.graph._instances.get(iid) if iid else None
            if inst is not None and not self.visible(inst, user):
                continue  # don't leak hidden rows through notification text
            items.append(note)
        return {"items": items}

    def start_run(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "run")
        name = body.get("agent") or (next(iter(self.agents)) if len(self.agents) == 1 else None)
        if name not in self.agents:
            raise ApiError(400, f"unknown agent {name!r}; available: {sorted(self.agents)}")
        cfg = self.agents[name]
        goal = body.get("goal") or (cfg.goals[0] if len(cfg.goals) == 1 else None)
        if goal not in cfg.goals:
            raise ApiError(400, f"agent {name} may pursue {cfg.goals}, not {goal!r}")
        self.checkpoint(user, "start_run", f"{name}/{goal}/{body.get('root') or body.get('case_id') or 'case'}",
                        body.get("justification"), goal=goal)
        sources = None
        if body.get("case_template"):  # build the case from the knowledge graph
            root = str(body.get("root") or "")
            with self.graph_lock:
                inst = self.graph._instances.get(root)
                if inst is None or not self.visible(inst, user):
                    raise ApiError(404, f"no object {root!r}")
                try:
                    case, found = build_case(self.graph, body["case_template"], root)
                except OntologyError as exc:
                    raise ApiError(400, str(exc)) from None
                base = snapshot(self.graph, found)  # what the case read: write-back compares against it
            sources = (body["case_template"], root, found, body.get("write_back", True) is not False, base)
        else:
            if "admin" not in user.permissions and not self.simulation:
                # the facts that trigger reviews and rules must come from the system of record, not the requester
                raise ApiError(403, "start runs from a case_template and a root object; free-form case data is "
                                    "accepted only from admins or on a server configured for simulation")
            case = body.get("case")
            if not isinstance(case, dict):
                raise ApiError(400, "case must be an object (or give case_template and root)")
        with cfg.lock:
            try:
                result = cfg.agent.run(goal, case, str(body.get("case_id") or (sources[1] if sources else "case")),
                                       started_by=user.name)
            except OntologyError as exc:
                raise ApiError(400, f"invalid case: {exc}") from None
            run_id, changed = self._store_result(result, name, sources=sources, started_by=user.name)
        self._changed(changed)
        return self._summary(result, run_id, user, receipt=True)

    def list_runs(self, user: User, status: Optional[str], limit: int, offset: int) -> Dict[str, Any]:
        self.require(user, "read")
        if "admin" in user.permissions:
            return {"items": self.store.list_runs(status, limit, offset)}
        rows = [r for r in self.store.list_runs(status, limit=10 ** 9)
                if self.views.can_see_run(user, self.store.load_run(r["run_id"]))]
        return {"items": rows[offset:offset + limit]}

    def _visible_runs(self, user: User) -> List[Any]:
        runs = self.store.all_runs()
        return runs if "admin" in user.permissions else [r for r in runs if self.views.can_see_run(user, r)]

    def get_run(self, user: User, run_id: str) -> Dict[str, Any]:
        self.require(user, "read")
        try:
            result = self.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        return self._summary(result, run_id, user)

    def run_audit(self, user: User, run_id: str) -> Dict[str, Any]:
        self.require(user, "audit")
        log = self.store.audit_log(run_id)
        if not len(log):
            raise ApiError(404, f"no run {run_id!r}")
        return {"run_id": run_id, "verified": self.store.verify_audit(run_id), "entries": log.to_list()}

    def _agent_for(self, run_id: str) -> AgentConfig:
        rows = [r for r in self.store.list_runs(limit=10 ** 9) if r["run_id"] == run_id]
        if not rows:
            raise ApiError(404, f"no run {run_id!r}")
        name = rows[0]["agent"]
        if name not in self.agents:
            raise ApiError(409, f"run {run_id} belongs to agent {name!r}, which is not configured")
        return self.agents[name]

    def resume_run(self, user: User, run_id: str, force: bool = False,
                   justification: Optional[str] = None) -> Dict[str, Any]:
        self.require(user, "run")
        cfg = self._agent_for(run_id)
        self.checkpoint(user, "resume_run", run_id, justification)
        with cfg.lock:
            result = self.store.load_run(run_id)
            if result.status not in ("deferred", "paused"):
                raise ApiError(409, f"run {run_id} is {result.status}; only deferred or paused runs resume here")
            try:
                result = cfg.agent.resume(result, force=force)
            except (ValueError, OntologyError) as exc:
                raise ApiError(409, str(exc)) from None
            _, changed = self._store_result(result, cfg.name, run_id)
        self._changed(changed)
        return self._summary(result, run_id, user, receipt=True)

    def list_reviews(self, user: User, status: Optional[str]) -> Dict[str, Any]:
        self.require(user, "review" if status in (None, "pending") else "read")
        views = (self.views.review_view(user, r) for r in self.store.list_reviews(status))
        return {"items": [v for v in views if v is not None]}

    def get_review(self, user: User, review_id: str) -> Dict[str, Any]:
        self.require(user, "read")
        try:
            review = self.store.get_review(review_id)
        except KeyError:
            raise ApiError(404, f"no review {review_id!r}") from None
        view = self.views.review_view(user, review)
        if view is None:  # readable by admins, the review's reviewers and the run's starter only
            raise ApiError(404, f"no review {review_id!r}")
        return view

    def decide(self, user: User, review_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "review")
        if not isinstance(body.get("approved"), bool):
            raise ApiError(400, "approved must be true or false")
        review = self.get_review(user, review_id)
        if "admin" not in user.permissions and not user.reviewer_roles & set(review["reviewers"]):
            raise ApiError(403, f"{user.name} may not decide reviews for {review['reviewers']}")
        if self.store.run_starter(review["run_id"]) == user.name:
            rules = [r for r in self.ontology.rules if r.id in (review["request"].get("rule_ids") or [])]
            if not rules or not all(r.params.get("allow_self_review") for r in rules):
                raise ApiError(403, "you started this run: another reviewer must decide its review "
                                    "(a rule can allow this with \"allow_self_review\": true)")
        cfg = self._agent_for(review["run_id"])
        self.checkpoint(user, "decide", review_id, body.get("justification") or body.get("comment"),
                        action=str(review["action"]).partition("@")[0], approved=body["approved"])
        comment = str(body.get("comment", ""))
        with cfg.lock:
            # Order matters: the review is marked decided only once the run has resumed, and reopened if
            # saving fails, so the review and the run can never disagree (no stranded awaiting_review run).
            if self.store.get_review(review_id)["status"] != "pending":
                raise ApiError(409, f"review {review_id} was already decided")
            stored = self.store.load_run(review["run_id"])
            try:
                result = cfg.agent.resume(stored, decision=ReviewDecision(body["approved"], user.name, comment))
            except (ValueError, OntologyError) as exc:
                raise ApiError(409, f"the run cannot continue: {exc}") from None
            except Exception as exc:
                self.log_error(f"resuming run {review['run_id']} after review {review_id}")
                raise ApiError(500, f"the run could not continue ({type(exc).__name__}); the review is still "
                                    "open") from None
            try:
                self.store.decide_review(review_id, body["approved"], user.name, comment)
            except StoreError as exc:
                raise ApiError(409, str(exc)) from None
            try:
                _, changed = self._store_result(result, cfg.name, review["run_id"])
            except Exception as exc:
                self.store.reopen_review(review_id)
                self.log_error(f"saving run {review['run_id']} after review {review_id}")
                raise ApiError(500, f"the decision could not be saved ({type(exc).__name__}); the review is "
                                    "still open") from None
        self._changed(changed)
        return self._summary(result, review["run_id"], user, receipt=True)

    # -- what-if scenarios -----------------------------------------------------------
    def _roles_for(self, user: User, spec: Dict[str, Any]) -> List[str]:
        """Roles a simulated action or plan uses: a configured agent's, or the caller's own."""
        if spec.get("agent"):
            if spec["agent"] not in self.agents:
                raise ApiError(400, f"unknown agent {spec['agent']!r}")
            return sorted(self.agents[spec["agent"]].agent.principal.roles)
        if spec.get("roles") is not None and "admin" in user.permissions:
            return list(spec["roles"])
        return sorted(user.roles)

    @staticmethod
    def _edit_ids(edit: Dict[str, Any]) -> List[str]:
        ids = [edit.get(k) for k in ("id", "source", "target", "root") if edit.get(k)]
        if edit.get("op") == "add":
            ids = [l.get("source") or l.get("target") for l in edit.get("links", [])]
        return [str(i) for i in ids]

    def _load_scenario(self, sid: str, user: User, write: bool = False):
        from .scenarios import Scenario

        try:
            row = self.store.get_scenario(sid)
        except KeyError:
            raise ApiError(404, f"no scenario {sid!r}") from None
        if write and "admin" not in user.permissions and row["created_by"] != user.name:
            raise ApiError(403, f"scenario {sid} belongs to {row['created_by']}")
        if write and row["status"] != "open":
            raise ApiError(409, f"scenario {sid} is {row['status']}")
        with self.graph_lock:
            try:
                scenario = Scenario(self.graph, row["name"], row["edits"], row["snapshot"])
            except OntologyError as exc:  # the live data moved so far that an edit no longer applies
                raise ApiError(409, f"scenario {sid} no longer applies to the live data: {exc}") from None
        return row, scenario

    def _apply_edits(self, scenario, edits: Any, user: User) -> None:
        if not isinstance(edits, list):
            raise ApiError(400, "edits must be a list")
        for i, edit in enumerate(edits):
            if not isinstance(edit, dict):
                raise ApiError(400, f"edit {i} must be an object")
            edit = dict(edit)
            for iid in self._edit_ids(edit):
                inst = scenario.graph._instances.get(iid)
                if inst is not None and not self.visible(inst, user):
                    raise ApiError(404, f"edit {i}: no object {iid!r}")
            if edit.get("op") == "action":
                edit["roles"] = self._roles_for(user, edit)
                edit.pop("agent", None)
            try:
                scenario.apply(edit)
            except (OntologyError, KeyError, TypeError) as exc:
                raise ApiError(400, f"edit {i}: {exc}") from None

    def _scenario_view(self, sid: str, row: Dict[str, Any], scenario, user: User) -> Dict[str, Any]:
        def seen(iid):
            inst = scenario.graph._instances.get(iid)
            return inst is not None and self.visible(inst, user)

        d = scenario.diff()
        with self.graph_lock:
            conflicts = scenario.conflicts(self.graph)
        return {"scenario_id": sid, "name": row["name"], "status": row["status"], "created_by": row["created_by"],
                "edits": len(scenario.edits),
                "results": [r for r, e in zip(scenario.results, scenario.edits)
                            if all(seen(i) for i in self._edit_ids(e) + ([e["id"]] if e.get("op") == "add" else []))],
                "diff": {"changed": {i: {a: self._diff_values(scenario, i, a, v, user) for a, v in delta.items()}
                                     for i, delta in d["changed"].items() if seen(i)},
                         "added": [i for i in d["added"] if seen(i)],
                         "added_status": {i: v for i, v in d["added_status"].items() if seen(i)},
                         "links": [l for l in d["links"] if seen(l[0]) and seen(l[2])]},
                "conflicts": [c for c in conflicts if seen(c["id"])]}

    # -- governed assistant and access log ------------------------------------------
    def chat_send(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "read")
        if self.chat is None:
            raise ApiError(404, "the assistant is not configured on this server")
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ApiError(400, "message must be a non-empty string")
        return self.chat.send(user, message[:20_000], body.get("chat_id")).as_dict()

    def chat_get(self, user: User, chat_id: str) -> Dict[str, Any]:
        self.require(user, "read")
        convo = self.store.get_chat(chat_id)
        if convo is None or convo["owner"] != user.name:
            raise ApiError(404, f"no chat {chat_id!r}")
        turns = []
        for m in convo["messages"]:  # the readable part: what the person asked and what the assistant said
            if isinstance(m["content"], str):
                turns.append({"role": m["role"], "text": m["content"]})
            elif m["role"] == "assistant":
                text = "\n".join(b.get("text", "") for b in m["content"] if b.get("type") == "text").strip()
                tools = [b["name"] for b in m["content"] if b.get("type") == "tool_use"]
                turns.append({"role": "assistant", "text": text, "tools": tools})
        return {"chat_id": chat_id, "turns": turns, "updated_at": convo["updated_at"]}

    def justifications(self, user: User, limit: int) -> Dict[str, Any]:
        self.require(user, "audit")
        return {"items": self.store.list_justifications(limit)}

    # -- run proposals: the assistant proposes, the person confirms ------------------------
    def create_proposal(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "run")
        name, goal = body.get("agent"), body.get("goal")
        if name not in self.agents or goal not in self.agents[name].goals:
            raise ApiError(400, f"agent {name!r} with goal {goal!r} is not available")
        if body.get("case_template") not in self.ontology.case_templates:
            raise ApiError(400, f"unknown case template {body.get('case_template')!r}")
        with self.graph_lock:
            inst = self.graph._instances.get(str(body.get("root")))
            if inst is None or not self.visible(inst, user):
                raise ApiError(404, f"no object {body.get('root')!r}")
        proposal = self.store.add_proposal(user.name, {k: body[k] for k in ("agent", "goal", "case_template", "root")})
        self._notify("proposal", [], f"The assistant proposes {goal} on {body['root']} for {user.name}",
                     {"proposal_id": proposal["proposal_id"], "owner": user.name})
        return {"proposal_id": proposal["proposal_id"], "status": "pending",
                "message": "Proposed, not started. The person confirms or declines it in the inbox (Assistant tab)."}

    def list_proposals(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        return {"items": self.store.list_proposals(user.name)}

    def confirm_proposal(self, user: User, pid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "run")
        proposal = self.store.get_proposal(pid)
        if proposal is None or proposal["owner"] != user.name:  # only the person the assistant was working for
            raise ApiError(404, f"no proposal {pid!r}")
        if not self.store.claim_proposal(pid):
            raise ApiError(409, f"proposal {pid} is {proposal['status']}")
        if body.get("confirm") is not True:
            self.store.settle_proposal(pid, "declined")
            return {"proposal_id": pid, "status": "declined"}
        try:
            run = self.start_run(user, {**proposal["body"], "justification": body.get("justification")})
        except Exception:
            self.store.settle_proposal(pid, "pending")  # nothing ran: the person can try again
            raise
        self.store.settle_proposal(pid, "confirmed", run["run_id"])
        return run

    # -- decision outcomes: what happened afterwards (dynamic layer) ------------------------
    def _visible_run(self, user: User, run_id: str):
        try:
            result = self.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        if not self.views.can_see_run(user, result):
            raise ApiError(404, f"no run {run_id!r}")
        return result

    def record_outcome(self, user: User, run_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Record what happened after a run or one of its decisions, in the run's tamper-evident audit chain."""
        self.require(user, "review")
        result = self._visible_run(user, run_id)
        label, good, action = body.get("label"), body.get("good"), body.get("action")
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise ApiError(400, "label must be a non-empty string of at most 200 characters")
        if not isinstance(good, bool):
            raise ApiError(400, "good must be true or false")
        if action is not None and action not in {s.action for s in result.steps if s.outcome}:
            raise ApiError(400, f"{action!r} is not an executed step of run {run_id}")
        rows = self.store.list_runs(limit=10 ** 9)
        agent = next((r["agent"] for r in rows if r["run_id"] == run_id), None)
        lock = self.agents[agent].lock if agent in self.agents else threading.Lock()
        with lock:
            result = self.store.load_run(run_id)
            result.audit.record("outcome", action=action, label=label.strip(), good=good,
                                note=str(body.get("note") or "")[:2000], recorded_by=user.name)
            self.store.save_run(result, run_id)
        return {"run_id": run_id, "outcomes": self.views.outcomes(user, result)}

    def list_outcomes(self, user: User, run_id: str) -> Dict[str, Any]:
        self.require(user, "read")
        return {"items": self.views.outcomes(user, self._visible_run(user, run_id))}

    def outcomes_summary(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        from .reporting import outcome_analysis

        return outcome_analysis(self._visible_runs(user), self.ontology)

    def list_agents(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        items = {}
        for name, cfg in self.agents.items():
            reason = cfg.agent.governance.suspended.get(cfg.agent.principal.name)
            items[name] = {"goals": cfg.goals, "roles": sorted(cfg.agent.principal.roles),
                           "suspended": reason is not None, "reason": reason}
        return {"items": items}

    def reinstate_agent(self, user: User, name: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "admin")
        if name not in self.agents:
            raise ApiError(404, f"no agent {name!r}")
        reason = str(body.get("reason") or "").strip()
        if len(reason) < 10:
            raise ApiError(400, "give a reason of at least 10 characters for reinstating the agent")
        cfg = self.agents[name]
        with cfg.lock:
            cfg.agent.governance.reinstate(cfg.agent.principal.name)
            self.store.reinstate(name, user.name, reason)
        return {"agent": name, "suspended": False, "reinstated_by": user.name, "reason": reason}

    def log_error(self, context: str) -> None:
        """Record the exception being handled, with its traceback, in the server log."""
        log.exception("%s failed", context)

    def log_access(self, user: Optional[User], kind: str, target: str, status: int) -> None:
        self.store.log_access(user.name if user else "-", kind, target, status)

    def access_log(self, user: User, principal: Optional[str], limit: int) -> Dict[str, Any]:
        self.require(user, "audit")
        return {"items": self.store.access_log(principal, limit)}

    def _diff_values(self, scenario, iid: str, attr: str, values: List[Any], user: User) -> List[Any]:
        """Before/after values of a scenario change, through the user's field access on each side."""
        out = []
        for graph, value in ((scenario.base, values[0]), (scenario.graph, values[1])):
            inst = graph._instances.get(iid) or scenario.graph._instances[iid]
            shown = self.field_value(inst, attr, user)
            out.append(value if shown == inst.attributes.get(attr) else shown)
        return out

    def list_scenarios(self, user: User, status: Optional[str]) -> Dict[str, Any]:
        self.require(user, "read")
        return {"items": self.store.list_scenarios(status)}

    def create_scenario(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        from .scenarios import Scenario

        self.require(user, "run")
        name = str(body.get("name") or "scenario")[:200]
        with self.graph_lock:
            scenario = Scenario(self.graph, name)
        self._apply_edits(scenario, body.get("edits", []), user)
        sid = self.store.save_scenario(None, name, user.name, scenario.edits, scenario.snapshot)
        return self._scenario_view(sid, self.store.get_scenario(sid), scenario, user)

    def get_scenario(self, user: User, sid: str) -> Dict[str, Any]:
        self.require(user, "read")
        row, scenario = self._load_scenario(sid, user)
        return self._scenario_view(sid, row, scenario, user)

    def add_scenario_edits(self, user: User, sid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "run")
        row, scenario = self._load_scenario(sid, user, write=True)
        self._apply_edits(scenario, body.get("edits"), user)
        self.store.save_scenario(sid, row["name"], row["created_by"], scenario.edits, scenario.snapshot)
        return self._scenario_view(sid, self.store.get_scenario(sid), scenario, user)

    def compare_scenario(self, user: User, sid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        from .scenarios import ScenarioError

        self.require(user, "read")
        row, scenario = self._load_scenario(sid, user)
        checks = []
        for c in body.get("checks") or []:
            root = scenario.graph._instances.get(str(c.get("root")))
            if root is not None and not self.visible(root, user):
                raise ApiError(404, f"no object {c.get('root')!r}")
            checks.append({"goal": c.get("goal"), "case_template": c.get("case_template"), "root": c.get("root"),
                           "roles": self._roles_for(user, c)})
        try:
            with self.graph_lock:
                report = scenario.compare(checks, schedule=bool(body.get("schedule")))
        except OntologyError as exc:
            raise ApiError(400, str(exc)) from None
        if "admin" not in user.permissions:
            report = self._redact_report(report, scenario, user)
        report["diff"] = self._scenario_view(sid, row, scenario, user)["diff"]
        return report

    def _redact_report(self, report: Dict[str, Any], scenario, user: User) -> Dict[str, Any]:
        """Remove what the caller may not see from a comparison: hidden ids and aggregates over hidden rows."""
        def seen(graph, iid):
            inst = graph._instances.get(iid)
            return inst is None or self.visible(inst, user)

        def answer(graph, value, qid):
            q = next(q for q in self.ontology.questions if q.id == qid)
            result = graph.ask(q)
            hidden = [i for i in result.instances if not self.visible(i, user)]
            if result.value is not None:
                return "withheld: aggregates rows you may not see" if hidden else value
            return [i for i in value if seen(graph, i)]

        for q in report.get("questions", []):
            if "error" in q:
                continue
            q["baseline"] = answer(scenario.base, q["baseline"], q["id"])
            q["scenario"] = answer(scenario.graph, q["scenario"], q["id"])
            q["changed"] = q["baseline"] != q["scenario"]
        for plan in report.get("plans", []):
            for side, graph in (("baseline", scenario.base), ("scenario", scenario.graph)):
                p = plan[side]
                for key in ("steps", "reviews"):
                    if key in p:
                        p[key] = [st if seen(graph, st.partition("@")[2]) else st.partition("@")[0] + "@(hidden)"
                                  for st in p[key]]
                if p.get("action") and not seen(graph, p["action"].partition("@")[2]):
                    p["action"] = p["action"].partition("@")[0] + "@(hidden)"
                    p["reasons"] = ["blocked by a rule on a record you may not see"]
        return report

    def commit_scenario(self, user: User, sid: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        from .scenarios import ConflictError

        self.require(user, "admin")
        row, scenario = self._load_scenario(sid, user, write=True)
        self.checkpoint(user, "commit_scenario", sid, (body or {}).get("justification"))
        with self.graph_lock:
            try:
                written = scenario.commit(self.graph, self.store)
            except ConflictError as exc:
                raise ApiError(409, str(exc)) from None
            except OntologyError as exc:
                raise ApiError(409, f"cannot commit: {exc}") from None
        self.store.save_scenario(sid, row["name"], row["created_by"], scenario.edits, scenario.snapshot, "committed")
        fired = self._changed(written)
        return {"scenario_id": sid, "status": "committed", "written": written,
                "triggered": [f.as_dict() for f in fired]}

    def discard_scenario(self, user: User, sid: str) -> Dict[str, Any]:
        self.require(user, "run")
        row, scenario = self._load_scenario(sid, user, write=True)
        self.store.save_scenario(sid, row["name"], row["created_by"], scenario.edits, scenario.snapshot, "discarded")
        return {"scenario_id": sid, "status": "discarded"}

    def report(self, user: User) -> str:
        self.require(user, "read")
        from .reporting import compliance_report

        report = compliance_report(self._visible_runs(user), self.ontology)
        if self.simulation:
            report = (f"> **SIMULATION SERVER.** Case data may be supplied by requesters and reviews may be decided "
                      f"automatically. These results are not evidence of governed operation.\n\n{report}")
        return report

    def score(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        from .scoring import score_deployment
        from .tools import ToolRegistry

        merged = ToolRegistry()
        for cfg in self.agents.values():
            for member in [cfg.agent] + cfg.agent.delegates:
                for t in member.tools:
                    merged._tools.append(t)
        with self.graph_lock:
            card = score_deployment(self.ontology, self._visible_runs(user), tools=merged, graph=self.graph).as_dict()
        card["simulation"] = self.simulation
        return card


# -- HTTP layer ------------------------------------------------------------------------
def _handler(service: AutologyService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Autology"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet by default; plug in your own access log
            pass

        def _send(self, status: int, body: Any, content_type: str = "application/json") -> None:
            data = body if isinstance(body, bytes) else (
                body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode())
            self.send_response(status)
            self._status = status
            self.send_header("Content-Type", content_type + ("; charset=utf-8" if "text" in content_type
                                                             or "json" in content_type or "javascript" in content_type
                                                             else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            if content_type == "text/html":
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ApiError(413, "request body too large")
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError:
                raise ApiError(400, "body must be JSON") from None
            if not isinstance(data, dict):
                raise ApiError(400, "body must be a JSON object")
            return data

        def _route(self, method: str) -> None:
            url = urlparse(self.path)
            path = url.path.rstrip("/") or "/"
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            self._status, self._user = 500, None
            try:
                self._dispatch(method, path, query)
            finally:
                if path.startswith("/api/") and path != "/api/health":
                    try:  # every API request, including failed sign-ins, goes to the append-only log
                        service.log_access(self._user, "http", f"{method} {path}", self._status)
                    except Exception:  # logging must never break a response
                        log.exception("writing the access log failed")

        def _dispatch(self, method: str, path: str, query: Dict[str, str]) -> None:
            try:
                if method == "GET" and path in ("/", "/index.html", "/app.js", "/app.css"):
                    name = {"/": "index.html"}.get(path, path.lstrip("/"))
                    ctype = {"html": "text/html", "js": "application/javascript", "css": "text/css"}[name.rsplit(".")[-1]]
                    return self._send(200, (STATIC / name).read_bytes(), ctype)
                if path == "/api/health":
                    from .audit import audit_key

                    return self._send(200, {"status": "ok", "ontology": service.ontology.ref,
                                            "simulation": service.simulation, "audit_keyed": audit_key() is not None,
                                            "scheduler": service.scheduler_status})
                if not path.startswith("/api/"):
                    raise ApiError(404, "not found")
                if path == "/api/auth/config" and method == "GET":  # what the inbox needs to offer SSO sign-in
                    return self._send(200, service.sso_config())
                if path == "/api/auth/token" and method == "POST":
                    return self._send(200, service.sso_token(self._body()))
                user = service.authenticate(self.headers.get("Authorization"))
                self._user = user
                parts = path.split("/")[2:]
                limit = max(1, min(int(query.get("limit", 100)), 1000))
                offset = max(0, int(query.get("offset", 0)))
                body = self._body() if method == "POST" else {}
                routes = {
                    ("GET", "me"): lambda: service.me(user),
                    ("GET", "ontology"): lambda: service.ontology_summary(user),
                    ("GET", "objects"): lambda: service.list_objects(user, query.get("type"), limit, offset,
                                                                     query.get("justification")),
                    ("GET", "justifications"): lambda: service.justifications(user, limit),
                    ("GET", "audit-heads"): lambda: (service.require(user, "audit"),
                                                     {"items": service.store.audit_heads()})[1],
                    ("POST", "objects"): lambda: service.upsert_object(user, body),
                    ("GET", "runs"): lambda: service.list_runs(user, query.get("status"), limit, offset),
                    ("POST", "runs"): lambda: service.start_run(user, body),
                    ("GET", "reviews"): lambda: service.list_reviews(user, query.get("status", "pending")),
                    ("GET", "score"): lambda: service.score(user),
                    ("GET", "automations"): lambda: service.list_automations(user),
                    ("GET", "notifications"): lambda: service.list_notifications(user, query.get("since"), limit),
                    ("POST", "tick"): lambda: (service.require(user, "admin"), service.tick())[1],
                    ("GET", "scenarios"): lambda: service.list_scenarios(user, query.get("status")),
                    ("POST", "scenarios"): lambda: service.create_scenario(user, body),
                    ("POST", "chat"): lambda: service.chat_send(user, body),
                    ("GET", "access-log"): lambda: service.access_log(user, query.get("principal"), limit),
                    ("GET", "agents"): lambda: service.list_agents(user),
                    ("GET", "proposals"): lambda: service.list_proposals(user),
                    ("GET", "outcomes"): lambda: service.outcomes_summary(user),
                    ("GET", "pipelines"): lambda: service.list_pipelines(user),
                    ("POST", "reporting"): lambda: (service.require(user, "admin"), service.refresh_reporting())[1],
                }
                key = (method, parts[0]) if len(parts) == 1 else None
                if key in routes:
                    return self._send(200, routes[key]())
                if method == "GET" and len(parts) == 2 and parts[0] == "sdk":
                    from .sdk import GENERATORS

                    service.require(user, "read")
                    if parts[1] not in GENERATORS:
                        raise ApiError(404, f"no client for {parts[1]!r}; available: {sorted(GENERATORS)}")
                    return self._send(200, GENERATORS[parts[1]](service.ontology), "text/plain")
                if method == "GET" and parts == ["metrics"]:
                    return self._send(200, service.metrics(user), "text/plain; version=0.0.4")
                if method == "GET" and parts == ["report"]:
                    return self._send(200, service.report(user), "text/markdown")
                if len(parts) == 2:
                    kind, ident = parts
                    if method == "GET" and kind == "objects":
                        return self._send(200, service.get_object(user, ident, query.get("justification")))
                    if method == "GET" and kind == "runs":
                        return self._send(200, service.get_run(user, ident))
                    if method == "GET" and kind == "reviews":
                        return self._send(200, service.get_review(user, ident))
                    if method == "GET" and kind == "scenarios":
                        return self._send(200, service.get_scenario(user, ident))
                    if method == "GET" and kind == "ingest-batches":
                        return self._send(200, service.ingest_batch(user, ident))
                    if method == "GET" and kind == "chat":
                        return self._send(200, service.chat_get(user, ident))
                    if method == "POST" and kind == "questions":
                        return self._send(200, service.answer(user, ident, body.get("params") or {},
                                                              body.get("justification")))
                if len(parts) == 3 and parts[0] == "objects" and parts[2] == "lineage" and method == "GET":
                    return self._send(200, service.object_lineage(user, parts[1]))
                if len(parts) == 3 and parts[0] == "pipelines" and parts[2] == "run" and method == "POST":
                    return self._send(200, service.run_pipeline(user, parts[1], body))
                if len(parts) == 3 and parts[0] == "runs":
                    if method == "GET" and parts[2] == "audit":
                        return self._send(200, service.run_audit(user, parts[1]))
                    if parts[2] == "outcomes":
                        if method == "POST":
                            return self._send(200, service.record_outcome(user, parts[1], body))
                        return self._send(200, service.list_outcomes(user, parts[1]))
                    if method == "GET" and parts[2] == "trace":
                        return self._send(200, service.run_trace(user, parts[1]))
                    if method == "POST" and parts[2] == "resume":
                        return self._send(200, service.resume_run(user, parts[1], bool(body.get("force")),
                                                                  body.get("justification")))
                if len(parts) == 3 and parts[0] == "scenarios" and method == "POST":
                    sid, verb = parts[1], parts[2]
                    handlers = {"edits": lambda: service.add_scenario_edits(user, sid, body),
                                "compare": lambda: service.compare_scenario(user, sid, body),
                                "commit": lambda: service.commit_scenario(user, sid, body),
                                "discard": lambda: service.discard_scenario(user, sid)}
                    if verb in handlers:
                        return self._send(200, handlers[verb]())
                if len(parts) == 3 and parts[0] == "proposals" and parts[2] == "decision" and method == "POST":
                    return self._send(200, service.confirm_proposal(user, parts[1], body))
                if len(parts) == 3 and parts[0] == "agents" and parts[2] == "reinstate" and method == "POST":
                    return self._send(200, service.reinstate_agent(user, parts[1], body))
                if len(parts) == 3 and parts[0] == "automations" and parts[2] == "run" and method == "POST":
                    return self._send(200, service.run_automation(user, parts[1], body))
                if len(parts) == 3 and parts[0] == "reviews" and parts[2] == "decision" and method == "POST":
                    return self._send(200, service.decide(user, parts[1], body))
                raise ApiError(404 if method == "GET" else 405, f"no route for {method} {path}")
            except ApiError as exc:
                self._send(exc.status, {"error": exc.message, **exc.extra})
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:  # never leak a traceback to clients; keep it in the server log
                service.log_error(f"{self.command} {urlparse(self.path).path}")
                self._send(500, {"error": f"internal error: {type(exc).__name__}"})

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

    return Handler


def make_server(service: AutologyService, host: str = "127.0.0.1", port: int = 8800) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _handler(service))
    server.daemon_threads = True
    return server


def serve(config_path: str, host: str = "127.0.0.1", port: int = 8800,
          store: Optional[str] = None) -> None:  # pragma: no cover - blocking
    import signal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    service = AutologyService.from_file(config_path, store)

    def stop_on_sigterm(signum, frame):  # `docker stop`, systemd, Kubernetes: shut down cleanly
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    server = make_server(service, host, port)
    stop = service.start_background()
    print(f"Autology API for {service.ontology.ref} on http://{host}:{server.server_port} "
          f"({len(service.agents)} agents, {len(service.users)} users, {len(service.automations)} automations, "
          f"store {service.store.path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        service.store.close()
        print("Autology stopped", flush=True)
