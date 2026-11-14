"""The Engine runs with no user interface installed and without Hermes (master instructions §2.1, §2A).

A minimal third-party client using only the standard library drives a complete governed process (start, two
reviews by two different people, completion with audit) against an engine whose UI files are absent.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from autology import server

from .helpers import ROOT
from .test_ingest import TOKENS, service


class HeadlessEngineTests(unittest.TestCase):
    def setUp(self):
        empty = Path(tempfile.mkdtemp())  # no inbox files at all: the engine ships without its UI
        patcher = mock.patch.object(server, "STATIC", empty)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.svc = service(automations={}, pipelines={})
        self.http = server.make_server(self.svc, "127.0.0.1", 0)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.shutdown)
        self.base = f"http://127.0.0.1:{self.http.server_port}"

    def call(self, method, path, who=None, body=None):
        headers = {"Content-Type": "application/json"}
        if who:
            headers["Authorization"] = f"Bearer {TOKENS[who]}"
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_a_third_party_client_runs_a_governed_process_without_any_ui(self):
        status, run = self.call("POST", "/api/runs", "hana", {"case_template": "claim_case", "root": "CL-2"})
        self.assertEqual((status, run["status"]), (200, "awaiting_review"))
        status, _ = self.call("POST", f"/api/reviews/{run['pending_review']}/decision", "ivan", {"approved": True})
        self.assertEqual(status, 200)
        _, reviews = self.call("GET", "/api/reviews?status=pending", "maria")
        second = [r for r in reviews["items"] if r["run_id"] == run["run_id"]][0]
        status, done = self.call("POST", f"/api/reviews/{second['review_id']}/decision", "maria", {"approved": True})
        self.assertEqual((status, done["status"]), (200, "completed"))
        status, audit = self.call("GET", f"/api/runs/{run['run_id']}/audit", "admin")
        self.assertTrue(audit["verified"])

    def test_the_ui_route_reports_that_no_ui_is_installed(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 404)
        self.assertIn("not installed", body["error"])
        self.assertEqual(self.call("GET", "/api/health")[0], 200)


class NoUiOrHermesDependencyTests(unittest.TestCase):
    def test_the_engine_never_imports_a_ui_or_hermes(self):
        code = ("import sys, autology, autology.server, autology.agent, autology.platform, autology.mcp; "
                "print(sorted(m for m in sys.modules if m.startswith('autology.console') or 'hermes' in m.lower()))")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                             env={**os.environ, "PYTHONPATH": str(ROOT)})
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]")

    def test_no_engine_module_mentions_hermes(self):
        for path in (ROOT / "autology").glob("*.py"):
            with self.subTest(path.name):
                self.assertNotIn("hermes", path.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
