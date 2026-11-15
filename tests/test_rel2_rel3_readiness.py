"""REL-2 (mandatory promotion gates) and REL-3 (evidence-based readiness scorecard).

  Q1 the report gives, for each of six dimensions, its calculation, the evidence used, the evidence missing, its
     blockers and the corrective actions; the figures can be recomputed from the conditions it lists
  Q2 a mandatory condition that does not hold blocks promotion; so does one that cannot be verified (a missing
     proof is not a pass)
  Q3 a high score never overrides a blocker, in the report and at the promotion itself
  Q4 production is not authorised even when every mandatory condition holds; the promotion is refused as before
  Q5 weights are a proposal: they are reported with their status, can be configured per use case, change the
     overall figure only, and are not part of the governing configuration
  Q6 the new mandatory conditions are measured on the running use case: an action without a tool, an action that
     only a production tool performs, a suspended agent, unreviewed model discretion, a decision-critical fact
     nobody may change, a write-back conflict; production-only conditions do not block a pilot
  Q7 through the platform: the report follows the published contract, is read by granted members only, records
     nothing, and includes what only the platform knows (the active release, unrestricted grants awaiting review)
  Q8 the mandatory conditions are evaluated at the promotion itself, on the server
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from autology import readiness
from autology.lifecycle import REFUSED_STAGES
from autology.openapi import PLATFORM_SCHEMAS
from autology.readiness import BOTH, DIMENSIONS, PRODUCTION, PROPOSED_WEIGHTS, Condition

from . import test_ingest
from .schema_check import errors
from .test_r2_use_case_lifecycle import LifecycleBase, make_platform, template_config
from .test_workspaces import Client

READY = "/platform/v1/workspaces/acme/use-cases/claims/readiness"


def held(n=1, mandatory=BOTH, dimension="ontology", ident=None):
    return Condition(ident or f"c{id(object())}", dimension, "a condition that holds", n, n, "holds", mandatory,
                     ["evidence"], None, "nothing to do")


def service(**overrides):
    svc = test_ingest.service(automations={}, **overrides)
    return svc


def model(change):
    """The insurance model after ``change(document)``, written to a temporary file."""
    doc = json.loads((test_ingest.EX / "ontology.json").read_text())
    change(doc)
    path = Path(tempfile.mkdtemp()) / "ontology.json"
    path.write_text(json.dumps(doc))
    return str(path)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        self.addCleanup(self.svc.close)

    def blockers(self, target="pilot", svc=None, context=None):
        return {b["id"] for b in readiness.report(svc or self.svc, target, context)["gates"]["blockers"]}

    def test_every_dimension_shows_its_calculation_and_evidence(self):  # Q1
        report = readiness.report(self.svc, "pilot")
        self.assertEqual([d["id"] for d in report["dimensions"]], list(DIMENSIONS))
        weighted = used = 0.0
        for d in report["dimensions"]:
            for key in ("calculation", "conditions", "evidence", "missing_evidence", "blocking", "actions"):
                self.assertIn(key, d)
            measured = [c for c in d["conditions"] if c["measured"]]
            expected = round(100 * sum(c["held"] / c["total"] for c in measured) / len(measured), 1)
            self.assertEqual(d["score"], expected, d["id"])  # recomputed from what the report lists
            self.assertIn(f"/ {len(measured)} measured conditions = {expected}", d["calculation"])
            self.assertEqual(d["blocking"], [c["id"] for c in d["conditions"] if c["blocking"]])
            for c in d["conditions"]:
                self.assertTrue(c["title"] and c["detail"], c["id"])
                self.assertEqual(bool(c["action"]), c["applicable"] and c["passed"] is not True, c["id"])
            weighted += expected * d["weight"]
            used += d["weight"]
        self.assertEqual(report["score"]["overall"], round(weighted / used, 1))
        self.assertEqual(report["score"]["weights"], PROPOSED_WEIGHTS)
        self.assertIn("not approved by the owner", report["score"]["weights_status"])
        self.assertEqual(report["configuration"]["fingerprint"], self.svc.ontology.fingerprint)
        data = next(d for d in report["dimensions"] if d["id"] == "data")
        facts = next(c for c in data["conditions"] if c["id"] == "decision_facts_protected")
        self.assertEqual((facts["held"], facts["passed"], facts["blocking"]), (0, False, False))  # production only
        self.assertIn("Claim.amount", facts["detail"])
        self.assertIn("Add a write_access rule", " ".join(data["actions"]))
        with self.assertRaises(ValueError):
            readiness.report(self.svc, "simulation")

    def test_what_does_not_hold_or_cannot_be_verified_blocks(self):  # Q2
        pilot = self.blockers("pilot")
        # nothing was simulated here, and a standalone engine cannot prove a release: both block
        self.assertEqual(pilot, {"simulated_run_completed", "configuration_unchanged_since_simulation",
                                 "approved_release_active"})
        report = readiness.report(self.svc, "production")
        reasons = {b["id"]: b["reason"] for b in report["gates"]["blockers"]}
        self.assertEqual(reasons["recovery_evidence"],
                         "not verified: a recorded platform backup verification and restore drill")
        self.assertIn("not verified", reasons["unrestricted_grants_reviewed"])
        self.assertEqual(reasons["decision_facts_protected"], "does not hold")
        operations = next(d for d in report["dimensions"] if d["id"] == "operations")
        self.assertTrue(any("A verified backup exists" in m for m in operations["missing_evidence"]))
        self.assertIn("recovery_evidence", operations["blocking"])
        # the same evidence, once supplied, is measured rather than assumed
        supplied = {"recovery": {"verified": True, "detail": "drill of 14 Nov"}, "unrestricted_needing_review": 0}
        self.assertFalse({"recovery_evidence", "unrestricted_grants_reviewed"} & self.blockers("production", context=supplied))
        self.assertIn("recovery_evidence", self.blockers("production", context={"recovery": {"verified": False}}))

    def test_a_high_score_never_overrides_a_blocker(self):  # Q3
        fine = [held(dimension=d) for d in DIMENSIONS for _ in range(5)]
        report = readiness.report(self.svc, "pilot", found=fine)
        self.assertEqual((report["score"]["overall"], report["promotion"]["allowed"]), (100.0, True))
        one = Condition("release_missing", "operations", "An approved release is active", None, 1, "unknown", BOTH,
                        [], "the release registry", "Activate an approved release")
        report = readiness.report(self.svc, "pilot", found=fine + [one])
        self.assertEqual(report["score"]["overall"], 100.0)  # an unmeasured condition does not lower the score...
        self.assertEqual((report["promotion"]["allowed"], [b["id"] for b in report["gates"]["blockers"]]),
                         (False, ["release_missing"]))  # ...and still blocks
        self.assertIn("the score does not change that", report["promotion"]["reason"])
        failing = Condition("agent_suspended", "agents", "No agent is suspended", 0, 1, "suspended: claims", BOTH)
        report = readiness.report(self.svc, "pilot", found=fine + [failing])
        self.assertGreaterEqual(report["score"]["overall"], 97)
        self.assertFalse(report["promotion"]["allowed"])
        advisory = Condition("advice", "data", "Advisory only", 0, 4, "none", ())
        report = readiness.report(self.svc, "pilot", found=fine + [advisory])
        self.assertTrue(report["promotion"]["allowed"])  # and a low figure alone blocks nothing
        self.assertLess(report["score"]["overall"], 100)

    def test_production_is_not_authorised_whatever_the_gates_say(self):  # Q4
        fine = [held(dimension=d) for d in DIMENSIONS]
        report = readiness.report(self.svc, "production", found=fine)
        self.assertEqual((report["gates"]["passed"], report["score"]["overall"]), (True, 100.0))
        self.assertEqual((report["promotion"]["allowed"], report["production"]),
                         (False, {"authorised": False, "reason": REFUSED_STAGES["production"]}))
        self.assertIn("production is not authorised", report["promotion"]["reason"])
        self.assertEqual(readiness.report(self.svc, "pilot", found=fine)["production"]["authorised"], False)

    def test_weights_are_a_proposal_and_only_change_the_overall_figure(self):  # Q5
        base = readiness.report(self.svc, "pilot")
        weights = {d: 0 for d in DIMENSIONS} | {"evidence": 1}
        tuned = service(readiness={"weights": weights})
        self.addCleanup(tuned.close)
        report = readiness.report(tuned, "pilot")
        evidence = next(d for d in report["dimensions"] if d["id"] == "evidence")
        self.assertEqual(report["score"]["overall"], evidence["score"])
        self.assertNotEqual(report["score"]["overall"], base["score"]["overall"])
        self.assertIn("configured for this use case", report["score"]["weights_status"])
        self.assertIn("not approved by the owner", report["score"]["weights_status"])
        self.assertEqual(report["gates"], base["gates"])  # the gates do not depend on any weight
        self.assertEqual([d["score"] for d in report["dimensions"]], [d["score"] for d in base["dimensions"]])
        self.assertEqual(tuned.configuration_fingerprint, self.svc.configuration_fingerprint)  # not governing
        for bad in ({"weights": {"ontology": 1}}, {"weights": {d: -1 for d in DIMENSIONS}},
                    {"weights": {d: 0 for d in DIMENSIONS}}, {"weights": {d: "1" for d in DIMENSIONS}},
                    {"weights": PROPOSED_WEIGHTS, "approved": True}, "high"):
            with self.assertRaises(ValueError):
                service(readiness=bad)
        self.assertEqual(sum(PROPOSED_WEIGHTS.values()), 100)

    def test_the_new_conditions_are_measured_on_the_running_use_case(self):  # Q6
        def without_tool(doc):
            doc["actions"]["audit_claim"] = {"description": "Audit the claim", "capability": "claims.audit",
                                             "requires": ["Claim.status == 'paid'"], "effects": {"Claim": {}},
                                             "side_effect": "none"}

        def critical(doc):
            doc["entities"]["Claim"]["attributes"]["amount"] = {"type": "number", "decision_critical": True}

        for label, overrides, expected in (
                ("an action no tool performs", {"ontology": model(without_tool)}, "actions_have_a_tool"),
                ("a decision-critical fact with no writer", {"ontology": model(critical)},
                 "critical_facts_have_a_writer")):
            svc = service(**overrides)
            self.addCleanup(svc.close)
            self.assertIn(expected, self.blockers("pilot", svc), label)
        self.assertNotIn("actions_have_a_tool", self.blockers())
        self.assertNotIn("critical_facts_have_a_writer", self.blockers())  # nothing classified: not applicable
        # unreviewed model discretion, a suspended agent, a tool that exists only for production
        self.svc.model_findings.append("agent claims: model_discretion is open")
        self.assertIn("model_discretion_reviewed", self.blockers())
        self.svc.model_findings.clear()
        agent = self.svc.agents["claims"].agent
        agent.governance.suspended[agent.principal.name] = "three violations"
        self.assertIn("no_agent_suspended", self.blockers())
        agent.governance.suspended.clear()
        tool = next(t for t in agent.tools if t.capability == self.svc.ontology.actions["pay_claim"].capability)
        before, tool.environment = tool.environment, "production"
        self.assertIn("actions_testable_before_production", self.blockers())
        tool.environment = before
        # a write-back waiting on a conflict
        self.svc.store.pending_write_backs = lambda: ["R-1"]
        self.svc.store.run_sources = lambda run_id: {"conflicts": [{"id": "CL-1", "attribute": "amount"}]}
        self.assertIn("no_write_back_conflict", self.blockers())
        del self.svc.store.pending_write_backs, self.svc.store.run_sources
        # production-only conditions are reported for a pilot without blocking it
        self.assertFalse({"decision_facts_protected", "side_effects_declared", "actions_exercised",
                          "review_paths_exercised", "recovery_evidence"} & self.blockers("pilot"))
        self.assertTrue({"decision_facts_protected", "actions_exercised", "recovery_evidence"}
                        <= self.blockers("production"))
        # exercising the model is evidence: a completed run performs actions and a review is decided
        u = {x.name: x for x in self.svc.users}
        self.svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        done = readiness.report(self.svc, "production")
        exercised = next(c for d in done["dimensions"] for c in d["conditions"] if c["id"] == "actions_exercised")
        self.assertGreater(exercised["held"], 0)
        self.assertLess(exercised["held"], exercised["total"])
        self.assertIn("never performed", exercised["detail"])
        self.assertEqual(PRODUCTION, ("production",))


class PlatformTests(LifecycleBase):
    def ready(self, target="pilot", token="acme-hana", path=READY):
        return self.c.call("GET", f"{path}?target={target}", token)

    def test_the_report_through_the_platform(self):  # Q7
        status, report = self.ready()
        self.assertEqual(status, 200)
        self.assertEqual(errors(report, PLATFORM_SCHEMAS["Readiness"], PLATFORM_SCHEMAS), [])
        self.assertEqual((report["stage"], report["target"], report["promotion"]["allowed"]), ("draft", "pilot", False))
        blockers = {b["id"] for b in report["gates"]["blockers"]}
        self.assertIn("approved_release_active", blockers)  # known to the platform: measured, not missing
        release = next(c for d in report["dimensions"] for c in d["conditions"] if c["id"] == "approved_release_active")
        self.assertEqual((release["measured"], release["passed"]), (True, False))
        review = next(c for d in report["dimensions"] for c in d["conditions"]
                      if c["id"] == "unrestricted_grants_reviewed")
        self.assertTrue(review["measured"])
        self.assertIn("grants await review", review["detail"])
        history = self.c.call("GET", "/platform/workspaces/acme/use-cases/claims", "acme-hana")[1]["history"]
        self.assertEqual(history, [])  # reading the report records nothing
        self.assertEqual(self.ready("production")[1]["production"]["authorised"], False)
        self.assertEqual(self.ready("nowhere")[0], 400)
        self.assertEqual(self.ready(token=None)[0], 401)
        self.assertEqual(self.ready(token="nw-nadia")[0], 404)  # another tenant: the same 404 as anything else
        self.assertEqual(self.ready(path="/platform/v1/workspaces/northwind/use-cases/claims/readiness")[0], 404)
        self.assertEqual(self.c.call("POST", READY, "acme-ada", {})[0], 404)

    def test_the_gates_are_evaluated_at_the_promotion_itself(self):  # Q3, Q8
        self.assertEqual(self.move("simulation")[0], 200)
        self.complete_a_run()
        self.release()
        _, report = self.ready()
        self.assertEqual((report["promotion"]["allowed"], report["gates"]["blockers"]), (True, []))
        # one mandatory condition stops holding: the figure barely moves, the promotion is refused
        agent = self.pf.workspaces["acme"].use_cases["claims"].service.agents["claims"].agent
        agent.governance.suspended[agent.principal.name] = "three violations"
        _, blocked = self.ready()
        self.assertGreater(blocked["score"]["overall"], 80)
        self.assertEqual(([b["id"] for b in blocked["gates"]["blockers"]], blocked["promotion"]["allowed"]),
                         (["no_agent_suspended"], False))
        status, out = self.move("pilot", "the score is high")
        self.assertEqual(status, 409)
        self.assertEqual([c["id"] for c in out["checks"] if not c["passed"]], ["no_agent_suspended"])
        agent.governance.suspended.clear()
        self.assertEqual(self.move("pilot", "every mandatory condition holds")[0], 200)
        status, out = self.move("production", "go live")  # Q4: as before
        self.assertEqual(status, 403)
        _, after = self.ready("production")
        self.assertEqual((after["stage"], after["promotion"]["allowed"]), ("pilot", False))

    def test_a_use_case_whose_action_has_no_tool_does_not_reach_a_pilot(self):  # Q6, Q8
        def change(doc):
            doc["actions"]["audit_claim"] = {"description": "Audit the claim", "capability": "claims.audit",
                                             "requires": ["Claim.status == 'paid'"], "effects": {"Claim": {}},
                                             "side_effect": "none"}
        self.c.server.shutdown()
        self.c.server.server_close()
        self.pf.close()
        os.environ.setdefault("AUTOLOGY_AUDIT_KEY", "k" * 32)
        self.pf = make_platform(templates={"demo": {"config": template_config(ontology=model(change))}})
        self.c = Client(self.pf)
        base = "/platform/workspaces/acme/use-cases/demo"
        self.assertEqual(self.c.call("POST", "/platform/workspaces/acme/use-cases", "acme-ada",
                                     {"id": "demo", "template": "demo"})[0], 201)
        self.assertEqual(self.move("simulation", path=f"{base}/stage")[0], 200)
        _, dry = self.c.call("GET", f"{base}/checks?to=pilot", "acme-ada")
        self.assertIn("actions_have_a_tool", [c["id"] for c in dry["checks"] if not c["passed"]])
        self.assertEqual(self.move("pilot", path=f"{base}/stage")[0], 409)


if __name__ == "__main__":
    unittest.main()
