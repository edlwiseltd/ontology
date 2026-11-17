"""Workspaces: several isolated organisations, each with several use cases, behind one router.

    python -m autology platform platform.json [--host 127.0.0.1] [--port 8700]

A **workspace** is an organisation (a client, or any scope that must be isolated). It has **members** and
**use cases**. A **use case** (motor claims, order fulfilment, maintenance work orders...) is a complete engine:
its own ontology, agents, rules, data, runs, reviews, audit chain and settings.

**Isolation mode: a dedicated store per use case, enforced server-side.** Every use case runs on its own SQLite
store under ``<data_dir>/<workspace>/<use case>/``, and its Claude key file under ``<data_dir>/<workspace>/``. A
use case's engine only knows the members of its own workspace who were granted that use case, so even a request
that reached it directly with another workspace's token would be refused. The use case's own config cannot move
its store or secrets elsewhere, and company sign-in (``oidc``) is not used in this mode (identity is per workspace
member; see the planning documents).

**The router** resolves the caller's API token to exactly one workspace member (tokens are unique across the
platform) and serves only:

* ``GET /platform/health`` (no details);
* ``GET /platform/me``: the caller's workspace and the use cases they may open;
* ``/w/<workspace>/u/<use case>/api/...``: the use case's REST API, unchanged (the same dispatcher as a
  single-engine server, so every permission, rule and the use case's access log apply);
* use-case management and lifecycle stages (R2 slice, see :mod:`autology.lifecycle`):
  ``GET /platform/templates`` (workspace administrators: the operator's approved templates),
  ``GET|POST /platform/workspaces/<ws>/use-cases`` (list the use cases you may open; administrators create one
  from a template), ``GET /platform/workspaces/<ws>/use-cases/<uc>`` (detail and stage history),
  ``GET .../<uc>/checks?to=<stage>`` (the checks of a stage, evaluated now, nothing recorded) and
  ``POST .../<uc>/stage`` with ``{"to": stage, "reason": text}`` (administrators).

A workspace the caller is not a member of, a use case they were not granted, and one that does not exist all get
the same ``404 not found``: nobody learns what other workspaces exist. Refusals are written to the platform's own
append-only access log.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import unquote, urlsplit

from . import ai_policy, credentials, limits
from .audit import audit_key, workspace_key
from . import readiness
from .lifecycle import Check, Lifecycle, LifecycleError, STAGES
from .administration import AdminError, AdminLog, new_grant_id, pending_grants, pending_token_requests
from .releases import ReleaseError, ReleaseRegistry, fingerprint_of
from .server import ApiExchange, AutologyService, PERMISSIONS, hash_token, read_body
from .store import Store
from .tenancy import Tenancy, TenancyError

log = logging.getLogger("autology.platform")
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ADMINISTRATIVE = "configure"  # the engine permission an administrative role carries; never business data (IAM-3)
UNRESTRICTED = "admin"  # the engine permission that bypasses row and field rules on one use case's data
# What the engine's "admin" permission means, stated once (R2 security sprint B). It is never implied by an
# administrative role: it exists only as an explicit grant on one use case, acknowledged as unrestricted by the
# person who proposes it and by the other person who approves it.
UNRESTRICTED_MEANS = (
    "reads every record and every field of the use case: row rules (data_access) and field rules do not apply",
    "reads every run, review, notification and reconciliation item, whatever the roles involved",
    "starts and resumes runs with all of the agent's roles, and free-form cases outside simulation",
    "decides reviews whatever reviewer role they ask for (still never its own run's, never as a service identity)",
    "writes records directly, edits and commits any scenario, reinstates agents, runs the scheduler and reporting "
    "(a fact the model classifies decision-critical still changes only with the roles of its write rule)",
    "never reaches another use case, another workspace or another tenant; never changes members, grants, "
    "stages or releases (those are administrative roles, which in turn read no data)",
)
ONTOLOGY_OVERRIDE = "ontology.json"  # in <data_dir>/<ws>/<uc>/: this use case's own ontology (published or restored)
# beside it: the agents, simulated tools and sample records configured in Studio (published or restored with the
# model, never apart from it: one release covers both)
SOLUTION_OVERRIDE = "solution.json"
_KEEP = object()


def _is_document(value: Any) -> bool:
    """A model document as a release keeps it (an empty model has a name and nothing else yet)."""
    return isinstance(value, dict) and ("entities" in value or "name" in value)


def _put(path: Path, content: Any) -> None:
    """Write ``content`` (JSON-ready, or raw bytes) to ``path`` through a temporary file; ``None`` removes it."""
    if content is None:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_suffix(".tmp")
    if isinstance(content, bytes):
        tmp.write_bytes(content)
    else:
        tmp.write_text(json.dumps(content, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
NOT_FOUND = json.dumps({"error": "not found"}).encode()


_UNRESTRICTED_HELP = (
    'the "admin" permission is unrestricted access to this use case\'s business data: row and field rules do not '
    'apply to it. Grant narrower permissions where they are enough (read, run, review, audit, ingest, reconcile, '
    'with roles); to go ahead, send "unrestricted": true. The proposer and the approver each acknowledge it')


ANTHROPIC_API = "https://api.anthropic.com"  # the provider's own address: never taken from the environment


def _anthropic_adapter(policy: Dict[str, Any], key: Optional[str], http_client: Any = None) -> Any:
    """The adapter of one workspace: the SDK's client with that workspace's key and nothing else. The address is
    fixed here and the other credentials an SDK would pick up by itself (an environment variable, a signed-in
    profile) are switched off, so a key can only go to the provider it was issued by, and only this key goes."""
    import importlib

    from .ai import AnthropicProvider

    if not key:
        raise ValueError("no key")
    options = {"http_client": http_client} if http_client is not None else {}
    client = importlib.import_module("anthropic").Anthropic(api_key=key, auth_token=None, base_url=ANTHROPIC_API,
                                                            **options)
    client.auth_token = None  # an ANTHROPIC_AUTH_TOKEN in the environment is not this workspace's credential
    return AnthropicProvider(client)


# provider id -> adapter factory (policy, key). Having an adapter installed authorises nothing: a workspace reaches
# a provider only with an approved policy that the owner's authorisation covers (see _ai_standing). The adapter
# listed here was first run against its provider on 17 November 2026, on synthetic data, for one workspace.
PROVIDER_ADAPTERS: Dict[str, Any] = {"anthropic": _anthropic_adapter}


class PlatformError(ValueError):
    pass


SWAP_WAIT = 10.0  # seconds a request waits for an engine being switched, and a switch for requests in flight


class Busy(Exception):
    """An engine switch could not start (requests still in flight) or a request could not wait any longer."""


class Gate:
    """Who may touch one use case's engine: any number of requests together, or one switch of the engine alone.
    A switch (reload, publication, release activation) waits for the requests in flight, which finish on the
    configuration they started on; requests that arrive during a switch wait for it and then see the new engine,
    never something in between."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._shared = 0
        self._owner: Optional[int] = None
        self._depth = 0

    def enter(self, timeout: Optional[float] = None) -> bool:
        import time

        end = time.monotonic() + (SWAP_WAIT if timeout is None else timeout)
        with self._cond:
            if self._owner == threading.get_ident():  # the switching thread itself reads what it is building
                self._depth += 1
                return True
            while self._owner is not None:
                left = end - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
            self._shared += 1
            return True

    def leave(self) -> None:
        with self._cond:
            if self._owner == threading.get_ident():
                self._depth -= 1
            else:
                self._shared -= 1
            self._cond.notify_all()

    def acquire(self, timeout: Optional[float] = None) -> None:
        import time

        me, end = threading.get_ident(), time.monotonic() + (SWAP_WAIT if timeout is None else timeout)
        with self._cond:
            if self._owner == me:
                self._depth += 1
                return
            while self._owner is not None:
                left = end - time.monotonic()
                if left <= 0:
                    raise Busy()
                self._cond.wait(left)
            self._owner, self._depth = me, 1  # from now on, new requests wait
            while self._shared:
                left = end - time.monotonic()
                if left <= 0:
                    self._owner, self._depth = None, 0
                    self._cond.notify_all()
                    raise Busy()
                self._cond.wait(left)

    def release(self) -> None:
        with self._cond:
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
            self._cond.notify_all()


@dataclass
class Member:
    name: str
    workspace: str
    token_sha256: str
    workspace_admin: bool = False
    use_cases: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # use case -> permissions/roles/reviewer roles
    kind: str = "person"  # or "service": a machine identity never records a human approval (D11, F-02)
    tenant: str = ""  # the tenant the identity belongs to (IAM-1): it reaches no other tenant's workspaces
    tenant_admin: bool = False  # administers every workspace of the tenant (an administrative role, IAM-1)
    scope: str = "workspace"  # where the identity is defined: "workspace" (one workspace) or "tenant"
    token_expires: Optional[float] = None  # an explicit, earlier expiry given in the configuration (GAP-030)
    expires_at: Optional[float] = None  # when the token stops working: lifetime from first sight, or token_expires

    def grant(self, use_case: str) -> Optional[Dict[str, Any]]:
        """What the member may do in one use case's engine. An administrator (of the workspace or of the tenant)
        gets the administrative permission only (IAM-3, D22a): ``configure`` reads no business record, run,
        review or audit entry. Business data needs an explicit grant, like for anyone else; an administrative role
        never bypasses row, field, workspace or use-case authorisation."""
        explicit = self.use_cases.get(use_case)
        if not self.workspace_admin:
            return explicit
        if explicit is None:
            return {"permissions": [ADMINISTRATIVE], "roles": [], "reviewer_roles": []}
        return {**explicit, "permissions": sorted(set(explicit["permissions"]) | {ADMINISTRATIVE})}

    def has_data_access(self, use_case: str) -> bool:
        return bool(set((self.grant(use_case) or {}).get("permissions", [])) - {ADMINISTRATIVE})


@dataclass
class UseCase:
    id: str
    workspace: str
    name: str
    service: AutologyService
    origin: str = "configuration"  # "configuration" (platform.json) or "template" (created through the API)
    template: Optional[str] = None
    spec: Dict[str, Any] = field(default_factory=dict)  # how it was loaded (its config file), for a reload (ADM-2)
    stop: Optional[threading.Event] = None  # its scheduler, while the platform runs in the background
    # set when a switch failed and even the previous configuration could not be loaded again: nothing is served
    unavailable: Optional[str] = None


@dataclass
class TenantMember:
    """An identity defined for the whole tenant: a tenant administrator, or a person or service with explicit
    memberships in some of the tenant's workspaces. Belonging to a tenant gives no workspace access by itself."""

    name: str
    token_sha256: str
    kind: str = "person"
    tenant_admin: bool = False
    workspaces: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # workspace -> {workspace_admin, use_cases}
    token_expires: Optional[float] = None


@dataclass
class Tenant:
    """One customer organisation: it owns workspaces; identities and data never cross to another tenant (IAM-1)."""

    id: str
    name: str
    workspaces: List[str] = field(default_factory=list)
    members: Dict[str, TenantMember] = field(default_factory=dict)
    dedicated: bool = False  # the tenant of a single workspace that was not grouped with others


@dataclass
class Workspace:
    id: str
    name: str
    tenant: str = ""
    members: Dict[str, Member] = field(default_factory=dict)
    use_cases: Dict[str, UseCase] = field(default_factory=dict)
    oidc: Optional[Dict[str, Any]] = None  # the workspace's own company sign-in (ISO-3)
    env_prefix: str = ""  # the only environment variables (credentials) its configuration may name (ISO-4)
    # members who may approve releases besides the workspace administrators, e.g. a designated external approver
    # for a workspace with one administrator (D11); never the proposer, never a service identity
    release_approvers: Tuple[str, ...] = ()
    config_members: Dict[str, Member] = field(default_factory=dict)  # platform.json's members, before the admin log
    # where each data grant comes from, who approved it and whether a person reviewed it: (member, use case) -> record
    grant_records: Dict[Tuple[str, str], Dict[str, Any]] = field(default_factory=dict)
    token_issuers: Dict[str, str] = field(default_factory=dict)  # member -> who issued the token they hold now
    gates: Dict[str, Gate] = field(default_factory=dict)  # use case id -> who may touch its engine now
    admin_problem: Optional[str] = None  # the administration log does not verify: only configured admins remain


def _copy_member(m: Member) -> Member:
    return Member(m.name, m.workspace, m.token_sha256, m.workspace_admin, json.loads(json.dumps(m.use_cases)), m.kind,
                  m.tenant, m.tenant_admin, m.scope, m.token_expires, m.expires_at)


def _explicit_expiry(spec: Dict[str, Any], where: str) -> Optional[float]:
    if spec.get("token_expires") is None:
        return None
    try:
        return credentials.parse_time(spec["token_expires"], where)
    except credentials.CredentialError as exc:
        raise PlatformError(str(exc)) from None


def _grants(spec: Any, where: str) -> Dict[str, Dict[str, Any]]:
    grants: Dict[str, Dict[str, Any]] = {}
    for uc, g in (spec or {}).items():
        perms = set(g.get("permissions") or [])
        if perms - PERMISSIONS:
            raise PlatformError(f"{where}: unknown permissions {sorted(perms - PERMISSIONS)}")
        grants[uc] = {"permissions": sorted(perms), "roles": list(g.get("roles") or []),
                      "reviewer_roles": list(g.get("reviewer_roles") or []),
                      "run_as": {a: list(r) for a, r in (g.get("run_as") or {}).items()}}
    return grants


