# 01 — Autology code audit

| | |
|---|---|
| Audited revision | `fdfaf01c35d628db794ca761b43992eb62bd7418` on branch `claude/autology-ontology-agent-4ajjer` (13 Nov 2026) |
| Method | Source inspection, full test run with branch coverage, 30+ purpose-built proof-of-concept and scenario scripts executed against the code, live checks against real PostgreSQL, Keycloak, Metabase, Prometheus and Docker |
| Evidence | [`audit/evidence/`](evidence/): every script and its captured output. Re-run any with `cd <repo> && PYTHONPATH=. AUTOLOGY_AUDIT_KEY=k python3 audit/evidence/<dir>/<script>.py` |
| Classification | A real-world validated · B automated-test validated · C implemented, insufficiently validated · D documented only · E missing · NV not verifiable here |

> **Independence statement.** The code was written in this same working session by the same AI assistant that
> led this audit. To limit self-assessment bias, three separate reviewer agents (security, reliability,
> architecture) were given the code and the audit brief but *not* the author's conclusions, and every defect they
> reported as confirmed was re-executed by the lead auditor before inclusion. They are still the same model
> family; a human or third-party review remains necessary before any external claim (see 03, gate 95).

## 1. Repository inventory

| Item | Count / fact | Evidence |
|---|---|---|
| Branches | `claude/autology-ontology-agent-4ajjer` (all Autology work, 46 commits, 27 Sep – 13 Nov 2026); `claude/new-session-aee75a` (3 commits of unrelated video-tool notes, an ancestor of the main branch) | `git branch -a`, `git merge-base --is-ancestor` |
| Framework package | 35 modules, 12,913 lines (SLOC 10,226), plus a web inbox of 779 lines (HTML/JS/CSS) | `wc -l autology/*.py`; radon raw |
| Runtime dependencies | none (standard library). Optional extras: `llm` (anthropic), `yaml`, `postgres` (psycopg) | `pyproject.toml` |
| Tests | 44 test modules, 408 test methods, 7,590 lines | `grep -c "def test_"`; test run |
| CLI commands | 21 | `python -m autology --help` |
| REST routes | 50 API routes + 4 static files (49 documented; `GET /api/runs/{id}/outcomes` undocumented) | `server.py` `_dispatch` lines 1405–1518 |
| Examples | 6 deployments in 6 domains: customer onboarding, manufacturing, care referral, aerospace scheduling, order fulfilment, motor insurance | `examples/` |
| Deployment | Dockerfile, compose example, Prometheus config, smoke test, CI (tests on Python 3.10 and 3.13 with PostgreSQL; wheel + Docker smoke job), release workflow | `.github/workflows/`, `deploy/` |
| Licence | **none** (no LICENSE file, no licence metadata) | `ls LICENSE*` |

### Module map (actual architecture)

```
foundation   expressions · audit · economics · tracing · oidc            (no internal imports)
model        ontology → expressions;  state · versioning · lint · export → ontology;  graph → ontology, expressions
policy       governance → ontology, state;  planner → governance, state;  tools;  reasoners → ontology;  impact
agent        agent → audit, governance, ontology, planner, reasoners, state, tools
features     reporting · scoring · persistence · scenarios · scheduling · automation · ingest · adapters · evals · sdk
service      store → agent, audit, graph;  views;  server (fan-out 19);  chat, mcp, warehouse → server (lazy)
entry        __main__ (21 commands), __init__
```

The core (ontology → governance → planner → agent → audit) never imports the service layer; there is no import
cycle among top-level imports. One lazy cycle exists (`chat`/`warehouse` → `server` for `ApiError`/`User`).
Evidence: `audit/evidence/architecture/inventory.py`.

