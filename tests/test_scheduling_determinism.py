"""Review item 10: deterministic list scheduling, and an honest reason for stopping."""

import json
import os
import subprocess
import sys
import unittest

from autology import Ontology
from autology.graph import KnowledgeGraph
from autology.scheduling import ListScheduler, build_problem

from .helpers import ROOT

SCHED = ROOT / "examples" / "scheduling"
PROBE = """
import json, sys
sys.path.insert(0, {root!r})
from autology import Ontology
from autology.graph import KnowledgeGraph
from autology.scheduling import ListScheduler, build_problem
onto = Ontology.load({onto!r})
graph = KnowledgeGraph.from_dict(onto, json.load(open({data!r})))
problem = build_problem(onto, graph)
sched = ListScheduler(iterations=25).solve(problem, time_limit=1000)
print(json.dumps({{t: [a.start, a.resources] for t, a in sorted(sched.assignments.items())}}, sort_keys=True))
"""


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_schedule_in_every_process(self):
        code = PROBE.format(root=str(ROOT), onto=str(SCHED / "ontology.json"), data=str(SCHED / "data.json"))
        outputs = set()
        for seed in ("1", "2", "3"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=300)
            self.assertEqual(out.returncode, 0, out.stderr)
            outputs.add(out.stdout)
        self.assertEqual(len(outputs), 1)

    def test_stop_reason_is_reported(self):
        onto = Ontology.load(SCHED / "ontology.json")
        graph = KnowledgeGraph.from_dict(onto, json.loads((SCHED / "data.json").read_text()))
        problem = build_problem(onto, graph)
        timed = ListScheduler(iterations=10_000).solve(problem, time_limit=0.0)
        self.assertEqual(timed.stopped, "time_limit")
        self.assertIn("time limit", timed.note)
        self.assertEqual(timed.as_dict()["stopped"], "time_limit")
        done = ListScheduler(iterations=2).solve(problem, time_limit=1000)
        self.assertIn(done.stopped, ("iterations", "lower_bound"))
        if done.status != "optimal":
            self.assertEqual(done.stopped, "iterations")
            self.assertIn("2 passes", done.note)


if __name__ == "__main__":
    unittest.main()
