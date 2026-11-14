# Autology — requirements traceability

*14 November 2026 at `dfe8b3f`. Requirement → design → code → test → evidence → release gate. Sources: the master
instructions of 14 November (MI) and the master execution prompt (MP). Statuses per MP Rule 5.
Supersedes the section-by-section table of [AUTOLOGY_PREUVE_EXECUTION_INSTRUCTIONS.md](AUTOLOGY_PREUVE_EXECUTION_INSTRUCTIONS.md).*

## 1. Final acceptance criteria (MP §13; MI §13 equivalents in brackets)

| # | Criterion | Design | Code | Tests | Status | Gate |
|---|---|---|---|---|---|---|
| 1 | Engine independent of all UIs | [Architecture §1, §6](AUTOLOGY_ARCHITECTURE_TARGET.md) | `server.py` (optional inbox), `console.py` (separate) | `test_engine_headless.py`, `test_console.py` | Implemented and verified; versioned API contract not started | R2 exit (§2A test) |
| 2 | Two workspaces cannot access each other's data or tools [MI 1] | [Security §3](AUTOLOGY_SECURITY_AND_TENANCY.md) | `platform.py`, `audit.py`, `mcp.py` | `test_workspaces.py`, `test_iso1`–`iso4_*.py` | Implemented and verified for every existing path; document uploads do not exist yet | R1 (G3) |
| 3 | Several use cases with independent configuration and readiness [MI 2] | ADR-001 | `platform.py` | `test_workspaces.py`, `test_iso4_isolation_matrix.py` | Partially implemented: configuration yes, readiness status per use case not started (REL-3) | R2 |
| 4 | Studio generates an initial ontology from a description [MI 3] | [Roadmap R2](AUTOLOGY_RELEASE_ROADMAP.md) ARC-1 | — | — | Not started | R2 exit |
| 5 | Discovery questions adapt [MI 4] | ARC-3 | — | — | Not started | R2 exit |
| 6 | Excel templates generated, validated, reimported [MI 5] | XL-1–4 | — | — | Not started (`openpyxl` approved and evaluated) | R3 exit |
| 7 | Human organisation modelled, mapped to approved responsibilities [MI 6] | ORG-1/2 | — | — | Not started | R3 exit |
| 8 | Agent definitions and hierarchies generated under governance [MI 6] | AGF-1 | `agent.py` delegation, GOV-5 roles | `test_gov5_effective_permissions.py` (governance part) | Not started (factory); the governance it relies on is verified | R4 exit |
| 9 | Plugins, skills, connectors cannot bypass policies [MI 9] | INT-1, HRM-1 | `agent.py` result validation, journal | `test_agent.py` guardrails, `test_mod3_typed_outputs.py`, `test_external_effects*.py` | Partially implemented: every tool goes through governance and the journal; registry, plugins and Hermes adapter not started | R4 exit |
| 10 | External actions reliable, recoverable, audited [MI 10] | [R1 report §4](AUTOLOGY_R1_COMPLETION_REPORT.md) ACT-1–6 | `effects.py`, `agent.py`, `adapters.py`, `store.py`, `server.py` | `test_external_effects.py`, `test_external_effects_matrix.py` (112), `test_act6_revalidation.py` | Implemented and verified against simulated systems; not yet against a real ERP | R1 (G1); R4 sandbox |
| 11 | Production blocked when a gate fails [MI 7, 8] | REL-2 | `scoring.py` (scores only) | — | Not started (no release objects yet) | R2 |
| — | Existing behaviour preserved [MI 11] | Rule 1 | — | full suite, 559 | Implemented and verified | every increment |

## 2. Architectural principles (MP §2, MI §2, §2A)

| Requirement | Code | Tests | Status |
|---|---|---|---|
| Engine owns ontology, planning, orchestration, rules, authorisation, approvals, action authorisation, audit, outcomes, automation | `ontology.py`, `planner.py`, `agent.py`, `governance.py`, `server.py`, `audit.py`, `automation.py`, `effects.py` | suite | Implemented and verified (maturity and deployment enforcement: not started) |
| Engine works without Studio, Workspace UI or Hermes | `server.py` | `test_engine_headless.py` | Implemented and verified |
| UIs use only versioned, documented API contracts | Console uses the API | `test_console.py` | Partially implemented: no versioned contract |
| No governance only in the browser | server-side checks | `test_entry_point_matrix.py` | Implemented and verified |
| No AI-generated permission, rule or release active without approval | assistant proposes; people confirm | `test_governance_extras.py`, `test_chat_safety.py` | Implemented and verified for runs; rules and releases: R2 |
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
| Per-workspace maturity and deployment status | Not started | REL-1/3 |
| Use-case lifecycle Draft → Simulation → Pilot → Production | Not started | REL-1 |
| Cross-use-case access policy defined and tested | Implemented and verified: none implicit | `test_iso4_isolation_matrix.py`: `UseCaseBoundaryTests` |
| Industry templates hold no customer data | Not started (blueprints) | BP-1 |

## 4. Studio, AI Solution Architect, Excel, organisation, agents, integrations (MP §4–7, MI §4–8)

| Requirement | Release | Status |
|---|---|---|
| Studio as a separate application | R2 | Not started |
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
