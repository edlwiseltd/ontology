# Autology — independent semantic review: readiness package

*20 November 2026. Status: **a package prepared for a review that has not taken place.** No independent domain
expert has reviewed any model. No reviewer was contacted, invited or appointed. Nothing was sent or uploaded. Every
judgment field of every real form is empty. The only filled forms are those of a rehearsal on a synthetic case, by
reviewers named as not being people. No provider was called.*

It starts from Part C of `planning/AUTOLOGY_DOMAIN_EXPERT_REVIEW_REQUIREMENTS.md` and keeps it. The changes it
proposes to Part C are listed in §4, openly; none replaces protocol V1, and proposed protocol V2 stays proposed
(D30 g).

## 1. What a review can and cannot establish

| Statement | Established by | Not established by |
|---|---|---|
| The model loads, is consistent and can run | The Engine (already measured) | — |
| A member confirmed an inferred element | The recorded decision | — |
| **The model describes the business correctly** | **An independent person qualified in the domain** | The Engine's acceptance; a member's confirmation; any automated score; this package |

Results stay in three sections and are never added up:

| | Component | What is reported | Who establishes it |
|---|---|---|---|
| A | **AI Architect** | Fidelity to the brief, completeness, assumptions, evidence, semantic defects | The independent reviewers (S1 to S6, M1 to M5, M7) |
| B | **Application Builder** | Whether a manifest is generated deterministically and conforms to the accepted model | Deterministic checks. The reviewer's view of the screens (M6) is reported here, apart from A |
| C | **Engine** | Structural validity, authorization, enforceable constraints | Deterministic checks and tests |

A review is of the **original output as frozen**. A model after a person's corrections is a different subject; if it
is reviewed, the result is labelled "corrected model" and kept apart. A blanket confirmation by a member is not
independent evidence of anything.

## 2. Frozen case inventory

Produced by `python deploy/make_review_package.py inventory planning/review-package`; kept in
`planning/review-package/inventory.json` and `.txt`; a test compares the kept file with what the tool produces, so
a changed artifact no longer matches (`tests/test_semrev1_review_package.py`). Hashes are SHA-256 of the files as
they are in the repository.

### 2.1 Real model outputs (answered on 17 November 2026 under the authorisation then in force)

| Case | File | Elements (stated / inferred) | Refused by the Engine | Stored citations | Decisions on record |
|---|---|---|---|---|---|
| `journey:ground-handling` | `planning/evidence/claude-eval-2026-11-17/ground-handling/proposal-revision-2.json` | 40 (17 / 23) | 0 | 28 cite the brief as a whole; **12 cite nothing**; none cites an answer | 39 of 40 accepted by a project member (22 of 23 inferred). A member, not an expert |
| `run2:b2b-procurement:1` and `:2` | `…/run2-after-correction/b2b-procurement-1.json`, `-2.json` | 26 (17 / 9); 28 (18 / 10) | 1; 1 | Every element cites the brief as a whole | None |
| `run2:global-logistics:1` | `…/global-logistics-1.json` | 29 (17 / 12) | 1 | The same | None |
| `run2:hospital-operations:1` and `:2` | `…/hospital-operations-1.json`, `-2.json` | 26 (16 / 10); 38 (15 / 23) | 2; 2 | The same | None |
| `run2:insurance-claims:1` and `:2` | `…/insurance-claims-1.json`, `-2.json` | 28 (18 / 10); 32 (21 / 11) | 1; 1 | The same | None |
| `canary:bicycle-rental` | `…/canary/proposal.json` | 20 (12 / 8) | 5 | Every element cites the brief as a whole | None. A three-sentence connectivity request: **not proposed for review** |

The exact hash of each file is in `planning/review-package/inventory.txt`. `airline-disruption` has no kept answer
in run 2 (the answer was refused whole then): there is nothing to review for it.

### 2.2 What exists without any model output

| Case | What it is | Reviewable now? |
|---|---|---|
| `reserved:museum-loans`, `reserved:harbour-pilotage` | Held-out briefs. Each has a **hand-written reference answer** and the decisions of a synthetic reviewer written with the case | **No.** No real model has answered them. Their content is not copied into this package or used in any example |
| `v2:*` (eight cases) | Held-out cases of proposed protocol V2, never run | **No** |
| The three domain packs (crisis management, network intelligence, venue booking) | Engineer-written templates | Covered by Parts A and B of the requirements, not by this package |

