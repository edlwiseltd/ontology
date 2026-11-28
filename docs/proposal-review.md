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
| 5 | Per-element acceptance, correction or rejection | `POST …/proposals/{id}/decision` with `accepted`, `rejected`, `corrected`, `expected_version` | **none** |
| 6 | Where everything stands; what a decision broke; what the loader says | `GET …/proposals/{id}` → `review` | none |
| 7 | A draft | `POST /api/v1/model/draft` (the Engine establishes its provenance; `origin` is optional and checked) | none |
| 8 | Publication and release | the existing governance: a second person | none |

Nothing in steps 1 to 6 changes a model. A draft is saved by a person; it becomes active only through a release
approved by another person.

### What the Engine refuses, and how it knows where a draft comes from

Every draft of a model is classified **by the Engine** when it is saved (`ArchitectService.save_draft` →
`proposal_review.classify`), whether or not the request names a proposal. The request's `origin` is a claim that is
checked; it proves nothing. The classification compares every element the draft adds or changes with the elements
of **every** proposal stored in the use case, by identity and by content:

| What the draft adds or changes | Result |
|---|---|
| An element identical to one a proposal holds and that is **kept** there (stated and not rejected; accepted; or corrected to exactly this content) | Saved. Recorded as coming from that proposal, with the revision, the decision and who made it |
| An element identical to one that was **rejected**, is **inferred and unconfirmed**, or is the content **before** a correction | **409, nothing saved**, with the list. The same answer with or without `origin`: leaving the reference out changes nothing |
| An element with the same identity as a proposal's element and **other content**, in a draft that names that proposal | **409**: "an edited element needs a recorded correction" |
| The same, in a draft that names no proposal | Saved as the author's own, and **flagged** in the record ("same element as one of proposal … (not confirmed there)") |
| An `origin` from which nothing in the draft comes, or that names another proposal than the one the elements belong to | **409** |
| An `origin` that does not exist in this use case (another use case, another workspace, an invented one) | 400 |
| Anything else | Saved as authored by hand by the authenticated member |

The record the Engine keeps with each draft revision (`model_drafts.provenance`, returned as `provenance` by
`GET /api/v1/model/draft`):

| Mode | Meaning | Who establishes it |
|---|---|---|
| `architect_proposal` | At least one added or changed element comes from a stored proposal, confirmed | The Engine, from the stored proposals and decisions |
| `manual_authoring` | Elements were added or changed and none comes from a proposal | The Engine; the author is the authenticated member |
| `derived_revision` | The model is the one of the revision before (or the one that runs), unchanged: a configuration save, or the same model saved again | The Engine |
| `imported_configuration` | Reserved. **No route imports a draft today**; a template installs an active model through the platform's governance, and a restore brings rows back as they were | — |
| `legacy_unknown` | A draft row written before the Engine classified drafts: where its elements come from was never established | Reported, never stored: nothing is written into an old row |

The record carries the proposals the model rests on over all its revisions. It only grows: no request can shorten
it, and a later save that names no proposal does not remove an earlier link.

**A draft of unknown provenance** is not published (409 from `Platform.publish_draft`) and is not built upon: when
it is saved again, everything it holds beyond the model that runs is classified again, and elements of a proposal
that nobody confirmed are refused. What is left is attributed to the person who saved it again, and the record
says `reestablished_from_legacy`.

**What this cannot prove.** Content typed again by hand, reworded, or copied from a tool outside Autology cannot be
told from a person's own work, by this or any check on the server. Such content is attributed to the authenticated
author, flagged when it has the identity of a proposal's element, and — like every draft — becomes active only when
a **second person** publishes it and a release is approved. The record states this limit itself (`cannot_prove`).

These refusals are engineering defaults of November 2026, recorded for the owner's confirmation (decisions D36 and
D37). Evidence: `tests/test_gap107_draft_origin.py`, `tests/test_rev1_proposal_review.py`.

### Every way a draft is written, and what is trusted at each

