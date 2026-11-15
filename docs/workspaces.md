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
| Member | A person (or, with `"kind": "service"`, a machine identity such as a pipeline) in one workspace; `workspace_admin`, or per-use-case permissions, ontology roles and reviewer roles. A service member never decides a human review or settles an external call | `workspaces.<id>.members` |
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
| `GET /platform/me` | a member | Their workspace, and the use cases they may open, with their permissions and API path |
| `/w/<workspace>/u/<use case>/api/...` | a member granted that use case | The use case's REST API, exactly as for a single engine ([`platform.md`](platform.md)) |
| `GET /platform/templates` | a workspace administrator | The operator's approved templates (id, name, description; never file paths) |
| `GET /platform/workspaces/<ws>/use-cases` | a member | The use cases of their workspace they may open, each with its stage |
| `POST /platform/workspaces/<ws>/use-cases` | a workspace administrator | Create a use case from a template: `{"id", "name", "template"}`; it starts in draft |
| `GET /platform/workspaces/<ws>/use-cases/<uc>` | a member granted it | Detail: stage, stale flag, integrity problem, ontology fingerprint, stage history |
| `GET /platform/workspaces/<ws>/use-cases/<uc>/checks?to=<stage>` | a member granted it | The checks of the target stage, evaluated now; nothing is recorded |
| `POST /platform/workspaces/<ws>/use-cases/<uc>/stage` | a workspace administrator (a person) | `{"to", "reason"}`: move one stage, if every check passes |
| `GET /platform/workspaces/<ws>/use-cases/<uc>/releases` | a member granted it, or a release approver | Releases, the active one, the running configuration's fingerprint, `drift`, the release history |
| `POST /platform/workspaces/<ws>/use-cases/<uc>/releases` | a workspace administrator (a person) | `{"note"}`: propose a release of the configuration the engine runs now (201) |
| `GET /platform/workspaces/<ws>/use-cases/<uc>/releases/<n>` | a member granted it, or a release approver | One release; administrators and release approvers also get its snapshot |
| `POST .../releases/<n>/approve` | a person with release authority, not the proposer | `{"reason"}`: approve, bound to the release's fingerprint |
| `POST .../releases/<n>/revoke` | the approver or a workspace administrator | `{"reason"}`: withdraw an approval before activation |
| `POST .../<uc>/reload` | a workspace administrator (a person) | `{"reason"}`: reload the engine from its files without a restart; refused, with nothing changed, if they do not load. Not an activation |
| `GET /platform/workspaces/<ws>/members` | a workspace administrator or approver | Members (configured or added through the API), their grants, pending grant proposals, the administration history |
| `POST /platform/workspaces/<ws>/members` | a workspace administrator (a person) | `{"name", "kind", "reason"}`: add a person or a service identity; the token is in the answer, once |
| `POST .../members/<name>/token` | a workspace administrator (a person) | `{"reason"}`: replace the member's token (the old one stops at once); the new one is shown once |
| `POST .../members/<name>/revoke` | a workspace administrator (a person) | `{"use_case", "reason"}`: take the member's access to one use case away, at once |
| `POST .../members/<name>/remove` | a workspace administrator (a person) | `{"reason"}`: remove the member |
| `POST /platform/workspaces/<ws>/grants` | a workspace administrator (a person) | `{"member", "use_case", "permissions", "roles", "reviewer_roles", "run_as", "reason"}`: propose a grant (checked by the engine first) |
| `POST .../grants/<id>/approve` | a person with authority who is neither the proposer nor the member | `{"reason"}`: the grant takes effect at the next request |
| `POST .../grants/<id>/withdraw` | a workspace administrator (a person) | `{"reason"}`: drop a pending proposal |
| `POST .../releases/<n>/activate` | a workspace administrator (a person) | `{"reason"}`: activate an approved release that is exactly what runs; an older one is a rollback. The answer lists runs waiting on another configuration |

Every route above (except the contract itself) is also served under `/platform/v1/...`, and every engine route
under `/w/<ws>/u/<uc>/api/v1/...`: same handlers, same rules, with one error envelope, page metadata on lists and
a version header. The unversioned paths keep their shape and are deprecated, not removed: see
[`api-versioning.md`](api-versioning.md).

Another workspace, a use case not granted and one that does not exist all get the same `404 not found` on these
routes too. A member granted a use case but not administrator gets `403` on the writes.

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
- Workspace administrators exist only in `platform.json`: no API call creates or removes one.
- If the log does not verify (changed outside Autology), only the configured administrators keep access until an
  operator repairs it.
- **Reload** rebuilds one use case's engine from its files without restarting the platform, after loading them into a
  throwaway engine first. A reload is not an activation: with an active release, changed files count as drift and
  the use case runs nothing until a person activates an approved release of them.

## Releases (REL-1a)

A **release** is an immutable, content-addressed snapshot of what governs a use case: its ontology, the engine
settings that decide what runs and who may do what (agents, approvers, automations, service identities, webhooks,
checkpoints) and each agent's tool declarations. Its fingerprint (SHA-256) is shown as `configuration` in the
use case and in the engine's `/api/health`. Store paths, members, sign-in and secrets files are not part of it.

1. A workspace administrator **proposes** the configuration the engine runs now.
2. Another **person** with release authority **approves** it: a workspace administrator or a member named in the
   workspace's `"release_approvers"` (for example an external approver with no other access, which a workspace with a
   single administrator needs). The proposer never approves their own release; a service identity never approves.
3. A workspace administrator **activates** it. Activation is refused unless the engine runs exactly that
   configuration. Activating an older approved release is recorded as a **rollback**.

While a release is active, an engine running another configuration (a file changed and the use case restarted)
counts as **draft**: nothing runs and nothing is sent until a person activates an approved release of what now runs.
**Pilot** requires an approved active release (check `approved_release_active`). A run started on one configuration
never continues on another: its review decision is refused (409) and the activation lists it; start a new run.
A release approval authorises no business action: the stage and the ontology's rules still decide what runs.
Releases live in `<data_dir>/releases.db`, append-only, chained with the workspace's audit key; a changed history or
snapshot is detected and the use case then counts as draft.

**Limits:** activation does not reload the engine (deploy the release's files, then reload the use case or restart); Studio drafts
cannot yet become releases; Python code imported by tools is not part of the snapshot.

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

Member administration through the API (members and grants are defined in `platform.json` and loaded at
start; use cases can be created from templates, not renamed or archived), stages enforced at run time, shared
resources between use cases, and a database other than SQLite per use case. See [`../planning/AUTOLOGY_IMPLEMENTATION_BACKLOG.md`](../planning/AUTOLOGY_IMPLEMENTATION_BACKLOG.md).

**Agent grants per use case.** A member's grant for a use case may carry `"run_as": {"claims": ["fraud_analytics", "finance"]}`: the roles that member may use through that agent, beyond their own (see "What an agent may do for a person" in [platform.md](platform.md)). Without it, the agent acts with the member's own roles only.
