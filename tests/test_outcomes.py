"""Dynamic layer: link decisions to what happened afterwards, and learn from it."""

import unittest

from autology.reporting import compliance_report, outcome_analysis
from autology.server import ApiError

from .test_platform import _Api, add_big_order, service


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}
        run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        self.run_id = run["run_id"]
        self.svc.decide(self.u["lena"], run["pending_review"], {"approved": True, "comment": "carrier ok"})

    def test_record_and_learn(self):
        out = self.svc.record_outcome(self.u["lena"], self.run_id, {
            "action": "ship_order@O-4", "label": "damaged in transit", "good": False,
            "note": "turbine arrived with a cracked housing"})
        self.assertEqual(out["outcomes"][-1]["label"], "damaged in transit")
        self.svc.record_outcome(self.u["lena"], self.run_id, {"action": "credit_check@O-4", "label": "paid on time",
                                                              "good": True})
        self.assertTrue(self.svc.store.verify_audit(self.run_id))  # part of the run's tamper-evident history
        events = [e for e in self.svc.store.audit_log(self.run_id) if e.event == "outcome"]
        self.assertEqual([e.data["recorded_by"] for e in events], ["lena", "lena"])
        view = self.svc.get_run(self.u["olivia"], self.run_id)
        self.assertEqual(len(view["outcomes"]), 2)

        analysis = outcome_analysis(self.svc.store.all_runs(), self.svc.ontology)
        ship = analysis["actions"]["ship_order"]
        self.assertEqual((ship["judged"], ship["bad"], ship["reviewed_then_bad"]), (1, 1, 1))
        rule = analysis["rules"]["R-LOG-001"]
        self.assertEqual((rule["judged"], rule["bad"]), (1, 1))
        self.assertIn("R-LOG-001", " ".join(analysis["suggestions"]))
        report = compliance_report(self.svc.store.all_runs(), self.svc.ontology)
        self.assertIn("## Decisions and their outcomes", report)
        self.assertIn("| ship_order | 1 | 1 | 0 | 1 |", report)

    def test_unreviewed_actions_that_go_wrong_suggest_a_review(self):
        self.svc.record_outcome(self.u["lena"], self.run_id, {"action": "pick_order@O-4", "label": "wrong item",
                                                              "good": False})
        analysis = outcome_analysis(self.svc.store.all_runs(), self.svc.ontology)
        self.assertEqual(analysis["actions"]["pick_order"]["bad"], 1)
        self.assertTrue(any("pick_order" in s and "human_review" in s for s in analysis["suggestions"]))

    def test_validation_and_permissions(self):
        cases = [
            (self.u["audrey"], {"label": "x", "good": True}, 403),  # read/audit only
            (self.u["lena"], {"label": "x", "good": "yes"}, 400),
            (self.u["lena"], {"good": True}, 400),
            (self.u["lena"], {"action": "fly@O-4", "label": "x", "good": True}, 400),  # not a step of this run
        ]
        for user, body, status in cases:
            with self.subTest(body=body), self.assertRaises(ApiError) as cm:
                self.svc.record_outcome(user, self.run_id, body)
            self.assertEqual(cm.exception.status, status)
        with self.assertRaises(ApiError) as cm:
            self.svc.record_outcome(self.u["lena"], "nope", {"label": "x", "good": True})
        self.assertEqual(cm.exception.status, 404)
        whole = self.svc.record_outcome(self.u["lena"], self.run_id, {"label": "customer satisfied", "good": True})
        self.assertIsNone(whole["outcomes"][-1]["action"])  # about the run as a whole

    def test_http(self):
        api = _Api(self.svc)
        try:
            status, out, _ = api.call("POST", f"/api/runs/{self.run_id}/outcomes", "lena",
                                      {"action": "ship_order@O-4", "label": "on time", "good": True})
            self.assertEqual(status, 200)
            self.assertEqual(api.call("GET", f"/api/runs/{self.run_id}/outcomes", "olivia")[1]["items"][0]["label"],
                             "on time")
            status, summary, _ = api.call("GET", "/api/outcomes", "olivia")
            self.assertEqual(summary["actions"]["ship_order"]["good"], 1)
        finally:
            api.server.shutdown()


if __name__ == "__main__":
    unittest.main()
