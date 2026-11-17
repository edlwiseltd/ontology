# Application contract: how a domain application consumes a released solution

*Status: a technical contract validated on two synthetic demonstrators (R2 cross-domain validation, November 2026). Since then an Application Builder renders applications from a manifest: see [application-builder](application-builder.md).
It describes what exists in the Engine's API today and names what does not. It is not an application builder.*

Autology has three roles:

| Role | What it is | What it never does |
|---|---|---|
| **Engine** | the kernel: model, rules, agents, runs, reviews, audit, releases | hold any domain |
| **Studio** | where a solution is described, validated, configured, released and rehearsed | write to Engine storage; act as the domain's daily screen |
| **Domain application** | what the people of one domain use every day (a coordination desk, a case workbench) | hold rules, workflow, permissions or audit of its own |

A domain application is a **client of one released solution**. It reads the records it is allowed to read, asks for
governed actions, shows people the reviews that wait for them, and cites the audit trail. Everything that decides
stays in the Engine. A reference client with two small domain views is in `examples/domains/reference_app.py`; its
conformance tests are `tests/test_xdom2_application_contract.py`.

## The contract, item by item

Paths: the Engine's API of a use case is `/w/{workspace}/u/{use-case}/api/v1`; the platform's is
`/platform/v1/workspaces/{workspace}`. Both publish an OpenAPI 3.1 document (`/api/openapi.json`,
`/platform/openapi.json`) that needs no token.

| # | What an application needs | How it is done today | State |
|---|---|---|---|
| 1 | **Registration** | The application is a **service member** of the workspace (`POST …/members` with `"kind": "service"`), with a token shown once and an expiry. There is no separate register of applications: nothing records an application's name, version, owner or declared scope as such | Tested · partly (identity yes, application record no) |
| 2 | **Workspace scope** | The token belongs to one workspace. Every path names the workspace and the use case; the other workspace answers 401, 403 or 404 and confirms nothing | Tested |
| 3 | **Release identity** | `GET …/use-cases/{uc}` gives `release.active` (number, identifier, fingerprint) and the stage; `GET …/releases` gives who proposed and who approved. Every run carries `configuration`, the fingerprint of the release it ran on | Tested |
| 4 | **Authentication and permissions** | Bearer token (or OpenID Connect per workspace). Permissions are grants on one use case, proposed by an administrator and approved by a second person: `read`, `run`, `review`, `audit`, `ingest`, `admin`. `GET /me` says what the caller holds. A service identity cannot decide a review and cannot approve anything | Tested |
| 5 | **Authorised data queries** | `GET /objects?type=…`, `GET /objects/{id}` (attributes, links, revision), `GET /objects/{id}/lineage`, `POST /questions/{id}` for the questions a model declares. Row and field rules of the model apply to the application as to a person: a hidden row is a 404, a hidden field is redacted | Tested |
| 6 | **Case creation and updates** | `POST /objects` creates or changes a record with optimistic concurrency. **It needs the `admin` data permission**, which is acknowledged as unrestricted by two people. There is no narrower "create and update records of this use case" right. The `operate` permission specified for owner decision D24 does **not** cover this: it is for operational routes (a scheduler pass, a reporting refresh). A separate proposal for narrow record rights exists (`planning/AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md`); nothing of it is implemented. Feeds can also arrive through configured ingestion pipelines (`ingest`) | Not available to an application without an over-broad grant |
| 7 | **Governed action requests** | `POST /runs` with a case template and a root record. The Engine plans, checks every rule and answers `completed`, `awaiting_review` or `escalated`; one open run per record. The application performs no action itself and cannot name a tool | Tested |
| 8 | **Approval requests** | `GET /reviews` lists what waits for the caller's reviewer roles; `POST /reviews/{id}/decision` records a **person's** decision with that person's token. The application shows the request and passes on the person's own session; it never decides | Tested |
| 9 | **Event subscriptions** | `GET /notifications?since=…` is polled; an operator can configure webhooks per use case in the deployment configuration. There is no subscription an application can create for itself, no delivery guarantee and no replay cursor beyond `since` | Partly |
| 10 | **Audit references** | `GET /runs/{id}/audit` (needs `audit`) returns the signed chain and whether it verifies; `GET /audit-heads` the chain heads. An application stores the run identifier and the release fingerprint beside its own records: that pair is the reference | Tested |
| 11 | **Version compatibility** | The API is versioned in the path (`/api/v1`) with a published contract. The model has a reference and a fingerprint (`GET /ontology`); the release has a fingerprint. The reference client pins what it was accepted with and refuses to start on a mismatch. The Engine does not yet let a caller state "I expect release X" on a request and refuse otherwise | Tested on the client side · not enforced by the Engine |
| 12 | **Visualisation metadata** | `GET /ontology` gives entities, states, attributes with types, relationships, actions, goals and rules: enough to draw a model or a record graph. There is no presentation metadata (labels for people, icons, colours, layouts, which entity is a node and which an edge): the reference client takes those as its own parameters | Partly |
| 13 | **Tool and capability declarations** | `GET /ontology` lists actions and agents; `GET /tools/catalog` the tools a configuration may use (three simulated ones; connectors, custom code and model reasoners are listed as unavailable); the release's components say how many tools are simulated. An application cannot declare capabilities of its own to the Engine | Tested (read) · not implemented (declare) |

