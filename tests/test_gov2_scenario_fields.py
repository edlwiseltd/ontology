"""GOV-2 (audit GAP-012): what-if comparisons never reveal fields the user may not read."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from autology.chat import _what_if
from autology.server import ApiError, AutologyService

from .test_platform import EX, TOKENS

EXTRA_QUESTIONS = [
    {"id": "CQ-X1", "question": "Total credit limit of all customers", "find": "Customer",
     "aggregate": {"sum": "Customer.credit_limit"}},
    {"id": "CQ-X2", "question": "Customers with a credit limit above 200k", "find": "Customer",
     "where": "Customer.credit_limit > 200000"},
    {"id": "CQ-X3", "question": "Total order value", "find": "Order", "aggregate": {"sum": "Order.amount"}},
]


def service(**overrides):
    os.environ.update({f"AUTOLOGY_TOKEN_{n.upper()}": t for n, t in TOKENS.items()})
    folder = Path(tempfile.mkdtemp())
    onto = json.loads((EX / "ontology.json").read_text())
    onto["competency_questions"] = onto["competency_questions"] + EXTRA_QUESTIONS
    (folder / "ontology.json").write_text(json.dumps(onto))
    for name in ("tools.json", "data.json"):
        (folder / name).write_text((EX / name).read_text())
    cfg = json.loads((EX / "server.json").read_text())
    cfg.update(store=str(folder / "s.db"), automations={}, chat=None, **overrides)
    return AutologyService(cfg, folder)


def user(svc, name):
    return next(u for u in svc.users if u.name == name)


def question(report, qid):
    return next(q for q in report["questions"] if q["id"] == qid)


class ScenarioFieldTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        self.olivia = user(self.svc, "olivia")  # ops: Customer.credit_limit is for finance only

    def test_the_direct_question_was_already_refused(self):
        with self.assertRaises(ApiError) as cm:
            self.svc.answer(self.olivia, "CQ-X1", {})
        self.assertEqual(cm.exception.status, 403)

    def test_a_comparison_withholds_answers_built_on_hidden_fields(self):
        sc = self.svc.create_scenario(self.olivia, {"name": "probe", "edits": []})
        report = self.svc.compare_scenario(self.olivia, sc["scenario_id"], {"checks": []})
        for qid in ("CQ-X1", "CQ-X2"):
            q = question(report, qid)
            self.assertTrue(str(q["baseline"]).startswith("withheld"), q)
            self.assertTrue(str(q["scenario"]).startswith("withheld"), q)
        self.assertNotIn("250000", json.dumps(report))
        # questions that do not use the field are still answered
        self.assertIsInstance(question(report, "CQ-01")["baseline"], list)

    def test_editing_a_field_you_may_not_read_is_refused(self):
        with self.assertRaises(ApiError) as cm:
            self.svc.create_scenario(self.olivia, {"name": "probe", "edits": [
                {"op": "set", "id": "C-1", "attributes": {"credit_limit": 0}}]})
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("Customer.credit_limit", cm.exception.message)

    def test_fields_needing_a_justification_are_withheld_even_for_admins(self):
        admin = user(self.svc, "admin")  # CP-CREDIT: reading Customer.credit_limit needs a written reason
        sc = self.svc.create_scenario(admin, {"name": "probe", "edits": []})
        report = self.svc.compare_scenario(admin, sc["scenario_id"], {"checks": []})
        self.assertIn("justification", question(report, "CQ-X1")["baseline"])
        # finance can ask the question directly, with its reason, through the normal path
        audrey = user(self.svc, "audrey")
        self.assertEqual(self.svc.answer(audrey, "CQ-X1", {}, "quarterly credit exposure review")["answer"],
                         sum(i.attributes["credit_limit"] for i in self.svc.graph.instances("Customer")))

    def test_the_assistant_what_if_withholds_fields_not_sent_to_the_model(self):
        svc = service(chat_redact={"fields": ["Order.amount"]})
        boss = user(svc, "admin")  # sees every order and Order.amount; the deployment keeps it from the provider
        sc = svc.create_scenario(boss, {"name": "direct", "edits": []})
        direct = question(svc.compare_scenario(boss, sc["scenario_id"], {"checks": []}), "CQ-X3")
        self.assertIsInstance(direct["baseline"], (int, float))  # people see it in the API and Console
        via_assistant = question(_what_if(svc, boss, {"name": "t", "edits": []}), "CQ-X3")
        self.assertIn("not sent to the model provider", via_assistant["baseline"])


if __name__ == "__main__":
    unittest.main()
