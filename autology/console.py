"""Autology Console: a separate, conversational UI for talking to an Autology engine.

    python -m autology console --engine http://127.0.0.1:8800 [--host 127.0.0.1] [--port 8900]

The console is its own small web server, on its own address, separate from the engine and from the engine's
review inbox. It serves a single-page app and forwards ``/api/...`` requests to the engine, unchanged, so the
browser talks to one origin (no CORS) and the engine sees an ordinary API client:

* it holds no credentials and no state: the person's API token (or single sign-on token) stays in their browser
  tab and is passed through on each request; every permission, row and field rule is the engine's;
* it forwards only ``GET`` and ``POST`` under ``/api/``, with ``Authorization`` and ``Content-Type`` and nothing
  else; it never follows redirects; bodies are limited to 1 MB with a valid ``Content-Length``;
* if the engine cannot be reached it answers ``502`` with a JSON error.

In the app, people talk to the engine in plain language (through the engine's governed assistant when one is
configured) or with commands such as ``/ask CQ-01``, ``/run CL-4``, ``/explain <run id>`` and ``/reviews``;
without an assistant, plain language is matched to the ontology's own questions, objects and goals.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import __version__

log = logging.getLogger("autology.console")

STATIC = Path(__file__).resolve().parent / "console_static"
FILES = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
         "/console.js": ("console.js", "application/javascript"),
         "/commands.js": ("commands.js", "application/javascript"),
         "/console.css": ("console.css", "text/css")}
MAX_BODY = 1_000_000
TIMEOUT = 120.0  # the assistant may take a while to answer
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - never follow redirects
        return None


def normalise_engine(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"engine must be an http(s) URL, got {url!r}")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("engine must be the server's base URL, e.g. http://127.0.0.1:8800")
    return f"{parsed.scheme}://{parsed.netloc}"


class Console:
    """The forwarding logic, independent of HTTP serving (so it can be tested directly)."""

    def __init__(self, engine: str, timeout: float = TIMEOUT):
        self.engine = normalise_engine(engine)
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect())

    def info(self) -> Dict[str, Any]:
        return {"console": __version__, "engine": self.engine}

    def forward(self, method: str, path_and_query: str, headers: Dict[str, str],
                body: Optional[bytes]) -> Tuple[int, str, bytes]:
        """Send one API request to the engine; returns (status, content type, body)."""
        if method not in ("GET", "POST"):
            return 405, "application/json", json.dumps({"error": f"{method} is not forwarded"}).encode()
        path = urllib.parse.urlsplit(path_and_query).path
        if not path.startswith("/api/") or ".." in path or "//" in path:
            return 404, "application/json", json.dumps({"error": "not found"}).encode()
        out_headers = {k: v for k, v in headers.items() if k.lower() in ("authorization", "content-type")}
        req = urllib.request.Request(self.engine + path_and_query, data=body if method == "POST" else None,
                                     method=method, headers=out_headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.status, resp.headers.get("Content-Type", "application/json"), resp.read()
        except urllib.error.HTTPError as exc:  # the engine answered with an error status: pass it on as-is
            data = exc.read() if exc.fp else b""
            return exc.code, exc.headers.get("Content-Type", "application/json"), data
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("engine %s unreachable: %s", self.engine, exc)
            return 502, "application/json", json.dumps(
                {"error": f"the engine at {self.engine} cannot be reached"}).encode()


def _handler(console: Console):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AutologyConsole"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet: the engine keeps the access log
            pass

        def _send(self, status: int, ctype: str, data: bytes) -> None:
            self.send_response(status)
            charset = "; charset=utf-8" if ctype.split(";")[0] in ("text/html", "text/css", "application/javascript",
                                                                     "application/json") and "charset" not in ctype \
                else ""
            self.send_header("Content-Type", ctype + charset)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if ctype == "text/html":
                self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, message: str) -> None:
            self._send(status, "application/json", json.dumps({"error": message}).encode())

        def _route(self, method: str) -> None:
            path = urllib.parse.urlsplit(self.path).path
            if method == "GET" and path in FILES:
                name, ctype = FILES[path]
                return self._send(200, ctype, (STATIC / name).read_bytes())
            if method == "GET" and path == "/console/info":
                return self._send(200, "application/json", json.dumps(console.info()).encode())
            if not path.startswith("/api/"):
                return self._error(404, "not found")
            body = None
            if method == "POST":
                raw = self.headers.get("Content-Length")
                if raw is None or not raw.strip().isdigit():  # also refuses negative lengths
                    return self._error(411, "a valid Content-Length is required")
                length = int(raw)
                if length > MAX_BODY:
                    return self._error(413, "request body too large")
                body = self.rfile.read(length)
            headers = {k: v for k, v in self.headers.items()}
            status, ctype, data = console.forward(method, self.path, headers, body)
            self._send(status, ctype, data)

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

        def _not_allowed(self):
            self._error(405, f"{self.command} is not supported")

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed  # noqa: N815

    return Handler


def make_console(engine: str, host: str = "127.0.0.1", port: int = 8900) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _handler(Console(engine)))
    server.daemon_threads = True
    return server


def serve(engine: str, host: str = "127.0.0.1", port: int = 8900) -> None:  # pragma: no cover - blocking
    import signal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = make_console(engine, host, port)

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"Autology Console on http://{host}:{server.server_port}, talking to the engine at "
          f"{normalise_engine(engine)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
