"""Tier 1 platform: SQLite store, asynchronous reviews, REST API with auth, web inbox serving."""

import copy
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

from autology import DeferredApprover, Ontology, ReviewDecision, WorkAgent
from autology.__main__ import main as cli
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph
from autology.persistence import result_from_dict, result_to_dict
from autology.reporting import classify
from autology.server import AutologyService, hash_token, make_server, new_token
from autology.store import Store, StoreError

from .helpers import ROOT

EX = ROOT / "examples" / "order_fulfilment"
CASE = json.loads((EX / "case.json").read_text())
TOKENS = {"olivia": "tok-olivia", "lena": "tok-lena", "audrey": "tok-audrey", "admin": "tok-admin"}


def fulfilment_agent(approver=None, **kw):
    onto = Ontology.load(EX / "ontology.json")
    return WorkAgent("fulfilment", onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops", "finance"],
                     approver=approver or DeferredApprover(), **kw)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "store.db"
        self.store = Store(self.path)
        self.onto = Ontology.load(EX / "ontology.json")

    def test_graph_roundtrip(self):
        graph = KnowledgeGraph.from_dict(self.onto, json.loads((EX / "data.json").read_text()))
        self.assertEqual(self.store.save_graph(graph), 5)
        again = Store(self.path).load_graph(self.onto)  # a new connection: survives restarts
        self.assertEqual(again.ask("CQ-01").answer, ["O-1", "O-2", "O-3"])
        self.store.upsert_instance("Order", "O-4", {"sku": "X", "status": "received"})
        self.store.add_link("K-1", "covers", "O-4")
        self.assertEqual(Store(self.path).load_graph(self.onto).ask("CQ-01").answer, ["O-1", "O-2", "O-3", "O-4"])
        self.assertEqual(self.store.count_instances("Order"), 4)

    def test_runs_and_append_only_audit(self):
        result = fulfilment_agent().run("fulfil_contract", CASE, "K-1")
        run_id = self.store.save_run(result, agent="fulfilment")
        self.assertEqual(result.run_id, run_id)
        self.assertEqual(self.store.list_runs()[0]["status"], "awaiting_review")
        self.assertEqual(self.store.list_runs("completed"), [])
        loaded = Store(self.path).load_run(run_id)
        self.assertEqual((loaded.status, loaded.path), (result.status, result.path))
        self.assertTrue(self.store.verify_audit(run_id))
        self.assertTrue(self.store.audit_events("review.requested"))
        self.assertEqual(len(self.store.audit_events(run_id=run_id, limit=5)), 5)
        for sql in ("UPDATE audit SET data='{}'", "DELETE FROM audit"):
            with self.subTest(sql), self.assertRaisesRegex(sqlite3.DatabaseError, "append-only"):
                self.store._db.execute(sql)
        other = fulfilment_agent().run("fulfil_contract", CASE, "K-1")
        with self.assertRaisesRegex(StoreError, "diverges"):
            self.store.save_run(other, run_id)
        result.audit._entries[3].data["step"] = 99  # tampered in memory
        with self.assertRaisesRegex(StoreError, "does not verify"):
            self.store.save_run(result, "fresh-id")
        with self.assertRaises(KeyError):
            self.store.load_run("nope")

    def test_review_lifecycle(self):
        result = fulfilment_agent().run("fulfil_contract", CASE, "K-1")
        run_id = self.store.save_run(result)
        from autology.agent import ReviewRequest

        review_id = self.store.create_review(run_id, ReviewRequest(**result.run.pending_review))
        self.assertEqual([r["review_id"] for r in self.store.list_reviews(reviewer_roles=["logistics_manager"])],
                         [review_id])
        self.assertEqual(self.store.list_reviews(reviewer_roles=["cfo"]), [])
        decided = self.store.decide_review(review_id, True, "lena", "ok")
        self.assertEqual((decided["status"], decided["decided_by"]), ("approved", "lena"))
        with self.assertRaisesRegex(StoreError, "already decided"):
            self.store.decide_review(review_id, False, "eve")
        with self.assertRaises(KeyError):
            self.store.get_review("nope")
        with self.assertRaises(KeyError):
            self.store.decide_review("nope", True, "x")

    def test_newer_schema_refused(self):
        self.store._db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        with self.assertRaisesRegex(StoreError, "newer"):
            Store(self.path)


