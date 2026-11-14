# Autology — R2 increment 1: execution gates

*14 November 2026 · branch `claude/autology-ontology-agent-4ajjer`. Asked by the owner after the first R2 slice:
"les étapes sont encore essentiellement administratives … il faut distinguer les simulations autorisées des
actions à effet externe et appliquer les restrictions à tous les points d'entrée : API, MCP, agents autonomes et
tâches planifiées." No ERP write, no deployment, no production authorisation.*

## 1. Rule

A use case's lifecycle stage now governs what its engine executes. The engine reads the stage at every check (no
cache), so a move applies at once, also when it is made by another process.

| Stage | Runs start or continue | Tools the runs may call |
|---|---|---|
| Draft | **No** | none |
| Simulation | Yes | `simulated` only (decision tables, declared stubs) |
| Pilot | Yes | `simulated` and `sandbox` |
| Production | refused as a stage (PROD) | — |

* `production` tools are called by **no** stage (decision D15 pending).
* A **stale** stage (the configuration changed after it was granted) or a history that does not verify counts as
  **draft**. If the stage cannot be read, the engine fails closed (draft).
* Every tool declares an `environment`. `table` tools are always `simulated`; `python` and `http` tools and
  registries default to `production` (anything that can reach outside is treated as real unless the operator
  declares otherwise).
* A step whose every tool is refused is **not sent**: no journal intent is written, the run escalates with
  "nothing was sent", and the audit chain records `step.blocked`. If an allowed tool exists for the same
  capability (for example a simulated stub), it is used instead.

## 2. Entry points covered

| Entry point | Where the gate is | Behaviour when runs are not allowed | Test |
|---|---|---|---|
| REST `POST /runs` | `start_run` | 409 | `DraftTests.test_no_run_starts_or_continues_in_draft_through_any_entry_point` |
| Assistant (chat) and MCP `start_run` | they only record a proposal; confirming calls `start_run` | 409; the proposal stays pending | same test |
| REST `POST /runs/{id}/resume` | `resume_run` | 409 | `…test_a_run_waiting_for_review_does_not_continue_once_back_in_draft` |
| Review decision | `decide`, before the decision is recorded | 409; the review stays pending | same test |
| Manual automation firing | `run_automation` and `_fire` | 409 / skipped | first test |
| Scheduled automations | `tick` | not evaluated; `paused` reported | `…test_scheduled_work_waits_while_in_draft` |
| Deferred retries | `tick` | not resumed | same |
| Recovery after a crash or reconciliation | `recover` | nothing continues | same |
| Every tool call of every agent and delegate | `WorkAgent._execute` (the only place tools are called in the service) | refused tools skipped; none left → not sent, escalation | `SimulationTests`, `SimulationWithoutStubTests`, `PilotTests` |

Outside the platform, `autology run` (CLI) and the offline evaluation harness run agents on a standalone
configuration; a standalone engine is not governed by stages (`DeclarationTests.test_a_standalone_engine_is_not_governed_by_stages`).
Governed deployments use the platform (ADR-001: pilots run as one workspace per deployment).

## 3. Acceptance criteria

| # | Criterion | Tests (`tests/test_r2_execution_gates.py`) | Status |
|---|---|---|---|
| G1 | In draft no run starts or continues through any entry point in §2; reads, ingestion and proposals stay possible | `DraftTests` (3) | Implemented and verified |
| G2 | A stage change applies at once, also from another process | `DraftTests.test_a_stage_change_from_another_process_applies_at_once`, `…waiting_for_review…` | Implemented and verified |
| G3 | In simulation no sandbox or production system is reached; a blocked step is not sent, escalates and is audited | `SimulationTests`, `SimulationWithoutStubTests` | Implemented and verified (with instrumented production and sandbox systems that count real calls: 0) |
| G4 | In pilot the sandbox is reached and production never | `PilotTests` | Implemented and verified |
| G5 | Stale stage, edited history and unreadable stage all count as draft | `EffectiveStageTests` (3) | Implemented and verified |
| G6 | Environments are declared and checked at load; a standalone engine is not governed | `DeclarationTests` (2) | Implemented and verified |

