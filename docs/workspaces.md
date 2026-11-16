# Workspaces and use cases

One Autology platform can serve several **workspaces**, each an isolated organisation (a client, a subsidiary,
any scope that must not see the others), and each workspace can run several **use cases** (motor claims, order
fulfilment, maintenance work orders...). Example: [`examples/platform/platform.json`](../examples/platform/platform.json).

```bash
python -m autology platform examples/platform/platform.json --port 8700
python -m autology console --engine http://127.0.0.1:8700/w/acme/u/claims --port 8900   # a UI for one use case
```

## Model

| Concept | What it is | Where it is defined |
|---|---|---|
| Platform | The router, the platform access log, the data directory | `platform.json` |
| Workspace | Members (people with one API token each), use cases, a secrets file | `platform.json` → `workspaces.<id>` |
| Member | A person (or, with `"kind": "service"`, a machine identity such as a pipeline) in one workspace; `workspace_admin` (an administrative role: no business data by itself, IAM-3) and/or per-use-case permissions, ontology roles and reviewer roles. A service member never decides a human review or settles an external call | `workspaces.<id>.members` |
| Use case | A complete engine: ontology, agents, tools, rules, pipelines, automations, settings; its own store and audit chain | `workspaces.<id>.use_cases.<id>.config` → an ordinary `server.json` |

A use case's `server.json` is the same file a single engine uses. The platform replaces three things in it: the
store path (`<data_dir>/<workspace>/<use case>/autology.db`), the users (the workspace members granted that use
case) and the secrets file (`<data_dir>/<workspace>/secrets.json`). It drops company sign-in (`oidc`) in this
mode. The same `server.json` can therefore back a use case in several workspaces, each with its own data.

## API

