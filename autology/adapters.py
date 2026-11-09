"""Declarative adapters: connect any system, reviewer workflow or model without writing glue code.

Tools (``load_tools``) - a JSON config describing the registry::

    {
      "python_path": ["."],                                  # dirs (relative to the file) to import from
      "registries": ["my_tools:build_registry"],             # factories returning a ToolRegistry
      "tools": [
        {"name": "kyc", "capability": "kyc.verify", "type": "python", "target": "my_tools:kyc"},
        {"name": "clm", "capability": "contract.validate", "type": "http",
         "url": "https://clm.example.com/validate", "headers": {"Authorization": "Bearer ${CLM_TOKEN}"},
         "timeout": 10, "cost": 0.2, "when": "Contract.value > 0", "priority": 1}
      ]
    }

A ``"type": "table"`` tool is a declarative decision table - for simulated
environments, stubs and simple rules engines::

    {"name": "triage_rules", "capability": "clinical.triage", "type": "table", "cost": 0.1, "rows": [
       {"when": "Patient.age >= 65", "outcome": "urgent", "message": "age-based escalation"},
       {"outcome": "routine", "updates": {"Patient": {"risk": "low"}}}]}

Rows are checked in order against the call's inputs and (redacted) case view; the
first match answers. A row with ``"error"`` raises :class:`ToolError` (to simulate
outages). No matching row raises :class:`ToolError` too.

An HTTP tool receives ``{"action", "capability", "inputs", "context", "attempt"}``
as JSON and answers ``{"outcome"?, "updates"?, "message"?, "output"?}``. Network
errors, timeouts and non-2xx replies raise :class:`ToolError`, so the action's
failure policy (retry, fallback tool, escalate) applies. ``${VAR}`` in headers or
URLs is read from the environment - keep secrets out of config files.

Approvers (``load_approver``) - ``"auto"``, ``"deny"``, ``"console"``, a policy
``{"type": "policy", "decisions": {"sign_contract": "Contract.value < 2000000", "x": false}, "default": true}``
(a decision is a boolean or a condition on the case),
or ``{"type": "http", "url": ...}`` posting the review request and expecting
``{"approved": bool, "reviewer"?, "comment"?}``. HTTP failures **decline** (fail closed).

Reasoners (``load_reasoner``) - ``"planner"``, ``"claude"``, ``"routing"``, or
``"module:factory"`` returning any object with ``propose(ctx)``.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Union

from .agent import AutoApprover, ConsoleApprover, ReviewDecision, ReviewRequest
from .reasoners import ClaudeReasoner, PlanFollowingReasoner, RoutingReasoner
from .tools import ToolCall, ToolError, ToolRegistry, ToolResult

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class AdapterError(ValueError):
    pass


def _expand(text: str) -> str:
    def sub(m: re.Match) -> str:
        if m.group(1) not in os.environ:
            raise AdapterError(f"environment variable {m.group(1)} is not set")
        return os.environ[m.group(1)]

    return _ENV.sub(sub, text)


def import_target(target: str, search: tuple = ()) -> Any:
    """Import ``"package.module:attribute"``."""
    module_name, sep, attr = target.partition(":")
    if not sep or not module_name or not attr:
        raise AdapterError(f"target {target!r} must look like 'module:attribute'")
    for path in search:
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise AdapterError(f"cannot import {module_name!r}: {exc}") from None
    try:
        obj = module
        for part in attr.split("."):
            obj = getattr(obj, part)
        return obj
    except AttributeError:
        raise AdapterError(f"{module_name!r} has no attribute {attr!r}") from None


def _post_json(url: str, payload: Any, headers: Mapping[str, str], timeout: float) -> Any:
    body = json.dumps(payload, default=str).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL comes from operator config
        raw = resp.read().decode() or "{}"
    return json.loads(raw)


def http_tool(url: str, headers: Optional[Mapping[str, str]] = None, timeout: float = 10.0) -> Callable:
    """A tool handler that delegates to a JSON-over-HTTP service."""

    def handler(call: ToolCall) -> ToolResult:
        payload = {"action": call.action, "capability": call.capability, "inputs": call.inputs,
                   "context": call.context, "attempt": call.attempt}
        target = _expand(url)  # configuration errors (missing env vars) must surface, not look like outages
        resolved = {k: _expand(v) for k, v in (headers or {}).items()}
        try:
            data = _post_json(target, payload, resolved, timeout)
        except urllib.error.HTTPError as exc:
            raise ToolError(f"HTTP {exc.code} from {url}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ToolError(f"cannot reach {url}: {exc}") from None
        except ValueError:
            raise ToolError(f"{url} returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ToolError(f"{url} returned {type(data).__name__}, expected an object")
        return ToolResult(data.get("outcome"), data.get("updates") or {}, str(data.get("message", "")),
                          data.get("output"))

    handler.__doc__ = f"HTTP tool at {url}"
    return handler


def table_tool(rows):
    """A tool handler answering from a decision table (see module docstring)."""
    from .expressions import compile_expression
    from .governance import REDACTED

    compiled = [(compile_expression(r["when"]) if r.get("when") else None, r) for r in rows]

    def handler(call: ToolCall) -> ToolResult:
        def resolve(entity: str, attr: str):
            ref = f"{entity}.{attr}"
            value = call.inputs[ref] if ref in call.inputs else call.context.get(entity, {}).get(attr)
            return None if value == REDACTED else value

        for expr, row in compiled:
            if expr is None or expr.evaluate(resolve):
                if row.get("error"):
                    raise ToolError(str(row["error"]))
                return ToolResult(row.get("outcome"), row.get("updates") or {}, str(row.get("message", "")),
                                  row.get("output"))
        raise ToolError("no decision-table row matched")

    handler.__doc__ = f"decision table with {len(rows)} rows"
    return handler


def load_tools(config: Union[str, Path, Mapping[str, Any]], base_dir: Optional[Path] = None) -> ToolRegistry:
    """Build a :class:`ToolRegistry` from a JSON file or dict (see module docstring)."""
    if not isinstance(config, Mapping):
        path = Path(config).resolve()
        base_dir = path.parent
        config = json.loads(path.read_text(encoding="utf-8"))
    base = Path(base_dir or ".").resolve()
    search = tuple(str((base / p).resolve()) for p in config.get("python_path", ["."]))
    registry = ToolRegistry()
    for spec in config.get("registries", []):
        target, kwargs = (spec, {}) if isinstance(spec, str) else (spec["target"], spec.get("kwargs", {}))
        sub = import_target(target, search)(**kwargs)
        if not isinstance(sub, ToolRegistry):
            raise AdapterError(f"{target} did not return a ToolRegistry")
        for t in sub:
            registry.register(t.name, t.capability, t.handler, when=str(t.when) if t.when else None,
                              priority=t.priority, description=t.description, cost=t.cost)
    for spec in config.get("tools", []):
        kind = spec.get("type", "python")
        try:
            name, capability = spec["name"], spec["capability"]
        except KeyError as exc:
            raise AdapterError(f"tool spec {spec!r} is missing {exc.args[0]!r}") from None
        if kind == "python":
            handler = import_target(spec["target"], search)
        elif kind == "http":
            handler = http_tool(spec["url"], spec.get("headers"), float(spec.get("timeout", 10)))
        elif kind == "table":
            handler = table_tool(spec.get("rows") or [{}])
        else:
            raise AdapterError(f"tool {name!r}: unknown type {kind!r} (python | http | table)")
        registry.register(name, capability, handler, when=spec.get("when"), priority=int(spec.get("priority", 0)),
                          description=spec.get("description", ""), cost=float(spec.get("cost", 0)))
    return registry


class HttpApprover:
    """Send review requests to a workflow service (ticketing, chat ops...). Fails closed."""

    def __init__(self, url: str, headers: Optional[Mapping[str, str]] = None, timeout: float = 30.0):
        self.url, self.headers, self.timeout = url, dict(headers or {}), timeout

    def review(self, request: ReviewRequest) -> ReviewDecision:
        target = _expand(self.url)
        resolved = {k: _expand(v) for k, v in self.headers.items()}
        try:
            data = _post_json(target, request.__dict__, resolved, self.timeout)
            return ReviewDecision(bool(data.get("approved", False)), str(data.get("reviewer", self.url)),
                                  str(data.get("comment", "")))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as exc:
            return ReviewDecision(False, "http-approver", f"declined: review service unavailable ({exc})")


def _condition(source: str):
    """Approve when ``source`` (e.g. ``"Contract.value < 2000000"``) holds on the request's redacted view.

    Redacted or missing fields resolve to None, so conditions on data the reviewer cannot see fail closed.
    """
    from .expressions import compile_expression
    from .governance import REDACTED

    expr = compile_expression(source)

    def decide(request: ReviewRequest) -> bool:
        def resolve(entity: str, attr: str):
            value = request.view.get(entity, {}).get(attr)
            return None if value == REDACTED else value

        return expr.evaluate(resolve)

    return decide


def load_approver(spec: Union[str, Mapping[str, Any], None]):
    if spec in (None, "deny"):
        return AutoApprover(default=False)
    if spec == "auto":
        return AutoApprover(default=True)
    if spec == "console":
        return ConsoleApprover()
    if isinstance(spec, str):
        path = Path(spec)
        if path.suffix == ".json" and path.exists():
            return load_approver(json.loads(path.read_text(encoding="utf-8")))
        raise AdapterError(f"unknown approver {spec!r} (auto | deny | console | policy.json)")
    kind = spec.get("type", "policy")
    if kind == "policy":
        decisions = {action: (_condition(rule) if isinstance(rule, str) else bool(rule))
                     for action, rule in dict(spec.get("decisions", {})).items()}
        return AutoApprover(decisions, bool(spec.get("default", False)), spec.get("reviewer", "policy"))
    if kind == "http":
        return HttpApprover(spec["url"], spec.get("headers"), float(spec.get("timeout", 30)))
    raise AdapterError(f"unknown approver type {kind!r} (policy | http)")


def load_reasoner(spec: Optional[str], search: tuple = ()):
    if spec in (None, "planner"):
        return PlanFollowingReasoner()
    if spec == "claude":
        return ClaudeReasoner()
    if spec == "routing":
        return RoutingReasoner.with_claude()
    factory = import_target(spec, search)
    try:
        reasoner = factory() if isinstance(factory, type) or not hasattr(factory, "propose") else factory
    except TypeError as exc:
        raise AdapterError(f"{spec} could not be called without arguments: {exc}") from None
    if not hasattr(reasoner, "propose"):
        raise AdapterError(f"{spec} did not produce a reasoner (needs propose(ctx))")
    return reasoner
