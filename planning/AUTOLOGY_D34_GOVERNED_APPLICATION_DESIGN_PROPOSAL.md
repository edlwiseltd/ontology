# Autology — governed application designs: proposal and owner decision record (D34, GAP-101)

*17 November 2026. Status: **proposal for the owner. Nothing here is in force.** An application design is today a
draft the Engine keeps: nobody approves it and no release contains it. This document proposes how a design could
become governed, lists the seven questions only the owner can answer, and describes an inactive prototype that
tests the proposed lifecycle on invented fixtures (`autology/design_governance.py`,
`tests/test_d34_design_governance.py`). It completes item 1 of the
[D34 decision package](AUTOLOGY_D34_APPLICATION_PLATFORM_DECISION_PACKAGE.md); the registry and the event feed
stay there.*

## 1. What is in force today (unchanged by this sprint)

| | Today | Engine enforcement point |
|---|---|---|
| What a design is | A draft: append-only, attributed, saved for one configuration | `store.save_application_draft`; `applications.ApplicationService.save` |
| Who may save one | A person holding `configure` | `applications.ApplicationService.save` |
| Validation | By the Engine, on save and again on every read | `appspec.validate`; `applications.ApplicationService.application` |
| Binding | Served only while the configuration it was saved for runs (409 otherwise) | `applications.ApplicationService.application` |
| Approval | **None.** No second person, no reviewer | — |
| In a release | **No.** A release's fingerprint does not include it | — |
| What it is called | Six states, two of them "not supported" (approved release artifact, production) | `applications.ApplicationService.governance` |

## 2. Proposed lifecycle

    draft ─► validated ─► in review ─► approved ─► bound to a release ─► simulation ─► active
      ▲                       │                          (bound, simulation, active) ─► suspended ─► back
      └────── rejected ───────┘                           any state ─► revoked (final); active ─► superseded (final)

| Step | Who | Condition | Existing governance it reuses |
|---|---|---|---|
| Design draft | A person with `configure` | — | The draft store and its revisions |
| Manifest validation | The Engine | Its own check of this exact design against what runs | `appspec.validate` |
| Review | The author submits; a reviewer reads | Only a validated design; the author cannot decide | Separation of duties, as for releases and grants |
| Approval | A second person (who exactly: question 3) | Of one digest: a design that changes afterwards starts again | The release approver's office, or a new one |
| Release binding | The platform | A release that is approved, by someone other than its proposer, for the same model and configuration | `platform` release proposal, approval, fingerprint |
| Simulation | The platform | The bound release is the active one; stage Simulation | Stage gates |
| Activation | The platform | The bound release is the active one; stage Simulation or Pilot. **Production is refused**: production execution is disabled | `platform.activate_release`; stage gates |

**No second publication authority.** Under either option of question 2, what reaches users is a release that was
proposed, approved by a second person and activated by the platform's existing release governance. Studio's
designer proposes; it publishes nothing.

## 3. The record of a governed design

What the prototype's `artifact()` holds, and a reviewer or an auditor would read:

| Field | Content |
|---|---|
| Manifest identifier | The manifest's `id` |
| Version | Design revision (a number) and the digest of the manifest's content |
| Workspace, use case | From the binding; a design never moves between them |
| Ontology fingerprint | The released model it presents |
| Configuration fingerprint | The release configuration it was validated against |
| Author | Who saved it |
| Reviewers | Everyone who approved or rejected it |
| Approval status | None, or approved: by whom, when, **of which digest** |
| Release reference | Number, fingerprint and approver of the release it is bound to |
| Effective permissions | **Granted by the design: none, by construction.** Needed to use each screen: the Engine permission (`read`, `run`, `review`, `audit`) |
| Compatible runtime version | Manifest version and Engine API version |
| Audit references | Every step: event, who, when, from which state to which, the reason |
| Rollback behaviour | Restoring a release restores the design bound to it; a design of another release is never shown on it; with none, the application is not shown |

## 3a. The release a design would be part of (added 19 November; computed by the prototype, not in force)

`design_governance.release_structure(snapshot, manifest, approval)` shows what a governed release would be made of
under the recommended option (Q1 A):

| Part | Content | Own fingerprint |
|---|---|---|
| Validated ontology | Entities, relationships, actions, goals, case templates | yes |
| Approved rules | The model's rules | yes |
| Approved agent configuration | Agents, tools, autonomy | yes |
| Application manifest | The design | yes (its digest) |
| Runtime compatibility metadata | Manifest format and Engine API version the design needs | yes |
| **Combined release fingerprint** | Over all of the above | one |
| Review and approval evidence | Proposer, approver, time: **carried from the existing release governance, checked, never created here** | — |
| Audit references | References into the signed administration log | — |

Properties tested (`tests/test_d34_design_governance.py`, `ReleaseStructureTests`):

