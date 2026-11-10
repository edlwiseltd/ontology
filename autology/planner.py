"""Workflow orchestration: derive the path to a goal from the ontology at run time.

There is no stored workflow. Given the current state, the planner searches
over ontology actions (preconditions -> outcome effects) for the cheapest
sequence that reaches the goal while respecting the governance layer's hard
rules. Each action's first (expected) outcome costs nothing extra; other
outcomes are considered at a penalty, so the planner prefers the happy path
but can still find routes that *need* a non-default outcome (e.g. a clause
check that will report a missing clause, followed by a Legal redline). Because the agent re-plans after every step, an
unexpected outcome (a rejected contract, a failed check) simply produces a
new plan - e.g. *escalate to Legal for revision, then re-review* - instead of
a failed workflow.
"""

from __future__ import annotations

import heapq
import itertools
from typing import Dict, List, Optional, Tuple

from .governance import GovernanceLayer, Principal
from .ontology import ActionType, Goal, Ontology, Outcome
from .state import GroundAction, WorldState


def apply_outcome(state: WorldState, outcome: Outcome, binding: Optional[Dict[str, str]] = None) -> None:
    binding = binding or {}
    for entity, changes in outcome.effects.items():
        for attr, value in changes.items():
            state.set(entity, attr, value, binding.get(entity))


class Planner:
    """Cheapest compliant path to a goal.

    Single-instance cases are planned with an exact uniform-cost search. When the case holds
    multi-instance entities, actions are *grounded* per instance (``ship_order@O-2``) and an
    ``all_of`` goal is planned one instance at a time - each sub-search is small and exact, so
    many instances don't explode the search, but the combined plan is not guaranteed to be the
    cheapest overall.
    """

    def __init__(self, ontology: Ontology, governance: GovernanceLayer, max_depth: int = 60,
                 max_expansions: int = 20000, alternative_outcome_penalty: int = 5):
        self.ontology = ontology
        self.governance = governance
        self.max_depth = max_depth
        self.max_expansions = max_expansions
        self.alternative_outcome_penalty = alternative_outcome_penalty

    def applicable(self, state: WorldState, principal, enforce_rules=True) -> List[GroundAction]:
        """Ground actions whose preconditions hold and (by default) that the hard rules allow right now.

        ``principal`` may be a list (an agent and its delegates): an action is allowed when at
        least one member may perform it - roles are never pooled across members.
        ``enforce_rules="steps"`` enforces mandatory steps only; ``False`` ignores all rules.
        """
        members = list(principal) if isinstance(principal, (list, tuple)) else [principal]
        found = []
        for action in self.ontology.actions.values():
            targets = state.instances(action.for_each) if action.for_each else [None]
            for target in targets:
                ga = GroundAction(action, target)
                resolve = state.resolver(ga.binding)
                if all(e.evaluate(resolve) for e in action.requires) and (
                        not enforce_rules or any(self.governance.permits_in_plan(ga, state, m, enforce_rules == "steps")
                                                 for m in members)):
                    found.append(ga)
        return found

    def simulate(self, state: WorldState, action, outcome: Optional[Outcome] = None) -> WorldState:
        ga = action if isinstance(action, GroundAction) else GroundAction(action)
        nxt = state.copy()
        outcome = outcome or ga.action.expected_outcome
        apply_outcome(nxt, outcome, ga.binding)
        self.governance.record_completion(ga.action, outcome.name, nxt, ga.target)
        return nxt

    def plan(self, state: WorldState, goal: Goal, principal: Principal,
             enforce_rules: bool = True) -> Optional[List[str]]:
        """Compliant action sequence (ground names) reaching ``goal``; ``[]`` if reached, ``None`` if impossible.

        ``enforce_rules=False`` ignores governance rules (preconditions still apply); the agent uses
        it only to *explain* which rule blocks the way when no compliant plan exists.
        """
        detailed = self.plan_with_outcomes(state, goal, principal, enforce_rules)
        return None if detailed is None else [name for name, _ in detailed]

    def plan_with_outcomes(self, state: WorldState, goal: Goal, principal: Principal,
                           enforce_rules=True) -> Optional[List[Tuple[str, str]]]:
        """Like :meth:`plan`, but each step carries the outcome the plan assumes."""
        if goal.target.evaluate(state.resolver()):
            return []
        if state.collections:
            decomposed = self._plan_by_instance(state, goal, principal, enforce_rules)
            if decomposed is not False:
                return decomposed
        found = self._search(state, lambda st: goal.target.evaluate(st.resolver()), principal, enforce_rules)
        return found[0] if found else None

    def _search(self, state: WorldState, is_goal, principal, enforce_rules, allowed=None):
        """Uniform-cost search. Returns ``(path, final_state)``, ``None`` if exhausted, ``False`` if out of budget."""
        tie = itertools.count()
        frontier = [(0, next(tie), state, [])]
        best = {state.key(): 0}
        expansions = 0
        while frontier:
            if expansions >= self.max_expansions:
                return False
            cost, _, current, path = heapq.heappop(frontier)
            if is_goal(current):
                return path, current
            if len(path) >= self.max_depth:
                continue
            expansions += 1
            for ga in self.applicable(current, principal, enforce_rules):
                if allowed is not None and not allowed(ga):
                    continue
                for i, outcome in enumerate(ga.action.outcomes):
                    nxt = self.simulate(current, ga, outcome)
                    key = nxt.key()
                    new_cost = cost + ga.action.cost + (self.alternative_outcome_penalty if i else 0)
                    if key in best and best[key] <= new_cost:
                        continue
                    best[key] = new_cost
                    heapq.heappush(frontier, (new_cost, next(tie), nxt, path + [(ga.name, outcome.name)]))
        return None

    def _plan_by_instance(self, state: WorldState, goal: Goal, principal, enforce_rules):
        """Plan ``all_of`` goals one instance at a time on the evolving state.

        Each sub-search may use actions on the focus instance, single-instance actions and actions on
        other entities - small and exact - so many instances don't explode the search. The combined plan
        is compliant but not guaranteed cheapest overall. Returns ``False`` when the goal cannot be
        decomposed or a sub-search ran out of budget (the caller then searches the whole space).
        """
        quantified, rest = goal.target.decompose()
        quantified = [(sorted(e & set(state.collections)), inner) for e, inner in quantified]
        quantified = [(e[0], inner) for e, inner in quantified if len(e) == 1]
        if not quantified:
            return False
        holds_rest = lambda st: all(r.evaluate(st.resolver()) for r in rest)  # noqa: E731
        plan: List[Tuple[str, str]] = []
        current = state
        for entity, inner in quantified:
            for iid in current.instances(entity):
                if inner.evaluate(current.resolver({entity: iid})):
                    continue

                def done(st, entity=entity, iid=iid, inner=inner):
                    return inner.evaluate(st.resolver({entity: iid}))

                def allowed(ga, entity=entity, iid=iid):
                    return ga.action.for_each != entity or ga.target == iid

                found = self._search(current, done, principal, enforce_rules, allowed)
                if found is False:
                    return False
                if found is None:
                    return None  # this instance cannot reach its condition: the goal is unreachable
                path, current = found
                plan += path
        if not holds_rest(current):
            found = self._search(current, lambda st: goal.target.evaluate(st.resolver()), principal, enforce_rules)
            if not found:
                return found
            path, current = found
            plan += path
        return plan if goal.target.evaluate(current.resolver()) else False
