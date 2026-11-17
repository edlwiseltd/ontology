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
from typing import TYPE_CHECKING, Any, Callable, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .agent import DeferredApprover, WorkAgent
from .automation import Automation, Automator, Firing, load_automations
from .governance import REDACTED, GovernanceLayer, Principal

JUSTIFY = "***justification required***"
from .graph import Instance, KnowledgeGraph, build_case, snapshot
from .integrity import record_refusal
from .ontology import Ontology, OntologyError, type_ok
from .openapi import page_window, versioned_response
from .readiness import checked_weights
from .store import Store, StoreError, StoreJournal

if TYPE_CHECKING:  # the services import this module: these names are for the type checker only
    from .architecting import ArchitectService
    from .configuring import ConfigurationService
    from .ingestion import IngestionService
    from .notifications import NotificationService
    from .reviews import ReviewService
    from .runs import RunService

log = logging.getLogger("autology.server")
# "configure" is the administrative permission (IAM-3, D22a): design the model, change the assistant's settings.
# It reads no business record, run, review or audit entry. "admin" is full authority on one engine's data and
# operations; it implies every other permission and is given only by an explicit grant, never by an
# administrative role.
PERMISSIONS = frozenset({"read", "run", "review", "audit", "ingest", "reconcile", "configure", "admin"})
PRINCIPAL_KINDS = ("person", "service")  # who an API identity is: a signed-in person, or a machine (D11, F-02)
FINAL_STATUSES = frozenset({"completed", "blocked", "escalated", "suspended", "cancelled"})
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
    # roles an administrator lets this person use through an agent, beyond their own (D4): {agent: roles}
    run_as: Tuple[Tuple[str, FrozenSet[str]], ...] = ()
    # "person" or "service" (a script, pipeline or integration): only a person records human approvals (D11, F-02)
    kind: str = "person"
    # when the API token stops working (seconds since the epoch; GAP-030); None for a company sign-in, whose ID
    # token carries its own expiry
    expires_at: Optional[float] = None

    def grants(self, agent: str) -> FrozenSet[str]:
        return next((roles for name, roles in self.run_as if name == agent), frozenset())

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


def _services(engine: "AutologyService", config: Dict[str, Any]) -> Tuple[
        "NotificationService", "IngestionService", "RunService", "ReviewService", "ArchitectService",
        "ConfigurationService"]:
    """ARC-0: responsibilities taken out of the engine class, one at a time. Each service works through the
    engine it belongs to (its store, its rules, its permission checks): there is still one authority, the engine."""
    from .architecting import ArchitectService
    from .configuring import ConfigurationService
    from .ingestion import IngestionService
    from .notifications import NotificationService
    from .reviews import ReviewService
    from .runs import RunService

    return (NotificationService(engine), IngestionService(engine), RunService(engine), ReviewService(engine),
            ArchitectService(engine, config), ConfigurationService(engine, config))


def _tools(spec: Dict[str, Any], rel: Callable[[str], str]) -> Any:
    """An agent's tools: a file an operator wrote, or the declaration itself (a Studio-managed configuration)."""
    return spec["tools"] if isinstance(spec["tools"], dict) else rel(spec["tools"])