| Path | Who | What |
|---|---|---|
| `GET /platform/health` | anyone | `{"status": "ok"}`, nothing else |
| `GET /platform/openapi.json` | anyone | The platform API contract (OpenAPI 3.1, paths under `/platform/v1`) |
| `GET /platform/me` | a member | Their workspace, and the use cases they may open, with their permissions and API path; their tenant and every workspace they belong to (`?workspace=<id>` selects one) |
| `GET /platform/tenants/<tenant>` | a member of that tenant | The tenant and its workspaces (their own; all, with the tenant-level members, for a tenant administrator). Another tenant: `404` |
| `/w/<workspace>/u/<use case>/api/...` | a member granted that use case | The use case's REST API, exactly as for a single engine ([`platform.md`](platform.md)) |
| `GET /platform/templates` | a workspace administrator | The operator's approved templates (id, name, description; never file paths) |
| `GET /platform/workspaces/<ws>/use-cases` | a member | The use cases of their workspace they may open, each with its stage |
| `POST /platform/workspaces/<ws>/use-cases` | a workspace administrator | Create a use case from a template: `{"id", "name", "template"}`; it starts in draft |
| `GET /platform/workspaces/<ws>/use-cases/<uc>` | a member granted it | Detail: stage, stale flag, integrity problem, ontology fingerprint, stage history |
| `GET /platform/workspaces/<ws>/use-cases/<uc>/checks?to=<stage>` | a member granted it | The checks of the target stage, evaluated now; nothing is recorded |
| `GET /platform/workspaces/<ws>/use-cases/<uc>/readiness?target=<pilot or production>&of=<active, draft or release:n>` | a member granted it (`of=draft` and `of=release:n`: people who configure or release the use case) | The readiness report of one configuration, named in `subject`: what runs (default), the saved draft, or a release that is not active. Mandatory gates with their blockers, the scorecard per dimension (calculation, evidence, missing evidence, corrective actions) and, for a configuration that does not run, the conditions that differ from what runs; nothing is recorded |
| `POST /platform/workspaces/<ws>/use-cases/<uc>/stage` | a workspace administrator (a person) | `{"to", "reason"}`: move one stage, if every check passes |
| `GET /platform/workspaces/<ws>/use-cases/<uc>/releases` | a member granted it, or a release approver | Releases, the active one, the running configuration's fingerprint, `drift`, the release history; for people who may publish, `draft`: the saved draft's revision number and who saved it (never its content) |
| `POST /platform/workspaces/<ws>/use-cases/<uc>/releases` | a workspace administrator (a person) | `{"note"}`: propose a release of the configuration the engine runs now (201) |
| `GET /platform/workspaces/<ws>/use-cases/<uc>/releases/<n>` | a member granted it, or a release approver | One release, with `components` (model, rules, action definitions, workflows, agents, tools, governing settings: counts, names and a fingerprint each) and `verification` (the snapshot matches its fingerprint; coherent, or the reasons it could not execute); administrators and release approvers also get its snapshot |
| `POST .../releases/<n>/approve` | a person with release authority, not the proposer | `{"reason"}`: approve, bound to the release's fingerprint |
| `POST .../releases/<n>/revoke` | the approver or a workspace administrator | `{"reason"}`: withdraw an approval before activation |
| `POST .../<uc>/publish-draft` | a person with release authority who did not save the revision | `{"revision", "reason"}`: make a saved, valid draft revision the use case's model, with the agents and simulated tools configured in the same revision (checked against the model first), and reload; it needs a release to run |
| `POST .../releases/<n>/restore` | a workspace administrator (a person) | `{"reason"}`: put an **approved** release's model, and the agents and simulated tools released with it, back and reload; activate that release afterwards to roll back |
| `POST .../<uc>/reload` | a workspace administrator (a person) | `{"reason"}`: reload the engine from its files without a restart; refused, with nothing changed, if they do not load. Not an activation |
| `GET /platform/workspaces/<ws>/members` | a workspace administrator or approver | Members (configured or added through the API), their grants, pending grant proposals, the administration history |
| `POST /platform/workspaces/<ws>/members` | a workspace administrator (a person) | `{"name", "kind", "reason"}`: add a person or a service identity; the token is in the answer, once |
| `POST .../members/<name>/token` | a workspace administrator (a person) | `{"reason"}`: replace the member's token (the old one stops at once); the new one is shown once |
| `POST .../members/<name>/revoke` | a workspace administrator (a person) | `{"use_case", "reason"}`: take the member's access to one use case away, at once |
| `POST .../members/<name>/remove` | a workspace administrator (a person) | `{"reason"}`: remove the member |
| `POST /platform/workspaces/<ws>/grants` | a workspace administrator (a person) | `{"member", "use_case", "permissions", "roles", "reviewer_roles", "run_as", "reason"}`: propose a grant (checked by the engine first) |
| `POST .../grants/<id>/approve` | a person with authority who is neither the proposer nor the member | `{"reason"}`: the grant takes effect at the next request |
| `POST .../grants/<id>/withdraw` | a workspace administrator (a person) | `{"reason"}`: drop a pending proposal |
| `POST .../releases/<n>/activate` | a workspace administrator (a person) | `{"reason"}`: activate an approved release: its model and its agents are put in place together, or nothing changes; an older one is a rollback. A release that could not execute (a model with goals and no agent, an agent whose goals or tools do not fit the model) is refused, and the refusal is recorded in the administration log. The answer counts the runs waiting on another configuration |

Every route above (except the contract itself) is also served under `/platform/v1/...`, and every engine route
under `/w/<ws>/u/<uc>/api/v1/...`: same handlers, same rules, with one error envelope, page metadata on lists and
a version header. The unversioned paths keep their shape and are deprecated, not removed: see
[`api-versioning.md`](api-versioning.md).

Another workspace, a use case not granted and one that does not exist all get the same `404 not found` on these
routes too. A member granted a use case but not administrator gets `403` on the writes.

## Tenants (IAM-1)

A **tenant** is one customer organisation. It owns one or more workspaces; a workspace belongs to exactly one
tenant; identities belong to one tenant and get the same `404` for another tenant's workspaces, use cases and
tenant as for ones that do not exist.

```json
"tenants": {
  "acme-group": {
    "name": "Acme Group",
    "workspaces": ["acme", "acme-eu"],
    "members": [
      {"name": "tara", "token_env": "ACME_GROUP_TOKEN_TARA", "tenant_admin": true},
      {"name": "sam", "token_env": "ACME_GROUP_TOKEN_SAM", "workspaces": {
        "acme":    {"use_cases": {"claims": {"permissions": ["read", "run"], "roles": ["claims_handler"]}}},
        "acme-eu": {"workspace_admin": true}}}
    ]
  }
}
```

- A workspace that no tenant lists is the single workspace of a **dedicated tenant** with the workspace's own id:
  a configuration without `tenants` behaves exactly as before.
