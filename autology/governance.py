"""Governance layer: enforces the ontology's immutable rules.

The governance layer sits between *deciding* and *doing*. Whatever proposes
the next action - the built-in planner, an LLM, or a buggy custom reasoner -
the action only runs if :meth:`GovernanceLayer.evaluate` allows it.

``mandatory_step``  ``step`` must have completed (optionally with ``outcome``)
                    before ``before`` may run; ``reset_by`` actions void it.
``human_review``    ``action`` needs sign-off from a human holding ``reviewer``.
``data_access``     ``field`` may only be read by principals holding ``roles``.
``write_access``    ``field`` may only be modified by principals holding ``roles``
                    (e.g. "only Finance can modify payment terms").
``action_access``   ``action`` may only be executed by principals holding ``roles``.
``prohibition``     ``action`` must never run while ``when`` holds.

Any rule may carry a ``when`` condition (attribute-based access control).
Every decision carries provenance: which rules were satisfied, on which
facts. Principals that keep proposing forbidden actions are suspended
after ``settings.max_violations`` denials.
"""

from __future__ import annotations

from collections import Counter
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
    """Who is acting: an agent identity and the roles (attributes) granted to it."""

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
    rule_ids: List[str] = field(default_factory=list)  # rules that denied / require review
    reviewers: Tuple[str, ...] = ()
    satisfied: List[str] = field(default_factory=list)  # rules checked and satisfied
    facts: Dict[str, Any] = field(default_factory=dict)  # facts the decision relied on (redacted)

    @property
    def allowed(self) -> bool:
        return self.verdict is not Verdict.DENY

    def explanation(self) -> str:
        """Provenance sentence, e.g. "sign_contract allowed: satisfied R-LEGAL-001; facts Contract.value=48000"."""
        head = {Verdict.ALLOW: "allowed", Verdict.REVIEW: "requires human review",
                Verdict.DENY: "denied"}[self.verdict]
        parts = [f"{self.action} {head}"]
        if self.verdict is Verdict.DENY:
            parts.append("because " + "; ".join(self.reasons))
        else:
            if self.satisfied:
                parts.append("satisfied " + ", ".join(self.satisfied))
            if self.verdict is Verdict.REVIEW:
                parts.append("pending " + ", ".join(self.rule_ids))
        if self.facts:
            parts.append("facts " + ", ".join(f"{k}={v!r}" for k, v in sorted(self.facts.items())))
        return "; ".join(parts)


class IntegrityError(RuntimeError):
    """The ontology changed after governance was bound to it."""


