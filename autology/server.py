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
      ]
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
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .agent import DeferredApprover, ReviewDecision, WorkAgent
from .governance import REDACTED, GovernanceLayer, Principal
from .graph import Instance, KnowledgeGraph
from .ontology import Ontology, OntologyError
from .store import Store, StoreError

PERMISSIONS = frozenset({"read", "run", "review", "audit", "admin"})
MAX_BODY = 1_000_000
STATIC = Path(__file__).resolve().parent / "static"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


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
        self.agents: Dict[str, AgentConfig] = {}
        for name, spec in (config.get("agents") or {}).items():
            delegates = [WorkAgent(d["name"], self.ontology, load_tools(rel(d["tools"])), roles=d.get("roles", []))
                         for d in spec.get("delegates", [])]
            approver_spec = spec.get("approver", "inbox")
            approver = DeferredApprover() if approver_spec == "inbox" else load_approver(
                rel(approver_spec) if str(approver_spec).endswith(".json") else approver_spec)
            agent = WorkAgent(name, self.ontology, load_tools(rel(spec["tools"])), roles=spec.get("roles", []),
                              delegates=delegates, approver=approver,
                              reasoner=load_reasoner(spec.get("reasoner"), (str(base),)))
            goals = list(spec.get("goals") or self.ontology.goals)
            unknown = [g for g in goals if g not in self.ontology.goals]
            if unknown:
                raise OntologyError(f"agent {name}: unknown goals {unknown}")
            self.agents[name] = AgentConfig(name, agent, goals)
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

    @classmethod
    def from_file(cls, path: str) -> "AutologyService":
        p = Path(path).resolve()
        return cls(json.loads(p.read_text(encoding="utf-8")), p.parent)

    # -- auth ---------------------------------------------------------------
    def authenticate(self, header: Optional[str]) -> User:
        if not header or not header.startswith("Bearer "):
            raise ApiError(401, "missing bearer token")
        digest = hash_token(header[7:].strip())
        found = None
        for user in self.users:  # compare against every user: constant time per user, no early exit
            if hmac.compare_digest(digest, user.token_sha256):
                found = user
        if found is None:
            raise ApiError(401, "invalid token")
        return found

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
        return rule.when.evaluate(lambda e, a: inst.get(a) if e == inst.type else None)

    def visible(self, inst: Instance, user: User) -> bool:
        if "admin" in user.permissions:
            return True
        for rule in self.ontology.rules_of("row_access"):
            if rule.params["entity"] == inst.type and self._rule_applies(rule, inst) and \
                    not user.roles & set(rule.params["roles"]):
                return False
        return True

    def object_view(self, inst: Instance, user: User) -> Dict[str, Any]:
        attrs = {}
        for attr, value in inst.attributes.items():
            ref = f"{inst.type}.{attr}"
            hidden = "admin" not in user.permissions and any(
                r.params["field"] == ref and self._rule_applies(r, inst) and not user.roles & set(r.params["roles"])
                for r in self.ontology.rules_of("data_access"))
            attrs[attr] = REDACTED if hidden else value
        return {"id": inst.id, "type": inst.type, "attributes": attrs}

    # -- endpoints --------------------------------------------------------------
    def me(self, user: User) -> Dict[str, Any]:
        return {"name": user.name, "permissions": sorted(user.permissions), "roles": sorted(user.roles),
                "reviewer_roles": sorted(user.reviewer_roles)}

    def ontology_summary(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        o = self.ontology
        return {"ref": o.ref, "fingerprint": o.fingerprint, "description": o.description, "modules": list(o.modules),
                "entities": {e.name: {"states": list(e.states), "multiple": e.multiple,
                                      "attributes": {a.name: a.type for a in e.attributes.values()}}
                             for e in o.entities.values()},
                "actions": {a.name: {"description": a.description, "for_each": a.for_each} for a in o.actions.values()},
                "goals": {g.name: {"description": g.description, "target": str(g.target)} for g in o.goals.values()},
                "rules": [{"id": r.id, "kind": r.kind, "description": r.description} for r in o.rules],
                "questions": [{"id": q.id, "question": q.question} for q in o.questions],
                "agents": {n: {"goals": a.goals, "roles": sorted(a.agent.principal.roles)} for n, a in self.agents.items()}}

    def list_objects(self, user: User, entity_type: Optional[str], limit: int, offset: int) -> Dict[str, Any]:
        self.require(user, "read")
        if entity_type and entity_type not in self.ontology.entities:
            raise ApiError(404, f"unknown entity type {entity_type!r}")
        with self.graph_lock:
            found = [i for i in self.graph.instances(entity_type) if self.visible(i, user)]
            found.sort(key=lambda i: i.id)
            page = found[offset:offset + limit]
            return {"total": len(found), "items": [self.object_view(i, user) for i in page]}

    def get_object(self, user: User, iid: str) -> Dict[str, Any]:
        self.require(user, "read")
        with self.graph_lock:
            try:
                inst = self.graph.get(iid)
            except KeyError:
                raise ApiError(404, f"no object {iid!r}") from None
            if not self.visible(inst, user):
                raise ApiError(404, f"no object {iid!r}")  # don't reveal that a hidden row exists
            out = self.object_view(inst, user)
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
        etype, iid, attrs = body.get("type"), body.get("id"), dict(body.get("attributes") or {})
        if not etype or not iid:
            raise ApiError(400, "type and id are required")
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
        return self.object_view(inst, user)

    def answer(self, user: User, qid: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "read")
        with self.graph_lock:
            try:
                result = self.graph.ask(qid, **params)
            except OntologyError as exc:
                raise ApiError(404, str(exc)) from None
            ids = [i.id for i in result.instances if self.visible(i, user)]
            if result.value is not None and len(ids) != len(result.instances):
                raise ApiError(403, "the answer aggregates rows you may not see")
            return {"question": qid, "answer": result.value if result.value is not None else ids}

    def _summary(self, result, run_id: str, user: User) -> Dict[str, Any]:
        out = {"run_id": run_id, "case_id": result.case_id, "goal": result.goal, "status": result.status,
               "steps": [{"index": s.index, "action": s.action, "verdict": s.verdict, "outcome": s.outcome,
                          "executed_by": s.executed_by, "reviewer": s.reviewer, "message": s.message,
                          "explanation": s.explanation} for s in result.steps],
               "escalation": result.escalation.__dict__ if result.escalation else None,
               "costs": result.costs, "audit_verified": self.store.verify_audit(run_id)}
        out["state"] = self.access.redacted_view(result.state, user.principal) if "admin" not in user.permissions \
            else {**result.state.entities, **result.state.collections}
        pending = [r for r in self.store.list_reviews("pending") if r["run_id"] == run_id]
        out["pending_review"] = pending[0]["review_id"] if pending else None
        return out

    def _store_result(self, result, agent_name: str, run_id: Optional[str] = None) -> str:
        run_id = self.store.save_run(result, run_id, agent_name)
        if result.status == "awaiting_review" and result.run and result.run.pending_review:
            from .agent import ReviewRequest

            req = ReviewRequest(**{k: v for k, v in result.run.pending_review.items()
                                   if k in ReviewRequest.__dataclass_fields__})
            self.store.create_review(run_id, req)
        return run_id

    def start_run(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "run")
        name = body.get("agent") or (next(iter(self.agents)) if len(self.agents) == 1 else None)
        if name not in self.agents:
            raise ApiError(400, f"unknown agent {name!r}; available: {sorted(self.agents)}")
        cfg = self.agents[name]
        goal = body.get("goal") or (cfg.goals[0] if len(cfg.goals) == 1 else None)
        if goal not in cfg.goals:
            raise ApiError(400, f"agent {name} may pursue {cfg.goals}, not {goal!r}")
        case = body.get("case")
        if not isinstance(case, dict):
            raise ApiError(400, "case must be an object")
        with cfg.lock:
            try:
                result = cfg.agent.run(goal, case, str(body.get("case_id") or "case"))
            except OntologyError as exc:
                raise ApiError(400, f"invalid case: {exc}") from None
            run_id = self._store_result(result, name)
        return self._summary(result, run_id, user)

    def list_runs(self, user: User, status: Optional[str], limit: int, offset: int) -> Dict[str, Any]:
        self.require(user, "read")
        return {"items": self.store.list_runs(status, limit, offset)}

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

    def resume_run(self, user: User, run_id: str, force: bool = False) -> Dict[str, Any]:
        self.require(user, "run")
        cfg = self._agent_for(run_id)
        with cfg.lock:
            result = self.store.load_run(run_id)
            if result.status not in ("deferred", "paused"):
                raise ApiError(409, f"run {run_id} is {result.status}; only deferred or paused runs resume here")
            try:
                result = cfg.agent.resume(result, force=force)
            except (ValueError, OntologyError) as exc:
                raise ApiError(409, str(exc)) from None
            self._store_result(result, cfg.name, run_id)
        return self._summary(result, run_id, user)

    def list_reviews(self, user: User, status: Optional[str]) -> Dict[str, Any]:
        self.require(user, "review" if status in (None, "pending") else "read")
        roles = None if "admin" in user.permissions else user.reviewer_roles
        return {"items": self.store.list_reviews(status, roles)}

    def get_review(self, user: User, review_id: str) -> Dict[str, Any]:
        self.require(user, "read")
        try:
            return self.store.get_review(review_id)
        except KeyError:
            raise ApiError(404, f"no review {review_id!r}") from None

    def decide(self, user: User, review_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        self.require(user, "review")
        if not isinstance(body.get("approved"), bool):
            raise ApiError(400, "approved must be true or false")
        review = self.get_review(user, review_id)
        if "admin" not in user.permissions and not user.reviewer_roles & set(review["reviewers"]):
            raise ApiError(403, f"{user.name} may not decide reviews for {review['reviewers']}")
        cfg = self._agent_for(review["run_id"])
        with cfg.lock:
            try:
                self.store.decide_review(review_id, body["approved"], user.name, str(body.get("comment", "")))
            except StoreError as exc:
                raise ApiError(409, str(exc)) from None
            result = self.store.load_run(review["run_id"])
            decision = ReviewDecision(body["approved"], user.name, str(body.get("comment", "")))
            result = cfg.agent.resume(result, decision=decision)
            self._store_result(result, cfg.name, review["run_id"])
        return self._summary(result, review["run_id"], user)

    def report(self, user: User) -> str:
        self.require(user, "read")
        from .reporting import compliance_report

        return compliance_report(self.store.all_runs(), self.ontology)

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
            return score_deployment(self.ontology, self.store.all_runs(), tools=merged, graph=self.graph).as_dict()


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
            try:
                if method == "GET" and path in ("/", "/index.html", "/app.js", "/app.css"):
                    name = {"/": "index.html"}.get(path, path.lstrip("/"))
                    ctype = {"html": "text/html", "js": "application/javascript", "css": "text/css"}[name.rsplit(".")[-1]]
                    return self._send(200, (STATIC / name).read_bytes(), ctype)
                if path == "/api/health":
                    return self._send(200, {"status": "ok", "ontology": service.ontology.ref})
                if not path.startswith("/api/"):
                    raise ApiError(404, "not found")
                user = service.authenticate(self.headers.get("Authorization"))
                parts = path.split("/")[2:]
                limit = max(1, min(int(query.get("limit", 100)), 1000))
                offset = max(0, int(query.get("offset", 0)))
                body = self._body() if method == "POST" else {}
                routes = {
                    ("GET", "me"): lambda: service.me(user),
                    ("GET", "ontology"): lambda: service.ontology_summary(user),
                    ("GET", "objects"): lambda: service.list_objects(user, query.get("type"), limit, offset),
                    ("POST", "objects"): lambda: service.upsert_object(user, body),
                    ("GET", "runs"): lambda: service.list_runs(user, query.get("status"), limit, offset),
                    ("POST", "runs"): lambda: service.start_run(user, body),
                    ("GET", "reviews"): lambda: service.list_reviews(user, query.get("status", "pending")),
                    ("GET", "score"): lambda: service.score(user),
                }
                key = (method, parts[0]) if len(parts) == 1 else None
                if key in routes:
                    return self._send(200, routes[key]())
                if method == "GET" and parts == ["report"]:
                    return self._send(200, service.report(user), "text/markdown")
                if len(parts) == 2:
                    kind, ident = parts
                    if method == "GET" and kind == "objects":
                        return self._send(200, service.get_object(user, ident))
                    if method == "GET" and kind == "runs":
                        return self._send(200, service.get_run(user, ident))
                    if method == "GET" and kind == "reviews":
                        return self._send(200, service.get_review(user, ident))
                    if method == "POST" and kind == "questions":
                        return self._send(200, service.answer(user, ident, body.get("params") or {}))
                if len(parts) == 3 and parts[0] == "runs":
                    if method == "GET" and parts[2] == "audit":
                        return self._send(200, service.run_audit(user, parts[1]))
                    if method == "POST" and parts[2] == "resume":
                        return self._send(200, service.resume_run(user, parts[1], bool(body.get("force"))))
                if len(parts) == 3 and parts[0] == "reviews" and parts[2] == "decision" and method == "POST":
                    return self._send(200, service.decide(user, parts[1], body))
                raise ApiError(404 if method == "GET" else 405, f"no route for {method} {path}")
            except ApiError as exc:
                self._send(exc.status, {"error": exc.message})
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
            except Exception as exc:  # pragma: no cover - never leak a traceback to clients
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


def serve(config_path: str, host: str = "127.0.0.1", port: int = 8800) -> None:  # pragma: no cover - blocking
    service = AutologyService.from_file(config_path)
    server = make_server(service, host, port)
    print(f"Autology API for {service.ontology.ref} on http://{host}:{server.server_port} "
          f"({len(service.agents)} agents, {len(service.users)} users, store {service.store.path})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
