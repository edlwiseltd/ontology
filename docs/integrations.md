# Connecting Autology to the rest of the stack (Tier 3)

Autology is the ontology-and-agent layer. It does not try to be a data platform, a BI tool or an identity
provider. Tier 3 connects it to the ones a company already has, so each does what it is good at:

| Need | Use | Autology provides |
|---|---|---|
| Moving data out of source systems | Airbyte, dlt, Meltano, Fivetran, dbt, or plain exports | Pipelines that pull from files, SQL databases and web APIs, or accept pushed rows; checks, quarantine and lineage |
| Dashboards and analysis | Metabase, Superset, Grafana, Power BI, Tableau | A governed reporting database (SQLite or PostgreSQL), refreshed on a schedule |
| Operational monitoring and alerts | Prometheus with Grafana or Alertmanager | `GET /api/metrics` in the Prometheus text format |
| Acting in business systems | Odoo, SAP, payment providers, any API | Write-ahead journal, idempotency keys, no blind retry, confirmation contracts, reconciliation (below) |
| Company sign-in | Okta, Microsoft Entra ID, Keycloak, Auth0, Google, any OpenID Connect provider | Verified ID and access tokens, group-to-role mappings, a sign-in button in the inbox |
| Delivery | Docker, Compose, GitHub Releases and Container Registry | An image, an online backup command, a smoke test and a release workflow ([`deployment.md`](deployment.md)) |

## Acting in other systems safely

Pipelines and the reporting database only read. When an agent *acts* in another system (pays a claim, ships an
order, sends a contract), a repeat or a lost reply can do real harm. Every tool call goes through the external
effects journal (`autology/effects.py`), kept in the store:

