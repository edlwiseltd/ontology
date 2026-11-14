"""MOD-2 (audit GAP-017): a record missing from a case is unknown, never present "in its initial state"."""

import copy
import json
import unittest
from pathlib import Path

from autology import AutoApprover, DeferredApprover, Ontology, OntologyError, WorkAgent
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph, build_case
from autology.state import WorldState

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples" / "auto_insurance"
CARE = ROOT / "examples" / "care_referral"
ROLES = ["fraud_analytics", "finance", "claims_handler"]


def claim_case(root="CL-1"):
    onto = Ontology.load(EX / "ontology.json")
    graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
    case, _ = build_case(graph, "claim_case", root)
    return onto, case


def agent(onto, approver=None):
    return WorkAgent("claims", onto, load_tools(EX / "tools.json"), roles=ROLES,
                     approver=approver or DeferredApprover())


class MissingRecordTests(unittest.TestCase):
    def test_a_missing_record_has_no_status_and_no_values(self):
        onto, case = claim_case()
        del case["Policy"]
        state = WorldState.initial(onto, case)
        self.assertIsNone(state.get("Policy", "status"))
        self.assertTrue(all(v is None for v in state.entities["Policy"].values()))

    def test_a_claim_without_its_policy_is_never_approved_or_paid(self):
        # the audit's case: the policy was assumed "active" and the claim approved and paid with amount None
        onto, case = claim_case()
        del case["Policy"]
        result = agent(onto).run("settle_claim", case, "no-policy")
        done = [s.action for s in result.steps if s.outcome]
        self.assertNotIn("approve_claim", done)
        self.assertNotIn("pay_claim", done)
        self.assertIsNone(result.state.get("Payment", "amount"))
        # the only way left is a rejection, which an investigator decides (R-SIU-REJECT)
        self.assertEqual((result.status, result.run.pending_review["action"]), ("awaiting_review", "reject_claim"))

    def test_with_no_way_left_the_explanation_names_the_missing_record(self):
        onto, case = claim_case()
        doc = json.loads((EX / "ontology.json").read_text())
        del doc["actions"]["reject_claim"]
        doc["rules"] = [r for r in doc["rules"] if r.get("action") != "reject_claim"]
        onto = Ontology.from_dict(doc)
        del case["Policy"]
        result = agent(onto).run("settle_claim", case, "no-policy")
        self.assertEqual(result.status, "escalated")
        details = " ".join(result.escalation.details)
        self.assertIn("Policy is not in the case", details)
        self.assertIn("approve_claim", details)

    def test_an_effect_computed_from_an_unknown_value_blocks_the_action(self):
        onto, case = claim_case()
        case["Claim"]["amount"] = None  # the payout cannot be computed
        result = agent(onto).run("settle_claim", case, "no-amount")
        self.assertNotIn("approve_claim", [s.action for s in result.steps if s.outcome])
        self.assertIsNone(result.state.get("Claim", "approved_amount"))
        doc = json.loads((EX / "ontology.json").read_text())
        del doc["actions"]["reject_claim"]
        doc["rules"] = [r for r in doc["rules"] if r.get("action") != "reject_claim"]
        result = agent(Ontology.from_dict(doc)).run("settle_claim", case, "no-amount")
        self.assertEqual(result.status, "escalated")
        self.assertIn("Claim.approved_amount", " ".join(result.escalation.details))

    def test_the_same_claim_with_its_policy_still_settles(self):
        onto, case = claim_case()
        result = agent(onto, AutoApprover(default=True)).run("settle_claim", case, "ok")
        self.assertEqual(result.status, "completed")

    def test_records_the_process_creates_can_start_in_their_initial_state(self):
        onto = Ontology.load(CARE / "ontology.json")
        self.assertEqual(onto.entities["CarePlan"].when_absent, "initial")
        case = json.loads((CARE / "pilot_cases.json").read_text())
        case = (case if isinstance(case, list) else case["cases"])[0]
        case = case.get("case", case)
        self.assertNotIn("CarePlan", case)
        self.assertEqual(WorldState.initial(onto, case).get("CarePlan", "status"), "none")

    def test_when_absent_takes_two_values(self):
        doc = json.loads((CARE / "ontology.json").read_text())
        bad = copy.deepcopy(doc)
        bad["entities"]["CarePlan"]["when_absent"] = "assume"
        with self.assertRaises(OntologyError):
            Ontology.from_dict(bad)


if __name__ == "__main__":
    unittest.main()
