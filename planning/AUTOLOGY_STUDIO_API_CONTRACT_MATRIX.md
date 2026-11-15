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
| Edit the model (nodes, edges, properties, layout) in a draft | `GET/POST /w/{ws}/u/{uc}/api/model/draft` (`expected_revision`), `GET …/model/draft/history` | read; save: admin | Verified | e2e design journey (add, connect, inspector edits, save as revision 1, stale save refused 409); `tests/test_studio2_modeling.py` |
| Architect: brief → provisional proposal | `POST …/architect/proposals` | admin | **Verified for the blueprint generator (not AI)**; a model-based generator is **Blocked** on D7/D10 | e2e (11 provisional items, labelled "blueprint · not AI"); unit `ProposalTests` |
| Contextual discovery questions | returned by `GET …/model/draft` and `POST …/model/validate` | read | Verified (rule-based, from real gaps; not AI) | e2e "questions come from real gaps"; unit `QuestionTests` |
| Node/edge validation feedback | `POST …/model/validate` (engine strict loader; path, node, field or edge) | read | Verified (one blocking problem at a time) | e2e "malformed attribute refused and anchored to its node"; unit `ValidationTests` |
| Releases, independent approval, rollback | — | — | **Blocked**: release governance (REL-1/2) and D11 | — |
| Members, grants, delegations | — | — | **Blocked**: ADM-1 | — |
| Platform API contract (`/platform/v1/*` in OpenAPI) | `GET /platform/openapi.json` | none (no data) | **Verified** (15 Nov): every platform route, typed responses; Studio types generated from it | `tests/test_api_v1.py` (schema conformance from a real platform; drift) |
| API version | every Studio call uses `/platform/v1/...` and `/w/{ws}/u/{uc}/api/v1/...`; errors read from the v1 envelope | unchanged (same handlers) | **Verified** (15 Nov) | e2e: direct v1 and legacy calls both refused (403/404/404/403/403); 409 conflict read from `error.details` |

## Backend contracts Studio needs next (proposals, not implemented)

*Items 1 and 2 below were implemented in Studio increment 2 (`/api/model/draft`, `/api/model/validate`); item 3 exists with a blueprint generator only.*

1. `GET/POST /w/{ws}/u/{uc}/api/model/draft` — a draft copy of the configuration with a revision; writes name the
   revision they read (the record-revision mechanism of GAP-018 applied to configuration).
2. `POST …/model/draft/validate` — strict-schema validation returning `{path, message, fix}` per problem, so
   Studio anchors errors to nodes, edges and fields.
3. `POST …/architect/proposals` — AI proposals as typed patches with provenance and confidence, never applied
   until a person accepts them (needs D7/D10).
4. Platform routes added to the OpenAPI contract.
