# 02 — Autology test evidence

All numbers below were measured during this audit at revision `fdfaf01`. Nothing is copied from earlier reports.

## 1. Environment

| | |
|---|---|
| Local | Linux container, Python 3.13.18; optional dependencies present: OR-Tools 9.15.6755, rdflib 7.1.4, cryptography 44.0.2, psycopg 3.2.3, Node 22 with `tsc`; PostgreSQL 16 (Docker) at `127.0.0.1:55432`; Docker 29.9 |
| CI | GitHub Actions run 43455793202 on the same commit: `test (3.10)`, `test (3.13)` (each with a PostgreSQL 16 service, no skipped tests allowed, coverage ≥ 95%) and `package` (wheel build and install, Docker build, container smoke test, compose validation). **All three jobs green.** |
| Not available | A real LLM API key; a real ERP or payment system; a second organisation's environment; a human tester |

## 2. Full test suite

```bash
AUTOLOGY_AUDIT_KEY=audit-key AUTOLOGY_TEST_PG_DSN=postgresql://postgres:test@127.0.0.1:55432/postgres \
  python3 -m coverage run --branch --source=autology -m unittest discover -s tests -t . -v
```

| Result | Value |
|---|---|
| Tests run | **408** |
| Passed / failed / errors | **408 / 0 / 0** |
| Skipped | **0** (all 9 conditional skips had their dependency present) |
| Wall time | 144.9 s |
| Line coverage | **97.0%** (8,306 of 8,565 statements) |
| Branch coverage | **93.3%** (3,099 of 3,320 branches) |
| Combined (coverage.py) | 96% |
| Lowest modules | reporting 91%, agent 93%, economics 93%, reasoners 93%, scoring 93%, warehouse 93%, ingest 94%, oidc 94%, views 94% |

Per-test log: [`evidence/test-run/tests-summary.log`](evidence/test-run/tests-summary.log); per-module coverage:
[`evidence/test-run/coverage.txt`](evidence/test-run/coverage.txt).

**What the coverage does and does not say.** High line and branch coverage shows that most code paths run under
test. It does not show that the paths are *right*: every critical defect in section 4 sits in code that is
covered. In particular the existing test `test_decide_stays_consistent_when_saving_fails` asserts the behaviour
that causes duplicate execution (GAP-004). There are no failure-injection tests for external side effects, no
load or performance tests, no fuzzing, no mutation testing and no static type checking in CI (mypy reports 165
errors).

| Kind of testing | Present? |
|---|---|
| Unit and component | Yes, extensive |
| Integration with real services | Yes, for PostgreSQL (ingestion and reporting) in CI; manually for Keycloak, Metabase, Prometheus |
| Container / deployment smoke | Yes, in CI |
| Security tests | Partial: many access-control tests; this audit's PoCs found gaps they did not cover |
| Failure-recovery tests | Partial: tool failures, retries, save failures; **none for side effects after timeouts or crashes** |
| Concurrency tests | One (concurrent review decision); none for concurrent runs on one record |
| Load / performance / scalability | **None** |
| Real LLM | **None** (no key) |

## 3. Real-system checks performed (class A evidence)

| Check | System | Result |
|---|---|---|
| Incremental SQL ingestion (numeric/timestamp columns, watermark) | PostgreSQL 16 via psycopg | Pass (CI and local) |
| Reporting export to PostgreSQL | PostgreSQL 16 | Pass (CI and local) |
| BI tool reads the governed export; PII column absent | Metabase 0.56 (Docker) | Pass (Tier 3 work, 13 Nov) |
| Metrics scrape with bearer token, direct and via compose network | Prometheus 3.5 (Docker) | Pass |
| SSO login through the IdP's page into the inbox; reviewer sees her review | Keycloak 26 + headless Chromium | Pass |
| Container lifecycle: health, sign-in, data load → governed run, metrics, bad token refused, online backup verified, SIGTERM stop, restart with data | Docker, `deploy/smoke_test.sh` | Pass (local and CI) |

These were run against local containers, not customer systems. None involved a real business process with real
external side effects.

## 4. End-to-end operational scenarios

Scripts in [`evidence/reliability/`](evidence/reliability/) (local "bank" HTTP server recording every call;
insurance example), [`evidence/security/`](evidence/security/) and [`evidence/auditor/`](evidence/auditor/).
Key scripts were executed twice: once by the reviewer and once by the lead auditor (`*.reverify.out`).