### 2.3 What each record lacks, and what that does to a review

| Gap | Where | Effect on what an expert can judge |
|---|---|---|
| Citations are coarse: "brief", never a passage | Every kept answer | S4 (basis) is judged against the whole brief. The reviewer cannot be shown which sentence an element rests on, because none was recorded |
| 12 inferred elements cite nothing | `journey:ground-handling` | S4 is "nothing cited" for them; S1 to S3, S5 and S6 can still be judged |
| No element shows the answer it came from | `journey:ground-handling` (GAP-081, fixed for later proposals) | Whether the clarification answers were used correctly cannot be traced per element; M4 is judged from the list of questions and answers as a whole |
| No structured evidence entry | Every kept answer (the field was introduced after 17 November) | The element trace of the chain evaluation shows the stored coarse label instead, marked "cited at the time; not re-checked" (GAP-113, fixed on 20 November; before that it wrote these links as missing). The Engine never checked these citations against what was given |
| No decision of any person | The seven run 2 answers | There is no "selective confirmation" to review; any "all confirmed" figure about them is a counterfactual |
| The briefs were written by the project | Every case | A reviewer judges the model against a synthetic description, not against a real organisation |
| Held-out cases are files of the repository and of the shipped package | Reserved and V2 cases (GAP-114) | Before any real-model run on them: who can read the repository and the package decides whether they are still held out |

Nothing missing is reconstructed. The eleven links of the element trace (source, suggestion, evidence,
clarification, decision, draft, validation, release, application, simulated action, audit) are kept as they are,
with `missing: <why>` where a link does not exist. The package holds element names and model content only: no
record, and no value of a record.

## 3. Readiness per case

| Case | Frozen artifact | Source evidence available | Rubric | Still needed from the owner | What the expert can judge |
|---|---|---|---|---|---|
| `journey:ground-handling` | Yes (hash in the inventory); blank form generated on request, 40 rows | The brief, the 8 answers a member gave to the architect's first questions, 7 further questions, 4 assumptions, 4 unknowns; per element a rationale and a coarse citation (28 of 40) | Part C, as extended in §4 | Reviewer appointment; agreement to share the brief and the output outside the project; rubric and thresholds agreed before scoring | A fully, except S4 for 12 elements. A second, separately labelled review of the released (corrected) model is possible |
| `run2:*` (four cases, seven answers) | Yes; forms on request | The brief; per element a rationale and "brief" | The same | The same, per domain: procurement, logistics, hospital operations, insurance claims | A, with S4 against the whole brief. No decisions to review |
| `reserved:*`, `v2:*` | Frozen, but no model output | — | — | A separately authorised real-model run, the D30 gates and a reconciled spending record | Nothing yet |

**Ready now:** the inventory, the rubric, the blank form, the completeness check, the protocol, and the rehearsal.
**Not ready, and not for engineering to supply:** reviewers, their appointment, the agreement to share, the agreed
thresholds.

## 4. Rubric

Scale for every criterion: **0** wrong or harmful · **1** misleading or materially incomplete · **2** acceptable
with corrections · **3** correct as it stands · **n/a**. A field left empty was not judged and is never counted.

| # | Per element | Covers |
|---|---|---|
| S1 | Existence | Entities, relationships, actions and rules that exist in the business as described |
| S2 | Naming and terminology | What practitioners call it |
| S3 | Content | Properties, states, **cardinalities**, conditions, limits |
| S4 | Basis | "Stated" is stated; "inferred" is a reasonable inference; **unsupported inference** |
| S5 | Authority | The role that decides holds that authority in practice |
| S6 | Safety and **operational consequence** | Harm, loss or breach of duty if acted on as modelled |

| # | Per model | Covers |
|---|---|---|
| M1 | Completeness | **Omissions** the business cannot work without |
| M2 | Process fidelity | The order work really takes, exceptions included |
| M3 | Approvals | Decisions reserved for a person: missing ones, needless ones |
| M4 | Clarification | Whether the questions were the ones a practitioner would ask first |
| M5 | Confirmed inferences | Inferred elements a member confirmed that should not have been (only where decisions are on record) |
| M6 | Fitness of the application | Reported under component B |
| M7 | **Contradictions** | Within the model, or between the model and the brief |

**Proposed changes to Part C, for agreement (not applied to Part C itself):**

