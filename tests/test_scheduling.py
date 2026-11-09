"""Ontology + dual-agent scheduling: ImpactAgent, ScheduleAgent, solvers, validation, governed replanning."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from autology import AutoApprover, Ontology, OntologyError, Proposal, WorkAgent
from autology.graph import KnowledgeGraph
from autology.impact import ImpactAgent
from autology.ontology import load_document
from autology.scheduling import (Assignment, Job, ListScheduler, Problem, Schedule, ScheduleAgent, Task, build_problem,
                                 clone_job, default_solver, gantt_html, gantt_text, scheduling_tools, validate_schedule)

from .helpers import ROOT

EX = ROOT / "examples" / "scheduling"
ONTO = EX / "ontology.json"
DATA = json.loads((EX / "data.json").read_text())

try:
    from autology.scheduling import CpSatSolver

    CpSatSolver()
    HAVE_ORTOOLS = True
except ImportError:
    HAVE_ORTOOLS = False


def fresh():
    onto = Ontology.load(ONTO)
    return onto, KnowledgeGraph.from_dict(onto, copy.deepcopy(DATA))


def tiny_problem():
    """2 jobs x 2 tasks on 2 machines: optimum makespan 7 (lower bound 7)."""
    tasks = {"A1": Task("A1", "A", 10, 3, [("M1",)]), "A2": Task("A2", "A", 20, 2, [("M2",)]),
             "B1": Task("B1", "B", 10, 2, [("M2",)]), "B2": Task("B2", "B", 20, 4, [("M1",)])}
    jobs = {"A": Job("A", ["A1", "A2"]), "B": Job("B", ["B1", "B2"])}
    return Problem(jobs, tasks)


class OntologySectionTests(unittest.TestCase):
    def test_example_has_both_sections(self):
        onto = Ontology.load(ONTO)
        self.assertEqual({r.id for r in onto.impact_rules}, {"IMP-ECN", "IMP-MACHINE", "IMP-ALERT", "IMP-MOLD",
                                                            "IMP-RETURN"})
        self.assertEqual(onto.scheduling.resource_types(onto), ("Machine", "Mold", "Operator"))
        self.assertEqual(onto.scheduling.context_types(onto), ("Material", "Part"))

    def test_invalid_sections(self):
        def bad(mutate):
            doc = load_document(ONTO)
            mutate(doc)
            return doc

        sch = lambda d: d["scheduling"]  # noqa: E731
        imp = lambda d: d["impact_rules"][0]  # noqa: E731
        cases = {
            "unknown event": lambda d: imp(d).update(event="Comet"),
            "bad path": lambda d: imp(d).update(paths=["changes.flies"]),
            "no paths": lambda d: imp(d).update(paths=[]),
            "bad adjust key": lambda d: imp(d).update(adjust={"speed": "ECN.duration_factor"}),
            "adjust other entity": lambda d: imp(d).update(adjust={"release": "Part.revision"}),
            "apply bad state": lambda d: imp(d).update(apply=[{"path": "changes", "set": {"status": "melted"}}]),
            "duplicate rule": lambda d: d["impact_rules"].append(dict(imp(d))),
            "job_tasks": lambda d: sch(d).update(job_tasks="produces"),
            "precedence": lambda d: sch(d).update(job_precedence="produces"),
            "no resources": lambda d: sch(d).update(resources=[]),
            "availability": lambda d: sch(d)["availability"].update(Part="Part.status == 'released'"),
            "check entity": lambda d: sch(d)["checks"].append({"id": "X", "when": "ECN.duration_factor > 1"}),
            "slot attr": lambda d: sch(d)["checks"].append({"id": "X", "when": "Slot.colour == 1"}),
            "severity": lambda d: sch(d)["checks"].append({"id": "X", "when": "Slot.end > 1", "severity": "meh"}),
            "dup check": lambda d: sch(d)["checks"].append(dict(sch(d)["checks"][0])),
            "context": lambda d: sch(d).update(context=["nope"]),
        }
        for label, mutate in cases.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                Ontology.from_dict(bad(mutate))


class ImpactAgentTests(unittest.TestCase):
    def test_ecn_impact_with_reasoning_chains(self):
        onto, graph = fresh()
        report = ImpactAgent(onto, graph).analyze("ECN-7")
        self.assertEqual(report.rule_ids, ["IMP-ECN"])
        self.assertEqual((report.count("Part"), report.count("WorkOrder"), report.count("Process")), (4, 13, 36))
        self.assertEqual(report.explain("EQ_05"),
                         "ECN-7 -changes-> PT-02 <-produces- WO-02 -hasProcess-> WO-02/20 -requiresMachine-> EQ_05")
        self.assertEqual(graph.get("PT-02").get("status"), "under_change")  # event applied
        adj = report.adjustments["WO-02/10"]
        self.assertEqual(adj, {"duration_factor": 1.25, "release": 6.0})
        self.assertIn("OP_07", report.unavailable)  # absent heat-treat operator on an affected process
        self.assertTrue(all(r.severity == "warning" for r in report.risks))
        self.assertIn("not affected", report.explain("WO-99"))
        self.assertIn("4 Part, 13 WorkOrder", report.summary(onto))

    def test_breakdown_alert_takes_machine_down(self):
        onto, graph = fresh()
        report = ImpactAgent(onto, graph).analyze("ALERT-11")  # the only heat-treat furnace
        self.assertEqual(graph.get("EQ_11").get("status"), "down")
        self.assertIn("EQ_11", report.unavailable)
        self.assertTrue(report.risks and all(r.severity == "critical" or "OP_07" in r.message for r in report.risks))
        self.assertTrue(any("no alternative" in r.message for r in report.risks))

    def test_conditional_rules_and_errors(self):
        onto, graph = fresh()
        self.assertEqual(ImpactAgent(onto, graph).analyze("EQ_01").rule_ids, [])  # machine is available
        self.assertEqual(ImpactAgent(onto, graph).analyze("OP_01").affected, {})  # no rule for operators
        with self.assertRaises(OntologyError):
            ImpactAgent(onto, graph).analyze("NOPE")
        dry = ImpactAgent(onto, graph).analyze("ALERT-05", apply=False)
        self.assertNotIn("EQ_05", dry.unavailable)


class ProblemAndSolverTests(unittest.TestCase):
    def test_build_problem_applies_constraints(self):
        onto, graph = fresh()
        base = build_problem(onto, graph)
        self.assertEqual((len(base.jobs), len(base.tasks)), (40, 101))
        self.assertIn("OP_07", base.excluded_resources)
        self.assertEqual(base.jobs["WO-01"].after, ["WO-03"])  # WO-03 feeds WO-01: WO-01 waits for it
        self.assertEqual(base.jobs["WO-03"].after, [])
        report = ImpactAgent(onto, graph).analyze("ECN-7")
        constrained = build_problem(onto, graph, report)
        self.assertEqual(constrained.tasks["WO-02/10"].release, 6)
        self.assertGreater(constrained.tasks["WO-02/10"].duration, base.tasks["WO-02/10"].duration)
        self.assertEqual(constrained.tasks["WO-01/10"].release, 0)  # not affected by ECN-7
        down = build_problem(onto, graph, ImpactAgent(onto, graph).analyze("ALERT-05"))
        self.assertFalse(any("EQ_05" in g for t in down.tasks.values() for g in t.groups))
        self.assertIn("EQ_05", down.excluded_resources)

    def test_holds_cascade_along_precedence(self):
        onto, graph = fresh()
        report = ImpactAgent(onto, graph).analyze("ALERT-11")
        problem = build_problem(onto, graph, report)
        self.assertTrue(problem.on_hold)
        heat_jobs = {j for j, reason in problem.on_hold.items() if "requiresMachine" in reason}
        self.assertTrue(heat_jobs)
        for job in problem.jobs.values():
            self.assertFalse(set(job.after) & set(problem.on_hold))

    def test_list_scheduler_is_valid_and_honest(self):
        onto, graph = fresh()
        problem = build_problem(onto, graph)
        schedule = ListScheduler(iterations=40).solve(problem, 5)
        self.assertIn(schedule.status, ("optimal", "feasible"))
        self.assertGreaterEqual(schedule.makespan, schedule.lower_bound)
        self.assertEqual(schedule.status == "optimal", schedule.makespan == schedule.lower_bound)
        invariants = [w for w in validate_schedule(onto, graph, problem, schedule) if w.check.startswith("INV")]
        self.assertEqual(invariants, [])
        again = ListScheduler(iterations=40).solve(problem, 5)
        self.assertEqual(again.makespan, schedule.makespan)  # seeded: reproducible

    def test_tiny_problem_proven_optimal(self):
        schedule = ListScheduler().solve(tiny_problem())
        self.assertEqual((schedule.makespan, schedule.lower_bound, schedule.status), (7, 7, "optimal"))
        self.assertEqual(schedule.gap, 0.0)

    @unittest.skipUnless(HAVE_ORTOOLS, "OR-Tools not installed")
    def test_cp_sat_matches_or_beats_heuristic(self):
        onto, graph = fresh()
        problem = build_problem(onto, graph, ImpactAgent(onto, graph).analyze("ECN-7"))
        exact = CpSatSolver().solve(problem, 20)
        heuristic = ListScheduler(iterations=40).solve(problem, 5)
        self.assertIn(exact.status, ("optimal", "feasible"))
        self.assertLessEqual(exact.makespan, heuristic.makespan)
        self.assertGreaterEqual(exact.makespan, problem.lower_bound())
        self.assertEqual([w for w in validate_schedule(onto, graph, problem, exact) if w.check.startswith("INV")], [])
        tiny = CpSatSolver().solve(tiny_problem(), 5)
        self.assertEqual((tiny.status, tiny.makespan), ("optimal", 7))

    @unittest.skipUnless(HAVE_ORTOOLS, "OR-Tools not installed")
    def test_cp_sat_lexicographic_lateness(self):
        onto, graph = fresh()
        problem = build_problem(onto, graph, ImpactAgent(onto, graph).analyze("ECN-7"))
        plain = CpSatSolver(tardiness=False).solve(problem, 20)
        lexi = CpSatSolver().solve(problem, 20)
        self.assertEqual(lexi.makespan, plain.makespan)  # same makespan ...
        self.assertLessEqual(sum(lexi.tardiness(problem).values()), sum(plain.tardiness(problem).values()))
        self.assertIn("total lateness", lexi.note)  # ... and lateness minimised at that makespan

    def test_default_solver(self):
        self.assertIsInstance(default_solver("builtin"), ListScheduler)
        self.assertEqual(type(default_solver()).__name__, "CpSatSolver" if HAVE_ORTOOLS else "ListScheduler")
        if not HAVE_ORTOOLS:
            with self.assertRaises(ImportError):
                default_solver("cp-sat")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.onto, self.graph = fresh()
        self.problem = build_problem(self.onto, self.graph)
        self.schedule = ListScheduler(iterations=10).solve(self.problem, 2)

    def test_semantic_checks_fire(self):
        found = {w.check for w in validate_schedule(self.onto, self.graph, self.problem, self.schedule)}
        self.assertIn("CHK-CALIBRATION", found)  # EQ_12 calibration expires at 60h
        self.graph.get("MAT-TI64").attributes["on_hand_kg"] = 10
        self.graph.get("OP_10").attributes["cert_expires_h"] = 1
        found = validate_schedule(self.onto, self.graph, self.problem, self.schedule)
        checks = {w.check for w in found}
        self.assertTrue({"CHK-MATERIAL", "CHK-CERTIFICATION"} <= checks)
        msg = next(w.message for w in found if w.check == "CHK-MATERIAL")
        self.assertRegex(msg, r"only 10 kg on hand")

    def test_invariants_catch_a_broken_solver(self):
        broken = copy.deepcopy(self.schedule)
        a, b = list(broken.assignments.values())[:2]
        same = [x for x in broken.assignments.values() if x.resources[0] == a.resources[0] and x.task != a.task][0]
        same.start, same.end = a.start, a.end
        first_two = self.problem.jobs["WO-01"].tasks[:2]
        broken.assignments[first_two[1]].start = broken.assignments[first_two[0]].start
        checks = {w.check for w in validate_schedule(self.onto, self.graph, self.problem, broken)}
        self.assertTrue({"INV-OVERLAP", "INV-SEQUENCE"} <= checks)
        del broken.assignments[first_two[0]]
        self.assertIn("INV-MISSING", {w.check for w in validate_schedule(self.onto, self.graph, self.problem, broken)})
        none = Schedule("infeasible", None, {}, "x")
        self.assertEqual(validate_schedule(self.onto, self.graph, self.problem, none)[0].check, "SOLVER")
        self.graph.get("EQ_01").attributes["status"] = "down"
        self.assertIn("INV-AVAILABILITY", {w.check for w in validate_schedule(self.onto, self.graph, self.problem,
                                                                             self.schedule)})

    def test_rework_inherits_routing_and_rendering(self):
        job = clone_job(self.onto, self.graph, "WO-04", "WO-04-RW", from_seq=20, link=("reworks", "WO-04"))
        tasks = self.graph.neighbours(job, "hasProcess")
        self.assertEqual([t.id for t in tasks], ["WO-04-RW/20", "WO-04-RW/30"])
        self.assertEqual({m.id for m in self.graph.neighbours(tasks[0], "requiresMachine")}, {"EQ_11"})
        self.assertEqual(self.graph.neighbours(job, "produces")[0].id, "PT-04")
        agent = ScheduleAgent(self.onto, self.graph, ListScheduler(iterations=5))
        result = agent.replan("QR-1", baseline=self.schedule)
        self.assertIn("WO-04-RW", result.problem.jobs)
        self.assertIsInstance(result.delays, dict)
        self.assertGreaterEqual(result.critical, 0)
        self.assertIn("EQ_11", gantt_text(result.schedule, result.problem))
        page = gantt_html(result, "after QR-1")
        self.assertIn("<svg", page)
        self.assertIn("prefers-color-scheme", page)
        json.dumps(result.as_dict(), default=str)
        self.assertEqual(gantt_text(Schedule("infeasible", None, {}, "x"), result.problem), "(empty schedule)")


class GovernedReplanningTests(unittest.TestCase):
    def agent(self, out_dir, **kw):
        onto = Ontology.load(ONTO)
        tools = scheduling_tools(str(ONTO), str(EX / "data.json"), solver="builtin", time_limit=2, out_dir=out_dir,
                                 rework={"event": "QualityReturn", "source": "returnOf", "link": "reworks",
                                         "from_seq": "from_seq"})
        kw.setdefault("approver", AutoApprover({"publish_to_mes": lambda r: "Replan" in r.view}, default=False))
        return onto, WorkAgent("scheduler-agent", onto, tools, roles=["scheduler"], **kw)

    def test_full_loop_publishes_schedule_and_gantt(self):
        out = tempfile.mkdtemp()
        _, agent = self.agent(out)
        result = agent.run("replan_after_event", {"Replan": {"event_id": "ECN-7"}}, "ECN-7")
        self.assertTrue(result.completed, result.escalation)
        self.assertEqual([s.action for s in result.steps],
                         ["analyze_impact", "optimize_schedule", "validate_schedule", "publish_to_mes"])
        self.assertEqual(result.steps[-1].verdict, "review")  # 15h delay -> planner review (R-SCH-003)
        saved = json.loads((Path(out) / "schedule-ECN-7.json").read_text())
        self.assertEqual(saved["impact"]["affected"]["Part"], ["PT-02", "PT-05", "PT-07", "PT-11"])
        self.assertTrue((Path(out) / "schedule-ECN-7.html").exists())

    def test_on_hold_jobs_block_publication(self):
        approver = AutoApprover({"publish_to_mes": lambda r: False})
        _, agent = self.agent(tempfile.mkdtemp(), approver=approver)
        result = agent.run("replan_after_event", {"Replan": {"event_id": "ALERT-11"}}, "furnace")
        self.assertEqual(result.status, "blocked")
        self.assertGreater(result.state.get("Replan", "jobs_on_hold"), 0)
        self.assertEqual(approver.requests[0].rule_ids, ["R-SCH-003"])

    def test_cannot_publish_unvalidated_or_without_role(self):
        class Rogue:
            def propose(self, ctx):
                return Proposal("publish_to_mes", "ship it", "rogue")

        _, agent = self.agent(tempfile.mkdtemp(), reasoner=Rogue())
        result = agent.run("replan_after_event", {"Replan": {"event_id": "ECN-8"}}, "rogue")
        self.assertEqual(result.status, "suspended")  # max_violations = 3
        self.assertNotIn("publish_to_mes:done", result.path)
        onto, _ = self.agent(None)
        planner = WorkAgent("planner", onto, scheduling_tools(str(ONTO), str(EX / "data.json"), solver="builtin"),
                            roles=["planner"], approver=AutoApprover())
        res = planner.run("replan_after_event", {"Replan": {"event_id": "ECN-8"}})
        self.assertEqual(res.status, "escalated")  # planners may analyse but not optimise or publish
        self.assertTrue(any("R-SCH-007" in d or "may not execute optimize_schedule" in d
                            for d in res.escalation.details))

    def test_tool_errors(self):
        tools = scheduling_tools(str(ONTO), str(EX / "data.json"), solver="builtin")
        by_cap = {t.capability: t for t in tools}
        from autology.tools import ToolCall, ToolError

        call = lambda cap, ev: by_cap[cap].handler(ToolCall("x", cap, {"Replan.event_id": ev}, {}, 1))  # noqa: E731
        for cap in ("scheduling.solve", "scheduling.validate", "scheduling.publish"):
            with self.subTest(cap), self.assertRaises(ToolError):
                call(cap, "ECN-7")  # steps out of order
        with self.assertRaises(ToolError):
            call("scheduling.impact", None)
        with self.assertRaises(ToolError):
            call("scheduling.impact", "NOPE")


if __name__ == "__main__":
    unittest.main()


class SparqlEquivalenceTests(unittest.TestCase):
    def test_graph_export(self):
        from autology.export import graph_to_turtle

        onto, graph = fresh()
        ttl = graph_to_turtle(graph)
        self.assertIn(":i_ECN_7 :changes :i_PT_02 .", ttl)
        self.assertIn(":Machine_status :Machine_available", ttl)

    def test_impact_paths_equal_sparql_property_paths(self):
        try:
            import rdflib
        except ImportError:
            self.skipTest("rdflib not installed")
        from autology.export import graph_to_turtle, to_turtle

        onto, graph = fresh()
        g = rdflib.Graph()
        g.parse(data=to_turtle(onto) + graph_to_turtle(graph), format="turtle")
        base = f"https://autology.dev/ontology/{onto.name}/{onto.version}#"
        rows = g.query(f"PREFIX : <{base}> SELECT DISTINCT ?id WHERE {{ :i_ECN_7 :changes/^:produces ?wo . ?wo :id ?id }}")
        sparql = sorted(str(r[0]) for r in rows)
        self.assertEqual(sparql, sorted(ImpactAgent(onto, graph).analyze("ECN-7").affected["WorkOrder"]))
