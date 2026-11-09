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
from typing import List, Optional, Tuple

from .governance import GovernanceLayer, Principal
from .ontology import ActionType, Goal, Ontology, Outcome
from .state import WorldState


def apply_outcome(state: WorldState, outcome: Outcome) -> None:
    for entity, changes in outcome.effects.items():
        for attr, value in changes.items():
            state.set(entity, attr, value)


class Planner:
    def __init__(self, ontology: Ontology, governance: GovernanceLayer, max_depth: int = 25,
                 max_expansions: int = 20000, alternative_outcome_penalty: int = 5):
        self.ontology = ontology
        self.governance = governance
        self.max_depth = max_depth
        self.max_expansions = max_expansions
        self.alternative_outcome_penalty = alternative_outcome_penalty

    def applicable(self, state: WorldState, principal: Principal, enforce_rules: bool = True) -> List[ActionType]:
        """Actions whose preconditions hold and (by default) that the hard rules allow right now."""
        return [a for a in self.ontology.actions.values()
                if all(e.evaluate(state.get) for e in a.requires)
                and (not enforce_rules or self.governance.permits_in_plan(a, state, principal))]

    def simulate(self, state: WorldState, action: ActionType, outcome: Optional[Outcome] = None) -> WorldState:
        nxt = state.copy()
        outcome = outcome or action.expected_outcome
        apply_outcome(nxt, outcome)
        self.governance.record_completion(action, outcome.name, nxt)
        return nxt

    def plan(self, state: WorldState, goal: Goal, principal: Principal,
             enforce_rules: bool = True) -> Optional[List[str]]:
        """Cheapest compliant action sequence reaching ``goal``; ``[]`` if already reached, ``None`` if impossible.

        ``enforce_rules=False`` ignores governance rules (preconditions still apply); the agent uses
        it only to *explain* which rule blocks the way when no compliant plan exists.
        """
        detailed = self.plan_with_outcomes(state, goal, principal, enforce_rules)
        return None if detailed is None else [name for name, _ in detailed]

    def plan_with_outcomes(self, state: WorldState, goal: Goal, principal: Principal,
                           enforce_rules: bool = True) -> Optional[List[Tuple[str, str]]]:
        """Like :meth:`plan`, but each step carries the outcome the plan assumes."""
        if goal.target.evaluate(state.get):
            return []
        tie = itertools.count()
        frontier = [(0, next(tie), state, [])]
        best = {state.key(): 0}
        expansions = 0
        while frontier and expansions < self.max_expansions:
            cost, _, current, path = heapq.heappop(frontier)
            if goal.target.evaluate(current.get):
                return path
            if len(path) >= self.max_depth:
                continue
            expansions += 1
            for action in self.applicable(current, principal, enforce_rules):
                for i, outcome in enumerate(action.outcomes):
                    nxt = self.simulate(current, action, outcome)
                    key = nxt.key()
                    new_cost = cost + action.cost + (self.alternative_outcome_penalty if i else 0)
                    if key in best and best[key] <= new_cost:
                        continue
                    best[key] = new_cost
                    heapq.heappush(frontier, (new_cost, next(tie), nxt, path + [(action.name, outcome.name)]))
        return None
