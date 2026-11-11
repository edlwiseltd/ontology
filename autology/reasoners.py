"""Reasoners decide *which* compliant action an agent takes next.

The reasoner is the "intelligence" slot of the agent. It never acts on its
own: it proposes one of the candidate actions the ontology allows right now,
and the governance layer has the final word. That makes it safe to plug in a
language model - a model can choose among ontology-valid moves, but it cannot
invent a step, skip a mandatory one, or read data the agent is not entitled to.

Provider-agnostic: :class:`LLMReasoner` works with any :class:`ChatModel` -
an object with ``complete_json(system, prompt, schema, effort)``. Adapters:

* :class:`AnthropicChatModel` - Claude via the official ``anthropic`` SDK (default);
* :class:`FunctionChatModel` - wrap any callable: another vendor's SDK, a local
  model server, a rules engine, or a test double.

:class:`ClaudeReasoner` is ``LLMReasoner(AnthropicChatModel(...))``.

Cost controls: :class:`RoutingReasoner` right-sizes the model per decision
(no call when only one move is valid; small model for simple choices; large
model for complex ones); :class:`LLMReasoner` caches decisions for identical
redacted situations, keeps the stable ontology prefix in the system prompt
(prompt-cache friendly) and reports usage and cost on every proposal.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple

from .ontology import ActionType, Goal, Ontology

# USD per million tokens (input, output). Extend with register_price() for other models/providers.
PRICES: Dict[str, Tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_READ_FACTOR = 0.1  # cache reads bill at ~0.1x the input rate
CACHE_WRITE_FACTOR = 1.25  # 5-minute cache writes bill at 1.25x
# Claude models that accept the server-side refusal fallback (`fallbacks: "default"`) on the Claude API
SERVER_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-1"})


def register_price(model: str, input_per_mtok: float, output_per_mtok: float) -> None:
    """Add or update a model's price so costs are tracked for any provider."""
    PRICES[model] = (float(input_per_mtok), float(output_per_mtok))


def is_priced(model: Optional[str]) -> bool:
    return model in PRICES


def billable_tokens(usage: Mapping[str, int]) -> int:
    return sum(int(usage.get(k, 0) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                     "cache_creation_input_tokens"))


def estimate_cost(model: str, usage: Mapping[str, int]) -> float:
    """USD cost of ``usage``. A model missing from PRICES returns 0.0 here: callers must check
    :func:`is_priced` and report its tokens as *unpriced* rather than free (see LLMReasoner)."""
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (usage.get("input_tokens", 0) * price_in
            + usage.get("cache_read_input_tokens", 0) * price_in * CACHE_READ_FACTOR
            + usage.get("cache_creation_input_tokens", 0) * price_in * CACHE_WRITE_FACTOR
            + usage.get("output_tokens", 0) * price_out) / 1_000_000


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
    unpriced_tokens: int = 0  # tokens of a model with no registered price: cost unknown, not zero


class Reasoner(Protocol):
    def propose(self, ctx: DecisionContext) -> Proposal: ...


class PlanFollowingReasoner:
    """Deterministic default: take the next step of the cheapest compliant plan."""

    def propose(self, ctx: DecisionContext) -> Proposal:
        step = ctx.plan[0]
        return Proposal(step, f"next step of planned path {' -> '.join(ctx.plan)}", "planner")


# -- provider-neutral model interface ------------------------------------------------
@dataclass
class LLMResponse:
    data: Optional[Dict[str, Any]]  # parsed JSON object matching the schema, or None
    stop_reason: str = "end_turn"  # "end_turn" means a complete answer; anything else triggers fallback
    usage: Dict[str, int] = field(default_factory=dict)
    model: Optional[str] = None
    error: Optional[str] = None  # transport/API error description


class ChatModel(Protocol):
    model: str

    def complete_json(self, *, system: str, prompt: str, schema: Dict[str, Any],
                      effort: Optional[str] = None) -> LLMResponse: ...


