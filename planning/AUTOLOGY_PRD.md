# Autology — Product Requirements Document (PRD)

| | |
|---|---|
| Version | 1.1 — 14 November 2026 (owner decisions D1, D4–D7 and Excel recorded) |
| Owner | Product owner (Autology) |
| Status | R1 delivered ([close-out](AUTOLOGY_R1_CLOSEOUT.md)); R1 safety and isolation gates met in the repository. R2 planned. No production deployment is authorised |
| Related | [current state](AUTOLOGY_CURRENT_STATE_AND_GAPS.md) · [architecture](AUTOLOGY_TARGET_ARCHITECTURE.md) · [requirements catalogue](AUTOLOGY_PRODUCT_REQUIREMENTS.md) · [security](AUTOLOGY_SECURITY_AND_TENANCY.md) · [readiness](AUTOLOGY_READINESS_AND_RELEASE_GATES.md) · [audit](../audit/README.md) |

## 1. Product vision

Autology lets a company describe how its business works (objects, rules, decisions, who approves what) and then
have AI agents carry out that work inside those rules: planning each case, acting in the company's systems, asking
the right person when a decision needs a human, and keeping a tamper-evident record of why everything happened.
It is sold to companies in any industry, on any ERP and with any AI model provider.

## 2. Problem

Enterprise AI pilots stall because (a) each team describes the business differently, (b) rules live in many
systems, (c) nobody can prove why the AI did something, and (d) an AI acting in real systems can do harm
(duplicate payments, unauthorised actions). Workflow tools fix the path but not the rules; chat assistants answer
but cannot be trusted to act.

## 3. Users (personas)

| Persona | Goal | Uses |
|---|---|---|
| **Platform operator** (Autology or customer IT) | Run the platform safely: deploy, back up, upgrade, monitor | CLI, Docker, metrics |
| **Workspace administrator** | Set up an organisation: members, use cases, connections, AI settings | Studio (planned), Console configuration |
| **Solution architect** (consultant or customer analyst) | Turn a business description into a working use case | Studio + AI Solution Architect (planned) |
| **Business user** (e.g. claims handler) | Get cases done, ask questions, start work | Workspace UI / Console |
| **Approver / reviewer** (e.g. claims manager) | Decide what needs a human, with the facts | Workspace UI / Console reviews |
| **Auditor / compliance** | Prove what happened and why | Audit API, reports, reporting database |
| **Integration engineer** | Connect ERP/CRM/EAM systems safely | Integration Hub (partly), pipelines, tools |

## 4. Goals and success metrics

| Goal | Metric | Target | Measured by |
|---|---|---|---|
| G1 Safe to act in real systems | Duplicate external executions; actions reported done without confirmation | 0 in the fault-injection suite | `tests/test_external_effects.py` (ACT stories) |
| G2 Rules can't be bypassed | Unauthorised actions or disclosures in the security regression suite | 0 | audit PoCs as tests (GOV stories) |
| G3 Customers are isolated | Cross-workspace access through any entry point | 0 | `tests/test_workspaces.py` + ISO stories |
| G4 Fast to set up a use case | Time from business brief to a validated draft use case | < 1 day for an MVO (target, to be measured in R2) | ARC stories, pilot logs |
| G5 Proven in the real world | Real end-to-end processes in pilot / production | ≥ 1 pilot (R3), ≥ 2 customers on different systems (R4) | pilot reports |
| G6 Verified maturity | Independent audit score | ≥ 80 after R1, ≥ 90 after R3, ≥ 95 after R4 | re-audit per release |

## 5. Scope

**In scope:** the headless engine and its public API; the workspace router; Studio and the Workspace UI as separate
applications; AI Solution Architect; Excel template factory; organisation and agent models; Integration Hub with
read-only connectors first, then safe writes; readiness scoring and release gates.

**Out of scope (for now):** a low-code application builder; our own data warehouse; real-time streaming; Hermes as
a dependency (optional adapter only); production writes to customer systems without explicit authorisation.

**Constraints:** engine stays domain-, ERP-, UI- and LLM-agnostic; every policy is enforced server-side; UIs only use
the versioned public API; no AI-generated permission, rule, credential or release is active without human approval;
existing behaviour and tests are preserved.

## 6. Releases

| Release | Theme | Exit criteria |
|---|---|---|
| **R1 — Safe pilot** | Close the audit's critical and high gaps; finish workspace isolation | Gate 80 of the audit: G1 = 0, G2 = 0, G3 = 0, licence decided |
| **R2 — Studio foundation** | API contract, releases and gates, AI Solution Architect, Excel factory, UIs separated | Acceptance tests 3, 4, 5, 7, 8 of the master instructions |
| **R3 — Integrations and runtime UI** | Capability registry, Odoo read-only then safe writes, org and agent models, generated Workspace UI, first pilot | Gate 90; one real process in pilot |
| **R4 — Enterprise and commercial** | Second customer on a different system, scale, restore drills, external pentest, blueprints | Gate 95 |

