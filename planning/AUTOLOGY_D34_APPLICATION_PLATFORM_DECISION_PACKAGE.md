# Autology — application platform: decision package for D34

*17 November 2026. Status: **for the owner's decision. Nothing in §2 and §3 is implemented.** What the Application
Builder sprint did build is listed in §1 as applied engineering defaults, reversible, and is not a ratification of
anything.*

D34 asks which gaps of the application contract to close, and in which order. Five items: presentation metadata,
application registration, release pinning, narrow operational permissions, an event feed.

*Added by the stabilisation sprint (17 November): the lifecycle by which a design could become governed, with the
owner's seven questions, is in the [governed application design proposal](AUTOLOGY_D34_GOVERNED_APPLICATION_DESIGN_PROPOSAL.md);
the twelve operations of item 4 are in the [D24 proposal](AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md); default d
of §5 is assessed in the [runtime separation assessment](AUTOLOGY_D35_RUNTIME_SEPARATION_ASSESSMENT.md). Each has an
inactive, tested prototype; none is in force.*

## 1. Where each item stands after the Application Builder sprint

| # | Item | State | Evidence |
|---|---|---|---|
| 1 | **Presentation metadata** | **Built as a design draft.** A closed, versioned manifest generated from what runs, validated and stored by the Engine, rendered by a separate runtime. **Not part of a governed release**: nobody approves a design, and a release's fingerprint does not include it | `autology/appspec.py`; [application-builder](../docs/application-builder.md); `tests/test_app1_application_builder.py` |
| 2 | **Application registration** | **Not built.** An application is still a service member or a person's own session. Nothing records an application as such | §2 |
| 3 | **Release pinning** | **Built, in two parts.** (a) The Engine serves a design only on the configuration it was saved for (409 otherwise). (b) A request may name the configuration it expects; the Engine refuses it when another runs. Both are Engine-side. Neither is a security boundary: a client that sends no expectation is served | Same tests (B6); browser check "after a new release…" |
| 4 | **Narrow operational permissions** | **Not built; a proposal exists.** Forms are previews; writes need the unrestricted permission | [proposal](AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md) |
| 5 | **Event feed** | **Not built.** Screens are refreshed on request | §3 |

## 2. Application Registry: contract and assessment

**Purpose.** Know which applications exist on a workspace, what each was accepted for, and be able to stop one.
A registration **grants nothing**: permissions stay with the members and service identities that hold grants.

| Field | Content | Rule |
|---|---|---|
| `id` | A name unique in the workspace | Immutable |
| `workspace`, `use_case` | Where it belongs | One use case per registration |
| `identity` | The service member it runs as, when it has one; none for an application people open with their own session | The member must exist in the workspace; registration gives it no grant |
| `release` | The release number and fingerprint it was accepted for | Compared at every start; a registration is not carried to another release silently |
| `manifest` | The design revision and its digest | The Engine serves this revision to this application, not "the latest" |
| `manifest_version`, `engine_api` | Contract versions | Refused when unsupported |
| `status` | `proposed`, `accepted`, `suspended`, `retired` | `accepted` needs a second person; `suspended` takes effect on the next request |
| `capabilities` | Which runtime capabilities it may use, from a closed list: read records, start runs, show reviews, read audit, write records (only once narrow rights exist) | A capability is a **ceiling** on what the application's sessions ask for, never a grant; the lower of capability and permission applies |
| `owner`, `accepted_by`, dates | Who answers for it | In the signed administration log |

Routes (proposed): `POST …/applications` (propose), `POST …/applications/{id}/accept` (a second person),
`…/suspend`, `…/retire`, `GET …/applications`. The runtime would send its registration id; the Engine would refuse
a suspended or unknown one.

**Assessment.** About the size of the grant mechanism it resembles (two-person record, administration log,
listing). Bounded. Its value is governance (who accepted which application for which release, and a kill switch),
not function: the demonstrations work without it. It becomes necessary the day a second, independently built
application appears, or a design must be approved.

