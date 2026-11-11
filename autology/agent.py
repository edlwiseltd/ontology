"""AI agent layer: autonomous, ontology-bound execution.

A :class:`WorkAgent` is given a *goal* and a *case* (the facts of one
business instance). It then loops:

1. **observe**  - is the goal reached? is the pinned ontology still valid?
2. **plan**     - derive the cheapest compliant path from the ontology;
3. **reason**   - a reasoner (deterministic or LLM) proposes the next action;
4. **govern**   - governance allows, denies, or routes to human review; actions
                  the agent may not perform itself are delegated to a team member
                  that may (e.g. payment terms -> FinanceAgent);
5. **act**      - pick a tool for the action's capability *in this context*; on
                  failure apply the action's self-healing policy (fallback tools,
                  backoff, defer & resume, escalate);
6. **learn**    - apply the actual outcome to the state and re-plan.

Unexpected outcomes are not failures: the next iteration simply plans a new
path. The agent stops - and hands over to a human - only when no compliant
path exists, a reviewer declines, tools keep failing, or the ontology is
unavailable (fail safe: pause, never guess).
"""

from __future__ import annotations

import copy
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from .audit import AuditLog
from .governance import Decision, GovernanceLayer, IntegrityError, Principal, Verdict
from .ontology import STATUS, ActionType, Ontology, OntologyError
from .planner import Planner, apply_outcome
from .reasoners import DecisionContext, PlanFollowingReasoner, Proposal, Reasoner
from .state import GroundAction, WorldState, ground
from .tools import ToolCall, ToolError, ToolRegistry, ToolResult


# -- human-in-the-loop ------------------------------------------------------
@dataclass
class ReviewRequest:
    """A context-rich request: what, why (rules), on which facts, and what happened so far."""

    case_id: str
    action: str
    description: str
    reviewers: tuple
    reasons: List[str]  # rule justifications
    view: Mapping[str, Mapping[str, Any]]  # redacted case state
    history: List[str] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    rule_ids: List[str] = field(default_factory=list)
    binding: Dict[str, str] = field(default_factory=dict)  # instance the action works on, per entity

    def summary(self) -> str:
        lines = [f"{self.action} on case {self.case_id} needs {'/'.join(self.reviewers)} approval",
                 f"  why: {'; '.join(self.reasons)} ({', '.join(self.rule_ids)})"]
        if self.facts:
            lines.append("  facts: " + ", ".join(f"{k}={v!r}" for k, v in sorted(self.facts.items())))
        lines.append(f"  history: {' > '.join(self.history) or 'none'}")
        return "\n".join(lines)


@dataclass
class ReviewDecision:
    approved: bool
    reviewer: str
    comment: str = ""
    automatic: bool = False  # decided by a script or policy, not a person (reports flag it)


class Approver(Protocol):
    def review(self, request: ReviewRequest) -> Optional[ReviewDecision]:
        """Decide now, or return None to park the run until a decision arrives (see WorkAgent.resume)."""
        ...


class DeferredApprover:
    """Never decides inline: every review parks the run as ``awaiting_review`` (for inboxes and ticketing)."""

    def __init__(self) -> None:
        self.requests: List[ReviewRequest] = []

    def review(self, request: ReviewRequest) -> None:
        self.requests.append(request)
        return None


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
        base = request.action.partition("@")[0]  # per-instance actions are reviewed under their action name
        rule = self.decisions.get(request.action, self.decisions.get(base, self.default))
        approved = bool(rule(request) if callable(rule) else rule)
        return ReviewDecision(approved, f"{self.reviewer}[{'/'.join(request.reviewers)}]",
                              "approved" if approved else "declined", automatic=True)

    @property
    def can_approve(self) -> bool:
        """Whether this approver ever approves (a deny-everything approver never does)."""
        return bool(self.default) or any(v is not False for v in self.decisions.values())


class ConsoleApprover:
    """Ask a human on the terminal."""

    def review(self, request: ReviewRequest) -> ReviewDecision:
        print(f"\n[REVIEW] {request.summary()}")
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
    executed_by: Optional[str] = None
    explanation: str = ""


@dataclass
class Escalation:
    reason: str
    to: str = "operations"
    action: Optional[str] = None
    details: List[str] = field(default_factory=list)


