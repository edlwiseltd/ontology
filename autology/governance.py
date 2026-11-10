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
``row_access``      instances of ``entity`` for which ``when`` holds are visible to, and
                    can be acted on by, principals holding ``roles`` only (row-level security).

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

from .ontology import ID, ActionType, Ontology, Rule
from .state import GroundAction, WorldState, ground, ground_name

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
    def _step_key(self, step: str, ga: GroundAction) -> str:
        """Steps are tracked per instance when the step and the gated action range over the same entity."""
        step_action = self.ontology.actions.get(step)
        if ga.target and step_action is not None and step_action.for_each == ga.action.for_each:
            return ground_name(step, ga.target)
        return step

    def _mandatory_satisfied(self, rule: Rule, state: WorldState, ga: GroundAction) -> bool:
        outcome = state.steps.get(self._step_key(rule.params["step"], ga))
        if outcome is None:
            return False
        wanted = rule.params.get("outcome")
        return wanted is None or outcome == wanted

    def _instance_of(self, entity: str, state: WorldState, ga: GroundAction) -> Optional[str]:
        """Instance id an action works on for ``entity``: its target, or the single instance's id."""
        if entity in state.collections:
            return ga.target if entity == ga.action.for_each else None
        return state.entities.get(entity, {}).get(ID) or entity

    def row_visible(self, entity: str, state: WorldState, principal: Principal,
                    instance: Optional[str] = None) -> Tuple[bool, Optional[Rule]]:
        """Row-level access: may ``principal`` see this instance at all?"""
        binding = {entity: instance} if instance and entity in state.collections else {}
        resolve = state.resolver(binding)
        for rule in self.ontology.rules_of("row_access"):
            if rule.params["entity"] == entity and rule.applies(resolve):
                if not principal.roles & set(rule.params["roles"]):
                    return False, rule
        return True, None

    def _check(self, action, state: WorldState, principal: Principal, check_preconditions: bool = True,
               only_steps: bool = False) -> Tuple[List[Tuple[Optional[str], str]], List[str], set]:
        """``only_steps`` checks mandatory steps only (used to explain blocks: access and prohibitions relaxed)."""
        ga = ground(self.ontology, action)
        act = ga.action
        resolve = state.resolver(ga.binding)
        problems: List[Tuple[Optional[str], str]] = []
        satisfied: List[str] = []
        refs: set = set()
        if principal.name in self.suspended and not only_steps:
            problems.append((None, f"{principal.name} is {self.suspended[principal.name]}"))
        if act.for_each and not ga.target:
            problems.append((None, f"{act.name} works on one {act.for_each} at a time: name the instance"))
        elif ga.target and ga.target not in state.collections.get(act.for_each or "", {}):
            problems.append((None, f"{act.for_each} {ga.target!r} is not part of this case"))
        if check_preconditions:
            for expr in act.requires:
                refs |= expr.references
                if not expr.evaluate(resolve):
                    problems.append((None, f"precondition not met: {expr}"))
        for entity in ([] if only_steps else sorted(act.touches())):
            iid = self._instance_of(entity, state, ga)
            if iid is None:
                continue
            visible, rule = self.row_visible(entity, state, principal, iid)
            if not visible:
                problems.append((rule.id, f"{principal.name} may not access {entity} {iid}: {rule.description}"))
        for rule in self.ontology.rules:
            p = rule.params
            applies_to_action = (
                (rule.kind == "mandatory_step" and p["before"] == act.name)
                or (rule.kind in ("prohibition", "action_access", "human_review") and p["action"] == act.name)
                or (rule.kind == "data_access" and p["field"] in act.reads)
                or (rule.kind == "write_access" and p["field"] in act.writes))
            if not applies_to_action or (only_steps and rule.kind != "mandatory_step") or not rule.applies(resolve):
                continue
            if rule.when is not None:
                refs |= rule.when.references
            if rule.kind == "mandatory_step":
                if self._mandatory_satisfied(rule, state, ga):
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
                            "action_access": f"execute {act.name}"}[rule.kind]
                    problems.append((rule.id, f"{principal.name} may not {verb}: {rule.description}"))
        return problems, satisfied, refs

    def permits_in_plan(self, action, state: WorldState, principal: Principal, only_steps: bool = False) -> bool:
        """Planner hook: would the hard rules allow this action (ignoring human review)?"""
        return not self._check(action, state, principal, check_preconditions=False, only_steps=only_steps)[0]

    def evaluate(self, action, state: WorldState, principal: Principal) -> Decision:
        """Decide on an action - an ActionType, a GroundAction, or a name such as ``ship_order@O-2``."""
        self.check_integrity()
        try:
            ga = ground(self.ontology, action)
        except KeyError:
            return Decision(Verdict.DENY, str(action), [f"{action!r} is not an action in the ontology"])
        resolve = state.resolver(ga.binding)
        problems, satisfied, refs = self._check(ga, state, principal)
        facts = {f"{e}.{a}": (resolve(e, a) if self.can_read(f"{e}.{a}", state, principal, ga.binding) else REDACTED)
                 for e, a in sorted(refs)}
        if problems:
            return Decision(Verdict.DENY, ga.name, [m for _, m in problems],
                            [rid for rid, _ in problems if rid], satisfied=satisfied, facts=facts)
        reviews = [r for r in self.ontology.rules_of("human_review")
                   if r.params["action"] == ga.action.name and r.applies(resolve)]
        if reviews:
            return Decision(Verdict.REVIEW, ga.name, [r.description for r in reviews],
                            [r.id for r in reviews], tuple(dict.fromkeys(r.params["reviewer"] for r in reviews)),
                            satisfied, facts)
        return Decision(Verdict.ALLOW, ga.name, ["all rules satisfied"], satisfied=satisfied, facts=facts)

    def can_write(self, ref: str, state: WorldState, principal: Principal,
                  binding: Optional[Dict[str, str]] = None) -> bool:
        resolve = state.resolver(binding)
        for rule in self.ontology.rules_of("write_access"):
            if rule.params["field"] == ref and rule.applies(resolve) and not principal.roles & set(rule.params["roles"]):
                return False
        return True

    def record_completion(self, action, outcome: str, state: WorldState, target: Optional[str] = None) -> None:
        """Update step bookkeeping after an action ran (including resets)."""
        ga = ground(self.ontology, action, target=target)
        if target and not ga.target:
            ga = GroundAction(ga.action, target)
        for rule in self.ontology.rules_of("mandatory_step"):
            if ga.action.name in rule.params.get("reset_by", ()):
                state.steps.pop(self._step_key(rule.params["step"], ga), None)
        state.steps[ga.name] = outcome

    # -- data access ----------------------------------------------------
    def can_read(self, ref: str, state: WorldState, principal: Principal,
                 binding: Optional[Dict[str, str]] = None) -> bool:
        resolve = state.resolver(binding)
        for rule in self.ontology.rules_of("data_access"):
            if rule.params["field"] == ref and rule.applies(resolve):
                if not principal.roles & set(rule.params["roles"]):
                    return False
        return True

    def redacted_view(self, state: WorldState, principal: Principal) -> Dict[str, Dict[str, Any]]:
        """State as the principal may see it (reasoning, LLM prompts, reviews).

        Fields the principal may not read are redacted; instances hidden by ``row_access``
        rules are left out entirely (single instances are fully redacted).
        """
        view: Dict[str, Dict[str, Any]] = {}
        for entity, values in state.entities.items():
            visible, _ = self.row_visible(entity, state, principal)
            view[entity] = {attr: (val if visible and self.can_read(f"{entity}.{attr}", state, principal) else REDACTED)
                            for attr, val in values.items()}
        for entity, bucket in state.collections.items():
            shown: Dict[str, Any] = {}
            for iid, values in sorted(bucket.items()):
                if not self.row_visible(entity, state, principal, iid)[0]:
                    continue
                binding = {entity: iid}
                shown[iid] = {attr: (val if self.can_read(f"{entity}.{attr}", state, principal, binding) else REDACTED)
                              for attr, val in values.items()}
            view[entity] = shown
        return view
