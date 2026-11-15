"""Dry run of a model document: what would the engine's agent do with this model, before anything is published?

``simulate(document)`` loads the document with the strict loader, builds a throwaway agent with the engine's own
planner and governance, and runs one synthetic case toward a goal. It exists so that a proposed or drafted model
can be exercised during design (Studio's onboarding) without making it active.

What it is **not**: a run of the use case. Nothing is stored, no record is read or written, no configured tool
is called. Every action is performed by a stub that does nothing (environment ``simulated``); the audit trace is
an in-memory list, not a signed chain. A human review is never decided silently: the run parks at each review
and continues only with an explicit simulated decision in the request, given as one of the reviewer roles the
rule names. The answer says all of this itself, so it cannot be mistaken for evidence of a real run: the readiness
conditions (:mod:`autology.readiness`) count stored runs only.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .agent import DeferredApprover, ReviewDecision, WorkAgent
from .ontology import Ontology, OntologyError
from .tools import ToolRegistry, ToolResult

_SAMPLES: Dict[str, Any] = {"string": "sample", "number": 0, "integer": 0, "boolean": False, "date": "2026-01-01",
                            "datetime": "2026-01-01T00:00:00Z"}
_THRESHOLD = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*(>=|>)\s*(\d+(?:\.\d+)?)")
MAX_REVIEWS = 20


class SimulationError(ValueError):
    """The simulation cannot be made (the document, the goal, the case or a simulated decision is not usable)."""


def sample_case(onto: Ontology, document: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """One synthetic record per entity, in its initial state. Numbers that a human-review rule compares against
    a threshold are set at that threshold, so that the review the model asks for is exercised by default."""
    case: Dict[str, Dict[str, Any]] = {}
    for name, etype in onto.entities.items():
        case[name] = {"status": etype.initial_state,
                      **{a.name: _SAMPLES.get(a.type, "sample") for a in etype.attributes.values()}}
    for rule in document.get("rules") or []:
        if isinstance(rule, Mapping) and rule.get("type") == "human_review" and isinstance(rule.get("when"), str):
            for entity, attribute, op, number in _THRESHOLD.findall(rule["when"]):
                if entity in case and attribute in case[entity] and not isinstance(case[entity][attribute], bool) \
                        and isinstance(case[entity][attribute], (int, float)):
                    value = float(number) + (1 if op == ">" else 0)
                    case[entity][attribute] = int(value) if value == int(value) else value
    return case


def _roles(onto: Ontology) -> List[str]:
    """Every role an access rule names: the simulated agent may do what the model restricts by role."""
    return sorted({role for rule in onto.rules if rule.kind in ("action_access", "data_access", "write_access",
                                                               "row_access") for role in rule.params["roles"]})


def _plain(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if not isinstance(value, str) else value[:300]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in list(value)[:20]]
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in list(value.items())[:30]}
    return str(value)[:300]


def simulate(document: Any, case: Optional[Mapping[str, Any]] = None, goal: Optional[str] = None,
             roles: Optional[Iterable[str]] = None, approvals: Sequence[Mapping[str, Any]] = ()) -> Dict[str, Any]:
    """Run one synthetic case of ``document`` toward ``goal`` with stub tools; see the module docstring.

    ``approvals`` are the simulated review decisions, used in order as the run asks for them:
    ``{"action": name, "approved": bool, "as": reviewer role}``."""
    if not isinstance(document, Mapping):
        raise SimulationError("document: an ontology document")
    try:
        onto = Ontology.from_dict(dict(document))
    except OntologyError as exc:
        raise SimulationError(f"the model does not validate: {exc}") from None
    if not onto.goals:
        raise SimulationError("the model has no goal: nothing can be planned")
    goal = goal or sorted(onto.goals)[0]
    if goal not in onto.goals:
        raise SimulationError(f"goal: one of {sorted(onto.goals)}")
    if any(e.multiple for e in onto.entities.values()) and case is None:
        raise SimulationError("this model has multi-instance entities: give the case to simulate")
    if case is not None and not (isinstance(case, Mapping) and all(isinstance(v, (Mapping, list)) for v in case.values())):
        raise SimulationError("case: {entity: {attribute: value}}")
    used_case = {k: dict(v) if isinstance(v, Mapping) else v for k, v in (case or sample_case(onto, document)).items()}
    agent_roles = sorted(set(roles)) if roles is not None else _roles(onto)
    tools = ToolRegistry()
    for capability in sorted({a.capability for a in onto.actions.values()}):
        tools.register(f"simulated:{capability}", capability, lambda call: ToolResult(), environment="simulated")
    approver = DeferredApprover()
    agent = WorkAgent("simulation", onto, tools, roles=agent_roles, approver=approver)
    try:
        result = agent.run(goal, used_case, case_id="draft-simulation")
    except (OntologyError, KeyError, TypeError, ValueError) as exc:
        raise SimulationError(f"the case cannot be run: {exc}") from None
    waiting, decided = list(approvals), []
    pending: Optional[Dict[str, Any]] = None
    for _ in range(MAX_REVIEWS):
        if result.status != "awaiting_review":
            break
        request = approver.requests[-1]
        pending = {"action": request.action, "reviewers": list(request.reviewers), "reasons": list(request.reasons),
                   "rules": list(request.rule_ids), "facts": _plain(request.facts)}
        given = next((a for a in waiting if isinstance(a, Mapping) and a.get("action") == request.action), None)
        if given is None:
            break
        waiting.remove(given)
        role = given.get("as") or (request.reviewers[0] if len(request.reviewers) == 1 else None)
        if role not in request.reviewers or not isinstance(given.get("approved"), bool):
            raise SimulationError(f"a simulated decision on {request.action} is {{\"approved\": true or false, \"as\": "
                                  f"one of {list(request.reviewers)}}}")
        decided.append({"action": request.action, "approved": given["approved"], "as": role,
                        "note": "simulated decision: no person reviewed anything"})
        result = agent.resume(result, decision=ReviewDecision(given["approved"], f"simulated:{role}",
                                                              "simulated decision in a draft simulation", True))
        pending = None
    return {
        "simulated": True, "persisted": False,
        "notice": "A dry run of a model document: nothing was stored, no record was read or written, and every "
                  "action was performed by a stub that does nothing. It is not evidence of a real run.",
        "model": {"ref": onto.ref, "fingerprint": onto.fingerprint}, "goal": goal,
        "agent": {"roles": agent_roles, "tools": "one simulated stub per capability"},
        "case": _plain(used_case), "status": result.status,
        "steps": [{"index": s.index, "action": s.action, "verdict": s.verdict, "tool": s.tool, "outcome": s.outcome,
                   "reviewer": s.reviewer, "explanation": s.explanation[:300]} for s in result.steps],
        "pending_review": pending if result.status == "awaiting_review" else None,
        "reviews": decided,
        "escalation": None if result.escalation is None else {"reason": result.escalation.reason,
                                                               "action": result.escalation.action,
                                                               "details": list(result.escalation.details)[:10]},
        "refused": [{"action": d.action, "reasons": list(d.reasons)[:5]} for d in result.violations][:20],
        "final_state": _plain(result.state.entities),
        "audit": {"note": "in-memory trace of this simulation, not a stored signed audit chain",
                  "events": [{"seq": e.seq, "event": e.event, "data": _plain(e.data)} for e in result.audit][:400]},
    }
