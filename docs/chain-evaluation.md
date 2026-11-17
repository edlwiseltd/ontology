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

## What it cannot show

* Whether a model is right for a real organisation: independent domain reviewers judge that, separately.
* A real provider's behaviour on the reserved briefs: no call was authorised.
* Usability, performance under load, or anything in production.
