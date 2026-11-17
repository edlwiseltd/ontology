# Work in progress — Autology

*Updated 17 November 2026 (Application Builder sprint). Branch `claude/autology-ontology-agent-4ajjer`.*

## Done in this directive

| Item | Commit | Evidence |
|---|---|---|
| Owner decisions D11, D7/D10, D19 recorded | `5516358` | `planning/AUTOLOGY_DECISION_REGISTER.md` |
| H-1 / F-01: outbound credentials confined to the configured origin (GAP-058) | `5516358` | `tests/test_h1_outbound.py` (7 of 12 failed before the fix); CI run 67 |
| H-1 / F-02: machines never record human approvals (GAP-059) | `5516358` | `tests/test_h1_approval_identity.py` (6 of 6 failed before the fix); CI run 67 |
| REL-1a: immutable releases, independent approval, drift, rollback, run binding (GAP-020) | `c2ea711` | `tests/test_rel1a_releases.py`; CI run 68 |
| Architecture Part B: plugin runtime, knowledge hub, composable intelligence, decision and action modelling, autonomy | `c2ea711` | `planning/AUTOLOGY_ARCHITECTURE_TARGET.md` |
| Legal decision package D19 (not counsel's approval) | `c2ea711` | `planning/AUTOLOGY_LEGAL_DECISION_PACKAGE_D19.md` |
| ADM-1/ADM-2: members, tokens, grants (independent approval) without restarts; engine reload | `839e9d3` | `tests/test_adm1_administration.py`; CI run 70 |
| STU-6: Releases tab in Studio; publish a draft; restore a release's model | `839e9d3` | `tests/test_stu6_publish.py`; 31/31 browser checks; CI run 70 |
| QA-1: ruff, mypy ratchet (201), pip-audit, npm audit; base image by digest, actions by SHA | `cb91221` | CI run 71 (five jobs, incl. `quality`) |
| IAM-1: tenants own workspaces; versioned tenancy registry; migration into dedicated tenants | `0008ae4` | `tests/test_iam1_tenants.py`; CI run 75 |
| IAM-3: administrators carry no business-data access; explicit approved grants; migration; GAP-061 fixed | `88e5fd7` | `tests/test_iam3_privilege_separation.py`; 33/33 browser checks; CI run 76 |

## R2 security and reliability sprint (15 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| A — GAP-030: token lifetimes, revocation, rotation, rate limits, timeouts | Done, `940c04f`, CI run 78 | `tests/test_gap030_security.py` (27 tests); see the implementation log |
| B — IAM administrative security | Done, `01228d3` (CI run 79: Python jobs green, one Studio browser check failed on a UI race fixed in C) | `tests/test_iamb_admin_hardening.py` (12 tests); GAP-062, GAP-063 found and fixed |
| C — Backup, restore and release activation | Done, `8111d7f`, CI run 80 | `tests/test_ops1_recovery_and_activation.py` (14 tests); GAP-033 fixed |
| D — Studio tenant and membership administration | Done, `0e9967a`, CI run 81 | Access screen in Studio; 23 Vitest, 56/56 browser checks |

## Decision integrity, AI security boundaries and architecture foundations (15 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| A — SEC-A: GAP-045, GAP-037, GAP-035 | Done, `4093749`, CI run 84 | `tests/test_seca_decision_integrity.py` (18 tests, with a model that obeys what it reads) |
| B — D24 least-privilege `operate` | **Blocked on the owner's approval**; design, tests of present behaviour and access-review evidence done, `6f25695` (CI run 85 failed on a race in one browser check, fixed in `8c5a44c`; the commit is part of green run 86) | `tests/test_d24_operate_readiness.py` (4 tests); [IAM target §7](planning/AUTOLOGY_IAM_TARGET.md) |
| C — MIG-1 and a first step of ARC-0 | MIG-1 done, ARC-0 partial, `846a3cc`, CI run 86 | `tests/test_mig1_migrations.py` (6), `tests/test_arc0_services.py` (4); GAP-041 fixed, GAP-026 partly |
| D — AI-1 provider-neutral AI foundation | Foundation done **with test doubles only**, `744deae`, CI run 88; no real provider, GAP-052 open | `tests/test_ai1_provider_foundation.py` (18 tests); see the implementation log |

## R2 closure, AI Architect integration and rapid onboarding proof (15 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| A — decision-critical facts fail closed on every write path (GAP-064) | Done, `4323391`, CI run 90 | `tests/test_r2c_critical_fields.py` (11) |
| B — D24 `operate` | **Blocked on the owner's approval**; exact specification written, `3a49e69`, CI run 90 | [D24 specification](planning/AUTOLOGY_D24_OPERATE_SPECIFICATION.md) |
| C — ARC-0: runs and reviews extracted | Done (ARC-0 still partial), `791c02b`, CI run 91 | `tests/test_arc0_services.py` (7) |
| D — REL-2 gates and REL-3 scorecard | Done; weights proposed, not ratified (D26), `f91d045`, CI run 92 | `tests/test_rel2_rel3_readiness.py` (10) |
| E — architect through the versioned API | Done **with a sandbox test double only**, `ccc551d`, CI run 93 | `tests/test_arc1_architect_api.py` (10); [evaluation protocol](planning/AUTOLOGY_AI_PROVIDER_EVALUATION_PROTOCOL.md) |
| F — rapid onboarding slice in Studio | Demonstrated in the browser (sandbox, synthetic) | `tests/test_onb1_draft_simulation.py` (7), 17 browser checks; [how to run it](docs/onboarding-demo.md) |

## Waiting for the owner

| Item | Needs |
|---|---|
| Name the release approver per workspace (D11 operational detail) | A single-administrator workspace cannot activate a release until it has one |
| Configure AI providers per workspace, data classes and keys (D7/D10 details), and authorise an evaluation protocol | AI-1 real-provider runs; closing GAP-052; exposing model proposals in Studio |
| D24: approve (or decline) the narrower `operate` permission as designed | Implementation is about 1–2 days once approved; nothing changes until then |
| D26: readiness weights and the mandatory conditions per stage | Reports say the weights are a proposal until approved |
| Counsel's answers L1–L9 (D19) | GAP-031 closure; distribution stays blocked |
| Review the migrated administrator grants (IAM-3) in each existing workspace | Revoke those not needed |
| D22b–e; authorisation for IAM-2, IAM-4, IAM-5, IAM-6 | Not started, by instruction |
| D24: keep the engine's unrestricted `admin` permission as an acknowledged, reviewed grant? D25: company sign-in for people | See the decision register; migrated administrator grants wait for confirm / narrow / revoke in each workspace's access review |
| D23: confirm default token lifetimes (90 d people, 365 d services) and rate limits | Existing tokens expire one lifetime after the upgrade: plan re-keying |
| Next increment authorisation | Readiness (REL-3), AI-1 once D7/D10 are configured |

## Hard limits (unchanged)

- No production deployment.
- No production ERP writes.
- No commercial distribution.
- No confidential data sent to an external AI provider without approved configuration.
- No self-approval of releases.

## Activation sprint: solution activation, persistent simulation, onboarding (16 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| A — agents and simulated tools from Studio | Done (drafts only; releases carry them from B) | `tests/test_act1_solution_configuration.py` (10); 33 Studio unit tests; 81/81 browser checks; see the implementation log |
| B — executable configuration inside the release | Done | `tests/test_act2_release_configuration.py` (12); 884 tests, 95.82 %; 82/82 browser checks |
| C — persistent governed simulation from Studio | Done | `tests/test_act3_persistent_simulation.py` (8); run cancellation; template `supplier_disruption.json`; GAP-066 found and fixed (`tests/test_gap066_store_lock.py`) |
| D — readiness for draft, proposed and active release | Done (weights provisional, D26) | `tests/test_act4_readiness_subjects.py` (5) |
| E, F — end-to-end journey and reference demonstration | Done, sandbox architect and simulated tools only | nine-step Onboarding flow; [docs/solution-demo.md](docs/solution-demo.md); 111/111 browser checks (29 are the demonstration) |
| Section 10 — real provider preparation | Design only; nothing implemented, no provider contacted | [planning/AUTOLOGY_AI_PROVIDER_WORKSPACE_CONFIGURATION_DESIGN.md](planning/AUTOLOGY_AI_PROVIDER_WORKSPACE_CONFIGURATION_DESIGN.md) |

**Still blocked on the owner:** D24 (`operate`), D7/D10 (a real AI provider), D26 (readiness weights and mandatory
sets). D27 lists the engineering defaults applied in this sprint for confirmation. **Not done:** Production
execution, real connectors, any language model, timing with real users, independent security review.
Report: [planning/AUTOLOGY_ACTIVATION_SPRINT_REPORT.md](planning/AUTOLOGY_ACTIVATION_SPRINT_REPORT.md).

## Architect sprint: provider governance, architect on unfamiliar briefs, evaluation (16 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| A — operational integrity | Done | `tests/test_arch1_operational_integrity.py` (9); GAP-067 found by the first recovery rehearsal and fixed |
| B — AI provider policy per workspace, spending ledger | Done **with test doubles**; no authorisation deployed, no provider contacted | `tests/test_arch2_ai_provider_governance.py` (14) |
| C — architect contract for unfamiliar briefs | Done **with test doubles**; not demonstrated with a real model | `tests/test_arch3_architect_and_evaluation.py` (C1–C5) |
| D — novel-case evaluation suite, thresholds fixed | Done; run on reference answers and on the sandbox only | same file (E1–E5); `python -m autology architect-eval --self-check` |
| E — Studio onboarding | Done, demonstrated with the sandbox | 40 Studio unit tests; 118/118 browser checks |
| F — genuine provider evaluation | **Blocked by D7/D10** (ready for external evaluation) | — |

Report: [planning/AUTOLOGY_ARCHITECT_SPRINT_REPORT.md](planning/AUTOLOGY_ARCHITECT_SPRINT_REPORT.md).

## Claude activation sprint: everything before the first call (16 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| 1 — model pinned in the use case and the release | Done, tested with doubles | `tests/test_claude1_model_pinning.py` (8) |
| 2 — Anthropic adapter against the provider's SDK, offline | Done; four latent defects found and fixed (GAP-068 to GAP-071); **not** verified against the provider | `tests/test_claude2_anthropic_adapter.py` (9) |
| 3 — spending around a real call | Done, tested with doubles | `tests/test_claude3_evaluation_deployment.py` (S1) |
| 4 — evaluation deployment and operator's guide | Done; waits for the decision and the key | `deploy/evaluation_setup.py`; [docs/ai-provider-activation.md](docs/ai-provider-activation.md) |
| 5 — five cases with a real model, ground-handling brief, Studio journey | **Blocked on the key only**: the owner's decision is recorded (`D7D10-2026-11-16-EVAL`: workspace `evaluation`, `claude-opus-5-5`, synthetic data, 10 USD a month, 1 USD a request, until 23 Nov 2026); `EVALUATION_AI_KEY` is not in the environment | [report §7](planning/AUTOLOGY_CLAUDE_ACTIVATION_REPORT.md) has the exact commands for the session that has the key |

No request was sent to a provider in that sprint (the first one was sent on 17 November, below). Report:
[planning/AUTOLOGY_CLAUDE_ACTIVATION_REPORT.md](planning/AUTOLOGY_CLAUDE_ACTIVATION_REPORT.md).

**16 Nov, 22:49 UTC:** first real execution attempted and stopped at the credential check: `EVALUATION_AI_KEY` is
not set in the environment `ontology`. No call was made. The model identifier and its price were confirmed against
the provider's published documentation (implementation log). A session that has the variable starts with
`python deploy/evaluation_setup.py --check`, then one canary call, then the five cases.


## First real model run (17 November 2026)

Authorisation `D7D10-2026-11-16-EVAL`: workspace `evaluation`, Anthropic, `claude-opus-5-5`, synthetic data, 10 USD
a month. The key was in the environment from 07:47 UTC.

| Step | Status | Evidence |
|---|---|---|
| Verify, deploy, authorise (two identities, one operator) | Done | Report §A |
| Canary: one real call | **Passed on the fourth attempt** (three refused by the provider at no charge: GAP-072, GAP-073) | `planning/evidence/claude-eval-2026-11-17/canary/` |
| Five-case evaluation, original | **Thresholds not met: 5 of 13** | `run1-original/` |
| Corrections (GAP-074, GAP-075), second run | **Thresholds not met: 3 of 13**; two answers refused whole (GAP-082) | `run2-after-correction/` |
| Unfamiliar brief (airport ground handling) in Studio | Demonstrated: 40 of 40 elements accepted, three governed releases, four stored runs (autonomous, approval-dependent, refused by policy), verified audit, readiness | `ground-handling/` |
| Spending | 4.418875 USD recorded, 5.581125 USD left (corrected by one millionth after reconciliation); 33 requests, 24 answers | `spending-ledger.json` |

Defects: GAP-072 to GAP-079 fixed; GAP-080, GAP-081 open; GAP-082, GAP-083 wait for the owner (D30 f, g).
Commits `a2b5cb7`, `253544d`; CI runs 107 and 108 green. **GAP-052 is partly fixed, R2 is not closed.** Nothing further is sent to the provider without the owner's word.
Report: [planning/AUTOLOGY_FIRST_REAL_CLAUDE_EVALUATION_REPORT.md](planning/AUTOLOGY_FIRST_REAL_CLAUDE_EVALUATION_REPORT.md).

## AI Architect reliability and evaluation stabilisation (17 November 2026)

No call to a provider; nothing spent. Report:
[planning/AUTOLOGY_AI_ARCHITECT_RELIABILITY_REPORT.md](planning/AUTOLOGY_AI_ARCHITECT_RELIABILITY_REPORT.md).

| Increment | Status | Evidence |
|---|---|---|
| A — spending ledger that outlives a deployment (P0, GAP-085) | **Done**; the ledger of 17 Nov restored and reconciled (27 entries, 4.418875 USD spent, 5.581125 left) | `tests/test_stab1_spending_ledger.py` (18) |
| B — structured output (GAP-082) | Diagnostics, closed key list and evidence done; **the rule is unchanged and the choice is the owner's** | `tests/test_stab2_structured_output.py` (8); [decision record](planning/AUTOLOGY_STRUCTURED_OUTPUT_DECISION_RECORD.md) |
| C — proposal lifecycle in Studio (GAP-080) | **Done**, with the sandbox | `tests/test_stab3_proposal_lifecycle.py` (8); 8 browser checks |
| D — provenance (GAP-081) | **Done**, with the sandbox | same file |
| E, G — evaluation methodology (GAP-083) | Version 2 **proposed, not in force**; version 1 untouched | `tests/test_stab4_evaluation_protocol.py` (11); [protocol](planning/AUTOLOGY_ARCHITECT_EVALUATION_PROTOCOL_V2.md); [expert form](planning/AUTOLOGY_ARCHITECT_EXPERT_REVIEW_FORM.md) |
| F — record editor, consistency findings, several agents | Editor: partial (needs the unrestricted permission; D24). Findings: done. Several agents: [design only](planning/AUTOLOGY_MULTI_AGENT_COORDINATION_DESIGN.md) | `tests/test_stab5_workflow_consistency.py` (5); 8 browser checks |
| Third real evaluation | **Not run. Ready for controlled re-evaluation — awaiting owner authorization** | Report §4 |

Commit `8c9fe94`; CI run 110 green. Waiting for the owner: D30 (f), (g), (h); D31; D32; D24; D26; two independent reviewers; the provider's invoice.
**R2 is not closed.**

## R2 cross-domain validation: one Engine, one Studio, two unrelated applications (17 November 2026)

No call to a provider; nothing spent. Synthetic data and simulated tools only. Report:
[planning/AUTOLOGY_CROSS_DOMAIN_ARCHITECTURE_VALIDATION_REPORT.md](planning/AUTOLOGY_CROSS_DOMAIN_ARCHITECTURE_VALIDATION_REPORT.md).

| Item | Status | Evidence |
|---|---|---|
| Two domain packs as configuration (crisis management, network intelligence) | **Done**; engineer-written templates through the sandbox test double, and labelled so | `examples/domains/`; `tests/test_xdom1_cross_domain.py` (23) |
| Kernel: zero domain-specific changes; five general corrections (GAP-092, 094, 095, 096, 097) | **Done** | Same file: neutrality scan, isolation I1 to I8 |
| Studio: the same journey for both domains | **Done** with the sandbox | `studio/web/e2e/domains.mjs` (56 browser checks) |
| Application contract and synthetic reference client | **Done** as a contract; gaps listed (GAP-093, GAP-100; D24, D34) | `docs/application-contract.md`; `tests/test_xdom2_application_contract.py` (6) |
| GAP-082 element-level rejection | Built and tested; **not in force** | `tests/test_xdom3_element_level_rejection.py` (15) |
| GAP-083 cross-domain reading of protocol version 2; expert-review requirements | **Proposed, not in force**; no reviewer engaged | `tests/test_xdom4_cross_domain_assessment.py` (5) |
| D31 durable ledger deployment | Assessment only; no infrastructure changed | `planning/AUTOLOGY_SPENDING_LEDGER_DEPLOYMENT_ASSESSMENT.md` |
| Onboarding an unfamiliar domain with a language model | **Not shown** (GAP-098); needs D30 h | Report, Summary and G.7 |

Waiting for the owner: D30 (f), (g), (h); D31; D32; D24; D26; D33 (four general defaults of this sprint); D34
(application contract gaps); reviewers for both demonstrator domains. **R2 is not closed.**

Commits `c202a68`, `d046b8d`, `84c2725`; CI run 112 green, run 113 failed on one racy new browser check (corrected), run 114 green on the final code.

## Application Builder: from a released model to a business application (17 November 2026)

No call to a provider; nothing spent. Synthetic data and simulated tools only. Report:
[planning/AUTOLOGY_APPLICATION_BUILDER_MVP_REPORT.md](planning/AUTOLOGY_APPLICATION_BUILDER_MVP_REPORT.md).

| Item | Status | Evidence |
|---|---|---|
| Application manifest (closed, versioned), deterministic generator, validation, per-caller tailoring | **Done** | `autology/appspec.py`; `tests/test_app1_application_builder.py` (14) |
| Designs saved by the Engine, bound to a configuration; refused on any other; requests may name their configuration | **Done** as design drafts; **not part of a release** (GAP-101, D34) | `autology/applications.py`; store schema 20 |
| Application runtime, separate from Studio, eight view components | **Done**; served with Studio (GAP-103) | `studio/web/runtime/`; `studio/web/tests/runtime.test.ts` (15) |
| Studio Application Designer | **Done** | `components/ApplicationDesigner.tsx` |
| Three demonstrations (crisis, network intelligence, venue booking without a template) | **Done** in a browser | `studio/web/e2e/apps.mjs` (87 checks) |
| Creating or changing records from an application | **Not available**: forms are previews | [record rights proposal](planning/AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md) |
| Application registry, event feed | Contracts only | [D34 package](planning/AUTOLOGY_D34_APPLICATION_PLATFORM_DECISION_PACKAGE.md) |
| A language model anywhere in this | **None.** Generation is deterministic; the AI Architect is unchanged and unproven | Report, G.11 |

Waiting for the owner: D24 (with the new record-rights proposal), D26, D30 (f), (g), (h), D31, D32, D33, D34, D35.
**R2 is not closed.**
