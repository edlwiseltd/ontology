"""ACT-6 (audit GAP-009): a run resumed after a review re-checks the live data it relies on."""

import unittest

from .test_ingest import service


class RevalidationTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, pipelines={})
        self.u = {x.name: x for x in self.svc.users}

    def at_manager_review(self, **body):
        run = self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-2", **body})
        self.svc.decide(self.u["ivan"], run["pending_review"], {"approved": True})  # the investigator clears it
        review = [r for r in self.svc.store.list_reviews("pending") if r["run_id"] == run["run_id"]][0]
        self.assertEqual(review["action"], "pay_claim")
        return run, review

    def edit(self, iid, **attrs):
        inst = self.svc.graph.get(iid)
        self.svc.upsert_object(self.u["admin"], {"type": inst.type, "id": iid, "attributes": {
            **{k: v for k, v in inst.attributes.items() if v is not None}, **attrs}})

    def payments(self):
        return [c for c in self.svc.store.list_calls() if c["action"] == "pay_claim"]

    def test_a_changed_reviewed_fact_needs_a_new_review(self):
        run, review = self.at_manager_review()
        seen = review["request"]["facts"]
        self.edit("CL-2", amount=90000)  # the claim grew while the manager looked at it
        out = self.svc.decide(self.u["maria"], review["review_id"], {"approved": True})
        self.assertEqual(out["status"], "awaiting_review")
        self.assertEqual(self.payments(), [])  # the approval of the old amount did not pay the new one
        again = [r for r in self.svc.store.list_reviews("pending") if r["run_id"] == run["run_id"]]
        self.assertEqual(len(again), 1)
        self.assertNotEqual(again[0]["review_id"], review["review_id"])
        self.assertNotEqual(again[0]["request"]["facts"], seen)
        audit = [e.event for e in self.svc.store.load_run(run["run_id"]).audit]
        self.assertIn("case.refreshed", audit)
        self.assertIn("review.superseded", audit)
        # the manager approves what is now true, and the claim is paid once
        self.assertEqual(self.svc.decide(self.u["maria"], again[0]["review_id"], {"approved": True})["status"],
                         "completed")
        self.assertEqual(len(self.payments()), 1)

    def test_a_claim_rejected_meanwhile_is_not_paid(self):
        run, review = self.at_manager_review()
        self.edit("CL-2", status="rejected")
        out = self.svc.decide(self.u["maria"], review["review_id"], {"approved": True})
        self.assertEqual(self.payments(), [])
        self.assertEqual(self.svc.graph.get("CL-2").attributes["status"], "rejected")
        self.assertEqual(out["status"], "completed")  # the goal (paid or rejected) holds without paying

    def test_unrelated_changes_do_not_cancel_an_approval(self):
        run, review = self.at_manager_review()
        policy = next(i for i in self.svc.graph.instances("Policy") if any(
            t == "CL-2" for t in [s for s, _, x in self.svc.graph._links if x == i.id]))
        self.edit(policy.id, holder="New Holder Name")  # not a fact of the payment review
        self.assertEqual(self.svc.decide(self.u["maria"], review["review_id"], {"approved": True})["status"],
                         "completed")
        self.assertEqual(len(self.payments()), 1)

    def test_a_field_changed_by_the_run_and_outside_stops_the_run(self):
        run, review = self.at_manager_review(write_back=False)  # the run's changes stay in the run
        self.edit("CL-2", status="rejected")  # the run had approved it; someone rejected it outside
        out = self.svc.decide(self.u["maria"], review["review_id"], {"approved": True})
        self.assertEqual(out["status"], "escalated")
        self.assertEqual(self.payments(), [])
        result = self.svc.store.load_run(run["run_id"])
        self.assertIn("changed while the run waited", result.escalation.reason)
        self.assertIn("Claim.status", " ".join(result.escalation.details))


if __name__ == "__main__":
    unittest.main()
