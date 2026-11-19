# Autology — release roadmap

*14 November 2026 at `dfe8b3f`. Follows the owner's six-release sequence of 14 November. The table at the end
lists three deliberate dependency-order choices, each justified by repository evidence. Estimates are
engineer-days (d) for one experienced engineer with AI assistance, ±30 %, excluding external reviews and
customer coordination. **No production deployment is authorised** in any release until the owner authorises it.*

## 1. Overview

| Release | Theme | Exit criteria (master prompt §13 numbering) | Status |
|---|---|---|---|
| **R1** | Engineering foundation | Gate 80 repository criteria; G1 = G2 = G3 = 0; criteria 1, 2, 10 | **Done** ([report](AUTOLOGY_R1_COMPLETION_REPORT.md)); legal sign-off and independent re-verification open |
| **R2** | Studio foundation | 1 (versioned contract), 3 (readiness per use case), 4, 5, 11 (server-side gates) | **In progress**: done and open items per story in §3; exit requirements in §3.5 |
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

Open from R1: legal sign-off (counsel); independent re-verification. GAP-009 (atomic write-back) and GAP-018
(record revisions and seals, MCP through the platform) fixed on 14 Nov.

## 3. R2: Studio foundation

Goal: an administrator manages workspaces and use cases. The architecture is versioned as releases. Studio edits
the model visually on the engine's own schema. The AI Solution Architect proposes a provisional ontology and asks
questions derived from what is missing. Promotion is blocked server-side when a gate fails.

