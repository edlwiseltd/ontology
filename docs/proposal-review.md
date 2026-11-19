# Reviewing an architect's proposal, element by element

*Status: in force for stored proposals (November 2026). It concerns how **people** review what the architect
proposes. It does not change how a provider's answer is accepted: an answer that does not match the contract is
still refused whole (GAP-082; element-level reading of a non-conforming answer stays inactive until the owner
decides D30 f).*

## 1. What the system distinguishes, and where

| Thing | Where it is established | Where it is kept |
|---|---|---|
| A requirement the description **states** | `architect.origin_of`: the element cites the brief, an answer or a supplied source, checked against what was really given (`architect.canonical`) | The element: `basis: supplied`, `origin`, `evidence` |
| A model **inference** | The same function: nothing given is cited, or the element says so itself | `basis: inferred`, `origin: inference` |
| An unverified **assumption** | The proposal contract's `assumptions` section | The stored revision |
| A **missing** requirement | The contract's `questions` and `unknowns` | The stored revision; answers create the next revision |
| A **contradiction** | The contract's `contradictions` | The stored revision |
| An element the Engine **refused** | The strict loader, element by element, when the proposal is made (`architect._items`) | The revision's `rejected`, with the loader's words |
| An element a person **confirmed, corrected or rejected** | `ArchitectService.decide_proposal` | `architect_decisions`, `architect_corrections`: append-only, attributed |
| Where every element **stands now** | `proposal_review.standing` | Computed on each read from the history; never stored, so it cannot drift from it |

## 2. Traceability: from a sentence to a decision

`proposal_review.traceability` gives one line per element. For the element "the director approves loans above the
valuation limit" of a reference answer:

| Step | Value | Source |
|---|---|---|
| Business statement | "Objects insured above a valuation limit need the director's approval" | The brief |
| Element | `rule R-VALUE` (human review of `issue_agreement` when `valuation > 50000`) | The proposal |
| Basis | **inferred**: the brief names a limit and gives no amount | `basis`, `origin` |
| What it cites | `brief` | `evidence` |
| Engine's finding | passed (the strict loader accepts it beside the other elements) | `validation` |
| Person's decision | accepted, by whom, when, on which revision | `architect_decisions` |
| In the model | yes, because of that decision and for no other reason | `kept` |

An element the Engine refused has a line too: what was refused, in the loader's words, "not offered for review".

## 3. The rules of a review

1. An **inferred** element is confirmed only by a person's explicit acceptance or correction of *that* element.
   Nothing confirms it by default, in bulk by omission, or because a later revision repeats it.
2. A **stated** element needs no confirmation and can be rejected like any other.
3. The **last** decision about an element wins; every earlier one stays in its history.
4. A decision is about the element **as it was shown**. In a later revision it holds only while the element is
   unchanged; a changed element is undecided again.
5. A **rejected** element that a later revision proposes again is still rejected, and flagged "proposed again
   after it was rejected". It is never confirmed by reappearing.
6. A **correction** replaces the element's content with what the person wrote. It is attributed to them, needs no
   provider, and is validated like any other element.
7. A kept element that **depends** on one that is not kept is named, with the decision that caused it, before any
   validation. The verdict on the resulting model is the strict loader's.

Who may decide: a **person** holding `configure` on the use case. A service identity, a reader and a member of
another workspace cannot (403 or 404).

## 4. The workflow

| # | Step | Route | Provider call |
|---|---|---|---|
| 1 | A business description | `POST /api/v1/architect/proposals` | one |
| 2 | Proposed elements with their basis and evidence | the answer, stored as revision 1 | — |
| 3 | Unknowns, assumptions, contradictions, questions | the same answer | — |
| 4 | A person answers the questions | `POST …/proposals` with `revises` and `answers` → the next revision | one |
| 5 | Per-element acceptance, correction or rejection | `POST …/proposals/{id}/decision` with `accepted`, `rejected`, `corrected` | **none** |
| 6 | Where everything stands; what a decision broke; what the loader says | `GET …/proposals/{id}` → `review` | none |
| 7 | A draft | `POST /api/v1/model/draft` with `origin` | none |
| 8 | Publication and release | the existing governance: a second person | none |

Nothing in steps 1 to 6 changes a model. A draft is saved by a person; it becomes active only through a release
approved by another person.

### What the Engine refuses

A draft that names a proposal (`origin`) may not contain an element of that proposal that was **rejected**, or
**inferred and never confirmed**: 409, with the list, and nothing is saved. Studio therefore records the review
before it saves the draft.

A draft that names no proposal claims no origin, and is the author's own model: this check does not apply to it,
and it records no provenance. It still needs a second person to be published.

This refusal is new (November 2026) and is recorded as an engineering default for the owner's confirmation
(decision D36).

## 5. In Studio

* Inferred elements are **not selected** when a proposal is opened. The line above the list says how many are
  stated, inferred, confirmed, waiting and rejected.
* Each element shows where it stands: "inferred: needs your confirmation", "confirmed by …", "rejected by …",
  with its flags.
* "Select the N inferred elements not yet selected, to confirm them" is one explicit act; each element can also be
  ticked on its own.
* Saving records the review (selected: accepted; not selected: rejected) and then saves the draft.

Correcting an element's content is available through the API (`corrected`); Studio has no editor for it yet.

## 6. Which validator says what

There is one authority per question, and this workflow adds none. Evidence:
`tests/test_rev2_proposal_diagnostics.py`.

| Defect in a proposed model | Authority | Result |
|---|---|---|
| Undefined entity; invalid relationship endpoint | Strict loader | Refused: "unknown entity …" |
| Undefined property, in a rule or a condition | Strict loader | Refused: "has no attribute …" |
| Missing required property; a property the schema does not have | Strict loader | Refused |
| Conflicting state (an effect sets a state the entity lacks) | Strict loader | Refused |
| Missing approval authority (a review rule without a reviewer) | Strict loader | Refused |
| A rule on an action that does not exist | Strict loader | Refused |
| Impossible dependency in a case template | Strict loader | Refused |
| Rule contradiction (an action prohibited without condition) | Consistency checks | **Noticed**: `always_prohibited` |
| Unreachable outcome | Consistency checks | Noticed: `goal_unreachable` |
| Circular precondition (an action waits for a state only it produces) | Consistency checks | Noticed: `action_cannot_start` (new in this sprint) |
| Unsupported external capability; an agent given what the model lacks | Configuration check (`solution.check`) | Refused when the configuration is saved |
| A reference left behind by a rejection | Proposal review, then the strict loader | Named, then refused |

"Noticed" never refuses and never adds anything to a model: a person decides, and "this is intended" is an answer.
The review of a proposal carries these findings (`review.consistency`).

## 7. Limits

* Technical acceptance is not correctness. That an element was confirmed says a person confirmed it, not that it
  is right for the business. No domain expert has reviewed any model here.
* The quality of the architect's inferences is unchanged by this workflow: it makes them reviewable, not better.
* The provenance of an element rests on what the architect cited, checked against what was given; a citation that
  is real but irrelevant is not detected.
