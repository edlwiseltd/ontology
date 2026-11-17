"""The engine's API contract (API-1): one route table, published as OpenAPI 3.1 at ``GET /api/openapi.json``.

``ROUTES`` is the authoritative list of what the engine serves. ``tests/test_api_contract.py`` checks it against
the dispatcher in both directions (every route in the table is served; every path segment the dispatcher matches
belongs to a route in the table) and against ``docs/platform.md``. UIs (Studio, the Console, generated clients)
build against this contract, never against the engine's internals.

Each route names the permission it requires (``x-autology-permission``), as enforced by the engine. Request and
response bodies are JSON objects; their detailed schemas are not yet part of the contract (a later API-1 step), so
the contract fixes paths, methods, parameters, permissions and status codes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from . import __version__

API_VERSION = "1"

# (method, path, permission, summary, query parameters)
ROUTES: List[Tuple[str, str, str, str, Tuple[str, ...]]] = [
    ("GET", "/api/health", "none", "Liveness, stage and integrity summary", ()),
    ("GET", "/api/openapi.json", "none", "This contract", ()),
    ("GET", "/api/auth/config", "none", "What a sign-in page needs to offer company sign-in", ()),
    ("POST", "/api/auth/token", "none", "Exchange a company sign-in code for a token", ()),
    ("GET", "/api/me", "any", "The caller and their permissions", ()),
    ("GET", "/api/ontology", "read or configure", "The ontology the use case runs", ()),
    ("GET", "/api/objects", "read", "Records the caller may see", ("type", "limit", "offset", "justification")),
    ("POST", "/api/objects", "admin", "Create or update a record (revision-checked)", ()),
    ("GET", "/api/objects/{id}", "read", "One record", ("justification",)),
    ("GET", "/api/objects/{id}/lineage", "read", "Where a record's values came from", ()),
    ("GET", "/api/justifications", "audit", "Reasons people gave at checkpoints", ("limit",)),
    ("GET", "/api/audit-heads", "audit", "The head of every run's audit chain", ()),
    ("POST", "/api/questions/{id}", "read", "Answer a competency question", ()),
    ("GET", "/api/runs", "read", "Runs the caller may see", ("status", "limit", "offset")),
    ("POST", "/api/runs", "run", "Start a governed run", ()),
    ("GET", "/api/runs/{id}", "read", "One run", ()),
    ("GET", "/api/runs/{id}/audit", "audit", "A run's audit chain and whether it verifies", ()),
    ("GET", "/api/runs/{id}/trace", "audit", "A run as an OpenTelemetry trace", ()),
    ("GET", "/api/runs/{id}/outcomes", "read", "Recorded outcomes of a run", ()),
    ("POST", "/api/runs/{id}/outcomes", "review", "Record a decision's outcome", ()),
    ("POST", "/api/runs/{id}/resume", "run", "Resume a deferred or escalated run", ()),
    ("POST", "/api/runs/{id}/cancel", "run", "Cancel a run that is waiting (review, retry or resume)", ()),
    ("POST", "/api/runs/{id}/write-back", "reconcile", "Retry a run's write-back after a conflict", ()),
    ("GET", "/api/reviews", "review", "Human reviews", ("status",)),
    ("GET", "/api/reviews/{id}", "read", "One review", ()),
    ("POST", "/api/reviews/{id}/decision", "review", "Decide a human review", ()),
    ("GET", "/api/reconciliation", "reconcile, audit or admin", "External calls a person must settle", ()),
    ("POST", "/api/reconciliation/{key}", "reconcile", "Settle an external call", ()),
    ("POST", "/api/mcp", "read, run, review, audit, ingest, reconcile or admin", "One MCP JSON-RPC message", ()),
    ("GET", "/api/report", "read", "Readiness report", ()),
    ("GET", "/api/score", "read", "Readiness score", ()),
    ("GET", "/api/outcomes", "read", "Outcomes summary", ()),
    ("GET", "/api/pipelines", "ingest", "Data pipelines", ()),
    ("POST", "/api/pipelines/{name}/run", "ingest", "Run a data pipeline", ()),
    ("GET", "/api/ingest-batches/{id}", "ingest", "One load and its quarantined rows", ()),
    ("GET", "/api/metrics", "audit", "Prometheus metrics", ()),
    ("POST", "/api/reporting", "admin", "Refresh the reporting database", ()),
    ("GET", "/api/settings/assistant", "configure", "Assistant settings", ()),
    ("POST", "/api/settings/assistant", "configure", "Change the assistant settings", ()),
    ("POST", "/api/settings/assistant/test", "configure", "Test the assistant's model connection", ()),
    ("GET", "/api/automations", "read", "Automations", ()),
    ("POST", "/api/automations/{name}/run", "run", "Fire an automation by hand", ()),
    ("GET", "/api/notifications", "read", "Notifications", ("since", "limit")),
    ("POST", "/api/tick", "admin", "Run one scheduler pass", ()),
    ("GET", "/api/scenarios", "read", "What-if scenarios", ("status",)),
    ("POST", "/api/scenarios", "run", "Create a scenario", ()),
    ("GET", "/api/scenarios/{id}", "read", "One scenario", ()),
    ("POST", "/api/scenarios/{id}/edits", "run", "Add edits to a scenario (owner or admin)", ()),
    ("POST", "/api/scenarios/{id}/compare", "read", "Compare a scenario with the live data", ()),
    ("POST", "/api/scenarios/{id}/commit", "admin", "Apply a scenario to the live data", ()),
    ("POST", "/api/scenarios/{id}/discard", "run", "Discard a scenario (owner or admin)", ()),
    ("POST", "/api/chat", "read", "Talk to the governed assistant", ()),
    ("GET", "/api/chat/{id}", "read", "A conversation (owner)", ()),
    ("GET", "/api/proposals", "read", "Runs the assistant proposed", ()),
    ("POST", "/api/proposals/{id}/decision", "run", "Confirm or decline a proposal (owner)", ()),
    ("GET", "/api/agents", "read", "Agents and their state", ()),
    ("POST", "/api/agents/{name}/reinstate", "admin", "Reinstate a suspended agent", ()),
    ("GET", "/api/access-log", "audit", "The access log", ("principal", "limit")),
    ("GET", "/api/sdk/{language}", "read", "A typed client for this ontology", ()),
    ("GET", "/api/model/draft", "read or configure", "The model draft (never active), its validation and discovery questions", ()),
    ("POST", "/api/model/draft", "configure", "Save a draft revision over the one read (expected_revision)", ()),
    ("GET", "/api/model/draft/history", "read or configure", "Draft revisions", ()),
    ("POST", "/api/model/validate", "read or configure", "Validate a model document with the engine's strict loader", ()),
    ("POST", "/api/model/draft/simulate", "configure",
     "Dry run of a model document with stub tools: nothing stored, nothing called outside the engine", ()),
    ("GET", "/api/solution/draft", "read or configure",
     "The draft's executable configuration (agents, simulated tools, sample records), validated, with what runs", ()),
    ("POST", "/api/solution/draft", "configure", "Save the configuration part of the draft (or withdraw it)", ()),
    ("POST", "/api/solution/validate", "read or configure",
     "Validate a configuration against the draft's model and explain each agent's effective permissions", ()),
    ("POST", "/api/solution/suggest", "configure", "A starting configuration for the draft's model (nothing saved)", ()),
    ("GET", "/api/tools/catalog", "read or configure", "The approved tool catalogue: simulated tools, and what is unavailable", ()),
    ("POST", "/api/architect/proposals", "configure",
     "Provisional additions for a business brief: from approved blueprints (default), or through the AI gateway "
     "(generator model), stored as a revision", ()),
    ("GET", "/api/architect/proposals", "read or configure", "Stored proposals and the architect's provider", ()),
    ("GET", "/api/architect/proposals/{id}", "read or configure",
     "One proposal: a revision with its provenance, validation, history and review decisions", ("revision",)),
    ("POST", "/api/architect/proposals/{id}/decision", "configure",
     "Record which provisional items a person accepted or rejected (changes no model)", ()),
    ("GET", "/api/application", "read",
     "The application designed for what runs, as this caller may use it; 409 when another configuration runs", ()),
    ("POST", "/api/application/generate", "read or configure",
     "A draft application manifest generated from the released model and agents (deterministic; nothing saved)", ()),
    ("POST", "/api/application/validate", "read or configure",
     "Validate an application manifest against the model and configuration that run", ()),
    ("GET", "/api/application/draft", "read or configure", "The saved application design, its validation and history", ()),
    ("POST", "/api/application/draft", "configure",
     "Save an application design over the revision read (an invalid manifest is never stored)", ()),
]

# -- response envelope of API v1 (the same handlers serve /api and /api/v1) -----------------------------------
CODES = {400: "invalid_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
         405: "method_not_allowed", 409: "conflict", 411: "length_required", 413: "payload_too_large",
         429: "rate_limited",
         500: "internal_error", 502: "unavailable", 503: "unavailable"}
PAGINATED = {(m, p) for m, p, _perm, _s, q in ROUTES if "offset" in q}


def page_window(query: Dict[str, str]) -> Tuple[int, int]:
    """(limit, offset) of a list request; the engine's handlers and the v1 page metadata both use this, so the
    metadata always describes the window that was actually served. A non-integer raises ValueError (400)."""
    return max(1, min(int(query.get("limit", 100)), 1000)), max(0, int(query.get("offset", 0)))


def versioned_response(version: Optional[str], method: str, path: str, query: Dict[str, str], status: int,
                       content_type: str, data: bytes) -> Tuple[bytes, Dict[str, str]]:
    """Apply the v1 envelope to a response produced by the shared handlers. Unversioned paths keep their exact
    legacy shape and point to their v1 successor (compatibility policy: docs/api-versioning.md)."""
    if not version:
        return data, {"X-Autology-API-Version": "legacy",
                      "Link": f'</api/v1{path[len("/api"):]}>; rel="successor-version"'}
    headers = {"X-Autology-API-Version": version}
    if "json" not in content_type or not data:
        return data, headers
    try:
        body = json.loads(data)
    except ValueError:
        return data, headers
    if status >= 400 and isinstance(body, dict) and isinstance(body.get("error"), str):
        body = {"error": {"status": status, "code": CODES.get(status, "error"), "message": body["error"],
                          "details": {k: v for k, v in body.items() if k != "error"}}}
    elif status == 200 and isinstance(body, dict) and isinstance(body.get("items"), list) \
            and (method, path) in PAGINATED:
        limit, offset = page_window(query)  # it parsed when the list was served (status 200)
        n = len(body["items"])
        body = {**body, "page": {"limit": limit, "offset": offset, "returned": n,
                                 "next_offset": offset + n if n == limit else None}}
    return json.dumps(body, default=str).encode(), headers


# -- schemas of the bodies Studio and generated clients rely on (JSON Schema 2020-12, as in OpenAPI 3.1) ---------
def _obj(props: Dict[str, Any], required: Tuple[str, ...] = (), extra: bool = True) -> Dict[str, Any]:
    out: Dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": extra}
    if required:
        out["required"] = list(required)
    return out


S, I, B, N = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "number"}
NS = {"type": ["string", "null"]}
REF = lambda name: {"$ref": f"#/components/schemas/{name}"}  # noqa: E731
ANY = {"type": "object", "additionalProperties": True}  # a free-form JSON object
STAGE = {"type": "string", "enum": ["draft", "simulation", "pilot", "production"]}
SCHEMAS: Dict[str, Any] = {
    "Error": _obj({"error": _obj({"status": I, "code": S, "message": S, "details": ANY},
                                 ("status", "code", "message"))}, ("error",), extra=False),
    "Page": _obj({"limit": I, "offset": I, "returned": I, "next_offset": {"type": ["integer", "null"]}},
                 ("limit", "offset", "returned", "next_offset"), extra=False),
    "Health": _obj({"status": S, "ontology": S, "audit_keyed": B, "quarantined_records": I, "tampered_records": I,
                    "stage": STAGE, "runs_allowed": B, "tool_environments": {"type": "array", "items": S}},
                   ("status", "ontology")),
    "Me": _obj({"name": S, "permissions": {"type": "array", "items": S},
                "kind": {"type": "string", "enum": ["person", "service"]}, "token_expires_at": NS},
               ("name", "permissions")),
    "ObjectView": _obj({"id": S, "type": S, "attributes": ANY, "revision": I},
                       ("id", "type", "attributes", "revision")),
    "ObjectList": _obj({"items": {"type": "array", "items": REF("ObjectView")}, "page": REF("Page")}, ("items",)),
    "Entity": _obj({"states": {"type": "array", "items": S}, "multiple": B, "aliases": {"type": "array", "items": S},
                    "attributes": {"type": "object", "additionalProperties": S}},
                   ("states", "multiple", "attributes")),
    "Relationship": _obj({"source": S, "target": S, "kind": S, "cardinality": S},
                         ("source", "target", "kind", "cardinality"), extra=False),
    "OntologySummary": _obj({"ref": S, "fingerprint": S, "description": S,
                             "entities": {"type": "object", "additionalProperties": REF("Entity")},
                             "relationships": {"type": "array", "items": REF("Relationship")},
                             "actions": ANY,
                             "rules": {"type": "array", "items": _obj({"id": S, "kind": S, "description": S},
                                                                       ("id", "kind"))}},
                            ("ref", "fingerprint", "entities", "relationships", "actions", "rules")),
    "Problem": _obj({"path": S, "message": S, "node": S, "field": NS, "edge": I, "section": S, "name": S,
                     "index": I}, ("path", "message")),
    "Validation": _obj({"valid": B, "problems": {"type": "array", "items": REF("Problem")}, "note": S, "ref": S,
                        "fingerprint": S, "summary": {"type": "object", "additionalProperties": I}},
                       ("valid", "problems")),
    "Question": _obj({"id": S, "kind": S, "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                      "question": S, "why": S, "evidence": S, "node": S, "action": S, "rule": I},
                     ("id", "kind", "severity", "question", "why", "evidence")),
    "Draft": _obj({"revision": I, "document": ANY, "author": NS, "at": NS, "note": S,
                   # the architect proposal revision this model was saved from; null: not recorded (unknown)
                   "origin": {"oneOf": [{"type": "null"}, _obj({"proposal": S, "revision": I},
                                                               ("proposal", "revision"))]},
                   "active": _obj({"ref": S, "fingerprint": S}, ("ref", "fingerprint")),
                   "validation": REF("Validation"), "questions": {"type": "array", "items": REF("Question")},
                   "consistency": {"type": "array", "items": REF("ConsistencyFinding")},
                   "active_model_changed": B},
                  ("revision", "document", "active", "validation", "questions")),
    "ValidationResult": _obj({"validation": REF("Validation"),
                              "questions": {"type": "array", "items": REF("Question")},
                              "consistency": {"type": "array", "items": REF("ConsistencyFinding")}},
                             ("validation", "questions")),
    # a potential inconsistency of the workflow the model describes, for a person to decide: nothing is changed
    "ConsistencyFinding": _obj({"id": S, "kind": {"type": "string", "enum": [
        "goal_unreachable", "open_exception", "action_cannot_start", "obligation_cannot_be_met", "always_prohibited",
        "outside_effect_ungoverned", "state_never_reached"]},
        "severity": {"type": "string", "enum": ["high", "medium", "low"]}, "finding": S, "why": S,
        "a_person_could": {"type": "array", "items": S}, "action": S, "entity": S, "goal": S, "rule": S},
        ("id", "kind", "severity", "finding", "why", "a_person_could")),
    "ProposalItem": _obj({"id": S, "kind": {"type": "string",
                                           "enum": ["entity", "relationship", "action", "rule", "goal",
                                                    "case_template"]},
                          "name": NS, "value": {}, "rationale": S, "status": {"type": "string", "enum": ["provisional"]},
                          "sources": {"type": "array", "items": S}, "confidence": {"type": "number"},
                          "attention": {"type": "array", "items": S},
                          # supplied: something that was given is cited for it; inferred: the architect's reading
                          "basis": {"type": "string", "enum": ["supplied", "inferred"]},
                          # what it cites, canonically ("brief", "answer:<question id>", a given passage's id), and
                          # where it comes from in one word; "unknown": presented as supplied, nothing given cited
                          "evidence": {"type": "array", "items": _obj(
                              {"ref": S, "kind": {"type": "string", "enum": ["brief", "answer", "source"]}},
                              ("ref", "kind"))},
                          "origin": {"type": "string", "enum": ["brief", "answers", "sources", "several", "inference",
                                                                "unknown"]},
                          "validation": {"type": "string", "enum": ["passed"]},
                          "provenance": _obj({"generator": S, "blueprint": S, "ai": B, "provider": S, "model": S,
                                              "request_id": S, "matched_terms": {"type": "array", "items": S}},
                                             ("generator", "ai"))},
                         ("id", "kind", "value", "rationale", "status", "provenance")),
    "CatalogEntry": _obj({"id": S, "name": S, "environment": S, "available": B, "description": S,
                          "parameters": {"type": "array", "items": S}},
                         ("id", "name", "environment", "available", "description")),
    "ToolCatalog": _obj({"items": {"type": "array", "items": REF("CatalogEntry")}, "note": S}, ("items", "note")),
    "AgentPermission": _obj({
        "action": S, "status": {"type": "string", "enum": ["autonomous", "conditional", "review_required", "refused",
                                                           "not_assigned"]},
        "tool": NS, "simulated": B, "side_effect": S, "refused": {"type": "array", "items": S},
        "conditions": {"type": "array", "items": S},
        "reviews": {"type": "array", "items": _obj({"reviewer": NS, "when": NS, "rule": S}, ("reviewer", "when", "rule"))}},
        ("action", "status", "tool", "simulated", "side_effect", "refused", "conditions", "reviews")),
    "SolutionDraft": _obj({
        "revision": I, "author": NS, "at": NS, "note": S, "solution": {"type": ["object", "null"]},
        "state": {"type": "string", "enum": ["none", "invalid", "validated"]},
        "validation": _obj({"valid": B, "by": S, "problems": {"type": "array", "items": _obj(
            {"path": S, "message": S}, ("path", "message"))}}, ("valid", "problems", "by")),
        "permissions": {"type": "object", "additionalProperties": {"type": "array", "items": REF("AgentPermission")}},
        "simulated_tools": {"type": "array", "items": S},
        "active": _obj({"managed": {"type": "string", "enum": ["studio", "files", "none"]},
                        "agents": {"type": "array", "items": S}, "solution": {"type": ["object", "null"]},
                        "configuration": S, "editable": B, "note": S},
                       ("managed", "agents", "solution", "configuration", "editable", "note")),
        "changes": {"type": "array", "items": _obj(
            {"kind": S, "name": S, "change": {"type": "string", "enum": ["added", "removed", "changed"]},
             "fields": {"type": "array", "items": S}}, ("kind", "name", "change", "fields"))},
        "catalog": {"type": "array", "items": REF("CatalogEntry")}, "source": S, "saved": B},
        ("revision", "solution", "state", "validation", "permissions", "simulated_tools", "active", "changes",
         "catalog")),
    "SolutionSave": _obj({"solution": {"type": ["object", "null"]}, "expected_revision": {"type": "integer", "minimum": 0},
                          "note": S}, ("solution", "expected_revision")),
    "SolutionCheck": _obj({"solution": {"type": ["object", "null"]}, "document": ANY, "proposal": S}),
    # -- runs and reviews (typed since the architect sprint; before, these routes answered open objects) ---------
    "RunStep": _obj({"index": I, "action": S, "verdict": S, "outcome": NS, "tool": NS, "environment": NS,
                     "executed_by": NS, "reviewer": NS, "message": NS, "explanation": NS},
                    ("index", "action", "verdict", "outcome", "tool", "environment", "executed_by", "reviewer")),
    "Run": _obj({
        "run_id": S, "case_id": S, "goal": S,
        "status": {"type": "string", "enum": ["completed", "blocked", "escalated", "deferred", "paused", "suspended",
                                              "awaiting_review", "cancelled", "uncertain", "pending_confirmation"]},
        "agent": NS, "started_by": NS, "configuration": S, "simulated": B,
        "steps": {"type": "array", "items": REF("RunStep")},
        "escalation": {"oneOf": [{"type": "null"}, _obj({"reason": S, "to": S, "action": NS,
                                                         "details": {"type": "array", "items": S}},
                                                        ("reason", "to", "action", "details"))]},
        "costs": {"type": "object"}, "audit_verified": B, "state": {"type": "object"},
        "outcomes": {"type": "array", "items": {"type": "object"}},
        "write_back_conflicts": {"type": "array", "items": {"type": "object"}},
        "write_back": _obj({"state": S, "conflicts": I}, ("state", "conflicts")),
        "pending_review": NS,
        # for the person who started or resumed a run over records they may not see: a receipt, nothing else
        "hidden": B, "detail": S}, ("run_id", "case_id", "status")),
    "RunRow": _obj({"run_id": S, "case_id": S, "goal": S, "ontology": S, "agent": NS, "status": S, "created_at": S,
                    "updated_at": S, "started_by": NS}, ("run_id", "case_id", "goal", "status", "created_at")),
    "RunList": _obj({"items": {"type": "array", "items": REF("RunRow")}}, ("items",)),
    "AuditEntry": _obj({"seq": I, "timestamp": {"type": ["string", "number"]}, "event": S, "data": {"type": "object"},
                        "prev_hash": S, "hash": S}, ("seq", "event", "data", "hash")),
    "RunAudit": _obj({"run_id": S, "verified": B, "entries": {"type": "array", "items": REF("AuditEntry")}},
                     ("run_id", "verified", "entries")),
    "Review": _obj({
        "review_id": S, "run_id": S, "action": S, "reviewers": {"type": "array", "items": S},
        "status": {"type": "string", "enum": ["pending", "approved", "declined", "cancelled"]},
        "request": _obj({"case_id": S, "action": S, "description": NS, "reviewers": {"type": "array", "items": S},
                         "reasons": {"type": "array", "items": S}, "rule_ids": {"type": "array", "items": S},
                         "facts": {"type": "object"}, "view": {"type": "object"}, "explanation": NS,
                         "history": {"type": "array", "items": S}, "binding": {"type": "object"}}),
        "decision": {"oneOf": [{"type": "null"}, _obj({"approved": B, "reviewer": S, "comment": S, "cancelled": B},
                                                      ("approved", "reviewer"))]},
        "created_at": S, "decided_at": NS, "decided_by": NS},
        ("review_id", "run_id", "action", "reviewers", "status", "request", "created_at")),
    "ReviewList": _obj({"items": {"type": "array", "items": REF("Review")}}, ("items",)),
    "RunCancel": _obj({"reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ("reason",)),
    "RunStart": _obj({"case_template": S, "root": S, "agent": S, "goal": S, "case": {"type": "object"}, "case_id": S,
                      "write_back": B, "justification": S}),
    "ReviewDecision": _obj({"approved": B, "comment": S, "justification": S}, ("approved",)),
    "DraftSimulation": _obj({
        "simulated": B, "persisted": B, "notice": S, "requested_by": S,
        "model": _obj({"ref": S, "fingerprint": S}, ("ref", "fingerprint")), "goal": S,
        "agent": _obj({"roles": {"type": "array", "items": S}, "tools": S}, ("roles", "tools")), "case": ANY,
        "status": S,
        "steps": {"type": "array", "items": _obj(
            {"index": I, "action": S, "verdict": S, "tool": NS, "outcome": NS, "reviewer": NS, "explanation": S},
            ("index", "action", "verdict", "tool", "outcome"))},
        "pending_review": {"oneOf": [{"type": "null"}, _obj(
            {"action": S, "reviewers": {"type": "array", "items": S}, "reasons": {"type": "array", "items": S},
             "rules": {"type": "array", "items": S}, "facts": ANY}, ("action", "reviewers", "reasons", "rules"))]},
        "reviews": {"type": "array", "items": _obj({"action": S, "approved": B, "as": S, "note": S},
                                                   ("action", "approved", "as", "note"))},
        "escalation": {"oneOf": [{"type": "null"}, _obj({"reason": S, "action": NS,
                                                         "details": {"type": "array", "items": S}}, ("reason",))]},
        "refused": {"type": "array", "items": _obj({"action": S, "reasons": {"type": "array", "items": S}},
                                                   ("action", "reasons"))},
        "final_state": ANY,
        "audit": _obj({"note": S, "events": {"type": "array", "items": _obj({"seq": I, "event": S, "data": ANY},
                                                                             ("seq", "event", "data"))}},
                      ("note", "events"))},
        ("simulated", "persisted", "notice", "model", "goal", "agent", "case", "status", "steps", "pending_review",
         "reviews", "escalation", "refused", "final_state", "audit")),
    "DraftSimulationRequest": _obj({"document": ANY, "case": ANY, "goal": S, "roles": {"type": "array", "items": S},
                                    "approvals": {"type": "array", "items": _obj(
                                        {"action": S, "approved": B, "as": S}, ("action", "approved"))}}),
    "ProposalRevision": _obj({"revision": I, "at": S, "created_by": S, "answers": {"type": "array", "items": ANY},
                              "items": I, "rejected": I, "open_questions": I,
                              # who generated the revision: the generator, and for a model its provider and exact name
                              "generator": NS, "ai": B, "provider": NS, "model": NS,
                              "cost_usd": {"type": ["number", "null"]}, "feedback": S},
                             ("revision", "at", "created_by", "answers", "items", "rejected", "open_questions")),
    "ProposalDecision": _obj({"revision": I, "decided_by": S, "at": S, "accepted": {"type": "array", "items": S},
                              "rejected": {"type": "array", "items": S}, "note": S},
                             ("revision", "decided_by", "at", "accepted", "rejected", "note")),
    # the blueprint generator answers with the first four fields; the model generator stores a revision and
    # answers with all of them
    "Proposal": _obj({"generator": S, "ai": B, "blueprint": _obj({"id": S, "name": S}),
                      "matched_terms": {"type": "array", "items": S},
                      "items": {"type": "array", "items": REF("ProposalItem")}, "message": S,
                      "id": S, "revision": I, "latest_revision": I, "created_by": S, "at": S, "brief": S,
                      "provider": S, "model": S, "request_id": S,
                      "rejected": {"type": "array", "items": _obj({"kind": S, "name": S, "problem": S},
                                                                 ("kind", "name", "problem"))},
                      "answers": {"type": "array", "items": _obj({"id": S, "answer": S}, ("id", "answer"))},
                      "questions": {"type": "array", "items": _obj({"id": S, "question": S, "why": S},
                                                                  ("id", "question", "why"))},
                      "assumptions": {"type": "array", "items": _obj(
                          {"statement": S, "sources": {"type": "array", "items": S}, "confidence": {"type": "number"}},
                          ("statement", "sources", "confidence"))},
                      "unknowns": {"type": "array", "items": S},
                      "understanding": {"oneOf": [{"type": "null"}, _obj(
                          {"summary": S, "outcome": S, "actors": {"type": "array", "items": S},
                           "out_of_scope": {"type": "array", "items": S}}, ("summary", "outcome"))]},
                      "contradictions": {"type": "array", "items": _obj(
                          {"statement": S, "between": {"type": "array", "items": S}, "question": S},
                          ("statement", "between"))},
                      "feedback": S,
                      "suggestions": _obj({"roles": {"type": "array", "items": ANY},
                                           "agents": {"type": "array", "items": ANY},
                                           "integrations": {"type": "array", "items": ANY}, "note": S},
                                          ("roles", "agents", "integrations", "note")),
                      "validation": _obj({"valid": B, "items_validated": I, "by": S}, ("valid", "items_validated", "by")),
                      "usage": {"type": "object", "additionalProperties": {"type": "integer"}},
                      "cost_usd": {"type": "number"}, "unpriced_tokens": I,
                      "history": {"type": "array", "items": REF("ProposalRevision")},
                      "decisions": {"type": "array", "items": REF("ProposalDecision")},
                      "source_index": {"type": "object", "additionalProperties": _obj(
                          {"kind": {"type": "string", "enum": ["brief", "answer", "source"]}, "text": S,
                           "question": S}, ("kind", "text"))},
                      "drafts": {"type": "array", "items": _obj(
                          {"draft_revision": I, "proposal_revision": I, "saved_by": S, "at": S},
                          ("draft_revision", "proposal_revision", "saved_by", "at"))}},
                     ("generator", "ai", "items", "message")),
    "ProposalList": _obj({
        "items": {"type": "array", "items": _obj(
            {"id": S, "brief": S, "revisions": I, "generator": NS, "ai": B, "provider": NS, "decisions": I,
             "revision": I, "at": S, "created_by": S, "answers": {"type": "array", "items": ANY}, "items": I,
             "rejected": I, "open_questions": I, "model": NS, "cost_usd": {"type": ["number", "null"]},
             "feedback": S, "spent_usd": {"type": "number"}, "drafts": {"type": "array", "items": I}},
            ("id", "brief", "revisions", "generator", "ai", "provider", "decisions", "revision", "at"))},
        "architect": _obj({"configured": B, "generators": {"type": "array", "items": S}, "provider": S,
                           "language_model": B, "verified_against": S, "model": S,
                           "data_classes": {"type": "array", "items": S}, "wanted": NS, "bounded": B,
                           "wanted_model": NS, "policy_terms": NS,
                           # "synthetic": the operator declared that this use case sends only invented data
                           "content": {"type": "string", "enum": ["synthetic", "model_design"]},
                           # sandbox: a test double answers; authorised: a real provider, approved and covered by
                           # the owner's authorisation; not_authorised: one is named but may not be reached
                           "state": {"type": "string", "enum": ["none", "sandbox", "authorised", "not_authorised"]},
                           "reason": S}, ("configured", "generators", "state"))},
        ("items", "architect")),
    "ProposalDecisionRequest": _obj({"revision": I, "accepted": {"type": "array", "items": S},
                                     "rejected": {"type": "array", "items": S}, "note": S}),
    # the Application Builder: a manifest is described by autology.appspec.SCHEMA (closed and versioned); these
    # envelopes carry it
    "ApplicationCheck": _obj({"valid": {"type": "boolean"}, "problems": {"type": "array", "items": _obj({"path": S, "message": S})},
                              "by": S, "manifest_version": I, "digest": NS}, ("valid", "problems")),
    "ApplicationRunning": _obj({"model": S, "model_fingerprint": S, "configuration": S, "engine_api": S,
                                "workspace": S, "use_case": S}, ("model", "model_fingerprint", "configuration")),
    "ApplicationGenerated": _obj({"manifest": ANY, "validation": REF("ApplicationCheck"), "saved": {"type": "boolean"},
                                  "generator": ANY}, ("manifest", "validation", "saved", "generator")),
    "ApplicationValidation": _obj({"validation": REF("ApplicationCheck"), "running": REF("ApplicationRunning")},
                                  ("validation", "running")),
    "ApplicationDraft": _obj({"revision": I, "manifest": {"type": ["object", "null"]},
                              "validation": {"anyOf": [REF("ApplicationCheck"), {"type": "null"}]},
                              "history": {"type": "array", "items": ANY}, "running": REF("ApplicationRunning"),
                              "author": NS, "at": NS, "note": NS, "saved": {"type": "boolean"},
                              "governance": REF("ApplicationGovernance")},
                             ("revision", "manifest", "validation", "history", "running")),
    "Application": _obj({"manifest": ANY, "revision": I, "digest": S, "running": REF("ApplicationRunning"), "status": S,
                         "stage": NS, "runs_refused": NS, "production": {"type": "boolean"}, "you": ANY,
                         "governance": REF("ApplicationGovernance"),
                         # the active release the application runs on (null on an engine no platform hosts)
                         "release": {"anyOf": [{"type": "null"}, _obj({"number": I, "fingerprint": S, "runs": {"type": "boolean"}},
                                                                    ("number", "fingerprint", "runs"), extra=False)]}},
                        ("manifest", "revision", "digest", "running", "status", "production", "you", "governance", "release")),
    # where a design stands: six states, each said to be supported or not by the engine, and one sentence
    "ApplicationGovernance": _obj({**{state: _obj({"supported": {"type": "boolean"}, "value": {"type": "boolean"}, "detail": S},
                                              ("supported", "value", "detail"), extra=False)
                                      for state in ("design_draft", "validated_design", "configuration_bound",
                                                    "approved_release_artifact", "simulation_ready", "production_authorized")},
                                   "summary": S},
                                  ("design_draft", "validated_design", "configuration_bound", "approved_release_artifact",
                                   "simulation_ready", "production_authorized", "summary"), extra=False),
    "ApplicationGenerateRequest": _obj({"id": S}),
    "ApplicationValidateRequest": _obj({"manifest": ANY}, ("manifest",)),
    "ApplicationSave": _obj({"manifest": ANY, "expected_revision": {"type": "integer", "minimum": 0}, "note": S},
                            ("manifest", "expected_revision")),
    "DraftSave": _obj({"document": ANY, "expected_revision": {"type": "integer", "minimum": 0},
                       "note": S,
                       # the stored architect proposal revision this model was saved from, checked by the engine
                       "origin": _obj({"proposal": S, "revision": I}, ("proposal", "revision"))},
                      ("document", "expected_revision")),
    "ValidateRequest": _obj({"document": {}}, ("document",)),
    "ProposalRequest": _obj({"brief": {"type": "string", "minLength": 1, "maxLength": 4000},
                             "document": ANY, "generator": {"type": "string", "enum": ["blueprint", "model"]},
                             "revises": S,
                             # what to change in the proposal being revised: data for the architect, like the brief
                             "feedback": {"type": "string", "maxLength": 2000},
                             "answers": {"type": "array", "items": _obj(
                                 {"id": S, "answer": {"type": ["string", "number"]}}, ("id", "answer"))}}),
    "ObjectWrite": _obj({"type": S, "id": S, "attributes": ANY,
                         "expected_revision": {"type": "integer", "minimum": 0},
                         "links": {"type": "array", "items": _obj({"kind": S, "target": S}, ("kind", "target"))},
                         "justification": S}, ("type", "id", "attributes")),
}
RESPONSES = {("GET", "/api/health"): "Health", ("GET", "/api/me"): "Me", ("GET", "/api/objects"): "ObjectList",
             ("GET", "/api/objects/{id}"): "ObjectView", ("POST", "/api/objects"): "ObjectView",
             ("GET", "/api/ontology"): "OntologySummary", ("GET", "/api/model/draft"): "Draft",
             ("POST", "/api/model/draft"): "Draft", ("POST", "/api/model/validate"): "ValidationResult",
             ("POST", "/api/architect/proposals"): "Proposal",
             ("GET", "/api/architect/proposals"): "ProposalList",
             ("GET", "/api/architect/proposals/{id}"): "Proposal",
             ("POST", "/api/architect/proposals/{id}/decision"): "Proposal",
             ("POST", "/api/model/draft/simulate"): "DraftSimulation",
             ("GET", "/api/solution/draft"): "SolutionDraft", ("POST", "/api/solution/draft"): "SolutionDraft",
             ("POST", "/api/solution/validate"): "SolutionDraft", ("POST", "/api/solution/suggest"): "SolutionDraft",
             ("GET", "/api/tools/catalog"): "ToolCatalog",
             ("GET", "/api/runs"): "RunList", ("POST", "/api/runs"): "Run", ("GET", "/api/runs/{id}"): "Run",
             ("GET", "/api/runs/{id}/audit"): "RunAudit", ("POST", "/api/runs/{id}/cancel"): "Run",
             ("GET", "/api/reviews"): "ReviewList", ("GET", "/api/reviews/{id}"): "Review",
             ("POST", "/api/reviews/{id}/decision"): "Run",
             ("GET", "/api/application"): "Application", ("POST", "/api/application/generate"): "ApplicationGenerated",
             ("POST", "/api/application/validate"): "ApplicationValidation",
             ("GET", "/api/application/draft"): "ApplicationDraft", ("POST", "/api/application/draft"): "ApplicationDraft"}
REQUESTS = {("POST", "/api/model/draft"): "DraftSave", ("POST", "/api/model/validate"): "ValidateRequest",
            ("POST", "/api/architect/proposals"): "ProposalRequest", ("POST", "/api/objects"): "ObjectWrite",
            ("POST", "/api/architect/proposals/{id}/decision"): "ProposalDecisionRequest",
            ("POST", "/api/model/draft/simulate"): "DraftSimulationRequest",
            ("POST", "/api/solution/draft"): "SolutionSave", ("POST", "/api/solution/validate"): "SolutionCheck",
            ("POST", "/api/solution/suggest"): "SolutionCheck",
            ("POST", "/api/runs"): "RunStart", ("POST", "/api/runs/{id}/cancel"): "RunCancel",
            ("POST", "/api/reviews/{id}/decision"): "ReviewDecision",
            ("POST", "/api/application/generate"): "ApplicationGenerateRequest",
            ("POST", "/api/application/validate"): "ApplicationValidateRequest",
            ("POST", "/api/application/draft"): "ApplicationSave"}


def _operation_id(method: str, path: str) -> str:
    words = [w for w in re.split(r"[/{}\-.]+", re.sub(r"^/(api|platform)(/v1)?/", "", path)) if w]
    return method.lower() + "".join(w[:1].upper() + w[1:] for w in words)


def _paths(routes, prefix_from: str, prefix_to: str, responses, requests, statuses=None) -> Dict[str, Any]:
    paths: Dict[str, Dict[str, Any]] = {}
    for method, path, permission, summary, query in routes:
        params: List[Dict[str, Any]] = [{"name": p, "in": "path", "required": True, "schema": {"type": "string"}}
                                        for p in re.findall(r"\{([a-z]+)\}", path)]
        params += [{"name": q, "in": "query", "required": False, "schema": {"type": "string"}} for q in query]
        public = permission == "none"
        ok = (statuses or {}).get((method, path), "200")
        schema = REF(responses[(method, path)]) if (method, path) in responses else ANY
        out: Dict[str, Any] = {ok: {"description": "OK", "content": {"application/json": {"schema": schema}}}}
        for code, text in (("400", "Invalid request"), ("401", "Missing or invalid token"),
                           ("403", "Permission or checkpoint refused"), ("404", "Not found or not visible"),
                           ("409", "Conflict: state, stage or revision")):
            if public and code in ("401", "403"):
                continue
            out[code] = {"description": text, "content": {"application/json": {"schema": REF("Error")}}}
        out["429"] = {"description": "Too many requests: retry after the Retry-After header (seconds)",
                      "headers": {"Retry-After": {"schema": {"type": "integer"}}},
                      "content": {"application/json": {"schema": REF("Error")}}}
        if not public:
            out["503"] = {"description": "The use case is being switched to another configuration, or is "
                                         "unavailable: retry after the Retry-After header (seconds)",
                          "headers": {"Retry-After": {"schema": {"type": "integer"}}},
                          "content": {"application/json": {"schema": REF("Error")}}}
        op: Dict[str, Any] = {"operationId": _operation_id(method, path), "summary": summary,
                              "x-autology-permission": permission, "responses": out}
        if params:
            op["parameters"] = params
        if public:
            op["security"] = []
        if method == "POST":
            body = REF(requests[(method, path)]) if (method, path) in requests else ANY
            op["requestBody"] = {"required": (method, path) in requests,
                                 "content": {"application/json": {"schema": body}}}
        paths.setdefault(prefix_to + path[len(prefix_from):], {})[method.lower()] = op
    return paths


def spec() -> Dict[str, Any]:
    """The OpenAPI 3.1 document for the engine API, version 1 (``/api/v1``)."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Autology engine API", "version": API_VERSION,
                 "description": "The governed engine of one use case. Behind the platform router every path is "
                                "prefixed with /w/{workspace}/u/{use case}. Unversioned /api paths are the same "
                                "handlers with the legacy envelope (docs/api-versioning.md). Engine version "
                                + __version__ + "."},
        "servers": [{"url": "/"}],
        "security": [{"bearer": []}],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}, "schemas": SCHEMAS},
        "paths": _paths(ROUTES, "/api", "/api/v1", RESPONSES, REQUESTS),
    }


