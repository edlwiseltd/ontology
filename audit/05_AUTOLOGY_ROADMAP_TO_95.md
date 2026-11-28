# 05 — Roadmap to a verified 95 / 100

Current verified score: **47 / 100** (see [03](03_AUTOLOGY_MATURITY_SCORECARD.md)). The plan below fixes proven
defects first, reuses the existing architecture, and adds evidence only reality can provide (pilots, real models,
independent review). It deliberately avoids rewrites: the layered core, governance model, audit chain and
ingestion are kept; the execution path gains one missing concept — **the uncertain external action**.

Effort figures are planning estimates (see [04](04_AUTOLOGY_GAP_REGISTER.md) for assumptions), in
engineer-days (d).

## 1. Decisions the product owner must take first

| ID | Decision | Options | Recommendation | Blocks |
|---|---|---|---|---|
| D1 | Deployment model | (a) one deployment per customer, (b) shared multi-tenant service | (a) for the first customers: isolation by construction, no tenant code; revisit when a hosted offer is planned | GAP-044, gate 95 isolation criterion |
| D2 | Operational store | SQLite single node; PostgreSQL | SQLite for pilots with proven restore; PostgreSQL when a customer needs HA, more than one replica, or volumes the load test shows SQLite cannot carry | GAP-055 |
| D3 | Encryption at rest | Platform volume encryption; database-level encryption | Platform encryption, documented as a deployment requirement | GAP-034 |
| D4 | Whose authority does a run use? | Requester ∩ agent roles; refuse cases with hidden rows; explicit service mode | Requester ∩ agent for user-started runs; explicit, audited service identity for automations | GAP-013 |
| D5 | Licence and distribution | Proprietary EULA; open source (e.g. Apache-2.0); dual | Decide with legal counsel, including the LGPL component in the image | GAP-031 |
| D6 | First ERP and pilot | e.g. Odoo 18 Enterprise with a named customer process | One process with clear, reversible test transactions (e.g. sales order → invoice in a test database); confirm the customer's Odoo plan allows external API access | GAP-032, GAP-053 |
| D7 | Supported AI providers | One; two or more | Two (to prove provider independence), plus "no model" (planner only) | GAP-029, GAP-052 |
| D8 | Default for actions without a declared side-effect type | idempotent; non-idempotent | Non-idempotent (safe default: never auto-retry an unknown outcome) | GAP-001 |

## 2. Execution sequence

### Phase 1 — Safe external execution (P0 integrity) · ≈ 25–37 d (sum of item estimates; shared design may reduce it)

Order matters: the intent log is the foundation the other fixes rely on.

1. **GAP-007** Intent log: persist `step.intent` (with idempotency key) in the store and audit chain before each
   external call; `step.result` after.
2. **GAP-002** Idempotency keys derived from (run, step, action, instance), sent as header and payload.
3. **GAP-006** Confirmation contract per action and new step/run states `uncertain` and `pending_confirmation`;
   API, inbox, metrics and reports show them; a reconciliation job and an optional `confirm` tool resolve them.
4. **GAP-001, GAP-003** Outcome classification (*not sent* / *rejected* / *unknown*); no retry or fallback after
   *unknown* for non-idempotent actions (D8).
5. **GAP-004, GAP-005** Decide-then-execute ordering; resume, deferred tick and automation retry continue from the
   intent log and never re-execute; replace the test that asserts the old behaviour.
6. **GAP-008, GAP-009** Per-record run leases; re-validation of live data on resume; atomic write-back.
7. **GAP-010, GAP-017** Type-check tool outputs; absent entities are unknown, not "initial state".

**Verification:** a fault-injection suite (new `tests/test_external_effects.py`) running every combination of
{timeout after commit, reset after commit, 5xx after commit, refused, 202, empty body, failure body} ×
{idempotent, non-idempotent} × {inline, after review, deferred, automation} × {no crash, crash before save,
crash after save}, asserting zero duplicate executions and zero false confirmations. The audit's scripts in
`audit/evidence/reliability/` become regression tests.

### Phase 2 — Governance closure (P0 security) · ≈ 8–10 d

GAP-011, 012, 013 (per D4), 014, 015, 016, 018 (short-term lock), 031 (per D5).

**Verification:** a security regression suite made from every PoC in `audit/evidence/security/` and
`audit/evidence/auditor/`, plus an entry-point matrix test: each permission × each REST route, MCP tool, chat tool,
CLI command, automation and pipeline, asserting refusals.

### Gate 80 review

### Phase 3 — Enterprise hardening and real-world proof · ≈ 41–60 d plus pilot time

- **Evidence:** GAP-052 real-model eval suite on two providers (D7); GAP-033 automated restore drill with measured
  recovery time; GAP-024 load test against agreed targets; GAP-049 executed release.
- **Hardening:** GAP-019, 020, 021, 022, 023, 025 (mypy, linting and dependency audit in CI), 029, 030, 035, 037,
  038, 040, 041, 045, 047, 048, 057.
