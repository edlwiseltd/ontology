# Autology — release roadmap

*14 November 2026 at `dfe8b3f`. Follows the owner's six-release sequence of 14 November. The table at the end
lists three deliberate dependency-order choices, each justified by repository evidence. Estimates are
engineer-days (d) for one experienced engineer with AI assistance, ±30 %, excluding external reviews and
customer coordination. **No production deployment is authorised** in any release until the owner authorises it.*

## 1. Overview

| Release | Theme | Exit criteria (master prompt §13 numbering) | Status |
|---|---|---|---|
| **R1** | Engineering foundation | Gate 80 repository criteria; G1 = G2 = G3 = 0; criteria 1, 2, 10 | **Done** ([report](AUTOLOGY_R1_COMPLETION_REPORT.md)); legal sign-off and independent re-verification open |
| **R2** | Studio foundation | 1 (versioned contract), 3 (readiness per use case), 4, 5, 11 (server-side gates) | Planned |
| **R3** | Structured enterprise onboarding | 6, 7 | Planned |
| **R4** | Agent Factory and integrations | 8, 9, 10 against an Odoo 18 sandbox | Planned |
| **R5** | Operational experience | Workspace UI generated from the published use case | Planned |
| **R6** | Product readiness | Gates 90 and 95 (mostly external evidence) | Planned |

Security and deployment controls come early: the release objects, the server-side gates and the readiness engine
are in **R2**. R6 adds the dashboards and the evidence that the enforcement holds.

## 2. R1: Engineering foundation (done)

| Delivered | Evidence |
|---|---|
| GOV-1–5, MOD-1–4, ACT-1–6, ISO-1–4, LEG-1, ENG-1; entry-point and fault-injection matrices | [R1 completion report](AUTOLOGY_R1_COMPLETION_REPORT.md), 559 tests, CI runs 18–44 |

Open from R1: legal sign-off (counsel); independent re-verification; residuals of GAP-009 (atomic write-back) and
GAP-018 (reload on write), both in R3.

## 3. R2: Studio foundation

Goal: an administrator manages workspaces and use cases. The architecture is versioned as releases. Studio edits
the model visually on the engine's own schema. The AI Solution Architect proposes a provisional ontology and asks
questions derived from what is missing. Promotion is blocked server-side when a gate fails.

### 3.1 Prerequisites

| ID | Story | Why first | Acceptance | Est. |
|---|---|---|---|---|
| API-1 | OpenAPI 3.1 contract generated from one route table, with contract tests | Studio and third parties build against it | Every route in the table; a test fails if a route and the contract differ | 3 d |
| API-2 | `/api/v1` paths, deprecation policy, version header | UIs upgrade independently | Old paths answer with a deprecation header for one release | 1 d |
| ARC-0 | Split `AutologyService` into services behind the route table (GAP-026) | The new services (admin, releases, architect, imports) would otherwise grow the god object | No behaviour change: the full suite passes unchanged | 5–8 d |
| MIG-1 | Ordered migrations in one transaction (GAP-041) | R2 adds several tables | An interrupted migration leaves the old schema intact | 1 d |
| QA-1 | mypy, ruff and pip-audit in CI (GAP-025); pinned constraints (GAP-040) | Larger surface, more contributors | CI fails on new type errors or known High vulnerabilities | 2–3 d |
| AI-1 | Provider-neutral model adapter contract, validated with two adapters (D7) | The architect needs a model | The same eval suite passes with both adapters; adapter errors never escape (GAP-029). Real-provider runs need API keys from the owner | 3 d + API cost |
| UI-1 | Review inbox moved out of the engine process | Completes the UI separation | The engine serves only the API | 1 d |

### 3.2 Workspace and use-case management, releases and gates (engine)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| ADM-1 | Workspace administration API: create workspaces and use cases; add or remove members; propose grants | Changes are audited; a grant becomes active only when a second authorised administrator approves it, and never the proposer (master §6); cross-workspace attempts get 404 | 6 d |
| ADM-2 | Changes apply without restarting (hot reload of members, grants, use cases) | A new member can sign in within one request of approval; revoking access takes effect immediately | 2 d |
| REL-1 | Immutable use-case releases: Draft → Simulation → Pilot → Production, plus Suspended and Rollback; runs pinned to the release fingerprint (GAP-020) | A release is a content-addressed snapshot; rollback restores the previous one; a run started on release N continues on N | 6 d |
| REL-2 | Server-side hard gates on promotion | The gates of the instructions §10 (approval ownership, separation of duties, cross-tenant access, untested critical connector, critical vulnerability, no authoritative confirmation, no recovery evidence, audit gaps, sector controls) block promotion whatever the score; acceptance test 8 | 3 d |
| REL-3 | Use-case readiness scorecard: six dimensions, each metric with formula, denominator, target, evidence source, confidence, reviewer and refresh trigger; one scoring authority with `scoring.py` | Material changes invalidate the evidence they touch; acceptance test 7 | 6 d |
| REL-4 | Semantic diff covers every section (GAP-028) | Release diffs show impact rules, scheduling, questions, settings | 2 d |

