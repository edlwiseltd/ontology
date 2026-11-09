"""AI agent layer: autonomous, ontology-bound execution.

A :class:`WorkAgent` is given a *goal* and a *case* (the facts of one
business instance). It then loops:

1. **observe**  - is the goal reached?
2. **plan**     - derive the cheapest compliant path from the ontology;
3. **reason**   - a reasoner (deterministic or LLM) proposes the next action;
4. **govern**   - the governance layer allows, denies, or routes to human review;
5. **act**      - pick a tool for the action's capability *in this context* and run it;
6. **learn**    - apply the actual outcome to the state and re-plan.

Unexpected outcomes are not failures: the next iteration simply plans a new
path (e.g. a rejected contract leads to "escalate to Legal for revision").
The agent stops - and escalates to a human - only when no compliant path
exists, a reviewer declines, or a tool keeps failing.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol

from .audit import AuditLog
from .governance import Decision, GovernanceLayer, Principal, Verdict
from .ontology import STATUS, ActionType, Ontology, OntologyError
from .planner import Planner, apply_outcome
from .reasoners import DecisionContext, PlanFollowingReasoner, Proposal, Reasoner
from .state import WorldState
from .tools import ToolCall, ToolError, ToolRegistry, ToolResult


# -- human-in-the-loop ------------------------------------------------------
@dataclass
class ReviewRequest:
    case_id: str
    action: str
    description: str
    reviewers: tuple
    reasons: List[str]
    view: Mapping[str, Mapping[str, Any]]


@dataclass
class ReviewDecision:
    approved: bool
    reviewer: str
    comment: str = ""


class Approver(Protocol):
    def review(self, request: ReviewRequest) -> ReviewDecision: ...


class AutoApprover:
    """Scripted reviewers for demos and tests.

    ``decisions`` maps an action name to ``True``/``False`` or to a callable
    ``(ReviewRequest) -> bool``; unlisted actions get ``default``.
    """

    def __init__(self, decisions: Optional[Dict[str, Any]] = None, default: bool = True,
                 reviewer: str = "auto-reviewer"):
        self.decisions = decisions or {}
        self.default = default
        self.reviewer = reviewer
        self.requests: List[ReviewRequest] = []

    def review(self, request: ReviewRequest) -> ReviewDecision:
        self.requests.append(request)
        rule = self.decisions.get(request.action, self.default)
        approved = bool(rule(request) if callable(rule) else rule)
        return ReviewDecision(approved, f"{self.reviewer}[{'/'.join(request.reviewers)}]",
                              "approved" if approved else "declined")


class ConsoleApprover:
    """Ask a human on the terminal."""

    def review(self, request: ReviewRequest) -> ReviewDecision:
        print(f"\n[REVIEW] {request.action}: {request.description}")
        for reason in request.reasons:
            print(f"   - {reason}")
        answer = input(f"   Approve as {'/'.join(request.reviewers)}? [y/N] ").strip().lower()
        return ReviewDecision(answer in ("y", "yes"), "console", answer)


# -- results ----------------------------------------------------------------
@dataclass
class StepRecord:
    index: int
    action: str
    proposed_by: str
    rationale: str
    verdict: str
    tool: Optional[str] = None
    outcome: Optional[str] = None
    message: str = ""
    reviewer: Optional[str] = None


@dataclass
class Escalation:
    reason: str
    to: str = "operations"
    action: Optional[str] = None
    details: List[str] = field(default_factory=list)


@dataclass
class RunResult:
    status: str  # "completed" | "blocked" | "escalated"
    goal: str
    case_id: str
    steps: List[StepRecord]
    state: WorldState
    audit: AuditLog
    escalation: Optional[Escalation] = None
    violations: List[Decision] = field(default_factory=list)  # proposals governance refused

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def path(self) -> List[str]:
        return [f"{s.action}:{s.outcome}" for s in self.steps if s.outcome]


Observer = Callable[[str, Dict[str, Any]], None]


class WorkAgent:
    def __init__(self, name: str, ontology: Ontology, tools: ToolRegistry, *, roles=(),
                 reasoner: Optional[Reasoner] = None, approver: Optional[Approver] = None,
                 max_steps: int = 50, max_repeats: int = 3, tool_retries: int = 2,
                 observer: Optional[Observer] = None):
        self.principal = Principal(name, roles)
        self.ontology = ontology
        self.tools = tools
        self.governance = GovernanceLayer(ontology)
        self.planner = Planner(ontology, self.governance)
        self.reasoner = reasoner or PlanFollowingReasoner()
        self.approver = approver or AutoApprover(default=False)
        self.max_steps = max_steps
        self.max_repeats = max_repeats
        self.tool_retries = tool_retries
        self.observer = observer

    # -- helpers --------------------------------------------------------
    def _log(self, audit: AuditLog, event: str, **data: Any) -> None:
        audit.record(event, **data)
        if self.observer:
            self.observer(event, data)

    def _explain_block(self, state: WorldState, goal) -> List[str]:
        """Find the rule(s) standing between the current state and the goal."""
        unconstrained = self.planner.plan(state, goal, self.principal, enforce_rules=False)
        if unconstrained is None:
            return ["no sequence of ontology actions leads from the current state to the goal"]
        probe = state.copy()
        for name in unconstrained:
            action = self.ontology.actions[name]
            decision = self.governance.evaluate(action, probe, self.principal)
            if decision.verdict is Verdict.DENY:
                return [f"{name}: {r}" for r in decision.reasons]
            probe = self.planner.simulate(probe, action)
        return ["the only paths to the goal violate governance rules"]  # pragma: no cover

    def _execute(self, action: ActionType, state: WorldState, case_id: str, audit: AuditLog):
        tool = self.tools.select(action.capability, state)
        inputs = {ref: state.field(ref) for ref in action.reads}
        view = self.governance.redacted_view(state, self.principal)
        last_error: Optional[str] = None
        for attempt in range(1, self.tool_retries + 2):
            call = ToolCall(action.name, action.capability, inputs, view, attempt)
            self._log(audit, "tool.call", case=case_id, action=action.name, tool=tool.name, attempt=attempt)
            try:
                result = tool.handler(call) or ToolResult()
                return tool, result, None
            except ToolError as exc:
                last_error = str(exc)
                self._log(audit, "tool.error", case=case_id, action=action.name, tool=tool.name,
                          attempt=attempt, error=last_error)
        return tool, None, last_error

    def _validate_result(self, action: ActionType, result: ToolResult) -> Optional[str]:
        names = [o.name for o in action.outcomes]
        if result.outcome is not None and result.outcome not in names:
            return f"tool returned unknown outcome {result.outcome!r} (allowed: {names})"
        for entity, changes in result.updates.items():
            for attr in changes:
                if f"{entity}.{attr}" not in action.writes:
                    return f"tool attempted to write undeclared field {entity}.{attr}"
        return None

    # -- main loop ------------------------------------------------------
    def run(self, goal_name: str, case: Mapping[str, Mapping[str, Any]], case_id: str = "case") -> RunResult:
        if goal_name not in self.ontology.goals:
            raise OntologyError(f"unknown goal {goal_name!r}")
        goal = self.ontology.goals[goal_name]
        state = WorldState.initial(self.ontology, case)
        audit = AuditLog()
        steps: List[StepRecord] = []
        violations: List[Decision] = []
        history: List[str] = []
        attempts: Counter = Counter()

        def finish(status: str, escalation: Optional[Escalation] = None) -> RunResult:
            self._log(audit, "run.end", case=case_id, status=status,
                      escalation=escalation.__dict__ if escalation else None, state=state.snapshot())
            return RunResult(status, goal_name, case_id, steps, state, audit, escalation, violations)

        self._log(audit, "run.start", case=case_id, agent=self.principal.name,
                  roles=sorted(self.principal.roles), goal=goal_name, ontology=self.ontology.name,
                  ontology_version=self.ontology.version, fingerprint=self.ontology.fingerprint)

        for index in range(1, self.max_steps + 1):
            self.governance.check_integrity()
            if goal.target.evaluate(state.get):
                return finish("completed")

            plan = self.planner.plan(state, goal, self.principal)
            if plan is None:
                return finish("escalated", Escalation("no compliant path to the goal", "operations",
                                                      details=self._explain_block(state, goal)))
            self._log(audit, "plan", case=case_id, step=index, plan=plan)

            ctx = DecisionContext(self.ontology, goal, plan, self.planner.applicable(state, self.principal),
                                  self.governance.redacted_view(state, self.principal), list(history))
            proposal = self.reasoner.propose(ctx)
            decision = self.governance.evaluate(proposal.action, state, self.principal)
            if decision.verdict is Verdict.DENY:
                violations.append(decision)
                self._log(audit, "governance.deny", case=case_id, action=proposal.action,
                          proposed_by=proposal.source, reasons=decision.reasons, rules=decision.rule_ids)
                # The ontology, not the reasoner, has the last word: fall back to the compliant plan.
                proposal = Proposal(plan[0], f"governance override of {proposal.action!r}", "override")
                decision = self.governance.evaluate(plan[0], state, self.principal)
                if decision.verdict is Verdict.DENY:  # pragma: no cover - planner only emits compliant steps
                    return finish("escalated", Escalation("planned step denied", action=plan[0],
                                                          details=decision.reasons))

            action = self.ontology.actions[proposal.action]
            attempts[action.name] += 1
            if attempts[action.name] > self.max_repeats:
                return finish("escalated", Escalation(
                    f"{action.name} attempted {attempts[action.name] - 1} times without reaching the goal",
                    "operations", action.name, history[-6:]))

            record = StepRecord(index, action.name, proposal.source, proposal.rationale, decision.verdict.value)
            self._log(audit, "decision", case=case_id, step=index, action=action.name, verdict=decision.verdict.value,
                      proposed_by=proposal.source, rationale=proposal.rationale, rules=decision.rule_ids)

            if decision.verdict is Verdict.REVIEW:
                request = ReviewRequest(case_id, action.name, action.description, decision.reviewers,
                                        decision.reasons, self.governance.redacted_view(state, self.principal))
                review = self.approver.review(request)
                record.reviewer = review.reviewer
                self._log(audit, "review", case=case_id, action=action.name, approved=review.approved,
                          reviewer=review.reviewer, roles=list(decision.reviewers), comment=review.comment)
                if not review.approved:
                    record.message = f"declined by {review.reviewer}"
                    steps.append(record)
                    return finish("blocked", Escalation(f"human review declined {action.name}",
                                                        "/".join(decision.reviewers), action.name,
                                                        [review.comment]))

            try:
                tool, result, error = self._execute(action, state, case_id, audit)
            except LookupError as exc:
                steps.append(record)
                return finish("escalated", Escalation(str(exc), "it-integration", action.name))
            record.tool = tool.name
            if result is None:
                record.message = error or "tool failed"
                steps.append(record)
                return finish("escalated", Escalation(f"tool {tool.name} failed: {error}", "it-operations",
                                                      action.name))
            problem = self._validate_result(action, result)
            if problem:
                record.message = problem
                steps.append(record)
                self._log(audit, "governance.reject_result", case=case_id, action=action.name, reason=problem)
                return finish("escalated", Escalation(problem, "it-integration", action.name))

            outcome = action.outcome(result.outcome) if result.outcome else action.expected_outcome
            before = {e: v.get(STATUS) for e, v in state.entities.items()}
            for entity, changes in result.updates.items():
                for attr, value in changes.items():
                    state.set(entity, attr, value)
            apply_outcome(state, outcome)
            self.governance.record_completion(action, outcome.name, state)
            record.outcome, record.message = outcome.name, result.message
            steps.append(record)
            history.append(f"{action.name}->{outcome.name}")
            after = {e: v.get(STATUS) for e, v in state.entities.items()}
            self._log(audit, "step", case=case_id, step=index, action=action.name, tool=tool.name,
                      outcome=outcome.name, message=result.message,
                      transitions={e: [before[e], after[e]] for e in after if before[e] != after[e]})

        return finish("escalated", Escalation(f"step budget of {self.max_steps} exhausted"))
