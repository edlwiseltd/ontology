"""Governance layer: enforces the ontology's immutable rules.

The governance layer sits between *deciding* and *doing*. Whatever proposes
the next action - the built-in planner, an LLM, or a buggy custom reasoner -
the action only runs if :meth:`GovernanceLayer.evaluate` allows it. Rules:

``mandatory_step``  ``step`` must have completed (optionally with ``outcome``)
                    before ``before`` may run; ``reset_by`` actions invalidate
                    an earlier completion (e.g. revising a contract voids the
                    previous legal review).
``human_review``    ``action`` needs sign-off from a human holding ``reviewer``.
``data_access``     ``field`` may only be read by principals holding one of
                    ``roles``; others see it redacted.
``prohibition``     ``action`` must never run while ``when`` holds.

Any rule may carry a ``when`` condition that scopes it to a context, e.g.
``Customer.industry == 'Financial Services'``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from .ontology import ActionType, Ontology, Rule
from .state import WorldState

REDACTED = "***redacted***"


class Verdict(str, Enum):
    ALLOW = "allow"
    REVIEW = "review"  # allowed once a human with the reviewer role approves
    DENY = "deny"


@dataclass(frozen=True)
class Principal:
    """Who is acting: an agent identity and the roles granted to it."""

    name: str
    roles: FrozenSet[str] = frozenset()

    def __init__(self, name: str, roles=()):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "roles", frozenset(roles))


@dataclass
class Decision:
    verdict: Verdict
    action: str
    reasons: List[str] = field(default_factory=list)
    rule_ids: List[str] = field(default_factory=list)
    reviewers: Tuple[str, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.verdict is not Verdict.DENY


class IntegrityError(RuntimeError):
    """The ontology changed after governance was bound to it."""


class GovernanceLayer:
    def __init__(self, ontology: Ontology):
        self.ontology = ontology
        self._fingerprint = ontology.fingerprint

    # -- integrity ------------------------------------------------------
    def check_integrity(self) -> None:
        if self.ontology.fingerprint != self._fingerprint:
            raise IntegrityError("ontology fingerprint changed; refusing to execute")

    # -- rule evaluation ------------------------------------------------
    @staticmethod
    def _mandatory_satisfied(rule: Rule, state: WorldState) -> bool:
        outcome = state.steps.get(rule.params["step"])
        if outcome is None:
            return False
        wanted = rule.params.get("outcome")
        return wanted is None or outcome == wanted

    def _hard_violations(self, action: ActionType, state: WorldState, principal: Principal,
                         check_preconditions: bool = True) -> List[Tuple[Optional[str], str]]:
        problems: List[Tuple[Optional[str], str]] = []
        if check_preconditions:
            for expr in action.requires:
                if not expr.evaluate(state.get):
                    problems.append((None, f"precondition not met: {expr}"))
        for rule in self.ontology.rules:
            p = rule.params
            if rule.kind == "mandatory_step" and p["before"] == action.name and rule.applies(state.get):
                if not self._mandatory_satisfied(rule, state):
                    need = p["step"] + (f" (outcome {p['outcome']})" if p.get("outcome") else "")
                    problems.append((rule.id, f"mandatory step {need} has not been completed: {rule.description}"))
            elif rule.kind == "prohibition" and p["action"] == action.name and rule.applies(state.get):
                problems.append((rule.id, f"prohibited: {rule.description}"))
            elif rule.kind == "data_access" and p["field"] in action.reads and rule.applies(state.get):
                if not principal.roles & set(p["roles"]):
                    problems.append((rule.id, f"{principal.name} may not read {p['field']}: {rule.description}"))
        return problems

    def permits_in_plan(self, action: ActionType, state: WorldState, principal: Principal) -> bool:
        """Planner hook: would the hard rules allow this action (ignoring human review)?"""
        return not self._hard_violations(action, state, principal, check_preconditions=False)

    def evaluate(self, action: ActionType | str, state: WorldState, principal: Principal) -> Decision:
        self.check_integrity()
        if isinstance(action, str):
            if action not in self.ontology.actions:
                return Decision(Verdict.DENY, action, [f"{action!r} is not an action in the ontology"])
            action = self.ontology.actions[action]
        problems = self._hard_violations(action, state, principal)
        if problems:
            return Decision(Verdict.DENY, action.name, [m for _, m in problems],
                            [rid for rid, _ in problems if rid])
        reviews = [r for r in self.ontology.rules_of("human_review")
                   if r.params["action"] == action.name and r.applies(state.get)]
        if reviews:
            return Decision(Verdict.REVIEW, action.name, [r.description for r in reviews],
                            [r.id for r in reviews], tuple(dict.fromkeys(r.params["reviewer"] for r in reviews)))
        return Decision(Verdict.ALLOW, action.name, ["all rules satisfied"])

    def record_completion(self, action: ActionType, outcome: str, state: WorldState) -> None:
        """Update step bookkeeping after an action ran (including resets)."""
        for rule in self.ontology.rules_of("mandatory_step"):
            if action.name in rule.params.get("reset_by", ()):
                state.steps.pop(rule.params["step"], None)
        state.steps[action.name] = outcome

    # -- data access ----------------------------------------------------
    def can_read(self, ref: str, state: WorldState, principal: Principal) -> bool:
        for rule in self.ontology.rules_of("data_access"):
            if rule.params["field"] == ref and rule.applies(state.get):
                if not principal.roles & set(rule.params["roles"]):
                    return False
        return True

    def redacted_view(self, state: WorldState, principal: Principal) -> Dict[str, Dict[str, Any]]:
        """State as the principal is allowed to see it (used for reasoning / LLM prompts)."""
        view: Dict[str, Dict[str, Any]] = {}
        for entity, values in state.entities.items():
            view[entity] = {attr: (val if self.can_read(f"{entity}.{attr}", state, principal) else REDACTED)
                            for attr, val in values.items()}
        return view
