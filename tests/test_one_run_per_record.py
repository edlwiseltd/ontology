"""One open run per record: a claim can never have two runs that could both pay it (audit GAP-008)."""

import threading
import unittest

from autology.server import ApiError

from .test_ingest import TOKENS, service
from .test_platform import _Api

CL2 = {"case_template": "claim_case", "root": "CL-2"}  # 48,000: waits for an investigator, then a manager


class OneRunPerRecordTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})
        self.u = {x.name: x for x in self.svc.users}

    def runs_on(self, root):
        return [r for r in self.svc.store.list_runs(limit=100) if r["case_id"].endswith(root)]

    def test_second_run_on_an_open_claim_is_refused(self):
        first = self.svc.start_run(self.u["hana"], CL2)
        self.assertEqual(first["status"], "awaiting_review")
        with self.assertRaises(ApiError) as cm:
            self.svc.start_run(self.u["admin"], CL2)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.extra["active_run"], first["run_id"])
        self.assertIn("already has an open run", cm.exception.message)
        self.assertEqual(len(self.runs_on("CL-2")), 1)
        # other claims are not affected
        self.assertEqual(self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})["status"],
                         "completed")

    def test_a_finished_run_frees_the_claim(self):
        self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})  # completes at once
        again = self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(again["status"], "completed")  # nothing left to do, nothing blocked
        run = self.svc.start_run(self.u["hana"], CL2)
        self.svc.decide(self.u["ivan"], run["pending_review"], {"approved": False, "comment": "not covered"})
        self.assertEqual(self.svc.start_run(self.u["hana"], CL2)["status"], "awaiting_review")  # declined: free

    def test_simultaneous_starts_create_exactly_one_run(self):
        barrier, results = threading.Barrier(4), []

        def start(user):
            barrier.wait()
            try:
                results.append(self.svc.start_run(user, CL2)["status"])
            except ApiError as exc:
                results.append(exc.status)

        threads = [threading.Thread(target=start, args=(self.u[n],)) for n in ("hana", "admin", "hana", "admin")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(map(str, results)), ["409", "409", "409", "awaiting_review"])
        self.assertEqual(len(self.runs_on("CL-2")), 1)

    def test_automations_skip_claims_that_already_have_a_run(self):
        svc = service()  # with the settle-new-claims automation
        hana = next(u for u in svc.users if u.name == "hana")
        admin = next(u for u in svc.users if u.name == "admin")
        run = svc.start_run(hana, CL2)
        # the automation path itself (as fired on a data change) refuses a second run on the claim
        firing = svc._fire(svc.automations["settle_new_claims"], svc.graph.get("CL-2"), "change").as_dict()
        self.assertEqual((firing["status"], firing["run_id"]), ("skipped", run["run_id"]))
        self.assertIn("already has an open run", firing["detail"])
        # firing it by hand is skipped too (here already because the claim is no longer 'reported')
        out = svc.run_automation(admin, "settle_new_claims", {"instance": "CL-2"})
        self.assertEqual(out["firings"][0]["status"], "skipped")
        self.assertEqual(len([r for r in svc.store.list_runs(limit=100) if r["case_id"].endswith("CL-2")]), 1)
        fired = {f["instance"]: f["status"] for f in svc.tick()["firings"]}
        self.assertNotEqual(fired.get("CL-2"), "awaiting_review")  # the scheduler does not add a second run either

    def test_existing_duplicates_cannot_both_be_approved(self):
        self.svc.one_active_run_per_record = False  # how duplicates came about before this rule
        a = self.svc.start_run(self.u["hana"], CL2)
        b = self.svc.start_run(self.u["admin"], CL2)
        self.svc.one_active_run_per_record = True
        with self.assertRaises(ApiError) as cm:
            self.svc.decide(self.u["ivan"], a["pending_review"], {"approved": True})
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.extra["other_runs"], [b["run_id"]])
        # declining a duplicate is always allowed, and then the remaining run can go ahead
        self.svc.decide(self.u["ivan"], b["pending_review"], {"approved": False, "comment": "duplicate run"})
        out = self.svc.decide(self.u["ivan"], a["pending_review"], {"approved": True})
        self.assertEqual(out["status"], "awaiting_review")  # next: the claims manager for the 40,000 payment

    def test_can_be_switched_off_per_deployment(self):
        svc = service(automations={}, one_active_run_per_record=False)
        hana = next(u for u in svc.users if u.name == "hana")
        svc.start_run(hana, CL2)
        self.assertEqual(svc.start_run(hana, CL2)["status"], "awaiting_review")

    def test_http_answer_names_the_open_run(self):
        api = _Api(self.svc)
        self.addCleanup(api.server.shutdown)
        status, first, _ = api.call("POST", "/api/runs", TOKENS["hana"], CL2)
        status, body, _ = api.call("POST", "/api/runs", TOKENS["hana"], CL2)
        self.assertEqual((status, body["active_run"], body["active_status"]), (409, first["run_id"], "awaiting_review"))


if __name__ == "__main__":
    unittest.main()