class FunctionChatModel:
    """Adapt any callable ``fn(system, prompt, schema) -> dict`` (or ``(dict, usage)``) into a ChatModel.

    Use it to plug in another provider's SDK, a local model, or a deterministic stub.
    Exceptions raised by ``fn`` become an error response, so the reasoner falls back safely.
    """

    def __init__(self, fn: Callable[..., Any], model: str = "custom"):
        self.fn = fn
        self.model = model

    def complete_json(self, *, system: str, prompt: str, schema: Dict[str, Any],
                      effort: Optional[str] = None) -> LLMResponse:
        try:
            out = self.fn(system, prompt, schema)
        except Exception as exc:  # adapter boundary: any provider failure must degrade, not crash
            return LLMResponse(None, "error", {}, self.model, f"{type(exc).__name__}: {exc}")
        usage: Dict[str, int] = {}
        if isinstance(out, tuple):
            out, usage = out
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except ValueError as exc:
                return LLMResponse(None, "end_turn", usage, self.model, f"unparseable reply: {exc!r}")
        return LLMResponse(out if isinstance(out, dict) else None, "end_turn", dict(usage), self.model,
                           None if isinstance(out, dict) else "reply is not a JSON object")


class AnthropicChatModel:
    """Claude through the official ``anthropic`` SDK, with structured output.

    Enables prompt caching and, on models that support it, the server-side
    refusal fallback. Requires ``pip install anthropic`` and credentials
    (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile).
    """

    def __init__(self, client: Any = None, model: str = "claude-opus-5-5", effort: str = "medium",
                 max_tokens: int = 16000):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def complete_json(self, *, system: str, prompt: str, schema: Dict[str, Any],
                      effort: Optional[str] = None) -> LLMResponse:
        try:
            import anthropic

            api_errors: tuple = (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError)
        except ImportError:  # an injected client (e.g. a test double) without the SDK installed
            api_errors = ()
        request: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            cache_control={"type": "ephemeral"},
            output_config={"effort": effort or self.effort, "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        if self.model in SERVER_FALLBACK_MODELS:
            request.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            response = self.client.beta.messages.create(**request)
        except api_errors as exc:  # type: ignore[misc]
            return LLMResponse(None, "error", {}, self.model, f"{type(exc).__name__}: {exc}")
        usage = self._usage(response)
        served = getattr(response, "model", self.model)
        if response.stop_reason != "end_turn":
            return LLMResponse(None, str(response.stop_reason), usage, served)
        try:
            text = next(b.text for b in response.content if b.type == "text")
            data = json.loads(text)
        except (StopIteration, ValueError, TypeError) as exc:
            return LLMResponse(None, "end_turn", usage, served, f"unparseable reply: {exc!r}")
        return LLMResponse(data if isinstance(data, dict) else None, "end_turn", usage, served,
                           None if isinstance(data, dict) else "reply is not a JSON object")

    @staticmethod
    def _usage(response: Any) -> Dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        return {f: int(getattr(usage, f, 0) or 0) for f in fields}


SYSTEM_PROMPT = """You are the reasoning module of an Autology work agent. A business \
ontology defines the entities, actions and immutable rules of the organisation. Each \
turn you receive the goal, the current (redacted) case state, the actions that are \
valid right now, and the cheapest compliant plan computed from the ontology.

Choose the single next action that best advances the goal. Follow the suggested plan \
unless the case context gives a concrete reason to prefer another valid action, and \
say what that reason is. You can only choose from the listed actions; governance \
re-checks every choice, so never try to work around a rule."""


class LLMReasoner:
    """Lets any :class:`ChatModel` pick the next action, constrained to ontology-valid candidates.

    The answer must be ``{"action": <one candidate>, "rationale": ...}``; any error,
    refusal, truncation or invalid choice falls back to the deterministic planner, so
    the agent never stalls because a model is unavailable.
    """

    def __init__(self, model: ChatModel, fallback: Optional[Reasoner] = None, cache_size: int = 256,
                 effort: Optional[str] = None):
        self.chat = model
        self.effort = effort
        self.fallback = fallback or PlanFollowingReasoner()
        self.last_error: Optional[str] = None
        self.cache_size = cache_size
        self._cache: "OrderedDict[str, Proposal]" = OrderedDict()
        self.calls = 0
        self.cache_hits = 0
        self.total_cost_usd = 0.0

    @property
    def model(self) -> str:
        return self.chat.model

    @staticmethod
    def system_prompt(ctx: DecisionContext) -> str:
        # stable per ontology version -> prompt-cache friendly prefix
        return f"{SYSTEM_PROMPT}\n\n{ctx.ontology.describe()}"

    @staticmethod
    def user_prompt(ctx: DecisionContext) -> str:
        candidates = "\n".join(f"- {a.name}: {a.description}" for a in ctx.candidates)
        return (
            f"GOAL: {ctx.goal.name} - {ctx.goal.description} (target: {ctx.goal.target})\n\n"
            f"CASE STATE (redacted):\n{json.dumps(ctx.view, indent=2, default=str, sort_keys=True)}\n\n"
            f"HISTORY: {', '.join(ctx.history) or 'none'}\n\n"
            f"VALID ACTIONS NOW:\n{candidates}\n\n"
            f"SUGGESTED PLAN: {' -> '.join(ctx.plan)}"
        )

    @staticmethod
    def schema(names: List[str]) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": names}, "rationale": {"type": "string"}},
            "required": ["action", "rationale"],
            "additionalProperties": False,
        }

    def _cache_key(self, ctx: DecisionContext) -> str:
        payload = json.dumps([self.model, ctx.ontology.fingerprint, ctx.goal.name, ctx.view,
                              [a.name for a in ctx.candidates], ctx.plan], sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _fallback(self, ctx: DecisionContext, why: str, usage=None, cost: float = 0.0, unpriced: int = 0,
                  model: Optional[str] = None) -> Proposal:
        self.last_error = why
        proposal = self.fallback.propose(ctx)
        proposal.rationale = f"{proposal.rationale} (LLM fallback: {why})"
        proposal.usage, proposal.cost_usd, proposal.unpriced_tokens = dict(usage or {}), cost, unpriced
        if usage:
            proposal.model = model  # the model that was called, even though the planner chose
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
        self.calls += 1
        response = self.chat.complete_json(system=self.system_prompt(ctx), prompt=self.user_prompt(ctx),
                                           schema=self.schema(names), effort=self.effort)
        served = response.model or self.model
        cost = estimate_cost(served, response.usage)
        unpriced = 0 if is_priced(served) else billable_tokens(response.usage)  # unknown cost, not zero
        self.total_cost_usd += cost
        spent = (response.usage, cost, unpriced, served)
        if response.error and response.stop_reason == "error":
            return self._fallback(ctx, response.error, *spent)
        if response.stop_reason != "end_turn":
            return self._fallback(ctx, f"stop_reason={response.stop_reason}", *spent)
        if response.error or response.data is None:
            return self._fallback(ctx, response.error or "empty reply", *spent)
        action, rationale = response.data.get("action"), response.data.get("rationale", "")
        if action not in names:
            return self._fallback(ctx, f"model chose non-candidate {action!r}", *spent)
        self.last_error = None
        proposal = Proposal(action, str(rationale), "llm", served, response.usage, cost, unpriced)
        self._cache[key] = proposal
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return proposal


class ClaudeReasoner(LLMReasoner):
    """:class:`LLMReasoner` backed by Claude (:class:`AnthropicChatModel`)."""

    def __init__(self, client: Any = None, model: str = "claude-opus-5-5", effort: str = "medium",
                 max_tokens: int = 16000, fallback: Optional[Reasoner] = None, cache_size: int = 256):
        super().__init__(AnthropicChatModel(client, model, effort, max_tokens), fallback, cache_size)

    @property
    def client(self) -> Any:
        return self.chat.client


class RoutingReasoner:
    """Right-size the model per decision.

    * one valid move -> no model call;
    * up to ``simple_max_candidates`` valid moves -> ``simple`` reasoner (small model);
    * otherwise -> ``complex`` reasoner (large model).

    Works with any reasoners, so small and large models may come from different providers.
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