**First slice started (14 Nov, owner's instruction):** Studio workspace shell, use-case management from
templates, Draft → Simulation → Pilot stages with server-side checks; no ERP writes, no deployment. It covers part
of ADM-1, REL-1, REL-2 and STU-1, ahead of the prerequisites below (an owner-requested order change). Criteria,
evidence and what remains: [R2 slice report](AUTOLOGY_R2_SLICE_REPORT.md).

**Owner's review of the slice (14 Nov):** continue R2 in controlled increments; before the AI Solution Architect,
finish execution gates, release governance, workspace administration and the API contract. Increment 1
(execution gates) and the order of the next ones: [increment 1 report](AUTOLOGY_R2_INCREMENT1_EXECUTION_GATES.md) §6.

### 3.1 Prerequisites

| ID | Story | Why first | Acceptance | Est. |
|---|---|---|---|---|
| API-1 | OpenAPI 3.1 contract generated from one route table, with contract tests | Studio and third parties build against it | Every route in the table; a test fails if a route and the contract differ | 3 d — **partly done 14 Nov**: route table and contract tests both ways; **15 Nov**: typed schemas for the core and Studio routes (others generic) |
| API-2 | `/api/v1` paths, deprecation policy, version header | UIs upgrade independently | Old paths answer with a deprecation header for one release | 1 d — **done 15 Nov** (`/api/v1`, `/platform/v1`, `docs/api-versioning.md`); legacy paths deprecated, no removal date (owner decision) |
| ARC-0 | Split `AutologyService` into services behind the route table (GAP-026) | The new services (admin, releases, architect, imports) would otherwise grow the god object | No behaviour change: the full suite passes unchanged | 5–8 d — **first step done 15 Nov:** notifications and ingestion extracted behind unchanged engine methods, one authorisation path, size ratchet (2,323 → 2,142 lines). **second step done 15 Nov:** run lifecycle and review workflows extracted (class now 1,730 lines). Open: reconciliation, scenarios, model design, the assistant, the dispatcher's route table, `_validate` |
| MIG-1 | Ordered migrations in one transaction (GAP-041) | R2 adds several tables | An interrupted migration leaves the old schema intact | 1 d — **done 15 Nov:** versioned, ordered, idempotent steps; the whole upgrade is one transaction; incompatible states refused; additive only (no downgrade). Engine store only |
| QA-1 | mypy, ruff and pip-audit in CI (GAP-025); pinned constraints (GAP-040) | Larger surface, more contributors | CI fails on new type errors or known High vulnerabilities | 2–3 d — **done 15 Nov:** CI job `quality` (ruff bug rules, mypy ratchet at 201, pip-audit), `npm audit` in the studio job, actions pinned by SHA, base image by digest |
| AI-1 | Provider-neutral model adapter contract, validated with two adapters (D7) | The architect needs a model | The same eval suite passes with both adapters; adapter errors never escape (GAP-029). Real-provider runs need API keys from the owner | 3 d + API cost — **foundation done 15 Nov:** contract, gateway (workspace configuration, data classes, deadline, retries, validation, accounting, logging), two adapters verified with test doubles and a local mock endpoint, bridge to the agents' reasoner, AI Architect proposal contract. Open: the eval suite with two *real* providers (GAP-052; D7/D10), building agents on the gateway from configuration, exposure through the API |
| UI-1 | Review inbox moved out of the engine process | Completes the UI separation | The engine serves only the API | 1 d |

### 3.2 Workspace and use-case management, releases and gates (engine)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| ADM-1 | Workspace administration API: create workspaces and use cases; add or remove members; propose grants | Changes are audited; a grant becomes active only when a second authorised administrator approves it, and never the proposer (master §6); cross-workspace attempts get 404 | 6 d — **done 15 Nov (ADM-1a):** members (person or service), token replacement and use-case grants through `/platform/v1/workspaces/{ws}/members|grants`; a grant needs an independent approval (never the proposer, never the grantee, never a service); revocation immediate; append-only chained log; fail closed if it does not verify. **Since done (15 Nov):** the Studio Access screen (R2 sprint D). Open: workspace administrators and roles stay in configuration |
| ADM-2 | Changes apply without restarting (hot reload of members, grants, use cases) | A new member can sign in within one request of approval; revoking access takes effect immediately | 2 d — **done 15 Nov:** membership changes reach every engine at the next request; `POST .../use-cases/{uc}/reload` rebuilds an engine from its files after a throwaway load (not an activation) |
| REL-1 | Immutable use-case releases: Draft → Simulation → Pilot → Production, plus Suspended and Rollback; runs pinned to the release fingerprint (GAP-020) | A release is a content-addressed snapshot; rollback restores the previous one; a run started on release N continues on N | 6 d — **REL-1a done 15 Nov** (immutable content-addressed releases, independent approval bound to the fingerprint, activation of what runs only, drift stops execution, rollback recorded, runs and decisions bound to their configuration; pilot needs an approved active release). **Since done (15 Nov):** activation and rollback without restart (coordinated activation, R2 sprint C), releases created from Studio drafts and the Studio release screen (STU-6). Open: the Suspended state. Policy chosen: a run started on N **stops** on another configuration (a person restarts it), it is never migrated silently |
| REL-2 | Server-side hard gates on promotion | The gates of the instructions §10 (approval ownership, separation of duties, cross-tenant access, untested critical connector, critical vulnerability, no authoritative confirmation, no recovery evidence, audit gaps, sector controls) block promotion whatever the score; acceptance test 8 | 3 d — **done 15 Nov for what the repository can verify:** mandatory conditions per target stage, evaluated at the promotion; a missing proof blocks. Open: sector controls, critical-vulnerability and cross-tenant gates fed by external evidence |
| REL-3 | Use-case readiness scorecard: six dimensions, each metric with formula, denominator, target, evidence source, confidence, reviewer and refresh trigger; one scoring authority with `scoring.py` | Material changes invalidate the evidence they touch; acceptance test 7 | 6 d — **done 15 Nov (first version):** six dimensions with calculation, evidence, missing evidence, blockers and corrective actions; proposed weights (D26, not ratified). Open: reviewer and refresh trigger per metric, invalidation of evidence by material changes beyond the configuration fingerprint |
| REL-4 | Semantic diff covers every section (GAP-028) | Release diffs show impact rules, scheduling, questions, settings | 2 d |

### 3.3 AI Solution Architect and dynamic discovery (engine service, through AI-1)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| ARC-1 | Business brief → draft ontology in a draft release, validated by the strict schema (MOD-1) | Invalid model output is repaired or refused, never stored; every element is provisional; nothing reaches live data | 6 d — **path done 15 Nov with a sandbox test double:** description → stored proposal revision → questions and answers → engine-validated provisional items → recorded review; nothing applied. Open: a real provider (D7/D10, GAP-052), repair of invalid output, documents |
| ARC-2 | Provenance label on every element (`AI proposed`, `user supplied`, `document extracted`, `system synchronized`, `human verified`) and change lineage | A label changes only through an audited action; `human verified` needs a person | 3 d |
| ARC-3 | Next questions from the model's gaps: a deterministic gap analysis (rules on fields that have no source, actions without tools, entities without data, missing approvers or reviewer roles) ranked by risk and dependency, worded by the model | Each question names the fact or rule it resolves and the evidence expected; acceptance test 4 | 4 d |
| ARC-4 | Reconcile answers and documents: contradictions highlighted; safety-relevant ambiguity must be resolved before promotion (a REL-2 gate) | A contradiction blocks promotion until a person resolves it | 4 d |
| BP-1 | Oil & Gas upstream (maintenance work orders) and pharma (deviation / CAPA) blueprints as optional, versioned templates with no customer data | Acceptance test 3; brought forward because the R2 exit needs it | 4 d |
| SEC-A | Prompt-injection and data-boundary tests for briefs and documents (GAP-045) | Instructions inside a brief or document never become rules, grants or actions | 2 d — **done 15 Nov** for what exists (agent decisions, ingestion, notifications, model proposals): GAP-045, GAP-037, GAP-035 fixed; the tests use a model that obeys what it reads. Document intake (R3) must add its own cases |

### 3.4 Studio (a separate application)

| ID | Story | Acceptance | Est. |
|---|---|---|---|
| STU-1 | Shell: sign-in, workspace selector, use-case catalogue, built from the OpenAPI client (**done 14 Nov in Next.js, D9**, except the generated client; see [Studio spec](AUTOLOGY_STUDIO_UI_UX_SPEC.md)) | Builds, runs and deploys on its own; the engine's suite passes with Studio stopped; a user without admin rights gets nothing extra by changing routes | 6 d |
| STU-2 | Architect panel and provisional model view (entities, relations, actions, rules, provenance), editing through the API | Edits are validated server-side; provisional elements are marked as such | 8 d |
| STU-3 | Questions and missing-evidence queue | Follows ARC-3 | 3 d |
| STU-5 | Readiness and blockers dashboard | Read-only view of REL-3 | 3 d |
| STU-6 | Release history, promotion requests and approvals, rollback | Promotion goes through REL-2; the approver is not the requester | 3 d — **done 15 Nov:** Releases tab (propose, approve by another person, revoke, activate, restore a release's model), publish a saved draft as the use case's model (`publish-draft`), 6 browser checks |

**R2 effort:** about 95–110 d. **R2 sequence:**
1. Prerequisites.
2. ADM, REL-1, REL-2, REL-4.
3. AI-1.
4. ARC, BP-1, SEC-A, REL-3.
5. Studio, which can start as soon as the API contract is fixed.
6. The exit tests.

### 3.5 R2 exit requirements (updated 19 November 2026, governed-operations and architect-reliability sprint)

| Requirement | State | What is missing |
|---|---|---|
| Versioned API contract (criterion 1) | Met at repository level | Typed schemas for the routes still described generically |
| Server-side gates on stages and execution (criterion 11) | Met for Draft, Simulation and Pilot; Production is always refused | REL-2 hard gates on promotion; Production stays disabled until formally authorised |
| Releases with independent approval, activation and rollback | Met (REL-1a, STU-6, activation without restart). Since the activation sprint a release also carries the agents and simulated tools configured in Studio, names its parts with a fingerprint each, and is refused at activation when it could not execute | Suspended state; REL-4 full semantic diff |
| Workspace and member administration | Met (ADM-1, ADM-2, Studio Access screen) | Roles and workspace administrators in configuration only; D24 (`operate`) awaits the owner |
| Security prerequisites (GAP-030, SEC-A) | Met at repository level | Independent security review; D23 confirmation |
| Migrations and recovery (MIG-1, OPS-1) | Met at repository level | Platform registries outside the migration mechanism; production-sized restore drill. Since the architect sprint a recovery rehearsal can be run and recorded per workspace, and readiness reports it for the configuration it covered |
| Architecture (ARC-0) | Partial: notifications, ingestion, runs, reviews and the architect are services behind the engine (class 2,323 → 1,721 lines) | Reconciliation, scenarios, model design, assistant, dispatcher |
| Readiness per use case (criterion 3, REL-2, REL-3) | Met at repository level: for what runs, for the saved draft and for a release that is not active, each named with its configuration, with the differences against what runs | Owner approval of weights and mandatory sets (D26); recorded recovery evidence per use case; sector controls |
| AI Solution Architect (criteria 4, 5; ARC-1 to ARC-4) | Path demonstrated end to end in Studio with a sandbox test double: description, questions, stored revisions, visual review, engine validation, agents and simulated tools, governed release, **stored simulation runs**, readiness of draft and active (activation sprint; reference demonstration in [solution-demo](../docs/solution-demo.md)) | **A real provider under D7/D10 (GAP-052): everything around it is now built and tested with test doubles (workspace policy, spending ledger, contract for unfamiliar briefs, evaluation suite with thresholds); 17 Nov: the evaluation was run with a real provider (authorisation `D7D10-2026-11-16-EVAL`) and did not meet its thresholds; an unfamiliar brief was taken through Studio to a governed release and stored simulation runs ([report](AUTOLOGY_FIRST_REAL_CLAUDE_EVALUATION_REPORT.md)). Open: thresholds met on a stable system (GAP-082, GAP-083, D30), a second provider**; questions worded by a model; documents as input; BP-1 blueprints for the two named industries; anything outside the two templates' vocabulary |
| One engine and one Studio for unrelated domains (cross-domain validation, 17 Nov) | Shown on two synthetic demonstrators (crisis management, network intelligence): the same journey through the same routes, no domain vocabulary in the engine or Studio, separate workspaces, people, releases, runs and audit trails; an application contract with a reference client ([report](AUTOLOGY_CROSS_DOMAIN_ARCHITECTURE_VALIDATION_REPORT.md)) | **The models come from engineer-written templates through the sandbox test double: onboarding an unfamiliar domain with a language model is not shown (GAP-098, D30 h).** Expert review of both domains; a real application (D24, D34); several agents on one case (D32) |
| A business application rendered from a released model (Application Builder, 17 Nov) | Shown on three synthetic domains, one without a template: a closed manifest generated deterministically, arranged in Studio, validated and bound to a configuration by the Engine, rendered by a separate runtime; the Engine keeps every decision ([report](AUTOLOGY_APPLICATION_BUILDER_MVP_REPORT.md)) | **Not an R2 exit criterion and not operational.** A design is not part of a release (GAP-101); records cannot be created without the unrestricted permission (D24 proposal); no registry, no events (D34); the model it starts from is still not produced by an accepted AI Architect (GAP-098) |
| Stabilisation of the Application Builder (17 Nov) | The Engine states what a design is in six states, two of them "not supported" (approved release artifact, production); integrity verified by direct requests; an application says what it runs on; D24, D34 and D35 each have a reviewable proposal with an inactive, tested prototype; an end-to-end evaluation harness reports the architect, the builder and the Engine apart, without a provider call | The owner's decisions D24, D34, D35; a real-provider run of the chain on the reserved briefs (not authorised); independent domain review. **R2 is not closed** |
| Reviewable architect proposals and governed-operations readiness (19 Nov) | A proposal is reviewed element by element: inferred elements are confirmed only by a person's explicit, persisted decision; a rejected element stays rejected when proposed again; the Engine refuses a draft that takes an unconfirmed element from the proposal it names. The chain evaluation compares three treatments of inferred elements on kept evidence. The D24 write contract, the D34 release structure and the D35 contracts exist as inactive, tested prototypes or designs | The architect's own reliability with a real provider (unchanged, below thresholds); any domain-expert review; the owner's decisions D24, D30, D34, D35, D36. **R2 is not closed** |
| Agents and tools configured without files (activation sprint) | Met for simulated tools: configured in Studio, validated and compiled by the engine, released with the model | Connectors and sandbox tools from Studio (R4, Agent Factory); editing of decision-table writes; several agents sharing work is possible but not demonstrated |

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
| OPS-1 | Restore drill in CI with measured recovery time (GAP-033) — **brought forward, done 15 Nov** (R2 sprint C: platform backup, verification and restore, drill in the suite). Open: a drill against production-sized data | Repo |
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


## 10. Sequence after the master directive V2 (15 November 2026)

The owner's order is kept where the repository's dependencies allow it:

| # | Item | Status | Hard dependency found in the repository |
|---|---|---|---|
| 1 | Owner decisions D11, D7/D10, D19 recorded | Done | — |
| 2 | H-1 (F-01, F-02) | Done, CI run 67 | — |
| 3 | REL-1a releases | Done at repository level (see log) | — |
| 4 | Architecture Part B (plugins, knowledge hub, composable intelligence, decision/action, autonomy) | Documented | — |
| 5 | Workspace administration (ADM-1, ADM-2) | Done 15 Nov (owner: "all approved"); members screen done 15 Nov (R2 sprint D) | REL-1a (done); D11 details per workspace; hot reload is shared with release activation |
| 6 | Real AI Solution Architect (AI-1, ARC-1) | **AI-1, SEC-A and the ARC-1 path done 15 Nov with test doubles** (stored proposals, guided questions, review, draft simulation, Studio onboarding); the *real* architect needs authorisation **16 Nov (Claude activation sprint):** the model is pinned in the use case and the release, the Anthropic adapter is validated against the provider's SDK offline (four latent defects found and fixed, GAP-068 to GAP-071), a dedicated evaluation deployment is generated from the owner's decision; no call to a provider on that day. **17 Nov (first real model run):** canary, five-case evaluation twice and an unfamiliar brief in Studio with `claude-opus-5-5` on synthetic data, 4.42 USD; **thresholds not met**; twelve defects found, eight fixed ([report](AUTOLOGY_FIRST_REAL_CLAUDE_EVALUATION_REPORT.md)) **17 Nov (stabilisation sprint):** the spending ledger outlives a deployment (GAP-085); stored proposals are reopened, compared and traced to drafts and releases in Studio (GAP-080); elements keep canonical provenance (GAP-081); refusals of answers are classified and a decision record compares four options (GAP-082, undecided); evaluation protocol version 2 is proposed beside version 1 (GAP-083, undecided); workflow consistency findings; a record editor in Studio. No call to a provider in that sprint ([report](AUTOLOGY_AI_ARCHITECT_RELIABILITY_REPORT.md)) | Owner decisions D30 (f)–(h), D31, D32, then **one** evaluation run on a stable system (not run: it needs the owner's approval); a second provider (D7); two independent domain reviewers; GAP-052 partly fixed |
| 7 | Readiness assessment (REL-3) | Needs authorisation | REL-1a (a score belongs to a release); owner validation of weights |
| 8 | Excel Template Factory and document intake (R3) | Needs authorisation | F-01 origin rules for any fetched source; provenance model (B3) |
| 9 | Multi-provider AI and hybrid retrieval | Needs authorisation | AI-1; document intake |
| 10 | Plugin Runtime and first validated plugins | Needs authorisation | Isolation choice; REL-1a (plugins in the release); ADM-1; D13 |
| 11 | Decision & Action Designer | Needs authorisation | B5 model design; criticality model (B6) |
| 12 | Advanced autonomous agents, Integration Hub | Needs authorisation | Plugin runtime or connector contract; D6/D13/D15 |
| 13 | Independent Workspace UI and production operations | Needs authorisation | PROD, D2, D3, restore drills (GAP-033), independent security review |
| 14 | Multi-tenant IAM (D22): **IAM-1 tenant and IAM-3 admin/data separation done 15 Nov**; **GAP-030 done 15 Nov (R2 security sprint A)**; then IAM-2 platform operators, IAM-4 portal users, IAM-5 public visitors, IAM-6 agent and plugin identities | IAM-2/4/5/6 need authorisation and D22b–e | Extends the existing identity system ([gap analysis](AUTOLOGY_IAM_TARGET.md)); IAM-4/5 after GAP-030 (rate limiting, token expiry); IAM-6 with the plugin runtime |
