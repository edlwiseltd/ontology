"""ScheduleAgent: ontology-driven (flexible) job-shop scheduling.

The ontology's ``scheduling`` section says which entities are jobs (e.g. work
orders), tasks (processes), how tasks are ordered, how long they take, which
resources they need (machines, molds, operators - "one of" or "all of") and
when a resource is available. :func:`build_problem` turns the knowledge graph
into a solver-neutral :class:`Problem`, optionally constrained by an
:class:`~autology.impact.ImpactReport` (unavailable resources, ECN duration
factors, requalification release times).

Solvers (same interface, ``solve(problem, time_limit)``):

* :class:`CpSatSolver` - Google OR-Tools CP-SAT (``pip install ortools``): exact;
  reports ``optimal`` only when optimality is proven within the time limit,
  otherwise ``feasible`` with the solver's lower bound;
* :class:`ListScheduler` - dependency-free multi-start schedule generation with
  a computed lower bound; ``optimal`` only if the makespan meets that bound.

:func:`validate_schedule` then checks the result against the ontology - both the
solver's own constraints (overlaps, sequence, downtime, availability) and the
semantic checks the solver does not model (mold life, operator certification,
calibration due, material...) - and :func:`gantt_text` / :func:`gantt_html` render it.
"""

from __future__ import annotations

import html
import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .graph import Instance, KnowledgeGraph
from .impact import ImpactAgent, ImpactReport
from .ontology import Ontology, OntologyError


# -- problem model ------------------------------------------------------------------
@dataclass
class Task:
    id: str
    job: str
    seq: int
    duration: int
    groups: List[Tuple[str, ...]]  # each group: alternative resources; one per group is used
    release: int = 0


@dataclass
class Job:
    id: str
    tasks: List[str]
    release: int = 0
    due: Optional[int] = None
    after: List[str] = field(default_factory=list)  # jobs that must finish before this one starts


@dataclass
class Problem:
    jobs: Dict[str, Job]
    tasks: Dict[str, Task]
    on_hold: Dict[str, str] = field(default_factory=dict)  # job id -> reason it cannot be scheduled now
    excluded_resources: Dict[str, str] = field(default_factory=dict)  # resource id -> reason

    @property
    def resources(self) -> List[str]:
        return sorted({r for t in self.tasks.values() for g in t.groups for r in g})

    def horizon(self) -> int:
        return sum(t.duration for t in self.tasks.values()) + max(
            [t.release for t in self.tasks.values()] + [j.release for j in self.jobs.values()] + [0])

    def lower_bound(self) -> int:
        """Valid lower bound on the makespan: longest job chain, or busiest mandatory resource."""
        memo: Dict[str, int] = {}

        def finish(job_id: str, stack: Tuple[str, ...] = ()) -> int:
            if job_id in memo:
                return memo[job_id]
            if job_id in stack:
                raise OntologyError(f"job precedence cycle through {job_id}")
            job = self.jobs[job_id]
            t = max([job.release] + [finish(a, stack + (job_id,)) for a in job.after if a in self.jobs])
            for tid in job.tasks:
                task = self.tasks[tid]
                t = max(t, task.release) + task.duration
            memo[job_id] = t
            return t

        chain = max((finish(j) for j in self.jobs), default=0)
        load: Dict[str, List[Task]] = {}
        for task in self.tasks.values():
            for g in task.groups:
                if len(g) == 1:
                    load.setdefault(g[0], []).append(task)
        busiest = max((min(t.release for t in ts) + sum(t.duration for t in ts) for ts in load.values()), default=0)
        return max(chain, busiest)


@dataclass
class Assignment:
    task: str
    job: str
    start: int
    end: int
    resources: List[str]


@dataclass
class Schedule:
    status: str  # optimal | feasible | infeasible | unknown
    makespan: Optional[int]
    assignments: Dict[str, Assignment]
    solver: str
    lower_bound: int = 0
    wall_ms: float = 0.0
    note: str = ""

    @property
    def gap(self) -> Optional[float]:
        if not self.makespan:
            return None
        return round((self.makespan - self.lower_bound) / self.makespan, 4)

    def job_end(self, job: str) -> Optional[int]:
        ends = [a.end for a in self.assignments.values() if a.job == job]
        return max(ends) if ends else None

    def tardiness(self, problem: Problem) -> Dict[str, int]:
        late = {}
        for job in problem.jobs.values():
            end = self.job_end(job.id)
            if job.due is not None and end is not None and end > job.due:
                late[job.id] = end - job.due
        return late

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "makespan": self.makespan, "lower_bound": self.lower_bound, "gap": self.gap,
                "solver": self.solver, "wall_ms": self.wall_ms, "note": self.note,
                "assignments": [a.__dict__ for a in sorted(self.assignments.values(), key=lambda a: (a.start, a.task))]}