- **Membership is explicit at both levels.** Belonging to a tenant gives no workspace access: a tenant-level member
  reaches only the workspaces listed under `workspaces` (one identity and one token for all of them). A
  **tenant administrator** (`tenant_admin`, a person) administers every workspace of the tenant. A member defined
  inside a workspace stays an identity of that workspace only (`name@workspace`): two workspaces of one tenant may
  each have their own "hana", two different people. A tenant-level name is unique in the tenant.
- `GET /platform/me` adds `tenant`, `tenant_admin` and `workspaces` (every workspace the identity belongs to);
  `GET /platform/me?workspace=<id>` selects one. `GET /platform/tenants/<tenant>` shows the caller's tenant: their
  own workspaces, or all of them and the tenant-level members for a tenant administrator.
- **Which tenant owns a workspace is a record** (`<data_dir>/tenancy.db`, versioned, append-only, chained), not only
  configuration. A workspace that already has data when the registry first sees it is recorded in its own dedicated
  tenant (the migration); afterwards a configuration that places a workspace in another tenant than the recorded
  one is refused at start-up. Tenants are merged or split only by an explicit, reasoned operator action:

  ```bash
  python -m autology tenancy show   platform.json
  python -m autology tenancy assign platform.json <workspace> <tenant> --reason "who asked and why"
  ```
- Unchanged: per-workspace stores, audit keys, credential prefixes, sign-in providers, stages, releases and
  administration logs. The registry adds one file and rewrites none, so the previous software version still starts
  on the same data (with a configuration it understands). Back up `tenancy.db` with the rest of the data directory:
  without it, every workspace with data is recorded again in its own dedicated tenant.
- With MCP over a platform file, a token that belongs to several workspaces must say which:
  `python -m autology mcp platform.json --use-case claims --workspace acme-eu`.

**Limits.** Tenant-level members and tenant administrators are defined in `platform.json` (no API yet). Platform
operators have no Autology identity yet (IAM-2): `tenancy assign` records the operating-system user as a claim.
These are application controls; whoever can write the data directory, the configuration or the audit key is outside
them (file permissions, backups, encryption and key custody are infrastructure controls).

## Administrators do not see business data by default (IAM-3)

Being an administrator, of a workspace or of a tenant, is an **administrative** role. In every use case of the
workspace it carries one engine permission, `configure`: the model summary, model drafts and their validation,
architect proposals, the assistant's settings. It carries **no** business-data access: records, runs, reviews,
audit entries, reports, data upload, the scheduler and MCP all answer `403`, from the engine itself. An
administrative role never bypasses row, field, workspace or use-case rules.

- **Business data needs an explicit grant**, for administrators like for anyone: proposed with
  `POST .../grants` (permissions, roles, reviewer roles, `run_as`, for one use case), approved by another person
  with authority who is neither the proposer nor the person who receives it, recorded in the administration log,
  and revoked at once with `POST .../members/<name>/revoke`. A grant written in `platform.json` under an
  administrator's `use_cases` is explicit too. The engine's own `admin` permission (everything on one use case,
  regardless of row and field rules) exists only as such a grant.
- **Migration, once per workspace.** When this version first loads a workspace that already has data, each of its
  configured administrators receives, for each existing use case, an explicit `admin` grant recorded as
  `grant_migrated`: an upgrade takes nothing away silently, and what used to be hidden in a role is now visible in
  `GET .../members` and revocable. Nothing is granted afterwards: not to new administrators, new workspaces or use
  cases created later. Review the migrated grants and revoke those that are not needed.
- **A model never changes on one person's say-so.** A published model is loaded at once and its access rules then
  govern what members read, so `publish-draft` is refused to whoever saved the draft revision: another person with
  release authority (a workspace administrator or a named approver) publishes it. A release's model can be restored
  only if that release was approved.
- Separation of duties is unchanged: an administrator who holds a data grant still cannot decide the review of a run
  they started, approve their own release or their own grant.
- If the administration log does not verify, administrators keep the administrative role only.

### What the engine's `admin` permission means, and how it is given

`admin` on a use case is **unrestricted access to that use case's business data**. It is the one exception to least
privilege that remains, and it is never implied by a role. Someone who holds it:

- reads every record and field (row and field rules do not apply), every run, review, notification and
  reconciliation item;
