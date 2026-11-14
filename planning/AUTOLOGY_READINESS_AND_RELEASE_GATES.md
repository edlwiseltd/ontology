# Autology — readiness and release gates

Two independent assessments, never merged into one number:

- **(A) Platform/engine maturity**: how good the product is. Measured by audit (method in
  [`../audit/03_AUTOLOGY_MATURITY_SCORECARD.md`](../audit/03_AUTOLOGY_MATURITY_SCORECARD.md)). Last measured:
  **47/100** (13 Nov 2026). Not re-measured since.
- **(B) Use-case readiness**: how ready one configured use case in one workspace is for its next environment.
  **Not yet measurable**: the scorecard below is designed, not implemented.

## 1. Use-case scorecard (design)

Weights are the instructions' starting point; each use case may revise them with a recorded rationale.

| Dimension | Points | Example metrics (formula / denominator / evidence source) |
|---|---:|---|
| Ontology and process coverage | 20 | competency questions answered as expected / declared (`validate`); processes with a goal and a reachable plan / processes in scope; lint errors = 0 |
| Data quality, provenance, completeness | 15 | rows accepted / rows loaded (ingestion batches); required attributes present / required; records with lineage / records |
| Agent design and evaluation | 15 | eval pass rate on the use case's suite (`evals.py`); invalid model actions executed = 0; agents with supervisor and tests / agents |
| Governance, organisation, security | 20 | consequential actions covered by a review or prohibition rule / consequential actions; PII fields guarded / PII fields; SoD violations = 0 |
| Connector readiness and transactional reliability | 15 | side-effecting capabilities with idempotency + confirmation / side-effecting capabilities; fault-injection suite pass rate |
| Operations, monitoring, recovery | 15 | restore drill passed within target; metrics scraped; open uncertain actions = 0 |

Every metric records formula, denominator, target, evidence source, confidence, reviewer and refresh trigger.
Row counts are never quality: "rows uploaded" earns nothing without validation results. The existing
`scoring.py` is reused for ontology and governance metrics rather than replaced.

## 2. Release states

`Draft → Simulation → Pilot → Production`, plus `Suspended` and `Rolled back`. A release is an immutable snapshot
of the use case's configuration (ontology fingerprint, tools, rules, agents, pipelines) with its evidence and
approvals. Material changes create a new release and invalidate affected evidence.

## 3. Hard gates (server-side, independent of the score)

Promotion is refused, including by direct API call, when any of these holds:

| Gate | To Pilot | To Production |
|---|---|---|
| Every review rule has a reviewer role held by at least one person | ✔ | ✔ |
| No separation-of-duties violation (requester = approver on sensitive actions) | ✔ | ✔ |
| Cross-workspace isolation tests pass for the platform build | ✔ | ✔ |
| No external write capability without idempotency, confirmation contract and reconciliation | — (read-only or simulated only) | ✔ |
| Critical connectors tested against a real test instance | — | ✔ |
| No unresolved Critical or High security finding | ✔ (Critical) | ✔ |
| Restore drill evidence | — | ✔ |
| Audit traceability complete for every consequential action | ✔ | ✔ |
| Sector-specific safety/quality controls declared and satisfied (e.g. GxP, HSE) | as declared | ✔ |
| Readiness score | ≥ 80 | ≥ 95 (necessary, never sufficient) |

**Acceptance test [8]:** a configuration scoring 97 with one failed hard gate cannot enter Production through
Studio, the API or the CLI.

## 4. Implementation notes

Promotion is an engine API (`POST .../releases/{id}/promote`) that evaluates gates itself; Studio only displays
the result. Approvals reuse the review mechanism, so the same self-approval and audit rules apply.
