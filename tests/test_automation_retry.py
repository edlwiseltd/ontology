"""Automations: a firing that errors is retried after a wait, a limited number of times, then gives up."""

import json
import unittest

from autology import Ontology
from autology.automation import Automation, Automator, Firing, load_automations
from autology.expressions import compile_expression
from autology.graph import KnowledgeGraph
from autology.store import Store

from .test_platform import EX


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(EX / "ontology.json")
        self.graph = KnowledgeGraph.from_dict(self.onto, json.loads((EX / "data.json").read_text()))
        self.store = Store(":memory:")
        self.now = 1000.0
        self.calls = []
        self.broken = True
        auto = Automation("big", "Order", compile_expression("Order.amount > 10000"), retry_seconds=60, max_retries=3)

        def fire(a, inst, trigger):
            self.calls.append((inst.id, self.now))
            if self.broken:
                raise RuntimeError("downstream system down")
            return Firing(a.name, inst.id, trigger)

        self.engine = Automator({"big": auto}, self.store, lambda e: self.graph.instances(e), fire,
                                clock=lambda: self.now)

    def test_errors_are_retried_after_the_wait(self):
        with self.assertLogs("autology.automation", "ERROR"):
            self.engine.on_change(["O-3"])
        self.assertEqual(len(self.calls), 1)
        self.engine.tick()  # within the wait: no retry
        self.assertEqual(len(self.calls), 1)
        self.now += 61
        self.broken = False
        self.engine.tick()  # the condition still holds: retried, and this time it works
        self.assertEqual(len(self.calls), 2)
        self.now += 1000
        self.engine.tick()  # done: fires once only, as before
        self.assertEqual(len(self.calls), 2)

    def test_gives_up_after_max_retries(self):
        with self.assertLogs("autology.automation", "WARNING") as logs:
            for _ in range(6):
                self.engine.tick()
                self.now += 61
        self.assertEqual(len(self.calls), 3)  # max_retries attempts in all, then no more
        self.assertIn("giving up", "\n".join(logs.output))
        statuses = [f["status"] for f in self.store.list_firings("big")]
        self.assertIn("gave_up", statuses)

    def test_config(self):
        autos = load_automations({"a": {"entity": "Order", "notify": {"roles": ["x"]},
                                        "retry": {"after": 30, "max": 2}}}, self.onto, {})
        self.assertEqual((autos["a"].retry_seconds, autos["a"].max_retries), (30, 2))
        default = load_automations({"a": {"entity": "Order", "notify": {"roles": ["x"]}}}, self.onto, {})
        self.assertEqual((default["a"].retry_seconds, default["a"].max_retries), (300, 5))
        with self.assertRaises(Exception):
            load_automations({"a": {"entity": "Order", "notify": {"roles": ["x"]}, "retry": {"max": 0}}},
                             self.onto, {})


if __name__ == "__main__":
    unittest.main()
