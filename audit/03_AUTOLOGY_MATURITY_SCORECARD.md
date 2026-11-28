# 03 — Autology maturity scorecard

## Result

| | Score |
|---|---|
| **Overall product maturity** | **47 / 100** |
| Score A — Technical framework maturity | **59 / 100** |
| Score B — Enterprise operational readiness | **44 / 100** |
| Score C — Commercial product readiness | **41 / 100** |

This is lower than the PDF-based preliminary estimate of 60. The difference is not caused by missing features —
the repository contains more than the PDF describes — but by evidence produced during this audit: Autology can
execute an external action twice, or report an action as done when it was only accepted, and it has never been
run against a real business system or a real AI model.

**Confidence.** High for the deductions (each confirmed defect was executed and reproduced by the lead auditor).
Medium-high for the credits (backed by 408 passing tests and several real-system checks). Lower for anything
marked NV. The audit was performed by AI agents, one of which wrote the code; an independent human review could
move individual subscores by a few points either way, but not across a gate.

## Method

1. Subcriteria and weights were fixed before scoring (tables below).
2. Points are awarded only for evidence. Evidence class caps the credit for a subcriterion: **A** up to 100%,
   **B** up to 80%, **C** up to 40%, **D** 10%, **E** 0, **NV** up to 25% where the code exists.
3. Each confirmed defect deducts from the subcriterion it affects, in proportion to severity.
4. Internal readiness scores of the example deployments (95–100) and comparisons with Palantir are **not** used.
5. Coverage percentages are not maturity: they are one input to subcriterion 2.3 only.

## Domain 1 — Software architecture and core framework (30)

| # | Subcriterion | Max | Earned | Basis |
|---|---|---|---|---|
| 1.1 | Ontology model, validation, versioning, export | 8 | 5.5 | Rich model with functions, aliases, modules, eight rule kinds (B). Deducted: misspelled keys silently accepted, one dropped every precondition of an action (GAP-016, −1.5); JSON-LD crash, lossy export (GAP-027, −0.5); diff blind spots (GAP-028, −0.5) |
| 1.2 | Agent engine: planning, re-planning, reasoning, delegation, LLM robustness | 8 | 5.5 | Real run-time planning and re-planning, delegation, cost-aware tool choice (B); invalid model outputs never execute (B, fake models). Deducted: no real-model evidence (NV, −1.5); adapter exception escapes the fallback (GAP-029, −0.5); missing linked entity defaults to its initial state (GAP-017, −0.5) |
| 1.3 | State, persistence and recovery semantics | 6 | 2.5 | Atomic run saves, schema upgrades, newer schema refused (B). Deducted: no intent log (GAP-007), unchecked tool output types make the service unable to restart (GAP-010), in-memory graph never refreshed (GAP-018), ad-hoc migrations outside a transaction (GAP-041) |
| 1.4 | Maintainability | 4 | 2.0 | Acyclic, layered core (+). Deducted: 1,232-line service god object, complexity up to 111, 36 grade D–F functions, 165 mypy errors |
| 1.5 | Domain, model and system agnosticism | 4 | 3.0 | Same core runs six unrelated ontologies; no domain vocabulary in code (B). Deducted: chat contract shaped on one vendor's message format; only one provider adapter; hard-coded escalation roles |
| | **Total** | **30** | **18.5** | |

## Domain 2 — Governance and software quality (20)

| # | Subcriterion | Max | Earned | Basis |
|---|---|---|---|---|
| 2.1 | Governance enforcement across all entry points | 8 | 4.0 | Broad rule set, fail-closed evaluation, review integrity on direct paths, tool write validation (B). Deducted: self-review bypass via automation (GAP-011), hidden-field leak via scenarios (GAP-012), agent acting on records the requester cannot see (GAP-013) |
| 2.2 | Auditability and traceability | 5 | 3.0 | HMAC chain verifies after crash/restart, recorded heads, approvals bound to what reviewers saw (B). Deducted: unchained run-record fields allow skipping a review (GAP-014), in-flight external calls not recorded (GAP-007), rule fingerprint not recorded on resume (GAP-020) |
| 2.3 | Test depth and relevance | 5 | 3.5 | 408 tests, 0 skipped, 97.0% line / 93.3% branch, two Python versions, real PostgreSQL in CI. Deducted: no failure-injection tests for side effects, no load tests, one test asserts the defective behaviour (GAP-004) |
| 2.4 | Engineering quality gates | 2 | 0.5 | Coverage gate and no-skip rule in CI (+). No type checking, linting or dependency scanning in CI |
| | **Total** | **20** | **11.0** | |

## Domain 3 — Operational integrations (20)

| # | Subcriterion | Max | Earned | Basis |
|---|---|---|---|---|
| 3.1 | Outbound execution reliability: confirmation, idempotency, uncertain state | 8 | 1.0 | Timeouts, retries and escalation on clear failures exist. **Failed the core requirement**: duplicates after timeouts (GAP-001), no idempotency key (GAP-002), fallback double-execution (GAP-003), any 2xx treated as confirmed (GAP-006) |
| 3.2 | Recovery and reconciliation | 4 | 0.5 | Audit survives crashes. No reconciliation mechanism; duplicates on resume and retry (GAP-004, GAP-005) |
| 3.3 | Inbound data integration and connectors | 4 | 3.0 | Ingestion with checks, quarantine, watermarks, lineage; PostgreSQL validated (A). No ERP connector (E) |
| 3.4 | Consistency with systems of record under concurrency | 4 | 1.0 | Write-back conflict detection exists (B). Concurrent runs both execute (GAP-008); stale snapshots after review (GAP-009) |
| | **Total** | **20** | **5.5** | |

