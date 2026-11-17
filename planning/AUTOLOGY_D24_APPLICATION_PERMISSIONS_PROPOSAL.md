# Autology — least-privilege operations for applications: proposal for owner decision D24

*17 November 2026, revised by the stabilisation sprint. Status: **proposal. Nothing here is in force, activated or
granted.** The Application Builder runs without it: forms are previews, and an application user who tries to write a
record is refused by the Engine (tested). The semantics below exist as a pure, tested function that nothing in the
Engine calls (`autology/operation_policy.py`, `tests/test_d24_operation_policy.py`).*

## 1. Why a separate proposal

Decision D24 asks under which conditions the Engine keeps an unrestricted `admin` data permission. Its existing
specification ([AUTOLOGY_D24_OPERATE_SPECIFICATION.md](AUTOLOGY_D24_OPERATE_SPECIFICATION.md)) defines `operate`
for **operational routes** only: a scheduler pass and a reporting refresh. It gives no right to write a record.

A business application needs something else: a person at a desk must be able to **open a case and correct a
field** without holding a permission that bypasses every row and field rule of the use case. Today the only right
that lets `POST /api/v1/objects` through is `admin`, acknowledged as unrestricted by two people. Giving that to
every application user would undo the least-privilege direction of D22a. So the builder does not: it marks the
feature unavailable.

*Correction of earlier wording:* the cross-domain report and the application contract called this missing right
"the `operate` permission". They should not have: see the erratum in that report.

## 2. Twelve operations, kept apart

The data: `autology.operation_policy.OPERATIONS`. A test asserts the twelve, that three rights are new, that no
proposed right exists in the platform (a grant naming one is refused with 400), and that every enforcement point
named below exists in the code.

| # | Operation | Lets it through today | Proposed right | Scope of the right | Where the Engine enforces it |
|---|---|---|---|---|---|
| 1 | **Read records** | `read` | `read` (unchanged) | Rows and fields the model's rules allow | `server.AutologyService.visible`, `.object_view` |
| 2 | **Create records** | `admin` (unrestricted) | **`records.create`** (new) | Named entity types of one use case, named properties, the initial state only | `server.AutologyService.upsert_object` |
| 3 | **Update permitted fields** | `admin` (unrestricted) | **`records.update`** (new) | Named properties of named entity types, in the workflow states the grant names; optimistic concurrency | `server.AutologyService.upsert_object` |
| 4 | **Delete or archive records** | Not available: no route deletes a record | **`records.archive`** (new) | Archive only, where the model declares it; never a record with open work; **nothing is deleted** | `server.AutologyService.upsert_object` |
| 5 | **Request an action** | `run` | `run` (unchanged) | Ask for a run on a visible record; the Engine plans and checks every rule | `server.AutologyService.start_run` |
| 6 | **Execute an authorized action** | The Engine, inside a run | **No right: never a caller's** | A run executes, after every rule; no caller names a tool or skips a step | `runs.RunService` |
| 7 | **Request review** | The Engine, when a run reaches a review rule | **No right: never a caller's** | Nobody asks for a review directly or names a reviewer | `runs.RunService` |
| 8 | **Decide a review** | `review` + the reviewer role, as a person | unchanged | Never the requester, never a service identity, never another role's review | `server.AutologyService.require_person` |
| 9 | **Administer domain data** | `admin` (unrestricted) | `admin` (unchanged, **exceptional**) | Bulk loads and corrections outside the narrow rights; acknowledged by two people; in the access review | `server.AutologyService.upsert_object` |
| 10 | **Modify ontology** | `configure` | unchanged | Drafts only; a second person publishes | `server.AutologyService.require` |
| 11 | **Manage releases** | Workspace administrator and a release approver | unchanged | Propose and activate; another person approves | `platform.Platform.may_approve_releases` |
| 12 | **Administer permissions** | Workspace administrator | unchanged | Propose a grant for someone else; a second person approves; no data permission by office | `platform.Platform` (grant proposals) |

Twelve operations; three new rights; two operations that are no caller's; none implies another (tested: each right
alone opens exactly its own operation). **`admin` is the right of operation 9 only**: no routine operation needs it.

## 3. How a request is decided

`operation_policy.decide(request, grants, model)` reads, in this order, and stops at the first refusal:

