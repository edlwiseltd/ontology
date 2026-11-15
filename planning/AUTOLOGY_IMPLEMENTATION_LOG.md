# Autology — implementation log

## 14 November 2026 — Phase 0 and Phase 1 (workspace foundation)

**Inputs read.** The repository at `5400ad8`, the audit of 13 November (`audit/`), the master instructions of
14 November. The historical PDF was compared through the audit and [current state](AUTOLOGY_CURRENT_STATE_VERIFICATION.md).

**Changed.**

| Commit | Change |
|---|---|
| `4509b97` | `ApiExchange`: the REST dispatcher no longer depends on the HTTP server; the engine refuses negative or malformed `Content-Length` (411, audit GAP-015) and answers unsupported methods with JSON 405 |
| (this commit) | `autology/platform.py`: workspaces, members, use cases, router `/w/<ws>/u/<uc>/api`, `/platform/me`, platform access log; dedicated store per use case and secrets file per workspace; `secrets_file` setting in the engine; Console accepts a use-case base URL; `autology platform` command; `examples/platform`; `docs/workspaces.md`; seven planning documents |

**Tests run.**

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -t .` | 449 tests, OK (2 PostgreSQL tests skipped locally because no database was running; CI runs them) |
| `python -m unittest tests.test_workspaces` | 11 tests OK: membership, router health, methods and body limits, reporting target kept inside the use case, identical 404s, data/run/review/audit/secrets isolation, per-use-case users, Console through the router, token uniqueness, invalid definitions |
| `python -m unittest tests.test_api_exchange` | 3 tests OK |

**Known limitations.** Members and use cases are loaded from `platform.json` at start (no admin API yet). MCP and
company sign-in are single-engine only. One audit key signs every workspace's chains. Each use case's engine holds
its graph in memory. The review inbox is still served by the single-engine server (not by the platform).

**Next increment.** P0-5 (MCP and OIDC per workspace, per-workspace audit keys) and P1-1 (OpenAPI contract), then
P0-1 (external action safety), which gates every connector write.

## 14 November 2026 — stories

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| GOV-1 (GAP-011) | Firing an automation by hand: the caller is recorded as the run's starter (self-review refused), the automation's condition must hold (else `skipped`), the `start_run` checkpoint applies, and only records the caller may see are fired | `tests/test_gov1_manual_firing.py` (4, written failing first: 3 failed before the fix); suite 453 OK | `POST /api/automations/{name}/run` with an instance no longer forces a run when the condition is false; `tests/test_automation.py` updated accordingly |
| GOV-2 (GAP-012) | Scenario comparisons withhold answers to questions that read a field the user may not read, or a checkpoint-gated field (for admins too); scenario edits to unreadable fields are refused; the assistant's `what_if` withholds answers over fields not sent to the model provider. One helper (`question_refs`) now decides which fields a question reads, for direct answers, comparisons and the assistant | `tests/test_gov2_scenario_fields.py` (5, written failing first: 4 failed before the fix); suite 458 OK | Admins' comparisons now withhold questions over gated fields; before, they were answered without a justification |
| GOV-3 (GAP-013) | A person may start a run from a case template only if they may see every record in its case (403 otherwise, naming no hidden record); manual automation firings follow the same rule (`skipped`); resuming a run the caller may not see is 404; automations firing on their own keep their service identity. Decision D4 taken with the PRD default (refuse, not narrow the case) | `tests/test_gov3_requester_scope.py` (6, written failing first: 4 failed before the fix); suite 464 OK | Example user `lena` gains `run`, because ops-only `olivia` can no longer start runs on `K-1`, whose case includes EU order O-3. Six existing tests encoded the old behaviour and were updated: `test_automation` (2), `test_chat` (2), `test_scenarios` (1), `test_governance_extras` (1) |
| GOV-4 (GAP-014) | Every stored run row is sealed (HMAC under the audit key) over its record, status, agent, starter and chain head, bound to the run id. `verify_audit` checks the seal, so `unverified_runs` and `/api/health` report edits; a run whose seal fails is escalated to `security` instead of resuming. Store schema 11 (new `runs.seal` column; existing records sealed on first open) | `tests/test_gov4_run_record_seal.py` (8, written failing first: 5 failed before the fix, plus an upgrade test from schema 10, including the audit's `pending_review.action` PoC and a chain copied onto another run id); suite 472 OK with and without an audit key | Store schema 10 → 11 (`tests/test_delivery.py` expected 10). Chain entry digests are unchanged, so existing chains still verify |
| MOD-1 (GAP-016) | Strict ontology schema: unknown keys at every level (document, settings, entities, attributes, interfaces, relationships, actions, outcomes, on_failure, goals, functions, rules by type, questions, impact rules, case templates, scheduling) and unknown attribute types are errors naming the path and the closest valid key; each imported module is checked under its file name; `x-` keys are free; `docs/ontology.schema.json` is generated from the same table | `tests/test_mod1_strict_schema.py` (8: the audit's `requries` case, every key of every example ontology misspelled once — more than 400 cases — unknown types, rule keys by type, modules, extension keys, published schema); suite 480 OK | Ontologies with typos or unknown types no longer load. All six example ontologies load unchanged. `tests/test_sdk.py` no longer uses an unknown attribute type |
| MOD-2 (GAP-017) | A record missing from a case is unknown (status and fields `None`) unless its entity declares `"when_absent": "initial"` (records the process creates); an action whose computed effect would be unknown is not applicable; when no path is left, the escalation names the missing record or the unknown value | `tests/test_mod2_missing_records.py` (7, written failing first: 5 failed before the fix; includes the audit's claim-without-policy case); suite 487 OK | `examples/care_referral` marks `CarePlan` as created by the process; the onboarding test cases now include the signatory `Contact` they had omitted. A claim without its policy is no longer approved: only a rejection remains, which an investigator decides |
| MOD-3 (GAP-010) | Tool results are type-checked against attribute types and states (refused, audited, run escalated, nothing applied); at start-up, stored records that fail validation are quarantined (left out with their links, kept in the store, logged, `quarantine` notification to admins, health `degraded`, metric `autology_quarantined_records`) instead of stopping the service | `tests/test_mod3_typed_outputs.py` (4, written failing first: 3 failed before the fix; includes the audit's `fraud_score = "very low"` and a corrupted row at restart); suite 491 OK | `GET /api/health` gains `quarantined_records` and reports `degraded` when it is not 0 |
| ACT-1 to ACT-5 (GAP-001 to 007) | External effects journal (`autology/effects.py`, store table `external_calls`, schema 12): intent committed before every tool call and result after; a stable idempotency key per step (header `Idempotency-Key` and payload); completed calls replayed, never repeated; failures classed *not sent* / *failed* / *rejected* / *unknown*, with retry and fallback only where safe; actions declare `side_effect` and `confirmation`; `202` and unconfirmed replies are `pending_confirmation`; runs `uncertain` / `pending_confirmation` wait for a person (`GET/POST /api/reconciliation`, permission `reconcile`, not the starter); records with an unsettled call refuse new runs; review decisions are recorded before the run acts and never reopened; start-up and every tick recover interrupted calls and stranded runs | `tests/test_external_effects.py` (17: intent before call; calls listed after a crash; same key across retries, deferral and restart; the audit's fault matrix — timeout, reset and 5xx after the bank executed — with 0 duplicate payments; safe retry after a refused connection; idempotent retry; no fallback after an unknown outcome; no retry after a rejection; 202, empty and FAILED replies never done; crash after approval (10a), deferred run killed in flight (10c), automation retry after a failed save (10e): 0 duplicates; reconciliation as done or not done). New APIs, so the tests could not run against the old code; the audit's PoCs on the old code had shown 3, 2 and 2 executions. Suite 509 OK with and without an audit key | Statuses `uncertain` and `pending_confirmation`; a tool crash now parks the run as `uncertain` instead of `escalated`; HTTP `503` and other 5xx no longer fall back to another tool; decisions are no longer reopened when a save fails (`tests/test_tool_failures.py` rewritten for this); the claims example declares `confirmation` on `pay_claim` and `side_effect: none` on the fraud score; permission `reconcile` |
| ACT-6 (GAP-009) | Before a run continues after a review, it re-reads its live records: fields changed only outside are brought into the run; if a reviewed fact changed or the action no longer applies, the approval is superseded and the run plans again (a new review if still needed); a field both the run and someone else changed stops the run (escalated, both values shown) | `tests/test_act6_revalidation.py` (4, written failing first: 3 failed before the fix — the audit's 11b/11c: amount changed during review, claim rejected during review; and a conflicting field); suite 513 OK | `tests/test_write_back.py`: an order cancelled during its review is no longer shipped and then flagged as a write-back conflict; it is not shipped at all |
| GOV-5 (D4) | A run acts with the agent's roles narrowed to the requester's own roles plus an explicit administrator grant (`run_as` per agent), or to a declared service identity's roles for automations (`service_identities`, `"as"` required on every automation run, authorised per agent); delegates narrowed too; the effective roles are persisted and sealed with the run, so a reviewer does not widen it; `run.start` records effective roles, agent roles and `acting_as` | `tests/test_gov5_effective_permissions.py` (7, written failing first: 7 failed before the fix); suite 520 OK | Example configs gain `run_as` grants and service identities; tests with their own users or automations updated (`test_approvals`, `test_gov1_manual_firing`, `test_platform`, `test_review_integrity`); a server with an automation run lacking `"as"` no longer starts |
| ISO-2 | Each workspace's audit chains and run seals use a key derived from the platform key and the workspace id (`audit.workspace_key`); the key is an explicit property of each audit log, store and agent (no global state); `autology backup --audit-scope` | `tests/test_iso2_workspace_audit_keys.py` (3: distinct keys, a chain verifies only with its workspace's key, a chain copied into another workspace's store does not verify and counts as unverified). The module imports the new API, so it could not run on the old code, where every workspace shared one key and a copied chain verified; suite 523 OK | Use-case stores behind the router are keyed per workspace: stores created before this change by the platform do not verify with the new key (none exist outside tests) |
| ISO-1 | `autology mcp platform.json --use-case <uc>`: a member token serves only that member's use case in their own workspace; other workspaces, ungranted use cases and wrong tokens get the same refusal | `tests/test_iso1_mcp_per_workspace.py` (4, written failing first: all failed before the fix); suite 527 OK | `autology mcp` accepts a platform file |
| ISO-3 | A workspace may declare its own `oidc`; its use cases use it (a use case's own setting is ignored); the router passes a non-member token only to the engine of the workspace in the path, which verifies it against that issuer and mappings | `tests/test_iso3_oidc_per_workspace.py` (5: own provider accepted; another workspace's provider refused, including for another use case; no provider means every JWT refused; member tokens still work and a company account cannot take a member's name; each use case carries its workspace's issuer). Before the fix 2 failed; the 3 refusals held already because the router refused all JWTs; suite 532 OK | `platform.json` workspaces accept `oidc` |
| LEG-1 (D5) | Proprietary `LICENSE` (legal entity and final text left for the IP review), `pyproject` licence and classifiers (`Private :: Do Not Upload`), `THIRD_PARTY_NOTICES.md` and a machine-readable inventory (`deploy/third_party_licences.json`) built from the packages' own metadata, licence files copied into the Docker image | `tests/test_leg1_licences.py` (5: proprietary notice and metadata; no source file claims an open-source licence; every declared component inventoried; every installed dependency of a declared component listed with the licence family its metadata states, under the policy; notices complete). Written failing first: it found `build`'s three dependencies missing from the first inventory; suite 537 OK | Two components need the legal review before the Docker image is distributed: the LGPL-3.0 PostgreSQL driver (psycopg) and MPL-2.0 `certifi` |
| MOD-4 (GAP-018) | Added at R1 close-out: GAP-018 (High) was not in the R1 story list. A writer lease in the store (host, process, heartbeat renewed by the scheduler): a second writing process is refused while the holder is alive and its heartbeat fresh; a crashed holder, a dead process or an expired heartbeat frees it; `backup` and `reporting` open the store read-only; `ingest` reports the refusal | `tests/test_mod4_single_writer.py` (5, written failing first: all failed before the fix; includes a real CLI subprocess refused next to a live service); suite 542 OK | `autology ingest` against a store a running server holds now fails with exit code 1; the audit's long-term remedy (reload or version-check on write) remains for R3 |
| Gate 80.4 | Entry-point matrix: every documented REST route (from `docs/platform.md`) × every single permission and no permission, with real ids; plus the assistant/MCP tool lists against permissions. Found and fixed: the read-only assistant/MCP tools were listed for users without `read` (their calls were already refused) | `tests/test_entry_point_matrix.py` (3; 150+ refusal checks, 0 unauthorised 2xx); suite 545 OK | Users without `read` no longer see read tools in the assistant or MCP |
| Gates 80.1–80.3 | Full fault-injection matrix: 7 bank replies (ok, timeout / reset / 5xx after executing, 202, empty, FAILED) × 4 contexts (inline, after two reviews, deferred retry, automation) × crash or not × non-idempotent or idempotent = 112 combinations | `tests/test_external_effects_matrix.py`: in all 112, at most one execution at the bank, a claim paid only on a confirmed reply without a crash, every executed call visible in the journal with the bank's key; with a normal reply every context pays exactly once; suite 546 OK | none |
| MOD-4 fix | CI's container smoke test (run 37) failed: after `docker stop`, the restarted container (new hostname) was refused because the stopped server had not released its lease. A server now releases its lease on shutdown (`service.close()`, single engine and platform), and the refusal states when a lease left by a crash expires | `tests/test_mod4_single_writer.py` (7: + clean stop frees the store at once for another host, + refusal names the expiry); `deploy/smoke_test.sh` on a freshly built image passes locally (stop, restart, data and runs survive); suite 548 OK | none |

## 14 November 2026 — verification pass and R1-C increment

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| ISO-4 (R1-C) | Credentials scoped per workspace: the platform refuses to load a use case whose configuration (or any JSON file it references) names an environment variable outside the workspace's prefix (`${VAR}`, `*_env`, `{"env": ...}`); background jobs and the use-case boundary inside a workspace covered by tests | `tests/test_iso4_isolation_matrix.py` (8, the 4 credential tests failed before the fix; the scheduler and use-case boundary tests passed already: isolation by construction) | A `platform.json` workspace takes `env_prefix` (default `<WS>_`); a use case naming another workspace's variable no longer loads |
| ENG-1 (§2A) | Headless engine: the inbox is optional (`GET /` → 404 "not installed" instead of 500 when absent); a standard-library client runs a full governed process with no UI files; no engine module imports a UI or Hermes | `tests/test_engine_headless.py` (4; 1 failed before the fix); suite 559 OK | none for installed deployments |
| Docs | Stale statements fixed: README test counts (408), methodology (122, now marked historical), platform.md "not yet included" multi-tenant line | — | — |
| Verification pass | Every claim of the earlier evidence document re-run at `a03ed96` in a separate worktree (472 tests OK, 37 targeted OK, 96.8 % lines) and at the current commit (559 OK; 95.9 % lines before the R1-C tests); CI runs reconciled with commits; one inaccurate claim found (commit count window); eight required documents produced or renamed from existing ones (`CURRENT_STATE_VERIFICATION`, `ARCHITECTURE_TARGET`, `REQUIREMENTS_TRACEABILITY`, `R1_COMPLETION_REPORT`, `MATURITY_SCORECARD`, `RELEASE_ROADMAP` (owner's R1–R6 sequence), `DECISION_REGISTER`, `EXECUTIVE_STATUS_FR`); `openpyxl` evaluated (MIT, no known vulnerabilities, use with `defusedxml`) | — | Planning documents renamed: links updated |

## 14 November 2026 — R1 closure note and first R2 slice

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| R1 closure | `planning/AUTOLOGY_R1_CLOSURE_NOTE.md`: commit, CI run and test link per resolved gap; what needs independent review, legal validation and real-system trials | — | none |
| R2 slice: lifecycle (part of REL-1, REL-2) | `autology/lifecycle.py`: a stage per use case (draft, simulation, pilot; production refused) in `<data_dir>/lifecycle.db`; forward moves one step at a time, checked on the server at the moment of the move; moving back always allowed with a reason; history chained with the workspace's derived audit key; stale when the ontology fingerprint changes. Found while testing: a use case in the engine's own `simulation` (demo) mode must not reach pilot, so that is a pilot check | `tests/test_r2_use_case_lifecycle.py` (23); new API, so it could not run before | `/platform/me` lists each use case's stage |
| R2 slice: use-case management (part of ADM-1) | `platform.json` takes `"templates"` (operator-approved configurations); `GET /platform/templates`, `GET/POST /platform/workspaces/<ws>/use-cases`, `GET …/<uc>`, `GET …/<uc>/checks`, `POST …/<uc>/stage`; created use cases get their own store, the workspace credential scope, reload at start; a used id is never reused | same file, `UseCaseManagementTests` | A platform file naming a template whose configuration file is missing no longer starts (like a missing use-case config); `tests/test_iso1_mcp_per_workspace.py`'s copied platform file now resolves template paths too |
| R2 slice: Studio shell (part of STU-1; D9 open) | `studio/`: separate process (`python -m studio --platform URL`), standard library and plain JavaScript, imports nothing from the engine, not in the engine wheel; forwards only GET/POST under `/platform/` and `/w/` with `Authorization` and `Content-Type`; strict CSP | `tests/test_studio_shell.py` (10); manual Playwright run (desktop and phone width): sign-in, checks, move, create, refused pilot with its failing check | none for the engine |

Commits: `6df0911` (closure note, CI run 47 success), `77b9a59` (slice, CI run 48 success on all jobs). Suite 592 OK; 96.4 % line coverage.

## 14 November 2026 — R2 increment 1: execution gates

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Execution gates | The use case's stage governs execution, read at every check: draft runs nothing (REST start, confirmed proposals, resume, review decisions, manual and scheduled automations, deferred retries, recovery); every tool declares an `environment` and a stage allows `simulated` (simulation) or `simulated` + `sandbox` (pilot) systems, `production` none; a step with no allowed tool is not sent, escalates and is audited (`step.blocked`); stale, edited or unreadable stages count as draft; `/api/health` reports the stage | `tests/test_r2_execution_gates.py` (12; new API, could not run before) with instrumented production and sandbox systems counting real calls | Platform use cases in draft no longer run (they did before); `tests/test_workspaces.py` moves its use cases to simulation first; the lifecycle test proves "a run before simulation does not count" by leaving and re-entering simulation. `tools.json` accepts `environment`; a `table` tool declared non-simulated is refused. Standalone engines unchanged |
| GAP clarification | `planning/AUTOLOGY_PARTIAL_GAPS_CLARIFICATION.md`: GAP-009, 018, 031, what is fixed, what remains, closure criteria; found that MCP from a platform file cannot run next to the platform server (second writer) | — | none |

Commit `40f7780`, CI run 50 success on all jobs. Suite 604 OK; 96.5 % line coverage.

## 14 November 2026 — Increment A: GAP-009 atomic write-back

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| GAP-009 (rest) | **Reproduced first:** with one of two changed fields conflicting, the other was written (`write_back` returned `(['O-1'], ['status'])`); each record was written in its own transaction. **Fix:** `graph.plan_write_back` computes the whole write set without changing anything; any conflict refuses it all; `Store.commit_write_set` writes every record of the set, the run's write-back state and an append-only `write_back_log` entry in **one transaction** that first checks each stored record equals the server's copy (a record changed by another writer refuses the set); the in-memory graph changes only after the commit; a failure leaves everything unchanged and the write-back pending, completed by recovery (start-up and every tick; idempotent); run summaries carry `write_back: {state, conflicts}`; `POST /api/runs/{id}/write-back` (permission `reconcile`) retries after a person resolved a conflict. Store schema 12 → 13 (two columns on `run_sources`, new append-only table; existing runs marked written so nothing is replayed). Local records only: external effects keep the journal, confirmation and reconciliation | `tests/test_gap009_atomic_write_back.py` (10; the reproduction test fails on the previous code, the others use the new API). Found by the full suite during the work: the graph holds unknown fields as `None` where the store omits them, so the record comparison treats absent and `None` alike (`test_delivery` caught it). Suite **614 OK**; **96.45 %** lines | A run with any conflicting field writes **nothing** back (before: the other fields). The conflict notification now says nothing was written and how to retry |

Increment A evidence: `ceb9c24`, CI run 52 ([43631227072](https://github.com/edlwiseltd/ontology/actions/runs/43631227072)) success on all three jobs.

## 14 November 2026 — Increment B: GAP-018 MCP through the platform and record consistency

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| GAP-018 MCP | **Before:** `autology mcp platform.json --use-case` opened the use case's store, so next to the running platform server it was refused (MOD-4) and MCP could not serve the use case. **Now:** `POST /api/mcp` answers one MCP JSON-RPC message with the same MCP server, in the engine's (only writing) process, as the token's user; behind the platform it is `/w/<ws>/u/<uc>/api/mcp`, so the router's workspace isolation applies; `autology mcp --url <platform>/w/<ws>/u/<uc>` is a stdio relay that opens no store. A token with no permission gets 403. The file mode stays for when no server runs and now explains the refusal | `tests/test_gap018_record_consistency.py` `McpThroughThePlatformTests` (6); the entry-point matrix found that a permission-less token got 202, fixed | New route `POST /api/mcp`; new `--url` option |
| GAP-018 consistency | **Before:** instance rows had no revision or seal: a stale write overwrote newer data and a direct SQL change went unnoticed. **Now:** store schema 14 gives every record a revision and an HMAC seal (workspace audit key) over id, type, content and revision; the set of records is sealed too (XOR of seals, MAC'd), so deletions are detected. API writes, run write-backs and loads name the revision they read: stale → 409, nothing written, the authoritative record reloaded; seal mismatch → 409, nothing written over it, admins notified, health `degraded` (`tampered_records`), left out of the graph at the next start (quarantine). Migration seals existing rows as found | same file, `RevisionTests` (3), `OutOfBandTests` (6) | `tests/test_mod3_typed_outputs.py` now writes its invalid row through Autology (validly sealed): a raw SQL edit is caught earlier by its seal, which is a different case. GAP-009 tests: the failure injection targets the new write statement; the "changed just before commit" case is now reported as a seal mismatch |

Increment B, local evidence before the push: suite **629 OK** (2 PostgreSQL tests skipped locally); **96.24 %** lines (10,653 statements, 401 missed).

## 14 November 2026 — Execution gates: bypass check (R2 security)

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Gate bypass found and closed | Checked every path by which a draft or simulation use case could reach an outside system. **Bypass found:** HTTP approvers and webhooks were not governed by the stage: in simulation, a review request was posted to the HTTP approver (the regression test fails on the earlier code with the request recorded at the receiver). **Fix:** both declare an `environment` (default `production`) and follow the stage like tools; a review request that may not be sent is declined (fail closed, run blocked with the reason); a webhook that may not be delivered is skipped (the notification stays in the inbox). Remaining outbound data flows, not actions: OTLP trace export and the reporting database (operator-configured telemetry and analytics), pipeline reads (D18) | `tests/test_r2_execution_gates.py` `OutboundIntegrationTests` | Webhooks and HTTP approvers default to `production`: on a platform use case they are not reached until a stage allows their declared environment (none does for `production`). Standalone engines unchanged |
Suite 630 OK; 96.23 % lines.

## 14 November 2026 — Increment C: GAP-031 engineering preparation (legal closure stays open)

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| GAP-031 engineering | Built the image and listed what it really contains. **Findings:** the image's Python packages were unpinned, so its contents and licences changed with the build date (today: no MPL `certifi` any more; `opentelemetry-api` added; six inventory entries said "Docker image" wrongly). **Changes:** `deploy/image-constraints.txt` pins the image; `ARG EXTRAS` (default unchanged, `llm,postgres`) lets an image be built without the LGPL PostgreSQL driver; `deploy/image_licences.py` lists the packages inside a built image and checks them against the inventory, the policy and the pins; CI runs it on the default image and builds, checks (no weak copyleft) and smoke-tests the `EXTRAS=llm` image; `deploy/image-os-packages.txt` lists the 87 Debian packages for counsel; inventory and notices corrected; legal decision package L1–L5 (D19) | `tests/test_leg1_licences.py` (7: +pins match the inventory, +legal inputs exist); both images built locally (legacy builder: Docker Hub rate-limited BuildKit's metadata check) and smoke-tested | Image builds use exact versions; none of the legal decisions is taken |
Suite 632 OK; 96.22 % lines.

## 14 November 2026 — Increment D (R2 foundations): API-1 contract, first step

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| API-1 | `autology/openapi.py`: one route table (58 operations on 53 paths, each with its permission) generating an OpenAPI 3.1 document, served at `GET /api/openapi.json` (no token: it holds no data). **Found:** 11 routes were served but missing from the documented table (health, OpenAPI, sign-in config and token, justifications, audit heads, run trace, run outcomes GET/POST, outcomes summary, SDK); they are now documented, so the entry-point matrix checks their permissions too | `tests/test_api_contract.py` (C1 structure and public serving; C2 every contract route is served; C3 every path the dispatcher matches is in the contract; C4 contract = documentation, permissions included) | New public route `GET /api/openapi.json`. Not yet: request/response body schemas, `/api/v1` (API-2), a generated Studio client |
Suite 643 OK; 96.26 % lines.

**CI failure and fix (Increment C):** run 55 failed in the package job: `.dockerignore` excludes `deploy/`, so the
image build could not copy `deploy/image-constraints.txt`. The local check had used a copied build context that
did not apply `.dockerignore`, so it did not reproduce CI. Fixed by an exception in `.dockerignore`; re-verified by
building from the repository's own context (legacy builder, since Docker Hub rate-limited BuildKit locally) and
running the licence check on that image.

## 14 November 2026 — Studio in Next.js (owner package of 14 Nov): Increments 0 and 1

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Increment 0 | `planning/AUTOLOGY_STUDIO_UI_UX_SPEC.md` (reconciled with the repository), `…_JOURNEYS_AND_SCREEN_MAP.md`, `…_FRONTEND_ADR.md`, `…_API_CONTRACT_MATRIX.md`; D9 recorded as approved (Next.js) | — | — |
| Increment 1 | `studio/web`: Next.js 16 / React 19 / TypeScript, exact pins and lock file; one narrow relay (`lib/forward.ts`: GET/POST under `/platform/` and `/w/`, two headers, no redirects, 1 MB); typed client; workbench (catalogue, overview with execution state, checks, stage moves, history, creation from templates, light/dark themes); read-only ontology canvas (React Flow) with an entity list and inspector sharing one selection. Engine: `GET /api/ontology` now includes relationships. The interim Python shell is retired (all its functions covered). Found while doing it: Next.js installs optional `sharp`/`libvips` (LGPL-3.0) and `caniuse-lite` (CC-BY-4.0): Studio disables the image optimiser and the point is added to the legal package (L6) | `studio/web`: Vitest 13 (relay confinement, projection incl. 300 entities < 250 ms, client, separation); Playwright `e2e/run.sh` 13 browser checks + Studio-stopped engine check (desktop 1280 px and iPhone 13, keyboard selection, contrast 16.2:1 / 15.4:1, non-admin and cross-workspace direct calls refused 403/404/404); `tests/test_studio_separation.py` (4) replaces `tests/test_studio_shell.py`; new CI job `studio` | `python -m studio` no longer exists: run `studio/web` (see `studio/README.md`) |
Python suite after the Studio change: 637 OK (643 − 10 retired shell tests + 4 separation tests); 96.26 % lines. Studio: 13 Vitest, 13 + 1 browser checks.

**CI evidence, 14 Nov:** run 53 (`118f8bc`, GAP-018) success; run 54 (`22211cc`, gate bypass fix) success;
run 55 (`2939b00`, GAP-031) and run 56 (`8bfec1c`, API-1) **failed** in the package job only (`.dockerignore`
excluded the constraints file; tests and coverage passed); run 57 (`4f8de46`, fix, contains both) success on all
jobs including the image licence checks and the image without the LGPL driver; run 58 (`ddc8095`, Studio) success
on all four jobs (Python 3.10 and 3.13 with PostgreSQL, package, studio incl. browser tests).

## 14 November 2026 — Directive 02: GAP-018 re-verified; three remaining defects fixed

Re-checked the repository against each acceptance criterion of the directive instead of relying on Increment B.

| Finding | Before | Fix | Test (fails on the earlier code) |
|---|---|---|---|
| Scenario commit bypassed revision and seal checks | `POST /api/scenarios/{id}/commit` changed the live graph first, then wrote record by record with no expected revision: a tampered or stale row was overwritten, a failure left a partial commit | `Scenario.plan_commit` validates on a copy; `Store.write_records` writes all records and links in one transaction with expected revisions; live graph changes only after it; refusals reload the authoritative record | `ScenarioCommitTests` (4) |
| Interrupted schema upgrade | Columns added but rows not yet sealed → at the next start every record looked tampered and was left out | Every upgrade step and the version bump run in one transaction (SQLite DDL is transactional); an interrupted upgrade leaves the old schema and runs again | `MigrationRestartTests` |
| Lost update between API clients | The server checked only its own revision: two clients doing read-modify-write could silently lose one update | Object views carry `revision`; `POST /api/objects` accepts `expected_revision` (0 = must not exist): 409 with the current record when stale | `ClientRevisionTests` |
| Concurrency evidence | No test with parallel requests | 6 writers × 5 read-modify-write increments over HTTP with `expected_revision` + 2 MCP relay readers + 1 governed run, at once: final value and revision exact (30 increments, 61 stale writes refused and retried in the measured run, plus 1 run write-back), every record's seal and the record set verify, memory equals store, one writer lease | `ConcurrencyTests` |
Directive 02 suite: 644 OK (2 PostgreSQL tests skipped locally); 96.29 % lines (10,736 statements, 398 missed).
Directive 02 CI: `5a90fa8` → [run 60](https://github.com/edlwiseltd/ontology/actions/runs/43637875204) success on all four jobs (Python 3.10 and 3.13 with PostgreSQL, package, studio).

## 14 November 2026 — Studio increment 2: design a model from a brief (synthetic water treatment)

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Engine: model design | `autology/modeling.py`: located validation (the engine's strict loader; problem path mapped to a node, field or edge), rule-based discovery questions from real gaps (isolated entity, reviewer role nobody holds, capability no tool provides, undeclared repeat safety, no goal), blueprint proposals (`autology/blueprints/water_treatment.json`, synthetic) labelled `"ai": false`. Store schema 15: append-only `model_drafts`; drafts saved only over the revision read (409), by administrators; a draft never changes the active model. Routes `GET/POST /api/model/draft`, `GET /api/model/draft/history`, `POST /api/model/validate`, `POST /api/architect/proposals` (contract and entry-point matrix updated). New synthetic template `industrial-starter`. **Found by the engine's own validation:** two blueprint entities lacked states | `tests/test_studio2_modeling.py` (7), API contract and entry-point matrix (the new routes refuse users without their permission) | New routes; `GET /api/ontology` unchanged |
| Studio: Design tab | Brief → provisional items (checkbox accept/reject, "blueprint · not AI") → working copy on a React Flow canvas (new nodes dashed, problem nodes red, drag = layout metadata, connect = relationship) → inspector edits → engine validation after every change ("checking with the engine…" until the verdict) → questions → diff vs saved revision → save with `expected_revision`, conflict banner on 409. **Found by the browser test:** the validity badge showed the previous verdict while the engine was still checking a change; fixed with an explicit checking state. Canvas refits when entities are added | `studio/web`: Vitest 16; `e2e/run.sh` 23 browser checks + engine-without-Studio | "Model" tab renamed "Active model"; new "Design (draft)" tab |
Studio increment 2 evidence (local): Python suite 651 OK (2 PostgreSQL tests skipped locally), 96.31 % lines; Studio Vitest 16; browser checks 23/23 + engine-without-Studio. Found by the full suite: the packaging test pinned the package-data list; extended to the blueprints folder (and the CI wheel check).
Studio increment 2 CI: `f8db2ee` → [run 62](https://github.com/edlwiseltd/ontology/actions/runs/43642656647) success on all four jobs (Python 3.10 and 3.13 with PostgreSQL, package incl. the wheel's blueprint, studio incl. 23 browser checks).

## 15 November 2026 — Master directive, increment 1: API v1 foundation

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| API-2 versions | `/api/v1/...` (engine, also `/w/<ws>/u/<uc>/api/v1/...`) and `/platform/v1/...` run the **same handlers** as the unversioned paths: authentication, permissions, row/field rules, stage gates and the access log are unchanged (`server.py` `ApiExchange.run`, `platform.py` `handle`). v1 adds one error envelope `{"error": {status, code, message, details}}` (router refusals included, identical for foreign, unknown and ungranted workspaces), `page` metadata on the lists that take `limit`/`offset` (`objects`, `runs`; one shared `page_window` so the metadata describes the window served), and `X-Autology-API-Version`. Legacy paths keep their exact shape, say `legacy` and link to their successor (`Link: …; rel="successor-version"`, prefixed with `/w/<ws>/u/<uc>` behind the router). Policy: `docs/api-versioning.md`; removal of legacy paths is decision D20 (applied default: no removal without notice) | `tests/test_api_v1.py` (11): V1 same handlers, V2 headers/successor reachable/legacy errors unchanged, V3 envelope on 6 refusal kinds + identical isolation answers, V4 paging returns every object once, V5 every typed response validated against its schema from a real platform (10 engine, 8 platform), V6 Studio's contract copies equal what the engine publishes; CLI | New paths and headers only; no legacy response changed |
| API-1 schemas | `autology/openapi.py`: JSON Schemas for the core and Studio routes (health, me, objects list/get/write, ontology, model draft/save/validate, proposals) and every platform route; `platform_spec()` served at `GET /platform/openapi.json` (no token, no data); `python -m autology openapi [engine\|platform] [--write DIR]`. Validator for the tests: `tests/schema_check.py` (no new dependency) | as above | New public route `GET /platform/openapi.json` |
| Studio client | Studio calls only `/platform/v1` and `/api/v1`. Its types are generated by `openapi-typescript` 7.13.0 (MIT, dev-only, exact pin) from `studio/web/api/*.openapi.json` into `lib/generated/`; `lib/types.ts` holds aliases only (no hand-typed API shapes). Errors read from the envelope (`error.message`; `ApiError.data` = `error.details`, so the 409 conflict banner and refused-move checks keep working). CI: the studio job rewrites the contracts and the types and fails on any difference | Vitest 17 (+1: envelope); browser checks 25 (+2: direct v1 calls and legacy calls both refused 403/404/404/403/403; v1 refusal uses the envelope) + engine-without-Studio | Studio needs a platform with v1 (this commit or later) |

**Found while doing it (fixed before commit):** (1) free-form objects declared as `{"type": "object"}` were
generated as `Record<string, never>` (nothing assignable): they now say `additionalProperties: true`; (2) a local
`import json` in the new CLI branch shadowed the module import and broke `autology export` and `autology plan`
(caught by the full suite, `tests/test_agnostic.py`); (3) behind the router, the legacy successor link pointed
to `/api/v1/...` at the platform root, which is not reachable; it now carries the use case's prefix and the test
follows it.

**Limits:** typed 200 schemas only for the routes listed; other engine routes are in the contract with
parameters, permissions and errors but a generic object body. Only lists that already took `limit`/`offset` are
paginated. The Console, the MCP relay and the generated SDKs still use the legacy paths (deprecated, working).
Increment 1 evidence (local, 15 Nov): Python suite 661 OK (2 PostgreSQL tests skipped locally), 96.32 % lines (10,981 statements, 404 missed); Studio typecheck, Vitest 17, build, browser checks 25/25 + engine-without-Studio. CI: `f059f2e` → [run 64](https://github.com/edlwiseltd/ontology/actions/runs/43684759108) success on all four jobs (Python 3.10 and 3.13 with PostgreSQL, package, studio incl. the contract/type drift check and 25 browser checks).

## 15 November 2026 — Master directive V2: owner decisions, H-1 security remediation

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Owner decisions | Decision register: D11 (independent approval: direction approved), D7/D10 (multi-provider architecture approved in principle; per-workspace configuration, residency and keys still open), D19 (prepare the legal package; not counsel approval; GAP-031 stays open, distribution blocked) | — | — |
| H-1 / F-01 (GAP-058) | New `autology/outbound.py`: a destination chosen by the other side (redirect, `next` link) is used only within the configured origin or an explicit `next_origins` list; replies size-limited; error texts built from the configured URL without query or credentials, then redacted. Applied to pipelines, HTTP tools, the HTTP approver, webhooks, OIDC discovery/JWKS and trace export. A tool redirected to another origin is an unknown outcome (may have acted), never "not sent" | `tests/test_h1_outbound.py` 12 tests: **7 failed on `bc84fb2`** (next page to another host received the secret; cross-origin redirects followed with credentials for pipelines, tools, approver and webhooks; secret in a tool URL appeared in the error; oversized reply read), all pass now | `next` links to another origin need `next_origins`; cross-origin redirects are not followed |
| H-1 / F-02 (GAP-059) | `User.kind` / member `kind` (`person`, `service`); `require_person` in `decide` and `reconcile`; `HttpApprover.can_approve` (so a real server refuses it, as for automatic approvers) and its decisions are `automatic`, attributed to `http:<origin>`, with the claimed reviewer kept in the comment | `tests/test_h1_approval_identity.py` 6 tests, **all failed on `bc84fb2`**, all pass now. Two existing tests changed because the behaviour changed on purpose: `test_agnostic.test_http_approver_fails_closed` (attribution) and `test_r2_execution_gates.OutboundIntegrationTests` (the approver's stage gate is now checked on the approver directly, since a real server no longer accepts one) | A configuration using `"approver": {"type": "http"}` on a real server no longer starts: use `inbox`, or `simulation: true` for tests |
H-1 evidence (local): full suite 679 OK (2 PostgreSQL tests skipped locally). CI: see the next entry.

**H-1 CI:** `5516358` → [run 67](https://github.com/edlwiseltd/ontology/actions/runs/43690042494) success (all jobs).

## 15 November 2026 — Master directive V2: REL-1a immutable release governance

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Configuration fingerprint | `autology/releases.py` `configuration_snapshot`/`fingerprint_of`: ontology document, governing settings (all server settings except store, members, sign-in, logs, secrets, data, reporting target) and each agent's tool declarations; SHA-256 of canonical JSON. `AutologyService.configuration_fingerprint`, shown in `/api/health` and in the use-case view | `test_rel1a_releases.FingerprintTests` | `/api/health` and use cases gain `configuration` |
| Releases | `ReleaseRegistry` in `<data_dir>/releases.db`: immutable `releases` (triggers refuse UPDATE/DELETE), append-only HMAC-chained `release_events` (proposed, approved, approval_revoked, activated, rolled_back); snapshots re-hashed on every read. Platform routes `/platform/v1/.../releases[/<n>[/approve|/revoke|/activate]]`, in the platform contract with typed schemas; Studio types regenerated | `test_rel1a_releases` (9): propose rules and immutability; approval independence (not the proposer, not a service, release authority incl. an external approver without other grants), bound to the fingerprint, revocable before activation; activation only of the approved running configuration; drift → draft until the matching release is activated; rollback recorded; tampered snapshot → draft; isolation | New routes |
| Approval authority (D11) | Workspace `release_approvers` (persons who are members); stage moves and release operations need a person | as above; `test_h1_approval_identity` | Single-administrator workspaces need a named approver to activate any release |
| Execution binding (GAP-020, F-04) | `RunState.configuration` recorded at start (also in `run.start`); `WorkAgent.resume` refuses another configuration at every resume path; `AutologyService.decide` refuses (409) before recording; the platform's effective stage counts drift and broken release history as draft, with the reason in the refusal | `test_rel1a_releases` R7, R5 | A run waiting on another configuration must be restarted |
| Pilot gate | `Lifecycle.move(extra_checks=…)`; the platform adds `approved_release_active` for pilot | `test_r2_use_case_lifecycle` (updated: pilot now goes through a four-eyes release; the expected check list gains `approved_release_active`), `test_api_v1` V5 (release routes validated against their schemas) | Pilot needs an independently approved, active release that is what runs |
| Documentation | `docs/workspaces.md` (releases), architecture Part B, product requirements R-RG-3/4, R-GV-*, R-EX-*, R-KN-*, traceability, roadmap §10, legal package D19 (`planning/AUTOLOGY_LEGAL_DECISION_PACKAGE_D19.md`) | — | — |

**Policy choices (documented, owner may change):** a run never migrates to another configuration (it stops; a person
restarts it); approvers do not activate (administrators do); an activated release's approval cannot be revoked (roll
back instead). **Limits:** no hot reload (activation attests what a restarted engine runs); Studio drafts cannot yet
become releases; Python code imported by tools is outside the snapshot; the stage fingerprint is still the ontology's
(the release fingerprint covers the rest).
REL-1a evidence (local): full suite 688 OK (2 PostgreSQL tests skipped locally), 96.12 % lines (11,400 statements, 442 missed); Studio typecheck, 17 Vitest, build, 25/25 browser checks. CI: see below.
**REL-1a CI:** `c2ea711` → [run 68](https://github.com/edlwiseltd/ontology/actions/runs/43691161947) success on all four jobs (Python 3.10 and 3.13 with PostgreSQL, package with image licence checks, studio with contract drift check and 25 browser checks).

## 15 November 2026 — Owner: "all approved, go ahead": ADM-1/ADM-2 and STU-6

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| ADM-1 administration | `autology/administration.py`: per-workspace administration log in `<data_dir>/admin.db` (append-only triggers, HMAC chain): members added (person or service; token generated, shown once, only its hash kept), removed, re-keyed; grants proposed → approved (another person with authority: workspace administrator or `release_approvers`; never the proposer, never the grantee, never a service) or withdrawn; grants revoked at once. Replayed over `platform.json` at start-up and after each change; a log that does not verify leaves only the configured administrators (fail closed). Workspace administrators stay configuration-only. Routes `/platform/v1/workspaces/{ws}/members[...]`, `/grants[...]` in the contract | `tests/test_adm1_administration.py` (9) | New routes |
| ADM-2 hot reload | Membership changes reach every engine at the next request (`AutologyService.set_users`); `POST .../use-cases/{uc}/reload` loads the files into a throwaway engine first, then replaces the running one; a failed load changes nothing; a reload is not an activation (drift until a release is activated) | `test_adm1_administration.ReloadTests` | New route |
| STU-6 engine side | A use case may have its own ontology file in its data folder (never the shared configuration files): `POST .../publish-draft` (a saved, valid draft revision; previous file restored if the result does not load) and `POST .../releases/{n}/restore` (a release's model back; `matches_release` tells whether activating it is a true rollback). Both recorded in the administration log | `tests/test_stu6_publish.py` (2); `test_api_v1` V5 now validates all 25 typed platform routes | A published model also makes the stage stale: simulate it again (lifecycle rule) |
| STU-6 Studio | `components/ReleasesView.tsx`: Releases tab (running fingerprint, drift warning, propose, approve, revoke, activate, restore, publish the latest saved draft, history); client functions typed from the regenerated contract | e2e 31 checks (+6: proposal, no approval offered to the proposer, approval by another person, approver cannot activate (403), activation, a published draft becomes the active model) | New tab |
ADM/STU-6 evidence (local): full suite 699 OK (2 PostgreSQL tests skipped locally), 96.08 % lines (11,721 statements, 460 missed); Studio typecheck, 17 Vitest, build, 31/31 browser checks. CI: see below.
**ADM/STU-6 CI:** `839e9d3` → [run 70](https://github.com/edlwiseltd/ontology/actions/runs/43695630133) success (all jobs).

## 15 November 2026 — QA-1: quality gates and supply-chain pinning (audit F-06, F-12; GAP-025, GAP-040)

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Lint gate | `pyproject.toml` `[tool.ruff]`: rules that find bugs (E9, F, B006, B008, B012, B015, B018), line length 120; 42 findings fixed (unused imports, an unused variable in `reporting.metrics`, an f-string without placeholders); two intentional test patterns marked `noqa` | CI job `quality`: `ruff check autology tests deploy` | None at run time |
| Type ratchet | `deploy/mypy_ratchet.py` + `deploy/mypy-baseline.txt` (201 errors, mypy 2.4.1): CI fails if the count rises; `--update` lowers it | CI job `quality` | — |
| Vulnerability scans | `pip-audit -r deploy/image-constraints.txt` (CI job `quality`); `npm audit --omit=dev --audit-level=high` (studio job). Local run: no known vulnerability in either | CI | — |
| Supply-chain pinning | Base image `python:3.13-slim` pinned by digest; `actions/checkout`, `setup-python`, `setup-node` pinned by commit SHA (newest release of the major already used: v4.4.0, v5.6.0, v4.4.0); pip pinned (26.2.2); the QA tools pinned and inventoried (`deploy/third_party_licences.json`, `THIRD_PARTY_NOTICES.md`; CI only, not shipped) | `tests/test_leg1_licences.py` | Updating a pin is a deliberate change (`docs/deployment.md`) |
QA-1 evidence (local): ruff passes; mypy 201 (= baseline); pip-audit and npm audit: no known vulnerabilities; full suite 699 OK (2 PostgreSQL tests skipped locally), 96.07 % lines (11,718 statements, 460 missed). CI: see below.
**QA-1 CI:** `cb91221` → [run 71](https://github.com/edlwiseltd/ontology/actions/runs/43696230537) success on all five jobs (new `quality` job: ruff, mypy ratchet, pip-audit; studio job: npm audit; the image built from the digest-pinned base).

## 15 November 2026 — IAM development directive: IAM-1 tenant foundation (D22)

Evidence in `planning/AUTOLOGY_IAM_TARGET.md` re-checked against the code first (one identity system: tokens, OIDC
per workspace, members and grants, `kind`, engine permissions and ontology roles; engine `admin` bypasses row and
field rules, `server.py` `visible`): confirmed. IAM-1 extends it; no second identity system.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Tenant entity | `platform.py`: `Tenant` (id, name, workspaces, tenant-level members) and `TenantMember`; `Workspace.tenant`; `Member.tenant`, `tenant_admin`, `scope`. Configuration key `tenants` (workspaces listed by exactly one tenant; an unlisted workspace is a dedicated tenant with its own id) | `tests/test_iam1_tenants.py` (9) | None for configurations without `tenants` (T1; the 78 isolation, administration and release tests unchanged) |
| Versioned registry and migration | New `autology/tenancy.py`: `<data_dir>/tenancy.db`, schema version 1 in `meta` (a newer registry is refused), `assignments` append-only (triggers) and HMAC-chained (key derived from the platform audit key). Migration: a workspace that already has data is recorded in its own dedicated tenant whatever the configuration says; a new one per the configuration; all records in one transaction. A configuration that disagrees with the record is refused at start-up. Explicit action: `python -m autology tenancy show|assign` (reason required; reversible the same way) | T2 (existing workspaces → dedicated tenants; merging configuration refused; data and governance histories byte-identical), T3 (explicit assign, reverse, append-only, tamper → start refused), T4 (interrupted migration records nothing; newer schema refused), T5 (registry removed → rebuilt identically) | A new file in the data directory; start-up refused when configuration and record disagree |
| Membership boundaries | A token is one identity of one tenant, resolved per workspace (`members_for`, `member_for(…, workspace)`); tenant-level members reach only workspaces they explicitly belong to; a tenant administrator (a person) administers every workspace of the tenant; workspace-level members stay identities of their workspace (`name@workspace`), never merged even when their tenants are merged on purpose; tenant-level identities are not removed or re-keyed from one workspace | T6, T7 (11 cross-tenant requests get one identical 404; data written in one tenant or workspace is invisible in the others) | `GET /platform/me` gains `tenant`, `tenant_admin`, `workspaces` and `?workspace=`; new `GET /platform/tenants/{tenant}` (contract, Studio types regenerated) |
| MCP and background | `mcp --workspace` when a token has several memberships; never another tenant | T8 (MCP), T9 (every scheduler ticks: only the workspace whose data changed fires; three stores, three audit keys) | — |

**Design choices to confirm:** the migration treats a workspace as existing when its data folder is non-empty;
tenant-level members and tenant administrators are configuration-only (no API); per-workspace audit keys,
credential prefixes and sign-in stay as they were (changing the keys would invalidate existing chains).
**Extension points kept, nothing built:** `Member.kind`/`scope` (portal, public, plugin identities), the registry's
`by` field (operator identities, IAM-2), `TenantMember.workspaces` (per-workspace roles).
**Limits:** application-level control only (data directory, configuration and key custody are infrastructure);
`tenancy assign` records the OS user as a claim; no tenant-level OIDC yet.
IAM-1 evidence (local): full suite 708 OK (2 PostgreSQL tests skipped locally), 95.95 % lines (12,003 statements, 486 missed); ruff clean; mypy 199 (baseline 201); Studio typecheck, build, 31/31 browser checks. CI: see below.

## 15 November 2026 — IAM development directive: IAM-3 administrative privilege separation (D22a decided)

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Administrative permission | Engine permission `configure` (`server.py`): model summary, model drafts, validation, architect proposals, the assistant's settings. It reads no record, run, review or audit entry; MCP (HTTP and stdio) refuses an identity that holds nothing else. `admin` (everything on one engine, regardless of row and field rules) is unchanged and implies it | `test_entry_point_matrix` and `test_api_contract` now include a `configure`-only identity on every documented route (**found:** `POST /api/mcp` acknowledged it; fixed) | Routes that asked for `admin` only to design or configure now ask for `configure` (contract and docs updated) |
| Roles no longer carry data | `Member.grant`: a workspace or tenant administrator gets `configure` on every use case of the workspace and nothing else; explicit grants are merged with it. Activation answers list run identifiers only to callers with data access (a count otherwise) | `tests/test_iam3_privilege_separation.py` (9): S1 administrators refused on 13 data routes in 4 workspace/identity combinations, S2 administrative powers intact, S3 explicit approved grant obeys row and field rules and is revoked at once, S4 escalation attempts refused, S6 scoped to one use case, workspace and tenant, S7 self-review still refused. **All failed on `0008ae4`** (checked in a worktree) | Administrators lose implicit data access |
| Safe migration | `_separate_privileges`, once per workspace, recorded in its administration log (`privileges_separated`): in a workspace that already had data, each configured administrator receives an explicit `admin` grant per existing use case (`grant_migrated`, in one transaction), visible in the members view and revocable; nothing is given to new workspaces, administrators or use cases. A log that does not verify gives no data access | S5: migration, restart (runs once), revocation persists, interrupted migration records nothing, tampered log fails closed | Existing deployments keep working; review and revoke the migrated grants |
| Grants for administrators | `POST .../grants` and `.../members/<name>/revoke` now accept administrators (their data access is a grant like any other); approval still needs another person who is neither proposer nor grantee | S3, S4; `test_adm1_administration` updated (the 409 "already has every right" no longer exists) | — |
| **GAP-061, found and reproduced during this increment** | An administrator with `configure` only saved a draft without the row-access rule, published it alone, and a member then saw a record hidden from her (reproduced on the example orders use case). Fixed: the author of a draft revision cannot publish it (another person with release authority does; named approvers may); only an approved release's model can be restored. Studio shows why the button is disabled | S8; `test_stu6_publish` updated; e2e 33 checks (+2: the author is refused 403, a second person publishes) | `publish-draft` needs a second person |

**Tests changed on purpose** (the behaviour changed): 12 test modules build their platform through `data_admins`
(`tests/test_workspaces.py`), which writes out an explicit `admin` grant for the administrators they use to load
data; `test_r2_use_case_lifecycle` now asserts that creating a use case gives its administrator no data access.
**Remaining risks:** (1) two colluding persons defeat any four-eyes rule; (2) files changed on disk by whoever
operates the platform, backups and the audit key are outside application control (infrastructure); (3) the engine's
`admin` grant still bypasses row and field rules by design: grant narrower permissions where possible;
(4) the one-time migration grants `admin` per use case to existing administrators: a deliberate choice to break
nothing, to be reviewed and revoked by each customer; (5) `kind` and administrator flags come from configuration
(no operator identity yet, IAM-2); (6) standalone engines (no platform) keep their own `admin` users as configured.
**Not implemented, by instruction:** IAM-2, IAM-4, IAM-5, IAM-6. Extension points kept: `Member.kind`/`scope`,
`ADMINISTRATIVE` permission set, the tenancy registry's `by`, the grant workflow.
IAM-3 evidence (local): full suite 717 OK (2 PostgreSQL tests skipped locally), 95.93 % lines (12,055 statements, 491 missed); ruff clean; mypy 198 (baseline lowered 201 → 198); Studio typecheck, 17 Vitest, build, 33/33 browser checks. CI: see below.
**IAM CI:** IAM-1 `0008ae4` → [run 75](https://github.com/edlwiseltd/ontology/actions/runs/43745015501) success; IAM-3 `88e5fd7` → [run 76](https://github.com/edlwiseltd/ontology/actions/runs/43746947522) success (workflow conclusion: every job, including `quality` with the lowered mypy baseline and `studio` with 33 browser checks).

## 15 November 2026 — R2 security and reliability sprint, increment A: GAP-030 authentication security

Baseline verified before any change: HEAD `8135abd`, clean and in sync; 717 tests OK (2 PostgreSQL tests skipped
locally), 95.93 % lines; CI run 77 success.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Token lifetimes | New `autology/credentials.py`: `TokenPolicy` (`security.tokens`: `person_days` 90, `service_days` 365, at most 3650) and `CredentialRegistry` (first sight and revocation of every token digest; append-only, chained; `<data_dir>/credentials.db`, or `<store>.credentials` for a standalone engine). `User.expires_at`, `Member.expires_at`; enforced in `AutologyService.authenticate`, `Platform.members_for` and for every MCP message | T1, T2, T5, T6, T7 | **Yes: every API token now expires.** A token that existed before gets one lifetime from the first start of this version (not cut off, not eternal). `401` carries `reason: token_expired` |
| Revocation and rotation | `POST .../members/<name>/revoke-token` (`token_revoked`); a replaced or revoked token and a removed member's token are retired in the registry for good; `POST .../my-token` lets a person replace their own workspace-level token; services, tenant-level identities and expired tokens cannot | T3, T4 | New routes; rotation never changes grants and gives one lifetime |
| Rate limits | New `autology/limits.py`: fixed-window `RateLimiter` (classes `auth_failures`, `anonymous` per address; `api`, `mcp`, `admin`, `expensive` per identity; `tenant`), `client_address` (forwarded addresses believed from `trusted_proxies` only); enforced in the router and in `ApiExchange`; `429` + `Retry-After`, code `rate_limited` | R1–R7 | **Yes: requests above the limits get 429.** Defaults are generous (the 717 earlier tests pass unchanged) |
| Timeouts | `BoundedHTTPServer` (connection ceiling, slow-client timeout) for both servers; `outbound.urlopen` deadline for the whole call (`_Watch`), mapped to an unknown outcome for tools; `WorkAgent.max_seconds` (`security.run_seconds`): a run pauses between steps | S1–S4 | A trickling reply now ends at the deadline (3 × timeout by default); runs longer than 900 s pause and can be resumed |
| Contract | OpenAPI: two routes, `token_expires_at`, `kind`, member `token` state, `token_policy`, `429` on every operation; Studio types regenerated | `test_api_v1`, `test_api_contract` | Additive |

**Security properties verified by executed tests** (not an independent certification): expired, revoked and
replaced tokens are refused at every entry point; a refresh by a service, a tenant-level identity, another member or
with an expired token is refused; rights are unchanged by rotation; limits hold across use cases, API versions and
entry points and per tenant; forged `X-Forwarded-For` is ignored; MCP follows over HTTP and stdio; a deadline never
leaves an untracked external effect (journal state `unknown`, reconciliation, no second payment); automations keep
running as their service identity whatever happens to API tokens.
**Limits stated:** rate-limit counters and the connection ceiling are per process (single node); the registry and
the limits are application controls (whoever can delete files in the data directory can reset lifetimes); Studio
users share the relay's address for the failed-sign-in limit; an administrator who issues a token has seen it
(company sign-in avoids that); the agent lock is still held for a whole run (GAP-021 stays partly open).
**Decision to confirm:** D23 (default lifetimes and limits).
Evidence (local): full suite 744 OK (717 + 27; 2 PostgreSQL tests skipped locally), 95.94 % lines (12,644 statements,
513 missed; baseline 95.93 %); ruff clean; mypy 198 (= baseline, no new error); Studio typecheck and 17 Vitest OK
(generated types only). **CI:** `940c04f` → [run 78](https://github.com/edlwiseltd/ontology/actions/runs/43755274397) success
(five jobs: tests on Python 3.10 and 3.13 with PostgreSQL, package, studio, quality).

## 15 November 2026 — R2 security and reliability sprint, increment B: IAM administrative security

Verification first (no change): the administrative role (`configure`) is refused every data route through REST (v1
and legacy), MCP over HTTP and stdio, and gains nothing from the scheduler; these two tests pass on the previous
commit too. The engine's `admin` permission is consulted at 19 places (`server.py`, `views.py`): every one is a
bypass of a row, field, role or ownership rule *inside one use case*; none crosses a use case, workspace or tenant.
They are now stated once (`UNRESTRICTED_MEANS`, docs/workspaces.md) and awaiting the owner's decision D24.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Unrestricted access is deliberate | A grant proposal containing `admin` needs `"unrestricted": true`, and so does its approval; recorded on both events | H3 | **Yes:** proposals and approvals of `admin` without the acknowledgement get 400 |
| Access review and approval path | `GET .../access-review`: every data grant with origin (configuration, migration, grant), proposer, approver, `data_access`, `needs_review`; `POST .../members/<name>/confirm-grant` (`grant_confirmed`) by a person with authority who is not the member; replacing by a narrower grant; revoking | H4, H9 | New routes. Nothing is revoked automatically: migrated grants keep working until a person decides |
| **GAP-062** no take-over by re-keying | `POST .../members/<name>/token` for a member with business data records `token_requested` (202); `POST .../token-requests/<id>/approve` by another person issues the token, shown to that person only; `withdraw`; `token_issued_by` in the members view | H5 | **Yes:** re-keying a member with data needs two people (a member without data: unchanged) |
| **GAP-063** proposals end with the member | `member_removed` drops the member's pending proposals and token requests (replay and lists) | H6 | A namesake added later inherits nothing |
| Effective permissions | Members view: `effective` per use case (permissions and `data_access`), `tenant_admin`, `use_cases`, `permissions`, `you` (what the caller may do; information only) | H2, H8 | Additive |
| Service identities | No change needed; verified that they propose, approve, confirm, request and administer nothing | H7 | — |

**Tests changed on purpose:** `test_adm1_administration` (A3 re-key through a second person; A4 acknowledgement),
`test_iam3_privilege_separation` (S4 acknowledgement), `test_gap030_security` (T3 second person), `test_api_v1`
(new typed routes). 10 of the 12 new tests fail on the previous commit; the 2 that pass verify properties IAM-3
already had.
**Migration report and approval path** for existing permissions: the access review, per workspace; each migrated
administrator grant is confirmed by another person, replaced by a narrower grant, or revoked. No approved access was
revoked by this increment and no new superuser capability exists.
**Remaining risks:** `admin` remains a bypass inside a use case (D24); the person who issues a token has seen it,
and a new member's first token is issued by one administrator (D25, OIDC for people); two colluding persons defeat
any four-eyes rule; grants written in the configuration are the operator's (reported, flagged when unrestricted);
application controls only. Not an independent security certification.
Evidence (local): full suite 756 OK (744 + 12; 2 PostgreSQL tests skipped locally); ruff clean; mypy 198 (= baseline,
no new error); contract regenerated, Studio types follow. Coverage was not measured separately for this increment (a
source file was edited while the measuring run was in progress, which invalidates its line figures); the measurement
of increment C covers this code.
**CI for increment B:** `01228d3` → [run 79](https://github.com/edlwiseltd/ontology/actions/runs/43756581206): tests
(3.10, 3.13), package and quality succeeded; the **studio job failed** at one browser check (waiting for the
publication warning after switching use case). Cause, found by reading the component: a late answer of a refresh
started before the click put the previous use case's detail back on screen (`Workbench`, present since STU-6,
exposed by timing; the check passes locally). Fixed in the next commit (answers for an earlier selection are
dropped); the browser tests were not run locally before pushing increment B, which this log records as a miss.

## 15 November 2026 — R2 security and reliability sprint, increment C: backup, restore and release activation

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| **GAP-033** platform backup | New `autology/recovery.py` and commands `platform-backup`, `platform-verify`, `platform-restore`. Every SQLite database is copied with the online backup (one committed snapshot; the write-ahead log is included by construction); order: stores and models, then registries, then access log; writer leases cleared in the copy; deep verification (integrity, every registry chain, every run's audit chain) before the manifest is written; manifest with sizes, SHA-256 and counts, signed with a key derived from the audit key; folder appears only when complete; 0700/0600; secrets left out unless asked | B1, B3, B5, B6, B7, B8 | New commands. `autology backup` (one engine) unchanged |
| Restore | Manifest signature and hashes checked read-only; copy beside the target; deep verification; counts compared; then put in place. Never overwrites; the backup is only read; a failure leaves nothing | B1, B2, B4, B5 | — |
| Isolated restore drill | A second platform is started on the restored directory while the first runs: tenant mappings, members, grants, token lifetimes and revocations, releases, stages, runs and audit chains are compared with the source; the two do not influence each other | B1, B2 (in CI on every push) | — |
| Coordinated activation | `Platform.activate_release`: the release's model is put in place, the configuration rebuilt from the deployed files and compared with the release's fingerprint before anything changes, the engine switched under a per-use-case gate, the activation recorded, the stage re-granted (simulation only); on any failure the model and engine are put back | A1, A2, A3 | **Yes:** no restart, no reload and no manual stage steps after activation; rollback is one call; the old error "deploy that release's configuration and restart" is gone |
| No intermediate state | `Gate`: requests share a use case, a switch (reload, publication, activation, restore) is alone; requests in flight finish first (a switch gives up after 10 s rather than cut them), later ones wait, then see the new engine; the scheduler does not tick during a switch; `503` + `Retry-After` when a wait is too long or a use case is unavailable | A4, A5, A7 | Engine and use-case routes may answer 503 during a long switch |
| Authorisation unchanged | Only a workspace administrator who is a person activates; unapproved or revoked releases are refused; pilot is never granted automatically, production never | A6 | — |
| Studio | Releases screen: Activate, or "Roll back to this release", for any approved release (the separate "Restore its model" button is gone; the API route stays); `Workbench` drops late answers for an earlier selection | 33 browser checks | — |

**Tests changed on purpose:** `test_stu6_publish` (after activation the use case is simulated again by itself; the
manual stage steps were removed from the test).
**Consistency boundary and restoration order** are stated in `docs/deployment.md`; activation semantics in
`docs/workspaces.md`. **Limits:** SQLite stores; no point-in-time recovery; backup storage, encryption, retention
and scheduling are the operator's; agents' settings and tool declarations are deployed by the operator (activation
verifies them, it does not rewrite them); one platform process. Recovery was demonstrated by executed tests, on
synthetic example data only.
Evidence (local): full suite 770 OK (756 + 14; 2 PostgreSQL tests skipped locally), 95.76 % lines (13,270 statements,
562 missed; baseline 95.93 %: the new error paths of recovery and activation are not all exercised); ruff clean;
mypy 198 (= baseline, no new error); Studio typecheck, 17 Vitest, build, 33/33 browser checks.

## 15 November 2026 — R2 security and reliability sprint, increment D: Studio tenant and membership administration

Studio is extended, not rebuilt: one new component (`AccessView`), one helper module, new functions in the existing
typed client; no new library; the types come from the published contract (`npm run generate:api`). No backend
change was needed beyond what increments A to C added (`effective`, `you`, `use_cases`, `permissions` in the
members view; access review; token requests).

| Story | Change | Tests | Behaviour |
|---|---|---|---|
| Context | Header: tenant › workspace › area; a workspace switcher when the identity belongs to several (`GET /platform/v1/me?workspace=`); the Access screen names tenant and workspace with their ids | e2e "tenant and workspace are named explicitly" | The workspace is explicit in every call's path |
| Members and effective permissions | Table per member: role, token state and expiry, who issued the token, and per use case the effective permissions in words ("administration only, no business data", "data within row and field rules", "unrestricted data access") | e2e members; unit `accessLabel`, `roleOf`, `tokenLabel` | — |
| Add, remove, revoke | Add a member (token shown once, never kept on screen or in the history), remove, revoke a grant, revoke a token; each with a reason | e2e add, revoke (stops at once), remove (401) | — |
| Request and approve | Grant request form (member, use case, permissions, roles); "approval required" state; pending list with Approve / Withdraw; the proposer and the grantee are told why they cannot approve; unrestricted access needs an explicit acknowledgement | e2e approval journey with two people; proposer's direct approval 403; unrestricted without acknowledgement refused by the platform | — |
| Tokens | New token (two people when the member holds business data: the requester sees none, the second person sees it once); replace one's own token (Studio continues with the new one) | e2e re-key, own token | — |
| Review and history | Access review summary and the grants that wait for a person (Confirm / Revoke); administration history | e2e review summary, history | — |
| Denied states | A member without authority sees "You do not have permission…" with the platform's reason; errors from the platform are shown as given | e2e permission-denied state; seven direct calls refused (403 ×5, 404 ×2) | No security decision rests on a hidden control |
| Relay | `Retry-After` from the platform (429, 503) is passed on | unit | — |

Accessibility and responsiveness: every field has a label (checked in the browser test), tables have names, status
and errors use `role="status"` / `role="alert"`, the page has no horizontal scroll on a phone (checked); a full
WCAG audit was not done. **Limits:** tenant-level identities and administrators are still defined in the
configuration (shown, not edited); grants' `run_as` is not editable in the form (API only); the access review's
confirm action is in the screen but its browser check is indirect (the route is covered by
`test_iamb_admin_hardening.py`).
Evidence (local): Studio typecheck, 23 Vitest (17 + 6), build, 56/56 browser checks against a real platform (33 +
23); Python suite unchanged since increment C (770 OK).

**CI for increments C and D:** `8111d7f` → [run 80](https://github.com/edlwiseltd/ontology/actions/runs/43758498960)
success; `0e9967a` → [run 81](https://github.com/edlwiseltd/ontology/actions/runs/43758659079) success (five jobs
each: tests on Python 3.10 and 3.13 with PostgreSQL, package, studio with the 56 browser checks, quality). The
studio job that failed in run 79 passes in both.

**Sprint summary.** Four increments, four commits (`940c04f`, `01228d3`, `8111d7f`, `0e9967a`); tests 717 → 770
(Python), 17 → 23 (Studio unit), 33 → 56 (browser); line coverage 95.93 % → 95.76 %; mypy 198 → 198; ruff clean.
Defects closed: GAP-030, GAP-033, GAP-062, GAP-063; GAP-021 partly. Decisions awaiting the owner: D23, D24, D25.
None of this is an independent security certification.

## 15 November 2026 — Decision integrity sprint, increment A: SEC-A (GAP-045, GAP-037, GAP-035)

Baseline verified before any change: HEAD `317be70` (the completion report, documentation only, on top of
`bf8fb15`), clean and in sync; CI run 83 success; the suite had been re-run at `bf8fb15` for that report (770 OK).

All three defects were first reproduced on the previous commit with a script: an instruction in a record made the
agent refund a customer (`refunded ['refunder']`); a caller with only `ingest` set a write-protected amount from
48000 to 100; an operations reader's notification showed a finance-only credit limit.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| GAP-045 what a model may decide | New `autology/integrity.py`. Agent loop: a model's choice other than the plan's step is honoured only if the action is under human review in that state or listed in the agent's `model_may_choose`; otherwise the plan's step runs and `reasoner.deviation_refused` is recorded. `model_discretion`: `governed` (default), `plan`, `open`. Reasoner: data in a marked block that cannot be closed from inside; a reply with unexpected fields or a non-candidate is refused and recorded (`reasoner.refused`). Findings for unreviewed discretion at start and in `GET /api/agents` | I1–I7 | **Yes:** by default a model no longer moves an agent off the plan onto an unreviewed action. `"model_discretion": "open"` restores the earlier behaviour explicitly |
| GAP-037 who may change decision facts | `write_access` rules bind ingestion: caller's roles for pushed rows, pipeline `roles` for configured sources; refused rows are rejected individually. Load report: `decision_fields_changed`, `decisions_to_revalidate`; access-log entry; `evidence_changed` notification to the reviewers of pending decisions; pipeline listing shows decision fields and those unprotected | G1–G6 | **Yes:** a pipeline or caller without the role can no longer write a field a `write_access` rule protects. Fields without such a rule load as before |
| GAP-035 notifications per reader | Automation messages are stored as template and values and rendered for each reader; hidden and justification-gated fields show `[restricted]`; notes about a run the reader may not see are not listed; webhooks and stored text carry the audience-safe version | N1–N5 | **Yes:** readers without the right no longer see restricted values in notifications; **found on the way:** a justification-gated field was shown to every addressed reader, and no longer is |

**Tests changed on purpose:** `test_evals` (a contrarian or random model no longer changes what runs by default;
the earlier expectations are kept under `model_discretion = "open"`), `test_operations` (the repeat bound is tested
under `open`; the default now completes the case).
**Limits:** where policy grants a model discretion (a listed action, or `open`), the model can still be steered
inside it; a human reviewer reads the same text the model read; a decision-critical field without a `write_access`
rule remains writable by any ingester (listed, not blocked); pipeline definitions are operator files outside the
release snapshot; webhook redaction is by the addressed roles, not per receiving system. None of this is an
independent security certification.
Evidence (local): full suite 788 OK (770 + 18; 2 PostgreSQL tests skipped locally), 95.71 % lines (13,470
statements, 578 missed); after that run an unused helper was removed and one rule made stricter (a `write_access`
condition that cannot be evaluated now protects the field), re-checked with the targeted modules (47 OK); ruff
clean; mypy 198 (= baseline). No API route or schema changed, so Studio was not rebuilt. CI: run 84, success (see
the table at the end of this sprint's entries).

## 15 November 2026 — Decision integrity sprint, increment B: D24 least-privilege operations (blocked on approval)

**Status: partial, by design.** D24 was not approved in the directive, so no authorisation semantics changed:
`operate` does not exist as a permission and `admin` is what it was.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Design | Target separation of capabilities, proposed scope of `operate` (four engine operations that read no record), the steps if approved, and the question for the owner: [IAM target §7](AUTOLOGY_IAM_TARGET.md); D24 updated in the decision register | — | None |
| Present behaviour pinned | `operate` cannot be configured or granted; the four operations are refused without `admin` | `test_d24_operate_readiness.py` D1, D2 | None (characterisation) |
| Effective-access evidence | `GET .../access-review`: for every unrestricted grant, `usage` (operational, configuration, data requests found in the use case's access log) and `narrower_would_do`; summary `unrestricted_without_data_use` | D3, D4; updated `test_iamb_admin_hardening` (one exact-summary assertion) | Additive fields in the review |

**Remaining for D24:** the owner's approval; then the implementation steps listed in the design (about 1–2 days).
**Limits of the evidence:** it reads the last 2,000 requests of the identity in that use case; absence of data use
in the log is not proof that the access is unnecessary.

## 15 November 2026 — Decision integrity sprint, increment C: MIG-1 and a first step of ARC-0

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| MIG-1 (GAP-041) | New `autology/migrations.py`: eight versioned steps (4, 5, 6, 11, 12, 13, 14, 15) in ascending order, each idempotent; `upgrade()` runs new tables, the steps, the remaining schema statements, validation against the layout this version expects, the ledger (`schema_migrations`) and the version number in one transaction. `Store.__init__` uses it; a store at the current version is checked against the expected layout; `Store.migration_history()` | M1–M6: upgrades from schemas 3, 10 and 13 with runs, audit chains, records, reviews and logs intact; a failure injected at every step leaves version, tables, columns and rows as they were | New tables are now created inside the upgrade transaction (before, outside it). A store whose version says "current" while a column is missing is refused instead of being silently altered |
| ARC-0 (GAP-026), first step | `NotificationService` (`notifications.py`) and `IngestionService` (`ingestion.py`) hold the code of 12 methods; `AutologyService` keeps the same methods, which delegate. The services ask the engine for permissions, visibility and write rules | S1–S4: same signatures, calls on a service refused exactly as through the engine, interception on the engine still works, a ratchet on the class size (2,142 lines, 139 methods) | None |

**What is not claimed.** No rollback of a migration (additive steps; going back is restoring the backup). The
platform registries are outside this mechanism. ARC-0 is not complete: runs and reviews, scenarios, model design,
the assistant and the dispatcher's route table remain in the class.
Evidence (local): full suite 802 OK (788 + 4 for D24 + 6 for MIG-1 + 4 for ARC-0; 2 PostgreSQL tests skipped
locally), 95.82 % lines (13,636 statements, 570 missed; `migrations.py` 97 %, `notifications.py` 97 %,
`ingestion.py` 93 %); ruff clean; mypy 198 (= baseline). No API route or schema changed, so Studio was not rebuilt.
A mistake during this increment, recorded: `git stash` was used to compare type-check output while a suite was
running, which reverted tracked files under the run; that run was discarded and the suite was run again from a
quiet tree (the figures above). Comparisons now use a separate worktree.

## 15 November 2026 — Decision integrity sprint, increment D: AI-1 provider-neutral AI foundation

**Status: the foundation is built and verified with test doubles. It is not a provider integration.** No request
was sent to a real provider and no customer data was used (D7/D10 not exercised). GAP-052 stays open.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Contract and gateway | New `autology/ai.py`: `ModelRequest` (instructions, untrusted data kept apart, the answer's JSON Schema, declared data classes, deadline, request id), `ModelResponse`, `ProviderError` with fourteen classified kinds (retryable or not; outcome uncertain or not), `Capabilities`, and `ModelGateway`: explicit per-workspace configuration (nothing by default), data-class allow-list (`synthetic` only by default), one deadline per request enforced by the gateway, bounded retries for rate limits and outages only, schema validation of the answer, refusal of tool requests, replay of repeated request ids, token and cost accounting per workspace, one content-free log event per attempt | P1–P9 | None for existing paths: nothing uses the gateway unless code builds one |
| Two adapters | `AnthropicProvider` (Claude through the official SDK's client object; SDK retries turned off, the gateway decides) and `ChatCompletionsProvider` (chat-completions JSON over HTTP through `outbound.urlopen`: redirects confined to the origin, deadline, reply size limit, idempotency key; a key is sent over https only, or to this machine) | P1–P6 through both: a double of the SDK client and a local mock HTTP endpoint driven by one scripted model | None |
| Bridge to agents | `GatewayChatModel`: an agent's reasoner can call its model through the gateway; a failure of any kind makes the agent follow its plan | G1–G2: the same compromised model behind either adapter, or behind none, gives the same governed outcome and audit events | None |
| AI Architect proposal contract | New `autology/architect.py`: `SCHEMA` (entities with properties and states, relationships, actions with preconditions and effects, rules, goals, questions, assumptions, unknowns, sources, confidence; no place for permissions, grants, settings, self-review or tools), `propose()` returning provisional items validated by the engine's strict loader on the current model plus the items, and `rejected` items with the loader's message; a proposal only adds; nothing is saved or applied | A1–A7 | None: not exposed through the API or Studio (Studio's architect still uses blueprints, `"ai": false`) |
| Shared pieces | `autology/schema.py` (the JSON Schema checker moved from `tests/schema_check.py`, which re-exports it; it now also checks `anyOf`, `maximum`, `maxItems`); `reasoners.claude_request` / `claude_usage` extracted so the Claude request shape has one definition | Existing contract and reasoner tests | None |

**Security properties verified (with a model that obeys what it reads).** An answer with any field beyond the
form asked for is refused as a whole (`settings`, `permissions`, `grants`, `release`, `model_discretion`,
`allow_self_review`); a tool request is refused and no tool definition is ever sent; instructions hidden in a
retrieved source stay inside the data block and gain nothing; a proposal cannot redefine an existing entity,
action, rule or goal; an added access rule can only restrict (pinned on the engine); a workspace cannot use
another's provider, model outline, recorded answers or accounting; logs carry no prompt, data, answer or key;
the AI modules import no store, server, platform, release or tool module (A7).

**Limits, stated plainly.** (1) Both adapters were run against doubles only; structured-output support and
schema keywords differ between real providers and were not checked against any. (2) Data classes are declared by
the calling code, not detected from content. (3) A cancelled or timed-out call may still complete and be billed
at the provider; it is counted as uncertain, not as zero. (4) An adapter that hangs leaves a daemon thread until
it returns; there is no cap on concurrent requests per workspace and no spending limit yet. (5) Recorded answers
for repeated ids are kept in memory (256 per gateway) and lost at restart. (6) The engine's configuration does
not build agents on the gateway, and the older direct path (`AnthropicChatModel` without the gateway) is
unchanged (GAP-029 remains partly fixed). (7) Proposal quality is untested: no real model has produced one.

Evidence (local): full suite 820 OK (2 PostgreSQL tests skipped locally), 95.78 % lines (14,264
statements, 602 missed; `ai.py` 96 %, `architect.py` 94 %, `schema.py` 88 %); ruff clean; mypy
198 (= baseline). After that run one line changed (a repeated request now gets a copy of the recorded answer, not the
same object), re-checked with the AI-1 module and seven related ones (137 OK). No API route or schema changed;
Studio browser checks were run for the fix below (56/56).

### CI evidence for the decision-integrity sprint

| Increment | Commit | CI run | Result |
|---|---|---|---|
| A — SEC-A | `4093749` | [84](https://github.com/edlwiseltd/ontology/actions/runs/43764453135) | success (5 jobs) |
| B — D24 readiness | `6f25695` | [85](https://github.com/edlwiseltd/ontology/actions/runs/43765148960) | **failure**: the `studio` job, one browser check of 56 ("a revoked grant stops working at once"); the four other jobs passed. Cause: a race in the check itself, written in the previous sprint (it waited for text that is always on the row, so the next call could overtake the revocation request). The platform applies a revocation before answering, which `test_adm1_administration` A3 asserts. Not reproduced locally (timing); fixed in `8c5a44c`. Increment B has no green run of its own: its commit is part of run 86 |
| C — MIG-1, ARC-0 | `846a3cc` | [86](https://github.com/edlwiseltd/ontology/actions/runs/43765769862) | success (5 jobs; includes B) |
| Browser-check fix | `8c5a44c` | [87](https://github.com/edlwiseltd/ontology/actions/runs/43766793062) | success (5 jobs; browser checks 56/56) |
| D — AI-1 | `744deae` | [88](https://github.com/edlwiseltd/ontology/actions/runs/43767795604) | success (5 jobs) |

The commit that records these results is documentation only; its own run is reported with the sprint report
([sprint report](AUTOLOGY_R2_DECISION_INTEGRITY_SPRINT_REPORT.md)).

## 15 November 2026 — R2 closure sprint, increment A: decision-critical facts fail closed

Baseline verified before any change: HEAD `e2f54cf` (documentation only on top of `744deae`), clean and in sync;
CI run 89 success; the last report's measurable claims checked against the source (schema version 15, engine class
2,142 lines and 139 methods, 820 tests). **One discrepancy found:** the sprint report said write rules bind
"every ingestion path", which is true, but the record API (`POST /api/objects`) and scenario commit applied no
write rule (they require the unrestricted `admin` permission, which is exempt by definition), and a decision
field without a rule stayed writable by any ingester. Reproduced on `e2f54cf`: an `admin` without the rule's role
set a write-protected amount to 1 through the record API and to 2 through a scenario commit; an ingest-only caller
changed an unprotected decision field from 48000 to 100.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Explicit classification | Attribute key `"decision_critical": true` (strict loader, published JSON Schema, `Ontology.critical_fields`); lint SEC003 for a classified field no rule protects | K1 | None for existing models: the key is opt-in and a model without it keeps its fingerprint |
| One policy for every write path | `integrity.critical_refusal`: the writer must hold the roles of a `write_access` rule on the field, whatever the rule's condition; with no rule, nobody. Applied by ingestion (pushed, scheduled, command line), the record API (REST, MCP), scenario commit, and governance for an action's declared effects and tool results. The unrestricted permission is not exempt | K2–K6 | **Yes, for classified fields only** |
| No value in refusals | Refusals, logs, the access log and notifications name the field and the rule, never the attempted value | K7 | None |

**Human control stays a policy.** With the role and no review rule, an agent sets a classified fact and completes
on its own (K6). Release approval and the stage gates are untouched.
**Not changed, on purpose (D24 pending):** ordinary `write_access` rules on unclassified fields still do not bind
the unrestricted permission on the record API or a scenario commit (pinned by a test). Unclassified decision
fields are still reported, not blocked.
**Migration:** none required. To adopt for a field: classify it, add a `write_access` rule naming roles, give the
roles to the people and service identities that maintain it, declare them on the pipelines that load it
([integrations](../docs/integrations.md)).
Evidence (local): the 11 new tests pass, 10 of them fail on `e2f54cf`; full suite 832 OK (2 PostgreSQL tests
skipped locally), 95.79 % lines (14,313 statements, 603 missed; `integrity.py` 98 %, `governance.py` 98 %); ruff
clean; mypy 198 (= baseline). The engine class stayed within its size limit (a pure helper moved to `graph.py`).
No API route or schema changed.

## 15 November 2026 — R2 closure sprint, increment B: D24 specification (blocked on approval)

**Status: blocked, as instructed.** No authorisation semantics changed.
[D24 specification](AUTOLOGY_D24_OPERATE_SPECIFICATION.md): exact permitted operations (scheduler pass with a
counts-only answer, reporting refresh), prohibited capabilities, relationship to `admin`, `configure` and the data
permissions, additive migration with no automatic change of any grant, and twelve security tests to accompany an
implementation. **Correction to the previous design:** retrying a write-back needs `reconcile`, not `admin`, and
was wrongly listed as an operation `operate` would take over; the readiness test asserted `403 or 404` and hid
that. The test now asserts 403 on the three operations that do need `admin` and has a separate case for write-back
(5 tests, part of the 832-test run above). A sub-decision is put to the owner: whether reinstating a suspended
agent belongs to `operate` (recommended: no, it lifts a safety control).

## 15 November 2026 — R2 closure sprint, increment C: ARC-0, runs and reviews

| Responsibility | Where it lives now | Methods |
|---|---|---|
| Run lifecycle: start, store result and audit chain, list, read, audit, trace, resume, recover after a crash, write back all or nothing, retry a write-back, recorded outcomes | `autology/runs.py`, `RunService` | 22 |
| Human review workflow: list, read, decide, check that the facts did not move, continue the run | `autology/reviews.py`, `ReviewService` | 5 |

The engine keeps a method of the same name and signature for each, which delegates (at most four lines, checked).
The services reach everything through the engine (`e = self.engine`): `require`, `require_any`, `checkpoint`,
visibility, the stage gate, the agents' governance. `require_person` (a service identity never records what only a
person may) was moved back into the engine during the increment, because reconciliation uses it too: no service
defines an authority check (S5). Services import the engine module and never each other; the engine imports them
where it is built, so there is no import cycle at load (S7).
**Still in `AutologyService` (1,730 lines, 138 methods):** reconciliation of external effects, scenarios, model
design and drafts, the assistant, automation wiring, objects and questions, settings, the dispatcher's route
table, `_validate`.
Evidence (local): `tests/test_arc0_services.py` 7 OK (3 new); full suite 835 OK (2 PostgreSQL tests skipped
locally), 95.82 % lines (14,415 statements, 602 missed; `runs.py` 94 %, `reviews.py` 93 %); ruff clean; mypy 198
(= baseline). No API route, schema or behaviour changed: the 832 earlier tests pass unmodified.

## 15 November 2026 — R2 closure sprint, increment D: REL-2 gates and REL-3 scorecard

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| REL-2 mandatory gates | New `autology/readiness.py`: 27 conditions (the commit message says 26: it left out the release check the platform supplies) measured on the running use case, each with its evidence; a condition can be mandatory for `pilot` and `production` or for `production` only. A mandatory condition that does not hold, **or cannot be verified**, is a blocker. The platform evaluates the mandatory conditions at the promotion itself (`_stage_checks`) | Q2, Q3, Q6, Q8 | **Yes:** promotion to pilot now also requires: no linter error, at least one goal, no unreviewed model discretion, a tool for every action, no suspended agent, a simulated or sandbox tool for every action, no pending write-back conflict. The example use cases satisfy all seven |
| REL-3 scorecard | Six dimensions; each shows its calculation, evidence, missing evidence, blockers and corrective actions; the overall figure is the weighted mean of measured dimensions. `GET /platform/v1/workspaces/{ws}/use-cases/{uc}/readiness?target=` (granted members; typed in the contract) | Q1, Q5, Q7 | New route |
| Score never decides | `promotion.allowed` depends on blockers only; verified in the report and at the promotion (a use case scoring above 80 is refused on one failed condition) | Q3 | — |
| Production | Refused as before whatever the gates say; the report says so | Q4 | None |
| Weights | `PROPOSED_WEIGHTS` (15/15/20/15/20/15), configurable per use case (`readiness.weights`), reported with their status, not part of the governing configuration | Q5 | New optional configuration key |

**Decision for the owner (D26):** the weights and the mandatory sets. Until approved every report says the weights
are a proposal.
**Limits:** no backup verification or restore drill is recorded per use case, so that condition is always missing
evidence and blocks production readiness; "every action was performed" reads the 200 most recent completed runs;
the conditions cover what the repository can verify (no external security review, no sector controls).
Evidence (local): `tests/test_rel2_rel3_readiness.py` 9 OK; full suite 844 OK (2 PostgreSQL tests skipped
locally), 95.86 % lines (14,587 statements, 604 missed; `readiness.py` 99 %); ruff clean; mypy 198 (= baseline).
Studio (the platform contract changed, client types regenerated): typecheck clean, 23 unit tests, build, 56/56
browser checks.

## 15 November 2026 — R2 closure sprint, increment E: the AI Architect through the versioned API (test doubles only)

**No language model was used and none can be configured.** D7/D10 are not approved: the engine accepts one
architect provider, `sandbox`, a deterministic test double built on approved templates that contacts nothing;
any other value is refused at start. Its proposals are labelled `"ai": false`. GAP-052 stays open.

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| Path | `POST /api/v1/architect/proposals` with `"generator": "model"`: gateway (configuration, data classes, deadline, schema check, accounting, logging) → proposal contract → engine validation → **stored revision** with who asked, brief, answers, provider, model, assumptions, rejected items and validation. Default generator `blueprint` unchanged | E1, E9 | New optional request fields; three new routes (list, read, decision) |
| Guided questions and revisions | Questions carry an id; `{"revises", "answers"}` stores the next revision of the same proposal; history is append-only (database triggers) | E2 | — |
| Review | `POST .../proposals/{id}/decision` records what a person accepted or rejected; it changes no model | E3 | — |
| Contract additions | Descriptions of roles, agents and integrations (text for an administrator: never a grant); goals as items | E1, test_ai1 A3 | — |
| Sandbox provider and template | `autology/sandbox_ai.py`; `blueprints/service_request.json`, an industry-neutral request → review → approval → fulfilment → closure process with four parameters (threshold, approver role, handler role, fulfilment system); answers are sanitised template parameters, never expressions | E1, E7 | The blueprint generator now also knows this template |
| Service | `autology/architecting.py` (`ArchitectService`, ARC-0 style: the engine's method delegates; engine class 1,721 lines) | S1–S7 | — |
| Store | Schema 16: `architect_proposals`, `architect_decisions` (MIG-1 step; additive) | test_mig1 | Stores upgrade on open |

**Boundaries verified:** an answer outside the contract stores nothing (502); engine-refused items are stored as
rejected, never provisional; provider failures are reported with their kind; a brief or an answer containing
instructions changes no rule, permission, setting or release; `configure` proposes and reviews, `read` reads, a
service identity cannot review, MCP offers none of it; another workspace gets 404; the sandbox works with the
network made unusable.
**Prepared, not executed:** [evaluation protocol for a first real provider](AUTOLOGY_AI_PROVIDER_EVALUATION_PROTOCOL.md)
(what the owner approves, isolation and data rules, budget limits to implement first, failure handling, acceptance
criteria).
Evidence (local): `tests/test_arc1_architect_api.py` 10 OK; full suite 854 OK (2 PostgreSQL tests skipped
locally), 95.86 % lines (14,843 statements, 615 missed; `architecting.py` 98 %, `sandbox_ai.py` 88 %); after that
run two unused helpers were removed from `sandbox_ai.py` and 45 related tests re-run; ruff clean; mypy 198
(= baseline). Studio (engine contract changed, types regenerated): typecheck clean, 23 unit tests, build, 56/56
browser checks. The insurance example now enables the sandbox architect (`"ai": {"provider": "sandbox"}`).