| Module | Lines | Responsibility |
|---|---|---|
| server.py | 1566 | REST service: auth, SSO, visibility, objects, runs, reviews, scenarios, chat, ingestion, reporting, scheduler (`AutologyService`: 87 methods) |
| ontology.py | 1044 | Ontology model, loading, modules, validation, functions, aliases |
| scheduling.py | 846 | Job-shop scheduling (built-in and OR-Tools CP-SAT) |
| store.py | 690 | SQLite store: graph, runs, append-only audit, reviews, ingestion, lineage, backup |
| agent.py | 626 | Agent loop: observe → plan → reason → govern → act → re-plan; retries, fallbacks, deferral, reviews |
| ingest.py | 601 | Data pipelines, type coercion, checks, quarantine, watermarks, lineage |
| sdk.py | 553 | Generated Python/TypeScript clients |
| __main__.py | 530 | CLI |
| chat.py | 447 | Governed assistant |
| scoring.py | 424 | Readiness scorecard |
| evals.py | 382 | Reasoner evaluation suites |
| reasoners.py | 374 | Provider-neutral `ChatModel`, `LLMReasoner`, Anthropic adapter, routing |
| scenarios.py | 367 | What-if sandboxes |
| reporting.py | 337 | Metrics, compliance report, outcome analysis |
| oidc.py | 329 | OpenID Connect verification (RSA in the standard library) |
| warehouse.py | 316 | Governed BI export, Prometheus metrics |
| expressions.py | 302 | Safe rule/expression language (AST whitelist, three-valued logic) |
| governance.py | 299 | Rule enforcement |
| automation.py | 285 | Triggers on change/schedule/deadline |
| graph.py | 273 | Knowledge graph, case templates, write-back |
| adapters.py | 271 | Declarative python/http/table tools, approvers, reasoner loading |
| versioning.py | 226 | Semantic diff, semver checks |
| (13 more) | 1,960 | state, tracing, impact, planner, export, views, audit, mcp, economics, lint, tools, persistence, `__init__` |

## 2. Verified capabilities

| Capability | Class | Evidence |
|---|---|---|
| Ontology: entities, typed attributes, states, relationships, actions (preconditions, outcomes, effects, computed effects), goals, 8 rule kinds, functions, aliases, interfaces, modules | B | test_core, test_functions, test_aliases, test_engineering; validation of 8 deep-freeze mutations (architecture review) |
| Safe expression language (no code execution) | B | AST whitelist probes; security and architecture reviews found no escape |
| Knowledge graph + competency questions with expected answers | B | test_core, `validate --data` on all examples |
| Semantic diff + semver enforcement | B (with blind spots, GAP-028) | test_versioning_breaking; `diff` exit 3 verified |
| Turtle export | B | all 6 examples parsed by rdflib (208–496 triples) |
| JSON-LD export | **C/defect** | crashes on `examples/auto_insurance` (GAP-027) |
| Planner with re-planning, multi-instance cases, delegation | B | test_agent, test_multi_instance, test_planner_budget |
| LLM reasoner falls back to planner on invalid output | B (fake models) / **NV** with a real model | `evidence/reliability/s06_llm.py`: malformed JSON, unknown action, invalid action, exception, non-object all fell back; no API key available |
| Governance: mandatory steps, prohibitions, human review, data/row/action/write access, checkpoints, suspension | B, **with confirmed bypasses** (GAP-011/012/013) | test_governance_extras, test_visibility, test_review_integrity; `evidence/security/` |
| Asynchronous human reviews; self-review refused on the direct path; double decision prevented | B | poc01 (direct path 403), s11d (concurrent decide: one 200, one 409) |
| HMAC-keyed hash-chained audit, recorded heads, verification after crash/restart | B | test_audit_integrity; s09_10, s14 (verifies after SIGKILL and restart) |
| REST API with token auth and 6 permissions | B | test_platform, test_operations |
| Company sign-in (OIDC, PKCE, group mappings) | **A** | Keycloak 26 + headless Chromium sign-in to the inbox (Tier 3 work log); 12 forgery attempts refused (poc03) |
| Data ingestion (CSV/JSON/JSONL/SQL/HTTP/push), quarantine, watermarks, lineage | **A** for PostgreSQL source, B otherwise | test_ingest incl. live PostgreSQL in CI |
| Governed reporting DB for BI | **A** | Metabase 0.56 read the export; PostgreSQL target in CI |
| Prometheus metrics | **A** | Prometheus 3.5 scraped it (direct and via compose) |
| Docker image, graceful stop, restart with data intact, online verified backup | **A** (container lifecycle) | `deploy/smoke_test.sh`, run locally and in CI run 43455793202 (green) |
| Restore from backup | **NV** (documented, not executed as a procedure) | deployment.md |
| Release workflow (GHCR + GitHub release) | C | never executed: no tag pushed |
| Automations, what-if scenarios, evals, SDKs (tsc/node compiled), MCP, governed chat, OTLP tracing | B (chat and MCP with scripted models; tracing without a real collector) | respective test modules |
| Scheduling with OR-Tools CP-SAT | B | test_scheduling with OR-Tools 9.15 installed |
| Idempotency, uncertain state, reconciliation for external actions | **E** | grep finds no such mechanism; s07_08, s09_10 |
| ERP connectors (Odoo or other) | **E** | grep for odoo/xmlrpc: none |
| Multi-tenancy / organisation isolation in one deployment | **E** | no tenant concept in code |
| Encryption at rest, rate limiting, API-token expiry/rotation | **E** | code inspection |
| Real LLM provider in operation | **NV** | no API key in the environment |