@dataclass
class RunState:
    """Everything needed to continue a run later (deferral / resume)."""

    goal: str
    case_id: str
    state: WorldState
    steps: List[StepRecord] = field(default_factory=list)
    history: List[str] = field(default_factory=list)
    attempts: Counter = field(default_factory=Counter)  # executions per action
    failures: Counter = field(default_factory=Counter)  # failed tool rounds per action
    violations: List[Decision] = field(default_factory=list)
    costs: Dict[str, float] = field(default_factory=lambda: {"llm_usd": 0.0, "tools": 0.0, "llm_calls": 0})
    resume_at: Optional[float] = None
    ontology_ref: str = ""
    update_noticed: bool = False
    pending_review: Optional[Dict[str, Any]] = None  # review request the run is waiting on
    review_decisions: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # ground action -> decision to apply


@dataclass
class RunResult:
    status: str  # completed | blocked | escalated | deferred | paused | suspended | awaiting_review
    goal: str
    case_id: str
    steps: List[StepRecord]
    state: WorldState
    audit: AuditLog
    escalation: Optional[Escalation] = None
    violations: List[Decision] = field(default_factory=list)  # proposals governance refused
    costs: Dict[str, float] = field(default_factory=dict)
    resume_at: Optional[float] = None
    run: Optional[RunState] = field(default=None, repr=False)
    run_id: Optional[str] = None  # set when stored

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def path(self) -> List[str]:
        return [f"{s.action}:{s.outcome}" for s in self.steps if s.outcome]

    @property
    def human_touches(self) -> int:
        return sum(1 for s in self.steps if s.reviewer) + (0 if self.status in ("completed", "deferred") else 1)


Observer = Callable[[str, Dict[str, Any]], None]


def _statuses(state: WorldState) -> Dict[str, Any]:
    out = {e: v.get(STATUS) for e, v in state.entities.items()}
    for e, bucket in state.collections.items():
        for iid, v in bucket.items():
            out[f"{e}[{iid}]"] = v.get(STATUS)
    return out


