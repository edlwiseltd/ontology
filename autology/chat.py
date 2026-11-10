"""Governed chat: a conversational assistant that can only act through the deployment's API, as the user.

The assistant never touches data or agents directly. Every tool call goes through
:class:`autology.server.AutologyService` with the signed-in user's identity, so:

* it sees exactly what the user may see (row access hides records, field rules redact values);
* it can do only what the user's permissions allow (tools for running agents or scenarios are
  offered only to users with the ``run`` permission);
* runs it starts are governed agent runs: rules, human reviews and audit apply;
* it **cannot decide human reviews**. It can explain one, but a person decides in the inbox.

The model backend is provider-neutral (:class:`ChatBackend`). :class:`AnthropicChatBackend` uses Claude
through the official SDK; :class:`ScriptedChatBackend` drives the same loop from a function, for tests,
demos and other providers.

Server config::

    "chat": {"model": "claude-opus-5-5", "effort": "medium"}       # Claude (needs the anthropic package)
    "chat": {"backend": "my_module:factory"}                         # any ChatBackend
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

MAX_RESULT_CHARS = 20_000
MAX_TOOL_ROUNDS = 8

SYSTEM_PROMPT = """You are the assistant of an Autology deployment: a business ontology with governed \
agents. You help one signed-in person understand their data, runs and reviews, and start work.

You act only through the tools provided. They run as the signed-in person, so results show only \
what that person may see: hidden records are absent and some fields read "***redacted***". Do not \
guess at hidden or redacted values, and say so when something may be hidden from them.

Answer from tool results, not from memory, and name the records, runs and rules you relied on. \
When you start a run, it is governed: report its status, any review it waits for and any \
escalation, with the reason given. You cannot approve or decline reviews; point the person to \
the Reviews tab. Never say an action happened unless a tool result shows it. Keep answers short \
and concrete."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class ChatTurn:
    content: List[Dict[str, Any]]  # the assistant message content, exactly as it must be sent back
    text: str
    tool_calls: List[ToolCall]
    stop_reason: str  # end_turn | tool_use | pause_turn | max_tokens | refusal | error
    usage: Dict[str, int] = field(default_factory=dict)
    model: Optional[str] = None
    error: Optional[str] = None


