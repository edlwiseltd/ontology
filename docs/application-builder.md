# Application Builder: from a governed solution to a business application

*Status: a first vertical slice (November 2026), on synthetic data with simulated tools. It shows that an
application can be **rendered from a released model without writing the application**. It is not a product, the
designs it saves are previews, and nothing here runs in production.*

    business requirement → model → rules and agents → governed release
                                                          │
                                   generate (Engine, deterministic)
                                                          ▼
                              application manifest  ──  arranged in Studio's designer
                                                          │   validated and saved by the Engine
                                                          ▼
                          application runtime (a renderer)  ──  every record, action, decision
                                                                and audit entry asked from the Engine

## 1. Three layers, one authority

| Layer | Where | What it does | What it never does |
|---|---|---|---|
| **Engine** | `autology/` | Validates models, enforces rules, authenticates and authorises, runs governed actions, records reviews and audit, governs releases. For applications: generates, validates, stores and serves manifests (`appspec.py`, `applications.py`) | Hold a domain; trust what a manifest or a screen says about access |
| **Studio** | `studio/web/components`, `studio/web/lib` | The design environment. Its **Application** tab generates a manifest, lets a designer arrange it, asks the Engine to validate it, previews it and saves a draft | Act as the daily application; write to Engine storage; edit rules or permissions from the designer |
| **Application runtime** | `studio/web/runtime`, served at `/run/<workspace>/<use-case>` | Renders the manifest the Engine hands a caller: navigation, lists, records, relationships, forms, workflow, decisions, audit | Evaluate a rule; decide who may see or do something; keep an audit trail; execute anything a manifest contains |

The runtime and Studio are built and served together today (one Next.js project). They are separate in code: the
runtime imports nothing of Studio's, has its own sign-in and its own token, and Studio uses it in one place, the
designer's preview. A test keeps it so (`studio/web/tests/runtime.test.ts`). Serving the runtime from its own
origin is a deployment step that has not been taken.

**A button the runtime hides is hidden for comfort.** The Engine refuses the request behind it whether or not the
button is shown; the browser tests send those requests directly.

## 2. The application manifest

A manifest is JSON, version 1, described by a **closed schema** (`autology.appspec.SCHEMA`): a property the schema
does not name is refused, at any depth.

