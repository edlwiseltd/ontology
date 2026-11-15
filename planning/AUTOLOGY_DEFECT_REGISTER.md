# Autology — defect register (after R1)

*Updated 14 November 2026 at the R1 close-out (`f0a385a`); GAP-051 updated with the first R2 slice; 15 November: H-1 and REL-1a. Source: the audit's register
([`../audit/04_AUTOLOGY_GAP_REGISTER.md`](../audit/04_AUTOLOGY_GAP_REGISTER.md)), whose descriptions, severities and
evidence are unchanged; this file adds the current status. "Fixed" means the remedy is implemented and a test that
reproduces the audit's finding passes in CI; it has not been re-verified by an independent auditor.*

| Status | Count |
|---|---|
| Fixed | 22 |
| Open | 21 |
| Open (external evidence) | 5 |
| Open (owner decision) | 2 |
| Partly fixed | 9 |

*Counts updated 15 November 2026 (H-1: GAP-058, GAP-059 added and fixed; REL-1a: GAP-020 fixed; ADM-1/2 and STU-6: GAP-030, GAP-056 partly fixed, GAP-051 updated; QA-1: GAP-025 partly fixed, GAP-040 updated).* **High gaps not
fully fixed:** GAP-031 (waits for legal sign-off, D19), GAP-032 (ERP connector), GAP-052 (real models) and GAP-053
(real process), which need external systems, keys or a customer. GAP-009 and GAP-018 are **Fixed** (repository-
verified; independent re-verification open): GAP-009's atomicity is local, there is no compensation towards
external systems (audit F-14); GAP-018 detects, but cannot prevent, direct writes to the database file. Background
and closure criteria: [the clarification note](AUTOLOGY_PARTIAL_GAPS_CLARIFICATION.md).

