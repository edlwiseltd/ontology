# Autology — governed operations: next sprint plan (D24 a, D34 Q1, D35)

*20 November 2026. Status: **plan for the owner. No decision is recorded for D24, D34 or D35, so nothing below was
built, wired or activated.** The prototypes were inspected and their existing tests run as they are; they were not
extended. Test statuses use four words only: **planned**, **implemented but not run**, **passed**, **failed**.*

---

## 1. D24 a — create and update by an application user

### 1.1 The question, exactly

From `planning/AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md` §8, question a:

> Add `records.create` and `records.update` as scoped grants, as in §2 to §4?

Two rights. The proposal's third new right, `records.archive`, is question **c** and is **not** part of a. Its §4
(implementation plan) speaks of three names because it describes the whole proposal: under a alone, two are added.
Delete, archive, bulk writes and any general "operational" role are outside this plan.

### 1.2 What is in force today (verified 20 November)

| Behaviour | Evidence | Status |
|---|---|---|
| `records.create`, `records.update`, `records.archive` and `operate` are not permissions; a grant naming one is refused with 400 | `tests/test_app1_application_builder.py` (B9); `tests/test_d24_operation_policy.py::test_nothing_that_runs_uses_the_proposal` | **Passed** |
| An application user's write (`POST /api/v1/objects`) is 403 | `tests/test_app1_application_builder.py` (B9); `tests/test_app2_application_integrity.py` | **Passed** |
| Generated forms are previews and say so | Application browser suite | **Passed** |
| Nothing in the Engine or Studio imports the policy function | The prototype's own test; repeated by search on 20 November | **Passed** |

The sixteen tests of `tests/test_d24_operation_policy.py` prove what the policy *would decide*. They are not
evidence of a working authorization path: there is none.

### 1.3 What an approval must say

An approval of "D24 a" can mean four different things. The form asks for each separately.

| Scope | Content | Reaches a user? |
|---|---|---|
| S1 Definitions | The two names exist as grantable rights with their scope fields | No: a right nobody holds |
| S2 Enforcement | `upsert_object` decides through the policy; the `admin` path keeps working as today | No, until a grant is approved |
| S3 Sandbox enablement | Grants proposed and approved (two people) for synthetic members, in simulation workspaces | Synthetic users, synthetic records |
| S4 Forms that send | The runtime's form sends when the Engine says the entity type is writable for the caller | The same users, through the screen |

Production is not a scope of this decision: the Engine refuses the production stage whatever is approved here.

### 1.4 Staged plan (all blocked until the named scope is approved)

| Step | Change | Needs | Enforcement point |
|---|---|---|---|
| I1 | Add the two names to `server.PERMISSIONS`; grant proposal and approval validate `entities`, `properties`, optional `states` against the released model | S1 | `autology/platform.py` (grants) |
| I2 | `upsert_object` calls one decision function before any write; default is refusal; `admin` stays the exceptional path, named as such in the access log | S2 | `autology/server.py` |
| I3 | The answer of a write is `accepted`, `refused` or `simulated`, with `written` true for `accepted` only | S2 | The same |
| I4 | One access-log entry per decision, refused ones included: names, never values; the right that allowed the write | S2 | The Engine's signed access log |
| I5 | `GET /api/v1/application` reports which entity types the caller may write; the runtime's form sends only then | S4 | Engine decides; runtime shows |
| I6 | Grants for synthetic members in the three demonstrations | S3 | Two people, as for every grant |

### 1.5 What the Engine must enforce, and what still needs a stated contract

