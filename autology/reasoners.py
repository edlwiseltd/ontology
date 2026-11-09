"""Reasoners decide *which* compliant action an agent takes next.

The reasoner is the "intelligence" slot of the agent. It never acts on its
own: it proposes one of the candidate actions the ontology allows right now,
and the governance layer has the final word. That makes it safe to plug in a
language model - an LLM can choose among ontology-valid moves, but it cannot
invent a step, skip a mandatory one, or read data the agent is not entitled to.

Cost controls (methodology section 4.2):

* :class:`RoutingReasoner` right-sizes the model per decision - no model call
  at all when only one move is valid, a small model for simple choices, a
  large model for complex ones;
* :class:`ClaudeReasoner` caches decisions for identical (redacted) situations,
  keeps the stable ontology prefix in the system prompt so it is prompt-cached,
  and reports token usage and cost on every proposal.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol

from .ontology import ActionType, Goal, Ontology

# USD per million tokens (input, output). Update from the provider's pricing page.
PRICES: Dict[str, tuple] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_READ_FACTOR = 0.1  # cache reads bill at ~0.1x the input rate
CACHE_WRITE_FACTOR = 1.25  # 5-minute cache writes bill at 1.25x
# models that accept the server-side refusal fallback (`fallbacks: "default"`) on the Claude API
SERVER_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-1"})


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
    source: str  # "planner", "llm", "llm-cache", "override", ...
    model: Optional[str] = None
    usage: Dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0


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


def estimate_cost(model: str, usage: Mapping[str, int]) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (usage.get("input_tokens", 0) * price_in
            + usage.get("cache_read_input_tokens", 0) * price_in * CACHE_READ_FACTOR
            + usage.get("cache_creation_input_tokens", 0) * price_in * CACHE_WRITE_FACTOR
            + usage.get("output_tokens", 0) * price_out) / 1_000_000


class ClaudeReasoner:
    """Lets Claude pick the next action, constrained to ontology-valid candidates.

    Structured output restricts the reply to ``{"action": <one candidate>, "rationale": ...}``.
    Any API error, refusal or malformed reply falls back to the deterministic
    planner, so the agent never stalls because the model is unavailable.

    Requires ``pip install anthropic`` and credentials in the environment
    (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile).
    """

    def __init__(self, client: Any = None, model: str = "claude-opus-5-5", effort: str = "medium",
                 max_tokens: int = 16000, fallback: Optional[Reasoner] = None, cache_size: int = 256):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.fallback = fallback or PlanFollowingReasoner()
        self.last_error: Optional[str] = None
        self.cache_size = cache_size
        self._cache: "OrderedDict[str, Proposal]" = OrderedDict()
        self.calls = 0
        self.cache_hits = 0
        self.total_cost_usd = 0.0

    @staticmethod
    def _system(ctx: DecisionContext) -> str:
        # stable per ontology version -> prompt-cache friendly prefix
        return f"{SYSTEM_PROMPT}\n\n{ctx.ontology.describe()}"

    @staticmethod
    def _prompt(ctx: DecisionContext) -> str:
        candidates = "\n".join(f"- {a.name}: {a.description}" for a in ctx.candidates)
        return (
            f"GOAL: {ctx.goal.name} - {ctx.goal.description} (target: {ctx.goal.target})\n\n"
            f"CASE STATE (redacted):\n{json.dumps(ctx.view, indent=2, default=str, sort_keys=True)}\n\n"
            f"HISTORY: {', '.join(ctx.history) or 'none'}\n\n"
            f"VALID ACTIONS NOW:\n{candidates}\n\n"
            f"SUGGESTED PLAN: {' -> '.join(ctx.plan)}"
        )

    def _cache_key(self, ctx: DecisionContext) -> str:
        payload = json.dumps([self.model, ctx.ontology.fingerprint, ctx.goal.name, ctx.view,
                              [a.name for a in ctx.candidates], ctx.plan], sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _fallback(self, ctx: DecisionContext, why: str) -> Proposal:
        self.last_error = why
        proposal = self.fallback.propose(ctx)
        proposal.rationale = f"{proposal.rationale} (LLM fallback: {why})"
        return proposal

    def propose(self, ctx: DecisionContext) -> Proposal:
        names = [a.name for a in ctx.candidates]
        if not names:
            return self._fallback(ctx, "no candidates")
        key = self._cache_key(ctx)
        if key in self._cache:
            self.cache_hits += 1
            self._cache.move_to_end(key)
            hit = self._cache[key]
            return Proposal(hit.action, hit.rationale, "llm-cache", self.model)
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
        request: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            cache_control={"type": "ephemeral"},
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            system=self._system(ctx),
            messages=[{"role": "user", "content": self._prompt(ctx)}],
        )
        if self.model in SERVER_FALLBACK_MODELS:
            request.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        self.calls += 1
        try:
            response = self.client.beta.messages.create(**request)
        except api_errors as exc:  # type: ignore[misc]
            return self._fallback(ctx, f"{type(exc).__name__}: {exc}")
        usage = self._usage(response)
        cost = estimate_cost(self.model, usage)
        self.total_cost_usd += cost
        if response.stop_reason != "end_turn":
            proposal = self._fallback(ctx, f"stop_reason={response.stop_reason}")
            proposal.usage, proposal.cost_usd = usage, cost
            return proposal
        try:
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
            action, rationale = data["action"], data["rationale"]
        except (StopIteration, ValueError, KeyError, TypeError) as exc:
            proposal = self._fallback(ctx, f"unparseable reply: {exc!r}")
            proposal.usage, proposal.cost_usd = usage, cost
            return proposal
        if action not in names:
            proposal = self._fallback(ctx, f"model chose non-candidate {action!r}")
            proposal.usage, proposal.cost_usd = usage, cost
            return proposal
        self.last_error = None
        proposal = Proposal(action, rationale, "llm", getattr(response, "model", self.model), usage, cost)
        self._cache[key] = proposal
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return proposal

    @staticmethod
    def _usage(response: Any) -> Dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        return {f: int(getattr(usage, f, 0) or 0) for f in fields}


class RoutingReasoner:
    """Right-size the model per decision.

    * one valid move (or the plan's step is the only candidate) -> no model call;
    * up to ``simple_max_candidates`` valid moves -> ``simple`` reasoner (small model);
    * otherwise -> ``complex`` reasoner (large model).
    """

    def __init__(self, simple: Optional[Reasoner] = None, complex: Optional[Reasoner] = None,
                 simple_max_candidates: int = 2, deterministic: Optional[Reasoner] = None):
        self.deterministic = deterministic or PlanFollowingReasoner()
        self.simple = simple or self.deterministic
        self.complex = complex or self.simple
        self.simple_max_candidates = simple_max_candidates
        self.routes: Dict[str, int] = {"deterministic": 0, "simple": 0, "complex": 0}

    @classmethod
    def with_claude(cls, client: Any = None, small_model: str = "claude-haiku-5-5",
                    large_model: str = "claude-opus-5-5", **kw: Any) -> "RoutingReasoner":
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        return cls(ClaudeReasoner(client, small_model, effort="low"),
                   ClaudeReasoner(client, large_model, effort="medium"), **kw)

    def propose(self, ctx: DecisionContext) -> Proposal:
        n = len(ctx.candidates)
        if n <= 1:
            route, reasoner = "deterministic", self.deterministic
        elif n <= self.simple_max_candidates:
            route, reasoner = "simple", self.simple
        else:
            route, reasoner = "complex", self.complex
        self.routes[route] += 1
        proposal = reasoner.propose(ctx)
        if route == "deterministic":
            proposal.rationale = f"{proposal.rationale} (only one valid action: no model call)"
        return proposal
