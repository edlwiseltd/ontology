"""Activation sprint, increment D: readiness of what runs, of the saved draft and of a release that is not active.

One calculation (REL-2 gates and the REL-3 scorecard, ``autology.readiness``), three subjects. Nothing is computed
in Studio, and nothing here changes a stage, a release or what runs.

  D1 what runs: the report names the active release and the running configuration; it is otherwise what it was
  D2 the saved draft: named by its revision and its own configuration; measured on a throwaway engine, so its
     execution evidence is missing (never borrowed from what runs) and "not released" blocks it; the conditions
     that differ from what runs are listed; six dimensions, each with score, evidence, missing evidence, actions
  D3 a release that is not active: named by its number and state; the report says whether the deployed files
     reproduce it; approving it changes the reason it is blocked, not the fact
  D4 the score never decides: a subject whose mandatory conditions fail is blocked whatever it scores; weights
     stay labelled as not approved (D26); production stays refused; promotion to Pilot is still refused
  D5 assessing changes nothing and leaves nothing behind
  D6 authorisation, isolation and refusals: a draft is shown to people who configure or release; other
     workspaces see nothing; an unknown subject, release or target is refused; a draft that does not load says so
"""

import copy
import os
import tempfile

from autology.openapi import PLATFORM_SCHEMAS

from .schema_check import errors
from .test_act3_persistent_simulation import ENGINE, UC, SimulationBase

READY = f"{UC}/readiness?target=pilot"


def flat(report):
    return {c["id"]: c for d in report["dimensions"] for c in d["conditions"]}