| Part | Content |
|---|---|
| `manifest_version`, `id`, `title`, `description` | Identity and text |
| `binding` | The exact solution it was designed for: model reference and fingerprint, **configuration fingerprint** (the release's), Engine API version, workspace and use case |
| `roles` | Whom the application is meant for. Information only: a role the model does not have is refused, and no role is ever granted |
| `navigation` | Which views are in the menu, in which order, under which label |
| `views` | Eight types (below), each bound to things the model has |
| `unavailable` | What the application cannot do, and why. A fixed list: every application carries all of it |
| `presentation` | An accent from six names and a density from two. No colour value, no style, no asset |

| View type | Bound to | Shows |
|---|---|---|
| `DashboardView` | entities | Records the caller sees, counted by state |
| `EntityListView` | an entity, chosen attributes | A page of records |
| `EntityDetailView` | an entity, its attributes, its relationships | One record and its recorded links |
| `RelationshipView` | an entity and its relationships | A record and what it is linked to, as a picture and a table |
| `RecordFormView` | an entity and its attributes | A form; a preview unless the caller holds the unrestricted data permission |
| `WorkflowView` | a case template, its states, its actions, their rules, the agent | The states, what the rules say about each action, and "ask the solution to handle this record" |
| `ApprovalInboxView` | review rules | Requests that wait for the caller's decision |
| `AuditTimelineView` | — | The Engine's signed chain of one request, and, apart from it, what this screen did |

Every view, column, field, relationship, action and menu entry carries a `basis`: `ontology` (read from the
released model), `configuration` (from the approved agents), `default` (a presentation default nobody confirmed),
`confirmed` (a person changed it in the designer) or `unresolved` (the generator could not decide).

### What validation refuses (`appspec.validate`; nothing is repaired)

* anything the schema does not name; a view type the schema does not list; a property that belongs to another
  view type; a missing required property;
* an entity, attribute, relationship (with its direction), case template, action, rule or agent the released
  model and configuration do not have;
* a binding to another model, another version of it, another configuration, another use case or another workspace;
* text that is not plain text: markup, an address (`://`, `//`), `javascript:`, a template expression, a control
  character. It is refused, not cleaned;
* a role the model does not have; a missing entry of the "cannot do" list; duplicate view identifiers; a menu entry
  that points nowhere.

An invalid manifest is never stored.

## 3. Generation

`POST /api/v1/application/generate` builds a manifest from **what runs**: the released model and the approved
agents. It is deterministic (the same model gives the same manifest, byte for byte) and reads **structure only**:

| From the model | Generated |
|---|---|
| Case templates | A workflow view each, with the states of the root entity, the actions that touch it and the rules that name them; a dashboard of the root entities |
| Entities | A list, a record view and a form each; ordered: work items first, then the most connected |
| Attributes, in the order declared | Columns (the first five, plus the state) and fields (all); the first text attribute as the title |
| Relationships | Related sections on both ends; a relationship view |
| Review rules | A decision inbox |
| — | An audit view; the "cannot do" list |

No name means anything to it: a test replaces every name of a model by an opaque token and gets a manifest of the
same shape. It asks no language model. It needs no template: the third demonstration has none.

What it cannot decide, a person does in the designer: which of the generated screens belong in the menu, which
attributes a list should show, what the application is called.

## 4. Serving an application, and release binding

`GET /api/v1/application` returns the manifest **as this caller may use it**:

* views of an entity the caller can never see (an unconditional row rule that names none of the caller's roles)
  are removed, with every menu entry, related section and dashboard tile that points to it;
* attributes the caller can never read (an unconditional field rule) are removed;
* views that need a permission the caller does not hold are marked, with the reason;
* `you.may` says what the Engine will let the caller do (read records, start work, decide reviews, read audit,
  write records).

This tailoring only removes. Conditional rules are applied where they always were: on every record the data routes
return, whatever a manifest shows.

**Binding.** A design is saved for one configuration (the active release's fingerprint). The Engine serves it only
while that configuration runs:

| Situation | Answer |
|---|---|
| No design saved | 404 |
| A newer release was activated, or the release was rolled back | **409**, with the fingerprint designed for and the one running. The application shows nothing until a designer has generated or checked a design for what runs and saved it |
| The saved design no longer validates | 409 |
| Another use case's or workspace's manifest is saved here | 400: the binding names another model, configuration, workspace and use case |

**Requests.** A running application sends, with every request, the configuration it was read for
(`X-Autology-Configuration`). The Engine answers 409 when another one runs, on any route, before doing anything:
no run is started for a solution the caller did not mean. A request that names no configuration is served as
before, so this narrows and never widens.

What this is and is not:

* **Engine-enforced:** the two refusals above. They do not depend on the renderer behaving.
* **Not a security boundary:** the header is sent by the client. A client that omits it is served; it protects an
  honest application from acting on a solution that changed under it, not the Engine from a hostile client. The
  Engine's permissions and rules do that, with or without any application.
* **Not yet governed:** a design is a draft kept by the Engine, append-only and attributed. It is **not part of a
  release**: nobody approves it, and it is not in a release's fingerprint. Making the manifest a named part of a
  release (approved with it, rolled back with it) is the production requirement; it is a change to release
  governance and waits for the owner (D34).

### What a design is said to be

The Engine computes six states for the saved design and returns them with the design (`governance`, on
`GET /api/v1/application` and `GET /api/v1/application/draft`). Studio's designer and the running application print
them as received; neither words a state of its own.

| State | Supported by the Engine | True when |
|---|---|---|
| Design draft | yes | a design is saved (append-only, attributed) |
| Validated design | yes | the saved design validates against what runs **now** (checked on every read) |
| Configuration-bound design | yes | it was saved for the configuration that runs now |
| Approved release artifact | **no** | never: a design is in no release and nobody approves it (owner decision D34) |
| Simulation-ready | yes | validated, bound, the use case is in the simulation stage and runs are not refused |
| Production authorized | **no** | never: production execution is disabled |

A state the Engine does not have is reported as "not supported", not as "no": the difference between "this design
was not approved" and "there is nothing here that could approve it" is the point. An application that opens in a
browser is, at most, simulation-ready.

## 5. Permissions

A manifest grants nothing, and the runtime adds no permission.

| An application user can | Because the Engine gives them | Today |
|---|---|---|
| read records, within row and field rules | `read` | works |
| ask the solution to handle a record | `run` | works; the Engine plans, checks every rule and acts, waits or refuses |
| decide a review | `review` and the reviewer role, as a person, never on their own request | works |
| read the audit trail of a request | `audit` | works |
| **create or change a record** | only the unrestricted `admin` data permission | **forms are previews.** A narrow permission is proposed, not implemented: see `planning/AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md` |

## 6. Studio's Application Designer

Use case → **Application** tab: *generate from what runs → inspect → arrange → validate → preview → save a draft*.

A designer can: read every screen with what it is bound to and where each choice comes from; put screens in or out
of the menu, reorder and relabel them; choose which attributes a list shows (of those the model has); set the title
and the accent; see each action with the rules that govern it; see what the renderer does not support; preview; save
a versioned draft. A designer cannot write a rule, a permission, an expression or code: there is no input for it,
and the Engine would refuse the result.

Preview modes, always labelled, with "Production: unavailable":

| Mode | What it reads | Where |
|---|---|---|
| Configuration preview | Nothing: the screens as designed | Designer |
| Synthetic-data preview | Invented records, with the designer's own access, read only | Designer |
| Engine-backed simulation | Records, runs, reviews and audit, with each user's own access | The application's own address |

## 7. Language models

None is involved. Generation is deterministic. The journey "business description → model" is the AI Architect's,
which has not met its acceptance thresholds with a real provider; this builder starts **after** it, from a released
model. Three things are measured separately and must not be merged in a claim: the quality of a generated model
(open), the quality of an application generated from a valid model (this document), and whether governance holds
(tested here).

A model-proposed presentation would enter as a **proposed manifest**: the same closed schema, the same validation,
the same review by a person in the designer, `basis: "unresolved"` or a new `proposed` basis until confirmed, and
no path that executes anything. That interface is not built and is disabled: no call is authorised.

## 8. What it cannot do

Said by every application, from a fixed list: no saving of records without the unrestricted permission (D24); no
search, filter or sort by the Engine (filtering applies to the records loaded); no pushed events (D34); no
production; no map or location; no forecasting, optimisation, detection or graph analysis; one agent per run (D32).

Also: a design is not part of a release (§4); the runtime is served with Studio (§1); no export, print or
attachment; no localisation; no per-user layout; relationship pictures show one record's direct links.

## 9. Tests

| What | Where |
|---|---|
| Generator, validation, saving, binding, tailoring, isolation, D24 boundary, on three domains | `tests/test_app1_application_builder.py` |
| The six states, a design planted behind the API, field and row rules through direct requests, who may decide, other workspaces, the configuration precondition in every shape | `tests/test_app2_application_integrity.py` |
| Response schemas and routes | `tests/test_api_v1.py`, `tests/test_api_contract.py` |
| Renderer helpers, designer edits, separation and safety of the runtime's source | `studio/web/tests/runtime.test.ts` |
| Designer and runtime in a browser, three domains, release mismatch, pagination | `studio/web/e2e/apps.mjs` (`e2e/run_apps.sh`) |