def _num(value: Any, default: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def build_problem(ontology: Ontology, graph: KnowledgeGraph, impact: Optional[ImpactReport] = None,
                  jobs: Optional[Iterable[str]] = None) -> Problem:
    """Translate the knowledge graph into a scheduling problem (see module docstring)."""
    spec = ontology.scheduling
    if spec is None:
        raise OntologyError(f"{ontology.ref} has no scheduling section")
    checker = ImpactAgent(ontology, graph)
    wanted = set(jobs) if jobs is not None else None
    excluded: Dict[str, str] = {}
    problem = Problem({}, {})
    adjustments = impact.adjustments if impact else {}
    for job_inst in graph.instances(spec.job):
        if wanted is not None and job_inst.id not in wanted:
            continue
        task_insts = sorted(graph.neighbours(job_inst, spec.job_tasks), key=lambda t: (_num(t.get(spec.sequence)), t.id))
        job = Job(job_inst.id, [t.id for t in task_insts],
                  int(_num(job_inst.get(spec.release))) if spec.release else 0,
                  int(_num(job_inst.get(spec.due))) if spec.due and job_inst.get(spec.due) is not None else None)
        hold_reason = None
        tasks = []
        for t in task_insts:
            adj = adjustments.get(t.id, {})
            duration = int(round(_num(t.get(spec.duration), 0.0) * adj.get("duration_factor", 1.0)))
            groups = []
            for req in spec.resources:
                linked = graph.neighbours(t, req.step)
                if not linked:
                    continue
                usable = []
                for r in linked:
                    if checker.is_available(r):
                        usable.append(r.id)
                    else:
                        excluded[r.id] = f"{r.type} {r.id} unavailable (status {r.get('status')})"
                if req.alternatives:
                    if not usable:
                        hold_reason = f"{t.id}: no available {req.step} resource ({', '.join(r.id for r in linked)})"
                    groups.append(tuple(usable))
                else:
                    missing = [r.id for r in linked if r.id not in usable]
                    if missing:
                        hold_reason = f"{t.id}: required {', '.join(missing)} unavailable"
                    groups.extend((r,) for r in usable)
            tasks.append(Task(t.id, job.id, int(_num(t.get(spec.sequence))), max(duration, 0),
                              [g for g in groups if g], int(adj.get("release", 0))))
        if hold_reason:
            problem.on_hold[job.id] = hold_reason
            continue
        problem.jobs[job.id] = job
        for task in tasks:
            problem.tasks[task.id] = task
    if spec.job_precedence:
        for job_inst in graph.instances(spec.job):
            for succ in graph.neighbours(job_inst, spec.job_precedence):
                if succ.id in problem.jobs and job_inst.id in problem.jobs:
                    problem.jobs[succ.id].after.append(job_inst.id)
                elif succ.id in problem.jobs and job_inst.id in problem.on_hold:
                    problem.on_hold[succ.id] = f"waits for {job_inst.id}, which is on hold"
    for jid in list(problem.on_hold):  # cascade holds along precedence
        problem.jobs.pop(jid, None)
    changed = True
    while changed:
        changed = False
        for job in list(problem.jobs.values()):
            blocked = [a for a in job.after if a not in problem.jobs]
            if blocked:
                problem.on_hold[job.id] = f"waits for {', '.join(blocked)}, which is on hold"
                problem.jobs.pop(job.id)
                changed = True
    problem.tasks = {k: t for k, t in problem.tasks.items() if t.job in problem.jobs}
    problem.excluded_resources = excluded
    return problem


# -- solvers ----------------------------------------------------------------------------
class ListScheduler:
    """Dependency-free solver: randomised multi-start serial schedule generation (insertion-based).

    Priority rules mix most-work-remaining, earliest-due and shortest-processing-time with random
    perturbation; the best of ``iterations`` passes (or until ``time_limit``) is kept - lowest makespan,
    then lowest total lateness. The result is
    called ``optimal`` only when its makespan equals :meth:`Problem.lower_bound`.
    """

    name = "builtin-list-scheduler"

    def __init__(self, iterations: int = 300, seed: int = 0):
        self.iterations = iterations
        self.seed = seed

    @staticmethod
    def _fits(busy: List[Tuple[int, int]], start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in busy)

    @staticmethod
    def _earliest(busy: List[Tuple[int, int]], start: int, duration: int) -> int:
        t = start
        for s, e in sorted(busy):
            if t + duration <= s:
                break
            if e > t:
                t = e
        return t

    def _pass(self, problem: Problem, rng: random.Random, noise: float):
        busy: Dict[str, List[Tuple[int, int]]] = {r: [] for r in problem.resources}
        job_ready = {}
        remaining = {j.id: sum(problem.tasks[t].duration for t in j.tasks) for j in problem.jobs.values()}
        nxt = {j.id: 0 for j in problem.jobs.values()}
        prev_end = {j.id: 0 for j in problem.jobs.values()}
        done_jobs: Dict[str, int] = {}
        out: Dict[str, Assignment] = {}
        pending = {j.id for j in problem.jobs.values() if j.tasks}
        for j in problem.jobs.values():
            if not j.tasks:
                done_jobs[j.id] = j.release
        while pending:
            ready = [j for j in pending if all(a in done_jobs for a in problem.jobs[j].after)]
            if not ready:  # pragma: no cover - cycles are rejected by lower_bound()
                raise OntologyError("job precedence cycle")

            def key(jid):
                job = problem.jobs[jid]
                due = job.due if job.due is not None else 10 ** 9
                task = problem.tasks[job.tasks[nxt[jid]]]
                return (-remaining[jid] * (1 + noise * rng.random()), due * (1 + noise * rng.random()),
                        task.duration)

            jid = min(ready, key=key)
            job = problem.jobs[jid]
            task = problem.tasks[job.tasks[nxt[jid]]]
            if jid not in job_ready:
                job_ready[jid] = max([job.release] + [done_jobs[a] for a in job.after])
            t = max(job_ready[jid], prev_end[jid], task.release)
            for _ in range(10_000):
                picks, latest = [], t
                for g in task.groups:
                    cand = sorted(((self._earliest(busy[r], t, task.duration), rng.random(), r) for r in g))
                    start, _, r = cand[0]
                    picks.append(r)
                    latest = max(latest, start)
                if all(self._fits(busy[r], latest, latest + task.duration) for r in picks):
                    t = latest
                    break
                t = latest if latest > t else t + 1
            for r in picks:
                busy[r].append((t, t + task.duration))
            out[task.id] = Assignment(task.id, jid, t, t + task.duration, picks)
            prev_end[jid] = t + task.duration
            remaining[jid] -= task.duration
            nxt[jid] += 1
            if nxt[jid] == len(job.tasks):
                pending.discard(jid)
                done_jobs[jid] = prev_end[jid]
        makespan = max((a.end for a in out.values()), default=0)
        return makespan, out

    def solve(self, problem: Problem, time_limit: float = 2.0) -> Schedule:
        t0 = time.perf_counter()
        lb = problem.lower_bound()
        rng = random.Random(self.seed)
        best = None
        def lateness(out):
            total = 0
            for job in problem.jobs.values():
                ends = [out[t].end for t in job.tasks if t in out]
                if job.due is not None and ends:
                    total += max(0, max(ends) - job.due)
            return total

        for i in range(self.iterations):
            makespan, out = self._pass(problem, rng, 0.0 if i == 0 else 0.35)
            if best is None or (makespan, lateness(out)) < (best[0], lateness(best[1])):
                best = (makespan, out)
            if makespan <= lb or time.perf_counter() - t0 > time_limit:
                break
        makespan, out = best if best else (0, {})
        status = "optimal" if makespan <= lb else "feasible"
        return Schedule(status, makespan, out, self.name, lb, round((time.perf_counter() - t0) * 1000, 1),
                        "proven optimal: meets lower bound" if status == "optimal" else
                        f"heuristic; within {round(100 * (makespan - lb) / makespan, 1) if makespan else 0}% of lower bound")


class CpSatSolver:
    """Exact flexible job-shop model on Google OR-Tools CP-SAT.

    Lexicographic objective: minimise makespan; then, keeping that makespan, minimise the total
    lateness against job due dates (``tardiness=False`` for makespan only).
    """

    name = "ortools-cp-sat"

    def __init__(self, workers: int = 8, tardiness: bool = True):
        from ortools.sat.python import cp_model  # noqa: F401 - fail early if not installed

        self.workers = workers
        self.tardiness = tardiness  # lexicographic: minimise makespan, then total lateness

    def solve(self, problem: Problem, time_limit: float = 10.0) -> Schedule:
        from ortools.sat.python import cp_model

        t0 = time.perf_counter()
        model = cp_model.CpModel()
        horizon = max(problem.horizon(), 1)
        starts, ends, choice = {}, {}, {}
        per_resource: Dict[str, list] = {r: [] for r in problem.resources}
        for task in problem.tasks.values():
            job = problem.jobs[task.job]
            s = model.NewIntVar(max(task.release, job.release), horizon, f"s_{task.id}")
            e = model.NewIntVar(0, horizon, f"e_{task.id}")
            interval = model.NewIntervalVar(s, task.duration, e, f"i_{task.id}")
            starts[task.id], ends[task.id] = s, e
            for gi, group in enumerate(task.groups):
                if len(group) == 1:
                    per_resource[group[0]].append(interval)
                    choice[(task.id, gi)] = [(group[0], None)]
                    continue
                lits = []
                for r in group:
                    lit = model.NewBoolVar(f"x_{task.id}_{gi}_{r}")
                    per_resource[r].append(model.NewOptionalIntervalVar(s, task.duration, e, lit, f"o_{task.id}_{r}"))
                    lits.append((r, lit))
                model.AddExactlyOne(lit for _, lit in lits)
                choice[(task.id, gi)] = lits
        for intervals in per_resource.values():
            if len(intervals) > 1:
                model.AddNoOverlap(intervals)
        for job in problem.jobs.values():
            for a, b in zip(job.tasks, job.tasks[1:]):
                model.Add(ends[a] <= starts[b])
            if job.tasks:
                for pred in job.after:
                    if problem.jobs[pred].tasks:
                        model.Add(ends[problem.jobs[pred].tasks[-1]] <= starts[job.tasks[0]])
        makespan = model.NewIntVar(0, horizon, "makespan")
        if ends:
            model.AddMaxEquality(makespan, list(ends.values()))
        model.Minimize(makespan)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit)
        solver.parameters.num_search_workers = self.workers
        status = solver.Solve(model)
        name = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible",
                cp_model.INFEASIBLE: "infeasible"}.get(status, "unknown")
        if name not in ("optimal", "feasible"):
            wall = round((time.perf_counter() - t0) * 1000, 1)
            return Schedule(name, None, {}, self.name, problem.lower_bound(), wall, solver.StatusName(status))
        lb = max(int(solver.BestObjectiveBound()), problem.lower_bound())
        best = int(solver.ObjectiveValue()) if ends else 0
        tardiness_note = ""
        lates = []
        if self.tardiness:  # phase 2: keep the makespan, minimise total lateness against due dates
            for job in problem.jobs.values():
                if job.due is not None and job.tasks:
                    late = model.NewIntVar(0, horizon, f"late_{job.id}")
                    model.Add(late >= ends[job.tasks[-1]] - job.due)
                    lates.append(late)
            if lates:
                model.Add(makespan <= best)
                model.Minimize(sum(lates))
                for task_id, var in starts.items():  # warm start from the phase-1 solution
                    model.AddHint(var, solver.Value(var))
                phase1 = solver
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = float(time_limit)
                solver.parameters.num_search_workers = self.workers
                status2 = solver.Solve(model)
                if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    tardiness_note = (f"; total lateness {int(solver.ObjectiveValue())}"
                                      f" ({'optimal' if status2 == cp_model.OPTIMAL else 'best found'} at that makespan)")
                else:  # pragma: no cover - phase 1 solution always satisfies phase 2
                    solver = phase1
        wall = round((time.perf_counter() - t0) * 1000, 1)
        out = {}
        for task in problem.tasks.values():
            res = []
            for gi in range(len(task.groups)):
                for r, lit in choice[(task.id, gi)]:
                    if lit is None or solver.BooleanValue(lit):
                        res.append(r)
                        break
            out[task.id] = Assignment(task.id, task.job, solver.Value(starts[task.id]), solver.Value(ends[task.id]), res)
        note = "makespan optimality proven by CP-SAT" if name == "optimal" else f"time limit reached; bound {lb}"
        return Schedule(name, best, out, self.name, lb, wall, note + tardiness_note)


