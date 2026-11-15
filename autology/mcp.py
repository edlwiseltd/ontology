"""MCP interface: the governed ontology as tools for any Model Context Protocol client.

    AUTOLOGY_TOKEN=... python -m autology mcp server.json

The server speaks MCP over stdio (newline-delimited JSON-RPC 2.0), standard library only. It signs in
as the user whose API token is in ``AUTOLOGY_TOKEN`` (or ``--token-env NAME``) and offers exactly the
tools the governed assistant gets (:func:`autology.chat.tools_for`), so the same guarantees hold:

* every call runs as that user: permissions, row access and field access apply;
* ``start_run`` only records a proposal, which the person confirms in the inbox;
* nothing can decide a human review;
* values the deployment marks as not for model providers (``chat_redact``, default confidential) are
  withheld, because the MCP client is a model;
* every call is written to the access log as ``mcp.tool``.

**Next to a running platform (GAP-018).** A use case served by the platform is reached through the platform's
own authenticated API, never by opening its store a second time (one writer per store, MOD-4):

* MCP clients that speak HTTP post JSON-RPC messages to ``<platform>/w/<workspace>/u/<use case>/api/mcp``
  with the member's token (JSON responses; no server-sent events);
* stdio clients run ``python -m autology mcp --url <platform>/w/<workspace>/u/<use case>``, a relay that holds
  no store and forwards each message to that endpoint.

Either way the router resolves the token to one member of one workspace and the use case's engine applies
every permission, rule and execution gate; another workspace or an ungranted use case answers 404.
Serving a platform file directly (``mcp platform.json --use-case``) opens the use case's store, so it is
refused while the platform server runs.

Example client configuration (Claude Desktop, Claude Code and others)::

    {"mcpServers": {"autology": {"command": "python", "args": ["-m", "autology", "mcp", "/path/server.json"],
                                 "env": {"AUTOLOGY_TOKEN": "atl_..."}}}}
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, IO, Optional

from . import __version__

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = ("Tools over an Autology ontology: business objects, governed agent runs, reviews and what-if "
                "scenarios. Calls run as one signed-in person and see only what that person may see. Starting a "
                "run only proposes it; the person confirms it in the Autology inbox. Reviews are decided by "
                "people in the inbox, never through these tools.")


class McpServer:
    def __init__(self, service: Any, user: Any):
        from .chat import redacted_refs, tools_for

        self.service = service
        self.user = user
        self.tools = {t["name"]: t for t in tools_for(service, user)}
        self.refs = redacted_refs(service)

    def handle(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """One JSON-RPC message in, the response out (None for notifications)."""
        method, mid = message.get("method"), message.get("id")
        if mid is None:  # a notification (initialized, cancelled...): nothing to answer
            return None
        try:
            if method == "initialize":
                asked = (message.get("params") or {}).get("protocolVersion")
                result: Dict[str, Any] = {
                    "protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[1],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "autology", "version": __version__},
                    "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [{"name": t["name"], "description": t["description"],
                                     "inputSchema": t["input_schema"]} for t in self.tools.values()]}
            elif method == "tools/call":
                params = message.get("params") or {}
                result = self.call(str(params.get("name")), params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method!r}"}}
        except Exception as exc:  # never let one bad request end the session
            self.service.log_error(f"MCP {method}")
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": type(exc).__name__}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from .chat import redact_for_provider
        from .server import ApiError

        tool = self.tools.get(name)
        status, error = 200, False
        try:
            if tool is None:
                raise ApiError(404, f"no tool {name!r} for {self.user.name}")
            if not isinstance(arguments, dict):
                raise ApiError(400, "arguments must be an object")
            payload = redact_for_provider(self.service, tool["run"](arguments), self.refs)
            text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
        except ApiError as exc:
            status, error, text = exc.status, True, f"error {exc.status}: {exc.message}"
        except (KeyError, TypeError, ValueError) as exc:
            status, error, text = 400, True, f"invalid arguments: {exc}"
        self.service.log_access(self.user, "mcp.tool", name, status)
        return {"content": [{"type": "text", "text": text}], "isError": error}

    def serve(self, reader: IO[str], writer: IO[str]) -> None:
        for line in reader:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                response: Optional[Dict[str, Any]] = {"jsonrpc": "2.0", "id": None,
                                                      "error": {"code": -32700, "message": "parse error"}}
            else:
                if isinstance(message, list):  # batches are not part of current MCP; answer each
                    for item in message:
                        out = self.handle(item) if isinstance(item, dict) else None
                        if out:
                            writer.write(json.dumps(out) + "\n")
                    writer.flush()
                    continue
                response = self.handle(message) if isinstance(message, dict) else {
                    "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
            if response is not None:
                writer.write(json.dumps(response) + "\n")
                writer.flush()


def relay(url: str, token: str, reader: IO[str], writer: IO[str], timeout: float = 120.0) -> int:
    """Forward MCP messages from stdio to a use case's ``/api/mcp`` endpoint behind the platform router. Opens no
    store: the platform's own process is the only writer. Never follows redirects."""
    import urllib.error
    import urllib.request

    from .console import _NoRedirect, normalise_engine

    try:
        base = normalise_engine(url)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    opener = urllib.request.build_opener(_NoRedirect())
    for line in reader:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            writer.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700,
                                                                            "message": "parse error"}}) + "\n")
            writer.flush()
            continue
        mid = message.get("id") if isinstance(message, dict) else None
        req = urllib.request.Request(base + "/api/mcp", data=line.encode(), method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
            "Accept": "application/json"})
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = resp.read()
                answer = json.loads(data) if resp.status == 200 and data else None
        except urllib.error.HTTPError as exc:
            detail = (json.loads(exc.read() or b"{}") or {}).get("error", "") if exc.fp else ""
            answer = None if mid is None else {"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32001, "message": f"the platform refused the request ({exc.code}) {detail}".strip()}}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            answer = None if mid is None else {"jsonrpc": "2.0", "id": mid, "error": {
                "code": -32002, "message": "the platform cannot be reached"}}
        if answer is not None:
            writer.write(json.dumps(answer) + "\n")
            writer.flush()
    return 0


