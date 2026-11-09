"""Reasoners decide *which* compliant action an agent takes next.

The reasoner is the "intelligence" slot of the agent. It never acts on its
own: it proposes one of the candidate actions the ontology allows right now,
and the governance layer has the final word. That makes it safe to plug in a
language model - an LLM can choose among ontology-valid moves, but it cannot
invent a step, skip a mandatory one, or read data the agent is not entitled to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol

from .ontology import ActionType, Goal, Ontology


@dataclass
class DecisionContext:
    ontology: Ontology
    goal: Goal
    plan: List[str]  # the planner's cheapest compliant path from here
    candidates: List[ActionType]  # actions whose preconditions + hard rules hold now
    view: Mapping[str, Mapping[str, Any]]  # redacted state
    history: List[str] = field(default_factory=list)  # "action -> outcome" so far


@dataclass
class Proposal:
    action: str
    rationale: str
    source: str  # "planner", "llm", "override", ...


class Reasoner(Protocol):
    def propose(self, ctx: DecisionContext) -> Proposal: ...


class PlanFollowingReasoner:
    """Deterministic default: take the next step of the cheapest compliant plan."""

    def propose(self, ctx: DecisionContext) -> Proposal:
        step = ctx.plan[0]
        return Proposal(step, f"next step of planned path {' -> '.join(ctx.plan)}", "planner")


SYSTEM_PROMPT = """You are the reasoning module of an Autology work agent. A business \
ontology defines the entities, actions and immutable rules of the organisation. Each \
turn you receive the goal, the current (redacted) case state, the actions that are \
valid right now, and the cheapest compliant plan computed from the ontology.

Choose the single next action that best advances the goal. Follow the suggested plan \
unless the case context gives a concrete reason to prefer another valid action, and \
say what that reason is. You can only choose from the listed actions; governance \
re-checks every choice, so never try to work around a rule."""


class ClaudeReasoner:
    """Lets Claude pick the next action, constrained to ontology-valid candidates.

    Structured output restricts the reply to ``{"action": <one candidate>, "rationale": ...}``.
    Any API error, refusal or malformed reply falls back to the deterministic
    planner, so the agent never stalls because the model is unavailable.

    Requires ``pip install anthropic`` and credentials in the environment
    (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile).
    """

    def __init__(self, client: Any = None, model: str = "claude-opus-5-5", effort: str = "medium",
                 max_tokens: int = 16000, fallback: Optional[Reasoner] = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallback = fallback or PlanFollowingReasoner()
        self.last_error: Optional[str] = None

    @staticmethod
    def _prompt(ctx: DecisionContext) -> str:
        candidates = "\n".join(f"- {a.name}: {a.description}" for a in ctx.candidates)
        return (
            f"{ctx.ontology.describe()}\n\n"
            f"GOAL: {ctx.goal.name} - {ctx.goal.description} (target: {ctx.goal.target})\n\n"
            f"CASE STATE (redacted):\n{json.dumps(ctx.view, indent=2, default=str)}\n\n"
            f"HISTORY: {', '.join(ctx.history) or 'none'}\n\n"
            f"VALID ACTIONS NOW:\n{candidates}\n\n"
            f"SUGGESTED PLAN: {' -> '.join(ctx.plan)}"
        )

    def _fallback(self, ctx: DecisionContext, why: str) -> Proposal:
        self.last_error = why
        proposal = self.fallback.propose(ctx)
        proposal.rationale = f"{proposal.rationale} (LLM fallback: {why})"
        return proposal

    def propose(self, ctx: DecisionContext) -> Proposal:
        names = [a.name for a in ctx.candidates]
        if not names:
            return self._fallback(ctx, "no candidates")
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": names},
                "rationale": {"type": "string"},
            },
            "required": ["action", "rationale"],
            "additionalProperties": False,
        }
        try:
            import anthropic

            api_errors = (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError)
        except ImportError:  # an injected client (e.g. a test double) without the SDK installed
            api_errors = ()
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self._prompt(ctx)}],
            )
        except api_errors as exc:  # type: ignore[misc]
            return self._fallback(ctx, f"{type(exc).__name__}: {exc}")
        if response.stop_reason != "end_turn":
            return self._fallback(ctx, f"stop_reason={response.stop_reason}")
        try:
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
            action, rationale = data["action"], data["rationale"]
        except (StopIteration, ValueError, KeyError, TypeError) as exc:
            return self._fallback(ctx, f"unparseable reply: {exc!r}")
        if action not in names:
            return self._fallback(ctx, f"model chose non-candidate {action!r}")
        self.last_error = None
        return Proposal(action, rationale, "llm")
