# Autology — requirements traceability

*14 November 2026 at `dfe8b3f`. Requirement → design → code → test → evidence → release gate. Sources: the master
instructions of 14 November (MI) and the master execution prompt (MP). Statuses per MP Rule 5.
Supersedes the section-by-section table of [AUTOLOGY_PREUVE_EXECUTION_INSTRUCTIONS.md](AUTOLOGY_PREUVE_EXECUTION_INSTRUCTIONS.md).*

## 1. Final acceptance criteria (MP §13; MI §13 equivalents in brackets)

| # | Criterion | Design | Code | Tests | Status | Gate |
|---|---|---|---|---|---|---|
| 1 | Engine independent of all UIs | [Architecture §1, §6](AUTOLOGY_ARCHITECTURE_TARGET.md) | `server.py` (optional inbox), `console.py` (separate) | `test_engine_headless.py`, `test_console.py` | Implemented and verified; API contract (OpenAPI 3.1, `autology/openapi.py`, `test_api_contract.py`) implemented for paths, methods, parameters, permissions and status codes; `/api/v1` and `/platform/v1` with one error envelope, pagination and version headers (`test_api_v1.py`, 15 Nov); typed body schemas for the core and Studio routes only | R2 exit (§2A test) |
| 2 | Two workspaces cannot access each other's data or tools [MI 1] | [Security §3](AUTOLOGY_SECURITY_AND_TENANCY.md) | `platform.py`, `audit.py`, `mcp.py` | `test_workspaces.py`, `test_iso1`–`iso4_*.py`, `test_gap018_record_consistency.py` (MCP through the router) | Implemented and verified for every existing path; document uploads do not exist yet | R1 (G3) |
| 3 | Several use cases with independent configuration and readiness [MI 2] | ADR-001; [R2 slice](AUTOLOGY_R2_SLICE_REPORT.md) | `platform.py`, `lifecycle.py` | `test_workspaces.py`, `test_iso4_isolation_matrix.py`, `test_r2_use_case_lifecycle.py` | Partially implemented: independent configuration and an independent lifecycle stage per use case (Draft/Simulation/Pilot, server-side checks); readiness score per use case not started (REL-3) | R2 |
| 4 | Studio generates an initial ontology from a description [MI 3] | [Roadmap R2](AUTOLOGY_RELEASE_ROADMAP.md) ARC-1 | — | — | Not started | R2 exit |
| 5 | Discovery questions adapt [MI 4] | ARC-3 | — | — | Not started | R2 exit |
| 6 | Excel templates generated, validated, reimported [MI 5] | XL-1–4 | — | — | Not started (`openpyxl` approved and evaluated) | R3 exit |
| 7 | Human organisation modelled, mapped to approved responsibilities [MI 6] | ORG-1/2 | — | — | Not started | R3 exit |
| 8 | Agent definitions and hierarchies generated under governance [MI 6] | AGF-1 | `agent.py` delegation, GOV-5 roles | `test_gov5_effective_permissions.py` (governance part) | Not started (factory); the governance it relies on is verified | R4 exit |
| 9 | Plugins, skills, connectors cannot bypass policies [MI 9] | INT-1, HRM-1 | `agent.py` result validation, journal | `test_agent.py` guardrails, `test_mod3_typed_outputs.py`, `test_external_effects*.py` | Partially implemented: every tool goes through governance and the journal; registry, plugins and Hermes adapter not started | R4 exit |
| 10 | External actions reliable, recoverable, audited [MI 10] | [R1 report §4](AUTOLOGY_R1_COMPLETION_REPORT.md) ACT-1–6 | `effects.py`, `agent.py`, `adapters.py`, `store.py`, `server.py` | `test_external_effects.py`, `test_external_effects_matrix.py` (112), `test_act6_revalidation.py`, `test_gap009_atomic_write_back.py` (local write-back all or nothing) | Implemented and verified against simulated systems; not yet against a real ERP | R1 (G1); R4 sandbox |
| 11 | Production blocked when a gate fails [MI 7, 8] | REL-2 | `lifecycle.py` | `test_r2_use_case_lifecycle.py` | Partially implemented: production is refused outright; Simulation and Pilot moves need every check to pass; no release objects or score-based gates yet | R2 |
| — | Existing behaviour preserved [MI 11] | Rule 1 | — | full suite, 559 | Implemented and verified | every increment |

## 2. Architectural principles (MP §2, MI §2, §2A)