### 3.3 AI Solution Architect and dynamic discovery (engine service, through AI-1)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| ARC-1 | Business brief → draft ontology in a draft release, validated by the strict schema (MOD-1) | Invalid model output is repaired or refused, never stored; every element is provisional; nothing reaches live data | 6 d |
| ARC-2 | Provenance label on every element (`AI proposed`, `user supplied`, `document extracted`, `system synchronized`, `human verified`) and change lineage | A label changes only through an audited action; `human verified` needs a person | 3 d |
| ARC-3 | Next questions from the model's gaps: a deterministic gap analysis (rules on fields that have no source, actions without tools, entities without data, missing approvers or reviewer roles) ranked by risk and dependency, worded by the model | Each question names the fact or rule it resolves and the evidence expected; acceptance test 4 | 4 d |
| ARC-4 | Reconcile answers and documents: contradictions highlighted; safety-relevant ambiguity must be resolved before promotion (a REL-2 gate) | A contradiction blocks promotion until a person resolves it | 4 d |
| BP-1 | Oil & Gas upstream (maintenance work orders) and pharma (deviation / CAPA) blueprints as optional, versioned templates with no customer data | Acceptance test 3; brought forward because the R2 exit needs it | 4 d |
| SEC-A | Prompt-injection and data-boundary tests for briefs and documents (GAP-045) | Instructions inside a brief or document never become rules, grants or actions | 2 d |

### 3.4 Studio (a separate application)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| STU-1 | Shell: sign-in, workspace selector, use-case catalogue, built from the OpenAPI client | Builds, runs and deploys on its own; the engine's suite passes with Studio stopped; a user without admin rights gets nothing extra by changing routes | 6 d |
| STU-2 | Architect panel and provisional model view (entities, relations, actions, rules, provenance), editing through the API | Edits are validated server-side; provisional elements are marked as such | 8 d |
| STU-3 | Questions and missing-evidence queue | Follows ARC-3 | 3 d |
| STU-5 | Readiness and blockers dashboard | Read-only view of REL-3 | 3 d |
| STU-6 | Release history, promotion requests and approvals, rollback | Promotion goes through REL-2; the approver is not the requester | 3 d |

**R2 effort:** about 95–110 d. **R2 sequence:**
1. Prerequisites.
2. ADM, REL-1, REL-2, REL-4.
3. AI-1.
4. ARC, BP-1, SEC-A, REL-3.
5. Studio, which can start as soon as the API contract is fixed.
6. The exit tests.

## 4. R3: Structured enterprise onboarding

### 4.1 Excel Template Factory (engine; `openpyxl` approved, evaluated in the [decision register](AUTOLOGY_DECISION_REGISTER.md))

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| XL-1 | Template pack generated per workspace and use case from the ontology and the open questions | Each `.xlsx` has an instructions sheet, schema/template id and version, stable record id column, typed headers, required/optional flags, sample rows, dropdowns for vocabularies and states, units, reference columns, owner/source metadata; individual files and a bundle; regenerating a pack keeps existing ids | 5 d |
| XL-2 | Upload: quarantine → safe parse → validate | Macros (`.xlsm`) refused; size and zip-bomb limits; read-only, `data_only`, formulas never evaluated, text never treated as instructions; type, unit, id, foreign-key and duplicate checks; row- and cell-level errors and a downloadable error workbook; a file from another workspace refused | 6 d |
| XL-3 | Preview, human confirmation, transactional commit, provenance, rescoring | Nothing is written before a person confirms; the commit is one transaction into the draft release; provenance per row; readiness recalculated; acceptance test 5 | 3 d |
| XL-4 | First vertical slice: an employees and roles template, and an assets and equipment template | Both round-trip: generate → fill → upload → preview → commit, with the error classes of test 5 | 2 d |

Employee data stays minimal: only the fields the use case needs, and personal fields are marked `pii` so the
existing field rules apply.

### 4.2 Documents, provenance, organisation, systems

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| DOC-1 | Document ingestion (PDF, office files) into the draft release: quarantine, size limits, text extraction, per-workspace storage | Documents of workspace A never reachable from B; extracted text is data, never instructions (SEC-A tests extended) | 6 d |
| PRV-1 | Provenance and import versions across templates, documents and answers; nothing previously validated is lost when a template is regenerated | Reimport after regeneration keeps verified rows and their labels | 3 d |
| ORG-1 | Human organisation model: departments, positions, reporting lines, responsibilities, approval authorities, delegations, segregation-of-duties constraints, from templates or a read-only HRIS sync | Employment role never equals authorisation by itself; personal data minimised | 6 d |
| ORG-2 | Access recommendations from the organisation model, activated only after a second administrator approves (ADM-1); no self-granting | Acceptance criterion 7 | 4 d |
| SYS-1 | Enterprise system discovery: a template and questions for the systems in use (ERP, CRM, HR, DMS, BI), feeding R4's integration choices | Each discovered system recorded with owner, data domains and access mode | 3 d |
| ISO-5 | Isolation matrix extended to documents and imports | Cross-workspace document and import access refused | 1 d |
| HARD-1 | GAP-009 residual (atomic write-back), GAP-018 long-term (reload on write), GAP-022, GAP-036, GAP-048 | Regression tests | 5 d |
| STU-4 | Template centre: download, upload, row errors, preview, confirm | Follows XL-1 to XL-3 | 4 d |