## 7. Epics and stories

Status: ☐ to do · ◐ in progress · ☑ done · ⛔ blocked (decision needed). Size: S ≤ 1 day, M 2–3 days, L 4–6 days.

### R1 — Safe pilot

| ID | Story | Size | Status |
|---|---|---|---|
| **GOV — Governance cannot be bypassed** | | | |
| GOV-1 | Manual automation firing respects self-review, the automation's condition and checkpoints (GAP-011) | S | ☑ |
| GOV-2 | Scenario comparisons never reveal fields the user may not read (GAP-012) | S | ☑ |
| GOV-3 | A user cannot make an agent act on records they may not see (GAP-013) | M | ☑ |
| GOV-4 | The whole run record is protected by the audit MAC (GAP-014) | M | ☑ |
| GOV-5 | Runs act with the intersection of the requester's permissions, the agent's permissions, the workspace and the rules; scheduled agents use an explicitly authorised, least-privilege service identity (D4) | M | ☑ |
| **MOD — The model cannot silently weaken itself** | | | |
| MOD-1 | Misspelled ontology keys and unknown types are rejected (GAP-016) | M | ☑ |
| MOD-2 | Missing linked records are unknown, never "valid by default" (GAP-017) | S | ☑ |
| MOD-3 | Tool outputs are type-checked; a bad stored row never stops a restart (GAP-010) | S | ☑ |
| MOD-4 | One writer per store: a second process cannot write a store a live server holds (GAP-018, found missing from R1 at close-out) | S | ☑ |
| **ACT — External actions are safe** | | | |
| ACT-1 | Every external call is recorded (intent) before it is made, and its result after (GAP-007) | M | ☑ |
| ACT-2 | Every external call carries a stable idempotency key (GAP-002) | S | ☑ |
| ACT-3 | An ambiguous failure is never blindly retried or sent to a fallback provider (GAP-001, 003) | M | ☑ |
| ACT-4 | Actions declare what confirms them; "accepted" is not "done" (GAP-006) | M | ☑ |
| ACT-5 | Recovery never re-executes; people reconcile uncertain actions (GAP-004, 005) | L | ☑ |
| ACT-6 | A run resumed after review re-checks the data it relies on (GAP-009) | M | ☑ |
| **ISO — Workspace isolation everywhere** | | | |
| ISO-1 | MCP clients reach one use case of their own workspace only | S | ☑ |
| ISO-2 | Each workspace's audit chains are signed with its own key | M | ☑ |
| ISO-3 | Company sign-in (OIDC) configured per workspace | M | ☑ |
| **LEG — Legal** | | | |
| LEG-1 | Proprietary licence notice and third-party licence inventory, checked in CI (D5) | S | ☑ |

### R2 — Studio foundation

Detailed plan, acceptance criteria and estimates: [AUTOLOGY_R2_PLAN.md](AUTOLOGY_R2_PLAN.md).

| ID | Story | Size | Status |
|---|---|---|---|
| **R2.0 — Prerequisites** | | | |
| API-1 | OpenAPI 3.1 contract generated from one route table, with contract tests | M | ☐ |
| API-2 | Versioned `/api/v1` paths and a deprecation policy | S | ☐ |
| ARC-0 | Split the service into services behind the route table (GAP-026) | L | ☐ |
| MIG-1 | Ordered migrations in one transaction (GAP-041) | S | ☐ |
| QA-1 | mypy, ruff and pip-audit in CI; pinned constraints (GAP-025, GAP-040) | S | ☐ |
| AI-1 | Provider-neutral model adapter contract, validated with at least two adapters (D7) | M | ☐ |
| UI-1 | Review inbox moved out of the engine process | S | ☐ |
| **A — Dynamic workspaces and releases** | | | |
| ADM-1 | Workspace administration API; grants active only after a second administrator approves | L | ☐ |
| ADM-2 | Changes apply without restart; revocation immediate | S | ☐ |
| REL-1 | Immutable use-case releases (Draft → Simulation → Pilot → Production), runs pinned to the fingerprint (GAP-020) | L | ☐ |
| REL-2 | Promotion refused server-side when a hard gate fails, whatever the score | M | ☐ |
| REL-3 | Use-case readiness scorecard with evidence and blockers | L | ☐ |
| REL-4 | Semantic diff covers every section (GAP-028) | S | ☐ |
| **B — AI Solution Architect** | | | |
| ARC-1 | Business brief → provisional draft ontology, validated, in a draft release | L | ☐ |
| ARC-2 | Provenance label on every model element, with lineage | M | ☐ |
| ARC-3 | Next questions generated from the model's gaps | M | ☐ |
| ARC-4 | Reconcile answers and documents; contradictions block promotion | M | ☐ |
| BP-1 | Oil & Gas upstream and pharma blueprints (moved from R4: the R2 exit needs them) | M | ☐ |
| SEC-A | Prompt-injection and data-boundary tests for briefs and documents (GAP-045) | S | ☐ |
| **C — Excel Template Factory** | | | |
| XL-1 | Template pack generated from the ontology and open questions | L | ☐ |
| XL-2 | Upload: quarantine, safe parse, validation, row-level errors | L | ☐ |
| XL-3 | Preview, confirmed transactional commit, provenance, rescoring | M | ☐ |
| XL-4 | First templates: employees and roles; assets and equipment | S | ☐ |
| **D — Studio (separate application)** | | | |
| STU-1 | Shell: sign-in, workspace selector, use-case catalogue on the public API | L | ☐ |
| STU-2 | Architect panel and provisional model view | L | ☐ |
| STU-3 | Questions and missing-evidence queue | S | ☐ |
| STU-4 | Template centre | M | ☐ |
| STU-5 | Readiness and blockers dashboard | S | ☐ |
| STU-6 | Releases, promotion approvals, rollback | S | ☐ |