- starts and resumes runs with all of the agent's roles, and free-form cases outside simulation;
- decides reviews whatever reviewer role they ask for (still never for a run they started, never as a service
  identity);
- writes records directly, edits and commits any scenario, reinstates agents, runs the scheduler and reporting;
- never reaches another use case, workspace or tenant, and never changes members, grants, stages or releases.

So it is given deliberately: a proposal that contains `admin` is refused unless it carries `"unrestricted": true`,
and so is its approval; both persons acknowledge it, and the access review shows it. Prefer `read`, `run`,
`review`, `audit`, `ingest`, `reconcile` with roles: those obey every rule.

### Access review

`GET /platform/workspaces/<ws>/access-review` (administrators and approvers) lists every business-data grant: the
member, the use case, permissions and roles, `data_access` (`scoped` or `unrestricted`), where it comes from
(`configuration`, `migration`, or a `grant` with its proposer and approver), and `needs_review`. A grant needs
review when no person decided it with full knowledge: every grant created by the IAM-3 migration, and every
unrestricted grant that was not acknowledged twice (for example one written in the configuration). Three ways to
resolve one, each recorded:

- **confirm** it: `POST .../members/<name>/confirm-grant` with `use_case`, a reason, and `"unrestricted": true`
  when it is unrestricted; by a person with authority (administrator or named approver) who is **not** the member
  concerned. A confirmation is about the grant as it is: if the grant changes, it no longer applies;
- **replace** it with a narrower one: propose a grant for the same member and use case; once another person
  approves it, it takes the place of the old one;
- **revoke** it: `POST .../members/<name>/revoke`, at once.

Nothing is revoked automatically: the migrated grants keep working until a person decides, and the report shows how
many still wait.

### In Studio

Studio's **Access** screen (workspace menu) does all of the above without raw API calls: the tenant and its
workspaces, members with their effective permissions per use case and the state of their token, adding and removing
members, requesting grants, approving or withdrawing them, the access review, token requests, replacing one's own
token, and the administration history. A workspace switcher appears when an identity belongs to several workspaces.
Studio decides nothing: it shows the platform's answers (`you.may_administer`, `you.may_approve` are hints for which
buttons to show) and every call is checked by the platform again; a member without authority sees a clear
"permission denied" state, and a request that needs a second person says so.

### Who has seen a member's token

Whoever issues a token sees it once. The members view shows `token_issued_by` for each member (`configuration`, the
administrator who issued it, or `self` after the member replaced it with `my-token`).

- A new token for a member **who holds business data** is not issued by one person: `POST .../members/<name>/token`
  answers `202` with a request id, and another person with authority (not the requester) issues the token with
  `POST .../token-requests/<id>/approve` and is the only one to see it. An administrator alone can therefore not
  take over a member's access by re-keying them. A request can be withdrawn; removing the member ends it.
- A member without business data is re-keyed at once, as before. Removing a member also ends the grant proposals
  made for them: a later member with the same name inherits nothing.
- What remains: the person who issues a token could keep a copy, and a new member's first token is issued by one
  administrator before any grant is approved. Company sign-in (OIDC) avoids both, because nobody issues a secret;
  it is the recommended sign-in for people.

**Limits.** These are application controls: whoever can read the data directory, backups or the audit key is
outside them (file permissions, encryption and key custody are infrastructure controls). Platform operators have no
application identity, so they have no application permission on customer data either; governed exceptional access
is a later increment (IAM-2).

## Administration without restarts (ADM-1, ADM-2)

