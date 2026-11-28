# Autology — R2 decision integrity, AI security boundaries and architecture foundations: sprint report

*15 November 2026. Branch `claude/autology-ontology-agent-4ajjer`. This report summarises and points to the
sources of truth; it does not replace them: [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md),
[defect register](AUTOLOGY_DEFECT_REGISTER.md), [decision register](AUTOLOGY_DECISION_REGISTER.md),
[requirements traceability](AUTOLOGY_REQUIREMENTS_TRACEABILITY.md), [roadmap](AUTOLOGY_RELEASE_ROADMAP.md).*

**Outcome.** Increment A is complete (three defects fixed, each reproduced first). Increment B is blocked on the
owner's approval of D24, as the directive required; its design, tests and review evidence are done and nothing
about authorisation changed. Increment C delivered MIG-1 in full and a first, tested step of ARC-0. Increment D
delivered the provider-neutral AI foundation and the proposal contract, verified with test doubles only. No real
AI provider was contacted, no customer data was used, nothing was deployed, and Production execution remains
disabled.

Baseline verified before any change: HEAD `317be70` (the previous report, documentation only, on top of
`bf8fb15`), clean and in sync with the remote; CI run 83 success; 770 tests, 2 skipped, 95.77 % lines.

Test commands used throughout:
`python -m coverage run --source=autology -m unittest discover -s tests -t .` (full suite, coverage),
`ruff check autology tests deploy`, `python deploy/mypy_ratchet.py`, and for Studio
`npx tsc --noEmit && npx vitest run && npm run -s build && e2e/run.sh` in `studio/web`.

## 1. Increments

### Increment A — SEC-A

