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
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

from .audit import AuditLog
from .governance import Decision, GovernanceLayer, IntegrityError, Principal, Verdict
from .ontology import STATUS, ActionType, Ontology, OntologyError, type_ok
from .effects import (DONE, FAILED, NEEDS_PERSON, NOT_SENT, PENDING, REJECTED, REPLAY, RESOLVED_DONE,
                      RESOLVED_NOT_DONE, UNKNOWN, MemoryJournal, idempotency_key, inputs_digest)
from .planner import Planner, SearchBudgetExceeded, apply_outcome
from .reasoners import DecisionContext, PlanFollowingReasoner, Proposal, Reasoner
from .state import GroundAction, WorldState, ground
from .tools import NotSent, OutcomeUnknown, Rejected, ToolCall, ToolError, ToolRegistry, ToolResult


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
    costs: Dict[str, float] = field(default_factory=lambda: {"llm_usd": 0.0, "tools": 0.0, "llm_calls": 0,
                                                             "llm_unpriced_tokens": 0})
    resume_at: Optional[float] = None
    ontology_ref: str = ""
    update_noticed: bool = False
    pending_review: Optional[Dict[str, Any]] = None  # review request the run is waiting on
    review_decisions: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # ground action -> decision to apply
    run_key: str = ""  # stable identity of the run, fixed at start: idempotency keys derive from it
    # the roles this run may use: the agent's, narrowed to the requester's or the service identity's (D4).
    # None = the agent's own roles (library use without a requester)
    roles: Optional[List[str]] = None
    root: Optional[str] = None  # the record the case was built from (for the journal and reconciliation)
    pending_external: Optional[Dict[str, Any]] = None  # the external call a person must reconcile


