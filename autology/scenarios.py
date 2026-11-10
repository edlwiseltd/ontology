"""What-if scenarios: change a copy of the knowledge graph, compare the outcome, then commit or discard.

A scenario forks the graph and replays a list of *edits* on the copy. The real graph is untouched
until the scenario is committed::

    s = Scenario(graph, "machine 5 down")
    s.apply({"op": "add", "type": "Alert", "id": "AL-1", "attributes": {...}, "links": [...]})
    s.apply({"op": "event", "id": "AL-1"})               # impact rules propagate the event
    s.apply({"op": "set", "id": "O-3", "attributes": {"amount": 60000}})
    s.apply({"op": "action", "action": "ship_order", "case_template": "contract_case",
             "root": "K-1", "target": "O-2", "roles": ["ops"]})
    report = s.compare(checks=[{"goal": "fulfil_contract", "case_template": "contract_case", "root": "K-1",
                                "roles": ["ops", "finance"]}], schedule=True)
    s.commit(graph)                                       # refuses if the real data moved underneath

Edit operations:

``set``     change attributes of an instance (validated against the ontology, states included);
``add``     add an instance, optionally with ``links`` ``[{"kind", "target"}]`` or ``[{"kind", "source"}]``;
``link``    add a link ``{"source", "kind", "target"}``;
``action``  simulate one ontology action on a case built from the scenario graph. Governance decides
            exactly as for an agent: a denied action is recorded and not applied, an action that would
            need human review is applied and flagged. No tool is called. Outcome: ``outcome`` or the
            action's primary one;
``event``   apply an event instance's impact rules (see :mod:`autology.impact`) and record the impact.

``compare`` reports, against the unchanged baseline: competency-question answers that differ,
plans for goals (steps, or why no compliant plan exists), and optionally schedule KPIs.
"""

from __future__ import annotations

import copy as _copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .governance import GovernanceLayer, Principal, Verdict
from .graph import KnowledgeGraph, build_case, fork, write_back
from .ontology import ID, OntologyError
from .planner import Planner
from .state import WorldState, ground

OPS = ("set", "add", "link", "action", "event")


class ScenarioError(OntologyError):
    pass


class ConflictError(ScenarioError):
    def __init__(self, conflicts: List[Dict[str, Any]]):
        super().__init__("the live data changed since the scenario read it: "
                         + ", ".join(f"{c['id']}.{c['attribute']}" for c in conflicts))
        self.conflicts = conflicts


