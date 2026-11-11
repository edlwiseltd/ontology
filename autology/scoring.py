"""Readiness scorecard: how ready is an Autology deployment, and what should be fixed first?

Scores the three success factors of the methodology on 0-100:

* **Ontology quality** - lint findings, competency questions, security coverage,
  tool coverage, semantic richness, versioning;
* **Agent performance** - resolution (completed, or correctly stopped by policy),
  unplanned hand-offs, straight-through rate,
  cost per completed task, self-healing (needs agent runs);
* **Governance** - rule coverage, audit integrity, violations, ontology gaps,
  revocation policy.

Criteria that cannot be assessed with the evidence given (no runs, no sample
data, no tools, no cost budget) are reported as "not assessed" and excluded,
so the score never rewards or punishes missing evidence - but the scorecard
says what evidence to add. It also checks the roadmap's phase gates
(pilot -> scale -> optimise) and ranks recommendations by points recoverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .lint import lint
from .ontology import Ontology
from .reporting import metrics, ontology_gaps
from .versioning import VersionError, parse_version

PILLAR_WEIGHTS = {"Ontology quality": 0.40, "Agent performance": 0.35, "Governance": 0.25}
GRADES = ((85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F"))


@dataclass
class Criterion:
    name: str
    max_points: float
    earned: Optional[float]  # None = not assessed
    detail: str
    recommendation: str = ""

    @property
    def assessed(self) -> bool:
        return self.earned is not None

    @property
    def lost(self) -> float:
        return 0.0 if self.earned is None else self.max_points - self.earned


@dataclass
class Pillar:
    name: str
    weight: float
    criteria: List[Criterion]

    @property
    def assessed(self) -> bool:
        return any(c.assessed for c in self.criteria)

    @property
    def score(self) -> Optional[float]:
        done = [c for c in self.criteria if c.assessed]
        if not done:
            return None
        return round(100 * sum(c.earned for c in done) / sum(c.max_points for c in done), 1)


@dataclass
class Gate:
    phase: str
    criterion: str
    passed: Optional[bool]  # None = unknown (evidence missing)
    actual: str
    target: str


@dataclass
class Scorecard:
    subject: str
    pillars: List[Pillar]
    gates: List[Gate] = field(default_factory=list)

    @property
    def overall(self) -> Optional[float]:
        scored = [p for p in self.pillars if p.score is not None]
        if not scored:
            return None
        total_weight = sum(p.weight for p in scored)
        return round(sum(p.score * p.weight for p in scored) / total_weight, 1)

    @property
    def grade(self) -> str:
        overall = self.overall
        if overall is None:
            return "-"
        return next(g for threshold, g in GRADES if overall >= threshold)

    @property
    def coverage(self) -> float:
        """Share of criteria (by points) that could be assessed with the evidence given."""
        crit = [c for p in self.pillars for c in p.criteria]
        return round(sum(c.max_points for c in crit if c.assessed) / sum(c.max_points for c in crit), 2)

    def _next_gate(self):
        """(phase reached, next phase, its failing/unknown gates)."""
        reached = None
        for phase in ("Pilot", "Scale"):
            gates = [g for g in self.gates if g.phase == phase]
            open_gates = [g for g in gates if not g.passed]
            if gates and not open_gates:
                reached = phase
                continue
            return reached, phase, open_gates
        return reached, None, []

    @property
    def phase_reached(self) -> str:
        reached, nxt, open_gates = self._next_gate()
        head = f"{reached} gate passed" if reached else "pilot gate not passed"
        if nxt is None:
            return head
        failing = [g.criterion for g in open_gates if g.passed is False]
        unknown = [g.criterion for g in open_gates if g.passed is None]
        parts = []
        if failing:
            parts.append(f"failing: {', '.join(failing)}")
        if unknown:
            parts.append(f"unknown: {', '.join(unknown)}")
        return f"{head} - {nxt.lower()} gate {'; '.join(parts)}" if reached else f"{head} ({'; '.join(parts)})"

    def recommendations(self, limit: Optional[int] = None) -> List[str]:
        weighted = []
        for p in self.pillars:
            assessed_max = sum(c.max_points for c in p.criteria if c.assessed) or 1
            for c in p.criteria:
                if c.recommendation and (c.lost > 0.05 or not c.assessed):
                    # overall points this criterion could recover
                    impact = p.weight * 100 * (c.lost if c.assessed else c.max_points) / assessed_max
                    weighted.append((impact, c.assessed, f"[{p.name}] {c.recommendation}"))
        weighted.sort(key=lambda x: (not x[1], -x[0]))
        recs = [f"{text} (+{impact:.1f} pts)" if assessed else f"{text} (not assessed yet)"
                for impact, assessed, text in weighted if assessed]
        _, nxt, open_gates = self._next_gate()
        for g in open_gates:
            if g.passed is False:
                recs.append(f"[{nxt} gate] {g.criterion} is {g.actual}; target {g.target}")
            else:
                recs.append(f"[{nxt} gate] provide evidence for: {g.criterion} (target {g.target})")
        recs += [f"{text} (not assessed yet)" for _, assessed, text in weighted if not assessed]
        recs = list(dict.fromkeys(recs))
        return recs[:limit] if limit else recs

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subject": self.subject, "overall": self.overall, "grade": self.grade, "coverage": self.coverage,
            "phase": self.phase_reached,
            "pillars": {p.name: {"score": p.score, "weight": p.weight,
                                 "criteria": [c.__dict__ for c in p.criteria]} for p in self.pillars},
            "gates": [g.__dict__ for g in self.gates], "recommendations": self.recommendations(),
        }

    def render(self) -> str:
        overall = "n/a" if self.overall is None else f"{self.overall:.0f}/100"
        lines = [f"# Autology readiness scorecard - {self.subject}", "",
                 f"**Overall: {overall} (grade {self.grade})** · evidence coverage {self.coverage:.0%}  ",
                 f"**Roadmap:** {self.phase_reached}", "",
                 "_The score rates how well the deployment is built on the evidence given; the phase gates check "
                 "scope and business targets from the roadmap. A high score with open gates means: well built, "
                 "not yet big or valuable enough for the next phase._", "",
                 "| Pillar | Weight | Score |", "|---|---|---|"]
        for p in self.pillars:
            lines.append(f"| {p.name} | {p.weight:.0%} | {'not assessed' if p.score is None else f'{p.score:.0f}'} |")
        for p in self.pillars:
            lines += ["", f"## {p.name}", "", "| Criterion | Points | Detail |", "|---|---|---|"]
            for c in p.criteria:
                pts = "n/a" if not c.assessed else f"{c.earned:.1f} / {c.max_points:.0f}"
                lines.append(f"| {c.name} | {pts} | {c.detail} |")
        if self.gates:
            lines += ["", "## Phase gates", "", "| Phase | Criterion | Actual | Target | Result |", "|---|---|---|---|---|"]
            for g in self.gates:
                mark = {True: "pass", False: "FAIL", None: "unknown"}[g.passed]
                lines.append(f"| {g.phase} | {g.criterion} | {g.actual} | {g.target} | {mark} |")
        recs = self.recommendations(10)
        if recs:
            lines += ["", "## Top recommendations", ""] + [f"{i}. {r}" for i, r in enumerate(recs, 1)]
        return "\n".join(lines) + "\n"


# -- helpers -------------------------------------------------------------------
def _linear(value: float, zero_at: float, full_at: float) -> float:
    """0..1, linear between ``zero_at`` and ``full_at`` (works for either direction)."""
    if zero_at == full_at:
        return 1.0 if value >= full_at else 0.0
    frac = (value - zero_at) / (full_at - zero_at)
    return max(0.0, min(1.0, frac))


def _pct(x: float) -> str:
    return f"{x:.0%}"


# -- pillars -------------------------------------------------------------------
def _ontology_pillar(onto: Ontology, tools, graph) -> Pillar:
    crit: List[Criterion] = []
    findings = lint(onto, tools)
    errors = sum(f.level == "error" for f in findings)
    warnings = sum(f.level == "warning" for f in findings)
    infos = sum(f.level == "info" for f in findings)
    earned = max(0.0, 25 - 10 * errors - 4 * warnings - 1 * infos)
    worst = next((f for lvl in ("error", "warning", "info") for f in findings if f.level == lvl), None)
    crit.append(Criterion("Lint findings", 25, earned, f"{errors} errors, {warnings} warnings, {infos} info",
                          f"fix lint {worst.code}: {worst.message}" if worst else ""))

    n_q = len(onto.questions)
    declared = 10 * min(1.0, n_q / 3)
    if graph is not None and n_q:
        report = graph.check_competency()
        checked = [ok for _, _, ok in report if ok is not None]
        answered = 10 * (sum(checked) / len(checked)) if checked else 0.0
        detail = f"{n_q} declared, {sum(checked)}/{len(checked)} answered as expected"
        rec = ("add `expect` answers to competency questions" if not checked else
               "fix the model or data so every competency question answers as expected"
               if sum(checked) < len(checked) else "")
        if n_q < 3:
            rec = "declare at least 3 competency questions that the business needs answered"
        crit.append(Criterion("Competency questions", 20, declared + answered, detail, rec))
    else:
        crit.append(Criterion("Competency questions (declared)", 10, declared, f"{n_q} declared",
                              "" if n_q >= 3 else "declare at least 3 competency questions"))
        crit.append(Criterion("Competency questions (answered)", 10, None, "no sample data given",
                              "validate competency questions against sample data (`validate --data`)"))

    read_guard = {r.params["field"] for r in onto.rules_of("data_access")}
    write_guard = {r.params["field"] for r in onto.rules_of("write_access")}
    sensitive = [(f"{e.name}.{a.name}", a.sensitivity) for e in onto.entities.values()
                 for a in e.attributes.values() if a.sensitivity in ("pii", "confidential", "restricted")]
    if sensitive:
        guarded = [ref for ref, s in sensitive
                   if (ref in read_guard if s in ("pii", "confidential") else ref in write_guard)]
        unguarded = sorted(set(r for r, _ in sensitive) - set(guarded))
        crit.append(Criterion("Security by design", 20, 20 * len(guarded) / len(sensitive),
                              f"{len(guarded)}/{len(sensitive)} sensitive fields guarded",
                              f"add access rules for {', '.join(unguarded)}" if unguarded else ""))
    else:
        crit.append(Criterion("Security by design", 20, 12, "no attributes tagged pii/confidential/restricted",
                              "tag sensitive attributes (pii, restricted) so access rules can be enforced and linted"))

    if tools is not None:
        caps = set(tools.capabilities())
        covered = [a for a in onto.actions.values() if a.capability in caps]
        missing = sorted({a.capability for a in onto.actions.values()} - caps)
        crit.append(Criterion("Tool coverage", 15, 15 * len(covered) / max(1, len(onto.actions)),
                              f"{len(covered)}/{len(onto.actions)} actions have a tool",
                              f"integrate tools for {', '.join(missing)}" if missing else ""))
    else:
        crit.append(Criterion("Tool coverage", 15, None, "no tool registry given",
                              "score with the tool registry to check every action can be executed"))

    related = {r.source for r in onto.relationships} | {r.target for r in onto.relationships}
    rel_frac = len(related & set(onto.entities)) / max(1, len(onto.entities))
    described = [a for a in onto.actions.values() if a.description] + \
                [r for r in onto.rules if r.description]
    desc_frac = len(described) / max(1, len(onto.actions) + len(onto.rules))
    rec = ""
    if rel_frac < 1:
        rec = "link isolated entities with first-class relationships"
    elif desc_frac < 1:
        rec = "describe every action and rule (they are shown to reviewers and LLMs)"
    crit.append(Criterion("Semantic clarity", 10, 5 * rel_frac + 5 * desc_frac,
                          f"{rel_frac:.0%} of entities related, {desc_frac:.0%} of actions/rules described", rec))

    try:
        parse_version(onto.version)
        ok = True
    except VersionError:
        ok = False
    crit.append(Criterion("Versioning", 10, (6 if ok else 0) + (4 if onto.modules else 0),
                          f"version {onto.version} ({'semver' if ok else 'not semver'}), "
                          f"{len(onto.modules)} modules",
                          "use MAJOR.MINOR.PATCH versions so releases can be checked" if not ok else
                          ("split the ontology into domain modules (imports) as it grows" if not onto.modules else "")))
    return Pillar("Ontology quality", PILLAR_WEIGHTS["Ontology quality"], crit)


def _agent_pillar(results: List, budget: Optional[float]) -> Pillar:
    if not results:
        missing = "no agent runs given"
        rec = "run agents (e.g. a simulated pilot batch) and score the results"
        return Pillar("Agent performance", PILLAR_WEIGHTS["Agent performance"], [
            Criterion(name, pts, None, missing, rec) for name, pts in
            (("Resolution rate", 30), ("Unplanned hand-offs", 25), ("Straight-through rate", 15),
             ("Cost efficiency", 15), ("Self-healing", 15))])
    m = metrics(results)
    stops = m.by_outcome.get("policy_stop", 0)
    crit = [
        Criterion("Resolution rate", 30, 30 * _linear(m.resolution_rate, 0.5, 0.9),
                  f"{_pct(m.resolution_rate)} completed or correctly stopped by policy "
                  f"({m.by_outcome.get('completed', 0)} completed, {stops} policy stops; target 90%)",
                  "raise resolution: review unplanned escalation reasons and ontology gaps"),
        Criterion("Unplanned hand-offs", 25, 25 * _linear(m.unplanned_handoff_rate, 0.5, 0.1),
                  f"{_pct(m.unplanned_handoff_rate)} tool failures, gaps, loops, missing permissions, pauses or "
                  "suspensions (target <= 10%)",
                  "cut unplanned hand-offs: model the missing recovery paths the gap report lists"),
        Criterion("Straight-through rate", 15, 15 * _linear(m.straight_through_rate, 0.0, 0.7),
                  f"{_pct(m.straight_through_rate)} completed with no human (target 70%)",
                  "review whether human-review thresholds can be raised for low-risk cases"),
    ]
    cpt = m.cost_per_completed_task
    if m.llm_unpriced_tokens:  # an unknown cost is not a low cost
        crit.append(Criterion("Cost efficiency", 15, 0,
                              f"cost unknown: {m.llm_unpriced_tokens} tokens from models with no price "
                              f"({', '.join(m.unpriced_models) or 'unnamed'})",
                              "register a price for every model (reasoners.register_price or the suite's prices)"))
    elif budget and cpt is None:
        crit.append(Criterion("Cost efficiency", 15, 0, "no completed tasks: cost per completed task cannot be "
                              "measured", "make tasks complete before judging their cost"))
    elif budget:
        crit.append(Criterion("Cost efficiency", 15, 15 * _linear(cpt, 2 * budget, budget),
                              f"{cpt:.2f} per completed task (budget {budget:.2f})",
                              "lower cost per task: cheaper tools first, route simple decisions to small models"))
    else:
        shown = "n/a (nothing completed)" if cpt is None else f"{cpt:.2f}"
        crit.append(Criterion("Cost efficiency", 15, None, f"{shown} per completed task; "
                              "no budget given", "set a cost budget per completed task to score cost efficiency"))
    healed_pool = [r for r in results if r.audit.events("tool.error")]
    if healed_pool:
        healed = sum(1 for r in healed_pool if r.completed) / len(healed_pool)
        crit.append(Criterion("Self-healing", 15, 15 * healed,
                              f"{sum(1 for r in healed_pool if r.completed)}/{len(healed_pool)} runs with tool "
                              "failures still completed",
                              "add fallback tools or retry/backoff policies to actions whose tools fail"))
    else:
        crit.append(Criterion("Self-healing", 15, None, "no tool failures observed",
                              "inject tool faults in a simulated run to test failure policies"))
    return Pillar("Agent performance", PILLAR_WEIGHTS["Agent performance"], crit)


def _governance_pillar(onto: Ontology, results: List) -> Pillar:
    kinds = {r.kind for r in onto.rules}
    families = {
        "process (mandatory steps / prohibitions)": bool(kinds & {"mandatory_step", "prohibition"}),
        "human review": "human_review" in kinds,
        "access control": bool(kinds & {"data_access", "write_access", "action_access"}),
    }
    missing = [k for k, ok in families.items() if not ok]
    crit = [Criterion("Rule coverage", 20, 20 * sum(families.values()) / len(families),
                      f"{sum(families.values())}/3 rule families, {len(onto.rules)} rules",
                      f"add {', '.join(missing)} rules" if missing else "")]
    mv = onto.settings.get("max_violations")
    crit.append(Criterion("Access revocation", 10, 10 if mv else 0,
                          f"suspend after {mv} violations" if mv else "no max_violations setting",
                          "" if mv else "set settings.max_violations so misbehaving agents are suspended"))
    if results:
        intact = sum(1 for r in results if r.audit.verify())
        crit.append(Criterion("Audit integrity", 25, 25 * intact / len(results),
                              f"{intact}/{len(results)} audit trails verify",
                              "investigate tampered audit trails immediately"))
        m = metrics(results)
        per_task = m.governance_denials / m.tasks
        suspended = m.by_status.get("suspended", 0)
        crit.append(Criterion("Rule violations", 20, 20 * _linear(per_task, 0.5, 0.0),
                              f"{m.governance_denials} denied proposals ({per_task:.2f}/task), {suspended} suspensions",
                              "find why agents propose forbidden actions (reasoner prompts, stale plans)"))
        gaps = ontology_gaps(results)
        crit.append(Criterion("Ontology gaps", 25, max(0.0, 25 - 5 * len(gaps)),
                              f"{len(gaps)} distinct gaps in execution logs",
                              f"close ontology gap: {gaps[0].suggestion}" if gaps else ""))
    else:
        for name, pts in (("Audit integrity", 25), ("Rule violations", 20), ("Ontology gaps", 25)):
            crit.append(Criterion(name, pts, None, "no agent runs given",
                                  "score with agent runs to assess audit, violations and gaps"))
    return Pillar("Governance", PILLAR_WEIGHTS["Governance"], crit)


def _gates(onto: Ontology, results: List, roi: Optional[float], tasks_per_month: Optional[float]) -> List[Gate]:
    m = metrics(results) if results else None
    unplanned = m.unplanned_handoff_rate if m else None
    agents = {e.data.get("agent") for r in results for e in r.audit.events("run.start")} if results else set()
    agents |= {e.data.get("to_agent") for r in results for e in r.audit.events("delegate")} if results else set()
    agents.discard(None)

    def gate(phase, name, actual, target, passed):
        return Gate(phase=phase, criterion=name, passed=passed,
                    actual=actual if actual is not None else "unknown", target=target)

    n_ent, n_rules = len(onto.entities), len(onto.rules)
    gates = [
        gate("Pilot", "Ontology scope", f"{n_ent} entities, {n_rules} rules", ">= 5 entities, >= 10 rules",
             n_ent >= 5 and n_rules >= 10),
        gate("Pilot", "Agent success rate", _pct(m.resolution_rate) if m else None, "> 90% resolved",
             None if m is None else m.resolution_rate > 0.9),
        gate("Pilot", "Unplanned human intervention", _pct(unplanned) if m else None, "< 10%",
             None if m is None else unplanned < 0.1),
        gate("Pilot", "ROI", None if roi is None else _pct(roi), "> 200%", None if roi is None else roi > 2.0),
        gate("Scale", "Ontology scope", f"{n_ent} entities, {n_rules} rules", ">= 50 entities, >= 100 rules",
             n_ent >= 50 and n_rules >= 100),
        gate("Scale", "Agents in operation", str(len(agents)) if results else None, "> 10",
             None if not results else len(agents) > 10),
        gate("Scale", "Tasks per month", None if tasks_per_month is None else f"{tasks_per_month:,.0f}", "> 10,000",
             None if tasks_per_month is None else tasks_per_month > 10_000),
    ]
    return gates


def score_deployment(ontology: Ontology, results: Iterable = (), *, tools=None, graph=None,
                     cost_budget: Optional[float] = None, roi: Optional[float] = None,
                     tasks_per_month: Optional[float] = None, subject: Optional[str] = None) -> Scorecard:
    """Score an Autology deployment.

    ``results``: :class:`~autology.agent.RunResult` objects from real or simulated runs.
    ``tools``: a :class:`~autology.tools.ToolRegistry` (or merged registry) for coverage checks.
    ``graph``: a :class:`~autology.graph.KnowledgeGraph` with sample data for competency questions.
    ``cost_budget``: target cost per completed task. ``roi``: e.g. ``economics.evaluate(model).roi``.
    """
    results = list(results)
    pillars = [_ontology_pillar(ontology, tools, graph), _agent_pillar(results, cost_budget),
               _governance_pillar(ontology, results)]
    return Scorecard(subject or ontology.ref, pillars, _gates(ontology, results, roi, tasks_per_month))


def score_ontology(ontology: Ontology, *, tools=None, graph=None) -> Scorecard:
    """Ontology-only scorecard (no runs): useful as a CI check on every ontology change."""
    return score_deployment(ontology, (), tools=tools, graph=graph)
