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
    ("GET", "/api/ontology", "read", "The ontology the use case runs", ()),
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
    ("GET", "/api/settings/assistant", "admin", "Assistant settings", ()),
    ("POST", "/api/settings/assistant", "admin", "Change the assistant settings", ()),
    ("POST", "/api/settings/assistant/test", "admin", "Test the assistant's model connection", ()),
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
    ("GET", "/api/model/draft", "read", "The model draft (never active), its validation and discovery questions", ()),
    ("POST", "/api/model/draft", "admin", "Save a draft revision over the one read (expected_revision)", ()),
    ("GET", "/api/model/draft/history", "read", "Draft revisions", ()),
    ("POST", "/api/model/validate", "read", "Validate a model document with the engine's strict loader", ()),
    ("POST", "/api/architect/proposals", "admin", "Provisional additions for a business brief (blueprints; not AI)", ()),
]

# -- response envelope of API v1 (the same handlers serve /api and /api/v1) -----------------------------------
CODES = {400: "invalid_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
         405: "method_not_allowed", 409: "conflict", 411: "length_required", 413: "payload_too_large",
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
    "Me": _obj({"name": S, "permissions": {"type": "array", "items": S}}, ("name", "permissions")),
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
                   "active": _obj({"ref": S, "fingerprint": S}, ("ref", "fingerprint")),
                   "validation": REF("Validation"), "questions": {"type": "array", "items": REF("Question")},
                   "active_model_changed": B},
                  ("revision", "document", "active", "validation", "questions")),
    "ValidationResult": _obj({"validation": REF("Validation"),
                              "questions": {"type": "array", "items": REF("Question")}},
                             ("validation", "questions")),
    "ProposalItem": _obj({"id": S, "kind": {"type": "string", "enum": ["entity", "relationship", "action", "rule"]},
                          "name": NS, "value": {}, "rationale": S, "status": {"type": "string", "enum": ["provisional"]},
                          "provenance": _obj({"generator": S, "blueprint": S, "ai": B,
                                              "matched_terms": {"type": "array", "items": S}},
                                             ("generator", "ai"))},
                         ("id", "kind", "value", "rationale", "status", "provenance")),
    "Proposal": _obj({"generator": S, "ai": B, "blueprint": _obj({"id": S, "name": S}),
                      "matched_terms": {"type": "array", "items": S},
                      "items": {"type": "array", "items": REF("ProposalItem")}, "message": S},
                     ("generator", "ai", "items", "message")),
    "DraftSave": _obj({"document": ANY, "expected_revision": {"type": "integer", "minimum": 0},
                       "note": S}, ("document", "expected_revision")),
    "ValidateRequest": _obj({"document": {}}, ("document",)),
    "ProposalRequest": _obj({"brief": {"type": "string", "minLength": 1, "maxLength": 4000},
                             "document": ANY}, ("brief",)),
    "ObjectWrite": _obj({"type": S, "id": S, "attributes": ANY,
                         "expected_revision": {"type": "integer", "minimum": 0},
                         "links": {"type": "array", "items": _obj({"kind": S, "target": S}, ("kind", "target"))},
                         "justification": S}, ("type", "id", "attributes")),
}
RESPONSES = {("GET", "/api/health"): "Health", ("GET", "/api/me"): "Me", ("GET", "/api/objects"): "ObjectList",
             ("GET", "/api/objects/{id}"): "ObjectView", ("POST", "/api/objects"): "ObjectView",
             ("GET", "/api/ontology"): "OntologySummary", ("GET", "/api/model/draft"): "Draft",
             ("POST", "/api/model/draft"): "Draft", ("POST", "/api/model/validate"): "ValidationResult",
             ("POST", "/api/architect/proposals"): "Proposal"}
