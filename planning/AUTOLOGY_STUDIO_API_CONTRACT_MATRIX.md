# Autology Studio — screen/action to API matrix

*14 November 2026. Every Studio action, the endpoint behind it, who may do it (enforced by the server) and its
status: **Verified** (real API, covered by tests), **Implemented but unverified**, **Demo-only** (mock data,
labelled), **Planned**, **Blocked** (needs an engine capability or an owner decision). Nothing in Studio is
Demo-only today: every screen uses the real platform.*

| Screen / action | Endpoint | Authorisation (server) | Status | Evidence |
|---|---|---|---|---|
| Sign in, workspace context | `GET /platform/me` | member token | Verified | e2e "workspace and use cases from the real platform" |
| Use-case catalogue with stages | `GET /platform/workspaces/{ws}/use-cases` | member; other workspaces 404 | Verified | e2e direct-call check (404) |
| Use-case overview, history, effective stage | `GET /platform/workspaces/{ws}/use-cases/{uc}` | granted member | Verified | e2e overview, history |
| Readiness checks | `GET …/{uc}/checks?to=` | granted member | Verified | e2e "Check now" |
| Stage move (Draft → Simulation → Pilot; back) | `POST …/{uc}/stage` | workspace admin; production always 403 | Verified | e2e move; e2e direct call by a non-admin → 403 |
| Create use case from approved template | `GET /platform/templates`, `POST …/use-cases` | workspace admin | Verified | e2e create (starts in Draft) |
| Execution state shown ("Nothing runs…") | engine execution gates (`/api/health`: `stage`, `runs_allowed`) | engine | Verified (engine side: `tests/test_r2_execution_gates.py`) | e2e "draft use case: the engine runs nothing" |
| Ontology canvas, entity list, inspector (read-only) | `GET /w/{ws}/u/{uc}/api/ontology` (entities, relationships, rules) | `read` | Verified | e2e canvas = list (5 entities), keyboard selection |
| Edit the model (nodes, edges, properties) | — (no model-edit API) | — | **Blocked**: needs an engine draft-model API with schema validation and revision checks | — |
| AI Architect (brief → provisional proposal) | — | — | **Blocked**: needs engine endpoints (ARC-1) and a provider decision (D7/D10) | — |
| Contextual discovery questions | — | — | **Blocked**: ARC-3 | — |
| Node/edge validation feedback | engine strict schema (MOD-1) at load; no validate-draft endpoint | — | **Blocked**: needs `POST …/validate` returning JSON-pointer locations | — |
| Releases, independent approval, rollback | — | — | **Blocked**: release governance (REL-1/2) and D11 | — |
| Members, grants, delegations | — | — | **Blocked**: ADM-1 | — |
| Platform API contract (`/platform/*` in OpenAPI) | — | — | Planned (engine routes are in API-1; platform routes are not yet) | — |

## Backend contracts Studio needs next (proposals, not implemented)

1. `GET/POST /w/{ws}/u/{uc}/api/model/draft` — a draft copy of the configuration with a revision; writes name the
   revision they read (the record-revision mechanism of GAP-018 applied to configuration).
2. `POST …/model/draft/validate` — strict-schema validation returning `{path, message, fix}` per problem, so
   Studio anchors errors to nodes, edges and fields.
3. `POST …/architect/proposals` — AI proposals as typed patches with provenance and confidence, never applied
   until a person accepts them (needs D7/D10).
4. Platform routes added to the OpenAPI contract.
