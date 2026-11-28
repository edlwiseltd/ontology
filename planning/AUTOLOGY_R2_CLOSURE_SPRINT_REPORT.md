# Autology — R2 closure, AI Architect integration and rapid onboarding proof: engineering report

*15 November 2026. Branch `claude/autology-ontology-agent-4ajjer`. This report summarises and points to the
sources of truth, which remain the [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md), the
[defect register](AUTOLOGY_DEFECT_REGISTER.md), the [decision register](AUTOLOGY_DECISION_REGISTER.md), the
[requirements traceability](AUTOLOGY_REQUIREMENTS_TRACEABILITY.md) and the [roadmap](AUTOLOGY_RELEASE_ROADMAP.md).*

**Outcome.** A business description can now be taken, in Studio and through the versioned API, to a reviewed,
engine-validated draft, a simulation and a readiness report, with the engine as the only authority. This is
demonstrated with a **sandbox test double and synthetic data: no language model was used**, none can be
configured, nothing was deployed, and Production execution remains disabled. D24, D7/D10 and D26 await the owner.

Status words used below: **Implemented** (code exists), **Tested** (automated tests pass), **Demonstrated** (seen
working in the browser checks), **Partially implemented**, **Blocked**, **Planned**.

## 1. Git revisions

| | Revision |
|---|---|
| Start (verified: clean, in sync, CI run 89 success) | `e2f54cf` (documentation only on top of `744deae`, the baseline named in the directive) |
| End | `b67853e` (last code change; CI run 94 success, 5 jobs), followed by the documentation-only commit that adds this report |

Baseline check against the last report: the measurable claims held (schema 15, engine class 2,142 lines and 139
methods, 820 tests). **Two discrepancies were found and corrected:** write rules did not bind the record API or
scenario commit (fixed in increment A), and the D24 design wrongly listed write-back retry as needing `admin`
(corrected in increment B).

## 2. What was done, by increment