class AsyncReviewTests(unittest.TestCase):
    def test_park_survive_restart_and_resume(self):
        agent = fulfilment_agent()
        parked = agent.run("fulfil_contract", CASE, "K-1")
        self.assertEqual(parked.status, "awaiting_review")
        self.assertEqual(classify(parked), "pending")
        self.assertEqual(parked.run.pending_review["action"], "ship_order@O-4")
        restored = result_from_dict(json.loads(json.dumps(result_to_dict(parked))))
        with self.assertRaisesRegex(ValueError, "waiting for a review decision"):
            agent.resume(restored)
        done = agent.resume(restored, decision=ReviewDecision(True, "lena", "go"))
        self.assertTrue(done.completed, done.escalation)
        self.assertEqual([s.reviewer for s in done.steps if s.reviewer], ["lena"])
        reviews = done.audit.events("review")
        self.assertEqual((reviews[0].data["reviewer"], reviews[0].data["approved"]), ("lena", True))
        self.assertTrue(done.audit.verify())

    def test_declined_decision_blocks(self):
        agent = fulfilment_agent()
        parked = agent.run("fulfil_contract", CASE, "K-1")
        blocked = agent.resume(parked, decision=ReviewDecision(False, "lena", "carrier unavailable"))
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.escalation.details, ["carrier unavailable"])
        with self.assertRaises(ValueError):
            agent.resume(blocked)


