"""Multi-instance cases: many orders under one contract, per-instance actions and rules, row-level access."""

import copy
import json
import time
import unittest

from autology import AutoApprover, ExpressionError, Ontology, OntologyError, ToolResult, WorkAgent, compile_expression
from autology.adapters import load_approver, load_tools
from autology.agent import ReviewRequest
from autology.governance import GovernanceLayer, Principal, Verdict
from autology.persistence import result_from_dict, result_to_dict
from autology.planner import Planner
from autology.state import WorldState, ground_name, parse_ground

from .helpers import ROOT

EX = ROOT / "examples" / "order_fulfilment"
DOC = json.loads((EX / "ontology.json").read_text())
CASE = json.loads((EX / "case.json").read_text())


def onto(mutate=None):
    d = copy.deepcopy(DOC)
    if mutate:
        mutate(d)
    return Ontology.from_dict(d)


def agent(o=None, roles=("ops", "eu_ops", "finance"), **kw):
    o = o or onto()
    kw.setdefault("approver", AutoApprover({"ship_order": True}))
    return WorkAgent("fulfilment-agent", o, kw.pop("tools", None) or load_tools(EX / "tools.json"), roles=roles, **kw)


class ExpressionTests(unittest.TestCase):
    def state(self):
        return WorldState.initial(onto(), CASE)

    def test_quantifiers(self):
        st = self.state()
        r = st.resolver()
        self.assertTrue(compile_expression("all_of(Order.status == 'received')").evaluate(r))
        self.assertFalse(compile_expression("any_of(Order.amount > 500000)").evaluate(r))
        self.assertTrue(compile_expression("count_of(Order.amount >= 50000) == 2").evaluate(r))
        self.assertTrue(compile_expression("count_of(Order.region == 'EU') == 1 and Contract.status == 'draft'")
                        .evaluate(r))
        self.assertTrue(compile_expression("all_of(Customer.region == 'US')").evaluate(r))  # single entity: once
        st.set("Order", "status", "invoiced", "O-1")
        goal = compile_expression("Contract.status == 'signed' and all_of(Order.status == 'invoiced')")
        self.assertEqual(goal.deficit(st.resolver()), 1 + 4)  # contract + 4 orders still open
        self.assertEqual(r("Order", "status"), None)  # unbound multi-instance reference
        self.assertEqual(st.resolver({"Order": "O-1"})("Order", "id"), "O-1")

    def test_invalid_quantifiers(self):
        for bad in ("len(Order.status)", "all_of(Order.status == 'x', Order.amount > 1)", "all_of(1 == 1)",
                    "all_of(x=Order.status)", "foo(Order.status)"):
            with self.subTest(bad), self.assertRaises(ExpressionError):
                compile_expression(bad)

    def test_ground_names(self):
        self.assertEqual(ground_name("ship_order", "O-1"), "ship_order@O-1")
        self.assertEqual(parse_ground("ship_order@O-1"), ("ship_order", "O-1"))
        self.assertEqual(parse_ground("sign_contract"), ("sign_contract", None))


