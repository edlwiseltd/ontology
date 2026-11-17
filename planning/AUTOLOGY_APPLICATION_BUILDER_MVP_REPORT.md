# AUTOLOGY — APPLICATION BUILDER MVP REPORT

*R2 / Application Builder: from a governed ontology to a functional business application. 17 November 2026.
Branch `claude/autology-ontology-agent-4ajjer`. Engineering implementation, synthetic data, simulation only.*

## Summary

**What was asked.** Establish whether a governed ontology can become a usable, domain-specific application
without implementing the application's business logic by hand.

**What exists now.** For three unrelated synthetic domains, an application that a person can open, navigate and
work in was produced from the released model alone:

    released model + approved agents → generated manifest → arranged in Studio → validated and bound by the Engine
                                                                               → rendered by a separate runtime

Nobody wrote a screen for any of the three. One generator, one designer and one renderer served all three; the
third domain has no template at all. Every decision stayed with the Engine: what a person sees, which action is
allowed, which waits for a named person, which is refused, and the audit trail.

**What this is not.**

* **Not natural-language application generation.** The builder starts from a model that is already released. The
  step before it, a language model producing a sound model from a description, has not met its acceptance
  thresholds and was not touched. **No language model was asked anything, and nothing was spent.**
* **Not an operational application.** Records are invented, tools are simulated, production is disabled. A person
  cannot create or change a record from an application: that needs a permission that does not exist yet.
* **Not yet governed like the model it presents.** A design is a draft the Engine keeps and binds to one
  configuration. It is not a part of a release, and nobody approves it.

**R2 is not closed.**

| Kept as they were | State |
|---|---|
| Spending: 4.418875 USD spent, 5.581125 USD remaining, 10 USD ceiling | Unchanged; no provider call; the ledger was not opened for writing |
| Whole-answer refusal of a non-conforming model answer (D30 f) | In force |
| Evaluation protocol version 1 and its recorded results | Unchanged |
| D24 (`operate`), narrow record rights | Not implemented, not activated |
| Production execution | Disabled |
| mypy baseline | 198, not raised |

---

## A. Verified baseline

| Item | Found before any change |
|---|---|
| Branch, HEAD, working tree | `claude/autology-ontology-agent-4ajjer`, `152cba0`, clean, equal to the remote |
| CI | Run 114 (`84c2725`) success and run 115 (`152cba0`) success, read from GitHub. The figures the directive quoted (1,063 tests, 95.96 %, 58 unit tests, 135 and 56 browser checks) are those of run 114's tree; they were not assumed for this sprint, which re-ran everything (F) |
| Read | The cross-domain report, `docs/application-contract.md`, `examples/domains/reference_app.py`, both domain packs, the implementation log, the defect register (100 entries), the decision register, traceability, roadmap §3.5 |
| Interfaces inspected | Engine routes and their published contract (`openapi.py`), `ontology.py`, releases and configuration fingerprints, permissions and view policy (`views.py`, `governance.py`), runs, reviews, audit, the draft store and migrations; Studio's components, relay and API client |
| Reusable contracts found | Record list and record with links (`/objects`), runs (`/runs`), reviews (`/reviews`), the signed audit chain (`/runs/{id}/audit`), the model summary (`/ontology`), the configuration fingerprint each engine computes, append-only drafts with optimistic concurrency |

**Risks identified at the start, and what became of them**

| Risk | Outcome |
|---|---|
| A generated screen could become a second place where access is decided | The manifest has no permission in it; the Engine tailors it by removing only; the data routes are unchanged and tested with requests that bypass the screens |
| A manifest could carry code, markup or addresses | Closed schema; text that is not plain text is refused, not cleaned; the renderer has a fixed set of components and no way to turn data into markup (asserted on its source) |
| The application could go on showing screens for a model that changed | The Engine serves a design only on its configuration and refuses pinned requests after a release (tested in Python and in a browser) |
| Writing records would need the unrestricted permission | Not worked around: forms are previews; a proposal was written |
| The engine class is at its size limit (1,714 lines) | Not one line added to it: the builder is a separate service |
| The runtime could end up as a part of Studio | Separate directory, own sign-in and token, no import of Studio's code (asserted); served with Studio for now (GAP-103) |
| The builder could be fitted to the two existing domains | A third domain without a template; a test that replaces every name of a model by an opaque token |

