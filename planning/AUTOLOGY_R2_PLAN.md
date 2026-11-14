# Autology — R2 implementation plan: Studio foundation

*14 November 2026. Prerequisite met: the R1 safety and isolation gates pass in the repository
([close-out](AUTOLOGY_R1_CLOSEOUT.md)). No production deployment is authorised.*

## 1. Goal and exit criteria

R2 lets an administrator turn a business description into a governed, provisional use case. They describe the
business, answer the questions the system derives from what is missing, upload Excel data, and promote a tested
release. All of this goes through a Studio that is a separate application and talks to the engine only through
its versioned API.

**Exit criteria.** These are the master instructions' acceptance tests 3, 4, 5, 7 and 8, automated:

| # | Test | Automated check |
|---|---|---|
| 3 | An Oil & Gas upstream brief yields a clearly labelled provisional model; a pharma brief uses the same engine and Studio, with no core change | Both briefs through the architect API; the `autology/` core diff between them is empty; every element is labelled `AI proposed` |
| 4 | Missing facts produce context-dependent questions and a matching template pack, not a fixed questionnaire | Two briefs give different questions; each question names the fact it resolves and the evidence expected |
| 5 | Completed templates import with exact mappings and provenance; invalid units, missing ids, duplicates, broken references and cross-workspace data fail row by row | A fixture workbook per error class gives row/cell errors; a valid one commits with provenance |
| 7 | Readiness and blockers recalculate after evidence, policy and schema changes | REL-3 tests |
| 8 | A 97/100 configuration with a failed critical check cannot reach production, even through a direct API call | REL-2 test calling the promotion endpoint directly |

Plus: Studio is built, deployed and replaced independently; the engine passes its suite with Studio stopped; and a
minimal third-party client reaches the same governance (master instructions §2A).

## 2. Principles carried from R1

- **Headless engine.** Studio holds no business rules and no direct database access. Every write goes through the
  engine's governed API.
- **Nothing is live by default.** Architect output, imports and new grants land in a **draft release**. Only a
  promotion that passes the gates, approved by an authorised person, makes them active.
- **No AI-granted authority.** The architect proposes ontology elements, questions and templates. It never grants
  permissions, approves releases or writes live data.
- **Untrusted inputs stay data.** Briefs, documents and spreadsheets are treated as data, never as instructions to
  an agent; each workspace's content stays in its own store.

## 3. Prerequisites (R2.0): needed before Studio work

| ID | Story | Why first | Acceptance | Est. |
|---|---|---|---|---|
| API-1 | OpenAPI 3.1 contract generated from one route table, with contract tests | Studio and third parties build against it | Every route in the table; a test fails if a route and the contract differ | 3 d |
| API-2 | `/api/v1` paths, deprecation policy, version header | UIs upgrade independently | Old paths answer with a deprecation header for one release | 1 d |
| ARC-0 | Split `AutologyService` into services behind the route table (GAP-026) | The new services (admin, releases, architect, imports) would otherwise grow the god object | No behaviour change: the 548 tests pass unchanged | 5–8 d |
| MIG-1 | Ordered migrations in one transaction (GAP-041) | R2 adds several tables | An interrupted migration leaves the old schema intact | 1 d |
| QA-1 | mypy, ruff and pip-audit in CI (GAP-025); pinned constraints (GAP-040) | Larger surface, more contributors | CI fails on new type errors or known High vulnerabilities | 2–3 d |
| AI-1 | Provider-neutral model adapter contract, validated with two adapters (D7) | The architect needs a model | The same eval suite passes with both adapters; adapter errors never escape (GAP-029). Real-provider runs need API keys from the owner | 3 d + API cost |
| UI-1 | Review inbox moved out of the engine process | Completes the UI separation | The engine serves only the API | 1 d |

## 4. Workstreams

### A. Dynamic workspaces and releases (engine)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| ADM-1 | Workspace administration API: create workspaces and use cases; add or remove members; propose grants | Changes are audited; a grant becomes active only when a second authorised administrator approves it, and never the proposer (master §6); cross-workspace attempts get 404 | 6 d |
| ADM-2 | Changes apply without restarting (hot reload of members, grants, use cases) | A new member can sign in within one request of approval; revoking access takes effect immediately | 2 d |
| REL-1 | Immutable use-case releases: Draft → Simulation → Pilot → Production, plus Suspended and Rollback; runs pinned to the release fingerprint (GAP-020) | A release is a content-addressed snapshot; rollback restores the previous one; a run started on release N continues on N | 6 d |
| REL-2 | Server-side hard gates on promotion | The gates of the instructions §10 (approval ownership, separation of duties, cross-tenant access, untested critical connector, critical vulnerability, no authoritative confirmation, no recovery evidence, audit gaps, sector controls) block promotion whatever the score; acceptance test 8 | 3 d |
| REL-3 | Use-case readiness scorecard: six dimensions, each metric with formula, denominator, target, evidence source, confidence, reviewer and refresh trigger; one scoring authority with `scoring.py` | Material changes invalidate the evidence they touch; acceptance test 7 | 6 d |
| REL-4 | Semantic diff covers every section (GAP-028) | Release diffs show impact rules, scheduling, questions, settings | 2 d |