class ValidationTests(unittest.TestCase):
    def test_invalid_ontologies(self):
        act = lambda d, n: d["actions"][n]  # noqa: E731
        cases = {
            "for_each on single entity": lambda d: act(d, "sign_contract").update(for_each="Contract"),
            "unbound multi reference": lambda d: act(d, "sign_contract")["requires"].append("Order.amount > 1"),
            "unbound multi effect": lambda d: act(d, "sign_contract").update(effects={"Order": {"status": "picked"}}),
            "goal outside quantifier": lambda d: d["goals"]["fulfil_contract"].update(target="Order.status == 'x'"),
            "row condition other entity": lambda d: d["rules"].append(
                {"id": "R-X", "type": "row_access", "entity": "Order", "roles": ["x"], "when": "Customer.region == 'EU'"}),
            "row unknown entity": lambda d: d["rules"].append({"id": "R-X", "type": "row_access", "entity": "Ghost",
                                                               "roles": ["x"]}),
            "row no roles": lambda d: d["rules"].append({"id": "R-X", "type": "row_access", "entity": "Order"}),
        }
        for label, mutate in cases.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                onto(mutate)

        def two_multis(d):
            d["entities"]["Line"] = {"multiple": True, "states": ["open"], "attributes": {"qty": "integer"}}
            d["goals"]["fulfil_contract"]["target"] = "all_of(Order.status == 'x' and Line.qty > 1)"
        with self.assertRaisesRegex(OntologyError, "one multi-instance entity"):
            onto(two_multis)

    def test_case_data(self):
        o = onto()
        bad = {
            "dict for multi": {**CASE, "Order": {"sku": "x"}},
            "duplicate id": {**CASE, "Order": [{"id": "A"}, {"id": "A"}]},
            "bad state": {**CASE, "Order": [{"id": "A", "status": "teleported"}]},
            "list for single": {**CASE, "Contract": [{"value": 1}]},
            "unknown attribute": {**CASE, "Order": [{"id": "A", "colour": "red"}]},
        }
        for label, case in bad.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                WorldState.initial(o, case)
        st = WorldState.initial(o, {**CASE, "Order": [{"sku": "a"}, {"sku": "b"}]})
        self.assertEqual(st.instances("Order"), ["Order-1", "Order-2"])  # ids generated when missing
        with self.assertRaises(OntologyError):
            st.set("Order", "status", "picked")  # must say which instance
        self.assertIn("Order[2]", repr(st))


class FulfilmentRunTests(unittest.TestCase):
    def test_every_order_handled_with_per_instance_rules(self):
        approver = AutoApprover({"ship_order": True})
        result = agent(approver=approver).run("fulfil_contract", CASE, "K-1")
        self.assertTrue(result.completed, result.escalation)
        statuses = {k: v["status"] for k, v in result.state.collections["Order"].items()}
        self.assertEqual(statuses, {"O-1": "invoiced", "O-2": "invoiced", "O-3": "invoiced", "O-4": "invoiced",
                                    "O-5": "cancelled"})  # O-5 exceeds the 100k credit limit
        actions = [s.action for s in result.steps]
        self.assertEqual([a for a in actions if a.startswith("clear_hazmat")], ["clear_hazmat@O-2"])
        self.assertLess(actions.index("clear_hazmat@O-2"), actions.index("ship_order@O-2"))
        self.assertEqual([r.action for r in approver.requests], ["ship_order@O-4"])  # only the 85k order
        self.assertEqual(approver.requests[0].binding, {"Order": "O-4"})
        self.assertEqual(result.state.collections["Order"]["O-3"]["tracking"], "EU-TRACK")  # tool `when` per instance
        self.assertEqual(result.state.steps["clear_hazmat@O-2"], "done")
        self.assertTrue(result.audit.verify())

    def test_tools_receive_the_bound_instance(self):
        seen = []
        tools = load_tools(EX / "tools.json")

        def spy(call):
            seen.append((call.target, call.inputs["Order.sku"]))
            return ToolResult()

        tools.register("spy_wms", "warehouse.pick", spy, priority=9)
        agent(tools=tools).run("fulfil_contract", CASE)
        self.assertEqual(sorted(seen), [("O-1", "PUMP-10"), ("O-2", "SOLVENT-5"), ("O-3", "VALVE-2"),
                                        ("O-4", "TURBINE-1")])

    def test_tool_cannot_touch_another_instance(self):
        tools = load_tools(EX / "tools.json")
        tools.register("rogue_carrier", "carrier.ship", lambda c: ToolResult(updates={"Customer": {"name": "x"}}),
                       priority=9)
        res = agent(tools=tools).run("fulfil_contract", CASE)
        self.assertEqual(res.status, "escalated")
        self.assertIn("undeclared field", res.escalation.reason)

    def test_policy_conditions_see_the_instance_under_review(self):
        policy = load_approver(str(EX / "approvals.json"))  # approve ship_order when Order.amount < 100000
        view = {"Order": {"O-4": {"amount": 85000}, "O-9": {"amount": 250000}}}
        ok = ReviewRequest("c", "ship_order@O-4", "", ("x",), [], view, binding={"Order": "O-4"})
        no = ReviewRequest("c", "ship_order@O-9", "", ("x",), [], view, binding={"Order": "O-9"})
        self.assertTrue(policy.review(ok).approved)
        self.assertFalse(policy.review(no).approved)

    def test_persistence_keeps_collections(self):
        result = agent().run("fulfil_contract", CASE)
        back = result_from_dict(json.loads(json.dumps(result_to_dict(result))))
        self.assertEqual(back.state.collections, result.state.collections)
        self.assertTrue(back.audit.verify())

    def test_planner_scales_to_many_instances(self):
        many = copy.deepcopy(CASE)
        many["Order"] = [{"id": f"O-{i:02d}", "sku": "PUMP-10", "quantity": 1, "amount": 1000 + i, "region": "US",
                          "hazardous": i % 4 == 0} for i in range(12)]
        t0 = time.perf_counter()
        result = agent().run("fulfil_contract", many)
        self.assertTrue(result.completed, result.escalation)
        self.assertEqual(len([s for s in result.steps if s.action.startswith("invoice_order")]), 12)
        self.assertLess(time.perf_counter() - t0, 60)