REQUESTS = {("POST", "/api/model/draft"): "DraftSave", ("POST", "/api/model/validate"): "ValidateRequest",
            ("POST", "/api/architect/proposals"): "ProposalRequest", ("POST", "/api/objects"): "ObjectWrite"}


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
    ("GET", "/platform/me", "member", "The caller's workspace and the use cases they may open", ()),
    ("GET", "/platform/templates", "workspace admin", "Approved templates", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases", "member", "Use cases of the caller's workspace", ()),
    ("POST", "/platform/workspaces/{ws}/use-cases", "workspace admin", "Create a use case from a template", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}", "granted member", "One use case with its stage history", ()),
    ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/checks", "granted member", "Checks of a target stage", ("to",)),
    ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/stage", "workspace admin", "Move one stage", ()),
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
                "use_cases": {"type": "array", "items": _obj({"id": S, "name": S, "ontology": S, "stage": STAGE,
                                                              "path": S, "permissions": {"type": "array", "items": S}},
                                                             ("id", "name", "stage", "path"))}},
               ("workspace", "member", "workspace_admin", "use_cases")),
    "Template": _obj({"id": S, "name": S, "description": S}, ("id", "name", "description"), extra=False),
    "TemplateList": _obj({"items": {"type": "array", "items": REF("Template")}}, ("items",)),
    "CheckResult": _obj({"from": STAGE, "to": STAGE, "forward": B, "checks": {"type": "array", "items": REF("Check")},
                         "allowed": B}, ("from", "to", "forward", "checks", "allowed")),
    "MoveResult": {"allOf": [REF("CheckResult"), _obj({"use_case": REF("UseCase")}, ("use_case",))]},
    "UseCaseCreate": _obj({"id": S, "name": S, "template": S}, ("id", "template")),
    "StageMove": _obj({"to": STAGE, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ("to", "reason")),
    "Health": _obj({"status": S}, ("status",)),
    "Release": _obj({"number": I, "id": S, "fingerprint": S, "ontology_ref": S, "proposed_by": S, "note": S, "at": S,
                     "status": {"type": "string", "enum": ["proposed", "approved", "active", "superseded"]},
                     "approved_by": NS, "approved_at": NS, "activated_at": NS, "snapshot": ANY},
                    ("number", "id", "fingerprint", "proposed_by", "note", "at", "status")),
    "ReleaseEvent": _obj({"seq": I, "release": I, "event": {"type": "string", "enum": [
        "proposed", "approved", "approval_revoked", "activated", "rolled_back"]}, "by": S, "by_kind": S, "reason": S,
        "fingerprint": S, "at": S}, ("seq", "release", "event", "by", "by_kind", "fingerprint", "at")),
    "ReleaseState": _obj({"items": {"type": "array", "items": REF("Release")},
                          "active": {"oneOf": [REF("Release"), {"type": "null"}]}, "running_fingerprint": S,
                          "drift": B, "integrity_problem": NS,
                          "history": {"type": "array", "items": REF("ReleaseEvent")},
                          "may_propose": B, "may_approve": B},
                         ("items", "running_fingerprint", "drift", "history")),
    "ActivationResult": {"allOf": [REF("Release"), _obj({
        "event": {"type": "string", "enum": ["activated", "rolled_back"]},
        "runs_on_other_configurations": {"type": "array", "items": S}}, ("event", "runs_on_other_configurations"))]},
    "ReleaseProposal": _obj({"note": {"type": "string", "minLength": 1, "maxLength": 500}}, ("note",)),
    "ReleaseDecision": _obj({"reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ("reason",)),
}
PLATFORM_RESPONSES = {("GET", "/platform/me"): "Me", ("GET", "/platform/templates"): "TemplateList",
                      ("GET", "/platform/health"): "Health",
                      ("GET", "/platform/workspaces/{ws}/use-cases"): "UseCaseList",
                      ("POST", "/platform/workspaces/{ws}/use-cases"): "UseCase",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}"): "UseCase",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/checks"): "CheckResult",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/stage"): "MoveResult",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "ReleaseState",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "Release",
                      ("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}"): "Release",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/approve"): "Release",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/revoke"): "Release",
                      ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/activate"): "ActivationResult"}
PLATFORM_REQUESTS = {("POST", "/platform/workspaces/{ws}/use-cases"): "UseCaseCreate",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/stage"): "StageMove",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "ReleaseProposal",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/approve"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/revoke"): "ReleaseDecision",
                     ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/activate"): "ReleaseDecision"}


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
                         ("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases"): "201"}),
    }
