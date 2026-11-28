# AUTOLOGY — APPLICATION BUILDER STABILIZATION & AI READINESS REPORT

*17 November 2026. Branch `claude/autology-ontology-agent-4ajjer`. Engineering sprint on synthetic data with
simulated tools. **No provider was called, no credential was read, nothing was spent, nothing was deployed, and no
owner decision was taken or implied.** Where something is planned and not done, this report says "not done".*

## Summary

| Area | Result |
|---|---|
| CI on the Application Builder's final commit | **Green** (run 120). This sprint: run 121 green; run 122 **failed** on a packaging pin; run 123 on the corrected, final code **green** in all five jobs (see A) |
| Application integrity and security | Verified by direct requests against the Engine. **No Engine defect was found.** One real gap in wording was closed: the Engine now says what a design is, and that it is not a release |
| D24, D34, D35 | Each has a reviewable proposal with an **inactive**, tested prototype. **None is approved, none is active** |
| Usability | An application now says what it is and what it runs on; the menu is grouped; a record shows its provenance |
| AI Architect readiness | An end-to-end harness reports the architect, the builder and the Engine **apart**. It ran on reference answers and on the answers kept from the authorised evaluation. **No real-provider run on new briefs: not authorised** |
| R2 | **Not closed** |

---

## A. Baseline and CI

