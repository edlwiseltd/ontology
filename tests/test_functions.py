"""Functions: the 'how to calculate' element of the ontology's kinetic layer."""

import copy
import json
import unittest

from autology import AutoApprover, Ontology, OntologyError, WorkAgent
from autology.adapters import load_tools
from autology.expressions import compile_expression
from autology.governance import GovernanceLayer, Principal, Verdict
from autology.graph import KnowledgeGraph
from autology.state import WorldState

from .test_platform import CASE, EX

DOC = json.loads((EX / "ontology.json").read_text())


def with_functions(**extra):
    doc = copy.deepcopy(DOC)
    doc["functions"] = {
        "net": {"entity": "Order", "returns": "number", "description": "Amount after a 2% discount",
                "expr": "Order.amount * 0.98"},
        "big": {"entity": "Order", "returns": "boolean", "expr": "Order.net >= 50000"},  # uses another function
    }
    for key, value in extra.items():
        doc[key] = value(doc) if callable(value) else value
    return Ontology.from_dict(doc)


class ExpressionArithmeticTests(unittest.TestCase):
    def test_values(self):
        r = {"a": 8000, "d": 500, "l": 5000, "z": 0, "n": None}
        resolve = lambda e, a: r.get(a)  # noqa: E731
        c = compile_expression
        self.assertEqual(c("min(X.a - X.d, X.l)").value(resolve), 5000)
        self.assertEqual(c("round(X.a / 3, 2)").value(resolve), 2666.67)
        self.assertEqual(c("abs(-X.d) + max(X.d, X.l)").value(resolve), 5500)
        self.assertIsNone(c("X.a / X.z").value(resolve))  # no crash on division by zero
        self.assertIsNone(c("X.n + 1").value(resolve))
        self.assertFalse(c("X.n + 1 > 0").evaluate(resolve))
        self.assertIsNone(c("X.n * 2 > 0").evaluate_known(resolve))  # unknown, for fail-closed rules
        self.assertIsNone(c("max(X.n, 1) > 0").evaluate_known(resolve))
        self.assertIsNone(c("-X.n < 0").evaluate_known(resolve))
        self.assertTrue(c("X.a * 2 > 10000").evaluate_known(resolve))
        self.assertIsNone(c("True + 1").value(resolve))  # booleans are not numbers


class OntologyFunctionTests(unittest.TestCase):
    def test_functions_work_in_rules_goals_and_questions(self):
        onto = with_functions(
            rules=lambda d: d["rules"] + [{"id": "R-NET", "type": "human_review", "action": "ship_order",
                                            "reviewer": "logistics_manager", "when": "Order.big",
                                            "description": "Net value of 50,000 or more"}],
            competency_questions=lambda d: d["competency_questions"] + [
                {"id": "CQ-NET", "question": "Orders above 10,000 net?", "find": "Order",
                 "where": "Order.net > 10000"}])
        self.assertEqual(onto.functions["Order.net"].source, "Order.amount * 0.98")
        rule = next(r for r in onto.rules if r.id == "R-NET")
        self.assertIn(("Order", "amount"), rule.when.references)  # expanded: access rules see the real field
        graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
        self.assertEqual(graph.ask("CQ-NET").answer, ["O-3"])  # 12000 * 0.98
        self.assertEqual(graph.query("Order", "Order.net < 3000").ids, ["O-2"])
        case = copy.deepcopy(CASE)
        state = WorldState.initial(onto, {**case, "Order": [dict(case["Order"][3], status="picked")],
                                          "Contract": {"value": 1, "status": "signed"}})
        decision = GovernanceLayer(onto).evaluate("ship_order@O-4", state, Principal("a", frozenset({"ops"})))
        self.assertIn("R-NET", decision.rule_ids)  # 85000 * 0.98 >= 50000
        self.assertTrue(onto.expression("Order.big").evaluate(state.resolver({"Order": "O-4"})))

    def test_computed_effects(self):
        def invoice_net(d):
            actions = copy.deepcopy(d["actions"])
            actions["invoice_order"]["effects"]["Order"]["tracking"] = {"compute": "Order.sku"}
            d["entities"]["Order"]["attributes"]["invoiced_amount"] = "number"
            actions["invoice_order"]["effects"]["Order"]["invoiced_amount"] = {"compute": "Order.net"}
            return actions

        onto = with_functions(actions=invoice_net)
        agent = WorkAgent("a", onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops", "finance"],
                          approver=AutoApprover())
        result = agent.run("fulfil_contract", CASE, "k")
        self.assertEqual(result.status, "completed")
        o1 = result.state.collections["Order"]["O-1"]
        self.assertEqual((o1["invoiced_amount"], o1["tracking"]), (9000 * 0.98, "PUMP-10"))

    def test_validation(self):
        bad = {
            "unknown entity": {"f": {"entity": "Ghost", "expr": "1"}},
            "clashes with attribute": {"amount": {"entity": "Order", "expr": "1"}},
            "unknown field": {"f": {"entity": "Order", "expr": "Order.colour * 2"}},
            "returns": {"f": {"entity": "Order", "returns": "date", "expr": "1"}},
            "recursive": {"f": {"entity": "Order", "expr": "Order.g + 1"}, "g": {"entity": "Order", "expr": "Order.f"}},
            "no expr": {"f": {"entity": "Order"}},
        }
        for label, functions in bad.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                with_functions(functions=functions)
        with self.assertRaises(OntologyError):  # a computed effect on an unknown field
            def broken(d):
                actions = copy.deepcopy(d["actions"])
                actions["invoice_order"]["effects"]["Order"]["tracking"] = {"compute": "Order.ghost"}
                return actions
            with_functions(actions=broken)


if __name__ == "__main__":
    unittest.main()


class FunctionApiTests(unittest.TestCase):
    def test_objects_show_computed_values_through_access_rules(self):
        import tempfile
        from pathlib import Path

        from .test_platform import service

        doc = copy.deepcopy(DOC)
        doc["functions"] = {"net": {"entity": "Order", "expr": "Order.amount * 0.5"},
                            "headroom": {"entity": "Customer", "expr": "Customer.credit_limit - 1000"}}
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ontology.json").write_text(json.dumps(doc))
        svc = service(ontology=str(tmp / "ontology.json"), automations={}, chat=None)
        u = {x.name: x for x in svc.users}
        self.assertEqual(svc.get_object(u["olivia"], "O-1")["functions"], {"net": 4500})
        self.assertEqual(svc.get_object(u["olivia"], "C-1")["functions"], {"headroom": "***redacted***"})
        self.assertEqual(svc.ontology_summary(u["olivia"])["functions"]["Order.net"]["expr"], "Order.amount * 0.5")
        self.assertIn("Order.net -> number", svc.ontology.describe())

    def test_versioning(self):
        from autology.versioning import diff

        old = with_functions()
        changed = copy.deepcopy(DOC)
        changed["functions"] = {"net": {"entity": "Order", "returns": "integer", "expr": "Order.amount * 0.9"}}
        kinds = {(c.kind, c.level) for c in diff(old, Ontology.from_dict(changed))}
        self.assertTrue({("function.returns_changed", "major"), ("function.changed", "minor"),
                         ("function.removed", "major")} <= kinds)
