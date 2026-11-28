"""Review item 12: applying an event honours the impact rule's condition, as analysing it does."""

import json
import unittest

from autology import Ontology
from autology.graph import KnowledgeGraph
from autology.impact import ImpactAgent

from .helpers import ROOT

SCHED = ROOT / "examples" / "scheduling"


def plant(when):
    def plain(x):
        if hasattr(x, "items"):
            return {k: plain(v) for k, v in x.items()}
        return [plain(v) for v in x] if isinstance(x, (list, tuple)) else x

    doc = plain(Ontology.load(SCHED / "ontology.json").source)
    # the composed document; restrict IMP-ALERT to breakdowns
    for rule in doc["impact_rules"]:
        if rule["id"] == "IMP-ALERT":
            rule["when"] = when
    onto = Ontology.from_dict(doc)
    return onto, KnowledgeGraph.from_dict(onto, json.loads((SCHED / "data.json").read_text()))


class ApplyEventTests(unittest.TestCase):
    def test_condition_that_does_not_hold_changes_nothing(self):
        onto, graph = plant("MachineAlert.code == 'BREAKDOWN'")
        graph.get("ALERT-05").attributes["code"] = "INFO"  # a notice, not a breakdown
        agent = ImpactAgent(onto, graph)
        self.assertEqual(agent.apply_event("ALERT-05"), [])
        self.assertEqual(graph.get("EQ_05").attributes["status"], "available")
        self.assertEqual(agent.analyze("ALERT-05").rule_ids, [])  # analyze agrees

    def test_condition_that_holds_applies(self):
        onto, graph = plant("MachineAlert.code == 'BREAKDOWN'")
        self.assertEqual(ImpactAgent(onto, graph).apply_event("ALERT-05"), ["EQ_05"])
        self.assertEqual(graph.get("EQ_05").attributes["status"], "down")


if __name__ == "__main__":
    unittest.main()
