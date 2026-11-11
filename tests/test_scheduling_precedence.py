"""Review item 11: precedence through jobs that have no tasks."""

import unittest

from autology.scheduling import Job, ListScheduler, Problem, Task


class EmptyJobTests(unittest.TestCase):
    """A -> B (no tasks) -> C: C must still wait for A."""

    def problem(self):
        tasks = {"A1": Task("A1", "A", 0, 5, [("M1",)]), "C1": Task("C1", "C", 0, 3, [("M2",)])}
        jobs = {"A": Job("A", ["A1"]), "B": Job("B", [], after=["A"]), "C": Job("C", ["C1"], after=["B"])}
        return Problem(jobs, tasks)

    def test_list_scheduler_keeps_the_chain(self):
        sched = ListScheduler(iterations=5).solve(self.problem(), time_limit=10)
        self.assertGreaterEqual(sched.assignments["C1"].start, sched.assignments["A1"].end)

    def test_cp_sat_keeps_the_chain(self):
        try:
            from autology.scheduling import CpSatSolver
            import ortools  # noqa: F401
        except ImportError:
            self.skipTest("OR-Tools not installed")
        sched = CpSatSolver().solve(self.problem(), time_limit=10)
        self.assertGreaterEqual(sched.assignments["C1"].start, sched.assignments["A1"].end)

    def test_lower_bound_counts_the_chain(self):
        self.assertEqual(self.problem().lower_bound(), 8)

    def test_validation_catches_a_broken_chain(self):
        from autology.scheduling import Assignment, Schedule, precedence_violations

        bad = Schedule("feasible", 5, {"A1": Assignment("A1", "A", 0, 5, ["M1"]),
                                       "C1": Assignment("C1", "C", 0, 3, ["M2"])}, "test")
        problems = precedence_violations(self.problem(), bad)
        self.assertEqual(len(problems), 1)
        self.assertIn("C", problems[0])
        self.assertIn("A", problems[0])


if __name__ == "__main__":
    unittest.main()