`platform.json` stays the base. On top of it, an **administration log** per workspace (`<data_dir>/admin.db`,
append-only, chained with the workspace's audit key) records members added or removed, tokens replaced, grants
proposed, approved, withdrawn or revoked, and engine reloads. The members a workspace has are the configuration's
with the log replayed over them, at start-up and after every change: a change applies at the next request.

- Adding, removing, re-keying a member and revoking a grant: a workspace administrator who is a person. Taking
  access away needs nobody else.
- Giving access: a grant is **proposed**, and takes effect only when **another person with authority** (a workspace
  administrator or a member listed in `release_approvers`) approves it; never the proposer, never the member who
  receives it, never a service identity (D11). The engine checks the grant (permissions, `run_as` agents) before it
  is recorded.
- Workspace administrators exist only in `platform.json`: no API call creates or removes one. An administrator
  who is a person may replace her own token (`my-token`); the configured token then stops working.
- If the log does not verify (changed outside Autology), only the configured administrators keep access until an
  operator repairs it.
- **Reload** rebuilds one use case's engine from its files without restarting the platform, after loading them into a
  throwaway engine first. A reload is not an activation: with an active release, changed files count as drift and
  the use case runs nothing until a person activates an approved release of them.

## Token lifetimes, rate limits and timeouts (GAP-030)

Everything here is enforced by the server, for every entry point (REST, MCP over HTTP and stdio, Studio through its
relay). The `security` section of `platform.json` (all keys optional):

```json
"security": {
  "tokens": {"person_days": 90, "service_days": 365},
  "rate_limits": {"window_seconds": 60, "auth_failures": 30, "anonymous": 600, "api": 1200, "mcp": 300,
                  "admin": 120, "expensive": 120, "tenant": 12000},
  "trusted_proxies": ["10.0.0.0/8"],
  "server": {"max_connections": 64, "request_timeout_seconds": 30},
  "run_seconds": 900
}
```

**API tokens expire.** A token lives for the policy's number of days for its kind (people and service identities are
separate), counted from the first time the platform saw it; that date is recorded once in
`<data_dir>/credentials.db` (append-only, chained; only the token's SHA-256 is stored; a changed registry stops
the start). A member's configuration may give an earlier `"token_expires": "2027-01-31"`. A lifetime is always
finite (at most 3650 days). An expired token gets `401` with `reason: token_expired`; the access log names whose
it was. `GET /platform/me`, `GET /api/me` and the members view show `token_expires_at`.

- **Existing tokens (migration).** A token that existed before this version is registered the first time the new
  version starts: it keeps working for one full lifetime from the upgrade, then expires like any other. Nothing is
  cut off at the upgrade, and nothing is valid for ever. A restart or a reload never extends a lifetime.
- **Rotation.** `POST /platform/workspaces/<ws>/members/<name>/token` (a workspace administrator) or
  `POST /platform/workspaces/<ws>/my-token` (a person, for their own workspace-level token, while it is still
  valid) returns a new token once; the previous one is refused from then on, for good. The identity and its grants
  do not change, and the new token gets one lifetime, never more. A service identity cannot renew itself (an
  administrator re-keys it); an expired or revoked token renews nothing. Tenant-level identities are re-keyed in
  the configuration.
- **Revocation.** `POST /platform/workspaces/<ws>/members/<name>/revoke-token`: the token stops working at once
  (`reason: token_revoked`), the member and their grants stay, and an administrator issues a new token when
  appropriate. A replaced or revoked token, or the token of a removed member, never works again, even if a
  configuration file still names it. Administrators' own tokens are replaced by their owner (`my-token`) or in the
  configuration, not revoked by a colleague.
- Issuing, replacing and revoking are in the administration history (who, when, why) and in the registry's.
- Company sign-in (OIDC) is unchanged: an ID token carries its own expiry, verified on every request.

**Rate limits.** Counted per fixed window; a refused request gets `429`, a `Retry-After` header (seconds) and
`retry_after_seconds` in the body (`code: rate_limited` in API v1), is written to the access log, and does nothing
else. `auth_failures` and `anonymous` are per client address; `api`, `mcp`, `admin` (administrative changes) and
`expensive` (requests that start work: runs, resumes, decisions, chat, comparisons, pipelines, automations, model
proposals) are per identity in a workspace, whichever use case, API version or entry point is used; `tenant` is the
total of a tenant's authenticated requests, so one tenant at its limit takes nothing from another. After too many
failed sign-ins an address is refused *before* its credential is looked at: the answer says nothing about a guessed
token. A class set to `0` is not limited.

- **Client address.** The TCP peer's. `X-Forwarded-For` is believed only from a peer listed in `trusted_proxies`.
  Behind a reverse proxy, list it, or every client shares the proxy's address for the sign-in limit. Studio's relay
  does not forward client addresses: Studio users share the relay's address for that limit (identity limits are
  unaffected).
- **Single node.** Counters live in the memory of one platform process: they restart with it and are not shared
  between processes. With several instances, put a shared limit at the load balancer.