## 3. Capabilities absent from the historical PDF

The PDF (13 Nov 2026) predates Tier 3. Present now and absent from the PDF:

- Data ingestion pipelines with type and quality checks, quarantine, incremental watermarks that stop at rejected
  rows, and append-only per-object lineage (`ingest.py`, store schema 10); `ingest` permission; `autology ingest`.
- PostgreSQL support for ingestion sources and as a reporting target (tested in CI against PostgreSQL 16).
- Governed reporting database per audience (`warehouse.py`, `autology reporting`, `POST /api/reporting`).
- Prometheus metrics endpoint (`GET /api/metrics`).
- OpenID Connect SSO with PKCE inbox sign-in (`oidc.py`).
- Docker image, compose example, `autology backup` (online, verified), `--store` override, SIGTERM handling,
  smoke test in CI, release workflow; version 0.4.0.
- Test count rose from 355 to 408.

The PDF's limits "no data platform", "no single sign-on" and "SQLite on one machine" are partly addressed: data
can now be loaded and exported, SSO exists, but the operational store is still single-node SQLite.

## 4. Documentation versus implementation

| Claim | Source | Finding |
|---|---|---|
| Errors, refusals and invalid answers fall back to the planner | README, `LLMReasoner` | **Partial**: a non-API exception from the Anthropic client (`TypeError`) propagates (architecture review M3) |
| Export "so nothing is lost" | export.py docstring | **False**: JSON-LD crashes on computed effects; both formats omit functions, aliases, interfaces, impact rules, scheduling, case templates; Turtle and JSON-LD use different IRIs |
| Ontologies are validated | README, autology.md | **Partial**: misspelled keys are ignored. Verified: renaming `requires` to `requries` on `pay_claim` loads cleanly and silently drops its preconditions (`evidence/auditor/arch_spot.out`) |
| Date attributes are type-checked | platform.md:83 | **False**: `'not-a-date'` passes |
| "No connectors, pipelines … or lineage" | ontology-concepts.md | **Stale** (Tier 3 added them) |
| "122 tests" / "one instance per entity per case" | methodology.md:94, autology.md:81 | **Stale** |
| HTTP tool failures trigger the failure policy (retry, fallback) | adapters.py docstring | **True, and harmful** for non-idempotent actions (GAP-001, GAP-003) |
| Server refuses to start without an audit key | platform.md, deployment.md | True (but the store is opened and seeded before the check) |
| `score --min-score`, `diff` exit codes, backup exit 2, atomic reporting swap, 1 MB body limit | README, docs | True, except the body limit can be bypassed with a negative `Content-Length` (GAP-015) |

## 5. Confirmed defects (executed and reproduced)

Severity is for a deployment that executes real external actions. Each was reproduced by the lead auditor.
Full register with remediation: [04](04_AUTOLOGY_GAP_REGISTER.md).