| | Commit | CI |
|---|---|---|
| Start | `152cba0` | [run 115](https://github.com/edlwiseltd/ontology/actions/runs/44175682266): success |
| Increment 1: manifest, generator, validation, routes, binding, third domain | `bd41bc4` | [run 116](https://github.com/edlwiseltd/ontology/actions/runs/44180266322): **failed**, 1 of 1,076 tests: an older migration test pinned store schema 19 and the design table made it 20. Corrected in increment 3 |
| Increment 2: runtime, designer, browser demonstrations | `5cebf90` | run 117: not finished when this was written |
| Increment 3: documents, proposals, registers, the corrected pin | `45d3a27` | run 118: not finished when this was written |
| Increment 4: this report, provenance of the agent, final verification | the next commit | not run yet |

---

## B. Application Builder architecture

### B.1 Components

```
 Studio (design)                    Engine (authority)                        Application runtime (render)
 ───────────────                    ──────────────────                        ────────────────────────────
 Application tab                    appspec.py                                studio/web/runtime, at /run/<ws>/<uc>
  generate ───────────────────────▶  generate(model, agents, binding)
  inspect, arrange                   validate(manifest, model, running)       own sign-in, own token
  validate ───────────────────────▶  applications.py
  preview (the runtime, embedded)     save design (append-only, schema 20)
  save a draft ───────────────────▶   serve to one caller: tailor(), you.may ─▶ GET /application
                                                                               registry of 8 components
                                     unchanged, authoritative:
                                      /objects   rows and fields per caller ◀── lists, records, relationships
                                      /runs      plan, check rules, act    ◀── "ask the solution to handle this"
                                      /reviews   a named person decides    ◀── decision inbox
                                      /runs/{id}/audit  signed chain       ◀── audit trail
                                     every request may name its configuration: refused when another runs
```

| Area | Implementation | Shared by the three applications |
|---|---|---|
| Ontology validation | Engine (`ontology.py`, unchanged) | Yes |
| Manifest validation | `appspec.validate` | Yes: one function |
| UI generation | `appspec.generate` | Yes: one function, structure only |
| Component rendering | `runtime/RuntimeApp.tsx` (registry), `runtime/views.tsx` | Yes: eight components |
| Authentication | The Engine's bearer tokens; the runtime has its own session | Yes |
| Permissions | Engine-enforced on every route; `appspec.tailor` only removes | Yes |
| Release binding | `applications.application`, `applications.expect_configuration` | Yes |
| Workflow status | `views.tsx` `Workflow`, from `/runs` | Yes |
| Approval handling | The Engine's reviews; `ApprovalInbox` shows and forwards a person's decision | Yes |
| Audit display | `AuditTimeline`, from the signed chain | Yes |
| Domain content | The released model, the approved agents, the invented records | Configuration only |

Search for domain-specific branching: a unit test scans the runtime, the designer and its helpers for the three
domains' vocabulary (none), a Python test scans `appspec.py` and `applications.py` for every entity, action, rule
and case-template name of the three models (none), and the cross-domain scan of the whole Engine and Studio still
passes. **Zero domain-specific branches.**

### B.2 Manifest schema (version 1, closed)

`manifest_version`, `id`, `title`, `description`, `binding` (model, model fingerprint, **configuration
fingerprint**, Engine API version, workspace, use case), `roles` (information only), `navigation`, `views`,
`unavailable` (a fixed list every application carries), `presentation` (an accent from six names, a density from
two). Eight view types: dashboard, record list, record, relationships, form, workflow, decision inbox, audit trail.
Every choice carries where it comes from: the model, the approved configuration, a presentation default, a person's
confirmation, or unresolved. Full description: [docs/application-builder.md](../docs/application-builder.md).

### B.3 Runtime contract

The runtime asks `GET /api/v1/application` and receives the manifest tailored for the caller, what the Engine will
let the caller do, the stage and the binding. Everything else it shows comes from the Engine's ordinary routes. It
renders a view type only if it has a component for it; anything else is listed as not supported and not shown. It
keeps a list of what the screen did in this session and labels it "not an audit record".

### B.4 Studio integration

A new **Application** tab per use case: generate from what runs, inspect each screen with what it is bound to and
where each choice comes from, put screens in or out of the menu, reorder and relabel them, choose the attributes a
list shows, set title and accent, see each action with its rules, validate with the Engine, preview with the same
renderer, save a versioned draft. There is no input for a rule, a permission, an expression or code. Studio's model
editor and React Flow canvas are untouched; there is no second ontology editor.

### B.5 Release binding

| Behaviour | Enforced by | Tested |
|---|---|---|
| A design is saved for one configuration (the active release's fingerprint) | Engine | B5, B6 |
| It is served only while that configuration runs: 409 after a new release | Engine | B6; browser |
| 409 after a rollback as well (downgrade) | Engine | B6 |
| A manifest of another use case or workspace cannot be saved here | Engine (400) | B6 |
| A request that names its configuration is refused when another runs, before anything is done | Engine (409) | B6; browser |
| A saved design that no longer validates is not served | Engine | B6 |
| The application shows nothing and says why | Runtime | browser |

**Limits, stated plainly.** The request header is sent by the client: a client that omits it is served. It protects
an honest application from acting on a solution that changed under it; it is not what protects the Engine. And a
design is not part of a release: making it one (approved with the model, rolled back with it) is the production
requirement and a decision for the owner (D34, GAP-101).

### B.6 Permission boundaries

A manifest grants nothing. Tested: naming a role in a manifest gives it to nobody; a view of a restricted entity
saved by an administrator is not served to a person who cannot see that entity, and the record, its count and its
links stay hidden on the data routes; an application user's direct write is refused (403); a service identity is
told it decides no review.

---

## C. Generator implementation

| | Crisis management | Network intelligence | Venue booking (no template) |
|---|---|---|---|
| Input: released model | 10 entities, 10 relationships, 5 actions, 6 rules, 1 case template | 12, 16, 6, 6, 1 | 5, 4, 3, 3, 1 |
| Input: approved agent | `response_coordinator` | `case_analyst` | `booking_agent` |
| Generated views | **44**: 1 dashboard, 1 workflow, 10 lists, 10 records, 10 relationship views, 10 forms, 1 inbox, 1 audit | **52**: 1, 1, 12, 12, 12, 12, 1, 1 | **24**: 1, 1, 5, 5, 5, 5, 1, 1 |
| In the menu | 14 | 16 | 9 |
| Choices by origin | 168 from the model, 1 from the approved configuration, 53 presentation defaults | 233, 1, 71 | 82, 1, 30 |
| Validation by the Engine | accepted | accepted | accepted |
| Roles it is meant for | duty_coordinator, operations_officer | compliance_officer, financial_investigator, investigation_analyst | booking_clerk, facilities_manager |

**Validation findings.** None on generated manifests. On altered ones, each of these is refused (test B4): an
unknown property at any depth, an unknown view type, a property of another view type, an entity, attribute,
relationship, case template, action, rule or agent the model does not have, a binding to anything else, ten kinds
of hostile text in five places, a role the model does not have (`admin` included), a missing "cannot do" entry.

**Supported components:** the eight view types. **Generation limitations:**

* It proposes every entity as a screen. Which ones matter is a person's choice in the designer.
* Columns are the first attributes in the order the model declares them: it has no idea which are informative.
* Labels are the model's names split into words; a model with poor names gives poor labels.
* One level of relationships per screen; no cross-entity table, no chart, no map, no calendar, no board.
* It reads no data: it cannot tell that a column is always empty.
* It cannot express a conditional layout, a computed column or a custom component, by design.
* A model with no case template gets lists and records, and no workflow screen.

---

## D. Functional demonstration

All three were driven in a browser by one function with a three-row table (`studio/web/e2e/apps.mjs`, 87 checks).
Screenshots are written by each run to `studio/web/e2e/screenshots/app-<domain>-*.png` (six per domain); a selection
accompanies this report.

| | Crisis management | Network intelligence | Venue booking |
|---|---|---|---|
| Input configuration | `examples/domains/crisis_management` (template pack), release 1 | `examples/domains/network_intelligence` (template pack), release 1 | `examples/domains/venue_booking/model.json` and `solution.json`, saved as they are; release 1 |
| Generated navigation | Overview, Incident report: work, Incident report, Affected area, Assignment, Resource, Response team, Organization, Hazard event, Infrastructure, Shelter, Supply requirement, Decisions waiting for a person, Audit trail | Overview, Case file: work, Case file, Organization, Payment, Bank account, Association, Person, Contract, Invoice, Ownership declaration, Hypothesis, Evidence, Review record, Decisions waiting for a person, Audit trail | Overview, Booking request: work, Booking request, Room, Organiser, Equipment item, Deposit, Decisions waiting for a person, Audit trail |
| Designer's changes | Title, accent, one column removed, one menu label | Same | Same |
| Records shown | 5 incidents listed; INC-2002 opened with its fields | 3 case files; the association list shows the four ways a link is known; hypotheses with their competing explanation; evidence with source and quality | 3 requests; a list of 61 organisers read 25 at a time |
| Relationships | INC-2002 with its area and proposed assignment, each with its recorded state | CASE-3002 with its evidence, hypothesis and three organisations; caution: "a link … is not a finding about anybody" | BKG-4002 with its room, equipment and deposit |
| Supported actions | "Ask the solution to handle this record" on an incident | on a case file | on a booking request |
| Done within the policy | INC-2001: five simulated steps, completed | CASE-3001: closed without finding | BKG-4001: checked, confirmed, closed |
| Approval | INC-2002 (180 people): waits; the requester is told he cannot decide; the duty coordinator approves in her own session; completed | CASE-3002: every escalation waits for the compliance officer; approved | BKG-4002 (260 attendees): waits for the facilities manager; approved |
| Refusal | INC-2003: "Refused by policy: assign_response_team: prohibited: A team is never assigned on a prediction alone…"; no step | CASE-3003: "…A case that rests only on unverified evidence is never escalated"; no step | BKG-4003: "…A closed room is never booked"; no step |
| Restricted data | — | "Bank account" is not in the analyst's menu; the list is empty and the count is 0 for him on the Engine's route | — |
| Audit | The Engine's signed chain of INC-2002 verifies and shows "A person decided … approved by dana"; the screen's own activity is listed apart as "not an audit record" | Same, "approved by cleo" | Same, "approved by val" |
| Form | Preview: "Not saved"; the same write sent directly is refused (403) | Same | Same |

Demonstrated per the directive: for crisis, items 1 to 7; for network intelligence, items 1 to 9. Observed versus
inferred links are shown as recorded states of the association records, in lists and beside each node of the
relationship picture; the builder computes nothing about them.

**Not demonstrated:** a map, distances, forecasting or optimisation (none exists; the application says so); graph
queries or entity resolution; any real integration.

---

## E. Security validation

| Requirement | How it was tested | Result |
|---|---|---|
| No anonymous access | Requests without a token and with a bad one to the application routes (B8); browser | 401 |
| No cross-workspace or cross-tenant reads or writes | Administrators of one workspace on every application route of the other (B8); another workspace's operator in the browser | 403 or 404; no manifest in the answer |
| No privilege escalation through a manifest | A role added to a manifest; a restricted view kept in a saved design (B7) | The role is given to nobody; the view is not served; the data routes answer as before |
| No client-provided role treated as authoritative | The runtime sends no role; `you.may` is computed by the Engine from the caller's grants | By construction; B7 |
| No access to administration from an application | The reference application's refusals (cross-domain tests) still pass; an application user's write to `/objects` | 403 |
| Restricted records and fields | Bank accounts for the analyst: record, list, **count**, links from a payment, menu (B7; browser) | 404, empty, 0, none, absent |
| Strict manifest schema | Unknown properties, types and values at every level (B4) | Refused; never stored |
| No code, expression, markup, script or external address | Ten hostile strings in five places (B4); the runtime's source asserted to contain no HTML injection, `eval`, dynamic function, link or external address (unit test); hostile designs posted from the browser | Refused (400); nothing rendered |
| Release mismatch | New release, rollback, foreign manifest, stale pin (B6; browser) | 409 or 400; the application shows nothing |
| Unsupported write operations | Forms as previews; direct writes (B9; browser) | Nothing stored; 403 |
| No auto-approval; no bypass of review | The requester, in the application, cannot decide; a service identity is told it decides nothing; the reviewer decides in her own session | As designed; the decision is in the signed chain |
| No production activation; no release outside policy | The builder activates nothing; designs are drafts; releases still need two people | By construction; existing release tests pass |
| Secrets | Six known values searched for, by value, in every tracked and new file | None found in 1,614 files |

No governance bypass was found. One limit is recorded and not a bypass: an application's design is not approved by
anybody (GAP-101).

---

## F. Engineering quality

<!-- VERIFICATION -->
*Interim: this table is completed by the next commit, when the final full run and the complete browser run on the
final tree have finished. What is listed here was run.*

| Check | Result so far |
|---|---|
| The builder's Python tests, the contract suites, the migration suites | Pass |
| ruff; mypy ratchet | Clean; 198 (= baseline, not raised) |
| Studio typecheck; unit tests; build | Clean; 73 of 73; built |
| Application browser checks | 87 of 87 |
| Full Python suite, coverage, the two other browser suites, CI on the final tree | **Not finished: not claimed** |
<!-- /VERIFICATION -->

**Regression findings.** One: an older test pinned the store's schema version (CI run 116). No behaviour regressed.
Found and corrected during the work, before any commit: the renderer kept a list's rows on screen for a moment
under the next list's title, because a screen's state was not reset when the screen changed.

Tests added: `tests/test_app1_application_builder.py` (14), 5 routes added to the two contract suites,
`studio/web/tests/runtime.test.ts` (15), `studio/web/e2e/apps.mjs` (87 browser checks).

---

## G. Product readiness assessment

**1. Can Autology generate a functional application from an already validated ontology?**
Yes, within the stated limits. Evidence: three applications a person opens, navigates and works in, none of whose
screens was written by hand (D; 87 browser checks). "Functional" means: lists, records, relationships, governed
work with approvals and refusals, audit. It does not include creating or changing records.

**2. Does the same builder work across three unrelated domains?**
Yes. One generator, one validator, one designer, one renderer; the third domain has no template; a test with
opaque names shows the generator reads structure only (B1, B3).

**3. Which screens are generated automatically?**
All of them: an overview, a workflow screen per case template, and for each entity a list, a record, a
relationship view and a form; a decision inbox when the rules ask for a person; an audit trail.

**4. Which require manual configuration?**
None is required: a generated design is usable as it is. In practice a person will choose which entities belong in
the menu, which attributes a list shows, the title and the labels. Anything beyond that (a chart, a map, a custom
layout) cannot be configured at all today.

**5. Are business decisions still exclusively controlled by the Engine?**
Yes. The runtime evaluates no rule. Evidence: refusals and waits come back from `/runs` with the Engine's own
reason; requests sent directly, bypassing the screens, get the same answers (E).

**6. Can a domain application operate without unrestricted data-administration privileges?**
For reading, asking for work, deciding reviews and reading audit: yes, with `read`, `run`, `review` and `audit`.
**For creating or changing records: no.** That needs the unrestricted permission, so the feature is disabled.

**7. What remains blocked by D24 or D34?**
D24: narrow record rights, hence every form that saves, and Studio's record editor for ordinary members. D34: a
design as a governed part of a release; a register of applications with a way to suspend one; an event feed
(screens refresh on request). See the two packages.

**8. Can an application safely bind to a specific release?**
It binds, and the Engine refuses to serve it or its pinned requests on any other configuration, including after a
rollback. "Safely" needs two qualifications: the request pin is a client-sent precondition, not a security
boundary; and the design is bound to a release without being part of one.

**9. What prevents production deployment?**
Production execution is disabled and unauthorised. Tools are simulated; there is no connector. Records cannot be
created without an over-broad grant. Designs are not governed. The runtime shares an origin with Studio. No expert
review of any domain, no independent security review, no load test, no accessibility audit. The AI Architect has
not met its thresholds. Legal approvals are pending.

**10. What remains missing compared with an AI-native enterprise application builder?**
The AI part: a model that produces the ontology reliably (unproven) and proposes presentation (not built). Data
entry and editing. Server-side search, filter and sort. Events. Richer components (charts, maps, boards,
timelines), with a governed way to add one. Computed and cross-entity views. Per-role layouts. Localisation.
Designs approved and released with the model. A register of applications. Real connectors. Several agents on one
case. Publicly described platforms of this kind also offer pipelines, data integration and operational write-back
at scale; none of that is attempted here and no parity is claimed.

**11. What has actually been demonstrated using AI, versus deterministic generation and synthetic data?**
With AI: **nothing in this sprint.** The only AI evidence in the project remains the evaluation of 17 November,
which did not meet its thresholds. Deterministic: the generation of all three manifests. Template-based, through a
test double: the models of the first two domains. Hand-written: the model of the third. Synthetic: every record.
Simulated: every tool.

**12. Is R2 ready to close?**
**No.** The blocking criterion is unchanged: the AI Architect with a real provider under an accepted protocol.
Owner decisions D24, D26, D30 f/g/h, D31, D32, D33, D34 and now D35 are pending; legal approval, independent
security review and expert review have not taken place. The Application Builder is beyond R2's exit criteria; it
neither closes nor delays them.

---

## H. Next milestone recommendation

Toward *natural-language requirements → AI-generated ontology → governed application → safe operational
deployment*, the chain now has one unproven link at its start and one ungoverned link in its middle.

**The smallest next step: prove the first link, and feed it into this builder.** After the owner settles D30 f and
g, a third evaluation (D30 h, within the remaining 5.58 USD) on **blank, unfamiliar briefs with no template**, and,
for each model the Engine accepts, one more measurement that costs nothing: generate its application and record
whether the manifest validates and how many screens it has. That gives, for the first time, an end-to-end figure
from a description to a rendered application, with the three measurements kept apart (model quality, application
generation, governance).

In parallel, without any provider call, in this order: narrow record rights (the D24 proposal), then the manifest
as a governed part of a release (D34, GAP-101).

No production launch is recommended. The reliability, governance, security and expert-review requirements are not
met.

---

## Definition of Done

| Condition | Met? | Evidence |
|---|---|---|
| A real, navigable application UI can be generated from a validated ontology | **Yes** | D; 87 browser checks |
| At least two different domain configurations work with the same runtime | **Yes** | Three |
| A third unrelated ontology demonstrates generalization | **Yes** | Venue booking, no template; opaque-names test |
| No domain-specific code is introduced into the shared Engine | **Yes** | Scans (B.1) |
| No authorization or release-governance bypass exists | **None found** by the tests of E. Not independently reviewed |
| Application views respect the Engine's data restrictions | **Yes** | B7; browser |
| Unsupported write operations are clearly disabled | **Yes** | Forms say "Preview only"; direct writes refused |
| The generation process is deterministic and reproducible | **Yes** | B1 |
| The resulting configurations are versioned and traceable | **Partly.** Designs are append-only revisions with author, time, note and the configuration they were made for. They are **not** part of a release (GAP-101) |
| Relevant regression and security tests pass | **Not yet claimed**: see F (interim) |
| The report distinguishes demonstrated behaviour from proposed architecture | **Yes**: registry, event feed, narrow record rights and model-proposed presentation are proposals; everything in C, D and E was run |

Not a static mock-up: the renderer has no screen of its own. Remove the manifest and it shows "No application
here". And no complete natural-language application generation is claimed.

## Owner decisions

Nothing was decided by this sprint.

| Decision | State |
|---|---|
| D24 | `operate` specified, not implemented. **New:** a separate proposal for narrow record rights; an erratum on earlier wording |
| D26 | Readiness weights provisional |
| D30 f, g, h | Unchanged: element-level rejection inactive; protocol version 2 proposed; no third evaluation |
| D31, D32, D33 | Unchanged |
| D34 | Package written: registry and event feed contracts, a recommended order for the five items |
| D35 (new) | Four engineering defaults of this sprint, reversible: designs as drafts in the Engine; tailoring per caller; the configuration precondition on requests; the runtime served with Studio |