**Timeouts.** A connection that sends or reads nothing for `request_timeout_seconds` is closed, and at most
`max_connections` requests are served at once (others get `503` with `Retry-After` at once). These are about
connections only: work that has started is never cancelled by them. A run that exceeds `run_seconds` pauses
*between two steps* (`paused`, with the reason, in the audit as `time_budget_exhausted`) and can be resumed; an
action in flight is never cut. Calls to other systems have a deadline for the whole call (see
[integrations.md](integrations.md)): past it, the outcome is recorded as *unknown* and listed for reconciliation.

## Releases (REL-1a)

A **release** is an immutable, content-addressed snapshot of what governs a use case: its ontology, the engine
settings that decide what runs and who may do what (agents, approvers, automations, service identities, webhooks,
checkpoints) and each agent's tool declarations. Its fingerprint (SHA-256) is shown as `configuration` in the
use case and in the engine's `/api/health`. Store paths, members, sign-in and secrets files are not part of it.

1. A workspace administrator **proposes** the configuration the engine runs now.
2. Another **person** with release authority **approves** it: a workspace administrator or a member named in the
   workspace's `"release_approvers"` (for example an external approver with no other access, which a workspace with a
   single administrator needs). The proposer never approves their own release; a service identity never approves.
3. A workspace administrator **activates** it, in one step, with no restart and no reload:
   - if the engine does not already run the release's configuration, the platform puts the release's model in
     place, rebuilds the configuration from the deployed files and compares its fingerprint with the release's
     **before anything changes**. If they differ (a setting outside the model changed in the files), activation is
     refused and says so: deploy that release's files and activate again;
   - the engine is switched once the requests in flight have finished (a running step is never cut; if they do not
     finish within 10 seconds, activation is refused and can be repeated). Requests that arrive during the switch
     wait, then are served by the new configuration: nobody sees a model without its release. The scheduler does
     not tick during a switch;
   - if any step fails, the model and the engine that ran before are put back and the previous release stays
     active. If even that configuration no longer loads, the use case serves nothing (`503`) until a reload
     succeeds; other use cases are unaffected;
   - when the model changed, the use case is **simulated again at once** if the simulation checks pass, recorded
     in the stage history in the activator's name. Pilot is never granted automatically: a person decides it
     again, with its checks. Production is never granted.

   Activating an older approved release is a **rollback**, the same single step. Approvals are never rewritten:
   activation only appends to the history.

While a release is active, an engine running another configuration (a file changed and the use case restarted)
counts as **draft**: nothing runs and nothing is sent until a person activates an approved release of what now runs.
**Pilot** requires an approved active release (check `approved_release_active`). A run started on one configuration
never continues on another: its review decision is refused (409) and the activation lists it; start a new run.
A release approval authorises no business action: the stage and the ontology's rules still decide what runs.
Releases live in `<data_dir>/releases.db`, append-only, chained with the workspace's audit key; a changed history or
snapshot is detected and the use case then counts as draft.

**Limits:** a release carries its model, so the platform can put the model back by itself; agents' settings and
tool declarations live in the use case's files, which only the operator deploys (activation checks them, it does
not rewrite them); Python code imported by tools is not part of the snapshot; one platform process (no coordination
between several instances).

## Lifecycle stages (Draft → Simulation → Pilot)

Every use case has a stage, kept by the platform in `<data_dir>/lifecycle.db`; nothing in a use case's own
configuration can set it. Stages advance one at a time and only when every check passes, evaluated on the server
at the moment of the move. Moving back is always allowed. Every move records who, why, the checks and the ontology
fingerprint, in a chain keyed with the workspace's audit key.

| Target | Checks |
|---|---|
| Simulation | configuration valid (strict schema); audit chains signed with the workspace key; no quarantined record |
| Pilot | the simulation checks; the engine's own `simulation` mode (automatic approvals, free-form cases) off; every reviewer role of the rules held by a named member; every run audit chain verifies; no external call waiting for reconciliation; at least one run completed since entering simulation; the configuration is the one simulated |
| Production | **refused**: no production deployment is authorised in this release |

A stage is reported **stale** when the ontology fingerprint changed after it was granted, and the use case is
reported in draft with an **integrity problem** when its history was edited outside Autology (forward moves are
then refused). A pilot stage authorises no real customer or data.

### Execution gates

The stage governs what the use case's engine executes, read at every check, at every entry point (REST, the
assistant and MCP proposals, manual and scheduled automations, deferred retries, review decisions, recovery, and
every tool call):