| Requirement | Code | Tests | Status |
|---|---|---|---|
| Engine owns ontology, planning, orchestration, rules, authorisation, approvals, action authorisation, audit, outcomes, automation | `ontology.py`, `planner.py`, `agent.py`, `governance.py`, `server.py`, `audit.py`, `automation.py`, `effects.py` | suite | Implemented and verified (maturity and deployment enforcement: not started) |
| Engine works without Studio, Workspace UI or Hermes | `server.py` | `test_engine_headless.py` | Implemented and verified |
| UIs use only versioned, documented API contracts | Console and Studio use the API; contract at `GET /api/openapi.json` | `test_console.py`, `test_studio_shell.py`, `test_api_contract.py` | Implemented and verified for Studio: Studio calls only `/platform/v1` and `/api/v1` with TypeScript types generated from the published contracts (CI fails on drift, `test_api_v1.py` V6); the Console and MCP relay still use the deprecated legacy paths; typed bodies for the core and Studio routes only |
| No governance only in the browser | server-side checks | `test_entry_point_matrix.py` | Implemented and verified |
| No AI-generated permission, rule or release active without approval | assistant proposes; people confirm; releases need an independent person (REL-1a) | `test_governance_extras.py`, `test_chat_safety.py`, `test_rel1a_releases.py` | Implemented and verified for runs and configuration releases; Studio drafts still cannot become releases (needs hot reload, ADM-2) |
| R-GV-2: machines never record human approvals (D11, F-02) | `server.py` `User.kind`, `require_person`; `platform.py` member `kind`; `adapters.py` `HttpApprover.can_approve` | `test_h1_approval_identity.py` | Implemented and verified (`kind` is declared by the operator; company sign-in users count as persons) |
| R-GV-3: outbound credentials stay with their configured origin (F-01) | `outbound.py`; `ingest.py`, `adapters.py`, `server.py` (webhooks), `oidc.py`, `tracing.py` | `test_h1_outbound.py` | Implemented and verified (configured destinations stay trusted; no private-address blocking) |
| R-RG-3 / R-RG-4: immutable releases, independent approval, drift, rollback, run binding | `releases.py`; `platform.py` (`_releases`, `effective_stage_and_reason`, `_release_checks`); `agent.py` (`RunState.configuration`, `resume`); `server.py` (`configuration_fingerprint`, `decide`) | `test_rel1a_releases.py`, `test_r2_use_case_lifecycle.py` (pilot needs an approved active release) | Implemented and verified at repository level; activation needs a restart with the released files (no hot reload); Python code imported by tools is not in the snapshot |
| ADM-1/ADM-2: administration without restarts, independent grant approval | `administration.py`; `platform.py` (`_administration`, `_replay`, `_refresh`, `reload_use_case`); `server.py` (`parse_users`, `set_users`) | `test_adm1_administration.py` | Implemented and verified (API); Studio members screen not built |
| STU-6: releases in Studio; a draft becomes a governed release | `platform.py` (`publish_draft`, `restore_release`, per-use-case ontology file); `studio/web/components/ReleasesView.tsx` | `test_stu6_publish.py`; e2e (proposer offered no approval, approver cannot activate, activation, publish) | Implemented and verified |
| R-EX-1, R-KN-1..3, R-GV-4 (V2 directions) | — | — | Documented ([architecture Part B](AUTOLOGY_ARCHITECTURE_TARGET.md)); not implemented |
| R-IAM-2 tenant distinct from workspace (IAM-1) | `tenancy.py` (versioned, chained registry; migration; explicit `tenancy assign`), `platform.py` (`Tenant`, `TenantMember`, `members_for`, `tenant_view`), `mcp.py` (`--workspace`) | `test_iam1_tenants.py` (9: compatibility, migration, restart, rollback, membership boundaries, cross-tenant 404s, MCP, background) | Implemented and verified at repository level; tenant-level members and administrators are configuration-only; no tenant-level sign-in |
| R-IAM-6 administrative roles carry no business data (IAM-3, D22a) | `server.py` (`configure` permission, `require_any`, MCP refusal), `platform.py` (`Member.grant`, `_separate_privileges`, grants and revocation for administrators), `administration.py` (`grant_migrated`, `privileges_separated`, `append_batch`) | `test_iam3_privilege_separation.py` (8, all failing on the commit before); `test_entry_point_matrix.py` (a `configure`-only identity is refused on every data route) | Implemented and verified at repository level, including GAP-061 (a model's access rules never change on one person's say-so: the author of a draft cannot publish it) |
| R-IAM-1, R-IAM-3, R-IAM-4, R-IAM-5 (operators, portal, public, plugin identities) | Existing: tokens, OIDC per workspace, members, `kind`, engine permissions and ontology rules | `test_workspaces`, `test_iso1…4`, `test_oidc`, `test_adm1_administration`, `test_h1_approval_identity` | Internal users implemented; platform operators (IAM-2), portal users (IAM-4), public visitors (IAM-5), agent and plugin identities (IAM-6) **not implemented, not authorised** ([gap analysis](AUTOLOGY_IAM_TARGET.md)) |
| Hermes optional, never a dependency | — | `test_engine_headless.py` (`no_engine_module_mentions_hermes`) | Implemented and verified |

## 3. Workspaces and use cases (MP §3, MI §3)

