# AUTOLOGY — GOVERNED OPERATIONS & AI ARCHITECT RELIABILITY REPORT

*19 November 2026. Branch `claude/autology-ontology-agent-4ajjer`. Engineering work on synthetic data with
simulated tools. **No provider was called, no credential was read, the spending ledger was not written, nothing
was deployed, and no owner decision was taken or implied.** This directive was not treated as approval of D24,
D30, D34, D35 or any other pending decision; no approval was found in the repository.*

**The sprint is partially complete, as designed:** what needed no approval is built and in force; what needs the
owner is prepared, tested as inactive prototypes, and stops there.

## Summary

| Workstream | Result | Status |
|---|---|---|
| A. AI Architect reliability | A proposal is now reviewed element by element: inferred elements are confirmed only by a person's explicit decision, decisions and corrections are persisted and attributed, a rejected element stays rejected when proposed again, and the Engine refuses a draft that takes an unconfirmed element from the proposal it names | **Implemented, active, verified** |
| B. AI Architect evaluation | The existing harness runs three treatments of inferred elements and reports the architect, the builder and the Engine apart. Replayed on kept evidence | **Implemented, verified; no provider call** |
| C. Governed business operations (D24) | The write contract and twelve security acceptance cases, against the inactive prototype | **Implemented but inactive.** Forms stay previews |
| D. Governed application releases (D34) | The release structure with a combined fingerprint, in the inactive prototype | **Implemented but inactive.** Designs stay drafts |
| E. Runtime separation (D35) | Contracts of the target; the runtime's version check | Version check **active**; the rest **proposed** |
| F. Three-domain regression | Crisis management, network intelligence, venue booking | **No regression** |
| R2 | | **Not closed** |

The quality of the architect's own inferences is unchanged by this sprint. The workflow makes them reviewable; it
does not make them right, and **no domain expert has reviewed any model.**

---

## A. Engineering baseline

