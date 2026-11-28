# Autology — Product Requirements Document (PRD)

| | |
|---|---|
| Version | 1.2 — 14 November 2026 (six-release sequence; decisions moved to the register) |
| Owner | Product owner (Autology) |
| Status | R1 delivered ([close-out](AUTOLOGY_R1_COMPLETION_REPORT.md)); R1 safety and isolation gates met in the repository. R2 planned. No production deployment is authorised |
| Related | [current state](AUTOLOGY_CURRENT_STATE_VERIFICATION.md) · [architecture](AUTOLOGY_ARCHITECTURE_TARGET.md) · [requirements catalogue](AUTOLOGY_PRODUCT_REQUIREMENTS.md) · [security](AUTOLOGY_SECURITY_AND_TENANCY.md) · [readiness](AUTOLOGY_READINESS_AND_RELEASE_GATES.md) · [audit](../audit/README.md) |

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

Six releases, in the owner's sequence of 14 November: **R1** engineering foundation (done), **R2** Studio
foundation, **R3** structured enterprise onboarding, **R4** Agent Factory and integrations, **R5** operational
experience, **R6** product readiness. Scope, stories, estimates, exit criteria and dependencies:
[release roadmap](AUTOLOGY_RELEASE_ROADMAP.md) (authoritative for R2–R6).

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

### R2 – R6

See the [release roadmap](AUTOLOGY_RELEASE_ROADMAP.md).

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

All owner decisions (approved, pending, applied defaults) are in the
[decision register](AUTOLOGY_DECISION_REGISTER.md).

## 11. Working agreement

**Definition of ready:** story has acceptance criteria and, for a defect, a reproducing test or PoC.
**Definition of done:** acceptance criteria covered by automated tests; full suite green locally and in CI;
docs updated; status updated in this PRD and in the [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md); one
commit per story.