| ID | Defect | Sev. | Evidence |
|---|---|---|---|
| GAP-001 | A timeout or dropped connection after the external system acted is treated as "not done" and retried: 3 identical payments, run reported as failed | Critical | `reliability/s07_08_http.py` → "external calls received: 3" |
| GAP-002 | No idempotency key or run/step id is sent to external systems | Critical | same → "any idempotency/run/case id in payload: False" |
| GAP-003 | A fallback tool runs after an ambiguous failure: both providers pay | Critical | `s07b_fallback_timeout.py` → "bank A calls: 1 \| bank B calls: 1" |
| GAP-004 | Resuming after a review re-executes tools after a save failure or crash (review reopened, decided again, paid twice) | Critical | `s09_10_crash.py` 10a/10b |
| GAP-005 | Deferred-run resume and automation retry re-execute actions already performed | Critical | `s09_10_crash.py` 10c, `s10e_automation_retry.py` |
| GAP-006 | Any 2xx reply counts as confirmed success (`202 queued`, `{}`, `status: FAILED` in output → Payment `sent`) | Critical | `s07_08_http.py` 7d/7e/7h |
| GAP-007 | No write-ahead record of in-flight external calls: a crash leaves no trace of an executed payment | High | `s09_10_crash.py` 9a/9b/10d |
| GAP-008 | Two concurrent runs on the same record both execute; no conflict recorded | High | `s11_concurrency.py` → "statuses: ['completed','completed']", "external payment calls: 2" |
| GAP-009 | A run resumed after review acts on a stale snapshot; inconsistencies detected after the fact or not at all; write-back partial | High | `s11_concurrency.py` 11b/11c |
| GAP-010 | Tool outputs are not type-checked; one bad value prevents the service from restarting | High | `s05_input.py` → "RESTART FAILED: OntologyError … fraud_score must be number" |
| GAP-011 | Self-review bypass by firing an automation by hand; automation `when` ignored for manual firing | High | `security/poc01_automation_self_review.py` |
| GAP-012 | Fields hidden by `data_access`/checkpoints leak through scenario comparison | High | `security/poc02_scenario_compare_field_leak.py` → credit limit 250000 recovered |
| GAP-013 | Confused deputy: a user can start a run that acts on records they may not see (agent uses its own roles) | High | `auditor/s1_agent_acts_on_hidden_rows.py` → olivia (ops) ships EU order O-3 |
| GAP-014 | Run-record fields outside the HMAC chain (e.g. `pending_review.action`) can be edited to skip a review, undetected | High (requires write access to the store) | `reliability/s14_audit.py` |
| GAP-015 | Negative `Content-Length` bypasses the 1 MB limit without authentication (memory exhaustion) | Medium | `auditor/f3_content_length.py`; `security/poc04` (722 MB RSS from a 300 MB body) |
| GAP-016 | Misspelled ontology keys and unknown types are silently accepted (`requries` drops preconditions) | High | `auditor/arch_spot.out` |
| GAP-017 | A missing linked entity defaults to its initial state: claim approved and paid with amount `None` | High | `s05_input.py`, `s05b_denied.py` |
| GAP-018 | The server's in-memory graph is never reloaded: out-of-process `autology ingest` against a live store diverges (lost-update risk) | High | architecture review (two services on one store: 17 vs 14 instances) |
| GAP-019 | OIDC signing keys removed by the IdP stay trusted until restart | Low/Medium | `security/poc03_oidc.out` |
| GAP-020 | Ontology change while runs are paused: same version → new rules applied silently, fingerprint not recorded; version bump → paused runs stranded (409 forever) | Medium | `s13_ontology_change.py` |
| GAP-021 | HTTP timeout is per socket read (7.5 s observed for a 1 s timeout); the agent lock is held throughout, so one slow system blocks all runs of that agent | Medium | `s07b_fallback_timeout.py` |
| GAP-022 | One failing deferred run aborts the whole scheduler tick | Medium | `s10e_automation_retry.py`; server.py:648-659 |
| GAP-027 | JSON-LD export crashes on computed effects; IRIs differ between formats; Turtle breaks on identifiers with spaces | Medium | `auditor/arch_spot.out`; architecture review |
| GAP-029 | Anthropic adapter lets non-API exceptions escape the reasoner fallback | Medium | architecture review (TypeError reproduced) |

