"""Review item 15: running out of search budget is not the same as there being no compliant path."""

import unittest

from autology import AutoApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.governance import GovernanceLayer, Principal
from autology.planner import Planner, SearchBudgetExceeded
from autology.reporting import classify
from autology.state import WorldState

from .test_platform import CASE, EX

ALL = Principal("a", frozenset({"ops", "eu_ops", "finance"}))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(EX / "ontology.json")
        self.state = WorldState.initial(self.onto, CASE)
        self.goal = self.onto.goals["fulfil_contract"]

    def test_planner_reports_budget_exhaustion(self):
        tiny = Planner(self.onto, GovernanceLayer(self.onto), max_expansions=2)
        with self.assertRaises(SearchBudgetExceeded) as cm:
            tiny.plan(self.state, self.goal, ALL)
        self.assertIn("max_expansions", str(cm.exception))
        self.assertIsNotNone(Planner(self.onto, GovernanceLayer(self.onto)).plan(self.state, self.goal, ALL))

    def test_truly_impossible_is_still_none(self):
        ops_only = Principal("o", frozenset({"ops"}))  # nobody may run credit checks
        self.assertIsNone(Planner(self.onto, GovernanceLayer(self.onto)).plan(self.state, self.goal, ops_only))

    def test_agent_escalates_with_the_real_reason(self):
        agent = WorkAgent("a", self.onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops", "finance"],
                          approver=AutoApprover())
        agent.planner.max_expansions = 2
        result = agent.run("fulfil_contract", CASE, "k")
        self.assertEqual(result.status, "escalated")
        self.assertIn("search budget", result.escalation.reason)
        self.assertNotIn("no compliant path", result.escalation.reason)
        self.assertEqual(classify(result), "unplanned")  # not a policy stop


if __name__ == "__main__":
    unittest.main()