| Field | Content |
|---|---|
| Status | **Complete** |
| Original issue | GAP-045: text in business data could steer a model's choice among valid actions (an instruction in a record made the agent refund a customer). GAP-037: a caller holding only `ingest` could change a write-protected, decision-critical field (an amount from 48000 to 100). GAP-035: a notification showed a restricted field to a reader not entitled to it. All three were reproduced on the previous commit before the change |
| Implementation | `autology/integrity.py`. A model's choice that differs from the deterministic plan is honoured only where policy lets a model choose (the action is under human review in that state, or listed in the agent's `model_may_choose`); otherwise the plan's step runs and the refusal is audit evidence. `write_access` rules bind every ingestion path, with the caller's roles for pushed rows and the pipeline's declared roles for configured sources. Notifications are rendered per reader; restricted and justification-gated fields show `[restricted]`; stored text and webhooks carry the audience-safe version. None of the controls relies on prompt wording, content filtering or the model's own assessment: the tests use a model that obeys every instruction it reads |
| Tests | `tests/test_seca_decision_integrity.py`: 18 tests, OK. Full suite: 788 OK, 2 skipped (PostgreSQL, not available locally). ruff clean; mypy 198 (= baseline) |
| Coverage | 95.71 % lines (13,470 statements, 578 missed); `integrity.py` 98 % |
| Security | Controls are in the engine (governance, write rules, per-reader rendering). Limits: where policy grants a model discretion it can still be steered inside it; a decision field without a `write_access` rule is reported, not blocked |
| Commit | `4093749` |
| CI | [Run 84](https://github.com/edlwiseltd/ontology/actions/runs/43764453135): success (5 jobs) |
| Remaining gaps | Document intake (R3) must add its own injection cases; pipeline definitions are operator files outside the release snapshot |

### Increment B — D24 least-privilege "operate"

| Field | Content |
|---|---|
| Status | **Blocked** on the owner's approval of D24 (design, tests and review evidence complete; no authorisation change made) |
| Original issue | The engine's `admin` permission on a use case is unrestricted: it covers operational tasks and also bypasses row and field rules. A narrower `operate` permission would let operations staff work without access to business data |
| Implementation | Design recorded in [IAM target §7](AUTOLOGY_IAM_TARGET.md): separation of capabilities, the four engine operations `operate` would cover (none reads a record), the implementation steps, and the question for the owner. Access review extended with evidence only: for every unrestricted grant, what it was used for (operational, configuration or data requests in the access log) and whether a narrower grant would have served. `operate` does not exist as a permission; `admin` means what it meant; no existing permission was revoked |
| Tests | `tests/test_d24_operate_readiness.py`: 4 tests, OK (present behaviour pinned: `operate` cannot be configured or granted; the four operations are refused without `admin`; review evidence). Its changes are part of the 802-test full run recorded under Increment C |
| Coverage | Included in Increment C's figure (95.82 %) |
| Security | No authorisation semantics changed. The usage evidence reads the last 2,000 requests of an identity; absence of data use is not proof that access is unnecessary |
| Commit | `6f25695` |
| CI | [Run 85](https://github.com/edlwiseltd/ontology/actions/runs/43765148960): **failure** in the `studio` job, one browser check of 56; the four other jobs passed. Cause: a race in the check itself (written in the previous sprint), not in the platform; fixed in `8c5a44c`, [run 87](https://github.com/edlwiseltd/ontology/actions/runs/43766793062) success. This commit has no green run of its own; it is contained in green runs 86 and 87 |
| Remaining gaps | **Owner decision required: approve or decline `operate` as designed.** If approved: about 1–2 days of implementation, with migration that revokes nothing silently |

### Increment C — MIG-1 and ARC-0

| Field | Content |
|---|---|
| Status | MIG-1 **Complete**; ARC-0 **Partial** (first extraction delivered and tested; full decomposition not claimed) |
| Original issue | GAP-041: schema migrations ran outside a transaction with no ordered steps, so an interrupted upgrade could leave a store half-migrated. GAP-026: `AutologyService` concentrates most of the engine's responsibilities in one class |
| Implementation | `autology/migrations.py`: explicit versioned steps run in ascending order; new tables, every step, validation of the resulting layout, the ledger and the version number are one transaction; steps are idempotent, so an interrupted upgrade restarts safely; a store newer than the code, or one that claims the current version but lacks a table or column, is refused. Steps only add: tenant, authorisation, audit and release records are preserved, and no rollback is offered (going back is restoring the backup). ARC-0: notifications and ingestion extracted into `NotificationService` and `IngestionService`; the engine keeps the same methods, which delegate, and the services ask the engine for permissions, so there is one authorisation path |
| Tests | `tests/test_mig1_migrations.py`: 6 tests, OK (upgrades from schemas 3, 10 and 13 with data intact; a failure injected at every step leaves the store as it was). `tests/test_arc0_services.py`: 4 tests, OK (same behaviour through engine and service, no second authority, size ratchet). Full suite: 802 OK, 2 skipped. ruff clean; mypy 198 |
| Coverage | 95.82 % lines (13,636 statements, 570 missed); `migrations.py` 97 %, `notifications.py` 97 %, `ingestion.py` 93 % |
| Security | Authorisation is still decided only by the engine; extraction changed no behaviour (full suite unchanged) |
| Commit | `846a3cc` |
| CI | [Run 86](https://github.com/edlwiseltd/ontology/actions/runs/43765769862): success (5 jobs) |
| Remaining gaps | ARC-0: runs and reviews, scenarios, model design, the assistant, the dispatcher's route table. MIG-1: the platform registries (tenancy, administration, releases) have one schema each and are outside the mechanism. A process mistake is recorded in the log (a `git stash` during a suite run; that run was discarded and repeated) |

### Increment D — AI-1 provider-neutral AI foundation

| Field | Content |
|---|---|
| Status | **Complete as a foundation verified with test doubles**; not a provider integration (GAP-052 stays open) |
| Original issue | GAP-029: the model contract was shaped by one vendor, with one adapter, and adapter failures could escape. The roadmap's AI-1 asks for a provider-neutral contract validated with two adapters before any AI Architect work |
| Implementation | `autology/ai.py`: `ModelGateway.invoke(ModelRequest)` returns a `ModelResponse` or a classified `ProviderError`. Provider-neutral concerns live in the gateway: explicit per-workspace configuration (nothing by default), allowed data classes (`synthetic` only by default), a request deadline that holds even if an adapter hangs, cancellation, bounded retries for rate limits and outages only, JSON Schema validation of the answer, refusal of tool requests (none is ever offered), replay of repeated request ids, token and cost accounting, content-free logging, capability reporting. Two independently written adapters: Claude through the official SDK's client object, and chat-completions JSON over HTTP. `GatewayChatModel` lets agents use the gateway. `autology/architect.py`: the AI Architect proposal contract (entities, properties, states, relationships, actions with preconditions, rules, goals, questions, assumptions, unknowns, sources, confidence); a proposal only adds, every item is validated by the engine's strict loader, nothing is saved or applied |
| Tests | `tests/test_ai1_provider_foundation.py`: 18 tests, OK, each through both adapters where relevant: provider failures; invalid, mistyped and over-complete answers; tool requests; cross-workspace attempts; malicious text in retrieved context; timeouts and uncertain outcomes; cancellation; repeats and retries; proposals violating ontology constraints; the same governed outcome whichever provider answers; the AI modules import no store, server, release or tool. Full suite: 820 OK, 2 skipped; one line changed afterwards and was re-checked with 137 related tests. ruff clean; mypy 198 |
| Coverage | 95.78 % lines (14,264 statements, 602 missed); `ai.py` 96 %, `architect.py` 94 %, `schema.py` 88 % |
| Security | A model's answer is untrusted data whichever provider produced it. It cannot write records, activate releases or call business systems: the path holds none of them. Not exposed through the API or Studio |
| Commit | `744deae` |
| CI | [Run 88](https://github.com/edlwiseltd/ontology/actions/runs/43767795604): success (5 jobs) |
| Remaining gaps | No real provider has been called; structured-output support differs between providers and is unverified; data classes are declared by code, not detected; no per-workspace concurrency or spending cap; the engine's configuration does not yet build agents on the gateway |

## 2. Sprint completion

**1. Security posture.** Three audit defects on decision integrity are fixed with controls in the engine, and the
AI path now has explicit boundaries: untrusted content never becomes an instruction, an answer never carries more
than the form asked for, and nothing a model returns is applied without the engine's validation and a person. No
security gate was bypassed. This is repository-level evidence, not an independent security review.

**2. GAP-035, GAP-037, GAP-045.** All three are **Fixed** in the defect register, each against its original
acceptance criterion with reproducible tests (18), after being reproduced on the previous commit.

**3. D24.** Not approved, therefore not implemented. Design, tests of present behaviour and effective-access
evidence are in place. **The owner's decision is required**: approve or decline the `operate` permission described
in the IAM target §7. D23 (token lifetimes and limits) and D25 (company sign-in for people) also still await
confirmation.

**4. MIG-1 and ARC-0.** MIG-1 is done for the engine store (GAP-041 fixed). ARC-0 is partial: two of the
responsibilities are extracted behind unchanged methods with a ratchet against regrowth (GAP-026 partly fixed).

**5. AI-1 adapter readiness.** The contract, the gateway, two adapters and the proposal contract are implemented
and pass with test doubles and a local mock endpoint. Ready for an authorised evaluation with a genuine provider;
not ready to be called an integration. GAP-052 remains open; GAP-029 is partly fixed.

**6. R2 exit requirements.** Updated in the [roadmap §3.5](AUTOLOGY_RELEASE_ROADMAP.md): contract, gates,
releases, administration, security prerequisites, migrations and recovery are met at repository level; ARC-0 is
partial; readiness scoring (REL-3) is not started; the AI Solution Architect has its foundation only.

**7. Remaining high-severity defects.** Four, none introduced or left unresolved by this sprint: GAP-031 (no
licence; engineering done, legal approvals open, stays partly fixed), GAP-032 (no ERP connector; live ERP work is
not authorised), GAP-052 (never run with a real AI model; external evidence) and GAP-053 (no real end-to-end
business process; external evidence). The register counts 32 fixed, 10 partly fixed and 21 open of 63.

**8. Next recommended increment.** In order: (a) the owner's decisions on D24 and on D7/D10 per workspace
(provider, data classes, key custody, evaluation protocol); (b) the next ARC-0 extraction (runs and reviews),
which is independent of any decision; (c) once authorised, an evaluation of AI-1 with a genuine provider on
synthetic data to close GAP-052, then exposure of model proposals through a revised API contract (ARC-1).