| Requirement | Design in the proposal | Open point |
|---|---|---|
| Explicit authorization; default refusal; a form grants nothing | Step 4 of the decision; the form and the manifest are not inputs (tested in the prototype) | — |
| Workspace, use case, entity, row and field restriction, hidden fields included | Steps 4 to 7; a field hidden from the caller is not written by the caller | — |
| Mass assignment | Only properties the grant names; any other property in the request refuses the whole request | Confirm: refuse the request, never drop the extra fields silently |
| Server-owned and immutable fields | A state is never written by a caller; decision-critical properties need their writer rule | The list of server-owned fields per record (identifier, revision, lineage, timestamps) should be written down with the approval |
| Identifier tampering | Create needs revision 0 and refuses an identifier that exists; update needs the record to be visible to the caller | Confirm: may a caller choose the identifier of a new record, or does the Engine issue it? |
| Unauthorised existing row; another tenant | 404 for a hidden record as for an absent one; 403 with no grant for that workspace | — |
| Validation against the model that runs | The strict loader's types and the model's rules, in their words | — |
| Concurrency | Every write names the revision it was made over; a mismatch is 409 and nothing is written | — |
| Atomic failure | One request, one record, one transaction | Bulk writes are excluded, so no partial result exists |
| Retries and idempotency | Not designed. With revision checks, a repeated create answers 409 "exists" and a repeated update answers 409 "changed" | **To decide with the approval:** is "409, read the record" the contract, or is an idempotency key wanted? Nothing is assumed |
| Truthful audit attribution | Who, kind of identity, right used, names of what changed, revision replaced | — |
| Simulated is never reported as written | `written` is true for `accepted` only | — |

### 1.6 Test mapping

The ten items of the test list, the prototype test that covers the semantics, and what an implementation still
needs. No result is recorded for a test that does not exist.

| # | Item | Prototype test (semantics only) | Status | API test needed | Browser check needed | Status |
|---|---|---|---|---|---|---|
| 1 | Authorised and unauthorised create and update | `test_each_operation_with_exactly_the_right_it_needs`; `test_the_twelve_cases_of_the_security_acceptance_list` | Passed | A member with the grant creates and updates through `POST /api/v1/objects`; without it, 403 and zero rows written | The form sends and shows "accepted" from the Engine's answer | Planned |
| 2 | Entity and property scope | `test_scope`; `test_rules_stand_above_grants` | Passed | Another entity type, another property: 403; an extra property in the body refuses the whole request | The form offers only writable fields | Planned |
| 3 | Relationship scope | `test_workflow_state_and_open_work` | Passed | Not in a: links are question b. A link in a request is refused | — | Planned |
| 4 | Hidden record; hidden field | The twelve cases; `test_a_field_hidden_from_the_caller_is_not_written_by_the_caller` | Passed | 404 for a hidden record; 403 for a hidden field; the record is unchanged afterwards | A hidden field is not in the form | Planned |
| 5 | Stale and concurrent revisions | `test_a_stale_version_and_two_writers_of_the_same_revision` | Passed | Two real requests over one revision: one written, one 409 | The conflict is shown and the record read again | Planned |
| 6 | State and business rules | `test_workflow_state_and_open_work`; `test_rules_stand_above_grants` | Passed | A state in the body is refused; a decision-critical field needs its rule | — | Planned |
| 7 | Another workspace | `test_scope` | Passed | A grant in one workspace opens nothing in another; 403 or 404 | — | Planned |
| 8 | Audit | `test_every_decision_leaves_one_record_with_names_and_no_value` | Passed | One signed access-log entry per decision; the chain verifies; no value in it | — | Planned |
| 9 | A user without the unrestricted permission | `test_no_right_implies_another`; `test_the_unrestricted_permission_passes_where_it_does_today_and_no_further` | Passed | The member holds no `admin`; an `admin` holder gets the answers of today | — | Planned |
| 10 | Simulated apart from persisted | `test_a_requested_change_is_accepted_refused_or_simulated_and_never_confused` | Passed | A rehearsal writes zero rows and answers `simulated`; an accepted write answers `accepted` | A preview never says "saved" | Planned |

Regression that must keep passing through every step: the refusals of §1.2 for anyone without an approved grant.

### 1.7 Decision form — D24 a

| | |
|---|---|
| Question | Add `records.create` and `records.update` as scoped grants, as in §2 to §4 of the application-permissions proposal? |
| Answer (yes / no) | |
| Scopes authorised (S1, S2, S3, S4) | |
| Retries: "409, read the record", or an idempotency key | |
| May a caller choose a new record's identifier | |
| Activation scope (workspaces; simulation only) | |
| Limitations accepted (no links, no archive, no delete, no bulk, not production) | |
| Decision-maker | |
| Date | |
| Durable reference | |