| Step | Reads | Refusal |
|---|---|---|
| 1 | The operation | 400: not one of the twelve |
| 2 | Whether it is a caller's at all | 403: operations 6 and 7 |
| 3 | The identity and its kind | 401 without one; 403: a service identity decides no review and administers nothing |
| 4 | Tenant/workspace, use case and the grant | 403: no grant **in force** (approved by a person who is neither its proposer nor its holder) names this workspace, this use case and this right |
| 5 | Entity type, properties, relationship names, workflow states named by the grant | 403 (409 for a state): outside the grant |
| 6 | Record visibility (the model's row rules) | 404: a hidden record and an absent one are the same answer |
| 7 | The model's rules, **above every grant** | 403: a state is never written; a decision-critical property needs its writer rule; a `write_access` rule; one's own request |

It does not read a form, a manifest, a screen or a request header (tested by listing what it reads). **A generated
form is never an authorisation**: the same request is decided the same way whether or not a form exists for it.

## 4. Implementation plan (to run only after approval)

| | Content |
|---|---|
| **Permission definitions** | Three grantable rights added to `server.PERMISSIONS`: `records.create`, `records.update`, `records.archive`. A grant of one names `entities`, and for create/update `properties` per entity type, optionally `links` (relationship names) and, for update, `states` |
| **Code locations** | `autology/server.py`: `upsert_object` calls one function before any write, replacing the single `require(user, "admin")` line (kept as the fallback that still passes). `autology/platform.py`: grant proposal and approval accept and validate the new fields against the released model; the members view and the access review list them. `autology/openapi.py`: the grant schemas. `autology/applications.py`: `you.may.write_records` becomes per entity type. `studio/web/runtime/views.tsx`: a form of a granted entity type sends; every other form stays a preview. The class-size ratchet of `AutologyService` is respected: the decision lives in its own module |
| **API changes** | Additive. `POST …/grants` accepts `entities`, `properties`, `links`, `states`. `POST /api/v1/objects` is unchanged in shape; it answers 403 with the step that refused. `GET /api/v1/application` reports writable entity types. A new `POST /api/v1/objects/{id}/archive` only if operation 4 is approved |
| **Migration** | None for data: no existing grant changes, no record changes. The store needs no new table (grants already hold a JSON document). Existing `admin` holders keep passing |
| **Backward compatibility** | Every request allowed today is allowed after; every request refused today is refused unless a new grant is approved by two people. API v1 stays v1 (additive). A client that ignores the new fields behaves as before |
| **Audit** | A grant: proposer, approver, scope, in the signed administration log (as today). A write: who, what changed, the revision replaced, and the right that allowed it (`records.update` or `admin`), so that routine and exceptional writes can be told apart in the access log |

## 5. Threat model

| Threat | Answer in the design | Test |
|---|---|---|
| A broad grant is given "to make the form work" | The form never needs `admin`; a narrow right exists | `test_twelve_operations…` (admin is the right of operation 9 only) |
| A manifest or a form claims a right | Not an input of the decision | `test_a_form_or_a_manifest_is_not_an_input` |
| A grant is self-approved, or approved by a service identity | Not in force | `test_a_grant_counts_once_a_second_person_approved_it` |
| A holder writes outside the scope: another workspace, use case, entity type, property | Refused at steps 4 and 5 | `test_scope` |
| A holder changes a state, or a decision-critical fact, by writing | Refused at step 7, whatever is granted, the unrestricted permission included | `test_rules_stand_above_grants`, `test_the_unrestricted_permission…` |
| A hidden record is probed through a write | 404, as for reading | `test_rules_stand_above_grants` |
| A closed case is quietly edited | The grant names the states in which changes are allowed | `test_workflow_state_and_open_work` |
| "Archive" is used to remove evidence | Nothing is deleted; no archive while work is open; only where the model declares it | `test_workflow_state_and_open_work` |
| A service identity collects rights until it can decide or administer | It may hold record rights; it never decides a review, changes the ontology, manages a release or a permission | `test_who_never_does_what` |
| A requester approves their own request | Refused | `test_who_never_does_what` |
| An administrator gains data access by office, or a data holder gains office | Neither | `test_who_never_does_what` |
| One right silently implies another | Each right alone opens only its own operation | `test_no_right_implies_another` |

## 6. Tests

**Run now, against the proposal (not in force):** `tests/test_d24_operation_policy.py`, 11 tests, the module covered
line by line. They prove the *semantics*; they do not prove an implementation, because there is none.

**In force today, and kept:** `tests/test_app1_application_builder.py` B9 (an application user's write is 403; a
grant naming a proposed right or `operate` is 400), `tests/test_app2_application_integrity.py`.

**To accompany an implementation** (the earlier T1 to T11, unchanged in intent): each row of §5 again, through the
API, on the three demonstrations; an `admin` holder gets the same answers as before; the Application Builder's form
sends for a granted entity type and stays a preview for every other.

## 7. What stays unavailable until the owner decides

| Feature of an application | State |
|---|---|
| Saving a new record from a form | Preview only |
| Editing a field of a record | Not offered |
| Archiving a record | Not offered; no route exists |
| Studio's record editor without the unrestricted permission (GAP-090) | Unchanged |

Nothing compensates for this by granting the unrestricted permission to application users.

## 8. Decision requested

| # | Question | If "yes" | If no answer |
|---|---|---|---|
| a | Add `records.create` and `records.update` as scoped grants, as in §2 to §4? | Implemented with the tests of §6; nothing is granted by the change itself | Forms stay previews |
| b | May `records.update` name link changes (attach a document to a case)? | Included, per relationship named | Links stay with `admin` |
| c | Add `records.archive` (archive, never delete), or leave archiving to actions in a run? | A route and a right, as in §2 | No archive; a model that wants one declares an action |
| d | Confirm that operations 6 and 7 are never a caller's (no "execute" and no "request review" permission)? | Recorded as policy | They stay so in the Engine, as today |
| e | Decide it together with the `operate` specification, or separately? | One review of data permissions | Each waits on its own |