| Gap | Title | Severity (audit) | Status | Fixed in | Evidence / next step |
|---|---|---|---|---|---|
| GAP-001 | Blind retry after an ambiguous failure duplicates external actions | Critical | **Fixed** | ACT-3 · `ac07e66` | `tests/test_external_effects.py` (fault matrix), `tests/test_external_effects_matrix.py` (112 combinations) |
| GAP-002 | No idempotency key reaches external systems | Critical | **Fixed** | ACT-2 · `ac07e66` | `IdempotencyKeyTests`: same key on retries, deferral, restart; header and payload |
| GAP-003 | Fallback tool runs after an ambiguous failure | Critical | **Fixed** | ACT-3 · `ac07e66` | `test_no_fallback_provider_after_an_unknown_outcome` |
| GAP-004 | Resuming after a review re-executes actions after a save failure or crash | Critical | **Fixed** | ACT-5 · `ac07e66` | `test_a_crash_after_approval_never_pays_twice`; `tests/test_tool_failures.py` rewritten (the old test asserted the defect) |
| GAP-005 | Deferred resumes and automation retries repeat executed actions | Critical | **Fixed** | ACT-5 · `ac07e66` | `test_a_deferred_run_killed_in_flight_does_not_pay_again`, `test_an_automation_retry_never_starts_a_second_payment` |
| GAP-006 | Any 2xx reply is treated as confirmed success | Critical | **Fixed** | ACT-4 · `ac07e66` | `ConfirmationTests`: 202, `{}` and FAILED never done |
| GAP-007 | No write-ahead record of in-flight external actions | High | **Fixed** | ACT-1 · `ac07e66` | `IntentLogTests`: intent committed before the call; calls listed after a crash |
| GAP-008 | Concurrent runs on the same record both execute | High | **Fixed** | `5400ad8` | `tests/test_one_run_per_record.py` |
| GAP-009 | Resumed runs act on stale data; write-back is partial | High | **Fixed** | ACT-6 · `c779566`; atomic write-back · Increment A (see log) | `tests/test_act6_revalidation.py`; `tests/test_gap009_atomic_write_back.py` (10): one conflicting field blocks the whole write set, several records commit together or not at all, an injected failure between two writes rolls everything back, a record changed just before the commit refuses the set, a crash is completed at restart, duplicate commits change nothing, superseded approvals unchanged, schema 12 → 13 migration. Local records only; independent re-verification open |
| GAP-010 | Tool outputs are not type-checked; one bad value prevents restart | High | **Fixed** | MOD-3 · `d480abe` | `tests/test_mod3_typed_outputs.py` |
| GAP-011 | Self-review bypass through manual automation firing | High | **Fixed** | GOV-1 · `c2a6b3b` | `tests/test_gov1_manual_firing.py` |
| GAP-012 | Hidden fields leak through scenario comparison | High | **Fixed** | GOV-2 · `467655f` | `tests/test_gov2_scenario_fields.py` |
| GAP-013 | Confused deputy: requester's access is not intersected with the agent's | High | **Fixed** | GOV-3 `beb970a`, GOV-5 `789a3c9` | `tests/test_gov3_requester_scope.py`, `tests/test_gov5_effective_permissions.py` |
| GAP-014 | Run-record fields outside the audit chain can be edited to skip a review | High (requires write access to the store) | **Fixed** | GOV-4 · `e69f06d` | `tests/test_gov4_run_record_seal.py` |
| GAP-015 | Unauthenticated memory exhaustion with a negative Content-Length | Medium (P0 because trivial and unauthenticated) | **Fixed** | `4509b97` | `tests/test_api_exchange.py` |
| GAP-016 | Misspelled ontology keys are silently ignored | High | **Fixed** | MOD-1 · `f20ddc1` | `tests/test_mod1_strict_schema.py` (400+ misspellings) |
| GAP-017 | A missing linked entity is treated as existing in its initial state | High | **Fixed** | MOD-2 · `b3a2deb` | `tests/test_mod2_missing_records.py` |
| GAP-018 | The server's graph is never refreshed from the store | High | **Fixed** (repository-verified; C1–C3 met, see the clarification note; independent re-verification open) | MOD-4 · `fd7ab77`, `f0a385a`; Increment B `118f8bc`; directive 02 (see log) | `tests/test_mod4_single_writer.py`; `tests/test_gap018_record_consistency.py` (15); `tests/test_gap018_directive02.py` (7, all failing on the code before directive 02): scenario commits now revision- and seal-checked in one transaction, schema upgrades transactional and restart-safe, API clients can send `expected_revision`, and a concurrency test (6 parallel writers, MCP readers and a run through the HTTP platform) loses no update and corrupts no record. **The Increment B "Fixed" was premature** for the scenario-commit path, found by this re-verification. Limits: detection, not prevention, of direct database writes; demo mode (no audit key) seals detect accidents only |
| GAP-019 | IdP-removed signing keys stay trusted until restart; `aud` object → 500 | Low–Med | **Open** |  | R3 hardening |
| GAP-020 | Ontology change while runs paused: silent rule change (same version), fingerprint not recorded; version bump strands runs | Med | **Fixed** (repository-verified, REL-1a; CI below) | REL-1a (see log) | Runs record the configuration fingerprint (ontology, governing settings, tool declarations) they started on and never continue on another (`WorkAgent.resume`); a review decision on another configuration is refused (409) before it is recorded; releases bind approvals to the fingerprint. `tests/test_rel1a_releases.py` (R7). Limits: Python code imported by tools is not in the fingerprint |
| GAP-021 | HTTP timeout is per read, not a deadline; agent lock held for whole runs, inline backoff under the lock | Med | **Open** |  | R3 hardening (deadline-based HTTP timeout; agent lock) |
| GAP-022 | One failing deferred run aborts the scheduler tick | Med | **Open** |  | R2 (small): isolate each deferred run in a tick |
| GAP-023 | Full-table scans and N+1 deserialisation on common endpoints | Med | **Open** |  | R3 (indexed queries, pagination) |
| GAP-024 | No load, soak or capacity tests | Med | **Open (external evidence)** |  | R4 OPS-2 load test with agreed targets |
| GAP-025 | No type checking, linting or dependency scanning in CI; 165 mypy errors | Med | **Partly fixed** | QA-1 (see log) | CI job `quality`: ruff (bug-finding rules, `pyproject.toml`; 42 findings fixed), a mypy ratchet (`deploy/mypy_ratchet.py`, baseline 201 errors on 15 Nov: the count may only go down), pip-audit on the image's pins, `npm audit` for Studio. Open: the 201 existing type errors |
| GAP-026 | `AutologyService` god object (1,232 lines, 87 methods); `_dispatch` CC 78; `_validate` CC 111 | Med | **Open** |  | R2: split the service (the god object grew in R1) |
| GAP-027 | JSON-LD export crashes on computed effects; IRIs differ between formats; Turtle breaks on spaces; both lossy | Med | **Open** |  | R3 |
| GAP-028 | Semantic diff ignores impact rules, scheduling, question contents, settings, descriptions | Med | **Open** |  | R2: needed by REL-1 (release diffs) |
| GAP-029 | Anthropic adapter lets non-API exceptions escape; chat contract vendor-shaped; one provider adapter | Med | **Partly fixed** |  | Adapter boundary unchanged; second provider adapter is R2 AI-1 (D7) |
| GAP-030 | API tokens never expire or rotate without restart; no rate limiting or lockout | Med | **Partly fixed** | ADM-1 (see log) | Tokens can be replaced without a restart (`POST .../members/<name>/token`, old token refused at once; `test_adm1_administration` A3). Open: expiry, rate limiting, lockout (R3) |
| GAP-031 | No licence; redistribution terms undefined | High (blocks any customer use) | **Partly fixed** (engineering done; legal open) | LEG-1 · `6a23ff5`; Increment C (see log) | `tests/test_leg1_licences.py`; CI checks the licences of what each built image contains; image pinned (`deploy/image-constraints.txt`); an image without the LGPL driver builds and passes the smoke test; base-image packages listed. **Open (legal):** decisions L1–L5 (D19). Customer distribution prohibited until recorded |
| GAP-032 | No ERP connector (Odoo or other) | High for target market | **Open** |  | R3 INT-2/INT-3 on an Odoo 18 sandbox (D6), now possible since ACT-1–6 pass |
| GAP-033 | Restore never exercised; no scheduled backups | Med | **Open** |  | R4 OPS-1 restore drill in CI |
| GAP-034 | No encryption at rest for the store | Med (customer-dependent) | **Open (owner decision)** |  | D3 still open |
| GAP-035 | Notification text may include restricted fields; review notifications lack an instance key for filtering | Med | **Open** |  | R2 |
| GAP-036 | Every reader can list and read every scenario | Low | **Open** |  | R2 (small): scenario owner/visibility checks |
| GAP-037 | `ingest` permission can change facts rules depend on (e.g. lower an amount below a review threshold) | Med | **Open** |  | Documented as privileged; per-attribute ingest rights in R3 |
| GAP-038 | Expressions: unbounded string/tuple repetition; list-literal equality; negated comparisons on missing data are true | Low–Med | **Open** |  | R3 |
| GAP-039 | Escalation roles `operations`, `security`, `it-integration` hard-coded | Low | **Open** |  | R2 (small) |
| GAP-040 | Unpinned `anthropic` (uses beta parameters), `ortools` undeclared, Docker installs unpinned, actions not SHA-pinned | Med | **Partly fixed** | Increment C; QA-1 (see log) | Image pins (`deploy/image-constraints.txt`), base image pinned by digest, GitHub Actions pinned by commit SHA, pip and the QA tools pinned in CI, licences inventoried. Open: hashes (`--require-hashes`), the unpinned `anthropic` extra in `pyproject.toml` (libraries keep ranges; applications pin) |
| GAP-041 | Schema migrations run outside a transaction, no ordered steps | Low | **Open** |  | R2: ordered migrations in a transaction (three more were added in R1: schema 11, 12) |
| GAP-042 | 56 MB of unrelated `.claude/skills` content and video notes in the repository | Low | **Open** |  | R2 (small): move unrelated content out |
| GAP-043 | Stale docs (methodology test count, autology.md multi-instance, ontology-concepts on pipelines; date types "checked"); one undocumented route | Low | **Partly fixed** |  | Docs updated with every R1 story; docs-claims checklist in CI open |
| GAP-044 | No organisation isolation inside one deployment | – | **Fixed** | Phase 1 `e157e5b`, ISO-1–3 | Workspaces with dedicated stores, keys, sign-in and MCP scope; D1: isolated pilots first. Independent verification open |
| GAP-045 | Text in data can steer an LLM's choice among valid actions; containment depends on rules existing | Med | **Open** |  | R2 with AI-1 (delimit untrusted data, injection evals) |
| GAP-046 | OIDC `redirect_uri` prefix check accepts `http://localhost.evil.com` (IdP still validates) | Low | **Open** |  | R2 (small) |
| GAP-047 | Declined reviews: no notification or replanning; blocked/escalated runs not notified; conflict notifications have no roles | Low–Med | **Open** |  | R2 |
| GAP-048 | NaN and negative amounts accepted in case data and tool results | Low | **Open** |  | R2 (small): reject NaN/inf |
| GAP-049 | Release workflow never executed | Low | **Open (external evidence)** |  | R2: cut a release candidate |
| GAP-050 | Unsupported methods return HTML 501; internal `ValueError` becomes 400 with the message | Low | **Partly fixed** | `4509b97` | Unsupported methods answer JSON 405; ValueError → 400 mapping open |
| GAP-051 | No administration UI: users, roles and pipelines change only by editing config and restarting | Med | **Partly fixed** | R2 slice; ADM-1/ADM-2 and STU-6 (see log) | Members (person or service), tokens and use-case grants change through the API without a restart (`tests/test_adm1_administration.py`): grants need an independent approval (D11), revocation is immediate, the log is append-only and chained. Releases are managed from Studio (Releases tab; e2e). Open: a members-and-grants screen in Studio; roles, pipelines and workspace administrators still change only in configuration |
| GAP-052 | Never run with a real AI model | High (for AI claims) | **Open (external evidence)** |  | R2 AI-1: needs API access to two providers |
| GAP-053 | No real end-to-end business process | High | **Open (external evidence)** |  | R3 pilot (customer) |
| GAP-054 | No independent human security review | Med | **Open (external evidence)** |  | R4 SEC-1 (external) |
| GAP-055 | Single-node SQLite store; no high availability | – | **Open (owner decision)** |  | D2 open: SQLite for the isolated pilots |
| GAP-056 | No ontology or rule editor for business users | Med | **Partly fixed** | Studio increment 2; STU-6 | Entities and relationships are edited visually in Studio drafts, validated by the engine, and a saved draft can be published as the use case's model, which then needs an independently approved release (`tests/test_stu6_publish.py`, e2e). Open: visual editors for rules, actions, processes, organisation, agents |
| GAP-057 | Automations run synchronously inside request threads under one lock | Med | **Open** |  | R3: background worker queue |
| GAP-058 (audit F-01, 15 Nov) | HTTP ingestion sent its secret headers to the "next page" URL chosen by the remote source, on any host; redirects were followed with credentials for pipelines, HTTP tools, the HTTP approver, webhooks, OIDC and trace export; replies unbounded; secrets could appear in error texts | Med | **Fixed** (repository-verified; CI below) | H-1 (see log) | `autology/outbound.py` (origin rules, same-origin redirects, size limit, redaction) used by `ingest.py`, `adapters.py`, `server.py` (webhooks), `oidc.py`, `tracing.py`; `next_origins` allow-list. `tests/test_h1_outbound.py` (12; 7 failed on `bc84fb2`). Limits: operator-configured destinations stay trusted (no private-address blocking, so on-premise systems keep working); not an independent security test |
| GAP-059 (audit F-02, 15 Nov) | A machine could record a "human" approval: the HTTP approver satisfied human reviews outside simulation with a reviewer name chosen by the remote service, and API identities had no person/service distinction | Med | **Fixed** (repository-verified; CI below) | H-1 (see log) | Users and platform members declare `kind` (`person` default, `service`); `decide` and `reconcile` refuse service identities (403); the HTTP approver counts as automatic (refused on a real server; attributed to `http:<origin>`, claimed name kept as a claim). `tests/test_h1_approval_identity.py` (6, all failed on `bc84fb2`). Policy-authorised autonomy unchanged (A5). Limits: `kind` is declared by the operator; company sign-in users are treated as persons; release approvals follow in REL-1a |