class AutologyService:
    """The API's behaviour, independent of HTTP (so it can be tested and embedded directly)."""

    def __init__(self, config: Dict[str, Any], base_dir: Path = Path(".")):
        from .adapters import load_approver, load_reasoner, load_tools

        base = self.base_dir = Path(base_dir)
        rel = lambda p: str((base / p).resolve())  # noqa: E731
        self.ontology_path = Path(rel(config["ontology"]))
        self.ontology = Ontology.load(self.ontology_path)
        from .audit import audit_key as env_audit_key, workspace_key

        # a workspace's chains are keyed with a key derived for it (ISO-2); otherwise AUTOLOGY_AUDIT_KEY itself
        self.audit_scope = config.get("audit_scope")
        self.audit_key = workspace_key(env_audit_key(), str(self.audit_scope)) if self.audit_scope else env_audit_key()
        self.store = Store(rel(config["store"]) if config.get("store", ":memory:") != ":memory:" else ":memory:",
                           audit_key=self.audit_key)
        import uuid

        # one writer per store (audit GAP-018): this process keeps the graph in memory, so no other may write
        self.lease_instance = uuid.uuid4().hex
        self.lease_ttl = max(180.0, 3 * float(config.get("automation_interval", 60)))
        self.writer = bool(config.get("writer", True))
        if self.writer:
            try:
                self.store.acquire_lease(self.lease_instance, self.lease_ttl)
            except StoreError as exc:
                raise ValueError(str(exc)) from None
        if config.get("data") and self.store.count_instances() == 0:
            data = config["data"] if isinstance(config["data"], dict) else json.loads(
                Path(rel(config["data"])).read_text(encoding="utf-8"))
            self.store.save_graph(KnowledgeGraph.from_dict(self.ontology, data))
        self.quarantined: List[Dict[str, Any]] = []  # stored records that no longer validate (audit GAP-010)
        self.graph = self.store.load_graph(self.ontology, quarantine=self.quarantined)
        # the revision of every record as this process last read or wrote it (optimistic concurrency, GAP-018)
        self.revisions: Dict[str, int] = self.store.instance_revisions(self.graph._instances)
        self._tampered = (0.0, 0)
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
        from .audit import KEY_ENV

        if self.audit_key is None and not self.simulation:
            raise ValueError(f"set {KEY_ENV} to a secret so the audit chain is keyed (HMAC); without it anyone who "
                             "can edit the store can rewrite the log undetected")
        # set by the platform: () -> the use case's effective stage (see execution_policy)
        # the platform answers the stage, or (stage, reason) when it can say why (drift, broken history)
        self.stage_gate: Optional[Callable[[], Any]] = None
        self.agents: Dict[str, AgentConfig] = {}
        self.model_findings: List[str] = []  # discretion a model has that no person reviews (GAP-045)
        for name, spec in (config.get("agents") or {}).items():
            delegates = [WorkAgent(d["name"], self.ontology, load_tools(_tools(d, rel)), roles=d.get("roles", []),
                                   audit_key=self.audit_key)
                         for d in spec.get("delegates", [])]
            approver_spec = spec.get("approver", "inbox")
            approver = DeferredApprover() if approver_spec == "inbox" else load_approver(
                rel(approver_spec) if str(approver_spec).endswith(".json") else approver_spec)
            if getattr(approver, "can_approve", False) and not self.simulation:
                raise ValueError(f"agent {name}: approver {approver_spec!r} approves human reviews without a "
                                 "person; use \"inbox\", or set \"simulation\": true for a test server")
            may_choose = spec.get("model_may_choose") or []
            if not isinstance(may_choose, list) or not all(isinstance(a, str) for a in may_choose):
                raise ValueError(f"agent {name}: model_may_choose must be a list of action names")
            agent = WorkAgent(name, self.ontology, load_tools(_tools(spec, rel)), roles=spec.get("roles", []),
                              delegates=delegates, approver=approver,
                              reasoner=load_reasoner(spec.get("reasoner"), (str(base),)),
                              journal=StoreJournal(self.store, name),  # external calls survive a crash
                              audit_key=self.audit_key,
                              # what a model reasoner may decide beyond the plan (GAP-045): governing settings,
                              # so they are part of the configuration fingerprint and of every release
                              model_discretion=spec.get("model_discretion", "governed"),
                              model_may_choose=may_choose, autonomy=spec.get("autonomy"))
            if spec.get("reasoner") not in (None, "planner"):
                from .integrity import model_findings

                for finding in model_findings(self.ontology, name, agent.model_discretion, may_choose):
                    self.model_findings.append(finding)
                    log.warning(finding)
            goals = list(spec.get("goals") or self.ontology.goals)
            unknown = [g for g in goals if g not in self.ontology.goals]
            if unknown:
                raise OntologyError(f"agent {name}: unknown goals {unknown}")
            self.agents[name] = AgentConfig(name, agent, goals)
            for member in [agent] + agent.delegates:
                member.tool_gate = self._tool_refused
            if hasattr(approver, "gate"):  # an HTTP approver reaches an outside system: the stage decides
                approver.gate = self._environment_refused
            held = self.store.active_suspension(name)
            if held:  # a suspension outlives restarts: only an admin reinstates the agent
                agent.governance.suspended[agent.principal.name] = held["reason"]
        # the governing configuration this engine runs (REL-1a): content-addressed; every run records it and never
        # continues on another one, and a platform release can only be activated when it is exactly this
        from .releases import configuration_snapshot, fingerprint_of

        try:
            document = json.loads(self.ontology_path.read_text(encoding="utf-8"))
        except ValueError:  # YAML ontologies: the loaded model stands for the document
            document = {"ref": self.ontology.ref}
        self.configuration_snapshot = configuration_snapshot(config, base, document, self.ontology.fingerprint,
                                                             self.ontology.ref)
        self.configuration_fingerprint = fingerprint_of(self.configuration_snapshot)
        for cfg_agent in self.agents.values():
            for member in [cfg_agent.agent] + cfg_agent.agent.delegates:
                member.configuration = self.configuration_fingerprint
        (self.notifications, self.ingestion, self.runs, self.reviews, self.architect,
         self.configuring) = _services(self, config)  # ARC-0: one service per responsibility taken out
        self._init_security(config, base)
        self.users: List[User] = self.parse_users(config.get("users", []))
        # identities automations run as (D4): explicit, least privilege, limited to named agents
        self.service_identities: Dict[str, Dict[str, Any]] = {}
        for sid, spec in (config.get("service_identities") or {}).items():
            agents_for = list(spec.get("agents") or [])
            for agent_name in agents_for:
                if agent_name not in self.agents:
                    raise ValueError(f"service identity {sid}: unknown agent {agent_name!r}")
            self.service_identities[sid] = {"roles": frozenset(spec.get("roles") or []), "agents": set(agents_for),
                                            "description": spec.get("description", "")}
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
        from .integrity import decision_fields

        # "Entity.attribute" -> what reads it to decide (rules, preconditions, goals, automations): GAP-037
        self.decision_fields = decision_fields(self.ontology, self.automations)
        for auto in self.automations.values():  # a run nobody asked for acts as an authorised service identity
            if auto.run:
                sid = auto.run.get("as")
                ident = self.service_identities.get(sid)
                if ident is None:
                    raise ValueError(f"automation {auto.name}: its runs need \"as\": a service identity from "
                                     f"service_identities (known: {sorted(self.service_identities) or 'none'})")
                if auto.run["agent"] not in ident["agents"]:
                    raise ValueError(f"automation {auto.name}: service identity {sid} is not authorised for agent "
                                     f"{auto.run['agent']}")
        self.automation_interval = float(config.get("automation_interval", 60))
        # one open run per record: a second run on the same claim could repeat its actions (e.g. pay twice)
        self.one_active_run_per_record = bool(config.get("one_active_run_per_record", True))
        self._starting: Dict[str, str] = {}  # root object -> who is starting a run on it right now
        self._starting_lock = threading.Lock()
        from .ingest import load_pipelines

        self.pipelines = load_pipelines(config.get("pipelines") or {}, self.ontology, base)
        self.ingest_lock = threading.Lock()  # one load at a time: plans are computed against the current graph
        self.reporting, self.readiness = dict(config.get("reporting") or {}), checked_weights(config.get("readiness"))
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
            from .tools import ENVIRONMENTS

            if hook.get("environment", "production") not in ENVIRONMENTS:
                raise ValueError(f"webhook {hook.get('url')!r}: environment must be one of {', '.join(ENVIRONMENTS)}")
            self.webhooks.append({"url": hook["url"], "kinds": set(hook.get("kinds") or []),
                                  "environment": hook.get("environment", "production")})
        self.deliveries: List[threading.Thread] = []  # webhook deliveries in flight (joined by tests)
        self.automator = Automator(self.automations, self.store, self._graph_instances, self._fire)
        from .views import ViewPolicy

        self.views = ViewPolicy(self)  # what each user may see of runs and reviews
        from .chat import GovernedChat

        self.tracing = dict(config.get("tracing") or {})
        if self.tracing and urlparse(str(self.tracing.get("endpoint", ""))).scheme not in ("http", "https"):
            raise ValueError("tracing endpoint must be an http or https URL")
        redact = dict(config.get("chat_redact") or {})
        # never sent to the model provider by the assistant, whatever the user may see (default: confidential)
        self.chat_redact_sensitivities = set(redact.get("sensitivities", ["confidential"]))
        self.chat_redact_fields = set(redact.get("fields", []))
        for ref in self.chat_redact_fields:
            self.ontology._check_field(ref, "chat_redact")
        self._chat_spec = dict(config.get("chat") or {})
        self._chat_search = (str(base),)
        from .settings import AssistantSettings

        secrets_file = config.get("secrets_file")  # where a Claude key saved from the Console is kept
        self.assistant_settings = AssistantSettings(self.store, config.get("chat"),
                                                    (base / secrets_file).resolve() if secrets_file else None)
        self.chat: Optional[GovernedChat] = None
        self._apply_assistant()
        for call in self.store.mark_interrupted_calls():  # nothing runs yet: an in-flight call was cut off
            log.error("external call %s (%s via %s) was in flight when the process stopped", call["key"],
                      call["action"], call["tool"])
            self._notify("reconciliation", [], f"{call['action']} via {call['tool']} was in flight when the server "
                                               "stopped; confirm whether it happened (GET /api/reconciliation)",
                         {"key": call["key"], "run_id": call.get("run_id"), "root": call.get("root")})
        self.recover()  # runs whose review was decided, or whose call was reconciled, before a crash
        for q in self.quarantined:  # tell admins, once per start, which stored records were left out
            log.error("stored %s %s fails validation and was left out of the graph: %s", q["type"], q["id"], q["reason"])
            self._notify("quarantine", [], f"Stored record {q['type']} {q['id']} no longer validates and was left "
                                           f"out: {q['reason']}. Fix it with an upsert or the ingestion pipeline.",
                         {"instance": q["id"], "type": q["type"]})

    @classmethod
    def from_file(cls, path: str, store: Optional[str] = None, assistant: Optional[str] = None,
                  audit_scope: Optional[str] = None, writer: bool = True) -> "AutologyService":
        """Load a server config; ``store`` overrides its store path (e.g. a volume in a container) and
        ``assistant`` turns on the governed assistant with that Claude model (or ``model:effort``)."""
        p = Path(path).resolve()
        config = json.loads(p.read_text(encoding="utf-8"))
        if store:
            config["store"] = store if store == ":memory:" else str(Path(store).resolve())
        if assistant:
            model, _, effort = assistant.partition(":")
            config["chat"] = {**(config.get("chat") or {}), "model": model or "claude-opus-5-5",
                              **({"effort": effort} if effort else {})}
        if audit_scope:  # a workspace's store behind the platform router uses that workspace's audit key
            config["audit_scope"] = audit_scope
        if not writer:  # read-only tools (backup, reporting) may run next to the server
            config["writer"] = False
        return cls(config, p.parent)

    # -- auth ---------------------------------------------------------------
    def _init_security(self, config: Dict[str, Any], base: Path) -> None:
        """``security`` in the configuration (GAP-030): token lifetimes, rate limits, trusted proxies, server
        limits. Behind the platform router, the platform supplies the limiter and each token's expiry."""
        from . import credentials, limits

        security = config.get("security") or {}
        if not isinstance(security, dict) or set(security) - {"tokens", "rate_limits", "trusted_proxies", "server",
                                                               "run_seconds"}:
            raise ValueError("security: tokens, rate_limits, trusted_proxies, server and run_seconds only")
        try:
            self.token_policy = credentials.TokenPolicy.parse(security.get("tokens"))
            self.limiter = limits.RateLimiter.parse(security.get("rate_limits"))
            self.trusted_proxies = limits.parse_proxies(security.get("trusted_proxies"))
            self.server_limits = limits.parse_server(security.get("server"))
        except (credentials.CredentialError, limits.LimitError) as exc:
            raise ValueError(str(exc)) from None
        run_seconds = security.get("run_seconds", 900)
        if isinstance(run_seconds, bool) or not isinstance(run_seconds, (int, float)) or not (1 <= run_seconds <= 86400):
            raise ValueError("security.run_seconds: between 1 and 86400")
        self.run_seconds = float(run_seconds)
        for cfg_agent in self.agents.values():  # checked between steps: a started action is never cut short
            for member in [cfg_agent.agent] + cfg_agent.agent.delegates:
                member.max_seconds = self.run_seconds
        self.background_guard: Optional[Tuple[Any, Any]] = None  # behind the platform: (enter, leave) of the gate
        self.limit_scope = ""  # behind the platform: "<workspace>:", so an identity is counted once per workspace
        self.tenant_key: Optional[str] = None  # behind the platform: the tenant all requests are counted under
        # Where token first-sight dates are kept: beside a SQLite store by default. "" means the caller (the
        # platform) supplies each token's expiry itself. Without a file (a memory or PostgreSQL store and no
        # credentials_file), lifetimes count from this start, and say so.
        self.credentials: Optional[credentials.CredentialRegistry] = None
        self._owns_credentials = False  # the platform's registry is shared: only its owner closes it
        self.credentials_persistent = False
        where = config.get("credentials_file")
        if where == "":
            return
        store_path = str(config.get("store") or "")
        if where:
            path = str((base / where).resolve())
        elif store_path and store_path != ":memory:" and "://" not in store_path:
            path = str((base / store_path).resolve()) + ".credentials"
        else:
            path = ":memory:"
        try:
            self.credentials = credentials.CredentialRegistry(path, self.audit_key)
        except credentials.CredentialError as exc:
            raise ValueError(str(exc)) from None
        self._owns_credentials = True
        self.credentials_persistent = path != ":memory:"
        if not self.credentials_persistent and config.get("users"):
            log.warning("no file to remember when API tokens were first seen (set credentials_file): their "
                        "lifetimes count from this start")

    def parse_users(self, specs: List[Dict[str, Any]]) -> List[User]:
        """API identities from configuration (or from the platform's membership, ADM-1). Raises ValueError."""
        users: List[User] = []
        for u in specs:
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
            run_as = u.get("run_as") or {}
            for agent_name, granted in run_as.items():
                cfg_agent = self.agents.get(agent_name)
                if cfg_agent is None:
                    raise ValueError(f"user {u['name']}: run_as names unknown agent {agent_name!r}")
            kind = u.get("kind", "person")
            if kind not in PRINCIPAL_KINDS:
                raise ValueError(f"user {u['name']}: kind must be one of {list(PRINCIPAL_KINDS)}")
            users.append(User(u["name"], digest.lower(), perms, frozenset(u.get("roles", [])),
                                   frozenset(u.get("reviewer_roles", [])),
                                   tuple(sorted((a, frozenset(r)) for a, r in run_as.items())), kind,
                                   self._token_expiry(u, digest.lower(), kind)))
        return users

    def _token_expiry(self, spec: Dict[str, Any], digest: str, kind: str) -> Optional[float]:
        """When this user's token stops working: what the platform computed (``token_expires_at``), or the
        policy's lifetime from the day the token was first seen, or an earlier explicit ``token_expires``."""
        from . import credentials

        if spec.get("token_expires_at") is not None:
            return float(spec["token_expires_at"])
        try:
            explicit = None if spec.get("token_expires") is None else credentials.parse_time(
                spec["token_expires"], f"user {spec['name']}")
        except credentials.CredentialError as exc:
            raise ValueError(str(exc)) from None
        if self.credentials is None:
            return explicit
        seen = self.credentials.register(digest, spec["name"], kind)
        return credentials.expires_at(seen, kind, self.token_policy, explicit)

    def set_users(self, specs: List[Dict[str, Any]]) -> None:
        """Replace the API identities at once (hot reload of membership, ADM-2): the next request sees them."""
        users = self.parse_users(specs)
        self.users, self._token_user_names = users, frozenset(u.name for u in users)

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
        problem = self.token_problem(found)
        if problem:
            raise ApiError(401, problem, {"reason": "token_expired" if "expired" in problem else "token_revoked"})
        return found

    def token_problem(self, user: User) -> Optional[str]:
        """Why this user's API token no longer works (expired, revoked), or None. Checked on every request, and
        again for each message of a long session (MCP over stdio)."""
        from . import credentials

        if not user.token_sha256:
            return None  # a company sign-in: the identity provider's token was verified, with its own expiry
        if self.credentials is not None and self.credentials.revoked(user.token_sha256):
            return "this token was revoked"
        if user.expires_at is not None and credentials.now() >= user.expires_at:
            return (f"this token expired on {credentials.iso(user.expires_at)}: ask an administrator for a new one"
                    if user.kind == "person" else
                    f"this service token expired on {credentials.iso(user.expires_at)}: an administrator must "
                    "issue a new one")
        return None

    def current(self, user: User) -> Optional[str]:
        """For a session that outlives one request: why ``user`` may not continue (token replaced, removed,
        expired or revoked since the session began), or None."""
        if not user.token_sha256:
            return None
        if not any(u.name == user.name and hmac.compare_digest(u.token_sha256, user.token_sha256)
                   for u in self.users):
            return "this token was replaced or its member removed"
        return self.token_problem(user)

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

    @staticmethod
    def require_any(user: User, *permissions: str) -> None:
        if not any(user.can(p) for p in permissions):
            raise ApiError(403, f"{user.name} lacks the {' or '.join(repr(p) for p in permissions)} permission")

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
        out = {"id": inst.id, "type": inst.type, "attributes": attrs,
               "revision": self.revisions.get(inst.id, 0)}  # send it back as expected_revision to avoid lost updates
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
        from . import credentials

        return {"name": user.name, "permissions": sorted(user.permissions), "roles": sorted(user.roles),
                "reviewer_roles": sorted(user.reviewer_roles), "kind": user.kind,
                "token_expires_at": credentials.iso(user.expires_at)}

    def ontology_summary(self, user: User) -> Dict[str, Any]:
        self.require_any(user, "read", "configure")
        o = self.ontology
        return {"ref": o.ref, "fingerprint": o.fingerprint, "description": o.description, "modules": list(o.modules),
                "free_form_cases": self.simulation or "admin" in user.permissions,
                "case_templates": {t.name: {"root": t.root} for t in o.case_templates.values()},
                "entities": {e.name: {"states": list(e.states), "multiple": e.multiple, "aliases": list(e.aliases),
                                      "attributes": {a.name: a.type for a in e.attributes.values()}}
                             for e in o.entities.values()},
                "relationships": [{"source": r.source, "target": r.target, "kind": r.kind,
                                   "cardinality": r.cardinality} for r in o.relationships],
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
        from .store import ABSENT, RecordConflict

        expected_by_client = body.get("expected_revision")
        if expected_by_client is not None and (isinstance(expected_by_client, bool)
                                               or not isinstance(expected_by_client, int) or expected_by_client < 0):
            raise ApiError(400, "expected_revision must be a non-negative integer (0: the record must not exist yet)")
        with self.graph_lock:
            if expected_by_client is not None and self.revisions.get(iid, 0) != expected_by_client:
                # the client read an older revision: refuse, and give it the current one (no lost update)
                current = self.graph._instances.get(iid)
                raise ApiError(409, f"{iid} was changed since you read it (revision {self.revisions.get(iid, 0)}, "
                                    f"you sent {expected_by_client}); nothing was written",
                               {"record": iid, "revision": self.revisions.get(iid, 0),
                                "current": self.object_view(current, user) if current is not None and
                                self.visible(current, user) else None})
            candidate = KnowledgeGraph(self.ontology)
            try:
                inst = candidate.add(etype, iid, **attrs)  # validates type, attributes and state
            except OntologyError as exc:
                raise ApiError(400, str(exc)) from None
            refused = record_refusal(self.ontology, self.graph, etype, iid, inst.attributes, user.roles)
            if refused:  # decision-critical facts bind every writer, the unrestricted permission included
                raise ApiError(403, f"{refused}; nothing was written")
            try:  # only over the revision this process holds: a stale or tampered row is never overwritten
                self.revisions[iid] = self.store.upsert_instance(etype, iid, inst.attributes,
                                                                 self.revisions.get(iid, ABSENT))
            except RecordConflict as exc:
                self._record_conflict(exc)
                raise ApiError(409, f"{exc}; nothing was written", {"record": iid, "tampered": exc.tampered}) \
                    from None
            before = self.graph._instances.get(iid)
            self.graph._instances[iid] = inst
            changed_facts = [] if before is None else sorted(
                a for a, v in inst.attributes.items()
                if before.attributes.get(a) != v and f"{etype}.{a}" in self.decision_fields)
            for link in body.get("links", []):
                try:
                    self.graph.link(iid, link["kind"], link["target"])
                except (OntologyError, KeyError) as exc:
                    raise ApiError(400, f"invalid link {link}: {exc}") from None
                self.store.add_link(iid, link["kind"], link["target"])
        out = self.object_view(inst, user)
        if changed_facts:
            self._evidence_changed({iid: changed_facts}, user.name)
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
            hidden = self._question_hidden_field(user, question, self.graph)
            if hidden:
                raise ApiError(403, f"the answer depends on {hidden}, which you may not read")
            gated = self._question_gated_fields(question, self.graph)
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

    @staticmethod
    def question_refs(question) -> set:
        """The ``Entity.attr`` fields a competency question reads: its filters and its aggregate."""
        refs = set()
        for expr in (question.where, question.result_where):
            refs |= {f"{e}.{a}" for e, a in (expr.references if expr else ()) if e != "Params"}
        if question.aggregate and question.aggregate[1]:
            refs.add(question.aggregate[1])
        return refs

    def _question_hidden_field(self, user: User, question, graph) -> Optional[str]:
        """The first field the question reads that the user may not read on some record of ``graph``."""
        for ref in sorted(self.question_refs(question)):
            entity, attr = ref.split(".", 1)
            if any(self.field_hidden(inst, attr, user) for inst in graph.instances(entity)):
                return ref
        return None

    def _question_gated_fields(self, question, graph) -> List[str]:
        """The checkpoint-gated fields (a written reason first) the question reads on some record."""
        gated = set()
        for ref in self.question_refs(question):
            entity, attr = ref.split(".", 1)
            gated |= {f"{i.type}.{attr}" for i in graph.instances(entity) if f"{i.type}.{attr}" in self.views.gated}
        return sorted(gated)

    def _summary(self, result, run_id: str, user: User, receipt: bool = False) -> Dict[str, Any]:
        return self.runs._summary(result, run_id, user, receipt)

    def _store_result(self, result, agent_name: str, run_id: Optional[str] = None,
                      sources: Optional[Tuple[str, str, Dict[str, Any], bool]] = None,
                      started_by: Optional[str] = None) -> Tuple[str, List[str]]:
        return self.runs._store_result(result, agent_name, run_id, sources, started_by)

    def _export_trace(self, run_id: str, result) -> None:
        return self.runs._export_trace(run_id, result)

    def run_trace(self, user: User, run_id: str) -> Dict[str, Any]:
        return self.runs.run_trace(user, run_id)

    def _write_back(self, run_id: str, result, linked: Dict[str, Any]) -> List[str]:
        return self.runs._write_back(run_id, result, linked)

    def complete_write_backs(self) -> List[Dict[str, Any]]:
        return self.runs.complete_write_backs()

    def retry_write_back(self, user: User, run_id: str) -> Dict[str, Any]:
        return self.runs.retry_write_back(user, run_id)

    def write_back_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.runs.write_back_status(run_id)

    def _changed(self, instance_ids: List[str]) -> List[Firing]:
        return self.automator.on_change(instance_ids) if instance_ids and self.automations else []

    # -- automations and notifications ------------------------------------------
    def _graph_instances(self, entity: Optional[str]) -> List[Instance]:
        with self.graph_lock:
            return list(self.graph.instances(entity))

    def close(self) -> None:
        """Stop writing: give up the store's writer lease (so the next server starts at once) and close it."""
        if self.writer:
            try:
                self.store.release_lease(self.lease_instance)
            except Exception:  # never block a shutdown
                log.warning("could not release the store's writer lease", exc_info=True)
        self.store.close()
        if self.credentials is not None and self._owns_credentials:
            self.credentials.close()

    def health(self) -> Dict[str, Any]:

        tampered = self.tampered_records()
        out = {"status": "degraded" if self.quarantined or tampered else "ok", "ontology": self.ontology.ref,
               "configuration": self.configuration_fingerprint,
               "simulation": self.simulation, "audit_keyed": self.audit_key is not None,
               "scheduler": self.scheduler_status, "quarantined_records": len(self.quarantined),
               "tampered_records": tampered}
        policy = self.execution_policy()
        if policy is not None:
            out["stage"] = policy["stage"]
            out["runs_allowed"] = policy["runs"]
            out["tool_environments"] = sorted(policy["environments"])
        return out

    # -- model design (Studio increment 2): drafts are never active ----------------------------------------------
    def _active_document(self) -> Dict[str, Any]:
        return json.loads(self.ontology_path.read_text(encoding="utf-8"))

    def model_draft(self, user: User) -> Dict[str, Any]:
        from .modeling import consistency, questions, validate

        self.require_any(user, "read", "configure")
        row = self.store.draft()
        doc = row["document"] if row else self._active_document()
        return {"revision": row["revision"] if row else 0, "document": doc, "origin": (row or {}).get("origin"),
                "author": row["author"] if row else None, "at": row["at"] if row else None,
                "note": row["note"] if row else "the active model (no draft saved yet)",
                "active": {"ref": self.ontology.ref, "fingerprint": self.ontology.fingerprint},
                "validation": validate(doc), "questions": questions(doc, self), "consistency": consistency(doc)["findings"],
                "active_model_changed": False}  # a draft never changes what runs (releases: REL-1)

    def save_model_draft(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        from .store import RecordConflict

        self.require(user, "configure")
        doc, expected = body.get("document"), body.get("expected_revision")
        if not isinstance(doc, dict):
            raise ApiError(400, "document must be a JSON object (an ontology document)")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ApiError(400, "expected_revision is required: the draft revision you read (0 if none)")
        if len(json.dumps(doc, default=str)) > 500_000:
            raise ApiError(413, "the draft is too large")
        try:
            self.architect.save_draft(doc, user.name, str(body.get("note") or "")[:500], expected, body.get("origin"))
        except RecordConflict as exc:
            raise ApiError(409, f"{exc}; reload the draft and apply your changes again",
                           {"revision": exc.revision}) from None
        return self.model_draft(user)

    def model_draft_history(self, user: User) -> Dict[str, Any]:
        self.require_any(user, "read", "configure")
        return {"items": self.store.draft_history()}

    def validate_model(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        from .modeling import consistency, questions, validate

        self.require_any(user, "read", "configure")
        doc = body.get("document")
        return {"validation": validate(doc), "questions": questions(doc, self), "consistency": consistency(doc)["findings"]}

    def architect_proposals(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.architect.architect_proposals(user, body)

    def mcp_message(self, user: User, message: Any) -> Optional[Dict[str, Any]]:
        """One MCP JSON-RPC message over HTTP (``POST /api/mcp``), answered by the same server as over stdio, as
        this user: the same tools, permissions, redaction and gates. Notifications get no answer."""
        from .mcp import McpServer

        # a token with no operational permission gets nothing, not even an acknowledgement; the administrative
        # "configure" permission is not one: MCP serves data and actions (IAM-3)
        if not user.permissions - {"configure"}:
            raise ApiError(403, f"{user.name} has no permission in this use case")
        if not isinstance(message, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        return McpServer(self, user, limited=False).handle(message)  # counted by the HTTP layer

    # -- record consistency (audit GAP-018) ---------------------------------------------------------------------
    def tampered_records(self) -> int:
        """How many stored records were changed outside Autology (seal mismatch). Cached for a minute."""
        checked_at, count = self._tampered
        if not checked_at or time.monotonic() - checked_at > 60:
            count = len(self.store.tampered_instances())
            self._tampered = (time.monotonic(), count)
        return count

    def _record_conflict(self, exc) -> None:
        """A write was refused because the stored record is not the one this process holds. A record sealed by
        Autology is authoritative: it is reloaded. A tampered one is never trusted: it stays out, admins are told."""
        if exc.tampered:
            self._tampered = (0.0, 0)
            log.warning("record %s: %s", exc.iid, exc.reason)
            self._notify("quarantine", [], f"Record {exc.iid} was changed outside Autology; it is not used and "
                                           "nothing was written over it. Review the store.", {"record": exc.iid})
            return
        row = self.store.read_instance(exc.iid)
        if row is None:
            self.graph._instances.pop(exc.iid, None)
            self.revisions.pop(exc.iid, None)
            return
        try:
            self.graph._instances[exc.iid] = KnowledgeGraph(self.ontology).add(row["type"], exc.iid,
                                                                               **row["attributes"])
            self.revisions[exc.iid] = row["revision"]
        except (OntologyError, ValueError, TypeError):
            self.log_error(f"reloading record {exc.iid}")

    # -- execution gates (R2): the use case's lifecycle stage governs what may run --------------------------
    def execution_policy(self) -> Optional[Dict[str, Any]]:
        """What the use case's stage allows now, read at every check (so a stage change applies at once, in
        every process). ``None`` for a standalone engine, which no platform stage governs."""
        if self.stage_gate is None:
            return None
        from .lifecycle import policy_for

        try:
            stage = self.stage_gate()
            policy = policy_for(stage[0] if isinstance(stage, tuple) else stage)
            if isinstance(stage, tuple) and stage[1] and policy["refusal"]:  # the platform says why (e.g. drift)
                policy = {**policy, "refusal": f"{policy['refusal']}. Reason: {stage[1]}"}
            return policy
        except Exception:  # the stage cannot be read: fail closed
            self.log_error("reading the use case's lifecycle stage")
            return policy_for(None)

    def _runs_refused(self) -> Optional[str]:
        policy = self.execution_policy()
        return None if policy is None or policy["runs"] else policy["refusal"]

    def _tool_refused(self, tool: Any) -> Optional[str]:
        return self._environment_refused(tool.environment, f"tool {tool.name}")

    def _environment_refused(self, environment: str, what: str) -> Optional[str]:
        """None if the use case's stage lets ``what`` reach a system of this environment, else the reason."""
        policy = self.execution_policy()
        if policy is None or environment in policy["environments"]:
            return None
        return (f"{what} reaches a {environment} system, which the use case's stage ({policy['stage']}) "
                "does not allow")

    def _require_runs(self) -> None:
        refusal = self._runs_refused()
        if refusal:
            raise ApiError(409, refusal, {"stage": self.execution_policy()["stage"]})

    def _not_for_notifications(self, inst: Instance, attr: str, user: User) -> bool:
        return self.notifications._not_for_notifications(inst, attr, user)

    def _hidden_from_roles(self, inst: Instance, attr: str, roles) -> bool:
        return self.notifications._hidden_from_roles(inst, attr, roles)

    def _notify_record(self, kind: str, roles, template: str, inst: Instance, ref: Dict[str, Any]) -> Dict[str, Any]:
        return self.notifications._notify_record(kind, roles, template, inst, ref)

    def _evidence_changed(self, changes: Dict[str, List[str]], by: str) -> List[str]:
        return self.notifications._evidence_changed(changes, by)

    def _notify(self, kind: str, roles, message: str, ref: Dict[str, Any]) -> Dict[str, Any]:
        return self.notifications._notify(kind, roles, message, ref)

    @staticmethod
    def _deliver(url: str, note: Dict[str, Any]) -> None:
        import urllib.request

        from . import outbound

        req = urllib.request.Request(url, json.dumps({"autology": note}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "Autology"})
        try:  # a redirect to another origin is not followed (audit F-01)
            outbound.urlopen(req, 5).close()
        except Exception:  # best effort: the notification stays in the store either way
            log.warning("webhook delivery to %s failed", urlparse(url).netloc, exc_info=True)  # no path: may hold tokens

    def _active_runs(self, root: str, exclude: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r for r in self.store.active_runs_for_root(root, FINAL_STATUSES) if r["run_id"] != exclude]

    def _exclusive(self, root: str, who: str):
        """Hold ``root`` while a run on it is started and stored; refuse if it already has an open run."""
        service = self

        class _Hold:
            def __enter__(self):
                if not service.one_active_run_per_record:
                    return self
                with service._starting_lock:
                    if root in service._starting:
                        raise ApiError(409, f"{root} already has a run being started (by {service._starting[root]}); "
                                            "wait for it to finish", {"root": root})
                    blocking = [c for c in service.store.blocking_calls(root) if service._has_effect(c)]
                    if blocking:  # an external call on this record may have happened: a person must say first
                        call = blocking[0]
                        raise ApiError(409, f"{root} has an external call whose outcome nobody has confirmed "
                                            f"({call['action']} via {call['tool']}, {call['state'].replace('_', ' ')}"
                                            f"{', from a run that was never saved' if call.get('orphan') else ''}). "
                                            "Reconcile it first (GET /api/reconciliation), so it cannot happen twice",
                                       {"root": root, "reconcile": [c["key"] for c in blocking]})
                    active = service._active_runs(root)
                    if active:
                        run = active[0]
                        raise ApiError(409, f"{root} already has an open run {run['run_id']} "
                                            f"({run['status'].replace('_', ' ')}, started by {run['started_by']}). "
                                            "Finish it (decide its review) or decline it before starting another, "
                                            "so its actions cannot run twice",
                                       {"root": root, "active_run": run["run_id"], "active_status": run["status"]})
                    service._starting[root] = who
                return self

            def __exit__(self, *exc):
                if service.one_active_run_per_record:
                    with service._starting_lock:
                        service._starting.pop(root, None)
                return False

        return _Hold()

    def _fire(self, auto: Automation, inst: Instance, trigger: str, starter: Optional[User] = None) -> Firing:
        """Fire an automation on a record. With ``starter`` (a person firing it by hand) the run is theirs: they
        are its starter and it may act only on records they may see. Otherwise it runs as the automation."""
        firing = Firing(auto.name, inst.id, trigger)
        if auto.run and self._runs_refused():
            firing.status, firing.detail = "skipped", self._runs_refused()
            return firing
        if auto.run:
            cfg = self.agents[auto.run["agent"]]
            template = auto.run["case_template"]
            who = starter.name if starter else f"automation:{auto.name}"
            try:
                hold = self._exclusive(inst.id, who)
                hold.__enter__()
            except ApiError as exc:  # the record already has an open run: never start a second one
                firing.status, firing.detail = "skipped", exc.message
                firing.run_id = exc.extra.get("active_run")
                return firing
            try:
                with self.graph_lock:
                    case, sources = build_case(self.graph, template, inst.id)
                    if starter is not None and self._case_hides_records(sources, starter):
                        firing.status = "skipped"
                        firing.detail = (f"the case for {inst.id} includes records you may not see; ask someone "
                                         "who may see all of them to start this run")
                        return firing
                    base = snapshot(self.graph, sources)
                with cfg.lock:
                    result = cfg.agent.run(auto.run["goal"], case, f"{auto.name}:{inst.id}", started_by=who,
                                           root=inst.id, roles=self.run_roles(cfg, starter) if starter else
                                           self.run_roles(cfg, identity=auto.run["as"]),
                                           acting_as=starter.name if starter else f"service:{auto.run['as']}")
                    firing.run_id, changed = self._store_result(
                        result, cfg.name, sources=(template, inst.id, sources, bool(auto.run["write_back"]), base),
                        started_by=who)
            finally:
                hold.__exit__(None, None, None)
            firing.status = result.status
            firing.detail = result.escalation.reason if result.escalation else ""
            self._changed(changed)
        if auto.notify:
            ref = {"automation": auto.name, "instance": inst.id, "run_id": firing.run_id, "status": firing.status}
            firing.notification_id = self._notify_record("automation", auto.notify["roles"], auto.template, inst,
                                                         ref)["notification_id"]
            if not auto.run:
                firing.status = "notified"
        return firing

    def tick(self) -> Dict[str, Any]:
        """One scheduler pass: resume deferred runs whose retry time has come, then evaluate automations."""
        resumed = []
        paused = self._runs_refused()  # the stage forbids runs: nothing resumes and no automation starts one
        for row in ([] if paused else self.store.list_runs("deferred", limit=10 ** 9)):
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
        if self.writer and not self.store.refresh_lease(self.lease_instance):
            log.error("another Autology process took over this store: stop one of them")
        recovered = self.recover()
        loads = self._due_pipelines()
        firings = self.automator.tick() if self.automations and not paused else []
        out = {"resumed": resumed, "firings": [f.as_dict() for f in firings]}
        if paused:
            out["paused"] = paused
        if recovered:
            out["recovered"] = recovered
        if self.pipelines:
            out["ingested"] = loads
        every = self.reporting.get("every")
        if every and (self._last_report is None or time.monotonic() - self._last_report >= float(every)):
            out["reporting"] = self.refresh_reporting()["rows"]
        return out

    # -- assistant settings (the Console's Configuration tab) ---------------------------------
    def _apply_assistant(self) -> None:
        from .chat import AnthropicChatBackend, GovernedChat, load_backend

        cfg = self.assistant_settings
        if cfg.custom_backend:  # a scripted or third-party backend from the config file
            backend = load_backend(self._chat_spec, self._chat_search)
        elif cfg.enabled:
            backend = AnthropicChatBackend(model=cfg.model, effort=cfg.effort, max_tokens=cfg.max_tokens,
                                           client_factory=cfg.client_factory())
        else:
            backend = None
        self.chat = GovernedChat(self, backend) if backend else None

    def assistant_view(self, user: User) -> Dict[str, Any]:
        self.require(user, "configure")
        return self.assistant_settings.view()

    def update_assistant(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        from .settings import SettingsError

        self.require(user, "configure")
        try:
            self.assistant_settings.update(body)
        except SettingsError as exc:
            raise ApiError(400, str(exc)) from None
        except OSError as exc:  # the secrets file could not be written
            raise ApiError(500, f"could not save the key: {exc.strerror or exc}") from None
        self._apply_assistant()
        changed = sorted(k for k in body if k != "api_key") + (["api_key"] if body.get("api_key") else [])
        self.log_access(user, "settings.assistant", ",".join(changed) or "-", 200)  # never the key itself
        return self.assistant_settings.view()

    def test_assistant(self, user: User) -> Dict[str, Any]:
        """Check the key and model with Claude without spending tokens (a model lookup)."""
        self.require(user, "configure")
        cfg = self.assistant_settings
        try:
            import anthropic
        except ImportError:
            return {"ok": False, "error": "the anthropic package is not installed where the engine runs "
                                          "(pip install anthropic)"}
        try:
            model = cfg.client_factory()().models.retrieve(cfg.model)
        except anthropic.AuthenticationError:
            return {"ok": False, "error": "Claude rejected the key: check it in console.anthropic.com"}
        except anthropic.PermissionDeniedError:
            return {"ok": False, "error": "the key is valid but not allowed to use this model or workspace"}
        except anthropic.NotFoundError:
            return {"ok": False, "error": f"{cfg.model} is not available to this key"}
        except anthropic.APIConnectionError:
            return {"ok": False, "error": "the engine cannot reach Claude (internet connection or proxy)"}
        except anthropic.APIStatusError as exc:
            return {"ok": False, "error": f"Claude answered {exc.status_code}"}
        except Exception as exc:  # e.g. no credentials at all
            from .chat import NO_CREDENTIALS

            text = str(exc).lower()
            return {"ok": False, "error": NO_CREDENTIALS if "authentication" in text or "api_key" in text
                    else type(exc).__name__}
        return {"ok": True, "model": getattr(model, "id", cfg.model),
                "name": getattr(model, "display_name", None)}

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
               pushed: Optional[Dict[str, Any]] = None, roles: Optional[FrozenSet[str]] = None,
               unrestricted: bool = False) -> Dict[str, Any]:
        return self.ingestion.ingest(name, triggered_by, dry_run, pushed, roles, unrestricted)

    def _due_pipelines(self) -> List[Dict[str, Any]]:
        return self.ingestion._due_pipelines()

    def list_pipelines(self, user: User) -> Dict[str, Any]:
        return self.ingestion.list_pipelines(user)

    def run_pipeline(self, user: User, name: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.ingestion.run_pipeline(user, name, body)

    def ingest_batch(self, user: User, batch_id: str) -> Dict[str, Any]:
        return self.ingestion.ingest_batch(user, batch_id)

    def object_lineage(self, user: User, iid: str) -> Dict[str, Any]:
        return self.ingestion.object_lineage(user, iid)

    def start_background(self, interval: Optional[float] = None) -> threading.Event:
        """Tick every ``interval`` seconds in a daemon thread; set the returned event to stop."""
        stop = threading.Event()
        every = interval or self.automation_interval

        def loop():
            while not stop.wait(every):
                # behind the platform the scheduler shares the use case with requests: it never ticks while the
                # engine is being switched, and an engine that was replaced meanwhile does not tick again
                guard = self.background_guard
                if guard is not None and not guard[0]():
                    continue
                try:
                    if stop.is_set():
                        continue
                    self.tick()
                    self.scheduler_status["last_tick"] = _utcnow()
                except Exception as exc:  # keep the scheduler alive, but never silently
                    self.log_error("scheduler tick")
                    self.scheduler_status["last_error"] = {"at": _utcnow(), "error": f"{type(exc).__name__}: {exc}"}
                finally:
                    if guard is not None:
                        guard[1]()

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
        if self.automations[name].run:
            self._require_runs()
        auto = self.automations[name]
        instance = body.get("instance")
        if instance:
            with self.graph_lock:
                inst = self.graph._instances.get(instance)
                if inst is None or not self.visible(inst, user):
                    raise ApiError(404, f"no object {instance!r}")
        if auto.run:  # firing by hand starts runs: the same checkpoint as starting one directly
            self.checkpoint(user, "start_run", f"{name}/{auto.run['goal']}/{instance or 'all'}",
                            body.get("justification"), goal=auto.run["goal"])
        try:
            firings = self.automator.run_now(name, instance, allow=lambda i: self.visible(i, user),
                                             starter=user)
        except KeyError:
            raise ApiError(400, f"{instance!r} is not a {self.automations[name].entity}") from None
        return {"firings": [f.as_dict() for f in firings]}

    def list_notifications(self, user: User, since: Optional[str], limit: int) -> Dict[str, Any]:
        return self.notifications.list_notifications(user, since, limit)

    def run_roles(self, cfg: AgentConfig, user: Optional[User] = None, identity: Optional[str] = None) -> List[str]:
        return self.runs.run_roles(cfg, user, identity)

    def _case_hides_records(self, sources: Dict[str, Any], user: User) -> bool:
        return self.runs._case_hides_records(sources, user)

    def start_run(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.runs.start_run(user, body)

    def list_runs(self, user: User, status: Optional[str], limit: int, offset: int) -> Dict[str, Any]:
        return self.runs.list_runs(user, status, limit, offset)

    def _visible_runs(self, user: User) -> List[Any]:
        return self.runs._visible_runs(user)

    def get_run(self, user: User, run_id: str) -> Dict[str, Any]:
        return self.runs.get_run(user, run_id)

    def run_audit(self, user: User, run_id: str) -> Dict[str, Any]:
        return self.runs.run_audit(user, run_id)

    def _agent_for(self, run_id: str) -> AgentConfig:
        return self.runs._agent_for(run_id)

    def resume_run(self, user: User, run_id: str, force: bool = False,
                   justification: Optional[str] = None) -> Dict[str, Any]:
        return self.runs.resume_run(user, run_id, force, justification)

    def list_reviews(self, user: User, status: Optional[str]) -> Dict[str, Any]:
        return self.reviews.list_reviews(user, status)

    def get_review(self, user: User, review_id: str) -> Dict[str, Any]:
        return self.reviews.get_review(user, review_id)

    def require_person(self, user: User, what: str) -> None:
        """A service identity (script, pipeline, integration) never records what only a person may (D11, F-02)."""
        if user.kind != "person":
            raise ApiError(403, f"{user.name} is a service identity: it cannot {what}; a signed-in person must")

    def decide(self, user: User, review_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.reviews.decide(user, review_id, body)

    def _live_changes(self, run_id: str, stored) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        return self.reviews._live_changes(run_id, stored)

    def _continue_after_review(self, cfg: AgentConfig, run_id: str, stored, decision, what: str) -> List[str]:
        return self.reviews._continue_after_review(cfg, run_id, stored, decision, what)

    def recover(self) -> List[Dict[str, Any]]:
        return self.runs.recover()

    # -- reconciliation of external calls (ACT-5) ----------------------------------------------
    def _call_visible(self, call: Dict[str, Any], user: User) -> bool:
        if "admin" in user.permissions:
            return True
        inst = self.graph._instances.get(call.get("root") or "")
        return inst is None or self.visible(inst, user)

    def _orphan(self, call: Dict[str, Any]) -> bool:
        """Was the call made by a run that was never saved (a crash, a failed save)?"""
        return not self.store._query("SELECT 1 FROM runs WHERE run_key=?", (call["run_key"],))

    def _has_effect(self, call: Dict[str, Any]) -> bool:
        action = self.ontology.actions.get(str(call.get("action") or "").partition("@")[0])
        return action is None or action.side_effect != "none"

    def list_reconciliation(self, user: User) -> Dict[str, Any]:
        """External calls a person must settle: outcome unknown, accepted but unconfirmed, or made by a run that
        was never saved."""
        if not ({"reconcile", "admin", "audit"} & user.permissions):
            raise ApiError(403, f"{user.name} lacks the 'reconcile' permission")
        rows = self.store.list_calls(["in_flight", "unknown", "pending_confirmation"])
        rows += [c for c in self.store.list_calls(["done"], orphans=True) if self._orphan(c) and self._has_effect(c)]
        items = []
        for c in rows:
            if not self._call_visible(c, user):
                continue
            item = {k: c.get(k) for k in ("key", "run_id", "root", "agent", "action", "tool", "attempt", "state",
                                          "detail", "created_at", "updated_at")}
            item["orphan"] = self._orphan(c)
            item["question"] = (f"Did {c['action']} via {c['tool']} happen? "
                                + ("The run that made it was never saved: check the record's data too."
                                   if item["orphan"] else "The run continues once you answer."))
            items.append(item)
        return {"items": items}

    def reconcile(self, user: User, key: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """A person settles one external call: it happened (with what the system returned) or it did not."""
        self.require(user, "reconcile")
        self.require_person(user, "settle an external call")
        call = self.store.get_call(key)
        if call is None or not self._call_visible(call, user):
            raise ApiError(404, f"no external call {key!r}")
        if not isinstance(body.get("done"), bool):
            raise ApiError(400, "done must be true (it happened) or false (it did not)")
        comment = str(body.get("comment") or "").strip()
        if len(comment) < 10:
            raise ApiError(400, "say how you checked (comment of at least 10 characters)")
        orphan = self._orphan(call)
        if call["state"] not in ("in_flight", "unknown", "pending_confirmation") and not (orphan and
                                                                                       call["state"] == "done"):
            raise ApiError(409, f"this call is {call['state'].replace('_', ' ')}: there is nothing to reconcile")
        if call.get("run_id") and self.store.run_starter(call["run_id"]) == user.name:
            raise ApiError(403, "you started this run: someone else must confirm what happened outside")
        fields: Dict[str, Any] = {}
        action = self.ontology.actions.get(str(call["action"]).partition("@")[0])
        if body["done"] and action is not None:
            outcome = body.get("outcome") or call.get("outcome")
            if outcome is not None and outcome not in [o.name for o in action.outcomes]:
                raise ApiError(400, f"unknown outcome {outcome!r}; {action.name} has {[o.name for o in action.outcomes]}")
            updates = body.get("updates") if body.get("updates") is not None else (call.get("updates") or {})
            if not isinstance(updates, dict):
                raise ApiError(400, "updates must be an object: Entity -> field -> value")
            for entity, changes in updates.items():
                for attr, value in (changes or {}).items():
                    ref = f"{entity}.{attr}"
                    if ref not in action.writes:
                        raise ApiError(400, f"{action.name} does not write {ref}")
                    declared = self.ontology.entities[entity].attributes.get(attr)
                    if declared is not None and not type_ok(declared.type, value):
                        raise ApiError(400, f"{ref} must be {declared.type}")
            missing = [ref for ref in (action.confirmation.fields if action.confirmation else ())
                       if (updates.get(ref.partition(".")[0]) or {}).get(ref.partition(".")[2]) in (None, "")]
            if missing:
                raise ApiError(400, f"to confirm {action.name}, give what the system returned: {', '.join(missing)}")
            fields = {"outcome": outcome, "updates": updates, "message": f"confirmed by {user.name}"}
        row = self.store.resolve_call(key, body["done"], user.name, comment, **fields)
        self._notify("reconciliation", [], f"{user.name} confirmed that {call['action']} "
                                           f"{'happened' if body['done'] else 'did not happen'} ({comment})",
                     {"key": key, "run_id": call.get("run_id"), "root": call.get("root")})
        out: Dict[str, Any] = {"call": {k: row.get(k) for k in ("key", "state", "resolved_by", "resolved_comment",
                                                               "run_id", "action")}}
        if orphan:
            out["note"] = ("the run that made this call was never saved: if it happened, update the record's data "
                           "(the run's other effects were not written back)")
        continued = [r for r in self.recover() if r["run_id"] == call.get("run_id")]
        if continued:
            out["run"] = continued[0]
        return out

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
            hidden = self._edit_hidden_field(scenario, edit, user)
            if hidden:  # what-if answers over a field you may not read would reveal it (audit GAP-012)
                raise ApiError(403, f"edit {i}: you may not read {hidden}, so you may not change it in a scenario")
            if edit.get("op") == "action":
                edit["roles"] = self._roles_for(user, edit)
                edit.pop("agent", None)
            try:
                scenario.apply(edit)
            except (OntologyError, KeyError, TypeError) as exc:
                raise ApiError(400, f"edit {i}: {exc}") from None

    def _edit_hidden_field(self, scenario, edit: Dict[str, Any], user: User) -> Optional[str]:
        attrs = edit.get("attributes")
        if edit.get("op") not in ("set", "add") or not isinstance(attrs, dict) or "admin" in user.permissions:
            return None
        if edit["op"] == "set":
            inst = scenario.graph._instances.get(str(edit.get("id")))
            if inst is None:
                return None  # the scenario reports the unknown object
            return next((f"{inst.type}.{a}" for a in sorted(attrs) if self.field_hidden(inst, a, user)), None)
        # a new record: refuse any field a data_access rule keeps from the user's roles
        entity = self.ontology.canonical(str(edit.get("type")))
        restricted = {r.params["field"] for r in self.ontology.rules_of("data_access")
                      if not user.roles & set(r.params["roles"])}
        return next((f"{entity}.{a}" for a in sorted(attrs) if f"{entity}.{a}" in restricted), None)

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
        return self.runs._visible_run(user, run_id)

    def record_outcome(self, user: User, run_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.runs.record_outcome(user, run_id, body)

    def list_outcomes(self, user: User, run_id: str) -> Dict[str, Any]:
        return self.runs.list_outcomes(user, run_id)

    def outcomes_summary(self, user: User) -> Dict[str, Any]:
        return self.runs.outcomes_summary(user)

    def list_agents(self, user: User) -> Dict[str, Any]:
        self.require(user, "read")
        items = {}
        for name, cfg in self.agents.items():
            reason = cfg.agent.governance.suspended.get(cfg.agent.principal.name)
            items[name] = {"goals": cfg.goals, "roles": sorted(cfg.agent.principal.roles),
                           "suspended": reason is not None, "reason": reason,
                           "model_discretion": cfg.agent.model_discretion,
                           "model_may_choose": sorted(cfg.agent.model_may_choose)}
        return {"items": items, "model_findings": list(self.model_findings)}

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
        report = self._redact_report(report, scenario, user)  # admins too: gated fields need a reason
        report["diff"] = self._scenario_view(sid, row, scenario, user)["diff"]
        return report

    def _redact_report(self, report: Dict[str, Any], scenario, user: User) -> Dict[str, Any]:
        """Remove what the caller may not see from a comparison: hidden ids, aggregates over hidden rows and
        every answer that reads a field the caller may not read or that needs a written reason first."""
        def seen(graph, iid):
            inst = graph._instances.get(iid)
            return inst is None or self.visible(inst, user)

        def answer(graph, value, qid):
            q = next(q for q in self.ontology.questions if q.id == qid)
            hidden = self._question_hidden_field(user, q, graph)
            if hidden:
                return f"withheld: depends on {hidden}, which you may not read"
            gated = self._question_gated_fields(q, graph)
            if gated:
                return (f"withheld: depends on {', '.join(gated)}, which needs a justification "
                        "(ask the question directly with your reason)")
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
        from .store import ABSENT, RecordConflict

        with self.graph_lock:
            try:  # one transaction over the revisions this process holds (GAP-018); live changes only after it
                written = scenario.commit(self.graph, self.store, expected={
                    iid: self.revisions.get(iid, ABSENT) for iid in list(scenario.diff()["added"])
                    + list(scenario.diff()["changed"])}, guard=lambda etype, iid, attrs: record_refusal(
                        self.ontology, self.graph, etype, iid, attrs, user.roles))
            except PermissionError as exc:
                raise ApiError(403, f"{exc}; nothing was committed") from None
            except ConflictError as exc:
                raise ApiError(409, str(exc)) from None
            except OntologyError as exc:
                raise ApiError(409, f"cannot commit: {exc}") from None
            except RecordConflict as exc:
                self._record_conflict(exc)
                raise ApiError(409, f"{exc}; nothing was committed", {"record": exc.iid, "tampered": exc.tampered}) \
                    from None
            self.revisions.update(self.store.instance_revisions(written))
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
def _too_many(wait: int, what: str) -> Dict[str, Any]:
    from .limits import too_many

    body = too_many(wait, what)
    return {"message": body["error"], "extra": {"retry_after_seconds": wait}}


def _engine_class(method: str, parts: List[str]) -> Optional[str]:
    from .limits import engine_class

    return engine_class(method, parts)


class ApiExchange:
    """One API request and its response, independent of how it arrived (HTTP server, workspace router, tests).

    Every entry point that speaks the REST API goes through this one dispatcher, so authentication, permissions,
    row and field rules and the access log are the same whichever server or router received the request.
    """

    def __init__(self, service: "AutologyService", method: str, path: str, headers: Any,
                 raw_body: Optional[bytes] = None, body_error: Optional[Tuple[int, str]] = None,
                 client: Optional[str] = None, counted: bool = False):
        self.service, self.command, self.path, self.headers = service, method, path, headers
        self.client = client or "-"  # the address the request is counted under (see autology.limits)
        self.counted = counted  # the router in front already counted this request for its identity and tenant
        self.raw_body, self.body_error = raw_body, body_error
        self.status, self.content_type, self.data = 500, "application/json", b""
        self.response_headers: Dict[str, str] = {}
        self._status, self._user = 500, None

    def _send(self, status: int, body: Any, content_type: str = "application/json") -> None:
        self.data = body if isinstance(body, bytes) else (
            body.encode() if isinstance(body, str) else json.dumps(body, default=str).encode())
        self.status = self._status = status
        self.content_type = content_type + ("; charset=utf-8" if "text" in content_type or "json" in content_type
                                            or "javascript" in content_type else "")
        self.response_headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
        if content_type == "text/html":
            self.response_headers["Content-Security-Policy"] = (
                "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")

    def _limit(self, name: str, key: str, what: str) -> None:
        wait = self.service.limiter.hit(name, key)
        if wait:
            raise ApiError(429, **_too_many(wait, what))

    def _body(self) -> Dict[str, Any]:
        if self.body_error:
            raise ApiError(*self.body_error)
        if not self.raw_body:
            return {}
        try:
            data = json.loads(self.raw_body)
        except ValueError:
            raise ApiError(400, "body must be JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "body must be a JSON object")
        return data

    def run(self) -> "ApiExchange":

        method, service = self.command, self.service
        url = urlparse(self.path)
        raw_path = url.path.rstrip("/") or "/"
        # API v1: /api/v1/... is served by the same handlers as /api/...; only the response envelope differs
        version = "1" if raw_path == "/api/v1" or raw_path.startswith("/api/v1/") else None
        path = "/api" + raw_path[len("/api/v1"):] if version else raw_path
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        self._status, self._user = 500, None
        try:
            self._dispatch(method, path, query)
        finally:
            if path.startswith("/api/") and path != "/api/health":
                try:  # every API request, including failed sign-ins, goes to the append-only log
                    service.log_access(self._user, "http", f"{method} {raw_path}", self._status)
                except Exception:  # logging must never break a response
                    log.exception("writing the access log failed")
        if path.startswith("/api"):
            self.data, extra = versioned_response(version, method, path, query, self.status, self.content_type,
                                                  self.data)
            self.response_headers.update(extra)
        return self

    def _dispatch(self, method: str, path: str, query: Dict[str, str]) -> None:
        service = self.service
        try:
            if method == "GET" and path in ("/", "/index.html", "/app.js", "/app.css"):
                name = {"/": "index.html"}.get(path, path.lstrip("/"))
                ctype = {"html": "text/html", "js": "application/javascript", "css": "text/css"}[name.rsplit(".")[-1]]
                if not (STATIC / name).is_file():  # a headless engine: the inbox is optional, the API is the product
                    raise ApiError(404, "the review inbox is not installed with this engine; use the API or the Console")
                return self._send(200, (STATIC / name).read_bytes(), ctype)
            limiter = service.limiter
            if path == "/api/health":
                self._limit("anonymous", self.client, "requests without a credential from this address")
                return self._send(200, service.health())
            if path == "/api/openapi.json" and method == "GET":  # the API contract (API-1): no data, no token
                from .openapi import spec

                self._limit("anonymous", self.client, "requests without a credential from this address")
                return self._send(200, spec())
            if not path.startswith("/api/"):
                raise ApiError(404, "not found")
            # an address that failed to authenticate too often is refused before its credential is looked at
            wait = limiter.blocked("auth_failures", self.client)
            if wait:
                raise ApiError(429, **_too_many(wait, "failed sign-ins from this address"))
            if path == "/api/auth/config" and method == "GET":  # what the inbox needs to offer SSO sign-in
                self._limit("anonymous", self.client, "requests without a credential from this address")
                return self._send(200, service.sso_config())
            try:
                if path == "/api/auth/token" and method == "POST":
                    self._limit("anonymous", self.client, "requests without a credential from this address")
                    return self._send(200, service.sso_token(self._body()))
                user = service.authenticate(self.headers.get("Authorization"))
            except ApiError as exc:
                if exc.status in (401, 403) and path != "/api/auth/config":
                    limiter.hit("auth_failures", self.client)
                raise
            self._user = user
            parts = path.split("/")[2:]
            # counted per identity whichever use case, version or entry point is used; then per tenant
            who = service.limit_scope + user.name
            if not self.counted:
                self._limit("api", who, f"requests by {user.name}")
                if service.tenant_key is not None:
                    self._limit("tenant", service.tenant_key, "requests of this tenant")
            extra_class = _engine_class(method, parts)
            if extra_class:
                self._limit(extra_class, who, {"mcp": "MCP messages", "admin": "administrative changes",
                                               "expensive": "requests that start work"}[extra_class]
                            + f" by {user.name}")
            limit, offset = page_window(query)
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
            if parts == ["model", "draft"]:  # model design (Studio): drafts never change what runs
                return self._send(200, service.model_draft(user) if method == "GET"
                                  else service.save_model_draft(user, body))
            if parts == ["model", "draft", "history"] and method == "GET":
                return self._send(200, service.model_draft_history(user))
            if parts == ["model", "validate"] and method == "POST":
                return self._send(200, service.validate_model(user, body))
            if parts == ["model", "draft", "simulate"] and method == "POST":
                return self._send(200, service.architect.simulate_draft(user, body))
            if parts == ["solution", "draft"] and method in ("GET", "POST"):
                return self._send(200, service.configuring.solution_draft(user) if method == "GET"
                                  else service.configuring.save_solution_draft(user, body))
            if parts == ["solution", "validate"] and method == "POST":
                return self._send(200, service.configuring.validate_solution(user, body))
            if parts == ["solution", "suggest"] and method == "POST":
                return self._send(200, service.configuring.suggest_solution(user, body))
            if parts == ["tools", "catalog"] and method == "GET":
                return self._send(200, service.configuring.tool_catalog(user))
            if parts == ["architect", "proposals"] and method in ("GET", "POST"):
                return self._send(200, service.architect_proposals(user, body) if method == "POST"
                                  else service.architect.list_proposals(user))
            if len(parts) == 3 and parts[:2] == ["architect", "proposals"] and method == "GET":
                revision = query.get("revision")
                if revision is not None and not str(revision).isdigit():
                    raise ApiError(400, "revision: a positive integer")
                return self._send(200, service.architect.get_proposal(user, parts[2],
                                                                      int(revision) if revision else None))
            if len(parts) == 4 and parts[:2] == ["architect", "proposals"] and parts[3] == "decision" \
                    and method == "POST":
                return self._send(200, service.architect.decide_proposal(user, parts[2], body))
            if key == ("POST", "mcp"):  # MCP over HTTP: the same tools, in this (the only writing) process
                answer = service.mcp_message(user, body)
                return self._send(202, b"") if answer is None else self._send(200, answer)
            if key in routes:
                return self._send(200, routes[key]())
            if method == "GET" and len(parts) == 2 and parts[0] == "sdk":
                from .sdk import GENERATORS

                service.require(user, "read")
                if parts[1] not in GENERATORS:
                    raise ApiError(404, f"no client for {parts[1]!r}; available: {sorted(GENERATORS)}")
                return self._send(200, GENERATORS[parts[1]](service.ontology), "text/plain")
            if parts == ["settings", "assistant"]:
                if method == "POST":
                    return self._send(200, service.update_assistant(user, body))
                return self._send(200, service.assistant_view(user))
            if parts == ["settings", "assistant", "test"] and method == "POST":
                return self._send(200, service.test_assistant(user))
            if method == "GET" and parts == ["metrics"]:
                return self._send(200, service.metrics(user), "text/plain; version=0.0.4")
            if method == "GET" and parts == ["report"]:
                return self._send(200, service.report(user), "text/markdown")
            if method == "GET" and parts == ["reconciliation"]:
                return self._send(200, service.list_reconciliation(user))
            if method == "POST" and len(parts) == 2 and parts[0] == "reconciliation":
                return self._send(200, service.reconcile(user, parts[1], self._body()))
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
                if method == "POST" and parts[2] == "write-back":
                    return self._send(200, service.retry_write_back(user, parts[1]))
                if method == "POST" and parts[2] == "cancel":
                    return self._send(200, service.runs.cancel_run(user, parts[1], body))
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
            if exc.status == 429:
                self.response_headers["Retry-After"] = str(exc.extra.get("retry_after_seconds", 1))
        except ValueError as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # never leak a traceback to clients; keep it in the server log
            service.log_error(f"{self.command} {urlparse(self.path).path}")
            self._send(500, {"error": f"internal error: {type(exc).__name__}"})


def read_body(headers: Any, rfile: Any, method: str) -> Tuple[Optional[bytes], Optional[Tuple[int, str]]]:
    """Read a request body safely: a valid, non-negative Content-Length of at most MAX_BODY, never "until EOF"."""
    if method != "POST":
        return None, None
    raw = headers.get("Content-Length")
    if raw is None:
        return b"", None
    if not raw.strip().isdigit():  # refuses negative and malformed lengths (rfile.read(-1) would read to EOF)
        return None, (411, "a valid Content-Length is required")
    length = int(raw)
    if length > MAX_BODY:
        return None, (413, "request body too large")
    return (rfile.read(length) if length else b""), None


def _handler(service: AutologyService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Autology"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet by default; plug in your own access log
            pass

        def _respond(self, method: str) -> None:
            from .limits import client_address

            raw, error = read_body(self.headers, self.rfile, method)
            client = client_address(self.client_address[0], self.headers.get("X-Forwarded-For"),
                                    service.trusted_proxies)
            ex = ApiExchange(service, method, self.path, self.headers, raw, error, client).run()
            self.send_response(ex.status)
            self.send_header("Content-Type", ex.content_type)
            self.send_header("Content-Length", str(len(ex.data)))
            for name, value in ex.response_headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(ex.data)

        def do_GET(self):  # noqa: N802
            self._respond("GET")

        def do_POST(self):  # noqa: N802
            self._respond("POST")

        def _not_allowed(self):  # a JSON answer, not the standard library's HTML 501 page
            data = json.dumps({"error": f"{self.command} is not supported"}).encode()
            self.send_response(405)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Allow", "GET, POST")
            self.end_headers()
            self.wfile.write(data)

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed  # noqa: N815

    return Handler


def make_server(service: AutologyService, host: str = "127.0.0.1", port: int = 8800) -> ThreadingHTTPServer:
    """The engine's HTTP server: at most ``security.server.max_connections`` requests at once, and a connection
    that sends or reads nothing for ``request_timeout_seconds`` is closed (GAP-030)."""
    from .limits import BoundedHTTPServer

    return BoundedHTTPServer((host, port), _handler(service), service.server_limits["max_connections"],
                             service.server_limits["request_timeout"])


def serve(config_path: str, host: str = "127.0.0.1", port: int = 8800,
          store: Optional[str] = None, assistant: Optional[str] = None) -> None:  # pragma: no cover - blocking
    import signal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    service = AutologyService.from_file(config_path, store, assistant)

    def stop_on_sigterm(signum, frame):  # `docker stop`, systemd, Kubernetes: shut down cleanly
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    server = make_server(service, host, port)
    stop = service.start_background()
    if service.chat is not None:
        print(f"Assistant: on ({getattr(service.chat.backend, 'model', 'custom backend')}); it signs in to Claude "
              "with ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile", flush=True)
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
        service.close()
        print("Autology stopped", flush=True)