def run(config_path: str, token_env: str = "AUTOLOGY_TOKEN", reader: IO[str] = sys.stdin,
        writer: IO[str] = sys.stdout, use_case: Optional[str] = None, workspace: Optional[str] = None) -> int:
    """Serve one engine over stdio. With a platform file (``platform.json``) the token must be a member's, and
    ``use_case`` names one of that member's use cases in their own workspace (ISO-1): nothing else is reachable."""
    import json
    import logging
    import os
    from pathlib import Path

    from .server import ApiError, AutologyService

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)  # stdout carries the protocol only
    token = os.environ.get(token_env)
    if not token:
        print(f"set {token_env} to an Autology API token", file=sys.stderr)
        return 2
    if "workspaces" in json.loads(Path(config_path).read_text(encoding="utf-8")):
        from .platform import Platform

        if not use_case:
            print("a platform file serves one use case: give --use-case", file=sys.stderr)
            return 2
        from .store import StoreError

        try:
            platform = Platform.from_file(config_path)
        except (StoreError, ValueError) as exc:  # e.g. the platform server holds the store: never a second writer
            print(f"{exc}\nWhile the platform server runs, serve MCP through it: "
                  "python -m autology mcp --url <platform>/w/<workspace>/u/<use case>", file=sys.stderr)
            return 2
        # the token's own memberships only (IAM-1): another tenant's or an ungranted use case is never a candidate
        found = [(platform.workspaces[w], m) for w, m in platform.members_for(f"Bearer {token}").items()
                 if (workspace is None or w == workspace) and use_case in platform.workspaces[w].use_cases
                 and m.grant(use_case)]
        if len(found) > 1:
            print(f"this token reaches use case {use_case} in several workspaces "
                  f"({', '.join(ws.id for ws, _ in found)}): give --workspace", file=sys.stderr)
            return 2
        if not found:  # the same answer for a bad token and a foreign use case
            print("sign-in failed: no such use case for this token", file=sys.stderr)
            return 2
        uc = found[0][0].use_cases[use_case]
        service = uc.service
    else:
        service = AutologyService.from_file(config_path)
    try:
        user = service.authenticate(f"Bearer {token}")
    except ApiError as exc:
        print(f"sign-in failed: {exc.message}", file=sys.stderr)
        return 2
    McpServer(service, user).serve(reader, writer)
    return 0