# -- the platform router's own routes (workspaces, use cases, stages) ------------------------------------------
PLATFORM_ROUTES: List[Tuple[str, str, str, str, Tuple[str, ...]]] = [
    ("GET", "/platform/health", "none", "Liveness of the platform", ()),
    ("GET", "/platform/openapi.json", "none", "This contract", ()),
    ("GET", "/platform/me", "member", "The caller's workspace and the use cases they may open; their tenant and "
     "every workspace they belong to (choose one with ?workspace=)", ("workspace",)),
    ("GET", "/platform/tenants/{tenant}", "member of the tenant",
     "The caller's tenant: its workspaces (their own, or all for a tenant administrator) (IAM-1)", ()),
    ("GET", "/platform/templates", "workspace admin", "Approved templates", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases", "member", "Use cases of the caller's workspace", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases", "workspace admin", "Create a use case from a template", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}", "granted member", "One use case with its stage history", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/checks", "granted member", "Checks of a target stage", ("to",)),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/readiness", "granted member",
     "Readiness report of what runs, of the saved draft or of a release: mandatory gates and evidence-based "
     "scorecard for a target stage", ("target", "of")),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/stage", "workspace admin", "Move one stage", ()),
    ("GET", "/platform/workspaces/{ws}/ai", "workspace admin or approver",
     "The workspace's AI provider policy, the owner's authorisation, spending and each use case's provider state", ()),
    ("POST", "/platform/workspaces/{ws}/ai/policy", "workspace admin (person)",
     "Propose an AI provider policy (never a key: a reference to it); another person approves", ()),
    ("POST", "/platform/workspaces/{ws}/ai/policy/{id}/approve", "approver (person, not the proposer)",
     "Approve a proposed AI provider policy", ()),
    ("POST", "/platform/workspaces/{ws}/ai/policy/{id}/withdraw", "workspace admin (person)",
     "Withdraw a proposed AI provider policy", ()),
    ("POST", "/platform/workspaces/{ws}/ai/disable", "workspace admin (person)",
     "Disable the AI provider policy in force (one person may always take access away)", ()),
    ("POST", "/platform/workspaces/{ws}/recovery-drill", "workspace admin (person)",
     "Rehearse a recovery (backup, verify, restore into a scratch folder, load) and record the evidence", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/sample-data", "granted member",
     "The synthetic sample records of the active release and which are loaded", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/sample-data", "workspace admin (person)",
     "Load the active release's synthetic sample records (explicit, recorded; never automatic)", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases", "granted member or release approver",
     "Releases, the active one, and whether the running configuration drifted (REL-1a)", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases", "workspace admin (person)",
     "Propose a release of the configuration the engine runs now", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}", "granted member or release approver",
     "One release (with its snapshot for administrators and release approvers)", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/approve", "release approver (person, not the "
     "proposer)", "Approve a release, bound to its fingerprint (D11)", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/revoke", "the approver or a workspace admin",
     "Revoke an approval before activation", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/activate", "workspace admin (person)",
     "Activate an approved release that is exactly what runs (a rollback when it is older)", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/publish-draft", "release authority (person, not the "
     "author of the revision)",
     "Make a saved, valid draft revision this use case's ontology, then reload; needs a release to run (STU-6)", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/restore", "workspace admin (person)",
     "Put an approved release's ontology back and reload; activate the release afterwards to roll back", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/reload", "workspace admin (person)",
     "Reload the engine from its files without a restart; not an activation (ADM-2)", ()),
    ("GET", "/platform/workspaces/{ws}/members", "workspace admin or approver",
     "Members, their grants, pending grant proposals and the administration history (ADM-1)", ()),
    ("POST", "/platform/workspaces/{ws}/members", "workspace admin (person)",
     "Add a member; the token is returned once", ()),
    ("POST", "/platform/workspaces/{ws}/members/{name}/remove", "workspace admin (person)", "Remove a member", ()),
    ("POST", "/platform/workspaces/{ws}/members/{name}/token", "workspace admin (person)",
     "Replace a member's token: returned once (200), or, for a member who holds business data, a request that "
     "another person with authority fulfils (202)", ()),
    ("POST", "/platform/workspaces/{ws}/members/{name}/revoke", "workspace admin (person)",
     "Revoke a member's grant on one use case, at once", ()),
    ("GET", "/platform/workspaces/{ws}/access-review", "workspace admin or approver",
     "Every business-data grant, its origin and whether a person still has to review it (sprint B)", ()),
    ("POST", "/platform/workspaces/{ws}/members/{name}/confirm-grant",
     "approver (person, not the member concerned)", "Record that an existing grant was reviewed and kept", ()),
    ("POST", "/platform/workspaces/{ws}/token-requests/{id}/approve", "approver (person, not the requester)",
     "Issue the requested token for a member who holds business data; returned once, to the approver only", ()),
    ("POST", "/platform/workspaces/{ws}/token-requests/{id}/withdraw", "workspace admin (person)",
     "Withdraw a pending token request", ()),
    ("POST", "/platform/workspaces/{ws}/members/{name}/revoke-token", "workspace admin (person)",
     "Revoke a member's token at once; the member and its grants stay (GAP-030)", ()),
    ("POST", "/platform/workspaces/{ws}/my-token", "member (person, workspace-level)",
     "Replace your own token before it expires; the new one is returned once (GAP-030)", ()),
    ("POST", "/platform/workspaces/{ws}/grants", "workspace admin (person)",
     "Propose a grant; it takes effect once another person with authority approves it", ()),
    ("POST", "/platform/workspaces/{ws}/grants/{id}/approve", "approver (person, not the proposer, not the grantee)",
     "Approve a grant proposal (D11)", ()),
    ("POST", "/platform/workspaces/{ws}/grants/{id}/withdraw", "workspace admin (person)",
     "Withdraw a grant proposal", ()),
]
STAGE_EVENT = _obj({"seq": I, "from_stage": STAGE, "to_stage": STAGE, "by": S, "reason": S, "fingerprint": S,
                    "at": S, "checks": {"type": "array", "items": REF("Check")}},
                   ("seq", "from_stage", "to_stage", "by", "reason", "at"))
PLATFORM_SCHEMAS: Dict[str, Any] = {
    "Error": SCHEMAS["Error"],
    "Check": _obj({"id": S, "passed": B, "detail": S}, ("id", "passed", "detail"), extra=False),
    "StageEvent": STAGE_EVENT,
    "UseCase": _obj({"id": S, "name": S, "origin": {"type": "string", "enum": ["configuration", "template"]},
                     "template": NS, "ontology": S, "fingerprint": S, "path": S,
                     "permissions": {"type": "array", "items": S}, "stage": STAGE, "effective_stage": STAGE,
                     "stale": B, "integrity_problem": NS, "stages": {"type": "array", "items": STAGE},
                     "history": {"type": "array", "items": REF("StageEvent")}, "configuration": S,
                     "release": _obj({"active": {"oneOf": [REF("Release"), {"type": "null"}]}, "drift": B,
                                      "integrity_problem": NS}, ("active", "drift"))},
                    ("id", "name", "origin", "ontology", "fingerprint", "path", "permissions", "stage",
                     "effective_stage", "stale", "stages")),
    "UseCaseList": _obj({"items": {"type": "array", "items": REF("UseCase")}}, ("items",)),
    "Me": _obj({"workspace": _obj({"id": S, "name": S}, ("id", "name")), "member": S, "workspace_admin": B,
                "release_approver": B,
                "kind": {"type": "string", "enum": ["person", "service"]}, "token_expires_at": NS,
                "use_cases": {"type": "array", "items": _obj({"id": S, "name": S, "ontology": S, "stage": STAGE,
                                                              "path": S, "permissions": {"type": "array", "items": S}},
                                                             ("id", "name", "stage", "path"))},
                "tenant": _obj({"id": S, "name": S}, ("id", "name")), "tenant_admin": B,
                "workspaces": {"type": "array", "items": _obj({"id": S, "name": S, "workspace_admin": B},
                                                              ("id", "name", "workspace_admin"))}},
               ("workspace", "member", "workspace_admin", "use_cases")),
    "TenantView": _obj({"id": S, "name": S, "dedicated": B, "tenant_admin": B,
                        "workspaces": {"type": "array", "items": _obj(
                            {"id": S, "name": S, "member": B, "workspace_admin": B},
                            ("id", "name", "member", "workspace_admin"))},
                        "members": {"type": "array", "items": _obj(
                            {"name": S, "kind": S, "tenant_admin": B, "workspaces": {"type": "array", "items": S}},
                            ("name", "kind", "tenant_admin", "workspaces"))}},
                       ("id", "name", "dedicated", "tenant_admin", "workspaces")),
    "Template": _obj({"id": S, "name": S, "description": S}, ("id", "name", "description"), extra=False),
    "TemplateList": _obj({"items": {"type": "array", "items": REF("Template")}}, ("items",)),
    "CheckResult": _obj({"from": STAGE, "to": STAGE, "forward": B, "checks": {"type": "array", "items": REF("Check")},
                         "allowed": B}, ("from", "to", "forward", "checks", "allowed")),
    "MoveResult": {"allOf": [REF("CheckResult"), _obj({"use_case": REF("UseCase")}, ("use_case",))]},
    "ReadinessCondition": _obj({"id": S, "dimension": S, "title": S, "applicable": B, "measured": B,
                                "passed": {"type": ["boolean", "null"]}, "held": {"type": ["integer", "null"]},
                                "total": I, "detail": S, "evidence": {"type": "array", "items": S},
                                "missing_evidence": NS, "mandatory_for": {"type": "array", "items": STAGE},
                                "blocking": B, "action": S},
                               ("id", "dimension", "title", "applicable", "measured", "passed", "held", "total",
                                "detail", "evidence", "missing_evidence", "mandatory_for", "blocking", "action")),
    "ReadinessDimension": _obj({"id": S, "title": S, "score": {"type": ["number", "null"]}, "weight": {"type": "number"},
                                "calculation": S, "conditions": {"type": "array", "items": REF("ReadinessCondition")},
                                "evidence": {"type": "array", "items": S},
                                "missing_evidence": {"type": "array", "items": S},
                                "blocking": {"type": "array", "items": S}, "actions": {"type": "array", "items": S}},
                               ("id", "title", "score", "weight", "calculation", "conditions", "evidence",
                                "missing_evidence", "blocking", "actions")),
    "Readiness": _obj({
        "target": STAGE, "generated_at": S, "stage": STAGE, "effective_stage": STAGE,
        "configuration": _obj({"ontology": S, "fingerprint": S}, ("ontology", "fingerprint")),
        "gates": _obj({"passed": B, "evaluated": I, "blockers": {"type": "array", "items": _obj(
            {"id": S, "dimension": S, "title": S, "detail": S, "reason": S, "action": S},
            ("id", "dimension", "title", "detail", "reason", "action"))}}, ("passed", "evaluated", "blockers")),
        "score": _obj({"overall": {"type": ["number", "null"]},
                       "weights": {"type": "object", "additionalProperties": {"type": "number"}},
                       "weights_status": S, "calculation": S, "note": S},
                      ("overall", "weights", "weights_status", "calculation", "note")),
        "dimensions": {"type": "array", "items": REF("ReadinessDimension")},
        "promotion": _obj({"allowed": B, "reason": S}, ("allowed", "reason")),
        "production": _obj({"authorised": B, "reason": S}, ("authorised", "reason")),
        # which configuration was assessed, and (for one that does not run) what differs from what runs
        "subject": _obj({"kind": {"type": "string", "enum": ["active", "draft", "release"]}, "label": S,
                         "revision": {"type": ["integer", "null"]}, "release": {"type": ["integer", "null"]},
                         "configuration": S, "model": S, "evaluated": S, "matches_release": B},
                        ("kind", "label", "revision", "release", "configuration", "model", "evaluated")),
        "compared_with": {"oneOf": [{"type": "null"}, _obj({
            "kind": S, "configuration": S, "same_configuration": B, "score": {"type": ["number", "null"]},
            "differences": {"type": "array", "items": _obj(
                {"id": S, "dimension": S, "title": S, "active": S, "subject": S, "detail": S, "blocking": B},
                ("id", "dimension", "title", "active", "subject", "detail", "blocking"))},
            "dimensions": {"type": "array", "items": _obj(
                {"id": S, "title": S, "active": {"type": ["number", "null"]}, "subject": {"type": ["number", "null"]}},
                ("id", "title", "active", "subject"))}},
            ("kind", "configuration", "same_configuration", "score", "differences", "dimensions"))]}},
        ("target", "generated_at", "stage", "effective_stage", "configuration", "gates", "score", "dimensions",
         "promotion", "production", "subject", "compared_with")),
    "AiPolicy": _obj({
        "provider": S, "model": S, "data_classes": {"type": "array", "items": S},
        "purposes": {"type": "array", "items": S},
        "limits": _obj({"max_input_tokens": I, "max_output_tokens": I, "concurrency": I,
                        "timeout_seconds": {"type": "number"}, "max_attempts": I},
                       ("max_input_tokens", "max_output_tokens", "concurrency", "timeout_seconds", "max_attempts")),
        "budget": _obj({"currency": S, "per_request": {"type": "number"}, "per_period": {"type": "number"},
                        "period": {"type": "string", "enum": ["day", "month"]}},
                       ("currency", "per_request", "per_period", "period")),
        # where the key lives, never the key
        "credential": {"oneOf": [{"type": "null"}, _obj({"ref": S, "note": S}, ("ref",))]},
        "retention": _obj({"prompts": S, "usage_days": I}, ("prompts", "usage_days")),
        "evaluation": _obj({"status": S, "reference": S}, ("status",)), "expires": NS, "priced": B,
        # the fingerprint of what the policy lets leave, and to which model: a use case pins it
        "terms": S},
        ("provider", "model", "data_classes", "purposes", "limits", "budget", "retention", "evaluation")),
    "AiView": _obj({
        "state": {"type": "string", "enum": ["none", "sandbox", "authorised", "not_authorised", "unavailable"]},
        "reason": S, "transmits_externally": B,
        "policy": {"oneOf": [{"type": "null"}, REF("AiPolicy")]},
        "approved_by": NS, "approved_at": NS, "proposed_by": NS,
        "owner_authorisation": _obj({"present": B, "decision": NS, "expires": NS, "note": S}, ("present",)),
        "pending": {"type": "array", "items": _obj({"id": S, "policy": REF("AiPolicy"), "proposed_by": S,
                                                    "proposed_at": S, "reason": S}, ("id", "policy", "proposed_by"))},
        "usage": {"oneOf": [{"type": "null"}, {"type": "object"}]}, "remaining_usd": {"type": ["number", "null"]},
        # the spending ledger every ceiling is counted in: where it stands and this workspace's periods
        "ledger": _obj({"available": B, "problem": S, "id": NS, "entries": {"type": ["integer", "null"]},
                        "outside_deployment": B, "bound_to_authorisation": B,
                        "history": {"type": "array", "items": _obj({
                            "period": S, "entries": I, "spent_usd": {"type": "number"},
                            "reserved_usd": {"type": "number"}, "carried_forward_usd": {"type": "number"}},
                            ("period", "entries", "spent_usd", "reserved_usd"))}},
                       ("available", "outside_deployment", "bound_to_authorisation", "history")),
        "adapters_installed": {"type": "array", "items": S},
        "use_cases": {"type": "array", "items": {"type": "object"}}, "proposed": S},
        ("state", "reason", "transmits_externally", "policy", "owner_authorisation", "pending", "use_cases")),
    "RecoveryDrill": _obj({"recorded": B, "at": S, "use_cases": {"type": "object", "additionalProperties": _obj(
        {"configuration": S, "reproduces_what_runs": B}, ("configuration", "reproduces_what_runs"))},
        "counts": {"type": "object"}, "files": I, "bytes": I, "steps": {"type": "array", "items": S},
        "seconds": {"type": "number"}}, ("recorded", "at", "use_cases", "counts", "steps")),
    "SampleData": _obj({"available": I, "loaded": {"type": "array", "items": S},
                        "already_present": {"type": "array", "items": S}, "records_marked_as_samples": I, "note": S,
                        "release": {"type": ["integer", "null"]}, "loadable": B, "refusal": NS, "may_load": B,
                        "just_loaded": {"type": "array", "items": S}, "skipped": {"type": "array", "items": S}},
                       ("available", "loaded", "already_present", "release", "loadable", "refusal", "may_load")),
    "UseCaseCreate": _obj({"id": S, "name": S, "template": S}, ("id", "template")),
    "StageMove": _obj({"to": STAGE, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ("to", "reason")),
    "Health": _obj({"status": S}, ("status",)),
    "Release": _obj({"number": I, "id": S, "fingerprint": S, "ontology_ref": S, "proposed_by": S, "note": S, "at": S,
                     "status": {"type": "string", "enum": ["proposed", "approved", "active", "superseded"]},
                     "approved_by": NS, "approved_at": NS, "activated_at": NS, "snapshot": ANY,
                     # one release read by number: what it contains, part by part, and whether it is coherent
                     "components": REF("ReleaseComponents"),
                     # the draft this configuration was published from and the architect proposal behind it;
                     # null: nothing was recorded (a configuration that was not published from a draft)
                     "design": {"oneOf": [{"type": "null"}, _obj({
                         "draft_revision": {"type": ["integer", "null"]}, "published_by": S, "published_at": S,
                         "proposal": {"oneOf": [{"type": "null"}, _obj({"proposal": S, "revision": I},
                                                                       ("proposal", "revision"))]}},
                         ("draft_revision", "proposal"))]},
                     # for a release that names a real AI provider: whether the workspace's policy serves it now
                     "ai_standing": _obj({"served": B, "reason": S}, ("served", "reason")),
                     "verification": _obj({"fingerprint_matches": B, "coherent": B, "by": S,
                                           "problems": {"type": "array", "items": S}},
                                          ("fingerprint_matches", "coherent", "problems"))},
                    ("number", "id", "fingerprint", "proposed_by", "note", "at", "status")),
    "ReleaseComponents": _obj({
        "model": _obj({"ref": NS, "fingerprint": S, "entities": I}, ("fingerprint", "entities")),
        "rules": _obj({"count": I, "fingerprint": S}, ("count", "fingerprint")),
        "actions": _obj({"count": I, "fingerprint": S}, ("count", "fingerprint")),
        "workflows": _obj({"case_templates": {"type": "array", "items": S}, "goals": {"type": "array", "items": S},
                           "automations": I, "fingerprint": S}, ("case_templates", "goals", "fingerprint")),
        "agents": _obj({"names": {"type": "array", "items": S}, "fingerprint": S,
                        "managed": {"type": "string", "enum": ["studio", "files", "none"]}},
                       ("names", "fingerprint", "managed")),
        "tools": _obj({"count": I, "simulated": I, "other": I, "all_simulated": B, "fingerprint": S},
                      ("count", "simulated", "other", "all_simulated", "fingerprint")),
        "governance": _obj({"settings": {"type": "array", "items": S}, "fingerprint": S}, ("settings", "fingerprint")),
        # the model this configuration may ask and the policy terms it was configured under (null: no AI setting)
        "ai": {"oneOf": [{"type": "null"}, _obj({"provider": NS, "model": NS, "policy_terms": NS, "content": NS,
                                                "fingerprint": S}, ("provider", "fingerprint"))]}},
        ("model", "rules", "actions", "workflows", "agents", "tools", "governance", "ai")),
    "ReleaseEvent": _obj({"seq": I, "release": I, "event": {"type": "string", "enum": [
        "proposed", "approved", "approval_revoked", "activated", "rolled_back"]}, "by": S, "by_kind": S, "reason": S,
        "fingerprint": S, "at": S}, ("seq", "release", "event", "by", "by_kind", "fingerprint", "at")),
    "ReleaseState": _obj({"items": {"type": "array", "items": REF("Release")},
                          "active": {"oneOf": [REF("Release"), {"type": "null"}]}, "running_fingerprint": S,
                          "drift": B, "integrity_problem": NS,
                          "history": {"type": "array", "items": REF("ReleaseEvent")},
                          "may_propose": B, "may_approve": B,
                          # for people who may publish: the saved draft revision and who saved it (never its content)
                          "draft": {"oneOf": [{"type": "null"}, _obj({"revision": I, "author": NS}, ("revision",))]}},
                         ("items", "running_fingerprint", "drift", "history")),
    "ActivationResult": {"allOf": [REF("Release"), _obj({
        "event": {"type": "string", "enum": ["activated", "rolled_back"]},
        "reloaded": B, "configuration": S,
        "stage": _obj({"stage": STAGE, "revalidated": B, "was": S, "next": NS, "problem": S,
                       "checks": {"type": "array", "items": ANY}}, ("stage", "revalidated")),
        "runs_on_other_configurations": {"type": "array", "items": S},
        "runs_on_other_configurations_count": I}, ("event", "runs_on_other_configurations"))]},
    "ReleaseProposal": _obj({"note": {"type": "string", "minLength": 1, "maxLength": 500}}, ("note",)),
    "Grant": _obj({"permissions": {"type": "array", "items": S}, "roles": {"type": "array", "items": S},
                   "reviewer_roles": {"type": "array", "items": S}, "run_as": ANY}, ("permissions",)),
    "WorkspaceMember": _obj({"name": S, "kind": {"type": "string", "enum": ["person", "service"]},
                             "workspace_admin": B, "approver": B,
                             "scope": {"type": "string", "enum": ["workspace", "tenant"]},
                             "token": {"type": "string", "enum": ["active", "expired", "revoked", "none"]},
                             "token_expires_at": NS, "token_issued_by": S, "tenant_admin": B,
                             "effective": {"type": "object", "additionalProperties": _obj(
                                 {"permissions": {"type": "array", "items": S},
                                  "data_access": {"type": "string", "enum": ["none", "scoped", "unrestricted"]}},
                                 ("permissions", "data_access"))},
                             "source": {"type": "string", "enum": ["configuration", "api"]},
                             "use_cases": {"type": "object", "additionalProperties": REF("Grant")}},
                            ("name", "kind", "workspace_admin", "source", "use_cases")),
    "AdminEvent": _obj({"seq": I, "event": S, "by": S, "reason": S, "data": ANY, "at": S},
                       ("seq", "event", "by", "reason", "data", "at")),
    "GrantProposal": _obj({"id": S, "member": S, "use_case": S, "grant": REF("Grant"), "proposed_by": S,
                           "status": S, "proposed_at": S, "reason": S, "unrestricted": B,
                           "data_access": {"type": "string", "enum": ["none", "scoped", "unrestricted"]}},
                          ("id", "member", "use_case", "grant")),
    "TokenRequest": _obj({"id": S, "name": S, "requested_by": S, "requested_at": S, "reason": S, "status": S,
                          "note": S}, ("id", "name")),
    "TokenIssuedOrRequested": {"oneOf": [REF("IssuedToken"), _obj({"status": {"type": "string", "enum": ["pending"]},
                                                                   "id": S, "name": S, "note": S},
                                                                  ("status", "id", "name"))]},
    "AccessReviewItem": _obj({"member": S, "kind": S, "administrator": B, "use_case": S,
                              "permissions": {"type": "array", "items": S}, "roles": {"type": "array", "items": S},
                              "reviewer_roles": {"type": "array", "items": S},
                              "data_access": {"type": "string", "enum": ["scoped", "unrestricted"]},
                              "origin": {"type": "string", "enum": ["configuration", "migration", "grant"]},
                              "granted_by": S, "approved_by": NS, "since": NS,
                              "review": {"oneOf": [_obj({"by": S, "at": S, "reason": S}, ("by", "at", "reason")),
                                                   {"type": "null"}]},
                              "needs_review": B, "narrower_would_do": B,
                              "usage": _obj({"operational": I, "configuration": I, "data": I,
                                             "last_request_at": NS}, ("operational", "configuration", "data"))},
                             ("member", "use_case", "permissions", "data_access", "origin", "needs_review")),
    "AccessReview": _obj({"workspace": S, "generated_at": S,
                          "items": {"type": "array", "items": REF("AccessReviewItem")},
                          "summary": _obj({"grants": I, "unrestricted": I, "administrators_with_data_access": I,
                                           "needs_review": I, "unrestricted_without_data_use": I},
                                          ("grants", "unrestricted", "needs_review")),
                          "unrestricted_means": {"type": "array", "items": S}, "how_to_resolve": S},
                         ("workspace", "items", "summary")),
    "GrantConfirmation": _obj({"use_case": S, "unrestricted": B,
                               "reason": {"type": "string", "minLength": 1, "maxLength": 500}},
                              ("use_case", "reason")),
    "GrantDecision": _obj({"reason": {"type": "string", "minLength": 1, "maxLength": 500}, "unrestricted": B},
                          ("reason",)),
    "Members": _obj({"members": {"type": "array", "items": REF("WorkspaceMember")},
                     "pending_grants": {"type": "array", "items": REF("GrantProposal")},
                     "history": {"type": "array", "items": REF("AdminEvent")}, "integrity_problem": NS,
                     "token_policy": _obj({"person_days": {"type": "number"}, "service_days": {"type": "number"}}),
                     "pending_token_requests": {"type": "array", "items": REF("TokenRequest")},
                     "use_cases": {"type": "array", "items": _obj({"id": S, "name": S}, ("id", "name"))},
                     "permissions": {"type": "array", "items": S},
                     "you": _obj({"member": S, "may_administer": B, "may_approve": B},
                                 ("member", "may_administer", "may_approve"))},
                    ("members", "pending_grants", "history")),
    "IssuedToken": _obj({"name": S, "kind": S, "token": S, "note": S, "token_expires_at": NS}, ("name", "token")),
    "OptionalReason": _obj({"reason": {"type": "string", "maxLength": 500}}),
    "MemberCreate": _obj({"name": S, "kind": {"type": "string", "enum": ["person", "service"]},
                          "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ("name", "reason")),
    "GrantCreate": _obj({"member": S, "use_case": S, "permissions": {"type": "array", "items": S},
                         "roles": {"type": "array", "items": S}, "reviewer_roles": {"type": "array", "items": S},
                         "run_as": ANY, "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                         "unrestricted": B},
                        ("member", "use_case", "permissions", "reason")),
    "PublishDraft": _obj({"revision": {"type": "integer", "minimum": 1},
                          "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ("revision", "reason")),
    "Published": {"allOf": [REF("UseCase"), _obj({"published_revision": I,
                                                  "published_agents": {"type": "array", "items": S}},
                                                 ("published_revision",))]},
    "Restored": {"allOf": [REF("UseCase"), _obj({"matches_release": B}, ("matches_release",))]},
    "Revocation": _obj({"use_case": S, "reason": {"type": "string", "minLength": 1, "maxLength": 500}},
                       ("use_case", "reason")),
    "ReleaseDecision": _obj({"reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ("reason",)),
}
PLATFORM_RESPONSES = {("GET", "/platform/me"): "Me", ("GET", "/platform/tenants/{tenant}"): "TenantView", ("GET", "/platform/templates"): "TemplateList",
                      ("GET", "/platform/health"): "Health",
                      ("GET", "/platform/workspaces/{ws}/use-cases"): "UseCaseList",
                      ("POST", "/platform/workspaces/{ws}/use-cases"): "UseCase",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}"): "UseCase",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/checks"): "CheckResult",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/readiness"): "Readiness",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/stage"): "MoveResult",
                      ("POST", "/platform/workspaces/{ws}/recovery-drill"): "RecoveryDrill",
                      ("GET", "/platform/workspaces/{ws}/ai"): "AiView",
                      ("POST", "/platform/workspaces/{ws}/ai/policy"): "AiView",
                      ("POST", "/platform/workspaces/{ws}/ai/policy/{id}/approve"): "AiView",
                      ("POST", "/platform/workspaces/{ws}/ai/policy/{id}/withdraw"): "AiView",
                      ("POST", "/platform/workspaces/{ws}/ai/disable"): "AiView",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/sample-data"): "SampleData",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/sample-data"): "SampleData",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "ReleaseState",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "Release",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}"): "Release",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/approve"): "Release",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/revoke"): "Release",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/activate"): "ActivationResult",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/reload"): "UseCase",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/publish-draft"): "Published",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/restore"): "Restored",
                      ("GET", "/platform/workspaces/{ws}/members"): "Members",
                      ("POST", "/platform/workspaces/{ws}/members"): "IssuedToken",
                      ("POST", "/platform/workspaces/{ws}/members/{name}/remove"): "Members",
                      ("POST", "/platform/workspaces/{ws}/members/{name}/token"): "TokenIssuedOrRequested",
                      ("GET", "/platform/workspaces/{ws}/access-review"): "AccessReview",
                      ("POST", "/platform/workspaces/{ws}/members/{name}/confirm-grant"): "AccessReview",
                      ("POST", "/platform/workspaces/{ws}/token-requests/{id}/approve"): "IssuedToken",
                      ("POST", "/platform/workspaces/{ws}/token-requests/{id}/withdraw"): "Members",
                      ("POST", "/platform/workspaces/{ws}/members/{name}/revoke"): "Members",
                      ("POST", "/platform/workspaces/{ws}/members/{name}/revoke-token"): "Members",
                      ("POST", "/platform/workspaces/{ws}/my-token"): "IssuedToken",
                      ("POST", "/platform/workspaces/{ws}/grants"): "GrantProposal",
                      ("POST", "/platform/workspaces/{ws}/grants/{id}/approve"): "Members",
                      ("POST", "/platform/workspaces/{ws}/grants/{id}/withdraw"): "Members"}
PLATFORM_REQUESTS = {("POST", "/platform/workspaces/{ws}/use-cases"): "UseCaseCreate",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/stage"): "StageMove",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "ReleaseProposal",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/approve"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/revoke"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/activate"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/reload"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/publish-draft"): "PublishDraft",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/restore"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/members"): "MemberCreate",
                     ("POST", "/platform/workspaces/{ws}/members/{name}/remove"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/members/{name}/token"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/members/{name}/revoke"): "Revocation",
                     ("POST", "/platform/workspaces/{ws}/members/{name}/revoke-token"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/my-token"): "OptionalReason",
                     ("POST", "/platform/workspaces/{ws}/grants"): "GrantCreate",
                     ("POST", "/platform/workspaces/{ws}/grants/{id}/approve"): "GrantDecision",
                     ("POST", "/platform/workspaces/{ws}/members/{name}/confirm-grant"): "GrantConfirmation",
                     ("POST", "/platform/workspaces/{ws}/token-requests/{id}/approve"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/token-requests/{id}/withdraw"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/grants/{id}/withdraw"): "ReleaseDecision"}


def platform_spec() -> Dict[str, Any]:
    """The OpenAPI 3.1 document for the platform router's own routes, version 1 (``/platform/v1``)."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Autology platform API", "version": API_VERSION,
                 "description": "Workspaces, use cases and lifecycle stages. Each use case's engine API is served "
                                "behind /w/{workspace}/u/{use case} (see the engine contract)."},
        "servers": [{"url": "/"}],
        "security": [{"bearer": []}],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
                       "schemas": PLATFORM_SCHEMAS},
        "paths": _paths(PLATFORM_ROUTES, "/platform", "/platform/v1", PLATFORM_RESPONSES, PLATFORM_REQUESTS,
                        {("POST", "/platform/workspaces/{ws}/use-cases"): "201",
                         ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "201",
                         ("POST", "/platform/workspaces/{ws}/members"): "201",
                         ("POST", "/platform/workspaces/{ws}/grants"): "201"}),
    }
