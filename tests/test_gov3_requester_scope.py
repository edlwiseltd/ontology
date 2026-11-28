"""GOV-3 (audit GAP-013): a run started by a person acts only on records that person may see."""

import json
import unittest

from autology.server import ApiError

from .test_gov1_manual_firing import service, sign, user
from .test_platform import add_big_order


class RequesterScopeTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        self.otto = user(self.svc, "otto")  # ops only: EU order O-3 (covered by contract K-1) is hidden from him

    def acted_on_o3(self):
        return self.svc.graph.get("O-3").attributes.get("status") != "received"

    def test_a_run_whose_case_includes_hidden_records_is_refused(self):
        self.assertTrue(self.svc.visible(self.svc.graph.get("K-1"), self.otto))
        self.assertFalse(self.svc.visible(self.svc.graph.get("O-3"), self.otto))
        with self.assertRaises(ApiError) as cm:
            self.svc.start_run(self.otto, {"case_template": "contract_case", "root": "K-1"})
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("records you may not see", cm.exception.message)
        self.assertNotIn("O-3", json.dumps([cm.exception.message, cm.exception.extra]))  # no hidden ids
        self.assertEqual(self.svc.store.list_runs(limit=10), [])
        self.assertFalse(self.acted_on_o3())

    def test_someone_who_sees_every_record_may_start_it(self):
        rita = user(self.svc, "rita")  # ops + eu_ops
        out = self.svc.start_run(rita, {"case_template": "contract_case", "root": "K-1"})
        self.assertNotIn("hidden", out)
        self.assertTrue(self.acted_on_o3())

    def test_cases_without_hidden_records_are_unaffected(self):
        add_big_order(self.svc)  # K-2 covers US order O-4
        out = self.svc.start_run(self.otto, {"case_template": "contract_case", "root": "K-2"})
        self.assertEqual(out["status"], "awaiting_review")

    def test_firing_an_automation_by_hand_is_limited_the_same_way(self):
        sign(self.svc, "K-1")
        out = self.svc.run_automation(self.otto, "fulfil", {"instance": "K-1"})
        firing = out["firings"][0]
        self.assertEqual((firing["status"], firing["run_id"]), ("skipped", None))
        self.assertIn("records you may not see", firing["detail"])
        self.assertNotIn("O-3", json.dumps(out))
        self.assertFalse(self.acted_on_o3())

    def test_automations_keep_their_service_identity(self):
        sign(self.svc, "K-1")
        firing = self.svc._fire(self.svc.automations["fulfil"], self.svc.graph.get("K-1"), "schedule").as_dict()
        self.assertEqual(self.svc.store.run_starter(firing["run_id"]), "automation:fulfil")
        steps = self.svc.store.load_run(firing["run_id"]).steps  # its service roles reach the EU order
        self.assertTrue(any(st.action.endswith("@O-3") for st in steps), [st.action for st in steps])

    def test_resuming_a_run_you_may_not_see_is_not_found(self):
        rita = user(self.svc, "rita")
        run = self.svc.start_run(rita, {"case_template": "contract_case", "root": "K-1"})
        with self.assertRaises(ApiError) as cm:
            self.svc.resume_run(self.otto, run["run_id"])
        self.assertEqual(cm.exception.status, 404)  # not 409 "completed": the run's existence is not revealed


if __name__ == "__main__":
    unittest.main()