Further confirmed lower-severity items (GAP-030 onward) are in [04](04_AUTOLOGY_GAP_REGISTER.md).

## 6. Things that held up under attack

- Twelve OIDC forgery attempts (alg `none`, HMAC with the public key, foreign key under known/new `kid`, wrong
  issuer/audience, issuer prefix, missing/expired/string `exp`, future `nbf`, `crit` header) were all refused.
- Direct self-review is refused; two concurrent decisions on one review yield exactly one decision.
- Tool results that write undeclared fields or statuses are refused; invalid LLM outputs never execute.
- Rules over unknown facts fail closed for prohibitions and reviews; bad case data is rejected at the API.
- The audit chain verifies after SIGKILL and restart; edits to the parked state are detected; a wrong key fails closed.
- No `innerHTML` in the inbox (data inserted as text only); SQL watermarks are bound parameters; pipeline templates
  allow plain fields only.

## 7. Architecture assessment

**Strengths.** A clean, acyclic core with no domain vocabulary in executable code (scan in
`evidence/architecture/domainscan.py`); the same core runs six unrelated ontologies; a provider-neutral
`ChatModel` protocol for reasoners; a strictly sandboxed expression language; fail-closed rule evaluation for the
security-relevant rule kinds.

**Weaknesses.**
- The external-execution model assumes tools are either clearly done or clearly not done. There is no notion of
  "maybe done", no intent log, no idempotency, no confirmation contract and no reconciliation. This is the single
  largest architectural gap and the root of GAP-001 to 009.
- `AutologyService` is a 1,232-line god object; `_dispatch` has cyclomatic complexity 78 and `Ontology._validate`
  111. Average complexity is 5.8; 36 functions are grade D–F (radon).
- mypy reports 165 errors (403 strict); type checking is not in CI.
- State lives in two places (in-memory graph and SQLite) with no cache invalidation (GAP-018).
- The chat backend contract uses Anthropic's message shapes; reasoners are neutral but only Anthropic has an
  adapter and a price table.
- Escalation roles (`operations`, `security`, `it-integration`) are hard-coded.

## 8. Odoo 18 Enterprise

No Odoo connector exists (E). The existing extension points that can host one without Odoo logic in the core:

| Need | Existing interface | Fit |
|---|---|---|
| Execute actions in Odoo | `python` tool (`adapters.py` `import_target`): any callable receiving a `ToolCall` | Good: an adapter package can call Odoo's external API (e.g. `execute_kw` over XML-RPC/JSON-RPC with the standard library) |
| | `http` tool | Poor: it posts a fixed Autology payload; Odoo's RPC envelope needs a shim |
| Read Odoo data into the graph | `ingest` `push` source; `sql` source against a reporting replica | Workable; a pluggable source type (none exists today) would be cleaner |
| Confirmation and idempotency | **missing in the core** (GAP-001–007) | Must be fixed first: an Odoo adapter cannot make payments or postings safe on its own |

Recommended shape: a separate `autology-odoo` package (tools + ingestion source + example ontology), using an
Autology-generated request id stored in a uniquely constrained field of the Odoo record for de-duplication, and a
read-back (`search_read`) to confirm state before reporting success. Access to Odoo's external API depends on the
customer's Odoo hosting plan and must be confirmed with the customer (product-owner decision, see 05).

## 9. Infrastructure position

The operational store is still SQLite, single writer, one replica (deployment.md says so). This is acceptable for a
single-customer pilot with modest volumes **if** backup *and restore* are proven and the external-execution defects
are fixed. It is not acceptable for high availability or multiple customers in one deployment. PostgreSQL is used
only for ingestion sources and the reporting target. Whether to build a PostgreSQL store, multi-tenancy or
Kubernetes support should follow the deployment model the product owner chooses (05, decisions D1–D3), not be
assumed.
