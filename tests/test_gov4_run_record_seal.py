"""GOV-4 (audit GAP-014): any edit to a stored run record is detected, not only edits to its audit chain."""

import json
import unittest

from autology.store import SCHEMA_VERSION, Store

from .test_ingest import service

CL2 = {"case_template": "claim_case", "root": "CL-2"}  # 48,000: waits for an investigator, then a manager


class RunRecordSealTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})
        self.u = {x.name: x for x in self.svc.users}
        self.run = self.svc.start_run(self.u["hana"], CL2)
        self.rid = self.run["run_id"]
        self.assertTrue(self.svc.store.verify_audit(self.rid))

    def edit_record(self, change):
        row = self.svc.store._query("SELECT record FROM runs WHERE run_id=?", (self.rid,))[0]
        rec = json.loads(row["record"])
        change(rec)
        self.svc.store._db.execute("UPDATE runs SET record=? WHERE run_id=?", (json.dumps(rec), self.rid))

    def assert_refused(self, user="ivan"):
        self.assertFalse(self.svc.store.verify_audit(self.rid))
        review = [r for r in self.svc.store.list_reviews("pending") if r["run_id"] == self.rid][0]
        out = self.svc.decide(self.u[user], review["review_id"], {"approved": True})
        self.assertNotEqual(out["status"], "completed")
        result = self.svc.store.load_run(self.rid)
        self.assertFalse(any(s.action.startswith("pay_claim") and s.outcome == "done" for s in result.steps),
                         [(s.action, s.outcome) for s in result.steps])
        self.assertIn("run record", (result.escalation.reason if result.escalation else ""))

    def test_editing_the_action_awaiting_review_is_detected(self):
        # the audit's PoC: one approval would then cover the payment review as well
        self.edit_record(lambda rec: rec["run"]["pending_review"].update(action="pay_claim"))
        self.assert_refused()

    def test_editing_attempts_or_the_ontology_reference_is_detected(self):
        self.edit_record(lambda rec: rec["run"].update(failures={"pay_claim": 99}, attempts={},
                                                       ontology_ref="auto-insurance-claims@0.9"))
        self.assert_refused()

    def test_editing_who_started_the_run_is_detected(self):
        # who started a run decides who may approve it (no self-review)
        self.svc.store._db.execute("UPDATE runs SET started_by='someone-else' WHERE run_id=?", (self.rid,))
        self.assertFalse(self.svc.store.verify_audit(self.rid))

    def test_a_chain_copied_onto_another_run_does_not_verify(self):
        db, other = self.svc.store._db, "copied-run"
        db.execute("INSERT INTO audit SELECT ?, seq, timestamp, event, data, prev_hash, hash, alg FROM audit "
                   "WHERE run_id=?", (other, self.rid))
        db.execute("INSERT INTO audit_heads SELECT ?, length, hash, mac, updated_at FROM audit_heads WHERE run_id=?",
                   (other, self.rid))
        columns = [r["name"] for r in db.execute("PRAGMA table_info(runs)") if r["name"] != "run_id"]
        db.execute(f"INSERT INTO runs (run_id, {', '.join(columns)}) SELECT ?, {', '.join(columns)} FROM runs "
                   "WHERE run_id=?", (other, self.rid))
        self.assertTrue(self.svc.store.audit_log(other).verify())  # the chain alone cannot tell
        self.assertFalse(self.svc.store.verify_audit(other))

    def test_untouched_runs_still_verify_and_resume(self):
        review = [r for r in self.svc.store.list_reviews("pending") if r["run_id"] == self.rid][0]
        out = self.svc.decide(self.u["ivan"], review["review_id"], {"approved": True})
        self.assertEqual(out["status"], "awaiting_review")  # next: the claims manager
        self.assertTrue(self.svc.store.verify_audit(self.rid))

    def test_reopening_the_store_keeps_the_seal(self):
        path = self.svc.store.path
        self.svc.store.close()
        again = Store(path)
        self.assertTrue(again.verify_audit(self.rid))
        again.close()

    def test_a_schema_10_store_is_sealed_on_upgrade(self):
        path = self.svc.store.path
        db = self.svc.store._db
        db.execute("ALTER TABLE runs DROP COLUMN seal")
        db.execute("UPDATE meta SET value='10' WHERE key='schema_version'")
        self.svc.store.close()
        again = Store(path)
        self.assertEqual(again._query("SELECT value FROM meta WHERE key='schema_version'")[0]["value"],
                         str(SCHEMA_VERSION))
        self.assertTrue(again.verify_audit(self.rid))
        again.close()

    def test_unverified_runs_are_reported(self):
        self.edit_record(lambda rec: rec.update(status="completed"))
        self.svc._verified = (0, 0)  # skip the one-minute cache
        self.assertEqual(self.svc.unverified_runs(), 1)


if __name__ == "__main__":
    unittest.main()