@dataclass
class Scenario:
    base: KnowledgeGraph
    name: str = "scenario"
    edits: List[Dict[str, Any]] = field(default_factory=list)
    snapshot: Optional[Dict[str, Dict[str, Any]]] = None  # base values of touched instances, when first read

    def __post_init__(self):
        self.ontology = self.base.ontology
        self.graph = fork(self.base)
        self.results: List[Dict[str, Any]] = []
        self.steps: Dict[Tuple[str, str], Dict[str, str]] = {}  # (template, root) -> steps done in this scenario
        self._added: List[str] = []
        self._links: List[Tuple[str, str, str]] = []
        fresh = self.snapshot is None
        self.snapshot = {} if fresh else dict(self.snapshot)
        edits, self.edits = list(self.edits), []
        for edit in edits:
            self.apply(edit, record_snapshot=fresh)

    # -- editing -------------------------------------------------------------
    def apply(self, edit: Mapping[str, Any], record_snapshot: bool = True) -> Dict[str, Any]:
        """Apply one edit to the scenario graph; returns what happened. Invalid edits raise and change nothing."""
        op = edit.get("op")
        if op not in OPS:
            raise ScenarioError(f"unknown edit op {op!r}; expected one of {list(OPS)}")
        result = getattr(self, f"_op_{op}")(dict(edit), record_snapshot)
        self.edits.append(_copy.deepcopy(dict(edit)))
        self.results.append(result)
        return result

    def _instance(self, iid: str):
        try:
            return self.graph.get(iid)
        except KeyError:
            raise ScenarioError(f"no instance {iid!r} in the scenario") from None

    def _touch(self, iid: str, record: bool) -> None:
        if record and iid not in self.snapshot and iid not in self._added:
            base = self.base._instances.get(iid)
            if base is not None:
                self.snapshot[iid] = dict(base.attributes)

    def _op_set(self, edit: Dict[str, Any], record: bool) -> Dict[str, Any]:
        inst = self._instance(str(edit.get("id")))
        attrs = dict(edit.get("attributes") or {})
        probe = KnowledgeGraph(self.ontology)
        probe.add(inst.type, inst.id, **{**{k: v for k, v in inst.attributes.items() if v is not None}, **attrs})
        self._touch(inst.id, record)
        inst.attributes.update(attrs)
        return {"op": "set", "id": inst.id, "changed": sorted(attrs)}

    def _op_add(self, edit: Dict[str, Any], record: bool) -> Dict[str, Any]:
        iid = str(edit.get("id") or "")
        if not iid or not edit.get("type"):
            raise ScenarioError("add needs a type and an id")
        links = []
        for link in edit.get("links", []):
            if "target" in link:
                links.append((iid, link["kind"], link["target"]))
            else:
                links.append((link["source"], link["kind"], iid))
        self.graph.add(edit["type"], iid, **dict(edit.get("attributes") or {}))
        try:
            for s, k, t in links:
                self.graph.link(s, k, t)
        except (KeyError, OntologyError) as exc:
            del self.graph._instances[iid]
            self.graph._links = [l for l in self.graph._links if iid not in (l[0], l[2])]
            raise ScenarioError(f"add {iid}: invalid link: {exc}") from None
        self._added.append(iid)
        self._links.extend(links)
        return {"op": "add", "id": iid, "links": len(links)}

    def _op_link(self, edit: Dict[str, Any], record: bool) -> Dict[str, Any]:
        try:
            self.graph.link(edit["source"], edit["kind"], edit["target"])
        except KeyError as exc:
            raise ScenarioError(f"link: unknown instance or field {exc}") from None
        self._links.append((edit["source"], edit["kind"], edit["target"]))
        return {"op": "link", "link": [edit["source"], edit["kind"], edit["target"]]}

    def _op_action(self, edit: Dict[str, Any], record: bool) -> Dict[str, Any]:
        name, template, root = edit.get("action"), edit.get("case_template"), str(edit.get("root") or "")
        if name not in self.ontology.actions:
            raise ScenarioError(f"unknown action {name!r}")
        case, sources = build_case(self.graph, template, root)
        state = WorldState.initial(self.ontology, case)
        state.steps.update(self.steps.get((template, root), {}))
        action, target = self.ontology.actions[name], edit.get("target")
        if action.for_each and target not in state.collections.get(action.for_each, {}):
            raise ScenarioError(f"action {name} works on one {action.for_each}: give a target from the case")
        if not action.for_each and target:
            raise ScenarioError(f"action {name} does not take a target")
        ga = ground(self.ontology, name, state, target)
        try:
            outcome = ga.action.outcome(edit["outcome"]) if edit.get("outcome") else ga.action.outcomes[0]
        except KeyError as exc:
            raise ScenarioError(str(exc.args[0])) from None
        principal = Principal("scenario", frozenset(edit.get("roles") or ()))
        decision = GovernanceLayer(self.ontology, max_violations=0).evaluate(ga, state, principal)
        out = {"op": "action", "action": ga.name, "verdict": decision.verdict.value, "reasons": list(decision.reasons),
               "rules": list(decision.rule_ids), "applied": False, "changed": []}
        if decision.verdict is Verdict.DENY:
            return out
        planner = Planner(self.ontology, GovernanceLayer(self.ontology, max_violations=0))
        after = planner.simulate(state, ga, outcome)
        for iid in [v for src in sources.values() for v in (src if isinstance(src, list) else [src])]:
            self._touch(iid, record)
        out.update(applied=True, outcome=outcome.name, changed=write_back(self.graph, after, sources))
        if decision.verdict is Verdict.REVIEW:
            out["needs_review_by"] = list(decision.reviewers)
        self.steps[(template, root)] = dict(after.steps)
        return out

    def _op_event(self, edit: Dict[str, Any], record: bool) -> Dict[str, Any]:
        from .impact import ImpactAgent

        event = self._instance(str(edit.get("id")))
        before = {i.id: dict(i.attributes) for i in self.graph.instances()}
        report = ImpactAgent(self.ontology, self.graph).analyze(event.id, apply=True)
        changed = [iid for iid, attrs in before.items() if self.graph.get(iid).attributes != attrs]
        for iid in changed:
            self._touch(iid, record)
        return {"op": "event", "id": event.id, "rules": list(report.rule_ids), "changed": changed,
                "affected": {t: len(ids) for t, ids in report.affected.items()},
                "risks": [r.__dict__ for r in report.risks]}

    # -- results -------------------------------------------------------------
    def diff(self) -> Dict[str, Any]:
        """Net changes against the baseline: changed attributes, added instances and added links."""
        changed: Dict[str, Dict[str, List[Any]]] = {}
        for inst in self.graph.instances():
            base = self.base._instances.get(inst.id)
            if base is None:
                continue
            delta = {a: [base.attributes.get(a), v] for a, v in inst.attributes.items() if base.attributes.get(a) != v}
            if delta:
                changed[inst.id] = delta
        added = [i for i in self._added if i in self.graph._instances]
        return {"changed": changed, "added": added, "links": [list(l) for l in self._links],
                "added_status": {i: f"{self.graph.get(i).type}, {self.graph.get(i).attributes.get('status')}"
                                 for i in added}}

    def conflicts(self, live: Optional[KnowledgeGraph] = None) -> List[Dict[str, Any]]:
        """Attributes this scenario changes whose live value moved since the scenario first read them."""
        live = live or self.base
        out = []
        for iid, delta in self.diff()["changed"].items():
            seen = self.snapshot.get(iid, {})
            inst = live._instances.get(iid)
            for attr in delta:
                now = inst.attributes.get(attr) if inst else None
                if attr in seen and seen[attr] != now:
                    out.append({"id": iid, "attribute": attr, "read": seen[attr], "live": now})
        for iid in self.diff()["added"]:
            if iid in live._instances:
                out.append({"id": iid, "attribute": ID, "read": None, "live": "exists"})
        return out

    def compare(self, checks: Sequence[Mapping[str, Any]] = (), questions: bool = True,
                schedule: bool = False, solver: Any = None) -> Dict[str, Any]:
        """Compare baseline and scenario: question answers, goal plans, and schedule KPIs."""
        report: Dict[str, Any] = {"scenario": self.name, "diff": self.diff()}
        if questions:
            report["questions"] = []
            for q in self.ontology.questions:
                try:
                    before, after = self.base.ask(q).answer, self.graph.ask(q).answer
                except Exception as exc:  # e.g. a question that needs parameters
                    report["questions"].append({"id": q.id, "question": q.question, "error": str(exc)})
                    continue
                report["questions"].append({"id": q.id, "question": q.question, "baseline": before,
                                            "scenario": after, "changed": before != after})
        report["plans"] = [{**dict(c), "baseline": self._plan(self.base, c), "scenario": self._plan(self.graph, c)}
                           for c in checks]
        if schedule:
            report["schedule"] = {"baseline": self._schedule(self.base, solver),
                                  "scenario": self._schedule(self.graph, solver)}
        return report

    def _plan(self, graph: KnowledgeGraph, check: Mapping[str, Any]) -> Dict[str, Any]:
        goal = self.ontology.goals.get(check.get("goal"))
        if goal is None:
            raise ScenarioError(f"unknown goal {check.get('goal')!r}")
        root = str(check.get("root") or "")
        if root not in graph._instances:
            return {"status": "absent"}
        case, _ = build_case(graph, check.get("case_template"), root)
        state = WorldState.initial(self.ontology, case)
        principal = Principal("scenario", frozenset(check.get("roles") or ()))
        planner = Planner(self.ontology, GovernanceLayer(self.ontology, max_violations=0))
        detailed = planner.plan_with_outcomes(state, goal, principal)
        if detailed is not None:
            governance, probe, reviews = GovernanceLayer(self.ontology, max_violations=0), state, []
            for name, outcome in detailed:  # which steps would wait for a person
                ga = ground(self.ontology, name, probe)
                if governance.evaluate(ga, probe, principal).verdict is Verdict.REVIEW:
                    reviews.append(name)
                probe = planner.simulate(probe, ga, ga.action.outcome(outcome))
            plan = [name for name, _ in detailed]
            return {"status": "reached" if not plan else "plan", "steps": plan, "length": len(plan),
                    "reviews": reviews}
        # as the agent explains blocks: relax access rules first but keep mandatory steps, then relax everything
        relaxed = planner.plan(state, goal, principal, enforce_rules="steps")
        if relaxed is None:
            relaxed = planner.plan(state, goal, principal, enforce_rules=False)
        if relaxed is None:
            return {"status": "unreachable", "reason": "no sequence of actions leads to the goal"}
        governance = GovernanceLayer(self.ontology, max_violations=0)
        probe = state
        for name in relaxed:
            decision = governance.evaluate(name, probe, principal)
            if decision.verdict is Verdict.DENY:
                return {"status": "blocked", "action": name, "reasons": list(decision.reasons),
                        "rules": list(decision.rule_ids)}
            probe = planner.simulate(probe, ground(self.ontology, name, probe))
        return {"status": "blocked", "reason": "every path to the goal violates a rule"}  # pragma: no cover

    def _schedule(self, graph: KnowledgeGraph, solver: Any) -> Dict[str, Any]:
        from .scheduling import ListScheduler, ScheduleAgent

        if self.ontology.scheduling is None:
            raise ScenarioError("the ontology has no scheduling section")
        problem, sched = ScheduleAgent(self.ontology, graph, solver or ListScheduler(), time_limit=5).schedule()
        late = sched.tardiness(problem)
        return {"status": sched.status, "makespan": sched.makespan, "jobs_scheduled": len(problem.jobs),
                "on_hold": dict(problem.on_hold), "late_jobs": sorted(late),
                "total_tardiness": sum(late.values()), "solver": sched.solver}

    def commit(self, live: Optional[KnowledgeGraph] = None, store: Any = None) -> List[str]:
        """Apply the scenario's net changes to ``live`` (default: the graph it was forked from) and ``store``.

        Raises :class:`ConflictError` if live values the scenario changes have moved since it read them.
        Returns the ids of instances written.
        """
        live = live or self.base
        conflicts = self.conflicts(live)
        if conflicts:
            raise ConflictError(conflicts)
        d = self.diff()
        written = []
        for iid in d["added"]:
            inst = self.graph.get(iid)
            live.add(inst.type, iid, **{k: v for k, v in inst.attributes.items()})
            written.append(iid)
        for iid, delta in d["changed"].items():
            live.get(iid).attributes.update({a: v[1] for a, v in delta.items()})
            written.append(iid)
        for s, k, t in self._links:
            if (s, k, t) not in live._links:
                live.link(s, k, t)
        if store is not None:
            for iid in written:
                inst = live.get(iid)
                store.upsert_instance(inst.type, iid, inst.attributes)
            for s, k, t in self._links:
                store.add_link(s, k, t)
        return written

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "edits": self.edits, "results": self.results, "diff": self.diff()}


