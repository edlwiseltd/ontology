"""Studio (interim shell): a separate application that reaches the platform over HTTP only (R2 slice).

Acceptance criteria (planning/AUTOLOGY_R2_SLICE_REPORT.md):
  S1 Studio does not import the engine package, and the engine does not import Studio
  S2 Studio forwards only GET and POST under /platform/ and /w/, with Authorization and Content-Type only, never
     follows redirects, bounds bodies and answers 502 when the platform is down
  S3 the page is served with a strict Content-Security-Policy and loads no inline script, and its script never
     inserts platform data as HTML
  S4 a workspace administrator can list use cases, create one from a template and move it Draft -> Simulation
     through Studio, and every refusal is the platform's
"""

import ast
import http.client
import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from studio.server import CSP, Studio, forwardable, make_studio, normalise_platform

from .helpers import ROOT
from .test_r2_use_case_lifecycle import close, make_platform
from .test_workspaces import Client

STUDIO = ROOT / "studio"


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


class Upstream:
    """A stand-in platform that records what reached it."""

    def __init__(self):
        seen = self.seen = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                seen.append((self.command, self.path, dict(self.headers.items()), body))
                if self.path.startswith("/platform/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "http://example.invalid/")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = b'{"ok": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer  # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def serve_studio(platform_url):
    server = make_studio(platform_url, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_port


def call(port, method, path, token=None, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    h = dict(headers or {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=h)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    try:
        return r.status, json.loads(raw), dict(r.getheaders())
    except ValueError:
        return r.status, raw, dict(r.getheaders())


class SeparationTests(unittest.TestCase):
    def test_studio_never_imports_the_engine_and_the_engine_never_imports_studio(self):  # S1
        files = sorted(STUDIO.glob("*.py"))
        self.assertGreaterEqual(len(files), 3)
        for f in files:
            self.assertNotIn("autology", imports(f), f.name)
        for f in sorted((ROOT / "autology").glob("*.py")):
            self.assertNotIn("studio", imports(f), f.name)

    def test_studio_is_not_shipped_inside_the_engine_package(self):  # S1
        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertIn('packages = ["autology"]', pyproject)
        self.assertNotIn("studio", pyproject)

    def test_the_platform_url_must_be_a_base_url(self):
        self.assertEqual(normalise_platform(" http://127.0.0.1:8700/ "), "http://127.0.0.1:8700")
        for bad in ("ftp://x", "http://", "http://h/w/acme", "http://h?x=1", "file:///etc/passwd"):
            with self.assertRaises(ValueError):
                normalise_platform(bad)


class ForwardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = Upstream()
        cls.server, cls.port = serve_studio(cls.up.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.up.server.shutdown()
        cls.up.server.server_close()

    def test_only_platform_and_use_case_paths_are_forwarded(self):  # S2
        table = {("GET", "/platform/me"): True, ("POST", "/platform/workspaces/a/use-cases"): True,
                 ("GET", "/w/a/u/b/api/health"): True, ("GET", "/api/health"): False, ("GET", "/admin"): False,
                 ("GET", "/platform/../api"): False, ("GET", "/w//u"): False, ("GET", "/w/a\\b"): False,
                 ("PUT", "/platform/me"): False, ("DELETE", "/w/a/u/b/api/x"): False}
        for (method, path), expected in table.items():
            self.assertEqual(forwardable(method, path), expected, (method, path))
        before = len(self.up.seen)
        self.assertEqual(call(self.port, "GET", "/api/health")[0], 404)
        self.assertEqual(call(self.port, "PUT", "/platform/me")[0], 405)
        self.assertEqual(Studio(self.up.url).forward("GET", "/elsewhere", {}, None)[0], 404)
        self.assertEqual(len(self.up.seen), before)  # nothing reached the platform

    def test_only_authorization_and_content_type_are_passed_on(self):  # S2
        status, out, _ = call(self.port, "POST", "/platform/x?y=1", "tok", {"a": 1},
                              headers={"Cookie": "session=1", "X-Forwarded-For": "1.2.3.4", "X-Custom": "z"})
        self.assertEqual((status, out), (200, {"ok": True}))
        method, path, headers, body = self.up.seen[-1]
        self.assertEqual((method, path, body), ("POST", "/platform/x?y=1", b'{"a": 1}'))
        lower = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(lower["authorization"], "Bearer tok")
        self.assertEqual(lower["content-type"], "application/json")
        self.assertFalse({"cookie", "x-forwarded-for", "x-custom"} & set(lower))

    def test_redirects_are_not_followed_and_bodies_are_bounded(self):  # S2
        self.assertEqual(call(self.port, "GET", "/platform/redirect")[0], 302)
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/platform/x")
        conn.putheader("Content-Length", "-1")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 411)
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/platform/x")
        conn.putheader("Content-Length", str(2_000_000))
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()

    def test_an_unreachable_platform_is_a_502(self):  # S2
        dead = Studio("http://127.0.0.1:9", timeout=2)
        status, _, data = dead.forward("GET", "/platform/me", {}, None)
        self.assertEqual((status, json.loads(data)["error"]), (502, "the platform at http://127.0.0.1:9 cannot be "
                                                                     "reached"))

    def test_the_page_has_a_strict_policy_and_no_inline_script(self):  # S3
        status, html, headers = call(self.port, "GET", "/")
        self.assertEqual((status, headers["Content-Security-Policy"]), (200, CSP))
        self.assertIn("script-src 'self'", CSP)
        self.assertNotIn("unsafe", CSP)
        html = html.decode()
        self.assertFalse(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html))
        self.assertFalse(re.search(r"\son[a-z]+=", html))  # no inline event handlers
        self.assertNotIn("style=", html)
        js = call(self.port, "GET", "/studio.js")
        self.assertEqual(js[0], 200)
        script = js[1].decode()
        for unsafe in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(unsafe, script)
        self.assertEqual(call(self.port, "GET", "/studio.css")[0], 200)
        self.assertEqual(call(self.port, "GET", "/studio/info")[1]["platform"], self.up.url)


class EndToEndTests(unittest.TestCase):  # S4
    def setUp(self):
        self.pf = make_platform()
        self.platform = Client(self.pf)
        self.server, self.port = serve_studio(self.platform.base)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.platform.server.shutdown()
        self.platform.server.server_close()
        close(self.pf)

    def test_an_administrator_manages_use_cases_and_stages_through_studio(self):
        status, me, _ = call(self.port, "GET", "/platform/me", "acme-ada")
        self.assertEqual((status, me["workspace"]["id"], me["workspace_admin"]), (200, "acme", True))
        _, listing, _ = call(self.port, "GET", "/platform/workspaces/acme/use-cases", "acme-ada")
        self.assertEqual({u["id"]: u["stage"] for u in listing["items"]}, {"claims": "draft", "orders": "draft"})
        _, templates, _ = call(self.port, "GET", "/platform/templates", "acme-ada")
        status, uc, _ = call(self.port, "POST", "/platform/workspaces/acme/use-cases", "acme-ada",
                             {"id": "claims-pilot", "name": "Claims pilot", "template": templates["items"][0]["id"]})
        self.assertEqual((status, uc["stage"]), (201, "draft"))
        _, checks, _ = call(self.port, "GET", "/platform/workspaces/acme/use-cases/claims-pilot/checks?to=simulation",
                            "acme-ada")
        self.assertTrue(checks["allowed"])
        status, moved, _ = call(self.port, "POST", "/platform/workspaces/acme/use-cases/claims-pilot/stage",
                                "acme-ada", {"to": "simulation", "reason": "first simulation"})
        self.assertEqual((status, moved["use_case"]["stage"]), (200, "simulation"))
        # the use case itself is reachable through Studio's forwarding of /w/
        self.assertEqual(call(self.port, "GET", "/w/acme/u/claims-pilot/api/health", "acme-ada")[0], 200)

    def test_every_refusal_is_the_platform_s(self):
        self.assertEqual(call(self.port, "GET", "/platform/me")[0], 401)
        self.assertEqual(call(self.port, "POST", "/platform/workspaces/acme/use-cases/claims/stage", "acme-hana",
                              {"to": "simulation", "reason": "x"})[:2], (403, {"error": "workspace administrators only"}))
        self.assertEqual(call(self.port, "POST", "/platform/workspaces/acme/use-cases/claims/stage", "acme-ada",
                              {"to": "production", "reason": "x"})[0], 403)
        self.assertEqual(call(self.port, "GET", "/platform/workspaces/acme/use-cases", "nw-nadia")[:2],
                         (404, {"error": "not found"}))


if __name__ == "__main__":
    unittest.main()