- **First ERP:** GAP-032, an `autology-odoo` package (tools with idempotency via a uniquely constrained request
  reference and read-back confirmation; an ingestion source), validated on an Odoo 18 test database.
- **Pilot:** GAP-053, one real process for an agreed period on the customer's test or staging system, then
  production with limits.

### Gate 90 review

### Phase 4 — Productization and independent assurance · ≈ 20–35 d, plus 15–25 d if an ontology editor is needed, plus external time

- A second ontology with a **different** real external system (e.g. a CRM or another ERP) to prove reuse.
- Customer isolation demonstrated under D1.
- GAP-054 independent penetration test and code review.
- GAP-051 administration (users, roles, pipelines without restarts); GAP-026 service split as needed.
- GAP-043 docs; operator runbooks, support and incident process; GAP-056 editor if the target buyers need it.

### Gate 95 review

## 3. Maturity gates

A gate is passed only when **every** criterion has evidence. "Repo" means it can be verified from the repository
and CI; "External" needs a live system, customer or independent party.

### Gate 80 — safe for a supervised pilot

| # | Criterion | Measure | Verifiable |
|---|---|---|---|
| 80.1 | No externally executed action falsely reported as confirmed | Fault-injection suite: 0 false confirmations | Repo |
| 80.2 | No duplicate external execution after timeout, crash, retry, fallback, resume or concurrency | Fault-injection suite: 0 duplicates for non-idempotent actions | Repo |
| 80.3 | Every in-flight external action is traceable after a crash | Crash at every save point → every call visible with key and state | Repo |
| 80.4 | Zero unauthorized actions or disclosures | Security regression suite and entry-point matrix: 0 failures | Repo |
| 80.5 | No known open Critical or High defect | Gap register | Repo |
| 80.6 | Strict ontology validation | Every documented key misspelled once → load fails | Repo |
| 80.7 | Licence and third-party notices in place | Files present; legal sign-off on distribution | Repo + External (legal) |
| 80.8 | Existing suite still green | 408+ tests, 0 skipped, CI on 3.10 and 3.13 | Repo |

### Gate 90 — ready for a production pilot

| # | Criterion | Measure | Verifiable |
|---|---|---|---|
| 90.1 | Gate 80 criteria still hold | CI | Repo |
| 90.2 | Restore verified | Automated drill: backup → fresh volume → start → all chains verify; recovery time measured and documented | Repo |
| 90.3 | Real AI providers validated | Eval suite on two providers: pass rate ≥ agreed target, 0 invalid actions executed, cost and latency published | External (API access) |
| 90.4 | One real end-to-end process | Pilot report: N transactions (agreed with the customer), 0 duplicates, 0 false confirmations, all uncertain actions reconciled, reviewer times | External (customer) |
| 90.5 | First ERP adapter validated | Adapter test suite against a real Odoo (or chosen ERP) test instance, including fault injection | External (test instance) |
| 90.6 | Capacity known | Load test meets agreed targets on the reference deployment | Repo + environment |
| 90.7 | Static quality gates | mypy and linting clean in CI; dependency audit with no known High vulnerabilities | Repo |
| 90.8 | All P1 items rated High closed | Gap register | Repo |

### Gate 95 — commercially distributable product

| # | Criterion | Measure | Verifiable |
|---|---|---|---|
| 95.1 | Gate 90 criteria still hold | | |
| 95.2 | Reuse proven | A second ontology with a different real external system runs with no changes to core modules beyond generic, reviewed extension points (diff of `autology/` core reviewed) | External + Repo |
| 95.3 | Customer isolation | Demonstrated under the D1 model (per-customer deployment: separate data, keys and configuration verified; or multi-tenant isolation tests) | Repo + environment |
| 95.4 | Independent assurance | External penetration test and code review: no open Critical or High findings | External |
| 95.5 | Production evidence | A pilot in production for an agreed period with 0 duplicates, 0 false confirmations, 0 unauthorized actions | External (customer) |
| 95.6 | Release and support | A tagged release published and installed from the registry; upgrade from the previous release tested; support and incident process documented | Repo + External |
| 95.7 | Documentation matches behaviour | Docs-claims checklist passes; no stale statements | Repo |

## 4. What each phase is expected to change

Scores are only awarded after the gate review. As a planning indication, closing Phase 1 and 2 removes the
deductions behind the integration, governance and audit subscores, but does not add real-world evidence; Domain 5
(15 points) and parts of Domains 3 and 4 can only be earned in Phases 3 and 4. A repository-only effort, however
thorough, cannot pass gate 90 or 95.

## 5. What not to do

- Do not rebuild the planner, governance model or audit chain: they held up under attack.
- Do not build multi-tenancy, Kubernetes manifests or a PostgreSQL store before D1/D2 say they are needed.
- Do not start the Odoo adapter before Phase 1: without intent logs, idempotency and confirmation, an ERP adapter
  would inherit the duplicate-execution defects.
- Do not count coverage or example readiness scores as maturity evidence.