| Stage the engine obeys | Runs | Tools called (by declared `environment`) |
|---|---|---|
| draft (also: stale, edited history, unreadable stage) | none start or continue | none |
| simulation | yes | `simulated` |
| pilot | yes | `simulated`, `sandbox` |

`production` tools are called by no stage. **Webhooks** and **HTTP approvers** reach outside systems too and follow the same rule: each declares an `"environment"` (default `production`); a webhook that may not be reached is not delivered (the notification stays in the inbox), and a review request that may not be sent is declined (fail closed). Declare each tool's `"environment"` in `tools.json`
(`simulated`, `sandbox`, `production`; `table` tools are `simulated`; others default to `production`). A step
with no allowed tool is not sent: the run escalates and the audit records `step.blocked`. `GET /api/health`
reports `stage`, `runs_allowed` and `tool_environments`. A standalone engine (no platform) is not governed by
stages.

## Readiness: mandatory gates and scorecard (REL-2, REL-3)

`GET /platform/v1/workspaces/<ws>/use-cases/<uc>/readiness?target=pilot` (or `production`) answers two questions
from one list of **conditions**, each measured on the running use case with its own evidence:

- **May it be promoted?** A condition can be mandatory for a target stage. A mandatory condition that does not
  hold, or that cannot be verified because its evidence is missing, is a **blocker**. `promotion.allowed` depends
  on the blockers only. The same mandatory conditions are evaluated on the server at the promotion itself
  (`POST .../stage`), where a blocker refuses the move (409) and is listed in `checks`.
- **How ready is it, and what is missing?** Six dimensions, each with a score from 0 to 100 (the mean of its
  measured conditions, `held / total` each), its `calculation` in full, the `evidence` used, the
  `missing_evidence`, its `blocking` conditions and the corrective `actions`.

| Dimension | Conditions (mandatory for: P pilot and production, X production only, – advisory) |
|---|---|
| Ontology validity | model loads under the strict schema (P); the linter reports no error (P); at least one goal (P); every entity is related (–) |
| Data and knowledge quality | every stored record validates (P); every fact classified decision-critical has a writer rule (P); every fact decisions read has a writer rule (X); the last load of every pipeline succeeded (X) |
| Permission and security integrity | audit chains are keyed (P); every reviewer role is held by a member (P); no unreviewed model discretion (P); every personal or confidential field has a read rule (X); every unrestricted grant was confirmed (X) |
| Agent and action readiness | every action has a tool (P); no agent is suspended (P); every action has a simulated or sandbox tool (P); every action declares its side effect (X) |
| Simulation and test evidence | the engine's simulation mode is off (P); a run completed since simulation began (P); the configuration is the one simulated (P); every action was performed in a completed run (X); every review path was decided by a person (X) |
| Operational and audit readiness | every audit chain verifies (P); no external call awaits reconciliation (P); an approved release is active and is what runs (P); no write-back conflict is pending (P); a verified backup and a rehearsed restore are recorded (X) |

**The score informs; it decides nothing.** A high score never overrides a blocker, and a low score alone blocks
nothing. `production` is refused in this release whatever the gates say (owner decision PROD): the report then
states `production.authorised: false`.

**Weights are a proposal** awaiting the owner (decision D26): ontology 15, data 15, security 20, agents 15,
evidence 20, operations 15. A use case's configuration may set others (`"readiness": {"weights": {...}}`, all six
dimensions); they change the overall figure only, are reported with their status, and are not part of the
governing configuration (a release's fingerprint does not depend on them).

Honest limits: no backup verification or restore drill is recorded per use case yet, so that condition is always
reported as missing evidence (and blocks production readiness); "every action was performed" reads the 200 most
recent completed runs; the methodology scorecard of `autology/scoring.py` (deployment quality) is a different,
unchanged instrument.

## Use cases created from templates

The operator lists approved configurations under `"templates"` in `platform.json`
(`{"claims-starter": {"name": "...", "description": "...", "config": "../auto_insurance/server.json"}}`). A
workspace administrator creates use cases from them, never from a configuration of their own. A created use case
gets its own store, the workspace's credential scope applies to it (a template naming another workspace's
variable is refused), it is recorded in `lifecycle.db` and loaded again at every start. An identifier whose data
directory already holds data is never reused. Only workspace administrators can open a created use case until
member grants can be managed through the API (ADM-1).