### R3 — Integrations and runtime UI

| ID | Story | Size | Status |
|---|---|---|---|
| INT-1 | Capability registry with declared effects, scopes, idempotency, health | M | ☐ |
| INT-2 | Odoo 18 Enterprise read-only connector against a sandbox database (D6) | L | ☐ |
| INT-3 | Odoo safe writes on the sandbox only, after ACT-1–6 pass; production writes stay disabled (D6) | L | ☐ |
| ORG-1 | Human organisation model from templates or read-only HRIS sync | M | ☐ |
| ORG-2 | Access recommendations need approval; no self-granting | M | ☐ |
| AGF-1 | Versioned agent specifications with supervisors and approval | L | ☐ |
| WUI-1 | Workspace UI rendered from the published use case | L | ☐ |
| HRM-1 | Optional Hermes adapter (only after verifying its real interfaces) | M | ☐ |

### R4 — Enterprise and commercial

| ID | Story | Size | Status |
|---|---|---|---|
| OPS-1 | Restore drill in CI with measured recovery time | S | ☐ |
| OPS-2 | Load test with agreed targets | M | ☐ |
| OPS-3 | PostgreSQL store (if D2 requires it) | L | ☐ |
| SEC-1 | External penetration test and fixes | — | ☐ |

## 8. Story details (R1)

Each story is test-first: the audit's proof-of-concept (where one exists) becomes a failing test before the fix.

**GOV-1 Manual automation firing respects governance.** *As an approver, I want a person who triggers an
automation by hand to count as the run's starter, so that they cannot approve their own run.*
- Given Rita triggers an automation by hand, when its run needs a review she is a reviewer for, then her decision
  is refused (403), as if she had started the run herself.
- Given the automation's condition does not hold for the chosen record, then nothing runs and the firing says why.
- The `start_run` checkpoint applies to manual firings. Firings on records the caller cannot see are not returned
  with their details.

**GOV-2 Scenario comparisons respect field access.** *As a data owner, I want what-if comparisons to withhold
answers that depend on fields the user may not read, so that hidden values cannot be inferred.*
- Given a question depends on a field hidden from the user (data_access) or gated (checkpoint), when they compare
  a scenario, then that question's answers are withheld with a reason.
- Scenario edits to fields the user may not read are refused. The assistant's `what_if` applies provider redaction.

**GOV-3 Agents act only on records the requester may see.** *As a data owner, I want a run started by a person to
be limited to records that person may see, so that the agent cannot be used to reach hidden records.*
- Given Olivia cannot see order O-3, when she starts a run on a contract that includes O-3, then the run is refused
  (or excludes O-3 — per decision; default: refused with the reason).
- Automations keep acting with their configured service identity, recorded as such.

**GOV-4 The run record is covered by the audit MAC.** *As an auditor, I want any edit to a stored run — not only
its event chain — to be detected.*
- Editing `pending_review`, status, steps or ontology reference in the store makes verification fail and the run
  refuse to resume; chains copied onto another run id do not verify.

**MOD-1 Strict ontology schema.** *As a solution architect, I want a typo in the model to be an error, so that a
safety check is never silently lost.* Every documented key misspelled once fails to load with its path; unknown
attribute types fail.