class _Api:
    def __init__(self, service):
        self.server = make_server(service, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def call(self, method, path, who=None, body=None, raw=None, headers=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        hdrs = {"Content-Type": "application/json", **(headers or {})}
        if who:
            hdrs["Authorization"] = f"Bearer {TOKENS.get(who, who)}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req) as r:
                payload = r.read()
                return r.status, (json.loads(payload) if "json" in r.headers["Content-Type"] else payload.decode()), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), e.headers


def service(**overrides):
    for name, token in TOKENS.items():
        os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
    cfg = json.loads((EX / "server.json").read_text())
    cfg["store"] = str(Path(tempfile.mkdtemp()) / "api.db")
    cfg.update(overrides)
    return AutologyService(cfg, EX)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = service()
        cls.api = _Api(cls.svc)

    @classmethod
    def tearDownClass(cls):
        cls.api.server.shutdown()

    def test_authentication(self):
        self.assertEqual(self.api.call("GET", "/api/health")[0], 200)
        self.assertEqual(self.api.call("GET", "/api/me")[0], 401)
        self.assertEqual(self.api.call("GET", "/api/me", "wrong-token")[0], 401)
        self.assertEqual(self.api.call("GET", "/api/me", headers={"Authorization": "Basic x"})[0], 401)
        status, me, _ = self.api.call("GET", "/api/me", "lena")
        self.assertEqual((status, me["reviewer_roles"]), (200, ["logistics_manager"]))

    def test_row_and_field_access(self):
        _, olivia, _ = self.api.call("GET", "/api/objects?type=Order", "olivia")
        _, lena, _ = self.api.call("GET", "/api/objects?type=Order", "lena")
        self.assertEqual(lena["total"] - olivia["total"], 1)  # the EU order is hidden from olivia
        self.assertNotIn("O-3", [i["id"] for i in olivia["items"]])
        self.assertIn("O-3", [i["id"] for i in lena["items"]])
        self.assertEqual(self.api.call("GET", "/api/objects/O-3", "olivia")[0], 404)  # hidden row looks absent
        _, customer, _ = self.api.call("GET", "/api/objects/C-1", "olivia")
        self.assertEqual(customer["attributes"]["credit_limit"], "***redacted***")
        self.assertEqual({l["id"] for l in customer["links"]}, {"K-1"})
        gated = self.api.call("GET", "/api/objects/C-1", "audrey")[1]["attributes"]["credit_limit"]
        self.assertEqual(gated, "***justification required***")  # checkpoint CP-CREDIT
        why = "?justification=" + "quarterly%20credit%20review"
        self.assertEqual(self.api.call("GET", "/api/objects/C-1" + why, "audrey")[1]["attributes"]["credit_limit"],
                         250000)
        self.assertEqual(self.api.call("GET", "/api/objects?type=Ghost", "olivia")[0], 404)
        self.assertEqual(self.api.call("POST", "/api/questions/CQ-03", "olivia", {})[0], 403)  # sum over hidden rows
        self.assertEqual(self.api.call("POST", "/api/questions/CQ-03", "lena", {})[1]["answer"], 12000)
        self.assertNotIn("O-3", self.api.call("POST", "/api/questions/CQ-01", "olivia", {})[1]["answer"])
        self.assertEqual(self.api.call("POST", "/api/questions/CQ-99", "olivia", {})[0], 404)

    def test_run_review_resume_flow(self):
        self.assertEqual(self.api.call("POST", "/api/runs", "lena", {"case": CASE})[0], 403)  # no run permission
        self.assertEqual(self.api.call("POST", "/api/runs", "olivia", {"case": "nope"})[0], 400)
        self.assertEqual(self.api.call("POST", "/api/runs", "olivia", {"case": {"Ghost": {}}})[0], 400)
        self.assertEqual(self.api.call("POST", "/api/runs", "olivia", {"agent": "ghost", "case": CASE})[0], 400)
        self.assertEqual(self.api.call("POST", "/api/runs", "olivia", {"goal": "ghost", "case": CASE})[0], 400)
        status, run, _ = self.api.call("POST", "/api/runs", "olivia", {"case": CASE, "case_id": "K-9"})
        self.assertEqual((status, run["status"]), (200, "awaiting_review"))
        self.assertNotIn("O-3", run["state"]["Order"])  # olivia's view of the run state
        review_id = run["pending_review"]
        self.assertEqual(self.api.call("GET", "/api/reviews", "olivia")[0], 403)
        self.assertIn(review_id, [r["review_id"] for r in self.api.call("GET", "/api/reviews", "lena")[1]["items"]])
        self.assertEqual(self.api.call("POST", f"/api/reviews/{review_id}/decision", "audrey", {"approved": True})[0], 403)
        self.assertEqual(self.api.call("POST", f"/api/reviews/{review_id}/decision", "lena", {"approved": "yes"})[0], 400)
        status, done, _ = self.api.call("POST", f"/api/reviews/{review_id}/decision", "lena",
                                        {"approved": True, "comment": "carrier confirmed"})
        self.assertEqual((status, done["status"], done["audit_verified"]), (200, "completed", True))
        self.assertEqual(self.api.call("POST", f"/api/reviews/{review_id}/decision", "lena", {"approved": True})[0], 409)
        self.assertEqual(self.api.call("GET", f"/api/reviews/{review_id}", "olivia")[1]["decided_by"], "lena")
        self.assertEqual(self.api.call("GET", "/api/reviews?status=approved", "olivia")[0], 200)
        run_id = run["run_id"]
        self.assertEqual(self.api.call("GET", f"/api/runs/{run_id}", "olivia")[1]["status"], "completed")
        self.assertEqual(self.api.call("GET", f"/api/runs/{run_id}/audit", "olivia")[0], 403)
        status, audit, _ = self.api.call("GET", f"/api/runs/{run_id}/audit", "audrey")
        self.assertTrue(audit["verified"])
        self.assertIn("lena", json.dumps([e for e in audit["entries"] if e["event"] == "review"]))
        self.assertEqual(self.api.call("POST", f"/api/runs/{run_id}/resume", "olivia", {})[0], 409)  # completed
        self.assertEqual(self.api.call("GET", "/api/runs/nope", "olivia")[0], 404)
        self.assertEqual(self.api.call("GET", "/api/runs/nope/audit", "audrey")[0], 404)
        self.assertEqual(self.api.call("GET", "/api/reviews/nope", "olivia")[0], 404)
        listed = self.api.call("GET", "/api/runs?status=completed", "olivia")[1]["items"]
        self.assertIn(run_id, [r["run_id"] for r in listed])
        status, report, _ = self.api.call("GET", "/api/report", "olivia")
        self.assertIn("Audit trails intact: yes", report)
        self.assertGreater(self.api.call("GET", "/api/score", "olivia")[1]["overall"], 0)

    def test_admin_data_upload(self):
        order = {"type": "Order", "id": "O-50", "attributes": {"sku": "X", "region": "US"}}
        contract = {"type": "Contract", "id": "K-50", "attributes": {"value": 1},
                    "links": [{"kind": "covers", "target": "O-50"}]}
        self.assertEqual(self.api.call("POST", "/api/objects", "olivia", order)[0], 403)
        self.assertEqual(self.api.call("POST", "/api/objects", "admin", {"type": "Order"})[0], 400)
        self.assertEqual(self.api.call("POST", "/api/objects", "admin", {**order, "attributes": {"colour": 1}})[0], 400)
        self.assertEqual(self.api.call("POST", "/api/objects", "admin", order)[0], 200)
        self.assertEqual(self.api.call("POST", "/api/objects", "admin",
                                       {**contract, "links": [{"kind": "flies", "target": "O-50"}]})[0], 400)
        self.assertEqual(self.api.call("POST", "/api/objects", "admin", contract)[0], 200)
        stored = Store(self.svc.store.path).load_graph(self.svc.ontology)  # persisted, survives a restart
        self.assertEqual(stored.get("O-50").get("sku"), "X")
        self.assertEqual([o.id for o in stored.neighbours(stored.get("K-50"), "covers")], ["O-50"])

    def test_http_hygiene_and_inbox(self):
        status, page, headers = self.api.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("Autology Inbox", page)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("textContent", self.api.call("GET", "/app.js")[1])
        self.assertIn("prefers-color-scheme", self.api.call("GET", "/app.css")[1])
        self.assertNotIn(".innerHTML", self.api.call("GET", "/app.js")[1])  # data is inserted as text only
        self.assertEqual(self.api.call("GET", "/etc/passwd")[0], 404)
        self.assertEqual(self.api.call("GET", "/api/nope", "olivia")[0], 404)
        self.assertEqual(self.api.call("POST", "/api/me", "olivia", {})[0], 405)
        self.assertEqual(self.api.call("POST", "/api/runs", "olivia", raw=b"{not json")[0], 400)
        self.assertEqual(self.api.call("POST", "/api/runs", "olivia", raw=b"[1]")[0], 400)
        self.assertEqual(self.api.call("POST", "/api/runs", "olivia", raw=b"x" * 1_000_001)[0], 413)
        self.assertEqual(self.api.call("GET", "/api/runs?limit=abc", "olivia")[0], 400)
        self.assertEqual(self.api.call("GET", "/api/ontology", "olivia")[1]["agents"]["fulfilment"]["goals"],
                         ["fulfil_contract"])


class DeferredResumeApiTests(unittest.TestCase):
    def test_deferred_run_resumes_through_the_api(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "flaky_tools.py").write_text(
            "from autology import ToolRegistry, ToolResult, ToolError\n"
            "state = {'fail': 1}\n"
            "def build():\n"
            "    reg = ToolRegistry()\n"
            "    def pick(call):\n"
            "        if state['fail']:\n"
            "            state['fail'] -= 1\n"
            "            raise ToolError('warehouse system down')\n"
            "        return ToolResult(message='picked')\n"
            "    reg.register('flaky_wms', 'warehouse.pick', pick, priority=9)\n"
            "    return reg\n")
        doc = json.loads((EX / "ontology.json").read_text())
        doc["actions"]["pick_order"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": 3600,
                                                      "fallback_tools": False}
        (tmp / "ontology.json").write_text(json.dumps(doc))
        tools = json.loads((EX / "tools.json").read_text())
        (tmp / "tools.json").write_text(json.dumps({**tools, "python_path": ["."],
                                                    "registries": ["flaky_tools:build"]}))
        token, digest = new_token()
        self.assertEqual(hash_token(token), digest)
        cfg = {"ontology": "ontology.json", "store": "s.db",
               "agents": {"ops": {"roles": ["ops", "eu_ops", "finance"], "tools": "tools.json", "approver": "auto"}},
               "users": [{"name": "op", "token_sha256": digest, "permissions": ["read", "run"]}]}
        api = _Api(AutologyService(cfg, tmp))
        try:
            TOKENS["op"] = token
            _, run, _ = api.call("POST", "/api/runs", "op", {"case": CASE})
            self.assertEqual(run["status"], "deferred")
            status, again, _ = api.call("POST", f"/api/runs/{run['run_id']}/resume", "op", {})
            self.assertEqual(again["status"], "deferred")  # retry window not reached
            status, done, _ = api.call("POST", f"/api/runs/{run['run_id']}/resume", "op", {"force": True})
            self.assertEqual(done["status"], "completed")
            self.assertTrue(done["audit_verified"])
        finally:
            api.server.shutdown()


class ConfigTests(unittest.TestCase):
    def test_invalid_configs(self):
        base = json.loads((EX / "server.json").read_text())
        base["store"] = ":memory:"
        for name, token in TOKENS.items():
            os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
        cases = {
            "bad permission": lambda c: c["users"][0].update(permissions=["fly"]),
            "bad hash": lambda c: c["users"][0].update(token_env=None, token_sha256="abc"),
            "missing env": lambda c: c["users"][0].update(token_env="AUTOLOGY_TOKEN_NOBODY_SET"),
            "unknown goal": lambda c: c["agents"]["fulfilment"].update(goals=["ghost"]),
        }
        os.environ.pop("AUTOLOGY_TOKEN_NOBODY_SET", None)
        for label, mutate in cases.items():
            cfg = copy.deepcopy(base)
            mutate(cfg)
            with self.subTest(label), self.assertRaises((ValueError, Exception)):
                AutologyService(cfg, EX)
        svc = AutologyService(base, EX)
        self.assertEqual(len(svc.users), 4)

    def test_cli_token_and_db(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli(["token"]), 0)
        token_line, hash_line = out.getvalue().splitlines()
        self.assertEqual(hash_token(token_line.split()[-1]), hash_line.split()[-1])
        db = Path(tempfile.mkdtemp()) / "cli.db"
        with redirect_stdout(io.StringIO()) as out:
            cli(["run", str(EX / "ontology.json"), "fulfil_contract", str(EX / "case.json"), "--tools",
                 str(EX / "tools.json"), "--roles", "ops,eu_ops,finance", "--approver", str(EX / "approvals.json"),
                 "--db", str(db)])
            cli(["report", str(EX / "ontology.json"), "--db", str(db)])
            self.assertEqual(cli(["report", str(EX / "ontology.json")]), 2)
            cli(["score", str(EX / "ontology.json"), "--db", str(db), "--json"])
        self.assertIn("completed 1", out.getvalue())
        self.assertEqual(Store(db).list_runs()[0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
