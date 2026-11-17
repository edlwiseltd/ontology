"""Stabilisation F2: potential inconsistencies of a workflow are found by reading the model, and given to a person.

On 17 November 2026 a stored run of a model proposed by a language model completed a turnaround while its
operational conflict was still open. The model loaded: nothing in it was *invalid*. The owner described the
weakness in words and the model proposed a prohibition. These checks find that kind of thing before a run does.

W1  the weakness of that day is found in the model as first released, and no longer in release 3
W2  a goal nothing leads to, an action that can never start, an obligation that can never be met, an action always
    prohibited, an outside effect no rule names, a state never reached
W3  nothing is changed and nothing is blocked: findings come beside validation, and a draft is saved all the same
W4  a model the loader refuses, or anything that is not a model, yields no crash
"""

import copy
import json
import unittest

from autology import consistency
from autology.modeling import validate

from .helpers import ROOT
from .test_arch2_ai_provider_governance import ENGINE, GovernanceBase

RELEASED = ROOT / "planning" / "evidence" / "claude-eval-2026-11-17" / "ground-handling" / "active-model-release-3.json"
MODEL = {"name": "orders", "version": "0.1.0",
         "entities": {"Order": {"states": ["open", "packed", "shipped"], "attributes": {"amount": "number"}},
                      "Complaint": {"states": ["raised", "answered"], "attributes": {"text": "string"}}},
         "relationships": [{"from": "Order", "to": "Complaint", "type": "complaints", "cardinality": "1..*"}],
         "actions": {"pack": {"capability": "ops.pack", "requires": ["Order.status == 'open'"],
                              "effects": {"Order": {"status": "packed"}}, "side_effect": "none"},
                     "ship": {"capability": "ops.ship", "requires": ["Order.status == 'packed'"],
                              "effects": {"Order": {"status": "shipped"}}, "side_effect": "non_idempotent"},
                     "answer": {"capability": "ops.answer", "requires": ["Complaint.status == 'raised'"],
                                "effects": {"Complaint": {"status": "answered"}}, "side_effect": "none"}},
         "rules": [{"id": "R-SHIP", "type": "action_access", "action": "ship", "roles": ["dispatcher"]}],
         "goals": {"shipped": {"target": "Order.status == 'shipped'"}}}


def kinds(document, severity=None):
    return sorted((f["kind"], f.get("action") or f.get("entity")) for f in consistency.findings(document)["findings"]
                  if severity is None or f["severity"] == severity)


class EvidenceTests(unittest.TestCase):
    def test_the_weakness_of_17_november_is_found_before_any_run(self):  # W1
        release3 = json.loads(RELEASED.read_text())
        added = "R_no_completion_with_unsettled_conflict"  # what the model proposed once the owner described the weakness
        self.assertIn(added, [r["id"] for r in release3["rules"]])
        first = copy.deepcopy(release3)
        first["rules"] = [r for r in first["rules"] if r["id"] != added]
        self.assertTrue(validate(first)["valid"] and validate(release3)["valid"])  # both load: validity was never the issue
        found = [f for f in consistency.findings(first)["findings"] if f["severity"] != "low"]
        self.assertEqual(len(found), 1)
        finding = found[0]
        self.assertEqual((finding["kind"], finding["action"], finding["entity"], finding["goal"], finding["severity"]),
                         ("open_exception", "complete_turnaround", "OperationalConflict", "turnaround_recovered", "medium"))
        self.assertEqual(finding["finding"], "complete_turnaround can bring a Turnaround to 'completed' whatever the state "
                                             "of its OperationalConflict")
        self.assertIn("while a OperationalConflict is still open or assessed", finding["why"])
        self.assertEqual(finding["a_person_could"][-1], "leave it: this is intended")
        self.assertIn("add a prohibition on complete_turnaround", " ".join(finding["a_person_could"]))
        self.assertEqual([f for f in consistency.findings(release3)["findings"] if f["severity"] != "low"], [])
        # a goal whose target accepts several states is reachable when one of them is
        self.assertNotIn("goal_unreachable", [f["kind"] for f in consistency.findings(release3)["findings"]])