Changed existing tests (they ran runs in draft, which is now refused): `tests/test_workspaces.py` moves its use
cases to simulation first; `tests/test_r2_use_case_lifecycle.py` proves "a run before simulation does not count"
by leaving and re-entering simulation, since a run in draft is now impossible.

## 4. Known limits (not hidden)

| Limit | Consequence | Where it is handled |
|---|---|---|
| A tool's environment is **declared** by the operator, not verified (an `http` tool marked `sandbox` could point at a production system) | The gate is as good as the declaration; only operator-approved templates can be used by workspaces | Integration Hub registry with verified endpoints (R4) |
| HTTP **approvers** and **notifications** are not gated by stage | A review request or notification can leave the platform in any stage | Next increments (gate approvers like tools) |
| **Pipelines** may read external sources in any stage | Draft and simulation may ingest real data (a read, not an effect) | Owner decision on data use in simulation (D10/D16) |
| Releases are not immutable yet: the stage is pinned to the ontology fingerprint only, not to the whole configuration (tools, rules files) | A change to `tools.json` alone does not make the stage stale | Increment 2 (release governance) |
| MCP served from a platform file cannot run next to the platform server (it is a second writer) | Safe, but MCP and server cannot serve one use case at once | GAP-018 C2 ([clarification](AUTOLOGY_PARTIAL_GAPS_CLARIFICATION.md)) |

## 5. Applied defaults awaiting the owner's confirmation

| ID | Default | Why |
|---|---|---|
| D17 | Pilot may call `sandbox` systems; `production` systems are called by no stage | Pilots need a real integration test; D6 allows an Odoo sandbox; D15 keeps production writes off |
| D18 | Simulation may read real data through pipelines | Designing a use case needs representative data; no effect leaves the platform through tools |

## 6. Next increments (proposed order; each with tests, CI and a report before the next starts)

| Increment | Content | Acceptance (measurable) | Owner input needed |
|---|---|---|---|
| 1b | GAP-009 all-or-nothing write-back | C1–C3 of the clarification | none |
| 2 | **Release governance**: a release is an immutable, content-addressed snapshot of the whole configuration (all files); the engine runs only the active release's snapshot; submit → independent approval (approver ≠ submitter, same workspace) → promotion; rollback to the previous release; every step in the keyed history; runs pinned to their release (GAP-020) | Editing any configuration file after approval changes nothing that runs; a submitter cannot approve; rollback restores the previous fingerprint; acceptance test 8 | **D11**: who approves when a workspace has a single administrator |
| 3 | **Workspace administration** (ADM-1): members, grants, delegations (`run_as`), revocations through the API and Studio; a grant becomes active only after a second administrator approves; no cross-workspace effect | Revocation applies at the next request; no grant crosses workspaces (isolation matrix extended); no self-granting | D11 (same) and D13 (secret store) for connector credentials |
| 4 | **API contract** (API-1/2): OpenAPI 3.1 generated from one route table, `/api/v1` and `/platform/v1`, contract tests; Studio's client generated from it | A route that differs from the contract fails CI; Studio uses only contract routes | D9 (Studio technology) only for the generated client's language |

Milestone asked by the owner: *an administrator designs a use case, simulates it and submits it for validation,
without any agent or connector bypassing its maturity state.* Increment 1 provides the "no bypass" part;
increment 2 provides "submit for validation"; the milestone is demonstrated end to end at the end of increment 2.

## 7. Evidence

| Item | Value |
|---|---|
| Full suite (local, before the push) | **604 tests, OK** (2 PostgreSQL tests skipped locally; CI runs them); 592 before, +12 |
| Coverage (engine package) | **96.5 % lines** (10,317 statements, 364 missed) |
| Commit and CI | [`40f7780`](https://github.com/edlwiseltd/ontology/commit/40f7780) → [run 50](https://github.com/edlwiseltd/ontology/actions/runs/43620645339): **success** (tests and coverage gate on Python 3.10 and 3.13 with PostgreSQL, wheel, Docker smoke test) |
