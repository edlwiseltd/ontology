"""OpenTelemetry trace export: every run's audit log as OTLP spans, for Jaeger, Tempo, Honeycomb, Datadog...

Mapping (one trace per run; the trace id is derived from the run id, so a resumed run stays one trace):

* root span ``autology.run <goal>``: from the first to the last audit entry; status ERROR when the run
  ended blocked, escalated or suspended;
* one child span per step ``<action>`` (from the decision to its outcome), with the verdict, the rules
  that decided it, who proposed and executed it, the model and its cost, and the outcome;
* tool calls as spans under their step; tool errors, deferrals and governance denials as error
  spans or span events; human reviews as span events carrying the reviewer and decision.

No case data or facts are exported: spans carry identifiers, rule ids and outcomes only.

    python -m autology trace --db autology.db --out traces.json
    python -m autology trace runs.jsonl --endpoint http://localhost:4318/v1/traces

Server config ``"tracing": {"endpoint": "...", "headers": {"x-api-key-env": "OTLP_KEY"}}`` exports each run
when it reaches a final status. Standard library only (OTLP/HTTP with JSON encoding).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import __version__ as VERSION

FINAL = {"completed", "blocked", "escalated", "suspended"}
FAILED = {"blocked", "escalated", "suspended"}


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ns(ts: str) -> int:
    dt = datetime.fromisoformat(ts)
    delta = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)) - EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000  # exact, no floats


def _id(seed: str, size: int) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:size]


def _attrs(values: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for key, value in values.items():
        if value is None or value == [] or value == "":
            continue
        if isinstance(value, bool):
            v: Dict[str, Any] = {"boolValue": value}
        elif isinstance(value, int):
            v = {"intValue": str(value)}
        elif isinstance(value, float):
            v = {"doubleValue": value}
        elif isinstance(value, (list, tuple)):
            v = {"arrayValue": {"values": [{"stringValue": str(x)} for x in value]}}
        else:
            v = {"stringValue": str(value)}
        out.append({"key": key, "value": v})
    return out


class _Span:
    def __init__(self, trace: str, span_id: str, parent: Optional[str], name: str, start: int, attrs: Dict[str, Any]):
        self.trace, self.id, self.parent, self.name = trace, span_id, parent, name
        self.start = self.end = start
        self.attrs = dict(attrs)
        self.events: List[Dict[str, Any]] = []
        self.error: Optional[str] = None

    def as_otlp(self) -> Dict[str, Any]:
        span = {"traceId": self.trace, "spanId": self.id, "name": self.name, "kind": 1,
                "startTimeUnixNano": str(self.start), "endTimeUnixNano": str(max(self.end, self.start)),
                "attributes": _attrs(self.attrs), "events": self.events,
                "status": {"code": 2, "message": self.error} if self.error else {"code": 1}}
        if self.parent:
            span["parentSpanId"] = self.parent
        return span


def run_spans(result: Any, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The spans of one run (a RunResult with its audit log)."""
    entries = list(result.audit)
    if not entries:
        return []
    rid = run_id or getattr(result, "run_id", None) or f"{result.case_id}:{entries[0].timestamp}"
    trace = _id(f"autology-run:{rid}", 32)
    counter = iter(range(1, 10 ** 9))
    new_id = lambda: _id(f"{rid}:{next(counter)}", 16)  # noqa: E731 - deterministic span ids
    root = _Span(trace, new_id(), None, f"autology.run {result.goal}", _ns(entries[0].timestamp),
                 {"autology.run_id": rid, "autology.case_id": result.case_id, "autology.goal": result.goal})
    spans = [root]
    steps: Dict[str, _Span] = {}  # action -> open step span
    tools: Dict[str, _Span] = {}  # action -> open tool span
    for e in entries:
        t, d = _ns(e.timestamp), e.data
        root.end = max(root.end, t)
        action = d.get("action")
        if e.event in ("run.start", "run.resume"):
            root.events.append({"timeUnixNano": str(t), "name": e.event,
                                "attributes": _attrs({"autology.agent": d.get("agent"),
                                                      "autology.ontology": d.get("ontology")})})
        elif e.event == "decision":
            span = _Span(trace, new_id(), root.id, action, t, {
                "autology.step": d.get("step"), "autology.action": action, "autology.verdict": d.get("verdict"),
                "autology.proposed_by": d.get("proposed_by"), "autology.executed_by": d.get("executed_by"),
                "autology.rules": d.get("rules") or [], "autology.rules_satisfied": d.get("satisfied_rules") or [],
                "gen_ai.request.model": d.get("model"), "autology.llm_cost_usd": d.get("llm_cost_usd") or None})
            steps[action] = span
            spans.append(span)
        elif e.event == "tool.call":
            parent = steps.get(action, root)
            span = _Span(trace, new_id(), parent.id, f"tool {d.get('tool')}", t, {
                "autology.tool": d.get("tool"), "autology.attempt": d.get("attempt"), "autology.tool_cost": d.get("cost")})
            tools[action] = span
            spans.append(span)
        elif e.event == "tool.error":
            span = tools.pop(action, None)
            if span:
                span.end, span.error = t, str(d.get("error", "tool error"))
        elif e.event == "step":
            if action in tools:
                tools.pop(action).end = t
            span = steps.pop(action, None)
            if span:
                span.end = t
                span.attrs.update({"autology.outcome": d.get("outcome"), "autology.tool": d.get("tool")})
        elif e.event in ("review.requested", "review"):
            target = steps.get(action, root)
            target.events.append({"timeUnixNano": str(t), "name": e.event, "attributes": _attrs({
                "autology.reviewer": d.get("reviewer"), "autology.approved": d.get("approved"),
                "autology.reviewer_roles": d.get("roles") or d.get("reviewers") or [],
                "autology.rules": d.get("rules") or []})})
            if e.event == "review" and d.get("approved") is False:
                target.end, target.error = t, "declined in human review"
        elif e.event == "governance.deny":
            span = _Span(trace, new_id(), root.id, f"denied {action}", t, {
                "autology.action": action, "autology.proposed_by": d.get("proposed_by"),
                "autology.rules": d.get("rules") or []})
            span.error = "; ".join(d.get("reasons") or ["denied by governance"])
            spans.append(span)
        elif e.event == "deferred":
            target = steps.pop(action, root)
            target.end = t
            target.events.append({"timeUnixNano": str(t), "name": "deferred", "attributes": _attrs(
                {"autology.error": d.get("error"), "autology.failures": d.get("failures")})})
        elif e.event == "run.end":
            status = d.get("status")
            root.attrs["autology.status"] = status
            esc = d.get("escalation") or {}
            if status in FAILED:
                root.error = esc.get("reason") or status
            for span in list(steps.values()) + list(tools.values()):  # whatever was open ends with this segment
                span.end = t
            steps.clear()  # a resumed run decides again: its new step spans start fresh
            tools.clear()
    for span in spans:
        span.end = max(span.end, span.start)
    return [s.as_otlp() for s in spans]