* a release **without** a design has exactly the fingerprint it has today: no existing release changes identity;
* with a design, the fingerprint covers it: changing a label changes the release's fingerprint and the application
  part's, and no other part's;
* changing a rule changes the rules part only, and a design bound to the earlier configuration is reported as
  bound to another;
* an approval by the proposer is reported as a problem; missing evidence is left empty, not filled in;
* rollback: the fingerprint identifies which design returns; a release with none shows nothing as governed.

The release authority stays the Engine's platform. Studio proposes; it establishes no approval of its own.

## 4. Owner decision record

Seven questions. For each: the options, what each means for security and for compatibility, and a recommendation
that is **not** a decision. The prototype implements the options as explicit parameters and refuses to run without
them: there is no default in the code.

### Q1. Do application designs become release artifacts?

| Option | Security implications | Compatibility risks |
|---|---|---|
| **A. Yes: a design is a named part of a release** | One approval covers what users see and what the Engine does; a design cannot change under an approved release; rollback is exact | The release snapshot and its fingerprint gain a part: every existing release has none, which must mean "no application", not "invalid". A label change needs a release |
| **B. A governed artifact of its own, bound to a release by reference** | The design has its own approval and history; the release fingerprint is untouched. Two approvals to keep consistent; the binding must be re-checked whenever either side changes | No change to existing releases. A new table and new routes. Risk of a second approval path drifting from the first |
| **C. No: designs stay drafts** | Nothing new to attack; but nobody ever approved what users see, so a production application cannot be claimed | None |

*Recommendation: A.* It is the option with one authority and one fingerprint.

### Q2. Does the approval of the ontology (the release) also approve the manifest?

| Option | Security implications | Compatibility risks |
|---|---|---|
| **A. Yes: the release approver approves the release with the design in it** (`with_release`) | The approver must actually be shown the design, or the approval is nominal; the readiness screen has to present it | The release proposal gains a visible part |
| **B. No: a separate approval, then binding** (`separate`) | A model expert is not asked to judge screens, and a presentation reviewer cannot approve a rule. More steps where one can be forgotten | A second approval workflow to build, test and audit |

*Recommendation: A, with the design shown in the release's readiness view.*

### Q3. Is a separate application-design reviewer required?

| Option | Security implications | Compatibility risks |
|---|---|---|
| **A. No: the release approver** | Fewer offices, fewer grants to review. The same person judges model and presentation | None: the office exists |
| **B. Yes: a new office** | Sharper separation of duties. One more office that can be granted too widely, and one more row in the access review | A new office in members, grants, access review and Studio |

*Recommendation: A now; B when a customer's organisation needs it.* In neither case may the author approve, or a
service identity (tested).

### Q4. How do manifest changes affect release versions?

| Option | Security implications | Compatibility risks |
|---|---|---|
| **A. Any change needs a new release** | What is approved is exactly what runs. Small presentation changes are slow, which invites pressure to bypass | Release numbers grow faster; each activation switches the engine |
| **B. A new design revision under the same release, approved on its own** | Faster. "Which screens did release 7 have on that day" needs the design history as well as the release | Requires Q1 option B |
| **C. Two classes: structural changes need a release, label and order changes a design revision** | A rule that classifies changes can be gamed; the classifier becomes a security control | Most to build and to explain |

*Recommendation: A.* It follows from Q1 option A, and it is the only one with nothing to classify.

### Q5. How does rollback restore compatible presentation?

| Option | Security implications | Compatibility risks |
|---|---|---|
| **A. The release's own design comes back with it** | Users never see screens of a model that no longer runs | Needs Q1 A, or a kept binding under Q1 B |
| **B. The newest design that still validates against the restored release** | A design nobody approved *for that release* could be shown | Surprising: the screens after a rollback are not the ones from before |
| **C. Nothing is shown until a person binds a design** | Safest for integrity; an outage for users at the worst moment | Today's behaviour (409) |

*Recommendation: A; C wherever the restored release has no design.* The prototype's `served()` does exactly this.

### Q6. How are suspension and revocation handled?

| Option | Security implications | Compatibility risks |
|---|---|---|
| **A. One administrator suspends; two people resume or revoke** | The protective direction is fast; the widening and the irreversible directions keep two people. One person can cause an outage | New states and routes |
| **B. Two people for everything** | No single-person outage. A harmful design stays up until a second person is found | The same |
| **C. No suspension of a design: suspend the use case or roll back the release** | Nothing new. Coarse: stopping one bad screen stops everything | None: both exist today |

*Recommendation: A.* A suspension changes no data and no rule; the Engine's permissions hold with or without a
design.

### Q7. How do migrations preserve existing drafts?

