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
  single-engine server, so every permission, rule and the use case's access log apply).

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

from .server import ApiExchange, AutologyService, PERMISSIONS, hash_token, read_body
from .store import Store

log = logging.getLogger("autology.platform")
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
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

    def grant(self, use_case: str) -> Optional[Dict[str, Any]]:
        if self.workspace_admin:
            return {"permissions": ["admin"], "roles": [], "reviewer_roles": []}
        return self.use_cases.get(use_case)


@dataclass
class UseCase:
    id: str
    workspace: str
    name: str
    service: AutologyService


@dataclass
class Workspace:
    id: str
    name: str
    members: Dict[str, Member] = field(default_factory=dict)
    use_cases: Dict[str, UseCase] = field(default_factory=dict)
    oidc: Optional[Dict[str, Any]] = None  # the workspace's own company sign-in (ISO-3)
    env_prefix: str = ""  # the only environment variables (credentials) its configuration may name (ISO-4)


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
        self.workspaces: Dict[str, Workspace] = {}
        self._tokens: Dict[str, Member] = {}
        for ws_id, ws_spec in (spec.get("workspaces") or {}).items():
            self._load_workspace(ws_id, ws_spec, base_dir)
        if not self.workspaces:
            raise PlatformError("the platform has no workspaces")

    @classmethod
    def from_file(cls, path: str) -> "Platform":
        p = Path(path).resolve()
        return cls(json.loads(p.read_text(encoding="utf-8")), p.parent)

    def _load_workspace(self, ws_id: str, spec: Dict[str, Any], base_dir: Path) -> None:
        if not ID.match(ws_id):
            raise PlatformError(f"workspace id {ws_id!r}: lowercase letters, digits and '-' only")
        ws = Workspace(ws_id, str(spec.get("name") or ws_id), oidc=dict(spec["oidc"]) if spec.get("oidc") else None,
                       env_prefix=str(spec.get("env_prefix") or ws_id.upper().replace("-", "_") + "_"))
        for i, m in enumerate(spec.get("members") or []):
            where = f"workspace {ws_id} member {m.get('name', i)}"
            name = str(m.get("name") or "")
            if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", name) or name in ws.members:
                raise PlatformError(f"{where}: a unique name of letters, digits and _.@- is required")
            digest = _token_digest(m, where)
            if digest in self._tokens:  # a token must identify exactly one person in exactly one workspace
                raise PlatformError(f"{where}: this token is already used by another member")
            grants = {}
            for uc, g in (m.get("use_cases") or {}).items():
                perms = set(g.get("permissions") or [])
                if perms - PERMISSIONS:
                    raise PlatformError(f"{where}: unknown permissions {sorted(perms - PERMISSIONS)}")
                grants[uc] = {"permissions": sorted(perms), "roles": list(g.get("roles") or []),
                              "reviewer_roles": list(g.get("reviewer_roles") or []),
                              "run_as": {a: list(r) for a, r in (g.get("run_as") or {}).items()}}
            member = Member(name, ws_id, digest, bool(m.get("workspace_admin")), grants)
            ws.members[name] = member
            self._tokens[digest] = member
        for uc_id, uc_spec in (spec.get("use_cases") or {}).items():
            if not ID.match(uc_id):
                raise PlatformError(f"use case id {uc_id!r}: lowercase letters, digits and '-' only")
            ws.use_cases[uc_id] = self._load_use_case(ws, uc_id, uc_spec, base_dir)
        for member in ws.members.values():
            unknown = set(member.use_cases) - set(ws.use_cases)
            if unknown:
                raise PlatformError(f"workspace {ws_id} member {member.name}: unknown use cases {sorted(unknown)}")
        self.workspaces[ws_id] = ws

    def _load_use_case(self, ws: Workspace, uc_id: str, spec: Dict[str, Any], base_dir: Path) -> UseCase:
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
        config.pop("oidc", None)  # a use case's own sign-in setting never applies: the workspace's does
        if ws.oidc:
            config["oidc"] = dict(ws.oidc)
        config.pop("log_file", None)
        reporting = config.get("reporting")
        if isinstance(reporting, dict) and isinstance(reporting.get("target"), str):
            reporting["target"] = str(home / "reporting.db")
        config["secrets_file"] = str(self.data_dir / ws.id / "secrets.json")
        config["audit_scope"] = ws.id  # the workspace's own audit key, derived from the platform's (ISO-2)
        users = []
        for member in ws.members.values():
            grant = member.grant(uc_id)
            if grant:
                users.append({"name": member.name, "token_sha256": member.token_sha256, **grant})
        config["users"] = users
        service = AutologyService(config, config_path.parent)
        return UseCase(uc_id, ws.id, str(spec.get("name") or uc_id), service)

    # -- requests --------------------------------------------------------------------------------------------
    def member_for(self, authorization: Optional[str]) -> Optional[Member]:
        if not authorization or not authorization.startswith("Bearer "):
            return None
        return self._tokens.get(hash_token(authorization[7:].strip()))

    def me(self, member: Member) -> Dict[str, Any]:
        ws = self.workspaces[member.workspace]
        return {"workspace": {"id": ws.id, "name": ws.name}, "member": member.name,
                "workspace_admin": member.workspace_admin,
                "use_cases": [{"id": uc.id, "name": uc.name, "ontology": uc.service.ontology.ref,
                               "permissions": member.grant(uc.id)["permissions"],
                               "path": f"/w/{ws.id}/u/{uc.id}"}
                              for uc in ws.use_cases.values() if member.grant(uc.id)]}

    def handle(self, method: str, raw_path: str, headers: Any, raw_body: Optional[bytes] = None,
               body_error: Optional[Tuple[int, str]] = None) -> Tuple[int, str, bytes, Dict[str, str]]:
        """One request through the router: (status, content type, body, extra headers)."""
        split = urlsplit(raw_path)
        path = split.path
        if method == "GET" and path == "/platform/health":
            return 200, "application/json", json.dumps({"status": "ok"}).encode(), {}
        member = self.member_for(headers.get("Authorization"))
        parts = path.split("/")
        # /w/<ws>/u/<uc>/api/...  ->  ['', 'w', ws, 'u', uc, 'api', ...]
        ok = (len(parts) >= 7 and parts[1] == "w" and parts[3] == "u" and parts[5] == "api"
              and ID.match(parts[2] or "") and ID.match(parts[4] or "") and ".." not in parts)
        ws = self.workspaces.get(parts[2]) if ok else None
        uc = ws.use_cases.get(parts[4]) if ws else None
        if member is None and uc is not None and ws.oidc:
            # not a member token: only this workspace's own sign-in provider may vouch for it (ISO-3). The use
            # case's engine verifies it against that issuer and its mappings; anything else is refused there.
            inner = "/" + "/".join(parts[5:]) + (f"?{split.query}" if split.query else "")
            ex = ApiExchange(uc.service, method, inner, headers, raw_body, body_error).run()
            self._log(None, method, path, ex.status)
            return ex.status, ex.content_type, ex.data, ex.response_headers
        if member is None:
            self._log(None, method, path, 401)
            return 401, "application/json", json.dumps({"error": "missing or invalid token"}).encode(), {}
        if path == "/platform/me" and method == "GET":
            return 200, "application/json", json.dumps(self.me(member)).encode(), {}
        if uc is None or ws.id != member.workspace or not member.grant(uc.id):
            self._log(member, method, path, 404)
            return 404, "application/json", NOT_FOUND, {}
        inner = "/" + "/".join(parts[5:]) + (f"?{split.query}" if split.query else "")
        ex = ApiExchange(uc.service, method, inner, headers, raw_body, body_error).run()
        return ex.status, ex.content_type, ex.data, ex.response_headers

    def _log(self, member: Optional[Member], method: str, path: str, status: int) -> None:
        try:
            who = f"{member.name}@{member.workspace}" if member else "anonymous"
            self.log.log_access(who, "platform", f"{method} {path}"[:500], status)
        except Exception:  # logging must never break a response
            log.exception("writing the platform access log failed")

    def services(self) -> List[AutologyService]:
        return [uc.service for ws in self.workspaces.values() for uc in ws.use_cases.values()]


def make_platform_server(platform: Platform, host: str = "127.0.0.1", port: int = 8700) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "Autology"
        sys_version = ""

        def log_message(self, fmt, *args):
            pass

        def _respond(self, method: str) -> None:
            raw, error = read_body(self.headers, self.rfile, method)
            status, ctype, data, extra = platform.handle(method, self.path, self.headers, raw, error)
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

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def serve(path: str, host: str = "127.0.0.1", port: int = 8700) -> None:  # pragma: no cover - blocking
    import signal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    platform = Platform.from_file(path)
    server = make_platform_server(platform, host, port)
    stops = [svc.start_background() for svc in platform.services()]

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
        for s in stops:
            s.set()
        server.server_close()
        for svc in platform.services():
            svc.close()
        platform.log.close()
