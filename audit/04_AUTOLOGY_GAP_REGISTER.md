# 04 — Autology gap register

**Priorities.** P0: blocks a safe pilot (security, governance bypass, transaction integrity, external execution
reliability, legal use). P1: enterprise hardening. P2: productization.

**Effort.** Estimates in engineer-days (d) for one experienced Python engineer who knows this codebase, including
tests and docs, excluding code review, QA by others and customer coordination. They are planning estimates, not
measurements; uncertainty is roughly ±50%.

**Status values.** Confirmed (executed and reproduced) · Confirmed by inspection · Suspected (code reading only) ·
Evidence gap (nothing is broken, but required evidence does not exist).

Evidence paths are relative to [`audit/evidence/`](evidence/).

---

## P0 — Critical blockers

### GAP-001 · Blind retry after an ambiguous failure duplicates external actions
- **Domain** Operational integrations · **Severity** Critical · **Status** Confirmed
- **Description** When an HTTP tool times out or the connection drops after the external system has acted, the
  call is treated as "not done" and retried immediately (3 attempts by default). The run reports failure while the
  money was sent three times.
- **Root cause** `adapters.py:116-121` maps every transport error to `ToolError`; `agent.py:337-363` retries any
  `ToolError`; default `FailurePolicy(max_attempts=3, backoff=0)` (`ontology.py:179-183`). "Never sent"
  (connection refused, DNS) and "sent, outcome unknown" (read timeout, reset, 5xx after commit) are not
  distinguished. Errors say "cannot reach" for servers that were reached.
- **Evidence** `reliability/s07_08_http.py` → `external calls received: 3`; `attempt fields seen by server: [1, 2, 3]`.
- **Remedy** Classify transport outcomes into *not sent* / *rejected* / *unknown*. Only *not sent* and explicit
  retryable rejections may be retried automatically; *unknown* moves the step to a new `uncertain` state (GAP-006).
  Per action, declare `side_effect: none | idempotent | non_idempotent`; automatic retry of an *unknown* outcome is
  allowed only for `idempotent` actions with an idempotency key (GAP-002).
- **Tests** Fault-injection server: timeout after commit, reset after commit, 5xx after commit, refused before
  commit; each for idempotent and non-idempotent actions.
- **Acceptance** Across the fault matrix, 0 duplicate executions of non-idempotent actions; every ambiguous case
  ends in `uncertain` with an audit entry.
- **Dependencies** GAP-002, GAP-006, GAP-007 · **Effort** 4–6 d

### GAP-002 · No idempotency key reaches external systems
- **Domain** Operational integrations · **Severity** Critical · **Status** Confirmed
- **Root cause** `ToolCall` (`tools.py:30-37`) carries no run, step or attempt-stable id; the HTTP payload
  (`adapters.py:109-110`) has none, and no `Idempotency-Key` header is sent.
- **Evidence** `s07_08_http.py` → `any idempotency/run/case id in payload: False`.
- **Remedy** Generate a deterministic key per (run, step, action, instance), persist it before the call, send it as
  `Idempotency-Key` header and in the payload, keep it across retries, resumes and fallbacks; expose it to python
  tools.
- **Tests** Same key on every retry and after restart; different keys for different steps.
- **Acceptance** Every external call carries a key that is stable across retries and recoveries and is stored in the audit.
- **Dependencies** GAP-007 · **Effort** 1–2 d

### GAP-003 · Fallback tool runs after an ambiguous failure
- **Domain** Operational integrations · **Severity** Critical · **Status** Confirmed
- **Evidence** `s07b_fallback_timeout.py` → `bank A calls: 1 | bank B calls: 1` (and 2 + 1 with `fallback_after=1`).
- **Root cause** `agent.py:339-355`: `fallback_tools` defaults to true and is applied to any `ToolError`.
- **Remedy** Never switch tool after an *unknown* outcome of a non-idempotent action; only after *not sent* or an
  explicit rejection.
- **Acceptance** Fault matrix: 0 cases where two providers execute the same step.
- **Dependencies** GAP-001 · **Effort** 0.5–1 d

### GAP-004 · Resuming after a review re-executes actions after a save failure or crash
- **Domain** Operational integrations / governance · **Severity** Critical · **Status** Confirmed
- **Evidence** `s09_10_crash.py` 10a (SIGKILL during payment after approval: review still pending on restart,
  decided again, `external calls now: 2`) and 10b (in-process save failure: review reopened, second decision pays again).
