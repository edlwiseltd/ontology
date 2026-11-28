"""Readiness for an independent semantic review: the package is prepared; no review is, or is pretended to be, done.

  V1 the inventory names every frozen artifact with its hash and what its record lacks, and copies no held-out content
  V2 a blank form has every judgment empty, and is refused until a declared, independent reviewer fills it
  V3 a judgment is about one content: a form about another content, or about something not frozen, is refused
  V4 a low rating owes a rationale and a severity; critical defects are listed apart; nothing is added up
  V5 the rehearsal is synthetic, says so everywhere, and a synthetic reviewer is refused outside it
  V6 the tool reaches nothing outside the repository
"""

import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tool():
    spec = importlib.util.spec_from_file_location("make_review_package", ROOT / "deploy" / "make_review_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReviewPackageTests(unittest.TestCase):
    def setUp(self):
        self.t = tool()

    def test_the_inventory_is_of_frozen_files_and_copies_nothing_held_out(self):  # V1
        held = self.t.inventory()
        by = {row["case"]: row for row in held["artifacts"]}
        self.assertEqual(sum(1 for c in by if c.startswith("run2:")), 7)
        self.assertEqual(sorted(c for c in by if c.startswith("reserved:")), ["reserved:harbour-pilotage", "reserved:museum-loans"])
        self.assertEqual(sum(1 for c in by if c.startswith("v2:")), 8)
        journey = by["journey:ground-handling"]
        self.assertEqual((journey["elements"], journey["inferred"], journey["with_a_citation_stored_at_the_time"],
                          journey["citing_an_answer"], journey["with_structured_evidence_entries"]), (40, 23, 28, 0, 0))
        self.assertEqual(journey["answered_by"]["provider"], "anthropic")
        first = by["run2:b2b-procurement:1"]
        self.assertEqual((first["elements"], first["citation_labels"], first["decisions_on_record"][:4]), (26, ["brief"], "none"))
        for row in held["artifacts"]:  # the hash is of the file as it is now: a changed case no longer matches what is kept
            self.assertEqual(row["sha256"], self.t.sha256(row["artifact"]), row["case"])
        self.assertEqual((held["aggregate"], held["provider_calls"]), (None, 0))
        text = json.dumps(held)
        for path in list((ROOT / "autology" / "evaluation_reserved").glob("*.json")) + list((ROOT / "autology" / "evaluation_v2").glob("*.json")):
            case = json.loads(path.read_text())
            self.assertNotIn(case["brief"][:60], text, path.name)       # a held-out brief is named and hashed, never copied
            self.assertEqual(by[f"{'reserved' if 'reserved' in str(path) else 'v2'}:{path.stem}"]["reviewable"], "nothing yet")
        kept = json.loads((ROOT / "planning" / "review-package" / "inventory.json").read_text())
        self.assertEqual(kept, json.loads(json.dumps(held, sort_keys=True)))   # the kept file is this output, not an edited copy

    def test_a_blank_form_judges_nothing_and_is_refused_until_a_declared_reviewer_fills_it(self):  # V2
        row, items = self.t._items("journey:ground-handling")
        form = self.t.blank_form(row, items)
        self.assertEqual((len(form["elements"]), form["artifact_sha256"], form["subject"]),
                         (40, row["sha256"], "the original output as frozen: not a corrected model"))
        for element in form["elements"]:
            self.assertEqual([element[k] for k in (*self.t.ELEMENT_CRITERIA, "judgment", "rationale", "severity", "suggested_correction")],
                             [None] * (len(self.t.ELEMENT_CRITERIA) + 4))
        self.assertTrue(all(v is None for v in form["model"].values()) and all(v in (None, "") for v in form["reviewer"].values()))
        cites = [e["cited_at_the_time"] for e in form["elements"]]
        self.assertEqual((cites.count(["brief"]), cites.count("missing: the element cites nothing")), (28, 12))  # shown as it is stored
        problems = self.t.check_form(form, items)
        self.assertIn("reviewer: name is empty", problems)
        self.assertIn("reviewer: independence of the project is not declared", problems)
        self.assertIn("reviewer: appointed_by is empty", problems)
        for held_out in ("reserved:museum-loans", "v2:building-permit", "canary:bicycle-rental", "no-such-case"):
            with self.assertRaises(SystemExit):      # no form exists for what has no model output to review
                self.t._items(held_out)
        self.assertEqual(self.t.rows_csv(form).count("\n"), 41)

    def test_what_a_filled_form_owes(self):  # V3, V4
        row, items = self.t.rehearsal_case()
        form = self.t._synthetic(self.t.blank_form(row, items), "A", items)
        self.assertEqual(self.t.check_form(form, items), [])
        cases = {
            "another content": (lambda f: f["elements"][3].update(version="0" * 16), "another content than the one frozen"),
            "not frozen": (lambda f: f["elements"].append({"id": "model:entity:Invented", "version": "x"}), "not an element of the frozen artifact"),
            "a row left out": (lambda f: f["elements"].pop(5), "no row in the form"),
            "outside the scale": (lambda f: f["elements"][4].update(S1=7), "a rating outside the scale"),
            "low without a reason": (lambda f: f["elements"][4].update(S2=1, severity="minor"), "a rating of 0 or 1 without a rationale"),
            "low without a severity": (lambda f: f["elements"][4].update(S2=1, rationale="because"), "a rating of 0 or 1 without a severity"),
            "critical without a basis": (lambda f: f["elements"][4].update(severity="critical", rationale="because"), "a critical defect without"),
            "unknown severity": (lambda f: f["elements"][4].update(severity="grave"), "an unknown severity"),
            "not independent": (lambda f: f["reviewer"].update(independent_of_the_project=False), "independence of the project is not declared"),
            "model outside the scale": (lambda f: f["model"].update(M1=9), "model: a rating outside the scale"),
        }
        for name, (change, expected) in cases.items():
            with self.subTest(name):
                changed = json.loads(json.dumps(form))
                change(changed)
                self.assertTrue(any(expected in p for p in self.t.check_form(changed, items)), self.t.check_form(changed, items))
        summary = self.t.summarise(form)
        self.assertEqual([d["id"] for d in summary["critical_defects"]], [form["elements"][0]["id"]])
        self.assertEqual((summary["aggregate"], summary["verdict"], summary["ratings_per_criterion"]["S3"]["not judged"]), (None, None, 1))
        self.assertFalse([k for k in summary if "score" in k or "total" in k or "pass" in k])

    def test_the_rehearsal_is_synthetic_and_says_so(self):  # V5
        out = self.t.rehearse()
        self.assertIn("SYNTHETIC REHEARSAL", out["label"])
        self.assertIn("not a review", out["label"])
        self.assertEqual((out["filled_forms_accepted"], out["provider_calls"], out["case"]["case"]), ([[], []], 0, "rehearsal:venue-booking"))
        self.assertTrue(all(s["synthetic_rehearsal"] and "not a person" in s["reviewer"] for s in out["summaries"]))
        self.assertEqual(out["a_synthetic_reviewer_outside_a_rehearsal_is_refused"], ["reviewer: a synthetic reviewer on a form that is not a rehearsal"])
        self.assertEqual(len(out["a_form_about_another_content_is_refused"]), 1)
        self.assertEqual(len(out["disagreements"]["for_adjudication"]), 2)     # kept for a person to adjudicate, never averaged
        with self.assertRaisesRegex(ValueError, "two different, named reviewers"):
            first = self.t._synthetic(self.t.blank_form(*self.t.rehearsal_case()), "A", [])
            self.t.disagreements(first, first)
        self.assertNotIn(out["case"]["artifact"], [r["artifact"] for r in self.t.inventory()["artifacts"]])  # apart from every frozen case
        kept = json.loads((ROOT / "planning" / "review-package" / "rehearsal.json").read_text())
        self.assertEqual(kept, json.loads(json.dumps(out, sort_keys=True)))

    def test_the_tool_reaches_nothing_outside_the_repository(self):  # V6
        source = (ROOT / "deploy" / "make_review_package.py").read_text()
        for word in ("urllib", "socket", "http", "requests", "subprocess", "os.environ", "getenv", "anthropic", "openai", "smtplib", "ai_ledger"):
            self.assertNotIn(word, source, word)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.t.main(["inventory"]), 0)


if __name__ == "__main__":
    unittest.main()