def _token_digest(spec: Dict[str, Any], where: str) -> str:
    if spec.get("token_env"):
        token = os.environ.get(spec["token_env"])
        if not token:
            raise PlatformError(f"{where}: environment variable {spec['token_env']} is not set")
        return hash_token(token)
    digest = str(spec.get("token_sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PlatformError(f"{where}: give token_env or a SHA-256 token_sha256")
    return digest


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _env_references(value: Any, base: Path, seen: Optional[set] = None) -> set:
    """Every environment variable a configuration names: ``${VAR}`` in strings, ``*_env`` keys, ``{"env": VAR}``,
    following the JSON files it references (tools, pipelines, approvers)."""
    seen = set() if seen is None else seen
    found: set = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and (key == "env" or key.endswith("_env")):
                found.add(item)
            found |= _env_references(item, base, seen)
    elif isinstance(value, list):
        for item in value:
            found |= _env_references(item, base, seen)
    elif isinstance(value, str):
        found |= set(_ENV_REF.findall(value))
        if value.endswith(".json"):
            path = (base / value).resolve()
            if path.is_file() and path not in seen:
                seen.add(path)
                try:
                    found |= _env_references(json.loads(path.read_text(encoding="utf-8")), path.parent, seen)
                except ValueError:
                    pass  # not a configuration file; the engine reports real errors when it loads it
    return found


class Platform:
    def __init__(self, spec: Dict[str, Any], base_dir: Path):
        base_dir = Path(base_dir).resolve()
        self.data_dir = (base_dir / spec.get("data_dir", "data")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log = Store(self.data_dir / "platform.db")  # the platform's own append-only access log
        # stages and created use cases, chained with each workspace's derived audit key
        self.lifecycle = Lifecycle(self.data_dir / "lifecycle.db", lambda ws: workspace_key(audit_key(), ws))
        # immutable releases of each use case's governing configuration (REL-1a), chained the same way
        self.releases = ReleaseRegistry(self.data_dir / "releases.db", lambda ws: workspace_key(audit_key(), ws))
        # members and grants changed through the API (ADM-1), replayed over platform.json, chained the same way
        self.admin = AdminLog(self.data_dir / "admin.db", lambda ws: workspace_key(audit_key(), ws))
        # GAP-030: token lifetimes (first sight of every token, revocations), rate limits, server limits
        security = spec.get("security") or {}
        if not isinstance(security, dict) or set(security) - {"tokens", "rate_limits", "trusted_proxies", "server",
                                                               "run_seconds"}:
            raise PlatformError("security: tokens, rate_limits, trusted_proxies, server and run_seconds only")
        try:
            self.token_policy = credentials.TokenPolicy.parse(security.get("tokens"))
            self.limiter = limits.RateLimiter.parse(security.get("rate_limits"))
            self.trusted_proxies = limits.parse_proxies(security.get("trusted_proxies"))
            self.server_limits = limits.parse_server(security.get("server"))
            self.credentials = credentials.CredentialRegistry(
                self.data_dir / "credentials.db", workspace_key(audit_key(), "platform:credentials"))
        except (credentials.CredentialError, limits.LimitError) as exc:
            raise PlatformError(str(exc)) from None
        self._security = {k: security[k] for k in ("run_seconds",) if k in security}
        # the owner's authorisations to reach a real AI provider (decisions D7, D10): deployment configuration,
        # never settable through the API. None is the normal state: only the sandbox test double answers then
        try:
            self.ai_authorisations = ai_policy.validate_authorisations(spec.get("ai_authorisations"),
                                                                       spec.get("workspaces") or {})
        except ValueError as exc:
            raise PlatformError(str(exc)) from None
        self.ai_ledger = ai_policy.SpendLedger(self.data_dir / "ai_ledger.db")
        self.workspaces: Dict[str, Workspace] = {}
        self.tenants: Dict[str, Tenant] = {}
        # token digest -> {workspace: Member}: one identity, with one Member per workspace it explicitly belongs to
        self._tokens: Dict[str, Dict[str, Member]] = {}
        self._identities: Dict[str, Tuple[str, str]] = {}  # token digest -> (tenant, name): one identity, one tenant
        self._base_dir = base_dir
        self._lock = threading.RLock()
        self._drilling = threading.Lock()  # one recovery rehearsal at a time
        self._stops: List[threading.Event] = []
        self.running = False
        # templates: configurations the operator approved; a workspace administrator may create use cases from
        # them, never from a configuration of their own (it could name another workspace's files or credentials)
        self.templates: Dict[str, Dict[str, Any]] = {}
        for t_id, t in (spec.get("templates") or {}).items():
            if not ID.match(t_id) or not isinstance(t, dict) or not t.get("config"):
                raise PlatformError(f"template {t_id!r}: an id of lowercase letters, digits and '-' and a config")
            if not (base_dir / t["config"]).resolve().is_file():
                raise PlatformError(f"template {t_id}: configuration file {t['config']} not found")
            self.templates[t_id] = {"id": t_id, "name": str(t.get("name") or t_id),
                                    "description": str(t.get("description") or ""), "config": t["config"]}
        workspace_specs = spec.get("workspaces") or {}
        if not workspace_specs:
            raise PlatformError("the platform has no workspaces")
        for ws_id in workspace_specs:
            if not ID.match(ws_id):
                raise PlatformError(f"workspace id {ws_id!r}: lowercase letters, digits and '-' only")
        self._load_tenants(spec.get("tenants") or {}, workspace_specs)
        # which tenant owns each workspace is a record, not only configuration (IAM-1): existing workspaces go to
        # their own dedicated tenant, and the configuration can never merge or split tenants by itself
        existing = {ws_id for ws_id in workspace_specs if (self.data_dir / ws_id).is_dir()
                    and any((self.data_dir / ws_id).iterdir())}
        self._existing = existing  # workspaces that had data before this start (migrations: IAM-1, IAM-3)
        try:
            self.tenancy = Tenancy(self.data_dir / "tenancy.db", workspace_key(audit_key(), "platform:tenancy"))
            self.tenancy.reconcile({ws_id: self._tenant_of[ws_id] for ws_id in workspace_specs}, existing)
        except TenancyError as exc:
            raise PlatformError(str(exc)) from None
        for ws_id, ws_spec in workspace_specs.items():
            self._load_workspace(ws_id, ws_spec, base_dir)

    def _load_tenants(self, specs: Dict[str, Any], workspace_specs: Dict[str, Any]) -> None:
        """``tenants`` in the configuration: each names its workspaces and its tenant-level members. A workspace no
        tenant lists is the single workspace of a dedicated tenant with its own id (how every workspace was before
        tenants existed)."""
        self._tenant_of: Dict[str, str] = {}
        for t_id, t in specs.items():
            if not ID.match(t_id) or not isinstance(t, dict):
                raise PlatformError(f"tenant id {t_id!r}: lowercase letters, digits and '-' only")
            listed = t.get("workspaces") or []
            if not isinstance(listed, list) or not listed:
                raise PlatformError(f"tenant {t_id}: workspaces must list at least one workspace")
            for ws_id in listed:
                if ws_id not in workspace_specs:
                    raise PlatformError(f"tenant {t_id}: unknown workspace {ws_id!r}")
                if ws_id in self._tenant_of:
                    raise PlatformError(f"workspace {ws_id} is listed by tenants {self._tenant_of[ws_id]} and {t_id}: "
                                        "a workspace belongs to exactly one tenant")
                self._tenant_of[ws_id] = t_id
            self.tenants[t_id] = Tenant(t_id, str(t.get("name") or t_id), list(listed))
        for ws_id, ws_spec in workspace_specs.items():
            if ws_id in self._tenant_of:
                continue
            if ws_id in self.tenants:  # a tenant with this id exists and does not list this workspace
                raise PlatformError(f"workspace {ws_id} is not listed by any tenant, and tenant {ws_id!r} does not "
                                    "list it: its dedicated tenant would have the same id. List it, or rename one")
            self._tenant_of[ws_id] = ws_id
            self.tenants[ws_id] = Tenant(ws_id, str(ws_spec.get("name") or ws_id), [ws_id], dedicated=True)
        for t_id, t in specs.items():
            tenant = self.tenants[t_id]
            for i, m in enumerate(t.get("members") or []):
                where = f"tenant {t_id} member {m.get('name', i)}"
                name = str(m.get("name") or "")
                if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", name) or name in tenant.members:
                    raise PlatformError(f"{where}: a unique name of letters, digits and _.@- is required")
                kind = m.get("kind", "person")
                if kind not in ("person", "service"):
                    raise PlatformError(f"{where}: kind must be \"person\" or \"service\"")
                tenant_admin = bool(m.get("tenant_admin"))
                if tenant_admin and kind != "person":
                    raise PlatformError(f"{where}: a tenant administrator must be a person, not a service identity")
                memberships: Dict[str, Dict[str, Any]] = {}
                for ws_id, ms in (m.get("workspaces") or {}).items():
                    if ws_id not in tenant.workspaces:  # membership is explicit and never leaves the tenant
                        raise PlatformError(f"{where}: {ws_id!r} is not a workspace of tenant {t_id}")
                    memberships[ws_id] = {"workspace_admin": bool((ms or {}).get("workspace_admin")),
                                          "use_cases": _grants((ms or {}).get("use_cases"), where)}
                if not tenant_admin and not memberships:
                    raise PlatformError(f"{where}: give tenant_admin, or at least one workspace membership "
                                        "(belonging to a tenant gives no access by itself)")
                digest = _token_digest(m, where)
                self._claim_token(digest, t_id, name, where)
                tenant.members[name] = TenantMember(name, digest, kind, tenant_admin, memberships,
                                                    _explicit_expiry(m, where))

    def _claim_token(self, digest: str, tenant: str, name: str, where: str) -> None:
        """A token identifies exactly one identity of exactly one tenant: no identity is shared across tenants."""
        owner = self._identities.setdefault(digest, (tenant, name))
        if owner != (tenant, name):
            raise PlatformError(f"{where}: this token is already used by another member")

    @classmethod
    def from_file(cls, path: str) -> "Platform":
        p = Path(path).resolve()
        return cls(json.loads(p.read_text(encoding="utf-8")), p.parent)

    def _load_workspace(self, ws_id: str, spec: Dict[str, Any], base_dir: Path) -> None:
        tenant = self.tenants[self._tenant_of[ws_id]]
        ws = Workspace(ws_id, str(spec.get("name") or ws_id), tenant=tenant.id,
                       oidc=dict(spec["oidc"]) if spec.get("oidc") else None,
                       env_prefix=str(spec.get("env_prefix") or ws_id.upper().replace("-", "_") + "_"))
        # A workspace-level member is an identity of that workspace only (``name@workspace``), exactly as before
        # tenants existed: two workspaces of one tenant may each have their own "hana", two different people who
        # are never merged. A tenant-level name is unique in the tenant, so it can never be confused with them.
        taken = set(tenant.members)
        for i, m in enumerate(spec.get("members") or []):
            where = f"workspace {ws_id} member {m.get('name', i)}"
            name = str(m.get("name") or "")
            if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", name) or name in ws.members:
                raise PlatformError(f"{where}: a unique name of letters, digits and _.@- is required")
            if name in taken:
                raise PlatformError(f"{where}: {name} is also a tenant-level member of tenant {tenant.id}; one name "
                                    "is one person: keep the tenant-level definition, with explicit memberships")
            digest = _token_digest(m, where)
            if digest in self._identities:  # a token must identify exactly one person in exactly one workspace
                raise PlatformError(f"{where}: this token is already used by another member")
            self._claim_token(digest, tenant.id, f"{name}@{ws_id}", where)
            grants = _grants(m.get("use_cases"), where)
            kind = m.get("kind", "person")
            if kind not in ("person", "service"):
                raise PlatformError(f"{where}: kind must be \"person\" or \"service\"")
            ws.members[name] = Member(name, ws_id, digest, bool(m.get("workspace_admin")), grants, kind, tenant.id,
                                      token_expires=_explicit_expiry(m, where))
        for tm in tenant.members.values():  # tenant-level identities: only where they explicitly belong
            membership = tm.workspaces.get(ws_id)
            if tm.tenant_admin or membership is not None:
                membership = membership or {"workspace_admin": False, "use_cases": {}}
                ws.members[tm.name] = Member(
                    tm.name, ws_id, tm.token_sha256, tm.tenant_admin or membership["workspace_admin"],
                    json.loads(json.dumps(membership["use_cases"])), tm.kind, tenant.id, tm.tenant_admin, "tenant",
                    tm.token_expires)
        for member in ws.members.values():
            unknown = set(member.use_cases) - set(spec.get("use_cases") or {}) - {
                r["id"] for r in self.lifecycle.created(ws_id)}
            if unknown:
                raise PlatformError(f"workspace {ws_id} member {member.name}: unknown use cases {sorted(unknown)}")
        ws.config_members = {n: _copy_member(m) for n, m in ws.members.items()}
        self._separate_privileges(ws, spec)  # IAM-3 migration, once per workspace, before the log is replayed
        self._replay(ws)  # the administration log over the configuration (ADM-1), before any engine is built
        for uc_id, uc_spec in (spec.get("use_cases") or {}).items():
            if not ID.match(uc_id):
                raise PlatformError(f"use case id {uc_id!r}: lowercase letters, digits and '-' only")
            ws.use_cases[uc_id] = self._load_use_case(ws, uc_id, uc_spec, base_dir)
        approvers = spec.get("release_approvers") or []
        if not isinstance(approvers, list) or any(a not in ws.config_members for a in approvers):
            raise PlatformError(f"workspace {ws_id}: release_approvers must name members of the workspace")
        if any(ws.config_members[a].kind != "person" for a in approvers):
            raise PlatformError(f"workspace {ws_id}: a release approver must be a person, not a service identity")
        ws.release_approvers = tuple(approvers)
        for row in self.lifecycle.created(ws_id):  # use cases created through the API come back after a restart
            if row["id"] in ws.use_cases:
                raise PlatformError(f"workspace {ws_id}: use case {row['id']} is both configured and created")
            if row["template"] not in self.templates:
                raise PlatformError(f"workspace {ws_id} use case {row['id']}: its template {row['template']} "
                                    "is no longer in the platform configuration")
            uc = self._load_use_case(ws, row["id"], {"name": row["name"],
                                                     "config": self.templates[row["template"]]["config"]}, base_dir)
            uc.origin, uc.template = "template", row["template"]
            ws.use_cases[row["id"]] = uc
        self.workspaces[ws_id] = ws
        self._rebuild_tokens()

    def _separate_privileges(self, ws: Workspace, spec: Dict[str, Any]) -> None:
        """IAM-3 migration, once per workspace (recorded in its administration log). Administrators no longer get
        business-data access from their role. So that an upgrade takes nothing away silently, the access each
        administrator of an **existing** workspace had implicitly becomes an explicit grant per use case: visible
        in the members view, revocable like any other, and never given again automatically (not to new
        administrators, new workspaces or new use cases)."""
        events, problem = self.admin.events(ws.id)
        if problem or any(e["event"] == "privileges_separated" for e in events):
            return  # a log that does not verify fails closed: administrators keep the administrative role only
        batch: List[Tuple[str, str, str, Dict[str, Any]]] = []
        if ws.id in self._existing:
            use_cases = list(spec.get("use_cases") or {}) + [r["id"] for r in self.lifecycle.created(ws.id)]
            for m in ws.config_members.values():
                if m.workspace_admin and m.scope == "workspace":
                    for uc_id in use_cases:
                        batch.append(("grant_migrated", "autology",
                                      "IAM-3 migration: the data access this administrator had from the role is now "
                                      "an explicit grant; revoke it if it is not needed",
                                      {"member": m.name, "use_case": uc_id, "grant": {
                                          "permissions": ["admin"], "roles": [], "reviewer_roles": [], "run_as": {}}}))
        batch.append(("privileges_separated", "autology",
                      "administrative roles no longer carry business-data access (IAM-3, D22a)",
                      {"existing_workspace": ws.id in self._existing, "grants_migrated": len(batch)}))
        self.admin.append_batch(ws.id, batch)

    # -- membership: platform.json plus the administration log (ADM-1, ADM-2) --------------------------------------
    def _replay(self, ws: Workspace) -> None:
        events, problem = self.admin.events(ws.id)
        ws.admin_problem = problem
        members = {n: _copy_member(m) for n, m in ws.config_members.items()}
        records: Dict[Tuple[str, str], Dict[str, Any]] = {
            (m.name, uc): {"origin": "configuration", "by": "configuration", "approved_by": None, "at": None,
                           "acknowledged": False, "review": None}
            for m in members.values() for uc in m.use_cases}
        issuers = {n: "configuration" for n in members}
        if problem:  # fail closed: only the configured administrators keep access until an operator repairs it
            ws.members = {n: m for n, m in members.items() if m.workspace_admin}
            ws.grant_records = {k: v for k, v in records.items() if k[0] in ws.members}
            ws.token_issuers = {n: v for n, v in issuers.items() if n in ws.members}
            self._stamp(ws.members.values())
            return
        proposals: Dict[str, Dict[str, Any]] = {}
        for e in events:
            d = e["data"]
            if e["event"] == "member_added":
                members[d["name"]] = Member(d["name"], ws.id, d["token_sha256"], False, {}, d["kind"], ws.tenant)
                issuers[d["name"]] = e["by"]
            elif e["event"] == "member_removed":
                members.pop(d["name"], None)
                issuers.pop(d["name"], None)
                records = {k: v for k, v in records.items() if k[0] != d["name"]}
                # proposals made for a removed member end with them: a later namesake never inherits one
                proposals = {k: v for k, v in proposals.items() if v["member"] != d["name"]}
            elif e["event"] == "token_rotated" and d["name"] in members:
                members[d["name"]].token_sha256 = d["token_sha256"]
                members[d["name"]].token_expires = None  # an explicit date was about the configured token
                issuers[d["name"]] = "self" if e["by"] == f"{d['name']}@{ws.id}" else e["by"]
            elif e["event"] == "token_revoked" and d["name"] in members:
                members[d["name"]].token_sha256 = ""  # no credential until an administrator issues a new one
            elif e["event"] == "grant_proposed":
                proposals[d["id"]] = {**d, "proposed_by": e["by"]}
            elif e["event"] == "grant_approved":
                p = proposals.pop(d["id"], None)
                if p and p["member"] in members:
                    members[p["member"]].use_cases[p["use_case"]] = p["grant"]
                    records[(p["member"], p["use_case"])] = {
                        "origin": "grant", "by": p["proposed_by"], "approved_by": e["by"], "at": e["at"],
                        "acknowledged": bool(p.get("unrestricted") and d.get("unrestricted")), "review": None}
            elif e["event"] == "grant_withdrawn":
                proposals.pop(d["id"], None)
            elif e["event"] == "grant_migrated" and d["member"] in members:
                have = members[d["member"]].use_cases.get(d["use_case"])
                members[d["member"]].use_cases[d["use_case"]] = d["grant"] if have is None else {
                    **have, "permissions": sorted(set(have["permissions"]) | set(d["grant"]["permissions"]))}
                records[(d["member"], d["use_case"])] = {"origin": "migration", "by": e["by"], "approved_by": None,
                                                         "at": e["at"], "acknowledged": False, "review": None}
            elif e["event"] == "grant_revoked" and d["member"] in members:
                members[d["member"]].use_cases.pop(d["use_case"], None)
                records.pop((d["member"], d["use_case"]), None)
            elif e["event"] == "grant_confirmed":
                rec = records.get((d["member"], d["use_case"]))
                have = members[d["member"]].use_cases.get(d["use_case"]) if d["member"] in members else None
                # a review is about the grant as it was: if the grant changed since, it does not carry over
                if rec is not None and have is not None and sorted(have["permissions"]) == sorted(d["permissions"]):
                    rec["review"] = {"by": e["by"], "at": e["at"], "reason": e["reason"]}
        self._stamp(members.values())
        ws.members = members
        ws.grant_records = {k: v for k, v in records.items() if k[0] in members and k[1] in members[k[0]].use_cases}
        ws.token_issuers = issuers

    def _stamp(self, members: Any) -> None:
        """Give each member's token its expiry: the policy's lifetime for its kind, counted from the first time
        the token was seen (recorded once in the credential registry), or an earlier explicit date. A token that
        existed before lifetimes were enforced is first seen at the upgrade: one full lifetime, not for ever."""
        for m in members:
            if not m.token_sha256:
                m.expires_at = None
                continue
            identity = f"{m.name}@{m.workspace}" if m.scope == "workspace" else f"{m.name}@tenant:{m.tenant}"
            seen = self.credentials.register(m.token_sha256, identity, m.kind)
            m.expires_at = credentials.expires_at(seen, m.kind, self.token_policy, m.token_expires)

    def _rebuild_tokens(self) -> None:
        tokens: Dict[str, Dict[str, Member]] = {}
        for ws in self.workspaces.values():
            for m in ws.members.values():
                if m.token_sha256:  # a member whose token was revoked has no credential
                    tokens.setdefault(m.token_sha256, {})[ws.id] = m
        self._tokens = tokens

    def users_for(self, ws: Workspace, uc_id: str) -> List[Dict[str, Any]]:
        users = []
        for member in ws.members.values():
            grant = member.grant(uc_id)
            if grant and member.token_sha256:
                users.append({"name": member.name, "token_sha256": member.token_sha256, "kind": member.kind,
                              "token_expires_at": member.expires_at, **grant})
        return users

    def _refresh(self, ws: Workspace) -> None:
        """Apply the administration log now: tokens and every engine's users change before the next request."""
        with self._lock:
            self._replay(ws)
            self._rebuild_tokens()
            for uc in ws.use_cases.values():
                uc.service.set_users(self.users_for(ws, uc.id))

    def _load_use_case(self, ws: Workspace, uc_id: str, spec: Dict[str, Any], base_dir: Path,
                       validate_only: bool = False, candidate: Optional[Path] = None) -> UseCase:
        config_path = (base_dir / spec["config"]).resolve()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        # integration credentials are environment variables of the platform process: a use case may name only its
        # own workspace's (ISO-4), so one workspace's configuration can never pick up another's secrets
        foreign = sorted(v for v in _env_references({k: v for k, v in config.items() if k != "users"},
                                                    config_path.parent) if not v.startswith(ws.env_prefix))
        if foreign:
            raise PlatformError(f"workspace {ws.id} use case {uc_id}: its configuration names environment variables "
                                f"outside the workspace's prefix {ws.env_prefix!r}: {', '.join(foreign)}")
        home = self.data_dir / ws.id / uc_id
        home.mkdir(parents=True, exist_ok=True)
        # the platform decides where the data lives and who the users are, never the use case's own config
        config["store"] = str(home / "autology.db")
        # where this use case's own model and agent configuration are read from: its data folder, or, for a
        # configuration that is not in place (a draft, a release's snapshot: see _probing), another folder
        own = candidate if candidate is not None else home
        override = own / ONTOLOGY_OVERRIDE
        if override.is_file():  # a Studio draft published to this use case, or a release's ontology restored
            config["ontology"] = str(override)
        managed = own / SOLUTION_OVERRIDE
        if managed.is_file():  # its agents and simulated tools, published or restored the same way
            self._apply_solution(config, config_path.parent, managed, f"workspace {ws.id} use case {uc_id}")
        config.pop("oidc", None)  # a use case's own sign-in setting never applies: the workspace's does
        if ws.oidc:
            config["oidc"] = dict(ws.oidc)
        config.pop("log_file", None)
        reporting = config.get("reporting")
        if isinstance(reporting, dict) and isinstance(reporting.get("target"), str):
            reporting["target"] = str(home / "reporting.db")
        config["secrets_file"] = str(self.data_dir / ws.id / "secrets.json")
        config["audit_scope"] = ws.id  # the workspace's own audit key, derived from the platform's (ISO-2)
        config["users"] = self.users_for(ws, uc_id)
        if not validate_only:  # a throwaway engine never reaches a provider: it gets no grant at all
            config["ai_grant"] = self._ai_grant(ws, uc_id)
        elif isinstance(config.get("ai"), dict) and config["ai"].get("provider") != "sandbox":
            config["ai_grant"] = {"refused": "a throwaway engine reaches no provider"}
        config["credentials_file"] = ""  # the platform supplies each token's expiry (one registry for all engines)
        config["security"] = dict(self._security)
        if validate_only:  # build a throwaway engine on an in-memory store: proves the files load, touches nothing
            config.update({"store": ":memory:", "secrets_file": str(home / ".validate-secrets.json")})
            probe = AutologyService(config, config_path.parent)
            if candidate is not None:
                return probe  # type: ignore[return-value]  # the caller reads it, then closes it (_probing)
            fingerprint = probe.configuration_fingerprint
            probe.close()
            return fingerprint  # type: ignore[return-value]
        service = AutologyService(config, config_path.parent)
        # one limiter for the whole platform: an identity is counted once per workspace, whatever the use case,
        # and every request of the tenant under the tenant (GAP-030)
        service.limiter, service.limit_scope, service.tenant_key = self.limiter, f"{ws.id}:", ws.tenant
        service.credentials = self.credentials  # revocations reach the engine too (never closed by the engine)
        uc = UseCase(uc_id, ws.id, str(spec.get("name") or uc_id), service, spec=dict(spec))
        service.stage_gate = lambda: self.effective_stage_and_reason(uc)  # execution gates: the stage governs every run
        gate = ws.gates.setdefault(uc_id, Gate())
        service.background_guard = (gate.enter, gate.leave)  # the scheduler never ticks while the engine is switched
        return uc

    # -- AI provider governance (autology.ai_policy) ------------------------------------------------------
    def _ai_policy(self, ws: Workspace) -> Tuple[Optional[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        from .administration import ai_policy_state

        events, problem = self.admin.events(ws.id)
        return (None, {}) if problem else ai_policy_state(events)

    def _ai_standing(self, ws: Workspace) -> Dict[str, Any]:
        """Where the workspace stands: no policy, a policy that may be served, or one that may not and why."""
        current, pending = self._ai_policy(ws)
        if current is None:
            return {"state": "none", "reason": "no AI provider policy is approved for this workspace",
                    "policy": None, "authorisation": None, "current": None, "pending": pending}
        policy = current["policy"]
        expires = ai_policy._parse_date(policy["expires"]) if policy.get("expires") else None
        authorisation, reason = ai_policy.authorisation_for(policy, ws.id, self.ai_authorisations)
        state = "sandbox" if policy["provider"] in ai_policy.NO_AUTHORISATION_NEEDED else "authorised"
        if expires is not None and datetime.now(timezone.utc) >= expires:
            state, reason = "not_authorised", f"the workspace's policy expired on {policy['expires']}"
        elif authorisation is None:
            state = "not_authorised"
        elif policy.get("credential") and not os.environ.get(policy["credential"]["ref"][4:]):
            state, reason = "unavailable", ("the credential reference of the policy names nothing in the platform's "
                                            "environment")
        elif policy["provider"] not in PROVIDER_ADAPTERS and policy["provider"] not in ai_policy.NO_AUTHORISATION_NEEDED:
            state, reason = "unavailable", f"no adapter is installed for the provider {policy['provider']}"
        return {"state": state, "reason": reason, "policy": policy, "authorisation": authorisation,
                "current": current, "pending": pending}

    def _ai_grant(self, ws: Workspace, uc_id: str) -> Dict[str, Any]:
        """What one use case's engine may use now: the policy with an adapter and a budget, or the refusal."""
        standing = self._ai_standing(ws)
        if standing["state"] not in ("sandbox", "authorised"):
            return {"refused": standing["reason"]}
        policy = standing["policy"]
        budget = ai_policy.Budget(self.ai_ledger, ws.id, uc_id, policy)
        if policy["provider"] in ai_policy.NO_AUTHORISATION_NEEDED:
            return {"policy": policy, "budget": budget}
        key = os.environ.get(policy["credential"]["ref"][4:])
        try:
            adapter = PROVIDER_ADAPTERS[policy["provider"]](policy, key)
        except Exception as exc:  # an adapter that cannot be built serves nothing; the key is never in the message
            return {"refused": f"the adapter for {policy['provider']} could not be prepared ({type(exc).__name__})"}
        return {"policy": policy, "budget": budget, "adapter": adapter}

    def _ai_fit(self, ws: Workspace, named: Mapping[str, Any]) -> Dict[str, Any]:
        """Whether the workspace's AI policy, as it stands now, serves a configuration that names ``named``
        (provider, model, policy terms). Reading only: what is served is decided by the engine's gateway."""
        standing = self._ai_standing(ws)
        policy = standing["policy"]
        if standing["state"] != "authorised" or policy is None:
            return {"served": False, "reason": standing["reason"] or "the workspace has no authorised AI policy"}
        if policy["provider"] != named.get("provider") or policy["model"] != named.get("model"):
            return {"served": False, "reason": f"the workspace's policy names {policy['provider']} "
                                               f"{policy['model']}, not what this release names"}
        if ai_policy.terms_fingerprint(policy) != named.get("policy_terms"):
            return {"served": False, "reason": "the workspace's policy terms changed since this release was made"}
        return {"served": True, "reason": ""}

    def _apply_ai(self, ws: Workspace) -> None:
        """Give every engine of the workspace the policy as it stands now (after an approval or a disabling)."""
        for uc in ws.use_cases.values():
            uc.service.architect.attach(self._ai_grant(ws, uc.id))

    def ai_view(self, ws: Workspace) -> Dict[str, Any]:
        standing = self._ai_standing(ws)
        policy = standing["policy"]
        usage = self.ai_ledger.usage(ws.id, policy["budget"]["period"]) if policy else None
        remaining = None
        if policy and usage:
            remaining = round(policy["budget"]["per_period"] - usage["spent_usd"] - usage["reserved_usd"], 6)
        current = standing["current"] or {}
        return {"state": standing["state"], "reason": standing["reason"],
                # only an authorised real provider is ever sent anything outside this platform
                "transmits_externally": standing["state"] == "authorised",
                "policy": ai_policy.describe(policy),
                "approved_by": current.get("approved_by"), "approved_at": current.get("approved_at"),
                "proposed_by": current.get("proposed_by"),
                "owner_authorisation": {"present": standing["authorisation"] is not None and standing["state"] != "none",
                                        "decision": (standing["authorisation"] or {}).get("decision"),
                                        "expires": (standing["authorisation"] or {}).get("expires"),
                                        "note": "written by the operator from an owner decision; it cannot be set here"},
                "pending": [{**p, "policy": ai_policy.describe(p["policy"])} for p in standing["pending"].values()],
                "usage": usage, "remaining_usd": remaining,
                "adapters_installed": sorted(PROVIDER_ADAPTERS),
                "use_cases": [{"id": uc.id, **uc.service.architect.status()} for uc in ws.use_cases.values()]}

    def _ai_routes(self, method: str, parts: List[str], ws: Workspace, member: Member, body: Dict[str, Any],
                   reason: str) -> Tuple[int, Any]:
        who = f"{member.name}@{ws.id}"
        if len(parts) == 6 and parts[5] == "policy":  # propose
            problems, policy = ai_policy.validate_policy(body.get("policy"), ws.env_prefix)
            if problems:
                raise AdminError(400, "the policy is not valid: " + "; ".join(problems))
            pid = new_grant_id()
            self.admin.append(ws.id, "ai_policy_proposed", who, reason, {"id": pid, "policy": policy})
            return 201, {**self.ai_view(ws), "proposed": pid}
        if len(parts) == 6 and parts[5] == "disable":
            def check_policy(events):
                from .administration import ai_policy_state

                if ai_policy_state(events)[0] is None:
                    raise AdminError(409, "no AI provider policy is in force")
            self.admin.append(ws.id, "ai_policy_disabled", who, reason, {}, check_policy)
            self._apply_ai(ws)
            return 200, self.ai_view(ws)
        if len(parts) == 8 and parts[5] == "policy" and parts[7] in ("approve", "withdraw"):
            pid, verb = parts[6], parts[7]

            def check(events):
                from .administration import ai_policy_state

                proposal = ai_policy_state(events)[1].get(pid)
                if proposal is None:
                    raise AdminError(404, f"no pending AI policy proposal {pid!r}")
                if verb == "approve" and proposal["proposed_by"] == who:
                    raise AdminError(403, "the proposer cannot approve their own AI policy: another person with "
                                          "authority must")
            self.admin.append(ws.id, f"ai_policy_{'approved' if verb == 'approve' else 'withdrawn'}", who, reason,
                              {"id": pid}, check)
            if verb == "approve":
                self._apply_ai(ws)
            return 200, self.ai_view(ws)
        return 404, None

    def recovery_drill(self, ws: Workspace, member: Member, reason: str) -> Dict[str, Any]:
        """Rehearse a recovery and record the evidence (REL-2 "recovery_evidence"): take a consistent backup of
        the platform's data, verify it completely, restore it into a scratch folder, and load each use case of
        this workspace from the restored files on a throwaway engine. Nothing running is touched, nothing is
        kept, and no stored run is continued. Evidence is recorded in the workspace's signed administration log
        only when every step succeeded; a failed rehearsal records nothing and says what failed."""
        from . import recovery

        reason = (reason or "").strip()
        if not (1 <= len(reason) <= 500):
            raise LifecycleError(400, "give a reason (1 to 500 characters)")
        if not self._drilling.acquire(blocking=False):
            raise LifecycleError(409, "a recovery rehearsal is already running")
        scratch = Path(tempfile.mkdtemp(prefix="autology-drill-"))
        try:
            try:
                taken = recovery.backup(self.data_dir, scratch / "backup")
                checked = recovery.verify(scratch / "backup")
                restored = recovery.restore(scratch / "backup", scratch / "restored")
            except recovery.RecoveryError as exc:
                raise LifecycleError(409, f"the rehearsal failed, no evidence was recorded: {exc}") from None
            use_cases: Dict[str, Any] = {}
            for uc in ws.use_cases.values():
                home = scratch / "restored" / ws.id / uc.id
                try:
                    probe: Any = self._load_use_case(ws, uc.id, uc.spec, self._base_dir, validate_only=True,
                                                     candidate=home)
                except (PlatformError, ValueError, OSError) as exc:
                    raise LifecycleError(409, f"the rehearsal failed, no evidence was recorded: use case {uc.id} "
                                              f"does not load from the restored files ({exc})") from None
                try:
                    restored_configuration = probe.configuration_fingerprint
                finally:
                    probe.close()
                use_cases[uc.id] = {"configuration": restored_configuration,
                                    "reproduces_what_runs": restored_configuration == uc.service.configuration_fingerprint}
            data = {"use_cases": use_cases, "counts": checked["counts"], "files": taken["files"],
                    "bytes": taken["bytes"], "steps": ["backup", "verify", "restore", "load"],
                    "seconds": round(taken["seconds"] + restored["seconds"], 3)}
            event = self.admin.append(ws.id, "recovery_rehearsed", f"{member.name}@{ws.id}", reason, data)
            return {"recorded": True, "at": event["at"], **data}
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            self._drilling.release()

    def _recovery_evidence(self, uc: UseCase) -> Optional[Dict[str, Any]]:
        """The last recorded recovery rehearsal that covered this use case, read against what runs now. Evidence
        for another configuration is reported as such, never as evidence for this one."""
        events, problem = self.admin.events(uc.workspace)
        if problem:
            return {"verified": False, "detail": problem, "evidence": []}
        last = next((e for e in reversed(events) if e["event"] == "recovery_rehearsed"
                     and uc.id in (e["data"].get("use_cases") or {})), None)
        if last is None:
            return None
        mine = last["data"]["use_cases"][uc.id]
        running = uc.service.configuration_fingerprint
        current = mine["configuration"] == running and bool(mine.get("reproduces_what_runs"))
        when = f"{last['at'][:19].replace('T', ' ')} UTC by {last['by']}"
        detail = (f"a backup was verified and its restore rehearsed on {when}; the restored configuration "
                  f"({running[:12]}) is what runs" if current else
                  f"the last rehearsal ({when}) covered configuration {mine['configuration'][:12]}; the use case "
                  f"now runs {running[:12]}: rehearse again")
        return {"verified": current, "detail": detail,
                "evidence": [f"administration log entry {last['seq']}: recovery rehearsed ({', '.join(last['data'].get('steps') or [])})"]}

    def _sample_refusal(self, uc: UseCase) -> Optional[str]:
        """Why sample records cannot be loaded into this use case now, or None."""
        rel = self.release_of(uc)
        if rel["integrity_problem"]:
            return rel["integrity_problem"]
        if not rel["active"] or rel["drift"]:
            return ("sample records are loaded only when an approved release is active and is what runs: no "
                    "unapproved configuration brings data with it")
        stage = self.effective_stage(uc)
        if stage not in ("draft", "simulation"):
            return f"sample records are for rehearsal: they are not loaded into a use case in {stage}"
        return None

    def sample_data(self, ws: Workspace, uc: UseCase, member: Member) -> Dict[str, Any]:
        status = uc.service.configuring.sample_status()
        refusal = self._sample_refusal(uc)
        active = self.release_of(uc)["active"]
        return {**status, "release": active["number"] if active else None, "loadable": refusal is None
                and status["available"] > len(status["loaded"]) + len(status["already_present"]),
                "refusal": refusal,
                "may_load": member.workspace_admin and member.kind == "person"}

    def load_sample_data(self, ws: Workspace, uc: UseCase, member: Member, reason: str) -> Dict[str, Any]:
        """Load the synthetic sample records of the active release, at a person's request (never automatically).
        Recorded in the workspace's administration log with who, why, which release and how many records."""
        reason = (reason or "").strip()
        if not (1 <= len(reason) <= 500):
            raise LifecycleError(400, "give a reason (1 to 500 characters)")
        refusal = self._sample_refusal(uc)
        if refusal:
            raise LifecycleError(409, refusal)
        active = self.release_of(uc)["active"]
        out = uc.service.configuring.load_samples(f"{member.name}@{ws.id}")
        self.admin.append(ws.id, "sample_data_loaded", f"{member.name}@{ws.id}", reason,
                          {"use_case": uc.id, "release": active["number"], "configuration": out["configuration"],
                           "loaded": len(out["loaded"]), "skipped": len(out["skipped"]), "links": out["links"]})
        return {**self.sample_data(ws, uc, member), "just_loaded": out["loaded"], "skipped": out["skipped"]}

    @contextmanager
    def _probing(self, ws: Workspace, uc: UseCase, document: Dict[str, Any], managed: Any):
        """A throwaway engine for a configuration that is not in place: the use case's deployed files with this
        model and this agent configuration, on an in-memory store, with the members as they are now. It has no
        runs and no records of its own, starts nothing in the background and leaves nothing behind."""
        scratch = Path(tempfile.mkdtemp(prefix="autology-probe-"))
        probe: Any = None
        try:
            _put(scratch / ONTOLOGY_OVERRIDE, document)
            if managed is not None:
                _put(scratch / SOLUTION_OVERRIDE, managed)
            probe = self._load_use_case(ws, uc.id, uc.spec, self._base_dir, validate_only=True, candidate=scratch)
            yield probe
        finally:
            if probe is not None:
                probe.close()
            shutil.rmtree(scratch, ignore_errors=True)

    def readiness_of(self, ws: Workspace, uc: UseCase, member: Member, target: str, of: str) -> Dict[str, Any]:
        """The readiness report (REL-2, REL-3) of one configuration of a use case, named in ``subject``: what runs
        (``active``), the saved draft (``draft``) or a release (``release:<n>``). The same conditions and the same
        calculation in every case; a configuration that does not run is measured on a throwaway engine, so its
        execution evidence is missing rather than borrowed, and the answer lists what differs from what runs."""
        if target not in readiness.TARGETS:
            raise LifecycleError(400, f"target: one of {', '.join(readiness.TARGETS)}")
        stage = {"stage": self.stage_of(uc)["stage"], "effective_stage": self.effective_stage(uc)}
        rel = self.release_of(uc)
        running = readiness.report(uc.service, target, self._readiness_context(uc))
        fingerprint = uc.service.configuration_fingerprint
        if of.startswith("release:") and of[8:].isdigit() and rel["active"] and not rel["drift"] \
                and rel["active"]["number"] == int(of[8:]):
            of = "active"  # the active release, asked for by its number, is what runs
        if of == "active":
            active = rel["active"] if rel["active"] and not rel["drift"] else None
            subject = {"kind": "active", "revision": None, "release": active["number"] if active else None,
                       "label": f"what runs now: release {active['number']}" if active else
                                "what runs now: not covered by an active release",
                       "configuration": fingerprint, "model": uc.service.ontology.ref,
                       "evaluated": "the running engine, with its runs, records and members"}
            return {**running, **stage, "subject": subject, "compared_with": None}
        # a draft or a waiting release is design work: shown to the people who design and release
        if not (member.workspace_admin or self.may_approve_releases(ws, member)
                or "configure" in (member.grant(uc.id) or {}).get("permissions", [])):
            raise LifecycleError(403, "the readiness of a draft or of a release that is not active is shown to "
                                      "people who configure or release this use case")
        if of == "draft":
            row = uc.service.store.draft()
            if row is None:
                raise LifecycleError(404, "no draft is saved for this use case")
            document, managed = row["document"], row.get("solution")
            if uc.service.configuring.managed == "files":
                managed = None  # an operator's agents apply: Studio does not configure them
            subject = {"kind": "draft", "revision": row["revision"], "release": None,
                       "label": f"draft revision {row['revision']} (not released)"}
            why = ("a draft is not a release: publish it, propose a release of it, have it approved by another "
                   "person and activate it")
        elif of.startswith("release:") and of[8:].isdigit():
            number = int(of[8:])
            item = self.releases.release(ws.id, uc.id, number)
            snapshot = self.releases.snapshot(ws.id, uc.id, number) or {}
            if not _is_document(snapshot.get("ontology")):
                raise LifecycleError(409, f"release {number} has no model document to assess")
            document, managed = snapshot["ontology"], (snapshot.get("settings") or {}).get("solution")
            subject = {"kind": "release", "revision": None, "release": number,
                       "label": f"release {number} ({item['status']}, not what runs)"}
            why = (f"release {number} is approved by {item['approved_by']} but is not active: activate it"
                   if item["approved_by"] else
                   f"release {number} is not approved: another person with release authority must approve it")
        else:
            raise LifecycleError(400, "of: active, draft or release:<number>")
        try:
            with self._probing(ws, uc, document, managed) as probe:
                context = self._readiness_context(uc, [Check("approved_release_active", False, why)])
                found = readiness.report(probe, target, context)
                subject.update({"configuration": probe.configuration_fingerprint, "model": probe.ontology.ref})
        except (PlatformError, ValueError, OSError) as exc:
            raise LifecycleError(409, f"{subject['label']} cannot be assessed, it does not load: {exc}") from None
        subject["evaluated"] = ("a throwaway engine built from this configuration: it has no runs or records of "
                                "its own, so its execution evidence is missing")
        if subject["kind"] == "release":
            subject["matches_release"] = subject["configuration"] == item["fingerprint"]
        return {**found, **stage, "subject": subject,
                "compared_with": {"kind": "active", "configuration": fingerprint,
                                  "same_configuration": subject["configuration"] == fingerprint,
                                  "score": running["score"]["overall"],
                                  **readiness.differences(running, found)}}

    @staticmethod
    def _apply_solution(config: Dict[str, Any], base: Path, path: Path, where: str) -> None:
        """Put a Studio-managed configuration into an engine's configuration: compiled by the engine's own rules
        against the model it will run with, or the use case does not load."""
        from . import solution as solutions

        if config.get("agents"):  # an operator's agents are never replaced silently
            raise PlatformError(f"{where}: its files configure agents and an agent configuration from Studio is "
                                "published too; remove one of the two")
        try:
            managed = json.loads(path.read_text(encoding="utf-8"))
            document = json.loads((base / config["ontology"]).read_text(encoding="utf-8"))
            compiled = solutions.compile_solution(managed, document)
        except (OSError, ValueError) as exc:  # unreadable, not JSON, or not valid for this model (SolutionError)
            raise PlatformError(f"{where}: the published agent and tool configuration does not fit the model: "
                                f"{exc}") from None
        # the sample records in the configuration are not loaded here: a release never brings data with it.
        # A person loads them explicitly, once an approved release runs (load_sample_data)
        config["agents"], config["solution"] = compiled["agents"], managed

    # -- requests --------------------------------------------------------------------------------------------
    def members_for(self, authorization: Optional[str]) -> Dict[str, Member]:
        """The token's identity as one Member per workspace it explicitly belongs to (all in one tenant)."""
        if not authorization or not authorization.startswith("Bearer "):
            return {}
        members = self._tokens.get(hash_token(authorization[7:].strip()), {})
        return {} if members and self._token_problem(members) else members

    @staticmethod
    def _expired(member: Member) -> bool:
        return member.expires_at is not None and credentials.now() >= member.expires_at

    def _token_problem(self, members: Dict[str, Member]) -> Optional[str]:
        """Why a known token is refused now (revoked, expired), or None. Checked on every request."""
        member = next(iter(members.values()))
        if self.credentials.revoked(member.token_sha256):
            return "this token was revoked"
        if self._expired(member):
            when = credentials.iso(member.expires_at)
            return (f"this token expired on {when}: sign in again or ask a workspace administrator for a new one"
                    if member.kind == "person" else
                    f"this service token expired on {when}: a workspace administrator must issue a new one")
        return None

    def refused_token(self, authorization: Optional[str]) -> Tuple[Optional[Member], Optional[str]]:
        """For the answer and the access log when a token is refused: whose it was and why, if it is a known one."""
        if not authorization or not authorization.startswith("Bearer "):
            return None, None
        members = self._tokens.get(hash_token(authorization[7:].strip()), {})
        if not members:
            return None, None
        return next(iter(members.values())), self._token_problem(members)

    def member_for(self, authorization: Optional[str], workspace: Optional[str] = None) -> Optional[Member]:
        """The token's Member in ``workspace`` (None if it has no membership there), or its first membership."""
        members = self.members_for(authorization)
        if workspace is not None:
            return members.get(workspace)
        return next(iter(members.values()), None)

    def me(self, member: Member, members: Optional[Dict[str, Member]] = None) -> Dict[str, Any]:
        ws = self.workspaces[member.workspace]
        tenant = self.tenants[ws.tenant]
        memberships = members or {ws.id: member}
        return {"workspace": {"id": ws.id, "name": ws.name}, "member": member.name, "kind": member.kind,
                "workspace_admin": member.workspace_admin,
                # what the caller may do with releases here (their own authority, nothing about anyone else)
                "release_approver": self.may_approve_releases(ws, member),
                "token_expires_at": credentials.iso(member.expires_at),
                "tenant": {"id": tenant.id, "name": tenant.name}, "tenant_admin": member.tenant_admin,
                # every workspace the identity explicitly belongs to; choose one with /platform/me?workspace=<id>
                "workspaces": [{"id": w, "name": self.workspaces[w].name, "workspace_admin": m.workspace_admin}
                               for w, m in memberships.items()],
                "use_cases": [{"id": uc.id, "name": uc.name, "ontology": uc.service.ontology.ref,
                               "permissions": member.grant(uc.id)["permissions"],
                               "stage": self.stage_of(uc)["stage"],
                               "path": f"/w/{ws.id}/u/{uc.id}"}
                              for uc in ws.use_cases.values() if member.grant(uc.id)]}

    def tenant_view(self, tenant: Tenant, members: Dict[str, Member]) -> Dict[str, Any]:
        """A tenant as one of its identities sees it: its own workspaces, or all of them for a tenant
        administrator, who also sees the tenant-level members. Never anything of another tenant."""
        admin = any(m.tenant_admin for m in members.values())
        visible = tenant.workspaces if admin else [w for w in tenant.workspaces if w in members]
        view: Dict[str, Any] = {
            "id": tenant.id, "name": tenant.name, "dedicated": tenant.dedicated, "tenant_admin": admin,
            "workspaces": [{"id": w, "name": self.workspaces[w].name, "member": w in members,
                            "workspace_admin": bool(members.get(w) and members[w].workspace_admin)} for w in visible]}
        if admin:
            view["members"] = [{"name": tm.name, "kind": tm.kind, "tenant_admin": tm.tenant_admin,
                                "workspaces": sorted(tm.workspaces)} for tm in tenant.members.values()]
        return view

    # -- use-case management and stages (R2 slice) -------------------------------------------------------------
    def stage_of(self, uc: UseCase) -> Dict[str, Any]:
        return self.lifecycle.status(uc.workspace, uc.id, uc.service.ontology.fingerprint)

    def release_of(self, uc: UseCase) -> Dict[str, Any]:
        """The use case's releases, the active one, and whether the running configuration drifted from it."""
        st = self.releases.state(uc.workspace, uc.id)
        running = uc.service.configuration_fingerprint
        active = st["active"]
        return {"active": active, "running_fingerprint": running,
                "drift": bool(active) and active["fingerprint"] != running,
                "integrity_problem": st["integrity_problem"], "items": st["items"], "history": st["history"]}

    def effective_stage(self, uc: UseCase) -> str:
        """The stage the engine obeys: a stale stage, a history that does not verify, a release history that does
        not verify, or a configuration that drifted from the active release all count as draft (nothing runs)."""
        return self.effective_stage_and_reason(uc)[0]

    def effective_stage_and_reason(self, uc: UseCase) -> Tuple[str, Optional[str]]:
        st = self.stage_of(uc)
        if st["integrity_problem"]:
            return "draft", st["integrity_problem"]
        if st["stale"]:
            return "draft", "the configuration changed since the stage was granted"
        rel = self.release_of(uc)
        if rel["integrity_problem"]:
            return "draft", rel["integrity_problem"]
        if rel["drift"]:
            return "draft", (f"the running configuration ({rel['running_fingerprint'][:12]}) is not the active release "
                             f"{rel['active']['number']}: a person must activate an approved release of it")
        return st["stage"], None

    def _release_checks(self, uc: UseCase) -> List[Check]:
        """Pilot needs an independently approved release that is active and is exactly what runs (REL-1a, D11)."""
        rel = self.release_of(uc)
        active = rel["active"]
        if rel["integrity_problem"]:
            return [Check("approved_release_active", False, rel["integrity_problem"])]
        if not active:
            return [Check("approved_release_active", False,
                          "no release is active: propose a release, have it approved by another person with release "
                          "authority, then activate it")]
        if rel["drift"]:
            return [Check("approved_release_active", False,
                          f"the running configuration ({rel['running_fingerprint'][:12]}) is not the active release "
                          f"{active['number']} ({active['fingerprint'][:12]})")]
        return [Check("approved_release_active", True,
                      f"release {active['number']} ({active['fingerprint'][:12]}) approved by {active['approved_by']} "
                      "is active and is what runs")]

    def use_case_view(self, uc: UseCase, member: Member, detail: bool = False) -> Dict[str, Any]:
        st = self.stage_of(uc)
        view = {"id": uc.id, "name": uc.name, "origin": uc.origin, "template": uc.template,
                "ontology": uc.service.ontology.ref, "fingerprint": uc.service.ontology.fingerprint,
                "path": f"/w/{uc.workspace}/u/{uc.id}",
                "permissions": (member.grant(uc.id) or {"permissions": []})["permissions"],  # an approver: none
                "stage": st["stage"], "stale": st["stale"], "integrity_problem": st["integrity_problem"],
                "effective_stage": self.effective_stage(uc), "stages": list(STAGES)}
        rel = self.release_of(uc)
        view["configuration"] = rel["running_fingerprint"]
        view["release"] = {"active": rel["active"], "drift": rel["drift"],
                           "integrity_problem": rel["integrity_problem"]}
        if detail:
            view["history"] = st["history"]
        return view

    def create_use_case(self, member: Member, uc_id: str, name: str, template: str) -> UseCase:
        ws = self.workspaces[member.workspace]
        if not isinstance(uc_id, str) or not ID.match(uc_id):
            raise LifecycleError(400, "id: lowercase letters, digits and '-' only (at most 63)")
        if not isinstance(name, str) or not (1 <= len(name.strip()) <= 120):
            raise LifecycleError(400, "name: 1 to 120 characters")
        if template not in self.templates:
            raise LifecycleError(400, f"unknown template {template!r}")
        with self._lock:
            if uc_id in ws.use_cases:
                raise LifecycleError(409, f"use case {uc_id} already exists")
            home = self.data_dir / ws.id / uc_id
            if home.exists() and any(home.iterdir()):  # never hand an earlier use case's data to a new one
                raise LifecycleError(409, f"the id {uc_id} was used before in this workspace and its data is kept; "
                                          "choose another id")
            try:
                uc = self._load_use_case(ws, uc_id, {"name": name.strip(),
                                                     "config": self.templates[template]["config"]}, self._base_dir)
            except PlatformError as exc:
                raise LifecycleError(400, str(exc))
            uc.origin, uc.template = "template", template
            self.lifecycle.record_created(ws.id, uc_id, uc.name, template, member.name)
            ws.use_cases[uc_id] = uc
            if self.running:
                uc.stop = uc.service.start_background()
                self._stops.append(uc.stop)
        return uc

    def _write_override(self, ws: Workspace, uc: UseCase, document: Dict[str, Any], member: Member, reason: str,
                        event: str, data: Dict[str, Any], solution: Any = _KEEP) -> UseCase:
        """Write this use case's own ontology (and, when given, its agent and tool configuration; ``None`` removes
        it) and reload its engine; if the result does not load, the previous files (or their absence) are put back
        and nothing changes. The two are written and reloaded as one step: never one without the other."""
        home = self.data_dir / ws.id / uc.id
        files = [(home / ONTOLOGY_OVERRIDE, document)]
        if solution is not _KEEP:
            files.append((home / SOLUTION_OVERRIDE, solution))
        with self._switching(ws, uc.id):  # alone on the engine from the first byte written to the reload
            previous = [(path, path.read_bytes() if path.is_file() else None) for path, _ in files]
            try:
                for path, content in files:
                    _put(path, content)
                fresh = self.reload_use_case(ws, uc, member, reason)
            except BaseException:
                for path, raw in previous:
                    _put(path, raw)
                raise
            self.admin.append(ws.id, event, f"{member.name}@{ws.id}", reason,
                              {**data, "use_case": uc.id, "configuration": fresh.service.configuration_fingerprint})
        return fresh

    def publish_draft(self, ws: Workspace, uc: UseCase, member: Member, revision: Any, reason: str) -> Dict[str, Any]:
        """Make a saved, valid Studio draft this use case's ontology (STU-6). Publishing changes the configuration:
        with an active release, nothing runs until a release of the new configuration is approved by another
        person and activated."""
        from . import solution as solutions
        from .modeling import validate

        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise LifecycleError(400, "revision: the saved draft revision to publish")
        row = uc.service.store.draft(revision)
        if row is None:
            raise LifecycleError(404, f"no draft revision {revision}")
        # A published model is loaded at once, and its access rules then govern what members read. So one person
        # never does it alone (IAM-3, GAP-061): whoever saved the revision cannot publish it.
        if row["author"] == member.name:
            raise LifecycleError(403, "you saved this draft revision: another person with release authority must "
                                      "publish it (a model's access rules never change on one person's say-so)")
        verdict = validate(row["document"])
        if not verdict["valid"]:
            raise LifecycleError(409, "the draft is not valid: " + "; ".join(p["message"] for p in verdict["problems"]))
        # the agents and simulated tools of the draft are published with its model, and checked against it first:
        # a configuration that refers to something the model no longer has is never put in place
        managed: Any = row.get("solution")
        if uc.service.configuring.managed == "files":
            managed = _KEEP  # an operator's agents: Studio never touches them
        elif managed is not None:
            problems, _ = solutions.check(managed, row["document"])
            if problems:
                raise LifecycleError(409, "the draft's agent and tool configuration does not fit its model: "
                                     + "; ".join(f"{p['path']}: {p['message']}" for p in problems[:5]))
        data: Dict[str, Any] = {"revision": revision}
        if isinstance(managed, dict):
            data["agents"] = sorted(managed.get("agents") or {})
        fresh = self._write_override(ws, uc, row["document"], member, reason, "draft_published", data, managed)
        return {**self.use_case_view(fresh, member, detail=True), "published_revision": revision,
                "published_agents": sorted(fresh.service.agents)}

    def restore_release(self, ws: Workspace, uc: UseCase, member: Member, number: int, reason: str) -> Dict[str, Any]:
        """Put a release's ontology, and the agent and tool configuration it was released with, back as this use
        case's own and reload (a rollback of the model and its agents together). The release can then be activated
        if everything else it covers is unchanged too."""
        snapshot = self.releases.snapshot(ws.id, uc.id, number)
        if snapshot is None:
            raise ReleaseError(404, f"no release {number}")
        if not _is_document(snapshot.get("ontology")):
            raise ReleaseError(409, f"release {number} has no ontology document to restore")
        release = self.releases.release(ws.id, uc.id, number)
        if not release["approved_by"] and release["status"] not in ("active", "superseded"):
            # only a model another person already approved comes back without a second look (IAM-3, GAP-061)
            raise ReleaseError(409, f"release {number} was never approved: its model cannot be restored; have the "
                                    "release approved first, or publish the model as a draft")
        fresh = self._write_override(ws, uc, snapshot["ontology"], member, reason, "release_restored",
                                     {"release": number}, (snapshot.get("settings") or {}).get("solution"))
        release = self.releases.release(ws.id, uc.id, number)
        return {**self.use_case_view(fresh, member, detail=True),
                "matches_release": release["fingerprint"] == fresh.service.configuration_fingerprint}

    @contextmanager
    def _switching(self, ws: Workspace, uc_id: str):
        """Alone on one use case's engine: requests in flight have finished, new ones wait."""
        gate = ws.gates.setdefault(uc_id, Gate())
        try:
            gate.acquire(SWAP_WAIT)
        except Busy:
            raise LifecycleError(409, "requests on this use case are still in progress: nothing was changed; "
                                      "try again when they have finished (a running step is never cut)") from None
        try:
            with self._lock:
                yield
        finally:
            gate.release()

    def _swap(self, ws: Workspace, uc: UseCase) -> UseCase:
        """Replace the running engine by one built from the files as they are now. The caller is alone on the use
        case (:meth:`_switching`) and has checked that the files load."""
        if uc.stop is not None:
            uc.stop.set()
        uc.service.close()
        fresh = self._load_use_case(ws, uc.id, uc.spec, self._base_dir)
        fresh.origin, fresh.template = uc.origin, uc.template
        ws.use_cases[uc.id] = fresh
        if self.running:
            fresh.stop = fresh.service.start_background()
            self._stops.append(fresh.stop)
        return fresh

    def reload_use_case(self, ws: Workspace, uc: UseCase, member: Member, reason: str) -> UseCase:
        """Reload one engine from its configuration files without restarting the platform (ADM-2). The files are
        first loaded into a throwaway engine; only if that works is the running engine replaced, once the requests
        in flight have finished. A reload is not an activation: if a release is active and the files changed, the
        use case counts as draft until a person activates an approved release of what now runs (REL-1a)."""
        reason = (reason or "").strip()
        if not (1 <= len(reason) <= 500):
            raise LifecycleError(400, "give a reason (1 to 500 characters)")
        with self._switching(ws, uc.id):
            uc = ws.use_cases[uc.id]
            before = uc.service.configuration_fingerprint
            try:
                after = self._load_use_case(ws, uc.id, uc.spec, self._base_dir, validate_only=True)
            except (PlatformError, ValueError, OSError) as exc:
                raise LifecycleError(400, f"the configuration does not load, nothing was changed: {exc}") from None
            fresh = self._swap(ws, uc)
            self.admin.append(ws.id, "engine_reloaded", f"{member.name}@{ws.id}", reason,
                              {"use_case": uc.id, "from": before, "to": after})
        return fresh

    def activate_release(self, ws: Workspace, uc: UseCase, member: Member, number: int,
                         reason: str) -> Dict[str, Any]:
        """Activate (or roll back to) a release; a refusal of an existing release is recorded in the workspace's
        administration log, as the activation itself is recorded in the release history."""
        try:
            return self._activate_release(ws, uc, member, number, reason)
        except ReleaseError as exc:
            if exc.status in (409, 500):
                try:
                    self.admin.append(ws.id, "release_activation_refused", f"{member.name}@{ws.id}",
                                      (reason or "").strip()[:500] or "no reason given",
                                      {"release": number, "use_case": uc.id, "refusal": str(exc)[:600]})
                except AdminError:  # the refusal stands whether or not it could be recorded
                    log.exception("could not record the refused activation of release %s of %s/%s", number, ws.id, uc.id)
            raise

    def _activate_release(self, ws: Workspace, uc: UseCase, member: Member, number: int,
                          reason: str) -> Dict[str, Any]:
        """Make an approved release what runs, in one coordinated step (REL-1a; R2 reliability sprint C).

        No restart and no separate reload: if the engine does not already run the release's configuration, the
        release's model is put in place, the configuration is rebuilt from the deployed files and checked against
        the release's fingerprint *before* anything changes, and the engine is switched only once the requests in
        flight have finished. Other requests wait and then see the new configuration, never a mixture. If any
        step fails, the model and the engine that ran before are put back and the previous release stays active
        (fail closed). Activating an older release is a rollback, the same way. The approval history is never
        rewritten: activation only appends."""
        from . import solution as solutions

        who = f"{member.name}@{ws.id}"
        reason = (reason or "").strip()
        if not (1 <= len(reason) <= 500):
            raise ReleaseError(400, "give a reason (1 to 500 characters)")
        with self._switching(ws, uc.id):
            uc = ws.use_cases[uc.id]
            st = self.releases.state(ws.id, uc.id)
            if st["integrity_problem"]:
                raise ReleaseError(409, st["integrity_problem"])
            target = next((i for i in st["items"] if i["number"] == number), None)
            if target is None:
                raise ReleaseError(404, f"no release {number}")
            if not target["approved_by"]:
                raise ReleaseError(409, f"release {number} is not approved: another person with release authority "
                                        "must approve it first")
            if target["status"] == "active":
                raise ReleaseError(409, f"release {number} is already active")
            previous = st["active"]
            kind = "rolled_back" if previous and previous["number"] > number else "activated"
            before = uc.service.configuration_fingerprint
            snapshot = self.releases.snapshot(ws.id, uc.id, number) or {}
            # the release must be coherent in itself (model, agents, tools refer to one another correctly) before
            # anything is touched: a release that could not execute is never brought into force
            incoherent = solutions.release_problems(snapshot)
            if incoherent:
                raise ReleaseError(409, f"release {number} cannot be activated, nothing was changed: "
                                   + "; ".join(incoherent[:5]))
            path = self.data_dir / ws.id / uc.id / ONTOLOGY_OVERRIDE
            agents_path = self.data_dir / ws.id / uc.id / SOLUTION_OVERRIDE
            model_before = path.read_bytes() if path.is_file() else None
            agents_before = agents_path.read_bytes() if agents_path.is_file() else None
            switched = False

            def put_back() -> None:
                """The model, the agent configuration and the engine that ran before the attempt."""
                _put(path, model_before)
                _put(agents_path, agents_before)
                if switched:
                    current = ws.use_cases[uc.id]
                    try:
                        self._swap(ws, current)
                    except Exception as exc:  # even the previous configuration no longer loads: serve nothing
                        current.unavailable = (f"activation of release {number} failed and the previous "
                                               f"configuration could not be loaded again ({type(exc).__name__})")
                        log.exception("use case %s/%s is unavailable", ws.id, uc.id)

            fresh = uc
            try:
                if target["fingerprint"] != before:
                    document = snapshot.get("ontology")
                    if _is_document(document):
                        _put(path, document)
                    # the release's own agents and simulated tools come back with its model (none: none)
                    _put(agents_path, (snapshot.get("settings") or {}).get("solution"))
                    try:
                        candidate = str(self._load_use_case(ws, uc.id, uc.spec, self._base_dir, validate_only=True))
                    except (PlatformError, ValueError, OSError) as exc:
                        raise ReleaseError(409, f"release {number} does not load with the deployed files, nothing "
                                                f"was changed: {exc}") from None
                    if candidate != target["fingerprint"]:
                        raise ReleaseError(
                            409, f"release {number} ({target['fingerprint'][:12]}) cannot be brought into force "
                                 f"from the deployed files: with its model they give configuration "
                                 f"{candidate[:12]}. What differs is outside the model (agents, governing settings "
                                 "or tool declarations in the use case's files): deploy that release's files, then "
                                 "activate it again; no restart or reload is needed. Nothing was changed")
                    switched = True
                    fresh = self._swap(ws, uc)
                running = fresh.service.configuration_fingerprint

                def check_activate(item, state):
                    if not item["approved_by"]:
                        raise ReleaseError(409, f"release {item['number']} is not approved")
                    if item["status"] == "active":
                        raise ReleaseError(409, f"release {item['number']} is already active")
                    if item["fingerprint"] != running:  # never record as active what does not run
                        raise ReleaseError(409, f"the engine runs configuration {running[:12]}, not release "
                                                f"{item['number']} ({item['fingerprint'][:12]})")
                out = self.releases.record(ws.id, uc.id, number, kind, who, reason, check_activate)
            except ReleaseError:
                put_back()
                raise
            except BaseException as exc:
                put_back()
                if not isinstance(exc, Exception):
                    raise
                log.exception("activation of release %s of %s/%s failed", number, ws.id, uc.id)
                state = ws.use_cases[uc.id].unavailable
                raise ReleaseError(500, f"the activation of release {number} failed ({type(exc).__name__}); "
                                   + (f"{state}: the use case serves nothing until a reload succeeds" if state else
                                      "the model and the engine that ran before were put back, and the release "
                                      "that was active stays active")) from None
            if switched:
                self.admin.append(ws.id, "release_restored", who, reason,
                                  {"release": number, "use_case": uc.id, "configuration": running,
                                   "by": "activation", "from": before})
            stage = self._revalidate_stage(ws, fresh, who, number)
            # runs started on another configuration never continue on this one (WorkAgent.resume, decide)
            waiting = [r["run_id"] for r in fresh.service.store.list_runs(limit=10 ** 6)
                       if r["status"] in ("awaiting_review", "deferred", "paused", "pending_confirmation")]
            stopped = [rid for rid in waiting if self._run_configuration(fresh, rid) not in ("", running)]
        # run identifiers are execution evidence: listed only for someone who may read this use case's data (IAM-3)
        return {**out, "event": kind, "reloaded": switched, "configuration": running, "stage": stage,
                "runs_on_other_configurations_count": len(stopped),
                "runs_on_other_configurations": stopped if member.has_data_access(uc.id) else []}

    def _revalidate_stage(self, ws: Workspace, uc: UseCase, who: str, number: int) -> Dict[str, Any]:
        """A stage is granted for one model. When an activation changes the model, the use case is simulated
        again at once if the simulation checks pass, so that the release that was just activated runs without a
        second manual step; pilot is never granted automatically (a person decides it again, with its checks),
        and production is never granted at all."""
        st = self.stage_of(uc)
        if st["integrity_problem"] or not st["stale"]:
            return {"stage": self.effective_stage(uc), "revalidated": False}
        was = st["stage"]
        try:
            self.lifecycle.move(ws.id, uc.id, uc.service, "draft", who,
                                f"release {number} activated: the model changed, the stage is granted again")
            self.lifecycle.move(ws.id, uc.id, uc.service, "simulation", who,
                                f"release {number} activated: simulated again on the new model",
                                extra_checks=self._stage_checks(uc))
        except LifecycleError as exc:
            return {"stage": self.effective_stage(uc), "revalidated": False, "was": was, "problem": str(exc),
                    "checks": exc.checks or []}
        return {"stage": self.effective_stage(uc), "revalidated": True, "was": was,
                "next": "pilot needs a person's decision again (POST .../stage)" if was == "pilot" else None}

    def _json(self, raw_body: Optional[bytes], body_error: Optional[Tuple[int, str]]) -> Dict[str, Any]:
        if body_error:
            raise LifecycleError(body_error[0], body_error[1])
        try:
            body = json.loads(raw_body or b"{}")
        except ValueError:
            raise LifecycleError(400, "the body must be JSON")
        if not isinstance(body, dict):
            raise LifecycleError(400, "the body must be a JSON object")
        return body

    def _manage(self, member: Optional[Member], method: str, parts: List[str], query: str,
                raw_body: Optional[bytes], body_error: Optional[Tuple[int, str]],
                members: Optional[Dict[str, Member]] = None) -> Tuple[int, Any]:
        """``/platform/templates``, ``/platform/tenants/<tenant>`` and
        ``/platform/workspaces/<ws>/use-cases[/<uc>[/checks|/stage]]``. ``member`` is the caller's membership in
        the workspace the path names (None: no membership there, whatever tenant it is in)."""
        members = members if members is not None else ({member.workspace: member} if member else {})
        if parts[2:] == ["templates"] and method == "GET":
            if not any(m.workspace_admin for m in members.values()):
                raise LifecycleError(403, "workspace administrators only")
            return 200, {"items": [{k: t[k] for k in ("id", "name", "description")} for t in self.templates.values()]}
        if len(parts) == 4 and parts[2] == "tenants" and method == "GET":
            tenant = self.tenants.get(parts[3])
            if tenant is None or not any(m.tenant == tenant.id for m in members.values()):
                return 404, None  # another tenant, or none: the same answer
            return 200, self.tenant_view(tenant, members)
        if member is None:
            return 404, None  # a workspace the caller does not belong to, another tenant's, or none: the same answer
        if len(parts) == 5 and parts[2] == "workspaces" and parts[4] == "my-token" and method == "POST":
            return self._own_token(self.workspaces[member.workspace], member, raw_body, body_error)
        if len(parts) >= 5 and parts[2] == "workspaces" and parts[4] in ("members", "grants", "token-requests",
                                                                         "access-review", "recovery-drill", "ai"):
            ws = self.workspaces.get(parts[3]) if parts[3] == member.workspace else None
            if ws is None:
                return 404, None  # another workspace, or none: the same answer
            return self._administration(method, parts, ws, member, raw_body, body_error)
        releases = len(parts) >= 7 and parts[6] in ("releases", "publish-draft")  # open to named approvers
        if len(parts) < 5 or parts[2] != "workspaces" or parts[4] != "use-cases" or len(parts) > (9 if releases else 7):
            return 404, None
        ws = self.workspaces.get(parts[3]) if parts[3] == member.workspace else None
        if ws is None:
            return 404, None  # another workspace, or none: the same answer
        if len(parts) == 5:
            if method == "GET":
                return 200, {"items": [self.use_case_view(uc, member) for uc in ws.use_cases.values()
                                       if member.grant(uc.id)]}
            if method == "POST":
                if not member.workspace_admin:
                    raise LifecycleError(403, "workspace administrators only")
                body = self._json(raw_body, body_error)
                uc = self.create_use_case(member, body.get("id"), body.get("name") or body.get("id") or "",
                                          body.get("template"))
                return 201, self.use_case_view(uc, member, detail=True)
            return 405, {"error": f"{method} is not supported here"}
        uc = ws.use_cases.get(parts[5])
        # a named release approver (e.g. an external one, D11) sees a use case's releases without other grants
        if uc is None or not (member.grant(uc.id) or (releases and member.name in ws.release_approvers)):
            return 404, None
        action = parts[6] if len(parts) >= 7 else None
        # reload, publication, activation and restore switch the engine: they take the use case for themselves.
        # Everything else shares it, waits for a switch in progress, and then sees the engine that is in force.
        switching = action in ("reload", "publish-draft") or (
            action == "releases" and len(parts) == 9 and parts[8] in ("activate", "restore"))
        if switching:
            return self._use_case_route(method, parts, query, ws, uc, member, raw_body, body_error)
        gate = ws.gates.setdefault(uc.id, Gate())
        if not gate.enter():
            raise LifecycleError(503, "this use case is being switched to another configuration: retry shortly")
        try:
            return self._use_case_route(method, parts, query, ws, ws.use_cases[uc.id], member, raw_body, body_error)
        finally:
            gate.leave()

    def _use_case_route(self, method: str, parts: List[str], query: str, ws: Workspace, uc: UseCase, member: Member,
                        raw_body: Optional[bytes], body_error: Optional[Tuple[int, str]]) -> Tuple[int, Any]:
        action = parts[6] if len(parts) >= 7 else None
        if action is None and method == "GET":
            return 200, self.use_case_view(uc, member, detail=True)
        if action == "checks" and method == "GET":
            target = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("to", "")
            return 200, self.lifecycle.move(ws.id, uc.id, uc.service, target, member.name, "", dry_run=True,
                                            extra_checks=self._stage_checks(uc))
        if action == "readiness" and method == "GET":
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            return 200, self.readiness_of(ws, uc, member, params.get("target", "pilot"),
                                          unquote(params.get("of", "active")))
        if action == "stage" and method == "POST":
            if not member.workspace_admin:
                raise LifecycleError(403, "workspace administrators only")
            self._require_person(member, "move a use case between stages")
            body = self._json(raw_body, body_error)
            moved = self.lifecycle.move(ws.id, uc.id, uc.service, str(body.get("to") or ""),
                                        f"{member.name}@{ws.id}", str(body.get("reason") or ""),
                                        extra_checks=self._stage_checks(uc))
            return 200, {**moved, "use_case": self.use_case_view(uc, member, detail=True)}
        if action == "sample-data" and len(parts) == 7:
            if method == "GET":
                return 200, self.sample_data(ws, uc, member)
            if method == "POST":
                if not member.workspace_admin:
                    raise LifecycleError(403, "workspace administrators only")
                self._require_person(member, "load sample records")
                body = self._json(raw_body, body_error)
                return 200, self.load_sample_data(ws, uc, member, str(body.get("reason") or ""))
            return 405, {"error": f"{method} is not supported here"}
        if action == "releases":
            return self._releases(method, parts, ws, uc, member, raw_body, body_error)
        if action == "publish-draft" and method == "POST" and len(parts) == 7:
            if not self.may_approve_releases(ws, member):
                raise LifecycleError(403, "only a person with release authority (a workspace administrator or a "
                                          "named release approver) may publish a draft")
            body = self._json(raw_body, body_error)
            return 200, self.publish_draft(ws, uc, member, body.get("revision"), str(body.get("reason") or ""))
        if action == "reload" and method == "POST" and len(parts) == 7:
            if not member.workspace_admin:
                raise LifecycleError(403, "workspace administrators only")
            self._require_person(member, "reload an engine")
            body = self._json(raw_body, body_error)
            fresh = self.reload_use_case(ws, uc, member, str(body.get("reason") or ""))
            return 200, self.use_case_view(fresh, member, detail=True)
        return 404, None

    def _stage_checks(self, uc: UseCase):
        """What the platform adds to a stage's own checks: the active release, and the mandatory readiness
        conditions (REL-2) that neither the stage nor the release already evaluates."""
        def checks(stage: str) -> List[Check]:
            if stage != "pilot":
                return []
            release = self._release_checks(uc)
            known = tuple(readiness.STAGE_CHECKS)  # evaluated by the stage itself and by the release check
            return release + readiness.gate_checks(uc.service, stage, self._readiness_context(uc, release), known)
        return checks

    def _readiness_context(self, uc: UseCase, release: Optional[List[Check]] = None) -> Dict[str, Any]:
        """What only the platform knows about a use case's readiness (autology.readiness)."""
        ws = self.workspaces[uc.workspace]
        waiting = sum(1 for i in self.access_review(ws)["items"] if i["use_case"] == uc.id and i["needs_review"])
        return {"entered_simulation": self.stage_of(uc)["entered_simulation"],
                "release_checks": release if release is not None else self._release_checks(uc),
                "unrestricted_needing_review": waiting,
                # the last recorded rehearsal that covered this use case, or None: evidence is never assumed
                "recovery": self._recovery_evidence(uc)}

    @staticmethod
    def _require_person(member: Member, what: str) -> None:
        if member.kind != "person":
            raise LifecycleError(403, f"{member.name} is a service identity: it cannot {what} (D11)")

    def may_approve_releases(self, ws: Workspace, member: Member) -> bool:
        """Independent approval authority (D11), for releases and grants: a person who is a workspace administrator
        or a named approver."""
        return member.kind == "person" and (member.workspace_admin or member.name in ws.release_approvers)

    @staticmethod
    def _data_access(grant: Optional[Dict[str, Any]]) -> str:
        """How much business data a grant reaches: none (administrative only), scoped (row and field rules
        apply) or unrestricted (the engine's ``admin`` permission: they do not)."""
        perms = set((grant or {}).get("permissions", [])) - {ADMINISTRATIVE}
        return "unrestricted" if UNRESTRICTED in perms else "scoped" if perms else "none"

    def _needs_review(self, record: Dict[str, Any], grant: Dict[str, Any]) -> bool:
        """A grant no person has looked at with full knowledge: created by the IAM-3 migration, or unrestricted
        without the two acknowledgements a proposal and its approval now carry."""
        if record.get("review"):
            return False
        return record["origin"] == "migration" or (self._data_access(grant) == "unrestricted"
                                                   and not record.get("acknowledged"))

    def members_view(self, ws: Workspace, viewer: Optional[Member] = None) -> Dict[str, Any]:
        events, problem = self.admin.events(ws.id)
        api_added = {e["data"]["name"] for e in events if e["event"] == "member_added"}
        view: Dict[str, Any] = {
                "members": [{"name": m.name, "kind": m.kind, "workspace_admin": m.workspace_admin,
                             "tenant_admin": m.tenant_admin,
                             "approver": m.name in ws.release_approvers, "scope": m.scope,
                             "token": ("none" if not m.token_sha256 else "revoked"
                                       if self.credentials.revoked(m.token_sha256) else
                                       "expired" if self._expired(m) else "active"),
                             "token_expires_at": credentials.iso(m.expires_at),
                             # who has seen the token this member holds now (whoever issues a token sees it once)
                             "token_issued_by": ws.token_issuers.get(m.name, "configuration"),
                             "source": "api" if m.name in api_added and m.name not in ws.config_members else
                             "configuration",
                             "use_cases": {uc: m.use_cases[uc] for uc in sorted(m.use_cases)},
                             # what the member may actually do in each use case, administrative role included
                             "effective": {uc: {"permissions": (m.grant(uc) or {"permissions": []})["permissions"],
                                                "data_access": self._data_access(m.grant(uc))}
                                           for uc in sorted(ws.use_cases)}}
                            for m in sorted(ws.members.values(), key=lambda m: m.name)],
                "pending_grants": sorted(pending_grants(events).values(), key=lambda g: g["proposed_at"]),
                "pending_token_requests": sorted(pending_token_requests(events).values(),
                                                 key=lambda r: r["requested_at"]),
                "token_policy": self.token_policy.view(),
                "use_cases": [{"id": uc.id, "name": uc.name} for uc in ws.use_cases.values()],
                "permissions": sorted(PERMISSIONS),
                "history": events, "integrity_problem": problem}
        if viewer is not None:  # what the caller may do here; the platform decides again on every call
            view["you"] = {"member": viewer.name, "may_administer": viewer.workspace_admin and viewer.kind == "person",
                           "may_approve": self.may_approve_releases(ws, viewer)}
        return view

    # What the engine's unrestricted permission is used for in practice (D24). Operational requests are those a
    # future, narrower "operate" permission would cover: they run the engine and read no business record.
    OPERATIONAL = (("POST", ("tick",)), ("POST", ("reporting",)), ("POST", ("agents", "*", "reinstate")),
                   ("POST", ("runs", "*", "write-back")))
    USAGE_WINDOW = 2000  # most recent requests of one identity looked at, per use case

    @classmethod
    def _usage_kind(cls, target: str) -> Optional[str]:
        """``"operational"``, ``"configuration"`` or ``"data"`` for an access-log target such as
        ``"POST /api/v1/tick"``; None for what tells nothing (sign-in, health, the caller's own identity)."""
        method, _, path = target.partition(" ")
        parts = [p for p in path.split("/") if p]
        if parts[:1] == ["api"]:
            parts = parts[1:]
        if parts[:1] == ["v1"]:
            parts = parts[1:]
        if not parts or parts[0] in ("me", "health", "openapi.json", "auth", "ontology", "agents") and method == "GET":
            return None
        for verb, shape in cls.OPERATIONAL:
            if method == verb and len(parts) == len(shape) and all(s in ("*", p) for s, p in zip(shape, parts)):
                return "operational"
        if parts[0] in ("model", "architect", "settings"):
            return "configuration"
        return "data"

    def _admin_usage(self, ws: Workspace, member: str, uc_id: str) -> Dict[str, Any]:
        """How an identity that holds the unrestricted permission on a use case has used the engine, from the
        use case's own access log (successful requests only). Evidence for an access review, not a control."""
        uc = ws.use_cases.get(uc_id)
        usage: Dict[str, Any] = {"operational": 0, "configuration": 0, "data": 0, "last_request_at": None}
        if uc is None or uc.unavailable:
            return usage
        try:
            rows = uc.service.store.access_log(member, limit=self.USAGE_WINDOW)
        except Exception:  # an engine being switched or closed: the review still answers
            return usage
        for row in rows:
            if row["kind"] != "http" or int(row["status"]) >= 400:
                continue
            kind = self._usage_kind(row["target"])
            if kind:
                usage[kind] += 1
                usage["last_request_at"] = usage["last_request_at"] or row["timestamp"]
        return usage

    def access_review(self, ws: Workspace) -> Dict[str, Any]:
        """Every business-data grant of the workspace, where it comes from and whether it still needs a person's
        review (R2 security sprint B): the report an owner reads after the IAM-3 migration, and regularly after."""
        items = []
        for m in sorted(ws.members.values(), key=lambda m: m.name):
            for uc_id in sorted(m.use_cases):
                grant = m.use_cases[uc_id]
                access = self._data_access(grant)
                if access == "none":
                    continue
                rec = ws.grant_records.get((m.name, uc_id)) or {"origin": "configuration", "by": "configuration",
                                                                "approved_by": None, "at": None, "review": None}
                usage = self._admin_usage(ws, m.name, uc_id) if access == "unrestricted" else None
                items.append({"member": m.name, "kind": m.kind, "administrator": m.workspace_admin,
                              # For unrestricted grants: what the access was used for. "narrower_would_do" is true
                              # when every recorded use was operational or configuration work, none of which
                              # needs to read business data: such a holder is a candidate for a narrower grant
                              # (and for the "operate" permission, should the owner approve it: D24).
                              **({"usage": usage, "narrower_would_do": usage["data"] == 0} if usage else {}),
                              "use_case": uc_id, "permissions": sorted(grant["permissions"]),
                              "roles": sorted(grant.get("roles") or []),
                              "reviewer_roles": sorted(grant.get("reviewer_roles") or []),
                              "data_access": access, "origin": rec["origin"], "granted_by": rec["by"],
                              "approved_by": rec["approved_by"], "since": rec["at"], "review": rec.get("review"),
                              "needs_review": self._needs_review(rec, grant)})
        return {"workspace": ws.id, "generated_at": credentials.iso(credentials.now()), "items": items,
                "summary": {"grants": len(items),
                            "unrestricted": sum(i["data_access"] == "unrestricted" for i in items),
                            "administrators_with_data_access": len({i["member"] for i in items if i["administrator"]}),
                            "needs_review": sum(i["needs_review"] for i in items),
                            "unrestricted_without_data_use": sum(bool(i.get("narrower_would_do")) for i in items)},
                "unrestricted_means": list(UNRESTRICTED_MEANS),
                "how_to_resolve": "for each grant that needs review, a person with authority who is not the member "
                                  "either confirms it (POST .../members/<name>/confirm-grant), revokes it "
                                  "(.../revoke), or replaces it with a narrower one (propose a grant, approved by "
                                  "another person)"}

    def _administration(self, method: str, parts: List[str], ws: Workspace, member: Member,
                        raw_body: Optional[bytes], body_error) -> Tuple[int, Any]:
        """``/platform/workspaces/<ws>/members[...]`` and ``/grants[...]`` (ADM-1). Changes apply at once (ADM-2)."""
        from .server import new_token

        who = f"{member.name}@{ws.id}"
        if not (member.workspace_admin or self.may_approve_releases(ws, member)):
            raise LifecycleError(403, "workspace administrators and approvers only")
        if parts[4] == "members" and len(parts) == 5 and method == "GET":
            return 200, self.members_view(ws, member)
        if parts[4] == "access-review" and len(parts) == 5 and method == "GET":
            return 200, self.access_review(ws)
        if parts[4] == "ai" and len(parts) == 5 and method == "GET":
            return 200, self.ai_view(ws)
        if method != "POST":
            return 405, {"error": f"{method} is not supported here"}
        body = self._json(raw_body, body_error)
        reason = str(body.get("reason") or "")
        # what a named approver who is not an administrator may also do: the second person's part of a decision
        second_person = (len(parts) == 7 and ((parts[4] in ("grants", "token-requests") and parts[6] == "approve")
                                              or (parts[4] == "members" and parts[6] == "confirm-grant"))) \
            or (len(parts) == 8 and parts[4] == "ai" and parts[7] == "approve")
        admin_only = not second_person
        if admin_only and not member.workspace_admin:
            raise LifecycleError(403, "workspace administrators only")
        self._require_person(member, "administer the workspace")
        if parts[4] == "recovery-drill" and len(parts) == 5:
            return 200, self.recovery_drill(ws, member, reason)
        if parts[4] == "ai":
            return self._ai_routes(method, parts, ws, member, body, reason)
        if parts[4] == "members" and len(parts) == 5:  # add a member: the token is shown once, only its hash kept
            name, kind = str(body.get("name") or ""), body.get("kind", "person")
            if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", name):
                raise AdminError(400, "name: 1 to 64 letters, digits and _.@-")
            if kind not in ("person", "service"):
                raise AdminError(400, 'kind must be "person" or "service"')
            token, digest = new_token()

            def check_new(events):
                if name in ws.members:
                    raise AdminError(409, f"{name} is already a member")
                tenant = self.tenants[ws.tenant]  # a tenant-level name is one person in the whole tenant (IAM-1)
                if name in tenant.members:
                    raise AdminError(409, f"{name} is already an identity of tenant {tenant.id}: give that person a "
                                          "membership of this workspace in the platform configuration")
            self.admin.append(ws.id, "member_added", who, reason, {"name": name, "kind": kind, "token_sha256": digest},
                              check_new)
            self._refresh(ws)
            return 201, {"name": name, "kind": kind, "token": token,
                         "token_expires_at": credentials.iso(ws.members[name].expires_at),
                         "note": "give this token to the member now: it is not stored and cannot be shown again"}
        if parts[4] == "members" and len(parts) == 7:
            name, action = parts[5], parts[6]
            target = ws.members.get(name)
            if target is None:
                return 404, None
            if target.workspace_admin and action in ("remove", "token"):
                raise AdminError(403, "workspace administrators are managed in the platform configuration only")
            if target.scope == "tenant" and action in ("remove", "token"):
                raise AdminError(403, f"{name} is an identity of the tenant, with memberships in the platform "
                                      "configuration: it is not removed or re-keyed from one workspace")
            if target.workspace_admin and action == "revoke-token":
                raise AdminError(403, "workspace administrators are managed in the platform configuration only")
            if target.scope == "tenant" and action == "revoke-token":
                raise AdminError(403, f"{name} is an identity of the tenant: its token is replaced in the platform "
                                      "configuration")
            if action == "remove":
                self.admin.append(ws.id, "member_removed", who, reason, {"name": name})
                self._retire(target.token_sha256, who, f"member removed: {reason}")
                self._refresh(ws)
                return 200, self.members_view(ws, member)
            if action == "token":
                # Whoever issues a token sees it. For a member who holds business data that would hand their
                # access to the administrator alone, so a second person issues it (D11, D22a); a member without
                # data access is re-keyed at once, as before.
                if any(target.has_data_access(uc) for uc in ws.use_cases):
                    rid = "t-" + new_grant_id()[2:]
                    self.admin.append(ws.id, "token_requested", who, reason, {"id": rid, "name": name})
                    return 202, {"status": "pending", "id": rid, "name": name,
                                 "note": f"{name} holds business-data access: another person with authority issues "
                                         "the token (POST .../token-requests/<id>/approve) and is the only one to "
                                         "see it"}
                return 200, self._rotate(ws, target, who, reason)
            if action == "confirm-grant":
                uc_id = str(body.get("use_case") or "")
                grant = target.use_cases.get(uc_id)
                if grant is None or self._data_access(grant) == "none":
                    raise AdminError(409, f"{name} has no data grant on {uc_id!r}")
                if not self.may_approve_releases(ws, member):
                    raise AdminError(403, "only a person with authority (a workspace administrator or a named "
                                          "approver) confirms a grant")
                if name == member.name:
                    raise AdminError(403, "nobody confirms their own grant: another person with authority must")
                if self._data_access(grant) == "unrestricted" and body.get("unrestricted") is not True:
                    raise AdminError(400, _UNRESTRICTED_HELP)
                self.admin.append(ws.id, "grant_confirmed", who, reason,
                                  {"member": name, "use_case": uc_id, "permissions": sorted(grant["permissions"])})
                self._refresh(ws)
                return 200, self.access_review(ws)
            if action == "revoke-token":
                if not target.token_sha256:
                    raise AdminError(409, f"{name} has no token to revoke")
                self.admin.append(ws.id, "token_revoked", who, reason, {"name": name})
                self._retire(target.token_sha256, who, f"revoked: {reason}")
                self._refresh(ws)
                return 200, self.members_view(ws, member)
            if action == "revoke":
                uc_id = str(body.get("use_case") or "")
                if uc_id not in target.use_cases:
                    raise AdminError(409, f"{name} has no grant on {uc_id!r}")
                self.admin.append(ws.id, "grant_revoked", who, reason, {"member": name, "use_case": uc_id})
                self._refresh(ws)
                return 200, self.members_view(ws, member)
            return 404, None
        if parts[4] == "grants" and len(parts) == 5:  # propose a grant: it takes effect only once approved
            name, uc_id = str(body.get("member") or ""), str(body.get("use_case") or "")
            target, uc = ws.members.get(name), ws.use_cases.get(uc_id)
            if target is None or uc is None:
                raise AdminError(400, "member and use_case must name a member and a use case of this workspace")
            perms = body.get("permissions") or []
            if not isinstance(perms, list) or set(perms) - PERMISSIONS:
                raise AdminError(400, f"permissions: a list of {sorted(PERMISSIONS)}")
            unrestricted = UNRESTRICTED in perms
            if unrestricted and body.get("unrestricted") is not True:  # never by accident, never by default
                raise AdminError(400, _UNRESTRICTED_HELP)
            grant = {"permissions": sorted(set(perms)), "roles": [str(r) for r in body.get("roles") or []],
                     "reviewer_roles": [str(r) for r in body.get("reviewer_roles") or []],
                     "run_as": {str(a): [str(r) for r in rs] for a, rs in (body.get("run_as") or {}).items()}}
            try:  # the engine's own rules (known agents, valid identity) before anything is recorded
                uc.service.parse_users([{"name": name, "token_sha256": target.token_sha256, "kind": target.kind,
                                         **grant}])
            except ValueError as exc:
                raise AdminError(400, str(exc)) from None
            gid = new_grant_id()
            self.admin.append(ws.id, "grant_proposed", who, reason,
                              {"id": gid, "member": name, "use_case": uc_id, "grant": grant,
                               **({"unrestricted": True} if unrestricted else {})})
            return 201, {"id": gid, "member": name, "use_case": uc_id, "grant": grant, "proposed_by": who,
                         "status": "pending", "data_access": self._data_access(grant)}
        if parts[4] == "grants" and len(parts) == 7 and parts[6] in ("approve", "withdraw"):
            gid = parts[5]

            def check(events):
                proposal = pending_grants(events).get(gid)
                if proposal is None:
                    raise AdminError(404, f"no pending grant {gid!r}")
                if parts[6] == "approve":
                    if proposal["proposed_by"] == who:
                        raise AdminError(403, "the proposer cannot approve their own proposal: another person with "
                                              "authority must (D11)")
                    if proposal["member"] == member.name:
                        raise AdminError(403, "nobody approves a grant to themselves")
                    if proposal["member"] not in ws.members or proposal["use_case"] not in ws.use_cases:
                        raise AdminError(409, "the member or the use case no longer exists")
                    if UNRESTRICTED in proposal["grant"]["permissions"] and body.get("unrestricted") is not True:
                        raise AdminError(400, _UNRESTRICTED_HELP)  # the approver acknowledges it too
            acknowledged = {"unrestricted": True} if body.get("unrestricted") is True and parts[6] == "approve" else {}
            self.admin.append(ws.id, "grant_approved" if parts[6] == "approve" else "grant_withdrawn", who, reason,
                              {"id": gid, **acknowledged}, check)
            self._refresh(ws)
            return 200, self.members_view(ws, member)
        if parts[4] == "token-requests" and len(parts) == 7 and parts[6] in ("approve", "withdraw"):
            rid = parts[5]
            request = pending_token_requests(self.admin.events(ws.id)[0]).get(rid)
            if request is None:
                raise AdminError(404, f"no pending token request {rid!r}")

            def check_request(events):
                if rid not in pending_token_requests(events):
                    raise AdminError(404, f"no pending token request {rid!r}")
                if parts[6] == "approve" and request["requested_by"] == who:
                    raise AdminError(403, "the requester cannot issue the token: another person with authority "
                                          "must (D11), so that no single person takes over a member's access")
                if parts[6] == "approve" and request["name"] not in ws.members:
                    raise AdminError(409, "the member no longer exists")
            if parts[6] == "withdraw":
                self.admin.append(ws.id, "token_request_withdrawn", who, reason, {"id": rid}, check_request)
                return 200, self.members_view(ws, member)
            return 200, self._rotate(ws, ws.members[request["name"]] if request["name"] in ws.members else None,
                                     who, reason, check_request, rid)
        return 404, None

    def _retire(self, digest: str, who: str, reason: str) -> None:
        """A token that was replaced, revoked or whose member was removed never works again, wherever it is named."""
        if digest:
            self.credentials.revoke(digest, who, reason)

    def _rotate(self, ws: Workspace, target: Optional[Member], who: str, reason: str, check: Any = None,
                request: Optional[str] = None) -> Dict[str, Any]:
        """Replace a member's token. The identity, its kind and its grants are unchanged; the new token gets one
        lifetime of the policy, never more; the previous token is refused from now on."""
        from .server import new_token

        if target is None:
            raise AdminError(409, "the member no longer exists")
        token, digest = new_token()
        self.admin.append(ws.id, "token_rotated", who, reason,
                          {"name": target.name, "token_sha256": digest, **({"request": request} if request else {})},
                          check)
        self._retire(target.token_sha256, who, f"replaced: {reason}")
        self._refresh(ws)
        return {"name": target.name, "token": token,
                "token_expires_at": credentials.iso(ws.members[target.name].expires_at),
                "note": "the previous token stopped working; this one is shown once"}

    def _own_token(self, ws: Workspace, member: Member, raw_body: Optional[bytes], body_error) -> Tuple[int, Any]:
        """``POST /platform/workspaces/<ws>/my-token``: a person replaces their own token before it expires.
        Not a service identity (an administrator re-keys machines), not a tenant-level identity (configuration),
        and never with an expired or revoked token: that one is refused before it gets here."""
        self._require_person(member, "replace its own token: a workspace administrator issues service tokens")
        if member.scope == "tenant":
            raise AdminError(403, f"{member.name} is an identity of the tenant: its token is replaced in the "
                                  "platform configuration")
        body = self._json(raw_body, body_error)
        return 200, self._rotate(ws, member, f"{member.name}@{ws.id}",
                                 str(body.get("reason") or "replaced by its owner"))

    def _releases(self, method: str, parts: List[str], ws: Workspace, uc: UseCase, member: Member,
                  raw_body: Optional[bytes], body_error) -> Tuple[int, Any]:
        """``.../<uc>/releases[/<n>[/approve|/revoke|/activate]]`` (REL-1a, D11)."""
        who = f"{member.name}@{ws.id}"
        if len(parts) == 7:
            if method == "GET":
                rel = self.release_of(uc)
                may_propose = member.workspace_admin and member.kind == "person"
                may_approve = self.may_approve_releases(ws, member)
                out = {**rel, "may_propose": may_propose, "may_approve": may_approve}
                if may_propose or may_approve:  # who may publish needs the revision to name, and who saved it
                    # a use case that serves nothing (its engine could not be loaded) has no draft to offer now
                    row = None if uc.unavailable else uc.service.store.draft()
                    out["draft"] = {"revision": row["revision"], "author": row["author"]} if row else None
                return 200, out
            if method == "POST":
                if not member.workspace_admin:
                    raise LifecycleError(403, "workspace administrators only")
                self._require_person(member, "propose a release")
                body = self._json(raw_body, body_error)
                note = str(body.get("note") or "").strip()
                if not (1 <= len(note) <= 500):
                    raise ReleaseError(400, "give a note (1 to 500 characters): what this release changes")
                return 201, self.releases.propose(ws.id, uc.id, uc.service.configuration_snapshot, who, note)
            return 405, {"error": f"{method} is not supported here"}
        try:
            number = int(parts[7])
        except ValueError:
            return 404, None
        if len(parts) == 8 and method == "GET":
            from . import solution as solutions

            item = self.releases.release(ws.id, uc.id, number)
            snapshot = self.releases.snapshot(ws.id, uc.id, number)
            # what the release contains, part by part, and whether it is coherent: fingerprints and counts only
            problems = solutions.release_problems(snapshot)
            components = solutions.release_components(snapshot)
            item = {**item, "components": components,
                    "verification": {"fingerprint_matches": fingerprint_of(snapshot or {}) == item["fingerprint"],
                                     "coherent": not problems, "problems": problems,
                                     "by": "the engine, from the release's own snapshot"}}
            if components["ai"] and components["ai"]["provider"] != "sandbox":
                # whether the workspace's policy, as it stands now, would serve what this release names
                item["ai_standing"] = self._ai_fit(ws, components["ai"])
            if member.workspace_admin or self.may_approve_releases(ws, member):  # the full snapshot: reviewers only
                item = {**item, "snapshot": snapshot}
            return 200, item
        if len(parts) != 9 or method != "POST" or parts[8] not in ("approve", "revoke", "activate", "restore"):
            return 404, None
        if parts[8] == "restore":
            if not member.workspace_admin:
                raise LifecycleError(403, "workspace administrators only")
            self._require_person(member, "restore a release")
            body = self._json(raw_body, body_error)
            return 200, self.restore_release(ws, uc, member, number, str(body.get("reason") or ""))
        body = self._json(raw_body, body_error)
        reason = str(body.get("reason") or "")
        if parts[8] == "approve":
            if not self.may_approve_releases(ws, member):
                raise LifecycleError(403, "only a person with release authority (a workspace administrator or a "
                                          "named release approver) may approve a release")

            def check_approve(item, st):
                if item["proposed_by"] == who:
                    raise ReleaseError(403, "the proposer cannot approve their own release: another person with "
                                            "release authority must (D11)")
                if item["status"] in ("approved", "active", "superseded") and item["approved_by"]:
                    raise ReleaseError(409, f"release {item['number']} is already approved by {item['approved_by']}")
            return 200, self.releases.record(ws.id, uc.id, number, "approved", who, reason, check_approve)
        if parts[8] == "revoke":
            def check_revoke(item, st):
                if not item["approved_by"]:
                    raise ReleaseError(409, f"release {item['number']} is not approved")
                if item["status"] in ("active", "superseded"):
                    raise ReleaseError(409, f"release {item['number']} was activated: roll back to another release "
                                            "instead of revoking its approval")
                if item["approved_by"] != who and not member.workspace_admin:
                    raise ReleaseError(403, "only the approver or a workspace administrator may revoke an approval")
            self._require_person(member, "revoke a release approval")
            return 200, self.releases.record(ws.id, uc.id, number, "approval_revoked", who, reason, check_revoke)
        if not member.workspace_admin:
            raise LifecycleError(403, "workspace administrators only")
        self._require_person(member, "activate a release")
        return 200, self.activate_release(ws, uc, member, number, reason)

    @staticmethod
    def _run_configuration(uc: UseCase, run_id: str) -> str:
        stored = uc.service.store.load_run(run_id)
        run = getattr(stored, "run", None)
        return getattr(run, "configuration", "") if run is not None else ""

    def start_background(self) -> None:
        """Start every use case's scheduler; use cases created later start when they are created."""
        with self._lock:
            self.running = True
            self._stops = []
            for ws in self.workspaces.values():
                for uc in ws.use_cases.values():
                    uc.stop = uc.service.start_background()
                    self._stops.append(uc.stop)

    def stop_background(self) -> None:
        with self._lock:
            self.running = False
            for s in self._stops:
                s.set()
            self._stops = []

    def handle(self, method: str, raw_path: str, headers: Any, raw_body: Optional[bytes] = None,
               body_error: Optional[Tuple[int, str]] = None,
               client: Optional[str] = None) -> Tuple[int, str, bytes, Dict[str, str]]:
        """One request through the router: (status, content type, body, extra headers). ``/platform/v1/...`` is
        served by the same handlers as ``/platform/...`` with the v1 envelope (docs/api-versioning.md)."""
        from .openapi import versioned_response

        split = urlsplit(raw_path)
        version = None
        if split.path == "/platform/v1" or split.path.startswith("/platform/v1/"):
            version = "1"
            raw_path = "/platform" + raw_path[len("/platform/v1"):]
        status, ctype, data, extra = self._handle(method, raw_path, headers, raw_body, body_error, client or "-")
        path = urlsplit(raw_path).path
        if path.startswith("/platform/"):
            data, more = versioned_response(version, method, path, {}, status, ctype, data)
            if not version:
                more["Link"] = f'</platform/v1{path[len("/platform"):]}>; rel="successor-version"'
            extra = {**extra, **more}
        elif path.startswith("/w/") and "Link" in extra:
            # the engine names its successor relative to its own root; behind the router that root is /w/<ws>/u/<uc>
            prefix = "/".join(path.split("/")[:5])
            extra = {**extra, "Link": extra["Link"].replace("</api/", f"<{prefix}/api/", 1)}
        elif path.startswith("/w/") and "/api/v1/" in path + "/":
            # refusals made by the router itself (unknown or foreign workspace, wrong token) use the v1 envelope
            # too, identically for every refused case; engine answers are already in it and pass unchanged
            data, more = versioned_response("1", method, path, {}, status, ctype, data)
            extra = {**extra, **more}
        return status, ctype, data, extra

    def _too_many(self, who: Optional[Member], method: str, path: str, wait: int,
                  what: str) -> Tuple[int, str, bytes, Dict[str, str]]:
        self._log(who, method, path, 429)
        return 429, "application/json", json.dumps(limits.too_many(wait, what)).encode(), {"Retry-After": str(wait)}

    def _handle(self, method: str, raw_path: str, headers: Any, raw_body: Optional[bytes] = None,
                body_error: Optional[Tuple[int, str]] = None,
                client: str = "-") -> Tuple[int, str, bytes, Dict[str, str]]:
        split = urlsplit(raw_path)
        path = split.path
        if method == "GET" and path in ("/platform/health", "/platform/openapi.json"):
            wait = self.limiter.hit("anonymous", client)
            if wait:
                return self._too_many(None, method, path, wait, "requests without a credential from this address")
        if method == "GET" and path == "/platform/health":
            return 200, "application/json", json.dumps({"status": "ok"}).encode(), {}
        if method == "GET" and path == "/platform/openapi.json":  # the platform's contract: no data, no token
            from .openapi import platform_spec

            return 200, "application/json", json.dumps(platform_spec()).encode(), {}
        # an address that failed to authenticate too often is refused before its credential is looked at, so the
        # answer tells nothing about a guessed token (GAP-030)
        wait = self.limiter.blocked("auth_failures", client)
        if wait:
            return self._too_many(None, method, path, wait, "failed sign-ins from this address")
        members = self.members_for(headers.get("Authorization"))  # the identity, per workspace it belongs to
        parts = path.split("/")
        # /w/<ws>/u/<uc>/api/...  ->  ['', 'w', ws, 'u', uc, 'api', ...]
        ok = (len(parts) >= 7 and parts[1] == "w" and parts[3] == "u" and parts[5] == "api"
              and ID.match(parts[2] or "") and ID.match(parts[4] or "") and ".." not in parts)
        ws = self.workspaces.get(parts[2]) if ok else None
        uc = ws.use_cases.get(parts[4]) if ws else None
        member = members.get(ws.id) if ws else next(iter(members.values()), None)
        if not members and uc is not None and ws.oidc:
            # not a member token: only this workspace's own sign-in provider may vouch for it (ISO-3). The use
            # case's engine verifies it against that issuer and its mappings; anything else is refused there.
            inner = "/" + "/".join(parts[5:]) + (f"?{split.query}" if split.query else "")
            assert ws is not None  # uc is one of its use cases
            return self._engine(ws, uc.id, None, method, path, inner, headers, raw_body, body_error, client, False)
        if not members:
            self.limiter.hit("auth_failures", client)
            whose, why = self.refused_token(headers.get("Authorization"))
            self._log(whose if why else None, method, path, 401)
            body = {"error": why, "reason": "token_expired" if "expired" in why else "token_revoked"} if why else {
                "error": "missing or invalid token"}
            return 401, "application/json", json.dumps(body).encode(), {}
        anyone = next(iter(members.values()))  # for the access log when the request names no workspace of theirs
        # Every authenticated request is counted here, once, whatever it asks for and however it is answered
        # (a refusal counts too): per identity in the workspace it names, and per tenant (GAP-030).
        counted = member or anyone
        who = f"{counted.workspace}:{counted.name}"
        for name, key, what in (("api", who, f"requests by {counted.name}"),
                                ("tenant", counted.tenant, "requests of this tenant"),
                                ("admin", who, f"administrative changes by {counted.name}")):
            if name == "admin" and not (method == "POST" and path.startswith("/platform/")):
                continue
            wait = self.limiter.hit(name, key)
            if wait:
                return self._too_many(counted, method, path, wait, what)
        if path == "/platform/me" and method == "GET":
            wanted = dict(p.split("=", 1) for p in split.query.split("&") if "=" in p).get("workspace")
            chosen = members.get(wanted) if wanted else anyone
            if chosen is None:  # not a workspace of theirs: the same answer as for any unknown one
                self._log(anyone, method, path, 404)
                return 404, "application/json", NOT_FOUND, {}
            return 200, "application/json", json.dumps(self.me(chosen, members)).encode(), {}
        if len(parts) >= 3 and parts[1] == "platform" and ".." not in parts:
            member = members.get(parts[3]) if len(parts) >= 4 and parts[2] == "workspaces" else None
            try:
                status, out = self._manage(member, method, parts, split.query, raw_body, body_error, members)
            except LifecycleError as exc:
                status, out = exc.status, {"error": str(exc), **({"checks": exc.checks} if exc.checks else {})}
            except (ReleaseError, AdminError) as exc:
                status, out = exc.status, {"error": str(exc)}
            if method != "GET" or status >= 400:
                self._log(member or anyone, method, path, status)
            if out is None:
                return 404, "application/json", NOT_FOUND, {}
            if status == 503:
                out["retry_after_seconds"] = 2
            return status, "application/json", json.dumps(out).encode(), ({"Retry-After": "2"} if status == 503
                                                                          else {})
        if uc is None or member is None or not member.grant(uc.id):
            self._log(member or anyone, method, path, 404)
            return 404, "application/json", NOT_FOUND, {}
        inner = "/" + "/".join(parts[5:]) + (f"?{split.query}" if split.query else "")
        assert ws is not None  # uc is one of its use cases
        return self._engine(ws, uc.id, member, method, path, inner, headers, raw_body, body_error, client, True)

    def _engine(self, ws: Workspace, uc_id: str, member: Optional[Member], method: str, path: str, inner: str,
                headers: Any, raw_body: Optional[bytes], body_error: Optional[Tuple[int, str]], client: str,
                counted: bool) -> Tuple[int, str, bytes, Dict[str, str]]:
        """One request to a use case's engine. It shares the use case with other requests; while the engine is
        being switched (a release activated, a reload) it waits, then is served by the engine in force: a request
        never sees a configuration that is half in place."""
        gate = ws.gates.setdefault(uc_id, Gate())
        if not gate.enter():
            return self._unavailable(member, method, path,
                                     "this use case is being switched to another configuration: retry shortly")
        try:
            uc = ws.use_cases[uc_id]
            if uc.unavailable:
                return self._unavailable(member, method, path, f"this use case is unavailable: {uc.unavailable}")
            ex = ApiExchange(uc.service, method, inner, headers, raw_body, body_error, client, counted=counted).run()
            if member is None:  # a company sign-in: the engine identified the caller, the router records the call
                self._log(None, method, path, ex.status)
            return ex.status, ex.content_type, ex.data, ex.response_headers
        finally:
            gate.leave()

    def _unavailable(self, who: Optional[Member], method: str, path: str,
                     message: str) -> Tuple[int, str, bytes, Dict[str, str]]:
        self._log(who, method, path, 503)
        return 503, "application/json", json.dumps({"error": message, "retry_after_seconds": 2}).encode(), {
            "Retry-After": "2"}

    def close(self) -> None:
        """Close every engine and registry (after the server stopped)."""
        for svc in self.services():
            svc.close()
        for part in (self.lifecycle, self.releases, self.admin, self.tenancy, self.credentials, self.log,
                     self.ai_ledger):
            part.close()

    def _log(self, member: Optional[Member], method: str, path: str, status: int) -> None:
        try:
            who = f"{member.name}@{member.workspace}" if member else "anonymous"
            self.log.log_access(who, "platform", f"{method} {path}"[:500], status)
        except Exception:  # logging must never break a response
            log.exception("writing the platform access log failed")

    def services(self) -> List[AutologyService]:
        with self._lock:
            return [uc.service for ws in self.workspaces.values() for uc in ws.use_cases.values()]


def make_platform_server(platform: Platform, host: str = "127.0.0.1", port: int = 8700) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "Autology"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass

        def _respond(self, method: str) -> None:
            raw, error = read_body(self.headers, self.rfile, method)
            client = limits.client_address(self.client_address[0], self.headers.get("X-Forwarded-For"),
                                           platform.trusted_proxies)
            status, ctype, data, extra = platform.handle(method, self.path, self.headers, raw, error, client)
            self.send_response(status)
            self.send_header("Content-Type", ctype if "charset" in ctype else ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for k, v in extra.items():
                if k not in ("X-Content-Type-Options", "Cache-Control"):
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            self._respond("GET")

        def do_POST(self):  # noqa: N802
            self._respond("POST")

        def _not_allowed(self):
            data = json.dumps({"error": f"{self.command} is not supported"}).encode()
            self.send_response(405)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed  # noqa: N815

    return limits.BoundedHTTPServer((host, port), Handler, platform.server_limits["max_connections"],
                                    platform.server_limits["request_timeout"])


def serve(path: str, host: str = "127.0.0.1", port: int = 8700) -> None:  # pragma: no cover - blocking
    import signal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    platform = Platform.from_file(path)
    server = make_platform_server(platform, host, port)
    platform.start_background()

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    for ws in platform.workspaces.values():
        print(f"workspace {ws.id}: {len(ws.members)} members, use cases "
              + ", ".join(f"{uc.id} ({uc.service.ontology.ref})" for uc in ws.use_cases.values()), flush=True)
    print(f"Autology platform on http://{host}:{server.server_port} (data in {platform.data_dir})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        platform.stop_background()
        server.server_close()
        platform.close()