| Guarantee | How |
|---|---|
| **Recorded before it happens** | An intent (run, step, action, tool, idempotency key, digest of the inputs) is committed before the call; the result after it. After a crash at any point, `GET /api/reconciliation` lists what may have happened |
| **One key per step** | Each step has an idempotency key, the same for every retry, resume and restart of that step. HTTP tools send it as the `Idempotency-Key` header and as `idempotency_key` in the payload; Python tools read `call.idempotency_key`. Pass it on to the system so it can refuse to act twice |
| **Never done twice by Autology** | Before calling, the agent looks the key up: a step already done is replayed from the journal, not called again (after a failed save, a crash, a deferral or a recovery) |
| **No blind retry** | Failures are classed. *Not sent* (connection refused, DNS, 408/425/429) and definite failures (`ToolError`) are retried and may go to a fallback tool. *Rejected* (other 4xx, `Rejected`) is not retried. *Unknown* (read timeout, reset, 5xx, unreadable reply, a tool crash, `OutcomeUnknown`) is never sent to another provider, and retried with the same key only if the action is declared `"side_effect": "idempotent"` or `"none"`; otherwise the run stops as `uncertain` |
| **Accepted is not done** | `202 Accepted` always leaves the step `pending_confirmation`. An action can declare `"confirmation": {"fields": ["Payment.reference"], "accepted": ["SETTLED"]}`: the reply must set those fields (and, with `accepted`, carry `output.status` in the list) before the action's effects apply. A status outside the list is a rejection |
| **People settle what nobody knows** | `uncertain` and `pending_confirmation` runs wait. A user with the `reconcile` permission (not the run's starter) answers `POST /api/reconciliation/{key}` with `{"done": true, "comment": "...", "updates": {"Payment": {"reference": "TX-1"}}}` (what the system returned) or `{"done": false, ...}`; the run then continues: replaying the confirmed result, or calling again with the same key |
| **Nothing new on a record in doubt** | While a call on a record is unknown, unconfirmed or from a run that was never saved, no run (manual, assistant or automation) may start on that record (409, naming the calls to reconcile) |
| **Recovery** | At start-up, calls still `in_flight` (cut off by a crash) become `unknown` and admins are notified. On start-up and every tick, runs whose review was decided but not continued, or whose call was reconciled, continue from the journal |

Declare, per action:

```jsonc
"pay_claim": {
  "capability": "payments.pay",
  "writes": ["Payment.reference"],
  "side_effect": "non_idempotent",          // the default; "idempotent" if the bank deduplicates by key; "none" for reads and scores
  "confirmation": {"fields": ["Payment.reference"]}
}
```

A review decision is recorded before the run acts, and never undone: if the run then fails or cannot be saved,
the answer says so and recovery continues it without repeating any call. Reviews are not reopened.

**Approvals apply to the facts that were reviewed.** Before a run continues after a review, it re-reads its live
records. A field changed only outside (the claim's amount corrected by the claims feed) is brought into the run;
if that changes a fact the reviewer saw, or the action no longer applies (the claim was rejected meanwhile), the
approval is not used: the run plans again and asks for a new review if one is still needed (`case.refreshed` and
`review.superseded` in the audit). A field the run had changed and someone changed outside too stops the run
(`escalated` to operations, with both values): a person decides which is right.

Run statuses `uncertain` and `pending_confirmation` count as open: they block a second run on the record, appear
in reports among the runs waiting for people, and in `GET /api/reconciliation` (permissions `reconcile`, `audit`
or `admin`; only records you may see).

**Not yet:** polling a system for confirmation (a person confirms today), and production writes to customer
systems: they stay disabled until the owner authorises them on an isolated test environment.

## Data ingestion

A **pipeline** reads records from other systems and loads them into the knowledge graph as ontology objects.
It is the only bulk way in, and it applies the same discipline as the rest of Autology: every value is converted
to the ontology's types and checked, rows that fail are **quarantined** with the reason instead of being loaded,
and every object remembers which load created or changed it (**lineage**).

```
source systems ──► (optional) Airbyte / dlt / dbt ──► staging DB or files ──► Autology pipeline ──► knowledge graph
                                                                   └── or push rows to the API ─┘        │
                                                                                                         ▼
                                                                                   automations start governed runs
```

### Defining a pipeline

The insurance example ([`examples/auto_insurance/pipelines/claims_feed.json`](../examples/auto_insurance/pipelines/claims_feed.json))
loads policies from a CSV export, new claims from an incremental feed, and repair shops pushed by another tool:

```json
{"name": "claims_feed", "every": 300,
 "sources": {
   "policies": {"type": "csv", "path": "../feeds/policies.csv"},
   "claims":   {"type": "jsonl", "path": "../feeds/claims.jsonl", "incremental": {"column": "updated_at"}},
   "shops":    {"type": "push"}},
 "mappings": [
   {"source": "claims", "entity": "Claim", "id": {"template": "CL-{claim_no}"},
    "attributes": {"amount": "amount", "reported_days_after": "days",
                   "status": {"value": "reported", "on": "create"}},
    "links": [{"kind": "against", "target": "policy_no"}],
    "checks": [{"attribute": "amount", "rule": "min", "value": 0,
                "message": "a claim amount cannot be negative"}]}]}
```

Register it in the server config with `"pipelines": {"claims_feed": "pipelines/claims_feed.json"}`.

**Sources**

| Type | Reads | Notes |
|---|---|---|
| `csv` | a CSV file | `delimiter`, `encoding` |
| `json` | a JSON file | `items`: dotted path to the list, e.g. `"data.claims"` |
| `jsonl` | one JSON object per line | |
| `sql` | a query | `database`: a SQLite file (opened read-only), or `driver` (any DB-API module, e.g. `psycopg`) with `dsn_env`, the environment variable holding the connection string. `{watermark}` in the query becomes a bound parameter |
| `http` | JSON over GET | `items`, `next` (dotted path to the next page's URL), `headers` with secrets as `{"env": "NAME", "prefix": "Bearer "}` |
| `push` | rows sent to `POST /api/pipelines/{name}/run` | `{"rows": {"shops": [{...}]}}`. A push call loads only what was pushed |

Connection strings and API keys always come from environment variables; a pipeline file never holds a secret.

**Mappings** turn a row into an object: `entity` (aliases work), `id` and `attributes` (each a column name, or
`{"column"}`, `{"template": "CL-{claim_no}"}` or `{"value"}`, with optional `map`, `default` and `on`), `links`
to other objects (`reverse: true` when the target points at this object), and `checks`.

**Incremental sources** (`"incremental": {"column": "updated_at"}`) remember the newest value they loaded and read
only newer rows next time.

### What happens to each row

1. **Convert** each value to the attribute's type: `"3200"` becomes `3200`, `"yes"` becomes `true`. A value that
   cannot be converted rejects the row.
2. **Check**: the state must be one of the entity's states; the mapping's checks (`required`, `min`, `max`, `in`,
   `pattern`) must pass; the id must be new or belong to an object of the same type, and appear once per load.
3. **Link**: every link target must exist already or be loaded in the same batch, and the ontology must have that
   relationship. A row whose target was rejected is rejected too.
4. **Write** the accepted rows in one transaction, with one lineage entry per object that changed (which pipeline,
   source and row; which attributes; which links). Unchanged rows write nothing.
5. **React**: changed objects go through the automations, so a newly loaded claim starts its settlement run.

**Quarantine.** Rejected rows are stored with the reason (`GET /api/ingest-batches/{id}`). They hold raw source
data, so only users with the `ingest` permission can read them.

**Watermarks stop at the first rejected row.** If a claim is rejected because its policy has not arrived yet, the
watermark is not moved past it, so the claim is read again on the next load and goes in once the policy exists.
Set `"skip_rejected": true` on the source to move past rejected rows instead.

**Lifecycle attributes.** Mapped attributes overwrite the graph on every load. Map attributes that agents change,
such as `status`, with `"on": "create"`: the source sets the first state, and later loads refresh the data
without undoing decisions.

### Running pipelines

```bash
python -m autology ingest server.json claims_feed --dry-run   # check and report; writes only the batch record
python -m autology ingest server.json claims_feed             # load (exit code 2 if any row was rejected)
python -m autology ingest server.json claims_feed --rows shops.json   # load pushed rows from a file
```

A pipeline with `"every": 300` also runs on the server's scheduler every five minutes. Over the API, a tool such
as Airbyte, dlt or a dbt job's final step signs in as a user with only the `ingest` permission and calls
`POST /api/pipelines/{name}/run`. `GET /api/objects/{id}/lineage` tells anyone who may read an object where it
came from.


**One writer per store.** A running server keeps the knowledge graph in memory, so it is the only process that
may write its store: `autology ingest` (or a second server) against a store a live server holds is refused and
names the server's process. Run pipelines through the server's API instead (`POST /api/pipelines/{name}/run`).
`autology backup` and `autology reporting` only read, and run next to the server. The lease is freed when the
server stops, when its process is gone, or when its heartbeat (renewed on every scheduler tick) is older than
three scheduler intervals (at least three minutes).
### Using a pipeline tool in front

Use an extraction tool when the source is awkward (a SaaS API with OAuth, change data capture from a production
database, hundreds of tables). Let it land the data in a staging database, model it with dbt if needed, and point
an Autology `sql` source at the staging tables. Autology then does what the pipeline tool cannot: map rows to
ontology objects, enforce the ontology's types and states, quarantine what does not fit, and trigger governed
work on what changed.

### Limits

- Loads are row-by-row in Python into SQLite: fine for tens of thousands of rows per load, not for millions.
- Deletions in a source are not propagated; retire objects with a state such as `closed` instead.
- `sql` sources are tested against SQLite and a real PostgreSQL 16 (through `psycopg`, in CI); other DB-API drivers
  (SQL Server, Oracle, MySQL) should work through the same path but are untested.
- Pushed requests are limited to 1 MB each; push large loads in chunks.

## Dashboards: the reporting database

BI tools read tables. `autology reporting` (or the server, on a schedule) writes a flat copy of the graph and of the
decision history that any of them can open:

| Table | One row per | Columns |
|---|---|---|
| `obj_<entity>` (e.g. `obj_claim`, `obj_repair_shop`) | object | `id`, `status`, one typed column per attribute, `updated_at` |
| `links` | link | `source`, `kind`, `target`, `source_type`, `target_type` |
| `runs` | agent run | agent, goal, case, status, who started it, times, step count, human touches, tool and model cost |
| `steps` | step of a run | action, verdict, outcome, executed by, reviewer |
| `reviews` | human review | action, reviewer roles, status, approved, created, decided, `hours_to_decide` |
| `outcomes` | recorded outcome | action, label, good, recorded by and when |
| `automation_firings` | automation firing | automation, object, trigger, time, result, run |
| `ingest_batches` | data load | pipeline, time, status, created, updated, unchanged, rejected |
| `_export` | setting | when it was written, for which roles, and what was left out |

```json
"reporting": {"target": "reporting.db", "roles": ["claims_handler"], "every": 300}
```

`target` is a SQLite file, or `{"driver": "psycopg", "dsn_env": "REPORTING_DSN"}` for PostgreSQL (or another
DB-API database). `every` refreshes it from the server's scheduler; `POST /api/reporting` (admin) or
`python -m autology reporting server.json [--out FILE] [--roles r1,r2]` refreshes it on demand.

**The dashboard audience is governed here, not in the BI tool.** The export is written *for* the ontology roles in
`roles`, through the same rules as an API user with those roles:

- records hidden by `row_access` rules are left out, with their links, and so are runs whose case holds one (and
  those runs' steps, reviews and outcomes);
- fields hidden by `data_access` rules are empty for the records they apply to;
- checkpoint-gated fields and fields marked `pii` or `confidential` are left out entirely; change
  `exclude_sensitivities`, or list fields in `include_fields`, to opt in;
- free text (step messages, explanations, review comments, outcome notes) is never exported.

Give each audience its own export (one file per audience, or one PostgreSQL database per audience) and let the BI
tool's own permissions decide who opens which. The SQLite file is replaced atomically, so dashboards never read half
an export, and a refresh keeps the file's permissions.

**Metabase**: add a database of type SQLite with the file's path (mount the folder into the container read-only),
or of type PostgreSQL. **Superset**: `sqlite:////data/reporting.db` or a `postgresql://` URI. **Grafana**: the
PostgreSQL data source, or a SQLite data source plugin.

*Checked for real:* Metabase 0.56 opened the export over SQLite, listed all thirteen tables, and ran a native query
joining claims to their runs; the `obj_policy` table had no `holder` column. The PostgreSQL target is tested in CI.

## Monitoring: Prometheus metrics

`GET /api/metrics` returns counts in the Prometheus text format, for any user with the `audit` permission. Give
Prometheus its own API token:

```yaml
scrape_configs:
  - job_name: autology
    metrics_path: /api/metrics
    authorization: {type: Bearer, credentials_file: /etc/prometheus/autology-token}
    static_configs: [{targets: ["autology:8800"]}]
```

| Metric | Use it to |
|---|---|
| `autology_reviews_pending{reviewer}`, `autology_review_oldest_pending_seconds{reviewer}` | alert when reviews pile up or wait too long |
| `autology_runs{agent,status}` | watch run outcomes; alert on `blocked` or `escalated` growth |
| `autology_audit_unverified_runs` | alert if any audit chain stops verifying (should always be 0) |
| `autology_quarantined_records` | alert if a stored record no longer validates and was left out of the graph at start-up (should always be 0) |
| `autology_agents_suspended` | alert when governance suspends an agent |
| `autology_ingest_last_success_timestamp_seconds{pipeline}`, `autology_ingest_rejected_rows_total{pipeline}` | alert on stale feeds and on bad data |
| `autology_automation_firings_total{automation,status}`, `autology_scheduler_errors` | spot failing automations |
| `autology_api_requests_total{status}`, `autology_objects{entity}`, `autology_info` | traffic, size, deployed version |

The metrics carry counts only: no record ids, names or values.

*Checked for real:* Prometheus 3.5 scraped the endpoint with a bearer token (target `up`) and answered queries for
`autology_objects` and `autology_ingest_rejected_rows_total`.

## Company sign-in: OpenID Connect

People sign in with their company account instead of a pasted API token, and their groups decide what they may do.

```json
"oidc": {
  "issuer": "https://login.example.com/realms/acme",
  "client_id": "autology-inbox",
  "audiences": ["autology-api"],
  "username_claim": "preferred_username",
  "mappings": [
    {"claim": "groups", "value": "claims-handlers", "permissions": ["read", "run"], "roles": ["claims_handler"]},
    {"claim": "groups", "value": "claims-managers", "permissions": ["read", "review"],
     "roles": ["claims_handler"], "reviewer_roles": ["claims_manager"]},
    {"claim": "email", "value": "ops-lead@example.com", "permissions": ["admin"]}]}
```

**In the identity provider**, register a client for the inbox: public (or confidential with
`"client_secret_env"`), authorization-code flow with PKCE (S256), redirect URI `https://<autology host>/`, and a
mapper that puts the user's groups in the ID token as `groups`.

**How the inbox signs in.** When `client_id` is set, the sign-in page offers *Sign in with your company account*.
The browser goes to the provider with a PKCE challenge, a `state` and a `nonce`; on the way back it checks the
`state`, and the Autology server exchanges the code at the provider, verifies the ID token (including the
`nonce`), and hands it to the browser, which uses it as its bearer token until it expires. The code is removed from
the address bar. When the token expires, the inbox asks the person to sign in again.

**API clients** (scripts, pipeline tools, Prometheus) may send an access token from the same provider when its
audience is listed in `audiences`, or keep using Autology API tokens. Both kinds work side by side.

**What is checked on every request**

- The signature, against the provider's published keys (found by OIDC discovery, re-fetched when a token names a
  new key, at most once a minute). RS256, RS384 and RS512 only; never `none` or shared-secret algorithms; RSA keys
  of at least 2048 bits. Verification uses only the Python standard library and is cross-checked in the tests
  against the `cryptography` package.
- Issuer (exact), audience, expiry and not-before, with `leeway` seconds (default 60) for clock skew.
- **No mapping, no access**: a valid account that no mapping grants a permission gets 403, never a default role.
- The user name (`username_claim`, default `sub`) must not be the name of an API-token user, so an account at the
  provider cannot take over a configured user's runs and reviews. Use a claim the provider's administrators
  control (`preferred_username` in Keycloak, `upn` in Entra ID, `email` with verified addresses).
- If the provider cannot be reached, sign-in fails (503); nothing falls back to weaker checks.

Everything after sign-in is unchanged: permissions, row and field access, reviewer roles, the rule that a requester
cannot decide their own review, and the access log, which records the provider's user name.

*Checked for real:* with Keycloak 26 as the provider (a realm with a public PKCE client and a groups mapper), a
headless Chromium clicked *Sign in with your company account*, logged in on Keycloak's page, and landed in the
inbox as `nora · read, review` with the claims-manager review waiting.

**Not included:** SAML (put a SAML-to-OIDC bridge such as Keycloak in front), refresh tokens (people sign in again
when the ID token expires), single logout, and EC (ES256) or PS256 signing keys.
