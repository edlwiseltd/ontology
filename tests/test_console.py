"""The Autology Console: a separate UI that talks to the engine only through its public API."""

import http.client
import json
import shutil
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autology.console import Console, make_console, normalise_engine

from .helpers import ROOT
from .test_ingest import TOKENS, service as insurance_service
from .test_platform import _Api

NODE = shutil.which("node")
STATIC = ROOT / "autology" / "console_static"


class ConsoleProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = insurance_service(automations={})
        cls.engine = _Api(cls.svc)
        cls.console = make_console(cls.engine.base, "127.0.0.1", 0)
        threading.Thread(target=cls.console.serve_forever, daemon=True).start()
        cls.port = cls.console.server_port

    @classmethod
    def tearDownClass(cls):
        cls.console.shutdown()
        cls.engine.server.shutdown()

    def call(self, method, path, token=None, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = dict(headers or {})
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            hdrs.setdefault("Content-Type", "application/json")
            hdrs.setdefault("Content-Length", str(len(data)))
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        ctype = resp.getheader("Content-Type") or ""
        return resp.status, (json.loads(payload) if "json" in ctype and payload else payload.decode()), resp

    def test_serves_the_app_with_a_strict_policy(self):
        status, page, resp = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Autology Console", page)
        self.assertIn("script-src 'self'", resp.getheader("Content-Security-Policy"))
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        for name in ("console.js", "commands.js", "console.css"):
            self.assertEqual(self.call("GET", "/" + name)[0], 200)
        status, info, _ = self.call("GET", "/console/info")
        self.assertEqual((status, info["engine"]), (200, self.engine.base))
        self.assertNotIn("innerHTML", (STATIC / "console.js").read_text().replace("never innerHTML", ""))

    def test_talks_to_the_engine_as_the_signed_in_person(self):
        status, me, _ = self.call("GET", "/api/me", TOKENS["hana"])
        self.assertEqual((status, me["name"]), (200, "hana"))
        status, onto, _ = self.call("GET", "/api/ontology", TOKENS["hana"])
        self.assertIs(onto["assistant"], False)  # the console knows up front to match plain language itself
        self.assertEqual(self.call("GET", "/api/me")[0], 401)  # no token: the engine refuses, the console passes it on
        self.assertEqual(self.call("GET", "/api/me", "wrong")[0], 401)
        status, answer, _ = self.call("POST", "/api/questions/CQ-03", TOKENS["hana"], {"params": {}})
        self.assertEqual((status, answer["answer"]), (200, ["CL-3"]))
        status, run, _ = self.call("POST", "/api/runs", TOKENS["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual((status, run["status"]), (200, "completed"))
        status, view, _ = self.call("GET", f"/api/runs/{run['run_id']}", TOKENS["hana"])
        self.assertEqual([s["action"] for s in view["steps"]], ["assess_fraud", "approve_claim", "pay_claim"])
        # the engine's own rules still apply: no review permission, no reviews
        self.assertEqual(self.call("GET", "/api/reviews?status=pending", TOKENS["hana"])[0], 403)
        self.assertEqual(self.call("GET", "/api/chat/none", TOKENS["hana"])[0], 404)
        status, err, _ = self.call("POST", "/api/chat", TOKENS["hana"], {"message": "hello"})
        self.assertEqual(status, 404)  # no assistant configured: the console falls back to matching
        self.assertIn("not configured", err["error"])

    def test_forwards_only_api_requests(self):
        self.assertEqual(self.call("GET", "/etc/passwd")[0], 404)
        self.assertEqual(self.call("GET", "/api/../console/info")[0], 404)
        self.assertEqual(self.call("DELETE", "/api/me", TOKENS["admin"])[0], 405)
        self.assertEqual(self.call("PUT", "/api/objects", TOKENS["admin"], {})[0], 405)

    def test_request_bodies_are_bounded(self):
        status, _, _ = self.call("POST", "/api/questions/CQ-01", TOKENS["hana"], raw=b"{}",
                                 headers={"Content-Length": "-1"})
        self.assertEqual(status, 411)  # a negative length must not mean "read until the client stops"
        status, _, _ = self.call("POST", "/api/questions/CQ-01", TOKENS["hana"], raw=b"{}",
                                 headers={"Content-Length": "abc"})
        self.assertEqual(status, 411)
        status, _, _ = self.call("POST", "/api/questions/CQ-01", TOKENS["hana"], raw=b"x" * 10,
                                 headers={"Content-Length": "2000000"})
        self.assertEqual(status, 413)

    def test_unreachable_engine_and_bad_urls(self):
        down = make_console("http://127.0.0.1:9", "127.0.0.1", 0)
        threading.Thread(target=down.serve_forever, daemon=True).start()
        self.addCleanup(down.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", down.server_port, timeout=10)
        conn.request("GET", "/api/me", headers={"Authorization": "Bearer x"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 502)
        self.assertIn("cannot be reached", json.loads(resp.read())["error"])
        self.assertEqual(normalise_engine("http://engine:8800/"), "http://engine:8800")
        for bad in ("ftp://x", "engine:8800", "http://engine:8800/api", "http://"):
            with self.subTest(bad), self.assertRaises(ValueError):
                normalise_engine(bad)

    def test_never_follows_redirects_or_forwards_other_headers(self):
        seen = {}

        class Engine(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                seen.update(dict(self.headers))
                self.send_response(302)
                self.send_header("Location", "http://169.254.169.254/latest/meta-data")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"moved": true}')

        fake = ThreadingHTTPServer(("127.0.0.1", 0), Engine)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        self.addCleanup(fake.shutdown)
        status, _, body = Console(f"http://127.0.0.1:{fake.server_port}").forward(
            "GET", "/api/me", {"Authorization": "Bearer t", "Cookie": "session=1", "X-Forwarded-For": "1.2.3.4"}, None)
        self.assertEqual((status, json.loads(body)), (302, {"moved": True}))  # passed back, not followed
        self.assertEqual(seen.get("Authorization"), "Bearer t")
        self.assertNotIn("Cookie", seen)
        self.assertNotIn("X-Forwarded-For", seen)


@unittest.skipUnless(NODE, "Node.js not installed")
class CommandLogicTests(unittest.TestCase):
    """commands.js has no DOM or network code, so Node runs it directly."""

    def node(self, script):
        out = subprocess.run([NODE, "-e", f"const C = require({json.dumps(str(STATIC / 'commands.js'))});\n{script}"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_parse(self):
        got = self.node('console.log(JSON.stringify([C.parse("/ask CQ-01 days=30 region=EU"), C.parse("which claims?"),'
                        ' C.parse("/RUN CL-4 goal=settle_claim"), C.parse("/nope x"), C.parse("/ask \\"CQ 1\\"")]))')
        self.assertEqual(got[0], {"command": "ask", "known": True, "args": ["CQ-01"],
                                  "options": {"days": "30", "region": "EU"}})
        self.assertEqual(got[1], {"command": None, "text": "which claims?"})
        self.assertEqual((got[2]["command"], got[2]["args"], got[2]["options"]), ("run", ["CL-4"], {"goal": "settle_claim"}))
        self.assertFalse(got[3]["known"])
        self.assertEqual(got[4]["args"], ["CQ 1"])

    def test_typed_values_and_completions(self):
        got = self.node('console.log(JSON.stringify([C.typed("30"), C.typed("2.5"), C.typed("true"), C.typed("EU"),'
                        ' C.completions("/ob").map(c => c.name), C.completions("").length]))')
        self.assertEqual(got[:4], [30, 2.5, True, "EU"])
        self.assertEqual(got[4], ["objects", "object"])
        self.assertGreaterEqual(got[5], 10)

    def test_plain_language_is_matched_to_the_ontology(self):
        svc = insurance_service(automations={})
        hana = next(u for u in svc.users if u.name == "hana")
        onto = json.dumps(svc.ontology_summary(hana))
        got = self.node(f"const o = {onto};\nconsole.log(JSON.stringify(["
                        'C.suggest("which claims were reported late?", o)[0],'
                        'C.suggest("show me all the cases", o).map(s => s.command),'
                        'C.suggest("please settle CL-4", o).map(s => s.command),'
                        'C.suggest("what is waiting for my approval", o).map(s => s.command),'
                        'C.suggest("why did run 0123456789ab stop", o)[0].command,'
                        'C.suggest("tell me a joke", o)]))')
        self.assertEqual(got[0]["command"], "/ask CQ-03")
        self.assertIn("/objects Claim", got[1])  # "cases" is another team's word for claims (an alias)
        self.assertEqual(got[2][0], "/run CL-4 goal=settle_claim")
        self.assertEqual(got[3][0], "/reviews")  # strong enough to answer directly
        self.assertEqual(got[4], "/explain 0123456789ab")
        self.assertEqual(got[5], [])


if __name__ == "__main__":
    unittest.main()
