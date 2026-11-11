"""Review item 2: row, field and checkpoint rules cover runs, reviews and question answers."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from autology.server import ApiError

from .test_platform import EX, _Api, add_big_order, service

REDACTED = "***redacted***"


def variant(**changes):
    """A service on a copy of the example ontology with extra rules / questions."""
    doc = json.loads((EX / "ontology.json").read_text())
    doc["rules"] += changes.get("rules", [])
    doc["competency_questions"] += changes.get("questions", [])
    tmp = Path(tempfile.mkdtemp())
    (tmp / "ontology.json").write_text(json.dumps(doc))
    return service(ontology=str(tmp / "ontology.json"), automations={}, chat=None)


class RunVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}

    def test_runs_with_hidden_rows_are_hidden(self):
        # K-1's case holds the EU order O-3, which Olivia (no eu_ops) may not see
        run = self.svc.start_run(self.u["admin"],
                                 {"case_template": "contract_case", "root": "K-1"})
        with self.assertRaises(ApiError) as cm:
            self.svc.get_run(self.u["olivia"], run["run_id"])
        self.assertEqual(cm.exception.status, 404)
        self.assertNotIn(run["run_id"], [r["run_id"] for r in self.svc.list_runs(self.u["olivia"], None, 50, 0)["items"]])
        self.assertEqual(self.svc.get_run(self.u["lena"], run["run_id"])["run_id"], run["run_id"])  # EU staff
        self.assertNotIn("O-3", self.svc.report(self.u["olivia"]))

    def test_explanations_do_not_carry_restricted_facts(self):
        svc = variant(rules=[{"id": "R-CL", "type": "action_access", "action": "pick_order", "roles": ["ops"],
                              "when": "Customer.credit_limit > 1", "description": "Picking is for operations"}])
        u = {x.name: x for x in svc.users}
        run = svc.start_run(u["olivia"], add_big_order(svc))
        stored = json.dumps([s.explanation for s in svc.store.load_run(run["run_id"]).steps])
        self.assertIn("Customer.credit_limit=500000", stored)  # the record keeps the fact
        admin_view = json.dumps(svc.get_run(u["admin"], run["run_id"]))
        self.assertNotIn("500000", admin_view)  # checkpoint-gated: admins give a reason too
        mine = json.dumps(svc.get_run(u["olivia"], run["run_id"]))
        self.assertNotIn("500000", mine)
        self.assertIn(f"Customer.credit_limit={REDACTED}", mine)

    def test_checkpoint_gated_fields_in_run_state(self):
        run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        audrey = self.svc.get_run(self.u["audrey"], run["run_id"])  # finance may read it, but only with a reason
        self.assertEqual(audrey["state"]["Customer"]["credit_limit"], "***justification required***")
        self.assertNotIn("500000", json.dumps(audrey))


class ReviewVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}
        self.run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        self.review_id = self.svc.list_reviews(self.u["lena"], "pending")["items"][0]["review_id"]

    def test_only_reviewers_admins_and_the_starter(self):
        with self.assertRaises(ApiError) as cm:
            self.svc.get_review(self.u["audrey"], self.review_id)
        self.assertEqual(cm.exception.status, 404)
        self.assertIsNone(self.svc.get_run(self.u["audrey"], self.run["run_id"])["pending_review"])
        lena = self.svc.get_review(self.u["lena"], self.review_id)
        self.assertEqual(lena["request"]["view"]["Customer"]["credit_limit"], REDACTED)  # her own field access
        self.assertEqual(lena["request"]["facts"]["Order.amount"], 85000)
        starter = self.svc.get_review(self.u["olivia"], self.review_id)
        self.assertEqual(starter["request"]["view"]["Customer"]["credit_limit"], REDACTED)
        self.assertEqual(self.svc.get_run(self.u["olivia"], self.run["run_id"])["pending_review"], self.review_id)
        admin = self.svc.get_review(self.u["admin"], self.review_id)
        self.assertEqual(admin["request"]["view"]["Customer"]["credit_limit"], "***justification required***")
        self.assertEqual(admin["request"]["view"]["Customer"]["name"], "Contoso Power")
        decided = self.svc.list_reviews(self.u["audrey"], "approved")["items"]
        self.assertEqual(decided, [])

    def test_decided_reviews_listing_is_filtered(self):
        self.svc.decide(self.u["lena"], self.review_id, {"approved": True, "comment": "ok"})
        self.assertEqual(self.svc.list_reviews(self.u["audrey"], "approved")["items"], [])
        self.assertEqual(len(self.svc.list_reviews(self.u["olivia"], "approved")["items"]), 1)  # her run

    def test_http(self):
        api = _Api(self.svc)
        try:
            self.assertEqual(api.call("GET", f"/api/reviews/{self.review_id}", "audrey")[0], 404)
            self.assertEqual(api.call("GET", f"/api/reviews/{self.review_id}", "lena")[0], 200)
        finally:
            api.server.shutdown()


class AnswerFieldAccessTests(unittest.TestCase):
    def test_filters_and_aggregates_on_restricted_fields(self):
        svc = variant(questions=[
            {"id": "CQ-RICH", "question": "Customers with a high limit?", "find": "Customer",
             "where": "Customer.credit_limit > 100000"},
            {"id": "CQ-LIM", "question": "Total credit?", "find": "Customer", "aggregate": {"sum": "Customer.credit_limit"}}])
        u = {x.name: x for x in svc.users}
        for qid in ("CQ-RICH", "CQ-LIM"):
            with self.subTest(qid), self.assertRaises(ApiError) as cm:
                svc.answer(u["olivia"], qid, {})  # olivia may not read credit limits
            self.assertEqual(cm.exception.status, 403)
            with self.assertRaises(ApiError) as cm:
                svc.answer(u["audrey"], qid, {})  # audrey may, after giving a reason (checkpoint CP-CREDIT)
            self.assertEqual(cm.exception.status, 428)
        self.assertEqual(svc.answer(u["audrey"], "CQ-RICH", {}, "portfolio review for Q3")["answer"], ["C-1"])
        self.assertEqual(svc.answer(u["olivia"], "CQ-01", {})["answer"], ["O-1", "O-2"])  # unaffected


class ScenarioFieldTests(unittest.TestCase):
    def test_scenario_diffs_hide_restricted_values(self):
        svc = service(automations={}, chat=None)
        u = {x.name: x for x in svc.users}
        sid = svc.create_scenario(u["admin"], {"edits": [
            {"op": "set", "id": "C-1", "attributes": {"credit_limit": 1}}]})["scenario_id"]
        view = svc.get_scenario(u["olivia"], sid)
        self.assertEqual(view["diff"]["changed"]["C-1"]["credit_limit"], [REDACTED, REDACTED])


if __name__ == "__main__":
    unittest.main()