**MOD-2 Missing records are unknown.** A case without a linked record treats that record's fields and state as
unknown: preconditions on it fail; computed effects that resolve to unknown block the action.

**MOD-3 Typed tool outputs.** A tool result whose values do not match the attribute types is refused and audited;
a store row that fails validation at start-up is quarantined with an alert instead of stopping the server.

**ACT-1 Intent log.** *As an operator, I want every external call recorded before it is made, so that after a crash
I can see exactly what might have happened.* Intent (run, step, action, idempotency key, inputs digest) is
committed to the store and chained in the audit before the call; the result after. After a crash at any point,
every call made is listed with its state.

**ACT-2 Idempotency key.** The same key for the same step across retries, resumes and restarts; sent as an
`Idempotency-Key` header and in the payload; available to Python tools.

**ACT-3 No blind retry.** Transport outcomes are classified: not sent, rejected, unknown. Only "not sent" and
explicit retryable rejections are retried automatically. An unknown outcome of an action not declared idempotent
puts the step in `uncertain`; no fallback provider is tried after an unknown outcome.

**ACT-4 Confirmation contract.** Actions may declare required confirmation fields and accepted statuses. A reply
without them (e.g. `202 queued`, `{}`) leaves the step `pending_confirmation`; only a confirmed reply applies the
action's effects.

**ACT-5 Recovery and reconciliation.** Resume, deferred retries and automation retries continue from the intent
log and never re-execute a step with an intent but no result. `GET /api/reconciliation` lists uncertain steps; an
authorised person resolves each (confirmed done with a reference, or confirmed not done), audited; the run then
continues.

**ACT-6 Re-validation after review.** On resume, records the remaining plan reads are re-read; if a fact used by a
review or precondition changed, the plan is re-evaluated and a changed reviewed fact requires a new review.

**ISO-1 MCP per workspace.** `autology mcp platform.json --use-case <id>` signs in with a member token and serves
only that member's use case in their workspace; other workspaces are unreachable.

**ISO-2 Audit key per workspace.** Each workspace's chains are keyed with a key derived from the platform key and
the workspace id; a chain from one workspace does not verify in another.

**ISO-3 OIDC per workspace.** Each workspace may configure its own issuer and mappings; a token from workspace A's
issuer is refused by workspace B.

## 9. Non-functional requirements

Security (OWASP ASVS L2 as the target for API and UIs); availability per deployment model (single node acceptable
for pilots with a proven restore); performance targets set with the first pilot (OPS-2); accessibility WCAG 2.1 AA
for UIs; Python 3.10+; no runtime dependencies in the engine core; every story keeps the suite green, adds tests,
and keeps coverage ≥ 95%.

## 10. Decisions

| ID | Decision (owner, 14 Nov 2026, unless marked open) | Consequence |
|---|---|---|
| D1 | Design for multi-tenancy while supporting dedicated, isolated customer deployments. Start with isolated pilot deployments | ADR-001 kept (a store per use case, router for shared hosting); pilots run as dedicated deployments; the platform router stays the multi-tenant path |
| D2 | *Open.* Proposal: SQLite for the isolated pilots (D1); PostgreSQL when a shared deployment needs it | OPS-3 (R4) |
| D3 | *Open.* Proposal: encrypted volumes per pilot deployment | Deployment guide |
| D4 | Agent permissions are the intersection of the initiating user's effective permissions, the agent's permissions, workspace boundaries and governance policies. Scheduled agents use explicitly authorised service identities with least privilege | GOV-3 (records) done; GOV-5 (roles and service identities) |
| D5 | Proprietary commercial distribution, subject to intellectual-property and third-party licence review | LEG-1 |
| D6 | Prepare an Odoo 18 Enterprise sandbox integration. No production ERP writes until the external action safety requirements pass | ACT-1–6 (R1) gate INT-2/INT-3 (R3), which target the sandbox only |
| D7 | Preserve provider independence; validate at least two model adapters | AI-1 (R2) |
| Excel | `openpyxl` approved as a dependency, subject to dependency security and licence checks | XL-1 (R2); checked in LEG-1's licence inventory |
| D8 | (audit) Actions without a declared side effect are non-idempotent | Applied in ACT-3: `side_effect` defaults to `non_idempotent` |
| D9–D11 | *Open*: Studio technology, model providers and data residency for briefs, second approver for small customers | See the [R2 plan](AUTOLOGY_R2_PLAN.md) §6 |

## 11. Working agreement

**Definition of ready:** story has acceptance criteria and, for a defect, a reproducing test or PoC.
**Definition of done:** acceptance criteria covered by automated tests; full suite green locally and in CI;
docs updated; status updated in this PRD and in the [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md); one
commit per story.