@dataclass
class RunResult:
    status: str  # completed | blocked | escalated | deferred | paused | suspended | awaiting_review
    #            | uncertain | pending_confirmation (an external call a person must reconcile)
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
                 observer: Optional[Observer] = None, journal=None, audit_key: Any = None):
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
        self.journal = journal if journal is not None else MemoryJournal()  # external calls (autology.effects)
        from .audit import ENV_KEY

        self.audit_key = ENV_KEY if audit_key is None else audit_key  # the key its audit chains are written with

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
        try:
            unconstrained = self.planner.plan_with_outcomes(state, goal, self.team, enforce_rules="steps")
            if unconstrained is None:
                unconstrained = self.planner.plan_with_outcomes(state, goal, self.team, enforce_rules=False)
        except SearchBudgetExceeded as exc:
            return [f"could not work out which rule blocks the way: {exc}"]
        if unconstrained is None:
            return self._unknown_blockers(state) or [
                "no sequence of ontology actions leads from the current state to the goal"]
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

    def _unknown_blockers(self, state: WorldState) -> List[str]:
        """Actions that cannot run because a record is missing from the case or a computed value is unknown."""
        absent = sorted(e for e, values in state.entities.items() if values.get(STATUS) is None)
        settable = {f"{e}.{a}" for act in self.ontology.actions.values() for ref in act.writes
                    for e, _, a in [ref.partition(".")]}
        settable |= {f"{e}.{a}" for act in self.ontology.actions.values() for o in act.outcomes
                     for e, changes in o.effects.items() for a in changes}
        out = []
        for action in self.ontology.actions.values():
            if action.for_each:
                continue
            used = {e for expr in action.requires for e, _ in expr.references} & set(absent)
            for entity in sorted(used):
                out.append(f"{action.name}: {entity} is not in the case, so nothing about it is known "
                           f"(link the {entity} record, or mark the entity \"when_absent\": \"initial\" if the "
                           "process creates it)")
            if used:
                continue
            for outcome in action.outcomes:  # a computed value from a field that is unknown and nothing sets
                for entity, changes in outcome.effects.items():
                    for attr, value in changes.items():
                        missing = sorted(f"{e}.{a}" for e, a in getattr(getattr(value, "expr", None),
                                                                        "references", ())
                                         if state.get(e, a) is None and f"{e}.{a}" not in settable)
                        if missing:
                            out.append(f"{action.name}: cannot compute {entity}.{attr} = {value.source}: "
                                       f"{', '.join(missing)} is unknown")
        return sorted(set(out))

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
                etype = self.ontology.entities.get(entity)
                value = changes[attr]
                if etype is not None and attr == STATUS and value not in etype.states:
                    return f"tool returned {ref} = {value!r}, which is not a state of {entity}"
                declared = etype.attributes.get(attr) if etype is not None else None
                if declared is not None and not type_ok(declared.type, value):  # audit GAP-010
                    return (f"tool returned {ref} = {value!r} ({type(value).__name__}), but {ref} is "
                            f"{declared.type}; nothing was applied")
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
        key = idempotency_key(run.run_key, action.name, run.attempts[action.name])
        prior = self.journal.get(key)
        if prior and prior["state"] in REPLAY:  # done before (a retry, a resume, a restart): never call again
            tool = next((t for t in candidates if t.name == prior.get("tool")), candidates[0])
            self._log(audit, "step.replayed", case=run.case_id, action=action.name, key=key, tool=prior.get("tool"),
                      state=prior["state"], resolved_by=prior.get("resolved_by"))
            return "ok", tool, ToolResult(prior.get("outcome"), prior.get("updates") or {},
                                          prior.get("message") or "", prior.get("output"))
        if prior and prior["state"] in NEEDS_PERSON:  # it may have happened: a person must say
            tool = next((t for t in candidates if t.name == prior.get("tool")), candidates[0])
            run.pending_external = {"key": key, "action": action.name, "tool": prior.get("tool"),
                                    "state": prior["state"], "detail": prior.get("detail")}
            return ("pending" if prior["state"] == PENDING else "uncertain"), tool, \
                prior.get("detail") or f"the outcome of {action.name} is {prior['state'].replace('_', ' ')}"
        if not policy.fallback_tools:
            candidates = candidates[:1]
        inputs = {ref: state.field(ref, action.binding) for ref in action.reads}
        digest = inputs_digest(inputs)
        view = self.governance.redacted_view(state, executor.principal)
        error = "tool failed"
        same_tool = None  # after an unknown outcome only the same system may be retried, with the same key

        def stop(status: str, tool, detail: str, state_name: str):
            run.pending_external = {"key": key, "action": action.name, "tool": tool.name, "state": state_name,
                                    "detail": detail}
            return status, tool, detail

        while True:
            round_no = run.failures[action.name] + 1
            this_round = [same_tool] if same_tool else (candidates if round_no > policy.fallback_after
                                                        else candidates[:1])
            for tool in this_round:
                call = ToolCall(action.action.name, action.capability, dict(inputs), view, round_no, action.target,
                                key)
                # write-ahead: the intent is on record before anything can happen outside (audit GAP-007)
                self.journal.intent(key, run_key=run.run_key, case_id=run.case_id, root=run.root,
                                    agent=self.name, action=action.name, tool=tool.name, inputs_digest=digest)
                self._log(audit, "step.intent", case=run.case_id, action=action.name, tool=tool.name, key=key,
                          attempt=round_no, inputs_digest=digest, side_effect=action.side_effect)
                self._log(audit, "tool.call", case=run.case_id, action=action.name, tool=tool.name,
                          attempt=round_no, executed_by=executor.name, cost=tool.cost)
                run.costs["tools"] += tool.cost
                try:
                    result = tool.handler(call) or ToolResult()
                except OutcomeUnknown as exc:
                    error = str(exc)
                    self.journal.result(key, UNKNOWN, detail=error)
                    self._log(audit, "step.result", case=run.case_id, action=action.name, key=key, state=UNKNOWN,
                              error=error)
                    if action.side_effect == "non_idempotent":
                        return stop("uncertain", tool, f"{tool.name}: {error}; it may have acted", UNKNOWN)
                    same_tool = tool  # idempotent or read-only: retry this system with the same key, no fallback
                    break
                except Rejected as exc:
                    error = str(exc)
                    self.journal.result(key, REJECTED, detail=error)
                    self._log(audit, "step.result", case=run.case_id, action=action.name, key=key, state=REJECTED,
                              error=error)
                    if not exc.retryable:
                        return "failed", tool, error
                except ToolError as exc:
                    error = str(exc)
                    outcome = NOT_SENT if isinstance(exc, NotSent) else FAILED
                    self.journal.result(key, outcome, detail=error)
                    self._log(audit, "tool.error", case=run.case_id, action=action.name, tool=tool.name,
                              attempt=round_no, error=error, state=outcome)
                except Exception as exc:  # a bug or an unexpected failure in the tool: it may have acted partly
                    error = f"{type(exc).__name__}: {exc}"
                    self.journal.result(key, UNKNOWN, detail=error)
                    self._log(audit, "tool.exception", case=run.case_id, action=action.name, tool=tool.name,
                              attempt=round_no, error=error)
                    return stop("crashed", tool, error, UNKNOWN)
                else:
                    state_name, detail = self._confirmation(action, result)
                    self.journal.result(key, state_name, outcome=result.outcome, updates=result.updates,
                                        message=result.message, output=result.output, detail=detail)
                    self._log(audit, "step.result", case=run.case_id, action=action.name, key=key, state=state_name,
                              detail=detail)
                    if state_name == PENDING:
                        return stop("pending", tool, detail, PENDING)
                    if state_name == REJECTED:
                        return "failed", tool, detail
                    return "ok", tool, result
            run.failures[action.name] += 1
            if run.failures[action.name] >= policy.max_attempts:
                if same_tool:  # retries of an unknown outcome ran out: a person decides what happened
                    return stop("uncertain", same_tool, f"{same_tool.name}: {error}; it may have acted", UNKNOWN)
                return "failed", candidates[0], error
            if policy.backoff_seconds > self.max_inline_wait:
                run.resume_at = self.clock() + policy.backoff_seconds
                return "deferred", candidates[0], error
            if policy.backoff_seconds:
                self.sleep(policy.backoff_seconds)

    @staticmethod
    def _confirmation(action: GroundAction, result: ToolResult) -> Tuple[str, str]:
        """Is the reply a confirmation? ``done``, ``pending_confirmation`` or ``rejected``, with the reason."""
        spec = action.action.confirmation
        if result.pending:
            return PENDING, f"{action.name}: the system accepted the request but has not confirmed it"
        if spec is None:
            return DONE, ""
        if spec.accepted:
            status = result.output.get("status") if isinstance(result.output, dict) else None
            if status is None:
                return PENDING, f"{action.name}: the reply has no status (expected one of {list(spec.accepted)})"
            if str(status) not in spec.accepted:
                return REJECTED, f"{action.name}: the system answered status {status!r}, not one of {list(spec.accepted)}"
        missing = [ref for ref in spec.fields
                   if (result.updates.get(ref.partition(".")[0]) or {}).get(ref.partition(".")[2]) in (None, "")]
        if missing:
            return PENDING, f"{action.name}: the reply does not confirm {', '.join(missing)}"
        return DONE, ""

    # -- public API -----------------------------------------------------
    def run(self, goal_name: str, case: Mapping[str, Mapping[str, Any]], case_id: str = "case",
            started_by: Optional[str] = None, run_key: Optional[str] = None, root: Optional[str] = None,
            roles: Optional[Iterable[str]] = None, acting_as: Optional[str] = None) -> RunResult:
        """Run toward a goal. ``run_key`` fixes the run's identity (and so its idempotency keys): pass the same
        key to make a repeat of the same work replay its completed external calls instead of making them again.
        ``roles`` narrows what the agent (and its delegates) may do in this run, for example to the roles of
        the person who asked; ``acting_as`` names that person or service identity in the audit."""
        import uuid

        if goal_name not in self.ontology.goals:
            raise OntologyError(f"unknown goal {goal_name!r}")
        run = RunState(goal_name, case_id, WorldState.initial(self.ontology, case), ontology_ref=self.ontology.ref,
                       run_key=run_key or uuid.uuid4().hex, root=root,
                       roles=sorted(roles) if roles is not None else None)
        audit = AuditLog(self.audit_key)
        effective = self.principal.roles & frozenset(roles) if roles is not None else self.principal.roles
        self._log(audit, "run.start", case=case_id, agent=self.name, roles=sorted(effective),
                  agent_roles=sorted(self.principal.roles), acting_as=acting_as,
                  delegates=[d.name for d in self.delegates], goal=goal_name, ontology=self.ontology.ref,
                  fingerprint=self.ontology.fingerprint, started_by=started_by, run_key=run.run_key)
        return self._loop(run, audit)

    def resume(self, previous: RunResult, force: bool = False,
               decision: Optional[ReviewDecision] = None, refresh: Sequence[Mapping[str, Any]] = (),
               conflicts: Sequence[Mapping[str, Any]] = ()) -> RunResult:
        """Continue a deferred, paused or awaiting-review run.

        Deferred runs wait for their retry window (unless ``force``); a run awaiting review needs the
        reviewer's ``decision``, which is applied to exactly the action that was waiting for it.
        """
        if previous.run is None or previous.status not in ("deferred", "paused", "awaiting_review", "uncertain",
                                                            "pending_confirmation"):
            raise ValueError(f"cannot resume a run with status {previous.status!r}")
        run = previous.run
        if previous.status in ("uncertain", "pending_confirmation"):
            pending = run.pending_external or {}
            row = self.journal.get(pending.get("key", "")) if pending else None
            if row is None or row["state"] not in (RESOLVED_DONE, RESOLVED_NOT_DONE):
                raise ValueError(f"the outcome of {pending.get('action', 'an external call')} has not been "
                                 "reconciled yet")
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
            stale = self._refresh(run, previous.audit, refresh, conflicts, pending) if (refresh or conflicts) else None
            if stale == "conflict":  # the run and someone else both changed a field it relies on: a person decides
                escalation = Escalation(
                    "the records changed while the run waited for review, on fields the run had changed too; "
                    "the decision was recorded but not applied", "operations", pending.get("action"),
                    [f"{c['entity']}.{c['attr']}: run {c['run']!r}, live {c['live']!r}" for c in conflicts])
                run.pending_review = None
                self._log(previous.audit, "run.end", case=run.case_id, status="escalated",
                          escalation=escalation.__dict__, state=run.state.snapshot(), costs=dict(run.costs),
                          resume_at=None)
                return RunResult("escalated", run.goal, run.case_id, run.steps, run.state, previous.audit,
                                 escalation, run.violations, dict(run.costs), None, run)
            if stale == "superseded" and decision.approved:
                # the reviewer approved other facts than the ones now true: ask again (audit GAP-009)
                self._log(previous.audit, "review.superseded", case=run.case_id, action=pending.get("action", ""),
                          reviewer=decision.reviewer, reviewed=pending.get("facts"))
                run.pending_review = None
                run.resume_at = None
                self._log(previous.audit, "run.resume", case=run.case_id, agent=self.name,
                          previous_status=previous.status)
                return self._loop(run, previous.audit)
            run.review_decisions[pending.get("action", "")] = {
                "approved": bool(decision.approved), "reviewer": decision.reviewer, "comment": decision.comment,
                "automatic": bool(getattr(decision, "automatic", False)),
                "audit_seq": entry.seq, "audit_hash": entry.hash}  # bound to the entry that granted it
            run.pending_review = None
        if run.ontology_ref != self.ontology.ref:
            raise OntologyError(f"run was started on {run.ontology_ref}; this agent uses {self.ontology.ref}")
        run.resume_at = None
        audit = previous.audit
        if previous.status in ("uncertain", "pending_confirmation"):
            row = self.journal.get(run.pending_external["key"])
            self._log(audit, "external.reconciled", case=run.case_id, action=run.pending_external["action"],
                      key=row["key"], done=row["state"] == RESOLVED_DONE, by=row.get("resolved_by"),
                      comment=row.get("resolved_comment"))
            run.pending_external = None
        self._log(audit, "run.resume", case=run.case_id, agent=self.name, previous_status=previous.status)
        return self._loop(run, audit)

    def _refresh(self, run: RunState, audit: AuditLog, refresh: Sequence[Mapping[str, Any]],
                 conflicts: Sequence[Mapping[str, Any]], pending: Mapping[str, Any]) -> Optional[str]:
        """Bring in what changed on the live records while the run waited (ACT-6). Returns ``"conflict"`` when
        a field the run had changed was changed outside too, ``"superseded"`` when a fact the reviewer saw is no
        longer true, else ``None``."""
        state = run.state
        for change in refresh:
            entity, iid = change["entity"], change.get("instance")
            if iid is not None and entity in state.collections:
                state.collections[entity].setdefault(iid, {})[change["attr"]] = change["live"]
            elif entity in state.entities:
                state.entities[entity][change["attr"]] = change["live"]
        self._log(audit, "case.refreshed", case=run.case_id,
                  changes=[{k: c.get(k) for k in ("entity", "instance", "attr", "base", "live")} for c in refresh],
                  conflicts=[dict(c) for c in conflicts])
        if conflicts:
            return "conflict"
        action = pending.get("action")
        if not action:
            return None
        try:
            ga = ground(self.ontology, action)
        except (OntologyError, KeyError):
            return "superseded"
        now = self.governance.evaluate(ga, state, self.principal)
        if not all(e.evaluate(state.resolver(ga.binding)) for e in ga.action.requires) or \
                self._normal(now.facts) != self._normal(pending.get("facts") or {}):
            return "superseded"
        return None

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
        if getattr(previous, "integrity_problem", None):
            return previous.integrity_problem
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
        if run.roles is None:
            return self._loop_body(run, audit)
        allowed = frozenset(run.roles)
        saved = [(m, m.principal) for m in [self] + list(self.delegates)]
        try:  # the agent and its delegates act with no more than the run's roles (the caller holds the lock)
            for member, principal in saved:
                member.principal = Principal(principal.name, principal.roles & allowed)
            return self._loop_body(run, audit)
        finally:
            for member, principal in saved:
                member.principal = principal

    def _loop_body(self, run: RunState, audit: AuditLog) -> RunResult:
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

            try:
                plan = self.planner.plan(state, goal, self.team)
            except SearchBudgetExceeded as exc:
                return finish("escalated", Escalation(f"planning search budget exhausted: {exc}", "operations",
                                                      details=["raise the planner's max_expansions, or simplify "
                                                               "the case"]))
            if plan is None:
                return finish("escalated", Escalation("no compliant path to the goal", "operations",
                                                      details=self._explain_block(state, goal)))
            self._log(audit, "plan", case=run.case_id, step=index, plan=plan)

            ctx = DecisionContext(self.ontology, goal, plan, self.planner.applicable(state, self.team),
                                  self.governance.redacted_view(state, self.principal), list(run.history))
            proposal = self.reasoner.propose(ctx)
            run.costs["llm_usd"] += proposal.cost_usd
            if proposal.unpriced_tokens:  # a model without a price: its cost is unknown, never counted as free
                run.costs["llm_unpriced_tokens"] = run.costs.get("llm_unpriced_tokens", 0) + proposal.unpriced_tokens
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
                      llm_cost_usd=proposal.cost_usd, unpriced_tokens=proposal.unpriced_tokens)
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
                used_decision = stored
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

            else:
                used_decision = None
            try:
                status, tool, payload = self._execute(run, action, executor, audit)
            except LookupError as exc:
                run.steps.append(record)
                return finish("escalated", Escalation(str(exc), "it-integration", action.name))
            record.tool = tool.name
            if status in ("crashed", "uncertain", "pending"):
                # the outside system may have acted: never retry blindly, a person reconciles the step
                run.attempts[action.name] -= 1  # the same step (and key) when the run continues
                if used_decision:  # the approval covers this step until it really completes
                    run.review_decisions[action.name] = used_decision
                record.message = payload
                run.steps.append(record)
                if status == "pending":
                    return finish("pending_confirmation", Escalation(
                        f"{action.name}: waiting for confirmation ({payload})", "reconciliation", action.name,
                        [f"idempotency key {run.pending_external['key']}"]))
                reason = (f"{action.name}: tool {tool.name} raised {payload}; it may have acted partly"
                          if status == "crashed" else f"{action.name}: outcome unknown ({payload})")
                return finish("uncertain", Escalation(
                    reason + "; confirm whether it happened before the run continues",
                    "it-integration" if status == "crashed" else "reconciliation", action.name,
                    [f"idempotency key {run.pending_external['key']}"]))
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
