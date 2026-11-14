"""Workspaces: two isolated organisations behind one router (master instructions, acceptance tests 1, 2 and 11)."""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from autology.console import make_console
from autology.platform import Platform, PlatformError, make_platform_server

from .helpers import ROOT

EX = ROOT / "examples" / "platform"
TOKENS = {"ACME_TOKEN_ADA": "acme-ada", "ACME_TOKEN_HANA": "acme-hana", "ACME_TOKEN_IVAN": "acme-ivan",
          "ACME_TOKEN_MARIA": "acme-maria", "ACME_TOKEN_OLIVIA": "acme-olivia", "ACME_TOKEN_LENA": "acme-lena",
          "NORTHWIND_TOKEN_NADIA": "nw-nadia", "NORTHWIND_TOKEN_HANA": "nw-hana"}
KEY = "sk-ant-api03-" + "y" * 40 + "ACME"


def platform(**changes):
    os.environ.update(TOKENS)
    spec = json.loads((EX / "platform.json").read_text())
    spec["data_dir"] = tempfile.mkdtemp()
    spec.update(changes)
    return Platform(spec, EX)


class Client:
    def __init__(self, pf):
        self.server = make_platform_server(pf, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def call(self, method, path, token=None, body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


class WorkspaceIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pf = platform()
        cls.c = Client(cls.pf)

    @classmethod
    def tearDownClass(cls):
        cls.c.server.shutdown()

    def test_members_see_only_their_workspace_and_granted_use_cases(self):
        status, me = self.c.call("GET", "/platform/me", "acme-ada")
        self.assertEqual((status, me["workspace"]["id"]), (200, "acme"))
        self.assertEqual({u["id"]: u["ontology"] for u in me["use_cases"]},
                         {"claims": "auto-insurance-claims@1.0.0", "orders": "order-fulfilment@1.1.0"})
        _, hana = self.c.call("GET", "/platform/me", "acme-hana")
        self.assertEqual([u["id"] for u in hana["use_cases"]], ["claims"])
        _, nw = self.c.call("GET", "/platform/me", "nw-hana")
        self.assertEqual((nw["workspace"]["id"], [u["id"] for u in nw["use_cases"]]), ("northwind", ["claims"]))

    def test_foreign_or_unknown_workspaces_are_indistinguishable(self):
        answers = {path: self.c.call("GET", path, "acme-hana") for path in (
            "/w/northwind/u/claims/api/me",     # exists, but not hers
            "/w/acme/u/orders/api/me",          # her workspace, use case not granted
            "/w/nowhere/u/claims/api/me",       # does not exist
            "/w/acme/u/nothing/api/me",
            "/w/acme/u/claims/../../northwind/u/claims/api/me",
            "/w/ACME/u/claims/api/me")}
        self.assertEqual({a for a in map(json.dumps, answers.values())}, {json.dumps([404, {"error": "not found"}])})
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims/api/me")[0], 401)  # no token
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims/api/me", "made-up")[0], 401)
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims/api/me", "nw-hana")[0], 404)  # same name, other person
        log = self.pf.log.access_log(limit=50)
        self.assertTrue(any(r["principal"] == "hana@acme" and r["status"] == 404 and "northwind" in r["target"]
                            for r in log))

    def test_data_written_in_one_workspace_never_appears_in_the_other(self):
        status, _ = self.c.call("POST", "/w/acme/u/claims/api/objects", "acme-ada", {
            "type": "Claim", "id": "CL-ACME-77", "attributes": {"amount": 777, "status": "reported"}})
        self.assertEqual(status, 200)
        _, mine = self.c.call("GET", "/w/acme/u/claims/api/objects?type=Claim", "acme-hana")
        _, theirs = self.c.call("GET", "/w/northwind/u/claims/api/objects?type=Claim", "nw-nadia")
        self.assertIn("CL-ACME-77", [i["id"] for i in mine["items"]])
        self.assertNotIn("CL-ACME-77", [i["id"] for i in theirs["items"]])
        self.assertEqual(self.c.call("GET", "/w/northwind/u/claims/api/objects/CL-ACME-77", "nw-nadia")[0], 404)
        # Northwind's administrator cannot write into Acme
        self.assertEqual(self.c.call("POST", "/w/acme/u/claims/api/objects", "nw-nadia",
                                     {"type": "Claim", "id": "CL-X", "attributes": {"amount": 1}})[0], 404)

    def test_runs_reviews_and_audit_stay_inside_the_workspace(self):
        status, run = self.c.call("POST", "/w/acme/u/claims/api/runs", "acme-hana",
                                  {"case_template": "claim_case", "root": "CL-2"})
        self.assertEqual((status, run["status"]), (200, "awaiting_review"))
        # a Northwind reviewer with the same role cannot see or decide it
        _, nw_reviews = self.c.call("GET", "/w/northwind/u/claims/api/reviews", "nw-hana")
        self.assertEqual(nw_reviews["items"], [])
        self.assertEqual(self.c.call("GET", f"/w/acme/u/claims/api/runs/{run['run_id']}", "nw-hana")[0], 404)
        self.assertEqual(self.c.call("POST", f"/w/acme/u/claims/api/reviews/{run['pending_review']}/decision",
                                     "nw-hana", {"approved": True})[0], 404)
        self.assertEqual(self.c.call("GET", f"/w/northwind/u/claims/api/runs/{run['run_id']}", "nw-hana")[0], 404)
        # Acme's own investigator can
        _, out = self.c.call("POST", f"/w/acme/u/claims/api/reviews/{run['pending_review']}/decision",
                             "acme-ivan", {"approved": True})
        self.assertEqual(out["status"], "awaiting_review")
        acme = self.pf.workspaces["acme"].use_cases["claims"].service
        nw = self.pf.workspaces["northwind"].use_cases["claims"].service
        self.assertTrue(acme.store.verify_audit(run["run_id"]))
        self.assertEqual(nw.store.list_runs(limit=10), [])
        # each use case's access log holds only its own workspace's people
        self.assertIn("ivan", {r["principal"] for r in acme.store.access_log(limit=200)})
        self.assertFalse({"ivan", "ada", "maria"} & {r["principal"] for r in nw.store.access_log(limit=200)})
        self.assertIsNone(nw.store.run_sources(run["run_id"]))

    def test_each_use_case_has_its_own_store_and_each_workspace_its_own_secrets(self):
        stores = {(ws.id, uc.id): Path(uc.service.store.path) for ws in self.pf.workspaces.values()
                  for uc in ws.use_cases.values()}
        self.assertEqual(len(set(stores.values())), 3)
        for (ws, uc), path in stores.items():
            self.assertEqual(path, self.pf.data_dir / ws / uc / "autology.db")
        status, view = self.c.call("POST", "/w/acme/u/claims/api/settings/assistant", "acme-ada",
                                   {"enabled": True, "api_key": KEY, "remember": True})
        self.assertEqual((status, view["key"]["hint"]), (200, "…ACME"))
        self.assertIn(KEY, (self.pf.data_dir / "acme" / "secrets.json").read_text())
        self.assertFalse((self.pf.data_dir / "northwind" / "secrets.json").exists())
        _, nw_view = self.c.call("GET", "/w/northwind/u/claims/api/settings/assistant", "nw-nadia")
        self.assertFalse(nw_view["key"]["set"])
        nw_db = self.pf.workspaces["northwind"].use_cases["claims"].service.store.path
        self.assertEqual(sqlite3.connect(nw_db).execute("SELECT COUNT(*) FROM instances WHERE id='CL-ACME-77'")
                         .fetchone()[0], 0)

    def test_use_case_config_cannot_escape_its_workspace(self):
        acme_claims = self.pf.workspaces["acme"].use_cases["claims"].service
        self.assertIsNone(acme_claims.oidc)  # company sign-in is per workspace in this mode, not per use case
        self.assertEqual({u.name for u in acme_claims.users}, {"ada", "hana", "ivan", "maria"})
        orders = self.pf.workspaces["acme"].use_cases["orders"].service
        self.assertEqual({u.name for u in orders.users}, {"ada", "olivia", "lena"})
        self.assertEqual({u.name for u in self.pf.workspaces["northwind"].use_cases["claims"].service.users},
                         {"nadia", "hana"})

    def test_the_console_talks_to_one_use_case_through_the_router(self):
        console = make_console(f"{self.c.base}/w/acme/u/claims", "127.0.0.1", 0)
        threading.Thread(target=console.serve_forever, daemon=True).start()
        self.addCleanup(console.shutdown)
        req = urllib.request.Request(f"http://127.0.0.1:{console.server_port}/api/me",
                                     headers={"Authorization": "Bearer acme-hana"})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.loads(r.read())["name"], "hana")
        req = urllib.request.Request(f"http://127.0.0.1:{console.server_port}/api/me",
                                     headers={"Authorization": "Bearer nw-hana"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 404)


class RouterHttpTests(unittest.TestCase):
    def test_methods_bodies_and_health(self):
        import http.client

        pf = platform()
        c = Client(pf)
        self.addCleanup(c.server.shutdown)
        self.assertEqual(c.call("GET", "/platform/health"), (200, {"status": "ok"}))
        self.assertEqual(len(pf.services()), 3)
        conn = http.client.HTTPConnection("127.0.0.1", c.server.server_port, timeout=10)
        conn.request("DELETE", "/w/acme/u/claims/api/me", headers={"Authorization": "Bearer acme-ada"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 405)
        resp.read()
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", c.server.server_port, timeout=10)
        conn.putrequest("POST", "/w/acme/u/claims/api/questions/CQ-01")
        conn.putheader("Authorization", "Bearer acme-hana")
        conn.putheader("Content-Length", "-1")
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 411)  # the router uses the engine's safe body reader
        conn.close()

    def test_reporting_target_is_kept_inside_the_use_case(self):
        os.environ.update(TOKENS)
        cfg = json.loads((ROOT / "examples" / "auto_insurance" / "server.json").read_text())
        cfg["reporting"] = {"target": "/tmp/anywhere/reporting.db", "roles": ["claims_handler"]}
        cfg.pop("pipelines", None)
        folder = Path(tempfile.mkdtemp())
        (folder / "server.json").write_text(json.dumps(cfg))
        for name in ("ontology.json", "tools.json", "data.json"):
            (folder / name).write_text((ROOT / "examples" / "auto_insurance" / name).read_text())
        spec = {"data_dir": str(folder / "data"), "workspaces": {"w1": {
            "members": [{"name": "a", "token_sha256": "a" * 64, "workspace_admin": True}],
            "use_cases": {"claims": {"config": "server.json"}}}}}
        pf = Platform(spec, folder)
        svc = pf.workspaces["w1"].use_cases["claims"].service
        self.assertEqual(Path(svc.reporting["target"]), folder / "data" / "w1" / "claims" / "reporting.db")


class PlatformConfigTests(unittest.TestCase):
    def test_a_token_identifies_one_person_in_one_workspace(self):
        os.environ["NORTHWIND_TOKEN_HANA"] = "acme-hana"  # the same secret in two workspaces
        self.addCleanup(os.environ.__setitem__, "NORTHWIND_TOKEN_HANA", "nw-hana")
        spec = json.loads((EX / "platform.json").read_text())
        spec["data_dir"] = tempfile.mkdtemp()
        os.environ.update({k: v for k, v in TOKENS.items() if k != "NORTHWIND_TOKEN_HANA"})
        with self.assertRaisesRegex(PlatformError, "already used by another member"):
            Platform(spec, EX)

    def test_invalid_definitions(self):
        os.environ.update(TOKENS)
        base = json.loads((EX / "platform.json").read_text())
        cases = {
            "workspace id": {"workspaces": {"Bad Name": base["workspaces"]["acme"]}},
            "use case id": {"workspaces": {"x": {"members": [], "use_cases": {"../up": {"config": "a.json"}}}}},
            "unknown use case grant": {"workspaces": {"x": {"members": [
                {"name": "a", "token_sha256": "0" * 64, "use_cases": {"ghost": {"permissions": ["read"]}}}],
                "use_cases": {}}}},
            "unknown permission": {"workspaces": {"x": {"members": [
                {"name": "a", "token_sha256": "1" * 64, "use_cases": {}},
                {"name": "b", "token_sha256": "2" * 64, "use_cases": {"c": {"permissions": ["root"]}}}],
                "use_cases": {}}}},
            "no workspaces": {"workspaces": {}},
            "bad member name": {"workspaces": {"x": {"members": [{"name": "a b", "token_sha256": "3" * 64}]}}},
            "bad token hash": {"workspaces": {"x": {"members": [{"name": "a", "token_sha256": "nope"}]}}},
            "missing token": {"workspaces": {"x": {"members": [{"name": "a", "token_env": "NOT_SET_ANYWHERE"}]}}},
        }
        for label, spec in cases.items():
            with self.subTest(label), self.assertRaises(PlatformError):
                Platform({"data_dir": tempfile.mkdtemp(), **spec}, EX)


if __name__ == "__main__":
    unittest.main()
