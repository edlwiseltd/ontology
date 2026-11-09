"""Readiness scorecard."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

from autology import AutoApprover, Ontology, WorkAgent
from autology.__main__ import main as cli
from autology.graph import KnowledgeGraph
from autology.scoring import GRADES, _linear, score_deployment, score_ontology

from .helpers import MFG, MFG_ONTOLOGY, ONTOLOGY_PATH, load_doc, manufacturing_tools as mt, order_case, \
    supplier_case


def all_tools():
    from autology import ToolRegistry

    merged = ToolRegistry()
    for reg in (mt.procurement_tools(), mt.finance_tools(), mt.production_tools(), mt.quality_tools()):
        for t in reg:
            merged.register(t.name, t.capability, t.handler, cost=t.cost)
    return merged


def clean_runs(onto, n=12):
    out = []
    for i in range(n):
        finance = WorkAgent("finance-agent", onto, mt.finance_tools(), roles=["finance"])
        agent = WorkAgent("procurement-agent", onto, mt.procurement_tools(), roles=["procurement"],
                          delegates=[finance], approver=AutoApprover())
        out.append(agent.run("contract_supplier", supplier_case(late_delivery_penalty=i % 4 != 0)))
    return out


def troubled_runs(onto):
    runs = []
    for faults in (mt.Faults(partial_delivery=True), mt.Faults(mes_down=9), mt.Faults()):
        agent = WorkAgent("production-agent", onto, mt.production_tools(faults), roles=["production"],
                          approver=AutoApprover(), max_inline_wait=1e9, sleep=lambda s: None)
        runs.append(agent.run("fulfil_order", order_case()))
    solo = WorkAgent("procurement-agent", onto, mt.procurement_tools(), roles=["procurement"], approver=AutoApprover())
    runs.append(solo.run("contract_supplier", supplier_case()))
    return runs


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(MFG_ONTOLOGY)
        self.graph = KnowledgeGraph.from_dict(self.onto, json.loads((MFG / "data.json").read_text()))

    def test_ontology_only_excludes_unassessed_evidence(self):
        card = score_ontology(self.onto)
        agent = next(p for p in card.pillars if p.name == "Agent performance")
        self.assertIsNone(agent.score)
        self.assertLess(card.coverage, 0.5)
        onto_p, gov_p = card.pillars[0], card.pillars[2]
        expected = (onto_p.score * onto_p.weight + gov_p.score * gov_p.weight) / (onto_p.weight + gov_p.weight)
        self.assertAlmostEqual(card.overall, round(expected, 1), places=1)
        self.assertTrue(any("not assessed yet" in r for r in card.recommendations()))

    def test_clean_deployment_scores_high_and_reports_gates(self):
        card = score_deployment(self.onto, clean_runs(self.onto), tools=all_tools(), graph=self.graph,
                                cost_budget=200, roi=3.0, tasks_per_month=1500)
        self.assertEqual(card.coverage, 0.95)  # no tool failures happened, so self-healing is not assessed
        healing = next(c for c in card.pillars[1].criteria if c.name == "Self-healing")
        self.assertFalse(healing.assessed)
        self.assertGreaterEqual(card.overall, 90)
        self.assertEqual(card.grade, "A")
        gates = {(g.phase, g.criterion): g.passed for g in card.gates}
        self.assertTrue(gates[("Pilot", "Agent success rate")])
        self.assertTrue(gates[("Pilot", "ROI")])
        self.assertTrue(gates[("Pilot", "Ontology scope")])  # 7 entities, 10 rules
        self.assertTrue(all(g.passed for g in card.gates if g.phase == "Pilot"))
        self.assertIn("Pilot gate passed - scale gate failing: Ontology scope, Agents in operation, Tasks per month",
                      card.phase_reached)
        self.assertIn("[Scale gate] Tasks per month is 1,500; target > 10,000", "\n".join(card.recommendations()))
        low_roi = score_deployment(self.onto, clean_runs(self.onto, 3), roi=1.4)
        self.assertIn("pilot gate not passed (failing: ROI", low_roi.phase_reached)

    def test_troubled_deployment_scores_lower_with_actionable_advice(self):
        clean = score_deployment(self.onto, clean_runs(self.onto), tools=all_tools(), graph=self.graph)
        bad = score_deployment(self.onto, troubled_runs(self.onto), tools=all_tools(), graph=self.graph)
        self.assertLess(bad.overall, clean.overall - 15)
        agent = next(p for p in bad.pillars if p.name == "Agent performance")
        self.assertLess(agent.score, 60)
        recs = "\n".join(bad.recommendations())
        self.assertIn("partial_delivery", recs)
        self.assertIn("raise resolution", bad.recommendations()[0])

    def test_recommendations_ranked_and_unique(self):
        card = score_deployment(self.onto, troubled_runs(self.onto), tools=all_tools())
        recs = card.recommendations()
        self.assertEqual(len(recs), len(set(recs)))
        impacts = [float(r.rsplit("(+", 1)[1].split()[0]) for r in recs if "(+" in r]
        self.assertEqual(impacts, sorted(impacts, reverse=True))

    def test_security_coverage_drops_when_pii_unguarded(self):
        doc = load_doc()
        guarded = score_ontology(Ontology.from_dict(doc)).pillars[0]
        doc["rules"] = [r for r in doc["rules"] if r["id"] != "R-PII-001"]
        unguarded = score_ontology(Ontology.from_dict(doc)).pillars[0]
        sec = lambda p: next(c for c in p.criteria if c.name == "Security by design")  # noqa: E731
        self.assertEqual(sec(guarded).earned, 20)
        self.assertEqual(sec(unguarded).earned, 10)  # Contact.email still guarded, Customer.tax_id not
        self.assertIn("Customer.tax_id", sec(unguarded).recommendation)

    def test_render_and_dict(self):
        card = score_deployment(self.onto, clean_runs(self.onto, 3), tools=all_tools())
        text = card.render()
        for heading in ("## Ontology quality", "## Agent performance", "## Governance", "## Phase gates"):
            self.assertIn(heading, text)
        data = card.as_dict()
        json.dumps(data, default=str)
        self.assertEqual(data["grade"], card.grade)

    def test_helpers(self):
        self.assertEqual(_linear(0.9, 0.5, 0.9), 1.0)
        self.assertEqual(_linear(0.5, 0.5, 0.9), 0.0)
        self.assertAlmostEqual(_linear(0.3, 0.5, 0.1), 0.5)  # lower is better
        self.assertEqual([g for _, g in GRADES], ["A", "B", "C", "D", "F"])

    def test_cli_gate(self):
        doc = load_doc()
        doc.pop("competency_questions")
        doc.pop("settings")
        weak = Path(tempfile.mkdtemp()) / "weak.json"
        weak.write_text(json.dumps(doc))
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            low = cli(["score", str(weak), "--min-score", "90"])
            ok = cli(["score", str(MFG_ONTOLOGY), "--data", str(MFG / "data.json"), "--min-score", "90"])
            cli(["score", str(MFG_ONTOLOGY), "--json"])
        self.assertEqual((low, ok), (4, 0))
        self.assertIn('"grade": "A"', out.getvalue())


if __name__ == "__main__":
    unittest.main()