| Requirement | Status | Evidence |
|---|---|---|
| Per-workspace identity and memberships | Implemented and verified (static configuration) | `test_workspaces.py` |
| Per-workspace data and stores | Implemented and verified | same |
| Per-workspace documents | Not started (no uploads exist) | — |
| Per-workspace ontologies and configuration | Implemented and verified | `examples/platform` |
| Per-workspace agents and executions | Implemented and verified | `test_iso4_isolation_matrix.py` |
| Per-workspace secrets and credentials | Implemented and verified | `test_workspaces.py`, `test_iso4_isolation_matrix.py` |
| Per-workspace audit | Implemented and verified | `test_iso2_*.py` |
| Per-workspace maturity and deployment status | Partially implemented: lifecycle stage per use case; maturity score not started | `test_r2_use_case_lifecycle.py`; REL-3 |
| Use-case lifecycle Draft → Simulation → Pilot → Production | Partially implemented: stages with server-side checks and a keyed history; production refused (PROD); stages not enforced at run time; no immutable releases | `test_r2_use_case_lifecycle.py`; REL-1 |
| Cross-use-case access policy defined and tested | Implemented and verified: none implicit | `test_iso4_isolation_matrix.py`: `UseCaseBoundaryTests` |
| Industry templates hold no customer data | Not started (blueprints) | BP-1 |

## 4. Studio, AI Solution Architect, Excel, organisation, agents, integrations (MP §4–7, MI §4–8)

| Requirement | Release | Status |
|---|---|---|
| Studio as a separate application | R2 | Implemented and verified for the shell (Next.js, `studio/web`, D9 approved): catalogue, overview, stage moves, creation, read-only ontology canvas; Vitest, Playwright browser tests, `test_studio_separation.py`. Editing, AI Architect, releases: blocked on engine APIs ([matrix](AUTOLOGY_STUDIO_API_CONTRACT_MATRIX.md)) |
| Natural-language brief → provisional ontology with provenance | R2 | Not started |
| Dynamic discovery (no fixed questionnaire) | R2 | Not started |
| Visual architecture producing engine-valid configuration (one model, the strict schema) | R2 | Not started; the strict schema (MOD-1, `docs/ontology.schema.json`) is the shared model |
| Excel Template Factory and governed import | R3 | Not started |
| Organisational intelligence | R3 | Not started |
| Agent Factory with governance | R4 | Not started |
| Integration Hub; Odoo 18 sandbox; optional Hermes | R4 | Not started (tools, HTTP adapter with action safety, pipelines exist) |
| External action reliability before any ERP write | R1 | Implemented and verified (simulated) |

## 5. Maturity and gates (MP §8, MI §10)

| Requirement | Status | Evidence |
|---|---|---|
| Platform maturity measured with evidence | Implemented: self-assessed ≈ 65, not independently verified | [Scorecard](AUTOLOGY_MATURITY_SCORECARD.md) |
| Use-case maturity, six dimensions, documented weights | Not started | REL-3 |
| Server-side gates that a high score cannot override | Not started | REL-2 |
| Reassessment on material change | Not started | REL-3 |

## 6. Required documents (MP §11, MI §14)

| Document | File |
|---|---|
| Current state verification | [AUTOLOGY_CURRENT_STATE_VERIFICATION.md](AUTOLOGY_CURRENT_STATE_VERIFICATION.md) (was *current state and gaps*) |
| Target architecture | [AUTOLOGY_ARCHITECTURE_TARGET.md](AUTOLOGY_ARCHITECTURE_TARGET.md) |
| Requirements traceability | this file |
| R1 completion report | [AUTOLOGY_R1_COMPLETION_REPORT.md](AUTOLOGY_R1_COMPLETION_REPORT.md) |
| Maturity scorecard | [AUTOLOGY_MATURITY_SCORECARD.md](AUTOLOGY_MATURITY_SCORECARD.md) |
| Release roadmap | [AUTOLOGY_RELEASE_ROADMAP.md](AUTOLOGY_RELEASE_ROADMAP.md) |
| Decision register | [AUTOLOGY_DECISION_REGISTER.md](AUTOLOGY_DECISION_REGISTER.md) |
| Executive status (French) | [AUTOLOGY_EXECUTIVE_STATUS_FR.md](AUTOLOGY_EXECUTIVE_STATUS_FR.md) |
| Also kept | [PRD](AUTOLOGY_PRD.md), [security and tenancy](AUTOLOGY_SECURITY_AND_TENANCY.md), [defect register](AUTOLOGY_DEFECT_REGISTER.md), [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md), [backlog](AUTOLOGY_IMPLEMENTATION_BACKLOG.md), [readiness and gates](AUTOLOGY_READINESS_AND_RELEASE_GATES.md), [product requirements](AUTOLOGY_PRODUCT_REQUIREMENTS.md) |