| Change | Why |
|---|---|
| M7 added | Part C had no place for contradictions |
| A **severity** per element (none, minor, major, critical), recorded apart from the ratings | An average hides one dangerous element. Critical defects are listed separately and never averaged |
| An **uncertainty** per element (low, medium, high) | A reviewer who is unsure should be able to say so |
| A **cited domain basis** per judgment (a standard, a regulation, a named practice, or "professional experience") | A critical finding must be checkable |
| The element's **version** on each row | A judgment is about one content; a form about another content is refused |

**Two instruments exist, and one must be chosen before scoring.** Proposed protocol V2 has its own form (one
judgment per element, 1 to 5; `architect_eval_v2.review_form`). Part C has six criteria on 0 to 3. They are not
interchangeable. Recommendation: Part C as extended here, because it separates what is wrong from how much it
matters. Choosing it does not ratify V2 and changes nothing in V1.

### Severity

| Severity | Meaning |
|---|---|
| Critical | Acting on the element as modelled could cause harm, loss, a breach of duty or of law, or makes the model unusable for its purpose |
| Major | Wrong in a way that changes how work is done or who decides |
| Minor | Naming, wording or detail without operational consequence |
| None | No defect |

A rating of 0 or 1 owes a rationale and a severity. A critical defect owes a rationale and a cited domain basis.
The completeness check enforces both.

### Thresholds (proposed; **to be agreed before any review; blank until then**)

No result exists, so no threshold can have been fitted to one. These are proposals only; nothing in the tool
applies them.

| # | Proposed rule | Agreed value |
|---|---|---|
| T1 | Any critical defect that survives adjudication: the model is "not acceptable as proposed", whatever the other ratings | |
| T2 | An element is "acceptable" when, after adjudication, S1, S3 and S6 are each 2 or 3 | |
| T3 | Share of acceptable elements required to call a model "usable as a starting point" (proposed: 80 %) | |
| T4 | Share of inferred elements rated 0 or 1 on S4 above which the architect's inferences are reported as unreliable for that case (proposed: 20 %) | |
| T5 | An element not judged by both reviewers is reported as not judged, and counts towards nothing | |

### Disagreement, adjudication, repeats, missing evidence

| Topic | Rule |
|---|---|
| Independence | Reviewers work apart and do not see each other's form, the case's expectations, the automated scores or, for a review of the original output, the member's decisions |
| Disagreement | Listed for adjudication when two ratings of one criterion are two or more points apart, or when one reviewer alone calls a defect critical (`disagreements` in the tool) |
| Adjudication | A third qualified person named by the owner, or a recorded joint session. Both original forms are kept; the adjudicated value is stored beside them, never over them |
| Repeat review | When the artifact's hash changes, a new model answer exists, the rubric version changes, or a conflict of interest is discovered |
| Missing evidence | An element that cites nothing: S4 is recorded "n/a: nothing cited", and the element is still judged on the rest. A missing link is reported as missing, not held against the model and not repaired |
| Recording | Forms are stored beside the evidence they concern, with roles and declarations. They change no earlier score and no threshold |

## 5. Reviewers (**pending the owner's agreement and appointment**)

| Requirement | Proposal |
|---|---|
| Number | **Two** independent reviewers per case, with adjudication. Pending agreement |
| Expertise | Has done or supervised the work the brief describes: for ground handling, turnaround coordination or airport operations; for the run 2 cases, procurement, freight logistics, hospital operations, insurance claims handling |
| Independence | Not a member of the project; did not write the case, the brief or the model; not employed by a party with an interest in the result |
| Disclosures | Role and organisation, experience, any relationship with the project, any commercial interest. Recorded on the form |
| Who cannot stand in | The author of the case or the model; any member of the engineering team; **an AI assistant, this one included** |
| Appointment | By the owner, in writing, with the date. The form records who appointed the reviewer; a form without it is refused by the check |
| Sharing | The brief and the model output would leave the project. They are synthetic and hold no personal data; sharing them is still the owner's decision, with whatever confidentiality terms the owner wants |

A draft of the instructions a reviewer would receive is in §8. **It has not been sent to anyone.**

## 6. The blank form

`python deploy/make_review_package.py form <case> <folder>` writes a form for one frozen artifact, as JSON and as
a sheet (CSV), with one row per element and **every judgment empty**. No form is generated for a case without a
model output. Forms for the real cases are generated when a review is authorised, not kept in the repository.