def render(report: Mapping[str, Any]) -> str:
    """A short markdown comparison report."""
    lines = [f"# Scenario: {report['scenario']}", ""]
    d = report["diff"]
    lines.append(f"**Changes:** {len(d['changed'])} instances changed, {len(d['added'])} added, "
                 f"{len(d['links'])} links added.")
    for iid, delta in d["changed"].items():
        lines.append(f"- {iid}: " + ", ".join(f"{a} {b!r} → {c!r}" for a, (b, c) in delta.items()))
    for iid in d["added"]:
        lines.append(f"- added {iid}" + (f" ({d['added_status'][iid]})" if d.get("added_status", {}).get(iid) else ""))
    qs = [q for q in report.get("questions", []) if q.get("changed")]
    if qs:
        lines += ["", "## Answers that change", "", "| Question | Baseline | Scenario |", "|---|---|---|"]
        lines += [f"| {q['question']} | {q['baseline']} | {q['scenario']} |" for q in qs]
    if report.get("plans"):
        lines += ["", "## Goals", ""]
        for p in report["plans"]:
            lines.append(f"- **{p['goal']} for {p['root']}**: baseline {_plan_text(p['baseline'])}; "
                         f"scenario {_plan_text(p['scenario'])}")
    if report.get("schedule"):
        b, s = report["schedule"]["baseline"], report["schedule"]["scenario"]
        lines += ["", "## Schedule", "", "| | Baseline | Scenario |", "|---|---|---|",
                  f"| Jobs scheduled | {b['jobs_scheduled']} | {s['jobs_scheduled']} |",
                  f"| Jobs on hold | {len(b['on_hold'])} | {len(s['on_hold'])} |",
                  f"| Makespan (scheduled jobs) | {b['makespan']} | {s['makespan']} |",
                  f"| Late jobs | {len(b['late_jobs'])} | {len(s['late_jobs'])} |",
                  f"| Total tardiness | {b['total_tardiness']} | {s['total_tardiness']} |"]
        held = sorted(set(s["on_hold"]) - set(b["on_hold"]))
        if held:
            lines += ["", "Newly on hold: " + "; ".join(f"{j} ({s['on_hold'][j]})" for j in held[:10])
                      + (f"; and {len(held) - 10} more" if len(held) > 10 else "")]
    return "\n".join(lines) + "\n"


def _plan_text(p: Mapping[str, Any]) -> str:
    if p["status"] == "plan":
        return f"{p['length']} steps" + (f", {len(p['reviews'])} need human review" if p.get("reviews") else "")
    if p["status"] == "blocked":
        return "blocked" + (f" at {p['action']} ({'; '.join(p['reasons'])})" if p.get("action") else "")
    return p["status"]