def default_solver(kind: str = "auto"):
    """``auto`` uses CP-SAT when OR-Tools is installed, else the built-in scheduler."""
    if kind in ("auto", "cp-sat", "ortools"):
        try:
            return CpSatSolver()
        except ImportError:
            if kind != "auto":
                raise
    return ListScheduler()


# -- validation -------------------------------------------------------------------------------
@dataclass
class ScheduleWarning:
    severity: str  # "critical" | "warning"
    check: str
    task: Optional[str]
    message: str


_TEMPLATE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\}")


def validate_schedule(ontology: Ontology, graph: KnowledgeGraph, problem: Problem,
                      schedule: Schedule) -> List[ScheduleWarning]:
    """Check a schedule against the ontology: solver invariants first, then the declared semantic checks."""
    spec = ontology.scheduling
    warnings: List[ScheduleWarning] = []
    if schedule.status not in ("optimal", "feasible"):
        return [ScheduleWarning("critical", "SOLVER", None, f"no schedule: solver status {schedule.status}")]
    checker = ImpactAgent(ontology, graph)
    # invariants (defence in depth: never trust a solver blindly)
    by_resource: Dict[str, List[Assignment]] = {}
    for a in schedule.assignments.values():
        for r in a.resources:
            by_resource.setdefault(r, []).append(a)
    for r, items in by_resource.items():
        items.sort(key=lambda a: a.start)
        for x, y in zip(items, items[1:]):
            if y.start < x.end:
                warnings.append(ScheduleWarning("critical", "INV-OVERLAP", y.task, f"{x.task} and {y.task} overlap on {r}"))
        inst = graph.get(r)
        if not checker.is_available(inst):
            warnings.append(ScheduleWarning("critical", "INV-AVAILABILITY", items[0].task,
                                            f"{r} is assigned but unavailable (status {inst.get('status')})"))
    for job in problem.jobs.values():
        seq = [schedule.assignments.get(t) for t in job.tasks]
        if any(a is None for a in seq):
            warnings.append(ScheduleWarning("critical", "INV-MISSING", None, f"{job.id} has unscheduled tasks"))
            continue
        for x, y in zip(seq, seq[1:]):
            if y.start < x.end:
                warnings.append(ScheduleWarning("critical", "INV-SEQUENCE", y.task, f"{y.task} starts before {x.task} ends"))
        for pred in job.after:
            end = schedule.job_end(pred)
            if seq and end is not None and seq[0].start < end:
                warnings.append(ScheduleWarning("critical", "INV-PRECEDENCE", seq[0].task,
                                                f"{job.id} starts before predecessor {pred} finishes"))
    for jid, late in sorted(schedule.tardiness(problem).items()):
        warnings.append(ScheduleWarning("warning", "DUE-DATE", None,
                                        f"{jid} finishes {late}{spec.time_unit} after its due date"))
    for jid, reason in sorted(problem.on_hold.items()):
        warnings.append(ScheduleWarning("critical", "ON-HOLD", None, f"{jid} not scheduled: {reason}"))
    # declared semantic checks
    for a in sorted(schedule.assignments.values(), key=lambda a: (a.start, a.task)):
        bound: Dict[str, Instance] = {spec.task: graph.get(a.task), spec.job: graph.get(a.job)}
        for r in a.resources:
            inst = graph.get(r)
            bound.setdefault(inst.type, inst)
        for step in spec.context:
            for inst in graph.neighbours(bound[spec.task], step)[:1]:
                bound.setdefault(inst.type, inst)
        for step in spec.job_context:
            for inst in graph.neighbours(bound[spec.job], step)[:1]:
                bound.setdefault(inst.type, inst)
        slot = {"start": a.start, "end": a.end, "duration": a.end - a.start}

        def resolve(entity: str, attr: str):
            if entity == "Slot":
                return slot.get(attr)
            inst = bound.get(entity)
            return inst.get(attr) if inst else None

        for check in spec.checks:
            needed = {e for e, _ in check.when.references} - {"Slot"}
            if not needed <= set(bound):
                continue
            if check.when.evaluate(resolve):
                message = _TEMPLATE.sub(lambda m: str(resolve(m.group(1), m.group(2))), check.message)
                warnings.append(ScheduleWarning(check.severity, check.id, a.task, message))
    return warnings


