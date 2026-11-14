# Autology — maturity scorecard

*14 November 2026 at `dfe8b3f`. Two separate assessments, as the master instructions require: (A) the Autology
platform itself and (B) each use case. Neither may be awarded without evidence.*

## 1. Platform maturity

**Last independently verified score: 47 / 100** (audit of 13 November, [`audit/03`](../audit/03_AUTOLOGY_MATURITY_SCORECARD.md)).
**Current self-assessment: ≈ 65 / 100, not independently verified.** It was made by the same AI agent that wrote the
R1 fixes, with the audit's own method:
- the same subcriteria, weights and evidence caps (A up to 100 %, B 80 %, C 40 %, NV 25 %);
- credit restored only where the cause of a deduction was removed and a test in CI shows it.

The R1-C increment (per-workspace credential scope, headless engine) strengthens 4.2 and 5.4 a little but does not
change the rounded total, so none is claimed.

| # | Subcriterion | Max | Audit | Now | Why |
|---|---|---|---|---|---|
| 1.1 | Ontology model and validation | 8 | 5.5 | 6.4 | GAP-016 fixed (capped at 80 % for B evidence); GAP-027/028 open |
| 1.2 | Agent engine | 8 | 5.5 | 6.0 | GAP-017 fixed; no real-model evidence; GAP-029 open |
| 1.3 | State, persistence, recovery | 6 | 2.5 | 4.2 | Intent journal, typed outputs, one writer; GAP-041 open |
| 1.4 | Maintainability | 4 | 2.0 | 2.0 | Unchanged; the service grew (GAP-026) |
| 1.5 | Agnosticism | 4 | 3.0 | 3.0 | Unchanged; one provider adapter |
| 2.1 | Governance across entry points | 8 | 4.0 | 6.4 | GAP-011/012/013 fixed, D4 intersection, entry-point matrix |
| 2.2 | Auditability | 5 | 3.0 | 3.7 | GAP-014 and GAP-007 fixed; GAP-020 open |
| 2.3 | Test depth | 5 | 3.5 | 3.9 | Fault-injection and entry-point matrices; no load tests |
| 2.4 | Quality gates | 2 | 0.5 | 0.6 | Licence gate added; still no mypy, linting, vulnerability audit |
| 3.1 | Outbound execution reliability | 8 | 1.0 | 5.6 | Core requirement met against a simulated bank; no real ERP; no automated confirmation polling |
| 3.2 | Recovery and reconciliation | 4 | 0.5 | 2.8 | Recovery and reconciliation API |
| 3.3 | Inbound integration | 4 | 3.0 | 3.0 | Unchanged |
| 3.4 | Consistency under concurrency | 4 | 1.0 | 2.8 | GAP-008 and GAP-009 fixed; write-back not atomic |
| 4.1 | Authentication | 4 | 3.0 | 3.0 | Per-workspace OIDC added; GAP-019/030 open |
| 4.2 | Authorization and data protection | 4 | 2.0 | 2.8 | GAP-011/012/013 fixed; no encryption at rest (D3) |
| 4.3 | Input hardening | 2 | 0.5 | 1.1 | GAP-015 fixed; GAP-038 open |
| 4.4 | Deployment, backup, observability | 5 | 3.0 | 3.0 | Unchanged; restore never exercised |
| 5.1 | Real end-to-end process | 5 | 0.5 | 0.5 | None yet |
| 5.2 | Real AI provider validation | 2 | 0.0 | 0.0 | None yet |
| 5.3 | Legal and distribution | 3 | 1.0 | 1.8 | Licence and notices; legal sign-off and a real release pending |
| 5.4 | Reuse and isolation | 3 | 1.0 | 1.8 | Organisation isolation built and tested; no real external system |
| 5.5 | Documentation and support | 2 | 1.0 | 1.0 | Unchanged |
| | **Total** | **100** | **47.0** | **≈ 65** | |

| Score | Audit | Self-assessed now |
|---|---|---|
| A — Technical framework | 59 | 72 |
| B — Enterprise operational readiness | 44 | 71 |
| C — Commercial product readiness | 41 | 47 |
| **Overall** | **47** | **≈ 65 (not independently verified)** |
| Use case / workspace readiness (scorecard of §10 of the instructions) | not measurable | **not yet measurable** (REL-3, R2) |

## 2. What prevents a 95 / 100 rating

A score is earned by passing gates, not by adding points. The audit's gates
([`audit/05` §3](../audit/05_AUTOLOGY_ROADMAP_TO_95.md)) stand:

| Gate | Criterion | Status | Needs |
|---|---|---|---|
| 80 | 80.1–80.4, 80.6, 80.8 (safety, authorisation, strict schema, suite) | Met in the repository | Independent re-verification |
| 80 | 80.5 no open Critical/High defect | Critical: none. High: residuals of GAP-009/018 (lower risk) | R3 hardening |
| 80 | 80.7 licence and legal sign-off | Files and CI check in place | **Counsel** (external) |
| 90 | 90.2 restore drill measured | Not done | R6 (OPS-1) |
| 90 | 90.3 two real AI providers validated | Not done | **Model API keys** (D7) |
| 90 | 90.4 one real end-to-end process | Not done | **A customer process and system access** |
| 90 | 90.5 first ERP adapter validated against a real test instance | Not done | **Odoo 18 sandbox** (D6) |
| 90 | 90.6 capacity known (load test) | Not done | Agreed targets |
| 90 | 90.7 mypy, linting, dependency audit in CI | Not done | QA-1 (R2) |
| 95 | 95.2 second ontology with a different real system, no core change | Not done | Second customer |
| 95 | 95.3 customer isolation demonstrated in the chosen deployment model | Built and tested in the repository | Demonstration in a real deployment |
| 95 | 95.4 external penetration test and code review | Not done | **External** |
| 95 | 95.5 production pilot evidence | Not done | **Customer, owner authorisation** |
| 95 | 95.6 published release, upgrade tested, support process | Not done | R6 |
| 95 | 95.7 documentation matches behaviour (docs-claims check in CI) | Partial (stale claims fixed by hand) | R6 |

**Domain 5 (real-world validation, 15 points)** scores 5.1 and can rise only with external evidence: a pilot, real
models, a legal sign-off and a published release. A repository-only effort cannot pass gates 90 or 95.

## 3. Use-case maturity

**Not yet measurable.** The use-case scorecard (REL-3, R2) will measure the six dimensions of the instructions (§10)
with, for each metric: its formula, denominator, target, evidence source, confidence, responsible reviewer and
refresh trigger. The starting weights are:

| Dimension | Points |
|---|---:|
| Ontology and business process coverage | 20 |
| Data quality, provenance and completeness | 15 |
| Agent design and evaluation | 15 |
| Governance, organisational responsibilities and security | 20 |
| Connector readiness and transactional reliability | 15 |
| Operational tests, monitoring and recovery | 15 |

The weights are adjusted, with the reasons documented, for each industry's safety criticality. It builds on
`scoring.py` (today: a deployment score 0–100 with roadmap gates) rather than a competing framework. Server-side
gates (REL-2) block promotion whatever the score.