class WorkAgent:
    def __init__(self, name: str, ontology: Ontology, tools: ToolRegistry, *, roles=(),
                 reasoner: Optional[Reasoner] = None, approver: Optional[Approver] = None,
                 delegates: Sequence["WorkAgent"] = (), governance: Optional[GovernanceLayer] = None,
                 registry=None, on_ontology_update: str = "continue",
                 max_steps: Optional[int] = None, max_repeats: int = 3, max_inline_wait: float = 5.0,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 observer: Optional[Observer] = None):
        if on_ontology_update not in ("continue", "pause"):
            raise ValueError("on_ontology_update must be 'continue' or 'pause'")
        self.principal = Principal(name, roles)
        self.ontology = ontology
        self.tools = tools
        self.governance = governance or GovernanceLayer(ontology)
        self.planner = Planner(ontology, self.governance)
        self.reasoner = reasoner or PlanFollowingReasoner()
        self.approver = approver or AutoApprover(default=False)  # fail closed
        self.delegates = list(delegates)
        self.registry = registry
        self.on_ontology_update = on_ontology_update
        self.max_steps = max_steps
        self.max_repeats = max_repeats
        self.max_inline_wait = max_inline_wait
        self.clock = clock
        self.sleep = sleep
        self.observer = observer

    @property
    def name(self) -> str:
        return self.principal.name

    @property
    def team(self) -> List[Principal]:
        """This agent and its delegates; an action is plannable if one of them may perform it."""
        return [self.principal] + [d.principal for d in self.delegates]

    @property
    def team_principal(self) -> Principal:
        """Planning identity: what the agent *and its delegates* are collectively allowed to do."""
        if not self.delegates:
            return self.principal
        roles = set(self.principal.roles)
        for d in self.delegates:
            roles |= d.principal.roles
        return Principal(f"{self.name}+team", roles)

    # -- helpers --------------------------------------------------------
    def _log(self, audit: AuditLog, event: str, **data: Any):
        entry = audit.record(event, **data)
        if self.observer:
            self.observer(event, data)
        return entry

    def _explain_block(self, state: WorldState, goal) -> List[str]:
        """Find the rule(s) standing between the current state and the goal."""
        if self.principal.name in self.governance.suspended:
            return [self.governance.suspended[self.principal.name]]
        # First relax only what makes a goal impossible (access, prohibitions) but keep mandatory steps, so the
        # explanation names the real blocker; if even that fails, relax everything.
        unconstrained = self.planner.plan_with_outcomes(state, goal, self.team, enforce_rules="steps")
        if unconstrained is None:
            unconstrained = self.planner.plan_with_outcomes(state, goal, self.team, enforce_rules=False)
        if unconstrained is None:
            return ["no sequence of ontology actions leads from the current state to the goal"]
        probe = state.copy()
        for name, outcome in unconstrained:
            ga = ground(self.ontology, name)
            decisions = [self.governance.evaluate(ga, probe, m) for m in self.team]
            if all(d.verdict is Verdict.DENY for d in decisions):
                if len(decisions) == 1:
                    return [f"{name}: {r}" for r in decisions[0].reasons]
                # each member is blocked for its own reasons - roles are never pooled
                return [f"{name}: {r}" for d in decisions for r in d.reasons]
            probe = self.planner.simulate(probe, ga, ga.action.outcome(outcome))
        return ["the only paths to the goal violate governance rules"]  # pragma: no cover

    def _authorize(self, action: str, state: WorldState) -> Tuple[Optional["WorkAgent"], Decision]:
        """Evaluate for this agent, else find a delegate that is allowed to act."""
        decision = self.governance.evaluate(action, state, self.principal)
        if decision.allowed:
            return self, decision
        for member in self.delegates:
            member_decision = self.governance.evaluate(action, state, member.principal)
            if member_decision.allowed:
                return member, member_decision
        return None, decision

    def _validate_result(self, action: GroundAction, result: ToolResult, state: WorldState,
                         executor: "WorkAgent") -> Optional[str]:
        names = [o.name for o in action.outcomes]
        if result.outcome is not None and result.outcome not in names:
            return f"tool returned unknown outcome {result.outcome!r} (allowed: {names})"
        for entity, changes in result.updates.items():
            for attr in changes:
                ref = f"{entity}.{attr}"
                if ref not in action.writes:
                    return f"tool attempted to write undeclared field {ref}"
                if entity in state.collections and entity not in action.binding:
                    return f"tool attempted to write {ref} on an instance the action is not working on"
                if not self.governance.can_write(ref, state, executor.principal, action.binding):
                    return f"{executor.name} may not modify {ref}"
        return None

    def _execute(self, run: RunState, action: GroundAction, executor: "WorkAgent", audit: AuditLog):
        """Run the action's tools under its failure policy.

        Returns ("ok", tool, result) | ("deferred", tool, error) | ("failed", tool, error)
        | ("crashed", tool, error). A tool that raises anything other than ToolError has crashed: it may
        have acted partly, so it is not retried and the run escalates with the error on record.
        """
        policy = action.on_failure
        state = run.state
        candidates = executor.tools.candidates(action.capability, state, action.tools, action.binding)
        if not candidates:
            extra = f" among allowed tools {list(action.tools)}" if action.tools else ""
            raise LookupError(f"no tool provides capability {action.capability!r} in this context{extra}")
        if not policy.fallback_tools:
            candidates = candidates[:1]
        inputs = {ref: state.field(ref, action.binding) for ref in action.reads}
        view = self.governance.redacted_view(state, executor.principal)
        error = "tool failed"
        while True:
            round_no = run.failures[action.name] + 1
            this_round = candidates if round_no > policy.fallback_after else candidates[:1]
            for tool in this_round:
                call = ToolCall(action.action.name, action.capability, dict(inputs), view, round_no, action.target)
                self._log(audit, "tool.call", case=run.case_id, action=action.name, tool=tool.name,
                          attempt=round_no, executed_by=executor.name, cost=tool.cost)
                run.costs["tools"] += tool.cost
                try:
                    return "ok", tool, (tool.handler(call) or ToolResult())
                except ToolError as exc:
                    error = str(exc)
                    self._log(audit, "tool.error", case=run.case_id, action=action.name, tool=tool.name,
                              attempt=round_no, error=error)
                except Exception as exc:  # a bug or an unexpected failure in the tool: stop, keep the record
                    error = f"{type(exc).__name__}: {exc}"
                    self._log(audit, "tool.exception", case=run.case_id, action=action.name, tool=tool.name,
                              attempt=round_no, error=error)
                    return "crashed", tool, error
            run.failures[action.name] += 1
            if run.failures[action.name] >= policy.max_attempts:
                return "failed", candidates[0], error
            if policy.backoff_seconds > self.max_inline_wait:
                run.resume_at = self.clock() + policy.backoff_seconds
                return "deferred", candidates[0], error
            if policy.backoff_seconds:
                self.sleep(policy.backoff_seconds)

    # -- public API -----------------------------------------------------
    def run(self, goal_name: str, case: Mapping[str, Mapping[str, Any]], case_id: str = "case",
            started_by: Optional[str] = None) -> RunResult:
        if goal_name not in self.ontology.goals:
            raise OntologyError(f"unknown goal {goal_name!r}")
        run = RunState(goal_name, case_id, WorldState.initial(self.ontology, case), ontology_ref=self.ontology.ref)
        audit = AuditLog()
        self._log(audit, "run.start", case=case_id, agent=self.name, roles=sorted(self.principal.roles),
                  delegates=[d.name for d in self.delegates], goal=goal_name, ontology=self.ontology.ref,
                  fingerprint=self.ontology.fingerprint, started_by=started_by)
        return self._loop(run, audit)

    def resume(self, previous: RunResult, force: bool = False,
               decision: Optional[ReviewDecision] = None) -> RunResult:
        """Continue a deferred, paused or awaiting-review run.

        Deferred runs wait for their retry window (unless ``force``); a run awaiting review needs the
        reviewer's ``decision``, which is applied to exactly the action that was waiting for it.
        """
        if previous.run is None or previous.status not in ("deferred", "paused", "awaiting_review"):
            raise ValueError(f"cannot resume a run with status {previous.status!r}")
        run = previous.run
        if previous.status == "deferred" and not force and run.resume_at and self.clock() < run.resume_at:
            return previous
        problem = self._tampering(previous)
        if problem:  # the resumable state lives outside the chain: it must match what the chain recorded
            audit = previous.audit
            self._log(audit, "integrity.violation", case=run.case_id, reason=problem)
            escalation = Escalation(f"stored run does not match its audit log: {problem}", "security")
            self._log(audit, "run.end", case=run.case_id, status="escalated", escalation=escalation.__dict__,
                      state=run.state.snapshot(), costs=dict(run.costs), resume_at=None)
            return RunResult("escalated", run.goal, run.case_id, run.steps, run.state, audit, escalation,
                             run.violations, dict(run.costs), None, run)
        if previous.status == "awaiting_review":
            if decision is None:
                raise ValueError("this run is waiting for a review decision")
            pending = run.pending_review or {}
            entry = self._log(previous.audit, "review.decision", case=run.case_id, action=pending.get("action", ""),
                              approved=bool(decision.approved), reviewer=decision.reviewer,
                              comment=decision.comment, automatic=bool(getattr(decision, "automatic", False)))
            run.review_decisions[pending.get("action", "")] = {
                "approved": bool(decision.approved), "reviewer": decision.reviewer, "comment": decision.comment,
                "automatic": bool(getattr(decision, "automatic", False)),
                "audit_seq": entry.seq, "audit_hash": entry.hash}  # bound to the entry that granted it
            run.pending_review = None
        if run.ontology_ref != self.ontology.ref:
            raise OntologyError(f"run was started on {run.ontology_ref}; this agent uses {self.ontology.ref}")
        run.resume_at = None
        audit = previous.audit
        self._log(audit, "run.resume", case=run.case_id, agent=self.name, previous_status=previous.status)
        return self._loop(run, audit)

    @staticmethod
    def _normal(value: Any) -> Any:
        return json.loads(json.dumps(value, default=str))

    @staticmethod
    def _decision_entry_ok(audit: AuditLog, action: str, stored: Dict[str, Any]) -> bool:
        entry = audit.entry(stored.get("audit_seq", -1)) if isinstance(stored.get("audit_seq"), int) else None
        return bool(entry and entry.hash == stored.get("audit_hash") and entry.event == "review.decision"
                    and entry.data.get("action") == action and entry.data.get("approved") == stored.get("approved")
                    and entry.data.get("reviewer") == stored.get("reviewer"))

    def _tampering(self, previous: RunResult) -> Optional[str]:
        """Why the stored, resumable run cannot be trusted, or None."""
        audit, run = previous.audit, previous.run
        if not audit.verify():
            return "the audit chain does not verify"
        ends = audit.events("run.end")
        if not ends:
            return "no run.end entry records where the run stopped"
        last = ends[-1].data
        if last.get("status") != previous.status:
            return f"status {previous.status!r} differs from the recorded {last.get('status')!r}"
        if self._normal(run.state.snapshot()) != last.get("state"):
            return "the case state differs from the state recorded when the run stopped"
        for action, stored in run.review_decisions.items():
            if not self._decision_entry_ok(audit, action, stored):
                return f"the stored review decision for {action} has no matching review.decision entry"
        return None

    # -- main loop ------------------------------------------------------
    def _check_ontology(self, run: RunState, audit: AuditLog) -> Optional[Escalation]:
        try:
            self.governance.check_integrity()
        except IntegrityError as exc:
            return Escalation(str(exc), "ontology-admin")
        if self.registry is None:
            return None
        if not self.registry.available(self.ontology.name, self.ontology.version):
            return Escalation(f"pinned ontology {self.ontology.ref} is unavailable (withdrawn)", "ontology-admin")
        latest = self.registry.latest(self.ontology.name)
        if latest is not None and latest.version != self.ontology.version:
            if self.on_ontology_update == "pause":
                return Escalation(f"ontology {latest.ref} published mid-run; paused on {self.ontology.ref}",
                                  "ontology-admin")
            if not run.update_noticed:
                run.update_noticed = True
                self._log(audit, "ontology.update_available", case=run.case_id, pinned=self.ontology.ref,
                          latest=latest.ref)
        return None

    def _loop(self, run: RunState, audit: AuditLog) -> RunResult:
        goal = self.ontology.goals[run.goal]
        state = run.state

        def finish(status: str, escalation: Optional[Escalation] = None) -> RunResult:
            self._log(audit, "run.end", case=run.case_id, status=status,
                      escalation=escalation.__dict__ if escalation else None, state=state.snapshot(),
                      costs=dict(run.costs), resume_at=run.resume_at)
            return RunResult(status, run.goal, run.case_id, run.steps, state, audit, escalation, run.violations,
                             dict(run.costs), run.resume_at, run)

        # default budget: 50 steps, plus 10 per instance of multi-instance entities
        budget = self.max_steps or 50 + 10 * sum(len(b) for b in state.collections.values())
        for _ in range(budget):
            index = len(run.steps) + 1
            problem = self._check_ontology(run, audit)
            if problem:
                return finish("paused", problem)  # fail safe: never act on an unverified ontology
            if self.principal.name in self.governance.suspended:
                return finish("suspended", Escalation(self.governance.suspended[self.principal.name],
                                                      "security", details=[f"{d.action}: {'; '.join(d.reasons)}"
                                                                           for d in run.violations[-3:]]))
            if goal.target.evaluate(state.resolver()):
                return finish("completed")

            plan = self.planner.plan(state, goal, self.team)
            if plan is None:
                return finish("escalated", Escalation("no compliant path to the goal", "operations",
                                                      details=self._explain_block(state, goal)))
            self._log(audit, "plan", case=run.case_id, step=index, plan=plan)

            ctx = DecisionContext(self.ontology, goal, plan, self.planner.applicable(state, self.team),
                                  self.governance.redacted_view(state, self.principal), list(run.history))
            proposal = self.reasoner.propose(ctx)
            run.costs["llm_usd"] += proposal.cost_usd
            if proposal.usage:
                run.costs["llm_calls"] += 1
            executor, decision = self._authorize(proposal.action, state)
            if executor is None:
                run.violations.append(decision)
                suspended = self.governance.record_violation(self.principal, decision, len(run.violations))
                self._log(audit, "governance.deny", case=run.case_id, action=proposal.action,
                          proposed_by=proposal.source, reasons=decision.reasons, rules=decision.rule_ids,
                          principal=self.name, suspended=suspended)
                if suspended:
                    continue  # top of loop reports the suspension
                # The ontology, not the reasoner, has the last word: fall back to the compliant plan.
                proposal = Proposal(plan[0], f"governance override of {proposal.action!r}", "override")
                executor, decision = self._authorize(plan[0], state)
                if executor is None:  # pragma: no cover - planner only emits compliant steps
                    return finish("escalated", Escalation("planned step denied", action=plan[0],
                                                          details=decision.reasons))

            action = ground(self.ontology, proposal.action)
            run.attempts[action.name] += 1
            if run.attempts[action.name] > self.max_repeats:
                return finish("escalated", Escalation(
                    f"{action.name} attempted {run.attempts[action.name] - 1} times without reaching the goal",
                    "operations", action.name, run.history[-6:]))

            explanation = decision.explanation()
            record = StepRecord(index, action.name, proposal.source, proposal.rationale, decision.verdict.value,
                                executed_by=executor.name, explanation=explanation)
            self._log(audit, "decision", case=run.case_id, step=index, action=action.name,
                      verdict=decision.verdict.value, proposed_by=proposal.source, model=proposal.model,
                      rationale=proposal.rationale, rules=decision.rule_ids, satisfied_rules=decision.satisfied,
                      facts=decision.facts, explanation=explanation, executed_by=executor.name,
                      llm_cost_usd=proposal.cost_usd)
            if executor is not self:
                self._log(audit, "delegate", case=run.case_id, action=action.name, from_agent=self.name,
                          to_agent=executor.name)

            if decision.verdict is Verdict.REVIEW:
                request = ReviewRequest(run.case_id, action.name, action.description, decision.reviewers,
                                        decision.reasons, self.governance.redacted_view(state, self.principal),
                                        list(run.history), decision.facts, explanation, decision.rule_ids,
                                        dict(action.binding))
                stored = run.review_decisions.pop(action.name, None)
                if stored and not self._decision_entry_ok(audit, action.name, stored):
                    return finish("escalated", Escalation(
                        f"stored review decision for {action.name} does not match the audit log", "security",
                        action.name))
                review = ReviewDecision(**{k: v for k, v in stored.items() if k in ReviewDecision.__dataclass_fields__}) \
                    if stored else self.approver.review(request)
                if review is None:  # the reviewer will answer later (inbox, ticket, ...): park the run
                    run.attempts[action.name] -= 1
                    run.pending_review = dict(request.__dict__)
                    self._log(audit, "review.requested", case=run.case_id, action=action.name,
                              roles=list(decision.reviewers), rules=decision.rule_ids, reasons=decision.reasons)
                    return finish("awaiting_review", Escalation(
                        f"awaiting {'/'.join(decision.reviewers)} review of {action.name}",
                        "/".join(decision.reviewers), action.name, list(decision.reasons)))
                record.reviewer = review.reviewer
                self._log(audit, "review", case=run.case_id, action=action.name, approved=review.approved,
                          reviewer=review.reviewer, roles=list(decision.reviewers), comment=review.comment,
                          rules=decision.rule_ids, automatic=bool(getattr(review, "automatic", False)))
                if not review.approved:
                    record.message = f"declined by {review.reviewer}"
                    run.steps.append(record)
                    return finish("blocked", Escalation(f"human review declined {action.name}",
                                                        "/".join(decision.reviewers), action.name,
                                                        [review.comment]))

            try:
                status, tool, payload = self._execute(run, action, executor, audit)
            except LookupError as exc:
                run.steps.append(record)
                return finish("escalated", Escalation(str(exc), "it-integration", action.name))
            record.tool = tool.name
            if status == "crashed":
                run.attempts[action.name] -= 1
                record.message = payload
                run.steps.append(record)
                return finish("escalated", Escalation(
                    f"{action.name}: tool {tool.name} raised {payload}; it may have acted partly, check before "
                    f"retrying", "it-integration", action.name))
            if status != "ok":
                run.attempts[action.name] -= 1  # the action did not run; don't count it as a repeat
                if status == "deferred":
                    self._log(audit, "deferred", case=run.case_id, action=action.name, error=payload,
                              resume_at=run.resume_at, failures=run.failures[action.name])
                    return finish("deferred", Escalation(
                        f"{action.name} failed ({payload}); retry scheduled", "scheduler", action.name))
                record.message = payload
                run.steps.append(record)
                return finish("escalated", Escalation(
                    f"{action.name} failed {run.failures[action.name]} times: {payload}",
                    action.on_failure.escalate_to, action.name))
            result: ToolResult = payload
            problem = self._validate_result(action, result, state, executor)
            if problem:
                record.message = problem
                run.steps.append(record)
                self._log(audit, "governance.reject_result", case=run.case_id, action=action.name, reason=problem)
                return finish("escalated", Escalation(problem, "it-integration", action.name))

            outcome = action.outcome(result.outcome) if result.outcome else action.expected_outcome
            before = _statuses(state)
            for entity, changes in result.updates.items():
                for attr, value in changes.items():
                    state.set(entity, attr, copy.deepcopy(value), action.binding.get(entity))
            apply_outcome(state, outcome, action.binding)
            self.governance.record_completion(action, outcome.name, state)
            run.failures.pop(action.name, None)
            record.outcome, record.message = outcome.name, result.message
            run.steps.append(record)
            run.history.append(f"{action.name}->{outcome.name}")
            after = _statuses(state)
            self._log(audit, "step", case=run.case_id, step=index, action=action.name, tool=tool.name,
                      outcome=outcome.name, message=result.message, executed_by=executor.name,
                      transitions={e: [before.get(e), after[e]] for e in after if before.get(e) != after[e]})

        return finish("escalated", Escalation(f"step budget of {budget} exhausted"))
