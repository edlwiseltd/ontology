# Autology — End-to-end solution activation, persistent simulation and rapid onboarding: engineering report

*16 November 2026. Branch `claude/autology-ontology-agent-4ajjer`. This report summarises and points to the
sources of truth: the [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md), the
[defect register](AUTOLOGY_DEFECT_REGISTER.md), the [decision register](AUTOLOGY_DECISION_REGISTER.md), the
[requirements traceability](AUTOLOGY_REQUIREMENTS_TRACEABILITY.md) and the [roadmap](AUTOLOGY_RELEASE_ROADMAP.md).*

## The acceptance question

> Can a new enterprise user configure and demonstrate an executable, governed business solution entirely from
> Autology Studio, without manually editing backend configuration files?

**Yes, within these limits.** In Studio, four people take a business description to a reviewed model, an agent
with simulated tools, a release approved by a second person, activation in the Simulation stage, stored runs with
an autonomous action, an approved action, a policy refusal, a cancellation and an injected failure, and readiness
reports for the draft and for what runs. No file is edited and no command is typed after the platform and Studio
are started. The journey is repeated by 29 browser checks and by API tests.

The limits are not small and are stated wherever the product shows them:

* The architect is a **sandbox test double** filling one of **two templates**. It is not a language model. A
  description outside the templates' vocabulary gets a question, not a solution (D7/D10 pending; GAP-052 open).
* Every tool is **simulated**. A completed run proves the governed flow, not a change in any real system.
* **Production is not available.** Nothing was deployed.
* No timing with real users was measured.

Status words: **Implemented** (code exists), **Tested** (automated tests pass), **Demonstrated** (seen working in
the browser checks), **Partial**, **Blocked**, **Not started**.

## A. Repository evidence

### A1. Revisions

| | Revision |
|---|---|
| Start (verified: tree clean, in sync, CI run 95 success; 862 tests, 95.88 %, 28 Studio unit tests, 73 browser checks as reported) | `d86ca23` (documentation on top of `b67853e`, the baseline named in the directive) |
| A | `2de9666` |
| B | `f20e06d` |
| Store-lock fix (GAP-066) | the commit before the last code commit |
| C, D, E, F | the last code commit (hash and CI run in §A4, added once the run finished) |

Baseline check: the reported figures held. Gaps confirmed in the code before any design: agents and tools came
only from files; a release restored the model only; no run could be cancelled; readiness measured the running
engine only.

### A2. What changed, by file

| Area | Files | What |
|---|---|---|
| Solution model (new) | `autology/solution.py` | A configuration as Studio edits it; validation against a model; compilation to the engine's existing agent configuration; effective permissions; the approved tool catalogue; release coherence and release parts |
| Configuration API (new) | `autology/configuring.py`, `autology/openapi.py`, `autology/store.py` (schema 17), `autology/migrations.py` | Five routes for the draft configuration; stored in draft revisions |
| Agent | `autology/agent.py` | Autonomy policy `supervised` (adds reviews only); `cancel` |
| Releases | `autology/platform.py`, `autology/administration.py` | Model and agents published, activated and rolled back together; refused when incoherent; refusals recorded; release parts and verification; readiness of a draft or a release on a throwaway engine; draft revision for publishers |
| Runs | `autology/runs.py`, `autology/views.py`, `autology/server.py` | `POST /runs/{id}/cancel`; the run view names its configuration, agent, tools and their environment |
| Proposals | `autology/architect.py`, `autology/sandbox_ai.py`, `autology/modeling.py` | Optional `case_templates` in the proposal contract |
| Readiness | `autology/readiness.py` | `differences` between two reports |
| Templates | `autology/blueprints/supplier_disruption.json` (new), `service_request.json` | Reference scenario; case template, configuration and sample records |
| Defect | `autology/store.py` | GAP-066 |
| Studio | `components/AgentsView.tsx`, `RunsView.tsx` (new), `OnboardingView.tsx`, `ReleasesView.tsx`, `Workbench.tsx`; `lib/solution.ts`, `lib/runs.ts` (new), `lib/api.ts`, `lib/types.ts`, `lib/model.ts`; `app/globals.css` | Agents & tools panel; runs panel; nine-step flow; release contents; release review by identifier |
| Tests | `tests/test_act1_…` (10), `test_act2_…` (13), `test_act3_…` (8), `test_act4_…` (5), `test_gap066_…` (2); Studio `solution.test.ts` (5), `runs.test.ts` (5); `e2e/run.mjs` (+38 checks) | — |
| Documents | `docs/solution-demo.md` (new), `docs/onboarding-demo.md`, `docs/platform.md`, `docs/workspaces.md`; `planning/AUTOLOGY_AI_PROVIDER_WORKSPACE_CONFIGURATION_DESIGN.md` (new); the five registers; `WIP.md` | — |

No dependency was added.

