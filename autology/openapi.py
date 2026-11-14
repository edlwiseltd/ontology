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

import re
from typing import Any, Dict, List, Tuple

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

ERROR = {"type": "object", "required": ["error"], "properties": {"error": {"type": "string"}},
         "additionalProperties": True}


def _operation_id(method: str, path: str) -> str:
    words = [w for w in re.split(r"[/{}\-.]+", path.replace("/api/", "")) if w]
    return method.lower() + "".join(w[:1].upper() + w[1:] for w in words)


def spec() -> Dict[str, Any]:
    """The OpenAPI 3.1 document for the engine API."""
    paths: Dict[str, Dict[str, Any]] = {}
    for method, path, permission, summary, query in ROUTES:
        params: List[Dict[str, Any]] = [{"name": p, "in": "path", "required": True, "schema": {"type": "string"}}
                                        for p in re.findall(r"\{([a-z]+)\}", path)]
        params += [{"name": q, "in": "query", "required": False, "schema": {"type": "string"}} for q in query]
        public = permission == "none"
        responses: Dict[str, Any] = {"200": {"description": "OK", "content": {"application/json": {
            "schema": {"type": "object"}}}}}
        for code, text in (("400", "Invalid request"), ("401", "Missing or invalid token"),
                           ("403", "Permission or checkpoint refused"), ("404", "Not found or not visible"),
                           ("409", "Conflict: state, stage or revision")):
            if public and code in ("401", "403"):
                continue
            responses[code] = {"description": text, "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/Error"}}}}
        op: Dict[str, Any] = {"operationId": _operation_id(method, path), "summary": summary,
                              "x-autology-permission": permission, "responses": responses}
        if params:
            op["parameters"] = params
        if public:
            op["security"] = []
        if method == "POST":
            op["requestBody"] = {"required": False, "content": {"application/json": {"schema": {"type": "object"}}}}
        paths.setdefault(path, {})[method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "Autology engine API", "version": API_VERSION,
                 "description": "The governed engine of one use case. Behind the platform router every path is "
                                "prefixed with /w/{workspace}/u/{use case}. Engine version " + __version__ + "."},
        "servers": [{"url": "/"}],
        "security": [{"bearer": []}],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
                       "schemas": {"Error": ERROR}},
        "paths": paths,
    }
