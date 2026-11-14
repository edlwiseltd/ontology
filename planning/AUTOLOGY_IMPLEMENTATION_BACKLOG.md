# Autology — implementation backlog

Effort: engineer-days for one engineer who knows the code, ±50%, excluding reviews and customer coordination.
"Gap" IDs refer to [`../audit/04_AUTOLOGY_GAP_REGISTER.md`](../audit/04_AUTOLOGY_GAP_REGISTER.md).

## Done in this increment (Phase 1 slice)

| ID | Item | Evidence |
|---|---|---|
| B-01 | Transport-independent API dispatcher (`ApiExchange`) | `tests/test_api_exchange.py` |
| B-02 | Engine body safety: negative/malformed `Content-Length` refused (GAP-015) | same |
| B-03 | Workspaces, members, use cases, router, dedicated stores, per-workspace secrets | `tests/test_workspaces.py` |
| B-04 | Console can target one use case behind the router | same |
| B-05 | One open run per record (GAP-008), earlier today | `tests/test_one_run_per_record.py` |

## P0 — before any pilot that writes to real systems

| ID | Item | Req | Files | Accept | Effort | Depends |
|---|---|---|---|---|---|---|
| P0-1 | Intent log + idempotency keys + outcome classification + confirmation contract + `uncertain` state + reconciliation (GAP-001–007) | R-AS-1 | `agent.py`, `adapters.py`, `tools.py`, `store.py`, `server.py` | Fault-injection matrix: 0 duplicates, 0 false confirmations | 15–25 | — |
| P0-2 | Close governance bypasses GAP-011, 012, 013, 014 | R-WS-1 | `server.py`, `automation.py`, `scenarios.py`, `agent.py`, `audit.py` | Audit PoCs become failing-then-passing tests | 5–7 | decision on GAP-013 semantics |
| P0-3 | Strict ontology schema (GAP-016), absent entities unknown (GAP-017), typed tool outputs (GAP-010) | R-SA-4 | `ontology.py`, `state.py`, `agent.py` | Misspelled keys rejected; restart never blocked by data | 4–5 | — |
| P0-4 | Licence and third-party notices (GAP-031) | — | repo root | Files present, legal sign-off | 0.5 + legal | owner decision |
| P0-5 | Workspace isolation for MCP, OIDC per workspace, per-workspace audit keys, per-workspace backup | R-WS-1 | `mcp.py`, `platform.py`, `audit.py`, `__main__.py` | Isolation tests extended to MCP and SSO | 4–6 | B-03 |

## P1 — Studio foundation and enterprise hardening

| ID | Item | Req | Accept | Effort |
|---|---|---|---|---|
| P1-1 | OpenAPI 3.1 contract generated from a declarative route table; contract tests; versioned `/api/v1`; deprecation policy | R-UI-3 | Contract test fails on an incompatible change | 4–6 |
| P1-2 | Workspace administration API (members, grants, use cases) with approvals and audit, hot reload | R-WS-3, R-ORG-2 | Grant requires approval by another admin; audited | 5–8 |
| P1-3 | Release objects and promotion API with hard gates; per-use-case scorecard | R-RG-1/2 | Acceptance test [8] | 8–12 |
| P1-4 | AI Solution Architect, minimal: brief → provisional ontology draft with provenance → validation → gap-driven questions; Oil & Gas maintenance + pharma briefs | R-SA-1/2/5 | Acceptance tests [3], [4] | 10–15 |
| P1-5 | Excel Template Factory: `.xlsx` generation from the ontology (standard library OOXML writer or `openpyxl` as an optional extra), upload → reuse `ingest.py` validation → preview → confirmed commit | R-XL-1/2/3 | Acceptance test [5] | 8–12 |
| P1-6 | Capability registry with declared effects, scopes, idempotency, health; read-only Odoo 18 connector | R-IH-1/2 | Odoo test instance read sync with lineage | 8–12 |
| P1-7 | GAP-009, 018, 021, 022, 023 (stale data, stale graph, timeouts, tick isolation, scans) | — | Regression tests | 6–9 |
| P1-8 | Move the review inbox out of the engine process; Studio and Workspace UI as separate build artifacts | R-UI-1 | Engine runs with every UI stopped; UI swap without engine change | 3–5 |

## P2 — productization

Org charts (human and agent, linked), Agent Factory specs and approval flow, Hermes adapter (only after verifying
its real interfaces), Workspace UI generated from the published use case, readiness dashboard, sector blueprint
catalog (Oil & Gas, pharma), PostgreSQL store if D2 requires it.

## Decisions needed from the owner

D1 deployment model (one platform per customer vs shared hosting) · D5 licence · GAP-013 semantics (requester ∩
agent roles) · first pilot process and Odoo access · supported AI providers · whether `openpyxl` (MIT) may be an
optional dependency for Excel.
