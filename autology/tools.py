"""Tool registry: the concrete systems agents can act through.

Ontology actions name a *capability* (``kyc.verify``, ``billing.setup``);
tools *provide* capabilities. A tool may declare a ``when`` condition so the
agent picks it only in a matching context - e.g. an enhanced KYC provider for
financial-services customers - and a ``priority`` to break ties. Workflows
never hard-code which API to call; the agent selects at run time.

Selection order: tools named in the action's ontology allow-list only (if one
is declared) -> context-specific tools before generic ones -> higher
``priority`` -> lower ``cost`` (per call, in your currency). Remaining
candidates are the fallbacks used by the action's failure policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .expressions import Expression, compile_expression
from .state import WorldState


class ToolError(RuntimeError):
    """Raised by a tool handler for a (possibly transient) failure."""


@dataclass
class ToolCall:
    action: str
    capability: str
    inputs: Dict[str, Any]  # only the fields the action declares in ``reads``
    context: Mapping[str, Mapping[str, Any]]  # redacted view of the case
    attempt: int = 1


@dataclass
class ToolResult:
    outcome: Optional[str] = None  # None -> the action's expected outcome
    updates: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # entity -> attr -> value (must be in ``writes``)
    message: str = ""
    output: Any = None


Handler = Callable[[ToolCall], ToolResult]


@dataclass
class Tool:
    name: str
    capability: str
    handler: Handler
    when: Optional[Expression] = None
    priority: int = 0
    description: str = ""
    cost: float = 0.0

    def matches(self, state: WorldState) -> bool:
        return self.when is None or self.when.evaluate(state.get)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: List[Tool] = []

    def register(self, name: str, capability: str, handler: Handler, *, when: Optional[str] = None,
                 priority: int = 0, description: str = "", cost: float = 0.0) -> Tool:
        tool = Tool(name, capability, handler, compile_expression(when) if when else None, priority,
                    description or (handler.__doc__ or "").strip(), float(cost))
        self._tools.append(tool)
        return tool

    def tool(self, capability: str, *, name: Optional[str] = None, when: Optional[str] = None,
             priority: int = 0, description: str = "", cost: float = 0.0) -> Callable[[Handler], Handler]:
        """Decorator form of :meth:`register`."""

        def decorate(fn: Handler) -> Handler:
            self.register(name or fn.__name__, capability, fn, when=when, priority=priority,
                          description=description, cost=cost)
            return fn

        return decorate

    def candidates(self, capability: str, state: WorldState, allowed: Sequence[str] = ()) -> List[Tool]:
        found = [t for t in self._tools if t.capability == capability and t.matches(state)
                 and (not allowed or t.name in allowed)]
        # context-specific tools beat generic ones; then explicit priority; then cheapest
        return sorted(found, key=lambda t: (t.when is None, -t.priority, t.cost))

    def select(self, capability: str, state: WorldState, allowed: Sequence[str] = ()) -> Tool:
        found = self.candidates(capability, state, allowed)
        if not found:
            extra = f" among allowed tools {list(allowed)}" if allowed else ""
            raise LookupError(f"no tool provides capability {capability!r} in this context{extra}")
        return found[0]

    def capabilities(self) -> List[str]:
        return sorted({t.capability for t in self._tools})

    def __iter__(self):
        return iter(self._tools)
