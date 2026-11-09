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
    ``pending``      - deferred, waiting for a retry window;
    ``unplanned``    - everything else: tool failures, unmodelled outcomes, missing capabilities
                       or permissions, loops, paused or suspended agents.
    """
    if result.status == "completed":
        return "completed"
    if result.status == "deferred":
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
    cost_per_completed_task: float = 0.0  # what outcome-based pricing should be benchmarked against
    avg_latency_ms: float = 0.0
    violations_by_principal: Dict[str, int] = field(default_factory=dict)
    by_outcome: Dict[str, int] = field(default_factory=dict)  # see classify()
    resolution_rate: float = 0.0  # (completed + correctly stopped by policy) / tasks
    unplanned_handoff_rate: float = 0.0  # unplanned / tasks

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
    human = [r for r in results if r.audit.events("review") or r.status in HUMAN_STATUSES]
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
        cost_per_completed_task=round((llm + tools) / by_status["completed"], 6) if by_status["completed"] else 0.0,
        avg_latency_ms=round(sum(_latency_ms(r) for r in results) / n, 3) if n else 0.0,
        violations_by_principal=dict(violators),
        by_outcome=dict(outcomes),
        resolution_rate=_rate(outcomes["completed"] + outcomes["policy_stop"], n),
        unplanned_handoff_rate=_rate(outcomes["unplanned"], n),
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


def compliance_report(results: Iterable[RunResult], ontology, title: Optional[str] = None) -> str:
    results = list(results)
    m = metrics(results)
    stats = rule_statistics(results, ontology)
    chain_ok = all(r.audit.verify() for r in results)
    lines = [f"# {title or 'Autology compliance report'}", "",
             f"Ontology: {ontology.ref} (fingerprint {ontology.fingerprint[:16]})  ",
             f"Tasks: {m.tasks} - " + ", ".join(f"{k} {v}" for k, v in sorted(m.by_status.items())) + "  ",
             f"Audit trails intact: {'yes' if chain_ok else 'NO - TAMPERING DETECTED'}", "",
             "## KPIs", "",
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
             f"| Cost per task / per completed task | {m.cost_per_task:.4f} / {m.cost_per_completed_task:.4f} |",
             f"| Avg agent latency | {m.avg_latency_ms:.1f} ms |", "",
             "## Rule adherence", "",
             "| Rule | Kind | Applied | Satisfied | Reviewed (ok/declined) | Denied | Adherence |",
             "|---|---|---|---|---|---|---|"]
    for s in stats.values():
        executed = s.satisfied + s.reviews_approved
        # governance checks every rule before an action runs, so executed actions always comply
        adherence = "100%" if executed else "-"
        lines.append(f"| {s.rule_id} | {s.kind} | {s.applications} | {s.satisfied} | "
                     f"{s.reviews_approved}/{s.reviews_declined} | {s.denied} | {adherence} |")
    lines += ["", "Adherence counts executed actions only: governance evaluates every rule before an action "
                  "runs, so an action cannot execute with an unsatisfied rule. Denials show where agents or "
                  "cases were stopped by the rule.", ""]
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
