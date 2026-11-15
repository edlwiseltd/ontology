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
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from . import credentials, limits
from .audit import audit_key, workspace_key
from .lifecycle import Check, Lifecycle, LifecycleError, STAGES
from .administration import AdminError, AdminLog, new_grant_id, pending_grants
from .releases import ReleaseError, ReleaseRegistry
from .server import ApiExchange, AutologyService, PERMISSIONS, hash_token, read_body
from .store import Store
from .tenancy import Tenancy, TenancyError

log = logging.getLogger("autology.platform")
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ADMINISTRATIVE = "configure"  # the engine permission an administrative role carries; never business data (IAM-3)
ONTOLOGY_OVERRIDE = "ontology.json"  # in <data_dir>/<ws>/<uc>/: this use case's own ontology (published or restored)
NOT_FOUND = json.dumps({"error": "not found"}).encode()


class PlatformError(ValueError):
    pass


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
        self.workspaces: Dict[str, Workspace] = {}
        self.tenants: Dict[str, Tenant] = {}
        # token digest -> {workspace: Member}: one identity, with one Member per workspace it explicitly belongs to
        self._tokens: Dict[str, Dict[str, Member]] = {}
        self._identities: Dict[str, Tuple[str, str]] = {}  # token digest -> (tenant, name): one identity, one tenant
        self._base_dir = base_dir
        self._lock = threading.RLock()
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
        if problem:  # fail closed: only the configured administrators keep access until an operator repairs it
            ws.members = {n: m for n, m in members.items() if m.workspace_admin}
            self._stamp(ws.members.values())
            return
        proposals: Dict[str, Dict[str, Any]] = {}
        for e in events:
            d = e["data"]
            if e["event"] == "member_added":
                members[d["name"]] = Member(d["name"], ws.id, d["token_sha256"], False, {}, d["kind"], ws.tenant)
            elif e["event"] == "member_removed":
                members.pop(d["name"], None)
            elif e["event"] == "token_rotated" and d["name"] in members:
                members[d["name"]].token_sha256 = d["token_sha256"]
                members[d["name"]].token_expires = None  # an explicit date was about the configured token
            elif e["event"] == "token_revoked" and d["name"] in members:
                members[d["name"]].token_sha256 = ""  # no credential until an administrator issues a new one
            elif e["event"] == "grant_proposed":
                proposals[d["id"]] = d
            elif e["event"] == "grant_approved":
                p = proposals.pop(d["id"], None)
                if p and p["member"] in members:
                    members[p["member"]].use_cases[p["use_case"]] = p["grant"]
            elif e["event"] == "grant_withdrawn":
                proposals.pop(d["id"], None)
            elif e["event"] == "grant_migrated" and d["member"] in members:
                have = members[d["member"]].use_cases.get(d["use_case"])
                members[d["member"]].use_cases[d["use_case"]] = d["grant"] if have is None else {
                    **have, "permissions": sorted(set(have["permissions"]) | set(d["grant"]["permissions"]))}
            elif e["event"] == "grant_revoked" and d["member"] in members:
                members[d["member"]].use_cases.pop(d["use_case"], None)
        self._stamp(members.values())
        ws.members = members

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
                       validate_only: bool = False) -> UseCase:
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
        override = home / ONTOLOGY_OVERRIDE
        if override.is_file():  # a Studio draft published to this use case, or a release's ontology restored
            config["ontology"] = str(override)
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
        config["credentials_file"] = ""  # the platform supplies each token's expiry (one registry for all engines)
        config["security"] = dict(self._security)
        if validate_only:  # build a throwaway engine on an in-memory store: proves the files load, touches nothing
            config.update({"store": ":memory:", "secrets_file": str(home / ".validate-secrets.json")})
            probe = AutologyService(config, config_path.parent)
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
        return uc

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
                        event: str, data: Dict[str, Any]) -> UseCase:
        """Write this use case's own ontology and reload its engine; if the result does not load, the previous file
        (or its absence) is put back and nothing changes."""
        path = self.data_dir / ws.id / uc.id / ONTOLOGY_OVERRIDE
        previous = path.read_bytes() if path.is_file() else None
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(document, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        try:
            fresh = self.reload_use_case(ws, uc, member, reason)
        except LifecycleError:
            if previous is None:
                path.unlink()
            else:
                path.write_bytes(previous)
            raise
        self.admin.append(ws.id, event, f"{member.name}@{ws.id}", reason,
                          {**data, "use_case": uc.id, "configuration": fresh.service.configuration_fingerprint})
        return fresh

    def publish_draft(self, ws: Workspace, uc: UseCase, member: Member, revision: Any, reason: str) -> Dict[str, Any]:
        """Make a saved, valid Studio draft this use case's ontology (STU-6). Publishing changes the configuration:
        with an active release, nothing runs until a release of the new configuration is approved by another
        person and activated."""
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
        fresh = self._write_override(ws, uc, row["document"], member, reason, "draft_published", {"revision": revision})
        return {**self.use_case_view(fresh, member, detail=True), "published_revision": revision}

    def restore_release(self, ws: Workspace, uc: UseCase, member: Member, number: int, reason: str) -> Dict[str, Any]:
        """Put a release's ontology back as this use case's ontology and reload (a rollback of the model). The
        release can then be activated if everything else it covers is unchanged too."""
        snapshot = self.releases.snapshot(ws.id, uc.id, number)
        if snapshot is None:
            raise ReleaseError(404, f"no release {number}")
        if not isinstance(snapshot.get("ontology"), dict) or "entities" not in snapshot["ontology"]:
            raise ReleaseError(409, f"release {number} has no ontology document to restore")
        release = self.releases.release(ws.id, uc.id, number)
        if not release["approved_by"] and release["status"] not in ("active", "superseded"):
            # only a model another person already approved comes back without a second look (IAM-3, GAP-061)
            raise ReleaseError(409, f"release {number} was never approved: its model cannot be restored; have the "
                                    "release approved first, or publish the model as a draft")
        fresh = self._write_override(ws, uc, snapshot["ontology"], member, reason, "release_restored",
                                     {"release": number})
        release = self.releases.release(ws.id, uc.id, number)
        return {**self.use_case_view(fresh, member, detail=True),
                "matches_release": release["fingerprint"] == fresh.service.configuration_fingerprint}

    def reload_use_case(self, ws: Workspace, uc: UseCase, member: Member, reason: str) -> UseCase:
        """Reload one engine from its configuration files without restarting the platform (ADM-2). The files are
        first loaded into a throwaway engine; only if that works is the running engine replaced. A reload is not
        an activation: if a release is active and the files changed, the use case counts as draft until a person
        activates an approved release of what now runs (REL-1a)."""
        reason = (reason or "").strip()
        if not (1 <= len(reason) <= 500):
            raise LifecycleError(400, "give a reason (1 to 500 characters)")
        with self._lock:
            before = uc.service.configuration_fingerprint
            try:
                after = self._load_use_case(ws, uc.id, uc.spec, self._base_dir, validate_only=True)
            except (PlatformError, ValueError, OSError) as exc:
                raise LifecycleError(400, f"the configuration does not load, nothing was changed: {exc}") from None
            if uc.stop is not None:
                uc.stop.set()
            uc.service.close()
            fresh = self._load_use_case(ws, uc.id, uc.spec, self._base_dir)
            fresh.origin, fresh.template = uc.origin, uc.template
            ws.use_cases[uc.id] = fresh
            if self.running:
                fresh.stop = fresh.service.start_background()
                self._stops.append(fresh.stop)
            self.admin.append(ws.id, "engine_reloaded", f"{member.name}@{ws.id}", reason,
                              {"use_case": uc.id, "from": before, "to": after})
        return fresh

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
        if len(parts) >= 5 and parts[2] == "workspaces" and parts[4] in ("members", "grants"):
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
        if action is None and method == "GET":
            return 200, self.use_case_view(uc, member, detail=True)
        if action == "checks" and method == "GET":
            target = dict(p.split("=", 1) for p in query.split("&") if "=" in p).get("to", "")
            return 200, self.lifecycle.move(ws.id, uc.id, uc.service, target, member.name, "", dry_run=True,
                                            extra_checks=self._stage_checks(uc))
        if action == "stage" and method == "POST":
            if not member.workspace_admin:
                raise LifecycleError(403, "workspace administrators only")
            self._require_person(member, "move a use case between stages")
            body = self._json(raw_body, body_error)
            moved = self.lifecycle.move(ws.id, uc.id, uc.service, str(body.get("to") or ""),
                                        f"{member.name}@{ws.id}", str(body.get("reason") or ""),
                                        extra_checks=self._stage_checks(uc))
            return 200, {**moved, "use_case": self.use_case_view(uc, member, detail=True)}
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
        return lambda stage: self._release_checks(uc) if stage == "pilot" else []

    @staticmethod
    def _require_person(member: Member, what: str) -> None:
        if member.kind != "person":
            raise LifecycleError(403, f"{member.name} is a service identity: it cannot {what} (D11)")

    def may_approve_releases(self, ws: Workspace, member: Member) -> bool:
        """Independent approval authority (D11), for releases and grants: a person who is a workspace administrator
        or a named approver."""
        return member.kind == "person" and (member.workspace_admin or member.name in ws.release_approvers)

    def members_view(self, ws: Workspace) -> Dict[str, Any]:
        events, problem = self.admin.events(ws.id)
        api_added = {e["data"]["name"] for e in events if e["event"] == "member_added"}
        return {"members": [{"name": m.name, "kind": m.kind, "workspace_admin": m.workspace_admin,
                             "approver": m.name in ws.release_approvers, "scope": m.scope,
                             "token": ("none" if not m.token_sha256 else "revoked"
                                       if self.credentials.revoked(m.token_sha256) else
                                       "expired" if self._expired(m) else "active"),
                             "token_expires_at": credentials.iso(m.expires_at),
                             "source": "api" if m.name in api_added and m.name not in ws.config_members else
                             "configuration",
                             "use_cases": {uc: m.use_cases[uc] for uc in sorted(m.use_cases)}}
                            for m in sorted(ws.members.values(), key=lambda m: m.name)],
                "pending_grants": sorted(pending_grants(events).values(), key=lambda g: g["proposed_at"]),
                "token_policy": self.token_policy.view(),
                "history": events, "integrity_problem": problem}

    def _administration(self, method: str, parts: List[str], ws: Workspace, member: Member,
                        raw_body: Optional[bytes], body_error) -> Tuple[int, Any]:
        """``/platform/workspaces/<ws>/members[...]`` and ``/grants[...]`` (ADM-1). Changes apply at once (ADM-2)."""
        from .server import new_token

        who = f"{member.name}@{ws.id}"
        if not (member.workspace_admin or self.may_approve_releases(ws, member)):
            raise LifecycleError(403, "workspace administrators and approvers only")
        if parts[4] == "members" and len(parts) == 5 and method == "GET":
            return 200, self.members_view(ws)
        if method != "POST":
            return 405, {"error": f"{method} is not supported here"}
        body = self._json(raw_body, body_error)
        reason = str(body.get("reason") or "")
        admin_only = not (parts[4] == "grants" and len(parts) == 7 and parts[6] == "approve")
        if admin_only and not member.workspace_admin:
            raise LifecycleError(403, "workspace administrators only")
        self._require_person(member, "administer the workspace")
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
                return 200, self.members_view(ws)
            if action == "token":
                return 200, self._rotate(ws, target, who, reason)
            if action == "revoke-token":
                if not target.token_sha256:
                    raise AdminError(409, f"{name} has no token to revoke")
                self.admin.append(ws.id, "token_revoked", who, reason, {"name": name})
                self._retire(target.token_sha256, who, f"revoked: {reason}")
                self._refresh(ws)
                return 200, self.members_view(ws)
            if action == "revoke":
                uc_id = str(body.get("use_case") or "")
                if uc_id not in target.use_cases:
                    raise AdminError(409, f"{name} has no grant on {uc_id!r}")
                self.admin.append(ws.id, "grant_revoked", who, reason, {"member": name, "use_case": uc_id})
                self._refresh(ws)
                return 200, self.members_view(ws)
            return 404, None
        if parts[4] == "grants" and len(parts) == 5:  # propose a grant: it takes effect only once approved
            name, uc_id = str(body.get("member") or ""), str(body.get("use_case") or "")
            target, uc = ws.members.get(name), ws.use_cases.get(uc_id)
            if target is None or uc is None:
                raise AdminError(400, "member and use_case must name a member and a use case of this workspace")
            perms = body.get("permissions") or []
            if not isinstance(perms, list) or set(perms) - PERMISSIONS:
                raise AdminError(400, f"permissions: a list of {sorted(PERMISSIONS)}")
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
                              {"id": gid, "member": name, "use_case": uc_id, "grant": grant})
            return 201, {"id": gid, "member": name, "use_case": uc_id, "grant": grant, "proposed_by": who,
                         "status": "pending"}
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
            self.admin.append(ws.id, "grant_approved" if parts[6] == "approve" else "grant_withdrawn", who, reason,
                              {"id": gid}, check)
            self._refresh(ws)
            return 200, self.members_view(ws)
        return 404, None

    def _retire(self, digest: str, who: str, reason: str) -> None:
        """A token that was replaced, revoked or whose member was removed never works again, wherever it is named."""
        if digest:
            self.credentials.revoke(digest, who, reason)

    def _rotate(self, ws: Workspace, target: Member, who: str, reason: str) -> Dict[str, Any]:
        """Replace a member's token. The identity, its kind and its grants are unchanged; the new token gets one
        lifetime of the policy, never more; the previous token is refused from now on."""
        from .server import new_token

        token, digest = new_token()
        self.admin.append(ws.id, "token_rotated", who, reason, {"name": target.name, "token_sha256": digest})
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
                return 200, {**rel, "may_propose": member.workspace_admin and member.kind == "person",
                             "may_approve": self.may_approve_releases(ws, member)}
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
            item = self.releases.release(ws.id, uc.id, number)
            if member.workspace_admin or self.may_approve_releases(ws, member):  # the full snapshot: reviewers only
                item = {**item, "snapshot": self.releases.snapshot(ws.id, uc.id, number)}
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
        running = uc.service.configuration_fingerprint
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
        event = {"kind": "activated"}

        def check_activate(item, st):
            if not item["approved_by"]:
                raise ReleaseError(409, f"release {item['number']} is not approved: another person with release "
                                        "authority must approve it first")
            if item["status"] == "active":
                raise ReleaseError(409, f"release {item['number']} is already active")
            if item["fingerprint"] != running:
                raise ReleaseError(409, f"the engine runs configuration {running[:12]}, not release {item['number']} "
                                        f"({item['fingerprint'][:12]}): deploy that release's configuration and "
                                        "restart, then activate it")
            active = st["active"]
            if active and active["number"] > item["number"]:
                event["kind"] = "rolled_back"

        st = self.releases.state(ws.id, uc.id)
        previous = st["active"]
        target = next((i for i in st["items"] if i["number"] == number), None)
        if target and previous and previous["number"] > number:
            event["kind"] = "rolled_back"
        out = self.releases.record(ws.id, uc.id, number, event["kind"], who, reason, check_activate)
        # runs started on another configuration never continue on this one (WorkAgent.resume, AutologyService.decide)
        waiting = [r["run_id"] for r in uc.service.store.list_runs(limit=10 ** 6)
                   if r["status"] in ("awaiting_review", "deferred", "paused", "pending_confirmation")]
        stopped = [rid for rid in waiting if self._run_configuration(uc, rid) not in ("", running)]
        # run identifiers are execution evidence: listed only for someone who may read this use case's data (IAM-3)
        return 200, {**out, "event": event["kind"], "runs_on_other_configurations_count": len(stopped),
                     "runs_on_other_configurations": stopped if member.has_data_access(uc.id) else []}

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
            ex = ApiExchange(uc.service, method, inner, headers, raw_body, body_error, client).run()
            self._log(None, method, path, ex.status)
            return ex.status, ex.content_type, ex.data, ex.response_headers
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
            return status, "application/json", json.dumps(out).encode(), {}
        if uc is None or member is None or not member.grant(uc.id):
            self._log(member or anyone, method, path, 404)
            return 404, "application/json", NOT_FOUND, {}
        inner = "/" + "/".join(parts[5:]) + (f"?{split.query}" if split.query else "")
        ex = ApiExchange(uc.service, method, inner, headers, raw_body, body_error, client, counted=True).run()
        return ex.status, ex.content_type, ex.data, ex.response_headers

    def close(self) -> None:
        """Close every engine and registry (after the server stopped)."""
        for svc in self.services():
            svc.close()
        for part in (self.lifecycle, self.releases, self.admin, self.tenancy, self.credentials, self.log):
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