# -- the agent -----------------------------------------------------------------------------------
@dataclass
class ReplanResult:
    event_id: Optional[str]
    impact: Optional[ImpactReport]
    baseline: Optional[Schedule]
    schedule: Schedule
    problem: Problem
    warnings: List[ScheduleWarning]

    @property
    def delays(self) -> Dict[str, int]:
        """Per job: finish-time change versus the baseline (positive = later)."""
        if not self.baseline:
            return {}
        out = {}
        for job in self.problem.jobs:
            before, after = self.baseline.job_end(job), self.schedule.job_end(job)
            if before is not None and after is not None and after != before:
                out[job] = after - before
        return out

    @property
    def critical(self) -> int:
        return sum(w.severity == "critical" for w in self.warnings)

    def as_dict(self) -> Dict[str, Any]:
        return {"event_id": self.event_id, "impact": self.impact.as_dict() if self.impact else None,
                "baseline": self.baseline.as_dict() if self.baseline else None, "schedule": self.schedule.as_dict(),
                "on_hold": self.problem.on_hold, "excluded_resources": self.problem.excluded_resources,
                "delays": self.delays, "warnings": [w.__dict__ for w in self.warnings]}


class ScheduleAgent:
    def __init__(self, ontology: Ontology, graph: KnowledgeGraph, solver=None, time_limit: float = 10.0):
        self.ontology = ontology
        self.graph = graph
        self.solver = solver or default_solver()
        self.time_limit = time_limit

    def schedule(self, impact: Optional[ImpactReport] = None) -> Tuple[Problem, Schedule]:
        problem = build_problem(self.ontology, self.graph, impact)
        return problem, self.solver.solve(problem, self.time_limit)

    def replan(self, event_id: Optional[str] = None, baseline: Optional[Schedule] = None) -> ReplanResult:
        impact = ImpactAgent(self.ontology, self.graph).analyze(event_id) if event_id else None
        problem, schedule = self.schedule(impact)
        warnings = validate_schedule(self.ontology, self.graph, problem, schedule)
        return ReplanResult(event_id, impact, baseline, schedule, problem, warnings)


