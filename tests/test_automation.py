"""Tier 2: automations, notifications, webhooks, cases built from the graph, write-back."""

import copy
import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from autology import Ontology, OntologyError
from autology.automation import Automation, Automator, Firing, load_automations
from autology.expressions import compile_expression
from autology.graph import Instance, KnowledgeGraph, build_case
from autology.store import SCHEMA_VERSION, Store

from .test_platform import EX, TOKENS, _Api, service

DATA = json.loads((EX / "data.json").read_text())
DOC = json.loads((EX / "ontology.json").read_text())


def onto_with(**changes):
    doc = copy.deepcopy(DOC)
    doc.update(changes)
    return Ontology.from_dict(doc)


class CaseTemplateTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(EX / "ontology.json")
        self.graph = KnowledgeGraph.from_dict(self.onto, DATA)

    def test_build_case_follows_relationships(self):
        case, sources = build_case(self.graph, "contract_case", "K-1")
        self.assertEqual(case["Customer"]["name"], "Northwind")
        self.assertEqual([o["id"] for o in case["Order"]], ["O-1", "O-2", "O-3"])
        self.assertEqual(sources, {"Contract": "K-1", "Customer": "C-1", "Order": ["O-1", "O-2", "O-3"]})
        # the case is valid input for an agent
        from autology.state import WorldState

        state = WorldState.initial(self.onto, case)
        self.assertEqual(state.get("Order", "status", "O-1"), "invoiced")

    def test_missing_single_entity_is_left_out(self):
        graph = KnowledgeGraph(self.onto)
        graph.add("Contract", "K-9", value=1)
        case, sources = build_case(graph, "contract_case", "K-9")
        self.assertNotIn("Customer", case)
        self.assertEqual(case["Order"], [])

    def test_build_case_errors(self):
        for args in [("ghost", "K-1"), ("contract_case", "nobody"), ("contract_case", "O-1")]:
            with self.subTest(args), self.assertRaises(OntologyError):
                build_case(self.graph, *args)

    def test_template_validation(self):
        bad = {
            "unknown root": {"root": "Ghost", "entities": {}},
            "unknown entity": {"root": "Contract", "entities": {"Contract": "self", "Ghost": "covers"}},
            "wrong end": {"root": "Contract", "entities": {"Contract": "self", "Customer": "covers"}},
            "bad step": {"root": "Contract", "entities": {"Contract": "self", "Order": "ships"}},
            "no root": {"root": "Contract", "entities": {"Order": "covers"}},
        }
        for label, spec in bad.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                onto_with(case_templates={"t": spec})

    def test_templates_merge_from_modules(self):
        base = Path(tempfile.mkdtemp())
        doc = copy.deepcopy(DOC)
        template = doc.pop("case_templates")
        (base / "main.json").write_text(json.dumps({**doc, "imports": ["extra.json"]}))
        (base / "extra.json").write_text(json.dumps({"name": "extra", "case_templates": template}))
        self.assertIn("contract_case", Ontology.load(base / "main.json").case_templates)


class LoadAutomationTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(EX / "ontology.json")
        self.agents = {"fulfilment": ["fulfil_contract"]}
        self.good = {"entity": "Contract", "when": "Contract.status == 'signed'",
                     "run": {"agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case"}}

    def test_valid(self):
        autos = load_automations({"a": self.good, "b": {"entity": "Order", "trigger": {"every": 60},
                                                         "notify": {"roles": ["finance"], "message": "{id} {amount}"}}},
                                 self.onto, self.agents)
        self.assertEqual(autos["a"].trigger, "change")
        self.assertTrue(autos["a"].run["write_back"])
        self.assertEqual(autos["b"].trigger, "every 60s")
        self.assertEqual(autos["b"].describe()["when"], None)
        inst = Instance("Order", "O-1", {"amount": 5})
        self.assertTrue(autos["b"].holds(inst, 0))
        self.assertFalse(autos["b"].holds(Instance("Contract", "K-1", {}), 0))
        self.assertEqual(autos["b"].message(inst), "O-1 5")

    def test_invalid(self):
        def variant(**kw):
            spec = copy.deepcopy(self.good)
            for k, v in kw.items():
                if v is None:
                    spec.pop(k, None)
                else:
                    spec[k] = v
            return spec

        bad = {
            "entity": variant(entity="Ghost"),
            "syntax": variant(when="Contract.status ==="),
            "other entity": variant(when="Order.amount > 1"),
            "params": variant(when="Contract.value > Params.limit"),
            "quantifier": variant(entity="Contract", when="all_of(Order.amount > 1)"),
            "trigger value": variant(trigger={"every": 0}),
            "trigger kind": variant(trigger="sometimes"),
            "nothing to do": variant(run=None),
            "agent": variant(run={"agent": "ghost", "goal": "fulfil_contract", "case_template": "contract_case"}),
            "goal": variant(run={"agent": "fulfilment", "goal": "ghost", "case_template": "contract_case"}),
            "template": variant(run={"agent": "fulfilment", "goal": "fulfil_contract", "case_template": "ghost"}),
            "template root": variant(entity="Order", when=None),
            "notify roles": variant(notify={"message": "x"}),
            "placeholder": variant(notify={"roles": ["x"], "message": "{ghost}"}),
        }
        for label, spec in bad.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                load_automations({"a": spec}, self.onto, self.agents)

    def test_condition_that_cannot_be_evaluated_does_not_hold(self):
        auto = Automation("a", "Order", compile_expression("Order.amount > 5"))
        self.assertFalse(auto.holds(Instance("Order", "O-1", {"amount": None}), 0))
        deadline = Automation("d", "Order", compile_expression("Order.amount < Params.now"))
        self.assertTrue(deadline.holds(Instance("Order", "O-1", {"amount": 5}), 10))
        self.assertFalse(deadline.holds(Instance("Order", "O-1", {"amount": 5}), 1))