**A simulation-only registration was not needed** for the MVP, and none was built: the runtime is addressed by
workspace and use case, and the Engine serves the one saved design.

## 3. Governed Event Feed: contract and assessment

**Purpose.** Let a screen learn that something changed without polling every list, and never tell a caller about
something they could not read.

| Field | Content |
|---|---|
| `id` | Monotonic per use case: the cursor |
| `source` | `engine` (runs, reviews, records), `platform` (releases, stage) |
| `workspace`, `use_case` | Scope: a feed is per use case; there is no workspace-wide or cross-workspace feed |
| `release` | The configuration fingerprint in force when it happened |
| `case` | The root record concerned, when there is one |
| `type` | A closed list: `run.started`, `run.waiting`, `run.completed`, `run.refused`, `review.requested`, `review.decided`, `record.changed`, `release.activated`, `stage.changed` |
| `at` | Time |
| payload | **References only**: identifiers, never attribute values. A reader fetches the record or run through the ordinary routes, where rules apply |

| Aspect | Proposed |
|---|---|
| Visibility | Filtered per caller, per event, with the same view policy as runs, reviews and records. An event about something hidden is **not delivered and not counted**: the cursor a caller sees has no visible gaps to count |
| Delivery | Pull: `GET …/events?after=<cursor>&limit=`. At-least-once from the reader's side; ordered per use case |
| Replay | From any cursor within a retention window; older cursors answer "too old: read the current state" |
| After a new release | A `release.activated` event; the application's pinned requests are refused from then on (already built) |
| Not included | Push (webhooks or sockets), subscriptions created by a client, cross-use-case feeds, payloads with data |

**Assessment.** The events exist already as audit and notification entries; the work is a per-caller filtered,
cursor-based read model with retention. Medium size, and the visibility filter is where the risk is: it must be
written against the existing view policy and tested with the isolation matrix. Push delivery is a later, separate
step with its own failure modes. **Nothing was implemented**, and no unrestricted subscription exists.

## 4. Recommendation (not a decision)

| Order | Item | Why this order | Size |
|---|---|---|---|
| 1 | **Narrow record rights** (item 4; D24 proposal) | It is the only item that blocks a function a real user needs on day one: opening a case | Small to medium |
| 2 | **The manifest as a part of the release** (finishes items 1 and 3) | Until then a design is a draft nobody approved. In a release it is approved with the model it presents, rolled back with it, and pinning becomes "this release" instead of "this fingerprint" | Medium: release parts, fingerprint, the designer's publish step |
| 3 | **Application Registry** (item 2) | Needed once designs are governed and more than one application exists | Medium |
| 4 | **Event feed, pull only** (item 5) | Useful, not blocking; do it after the visibility rules for applications have settled | Medium |
| — | Push events, a marketplace of components, model-proposed presentation | Not before the items above and an accepted evaluation of the architect | — |

Keeping all five under D34 until the owner decides.

## 5. Engineering defaults applied by the sprint (recorded as D35; reversible)

| | Default | To undo |
|---|---|---|
| a | Application designs are drafts kept by the Engine (store schema 20), bound to a configuration, outside releases | Remove the routes; the table stays unused |
| b | The Engine tailors a manifest per caller by removing what unconditional row and field rules hide | Serve the manifest untailored: the data routes protect the data either way |
| c | A request may carry `X-Autology-Configuration`; the Engine refuses it on a mismatch; Studio's relay forwards that header | Ignore the header |
| d | The runtime is served by the same web project as Studio, at `/run/…`, with its own sign-in and token | Deploy it as its own origin |

## 6. Questions

| # | Question |
|---|---|
| a | Is the order of §4 the owner's order? |
| b | Should a design become a governed part of a release (approved by a second person), as recommended? |
| c | Are the defaults of §5 confirmed? |