class GovernanceLayer:
    def __init__(self, ontology: Ontology, max_violations: Optional[int] = None):
        self.ontology = ontology
        self._fingerprint = ontology.fingerprint
        self.max_violations = max_violations if max_violations is not None else ontology.settings.get("max_violations")
        self.violations: Counter = Counter()
        self.suspended: Dict[str, str] = {}

    # -- integrity ------------------------------------------------------
    def check_integrity(self) -> None:
        if self.ontology.fingerprint != self._fingerprint:
            raise IntegrityError("ontology fingerprint changed; refusing to execute")

    # -- suspension -----------------------------------------------------
    def record_violation(self, principal: Principal, decision: Decision) -> bool:
        """Count a denied proposal; returns True if the principal is now suspended."""
        self.violations[principal.name] += 1
        if self.max_violations and self.violations[principal.name] >= self.max_violations:
            self.suspended.setdefault(principal.name, f"suspended after {self.violations[principal.name]} "
                                                      f"governance violations (last: {decision.action})")
            return True
        return False

    def reinstate(self, name: str) -> None:
        self.suspended.pop(name, None)
        self.violations.pop(name, None)

    # -- rule evaluation ------------------------------------------------
    @staticmethod
    def _mandatory_satisfied(rule: Rule, state: WorldState) -> bool:
        outcome = state.steps.get(rule.params["step"])
        if outcome is None:
            return False
        wanted = rule.params.get("outcome")
        return wanted is None or outcome == wanted

    def _check(self, action: ActionType, state: WorldState, principal: Principal,
               check_preconditions: bool = True) -> Tuple[List[Tuple[Optional[str], str]], List[str], set]:
        problems: List[Tuple[Optional[str], str]] = []
        satisfied: List[str] = []
        refs: set = set()
        if principal.name in self.suspended:
            problems.append((None, f"{principal.name} is {self.suspended[principal.name]}"))
        if check_preconditions:
            for expr in action.requires:
                refs |= expr.references
                if not expr.evaluate(state.get):
                    problems.append((None, f"precondition not met: {expr}"))
        for rule in self.ontology.rules:
            p = rule.params
            applies_to_action = (
                (rule.kind == "mandatory_step" and p["before"] == action.name)
                or (rule.kind in ("prohibition", "action_access", "human_review") and p["action"] == action.name)
                or (rule.kind == "data_access" and p["field"] in action.reads)
                or (rule.kind == "write_access" and p["field"] in action.writes))
            if not applies_to_action or not rule.applies(state.get):
                continue
            if rule.when is not None:
                refs |= rule.when.references
            if rule.kind == "mandatory_step":
                if self._mandatory_satisfied(rule, state):
                    satisfied.append(rule.id)
                else:
                    need = p["step"] + (f" (outcome {p['outcome']})" if p.get("outcome") else "")
                    problems.append((rule.id, f"mandatory step {need} has not been completed: {rule.description}"))
            elif rule.kind == "prohibition":
                problems.append((rule.id, f"prohibited: {rule.description}"))
            elif rule.kind in ("data_access", "write_access", "action_access"):
                if principal.roles & set(p["roles"]):
                    satisfied.append(rule.id)
                else:
                    verb = {"data_access": f"read {p.get('field')}", "write_access": f"modify {p.get('field')}",
                            "action_access": f"execute {action.name}"}[rule.kind]
                    problems.append((rule.id, f"{principal.name} may not {verb}: {rule.description}"))
        return problems, satisfied, refs

    def permits_in_plan(self, action: ActionType, state: WorldState, principal: Principal) -> bool:
        """Planner hook: would the hard rules allow this action (ignoring human review)?"""
        return not self._check(action, state, principal, check_preconditions=False)[0]

    def evaluate(self, action: ActionType | str, state: WorldState, principal: Principal) -> Decision:
        self.check_integrity()
        if isinstance(action, str):
            if action not in self.ontology.actions:
                return Decision(Verdict.DENY, action, [f"{action!r} is not an action in the ontology"])
            action = self.ontology.actions[action]
        problems, satisfied, refs = self._check(action, state, principal)
        facts = {f"{e}.{a}": (state.get(e, a) if self.can_read(f"{e}.{a}", state, principal) else REDACTED)
                 for e, a in sorted(refs)}
        if problems:
            return Decision(Verdict.DENY, action.name, [m for _, m in problems],
                            [rid for rid, _ in problems if rid], satisfied=satisfied, facts=facts)
        reviews = [r for r in self.ontology.rules_of("human_review")
                   if r.params["action"] == action.name and r.applies(state.get)]
        if reviews:
            return Decision(Verdict.REVIEW, action.name, [r.description for r in reviews],
                            [r.id for r in reviews], tuple(dict.fromkeys(r.params["reviewer"] for r in reviews)),
                            satisfied, facts)
        return Decision(Verdict.ALLOW, action.name, ["all rules satisfied"], satisfied=satisfied, facts=facts)

    def can_write(self, ref: str, state: WorldState, principal: Principal) -> bool:
        for rule in self.ontology.rules_of("write_access"):
            if rule.params["field"] == ref and rule.applies(state.get) and not principal.roles & set(rule.params["roles"]):
                return False
        return True

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
        """State as the principal is allowed to see it (used for reasoning / LLM prompts / reviews)."""
        view: Dict[str, Dict[str, Any]] = {}
        for entity, values in state.entities.items():
            view[entity] = {attr: (val if self.can_read(f"{entity}.{attr}", state, principal) else REDACTED)
                            for attr, val in values.items()}
        return view
