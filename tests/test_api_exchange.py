"""The transport-independent API dispatcher, and request-body safety in the engine's own HTTP server."""

import http.client
import json
import unittest

from autology.server import ApiExchange

from .test_ingest import TOKENS, service
from .test_platform import _Api


class ApiExchangeTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})

    def test_same_answers_without_a_socket(self):
        ex = ApiExchange(self.svc, "GET", "/api/me", {"Authorization": f"Bearer {TOKENS['hana']}"}).run()
        self.assertEqual((ex.status, json.loads(ex.data)["name"]), (200, "hana"))
        ex = ApiExchange(self.svc, "POST", "/api/questions/CQ-03", {"Authorization": f"Bearer {TOKENS['hana']}"},
                         b'{"params": {}}').run()
        self.assertEqual(json.loads(ex.data)["answer"], ["CL-3"])
        ex = ApiExchange(self.svc, "GET", "/api/me", {}).run()
        self.assertEqual(ex.status, 401)
        self.assertEqual(self.svc.store.access_log(limit=1)[0]["status"], 401)  # still logged
        ex = ApiExchange(self.svc, "POST", "/api/runs", {"Authorization": f"Bearer {TOKENS['hana']}"},
                         body_error=(413, "request body too large")).run()
        self.assertEqual(ex.status, 413)


class EngineBodySafetyTests(unittest.TestCase):
    def setUp(self):
        self.api = _Api(service(automations={}))
        self.addCleanup(self.api.server.shutdown)

    def raw(self, method, headers, body=b""):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server.server_port, timeout=10)
        conn.putrequest(method, "/api/questions/CQ-01")
        for k, v in headers.items():
            conn.putheader(k, v)
        conn.endheaders()
        if body:
            conn.send(body)
        resp = conn.getresponse()
        out = resp.status, resp.getheader("Content-Type"), resp.read()
        conn.close()
        return out

    def test_negative_or_malformed_length_is_refused_without_reading(self):  # audit GAP-015
        auth = {"Authorization": f"Bearer {TOKENS['hana']}", "Content-Type": "application/json"}
        for length in ("-1", "abc", "1e9"):
            with self.subTest(length):
                status, ctype, body = self.raw("POST", {**auth, "Content-Length": length}, b"{}")
                self.assertEqual(status, 411)
                self.assertIn("Content-Length", json.loads(body)["error"])
        status, _, _ = self.raw("POST", {**auth, "Content-Length": "2000000"}, b"{}")
        self.assertEqual(status, 413)
        status, _, body = self.raw("POST", {**auth, "Content-Length": "2"}, b"{}")
        self.assertEqual(status, 200)

    def test_unsupported_methods_answer_json(self):
        status, ctype, body = self.raw("DELETE", {"Authorization": f"Bearer {TOKENS['admin']}"})
        self.assertEqual((status, ctype.split(";")[0]), (405, "application/json"))
        self.assertIn("not supported", json.loads(body)["error"])


if __name__ == "__main__":
    unittest.main()