| Entry point | Code | Who may call it | What the caller controls | What the Engine decides |
|---|---|---|---|---|
| `POST /api/v1/model/draft` | `AutologyService.save_model_draft` → `ArchitectService.save_draft` | A member of the workspace holding `configure` on the use case (a person, or a service identity granted it by two people) | The document, a note, an optional `origin` | The provenance record, the refusals above, the author (from the token, never from the body) |
| `POST /api/v1/solution/draft` | `ConfigurationService.save_solution_draft` | The same | The configuration (agents, simulated tools, samples). **Not the model**: it is carried over from the revision before, or from the model that runs | `derived_revision`; the proposals the model rests on are carried forward |
| `POST /platform/v1/workspaces/{ws}/use-cases/{uc}/publish-draft` | `Platform.publish_draft` | A **person** with release authority who is **not** the revision's author | The revision number and a reason | 403 for the author, a service identity or a member without the authority; 409 for a revision without established provenance or a model the loader refuses |
| `POST /api/v1/architect/proposals/{id}/decision` | `ArchitectService.decide_proposal` | A **person** holding `configure` | Which elements, and corrected content | Who decided and when (from the token and the clock); 409 when the review moved on |

Nothing else writes a draft: no MCP tool, no command of `python -m autology`, no template and no import route
does (`grep` of `save_draft` and `model_drafts` over `autology/`: `store.py`, `architecting.py`,
`configuring.py`, `migrations.py`, `server.py`). A template installs an **active** model when a use case is
created, through the platform's own governance. A restore brings rows back exactly as they were, including rows
with no provenance.

What a request cannot supply: the author, the time, a decision, a decision's identifier, the mode. Fields of that
kind in a body are ignored or refused (`test_forged_decision_fields_are_not_taken`). A proposal identifier of
another use case or workspace does not exist in this one (400): each use case has its own store.

| Threat | Answer | Residual |
|---|---|---|
| Leave the proposal reference out | Every draft is compared with every stored proposal | — |
| Name another proposal, or a revision that showed other content | The reference is checked against what the elements match; the revision recorded is the one found | — |
| Edit an element slightly and keep the reference | Refused: an edit needs a recorded correction | — |
| Edit it and drop the reference | Saved as the author's own, flagged | **Cannot be proven** (GAP-109; D37 d) |
| Type the proposal again by hand, or bring content from outside Autology | Attributed to the author; a second person publishes | The same |
| Claim "manual" in the request | No such field is read | — |
| Forge a decision, a time or an identifier | Not taken from requests | — |
| A service identity reviews or publishes | Both need a person: 403 | A service identity granted `configure` may save a draft; it is classified like any other and named as its author |
| Shorten the list of proposals a model rests on | The record only grows | — |
| Write around the API into the store | Not reachable through any route; a row without provenance is not published | Someone with access to the database file is outside this model (operations) |

### Two reviewers at once

A decision may carry `expected_version`: the review's version the reviewer read (`review.version`, the number of
decisions and corrections recorded). If the review has moved on, the decision is **not recorded**: 409, with the
review as it is now. Studio always sends it.

## 5. In Studio

* Inferred elements are **not selected** when a proposal is opened. The line above the list says how many are
  stated, inferred, confirmed, waiting and rejected.
* Each element shows its type and name, its basis, what it cites, where it stands (waiting, accepted, corrected,
  rejected, superseded), the Engine's findings, what depends on it, and its **history**: every decision, by whom
  and when, in order. History is read from the Engine; nothing is kept in the browser.
* Each element has three explicit acts: **Accept**, **Correct**, **Reject**. Each is one call to the existing
  decision route; the Engine's answer, not the click, is what the screen then shows ("recorded by the Engine").
* **Correct** opens a side-by-side editor: the element as proposed on the left, structured fields on the right
  (text, lists, pairs, flags, numbers; never code). A field that breaks the element's shape is refused in the
  editor before anything is sent. A recorded correction is validated by the Engine with everything else that is
  kept: if the result is not a model the strict loader accepts, the screen says what became invalid and which
  elements depend on it. Such a model is not published (409 from the existing publication gate).
* A reviewer who decides over a review that someone else changed meanwhile is told so, shown the current review,
  and decides again. Nothing is overwritten.
* A member without the `configure` permission, a service identity and a member of another workspace see the
  Engine's refusal, in words.
* The screen says when a new provider call **would** be needed (new questions answered, a different description)
  and makes none for a decision or a correction.
* Reviewing a proposal is not approving a release: saving a draft changes nothing that runs, and the screen says so.
* "Select the N inferred elements not yet selected, to confirm them" is one explicit act. Saving records the
  decisions not yet recorded and then saves the draft; an element already corrected is never accepted again in its
  original form.

Evidence: `studio/web/e2e/domains.mjs` (review journey, in two domains), `studio/web/tests/correction.test.ts`.

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
