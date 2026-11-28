"""Regression gate: every example deployment, run end to end through the generic CLI, scores >= 95.

The examples use four unrelated domains (B2B onboarding, manufacturing procurement, healthcare
referrals, event-driven production scheduling) and no example-specific glue: an ontology, a tool config, an approval policy, cases and a
TCO model. The care-referral example has no Python at all - its systems are decision tables.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from autology.__main__ import main as cli
from autology.adapters import load_tools
from autology.tools import ToolCall, ToolError

from .helpers import ROOT

EX = ROOT / "examples"

DEPLOYMENTS = {
    "customer_onboarding": dict(
        ontology="ontology.json", goal="onboard_customer", tools="tools_pilot.json", score_tools="tools.json",
        run=["--roles", "sales,kyc"], budget="25", tco="tco.json"),
    "manufacturing": dict(
        ontology="enterprise.json", goal="contract_supplier", tools="tools_pilot.json", score_tools="all_tools.json",
        run=["--roles", "procurement", "--delegate", "finance-agent:finance:{dir}/finance_tools.json"],
        budget="50", tco="roi.json"),
    "care_referral": dict(
        ontology="ontology.json", goal="start_treatment", tools="tools_pilot.json", score_tools="all_tools.json",
        run=["--name", "care-coordinator", "--roles", "clinical", "--delegate",
             "booking-agent:admin:{dir}/admin_tools.json"], budget="25", tco="tco.json"),
    "scheduling": dict(
        ontology="ontology.json", goal="replan_after_event", tools="tools_pilot.json", score_tools="tools_pilot.json",
        run=["--name", "scheduler-agent", "--roles", "scheduler"], budget="1", tco="tco.json"),
}


def run_cli(*args):
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
        code = cli([str(a) for a in args])
    return code, out.getvalue()


class ReadinessTests(unittest.TestCase):
    def test_every_example_scores_at_least_95_with_full_evidence(self):
        for name, cfg in DEPLOYMENTS.items():
            with self.subTest(name):
                d = EX / name
                runs = Path(tempfile.mkdtemp()) / "runs.jsonl"
                extra = [a.format(dir=d) for a in cfg["run"]]
                run_cli("run", d / cfg["ontology"], cfg["goal"], d / "pilot_cases.json", "--tools", d / cfg["tools"],
                        "--approver", d / "approvals.json", "--out", runs, *extra)
                code, out = run_cli("score", d / cfg["ontology"], "--runs", runs, "--tools", d / cfg["score_tools"],
                                    "--data", d / "data.json", "--budget", cfg["budget"], "--tco", d / cfg["tco"],
                                    "--min-score", "95", "--json")
                card = json.loads(out)
                self.assertEqual(code, 0, f"{name} scored {card['overall']}")
                self.assertGreaterEqual(card["overall"], 95)
                self.assertEqual(card["coverage"], 1.0)
                for pillar in card["pillars"].values():
                    self.assertGreaterEqual(pillar["score"], 95)

    def test_decision_table_tools(self):
        reg = load_tools(EX / "care_referral" / "tools_pilot.json")
        triage = next(t for t in reg if t.name == "triage_rules")
        call = lambda inputs, ctx=None: ToolCall("triage", "clinical.triage", inputs, ctx or {}, 1)  # noqa: E731
        self.assertEqual(triage.handler(call({"Patient.age": 80, "Patient.condition": "rash"})).outcome, "urgent")
        self.assertEqual(triage.handler(call({"Patient.age": 30, "Patient.condition": "rash"})).outcome, "routine")
        admit = next(t for t in reg if t.name == "ehr_admit")
        with self.assertRaisesRegex(ToolError, "timeout"):
            admit.handler(call({"Patient.age": 42}))
        empty = load_tools({"tools": [{"name": "t", "capability": "c", "type": "table",
                                       "rows": [{"when": "Patient.age > 200"}]}]})
        with self.assertRaisesRegex(ToolError, "no decision-table row"):
            next(iter(empty)).handler(call({}, {"Patient": {"age": "***redacted***"}}))


if __name__ == "__main__":
    unittest.main()