| | |
|---|---|
| Starting HEAD | `18e8b17` (the Application Builder sprint's last commit), working tree clean, equal to the remote |
| Final code HEAD | `a9dd173`. The commit that adds this report follows it and changes documentation only (registers, log, roadmap, WIP, this file) |
| Git status at the end | Clean; local branch equal to `origin/claude/autology-ontology-agent-4ajjer` |

### CI runs (GitHub Actions, workflow `tests`: five jobs — test 3.10, test 3.13 with PostgreSQL and the 95 % coverage gate, package, studio, quality)

| Commit | Run | Result |
|---|---|---|
| `d9448b4` (before this sprint) | [119](https://github.com/edlwiseltd/ontology/actions/runs/44183758242) | Failed, as expected: an older test pinned the two headers Studio's relay forwarded |
| `18e8b17` (**baseline**) | [120](https://github.com/edlwiseltd/ontology/actions/runs/44184862851) | **Success**, all jobs |
| `30d6229` (increments 1 and 2) | [121](https://github.com/edlwiseltd/ontology/actions/runs/44189543152) | **Success**, all jobs |
| `316da27` (increments 3 and 4) | [122](https://github.com/edlwiseltd/ontology/actions/runs/44191809695) | **Failed** in the two Python jobs; `package`, `studio` and `quality` did not fail. One test: an older packaging test pinned the exact list of data folders the package ships, and increment 4 added one (the reserved briefs) |
| `a9dd173` (the pin corrected; **final code**) | [123](https://github.com/edlwiseltd/ontology/actions/runs/44193229434) | **Success**, all five jobs |
| The commit that adds this report (documentation only) | Started by the push | A file cannot contain the result of the CI run on its own commit: that result is given in the delivery message, and it does not change the code that run 123 verified |

### Local verification

| Check | On | Result |
|---|---|---|
| Full Python suite | `18e8b17` (baseline) | 1,077 tests, all passed, 2 skipped locally (PostgreSQL; they run in CI). Coverage 96.01 % (17,552 statements, 701 missed) |
| Full Python suite | `be5b21b` (increment 1) | 1,083 tests, all passed. Coverage 96.01 % |
| Full Python suite | `2d62473` (increment 3) | 1,102 tests, all passed. Coverage 96.07 % (17,804 statements, 700 missed) |
| Full Python suite | `316da27` (increment 4) | 1,113 tests: **1,112 passed, 1 failed** (the packaging pin described under CI run 122). Coverage 96.11 % |
| Full Python suite | `a9dd173` (**final code**) | **1,113 tests, all passed**, 2 skipped locally (PostgreSQL; they run in CI). Coverage **96.11 %** (17,980 statements, 700 missed) |
| Known secret values in the tree | final code | Six known values searched for, by value, in 1,636 files: none found |
| ruff | final code | Clean |
| mypy ratchet | final code | 198 errors = the accepted baseline of 198. **Not raised** |
| Studio typecheck, unit tests, build | final code | Clean; **80 unit tests** (were 73); build succeeds |
| Existing Studio browser journey | increment 3 | **135 of 135** |
| Cross-domain browser journey | increment 3 | **56 of 56** |
| Application Builder browser tests | final code | **108 of 108** (were 87) |
| Published API contract and generated client | final code | Regenerated; CI's `git diff --exit-code` check passes (runs 121, 122) |

### Were the two corrected test expectations a loss of coverage?

No. The two pins corrected at the end of the previous sprint still assert exact values:
`tests/test_stab3_proposal_lifecycle.py` asserts the migration list `[19, 20]` and schema `20` (was `[19]`, `19`), and
`tests/test_studio_separation.py` asserts exactly the three headers the relay forwards (was two). Neither was
loosened to "at least". In this sprint two existing assertions changed, both to a stricter or equal exact value.
`tests/test_app1_application_builder.py` B9 read nine proposed operations from `appspec`; it now reads twelve from
`operation_policy`; its behavioural part is unchanged (an application user's write is 403; a grant naming a proposed
right is 400), and it refuses one more proposed right than before. `tests/test_delivery.py` pinned the exact list of
data folders the package ships; it now pins the exact new list (one folder more) and also counts the two reserved
briefs. I had not found that pin before pushing increment 4, which is why CI run 122 failed.

**No test was removed. The coverage threshold (95 %) was not touched. The mypy baseline was not raised.**

### Outstanding failures

None on the final code (`a9dd173`): CI run 123 and the local full suite are green. During the sprint one CI run failed (122), on a packaging pin that I had not found before pushing increment 4. It was corrected to the exact new value, not loosened, and the full suite was run again afterwards.

---

## B. Application Builder integrity

A security claim below names the place in the Engine that enforces it and the test that tries to break it. No claim
rests on a screen. Tests send requests directly (`tests/test_app2_application_integrity.py`, six tests, eight
properties; `tests/test_app1_application_builder.py`).

### Release binding

| Situation | Engine's answer | Enforced in | Negative test |
|---|---|---|---|
| A newer release is activated under a saved design | 409; the design is reported as saved, valid for nothing that runs, bound to another configuration, not simulation-ready | `applications.ApplicationService.application`, `.governance` | app2 S2; browser "after a new release…" |
| Rollback to an earlier release | 409 for the newer design | Same | app1 B6 |
| A manifest of another workspace or use case is saved here | 400: the binding names another model, configuration, workspace, use case | `appspec.validate` | app1 B6 |
| A stale manifest (the model changed under it) | Not served: validated again on every read | `applications.ApplicationService.application` | app2 S2, S3 |
| A design written into the store behind the API (hostile title, an invented `grants` property) | 409 "no longer validates"; never served; grants nothing | Same; `appspec.SCHEMA` is closed | app2 S3 |
| Invalid or foreign configuration fingerprint on a request (eight shapes: zeros, truncated, upper case, padded, `null`, `*`, 5,000 characters, a tab) | 409 before anything is done; the caller's value is not echoed at length | `applications.expect_configuration` | app2 S8 |
| No configuration named on a request | **Served as always** | — | app2 S8 |
| The right configuration, without a token | 401 | `server` authentication | app2 S8 |
| The right configuration, without the permission | 403 | `server.AutologyService.require` | app2 S8 |

**The distinction the directive asks to preserve is preserved and tested:** the configuration header is a
compatibility precondition. It protects an honest application from acting on a solution that changed under it. It
is not a credential and not a permission; a client that omits it is served exactly as far as its token allows. "A
stale client cannot silently operate against an unintended release" is therefore true for the runtime (which always
sends it) and **not a guarantee against a client that chooses not to send it**; such a client still acts only
within its own permissions, and every run records the configuration it ran on.

### Security checks

| Claim | Enforced in | Negative test | Result |
|---|---|---|---|
| A manifest grants no permission | `appspec.SCHEMA` (closed: no place for one); `server.AutologyService.require` on each route | app1 B7, B9; app2 S3 | Holds |
| A restricted view cannot expose records | `server.AutologyService.visible` on every data route, whatever a manifest shows | app2 S5 | Holds |
| Restricted properties do not leak through relationships | `server.AutologyService.object_view` (redaction); `appspec.tailor` removes the column | app2 S4 | Holds |
| Counts and listings do not reveal hidden records | `visible` applied before counting; a hidden row is 404 by identifier and absent from every link | app2 S5; browser "restricted records stay uncounted" | Holds |
| A service identity cannot approve a human decision | `server.AutologyService.require_person` | app2 S6 (a service identity holding `review` and the reviewer role: 403) | Holds |
| The requester cannot decide their own request; an administrator cannot by office | Review service; IAM-3 | app2 S6 | Holds |
| Users cannot invoke actions of another workspace | `platform` routing and membership | app2 S7 (with and without the other workspace's configuration) | Holds |
| Metadata cannot inject executable code | `appspec.UNSAFE` refuses markup, addresses, template expressions; the runtime never turns data into markup (source test) | app1 B4; `runtime.test.ts`; browser "hostile designs are refused" | Holds |
| A stale client cannot silently operate against an unintended release | `applications.expect_configuration` | app2 S8 | Holds **for a client that names its configuration** (see above) |

**No Engine insufficiency was found, so no security correction was made.** The search function of the Engine does
not exist (GAP-102), so "search results" were tested as listings and counts.

### Misleading status: what was wrong and what was changed

Before this sprint an application said "design preview: not part of a governed release" in one line of its banner,
and Studio's designer said "saved as a design draft". True, but a reader could not tell *validated* from *bound*
from *approved*. Now the **Engine** computes six states and both screens print them as received:

| State | Engine supports it | Example: a saved, valid design on the configuration that runs |
|---|---|---|
| Design draft | yes | yes |
| Validated design | yes | yes |
| Configuration-bound design | yes | yes |
| **Approved release artifact** | **no** | **not supported** (owner decision D34) |
| Simulation-ready | yes | yes |
| **Production authorized** | **no** | **not supported** (production execution is disabled) |

A state the Engine does not have is printed as "not supported", not "no". A unit test fails if any screen of the
runtime or the designer uses the words *deployed*, *published*, *operational*, *live* or *released application*, or
names production other than to say it is unavailable.

### Remaining integrity limits

| Limit | Where recorded |
|---|---|
| A design is not approved by anyone and is in no release | GAP-101, D34 |
| The configuration header is optional for a client | By design; stated above and in `docs/application-builder.md` §4 |
| The runtime shares Studio's origin: browser-side separation is by convention | GAP-103, D35 |
| No independent security review or penetration test was run | Stated; not claimed |

---

## C. Governance readiness

### C.1 D24: least-privilege operations (proposal; **not approved, not active**)

[AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md](AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md)

| # | Operation | Today | Proposed |
|---|---|---|---|
| 1 | Read records | `read` | unchanged |
| 2 | Create records | `admin` (unrestricted) | **`records.create`**: named entity types and properties, the initial state only |
| 3 | Update permitted fields | `admin` (unrestricted) | **`records.update`**: named properties, in named workflow states |
| 4 | Delete or archive records | No route deletes | **`records.archive`**: archive only; nothing is deleted |
| 5 | Request an action | `run` | unchanged |
| 6 | Execute an authorized action | The Engine, inside a run | **Never a caller's** |
| 7 | Request review | The Engine, when a run reaches a review rule | **Never a caller's** |
| 8 | Decide a review | `review` + reviewer role, a person | unchanged |
| 9 | Administer domain data | `admin` (unrestricted) | unchanged, **exceptional**: the only operation that needs it |
| 10 | Modify ontology | `configure` | unchanged |
| 11 | Manage releases | Administrator + a release approver | unchanged |
| 12 | Administer permissions | Administrator; a second person approves | unchanged |

The proposal contains the permission definitions, code locations, API changes, migration (none for data), backward
compatibility, a threat model of twelve threats each tied to a test, and the audit requirement. The semantics run as
a pure function, `autology/operation_policy.py`, evaluated on workspace, use case, identity, roles and grants,
entity type, record visibility, operation, properties, workflow state and the model's rules. It does not read a
form, a manifest or a screen (tested). **Nothing in the Engine calls it; the Engine's permissions are the eight
they were (tested).** 11 deterministic tests, positive and negative.

Until the owner approves: forms stay previews, and nothing compensates by granting the unrestricted permission.

### C.2 D34: governed application designs (proposal; **pending**)

[AUTOLOGY_D34_GOVERNED_APPLICATION_DESIGN_PROPOSAL.md](AUTOLOGY_D34_GOVERNED_APPLICATION_DESIGN_PROPOSAL.md)

Lifecycle proposed: *design draft → manifest validation → review → approval → release binding → simulation →
activation*, with suspension and revocation. It reuses the release governance that exists (proposal, approval by a
second person, activation by the platform). **No second publication authority is created:** under every option,
what reaches users is a release the platform's existing governance approved.

The record of a governed design specifies all fifteen items the directive lists (manifest identifier, version,
workspace, use case, ontology fingerprint, configuration fingerprint, author, reviewers, approval status, release
reference, effective permissions, compatible runtime version, audit references, rollback behaviour; effective
permissions granted by a design: none, by construction).

An inactive prototype, `autology/design_governance.py`, models the lifecycle with the owner's four choices as
**explicit parameters with no default**: it refuses to run without them. 8 tests on invented fixtures. Whatever the
choices, it refuses: a step out of order; the author's own approval; a service identity; a design changed after
submission; a release that is not approved or that its proposer approved; **production**; resuming or revoking alone.

### C.3 D35: runtime separation (assessment; **awaiting confirmation**)

[AUTOLOGY_D35_RUNTIME_SEPARATION_ASSESSMENT.md](AUTOLOGY_D35_RUNTIME_SEPARATION_ASSESSMENT.md)

| Aspect | Today |
|---|---|
| Origin | **Shared** by Studio and every application |
| Authentication | Separate sign-in screens; **the same member tokens** work on both |
| Token management, session isolation | Separate keys in one origin's session storage: separation by convention, not by the browser |
| Content security policy | One, for both; allows inline scripts |
| API routing | One relay, which also reaches administration routes |
| Deployment | One build, one process |
| Tenant boundaries | The Engine's; unaffected by any of the above |

Target: **Studio Control Plane / Application Runtime Plane / Engine Governance Plane**. Recommendation: separate
origins first (one artefact started in two roles), then separate deployments; tokens for one plane are an identity
decision and were not started. Six migration steps, each with its regression test. Step 1 (a relay rule that
forwards only one use case's versioned API) is written and tested, **wired to nothing**. No infrastructure changed.

### C.4 Owner decisions

See section G.

### C.5 Migration risks

| Change | Risk | Mitigation proposed |
|---|---|---|
| D24 rights | A grant that is too wide; a write path that skips the new check | One enforcement point (`upsert_object`); grants name entity types and properties; two people; the model's rules stay above grants |
| D34, designs as release parts | Existing releases have no design: must mean "no governed application", not "invalid" | Optional part; fingerprint covers it only when present |
| D34, existing drafts | An approval nobody gave | Every draft migrates as a draft; none approved (tested) |
| D35, two origins | A token stored on one origin is absent on the other: users sign in twice | Stated; it is the point of the change |

---

## D. Application usability

Scope kept to what is useful on all three domains and needs no governance decision. No new view type. No map, no
financial detection, no domain algorithm.

| Change | Before | After |
|---|---|---|
| **Application status** | One line in the banner | An "About this application" screen: application and version, bound configuration, **current release** (new: the Engine reports the active release from the platform's register), environment, mode, the six design states, what the caller can do, what their permissions restrict, what no application can do yet |
| **Last successful interaction** | Not shown | Shown, labelled as **this screen's own clock**, with the sentence "It says when this screen last heard from the Engine, not how recent any record is." No freshness guarantee is invented |
| **Navigation** | One flat list | Grouped by what a screen is for (Overview, Work, Records, Evidence), derived from the view types, never from a name; a menu of more than nine entries gets a box to find a screen |
| **Record provenance** | Fields and links | Also: the revision the Engine holds, when the screen read it, and "where this record came from" asked from the Engine's lineage; when no load is recorded, it says so |
| **Preview and actual change** | A warning paragraph in the form | Also a label in the form's title: "Preview: nothing is saved" or "Sent to the Engine" |
| **Error states** | A message | A message with "Try again" where a load failed |

### Three-domain regression evidence

| Domain | Browser checks | Result |
|---|---|---|
| Crisis management | Designer, six states, grouped menu, About, list, record with provenance, relationships, governed action alone / waiting / refused, decision, audit | Pass |
| Network intelligence | The same steps; restricted records stay uncounted | Pass |
| Venue booking (no template) | The same steps; 61 records paged; a new release under a running application | Pass |
| All three | "The same designer and the same renderer produced three different applications, through the same steps" | Pass |

108 of 108 application checks; the opaque-names test (every name of a model replaced by a token gives a manifest of
the same shape) passes; the scans for domain vocabulary in the Engine, the designer and the runtime pass; manifests
are deterministic; fingerprints are stable across two generations.

### Screenshots (produced by the browser suite; sent with this report)

`app-<domain>-about.png`, `app-<domain>-list.png`, `app-<domain>-record.png` for crisis, netintel and venues (after);
the same list and record screens before increment 3; `chain-museum-loans.png`, `chain-harbour-pilotage.png`.

### Unsupported features (unchanged; said by every application)

Saving records without the unrestricted permission (D24); search, filter or sort by the Engine (GAP-102); pushed
events (D34); production; maps or location; forecasting, optimisation, detection or graph analysis; more than one
agent per run (D32). Also: no export, print or attachment; no localisation; no per-user layout.

---

## E. AI Architect end-to-end readiness

### E.1 Harness

`autology/chain_eval.py`, protocol `chain-v1`; `python -m autology chain-eval`; described in
[docs/chain-evaluation.md](../docs/chain-evaluation.md). Twelve steps, each attributed to a component:

1 description · 2 clarification questions (A) · 3 structured proposal (A) · 4 Engine validation (C) · 5 rejected
elements and reasons (C) · 6 only authorised corrections · 7 governed draft (C) · 8 manifest (B) · 9 manifest
validation (B) · 10 rendering (B) · 11 governed actions, refusals, approvals (C) · 12 reproducible report.

**Three results, no total.** `evaluate()` returns `"aggregate": null`; a test fails if any key of a result is named
like a score.

**Step 6 applies only decisions that were given.** A stated element is kept; an inferred element is kept only if
confirmed; nothing is repaired. If the kept elements do not make a model, the Engine refuses the draft and the
chain stops.

The command has **no option that calls a provider** (tested). The module contains no provider, credential or
network call (tested by reading its source).

### E.2 Test cases

| Set | Cases | State |
|---|---|---|
| **Reserved** (new) | `museum-loans`, `harbour-pilotage` | Two domains that no blueprint of a domain, example or earlier case covers. A test scans the Engine, blueprints, examples and Studio for their vocabulary: none. Each carries V1-style expectations, a hand-written reference answer and a synthetic reviewer's decisions. **Honest limit:** the industry-neutral "request and approval" template matches both briefs by two generic words; the template-based test double would answer with a generic model, not a model of the domain |
| V1 | Five | **Unchanged**; used only to replay kept answers |
| V2 | Eight | **Unchanged; not run**; V2 is proposed, not ratified |

### E.3 Dimensions captured per case

Accepted elements; missing concepts; invalid elements with the Engine's reasons; unsupported assumptions (inferred
elements); required clarifications; contradictions; approval requirements; manifest validity; number and type of
screens; browser execution (by the browser suite, for hosted cases); elapsed time; provider cost and usage **as
recorded with a kept answer**. When a case carries V1 expectations, V1's own scorer is called unchanged and its
measures are reported as V1's.

### E.4 Results

| Run | A. AI Architect | B. Application Builder | C. Engine |
|---|---|---|---|
| Reserved briefs, **reference answers (not a model)** | 2 of 2 answered; 26 elements, 0 refused; 5 inferred, of which 3 confirmed by the synthetic reviewer and 2 left out | 2 of 2 manifests valid, deterministic; 16 screens and 7 menu entries each | 2 of 2 drafts accepted; 2 of 2 runs proceed; 1 review requested: approved → completed, refused → blocked, a decision by another role refused |
| **Replay** of run 2's kept answers (a real model), **no decision of a person** | 4 of 5 answered (one was refused then); 114 elements, 5 refused by the Engine; 41 inferred | 1 of 1 valid | **1 of 4** drafts accepted |
| The same, **every inferred element assumed confirmed** (an assumption: no reviewer confirmed anything) | the same | 4 of 4 valid, deterministic | 4 of 4 drafts accepted; 3 of 4 runs proceed (one escalates at its first step); 2 reviews requested, both refuse a decision by another role |

Evidence: `planning/evidence/chain-eval-2026-11-17/` (three text reports, three JSON reports). The replays cost
nothing: the answers were paid for on 17 November and are read from disk. The kept files are byte-identical before
and after (tested).

**What the replay shows, and to which component it belongs:** the builder and the Engine handled every draft they
were given (B, C). The weak link is A and step 6: without a person confirming inferred elements, three of four real
answers do not make a model (GAP-104).

### E.5 Manifest and simulation results on hosted reserved drafts

| Stage | Result |
|---|---|
| Through the platform's API (`tests/test_chain1…` C8) | The draft from `museum-loans` is saved, configured with the Engine's plain starting configuration, published and released by two people (the author's own approval is refused), moved to Simulation; an application is generated, validated and saved; a run **waits for a person**; the requester's decision is 403; a member without `run` is 403; the reviewer approves; the audit chain verifies; the record reaches its final state |
| In a browser (`studio/web/e2e/apps.mjs`, section "chain") | Both reserved briefs: 7 of 7 menu screens drawn by the same runtime, no error; the About screen names release 1 and the six states |

### E.6 Missing real-provider evidence

| Missing | Why |
|---|---|
| Any answer of a real model to the two reserved briefs | **Not authorised.** No call was made |
| A third evaluation of protocol V1 | Not authorised; not run |
| Any evaluation under protocol V2 | V2 is not ratified |
| The grammar compilation probe | Not authorised; not performed |
| Independent domain reviewers' judgement of business correctness | Separate from this harness; not done |

### E.7 Pending approvals that bear on the AI Architect

| ID | Question | Status |
|---|---|---|
| D30 f | Element-level reading of a non-conforming answer instead of refusing it whole (GAP-082) | **Inactive.** The proposed module is tested and not in force |
| D30 g | Evaluation protocol V2 (17 measures, held-out and adversarial cases) | **Proposed**, not ratified |
| D30 h | A third paid evaluation | **Not authorised** |
| D31 | Where the authoritative spending ledger lives | Pending |

Spending, unchanged by this sprint: ceiling 10 USD, consumed 4.418875 USD, remaining 5.581125 USD (ledger of 27
entries, read-only). **The provider invoice is not yet reconciled.** The ledger was not replaced or written.

---

## F. Explicit answers

**1. Is the Application Builder stable under fully green CI?**
Yes, for the code. Commit `a9dd173` passed CI run 123 in all five jobs (Python 3.10 and 3.13 with PostgreSQL and the coverage gate, package, studio with its three browser suites, quality), and the local full suite passes (1,113 tests, coverage 96.11 %). It did not get there without a stumble: run 122 failed on an out-of-date packaging pin. The commit that adds this report changes documentation only; the result of its own CI run is given in the delivery message.

**2. Do all three demonstration domains still work?**
Yes, in simulation, on synthetic data. Crisis management, network intelligence and venue booking pass the same
steps through the same code: 108 of 108 application browser checks, 56 of 56 cross-domain checks, the opaque-names
test and three vocabulary scans.

**3. Are application permissions always Engine-enforced?**
For everything that was tested: yes, and each claim names its enforcement point (section B). A manifest grants
nothing; the runtime hides buttons for comfort only, and the requests behind them were sent directly and refused.
Two qualifications: the configuration header is a precondition a client may omit, not a boundary; and "always" is a
statement about the tests that exist, not a proof. No independent security review has been done.

**4. Are application designs governed releases?**
**No.** A design is a draft the Engine keeps, validates on every read and binds to one configuration. Nobody
approves it and no release contains it. The Engine itself now reports "approved release artifact: not supported".

**5. What remains blocked by D24?**
Creating a record from an application; editing a field; archiving; Studio's record editor without the unrestricted
permission. Forms are previews. The proposal and its tested semantics are ready; nothing is implemented in the
Engine.

**6. Is the runtime sufficiently isolated?**
For simulation and demonstrations: acceptable. **For production: no.** It shares Studio's origin, relay, content
security policy and token type. The Engine's permissions hold regardless; what is missing is browser-level
separation and its own deployment.

**7. Is end-to-end AI evaluation ready to run when authorised?**
The harness is ready and reproducible without a provider. To run it with one, the owner must authorise the calls
(workspace, model, budget, expiry), and the invoice of the earlier runs should be reconciled first. On the recorded
cost of the kept answers (0.799479 USD for four, about 0.20 USD each), one answer to each reserved brief would cost
about 0.40 USD, and two each about 0.80 USD, within the 1 USD per-request and the remaining 5.581125 USD limits.
This is an estimate from past answers, not a quotation. The reserved briefs have not been shown to any model.

**8. What is the measured AI Architect reliability, from authorised historical evidence only?**
Two runs of protocol V1 on 17 November, model `claude-opus-5-5`, five synthetic cases:

| | Run 1 | Run 2 (after one correction of the contract) |
|---|---|---|
| Cases with a scored answer | 5 of 5 | 3 of 5 (two answers refused as outside the contract) |
| Acceptance thresholds | **Not met** (8 of 13 measures below) | **Not met** (10 of 13 measures below) |
| Share of proposed elements the Engine accepted | 0.074 | 0.572 |
| Cases whose model ran in a draft simulation | 0.0 | 0.4 |

Added by this sprint, from the same kept answers and no new call: through the whole chain, 1 of 4 kept answers
gives a draft the Engine accepts without a person's confirmations; 4 of 4 with every inferred element assumed
confirmed. **The AI Architect has not met its acceptance thresholds.** These figures are recorded results; none was
changed, and no new overall maturity score is offered.

**9. What prevents production use?**
Production execution is disabled and not authorised. Beyond that: designs are not governed (D34); no narrow write
permission (D24); the runtime is not isolated (D35); the AI Architect is below its thresholds; no connector to a
real system (tools are simulated); no independent security review; legal approvals outstanding (GAP-031, D19); no
search in the Engine (GAP-102); no event feed; no load or recovery evidence at production size; no real user has
used it.

**10. What is the smallest next milestone?**
The owner's answers to **D24 a** (the two record rights) and **D34 Q1** (do designs become release artifacts).
With D24 a approved, the smallest build is `records.create` and `records.update` enforced in `upsert_object`, which
turns the three demonstrations' forms from previews into governed writes. It needs no provider and no deployment
change.

**11. Is R2 ready to close?**
**No.** That the Application Builder works is not R2's exit criterion. Open against R2's exit requirements: the
owner's decisions D24, D26, D30 f/g/h, D31, D32, D33, D34, D35; the AI Solution Architect below its acceptance
thresholds with a real provider; readiness weights unratified (D26); the remaining ARC-0 decomposition; independent
verification of what is "met at repository level".

---

## G. Owner decision table

| ID | Issue | Recommended option | Security implications | Implementation impact | Approval required | Current status |
|---|---|---|---|---|---|---|
| D24 a | Narrow record rights `records.create`, `records.update` | Yes, as scoped grants | Removes the pressure to grant the unrestricted permission; the model's rules stay above grants | Small to medium: one enforcement point, grant fields, form sends | Yes | **Not approved** |
| D24 b | May `records.update` name link changes | Yes, per relationship named | Links can reveal or connect records: named, not general | Small | Yes | Not approved |
| D24 c | `records.archive` (archive, never delete) | Leave to actions in a run for now | An archive right could hide evidence; an action is governed by rules | None if left | Yes | Not approved |
| D24 d | "Execute" and "request review" are never a caller's | Confirm | Keeps execution and review inside the Engine | None | Yes | Not approved |
| D24 e | Decide with the `operate` specification or separately | Together | One review of data permissions | — | Yes | Not approved |
| D26 | Readiness weights | Unchanged from earlier packages | — | — | Yes | **Provisional** |
| D30 f | Element-level reading of a non-conforming answer | Decide after a reviewed replay | Could admit a partially wrong model; proposed module rejects whole elements and repairs nothing | Module exists, inactive | Yes | **Inactive** |
| D30 g | Evaluation protocol V2 | Ratify before any further paid run | Fixes the injection measure's known weakness | Cases and scorer exist | Yes | **Proposed** |
| D30 h | A third paid evaluation | After D30 g and the invoice reconciliation | Spends money; synthetic data only | None | Yes | **Not authorised** |
| D31 | Location of the spending ledger | Keep the durable file outside the deployment | A ledger that can be reset is not a ceiling | None | Yes | **Pending** |
| D32 | Several governed agents in one run | Unchanged | — | Design only | Yes | **Design only** |
| D33 | Engineering defaults of the cross-domain validation | Confirm | — | None | Confirmation | **Awaiting confirmation** |
| D34 Q1 | Do designs become release artifacts | A: a named part of a release | One authority, one fingerprint; rollback is exact | Medium: release part, fingerprint, publish step | Yes | **Pending** |
| D34 Q2 | Does the release approval approve the manifest | A: yes, shown in readiness | The approver must be shown the design | Small | Yes | Pending |
| D34 Q3 | A separate design reviewer | A: no, the release approver | Fewer offices to grant and review | None | Yes | Pending |
| D34 Q4 | Manifest changes and release versions | A: a change needs a new release | What is approved is what runs | Follows Q1 | Yes | Pending |
| D34 Q5 | Rollback and presentation | A: the release's own design returns; else nothing is shown | Users never see screens of a model that no longer runs | Follows Q1 | Yes | Pending |
| D34 Q6 | Suspension and revocation | A: one suspends, two resume or revoke | Fast in the protective direction, two people in the others | Small | Yes | Pending |
| D34 Q7 | Existing drafts on migration | A: all kept as drafts, none approved | No approval nobody gave | Small | Yes | Pending |
| D35 a | One origin acceptable for simulation only | Confirm | Browser-side separation by convention | None | Confirmation | **Awaiting confirmation** |
| D35 b | Two roles, two origins as the next deployment change | Approve | The browser separates the sessions; the runtime's relay cannot reach administration | Small; no Engine change | Yes | Awaiting confirmation |
| D35 c | Tokens for one plane | Take into the identity roadmap | A stolen runtime token no longer works on administration | Identity change | Yes | Not started |

Nothing in this table was decided by this sprint. Code that exists for an item (the inactive modules) is not an
approval of it.

---

## H. Evidence package

### Commits (this sprint)

| Commit | Increment | Content |
|---|---|---|
| `be5b21b` | 1. Security and runtime integrity | Six Engine-computed design states; `tests/test_app2_application_integrity.py`; screens print the states |
| `30d6229` | 2. Governance decision packages | D24 (twelve operations), D34 (governed designs), D35 (runtime separation); two inactive modules with tests |
| `2d62473` | 3. Application usability hardening | About screen, active release reported by the Engine, grouped menu, record provenance |
| `316da27` | 4. End-to-end evaluation harness | `autology/chain_eval.py`, two reserved briefs, replay, hosted and browser stages |
| `a9dd173` | 4, correction | The packaging pin names the exact new list of data folders |
| the commit that adds this report | 5. Final verification | This report, registers, roadmap, WIP, log. Documentation only |

### Increments against the directive's workflow

| Increment | Scope | Acceptance | Changed modules | Regression tests | Security impact | Evidence |
|---|---|---|---|---|---|---|
| 0 Baseline and CI recovery | Verify the previous sprint's final commit | A green CI run on it | None | Full suite on `18e8b17` | None | CI run 120; 1,077 tests |
| 1 Security and runtime integrity | Close demonstrable defects without changing policy | Each claim has an enforcement point and a negative test | `applications.py`, `openapi.py`, runtime status | app2 (6 tests) | No Engine defect found; status wording made exact | Section B |
| 2 Governance decision packages | D24, D34, D35 with contracts, migrations, tests | Reviewable, implementable, **inactive** | `operation_policy.py`, `design_governance.py`, `forward.ts` (unwired rule) | 11 + 8 tests; "nothing that runs uses it" | None in force | Section C |
| 3 Usability hardening | Domain-independent improvements | Three domains pass unchanged | runtime `about.tsx`, `model.ts`, `views.tsx`; `platform.py` (one line), `applications.py` | 80 unit tests; 108 browser checks | The release number is shown to readers of the application: a number and a fingerprint already known to them, no person's name | Section D |
| 4 End-to-end evaluation harness | Reproducible measurement without paid calls | Three results, no total; historical results untouched | `chain_eval.py`, reserved briefs, CLI | 11 tests; 2 browser checks | No provider, credential or network call | Section E |
| 5 Final verification | Full CI and regression | A green run on the final commit | Registers, log, this report | Full suite | None | Section A |

### Test reports

| Suite | Count |
|---|---|
| Python tests, final code | 1,113 (were 1,077): all pass |
| New in this sprint | `test_app2_application_integrity` 6 · `test_d24_operation_policy` 11 · `test_d34_design_governance` 8 · `test_chain1_end_to_end_evaluation` 11 |
| Studio unit tests | 80 |
| Browser checks | 135 + 56 + 108 |

### Browser evidence

`studio/web/e2e/screenshots/` (produced by the suites, not committed): `app-<domain>-{designer,about,list,record,relationships,refused,audit}.png`,
`app-venues-release-mismatch.png`, `chain-museum-loans.png`, `chain-harbour-pilotage.png`.

### Architecture documentation

[docs/application-builder.md](../docs/application-builder.md) (six states; what an application tells its user) ·
[docs/chain-evaluation.md](../docs/chain-evaluation.md) (new) · [docs/application-contract.md](../docs/application-contract.md).

### Governance proposals

[D24 proposal](AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md) ·
[D34 governed design proposal](AUTOLOGY_D34_GOVERNED_APPLICATION_DESIGN_PROPOSAL.md) ·
[D34 platform package](AUTOLOGY_D34_APPLICATION_PLATFORM_DECISION_PACKAGE.md) ·
[D35 runtime separation assessment](AUTOLOGY_D35_RUNTIME_SEPARATION_ASSESSMENT.md).

### Updated defect register

[AUTOLOGY_DEFECT_REGISTER.md](AUTOLOGY_DEFECT_REGISTER.md): 105 entries (61 fixed, 19 open, 13 partly fixed, 7 owner
decision, 5 external evidence). Added: GAP-104 (what kept answers give through the chain without confirmations),
GAP-105 (a limit of the draft simulation's sample case). **No status was changed**: GAP-101 and GAP-103 gained a
proposal and an assessment and stay open.

### Updated implementation log

[AUTOLOGY_IMPLEMENTATION_LOG.md](AUTOLOGY_IMPLEMENTATION_LOG.md), entry "Application Builder stabilisation".
Decision register, traceability (STAB-1 to STAB-7), roadmap §3.5 and `WIP.md` are updated.

---

## Definition of Done

| # | Condition | State |
|---|---|---|
| 1 | The final committed tree passes complete CI | **Met for the final code** (`a9dd173`: CI run 123, all jobs). The documentation-only commit that adds this report is checked by the run its push starts; that result is in the delivery message |
| 2 | No regression in the Application Builder MVP | **Met**: every earlier test and browser check passes |
| 3 | The three demonstration applications remain operational in simulation | **Met** |
| 4 | Release-binding and permission boundaries are tested | **Met** (section B) |
| 5 | Application designs are accurately labelled according to governance status | **Met**: six Engine-computed states |
| 6 | D24 and D34 are documented with implementable, reviewable proposals | **Met** |
| 7 | No unapproved authorization policy has been activated | **Met**: the Engine's permissions are the eight they were (tested) |
| 8 | The end-to-end AI evaluation harness is reproducible without paid calls | **Met** |
| 9 | Historical evaluation results remain unchanged | **Met**: kept files byte-identical (tested); thresholds and cases untouched |
| 10 | No real provider, production system or customer dataset has been contacted | **Met** |
| 11 | All limitations are clearly reported | **Met** to the best of this report; listed in B, D, E, F |
| 12 | The final report contains verified CI and implementation evidence | **Met**: section A, with the failed run 122 recorded |