| Increment | Status | What exists now | Commit | CI |
|---|---|---|---|---|
| A — decision integrity hardening | Implemented, Tested | An attribute can be classified `decision_critical`. It then changes only with the roles of a `write_access` rule on it, on every write path (ingestion, record API over REST and MCP, scenario commit, agent effects and tool results), the unrestricted `admin` permission included; with no rule, nobody. Opt-in: existing models are unchanged. Refusals never carry the attempted value | `4323391` | [90](https://github.com/edlwiseltd/ontology/actions/runs/43772415336) success (pushed together with B) |
| B — least-privilege `operate` (D24) | **Blocked** on owner approval; specification written | Exact permitted operations (scheduler pass answered with counts only; reporting refresh), prohibited capabilities, relationship to `admin`, `configure` and data permissions, additive migration, twelve security tests. No authorisation change | `3a49e69` | [90](https://github.com/edlwiseltd/ontology/actions/runs/43772415336) success |
| C — ARC-0 extraction | Partially implemented, Tested | Extracted behind unchanged engine methods: run lifecycle (22 methods, `runs.py`) and review workflows (5 methods, `reviews.py`). Every permission, visibility and person-only check stays in the engine. Engine class 2,142 → 1,721 lines (with the architect service of E) | `791c02b` | [91](https://github.com/edlwiseltd/ontology/actions/runs/43773261995) success |
| D — REL-2 gates and REL-3 scorecard | Implemented, Tested | 27 conditions measured on the running use case. Mandatory conditions block promotion when they fail **or cannot be verified**, and are evaluated at the promotion itself. Six dimensions each show calculation, evidence, missing evidence, blockers and corrective actions. A high score never overrides a blocker. Production stays refused. Weights are a proposal | `f91d045` | [92](https://github.com/edlwiseltd/ontology/actions/runs/43774524421) success |
| E — AI Architect integration | Implemented, Tested, **with a test double only** | `POST /api/v1/architect/proposals` (`generator: model`) → AI gateway → proposal contract → engine validation → stored revision with provenance, assumptions and validation; guided questions and answers create further revisions; a person's review is recorded. Only the `sandbox` provider may be configured. Real-provider evaluation protocol written, not executed | `ccc551d` | [93](https://github.com/edlwiseltd/ontology/actions/runs/43776035198) success |
| F — rapid onboarding slice | Implemented, Tested, **Demonstrated** (sandbox) | Studio tab **Onboarding**: describe → questions → visual review (proposed against confirmed) → engine validation → draft → simulation with a simulated approval and audit trace → readiness with blockers. New engine route for a dry run of a draft with stub tools. Industry-neutral template | `b67853e` | [94](https://github.com/edlwiseltd/ontology/actions/runs/43777479501) success |

**Remaining after each increment:** A: unclassified decision fields are still only reported; ordinary write rules
still do not bind `admin` on the record API (part of D24). C: reconciliation, scenarios, model design, the
assistant and the dispatcher are still in the engine class. D: no recovery evidence is recorded per use case, so
that condition always blocks production readiness. E and F: see §6.

## 3. Tests, coverage and CI

| Measure | Start | End |
|---|---|---|
| Python tests (2 PostgreSQL tests skipped locally in both) | 820 | **862**, all passing |
| Line coverage | 95.78 % | **95.88 %** (14,938 statements, 616 missed) |
| ruff | clean | clean |
| mypy ratchet | 198 | 198 (baseline not raised) |
| Studio unit tests | 23 | **28** |
| Studio browser checks | 56 | **73** (17 are the onboarding journey) |

New test files: `test_r2c_critical_fields.py` (11; 10 fail on the previous commit), `test_rel2_rel3_readiness.py`
(10), `test_arc1_architect_api.py` (10), `test_onb1_draft_simulation.py` (7); extended: `test_arc0_services.py`
(4 → 7), `test_d24_operate_readiness.py` (4 → 5), `test_ai1_provider_foundation.py`, `test_api_v1.py`; Studio
`tests/onboarding.test.ts` (5). A full suite with coverage was run for every increment before its commit (A and B
shared one run; B changed a test and documents only).

## 4. Security

**Closed in this sprint:** GAP-064 (decision-critical facts could change without a named authority; the record
API and scenario commit applied no write rule) and GAP-065 (readiness failed on an empty model; found by the
demonstration, fixed before any release).

**Verified boundaries of the new AI path** (with hostile test doubles): an answer outside the contract stores
nothing; engine-refused items are never provisional; a brief or an answer containing instructions changes no
rule, permission, setting or release; proposing, reviewing and simulating change nothing that governs; only
`configure` may propose, review or simulate; another workspace gets 404; the sandbox works with the network made
unusable; a draft simulation calls no configured tool and stores nothing.

**Still open:** GAP-052 (never run with a real model), GAP-053 (no real end-to-end business process), GAP-031
(licence: legal approvals), GAP-032 (no ERP connector); the unrestricted `admin` permission still combines
operating the engine with unrestricted data access (D24). No independent security review has taken place.
Register: 34 fixed, 10 partly fixed, 21 open, of 65.

## 5. Demonstration

Instructions: [docs/onboarding-demo.md](../docs/onboarding-demo.md) (start the example platform and Studio, create
a use case from the template *Blank solution (guided onboarding)*, open the **Onboarding** tab). The same journey
runs in the browser checks: `cd studio/web && npm run build && e2e/run.sh`.

| Onboarding step | Through the UI |
|---|---|
| Business description → proposal | **Works** (sandbox architect; one industry-neutral template) |
| Guided questions, answers, revision history | **Works** |
| Visual review: entities and relationships, workflow, rules, permissions; proposed against confirmed | **Works** |
| Engine validation; save as a draft; review recorded with provenance | **Works** |
| Simulation with an authorised simulated decision; audit trace | **Works, simulated**: a dry run with stub tools, not a stored run |
| Readiness report with blockers | **Works**; it describes what runs now, not the draft |
| Publish, approve and activate the draft | Works in the Releases tab; **manual and two-person by design** |
| Stored simulation run of a model proposed this way | **Unavailable**: the use case has no configured agent or tools; an administrator must add them in configuration files |
| A description outside the template's vocabulary | **Unavailable** beyond a clarification question: needs a language model (D7/D10) |
| Documents as input, industry packs, real integrations | **Unavailable** (not authorised in this sprint) |

The scripted journey takes about 2 seconds. No timing with real users was measured: the 30-minute onboarding
target remains an aspiration, not a result.

## 6. Architectural debt and plugin compatibility

ARC-0 is partial (see C). The engine's configuration cannot yet declare agents and tools for a model designed in
Studio. Providers run in-process; the list of approved providers and the readiness conditions are code, not a
registry. These and four other points are recorded with their reasons in the
[architecture target, B10](AUTOLOGY_ARCHITECTURE_TARGET.md); none prevents a future plugin runtime, and no plugin
runtime was built.

## 7. Decisions awaiting the owner

| Decision | What is asked |
|---|---|
| **D24** | Approve or decline the `operate` permission as specified; whether reinstating a suspended agent belongs to it (recommended: no) |
| **D7 / D10** | For a named workspace: provider and model, data classes that may be sent, budget, key custody, evaluator. Then the [evaluation protocol](AUTOLOGY_AI_PROVIDER_EVALUATION_PROTOCOL.md) can run and GAP-052 can be addressed |
| **D26** (new) | The readiness weights (proposal: 15/15/20/15/20/15) and the mandatory conditions per stage |
| D23, D25 | Token lifetimes and limits; company sign-in for people (unchanged) |

## 8. R2 completion status

Met at repository level: versioned API contract, server-side stage and execution gates, releases with independent
approval, workspace and member administration, security prerequisites, migrations and recovery, readiness gates
and scorecard (first version). Partial: ARC-0. Demonstrated with a test double only: the AI Solution Architect
path and onboarding. Not met: a real provider (GAP-052), readiness weights ratified, the remaining ARC stories
(documents, contradictions), the two named industry blueprints. Details: [roadmap §3.5](AUTOLOGY_RELEASE_ROADMAP.md).

## 9. Recommended next increment

1. The owner's answers on D24, D7/D10 and D26.
2. Independent of any decision: let a use case's agents and simulated tools be declared from Studio and included
   in a release, so that a model proposed in onboarding can be published and run as a stored simulation. That
   closes the largest gap in the demonstration.
3. Once D7/D10 are approved for one workspace: the spending ceilings, then the evaluation protocol with a real
   provider on synthetic briefs.
