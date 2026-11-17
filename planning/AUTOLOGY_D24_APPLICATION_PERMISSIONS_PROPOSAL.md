# Autology — narrow record rights for applications: proposal for owner decision D24

*17 November 2026. Status: **proposal. Nothing here is implemented, activated or granted.** The Application
Builder runs without it: forms are previews, and an application user who tries to write a record is refused by the
Engine (tested).*

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

## 2. The nine operations, kept apart

The data: `autology.appspec.PROPOSED_OPERATIONS`; a test asserts that they stay nine, that create and update are
the only two that need the unrestricted permission today, and that no proposed permission exists in the platform.

| # | Operation | Needs today | Proposed | Scope of the proposed right | Never included |
|---|---|---|---|---|---|
| 1 | **Create a case** | `admin` (unrestricted) | `records.create` (new) | Named entity types of one use case; the Engine sets the initial state; identifiers the Engine checks | Any other entity type; a state other than the initial one; decision-critical attributes |
| 2 | **Read a case** | `read` | `read` (unchanged) | Rows and fields the model's rules allow | — |
| 3 | **Update allowed fields** | `admin` (unrestricted) | `records.update` (new) | Named attributes of named entity types; optimistic concurrency; the model's `write_access` rules still apply | `status` (states change by actions only); a decision-critical attribute without its writer rule; links, unless named |
| 4 | **Perform a permitted workflow action** | `run` | `run` (unchanged) | Ask for a run on a record the caller may see; the Engine plans and checks every rule | Choosing a tool; skipping a step; acting with a role the caller does not hold |
| 5 | **Request approval** | `run` | `run` (unchanged) | Not an operation of its own: a run that reaches a review rule waits | Addressing a reviewer; marking something as approved |
| 6 | **Review or approve** | `review` + the reviewer role, as a person | unchanged | The reviews of one's reviewer roles | One's own request; a service identity; another role's reviews |
| 7 | **Administer the ontology** | `configure` | unchanged | Drafts; a second person publishes | Activating anything |
| 8 | **Administer security** | workspace administrator | unchanged | Members and grants, each approved by a second person | Any data permission by office (IAM-3) |
| 9 | **Manage releases** | workspace administrator and a release approver | unchanged | Propose; another person approves; activate | Approving one's own proposal |

Nine operations, eight distinct rights, two of them new. None implies another.

## 3. Minimum design of the two new rights

* **A grant, like any other:** proposed by a workspace administrator, approved by a second person, recorded in the
  signed administration log, listed in the access review. It names the use case, the entity types and, for
  `records.update`, the attributes.
* **Enforced in one place:** `upsert_object`, before any write, by a function that answers "may this caller write
  this attribute of this type". `admin` keeps passing as today (compatibility).
* **Rules stay above grants:** a `write_access` rule still refuses a role it does not name; a decision-critical
  attribute still needs its writer rule; a row the caller cannot see cannot be updated (404, as for reading).
* **States are not written:** a record's state changes through actions, in a run. `records.create` sets the
  initial state only; `records.update` never touches `status`.
* **Evidence:** every write records who, when, what changed, and the revision it replaced (as today).
* **Service identities** may hold the rights (an intake integration); they still decide no review.

## 4. Tests to accompany an implementation

| # | Test | Expected |
|---|---|---|
| T1 | A holder of `records.create` for one entity type creates a record of it | 200; initial state; revision 1; in the access log as a data write |
| T2 | The same holder creates another entity type, sets another state, or writes a decision-critical attribute | 403 each |
| T3 | A holder of `records.update` for two attributes changes one of them, then a third | 200, then 403; a stale revision is 409 |
| T4 | An update of `status` | 403, whatever is granted |
| T5 | An update of a record hidden by a row rule | 404 |
| T6 | A `write_access` rule that names another role | 403, with the rule |
| T7 | Either right proposed by its grantee, or approved by the proposer or a service identity | Refused |
| T8 | A holder calls every other route of the contract | As without the right: no route is opened |
| T9 | An `admin` holder after the change | The same answers as before |
| T10 | The Application Builder with the right | The form of a granted entity type says "sent to the Engine"; every other form stays a preview |
| T11 | A manifest that names a form for an entity the caller has no right on | The form is a preview: a manifest grants nothing |

## 5. What stays unavailable until the owner decides

| Feature of an application | State |
|---|---|
| Saving a new record from a form | Preview only |
| Editing a field of a record | Not offered |
| Studio's record editor without the unrestricted permission (GAP-090) | Unchanged |

## 6. Decision requested

| # | Question | If "yes" | If no answer |
|---|---|---|---|
| a | Add `records.create` and `records.update` as scoped grants, as in §3? | Implemented with tests T1 to T11; nothing is granted by the change itself | Forms stay previews |
| b | May `records.update` name link changes (attach a document to a case)? | Included, per relationship named | Links stay with `admin` |
| c | Decide it together with the `operate` specification, or separately? | One review of data permissions | Each waits on its own |