def clone_job(ontology: Ontology, graph: KnowledgeGraph, source_job: str, new_id: str, *,
              from_seq: Optional[float] = None, release: Optional[int] = None,
              link: Optional[Tuple[str, str]] = None) -> Instance:
    """Create e.g. a rework order that inherits the source job's routing and resource links.

    Tasks with ``sequence >= from_seq`` are copied (all if None). ``link=(kind, target_id)`` adds
    a relationship from the new job (e.g. ``("reworks", "WO-12")``).
    """
    spec = ontology.scheduling
    src = graph.get(source_job)
    attrs = {k: v for k, v in src.attributes.items() if k != "status"}
    if release is not None and spec.release:
        attrs[spec.release] = release
    job = graph.add(spec.job, new_id, **attrs)
    for rel in ontology.relationships:  # copy the job's other outgoing links (e.g. which part it produces)
        if rel.source == spec.job and rel.kind not in (spec.job_tasks, spec.job_precedence):
            for target in graph.neighbours(src, rel.kind):
                graph.link(new_id, rel.kind, target.id)
    for task in graph.neighbours(src, spec.job_tasks):
        if from_seq is not None and _num(task.get(spec.sequence)) < from_seq:
            continue
        tid = f"{new_id}/{task.id.rsplit('/', 1)[-1]}"
        graph.add(spec.task, tid, **{k: v for k, v in task.attributes.items() if k != "status"})
        graph.link(new_id, spec.job_tasks, tid)
        for rel in ontology.relationships:
            if rel.source == spec.task:
                for target in graph.neighbours(task, rel.kind):
                    graph.link(tid, rel.kind, target.id)
    if link:
        graph.link(new_id, link[0], link[1])
    return job