| | |
|---|---|
| Branch | `claude/autology-ontology-agent-4ajjer` |
| Starting commit | `5e290be` (the documentation commit that followed `a9dd173`); working tree clean, equal to the remote |
| CI on the starting commit | [Run 124](https://github.com/edlwiseltd/ontology/actions/runs/44195281888): success, five jobs |
| Local full suite on the starting commit | 1,113 tests, all passed, 2 skipped locally (PostgreSQL; they run in CI); coverage 96.11 % |
| Final code commit | `fe37691` |
| The commit that adds this report | Follows it; documentation only |

### CI

| Commit | Run | Result |
|---|---|---|
| `5e290be` (start) | [124](https://github.com/edlwiseltd/ontology/actions/runs/44195281888) | Success |
| `fe37691` (final code) | [125](https://github.com/edlwiseltd/ontology/actions/runs/44625037181) | **Success**, all five jobs (Python 3.10 and 3.13 with PostgreSQL and the coverage gate, package, studio with its three browser suites, quality) |
| The commit that adds this report | Started by its push | Given in the delivery message: a file cannot hold the result of the run on its own commit |

### Verification on the final code

| Check | Result |
|---|---|
| Full Python suite | **1,139 tests, all passed** (were 1,113), 2 skipped locally (PostgreSQL; they run in CI) |
| Coverage | **96.12 %** (18,250 statements, 708 missed); gate 95 %, untouched |
| ruff | Clean |
| mypy ratchet | 198 errors = the baseline of 198. Not raised |
| Studio typecheck, unit tests, build | Clean; **81 unit tests** (were 80); build succeeds |
| Existing Studio browser journey | **135 of 135** |
| Cross-domain browser journey | **60 of 60** (were 56: four new checks) |
| Application Builder browser tests | **108 of 108** |
| Published API contract and generated client | Regenerated; in step |
| Spending ledger | 27 entries, file unmodified since 17 November (read-only check). Not written |
| Known secret values in the tree | Six known values searched for, by value, in 1,648 files: none found |

### Regression findings

| Finding | What was done |
|---|---|
| Two existing tests (`test_stab3_proposal_lifecycle`) saved a draft naming a proposal without recording any review of the inferred element it took | That is the behaviour this sprint ends (GAP-106). The tests now record the review first **and assert the new refusal**; nothing was removed or loosened |
| Three tests pin the store's schema version | Updated from 20 to 21 with the exact migration lists (`test_mig1_migrations`, `test_stab3_proposal_lifecycle`, `test_app1_application_builder`) |
| One browser test id of mine collided with an existing one | Renamed before any commit |

No security test was removed or loosened.

---

## B. AI Architect reliability

Described in [docs/proposal-review.md](../docs/proposal-review.md).

### B.1 What the pipeline distinguishes (inspection, A1)

| Thing | Established in | Kept in |
|---|---|---|
| Explicit user requirement | `architect.origin_of`, checked against what was really given | The element: `basis: supplied`, `origin`, `evidence` |
| Model inference | The same | `basis: inferred` |
| Unverified assumption | The contract's `assumptions` | The stored revision |
| Missing requirement | `questions`, `unknowns` | The stored revision; answers make the next one |
| Contradiction | `contradictions` | The stored revision |
| Rejected ontology element | The strict loader, when the proposal is made | `rejected`, in the loader's words |
| Human-confirmed, corrected or rejected element | `ArchitectService.decide_proposal` | `architect_decisions`, `architect_corrections`: append-only, attributed |
| Where each element stands now | `proposal_review.standing` | Computed on every read; not stored, so it cannot drift |

The traceability matrix from a business statement to an element, the Engine's finding and a person's decision is
`proposal_review.traceability` (one line per element; example in the document above).

**What was missing before this sprint (GAP-106):** nothing stopped an inferred element from entering a draft
unconfirmed. Studio selected every element by default and recorded the review only *after* saving the draft, and
the Engine checked nothing.

### B.2 The clarification and confirmation lifecycle (A2)

| # | Step | Provider call |
|---|---|---|
| 1 | Business description → proposal, stored as revision 1 | one |
| 2 to 4 | Elements with basis and evidence; unknowns, assumptions, contradictions; questions | — |
| 5 | A person answers → the next revision | one |
| 6 | **Per-element accept, correct or reject** (`POST …/proposals/{id}/decision`) | **none** |
| 7 | The review: every element's standing, what a decision broke, the loader's verdict, the consistency findings (`GET …/proposals/{id}` → `review`) | none |
| 8 | A draft, saved by a person; the Engine checks it against the review | none |
| 9 | Publication and release: the existing governance, a second person | none |

Acceptance criteria of the directive:

| Criterion | Enforced in | Test |
|---|---|---|
| Every inferred element can be reviewed individually | `proposal_review.standing` | rev1 `test_nothing_inferred_is_confirmed_by_default`; browser check |
| Human decisions are persisted and attributable | Store schema 21, append-only tables with triggers | rev1 API test: who, when, on which revision |
| Reopening a session preserves the decision history | Computed from the stored history | rev1 API test: the platform is restarted and the review is as it was left |
| Rejected elements do not silently reappear as confirmed | `standing`: a rejection carries; the element is flagged "proposed again after it was rejected" | rev1 `test_a_decision_is_about_the_element_as_it_was_shown`; API test with a third revision |
| Dependent elements are revalidated when an upstream element changes | `proposal_review.report`: dependency failures by name, then the strict loader | rev1 `test_what_depends_on…`; rev2 |
| Unsupported assumptions cannot automatically acquire authoritative status | `ArchitectService.save_draft`: 409 for a draft that takes an unconfirmed or rejected element from the proposal it names | rev1 API test; `test_stab3` (two tests) |
| No draft or release is activated by an AI-generated answer alone | Unchanged: a draft is a person's save; a release needs a second person | rev1 API test: after every step the draft revision is 0 |

Also: a decision is about the element **as it was shown** (unchanged in the next revision it carries; changed, it
is undecided again); a correction is the person's, needs no provider and is validated like any element; a service
identity, a reader and a member of another workspace decide nothing.

In Studio, inferred elements are no longer selected for the person; each shows where it stands; selecting the
inferred ones is one explicit act; saving records the review before the draft.

### B.3 Deterministic validation and diagnostics (A3)

One authority per question, and no new one. Twelve kinds of defect, evidence in
`tests/test_rev2_proposal_diagnostics.py`:

| Defect | Authority | Result |
|---|---|---|
| Undefined entity; invalid relationship endpoint; undefined property (rule or condition); missing required property; a property the schema lacks; conflicting state; missing approval authority; a rule on an unknown action; an impossible dependency in a case | Strict loader | **Refused**, in its own words |
| Rule contradiction; unreachable outcome; **circular precondition** (new: an action waits for a state only it produces) | Consistency checks | **Noticed** for a person; never refused; nothing added to the model |
| Unsupported external capability; an agent given what the model lacks | Configuration check | Refused when the configuration is saved |
| A reference left behind by a rejection | Proposal review, then the strict loader | Named, then refused |

No governance default was added to any model, and no acceptance policy changed.

### B.4 The GAP-082 boundary

**Kept.** Element-level reading of a provider answer that violates the contract (`autology/architect_elements.py`)
is still imported by nothing; an answer outside the contract is still refused whole. What this sprint put in
force is different: **people** reviewing the elements of an answer the gateway already accepted, which is the
existing proposal lifecycle made explicit and enforced.

### B.5 Unresolved model-quality limitations

* The architect's inferences are as good as they were: reviewable now, not better.
* A citation that is real but irrelevant is not detected.
* A draft that names no proposal is not checked against any (GAP-107).
* Studio cannot correct an element's content; the API can (GAP-108).
* The AI Architect has not met its acceptance thresholds with a real provider (two runs, 17 November).

---

## C. Evaluation results

`autology/chain_eval.py`, protocol `chain-v1`, extended, not replaced. V1's cases, scorer and thresholds are used
unchanged; V2 is not treated as approved and was not run. **There is no overall score.** Evidence:
`planning/evidence/chain-eval-2026-11-19/`.

### C.1 The three scenarios

| Scenario | What enters the draft | Evidence of |
|---|---|---|
| 1. No additional confirmation | Stated elements | What the answer gives alone |
| 2. Explicit selective confirmation | Also what **recorded, attributable** decisions accepted | What actual decisions made of it. No record, no scenario 2: none is invented |
| 3. Hypothetical full confirmation | Every inferred element | **A counterfactual**, not evidence that any element is right |

### C.2 Results

| Answers | Scenario 1 | Scenario 2 | Scenario 3 (counterfactual) |
|---|---|---|---|
| Reserved briefs, **reference answers (not a model)**, 2 cases | 2 drafts accepted; 2 manifests valid; 2 simulations complete | Synthetic reviewer's decisions: 2 accepted; 2 valid; one completes, one waits for a review | 2 accepted; 2 valid; one waits for a review, one escalates |
| Run 2's kept answers, **a real model**, 4 answered of 5 | **1 of 4** drafts accepted; 10 dependency failures named in the other three | **Not run: no decision is on record** | 4 of 4 accepted; 4 manifests valid; 3 of 4 simulations proceed |
| The ground-handling journey, **a real model**, 40 elements, 23 inferred | Draft **refused**; 4 dependency failures | The decisions on record (22 of 23 inferred accepted, 1 element not taken): draft **accepted**, manifest valid, simulation completes | Accepted; valid; the simulation waits for a review |

The "decisions on record" for the journey are the elements the released model's provenance says a member accepted
in Studio on 17 November. That member was the evaluation workspace's account, operated during the evaluation. It
is an acceptance in the design tool, **not a domain expert's review**.

### C.3 By component

| Component | What the evidence shows | What it does not show |
|---|---|---|
| **1. AI Architect** | From kept answers only: 4 of 5 cases answered in run 2; 114 elements proposed, 5 refused by the Engine, 41 inferred. Alone, 1 of 4 answers makes a model the Engine accepts. On the reserved briefs' reference answers, V1's measures are 1.0, which says the scorer accepts a sound answer, nothing about a model | Anything about a real model on the reserved briefs: not authorised. Semantic correctness: not assessed by anyone qualified |
| **The person's step** (not a component) | Confirmation rate, rejections, corrections and dependency failures are measured per case | Whether the decisions were right |
| **2. Application Builder** | Every draft the Engine accepted gave a valid, deterministic manifest (reference: 2 of 2; replay: 1 of 1 and 4 of 4; journey: 1 of 1) | Usability for real users |
| **3. Engine** | Refused every draft that did not make a model, naming why; ran every accepted one in a draft simulation; a decision by a role the rule does not name is refused; every simulated step leaves an event. Through the platform's API a reserved draft is released by two people and a run waits for a person (`test_chain1` C8) | A draft simulation's trace is not a signed chain, and the result says so |

### C.4 Real-provider execution gate

Not passed, and not attempted. Before any future provider evaluation: reconcile the provider invoice; confirm the
ledger's authoritative location (D31); the owner's authorisation for D30 h; model, workspace, expiry and limits;
the approved protocol (V1 until V2 is ratified); fail-closed budget enforcement verified. The ledger was not
replaced; no authorisation was inferred from the remaining balance; the grammar probe was not run; the reserved
briefs were shown to no model.

---

## D. Governed record operations (D24)

| | |
|---|---|
| **D24 status** | **Not approved.** No approval found. Engine permissions are unchanged: the eight they were (tested) |
| What exists | [Proposal](AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md) and an inactive prototype, `autology/operation_policy.py`, connected to no route |
| Application forms | **Preview only**, as before. Nobody was given unrestricted administration as a workaround |

### Permission matrix (proposed)

| Operation | Today | Proposed right | Scope |
|---|---|---|---|
| Create records | `admin` (unrestricted) | `records.create` | Named entity types and properties; the initial state only |
| Update permitted fields | `admin` (unrestricted) | `records.update` | Named properties, in named workflow states |
| Archive | No route | `records.archive` (optional) | Archive only; nothing is deleted |
| The other nine | unchanged | unchanged | See the proposal |

### Enforcement points and the order of checks (prototype)

Operation → whether it is a caller's → identity and its kind → tenant, workspace, use case and a grant in force →
entity type, properties, relationships, workflow states of the grant → record visibility → **the revision the
writer read** → the model's rules (a state is never written; a decision-critical property needs its writer rule;
`write_access`). In an implementation the single enforcement point is `server.AutologyService.upsert_object`.

### The governed write contract (C3)

Every decision returns the **requested** change and its **outcome**: `accepted`, `refused` or `simulated`.
`written` is true for `accepted` only. A rehearsal of a change that would be refused is refused. No interface may
say "saved" for a preview: the runtime's form already says "Preview: nothing is saved".

### Test cases (C4), against the inactive prototype: **non-production evidence**

Authorized creation · unauthorized creation · property-level restriction · entity-level restriction ·
cross-workspace modification · hidden record modification · invalid workflow state · attempted relationship
escalation · missing grant · stale version · concurrent update · audit integrity. All twelve in
`tests/test_d24_operation_policy.py` (15 tests in the file; the module is covered line by line).

### Audit behaviour

One record per decision, refused ones included: who, kind of identity, workspace, use case, operation, right,
entity, property and relationship names, outcome, the deciding step, the record's revision. Names only, never a
value; deterministic. The prototype signs and stores nothing: in an implementation this is the Engine's signed
access log.

### Remaining blockers

The owner's decision D24 a (and b, c, d, e). After it: the enforcement in `upsert_object`, the grant fields in the
platform, the form that sends. None of it is built.

---

## E. Governed applications (D34)

| | |
|---|---|
| **D34 status** | **Pending.** The seven questions Q1 to Q7 stand as they were, with their recommendations, which are not approvals |
| Manifest governance today | A design is a draft: validated on every read, bound to one configuration, approved by nobody, in no release. The Engine reports "approved release artifact: not supported" |
| What exists | [Proposal](AUTOLOGY_D34_GOVERNED_APPLICATION_DESIGN_PROPOSAL.md) and an inactive prototype, `autology/design_governance.py` |

### Release integration (proposed; computed by the prototype)

A release would consist of: validated ontology · approved rules · approved agent configuration · application
manifest · runtime compatibility metadata · one combined fingerprint · review and approval evidence (carried from
the existing release governance, checked, never created) · audit references. The release authority remains the
Engine's platform; Studio establishes no approval of its own.

### Fingerprint handling (tested)

* A release without a design has **exactly today's fingerprint**: no existing release changes identity.
* With a design the fingerprint covers it: a label change changes the release's fingerprint and the application
  part's, and no other part's.
* A rule change changes the rules part only; a design bound to the earlier configuration is reported.

### Rollback and migration evidence (tested)

Rolling back restores the design bound to that release, never a newer one; a release with none shows nothing as
governed. Existing drafts migrate as drafts: all kept, none approved. 12 tests in
`tests/test_d34_design_governance.py`.

Nothing of the lifecycle is activated: no route, no table, no screen.

---

## F. Runtime separation (D35)

| | |
|---|---|
| **D35 status** | **Awaiting confirmation.** No infrastructure was deployed and no identity policy changed |
| Today | The runtime shares Studio's origin, relay, content security policy and token type. Separation in the browser is by convention |

| Contract | Design | State |
|---|---|---|
| Separate origins | Studio on A, applications on B | Proposed |
| Restricted application relay | Only `/w/<ws>/u/<uc>/api/v1/` | Rule written and tested; **wired to nothing** |
| Session separation | Per-origin session storage | Follows from separate origins |
| Token scope | A runtime token refused by administration | An identity decision; not started |
| CSP boundaries | A stricter policy on B | Proposed |
| Deployment roles | One artefact, two roles | Proposed |
| **Version compatibility** | The runtime draws only the manifest format and Engine API it was built for | **Active, verified**: it shows a refusal and draws nothing otherwise |
| Migration and rollback | Each step a configuration change | Plan |

Simulation works as before (108 application checks). Details:
[assessment](AUTOLOGY_D35_RUNTIME_SEPARATION_ASSESSMENT.md) §4a.

---

## G. Three-domain regression

One Engine, one validator, one manifest generator, one designer, one renderer, one approval mechanism, one audit
system. No domain-specific branch was added (the vocabulary scans pass).

| Evidence | Crisis management | Network intelligence | Venue booking |
|---|---|---|---|
| Manifest generation, deterministic | pass | pass | pass |
| Navigation (grouped menu) | pass | pass | pass |
| Records and relationships | pass | pass | pass |
| Provenance on a record | pass | pass | pass |
| Approval-dependent action | pass | pass | pass |
| Policy-refused action | pass | pass | pass |
| Restricted data | — | pass (restricted records stay uncounted) | — |
| Release mismatch | — | — | pass |
| Audit verification | pass | pass | pass |
| Unsupported write behaviour (form is a preview; direct write refused) | pass | pass | pass |
| **New:** inferred elements wait for the person in the design journey | pass | pass | not applicable (no architect proposal: its model is saved as it is) |

Sources: 108 application browser checks, 60 cross-domain browser checks, `tests/test_app1…`, `test_app2…`,
`test_xdom1…`. The opaque-names test is retained and passes. **No regression was found.**

---

## H. Owner decision register

Status words: **Proposed** (a document) · **Implemented but inactive** (code that nothing in force calls) ·
**Approved** · **Active** · **Verified** (tested in CI).

| ID | Issue | Recommended option | Implementation impact | Approval required | Status |
|---|---|---|---|---|---|
| D24 a | Narrow record rights `records.create`, `records.update` | Yes, as scoped grants | One enforcement point; grant fields; forms send | Yes | **Implemented but inactive** |
| D24 b | Link changes under `records.update` | Yes, per relationship named | Small | Yes | Implemented but inactive |
| D24 c | `records.archive` | Leave to actions in a run | None if left | Yes | Implemented but inactive |
| D24 d | "Execute" and "request review" never a caller's | Confirm | None | Yes | Proposed |
| D24 e | With the `operate` specification or apart | Together | — | Yes | Proposed |
| D26 | Readiness weights | Unchanged | — | Yes | Provisional |
| D30 f | Element-level recovery of a non-conforming answer (GAP-082) | Decide after a reviewed replay | Module exists | Yes | **Implemented but inactive** |
| D30 g | Evaluation protocol V2 | Ratify before any further paid run | Cases and scorer exist | Yes | Proposed |
| D30 h | A third paid evaluation | After D30 g and the invoice reconciliation | None | Yes | **Not authorised** |
| D31 | Location of the spending ledger | Keep the durable file outside the deployment | None | Yes | Pending |
| D32 | Several governed agents in a run | Unchanged | Design only | Yes | Proposed |
| D33 | Cross-domain engineering defaults | Confirm | None | Confirmation | Active, awaiting confirmation |
| D34 Q1 | Does the manifest become a release artifact | A: a named part of a release | Release part, fingerprint, publish step | Yes | **Implemented but inactive** |
| D34 Q2 | Does release approval include the manifest | A: yes, shown in readiness | Small | Yes | Implemented but inactive |
| D34 Q3 | A separate design reviewer | A: no | None | Yes | Implemented but inactive |
| D34 Q4 | Do manifest changes require new releases | A: yes | Follows Q1 | Yes | Implemented but inactive |
| D34 Q5 | How rollback restores presentation | A: the release's own design; else nothing | Follows Q1 | Yes | Implemented but inactive |
| D34 Q6 | Suspension and revocation | A: one suspends, two resume or revoke | Small | Yes | Implemented but inactive |
| D34 Q7 | Migration of existing drafts | A: all kept as drafts, none approved | Small | Yes | Implemented but inactive |
| D35 a | One origin acceptable for simulation only | Confirm | None | Confirmation | Active, awaiting confirmation |
| D35 b | Two roles, two origins | Approve | Small; no Engine change | Yes | Proposed |
| D35 c | Tokens for one plane | Into the identity roadmap | Identity change | Yes | Proposed |
| **D36 a** | A draft naming a proposal is refused when it takes an unconfirmed or rejected element (new) | Confirm | Done | Confirmation | **Active, verified**, awaiting confirmation |
| **D36 b** | Studio does not select inferred elements for the person (new) | Confirm | Done | Confirmation | Active, verified, awaiting confirmation |
| **D36 c** | A decision holds while the element is unchanged; a rejection carries (new) | Confirm | Done | Confirmation | Active, verified, awaiting confirmation |
| **D36 d** | A person may correct an element through the API (new; store schema 21) | Confirm | Done | Confirmation | Active, verified, awaiting confirmation |
| **D36 e** | The runtime draws only the format and API it was built for (new) | Confirm | Done | Confirmation | Active, verified, awaiting confirmation |

D36 is a set of engineering defaults applied by this sprint. Each refuses more than before or records more than
before; none widens what anyone may do. They are reversible and are not presented as owner decisions.

---

## I. Product readiness

**1. Can the AI Architect identify and isolate uncertain ontology elements?**
Partly, and the isolation is the system's, not the model's judgement. Every element carries whether the
description states it or the architect inferred it, and that claim is checked against what was really given
(`architect.origin_of`; `test_stab3` provenance tests). The Engine then isolates inferred elements for review
(`test_rev1` R1). Whether the architect marks the *right* elements as uncertain was not measured.

**2. Can a person confirm or reject those elements without losing provenance?**
Yes. Each decision and correction is stored append-only with who, when and on which revision, survives a restart,
and the element keeps its basis, origin and evidence (`test_rev1` API test; `test_stab3` "provenance survives
from the brief to the release").

**3. Does selective confirmation improve technical acceptance?**
On the evidence available: yes, in one case of one. For the one kept real-model answer with decisions on record,
the draft is refused without confirmations and accepted with the 22 of 23 inferred elements a member accepted
(`test_chain1` journey test). For the four kept V1 answers no decision is on record; the counterfactual shows 1 of
4 becoming 4 of 4, which is an upper bound, not a finding.

**4. What evidence exists that the resulting ontologies are semantically correct?**
**None.** Technical acceptance says the Engine can load and run a model. No domain expert reviewed any model, and
this report claims no expert review. The reference answers were written by an engineer to exercise the harness.

**5. Can the Application Builder generate valid applications from confirmed models?**
Yes: every draft the Engine accepted produced a valid, deterministic manifest, in every scenario (`test_chain1`;
evidence files), and the reserved drafts are rendered in a browser (application browser suite, section "chain").

**6. Can applications create or update records under approved least-privilege permissions?**
**No.** No such permission is approved or exists in the Engine. Forms are previews; a direct write by an
application user is refused (`test_app1` B9). The proposed semantics are tested on an inactive prototype only.

**7. Are application designs governed release artifacts?**
**No.** They are drafts; the Engine says so itself.

**8. Does the Runtime remain isolated from unauthorized Engine capabilities?**
At the Engine: yes. Every request is authorised by the Engine whatever the runtime sends (`test_app2`), the
runtime asks only its use case's versioned API, and it now refuses formats it was not built for. In the browser:
not by a boundary. It shares Studio's origin and relay (GAP-103).

**9. Can the complete process run on an unfamiliar domain without a prepared template?**
With a reference answer standing in for the architect: yes, end to end, for two reserved domains, through the
platform's API and in a browser. **With a real model: not demonstrated**, and not attempted (not authorised).

**10. Which requirements still block R2?**
The AI Solution Architect below its acceptance thresholds with a real provider; the owner's decisions D24, D26,
D30 f/g/h, D31, D32, D33, D34, D35, D36; unratified readiness weights; the remaining ARC-0 decomposition;
independent verification of what is "met at repository level".

**11. What prevents production use?**
Production execution is disabled and not authorised. Also: no narrow write permission (D24); designs not governed
(D34); runtime not isolated in the browser (D35); the architect's reliability unproven; no domain-expert
validation; simulated tools only, no connector to a real system; no independent security review; legal approvals
outstanding (GAP-031, D19); no search in the Engine (GAP-102); no evidence at production size.

**12. What is the smallest defensible next milestone?**
The owner's answer to **D24 a**. With it, `records.create` and `records.update` are enforced in one place and the
three demonstrations' forms become governed writes. It needs no provider, no deployment change and no other
decision. The second smallest: authorising the chain evaluation on the two reserved briefs (D30 h, after the
invoice is reconciled), which is the only way to learn how a real model does on a domain nothing was built for.

---

## Definition of Done

| Condition | State |
|---|---|
| The final code passes complete CI | **Met** for the final code: `fe37691`, CI run 125, all five jobs. The documentation-only commit that adds this report is checked by the run its push starts; that result is in the delivery message |
| Existing business applications do not regress | **Met** (section G) |
| Ontology proposals preserve source and inference provenance | **Met** |
| Human confirmation is explicit, persisted and auditable | **Met** |
| Unresolved assumptions cannot silently become authoritative | **Met** for a draft that names its proposal; **not** for a draft that names none (GAP-107, stated) |
| Existing real-model outputs can be replayed deterministically | **Met**; the kept files are byte-identical before and after (tested) |
| AI Architect, Builder and Engine results are measured separately | **Met**; no overall score |
| Narrow-write readiness is documented and tested without unauthorized activation | **Met**; inactive |
| Application-release governance is documented and tested without unauthorized activation | **Met**; inactive |
| Existing permissions, release gates and audit integrity remain intact | **Met**; the Engine's permissions are the eight they were |
| Historical provider results and spending history are preserved | **Met**; ledger unmodified |
| Every pending owner decision remains explicitly identified | **Met** (section H) |
| R2 is not declared closed | **Not closed** |

## Evidence

| What | Where |
|---|---|
| Review rules, in force | `autology/proposal_review.py`, `autology/architecting.py`, store schema 21 |
| Tests added | `test_rev1_proposal_review` (9) · `test_rev2_proposal_diagnostics` (6) · `test_chain1…` (15, were 11) · `test_d24…` (15, were 11) · `test_d34…` (12, were 8) |
| Evaluation evidence | `planning/evidence/chain-eval-2026-11-19/` (three scenario reports, text and JSON; the journey with its recorded decisions) |
| Documents | [proposal review](../docs/proposal-review.md) · [chain evaluation](../docs/chain-evaluation.md) · [D24](AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md) · [D34](AUTOLOGY_D34_GOVERNED_APPLICATION_DESIGN_PROPOSAL.md) · [D35](AUTOLOGY_D35_RUNTIME_SEPARATION_ASSESSMENT.md) |
| Registers | Defect register: 108 entries (62 fixed, 21 open, 13 partly fixed, 7 owner decision, 5 external evidence). Decision register: D36 added. Traceability: GOV-A1 to GOV-E |