### A3. Tests, coverage, static analysis

| Measure | Start | End |
|---|---|---|
| Python tests (2 PostgreSQL tests skipped locally in both) | 862 | **900**, all passing |
| Line coverage | 95.88 % | **95.87 %** (15,560 statements, 642 missed) |
| ruff | clean | clean |
| mypy ratchet | 198 | 198 (baseline not raised) |
| Engine class size ratchet | 1,721 lines, 138 methods | 1,714 lines, 138 methods (not raised) |
| Studio unit tests | 28 | **38** |
| Studio browser checks | 73 | **111** (29 are the reference demonstration) |

A full Python run was made for A, for B, for C (on a snapshot), and for the final tree. Two things went wrong on
the way and are part of the record:

1. **A full run stalled twice.** The second time the stacks showed a real, pre-existing defect: a store lock left
   held when a transaction could not start (GAP-066). Fixed, with two tests that fail without the fix.
2. **The first run of the complete tree had one error**: a field added in this sprint read a closed store when a
   use case was unavailable after a failed activation. An existing test caught it; corrected; the final run is
   clean.

### A4. CI

| Increment | Commit | CI run | Result |
|---|---|---|---|
| A | `2de9666` | [96](https://github.com/edlwiseltd/ontology/actions/runs/43782756110) | success |
| B | `f20e06d` | [97](https://github.com/edlwiseltd/ontology/actions/runs/43785482615) | success |
| GAP-066 fix; C, D, E, F | CI_COMMIT | CI_RUN | CI_RESULT |

## B. Product evidence

**Launch and walkthrough:** [docs/solution-demo.md](../docs/solution-demo.md) (two start commands, then Studio
only). Scripted: `cd studio/web && npm run build && e2e/run.sh` (section 6; screenshots
`e2e/screenshots/demo-*.png`). Through the API: `tests/test_act3_persistent_simulation.py`.

| Evidence asked for | Where it is shown | Result |
|---|---|---|
| Screens and UI actions | Tabs **Agents & tools**, **Simulation runs**; **Onboarding** in nine steps; **Releases** with *Contents* and *Refresh*; **Review releases** for approvers | Implemented, Demonstrated |
| A configured agent and simulated tool | `disruption_agent`: role `supply_planner`, goal `disruption_resolved`, five simulated tools (one fails on purpose for records carrying a synthetic outage switch); per action the engine's verdict with the rule that gives it | Tested (S1–S9), Demonstrated |
| A validated release containing executable configuration | Release 1 of `supply`: seven parts with a fingerprint each, agents "configured in Studio", tools "all simulated", verdict "Coherent" | Tested (R1–R8), Demonstrated |
| A persistent simulation run | Five stored runs with identifiers, state, release link and audit chain; they survive a restart | Tested (P1, P8), Demonstrated |
| An authorised action | `DEL-1001`: `accept_delay` taken by the agent alone. `DEL-1002`: `expedite_shipment` after approval by an authorised reviewer who is not the requester | Tested (P2, P3), Demonstrated |
| A policy-refused action | `DEL-1003`: "switch_supplier: prohibited: A supplier under an exclusivity agreement is never replaced"; nothing executed. Also a reviewer's refusal | Tested (P4, P5), Demonstrated |
| Stored execution and audit evidence | Decision trace from the signed chain: plan, each policy check with its rules, each executed action with its tool, review request and decision, cancellation; the chain verifies | Tested (P1, P3, P6), Demonstrated |
| Draft versus active readiness | Step 9: what runs (release 1) and a changed draft (revision n), each named with its configuration; the draft lacks a release and execution evidence; the differing conditions are listed | Tested (D1–D6), Demonstrated |

## C. Security and architecture evidence

**Authorisation boundaries (each has a test that tries to cross it).**

| Boundary | Evidence |
|---|---|
| An agent gets no authority from configuration: an action is permitted only by a tool; a role grants only what a rule says; autonomy can only add reviews | `test_act1` S5, S6 |
| Only three simulated tools can be assigned; a connector, custom code or a model reasoner is refused by the engine even when sent directly | `test_act1` S1, S2; browser check |
| Saving a draft changes nothing that runs; a published change stops execution until its own release is active | `test_act1` S4; `test_act2` R2 |
| The author does not publish; the proposer does not approve; approvers do not activate; service identities do none of it | `test_act2` R4; `test_stu6`, `test_rel1a` (unchanged) |
| An operator's agents in files are never replaced by a Studio configuration | `test_act1` S7; `test_act2` R8 |
| A run needs `run`; a review needs `review`, the reviewer role, a person, and not the requester; the audit chain needs `audit`; administrators hold none of these by role | `test_act3` P3, P10 |
| Draft refuses runs; Production is refused | `test_act3` P1 |
| A release approver without a grant sees a use case's releases and nothing else | `test_act2` (approver path); `test_rel1a` (unchanged) |
| A draft's readiness is shown only to people who configure or release | `test_act4` D6 |

**Tenant and workspace isolation.** Every new route was called with another workspace's administrator
(`nw-nadia`): 404 in each case (`test_act1` S9, `test_act2` R8, `test_act3` P10–P11, `test_act4` D6). The
existing isolation suites are unchanged and pass.

**Simulated versus real effects.** Every assignable tool compiles to a decision table whose environment is
`simulated`; the release reports "all simulated"; each run step carries its tool's environment and the run says
"no other system was contacted". The runs screen states that a completed run is not proof that a real system
changed. No connector exists in a Studio-managed release.

**Failure and recovery.** A failed activation puts the model, the agents and the engine back (`test_act2` R5); a
rollback restores model and agents together, including "no agent" (R6); a failing tool is retried three times and
reported, identically each time (`test_act3` P7); a waiting run is cancelled with evidence (P6); runs survive a
restart and continue (P8); one open run per record, a review decided once (P9); a request can no longer hang on
a leaked store lock (GAP-066).

**Remaining architectural debt.**

* ARC-0 is still partial: reconciliation, scenarios, model design, the assistant and the dispatcher are in the
  engine class. This sprint added no method to it.
* The tool catalogue and the list of approved providers are code, not registries. The catalogue is the intended
  extension point for a future plugin runtime; none was built.
* Readiness of a draft builds a throwaway engine per request (about the cost of loading the use case).
* The agents panel cannot edit the fields a decision-table row writes.
* A run whose agent is no longer configured cannot be cancelled through the API.
* Sample records are loaded when a published configuration first meets an empty store, which can be before its
  release is approved (they are synthetic data, not configuration).
* Run and review routes still answer open objects in the API contract; Studio types them by hand.

## D. Final status

| Component | Status |
|---|---|
| A — agent and simulated-tool configuration from Studio | Implemented, Tested, Demonstrated |
| B — configuration inside the governed release; activation, rollback, refusal evidence | Implemented, Tested, Demonstrated |
| C — persistent governed simulation; cancellation | Implemented, Tested, Demonstrated (simulated tools only) |
| D — readiness for draft, waiting release and active release | Implemented, Tested, Demonstrated; weights provisional (D26) |
| E — one Studio flow from description to readiness | Implemented, Demonstrated |
| F — reference demonstration (supplier disruption) | Implemented, Tested, Demonstrated with a sandbox architect and synthetic data |
| Section 10 — per-workspace provider configuration and spending control | **Partial: design only** ([document](AUTOLOGY_AI_PROVIDER_WORKSPACE_CONFIGURATION_DESIGN.md)); nothing implemented |
| A real AI provider; free natural-language briefs | **Blocked** (D7/D10); GAP-052 open |
| `operate` permission | **Blocked** (D24); no change made |
| Readiness weights and mandatory sets as policy | **Blocked** (D26); labelled as a proposal everywhere |
| Connectors or sandbox tools from Studio; Production execution | **Not started**; not authorised |
| Timing with real users; independent security review | **Not started** |

### Decisions awaiting the owner

| Decision | What is asked |
|---|---|
| **D24** | Approve or decline the `operate` permission as specified. Unchanged in this sprint |
| **D7 / D10** | For a named workspace: provider, model, data classes, budget ceilings, key custody, retention, evaluator. The [design](AUTOLOGY_AI_PROVIDER_WORKSPACE_CONFIGURATION_DESIGN.md) lists five open points |
| **D26** | The readiness weights (proposal 15/15/20/15/20/15) and the mandatory conditions per stage |
| **D27** (new, for confirmation) | Five engineering defaults applied in this sprint, none of which grants an authority that did not exist; the most visible: a release that could not execute is refused at activation |
| D23, D25 | Unchanged |

### R2

**R2 is not closed.** Met at repository level: versioned API contract, stage and execution gates, releases with
independent approval now covering agents and tools, workspace and member administration, security prerequisites,
migrations and recovery, readiness gates and scorecard for drafts and releases, agents and simulated tools
without files. Partial: ARC-0. Demonstrated with a test double only: the AI Solution Architect path. Not met: a
real provider (GAP-052), ratified readiness weights, documents as input, the two named industry blueprints.
Details: [roadmap §3.5](AUTOLOGY_RELEASE_ROADMAP.md).

### Recommended next increment

1. The owner's answers on D7/D10 for one workspace; then the spending ceilings of the design, then the evaluation
   protocol on synthetic briefs. This is the only way past "two templates".
2. Independent of any decision: typed contracts for the run and review routes; cancellation of runs whose agent
   is gone; editing of decision-table writes; a recorded restore drill per use case (it blocks production
   readiness today).
3. A first session with real users on the reference demonstration, to replace the missing timing with a
   measurement.