# -- rendering -----------------------------------------------------------------------------------------
def gantt_text(schedule: Schedule, problem: Problem, width: int = 72, resources: Optional[Sequence[str]] = None) -> str:
    if not schedule.assignments:
        return "(empty schedule)"
    span = max(schedule.makespan or 1, 1)
    scale = width / span
    rows = resources or sorted({a.resources[0] for a in schedule.assignments.values() if a.resources})
    lines = [f"{'':10}0{'':{width - len(str(span)) - 1}}{span}"]
    for r in rows:
        bar = [" "] * width
        for a in schedule.assignments.values():
            if a.resources and a.resources[0] == r:
                s, e = int(a.start * scale), max(int(a.end * scale), int(a.start * scale) + 1)
                ch = a.job[-1]
                for i in range(s, min(e, width)):
                    bar[i] = ch
        lines.append(f"{r:<10}|{''.join(bar)}|")
    return "\n".join(lines)


def gantt_html(result: ReplanResult, title: str = "Schedule") -> str:
    """Self-contained HTML Gantt (one row per primary resource) with warnings - for shop-floor dashboards."""
    sch, problem = result.schedule, result.problem
    rows = sorted({a.resources[0] for a in sch.assignments.values() if a.resources})
    span = max(sch.makespan or 1, 1)
    w, row_h, left = 900, 22, 90
    jobs = sorted(problem.jobs)
    palette = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]
    color = {j: palette[i % len(palette)] for i, j in enumerate(jobs)}
    flagged = {wn.task for wn in result.warnings if wn.task}
    bars = []
    for i, r in enumerate(rows):
        y = 30 + i * row_h
        bars.append(f'<text x="4" y="{y + 15}" class="lbl">{html.escape(r)}</text>')
        for a in sch.assignments.values():
            if a.resources and a.resources[0] == r:
                x = left + a.start * (w - left) / span
                bw = max((a.end - a.start) * (w - left) / span, 1)
                stroke = ' stroke="#c00" stroke-width="2"' if a.task in flagged else ""
                tip = html.escape(f"{a.task} ({a.job}) {a.start}-{a.end} on {', '.join(a.resources)}")
                bars.append(f'<rect x="{x:.1f}" y="{y + 3}" width="{bw:.1f}" height="{row_h - 6}" rx="3" '
                            f'fill="{color[a.job]}"{stroke}><title>{tip}</title></rect>')
    height = 40 + len(rows) * row_h
    warn = "".join(f"<li class='{w_.severity}'><b>{html.escape(w_.check)}</b> {html.escape(w_.message)}</li>"
                   for w_ in result.warnings)
    summary = (f"{len(problem.jobs)} jobs, {len(problem.tasks)} tasks - makespan {sch.makespan} "
               f"({sch.status}, {sch.solver}, {sch.wall_ms} ms; lower bound {sch.lower_bound})")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{--bg:#fff;--fg:#1b1b1f;--muted:#666;--grid:#eee}}
@media (prefers-color-scheme: dark){{:root{{--bg:#17171a;--fg:#ececf1;--muted:#aaa;--grid:#2a2a30}}}}
body{{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;margin:16px}}
svg{{max-width:100%;height:auto}} .lbl{{fill:var(--fg);font:12px monospace}}
li.critical{{color:#d33}} li.warning{{color:#b77d00}} .muted{{color:var(--muted)}}
</style></head><body><h1>{html.escape(title)}</h1><p class="muted">{html.escape(summary)}</p>
<svg viewBox="0 0 {w} {height}" role="img" aria-label="Gantt chart">{''.join(bars)}</svg>
<h2>Warnings ({len(result.warnings)})</h2><ul>{warn or '<li>none</li>'}</ul></body></html>
"""


# -- tools for WorkAgents ----------------------------------------------------------------------------------
def scheduling_tools(ontology: str, data: str, solver: str = "auto", time_limit: float = 10.0,
                     out_dir: Optional[str] = None, event_field: str = "Replan.event_id",
                     rework: Optional[Dict[str, str]] = None):
    """A :class:`ToolRegistry` exposing impact analysis, scheduling, validation and publishing as tools.

    Capabilities: ``scheduling.impact``, ``scheduling.solve``, ``scheduling.validate``,
    ``scheduling.publish`` (writes schedule JSON + HTML Gantt to ``out_dir`` - swap for an
    ``http`` tool to push to a real MES). The event id is read from ``event_field``.
    Results are reported through the updates of the calling action's ``writes`` fields.

    ``rework`` - e.g. ``{"event": "QualityReturn", "source": "returnOf", "link": "reworks",
    "from_seq": "from_seq"}`` - makes a quality-return event create a rework job that inherits
    the returned job's routing (from the failed step on) before impact analysis.
    """
    from .tools import ToolCall, ToolError, ToolRegistry, ToolResult

    onto = Ontology.load(ontology)
    base = json.loads(Path(data).read_text(encoding="utf-8"))
    entity = event_field.partition(".")[0]
    state: Dict[str, Any] = {}
    tools = ToolRegistry()

    def graph_for(event_id: str) -> KnowledgeGraph:
        if event_id not in state:
            state[event_id] = {"graph": KnowledgeGraph.from_dict(onto, base)}
        return state[event_id]["graph"]

    def event_of(call: ToolCall) -> str:
        event_id = call.inputs.get(event_field)
        if not event_id:
            raise ToolError(f"{event_field} is not set")
        return str(event_id)

    @tools.tool("scheduling.impact", name="impact_agent", cost=0.01)
    def impact(call: ToolCall) -> ToolResult:
        """ImpactAgent: ontology inference of affected jobs, tasks and resources."""
        event_id = event_of(call)
        graph = graph_for(event_id)
        try:
            event = graph.get(event_id)
        except KeyError:
            raise ToolError(f"unknown event {event_id!r}") from None
        if rework and event.type == rework["event"] and not state[event_id].get("rework"):
            sources = graph.neighbours(event, rework["source"])
            if not sources:
                raise ToolError(f"{event_id} does not reference a job to rework")
            src = sources[0]
            seq = event.get(rework.get("from_seq", "from_seq"))
            new_job = clone_job(onto, graph, src.id, f"{src.id}-RW", from_seq=_num(seq) if seq is not None else None,
                                link=(rework["link"], src.id))
            state[event_id]["rework"] = new_job.id
        try:
            report = ImpactAgent(onto, graph).analyze(event_id)
        except OntologyError as exc:
            raise ToolError(str(exc)) from None
        state[event_id]["impact"] = report
        spec = onto.scheduling
        crit = sum(r.severity == "critical" for r in report.risks)
        return ToolResult(updates={entity: {"affected_jobs": report.count(spec.job),
                                            "affected_tasks": report.count(spec.task),
                                            "unavailable_resources": len(report.unavailable),
                                            "risks": len(report.risks), "critical_risks": crit}},
                          message=report.summary(onto), output=report.as_dict())

    @tools.tool("scheduling.solve", name="schedule_agent", cost=0.05)
    def solve(call: ToolCall) -> ToolResult:
        """ScheduleAgent: solve the constrained job-shop problem."""
        event_id = event_of(call)
        st = state.get(event_id) or {}
        if "impact" not in st:
            raise ToolError("run impact analysis first")
        graph = st["graph"]
        engine = default_solver(solver)
        base_problem = build_problem(onto, KnowledgeGraph.from_dict(onto, base))
        baseline = engine.solve(base_problem, time_limit)
        agent = ScheduleAgent(onto, graph, engine, time_limit)
        problem, sched = agent.schedule(st["impact"])
        st.update(problem=problem, schedule=sched, baseline=baseline)
        result = ReplanResult(event_id, st["impact"], baseline, sched, problem, [])
        delay = (sched.makespan or 0) - (baseline.makespan or 0)
        outcome = "infeasible" if sched.status not in ("optimal", "feasible") else None
        return ToolResult(outcome, {entity: {"makespan": sched.makespan, "baseline_makespan": baseline.makespan,
                                             "delay": delay, "solver_status": sched.status,
                                             "jobs_on_hold": len(problem.on_hold),
                                             "jobs_delayed": sum(1 for d in result.delays.values() if d > 0)}},
                          f"{len(problem.jobs)} jobs / {len(problem.tasks)} tasks: makespan {sched.makespan} "
                          f"({sched.status}, {sched.solver}, {sched.wall_ms} ms), baseline {baseline.makespan}")

    @tools.tool("scheduling.validate", name="ontology_validator", cost=0.01)
    def validate(call: ToolCall) -> ToolResult:
        """Ontology validation of the schedule (invariants + semantic checks)."""
        event_id = event_of(call)
        st = state.get(event_id) or {}
        if "schedule" not in st:
            raise ToolError("no schedule to validate")
        found = validate_schedule(onto, st["graph"], st["problem"], st["schedule"])
        st["warnings"] = found
        # jobs on hold are reported separately (jobs_on_hold); critical_warnings counts schedule/data findings
        crit = sum(w.severity == "critical" and w.check != "ON-HOLD" for w in found)
        held = sum(w.check == "ON-HOLD" for w in found)
        return ToolResult(updates={entity: {"warnings": len(found), "critical_warnings": crit}},
                          message=f"{len(found)} warnings ({crit} critical, {held} jobs on hold)")

    @tools.tool("scheduling.publish", name="mes_file_publisher", cost=0.1)
    def publish(call: ToolCall) -> ToolResult:
        """Publish the validated schedule (JSON + HTML Gantt) for MES and shop-floor dashboards."""
        event_id = event_of(call)
        st = state.get(event_id) or {}
        if "warnings" not in st:
            raise ToolError("schedule not validated")
        result = ReplanResult(event_id, st["impact"], st["baseline"], st["schedule"], st["problem"], st["warnings"])
        message = "schedule published"
        if out_dir:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", event_id)
            (out / f"schedule-{safe}.json").write_text(json.dumps(result.as_dict(), indent=1, default=str))
            (out / f"schedule-{safe}.html").write_text(gantt_html(result, f"Schedule after {event_id}"))
            message = f"schedule published to {out / ('schedule-' + safe + '.json')}"
        return ToolResult(message=message, output=result.as_dict())

    return tools