| # | Scenario | Expected | Observed | Result | Severity |
|---|---|---|---|---|---|
| 1 | Fully automated execution | Completes, written back, audit verifies | CL-1 assessed → approved 2,700 → paid; `verify_audit True` (`s01_03`) | **PASS** | – |
| 2 | Human approval required | Pauses, resumes on approval | CL-2: investigator review → claims-manager review (≥ 20,000) → paid 40,000 (`s01_03`) | **PASS** | – |
| 3 | Approval rejected | Clear terminal state or replanning | Terminal `blocked`, recorded; no replanning, no notification; claim left in an intermediate state (`s01_03`) | **PASS with gaps** | Low |
| 4 | Unauthorized action attempt | Refused on every path | Direct paths refused (403s). **Bypassed** via manual automation firing (self-review, `when` ignored) and via the agent acting on records the requester cannot see (`poc01`, `s1`) | **FAIL** | High |
| 5 | Missing or contradictory input | Reject or fail closed | Unknown entity/attribute/type/state rejected. **Missing Policy treated as `active`**: claim approved and paid with amount `None`; wrong-typed tool output persisted and **service cannot restart**; NaN amount paid (`s05`, `s05b`) | **FAIL** | High |
| 6 | Invalid output from an AI model | Never executes an invalid action | Fake model: all invalid outputs fell back to the planner; prompt injection steered a valid choice, contained by a review rule (`s06`). Real model: **not verifiable** | **PASS (simulated) / NV (real)** | – |
| 7 | External API unavailable | Retry, then escalate | Connection refused / 500: 3 attempts → escalated (pass). **`202 queued`, `{}`, `status: FAILED` → reported `completed`, Payment `sent`** (`s07_08`) | **FAIL** | Critical |
| 8 | Timeout after the action executed | Uncertain state, no blind retry, idempotency | **3 identical payments**, run reported failed; no idempotency key; fallback provider also pays (`s07_08`, `s07b`) | **FAIL** | Critical |
| 9 | Restart during execution | Intent persisted; uncertain on restart | **Nothing persisted** for an executed payment; retry pays again (`s09_10` 9a/9b) | **FAIL** | Critical |
| 10 | Recovery without duplicates | Resume does not repeat executed actions | Duplicates via review re-decision, deferred resume and automation retry (`s09_10` 10a–10c, `s10e`) | **FAIL** | Critical |
| 11 | Concurrent modification | Conflict detected before acting | Two concurrent runs both pay, no conflict; resumed run pays on stale data (`s11`). Concurrent review decisions safe (`s11d`) | **FAIL** | High |
| 12 | Permission bypass via API, MCP, tools | No bypass | API: hidden fields recovered via scenario comparison (`poc02`); self-review via automation (`poc01`). Tools: undeclared writes refused (pass). MCP: shares the chat tool code; the `what_if` leak path was identified by code reading but **not executed** | **FAIL (API)**, MCP partly NV | High |
| 13 | Rule change during an active execution | Pinned rules or explicit migration, recorded | Same version: new rules silently applied, fingerprint not recorded on resume. Version bump: paused runs stranded (`s13`) | **FAIL** | Medium |
| 14 | Audit verification after interruption | Chain verifies and is complete | Verifies after SIGKILL and restart (pass); in-flight external call absent; run-record fields outside the chain edited to skip a review, undetected (`s14`) | **PARTIAL** | High |
| 15 | Isolation of two customer organisations | Data and policy isolation | **Not supported** in one deployment (no tenant concept). Separate deployments are isolated by construction (separate config, store, keys) but this was not tested as an isolation claim | **E / not tested** | (decision D1) |

## 5. Static analysis

| Tool | Result | Evidence |
|---|---|---|
| radon cyclomatic complexity | 773 blocks, average 5.82; grades A 583, B 118, C 76, D 15, E 12, F 9; worst `Ontology._validate` 111, `_dispatch` 78, `lint` 68 | `evidence/architecture/cc.json` |
| mypy (`--ignore-missing-imports`) | 165 errors in 24 files (403 with `--strict`); sampled errors were annotation problems, not runtime bugs | `evidence/architecture/mypy.txt` |
| Domain-vocabulary scan of executable code | No business vocabulary outside docstrings | `evidence/architecture/domainscan.py` |
| RDF validity | Turtle of all 6 examples parses in rdflib; JSON-LD of `auto_insurance` crashes | `evidence/architecture/parse_rdf.py`, `evidence/auditor/arch_spot.out` |
| Dependency licences | anthropic Apache-2.0, PyYAML MIT, **psycopg LGPL-3.0 (bundled in the Docker image)**, OR-Tools Apache-2.0, rdflib BSD-3, cryptography Apache-2.0/BSD | `evidence/architecture/deps.json` |
| Dependency vulnerability scan | **Not performed** (no scanner run; CI has none) | – |

## 6. What could not be tested, and the effect on confidence

| Not tested | Why | Effect |
|---|---|---|
| A real LLM (Claude or any other) | No API key in the environment | AI-driven reasoning and the assistant are validated only with fake/scripted models; real-model robustness, cost and latency unknown |
| A real ERP, payment or CRM system | None available; no Odoo connector exists | No class-A evidence for outbound operations; the failure scenarios used a local HTTP stand-in |
| Restore from backup as an operational procedure | Not executed | Backup copies verify, but recovery time and procedure correctness are unproven |
| Load, soak, multi-user concurrency at scale | No tests or tooling | Capacity of the single-node design is unknown |
| Two service processes on one store | Only partially (architecture review showed divergence) | Supports GAP-018 |
| Release workflow publishing to GHCR | No tag pushed | Release path unexercised |
| Isolation between two organisations | No multi-tenant design | Cannot be claimed |
| Independent human review | Out of scope for this session | All reviewers were AI agents of the same family |
