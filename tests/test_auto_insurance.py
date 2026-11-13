"""The auto-insurance Minimum Viable Ontology: all five elements and all three layers in one small domain."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from autology import DeferredApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph, build_case
from autology.lint import lint
from autology.reporting import outcome_analysis
from autology.server import AutologyService

from .helpers import ROOT

EX = ROOT / "examples" / "auto_insurance"
TOKENS = {"hana": "tok-hana", "ivan": "tok-ivan", "maria": "tok-maria", "admin": "tok-admin-ai"}


def load():
    onto = Ontology.load(EX / "ontology.json")
    return onto, KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))


def run_claim(claim_id):
    onto, graph = load()
    case, _ = build_case(graph, "claim_case", claim_id)
    agent = WorkAgent("claims", onto, load_tools(EX / "tools.json"),
                      roles=["fraud_analytics", "finance", "claims_handler"], approver=DeferredApprover())
    return agent.run("settle_claim", case, claim_id)


def service():
    for name, token in TOKENS.items():
        os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
    cfg = json.loads((EX / "server.json").read_text())
    cfg["store"] = str(Path(tempfile.mkdtemp()) / "claims.db")
    cfg["automations"] = {}
    return AutologyService(cfg, EX)


class SemanticLayerTests(unittest.TestCase):
    def test_validates_and_answers_its_competency_questions(self):
        onto, graph = load()
        # Ontology.load validates: loading at all means the model is consistent
        self.assertEqual([f.code for f in lint(onto) if f.level != "info"], [])
        answers = {q: graph.ask(q).answer for q in ("CQ-01", "CQ-02", "CQ-03", "CQ-04")}
        self.assertEqual(answers, {"CQ-01": ["CL-1", "CL-2", "CL-3"], "CQ-02": ["RS-2"], "CQ-03": ["CL-3"],
                                   "CQ-04": 86200})

    def test_one_vocabulary(self):
        onto, _ = load()
        self.assertEqual(onto.canonical("Case"), "Claim")  # what another team calls a claim
        self.assertEqual(onto.canonical("Incident"), "Claim")
        self.assertIn("Claim.payout", onto.functions)
        self.assertIn("Also called: Case = Claim, Incident = Claim", onto.describe())


class KineticLayerTests(unittest.TestCase):
    def test_clean_claim_is_paid_the_computed_payout(self):
        result = run_claim("CL-1")
        self.assertEqual(result.status, "completed")
        self.assertEqual([s.action.partition("@")[0] for s in result.steps],
                         ["assess_fraud", "approve_claim", "pay_claim"])
        claim, payment = result.state.entities["Claim"], result.state.entities["Payment"]
        self.assertEqual(claim["approved_amount"], 2700)  # 3,200 less the 500 deductible
        self.assertEqual((payment["amount"], payment["status"]), (2700, "sent"))

    def test_suspicious_claim_waits_for_an_investigator(self):
        result = run_claim("CL-2")
        self.assertEqual(result.status, "awaiting_review")
        self.assertEqual(result.escalation.to, "special_investigations")
        self.assertEqual(result.escalation.action.partition("@")[0], "approve_claim")

    def test_fraud_is_never_paid(self):
        result = run_claim("CL-3")
        self.assertEqual(result.status, "awaiting_review")
        self.assertEqual(result.state.entities["Claim"]["fraud_band"], "certain")
        self.assertEqual(result.escalation.action.partition("@")[0], "reject_claim")
        self.assertNotIn("pay_claim", " ".join(s.action for s in result.steps))


class GovernedPlatformTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        self.u = {x.name: x for x in self.svc.users}

    def test_two_reviews_then_payout_capped_at_the_limit(self):
        run = self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-2"})
        self.svc.decide(self.u["ivan"], run["pending_review"], {"approved": True,
                                                                           "comment": "photos check out"})
        run = self.svc.get_run(self.u["hana"], run["run_id"])
        self.assertEqual(run["status"], "awaiting_review")  # 40,000 payout: the claims manager decides too
        self.assertEqual(run["state"]["Claim"]["approved_amount"], 40000)  # 47,000 capped at the 40,000 limit
        self.svc.decide(self.u["maria"], run["pending_review"], {"approved": True})
        run = self.svc.get_run(self.u["hana"], run["run_id"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["state"]["Payment"]["amount"], 40000)
        self.assertTrue(run["audit_verified"])

    def test_policy_holder_is_hidden_from_investigators(self):
        run = self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-2"})
        review = self.svc.get_review(self.u["ivan"], run["pending_review"])
        self.assertNotEqual(review["request"]["view"]["Policy"]["holder"], "Ben Okafor")
        self.assertEqual(self.svc.get_run(self.u["hana"], run["run_id"])["state"]["Policy"]["holder"], "Ben Okafor")

    def test_dynamic_layer_learns_from_outcomes(self):
        run = self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(run["status"], "completed")
        self.svc.record_outcome(self.u["maria"], run["run_id"], {
            "action": "approve_claim", "label": "repair cost exceeded estimate", "good": False})
        analysis = outcome_analysis(self.svc.store.all_runs(), self.svc.ontology)
        self.assertEqual(analysis["actions"]["approve_claim"]["bad"], 1)
        self.assertEqual(analysis["actions"]["approve_claim"]["unreviewed_bad"], 1)
        # a review rule exists for approvals, but its condition let this one through: widen it
        self.assertTrue(any("approve_claim" in s and "R-SIU-APPROVE did not apply" in s
                            for s in analysis["suggestions"]))


if __name__ == "__main__":
    unittest.main()
