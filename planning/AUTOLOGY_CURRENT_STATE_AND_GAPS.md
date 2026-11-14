# Autology — current state and gaps

*Updated 14 November 2026, revision after Phase 1 (see [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md)).
Builds on the independent audit of 13 November ([`../audit/`](../audit/README.md)); every claim below cites code,
tests or audit evidence.*

Status values: **Verified** (code + passing tests, some with real external systems), **Partial**, **Planned**
(designed, not built), **Missing**, **Not verifiable** (needs credentials, systems or people not available here).

## 1. The PDF (13 Nov) versus the code today

| PDF statement | Today | Evidence |
|---|---|---|
| ~11,000 Python lines in 32 files | 13,791 lines in 38 Python files (+ Console, settings, workspaces, Tier 3) | `wc -l autology/*.py` |
| 355 passing tests | 449 tests, 0 failing; CI runs them on Python 3.10 and 3.13 with PostgreSQL, nothing skipped | `python -m unittest discover -s tests -t .` |
| No data connectors | Ingestion pipelines (CSV/JSON/SQL incl. PostgreSQL/HTTP/push), checks, quarantine, lineage | `autology/ingest.py`, `tests/test_ingest.py` |
| No SSO | OpenID Connect verified with Keycloak (single-engine mode) | `autology/oidc.py`, audit 02 §3 |
| No project/workspace management | Workspaces with use cases, isolated stores, router (this increment) | `autology/platform.py`, `tests/test_workspaces.py` |
| No visual ontology editor | Still missing | — |
| No real-model validation | Still not verifiable here; the owner connected Claude on their PC on 14 Nov (manual, not recorded evidence) | — |

## 2. Capability classification against the master instructions

| Capability (instructions §) | Status | Evidence / gap |
|---|---|---|
| Engine: ontology, planning, governance, approvals, audit, REST, MCP, CLI (§2.1) | **Verified** | 449 tests; audit 01 §2 |
| Headless engine runs and is tested without any UI (§2A) | **Verified** | CLI/API/MCP tests; `deploy/smoke_test.sh` uses the API only |
| UI separate from the engine (§2A) | **Partial** | The Console is a separate process talking only to the public API (`autology/console.py`), but ships in the same Python package; the review inbox is still served by the engine (`autology/static/`) |
| Versioned API contract, OpenAPI, deprecation policy (§2A) | **Missing** | Routes documented in tables (`docs/platform.md`); no OpenAPI; typed SDKs exist (`autology/sdk.py`) |
| Transport-independent API dispatcher (prerequisite for BFF/router) | **Verified** (new) | `ApiExchange` in `autology/server.py`; `tests/test_api_exchange.py` |
| Workspace = isolation boundary, server-side (§2.5, §3, §11) | **Verified** for REST (new) | `autology/platform.py`; 11 tests (9 adversarial) through the HTTP router. MCP, SSO, events per workspace: **Missing** |
| Use cases with independent ontology, agents, data, audit (§2.6) | **Verified** (new) | Two use cases in one workspace with different ontologies (`examples/platform`) |
| Industry blueprints (§3) | **Partial** | Six example deployments act as templates; no versioned blueprint catalog |
| Environments/releases Draft→Simulation→Pilot→Production (§3, §10) | **Missing** | Only a `simulation` flag and ontology semver/diff (`versioning.py`); no release objects or promotion API |
| AI Solution Architect, dynamic questions, provenance labels (§4) | **Missing** | The governed assistant (`chat.py`) works on a published ontology, not on authoring one |
| Excel Template Factory and governed import (§5) | **Partial** | Ingestion gives validation, quarantine, lineage and dry-run preview for CSV/JSON/SQL; no `.xlsx` generation or upload, no human-confirmed commit step |
| Human org chart and agent org chart, approval of grants (§6) | **Missing** | Users, roles and reviewer roles live in config files |
| Agent Factory (versioned agent specs, supervisors) (§7) | **Partial** | Agents are configured (roles, tools, goals, delegates, approver); no spec object, version, supervisor or approval |
| Capability Registry / Integration Hub (§8) | **Partial** | `ToolRegistry` with capabilities, cost, conditions; tools have no declared effects, scopes, idempotency or health |
| Odoo / SAP / Dynamics / Power BI connectors (§8) | **Missing** (BI via the governed reporting DB: **Verified** with Metabase) | `warehouse.py` |
| Hermes (optional) (§8) | **Missing**, not required | — |
| Action safety: idempotency, uncertain state, reconciliation (§8) | **Missing** (GAP-001–007) | audit 04; GAP-008 (one run per record) **fixed** |
| Readiness scoring per use case, hard gates (§10) | **Partial** | `scoring.py` scores a deployment 0–100 with roadmap gates; not the six-dimension use-case scorecard; no server-side promotion gates |
| Studio (§9) | **Missing** | — |
| Workspace end-user UI (§9) | **Partial** | The Console: conversation, commands, reviews, configuration; not generated per use case |

## 3. Known defects still open (from the audit)

Critical: GAP-001 to GAP-007 (external action safety). High: GAP-009 (stale data after review), GAP-010
(unchecked tool output types), GAP-011 (self-review via automation), GAP-012 (field leak via scenarios), GAP-013
(confused deputy), GAP-014 (unchained run fields), GAP-016 (typos accepted in ontologies), GAP-017 (missing entity
treated as existing), GAP-018 (stale in-memory graph), GAP-031 (no licence). Fixed since the audit: GAP-008,
GAP-015.

## 4. Scores

| Assessment | Value | Basis |
|---|---|---|
| (A) Platform/engine product maturity | **Last measured 47/100** (audit, 13 Nov). Not re-measured after this increment | Two audit gaps closed and the workspace foundation added; a re-audit is needed before quoting a new number |
| (B) Use case / workspace readiness | **Not yet measurable** | The use-case scorecard of the instructions (§10) is not implemented yet |