class AutomatorTests(unittest.TestCase):
    """The engine alone, with an in-memory graph and a recording fire callback."""

    def setUp(self):
        self.onto = Ontology.load(EX / "ontology.json")
        self.graph = KnowledgeGraph.from_dict(self.onto, DATA)
        self.store = Store(":memory:")
        self.now = 1000.0
        self.calls = []
        self.autos = {
            "big": Automation("big", "Order", compile_expression("Order.amount > 10000")),
            "due": Automation("due", "Order", compile_expression("Order.quantity < Params.now")),
            "hourly": Automation("hourly", "Contract", None, every=3600),
        }
        self.engine = self._engine()

    def _engine(self, fire=None):
        def record(auto, inst, trigger):
            self.calls.append((auto.name, inst.id, trigger))
            return Firing(auto.name, inst.id, trigger, status="notified")

        return Automator(self.autos, self.store, lambda e: self.graph.instances(e), fire or record,
                         clock=lambda: self.now)

    def test_change_fires_once_until_rearmed(self):
        self.engine.on_change(["O-3", "ghost"])
        self.assertEqual(self.calls, [("big", "O-3", "change"), ("due", "O-3", "change")])
        self.engine.on_change(["O-3"])
        self.assertEqual(len(self.calls), 2)  # still true: no second firing
        self.graph.get("O-3").attributes["amount"] = 5
        self.engine.on_change(["O-3"])
        self.graph.get("O-3").attributes["amount"] = 50000
        self.engine.on_change(["O-3"])
        self.assertEqual(self.calls[-1], ("big", "O-3", "change"))
        self.assertEqual(sum(1 for c in self.calls if c[0] == "big"), 2)
        # the armed state is persisted: a fresh engine on the same store does not fire again
        self.calls.clear()
        self._engine().on_change(["O-3"])
        self.assertEqual(self.calls, [])
        self.assertEqual(len(self.store.list_firings("big")), 2)

    def test_tick_handles_time_and_schedules(self):
        self.now = 10
        self.engine.tick()
        self.assertIn(("due", "O-1", "change"), self.calls)  # quantity 4 < now 10
        self.assertNotIn(("due", "O-3", "change"), self.calls)  # quantity 50 not yet
        self.assertIn(("hourly", "K-1", "schedule"), self.calls)
        self.calls.clear()
        self.now = 100
        self.engine.tick()
        self.assertEqual(self.calls, [("due", "O-2", "change"), ("due", "O-3", "change")])  # hourly not due yet
        self.calls.clear()
        self.now = 100 + 3600
        self.engine.tick()
        self.assertEqual(self.calls, [("hourly", "K-1", "schedule")])

    def test_run_now_and_errors(self):
        holding = self.engine.run_now("big")
        self.assertEqual(len(holding), 1)  # only where the condition holds
        self.assertEqual(holding[0].trigger, "manual")
        skipped = self.engine.run_now("big", "O-1")[0]  # by hand on one instance: the condition still applies
        self.assertEqual(skipped.status, "skipped")
        self.assertIn("condition does not hold", skipped.detail)
        with self.assertRaises(KeyError):
            self.engine.run_now("big", "K-1")
        with self.assertRaises(KeyError):  # an instance the caller may not see is like one that does not exist
            self.engine.run_now("big", holding[0].instance, allow=lambda i: False)
        self.assertEqual(self.engine.run_now("big", allow=lambda i: False), [])

        def broken(auto, inst, trigger):
            raise RuntimeError("tool down")

        firing = self._engine(broken).run_now("big", holding[0].instance)[0]
        self.assertEqual((firing.status, firing.detail),
                         ("error", "RuntimeError: tool down; retry 2 of 5 after 300s"))

    def test_firings_that_write_back_are_queued(self):
        def cascade(auto, inst, trigger):
            self.calls.append((auto.name, inst.id))
            if inst.id == "O-3":  # this firing changes O-2, which must be evaluated afterwards
                self.graph.get("O-2").attributes["amount"] = 20000
                engine.on_change(["O-2"])
            return Firing(auto.name, inst.id, trigger)

        engine = self._engine(cascade)
        fired = engine.on_change(["O-3"])
        self.assertIn(("big", "O-2"), self.calls)
        self.assertEqual(len(fired), 4)  # big and due for O-3, then for O-2


class ServiceAutomationTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        self.users = {u.name: u for u in self.svc.users}

    def test_tick_runs_on_graph_data_and_writes_back(self):
        out = self.svc.tick()
        self.assertEqual([(f["automation"], f["instance"], f["status"]) for f in out["firings"]],
                         [("fulfil_signed_contracts", "K-1", "completed")])
        self.assertEqual([self.svc.graph.get(o).attributes["status"] for o in ("O-1", "O-2", "O-3")],
                         ["invoiced"] * 3)
        reloaded = self.svc.store.load_graph(self.svc.ontology)  # written to the store too
        self.assertTrue(reloaded.get("O-2").attributes["hazmat_cleared"])
        self.assertEqual(self.svc.tick()["firings"], [])  # already fired for K-1
        lena = self.svc.list_notifications(self.users["lena"], None, 10)["items"]
        self.assertEqual([n["message"] for n in lena], ["Contract K-1 is signed: fulfilment started"])
        self.assertEqual(self.svc.list_notifications(self.users["olivia"], None, 10)["items"], [])
        self.assertEqual(len(self.svc.list_notifications(self.users["admin"], None, 10)["items"]), 1)
        autos = self.svc.list_automations(self.users["olivia"])["items"]
        self.assertEqual(autos[0]["recent"][0]["run_status"], "completed")

    def test_signing_a_contract_starts_a_governed_run(self):
        admin, lena = self.users["admin"], self.users["lena"]
        self.svc.upsert_object(admin, {"type": "Customer", "id": "C-2", "attributes": {
            "name": "Acme", "region": "US", "credit_limit": 10 ** 6, "status": "approved"}})
        self.svc.upsert_object(admin, {"type": "Contract", "id": "K-2", "attributes": {"value": 1, "status": "draft"},
                                       "links": []})
        self.svc.upsert_object(admin, {"type": "Order", "id": "O-9", "attributes": {
            "sku": "X", "quantity": 1, "amount": 90000, "region": "US", "hazardous": False}})
        for s, k, t in [("C-2", "hasContract", "K-2"), ("K-2", "covers", "O-9")]:
            self.svc.graph.link(s, k, t)
        signed = self.svc.upsert_object(admin, {"type": "Contract", "id": "K-2",
                                                "attributes": {"value": 1, "status": "signed"}})
        firing = signed["triggered"][0]
        self.assertEqual(firing["status"], "awaiting_review")  # O-9 is above the review threshold
        self.assertEqual(self.svc.graph.get("O-9").attributes["status"], "picked")  # partial progress written back
        kinds = [n["kind"] for n in self.svc.list_notifications(lena, None, 10)["items"]]
        self.assertIn("review", kinds)
        review = self.svc.list_reviews(lena, "pending")["items"][0]
        done = self.svc.decide(lena, review["review_id"], {"approved": True, "comment": "ok"})
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.svc.graph.get("O-9").attributes["status"], "invoiced")

    def test_start_run_from_a_case_template(self):
        olivia = self.users["olivia"]
        out = self.svc.start_run(olivia, {"case_template": "contract_case", "root": "K-1", "write_back": False})
        self.assertEqual((out["status"], out["case_id"]), ("completed", "K-1"))
        self.assertEqual(self.svc.graph.get("O-3").attributes["status"], "received")  # write_back off
        from autology.server import ApiError

        for body in [{"case_template": "contract_case", "root": "nobody"},
                     {"case_template": "ghost", "root": "K-1"}]:
            with self.subTest(body), self.assertRaises(ApiError):
                self.svc.start_run(olivia, body)

    def test_scheduled_notifications_respect_row_access(self):
        admin = self.users["admin"]
        for oid, region in [("O-10", "EU"), ("O-11", "US")]:
            self.svc.upsert_object(admin, {"type": "Order", "id": oid, "attributes": {
                "sku": "Y", "quantity": 1, "amount": 70000, "region": region, "hazardous": False}})
        firings = [f for f in self.svc.tick()["firings"] if f["automation"] == "large_order_watch"]
        self.assertEqual(sorted(f["instance"] for f in firings), ["O-10", "O-11"])
        audrey = self.svc.list_notifications(self.users["audrey"], None, 10)["items"]
        self.assertEqual([n["message"] for n in audrey], ["Order O-11 for 70000 is still waiting for a credit check"])
        self.assertEqual(self.svc.list_notifications(self.users["audrey"], "9999", 10)["items"], [])
        self.assertEqual(len(self.svc.list_notifications(self.users["audrey"], None, 0)["items"]), 0)

    def test_api_endpoints(self):
        api = _Api(self.svc)
        try:
            self.assertEqual(api.call("POST", "/api/tick", "olivia", {})[0], 403)
            status, out, _ = api.call("POST", "/api/tick", "admin", {})
            self.assertEqual((status, len(out["firings"])), (200, 1))
            status, autos, _ = api.call("GET", "/api/automations", "olivia")
            self.assertEqual([a["name"] for a in autos["items"]], ["fulfil_signed_contracts", "large_order_watch"])
            self.assertEqual(api.call("POST", "/api/automations/ghost/run", "olivia", {})[0], 404)
            self.assertEqual(api.call("POST", "/api/automations/large_order_watch/run", "lena", {})[0], 403)
            self.assertEqual(api.call("POST", "/api/automations/large_order_watch/run", "olivia",
                                      {"instance": "O-3"})[0], 404)  # hidden from olivia
            self.assertEqual(api.call("POST", "/api/automations/large_order_watch/run", "olivia",
                                      {"instance": "K-1"})[0], 400)  # not an Order
            status, run, _ = api.call("POST", "/api/automations/fulfil_signed_contracts/run", "olivia",
                                      {"instance": "K-1"})
            self.assertEqual(run["firings"][0]["trigger"], "manual")
            status, notes, _ = api.call("GET", "/api/notifications?limit=5", "lena")
            self.assertEqual((status, len(notes["items"])), (200, 2))
        finally:
            api.server.shutdown()

    def test_deferred_runs_resume_on_tick(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "flaky_auto_tools.py").write_text(
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
        doc = copy.deepcopy(DOC)
        doc["actions"]["pick_order"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": 3600,
                                                      "fallback_tools": False}
        (tmp / "ontology.json").write_text(json.dumps(doc))
        (tmp / "data.json").write_text(json.dumps(DATA))
        tools = json.loads((EX / "tools.json").read_text())
        (tmp / "tools.json").write_text(json.dumps({**tools, "python_path": ["."],
                                                    "registries": ["flaky_auto_tools:build"]}))
        cfg = {"ontology": "ontology.json", "store": "s.db", "data": "data.json",
               "agents": {"ops": {"roles": ["ops", "eu_ops", "finance"], "tools": "tools.json", "approver": "auto"}},
               "simulation": True,
               "users": [{"name": "admin", "token_env": "AUTOLOGY_TOKEN_ADMIN", "permissions": ["admin"]}]}
        from autology.server import AutologyService

        svc = AutologyService(cfg, tmp)
        admin = svc.users[0]
        out = svc.start_run(admin, {"case_template": "contract_case", "root": "K-1"})
        self.assertEqual(out["status"], "deferred")
        self.assertEqual(svc.tick(), {"resumed": [], "firings": []})  # retry window not reached
        svc.agents["ops"].agent.clock = lambda: 10 ** 12
        self.assertEqual(svc.tick()["resumed"], [{"run_id": out["run_id"], "status": "completed"}])
        self.assertEqual(svc.graph.get("O-3").attributes["status"], "invoiced")
        svc.store._db.execute("UPDATE runs SET agent='gone' WHERE run_id=?", (out["run_id"],))
        svc.store._db.execute("UPDATE runs SET status='deferred' WHERE run_id=?", (out["run_id"],))
        self.assertEqual(svc.tick()["resumed"], [])  # agent no longer configured: left alone

    def test_background_scheduler(self):
        stop = self.svc.start_background(0.01)
        try:
            for _ in range(500):
                if self.svc.store.list_firings():
                    break
                threading.Event().wait(0.01)
        finally:
            stop.set()
        self.assertEqual(self.svc.store.list_firings()[0]["instance"], "K-1")

    def test_webhooks(self):
        received = []

        class Hook(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass

        hook = HTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=hook.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{hook.server_port}/hook"
            svc = service(webhooks=[{"url": url, "kinds": ["automation"]},
                                    {"url": "http://127.0.0.1:1/unreachable"}])
            svc.tick()
            for t in list(svc.deliveries):
                t.join(10)
            self.assertEqual([r["autology"]["kind"] for r in received], ["automation"])
        finally:
            hook.shutdown()
        with self.assertRaises(ValueError):
            service(webhooks=[{"url": "file:///etc/passwd"}])

    def test_invalid_automation_config(self):
        with self.assertRaises(OntologyError):
            service(automations={"x": {"entity": "Ghost", "notify": {"roles": ["a"]}}})


class StoreMigrationTests(unittest.TestCase):
    def test_version_one_store_is_upgraded(self):
        path = Path(tempfile.mkdtemp()) / "old.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        db.commit()
        db.close()
        store = Store(path)
        self.assertEqual(store._query("SELECT value FROM meta")[0]["value"], str(SCHEMA_VERSION))
        self.assertIsNone(store.run_sources("nothing"))
        self.assertIsNone(store.automation_state("a", "b"))
        self.assertEqual(store.list_firings(), [])


if __name__ == "__main__":
    unittest.main()
