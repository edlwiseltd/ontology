"""Operational metrics, compliance reports and ontology-gap analysis from agent runs.

* :func:`metrics`            - success rate, human-intervention rate, cost per task...
* :func:`compliance_report`  - per rule: how often it applied, was satisfied, denied
                               or sent to review ("100% of sign_contract executions
                               satisfied R-LEGAL-001");
* :func:`ontology_gaps`      - feedback loop: what the execution logs say is missing
                               from the ontology (unmodelled outcomes, undeclared
                               fields, missing capabilities, dead ends).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .agent import RunResult

HUMAN_STATUSES = ("blocked", "escalated", "paused", "suspended")
POLICY_MARKERS = ("prohibited:", "mandatory step")


def classify(result: RunResult) -> str:
    """Outcome class of a run.

    ``completed``    - goal reached;
    ``policy_stop``  - correctly stopped by governance: a human reviewer declined, or the only
                       paths to the goal violate a prohibition / mandatory-step rule (e.g. a
                       sanctioned party, a failed due-diligence check). This is the system working;
    ``pending``      - awaiting a human review decision (a planned hand-off, still open);
    ``unplanned``    - everything else: tool failures (including runs deferred for a retry after
                       one), unmodelled outcomes, missing capabilities or permissions, loops,
                       paused or suspended agents.
    """
    if result.status == "completed":
        return "completed"
    if result.status == "awaiting_review":
        return "pending"
    if result.status == "blocked":
        return "policy_stop"
    esc = result.escalation
    if (result.status == "escalated" and esc and esc.reason.startswith("no compliant path")
            and esc.details and all(any(m in d for m in POLICY_MARKERS) for d in esc.details)):
        return "policy_stop"
    return "unplanned"


@dataclass
class Metrics:
    tasks: int
    by_status: Dict[str, int]
    success_rate: float  # completed / tasks
    straight_through_rate: float  # completed with no human touch
    human_intervention_rate: float  # needed a reviewer or a hand-off
    reviews: int
    escalations: Dict[str, int]
    delegations: int
    governance_denials: int
    avg_steps: float
    llm_cost_usd: float
    tool_cost: float
    llm_calls: int
    cost_per_task: float
    cost_per_completed_task: Optional[float] = None  # None when nothing completed: it cannot be measured
    avg_latency_ms: float = 0.0
    violations_by_principal: Dict[str, int] = field(default_factory=dict)
    by_outcome: Dict[str, int] = field(default_factory=dict)  # see classify()
    resolution_rate: float = 0.0  # (completed + correctly stopped by policy) / tasks
    unplanned_handoff_rate: float = 0.0  # unplanned / tasks
    llm_unpriced_tokens: int = 0  # tokens of models with no registered price: their cost is unknown
    unpriced_models: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return dict(self.__dict__)


def _rate(n: int, d: int) -> float:
    return round(n / d, 4) if d else 0.0


def _latency_ms(result: RunResult) -> float:
    from datetime import datetime

    entries = list(result.audit)
    if len(entries) < 2:
        return 0.0
    start, end = (datetime.fromisoformat(entries[i].timestamp) for i in (0, -1))
    return (end - start).total_seconds() * 1000


def metrics(results: Iterable[RunResult]) -> Metrics:
    results = list(results)
    n = len(results)
    by_status = Counter(r.status for r in results)
    reviewed = [r for r in results if r.audit.events("review")]
    # a run parked for a review needs a person before it can finish: that is a human intervention too
    human = [r for r in results if r.audit.events("review") or r.status in HUMAN_STATUSES
             or r.status == "awaiting_review"]
    straight = [r for r in results if r.completed and not r.audit.events("review")]
    escalations = Counter(r.escalation.to for r in results if r.escalation and r.status in HUMAN_STATUSES)
    llm = sum(r.costs.get("llm_usd", 0.0) for r in results)
    tools = sum(r.costs.get("tools", 0.0) for r in results)
    violators: Counter = Counter()
    for r in results:
        for e in r.audit.events("governance.deny"):
            violators[e.data.get("principal", "?")] += 1
    outcomes = Counter(classify(r) for r in results)
    return Metrics(
        tasks=n, by_status=dict(by_status), success_rate=_rate(by_status["completed"], n),
        straight_through_rate=_rate(len(straight), n), human_intervention_rate=_rate(len(human), n),
        reviews=sum(len(r.audit.events("review")) for r in results), escalations=dict(escalations),
        delegations=sum(len(r.audit.events("delegate")) for r in results),
        governance_denials=sum(violators.values()),
        avg_steps=round(sum(len(r.steps) for r in results) / n, 2) if n else 0.0,
        llm_cost_usd=round(llm, 6), tool_cost=round(tools, 4),
        llm_calls=int(sum(r.costs.get("llm_calls", 0) for r in results)),
        cost_per_task=round((llm + tools) / n, 6) if n else 0.0,
        cost_per_completed_task=round((llm + tools) / by_status["completed"], 6) if by_status["completed"] else None,
        avg_latency_ms=round(sum(_latency_ms(r) for r in results) / n, 3) if n else 0.0,
        violations_by_principal=dict(violators),
        by_outcome=dict(outcomes),
        resolution_rate=_rate(outcomes["completed"] + outcomes["policy_stop"], n),
        unplanned_handoff_rate=_rate(outcomes["unplanned"], n),
        llm_unpriced_tokens=int(sum(r.costs.get("llm_unpriced_tokens", 0) for r in results)),
        unpriced_models=sorted({e.data.get("model") for r in results for e in r.audit.events("decision")
                                if e.data.get("unpriced_tokens")} - {None}),
    )


@dataclass
class RuleStats:
    rule_id: str
    kind: str
    description: str
    satisfied: int = 0  # action executed with the rule applying and satisfied
    denied: int = 0  # proposals blocked by the rule
    reviews_approved: int = 0
    reviews_declined: int = 0

    @property
    def applications(self) -> int:
        return self.satisfied + self.denied + self.reviews_approved + self.reviews_declined


def rule_statistics(results: Iterable[RunResult], ontology) -> Dict[str, RuleStats]:
    stats = {r.id: RuleStats(r.id, r.kind, r.description) for r in ontology.rules}
    for res in results:
        decisions = {(e.data["step"], e.data["action"]): e for e in res.audit.events("decision")}
        for e in res.audit.events("step"):
            d = decisions.get((e.data["step"], e.data["action"]))
            for rid in (d.data.get("satisfied_rules", []) if d else []):
                if rid in stats:
                    stats[rid].satisfied += 1
        for e in res.audit.events("governance.deny"):
            for rid in e.data.get("rules", []):
                if rid in stats:
                    stats[rid].denied += 1
        for e in res.audit.events("review"):
            for rid in e.data.get("rules", []):
                if rid in stats:
                    if e.data.get("approved"):
                        stats[rid].reviews_approved += 1
                    else:
                        stats[rid].reviews_declined += 1
    return stats


def outcome_analysis(results: Iterable[RunResult], ontology) -> Dict[str, object]:
    """Link decisions to what happened afterwards (``outcome`` audit entries) and suggest changes.

    Per action: how many executed decisions were later judged, how many went wrong, and how many of those
    had been approved in a human review. Per rule: outcomes of the decisions the rule took part in.
    """
    actions: Dict[str, Dict[str, int]] = defaultdict(lambda: {"judged": 0, "good": 0, "bad": 0,
                                                              "reviewed_then_bad": 0, "unreviewed_bad": 0})
    rules: Dict[str, Dict[str, int]] = defaultdict(lambda: {"judged": 0, "good": 0, "bad": 0})
    runs = {"judged": 0, "good": 0, "bad": 0}
    for r in results:
        decisions: Dict[str, dict] = {}
        reviewed = set()
        for e in r.audit:
            if e.event == "decision":
                decisions[e.data.get("action")] = e.data
            elif e.event == "review" and e.data.get("approved"):
                reviewed.add(e.data.get("action"))
        for e in r.audit.events("outcome"):
            good, act = bool(e.data.get("good")), e.data.get("action")
            if act is None:
                runs["judged"] += 1
                runs["good" if good else "bad"] += 1
                continue
            a = actions[act.partition("@")[0]]
            a["judged"] += 1
            a["good" if good else "bad"] += 1
            if not good:
                a["reviewed_then_bad" if act in reviewed else "unreviewed_bad"] += 1
            d = decisions.get(act, {})
            for rid in set(d.get("rules") or []) | set(d.get("satisfied_rules") or []):
                rules[rid]["judged"] += 1
                rules[rid]["good" if good else "bad"] += 1
    by_id = {rule.id: rule for rule in ontology.rules}
    suggestions = []
    for rid, s in sorted(rules.items()):
        if not s["bad"] or rid not in by_id:
            continue
        rule = by_id[rid]
        if rule.kind == "human_review":
            suggestions.append(f"{rid} ({rule.description}): {s['bad']} of {s['judged']} judged decisions it sent "
                               "for review went wrong after approval; revisit its threshold or the reviewers' guidance")
        else:
            suggestions.append(f"{rid} ({rule.description}): {s['bad']} of {s['judged']} judged decisions it allowed "
                               "went wrong; check that its condition captures the risk")
    review_rules: Dict[str, List[str]] = defaultdict(list)
    for rule in ontology.rules_of("human_review"):
        review_rules[rule.params.get("action")].append(rule.id)
    for name, s in sorted(actions.items()):
        if not s["unreviewed_bad"]:
            continue
        if name not in review_rules:
            suggestions.append(f"{name}: {s['bad']} of {s['judged']} judged decisions went wrong and no human_review "
                               "rule covers it; consider adding one for the risky cases")
        else:  # a review rule exists, but its condition let these through
            suggestions.append(f"{name}: {s['unreviewed_bad']} of {s['judged']} judged decisions went wrong without "
                               f"a review ({', '.join(review_rules[name])} did not apply); consider widening the "
                               "condition")
    return {"runs": runs, "actions": dict(actions), "rules": dict(rules), "suggestions": suggestions}


def compliance_report(results: Iterable[RunResult], ontology, title: Optional[str] = None) -> str:
    results = list(results)
    m = metrics(results)
    stats = rule_statistics(results, ontology)
    chain_ok = all(r.audit.verify() for r in results)
    lines = [f"# {title or 'Autology compliance report'}", "",
             f"Ontology: {ontology.ref} (fingerprint {ontology.fingerprint[:16]})  ",
             f"Tasks: {m.tasks} - " + ", ".join(f"{k} {v}" for k, v in sorted(m.by_status.items())) + "  ",
             f"Audit trails intact: {'yes' if chain_ok else 'NO - TAMPERING DETECTED'}", ""]
    if m.llm_unpriced_tokens:
        lines += [f"> **Model cost unknown:** {m.llm_unpriced_tokens} tokens came from models with no price "
                  f"({', '.join(m.unpriced_models) or 'unnamed'}). Costs below leave them out; register a price.", ""]
    automatic = sum(1 for r in results for e in r.audit if e.event == "review" and e.data.get("automatic"))
    if automatic:
        lines += [f"> **{automatic} human review{'s were' if automatic != 1 else ' was'} decided automatically** "
                  "(by a script or policy, not a person). Treat these runs as a simulation, not evidence that "
                  "reviews took place.", ""]
    lines += ["## KPIs", "",
             "| Metric | Value |", "|---|---|",
             f"| Success rate (completed) | {m.success_rate:.0%} |",
             f"| Resolution rate (completed or correctly stopped by policy) | {m.resolution_rate:.0%} |",
             f"| Unplanned hand-offs | {m.unplanned_handoff_rate:.0%} |",
             f"| Straight-through (no human) | {m.straight_through_rate:.0%} |",
             f"| Human intervention rate | {m.human_intervention_rate:.0%} |",
             f"| Human reviews | {m.reviews} |",
             f"| Delegations to specialist agents | {m.delegations} |",
             f"| Governance denials | {m.governance_denials} |",
             f"| Avg steps per task | {m.avg_steps} |",
             f"| LLM calls / cost | {m.llm_calls} / ${m.llm_cost_usd:.4f} |",
             f"| Tool cost | {m.tool_cost:.2f} |",
             f"| Cost per task / per completed task | {m.cost_per_task:.4f} / "
             f"{'n/a (nothing completed)' if m.cost_per_completed_task is None else f'{m.cost_per_completed_task:.4f}'} |",
             f"| Avg agent latency | {m.avg_latency_ms:.1f} ms |", "",
             "## Rule activity", "",
             "| Rule | Kind | Applied | Satisfied | Reviewed (ok/declined) | Denied |",
             "|---|---|---|---|---|---|"]
    for s in stats.values():
        lines.append(f"| {s.rule_id} | {s.kind} | {s.applications} | {s.satisfied} | "
                     f"{s.reviews_approved}/{s.reviews_declined} | {s.denied} |")
    lines += ["", "Counts come from the audit logs: *Satisfied* is how often an executed action met the rule, "
                  "*Denied* how often the rule stopped an action. Governance checks every rule before an action "
                  "runs; whether the logs themselves are intact is the audit line above.", ""]
    learned = outcome_analysis(results, ontology)
    if learned["actions"] or learned["runs"]["judged"]:
        lines += ["## Decisions and their outcomes", "",
                  "What happened after decisions, as recorded by people (`outcome` audit entries).", "",
                  "| Action | Judged | Bad | Good | Approved in review, then bad |", "|---|---|---|---|---|"]
        lines += [f"| {a} | {s['judged']} | {s['bad']} | {s['good']} | {s['reviewed_then_bad']} |"
                  for a, s in sorted(learned["actions"].items())]
        if learned["runs"]["judged"]:
            lines += ["", f"Whole runs judged: {learned['runs']['judged']} ({learned['runs']['bad']} bad)."]
        if learned["suggestions"]:
            lines += ["", "Suggested changes:", ""] + [f"- {s}" for s in learned["suggestions"]]
        lines.append("")
    if m.escalations:
        lines += ["## Hand-offs to humans", "", "| To | Count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(m.escalations.items())]
        lines.append("")
    gaps = ontology_gaps(results)
    if gaps:
        lines += ["## Ontology gaps (feedback loop)", ""]
        lines += [f"- **{g.kind}** ({g.count}x): {g.detail} - _{g.suggestion}_" for g in gaps]
        lines.append("")
    return "\n".join(lines)


@dataclass
class Gap:
    kind: str
    detail: str
    suggestion: str
    count: int = 1


_PATTERNS = [
    (re.compile(r"tool returned unknown outcome '([^']+)'"), "unmodelled outcome",
     "add outcome {0!r} (with its effects) to action {action!r}"),
    (re.compile(r"tool attempted to write undeclared field (\S+)"), "undeclared field",
     "declare {0} in the writes of action {action!r} (and in the entity if missing)"),
    (re.compile(r"no tool provides capability '([^']+)'"), "missing capability",
     "integrate a tool for capability {0!r} or allow an existing one"),
    (re.compile(r"no sequence of ontology actions leads"), "dead end",
     "model the missing action that leads from this state toward the goal"),
    (re.compile(r"attempted \d+ times without reaching the goal"), "loop",
     "add a recovery action/outcome so repeated failures of {action!r} can be resolved"),
]


def ontology_gaps(results: Iterable[RunResult]) -> List[Gap]:
    found: Dict[tuple, Gap] = {}
    for res in results:
        esc = res.escalation
        if not esc:
            continue
        texts = [esc.reason] + list(esc.details)
        for text in texts:
            for pattern, kind, suggestion in _PATTERNS:
                m = pattern.search(text)
                if m:
                    action = esc.action or "?"
                    detail = f"{action}: {text}" if esc.action else text
                    key = (kind, m.group(0), action)
                    if key in found:
                        found[key].count += 1
                    else:
                        found[key] = Gap(kind, detail, suggestion.format(*m.groups(), action=action))
    return sorted(found.values(), key=lambda g: (-g.count, g.kind))