| Option | Security implications | Compatibility risks |
|---|---|---|
| **A. Every existing draft becomes a draft of the lifecycle: same revision, author, time, note; none approved, none bound** | Nothing is approved by migration. Applications that are shown today stop being shown as governed until a person takes them through review | Today's previews keep working only if the preview route is kept beside the governed one |
| **B. The current valid draft of each use case is adopted as approved** | **An approval nobody gave.** Not recommended | Smoothest for users |
| **C. Drafts are discarded** | None | Work is lost |

*Recommendation: A, keeping today's preview route, labelled as it is now.* The prototype's `migrate()` does this
and is tested for "all of them, as drafts, none approved".

## 5. Technical contract (for review; not built)

| | Under Q1 A (recommended) | Under Q1 B |
|---|---|---|
| **Storage** | The release snapshot gains an optional `application` part (the manifest); `fingerprint_of` covers it. No new table; `application_drafts` stays the working copy | A table `application_designs` (the record of §3) and `application_design_events` (append-only) |
| **Routes** | `POST …/releases` accepts `application_revision`; the release view lists the part and its digest; `GET /api/v1/application` serves the active release's design and reports `approved_release_artifact: supported, true` | `POST /api/v1/application/designs/{rev}/submit`, `…/approve`, `…/reject`; `POST …/releases/{n}/bind-design` |
| **Engine check** | On activation and on every read: the design validates against the release that contains it | The same, plus the binding's fingerprints |
| **Runtime** | Unchanged: it renders what the Engine serves | Unchanged |
| **Request precondition** | `X-Autology-Configuration` stays; it may be joined by the release number | The same |
| **Store migration** | Schema 21: none needed for data; releases without the part mean "no governed application" | Schema 21: two tables, with the migration of Q7 |
| **Backward compatibility** | A release proposed without a design behaves as today | Releases are untouched |

## 6. What this sprint built, and what it did not

| May (directive §5.2) | Done |
|---|---|
| Improve deterministic validation | A stored design that did not come through validation is refused on read (tested by planting one behind the API) |
| Add non-activating design metadata | The six states (`governance`), computed by the Engine, returned with the design |
| Prepare a review-ready technical contract | §3 and §5 |
| Draft migration specifications | Q7 and §5 |
| Inactive or simulation-only prototype | `autology/design_governance.py`: pure functions, no storage, no route, imported by nothing that runs |
| Test the lifecycle with synthetic fixtures | `tests/test_d34_design_governance.py`: 12 tests (lifecycle, release structure, rollback and versioning, migration), the module covered line by line |

| Must not | Kept |
|---|---|
| Activate an unapproved publication workflow | No route, no table, no screen calls the prototype |
| Treat a draft design as a governed release | The Engine reports "approved release artifact: not supported"; the screens print it |
| Bypass the existing release approvals | The prototype refuses a release that is not approved, or that its proposer approved |
| Add automatic self-approval | The author, a service identity and the same person twice are refused |
| Enable production activation | Refused at two steps, under every policy |

### Added on 19 November (provenance sprint; still not in force)

A release that belongs to another workspace or another use case than the design is refused when a design is bound
to it ("the release belongs to another workspace / use case"). The negative cases asked for by the provenance
directive, and where each is covered **in the prototype**:

| Case | Test |
|---|---|
| Self-approval | `test_what_is_refused_whatever_the_choices` |
| Approval by a service identity | the same test |
| A manifest changed after approval | the same test (a design changed after it was submitted) |
| A stale release | the same test (a release that is not the active one) |
| Rollback | `test_a_rollback_shows_the_design_of_the_release_it_restores_or_nothing`; `test_rollback_and_versioning_as_they_would_work` |
| Suspension and resumption | `test_suspension_resumption_and_revocation` |
| A foreign workspace | `test_what_is_refused_whatever_the_choices` (added case) |
| Production | the same test (refused at two steps, under every policy) |

Migration-ready means: the record of §3, the release structure of §3a and the migration of Q7 are specified and
exercised on fixtures. It does not mean a table, a route or a screen exists: none does.

## 7. Decision requested

| # | Question | Recommended | If no answer |
|---|---|---|---|
| Q1 | Do designs become release artifacts? | A: a named part of a release | Designs stay drafts (C) |
| Q2 | Does the release approval approve the manifest? | A: yes, shown in readiness | — |
| Q3 | A separate design reviewer? | A: no, the release approver | — |
| Q4 | Manifest changes and release versions? | A: a change needs a new release | — |
| Q5 | Rollback and presentation? | A, else C | Today: nothing is shown (C) |
| Q6 | Suspension and revocation? | A: one suspends, two resume or revoke | Roll back, or suspend the use case (C) |
| Q7 | Existing drafts on migration? | A: all kept as drafts, none approved | — |

Until Q1 is answered, implementation stops at this proposal.
