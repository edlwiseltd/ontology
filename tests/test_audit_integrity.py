"""Review item 6: the audit trail is tamper-evident against someone who can edit the stored data."""

import copy
import os
import sqlite3
import unittest
from unittest import mock

from autology import Ontology, ReviewDecision, WorkAgent
from autology.adapters import load_tools
from autology.agent import DeferredApprover
from autology.audit import AuditEntry, AuditLog, _digest

from .test_platform import CASE, EX, add_big_order, service

KEY = {"AUTOLOGY_AUDIT_KEY": "test-secret-key-0123456789"}


def forge(log: AuditLog, index: int, **data) -> AuditLog:
    """What an attacker without the key does: edit an entry and recompute the plain hashes after it."""
    entries = log.to_list()
    entries[index]["data"] = {**entries[index]["data"], **data}
    prev = entries[index]["prev_hash"]
    for e in entries[index:]:
        e["prev_hash"] = prev
        e["hash"] = _digest(e["seq"], e["timestamp"], e["event"], e["data"], prev)
        e.pop("alg", None)
        prev = e["hash"]
    return AuditLog.from_list(entries)


class ChainTests(unittest.TestCase):
    @mock.patch.dict(os.environ, KEY)
    def test_rewritten_entries_fail_without_the_key(self):
        log = AuditLog()
        for i in range(4):
            log.record("step", n=i)
        self.assertTrue(log.verify())
        self.assertFalse(forge(log, 1, n=99).verify())

    @mock.patch.dict(os.environ, KEY)
    def test_truncation_is_detected_against_the_head(self):
        log = AuditLog()
        for i in range(4):
            log.record("step", n=i)
        head = log.head()
        cut = AuditLog.from_list(log.to_list()[:2])
        self.assertTrue(cut.verify(cut.head()))  # a shorter chain is still a valid chain...
        self.assertFalse(cut.verify(head))  # ...but not the one whose head was recorded
        self.assertTrue(log.verify(head))
        forged_head = dict(head, length=2, hash=cut.to_list()[-1]["hash"])
        self.assertFalse(cut.verify(forged_head))  # the head is keyed too


class StoreTests(unittest.TestCase):
    @mock.patch.dict(os.environ, KEY)
    def test_deleted_tail_is_detected(self):
        svc = service(automations={}, chat=None)
        olivia = next(u for u in svc.users if u.name == "olivia")
        run = svc.start_run(olivia, add_big_order(svc))
        self.assertTrue(svc.store.verify_audit(run["run_id"]))
        db = sqlite3.connect(svc.store.path)
        db.execute("DROP TRIGGER audit_no_delete")  # someone with database access
        db.execute("DELETE FROM audit WHERE run_id=? AND seq=(SELECT MAX(seq) FROM audit WHERE run_id=?)",
                   (run["run_id"], run["run_id"]))
        db.commit()
        self.assertFalse(svc.store.verify_audit(run["run_id"]))


class ResumeBindingTests(unittest.TestCase):
    def parked(self):
        onto = Ontology.load(EX / "ontology.json")
        agent = WorkAgent("a", onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops", "finance"],
                          approver=DeferredApprover())
        return agent, agent.run("fulfil_contract", CASE, "K-1")

    @mock.patch.dict(os.environ, KEY)
    def test_injected_approval_is_refused(self):
        agent, parked = self.parked()
        self.assertEqual(parked.status, "awaiting_review")
        waiting = parked.run.pending_review["action"]
        tampered = copy.copy(parked)
        tampered.status = "paused"  # edited in storage: no decision ever went through decide()
        tampered.run.review_decisions = {waiting: {"approved": True, "reviewer": "lena", "comment": "forged"}}
        tampered.run.pending_review = None
        result = agent.resume(tampered)
        self.assertNotEqual(result.status, "completed")
        self.assertIn("audit", result.escalation.reason)
        self.assertFalse(any(s.action == waiting and s.outcome for s in result.steps))

    @mock.patch.dict(os.environ, KEY)
    def test_edited_state_is_refused(self):
        agent, parked = self.parked()
        tampered = copy.copy(parked)
        tampered.status = "paused"
        tampered.run.pending_review = None
        tampered.run.state.collections["Order"]["O-4"]["amount"] = 100  # now below the review threshold
        result = agent.resume(tampered)
        self.assertEqual(result.status, "escalated")
        self.assertIn("does not match", result.escalation.reason)

    @mock.patch.dict(os.environ, KEY)
    def test_genuine_decision_still_works(self):
        agent, parked = self.parked()
        done = agent.resume(parked, decision=ReviewDecision(True, "lena", "ok"))
        self.assertEqual(done.status, "completed")  # O-5 is declined at the credit check: no second review
        self.assertTrue(done.audit.verify(done.audit.head()))


if __name__ == "__main__":
    unittest.main()


class ServerKeyTests(unittest.TestCase):
    def test_a_real_server_needs_the_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AUTOLOGY_AUDIT_KEY", None)
            with self.assertRaises(ValueError) as cm:
                service(automations={}, chat=None)
            self.assertIn("AUTOLOGY_AUDIT_KEY", str(cm.exception))
            self.assertTrue(service(automations={}, chat=None, simulation=True).simulation)  # test servers may

    def test_heads_endpoint_and_health(self):
        from .test_platform import _Api

        svc = service(automations={}, chat=None)
        olivia = next(u for u in svc.users if u.name == "olivia")
        run = svc.start_run(olivia, add_big_order(svc))
        api = _Api(svc)
        try:
            self.assertTrue(api.call("GET", "/api/health")[1]["audit_keyed"])
            self.assertEqual(api.call("GET", "/api/audit-heads", "olivia")[0], 403)
            heads = api.call("GET", "/api/audit-heads", "audrey")[1]["items"]
            head = next(h for h in heads if h["run_id"] == run["run_id"])
            self.assertEqual(head["length"], len(svc.store.audit_log(run["run_id"])))
            self.assertTrue(head["mac"])
        finally:
            api.server.shutdown()