---

## 2. D34 Q1 — application designs in governed releases

### 2.1 The question, exactly

From `planning/AUTOLOGY_D34_GOVERNED_APPLICATION_DESIGN_PROPOSAL.md` §4:

> **Q1. Do application designs become release artifacts?**
> A. Yes: a design is a named part of a release.
> B. A governed artifact of its own, bound to a release by reference.
> C. No: designs stay drafts.

The proposal recommends A. **The owner has recorded no answer.** The recommendation is not one.

### 2.2 What is in force today (verified 20 November)

A design is a draft the Engine keeps, bound to a configuration, outside any release. The Engine reports "approved
release artifact: not supported" and the screens print it. Nothing imports `autology/design_governance.py`. Its
twelve tests (`tests/test_d34_design_governance.py`) exercise a lifecycle on fixtures; they are not evidence of a
release integration.

### 2.3 What Q1 alone does not settle

The prototype has no default for the other questions and refuses to run without them. The same is true of an
implementation:

| Question | Needed before building under Q1 = A? | Why | If left unanswered |
|---|---|---|---|
| Q2 Does the release approval approve the manifest? | **Yes** | It decides whether there is one approval or two | Blocked: the approval path cannot be built |
| Q3 A separate design reviewer? | **Yes** | It decides who may approve | Blocked, with Q2 |
| Q4 Manifest changes and versions | Follows from A (option A: any change needs a new release); B and C need Q1 = B | To be confirmed, not assumed | Option B needs Q1 = B; option C adds a rule that classifies changes. Recorded as the owner's |
| Q5 Rollback and presentation | Follows from A (the release's own design returns); C where a release has none | To be confirmed | Today's behaviour (nothing shown) stays |
| Q6 Suspension and revocation | No | Can come later | Roll back the release or suspend the use case, as today |
| Q7 Existing drafts on migration | **Yes**, before any migration runs | Option B would be an approval nobody gave | Blocked: no migration is written |

So the smallest set that unblocks a build is **Q1, Q2, Q3 and Q7**, with Q4 and Q5 confirmed.

### 2.4 Scope if Q1 = A is approved with Q2, Q3 and Q7 (not built)

| Step | Change | Rule |
|---|---|---|
| G1 | A release names its parts: model, configuration, and optionally a design, each with a fingerprint, and a combined fingerprint | A release with no design keeps exactly the fingerprint it has today (the prototype's `release_structure` shows this on fixtures) |
| G2 | Proposing a release may include the validated design bound to that configuration | A design changed after it was submitted, a design of another workspace or use case, or one bound to another configuration is refused |
| G3 | Approval, by the authority Q2 and Q3 name | Never the author; never a service identity; approving a release, reviewing a proposal's elements and approving model content remain three distinct acts |
| G4 | Activation serves the design of the active release, and nothing else | A release that is not the active one serves nothing |
| G5 | Rollback serves the restored release's own design, or nothing | No design from another release |
| G6 | Migration: every existing draft becomes a draft of the lifecycle, none approved (if Q7 = A) | No retroactive approval; today's preview route stays, labelled as it is |
| G7 | Readiness and Studio show the design as part of the release | From the Engine's answer |

Production activation is refused at every step, whatever is approved.

### 2.5 The eight negative cases

| Case | Prototype test (fixtures only) | Status | Integration evidence needed | Status |
|---|---|---|---|---|
| Self-approval | `test_what_is_refused_whatever_the_choices` | Passed | The author approves their own release with a design: 403, through the platform API | Planned |
| Approval by a service identity | the same | Passed | 403 through the API | Planned |
| Manifest changed after approval | the same | Passed | A stored design altered behind the API no longer matches the release's fingerprint; it is not served | Planned |
| A stale release | the same | Passed | A design bound to a release that is no longer active is not served | Planned |
| Rollback | `test_a_rollback_shows_the_design_of_the_release_it_restores_or_nothing`; `test_rollback_and_versioning_as_they_would_work` | Passed | Roll back through the API; the application shown is the restored release's | Planned |
| Suspension and resumption | `test_suspension_resumption_and_revocation` | Passed | Depends on Q6 | Planned |
| A foreign workspace | `test_what_is_refused_whatever_the_choices` | Passed | A design or release of another workspace: 404 | Planned |
| Production | the same | Passed | The production stage refused with a design in the release | Planned |

### 2.6 Decision form — D34

| | |
|---|---|
| Q1 Do application designs become release artifacts? (A, B or C) | |
| Q2 Does the release approval approve the manifest? (A or B) | |
| Q3 A separate design reviewer? (A or B) | |
| Q4 Manifest changes and release versions (A, B or C) | |
| Q5 Rollback and presentation (A, B or C) | |
| Q6 Suspension and revocation (A, B or C; may be left for later) | |
| Q7 Existing drafts on migration (A, B or C) | |
| Implementation scope authorised (which of G1 to G7) | |
| Activation scope (simulation only; production is not authorised by this form) | |
| Decision-maker | |
| Date | |
| Durable reference | |

---

## 3. D35 — browser and identity separation

### 3.1 The present boundary, stated plainly (verified 20 November)

| Fact | Evidence |
|---|---|
| Studio and every application are pages of one web project on **one origin** | `studio/web/app/` |
| Each keeps its token under its own key in the tab's session storage. **Both keys are readable by any script on that origin**: separate keys are a naming convention, not isolation | `studio/web/lib/api.ts`, `runtime/client.ts` |
| An application is opened without an opener. That stops the new tab from reaching back; it does not separate two things on one origin | `studio/web/tests/runtime.test.ts` |
| Tokens are bearer tokens in a header. No cookie is used, so there is no cookie-borne request forgery to defend against today | No `Set-Cookie`, no `document.cookie` in the web project |
| One relay serves both and reaches administration routes | `studio/web/lib/forward.ts` |
| One content security policy for both: same-origin connections, no framing, inline scripts allowed | `studio/web/next.config.ts` |
| No message channel between windows or frames exists | No `postMessage`, no `iframe` in the web project |
| A token is valid on both planes | The platform's member tokens |

**The security boundary today is the Engine's authorization.** Nothing in the browser separates Studio from an
application.

### 3.2 Three separate decisions

| | d-a | d-b | d-c |
|---|---|---|---|
| Question | Confirm that one origin is acceptable **for simulation only**? | Approve steps 2 and 3 (two roles, two origins) as the next deployment change? | Take tokens for one plane into the identity roadmap? |
| If yes | Recorded; production stays blocked on separation | Built and tested locally first; deploying it is a further act | Specified with the identity roadmap; nothing is changed in tokens now |
| If no answer | The default stays, unconfirmed | Nothing changes | Not started |
| Changes code? | No | Yes | Not in this sprint (IAM-2, IAM-4 to IAM-6 are not to be implemented early) |

None of them is an approval to deploy, to change DNS or hosting, or to alter an identity policy.

### 3.3 Staged architecture and migration (nothing below is built unless marked)

| Stage | Content | Rollback |
|---|---|---|
| 0 Today | One origin; the properties of §3.1 pinned by tests | — |
| 1 Narrow relay | The application plane forwards only `GET` and `POST` under `/w/<workspace>/u/<use-case>/api/v1/`. **Written and unit-tested (`runtimeForwardable`); wired to nothing** | Not applicable: unused |
| 2 Two roles | One artefact started as `studio` or as `runtime`. The runtime role serves `/run/…` and the narrow relay; the Studio role stops serving `/run/…` and keeps the embedded preview | Start the single role again |
| 3 Two origins | Studio on origin A, applications on origin B. The designer's link points to B. Origin B gets its own, stricter policy (no inline script once a nonce is used; no framing) | Point the link back; start the single role |
| 4 Origin allowlist | Only if a browser ever calls the Engine directly (today both planes use a same-origin relay, and the Engine sends no cross-origin headers): the Engine names the allowed origins per workspace, exactly; no wildcard | Remove the allowlist: direct calls stop |
| 5 Separate package | The runtime is versioned on its own and states the manifest formats and Engine API versions it draws | Ship the combined package |
| 6 Plane-scoped tokens | A token carries its plane and its use case; administration routes refuse an application-plane token whatever the holder's office; expiry and revocation as for member tokens | An identity decision; not started |

Responsibilities after stage 3: **Studio** designs, releases and administers, and never holds a business user's
session. **The runtime** renders a manifest and asks its own use case's versioned API, and holds no administration
route and no Studio code. **The Engine** decides everything.

Points the plan fixes in advance:

| Topic | Rule |
|---|---|
| Sessions and credentials | One token per origin's storage; signing out of one plane does not touch the other |
| Token audience and scope | Stage 6. Until then a token stolen from the application origin still works on administration routes **through the Engine's own authorization only**: an ordinary user's token has no office |
| Cookies and request forgery | Stay with bearer tokens in a header. If a cookie session were ever introduced: `SameSite=Strict`, `Secure`, `HttpOnly`, and a request-forgery token on every state-changing route, decided separately |
| Cross-origin requests | None by design: each origin talks to its own relay |
| Messages between windows | None exists. If an embedded preview across origins is ever built: the receiver checks the sender's exact origin and window, and accepts a closed set of message types |
| Embedding | `frame-ancestors 'none'` on both origins, unless the preview above is decided |
| Versions | The runtime refuses a manifest format or Engine API it does not know (**in force**) |
| Sign-out, rollback, restoration | Each stage is a configuration change that can be undone; a rollback must not leave the wider relay reachable from the application origin |

### 3.4 Boundary by boundary: negative tests and their true status

| Boundary | Negative test | Status |
|---|---|---|
| Code | The runtime imports nothing of Studio's | **Passed** (`studio/web/tests/runtime.test.ts`) |
| Token key | The runtime never reads Studio's key | **Passed** (same) |
| API surface | The runtime asks only `/w/<ws>/u/<uc>/api/v1/…` | **Passed** (same) |
| Opener | The application tab has no opener | **Passed** (same) |
| Versions | An unknown manifest format or Engine API is refused before anything is drawn | **Passed** (same; application browser suite) |
| Relay rule | `/platform/…`, the unversioned API and other methods are not forwardable | **Passed as a unit** (`forward.test.ts`); **no route uses the rule**, so it protects nothing yet |
| Roles | The runtime role answers 404 for Studio's pages and 403 or 404 for `/platform/…`; the Studio role answers 404 for `/run/…` | Planned |
| Origins | A token stored by Studio is absent from the application origin's storage, and the reverse | Planned |
| Runtime cannot use Studio's authority | From origin B, no request reaches an administration route | Planned |
| Studio credentials cannot leak through the runtime | A script on origin B reads no Studio token | Planned (true by the browser's rules once two origins exist; a local two-port fixture can show it, which is not deployed-origin evidence) |
| A foreign origin or use case | A request for another use case from origin B is refused by the relay and by the Engine | Planned for the relay; **Passed** for the Engine (`tests/test_xdom1_cross_domain.py`, `test_app2_application_integrity.py`) |
| Relay abuse | Path traversal, a doubled slash, an encoded `/platform`, an unlisted method | Planned (the unit test covers the listed shapes only) |
| Content security policy | Origin B serves no inline script and allows no framing | Planned |
| Token scope | An application-plane token is refused by every `/platform/` route | Planned; blocked on d-c |
| Rollback | After returning to one role, the three demonstrations pass and no wider access remains from origin B | Planned |

The tests marked planned **cannot pass today**: there is one origin. Nothing here is "implemented but not run", and
nothing failed.

### 3.5 Decision form — D35

| | |
|---|---|
| d-a One origin acceptable for simulation only? (yes / no) | |
| d-b Approve stages 2 and 3 as the next change? (yes / no) | |
| d-b Implementation scope authorised (local build and tests only; deployment is not authorised by this form) | |
| d-c Take plane-scoped tokens into the identity roadmap? (yes / no) | |
| Limitations accepted (no DNS, hosting, identity-policy or live-token change) | |
| Decision-maker | |
| Date | |
| Durable reference | |
