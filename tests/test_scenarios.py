"""Tier 2: what-if scenarios on a fork of the knowledge graph."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from autology import Ontology
from autology.__main__ import main as cli
from autology.graph import KnowledgeGraph
from autology.scenarios import ConflictError, Scenario, ScenarioError, render
from autology.store import Store

from .helpers import ROOT
from .test_platform import EX, _Api, service

DATA = json.loads((EX / "data.json").read_text())
SCHED = ROOT / "examples" / "scheduling"
ALL = ["ops", "eu_ops", "finance"]
NEW_ORDER = {"op": "add", "type": "Order", "id": "O-6",
             "attributes": {"sku": "T", "quantity": 1, "amount": 95000, "region": "US", "hazardous": False},
             "links": [{"kind": "covers", "source": "K-1"}]}


def act(action, target=None, roles=ALL, **kw):
    edit = {"op": "action", "action": action, "case_template": "contract_case", "root": "K-1", "roles": roles, **kw}
    if target:
        edit["target"] = target
    return edit


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(EX / "ontology.json")
        self.graph = KnowledgeGraph.from_dict(self.onto, DATA)

    def test_edits_never_touch_the_base_graph(self):
        s = Scenario(self.graph, "s")
        s.apply({"op": "set", "id": "O-3", "attributes": {"amount": 60000}})
        s.apply(NEW_ORDER)
        s.apply({"op": "link", "source": "K-1", "kind": "covers", "target": "O-6"})
        self.assertEqual(self.graph.get("O-3").attributes["amount"], 12000)
        self.assertNotIn("O-6", self.graph._instances)
        d = s.diff()
        self.assertEqual(d["changed"], {"O-3": {"amount": [12000, 60000]}})
        self.assertEqual((d["added"], d["added_status"]), (["O-6"], {"O-6": "Order, received"}))
        self.assertEqual(len(d["links"]), 2)

    def test_simulated_actions_are_governed(self):
        s = Scenario(self.graph)
        allowed = s.apply(act("credit_check", "O-3"))
        self.assertEqual((allowed["verdict"], allowed["applied"], allowed["changed"]), ("allow", True, ["O-3"]))
        self.assertEqual(s.graph.get("O-3").attributes["status"], "credit_checked")
        denied = s.apply(act("credit_check", "O-3", roles=["ops"]))  # no longer received, and not finance
        self.assertEqual((denied["verdict"], denied["applied"]), ("deny", False))
        self.assertIn("R-FIN-002", denied["rules"])
        hazmat = s.apply(act("ship_order", "O-2"))
        self.assertEqual(hazmat["rules"], ["R-HAZ-001"])  # mandatory step first
        s.apply(act("clear_hazmat", "O-2"))
        shipped = s.apply(act("ship_order", "O-2"))  # the step done in this scenario counts
        self.assertTrue(shipped["applied"])
        s.apply(NEW_ORDER)
        for step in ("credit_check", "pick_order"):
            s.apply(act(step, "O-6"))
        review = s.apply(act("ship_order", "O-6"))
        self.assertEqual((review["verdict"], review["needs_review_by"]), ("review", ["logistics_manager"]))
        self.assertEqual(s.graph.get("O-6").attributes["status"], "shipped")

    def test_invalid_edits(self):
        s = Scenario(self.graph)
        bad = [
            {"op": "delete"},
            {"op": "set", "id": "nobody", "attributes": {}},
            {"op": "set", "id": "O-1", "attributes": {"status": "lost"}},
            {"op": "set", "id": "O-1", "attributes": {"colour": "red"}},
            {"op": "add", "type": "Order"},
            {"op": "add", "type": "Order", "id": "O-1"},
            {"op": "add", "type": "Order", "id": "O-8", "links": [{"kind": "covers", "source": "nobody"}]},
            {"op": "link", "source": "K-1", "kind": "covers", "target": "nobody"},
            {"op": "link", "source": "O-1", "kind": "covers", "target": "O-2"},
            act("fly"),
            act("ship_order"),  # needs a target
            act("ship_order", "O-99"),
            act("sign_contract", "O-1"),  # takes no target
            act("ship_order", "O-2", outcome="lost"),
            {"op": "event", "id": "nobody"},
        ]
        for edit in bad:
            with self.subTest(edit), self.assertRaises((ScenarioError, Exception)):
                s.apply(edit)
        self.assertNotIn("O-8", s.graph._instances)  # a failed add is rolled back
        self.assertEqual(s.edits, [])
        self.assertEqual(s.diff()["changed"], {})

    def test_outcomes(self):
        s = Scenario(self.graph)
        out = s.apply(act("credit_check", "O-3", outcome=self.onto.actions["credit_check"].outcomes[-1].name))
        self.assertTrue(out["applied"])

    def test_conflicts_and_commit(self):
        store = Store(":memory:")
        store.save_graph(self.graph)
        s = Scenario(self.graph, "s", [{"op": "set", "id": "O-3", "attributes": {"amount": 60000}}, NEW_ORDER])
        self.assertEqual(s.conflicts(), [])
        # replayed later from its stored edits and snapshot: still detects that live data moved
        stored = Scenario(self.graph, "s", s.edits, s.snapshot)
        self.graph.get("O-3").attributes["amount"] = 1
        self.assertEqual(stored.conflicts(), [{"id": "O-3", "attribute": "amount", "read": 12000, "live": 1}])
        with self.assertRaises(ConflictError):
            stored.commit()
        self.graph.get("O-3").attributes["amount"] = 12000
        written = stored.commit(store=store)
        self.assertEqual(sorted(written), ["O-3", "O-6"])
        self.assertEqual(self.graph.get("O-3").attributes["amount"], 60000)
        reloaded = store.load_graph(self.onto)
        self.assertEqual(reloaded.ask("CQ-01").answer, ["O-1", "O-2", "O-3", "O-6"])
        self.assertEqual(Scenario(self.graph, "again", [{**NEW_ORDER, "id": "O-7"}]).conflicts(), [])
        clash = Scenario(KnowledgeGraph.from_dict(self.onto, DATA), "c", [NEW_ORDER])
        self.assertEqual(clash.conflicts(self.graph)[0]["live"], "exists")

    def test_compare_plans_and_questions(self):
        s = Scenario(self.graph, "s", [NEW_ORDER, {"op": "set", "id": "O-3", "attributes": {"amount": 1}}])
        checks = [{"goal": "fulfil_contract", "case_template": "contract_case", "root": "K-1", "roles": ALL},
                  {"goal": "fulfil_contract", "case_template": "contract_case", "root": "K-1", "roles": ["ops"]},
                  {"goal": "fulfil_contract", "case_template": "contract_case", "root": "K-404", "roles": ALL}]
        report = s.compare(checks)
        q = {x["id"]: x for x in report["questions"]}
        self.assertTrue(q["CQ-01"]["changed"])
        self.assertEqual((q["CQ-03"]["baseline"], q["CQ-03"]["scenario"]), (12000, 1))
        self.assertFalse(q["CQ-02"]["changed"])
        full, ops, absent = report["plans"]
        self.assertEqual((full["baseline"]["length"], full["scenario"]["length"]), (7, 11))
        self.assertEqual(full["scenario"]["reviews"], ["ship_order@O-6"])
        self.assertEqual(ops["scenario"]["status"], "blocked")
        self.assertIn("R-FIN-002", ops["scenario"]["rules"])
        self.assertEqual(absent["scenario"], {"status": "absent"})
        text = render(report)
        self.assertIn("11 steps, 1 need human review", text)
        self.assertIn("blocked at credit_check", text)
        with self.assertRaises(ScenarioError):
            s.compare([{"goal": "ghost", "case_template": "contract_case", "root": "K-1"}])
        with self.assertRaises(ScenarioError):
            s.compare(schedule=True)  # no scheduling section

    def test_reached_and_unreachable(self):
        graph = KnowledgeGraph.from_dict(self.onto, DATA)
        for o in ("O-2", "O-3"):
            graph.get(o).attributes["status"] = "cancelled"
        check = {"goal": "fulfil_contract", "case_template": "contract_case", "root": "K-1", "roles": ALL}
        self.assertEqual(Scenario(graph).compare([check], questions=False)["plans"][0]["baseline"]["status"], "reached")
        doc = json.loads((EX / "ontology.json").read_text())
        doc["goals"]["fulfil_contract"]["target"] = "Contract.status == 'draft'"  # no action un-signs a contract
        onto = Ontology.from_dict(doc)
        plan = Scenario(KnowledgeGraph.from_dict(onto, DATA)).compare([check], questions=False)["plans"][0]
        self.assertEqual(plan["baseline"]["status"], "unreachable")

    def test_question_errors_are_reported(self):
        from unittest import mock

        s = Scenario(self.graph)
        with mock.patch.object(s.base, "ask", side_effect=ScenarioError("needs a parameter")):
            report = s.compare()
        self.assertEqual(report["questions"][0]["error"], "needs a parameter")

    def test_machine_breakdown_scenario(self):
        onto = Ontology.load(SCHED / "ontology.json")
        graph = KnowledgeGraph.from_dict(onto, json.loads((SCHED / "data.json").read_text()))
        spec = json.loads((SCHED / "scenario_breakdown.json").read_text())
        s = Scenario(graph, spec["name"], spec["edits"])
        self.assertEqual(s.results[0]["changed"], ["EQ_05"])
        self.assertTrue(s.results[0]["risks"])
        report = s.compare(schedule=True)
        sched = report["schedule"]
        self.assertEqual(sched["baseline"]["on_hold"], {})
        self.assertGreater(len(sched["scenario"]["on_hold"]), 0)
        self.assertEqual(sched["scenario"]["jobs_scheduled"] + len(sched["scenario"]["on_hold"]),
                         sched["baseline"]["jobs_scheduled"])
        self.assertIn("Newly on hold", render(report))
        self.assertEqual(graph.get("EQ_05").attributes["status"], "available")  # base untouched


class ScenarioCliTests(unittest.TestCase):
    def test_cli(self):
        out, err = io.StringIO(), io.StringIO()
        target = Path(tempfile.mkdtemp()) / "after.json"
        spec = json.loads((EX / "scenario.json").read_text())
        spec["edits"].append(act("credit_check", "O-3", roles=["ops"]))  # denied: reported on stderr
        path = target.with_name("scenario.json")
        path.write_text(json.dumps(spec))
        with redirect_stdout(out), redirect_stderr(err):
            code = cli(["scenario", str(EX / "ontology.json"), str(EX / "data.json"), str(path), "--commit", str(target)])
        self.assertEqual(code, 0)
        self.assertIn("1 need human review", out.getvalue())
        self.assertIn("was denied", err.getvalue())
        after = json.loads(target.read_text())
        self.assertIn("O-6", [i["id"] for i in after["instances"]])
        path.write_text(json.dumps(spec["edits"][:1]))  # a bare list of edits
        out = io.StringIO()
        with redirect_stdout(out):
            cli(["scenario", str(EX / "ontology.json"), str(EX / "data.json"), str(path), "--json"])
        self.assertEqual(json.loads(out.getvalue())["diff"]["added"], ["O-6"])


class ScenarioApiTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})
        self.users = {u.name: u for u in self.svc.users}

    def test_lifecycle(self):
        from autology.server import ApiError

        svc, u = self.svc, self.users
        with self.assertRaises(ApiError) as cm:
            svc.create_scenario(u["lena"], {"name": "x"})  # needs run permission
        self.assertEqual(cm.exception.status, 403)
        created = svc.create_scenario(u["olivia"], {"name": "rush", "edits": [NEW_ORDER]})
        sid = created["scenario_id"]
        self.assertEqual((created["diff"]["added"], created["status"]), (["O-6"], "open"))
        # the agent's roles make the simulated action allowed; olivia's own would be denied
        view = svc.add_scenario_edits(u["olivia"], sid, {"edits": [act("credit_check", "O-6", agent="fulfilment")]})
        self.assertEqual(view["results"][-1]["verdict"], "allow")
        view = svc.add_scenario_edits(u["olivia"], sid, {"edits": [act("pick_order", "O-6", roles=["admin-ish"])]})
        self.assertEqual(view["results"][-1]["verdict"], "allow")  # roles ignored for non-admins: her own (ops)
        self.assertEqual(svc.store.get_scenario(sid)["edits"][-1]["roles"], ["ops"])
        for who, body, status in [
            ("olivia", {"edits": [{"op": "set", "id": "O-3", "attributes": {"amount": 1}}]}, 404),  # hidden row
            ("olivia", {"edits": [act("credit_check", "O-6", agent="ghost")]}, 400),
            ("olivia", {"edits": "nope"}, 400),
            ("olivia", {"edits": ["nope"]}, 400),
            ("olivia", {"edits": [{"op": "set", "id": "O-1", "attributes": {"status": "lost"}}]}, 400),
            ("admin", {"edits": None}, 400),
        ]:
            with self.subTest(body), self.assertRaises(ApiError) as cm:
                svc.add_scenario_edits(u[who], sid, body)
            self.assertEqual(cm.exception.status, status)

        lena_view = svc.get_scenario(u["lena"], sid)
        self.assertEqual(len(lena_view["results"]), 3)
        with self.assertRaises(ApiError) as cm:
            svc.compare_scenario(u["olivia"], sid, {"checks": [{"goal": "fulfil_contract", "case_template":
                                                                 "contract_case", "root": "O-3"}]})
        self.assertEqual(cm.exception.status, 404)
        checks = [{"goal": "fulfil_contract", "case_template": "contract_case", "root": "K-1", "agent": "fulfilment"}]
        report = svc.compare_scenario(u["olivia"], sid, {"checks": checks})
        q = {x["id"]: x for x in report["questions"]}
        self.assertEqual(q["CQ-03"]["baseline"], "withheld: aggregates rows you may not see")
        self.assertNotIn("O-3", q["CQ-01"]["scenario"])
        steps = report["plans"][0]["scenario"]["steps"]
        self.assertIn("ship_order@(hidden)", steps)
        self.assertNotIn("ship_order@O-3", steps)
        admin_report = svc.compare_scenario(u["admin"], sid, {"checks": checks})
        self.assertIn("ship_order@O-3", admin_report["plans"][0]["scenario"]["steps"])
        with self.assertRaises(ApiError) as cm:
            svc.compare_scenario(u["olivia"], sid, {"checks": [{**checks[0], "goal": "ghost"}]})
        self.assertEqual(cm.exception.status, 400)
        blocked = svc.compare_scenario(u["olivia"], sid, {"checks": [{**checks[0], "agent": None}]})
        self.assertEqual(blocked["plans"][0]["scenario"]["status"], "blocked")
        self.assertEqual(blocked["plans"][0]["scenario"]["action"], "credit_check@(hidden)")

        with self.assertRaises(ApiError) as cm:
            svc.commit_scenario(u["olivia"], sid)
        self.assertEqual(cm.exception.status, 403)
        done = svc.commit_scenario(u["admin"], sid)
        self.assertEqual(done["written"], ["O-6"])
        self.assertEqual(svc.graph.get("O-6").attributes["status"], "picked")
        self.assertEqual(svc.store.load_graph(svc.ontology).get("O-6").attributes["status"], "picked")
        with self.assertRaises(ApiError) as cm:
            svc.discard_scenario(u["olivia"], sid)
        self.assertEqual(cm.exception.status, 409)  # already committed
        self.assertEqual(svc.list_scenarios(u["lena"], "committed")["items"][0]["scenario_id"], sid)

    def test_ownership_conflicts_and_stale_scenarios(self):
        from autology.server import ApiError

        svc, u = self.svc, self.users
        sid = svc.create_scenario(u["olivia"], {"edits": [{"op": "set", "id": "O-1", "attributes": {"amount": 5}}]})[
            "scenario_id"]
        with self.assertRaises(ApiError) as cm:
            svc.discard_scenario(service().users[0], "nope")
        self.assertEqual(cm.exception.status, 404)
        svc.users.append(type(u["olivia"])("olga", "0" * 64, frozenset({"read", "run"})))
        with self.assertRaises(ApiError) as cm:
            svc.add_scenario_edits(svc.users[-1], sid, {"edits": []})
        self.assertEqual(cm.exception.status, 403)  # not hers
        svc.upsert_object(u["admin"], {"type": "Order", "id": "O-1", "attributes": {
            "sku": "PUMP-10", "quantity": 4, "amount": 9999, "region": "US", "hazardous": False, "status": "invoiced"}})
        view = svc.get_scenario(u["olivia"], sid)
        self.assertEqual(view["conflicts"][0]["live"], 9999)
        with self.assertRaises(ApiError) as cm:
            svc.commit_scenario(u["admin"], sid)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(svc.discard_scenario(u["olivia"], sid)["status"], "discarded")
        # a scenario whose edits no longer apply to the live data
        sid2 = svc.create_scenario(u["olivia"], {"edits": [NEW_ORDER]})["scenario_id"]
        svc.upsert_object(u["admin"], {"type": "Order", "id": "O-6", "attributes": {"sku": "X"}})
        with self.assertRaises(ApiError) as cm:
            svc.get_scenario(u["olivia"], sid2)
        self.assertEqual(cm.exception.status, 409)

    def test_admin_roles_and_commit_triggers_automations(self):
        svc = service()
        admin = next(x for x in svc.users if x.name == "admin")
        svc.tick()  # K-1 fulfilled and its automation armed
        sid = svc.create_scenario(admin, {"edits": [
            {"op": "add", "type": "Contract", "id": "K-5", "attributes": {"value": 1, "status": "signed"}},
            act("credit_check", "O-3", roles=["finance", "eu_ops"])]})["scenario_id"]
        self.assertEqual(svc.store.get_scenario(sid)["edits"][1]["roles"], ["finance", "eu_ops"])
        done = svc.commit_scenario(admin, sid)
        self.assertEqual(done["triggered"][0]["instance"], "K-5")

    def test_http_routes(self):
        api = _Api(self.svc)
        try:
            status, created, _ = api.call("POST", "/api/scenarios", "olivia", {"name": "h", "edits": [NEW_ORDER]})
            self.assertEqual(status, 200)
            sid = created["scenario_id"]
            self.assertEqual(api.call("GET", "/api/scenarios", "lena")[1]["items"][0]["scenario_id"], sid)
            self.assertEqual(api.call("GET", f"/api/scenarios/{sid}", "lena")[1]["diff"]["added"], ["O-6"])
            self.assertEqual(api.call("GET", "/api/scenarios/nope", "lena")[0], 404)
            self.assertEqual(api.call("POST", f"/api/scenarios/{sid}/edits", "olivia", {"edits": []})[0], 200)
            self.assertEqual(api.call("POST", f"/api/scenarios/{sid}/compare", "lena", {})[0], 200)
            self.assertEqual(api.call("POST", f"/api/scenarios/{sid}/fly", "olivia", {})[0], 405)
            self.assertEqual(api.call("POST", f"/api/scenarios/{sid}/commit", "admin", {})[0], 200)
            sid2 = api.call("POST", "/api/scenarios", "olivia", {})[1]["scenario_id"]
            self.assertEqual(api.call("POST", f"/api/scenarios/{sid2}/discard", "olivia", {})[1]["status"], "discarded")
        finally:
            api.server.shutdown()


if __name__ == "__main__":
    unittest.main()
