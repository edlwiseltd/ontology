# End-to-end chain evaluation (protocol `chain-v1`)

*Status: a harness, built and tested **without any provider call** (November 2026). It is ready to receive a real
provider's answers when the owner authorises them; until then it runs on hand-written reference answers and on the
answers kept from the one authorised evaluation. It replaces nothing: protocols V1 and V2 of the architect
evaluation are used as they are.*

## What it measures, and what it refuses to add up

The chain is: *business description → clarification questions → proposal → Engine validation → a person's
corrections → governed draft → application manifest → rendering → governed work → report*. Three components do
that work, and a weakness of one must not be hidden by the strength of another:

| | Component | What is reported |
|---|---|---|
| **A** | **AI Architect** | Whether it answered; questions asked; clarifications it says it needs; contradictions named; elements proposed, accepted and refused (with the Engine's reasons); inferred elements that need a person's confirmation; approval requirements proposed; missing concepts and V1's thirteen deterministic measures when the case carries V1 expectations; provider, model, cost and usage **as recorded with the answer** |
| **B** | **Application Builder** | Given a draft the Engine accepts: whether a manifest is generated, validates, is deterministic; number and type of screens; menu entries; whether every screen is of a type the renderer draws |
| **C** | **Autology Engine** | Whether the draft is accepted by the strict loader; what governed work does with it: the default run, a review that waits for a person, the run after an approval, after a refusal, a decision by a role the rule does not name, a run with no role |

**There is no total.** `evaluate()` returns `"aggregate": null`, a test fails if any key of a result is named like a
score, and the text report ends with "No total is computed".

## The twelve steps

| # | Step | Component | Notes |
|---|---|---|---|
| 1 | An unfamiliar business description | harness | The case's brief; synthetic |
| 2 | Clarification questions | A | |
| 3 | A structured proposal | A | Through the same gateway and contract as any proposal |
| 4 | Validation by the Engine | C | The strict loader, element by element |
| 5 | Rejected elements and their reasons | C | Recorded, never repaired |
| 6 | **Only authorised corrections and confirmations** | harness | See below |
| 7 | A governed draft | C | The kept elements, applied; the Engine accepts the draft or refuses it |
| 8 | An application manifest | B | `appspec.generate` |
| 9 | Validation of the manifest | B | `appspec.validate` |
| 10 | Rendering in simulation | B | In the harness: every screen is of a view type the renderer draws. **A browser is not run by the harness**; the browser suite renders the reserved briefs' hosted applications (`studio/web/e2e/apps.mjs`, section "chain") |
| 11 | Governed actions, refusals and approvals | C | A draft simulation: stub tools, nothing stored, no silent decision. Through the platform's API in `tests/test_chain1…` (C8) |
| 12 | A reproducible report | harness | A digest of what the case produced, without clocks or request identifiers |

### Step 6: corrections are a person's

* an element the brief **states** is kept;
* an **inferred** element is kept only if a decision confirms it;
* an element a decision drops is removed;
* a decision that names no element is reported and applied to nothing;
* nothing is repaired and no default is filled in: if the kept elements do not make a model, the Engine refuses the
  draft and the chain stops there.

A reserved case carries the decisions of a synthetic reviewer. A replay of kept answers has none; it is reported
twice: with **no decision** (what the answers give on their own) and with **every inferred element assumed
confirmed** (`--assume-confirmed`), which the report states as an assumption: no reviewer confirmed anything.

## Cases

| Set | Cases | Used for |
|---|---|---|
| **Reserved** (`autology/evaluation_reserved/`) | `museum-loans`, `harbour-pilotage` | This evaluation only. Two domains no blueprint of a domain, example or earlier case covers. A test scans the Engine, the blueprints, the examples and Studio for their vocabulary and finds none. The industry-neutral "request and approval" template matches both briefs by two generic words: the template-based test double would answer with a generic model, not a model of the domain |
| V1 (`autology/evaluation/`) | Five | Replays of the authorised evaluation's kept answers. Unchanged |
| V2 (`autology/evaluation_v2/`) | Eight | Not run here: V2 is proposed and not ratified |

Each reserved case carries a hand-written reference answer. It is not a model's output and is never used to answer
a request; it exists so that the chain can be exercised and the harness tested.

## Running it

    python -m autology chain-eval --reference                     # the reserved briefs, reference answers
    python -m autology chain-eval --replay <folder>               # kept answers, no decision of a person
    python -m autology chain-eval --replay <folder> --assume-confirmed
    python -m autology chain-eval --reference --json
    python -m autology chain-eval --reference --scenarios          # the three treatments, side by side
    python -m autology chain-eval --replay <folder> --scenarios
    python -m autology chain-eval --journey <folder> --scenarios   # a kept Studio journey and its recorded decisions

There is deliberately **no option that calls a provider**. When the owner authorises an evaluation, the same
`evaluate(cases, ask)` takes the `ask` that `architect-eval --platform` builds for the authorised workspace, under
that authorisation's model, budget and ledger; nothing else changes.

## What was run (17 November 2026; evidence in `planning/evidence/chain-eval-2026-11-17/`)

| Run | A. Architect | B. Builder | C. Engine |
|---|---|---|---|
| Reserved briefs, **reference answers (not a model)** | 2 of 2 answered; 26 elements, 0 refused, 5 inferred | 2 of 2 manifests valid and deterministic (16 screens each) | 2 of 2 drafts accepted; 2 of 2 runs proceed; 1 review requested, a decision by another role refused |
| Run 2's kept answers (**a real model, answered on 17 November under the authorisation then in force**), no decision | 4 of 5 answered (one answer was refused then); 114 elements, 5 refused, 41 inferred | 1 of 1 | **1 of 4** drafts accepted: without the inferred elements, three answers do not make a model |
| The same, every inferred element assumed confirmed | the same | 4 of 4 manifests valid | 4 of 4 drafts accepted; 3 of 4 runs proceed (one escalates at its first step); 2 reviews requested |

The second and third rows cost nothing: the answers were paid for on 17 November (0.799479 USD for these four) and
are read from disk. They say something real about the chain: **the architect's usable output depends on a person
confirming inferred elements**, and the builder and the Engine handled every draft they were given.

## Three treatments of inferred elements (added 19 November 2026)

`python -m autology chain-eval … --scenarios` runs every case three ways and puts them side by side
(`chain_eval.scenarios`). Step 6 uses the Engine's own review rules (`autology/proposal_review.py`), so the harness
and the Engine cannot disagree about what a confirmation is.

| Scenario | What enters the draft | What it is evidence of |
|---|---|---|
| **1. No additional confirmation** | The elements the description states | What the answer gives on its own |
| **2. Explicit selective confirmation** | Also the inferred elements that **recorded, attributable** decisions accepted or corrected | What a person's actual decisions made of it. A case with no decision on record has no scenario 2: none is invented |
| **3. Hypothetical full confirmation** | Every inferred element | **A counterfactual.** It shows what the Engine would do if everything were confirmed. It is not evidence that any element is right |

Where recorded decisions come from: a reserved brief carries a synthetic reviewer's decisions, written with the
case and labelled so. A Studio journey kept as evidence (`--journey <folder>`) carries the decisions recorded in
its released model's provenance: which elements a member accepted in the design tool. That is a member's
acceptance, not a domain expert's review.

### Measures, per component and for the person's step

| Where | Measure |
|---|---|
| **A. AI Architect** | Clarification coverage and model completeness against the case's reference expectations (V1's scorer, unchanged); inferred elements requiring review; elements refused by the Engine; cost and time as recorded |
| **The person's step** (not a component's performance) | Confirmation rate; elements rejected; corrections; dependency failures (which decision broke what) |
| **B. Application Builder** | Manifest validation; generated screens |
| **C. Engine** | Validated elements; accepted governed drafts; governed action outcomes; audit completeness of the simulated run (every step leaves an event; **a draft simulation's trace is not a signed chain**, and the result says so) |

### Results on the kept evidence (19 November 2026; `planning/evidence/chain-eval-2026-11-19/`; no call made)

| Answers | Scenario 1 | Scenario 2 | Scenario 3 (counterfactual) |
|---|---|---|---|
| Reserved briefs, reference answers (not a model): 2 cases | 2 drafts accepted, 2 manifests valid; both simulations complete | Synthetic reviewer: 2 accepted, 2 valid; one completes, one waits for a review | 2 accepted, 2 valid; one waits for a review, one escalates |
| Run 2's kept answers (a real model): 4 answered of 5 | **1 of 4** drafts accepted; 10 dependency failures named across the other three | **Not run: no decision is on record for these answers** | 4 of 4 accepted, 4 manifests valid; 3 of 4 simulations proceed |
| The ground-handling journey (a real model; 40 elements, 23 inferred) | Draft **refused**: 4 dependency failures | The decisions on record (39 elements accepted, 1 not; 22 of 23 inferred confirmed): draft **accepted**, manifest valid, simulation completes | Accepted, valid; the simulation waits for a review |

What this supports: on the one real answer with decisions on record, selective confirmation turns a refused draft
into an accepted one. What it does not support: that the confirmed elements are right. Nobody qualified in the
domain reviewed them.

## The whole chain, element by element (added 19 November 2026, provenance sprint)

`run_case` now returns a `trace`: one line per proposed element across eleven links. It extends
`proposal_review.traceability` (which ends at the person's decision) through the draft, the Engine's validation,
the release, the application screens that show the element, the simulated action and the audit trail.

| Link | What the line says | Written as missing when |
|---|---|---|
| source | Where the element's statement comes from: the brief, an answer, a supplied source. For an answer stored before structured evidence was kept: the label the model cited then, written `<label> (cited at the time; not re-checked)` | The element cites nothing: no structured evidence entry and no stored label |
| suggestion | The architect's element and its basis (stated or inferred) | — |
| evidence | What the element cites: the structured evidence entries the Engine matched against what was given; or, for an older answer, the stored labels, each marked `(cited at the time; not re-checked)` | Nothing is cited |
| clarification | The answer of a person it rests on (for an older answer: a stored label that names an answer, marked in the same way) | (reported as "none cited", which is not a defect) |
| decision | The person's decision, by whom | Inferred and nobody confirmed it; rejected |
| draft | In the draft, or not | Not kept |
| validation | The strict loader's verdict on the draft | The loader refused the draft |
| release | The release number, when the answer comes from a released journey | The evaluation releases nothing, and says so |
| application | The screens of the generated application bound to the element | No screen is bound; no application |
| simulated action | Executed by the default simulated run | An action the default run did not reach |
| audit | Events of the simulation's trace (**in memory, not a signed chain**) | No event concerns the element |

A missing link is written as `missing: <why>`; nothing is filled in. The trace holds element names, never a
record or a value of a record, so it shows nothing a field or row rule hides; the records themselves stay behind
the Engine's API and its permissions. Evidence: `tests/test_chain1_end_to_end_evaluation.py` (class `TraceTests`).

**Citations stored with older answers (20 November 2026, GAP-113).** The answers stored on 17 November 2026 were
recorded before the structured field `evidence` existed. They hold an older field, `sources`: the citation the
model gave at the time (for these answers always the brief as a whole, never a passage). Until 20 November the
trace read only `evidence` and so wrote source and evidence as missing for every element of those answers, which
understated what is stored. The trace now shows the stored label, and marks it:

* `brief (cited at the time; not re-checked)` means: the file holds this label for the element. The Engine did
  not match it again against what was given, and the trace does not say the citation is right. It is **not**
  verified evidence, and nothing is reconstructed or inferred from it.
* Structured evidence, where an answer holds it, is shown as before and is never replaced by a stored label.
* An element with neither is still written `missing: the element cites nothing that was given`.
* Each line carries `cited_at_the_time_not_rechecked` (true or false), and the summary counts those elements, so
  a stored label is never counted with checked evidence without saying so.

What the traces show on the kept evidence:

| Answer | Elements | Without any missing link | Links missing (number of elements) |
|---|---|---|---|
| Reserved brief `museum-loans`, reference answer, the synthetic reviewer's decisions | 13 | 0 | release 13 (the evaluation releases nothing); audit 11 (only the two actions the default run executed leave an event); application 2; decision, draft and validation 1 each (the inferred rule nobody confirmed); simulated action 1 (an action the default run did not reach) |
| The kept ground-handling journey (a real model), the decisions on record | 40 | 0 | source 12 and evidence 12: the elements that cite nothing. The other 28 show the stored label `brief`, marked as cited at the time and not re-checked; none cites an answer; no passage was recorded and none is reconstructed (GAP-111, GAP-113); audit 40 and simulated action 14: the default simulated run of this model completes without executing any action; application 20; draft, validation and release 1 each (the one element not accepted) |
| Run 2's kept answers (a real model; seven files, no decision on record) | 26 to 38 per answer | 0 | source 0 and evidence 0: every element shows the stored label `brief`, marked as cited at the time and not re-checked; the other links depend on the scenario (with no decision, 1 of 4 first answers gives an accepted draft) |

The figures reported on 19 November ("source 40 and evidence 40" for the journey) are kept as they were reported
in `planning/evidence/provenance-2026-11-19/`. They were what the trace wrote then; the stored file has not
changed. The figures above are in `planning/evidence/chain-trace-2026-11-20/`.

The audit link is written as missing for every element that no executed step concerns: a simulation records
events for steps, not for entities or rules. That is a limit of what a simulated run can attest, stated rather
than papered over.

### Six replay scenarios (`deploy/make_chain_evidence.py`; `planning/evidence/chain-trace-2026-11-20/`, and as reported on 19 November in `planning/evidence/provenance-2026-11-19/`)

| # | Scenario | Result on `museum-loans` (a reference answer, not a model) |
|---|---|---|
| 1 | No element confirmed | 0 of 3 confirmed; draft accepted (the brief states enough); simulation completes |
| 2 | Only the recorded, attributable confirmations (a synthetic reviewer, written with the case) | 2 of 3; accepted; the simulation waits for a review |
| 3 | Hypothetical: all confirmed (**a counterfactual**) | 3 of 3; accepted; waits for a review |
| 4a | A rejection | The rejected entity leaves two elements without what they need; both are named; the Engine **refuses** the draft; no manifest |
| 4b | A correction | One correction, validated again; accepted |
| 5 | A model authored by hand, no architect proposal | Provenance `manual_authoring`, established by the Engine; A is not applicable; B and C as for any model |
| 6 | The same as a legacy draft of unknown provenance | `legacy_unknown`; **may not be published** until saved again and classified |

Scenarios 4a and 4b use decisions written with the evidence script and labelled "no person made them". The kept
journey gives 0 of 23 (draft refused), 22 of 23 (accepted) and 23 of 23 (counterfactual; accepted). Run 2's kept
answers are unchanged: 1 of 4 drafts accepted alone, 4 of 4 as a counterfactual, and no scenario 2 because no
decision is on record. A test compares the files kept in `chain-trace-2026-11-20/` with what the harness gives
today, and checks that the folder of 19 November is unchanged. Between the two folders only the source and
evidence links of the kept journey differ (40 missing then; 12 missing and 28 shown as stored now); no scenario
result changed.

No score recorded earlier was changed, no held-out case was modified, and no provider was called.

## What it cannot show

* Whether a model is right for a real organisation: independent domain reviewers judge that, separately.
* A real provider's behaviour on the reserved briefs: no call was authorised.
* Usability, performance under load, or anything in production.
