"""MOD-3 (audit GAP-010): wrong-typed tool output is refused; a bad stored row never stops a restart."""

import json
import unittest

from autology import DeferredApprover, ToolRegistry, ToolResult, WorkAgent
from autology.adapters import load_tools
from autology.server import AutologyService

from .test_ingest import EX, service
from .test_mod2_missing_records import claim_case

ROLES = ["fraud_analytics", "finance", "claims_handler"]


def tools_with_fraud_score(value):
    reg = load_tools(EX / "tools.json")
    reg.register("bad_fraud_engine", "fraud.score",
                 lambda call: ToolResult(outcome="clear", updates={"Claim": {"fraud_score": value}}), priority=99)
    return reg


class TypedToolOutputTests(unittest.TestCase):
    def run_with(self, value):
        o, case = claim_case()
        agent = WorkAgent("claims", o, tools_with_fraud_score(value), roles=ROLES, approver=DeferredApprover())
        return agent.run("settle_claim", case, "typed")

    def test_a_wrong_typed_value_is_refused_and_audited(self):
        result = self.run_with("very low")  # the audit's case: fraud_score is a number
        self.assertEqual(result.status, "escalated")
        self.assertIn("Claim.fraud_score", result.escalation.reason)
        self.assertIn("number", result.escalation.reason)
        self.assertIsNone(result.state.get("Claim", "fraud_score"))  # nothing applied
        rejected = result.audit.events("governance.reject_result")
        self.assertEqual(len(rejected), 1)
        self.assertIn("very low", rejected[0].data["reason"])

    def test_booleans_are_not_numbers(self):
        result = self.run_with(True)
        self.assertEqual(result.status, "escalated")
        self.assertIn("Claim.fraud_score", result.escalation.reason)

    def test_a_correct_value_still_flows(self):
        result = self.run_with(0.12)
        self.assertNotEqual(result.status, "escalated")
        self.assertEqual(result.state.get("Claim", "fraud_score"), 0.12)


class StartupQuarantineTests(unittest.TestCase):
    def test_a_corrupted_row_is_quarantined_with_an_alert_and_the_service_starts(self):
        svc = service(automations={})
        path = svc.store.path
        svc.store._db.execute("UPDATE instances SET attributes=? WHERE id='CL-1'",
                              (json.dumps({"amount": "lots", "status": "reported"}),))
        svc.store.close()
        cfg = json.loads((EX / "server.json").read_text())
        cfg.update(store=path, automations={})
        again = AutologyService(cfg, EX)  # used to raise OntologyError and refuse to start
        self.assertNotIn("CL-1", again.graph._instances)
        self.assertIn("CL-2", again.graph._instances)
        self.assertEqual([q["id"] for q in again.quarantined], ["CL-1"])
        self.assertIn("amount must be number", again.quarantined[0]["reason"])
        admin = next(u for u in again.users if u.name == "admin")
        notes = again.list_notifications(admin, None, 10)["items"]
        self.assertTrue(any(n["kind"] == "quarantine" and "CL-1" in n["message"] for n in notes), notes)
        self.assertEqual((again.health()["status"], again.health()["quarantined_records"]), ("degraded", 1))
        self.assertIn("autology_quarantined_records 1", again.metrics(admin))
        # the row is kept for repair, not deleted
        self.assertEqual(len(again.store._query("SELECT 1 FROM instances WHERE id='CL-1'")), 1)
        # links to the quarantined record are left out with it
        self.assertFalse(any("CL-1" in (s, t) for s, _, t in again.graph._links))


if __name__ == "__main__":
    unittest.main()
