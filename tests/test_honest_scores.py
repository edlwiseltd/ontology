"""Review item 13: scores and reports must not flatter."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from autology import AutoApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.agent import DeferredApprover
from autology.evals import load_suite, run_suite
from autology.reasoners import FunctionChatModel, LLMReasoner
from autology.reporting import classify, compliance_report, metrics
from autology.scoring import score_deployment

from .test_platform import CASE, EX


def agent(**kw):
    onto = Ontology.load(EX / "ontology.json")
    kw.setdefault("roles", ["ops", "eu_ops", "finance"])
    return onto, WorkAgent("a", onto, load_tools(EX / "tools.json"), **kw)


class CostEfficiencyTests(unittest.TestCase):
    def test_nothing_completed_is_not_full_marks(self):
        onto, a = agent(roles=["ops"])  # no finance: every run escalates
        runs = [a.run("fulfil_contract", CASE, f"c{i}") for i in range(3)]
        self.assertFalse(any(r.completed for r in runs))
        m = metrics(runs)
        self.assertIsNone(m.cost_per_completed_task)
        crit = {c.name: c for p in score_deployment(onto, runs, cost_budget=10).pillars for c in p.criteria}
        self.assertEqual(crit["Cost efficiency"].earned, 0)
        self.assertIn("no completed task", crit["Cost efficiency"].detail)
        self.assertIn("n/a", compliance_report(runs, onto))


class HandOffTests(unittest.TestCase):
    def test_parked_and_deferred_runs_are_not_hand_off_free(self):
        onto, a = agent(approver=DeferredApprover())
        parked = a.run("fulfil_contract", CASE, "k")
        self.assertEqual(parked.status, "awaiting_review")
        m = metrics([parked])
        self.assertEqual(m.human_intervention_rate, 1.0)  # a person must act before it can finish
        doc = json.loads((EX / "ontology.json").read_text())
        doc["actions"]["pick_order"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": 3600,
                                                      "fallback_tools": False}
        onto2 = Ontology.from_dict(doc)
        tools = load_tools(EX / "tools.json")

        def down(call):
            from autology import ToolError

            raise ToolError("warehouse system down")

        tools.register("down", onto2.actions["pick_order"].capability, down, priority=99)
        deferred = WorkAgent("a", onto2, tools, roles=["ops", "eu_ops", "finance"],
                             approver=AutoApprover()).run("fulfil_contract", CASE, "d")
        self.assertEqual(deferred.status, "deferred")
        self.assertEqual(classify(deferred), "unplanned")  # a tool failure waiting for a retry
        self.assertEqual(metrics([deferred]).unplanned_handoff_rate, 1.0)


class EvalTests(unittest.TestCase):
    def write(self, expect):
        doc = json.loads((EX / "evals.json").read_text())
        doc["cases"] = [{"id": "x", "case_file": "case.json", "expect": expect}]
        doc["reasoners"] = {"planner": "planner"}
        path = EX / "_tmp_honest_suite.json"
        path.write_text(json.dumps(doc))
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_wrongly_typed_or_empty_expectations_are_rejected(self):
        for expect in [{"excludes": "ship_order"}, {"contains": "credit_check"}, {"order": "a"},
                       {"final": "Contract.status == 'signed'"}, {"contains": []}, {"max_steps": "5"},
                       {"reviews": 1.5}, {"status": 3}]:
            with self.subTest(expect), self.assertRaises(Exception):
                load_suite(self.write(expect))

    def test_a_case_with_no_checks_does_not_pass(self):
        suite = load_suite(self.write({"status": "completed"}))
        suite.cases[0].expect = {}
        result = run_suite(suite).results[0]
        self.assertFalse(result.passed)


class PriceTests(unittest.TestCase):
    def test_unpriced_model_is_not_free(self):
        def choose(system, prompt, schema):
            return {"action": schema["properties"]["action"]["enum"][0], "rationale": "x"}, \
                {"input_tokens": 1000, "output_tokens": 100}

        onto, a = agent(approver=AutoApprover(),
                        reasoner=LLMReasoner(FunctionChatModel(choose, model="mystery-model"), cache_size=0))
        run = a.run("fulfil_contract", CASE, "k")
        self.assertGreater(run.costs["llm_unpriced_tokens"], 0)
        m = metrics([run])
        self.assertGreater(m.llm_unpriced_tokens, 0)
        self.assertIn("no price", compliance_report([run], onto))
        crit = {c.name: c for p in score_deployment(onto, [run], cost_budget=1000).pillars for c in p.criteria}
        self.assertEqual(crit["Cost efficiency"].earned, 0)
        self.assertIn("mystery-model", crit["Cost efficiency"].detail)


class AdherenceTests(unittest.TestCase):
    def test_no_hard_coded_adherence(self):
        onto, a = agent(approver=AutoApprover())
        report = compliance_report([a.run("fulfil_contract", CASE, "k")], onto)
        self.assertNotIn("100%", report.split("## Rule")[1].split("\n\n")[1])
        self.assertNotIn("| Adherence |", report)


if __name__ == "__main__":
    unittest.main()