"Tested" means: exercised by `tests/test_xdom2_application_contract.py` against both demonstrators with a service
identity, on synthetic data with simulated tools. It does not mean operated.

## What connecting does not give

Being connected is not being trusted. With `read`, `run` and `audit` on its use case, the reference application:

* cannot write a record, save a model or a configuration, ask the architect, publish, propose, approve or activate a
  release, move a stage, load sample data, read the member list or propose a grant (403 or 404 each time, each
  recorded in the Engine's access log under the application's name);
* cannot decide a review, including the one its own request created;
* reaches nothing in another workspace, even one hosted by the same platform with identically named entities and
  record identifiers.

One thing it can do and does not need (reported as GAP-093): `read` also reads the **design** of its use case, that
is the draft model and the design sessions with their descriptions and answers. No record is in them and nothing
can be changed, but a narrower permission would be cleaner.

## Start-up sequence of a conforming application

1. `GET /me`: am I who I think I am, and is my token still valid for long enough?
2. `GET …/use-cases/{uc}`: is a release active, in a stage I work in? Is its fingerprint the one I was accepted with?
3. `GET /ontology`: are the case templates and actions I call still there?
4. If any answer is no: stop and tell a person. Do not degrade silently.
5. From then on: read, ask for runs, show reviews, cite audit. Keep every refusal.

## What is missing for a real application (bounded proposals, none implemented)

| Gap | Smallest useful step |
|---|---|
| Case creation needs `admin` | Narrow record rights (create records of named entity types; update named attributes), decided with D24: see the proposal. Not the `operate` permission, which covers operational routes |
| No application register | A workspace-level record per application: name, version, owner, the service identity it uses, the release fingerprints it was accepted with |
| No self-service events | A cursor-based event feed per use case (runs, reviews, releases), readable with `read`, before any push delivery |
| Release pinning is client-side | An optional request header naming the expected release fingerprint; the Engine answers 409 when another release is active |
| No presentation metadata | An optional, versioned "presentation" section in the solution configuration, released with it, ignored by the Engine |
| `read` includes the design | Separate reading records from reading the design (with the D24 review of permissions) |

None of these is a second workflow engine, and none of them requires the Engine to know a domain.

## Limits of this validation

Two synthetic demonstrators and one reference client show that the contract is *sufficient to read, ask, wait and
cite*. They do not show performance under load, behaviour with a real system of record, usability for operators, or
suitability for emergency response or investigations. Those need real integrations, expert review and the owner's
decisions.