def to_otlp(runs: Iterable[Tuple[Optional[str], Any]], service_name: str = "autology",
            ontology_ref: str = "") -> Dict[str, Any]:
    """OTLP/JSON ``ExportTraceServiceRequest`` for ``(run_id, RunResult)`` pairs."""
    spans = [s for run_id, result in runs for s in run_spans(result, run_id)]
    resource = _attrs({"service.name": service_name, "autology.ontology": ontology_ref})
    return {"resourceSpans": [{"resource": {"attributes": resource},
                               "scopeSpans": [{"scope": {"name": "autology", "version": VERSION}, "spans": spans}]}]}


def export(payload: Dict[str, Any], endpoint: str, headers: Optional[Dict[str, str]] = None,
           timeout: float = 10.0) -> int:
    """POST an OTLP/JSON payload to a collector (``.../v1/traces``). Returns the HTTP status."""
    import urllib.request

    req = urllib.request.Request(endpoint, json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


def resolve_headers(spec: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Header values ending in ``-env`` keys name environment variables: ``{"x-api-key-env": "OTLP_KEY"}``."""
    out = {}
    for key, value in (spec or {}).items():
        if key.endswith("-env"):
            out[key[:-4]] = os.environ.get(value, "")
        else:
            out[key] = value
    return out