class RowAccessTests(unittest.TestCase):
    def setUp(self):
        self.o = onto()
        self.gov = GovernanceLayer(self.o)
        self.state = WorldState.initial(self.o, CASE)

    def test_redacted_view_hides_rows(self):
        us = self.gov.redacted_view(self.state, Principal("us", ["ops"]))
        eu = self.gov.redacted_view(self.state, Principal("eu", ["ops", "eu_ops", "finance"]))
        self.assertNotIn("O-3", us["Order"])
        self.assertIn("O-3", eu["Order"])
        self.assertEqual(us["Customer"]["credit_limit"], "***redacted***")
        self.assertEqual(eu["Customer"]["credit_limit"], 100000)

    def test_actions_on_hidden_rows_denied(self):
        self.state.set("Contract", "status", "signed")
        us = Principal("us", ["ops", "finance"])
        decision = self.gov.evaluate("credit_check@O-3", self.state, us)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertIn("R-ROW-001", decision.rule_ids)
        self.assertEqual(self.gov.evaluate("credit_check@O-1", self.state, us).verdict, Verdict.ALLOW)
        self.assertEqual(self.gov.evaluate("credit_check", self.state, us).verdict, Verdict.DENY)  # which order?
        self.assertIn("not part of this case", self.gov.evaluate("credit_check@O-99", self.state, us).reasons[0])
        planner = Planner(self.o, self.gov)
        names = {g.name for g in planner.applicable(self.state, us)}
        self.assertIn("credit_check@O-1", names)
        self.assertNotIn("credit_check@O-3", names)

    def test_escalation_names_the_real_blocker(self):
        res = agent(roles=("ops", "finance")).run("fulfil_contract", CASE)
        self.assertEqual(res.status, "escalated")
        self.assertEqual(res.escalation.details,
                         ["credit_check@O-3: fulfilment-agent may not access Order O-3: "
                          "EU orders are handled by EU operations only (data residency)"])

    def test_roles_are_not_pooled_across_delegates(self):
        tools = load_tools(EX / "tools.json")
        finance = WorkAgent("finance-agent", self.o, tools, roles=["finance"])
        res = agent(roles=("ops", "eu_ops"), delegates=[finance]).run("fulfil_contract", CASE)
        self.assertEqual(res.status, "escalated")
        self.assertTrue(any("finance-agent may not access Order O-3" in d for d in res.escalation.details))
        self.assertTrue(any("fulfilment-agent may not execute credit_check" in d for d in res.escalation.details))
        eu_finance = WorkAgent("eu-finance", self.o, tools, roles=["finance", "eu_ops"])
        ok = agent(roles=("ops", "eu_ops"), delegates=[eu_finance]).run("fulfil_contract", CASE)
        self.assertTrue(ok.completed, ok.escalation)
        self.assertEqual({s.executed_by for s in ok.steps if s.action.startswith("credit_check")}, {"eu-finance"})


if __name__ == "__main__":
    unittest.main()