**R3 effort:** about 50–60 d.

## 5. R4: Agent Factory and integrations

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| AGF-1 | Versioned agent specifications: mission, objectives, scope and objects, role and position, allowed tools and skills, delegation, triggers, permissions, approval requirements, escalation, accountability and audit | Specs are proposals in a draft release; no agent activates or grants itself permissions | 6 d |
| AGF-2 | Agent proposals from process requirements, with a measurable value per agent; human–agent responsibility mapping; visual agent chart in Studio | Acceptance criterion 8; no agent without a justified responsibility | 6 d |
| AGF-3 | Agent evaluation and simulation before promotion (reuses the evaluation harness and scenarios) | A spec fails promotion without passing evaluations | 4 d |
| INT-1 | Capability registry: name, version, provider, schema, effects, scopes, idempotency, timeout, health, tenant authorisation, test status; skills, tools and schedulers distinguished | Every call still goes through governance and the journal; acceptance criterion 9 | 5 d |
| INT-2 | Odoo 18 Enterprise read-only connector against a **sandbox** (D6) | Read sync with lineage on the sandbox | 6 d |
| INT-3 | Odoo writes on the **sandbox only**: idempotency via a unique request reference, read-back confirmation, reconciliation | Fault injection against the sandbox: 0 duplicates, 0 false confirmations; **production writes stay disabled** | 6 d |
| INT-4 | Further connectors chosen per customer architecture (SAP, Dynamics, Power BI as analytics, DMS, HRIS) | Per connector: the same contract tests | per connector |
| HRM-1 | Optional Hermes adapter, only after its real interfaces are verified; Autology works when Hermes is down | Acceptance criterion 9 (Hermes outage: MI test 9) | 4 d |

**R4 effort:** about 40–45 d plus per-connector work. Needs: Odoo sandbox access (owner).

## 6. R5: Operational experience

| ID | Story | Est. |
|---|---|---|
| WUI-1 | Workspace UI generated from the published use case: records, tasks, alerts, approvals, recommendations, execution states, "why" explanations; role-aware; accessible (WCAG 2.1 AA) | 10 d |
| WUI-2 | Approval and reconciliation inboxes in the Workspace UI (reviews, uncertain external calls) | 4 d |
| WUI-3 | Operational dashboards, notifications (incl. declined reviews, GAP-047) and agent monitoring | 5 d |
| WUI-4 | Use-case lifecycle visible to end users (which release is live; suspended/rollback states) | 2 d |

**R5 effort:** about 20–25 d.

## 7. R6: Product readiness

| ID | Story | Kind |
|---|---|---|
| RDY-1 | Maturity dashboards (platform and use case) and evidence that deployment enforcement holds | Repo |
| OPS-1 | Restore drill in CI with measured recovery time (GAP-033) | Repo |
| OPS-2 | Load test against agreed targets (GAP-024) | Repo + environment |
| OPS-3 | PostgreSQL store if D2 requires it | Repo |
| SEC-1 | External penetration test and code review; fixes | **External** |
| VAL-1 | Second customer on a different real system without core change (gate 95.2); a production pilot (95.5) | **External**, owner authorisation |
| REL-5 | Published release, upgrade from the previous release tested, support and incident process (GAP-049) | Repo + external |
| DOC-2 | Installation guide, docs-claims check in CI (GAP-043) | Repo |
| COM-1 | Commercial packaging after legal sign-off (D5) | External |

## 8. Order changes and why

| Change | Reason |
|---|---|
| Release objects, server-side gates and the readiness engine in R2, not R6 | Security and deployment controls must exist before Studio can publish anything; R6 measures and shows them |
| Oil & Gas and pharma blueprints in R2 | The R2 exit (architect on two industries) needs them |
| Template import commits into a draft release (R3 after R2's REL-1) | Nothing imported may become live without promotion |

## 9. Cross-release risks


| Risk | Mitigation |
|---|---|
| Model output that looks valid but is wrong (invented roles, thresholds) | Strict schema, provenance labels, nothing active before a reviewed promotion, contradiction gates |
| Spreadsheet attacks (zip bombs, external links, macros, formula injection) | XL-2's safe parse, quarantine and limits; exported cells escaped against formula injection |
| Studio drifting into business logic | Contract tests; the engine's suite runs with Studio stopped; review rule: no policy in the UI |
| Scope: Studio views grow faster than engine features | Studio stories start only when their API exists and is tested |
| Personal data in employee templates | Data minimisation, `pii` fields under field rules, no personal data in sample rows |
