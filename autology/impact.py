"""ImpactAgent: "an event happened - who and what is affected?"

Given an event instance in the knowledge graph (an engineering change, a machine
failure, a quality return...), the agent walks the ontology's declared
``impact_rules`` - relationship paths, the equivalent of SPARQL property paths -
and returns:

* every affected instance, grouped by entity type, each with the **reasoning
  chain** that connects it to the event (``ECN-7 -changes-> PT-02
  <-produces- WO-03 -hasProcess-> WO-03/20 -requiresMachine-> EQ_05``);
* the affected resources that are **unavailable** (per the scheduling spec's
  availability conditions);
* **risks**: affected tasks whose resource requirements are degraded (some
  alternatives unavailable) or broken (none left);
* **adjustments** to apply when rescheduling (e.g. ECN duration factor,
  requalification release time).

The output is a cleaned set of constraints for :class:`autology.scheduling.ScheduleAgent`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .graph import Instance, KnowledgeGraph
from .ontology import Ontology, OntologyError


@dataclass
class Risk:
    severity: str  # "critical": no resource left for a requirement; "warning": reduced capacity
    task: str
    job: Optional[str]
    message: str
    chain: str = ""


@dataclass
class ImpactReport:
    event_id: str
    event_type: str
    rule_ids: List[str]
    affected: Dict[str, List[str]] = field(default_factory=dict)  # entity type -> ids
    chains: Dict[str, str] = field(default_factory=dict)  # id -> reasoning chain from the event
    unavailable: List[str] = field(default_factory=list)  # affected resources that are not available
    risks: List[Risk] = field(default_factory=list)
    adjustments: Dict[str, Dict[str, float]] = field(default_factory=dict)  # task id -> {"duration_factor", "release"}

    def count(self, entity_type: str) -> int:
        return len(self.affected.get(entity_type, []))

    def explain(self, instance_id: str) -> str:
        return self.chains.get(instance_id, f"{instance_id} is not affected by {self.event_id}")

    def summary(self, ontology: Ontology) -> str:
        parts = [f"{len(ids)} {etype}" for etype, ids in self.affected.items()]
        spec = ontology.scheduling
        crit = sum(r.severity == "critical" for r in self.risks)
        line = f"{self.event_id} ({self.event_type}) affects " + (", ".join(parts) or "nothing")
        if spec:
            line += f"; {len(self.unavailable)} affected resources unavailable; {len(self.risks)} risks ({crit} critical)"
        return line

    def as_dict(self) -> Dict[str, Any]:
        return {"event_id": self.event_id, "event_type": self.event_type, "rule_ids": self.rule_ids,
                "affected": self.affected, "chains": self.chains, "unavailable": self.unavailable,
                "risks": [r.__dict__ for r in self.risks], "adjustments": self.adjustments}


def _edge(step: str, target: str) -> str:
    return f" <-{step[1:]}- {target}" if step.startswith("^") else f" -{step}-> {target}"


class ImpactAgent:
    def __init__(self, ontology: Ontology, graph: KnowledgeGraph):
        self.ontology = ontology
        self.graph = graph

    def is_available(self, inst: Instance) -> bool:
        spec = self.ontology.scheduling
        expr = spec.availability.get(inst.type) if spec else None
        if expr is None:
            return True
        return expr.evaluate(lambda e, a: inst.get(a) if e == inst.type else None)

    def apply_event(self, event_id: str) -> List[str]:
        """Apply the event's declared state changes to the graph (e.g. alert -> machine down). Returns touched ids."""
        event = self.graph.get(event_id)
        touched = []
        for rule in self.ontology.impact_rules:
            if rule.event != event.type:
                continue
            for path, values in rule.apply:
                frontier = [event]
                for step in path:
                    frontier = [n for inst in frontier for n in self.graph.neighbours(inst, step)]
                for inst in frontier:
                    inst.attributes.update(dict(values))
                    touched.append(inst.id)
        return touched

    def analyze(self, event_id: str, apply: bool = True) -> ImpactReport:
        """Trace the impact of ``event_id``. With ``apply`` the event's state changes are applied first
        (this mutates the graph - analyse a copy if you need the pre-event state)."""
        try:
            event = self.graph.get(event_id)
        except KeyError:
            raise OntologyError(f"unknown event instance {event_id!r}") from None
        if apply:
            self.apply_event(event_id)
        resolve = lambda e, a: event.get(a) if e == event.type else None  # noqa: E731
        rules = [r for r in self.ontology.impact_rules
                 if r.event == event.type and (r.when is None or r.when.evaluate(resolve))]
        report = ImpactReport(event.id, event.type, [r.id for r in rules])
        if not rules:
            return report
        order: Dict[str, List[str]] = {}
        for rule in rules:
            for path in rule.paths:
                frontier: List[Tuple[Instance, str]] = [(event, event.id)]
                for step in path:
                    nxt: List[Tuple[Instance, str]] = []
                    for inst, chain in frontier:
                        for n in self.graph.neighbours(inst, step):
                            c = chain + _edge(step, n.id)
                            if n.id not in report.chains:
                                report.chains[n.id] = c
                                order.setdefault(n.type, []).append(n.id)
                            nxt.append((n, c))
                    frontier = nxt
        report.affected = {t: ids for t, ids in order.items()}
        spec = self.ontology.scheduling
        if spec is None:
            return report
        resource_types = set(spec.resource_types(self.ontology))
        if event.type in resource_types and not self.is_available(event):
            report.unavailable.append(event.id)  # e.g. the broken machine itself
        for etype in resource_types:
            for rid in report.affected.get(etype, []):
                if not self.is_available(self.graph.get(rid)):
                    report.unavailable.append(rid)
        # risks + adjustments for affected tasks
        job_of = {}
        for job in self.graph.instances(spec.job):
            for t in self.graph.neighbours(job, spec.job_tasks):
                job_of[t.id] = job.id
        for tid in report.affected.get(spec.task, []):
            task = self.graph.get(tid)
            for req in spec.resources:
                linked = self.graph.neighbours(task, req.step)
                down = [r for r in linked if not self.is_available(r)]
                if not down:
                    continue
                ok = [r for r in linked if r not in down]
                names = ", ".join(r.id for r in down)
                chain = report.chains.get(tid, "")
                if req.alternatives and ok:
                    report.risks.append(Risk("warning", tid, job_of.get(tid),
                                             f"{tid} loses {names} ({req.step}); {len(ok)} alternative(s) left",
                                             chain))
                else:
                    report.risks.append(Risk("critical", tid, job_of.get(tid),
                                             f"{tid} cannot run: {names} ({req.step}) unavailable and no alternative",
                                             chain))
            for rule in rules:
                if tid in report.chains and rule.adjust:
                    adj = report.adjustments.setdefault(tid, {})
                    for key, ref in rule.adjust.items():
                        value = event.get(ref.partition(".")[2])
                        if isinstance(value, (int, float)):
                            adj[key] = float(value)
        return report