class CheckTests(unittest.TestCase):
    def changed(self, **parts):
        document = copy.deepcopy(MODEL)
        for key, value in parts.items():
            document[key] = value(document[key]) if callable(value) else value
        return document

    def test_each_kind_of_inconsistency(self):  # W2
        self.assertEqual(kinds(MODEL, "high"), [])
        self.assertEqual(kinds(MODEL, "medium"), [("open_exception", "ship")])  # shipped while a complaint is raised
        guarded = self.changed(actions=lambda a: {**a, "ship": {**a["ship"], "requires": [
            "Order.status == 'packed' and Complaint.status == 'answered'"]}})
        self.assertEqual(kinds(guarded, "medium"), [])
        prohibited = self.changed(rules=lambda r: r + [{"id": "R-HOLD", "type": "prohibition", "action": "ship",
                                                       "when": "Complaint.status == 'raised'"}])
        self.assertEqual(kinds(prohibited, "medium"), [])

        no_way = self.changed(goals={"delivered": {"target": "Order.status == 'delivered' or Order.status == 'returned'"}},
                              entities=lambda e: {**e, "Order": {**e["Order"], "states": ["open", "packed", "shipped",
                                                                                         "delivered", "returned"]}})
        self.assertIn(("goal_unreachable", "Order"), kinds(no_way, "high"))
        unreachable = next(f for f in consistency.findings(no_way)["findings"] if f["kind"] == "goal_unreachable")
        self.assertIn("'delivered' or 'returned'", unreachable["finding"])

        stuck = self.changed(actions=lambda a: {k: v for k, v in a.items() if k != "pack"})
        self.assertIn(("action_cannot_start", "ship"), kinds(stuck, "medium"))
        self.assertIn(("goal_unreachable", "Order"), kinds(self.changed(actions=lambda a: {k: v for k, v in a.items() if k != "ship"}), "high"))

        obliged = self.changed(actions=lambda a: {k: v for k, v in a.items() if k != "pack"},
                               rules=lambda r: r + [{"id": "R-FIRST", "type": "mandatory_step", "step": "ship", "before": "answer"}])
        obligation = next(f for f in consistency.findings(obliged)["findings"] if f["kind"] == "obligation_cannot_be_met")
        self.assertEqual((obligation["severity"], obligation["rule"], obligation["action"]), ("high", "R-FIRST", "ship"))
        self.assertIn("answer would be blocked for ever", obligation["why"])

        barred = self.changed(rules=lambda r: r + [{"id": "R-NEVER", "type": "prohibition", "action": "pack"}])
        self.assertIn(("always_prohibited", "pack"), kinds(barred, "medium"))
        never = self.changed(rules=lambda r: r + [{"id": "R-NEVER", "type": "prohibition", "action": "pack"},
                                                  {"id": "R-MUST", "type": "mandatory_step", "step": "pack"}])
        self.assertIn(("obligation_cannot_be_met", "pack"), kinds(never, "high"))

        open_effect = self.changed(rules=[])
        self.assertIn(("outside_effect_ungoverned", "ship"), kinds(open_effect, "low"))
        self.assertNotIn(("outside_effect_ungoverned", "ship"), kinds(MODEL, "low"))  # an access rule names it
        unused = self.changed(entities=lambda e: {**e, "Order": {**e["Order"], "states": ["open", "packed", "shipped", "lost"]}})
        lost = next(f for f in consistency.findings(unused)["findings"] if f["kind"] == "state_never_reached")
        self.assertEqual((lost["entity"], lost["severity"]), ("Order", "low"))
        self.assertIn("lost", lost["finding"])

    def test_findings_are_ordered_explained_and_never_a_change(self):  # W3
        before = json.dumps(MODEL, sort_keys=True)
        out = consistency.findings(MODEL)
        self.assertEqual(json.dumps(MODEL, sort_keys=True), before)  # the document is read, never written
        self.assertEqual(out["checked"], list(consistency.CHECKS))
        self.assertIn("nothing was changed, nothing is blocked", out["note"])
        order = [f["severity"] for f in out["findings"]]
        self.assertEqual(order, sorted(order, key=["high", "medium", "low"].index))
        for finding in out["findings"]:
            self.assertEqual(set(finding) >= {"id", "kind", "severity", "finding", "why", "a_person_could"}, True)
            self.assertIn(finding["kind"], consistency.CHECKS)
            self.assertEqual(finding["a_person_could"][-1], "leave it: this is intended")
        self.assertEqual(len({f["id"] for f in out["findings"]}), len(out["findings"]))

    def test_anything_that_is_not_a_sound_model_yields_no_crash(self):  # W4
        for document in (None, [], "model", 7, {}, {"entities": "none"}, {"entities": {"A": None}, "actions": {"x": 3},
                                                                          "rules": [1, "two"], "goals": {"g": None},
                                                                          "relationships": ["r"]},
                         {"entities": {"A": {"states": []}}, "goals": {"g": {"target": "A.status == 'done'"}}},
                         {"actions": {"a": {"requires": "B.status == 'x'", "effects": {"B": "status"}}}}):
            out = consistency.findings(document)
            self.assertIsInstance(out["findings"], list, document)


class ApiTests(GovernanceBase):
    def test_findings_come_beside_validation_and_block_nothing(self):  # W3
        status, out = self.call("POST", f"{ENGINE}/model/validate", body={"document": MODEL})
        self.assertEqual(status, 200, out)
        self.assertTrue(out["validation"]["valid"])
        self.assertEqual([(f["kind"], f["severity"]) for f in out["consistency"] if f["severity"] != "low"],
                         [("open_exception", "medium")])
        status, draft = self.call("POST", f"{ENGINE}/model/draft", body={"document": MODEL, "expected_revision": 0,
                                                                         "note": "with a finding"})
        self.assertEqual((status, draft["revision"]), (200, 1))  # a finding is a question, not a refusal
        self.assertEqual(draft["consistency"], out["consistency"])
        status, read = self.call("GET", f"{ENGINE}/model/draft")
        self.assertEqual(read["consistency"], out["consistency"])
        # a malformed document gets the loader's answer, not an internal error (GAP-086), and no finding is made up
        for malformed in ({"entities": 5}, {"entities": {"A": 3}, "relationships": "none", "actions": [], "rules": {}}):
            status, bad = self.call("POST", f"{ENGINE}/model/validate", body={"document": malformed})
            self.assertEqual((status, bad["validation"]["valid"], bad["consistency"]), (200, False, []), malformed)
            self.assertIsInstance(bad["questions"], list)


if __name__ == "__main__":
    unittest.main()