## Domain 4 — Security and infrastructure (15)

| # | Subcriterion | Max | Earned | Basis |
|---|---|---|---|---|
| 4.1 | Authentication | 4 | 3.0 | OIDC validated with Keycloak and a real browser; 12 forgery attempts refused (A); hashed API tokens. Deducted: removed IdP keys stay trusted (GAP-019); no API-token expiry or rotation, no rate limiting (GAP-030) |
| 4.2 | Authorization and data protection | 4 | 2.0 | Row, field and checkpoint rules on most paths (B). Deducted: GAP-011, GAP-012, GAP-013; no encryption at rest (GAP-034) |
| 4.3 | Input hardening and denial of service | 2 | 0.5 | Body limit and strict JSON parsing exist. Deducted: unauthenticated memory exhaustion (GAP-015); expression repetition DoS (GAP-038) |
| 4.4 | Deployment, backup/restore, observability | 5 | 3.0 | Container lifecycle validated in CI (A); verified online backups (B); Prometheus and BI integrations (A). Deducted: restore never exercised (NV); single node, no HA; unpinned builds (GAP-040) |
| | **Total** | **15** | **8.5** | |

## Domain 5 — Real-world validation and commercial readiness (15)

| # | Subcriterion | Max | Earned | Basis |
|---|---|---|---|---|
| 5.1 | A real end-to-end business process against real external systems | 5 | 0.5 | None. Real infrastructure (PostgreSQL, Keycloak, Metabase, Prometheus) only; business tools are simulated |
| 5.2 | Real AI provider validation | 2 | 0.0 | NV: never run with a real model |
| 5.3 | Legal and distribution readiness | 3 | 1.0 | Wheel, image and release workflow exist (release never run, C). **No licence** (GAP-031); LGPL component bundled in the image needs a decision |
| 5.4 | Reuse across customers and isolation | 3 | 1.0 | Six ontologies on one core (B), none with a real external system; no organisation isolation within a deployment (E) |
| 5.5 | Documentation, onboarding, support | 2 | 1.0 | Extensive docs (some stale: GAP-043); no administration UI for users and config, no support or SLA process |
| | **Total** | **15** | **3.5** | |

## Overall

| Domain | Max | Earned |
|---|---|---|
| Software architecture and core framework | 30 | 18.5 |
| Governance and software quality | 20 | 11.0 |
| Operational integrations | 20 | 5.5 |
| Security and infrastructure | 15 | 8.5 |
| Real-world validation and commercial readiness | 15 | 3.5 |
| **Total** | **100** | **47.0** |

## Scores A, B and C

Each is a weighted view of the same subscores (normalised to 100), defined before calculation:

| Score | Composition | Result |
|---|---|---|
| A — Technical framework | 60% Domain 1 (61.7%) + 20% test depth and gates 2.3–2.4 (57.1%) + 20% governance and audit 2.1–2.2 (53.8%) | **59** |
| B — Enterprise operational readiness | 40% Domain 3 (27.5%) + 30% Domain 4 (56.7%) + 30% governance and audit 2.1–2.2 (53.8%) | **44** |
| C — Commercial product readiness | 60% Domain 5 (23.3%) + 20% deployment 4.4 (60%) + 20% agnosticism 1.5 (75%) | **41** |

## Confirmed defects versus unverified risks

| Confirmed (executed) | Unverified risks (not executed) |
|---|---|
| GAP-001 – 018, 019, 020, 021, 022, 027, 029 (see 01 and 04) | Real-model behaviour and cost; real ERP behaviour; restore procedure; load and capacity; MCP `what_if` leak path (code reading); notification templates exposing restricted fields (code reading); behaviour of two server processes on one store beyond the stale-graph observation |

## What prevents a higher rating

| Blocking condition | Gate | Status |
|---|---|---|
| Zero externally executed actions falsely reported as confirmed successes | 80 | **Fails** (GAP-006) |
| No duplicate external execution after timeout, crash or retry | 80 | **Fails** (GAP-001–005) |
| Zero unauthorized actions in the security test suite | 80 | **Fails** (GAP-011, 012, 013) |
| No known unresolved critical vulnerabilities | 80 | **Fails** (six Critical) |
| Complete traceability for critical decisions, including in-flight actions | 80 | **Fails** (GAP-007, 014) |
| A licence that allows customers to use the software | 80 | **Fails** |
| Verified restore procedure | 90 | Not verified |
| At least one real end-to-end operational process | 90 | Not done |
| Real AI provider validated | 90 | Not done |
| Second ontology with a different real external system, no substantial core change | 95 | Not done |
| Customer isolation demonstrated under the chosen deployment model | 95 | Not decided, not done |
| Independent (human or third-party) security review | 95 | Not done |

The full gate definitions are in [05](05_AUTOLOGY_ROADMAP_TO_95.md).