class ChatBackend(Protocol):
    def turn(self, system: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ChatTurn: ...


def _block_dict(block: Any) -> Dict[str, Any]:
    if isinstance(block, dict):
        return block
    for attr in ("to_dict", "model_dump"):
        fn = getattr(block, attr, None)
        if callable(fn):
            return fn()
    return dict(vars(block))


def echo_content(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Content to send back after a server-side fallback switched models mid-output.

    Before the last ``fallback`` block, thinking and tool-use blocks of the declined attempt are
    omitted; the fallback block stays exactly where it was, and everything after it echoes as is.
    """
    marks = [i for i, b in enumerate(blocks) if b.get("type") == "fallback"]
    if not marks:
        return blocks
    cut = marks[-1]
    drop = {"thinking", "redacted_thinking", "tool_use"}
    return [b for i, b in enumerate(blocks) if i >= cut or b.get("type") not in drop]


def _strict_ok(schema: Any) -> bool:
    """Strict tool use needs closed objects throughout; free-form parameters opt out."""
    if isinstance(schema, dict):
        if schema.get("additionalProperties") is True:
            return False
        return all(_strict_ok(v) for v in schema.values())
    if isinstance(schema, list):
        return all(_strict_ok(v) for v in schema)
    return True


class AnthropicChatBackend:
    """Claude through the official ``anthropic`` SDK: a manual tool loop step with prompt caching and
    the server-side refusal fallback on models that support it."""

    def __init__(self, client: Any = None, model: str = "claude-opus-5-5", effort: str = "medium",
                 max_tokens: int = 16000):
        self._client = client  # created on first use, so a server starts without the SDK or credentials
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def turn(self, system: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ChatTurn:
        from .reasoners import SERVER_FALLBACK_MODELS

        try:
            import anthropic

            api_errors: tuple = (anthropic.APIStatusError, anthropic.APIConnectionError)
        except ImportError:  # an injected test client without the SDK installed
            api_errors = ()
        request: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=[{"name": t["name"], "description": t["description"], "input_schema": t["input_schema"],
                    **({"strict": True} if _strict_ok(t["input_schema"]) else {})} for t in tools],
            output_config={"effort": self.effort},
            messages=messages,
        )
        if self.model in SERVER_FALLBACK_MODELS:
            request.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            response = self.client.beta.messages.create(**request)
        except ImportError:
            return ChatTurn([], "", [], "error", error="the anthropic package is not installed")
        except api_errors as exc:  # type: ignore[misc]
            return ChatTurn([], "", [], "error", error=f"{type(exc).__name__}: {exc}")
        from .reasoners import AnthropicChatModel

        content = echo_content([_block_dict(b) for b in response.content])
        text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
        calls = [ToolCall(b["id"], b["name"], dict(b.get("input") or {})) for b in content
                 if b.get("type") == "tool_use"]
        return ChatTurn(content, text, calls, str(response.stop_reason), AnthropicChatModel._usage(response),
                        getattr(response, "model", self.model))


class ScriptedChatBackend:
    """Drive the chat loop from ``fn(messages, tools) -> {"text": str, "tool_calls": [{"name", "input"}]}``.

    For tests, offline demos, or adapting another provider without its SDK in this package.
    """

    def __init__(self, fn: Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]],
                 model: str = "scripted"):
        self.fn = fn
        self.model = model

    def turn(self, system: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> ChatTurn:
        out = self.fn(messages, tools)
        if out.get("stop_reason") in ("refusal", "max_tokens", "error"):
            return ChatTurn([], out.get("text", ""), [], out["stop_reason"], model=self.model, error=out.get("error"))
        calls = [ToolCall(f"call_{uuid.uuid4().hex[:8]}", c["name"], dict(c.get("input") or {}))
                 for c in out.get("tool_calls", [])]
        content: List[Dict[str, Any]] = [{"type": "text", "text": out["text"]}] if out.get("text") else []
        content += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls]
        return ChatTurn(content, out.get("text", ""), calls, "tool_use" if calls else "end_turn", model=self.model)


def _schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def tools_for(service: Any, user: Any) -> List[Dict[str, Any]]:
    """The tools this user's assistant gets, each bound to the service with the user's identity."""
    o = service.ontology
    entity = {"type": "string", "enum": sorted(o.entities)}
    tools: List[Dict[str, Any]] = [
        {"name": "describe_ontology", "permission": "read",
         "description": "Entities with their states and attributes, actions, goals, rules and competency questions "
                        "of this deployment, plus the configured agents.",
         "input_schema": _schema({}, []),
         "run": lambda a: service.ontology_summary(user)},
        {"name": "list_objects", "permission": "read",
         "description": "List objects of one entity type that the person may see (first 50).",
         "input_schema": _schema({"type": entity}, ["type"]),
         "run": lambda a: service.list_objects(user, a["type"], 50, 0)},
        {"name": "get_object", "permission": "read",
         "description": "One object by id, with its attributes and links. Hidden objects look absent.",
         "input_schema": _schema({"id": {"type": "string"}}, ["id"]),
         "run": lambda a: service.get_object(user, a["id"])},
        {"name": "ask_question", "permission": "read",
         "description": "Answer one of the ontology's competency questions over the knowledge graph.",
         "input_schema": _schema({"question_id": {"type": "string", "enum": [q.id for q in o.questions] or [""]},
                                  "params": {"type": "object", "additionalProperties": True}},
                                 ["question_id", "params"]),
         "run": lambda a: service.answer(user, a["question_id"], a.get("params") or {})},
        {"name": "list_runs", "permission": "read",
         "description": "Recent agent runs, optionally filtered by status (completed, awaiting_review, blocked, "
                        "escalated, deferred, paused, suspended).",
         "input_schema": _schema({"status": {"type": "string"}}, ["status"]),
         "run": lambda a: service.list_runs(user, a.get("status") or None, 20, 0)},
        {"name": "get_run", "permission": "read",
         "description": "One run: its steps with the rules behind each decision, status, escalation and state.",
         "input_schema": _schema({"run_id": {"type": "string"}}, ["run_id"]),
         "run": lambda a: service.get_run(user, a["run_id"])},
        {"name": "list_notifications", "permission": "read",
         "description": "The person's latest notifications: reviews waiting and automations that fired.",
         "input_schema": _schema({}, []),
         "run": lambda a: service.list_notifications(user, None, 20)},
    ]
    if user.can("review"):
        tools.append({"name": "list_reviews", "permission": "review",
                      "description": "Human reviews waiting for this person, with the rule, facts and history. "
                                     "You can explain them; only the person can decide them, in the inbox.",
                      "input_schema": _schema({}, []),
                      "run": lambda a: service.list_reviews(user, "pending")})
    if user.can("run") and o.case_templates and service.agents:
        tools.append({"name": "start_run", "permission": "run",
                      "description": "Start a governed agent run on data from the knowledge graph: a case template "
                                     "assembles the case starting at the root object. Results are written back.",
                      "input_schema": _schema({"agent": {"type": "string", "enum": sorted(service.agents)},
                                               "goal": {"type": "string", "enum": sorted(o.goals)},
                                               "case_template": {"type": "string", "enum": sorted(o.case_templates)},
                                               "root": {"type": "string"}},
                                              ["agent", "goal", "case_template", "root"]),
                      "run": lambda a: service.start_run(user, dict(a))})
    if user.can("run"):
        tools.append({"name": "what_if", "permission": "run",
                      "description": "Simulate changes in a sandbox copy of the data and compare with the live data. "
                                     "Edits: {op: set, id, attributes} | {op: add, type, id, attributes, links} | "
                                     "{op: action, action, case_template, root, target, agent}. Checks: "
                                     "{goal, case_template, root, agent}. Nothing is committed.",
                      "input_schema": _schema({"name": {"type": "string"},
                                               "edits": {"type": "array", "items": {"type": "object",
                                                                                    "additionalProperties": True}},
                                               "checks": {"type": "array", "items": {"type": "object",
                                                                                     "additionalProperties": True}}},
                                              ["name", "edits", "checks"]),
                      "run": lambda a: _what_if(service, user, a)})
    return tools


def _what_if(service: Any, user: Any, a: Dict[str, Any]) -> Dict[str, Any]:
    created = service.create_scenario(user, {"name": a.get("name") or "chat scenario", "edits": a.get("edits") or []})
    report = service.compare_scenario(user, created["scenario_id"], {"checks": a.get("checks") or []})
    report["scenario_id"] = created["scenario_id"]
    report["results"] = created["results"]
    return report


@dataclass
class ChatReply:
    chat_id: str
    reply: str
    tool_calls: List[Dict[str, Any]]
    stop_reason: str
    usage: Dict[str, int]
    model: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class GovernedChat:
    """Runs the tool loop for one user message and keeps the conversation in the store."""

    def __init__(self, service: Any, backend: ChatBackend, max_rounds: int = MAX_TOOL_ROUNDS):
        self.service = service
        self.backend = backend
        self.max_rounds = max_rounds

    def system_prompt(self, user: Any) -> str:
        o = self.service.ontology
        return (f"{SYSTEM_PROMPT}\n\nSigned in: {user.name}; permissions: {', '.join(sorted(user.permissions))}; "
                f"data roles: {', '.join(sorted(user.roles)) or 'none'}; reviewer roles: "
                f"{', '.join(sorted(user.reviewer_roles)) or 'none'}.\n\n{o.describe()}")

    def send(self, user: Any, message: str, chat_id: Optional[str] = None) -> ChatReply:
        from .server import ApiError

        store = self.service.store
        if chat_id:
            convo = store.get_chat(chat_id)
            if convo is None or convo["owner"] != user.name:
                raise ApiError(404, f"no chat {chat_id!r}")
            messages = convo["messages"]
        else:
            chat_id, messages = uuid.uuid4().hex[:12], []
        messages.append({"role": "user", "content": message})
        tools = tools_for(self.service, user)
        by_name = {t["name"]: t for t in tools}
        system = self.system_prompt(user)
        calls: List[Dict[str, Any]] = []
        usage: Dict[str, int] = {}
        turn = None
        for _ in range(self.max_rounds):
            turn = self.backend.turn(system, messages, tools)
            for k, v in turn.usage.items():
                usage[k] = usage.get(k, 0) + v
            if turn.content:
                messages.append({"role": "assistant", "content": turn.content})
            if turn.stop_reason == "pause_turn":
                continue
            if turn.stop_reason != "tool_use" or not turn.tool_calls:
                break
            results = []
            for call in turn.tool_calls:
                tool = by_name.get(call.name)
                ok, payload = True, None
                try:
                    if tool is None:
                        raise ApiError(400, f"no tool {call.name!r}")
                    payload = tool["run"](call.input)
                except ApiError as exc:
                    ok, payload = False, f"error {exc.status}: {exc.message}"
                except (KeyError, TypeError, ValueError) as exc:
                    ok, payload = False, f"invalid input: {exc}"
                text = payload if isinstance(payload, str) else json.dumps(payload, default=str)
                if len(text) > MAX_RESULT_CHARS:
                    text = text[:MAX_RESULT_CHARS] + " ...[truncated]"
                result: Dict[str, Any] = {"type": "tool_result", "tool_use_id": call.id, "content": text}
                if not ok:
                    result["is_error"] = True
                results.append(result)
                calls.append({"name": call.name, "input": call.input, "ok": ok})
                self.service.log_access(user, "chat.tool", call.name, 200 if ok else 400)
            messages.append({"role": "user", "content": results})  # all results in one message
        assert turn is not None
        reply = turn.text
        if turn.stop_reason == "refusal":
            reply = "The model declined to answer this request. Try rephrasing, or ask an administrator."
        elif turn.stop_reason == "max_tokens":
            reply = (reply + "\n\n[The answer was cut off at the length limit.]").strip()
        elif turn.stop_reason == "error":
            reply = f"The assistant is unavailable right now ({turn.error})."
        elif turn.stop_reason in ("tool_use", "pause_turn"):
            reply = (reply + "\n\n[Stopped after the maximum number of tool rounds.]").strip()
        store.save_chat(chat_id, user.name, messages)
        return ChatReply(chat_id, reply, calls, turn.stop_reason, usage, turn.model)


def load_backend(spec: Optional[Dict[str, Any]], search: tuple = ()) -> Optional[ChatBackend]:
    """Build the chat backend from the server config's ``chat`` section (None: chat is off)."""
    if not spec:
        return None
    if spec.get("backend"):
        from .adapters import import_target

        target = import_target(spec["backend"], search)
        backend = target() if callable(target) and not hasattr(target, "turn") else target
        if not hasattr(backend, "turn"):
            raise ValueError(f"chat backend {spec['backend']} has no turn(system, messages, tools)")
        return backend
    return AnthropicChatBackend(model=spec.get("model", "claude-opus-5-5"), effort=spec.get("effort", "medium"),
                                max_tokens=int(spec.get("max_tokens", 16000)))