class ReadinessSubjectTests(SimulationBase):
    def setUp(self):
        super().setUp()
        self.simulate()
        self.assertEqual(self.begin("DEL-1001")[1]["status"], "completed")

    def supervised(self):
        changed = copy.deepcopy(self.configuration)
        changed["agents"]["disruption_agent"]["autonomy"] = {"mode": "supervised", "reviewer": "operations_manager"}
        return changed

    def test_what_runs_is_named_with_its_release_and_configuration(self):  # D1
        status, report = self.call("GET", READY)
        self.assertEqual(status, 200, report)
        self.assertEqual(errors(report, PLATFORM_SCHEMAS["Readiness"], PLATFORM_SCHEMAS), [])
        subject = report["subject"]
        self.assertEqual((subject["kind"], subject["release"], subject["revision"], subject["configuration"]),
                         ("active", self.release, None, self.fingerprint))
        self.assertIn(f"release {self.release}", subject["label"])
        self.assertIsNone(report["compared_with"])
        self.assertEqual(self.call("GET", f"{READY}&of=active")[1]["subject"], subject)
        mine = flat(report)
        self.assertTrue(mine["approved_release_active"]["passed"])
        self.assertEqual(len(report["dimensions"]), 6)
        # the active release asked for by number is the same subject, not a second calculation on a probe
        same = self.call("GET", f"{READY}&of=release:{self.release}")[1]
        self.assertEqual((same["subject"]["kind"], same["subject"]["configuration"]), ("active", self.fingerprint))

    def test_a_draft_is_assessed_on_its_own_configuration_without_borrowed_evidence(self):  # D2, D4, D5
        revision = self.draft(None, self.supervised())
        before = (self.desk.configuration_fingerprint, self.call("GET", UC)[1]["stage"],
                  sorted(os.listdir(self.home)), len(self.call("GET", f"{UC}/releases")[1]["history"]))
        probes = {p for p in os.listdir(tempfile.gettempdir()) if p.startswith("autology-probe-")}
        active = self.call("GET", READY)[1]
        status, report = self.call("GET", f"{READY}&of=draft")
        self.assertEqual(status, 200, report)
        self.assertEqual(errors(report, PLATFORM_SCHEMAS["Readiness"], PLATFORM_SCHEMAS), [])
        subject = report["subject"]
        self.assertEqual((subject["kind"], subject["revision"], subject["release"]), ("draft", revision, None))
        self.assertNotEqual(subject["configuration"], self.fingerprint)  # the draft's own configuration version
        self.assertIn("no runs or records of its own", subject["evaluated"])
        mine, theirs = flat(report), flat(active)
        # not released: blocked, with the way forward; and no run counts for it, though runs completed on what runs
        self.assertFalse(mine["approved_release_active"]["passed"])
        self.assertIn("a draft is not a release", mine["approved_release_active"]["detail"])
        self.assertTrue(theirs["simulated_run_completed"]["passed"])
        self.assertFalse(mine["simulated_run_completed"]["passed"])
        self.assertEqual((report["gates"]["passed"], report["promotion"]["allowed"]), (False, False))
        blockers = {b["id"] for b in report["gates"]["blockers"]}
        self.assertLessEqual({"approved_release_active", "simulated_run_completed"}, blockers)
        # six dimensions, each with its score, calculation, evidence, missing evidence and corrective actions
        self.assertEqual([d["id"] for d in report["dimensions"]], [d["id"] for d in active["dimensions"]])
        for d in report["dimensions"]:
            self.assertLessEqual({"score", "weight", "calculation", "conditions", "evidence", "missing_evidence",
                                  "blocking", "actions"}, set(d))
        # the differences against what runs: each condition whose standing changed, and both scores per dimension
        compared = report["compared_with"]
        self.assertEqual((compared["kind"], compared["configuration"], compared["same_configuration"],
                          compared["score"]), ("active", self.fingerprint, False, active["score"]["overall"]))
        changed = {d["id"]: (d["active"], d["subject"]) for d in compared["differences"]}
        self.assertEqual(changed["approved_release_active"], ("holds", "does not hold"))
        self.assertEqual(changed["simulated_run_completed"], ("holds", "does not hold"))
        self.assertEqual(sorted(changed), sorted(k for k in mine if (mine[k]["applicable"], mine[k]["measured"],
                                                                     mine[k]["passed"]) !=
                                                 (theirs[k]["applicable"], theirs[k]["measured"], theirs[k]["passed"])))
        self.assertEqual([(d["id"], d["active"]) for d in compared["dimensions"]],
                         [(d["id"], d["score"]) for d in active["dimensions"]])
        # the score informs and never decides; the weights are still a proposal; production is still refused
        self.assertIsNotNone(report["score"]["overall"])
        self.assertIn("not approved by the owner", report["score"]["weights_status"])
        self.assertFalse(report["production"]["authorised"])
        self.assertEqual(self.call("GET", f"{UC}/readiness?target=production&of=draft")[1]["promotion"]["allowed"], False)
        # nothing changed and nothing was left behind
        after = (self.desk.configuration_fingerprint, self.call("GET", UC)[1]["stage"],
                 sorted(os.listdir(self.home)), len(self.call("GET", f"{UC}/releases")[1]["history"]))
        self.assertEqual(after, before)
        self.assertEqual({p for p in os.listdir(tempfile.gettempdir()) if p.startswith("autology-probe-")}, probes)
        self.assertEqual(self.begin("DEL-1005")[1]["status"], "completed")  # what runs still runs

    def test_a_release_that_is_not_active_is_assessed_by_number(self):  # D3, D4
        status, _ = self.publish(self.draft(None, self.supervised()))
        self.assertEqual(status, 200)
        number = self.propose("supervised agent")
        status, report = self.call("GET", f"{READY}&of=release:{number}")
        self.assertEqual(status, 200, report)
        subject = report["subject"]
        self.assertEqual((subject["kind"], subject["release"], subject["matches_release"]), ("release", number, True))
        self.assertIn("proposed", subject["label"])
        self.assertEqual(subject["configuration"], self.call("GET", f"{UC}/releases/{number}")[1]["fingerprint"])
        reason = flat(report)["approved_release_active"]["detail"]
        self.assertIn("is not approved", reason)
        self.assertFalse(report["promotion"]["allowed"])
        self.assertEqual(self.approve(number)[0], 200)
        approved = self.call("GET", f"{READY}&of=release:{number}")[1]
        self.assertIn("approved", approved["subject"]["label"])
        self.assertIn("is not active: activate it", flat(approved)["approved_release_active"]["detail"])
        self.assertFalse(approved["promotion"]["allowed"])  # approval alone promotes nothing
        # the earlier release, no longer what runs, can be assessed too (a rollback candidate)
        earlier = self.call("GET", f"{READY}&of=release:{self.release}")[1]
        self.assertEqual((earlier["subject"]["kind"], earlier["subject"]["configuration"]), ("release", self.fingerprint))
        # stage promotion is what it was: Pilot is refused while mandatory conditions fail, whatever the scores
        status, out = self.call("POST", f"{UC}/stage", body={"to": "pilot", "reason": "the score looks fine"})
        self.assertEqual(status, 409, out)

    def test_who_may_ask_and_what_is_refused(self):  # D6
        self.draft(None, self.supervised())
        self.assertEqual(self.call("GET", READY, "acme-hana")[0], 200)  # what runs: any member of the use case
        status, out = self.call("GET", f"{READY}&of=draft", "acme-hana")
        self.assertEqual(status, 403, out)
        self.assertIn("configure or release", out["error"]["message"])
        self.assertEqual(self.call("GET", f"{READY}&of=release:{self.release}", self.zoe)[0], 200)  # active: as "active"
        # a named release approver without a grant here still sees this use case's releases only (D11, unchanged)
        self.assertEqual(self.call("GET", f"{READY}&of=draft", "acme-maria")[0], 404)
        self.assertEqual(self.call("GET", READY, "acme-maria")[0], 404)
        for token in ("nw-nadia", self.bot):
            self.assertEqual(self.call("GET", f"{READY}&of=draft", token)[0], 404, token)
        self.assertEqual(self.call("GET", f"{READY}&of=release:99")[0], 404)
        self.assertEqual(self.call("GET", f"{READY}&of=nonsense")[0], 400)
        self.assertEqual(self.call("GET", f"{READY}&of=release:x")[0], 400)
        self.assertEqual(self.call("GET", f"{UC}/readiness?target=moon&of=draft")[0], 400)
        claims = "/platform/v1/workspaces/acme/use-cases/claims/readiness?target=pilot&of=draft"
        self.assertEqual(self.call("GET", claims)[0], 404)  # no draft was ever saved there
        # a draft whose model does not load cannot be assessed, and the answer says why
        _, draft = self.call("GET", f"{ENGINE}/model/draft")
        broken = copy.deepcopy(draft["document"])
        broken["rules"].append({"id": "R-BAD", "type": "magic"})
        status, saved = self.call("POST", f"{ENGINE}/model/draft", body={"document": broken,
                                                                        "expected_revision": draft["revision"], "note": "broken"})
        self.assertEqual(status, 200, saved)
        status, out = self.call("GET", f"{READY}&of=draft")
        self.assertEqual(status, 409, out)
        self.assertIn("cannot be assessed", out["error"]["message"])

    def test_an_operators_use_case_is_assessed_with_its_own_agents(self):  # D2 (files-managed)
        claims = "/platform/v1/workspaces/acme/use-cases/claims"
        engine = "/w/acme/u/claims/api/v1"
        _, draft = self.call("GET", f"{engine}/model/draft")
        self.assertEqual(self.call("POST", f"{engine}/model/draft", body={
            "document": draft["document"], "expected_revision": draft["revision"], "note": "same model"})[0], 200)
        status, report = self.call("GET", f"{claims}/readiness?target=pilot&of=draft")
        self.assertEqual(status, 200, report)
        running = self.pf.workspaces["acme"].use_cases["claims"].service.configuration_fingerprint
        self.assertEqual((report["subject"]["kind"], report["subject"]["configuration"],
                          report["compared_with"]["same_configuration"]), ("draft", running, True))
        # a release approver who is a member of the use case may ask; a member who neither configures nor releases may not
        self.assertEqual(self.call("GET", f"{claims}/readiness?target=pilot&of=draft", "acme-maria")[0], 200)
        self.assertEqual(self.call("GET", f"{claims}/readiness?target=pilot&of=draft", "acme-hana")[0], 403)


if __name__ == "__main__":
    import unittest

    unittest.main()
