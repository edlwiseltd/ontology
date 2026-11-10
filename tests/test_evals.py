"""Tier 2: evaluation harness for reasoners."""

import copy
import io
import json
import random
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from autology import OntologyError
from autology.__main__ import main as cli
from autology.evals import Check, _make_reasoner, check, load_suite, run_suite
from autology.reasoners import FunctionChatModel, LLMReasoner, PlanFollowingReasoner

from .test_platform import EX

SUITE = EX / "evals.json"


def write_suite(**changes):
    doc = json.loads(SUITE.read_text())
    for k, v in changes.items():
        if v is None:
            doc.pop(k, None)
        else:
            doc[k] = v
    path = EX / f"_tmp_suite_{random.randrange(10 ** 9)}.json"
    path.write_text(json.dumps(doc))
    return path


class SuiteTests(unittest.TestCase):
    def tearDown(self):
        for p in EX.glob("_tmp_suite_*.json"):
            p.unlink()

    def test_example_suite(self):
        report = run_suite(load_suite(SUITE))
        summary = report.summary()
        self.assertEqual({n: m["pass_rate"] for n, m in summary.items()},
                         {"planner": 1.0, "contrarian": 1.0, "unreliable": 1.0})
        self.assertEqual(summary["planner"]["agreement"], 1.0)
        self.assertLess(summary["contrarian"]["agreement"], 1.0)  # legal choices, but not the planner's
        self.assertGreater(summary["contrarian"]["cost_usd"], 0)  # suite prices apply
        self.assertGreater(summary["unreliable"]["fallbacks"], 0)  # invalid answers fall back safely
        self.assertEqual(report.failures(), {})
        self.assertIn("| five orders | pass | pass | pass |", report.render())
        self.assertEqual(len(report.as_dict()["results"]), 15)

    def test_invalid_suites(self):
        bad_case = {"id": "x", "case": {}, "expect": {"colour": "red"}}
        variants = {
            "goal": {"goal": "ghost"},
            "case": {"cases": [{"id": "x"}]},
            "expectation": {"cases": [bad_case]},
            "final": {"cases": [{"id": "x", "case": {}, "expect": {"final": ["Order.status ==="]}}]},
            "case goal": {"cases": [{"id": "x", "case": {}, "goal": "ghost"}]},
        }
        for label, change in variants.items():
            with self.subTest(label), self.assertRaises(Exception):
                load_suite(write_suite(**change))

    def test_defaults_policy_and_delegates(self):
        path = write_suite(goal=None, approver="approvals.json", reasoners=None, repeats=2,
                           roles=["ops", "eu_ops"],
                           delegates=[{"name": "finance-bot", "roles": ["finance", "eu_ops"], "tools": "tools.json"}],
                           cases=[{"case_file": "case.json"}])
        suite = load_suite(path)
        self.assertEqual((suite.goal, list(suite.reasoners), suite.cases[0].id), ("fulfil_contract", ["planner"],
                                                                                  "case-1"))
        self.assertEqual(suite.cases[0].expect, {"status": "completed"})
        report = run_suite(suite)
        self.assertEqual(report.summary()["planner"]["runs"], 2)
        self.assertEqual(report.summary()["planner"]["passed"], 2)  # finance work delegated

    def test_failures_are_analysed(self):
        suite = load_suite(SUITE)
        suite.cases[0].expect = {"status": ["blocked", "escalated"], "contains": ["fly", "ship_order"],
                                 "excludes": ["ship_order"], "order": ["ship_order@O-2", "clear_hazmat@O-2"],
                                 "max_steps": 3, "reviews": 0, "final": ["Contract.value < 0"],
                                 "escalation": "nope", "max_fallbacks": -1, "max_cost_usd": -1}
        suite.cases[1].expect = {"order": ["fly", "ship_order"]}
        report = run_suite(suite, {"planner": "planner"})
        failed = {c.name: c.detail for c in report.results[0].checks if not c.passed}
        self.assertEqual(failed["status"], "got completed")
        self.assertEqual(failed["contains fly"], "never executed")
        self.assertNotIn("contains ship_order", failed)
        self.assertTrue(failed["excludes ship_order"].startswith("executed at step"))
        self.assertTrue(failed["order ship_order@O-2 -> clear_hazmat@O-2"].startswith("executed as clear_hazmat"))
        self.assertEqual(failed["max_steps 3"], "took 20")
        self.assertEqual(failed["reviews 0"], "got 1")
        self.assertEqual(failed["final Contract.value < 0"], "does not hold on the final state")
        self.assertEqual(failed["escalation mentions 'nope'"], "no escalation")
        self.assertIn("max_fallbacks -1", failed)
        self.assertIn("max_cost_usd -1", failed)
        self.assertEqual(report.results[1].checks[0].detail, "fly never executed")
        text = report.render()
        self.assertIn("## Failures", text)
        self.assertIn("| five orders | FAIL |", text)

    def test_many_failures_are_summarised(self):
        suite = load_suite(SUITE)
        for c in suite.cases:
            c.expect = {"max_steps": -1}
        text = run_suite(suite, {"a": "planner", "b": PlanFollowingReasoner()}).render()
        self.assertIn("and 5 more", text)

    def test_consistency_of_a_random_model(self):
        rng = random.Random(7)

        def pick(system, prompt, schema):
            return {"action": rng.choice(schema["properties"]["action"]["enum"]), "rationale": "random"}

        suite = load_suite(SUITE)
        suite.cases = suite.cases[:1]
        report = run_suite(suite, {"random": lambda: LLMReasoner(FunctionChatModel(pick), cache_size=0)}, repeats=3)
        m = report.summary()["random"]
        self.assertEqual(m["runs"], 3)
        self.assertEqual(m["pass_rate"], 1.0)  # governance keeps every random choice compliant
        self.assertLess(m["consistency"], 1.0)  # but the paths differ between attempts

    def test_make_reasoner(self):
        with self.assertRaises(TypeError):
            _make_reasoner(42, Path("."))
        r = PlanFollowingReasoner()
        self.assertIs(_make_reasoner(r, Path(".")), r)

    def test_check_without_expectations(self):
        result = SimpleNamespace(steps=[], status="completed", escalation=None, state=None)
        self.assertEqual(check({}, result, {}), [])
        broken = check({"final": ["Order.amount > 1"]}, result, {})[0]  # no state to evaluate on
        self.assertEqual((broken.passed, broken.detail.split(":")[0]), (False, "AttributeError"))
        self.assertTrue(Check("x", True).passed)


class EvalCliTests(unittest.TestCase):
    def tearDown(self):
        for p in EX.glob("_tmp_suite_*.json"):
            p.unlink()

    def test_cli(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli(["eval", str(SUITE), "--reasoner", "planner=planner", "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["summary"]["planner"]["pass_rate"], 1.0)
        path = write_suite(cases=[{"id": "x", "case_file": "case.json", "expect": {"max_steps": 1}}])
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(cli(["eval", str(path), "--reasoner", "p=planner", "--min-pass", "0.9"]), 5)
        self.assertIn("pass rate below 0.9", err.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli(["eval", str(path), "--reasoner", "p=planner", "--min-pass", "0"]), 0)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli(["eval", str(write_suite(goal="ghost"))]), 1)


if __name__ == "__main__":
    unittest.main()