## Isolation guarantees

These are enforced server-side and tested in `tests/test_workspaces.py` through the real HTTP router:

- **A token identifies exactly one person in exactly one workspace.** The platform refuses to start if two
  members share a token. Members with the same name in different workspaces are different people.
- **Another workspace does not exist for you.** A workspace you are not a member of, a use case you were not
  granted, an unknown workspace, a malformed path (`..`, upper case): all answer the same `404 not found`.
  Without a valid token, everything except health answers `401`.
- **Data, runs, reviews and audit live in separate stores.** Writing an object, starting a run or deciding a
  review in one workspace changes nothing in another. A reviewer with the same role in another workspace can
  neither see nor decide it. Each use case's access log holds only its own workspace's people.
- **Even a request that reached a use case's engine directly** with another workspace's token would be refused:
  each engine only knows the members of its own workspace that were granted it.
- **Secrets are per workspace.** A Claude key saved from one workspace's Console is written only to that
  workspace's secrets file and is not visible from another.
- **Refusals are logged** in the platform's append-only access log (`<data_dir>/platform.db`) as
  `member@workspace`.
- **Each workspace signs its own audit chains.** Its key is derived from the platform's `AUTOLOGY_AUDIT_KEY` and
  the workspace id (HMAC-SHA256), so a chain or run copied from one workspace's store into another's does not
  verify there, and holding one workspace's key does not reveal another's. Back up a use case's store with
  `autology backup CONFIG OUT --store <data_dir>/<ws>/<uc>/autology.db --audit-scope <ws>` so the copy is checked
  with the right key.

## Credentials per workspace

Integration credentials are environment variables of the platform process. A use case may name only its own
workspace's: those starting with the workspace's prefix (`ACME_` for workspace `acme` by default, or the workspace's
`"env_prefix"` in `platform.json`). The platform checks every reference form when it loads a use case: `${VAR}` in
tool and pipeline URLs and headers, `*_env` keys (`dsn_env`), and `{"env": "VAR"}` header values, in the use-case
configuration and every JSON file it references. A reference outside the prefix stops the platform from starting
and names the variable, so one workspace's configuration can never pick up another's secrets.

Python tools (`registries` in a tools file) are code the platform operator installs and trusts; Autology does not
sandbox them.

## Use cases inside a workspace

Use cases do not share anything implicitly: each has its own store, graph, agents, runs, reviews and audit chain,
and a member's grant for one use case gives nothing on another. Sharing data between use cases will need an
explicit, authorised mechanism (planned with workspace administration in R2).

## Company sign-in per workspace

A workspace may sign its people in with its own identity provider: add `"oidc"` to the workspace in
`platform.json`, with the same settings as a single engine (issuer, client id, audiences, mappings; see
[integrations](integrations.md)). It applies to every use case of that workspace; a use case's own `oidc` setting
is ignored behind the router.

```jsonc
"acme": {"name": "Acme", "oidc": {"issuer": "https://login.acme.example", "client_id": "autology", "mappings": [...]}, ...}
```

A token that is not a member token is passed only to the engine of the workspace in the path, which verifies it
against that workspace's issuer and mappings. A token from Acme's provider is refused by Northwind (401), and a
workspace without company sign-in refuses every such token. Company accounts whose name is a member's name are
refused, never mapped onto the member.

## MCP clients

Give an MCP client (Claude Desktop, an IDE) one member's token and one use case:

```bash
ACME_TOKEN=... python -m autology mcp examples/platform/platform.json --use-case claims --token-env ACME_TOKEN
```

The token decides the workspace; the client reaches that one use case only, with that member's permissions and
roles. A token from another workspace, a use case the member has no grant for, and a wrong token all get the same
refusal.

## Not yet included

Tenant-level identities and workspace administrators through the API (they are defined in `platform.json`), renaming
or archiving use cases, shared resources between use cases, and a database other than SQLite per use case. See [`../planning/AUTOLOGY_IMPLEMENTATION_BACKLOG.md`](../planning/AUTOLOGY_IMPLEMENTATION_BACKLOG.md).

**Agent grants per use case.** A member's grant for a use case may carry `"run_as": {"claims": ["fraud_analytics", "finance"]}`: the roles that member may use through that agent, beyond their own (see "What an agent may do for a person" in [platform.md](platform.md)). Without it, the agent acts with the member's own roles only.