### B. AI Solution Architect (engine service, through AI-1)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| ARC-1 | Business brief → draft ontology in a draft release, validated by the strict schema (MOD-1) | Invalid model output is repaired or refused, never stored; every element is provisional; nothing reaches live data | 6 d |
| ARC-2 | Provenance label on every element (`AI proposed`, `user supplied`, `document extracted`, `system synchronized`, `human verified`) and change lineage | A label changes only through an audited action; `human verified` needs a person | 3 d |
| ARC-3 | Next questions from the model's gaps: a deterministic gap analysis (rules on fields that have no source, actions without tools, entities without data, missing approvers or reviewer roles) ranked by risk and dependency, worded by the model | Each question names the fact or rule it resolves and the evidence expected; acceptance test 4 | 4 d |
| ARC-4 | Reconcile answers and documents: contradictions highlighted; safety-relevant ambiguity must be resolved before promotion (a REL-2 gate) | A contradiction blocks promotion until a person resolves it | 4 d |
| BP-1 | Oil & Gas upstream (maintenance work orders) and pharma (deviation / CAPA) blueprints as optional, versioned templates with no customer data | Acceptance test 3; brought forward from R4 because the R2 exit needs it | 4 d |
| SEC-A | Prompt-injection and data-boundary tests for briefs and documents (GAP-045) | Instructions inside a brief or document never become rules, grants or actions | 2 d |

### C. Excel Template Factory (engine; `openpyxl`, approved)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| XL-1 | Template pack generated per workspace and use case from the ontology and the open questions | Each `.xlsx` has an instructions sheet, schema/template id and version, stable record id column, typed headers, required/optional flags, sample rows, dropdowns for vocabularies and states, units, reference columns, owner/source metadata; individual files and a bundle; regenerating a pack keeps existing ids | 5 d |
| XL-2 | Upload: quarantine → safe parse → validate | Macros (`.xlsm`) refused; size and zip-bomb limits; read-only, `data_only`, formulas never evaluated, text never treated as instructions; type, unit, id, foreign-key and duplicate checks; row- and cell-level errors and a downloadable error workbook; a file from another workspace refused | 6 d |
| XL-3 | Preview, human confirmation, transactional commit, provenance, rescoring | Nothing is written before a person confirms; the commit is one transaction into the draft release; provenance per row; readiness recalculated; acceptance test 5 | 3 d |
| XL-4 | First vertical slice: an employees and roles template, and an assets and equipment template | Both round-trip: generate → fill → upload → preview → commit, with the error classes of test 5 | 2 d |

Employee data stays minimal: only the fields the use case needs, and personal fields are marked `pii` so the
existing field rules apply.

### D. Studio: a separate application

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| STU-1 | Shell: sign-in, workspace selector, use-case catalogue, built from the OpenAPI client | Builds, runs and deploys on its own; the engine's suite passes with Studio stopped; a user without admin rights gets nothing extra by changing routes | 6 d |
| STU-2 | Architect panel and provisional model view (entities, relations, actions, rules, provenance), editing through the API | Edits are validated server-side; provisional elements are marked as such | 8 d |
| STU-3 | Questions and missing-evidence queue | Follows ARC-3 | 3 d |
| STU-4 | Template centre: download, upload, row errors, preview, confirm | Follows XL-1 to XL-3 | 4 d |
| STU-5 | Readiness and blockers dashboard | Read-only view of REL-3 | 3 d |
| STU-6 | Release history, promotion requests and approvals, rollback | Promotion goes through REL-2; the approver is not the requester | 3 d |

## 5. Sequence

| Step | Content | Depends on |
|---|---|---|
| 1 | API-1, API-2, ARC-0, MIG-1, QA-1, UI-1 | — |
| 2 | ADM-1, ADM-2, REL-1, REL-2, REL-4 | 1 |
| 3 | XL-1 to XL-4 (engine) · AI-1 | 2 (draft releases) |
| 4 | ARC-1 to ARC-4, BP-1, SEC-A · REL-3 | 2, 3 (AI-1) |
| 5 | STU-1 to STU-6 | 1 (contract); views follow 2–4 |
| 6 | Exit tests 3, 4, 5, 7, 8 and the §2A deployment test | all |

**Effort.** About 115–130 engineer-days, assuming one experienced engineer with AI assistance, model API access
from step 3, and no external reviews inside R2. Studio (≈ 27 d) can run in parallel with steps 3–4 once step 1 has
fixed the contract.

## 6. Decisions needed before or during R2

| ID | Decision | Recommendation |
|---|---|---|
| D9 | Studio technology and repository | A TypeScript single-page application in its own directory and package (`studio/`), with its own build, Dockerfile and release, using a client generated from the OpenAPI contract. Same repository for now, separate artefacts (master §2A) |
| D10 | Which model providers for AI-1 and the architect, and where workspace briefs may be sent | Two providers (D7); per-workspace setting for whether briefs and documents may leave for a model provider (data residency) |
| D11 | Second approver for grants and promotions in small customers | Allow a named external approver role when a workspace has only one administrator |
| D2, D3 | Store and encryption at rest | Still open; not blocking R2 on isolated pilots |

## 7. Not in R2

Integration Hub and capability registry, Odoo sandbox connector (R3, after ACT-1–6, per D6); human organisation
model and Agent Factory (R3); generated Workspace end-user UI (R3); load tests, restore drill, external penetration
test (R4).

## 8. Risks

| Risk | Mitigation |
|---|---|
| Model output that looks valid but is wrong (invented roles, thresholds) | Strict schema, provenance labels, nothing active before a reviewed promotion, contradiction gates |
| Spreadsheet attacks (zip bombs, external links, macros, formula injection) | XL-2's safe parse, quarantine and limits; exported cells escaped against formula injection |
| Studio drifting into business logic | Contract tests; the engine's suite runs with Studio stopped; review rule: no policy in the UI |
| Scope: Studio views grow faster than engine features | Studio stories start only when their API exists and is tested |
| Personal data in employee templates | Data minimisation, `pii` fields under field rules, no personal data in sample rows |
