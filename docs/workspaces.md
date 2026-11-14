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
| Member | A person in one workspace; `workspace_admin`, or per-use-case permissions, ontology roles and reviewer roles | `workspaces.<id>.members` |
| Use case | A complete engine: ontology, agents, tools, rules, pipelines, automations, settings; its own store and audit chain | `workspaces.<id>.use_cases.<id>.config` → an ordinary `server.json` |

A use case's `server.json` is the same file a single engine uses. The platform replaces three things in it: the
store path (`<data_dir>/<workspace>/<use case>/autology.db`), the users (the workspace members granted that use
case) and the secrets file (`<data_dir>/<workspace>/secrets.json`). It drops company sign-in (`oidc`) in this
mode. The same `server.json` can therefore back a use case in several workspaces, each with its own data.

## API

| Path | Who | What |
|---|---|---|
| `GET /platform/health` | anyone | `{"status": "ok"}`, nothing else |
| `GET /platform/me` | a member | Their workspace, and the use cases they may open, with their permissions and API path |
| `/w/<workspace>/u/<use case>/api/...` | a member granted that use case | The use case's REST API, exactly as for a single engine ([`platform.md`](platform.md)) |

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

Workspace administration through the API (members and use cases are defined in `platform.json` and loaded at
start), shared
resources between use cases, and a database other than SQLite per use case. See [`../planning/AUTOLOGY_IMPLEMENTATION_BACKLOG.md`](../planning/AUTOLOGY_IMPLEMENTATION_BACKLOG.md).

**Agent grants per use case.** A member's grant for a use case may carry `"run_as": {"claims": ["fraud_analytics", "finance"]}`: the roles that member may use through that agent, beyond their own (see "What an agent may do for a person" in [platform.md](platform.md)). Without it, the agent acts with the member's own roles only.