| Part | Fields |
|---|---|
| Header | Case; artifact; artifact SHA-256; subject ("the original output as frozen: not a corrected model"); rubric version |
| Reviewer | Name; role and organisation; domain experience; independent of the project; conflicts disclosed; appointed by; date |
| Per element | Element id; **version**; kind; basis shown; what it cited at the time; S1 to S6; judgment; cited domain basis; rationale; severity; uncertainty; suggested correction |
| Per model | M1 to M7; what is missing; what is wrong |

`python deploy/make_review_package.py check <form.json>` refuses a form with an undeclared or non-independent
reviewer, a row about another content than the one frozen, a missing row, a rating outside the scale, a low rating
without rationale and severity, or a critical defect without a cited basis. Its summary gives counts per criterion
and lists critical defects apart. It computes **no average over criteria, no total and no verdict**.

## 7. Rehearsal (synthetic; readiness evidence only)

Run on 20 November with `python deploy/make_review_package.py rehearse planning/review-package`; kept in
`planning/review-package/rehearsal.json`.

| | |
|---|---|
| Case | An engineer-written example model (`examples/domains/venue_booking/model.json`, 17 elements). **Not** a held-out case, not a model output |
| Reviewers | Two, each named "SYNTHETIC REHEARSAL: not a person, not a reviewer". Their judgments are derived from the position of a row, so they mean nothing about the model |
| A blank form | Refused: reviewer not declared |
| Two filled forms | Accepted as complete |
| A form about another content | Refused for that element |
| A synthetic reviewer on a form not marked as a rehearsal | Refused |
| Disagreements | 2 elements listed for adjudication; 1 critical defect listed apart |
| What it shows | The package is complete and the form can be filled and checked |
| What it does not show | Anything about any model, any domain or any reviewer |

## 8. Draft instructions for a reviewer (**draft; not sent; no recipient exists**)

> You are asked to judge whether a model of a business process describes that business correctly. You are not
> asked to review software. You receive a description of the business (written for this exercise; it is not a real
> organisation), the model a language model proposed from it, and a form. For each element, rate six criteria from
> 0 to 3, and say how serious any defect is. Leave empty what you cannot judge. Where you find a serious defect,
> say what in your professional knowledge it rests on. Work alone; another reviewer does the same, and your forms
> are compared afterwards. Your name, role and any relationship with the project are recorded with your review.

## 9. Evidence distinctions that must survive any report

* `museum-loans` and `harbour-pilotage` are reserved briefs. The answer used in their replays is a **reference
  answer written by hand**, with **synthetic** review decisions. It is not a model's output.
* The run 2 files are real provider outputs of 17 November. An "all confirmed" figure about them is a
  **counterfactual**: nobody confirmed anything.
* The ground-handling proposal is a real provider output; its recorded decisions are a project member's.
* No reserved brief has an authorised real-model answer.

## 10. What this package does not authorise

A provider run, on the reserved briefs or anything else, needs its own explicit authorization, a reconciled
spending record, and the applicable D30 gates. D30 f stays inactive, D30 g (V2) proposed, D30 h not authorised.
Being ready for an expert review authorises no inference, no sharing of data outside the project and no spending.

## 11. Readiness checklist

| Item | State |
|---|---|
| Frozen inventory with hashes and gaps | **Ready** |
| Rubric, severity, form, completeness check | **Ready** (proposed extensions listed in §4) |
| Rehearsal | **Done, synthetic** |
| Choice of instrument (Part C as extended, or the V2 form) | Pending the owner |
| Thresholds T1 to T5 | Pending the owner, before any scoring |
| Number of reviewers and adjudication | Pending the owner |
| Which cases to review first | Pending the owner (suggestion: the ground-handling proposal, the only one with answers and decisions on record) |
| Appointment of reviewers; agreement to share | Pending the owner |
| A review | **Has not taken place** |

### Decision form — independent semantic review

| | |
|---|---|
| Instrument (Part C as extended / V2 form) | |
| Thresholds agreed (T1 to T5, with values) | |
| Cases to review first | |
| Number of reviewers; adjudicator | |
| Reviewers appointed (names, roles, date) | |
| Sharing outside the project authorised (what, with whom, on what terms) | |
| Decision-maker | |
| Date | |
| Durable reference | |
