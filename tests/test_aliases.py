"""Semantic fragmentation: one concept, many teams' names."""

import copy
import json
import unittest

from autology import Ontology, OntologyError
from autology.graph import KnowledgeGraph
from autology.lint import lint
from autology.state import WorldState

from .test_platform import CASE, EX, service

DOC = json.loads((EX / "ontology.json").read_text())


def aliased(**more):
    doc = copy.deepcopy(DOC)
    doc["entities"]["Order"]["aliases"] = ["PurchaseOrder", "SalesOrder"]
    doc["entities"]["Customer"]["aliases"] = ["Account"]
    for key, value in more.items():
        doc[key] = value(doc) if callable(value) else value
    return Ontology.from_dict(doc)


class AliasTests(unittest.TestCase):
    def test_every_name_means_the_same_concept(self):
        onto = aliased(
            rules=lambda d: d["rules"] + [
                {"id": "R-SO", "type": "prohibition", "action": "ship_order", "when": "SalesOrder.quantity > 1000",
                 "description": "Sales writes SalesOrder"},
                {"id": "R-ACC", "type": "data_access", "field": "Account.name", "roles": ["ops", "finance"],
                 "description": "Finance writes Account"}],
            competency_questions=lambda d: d["competency_questions"] + [
                {"id": "CQ-PO", "question": "Purchase orders over 5,000?", "find": "PurchaseOrder",
                 "where": "PurchaseOrder.amount > 5000"}])
        self.assertEqual((onto.canonical("SalesOrder"), onto.canonical("Order"), onto.canonical("x")),
                         ("Order", "Order", "x"))
        rule = next(r for r in onto.rules if r.id == "R-SO")
        self.assertEqual(rule.when.references, frozenset({("Order", "quantity")}))
        self.assertEqual(next(r for r in onto.rules if r.id == "R-ACC").params["field"], "Customer.name")
        graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
        self.assertEqual(graph.ask("CQ-PO").answer, ["O-1", "O-3"])
        self.assertEqual(graph.query("SalesOrder", "SalesOrder.region == 'EU'").ids, ["O-3"])
        graph.add("PurchaseOrder", "O-9", amount=1)
        self.assertEqual(graph.get("O-9").type, "Order")
        case = copy.deepcopy(CASE)
        case["Account"] = case.pop("Customer")
        state = WorldState.initial(onto, case)
        self.assertEqual(state.get("Customer", "name"), "Northwind")
        with self.assertRaises(OntologyError):
            WorldState.initial(onto, {**case, "Customer": {}})  # the same concept given twice
        self.assertIn("Account = Customer", onto.describe())
        self.assertTrue(onto.expression("Account.name == 'Northwind'").evaluate(state.resolver()))

    def test_one_term_one_concept(self):
        bad = {
            "alias names an entity": lambda d: d["entities"]["Order"].update(aliases=["Contract"]),
            "alias used twice": lambda d: (d["entities"]["Order"].update(aliases=["Deal"]),
                                           d["entities"]["Contract"].update(aliases=["Deal"])),
            "not an identifier": lambda d: d["entities"]["Order"].update(aliases=["sales order"]),
        }
        for label, mutate in bad.items():
            doc = copy.deepcopy(DOC)
            mutate(doc)
            with self.subTest(label), self.assertRaises(OntologyError):
                Ontology.from_dict(doc)

    def test_api_and_versioning(self):
        from autology.versioning import diff

        old = aliased()
        svc = service(automations={}, chat=None)
        svc.ontology = old  # the same example, with aliases
        olivia = next(u for u in svc.users if u.name == "olivia")
        self.assertEqual([i["id"] for i in svc.list_objects(olivia, "SalesOrder", 10, 0)["items"]], ["O-1", "O-2"])
        self.assertEqual(svc.ontology_summary(olivia)["entities"]["Customer"]["aliases"], ["Account"])
        doc = copy.deepcopy(DOC)
        doc["entities"]["Order"]["aliases"] = ["PurchaseOrder"]
        kinds = {(c.kind, c.level) for c in diff(old, Ontology.from_dict(doc))}
        self.assertIn(("alias.removed", "major"), kinds)

    def test_lint_flags_likely_duplicates(self):
        doc = copy.deepcopy(DOC)
        doc["entities"]["Case"] = copy.deepcopy(doc["entities"]["Order"])
        doc["entities"]["Case"].pop("multiple")
        codes = [f.code for f in lint(Ontology.from_dict(doc))]
        self.assertIn("DUP001", codes)
        self.assertNotIn("DUP001", [f.code for f in lint(Ontology.from_dict(DOC))])


if __name__ == "__main__":
    unittest.main()