- **Root cause** `server.py:971-990` resumes the run (executing tools) before recording the decision and, on a save
  failure, reopens the review (line 987). The run is persisted only at the end (`_store_result`). The test
  `test_decide_stays_consistent_when_saving_fails` asserts this behaviour.
- **Remedy** Record the decision first (decided, run "resuming"), persist each step's intent before executing it
  (GAP-007), and on restart continue from the intent log: steps with an intent and no result become `uncertain`,
  never re-executed. Replace the existing test with one asserting no duplicate.
- **Acceptance** SIGKILL at each point of the decide → execute → save sequence: 0 duplicates; review never reopened
  after any tool executed.
- **Dependencies** GAP-007 · **Effort** 3–4 d

### GAP-005 · Deferred resumes and automation retries repeat executed actions
- **Domain** Operational integrations · **Severity** Critical · **Status** Confirmed
- **Evidence** `s09_10_crash.py` 10c (deferred run: calls 1 → 2 → 3); `s10e_automation_retry.py` (firing errors
  after the run's tools executed, retry starts a new run: `payment calls: 2`).
- **Root cause** `server.py:655-657` (tick resumes from the last saved state); `automation.py:279` re-arms a firing
  whose run already executed tools inside `server.py:629-633`.
- **Remedy** Same intent log as GAP-004; automation firing records the run id before starting and never starts a
  second run for the same firing; a failed save marks the run `uncertain`, not retryable.
- **Acceptance** Fault injection at every save point in tick and firing: 0 duplicates.
- **Dependencies** GAP-007 · **Effort** 2–3 d

### GAP-006 · Any 2xx reply is treated as confirmed success
- **Domain** Operational integrations · **Severity** Critical · **Status** Confirmed
- **Evidence** `s07_08_http.py` 7d/7e/7h: `{}`, `202 {"message": "queued"}` and `{"output": {"status": "FAILED"}}`
  all produced `completed`, Claim `paid`, Payment `sent` with `reference: None`.
- **Root cause** `adapters.py:124` returns outcome `None` when the reply has none; `agent.py:610` substitutes the
  action's expected outcome; effects then assert `Payment.status = sent`.
- **Remedy** A confirmation contract per action: required reply fields (e.g. an external reference) and accepted
  status values; `202` or a missing confirmation leaves the step `pending_confirmation`; an optional `confirm`
  tool (status query) completes or fails it; a reconciliation job (GAP-007) polls uncertain and pending steps.
  Add run/step statuses `uncertain` and `pending_confirmation` to the API, inbox, metrics and reports.
- **Acceptance** No action is marked done without its declared confirmation; 202/empty/failed bodies never yield
  `completed`.
- **Dependencies** none · **Effort** 4–6 d

### GAP-007 · No write-ahead record of in-flight external actions
- **Domain** Auditability / integrations · **Severity** High · **Status** Confirmed
- **Evidence** `s09_10_crash.py` 9a/9b: after a crash following a successful payment, `runs: []`, `reviews: []`,
  claim still `reported`; 10d: automation marked active, no firing, no run — an orphaned payment nobody can find.
- **Root cause** The audit is in memory until the run ends (`agent.py:260-264`); no intent table.
- **Remedy** Append `step.intent` (key, action, inputs digest) to the store and the audit chain before each external
  call, and `step.result` after; a startup and periodic reconciler lists intents without results.
- **Acceptance** After a crash at any point, every external call made is visible with its idempotency key and state.
- **Dependencies** none (foundation for 001–006) · **Effort** 3–5 d

### GAP-008 · Concurrent runs on the same record both execute
- **Domain** Integrations / consistency · **Severity** High · **Status** Confirmed
- **Evidence** `s11_concurrency.py` 11a → `statuses: ['completed', 'completed']`, `external payment calls: 2`, `conflicts: []`.
- **Root cause** `start_run` builds the case under `graph_lock`, then waits on the agent lock (`server.py:854-875`);
  no per-record lease; write-back treats equal values as "no conflict" (`graph.py:242-244`).
- **Remedy** A per-root-record lease (one active run per root and goal, configurable), checked before start and
  held until a terminal state; versioned records (row version) for optimistic concurrency.
- **Acceptance** Two simultaneous starts on one record: one runs, the other is refused or queued; 0 duplicate actions.
- **Dependencies** none · **Effort** 2–3 d

### GAP-009 · Resumed runs act on stale data; write-back is partial
- **Domain** Integrations / consistency · **Severity** High · **Status** Confirmed
- **Evidence** `s11_concurrency.py` 11b (claim rejected and amount changed during review; run still paid 40,000)
  and 11c (ingestion changed amount mid-review; `conflicts: []`).
- **Root cause** `resume` does not re-read live records or re-check preconditions (`agent.py:377-415`); write-back
  is field-by-field and only for fields the run wrote (`graph.py:237-252`).
- **Remedy** On resume, re-read the case's records; if any field the remaining plan reads has changed, re-evaluate
  preconditions and rules and, if a reviewed fact changed, require a new review; make write-back all-or-nothing per run.
- **Acceptance** Change a reviewed fact during a pending review → the action does not execute without a new review.
- **Dependencies** GAP-008 · **Effort** 3–4 d

### GAP-010 · Tool outputs are not type-checked; one bad value prevents restart
- **Domain** Architecture / availability · **Severity** High · **Status** Confirmed
- **Evidence** `reliability/s05_input.py` → `RESTART FAILED: OntologyError Claim 'CL-1': fraud_score must be number, got str 'very low'`.
- **Root cause** `_validate_result` (`agent.py:303-317`) checks names and permissions, not types; `state.set`,
  `write_back` and `store.upsert_instance` don't type-check; `store.load_graph` does, at startup.
- **Remedy** Type-check tool updates against attribute types (reject the result, step fails safely); make startup
  quarantine invalid stored rows with an alert rather than refusing to start.
- **Acceptance** Wrong-typed tool output is refused and audited; a corrupted row does not stop the service.
- **Effort** 1–2 d

### GAP-011 · Self-review bypass through manual automation firing
- **Domain** Governance · **Severity** High · **Status** Confirmed
- **Evidence** `security/poc01_automation_self_review.py`: direct self-review refused (403); via
  `POST /api/automations/{name}/run` on a `draft` contract the same user approves her own run's review (200);
  the automation's `when` (status `signed`) was ignored; no checkpoint applied.
- **Root cause** `server.py` `run_automation` does not record the triggering user; `decide` checks only
  `run_starter`; `automation.py` `run_now` skips `when` when an instance is given; firings returned unfiltered.
- **Remedy** Record `triggered_by` and include it in the self-review check; evaluate `when` for manual firings (or
  require admin); apply the `start_run` checkpoint; filter returned firings by visibility.
- **Acceptance** PoC returns 403; automated test per bypass path.
- **Effort** 1 d

### GAP-012 · Hidden fields leak through scenario comparison
- **Domain** Governance / data protection · **Severity** High · **Status** Confirmed
- **Evidence** `security/poc02_scenario_compare_field_leak.py`: `/questions` refuses (403), but `compare_scenario`
  returns the answers, and a scenario edit recovers the exact credit limit (250000).
- **Root cause** `server.py` `_redact_report.answer()` checks row visibility only, not `field_hidden` or gated
  fields; admins bypass `read_field` checkpoints there; scenario `set` edits are allowed on unreadable fields.
  Likely also reachable through the assistant/MCP `what_if` tool (not executed).
- **Remedy** Reuse the `answer()` field checks for every question in comparisons; refuse edits to fields the user
  cannot read or write; apply provider redaction in `what_if`.
- **Acceptance** PoC returns no hidden value; the same test through the chat/MCP tool.
- **Effort** 1–1.5 d

### GAP-013 · Confused deputy: requester's access is not intersected with the agent's
- **Domain** Governance · **Severity** High · **Status** Confirmed
- **Evidence** `auditor/s1_agent_acts_on_hidden_rows.py`: `olivia` (role `ops`, cannot see EU order O-3) starts a
  run on K-1; the agent credit-checks, picks, ships and invoices O-3.
- **Root cause** `start_run` checks only the root object's visibility; the case template pulls in hidden rows and the
  agent acts with its own roles. `resume_run` does not check run visibility.
- **Remedy** Product decision (05, D4): either refuse runs whose case includes rows the requester cannot see, or
  run with the intersection of requester and agent roles, with an explicit, audited "service" mode for automations.
- **Acceptance** Requester without access to a record cannot cause an action on it via any entry point.
- **Effort** 1.5–2 d

### GAP-014 · Run-record fields outside the audit chain can be edited to skip a review
- **Domain** Auditability · **Severity** High (requires write access to the store) · **Status** Confirmed
- **Evidence** `reliability/s14_audit.py`: editing `pending_review.action` made one approval cover both reviews;
  `verify_audit True`. Also: `_digest`/`_head_mac` exclude `run_id`, so a chain could be transplanted (by inspection).
- **Root cause** `_tampering` (`agent.py:428-444`) checks status and state only.
- **Remedy** MAC the full run record (or derive it from the chain), bind `run_id` into digests and head MACs, and
  check `pending_review` against the last `review.requested` entry.
- **Acceptance** Any edit to the stored run record or a transplanted chain fails verification.
- **Effort** 1.5–2 d

### GAP-015 · Unauthenticated memory exhaustion with a negative Content-Length
- **Domain** Security · **Severity** Medium (P0 because trivial and unauthenticated) · **Status** Confirmed
- **Evidence** `auditor/f3_content_length.py`: `Content-Length 2000000` → 413; `Content-Length -1` with a 5 MB body → processed (404);
  `security/poc04`: 722 MB resident memory from one 300 MB request.
- **Root cause** `server.py` `_body()` checks only `length > MAX_BODY`; `rfile.read(-1)` reads to EOF.
- **Remedy** Reject negative, missing or non-numeric lengths on POST (400/411); never read more than `MAX_BODY`.
- **Effort** 0.25 d

### GAP-016 · Misspelled ontology keys are silently ignored
- **Domain** Architecture / governance · **Severity** High · **Status** Confirmed
- **Evidence** `auditor/arch_spot.out`: `requries` instead of `requires` on `pay_claim` loads cleanly and the action
  has 0 preconditions; unknown attribute type `nmber` accepted. `validate` and `lint` pass.
- **Root cause** `_from_dict` reads known keys and ignores the rest; `type_ok` accepts unknown types.
- **Remedy** Strict schema: reject unknown keys at every level and unknown types (JSON Schema published for editors).
- **Acceptance** Every documented key misspelled once → load fails with the path.
- **Effort** 1.5–2 d

### GAP-017 · A missing linked entity is treated as existing in its initial state
- **Domain** Architecture / governance · **Severity** High · **Status** Confirmed
- **Evidence** `reliability/s05_input.py`, `s05b_denied.py`: claim without a policy → `Policy.status = active`,
  approved with `approved_amount None`, later paid `amount None` after review.
- **Root cause** `state.py:73-76` sets `STATUS` to the initial state for absent entities.
- **Remedy** Absent entities have unknown status (`None`); preconditions on them fail; computed effects that resolve
  to unknown block the action.
- **Effort** 1 d (+ example and test updates)

### GAP-018 · The server's graph is never refreshed from the store
- **Domain** Architecture / data integrity · **Severity** High · **Status** Confirmed (architecture review)
- **Evidence** Two services on one store: after one ingested, the store had 17 instances, the other's graph 14;
  later upserts write whole attribute dicts from the stale copy. `docs/integrations.md` shows CLI ingestion alongside a running server.
- **Remedy** Short term: document "one writer; use the API while the server runs", make the CLI refuse when a
  server holds the store (lock file). Long term: reload or version-check records on write.
- **Effort** 0.5 d short term; 3–5 d long term

### GAP-031 · No licence; redistribution terms undefined
- **Domain** Commercial · **Severity** High (blocks any customer use) · **Status** Confirmed
- **Evidence** No LICENSE file or licence metadata; the Docker image bundles psycopg (LGPL-3.0).
- **Remedy** Product-owner decision (05, D5): proprietary EULA or open-source licence; licence metadata; third-party
  notices; legal check of LGPL obligations for the image.
- **Effort** 0.5 d engineering, plus legal time

---

## P1 — Enterprise hardening

| ID | Issue | Sev. | Status | Root cause / files | Remedy | Acceptance | Effort |
|---|---|---|---|---|---|---|---|
| GAP-019 | IdP-removed signing keys stay trusted until restart; `aud` object → 500 | Low–Med | Confirmed (`security/poc03`) | `oidc.py` `key()` caches forever | Cache lifetime, drop keys absent from latest JWKS, type-check `aud` | Removed key refused after refresh interval | 0.5 d |
| GAP-020 | Ontology change while runs paused: silent rule change (same version), fingerprint not recorded; version bump strands runs | Med | Confirmed (`s13`) | `agent.py:410-411` compares name@version only | Pin runs to fingerprint; record fingerprint on every resume; migration or cancel path for paused runs | Changed rules never apply silently; stranded runs can be cancelled with an audit entry | 2–3 d |
| GAP-021 | HTTP timeout is per read, not a deadline; agent lock held for whole runs, inline backoff under the lock | Med | Confirmed (`s07b`: 7.5 s for a 1 s timeout) | `adapters.py` urllib; `server.py:871`; `agent.py:359-363` | Overall deadline per call; release the agent lock around external I/O or move runs to workers | One slow system does not block other runs | 2–3 d |
| GAP-022 | One failing deferred run aborts the scheduler tick | Med | Confirmed | `server.py:648-659` | Per-item isolation and error reporting | Failure of one run does not skip others | 0.5 d |
| GAP-023 | Full-table scans and N+1 deserialisation on common endpoints | Med | Confirmed by inspection | `list_runs(limit=10**9)` at 7 call sites | Indexed queries, pagination in the store | Endpoints O(page) at 100k runs | 2–3 d |
| GAP-024 | No load, soak or capacity tests | Med | Evidence gap | – | Load test suite (runs/hour, concurrent reviewers, ingest rows/min) with targets agreed with the product owner | Published capacity for the reference deployment | 3–5 d |
| GAP-025 | No type checking, linting or dependency scanning in CI; 165 mypy errors | Med | Confirmed | CI config | Fix mypy errors, add mypy, ruff and a dependency audit (e.g. pip-audit) to CI | CI fails on new type errors and known-vulnerable dependencies | 3–4 d |
| GAP-027 | JSON-LD export crashes on computed effects; IRIs differ between formats; Turtle breaks on spaces; both lossy | Med | Confirmed | `export.py` | One IRI scheme, escaping, serialise `Computed`, export all sections; round-trip tests | All examples export in both formats and parse | 2–3 d |
| GAP-028 | Semantic diff ignores impact rules, scheduling, question contents, settings, descriptions | Med | Confirmed (architecture review) | `versioning.py` `diff` | Cover every section; fail release on unknown changes | Mutation test per section | 1.5–2 d |
| GAP-029 | Anthropic adapter lets non-API exceptions escape; chat contract vendor-shaped; one provider adapter | Med | Confirmed | `reasoners.py:169-190`, `chat.py` | Catch all at the adapter boundary; neutral chat message model; second provider adapter | Same eval suite passes on two providers | 4–6 d |
| GAP-030 | API tokens never expire or rotate without restart; no rate limiting or lockout | Med | Confirmed by inspection | `server.py` user loading | Token expiry and rotation; per-principal rate limits | Expired token refused; brute force throttled | 2–3 d |
| GAP-032 | No ERP connector (Odoo or other) | High for target market | Missing | – | `autology-odoo` package on top of GAP-001–007 (see 01 §8) | Real Odoo test instance: order/invoice flow with confirmation and no duplicates | 8–12 d after P0 |
| GAP-033 | Restore never exercised; no scheduled backups | Med | Evidence gap | deployment.md | Automated restore test (backup → new volume → start → verify), backup scheduling guidance | Restore drill passes in CI; measured recovery time | 1–2 d |
| GAP-034 | No encryption at rest for the store | Med (customer-dependent) | Missing | – | Decide (05, D3): volume encryption at the platform, or SQLCipher/PostgreSQL TDE | Documented and tested per deployment model | 1–3 d |
| GAP-035 | Notification text may include restricted fields; review notifications lack an instance key for filtering | Med | Suspected (code reading) | `automation.py` templates, `server.py` `list_notifications` | Check template fields against access rules at load; filter all notifications by record | Test with restricted field and hidden row | 1 d |
| GAP-037 | `ingest` permission can change facts rules depend on (e.g. lower an amount below a review threshold) | Med | Confirmed by inspection | `ingest.py`, `server.py` `ingest` | Document as privileged; optional per-attribute write restrictions for pipelines; audit pipeline changes to rule-relevant fields | Pipeline cannot write fields not listed for it | 1–2 d |
| GAP-038 | Expressions: unbounded string/tuple repetition; list-literal equality; negated comparisons on missing data are true | Low–Med | Confirmed (architecture review) | `expressions.py` | Size caps; list equality; treat negations over unknown as unknown in preconditions | Probes return bounded/unknown | 1 d |
| GAP-040 | Unpinned `anthropic` (uses beta parameters), `ortools` undeclared, Docker installs unpinned, actions not SHA-pinned | Med | Confirmed | `pyproject.toml`, Dockerfile, workflows | Constraints/lock file; declared extras; pinned actions | Reproducible image digest from a tag | 1 d |
| GAP-041 | Schema migrations run outside a transaction, no ordered steps | Low | Confirmed | `store.py:159-171` | Versioned migration steps in a transaction | Interrupted migration leaves the old schema intact | 1 d |
| GAP-044 | No organisation isolation inside one deployment | – | Missing | – | Decision (05, D1). Recommended: one deployment per customer; build multi-tenancy only if the business model needs shared hosting | Isolation demonstrated for the chosen model | 0.5 d (per-customer) to 15–25 d (multi-tenant) |
| GAP-045 | Text in data can steer an LLM's choice among valid actions; containment depends on rules existing | Med | Confirmed (`s06` 6h) | `reasoners.py` prompt construction | Delimit untrusted data in prompts, injection evals in the eval suite, lint warning for consequential actions without review rules when an LLM reasoner is configured | Injection eval suite passes; lint flags uncovered actions | 2–3 d |
| GAP-047 | Declined reviews: no notification or replanning; blocked/escalated runs not notified; conflict notifications have no roles | Low–Med | Confirmed (`s01_03`, `s11d`) | `server.py` notifications | Notify starter and escalation role on terminal non-success; role-addressed conflict notices | Each terminal non-success produces a notice | 1 d |
| GAP-048 | NaN and negative amounts accepted in case data and tool results | Low | Confirmed (`s05`) | `ontology.py` `type_ok` | Reject NaN/inf; optional attribute ranges | NaN refused at API and tool boundary | 0.5 d |
| GAP-049 | Release workflow never executed | Low | Evidence gap | `.github/workflows/release.yml` | Cut a release candidate tag on a test repository or registry | Image and wheel published and pulled | 0.5 d |
| GAP-052 | Never run with a real AI model | High (for AI claims) | Evidence gap | – | Eval suite against at least two real providers; record pass rate, cost, latency | Published eval results | 2–3 d + API cost |
| GAP-053 | No real end-to-end business process | High | Evidence gap | – | Pilot with one customer process on a test instance of their system | Signed pilot report with metrics | depends on customer |
| GAP-054 | No independent human security review | Med | Evidence gap | – | External penetration test and code review | Report with no open Critical/High | external |
| GAP-055 | Single-node SQLite store; no high availability | – | Confirmed (documented) | `store.py` | Decision (05, D2): acceptable for single-customer pilots; PostgreSQL store if HA or volume requires it | Meets the agreed availability target | 10–15 d for a PostgreSQL store |
| GAP-057 | Automations run synchronously inside request threads under one lock | Med | Confirmed by inspection | `automation.py:188-205, 262` | Background worker queue | Request latency independent of automation runs | 2–3 d |

## P2 — Productization

| ID | Issue | Sev. | Status | Remedy | Effort |
|---|---|---|---|---|---|
| GAP-026 | `AutologyService` god object (1,232 lines, 87 methods); `_dispatch` CC 78; `_validate` CC 111 | Med | Confirmed | Split into services and a route table; per-section validators | 5–8 d |
| GAP-036 | Every reader can list and read every scenario | Low | Confirmed by inspection | Owner/visibility checks on scenarios | 0.5 d |
| GAP-039 | Escalation roles `operations`, `security`, `it-integration` hard-coded | Low | Confirmed | Configurable in ontology settings | 0.5 d |
| GAP-042 | 56 MB of unrelated `.claude/skills` content and video notes in the repository | Low | Confirmed | Move out | 0.25 d |
| GAP-043 | Stale docs (methodology test count, autology.md multi-instance, ontology-concepts on pipelines; date types "checked"); one undocumented route | Low | Confirmed | Doc pass with a docs-claims checklist in CI | 1 d |
| GAP-046 | OIDC `redirect_uri` prefix check accepts `http://localhost.evil.com` (IdP still validates) | Low | Confirmed by inspection | Parse the URL; compare host exactly | 0.25 d |
| GAP-050 | Unsupported methods return HTML 501; internal `ValueError` becomes 400 with the message | Low | Confirmed | JSON errors; map only validation errors to 400 | 0.5 d |
| GAP-051 | No administration UI: users, roles and pipelines change only by editing config and restarting | Med | Confirmed | Admin API and screens; hot reload of users | 5–10 d |
| GAP-056 | No ontology or rule editor for business users | Med | Missing | Web editor on top of the strict schema (GAP-016) | 15–25 d |
