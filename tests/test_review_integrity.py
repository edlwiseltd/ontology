"""Review item 1: the facts that trigger reviews and access rules cannot be chosen or blanked by the requester."""

import copy
import json
import unittest

from autology import Ontology, OntologyError
from autology.governance import GovernanceLayer, Principal, Verdict
from autology.server import ApiError
from autology.state import WorldState

from .test_platform import CASE, EX, service

DOC = json.loads((EX / "ontology.json").read_text())
OPS = Principal("ops-agent", frozenset({"ops", "eu_ops", "finance"}))


def onto_with(*rules):
    doc = copy.deepcopy(DOC)
    doc["rules"] += list(rules)
    return Ontology.from_dict(doc)


def picked_order(**attrs):
    case = copy.deepcopy(CASE)
    case["Customer"]["status"] = "approved"
    case["Contract"]["status"] = "signed"
    case["Order"] = [{"id": "O-9", "sku": "X", "quantity": 1, "region": "US", "hazardous": False,
                      "status": "picked", **attrs}]
    return case


class FreeFormCaseTests(unittest.TestCase):
    def test_requester_cannot_supply_the_facts(self):
        svc = service(automations={}, chat=None)
        users = {u.name: u for u in svc.users}
        lowered = copy.deepcopy(CASE)
        lowered["Order"] = [dict(o, amount=49_999) if o["id"] == "O-4" else o for o in lowered["Order"]]
        with self.assertRaises(ApiError) as cm:
            svc.start_run(users["olivia"], {"case": lowered})
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("case_template", cm.exception.message)
        self.assertEqual(svc.store.list_runs(), [])
        # admins may (for support and repair), and so may anyone on a server configured for simulation
        self.assertEqual(svc.start_run(users["admin"], {"case": CASE})["status"], "awaiting_review")
        sim = service(automations={}, chat=None, simulation=True)
        lena = next(u for u in sim.users if u.name == "lena")  # the case holds an EU order: EU operations start it
        self.assertEqual(sim.start_run(lena, {"case": CASE})["status"], "awaiting_review")
        self.assertTrue(sim.ontology_summary(lena)["free_form_cases"])
        self.assertFalse(svc.ontology_summary(users["olivia"])["free_form_cases"])


class AttributeTypeTests(unittest.TestCase):
    def test_case_values_must_match_declared_types(self):
        onto = Ontology.load(EX / "ontology.json")
        bad = [{"amount": "80000"}, {"quantity": 1.5}, {"hazardous": "no"}, {"amount": True}, {"sku": 7}]
        for attrs in bad:
            with self.subTest(attrs), self.assertRaises(OntologyError):
                WorldState.initial(onto, picked_order(**{"amount": 1, **attrs}))
        ok = WorldState.initial(onto, picked_order(amount=80_000, quantity=2))  # int is a valid number
        self.assertEqual(ok.get("Order", "amount", "O-9"), 80_000)
        WorldState.initial(onto, picked_order(amount=None))  # missing is allowed: rules treat it as unknown

    def test_graph_data_is_checked_too(self):
        from autology.graph import KnowledgeGraph

        graph = KnowledgeGraph(Ontology.load(EX / "ontology.json"))
        with self.assertRaises(OntologyError):
            graph.add("Order", "O-1", amount="lots")


class UnknownFactTests(unittest.TestCase):
    def test_review_applies_when_amount_is_unknown(self):
        onto = Ontology.load(EX / "ontology.json")
        state = WorldState.initial(onto, picked_order())  # no amount at all
        decision = GovernanceLayer(onto).evaluate("ship_order@O-9", state, OPS)
        self.assertEqual(decision.verdict, Verdict.REVIEW)
        self.assertEqual(decision.rule_ids, ["R-LOG-001"])
        self.assertTrue(any("unknown" in r and "Order.amount" in r for r in decision.reasons), decision.reasons)
        known = WorldState.initial(onto, picked_order(amount=100))
        self.assertEqual(GovernanceLayer(onto).evaluate("ship_order@O-9", known, OPS).verdict, Verdict.ALLOW)

    def test_prohibition_applies_when_unknown(self):
        onto = onto_with({"id": "P-1", "type": "prohibition", "action": "ship_order",
                          "when": "Order.amount > 1000000", "description": "No mega orders"})
        state = WorldState.initial(onto, picked_order())
        decision = GovernanceLayer(onto).evaluate("ship_order@O-9", state, OPS)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertIn("P-1", decision.rule_ids)

    def test_row_and_field_rules_apply_when_unknown(self):
        onto = onto_with({"id": "D-1", "type": "data_access", "field": "Order.sku", "when": "Order.region == 'EU'",
                          "roles": ["eu_ops"], "description": "EU SKUs"})
        state = WorldState.initial(onto, picked_order(region=None, amount=10))
        ops = Principal("o", frozenset({"ops"}))
        gov = GovernanceLayer(onto)
        visible, rule = gov.row_visible("Order", state, ops, "O-9")
        self.assertEqual((visible, rule.id), (False, "R-ROW-001"))  # region unknown: treated as possibly EU
        self.assertFalse(gov.can_read("Order.sku", state, ops, {"Order": "O-9"}))
        self.assertTrue(gov.row_visible("Order", state, Principal("e", frozenset({"eu_ops"})), "O-9")[0])

    def test_api_row_access_when_unknown(self):
        svc = service(automations={}, chat=None)
        admin = next(u for u in svc.users if u.name == "admin")
        olivia = next(u for u in svc.users if u.name == "olivia")
        svc.upsert_object(admin, {"type": "Order", "id": "O-77", "attributes": {"sku": "X", "amount": 5}})
        with self.assertRaises(ApiError) as cm:
            svc.get_object(olivia, "O-77")  # no region: may be EU, so hidden from non-EU staff
        self.assertEqual(cm.exception.status, 404)

    def test_mandatory_steps_and_preconditions_keep_two_valued_logic(self):
        onto = Ontology.load(EX / "ontology.json")
        state = WorldState.initial(onto, picked_order(amount=10, hazardous=None))
        # R-HAZ-001 (mandatory step, "when Order.hazardous == True") is not one of the fail-closed kinds
        decision = GovernanceLayer(onto).evaluate("ship_order@O-9", state, OPS)
        self.assertEqual(decision.verdict, Verdict.ALLOW)


if __name__ == "__main__":
    unittest.main()
