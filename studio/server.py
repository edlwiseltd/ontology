"""Studio's own small web server: static files, and forwarding of platform API calls.

    python -m studio --platform http://127.0.0.1:8700 [--host 127.0.0.1] [--port 8950]

* It serves the Studio single-page app and forwards **only** ``GET`` and ``POST`` requests under ``/platform/``
  and ``/w/`` to the platform, so the browser talks to one origin (no CORS). Everything else is ``404``.
* It holds no credentials and no state: the person's API token stays in their browser tab and is passed through
  on each request with ``Content-Type``; no other header is forwarded. Every permission, check and stage rule is
  the platform's: Studio decides nothing.
* It never follows redirects; request bodies need a valid ``Content-Length`` and are limited to 1 MB; when the
  platform cannot be reached it answers ``502`` with a JSON error.
* HTML is served with a strict Content-Security-Policy (no inline scripts or styles, same-origin connections).

It does not import the engine package: Studio and the engine share nothing but the HTTP API.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import __version__

log = logging.getLogger("studio")

STATIC = Path(__file__).resolve().parent / "static"
FILES = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
         "/studio.js": ("studio.js", "application/javascript"), "/studio.css": ("studio.css", "text/css")}
FORWARDED_PREFIXES = ("/platform/", "/w/")
FORWARDED_HEADERS = ("authorization", "content-type")
MAX_BODY = 1_000_000
TIMEOUT = 60.0
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - never follow redirects
        return None


def normalise_platform(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"platform must be an http(s) URL, got {url!r}")
    if parsed.path.strip("/") or parsed.query or parsed.fragment:
        raise ValueError("platform must be the platform's base URL, e.g. http://127.0.0.1:8700")
    return f"{parsed.scheme}://{parsed.netloc}"


def forwardable(method: str, path: str) -> bool:
    return (method in ("GET", "POST") and path.startswith(FORWARDED_PREFIXES) and ".." not in path
            and "//" not in path and "\\" not in path)


class Studio:
    """The forwarding logic, independent of HTTP serving (so it can be tested directly)."""

    def __init__(self, platform: str, timeout: float = TIMEOUT):
        self.platform = normalise_platform(platform)
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect())

    def info(self) -> Dict[str, str]:
        return {"studio": __version__, "platform": self.platform}

    def forward(self, method: str, path_and_query: str, headers: Dict[str, str],
                body: Optional[bytes]) -> Tuple[int, str, bytes]:
        path = urllib.parse.urlsplit(path_and_query).path
        if not forwardable(method, path):
            return 404, "application/json", json.dumps({"error": "not found"}).encode()
        out = {k: v for k, v in headers.items() if k.lower() in FORWARDED_HEADERS}
        req = urllib.request.Request(self.platform + path_and_query, data=body if method == "POST" else None,
                                     method=method, headers=out)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.status, resp.headers.get("Content-Type", "application/json"), resp.read()
        except urllib.error.HTTPError as exc:  # the platform answered with an error status: pass it on as-is
            return exc.code, exc.headers.get("Content-Type", "application/json"), exc.read() if exc.fp else b""
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.warning("platform %s unreachable: %s", self.platform, exc)
            return 502, "application/json", json.dumps(
                {"error": f"the platform at {self.platform} cannot be reached"}).encode()


def _handler(studio: Studio):
    class Handler(BaseHTTPRequestHandler):
        server_version = "AutologyStudio"
        sys_version = ""

        def log_message(self, fmt, *args):  # quiet: the platform keeps the access log
            pass

        def _send(self, status: int, ctype: str, data: bytes) -> None:
            self.send_response(status)
            if ctype.split(";")[0] in ("text/html", "text/css", "application/javascript", "application/json") \
                    and "charset" not in ctype:
                ctype += "; charset=utf-8"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if ctype.startswith("text/html"):
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
            if method == "GET" and path == "/studio/info":
                return self._send(200, "application/json", json.dumps(studio.info()).encode())
            if not forwardable(method, path):
                return self._error(404, "not found")
            body = None
            if method == "POST":
                raw = self.headers.get("Content-Length")
                if raw is None or not raw.strip().isdigit():  # also refuses negative lengths
                    return self._error(411, "a valid Content-Length is required")
                if int(raw) > MAX_BODY:
                    return self._error(413, "request body too large")
                body = self.rfile.read(int(raw))
            status, ctype, data = studio.forward(method, self.path, dict(self.headers.items()), body)
            self._send(status, ctype, data)

        def do_GET(self):  # noqa: N802
            self._route("GET")

        def do_POST(self):  # noqa: N802
            self._route("POST")

        def _not_allowed(self):
            self._error(405, f"{self.command} is not supported")

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _not_allowed  # noqa: N815

    return Handler


def make_studio(platform: str, host: str = "127.0.0.1", port: int = 8950) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _handler(Studio(platform)))
    server.daemon_threads = True
    return server


def serve(platform: str, host: str = "127.0.0.1", port: int = 8950) -> None:  # pragma: no cover - blocking
    import signal

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = make_studio(platform, host, port)

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"Autology Studio (interim shell) on http://{host}:{server.server_port}, platform "
          f"{normalise_platform(platform)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
