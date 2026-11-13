# Connecting Autology to the rest of the stack (Tier 3)

Autology is the ontology-and-agent layer. It does not try to be a data platform, a BI tool or an identity
provider. Tier 3 connects it to the ones a company already has, so each does what it is good at:

| Need | Use | Autology provides |
|---|---|---|
| Moving data out of source systems | Airbyte, dlt, Meltano, Fivetran, dbt, or plain exports | Pipelines that pull from files, SQL databases and web APIs, or accept pushed rows; checks, quarantine and lineage |

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
