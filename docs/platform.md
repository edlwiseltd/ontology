# Running Autology as a shared service

Tier 1 makes Autology usable by many projects and people at once. It adds five things:

| Capability | What it gives you | Module |
|---|---|---|
| **Multiple records per case** | One case can hold many orders, lines or shipments. Actions run once per record, and rules and access apply per record | `state.py`, `planner.py`, `governance.py` |
| **Row-level access** | Records can be hidden from people and agents without the right role, such as EU orders visible to EU staff only | `governance.py` (`row_access` rule) |
| **Persistent store** | The knowledge graph, every run, a tamper-evident audit log and review decisions survive restarts | `store.py` (SQLite) |
| **Asynchronous reviews** | A run pauses at a human review and resumes when someone decides, possibly hours later and after a restart | `agent.py` (`DeferredApprover`, `resume`) |
| **REST API and web inbox** | Token authentication, per-user permissions and data access, plus a browser inbox for reviews and monitoring | `server.py`, `static/` |

Tier 2 builds on it:

| Capability | Section |
|---|---|
| Automations on data changes, deadlines and schedules; cases built from the graph; write-back; notifications and webhooks | [Automations and notifications](#automations-and-notifications-tier-2) |
| What-if scenarios with conflict-checked commit | [What-if scenarios](#what-if-scenarios-tier-2) |
| Typed Python and TypeScript clients | [Typed client libraries](#typed-client-libraries-tier-2) |
| A governed assistant | [Governed assistant](#governed-assistant-tier-2) |
| An API access log | [Access log](#access-log-tier-2) |
| Justification checkpoints | [Checkpoints](#checkpoints-tier-2) |
| Ontology interfaces | [Interfaces](#interfaces-tier-2) |
| OpenTelemetry trace export | [Tracing](#tracing-tier-2) |
| Evaluation suites for reasoners | [`evals.md`](evals.md) |

The core still needs no third-party dependencies. The store uses SQLite and the server uses `http.server`, both from the Python standard library.

A separate conversational UI for the engine, the **Autology Console**, is described in [`console.md`](console.md).

## Quick start

```bash
cd examples/order_fulfilment
export AUTOLOGY_TOKEN_OLIVIA=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export AUTOLOGY_TOKEN_LENA=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export AUTOLOGY_TOKEN_AUDREY=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export AUTOLOGY_TOKEN_ADMIN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export AUTOLOGY_AUDIT_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")   # keep it: needed to verify logs later
echo "olivia: $AUTOLOGY_TOKEN_OLIVIA   lena: $AUTOLOGY_TOKEN_LENA"
python -m autology serve server.json --port 8800
```

Open `http://127.0.0.1:8800` and sign in with the admin token. Start a run from **Start a run** by pasting `case.json` as case data: only admins may hand an agent case data directly. The run pauses because order O-4 is worth more than 50,000. Sign in as Lena, who holds the logistics-manager reviewer role: the review is in her inbox with the rule, the facts and the history. Approve it and the run completes.

Everyone else starts runs from the stored data: pick the `contract_case` template and an object to start from, such as `K-1`, and the case is assembled from the knowledge graph. A person may start a run only if they may see every record in its case. Olivia (ops) cannot start one on `K-1`, because its case includes the EU order O-3. Lena (ops and EU ops) can.

The example has four users, each showing a different access level:

| User | Permissions | Data roles | Sees |
|---|---|---|---|
| olivia | read, run | ops | 2 of 3 orders: the EU order is hidden; credit limits are redacted |
| lena | read, run, review | ops, eu_ops | all orders; can start runs on them and decide logistics reviews (never on runs she started) |
| audrey | read, audit | finance | credit limits; raw audit entries |
| admin | admin | — | everything; can upload data |

## Multiple records per case

Mark an entity `"multiple": true`, give actions that work on one record at a time a `"for_each"`, and use quantifiers in goals:

```jsonc
"entities": {"Order": {"multiple": true, "states": ["received", "picked", "shipped", "invoiced", "cancelled"], ...}},
"actions": {
  "ship_order": {"for_each": "Order", "requires": ["Order.status == 'picked'"], "effects": {"Order": {"status": "shipped"}}, ...}
},
"goals": {"fulfil_contract": {"target": "Contract.status == 'signed' and all_of(Order.status in ['invoiced', 'cancelled'])"}},
"rules": [
  {"id": "R-HAZ-001", "type": "mandatory_step", "when": "Order.hazardous == True", "step": "clear_hazmat", "before": "ship_order"},
  {"id": "R-ROW-001", "type": "row_access", "entity": "Order", "when": "Order.region == 'EU'", "roles": ["eu_ops"]}
]
```

- **Case data** gives a list for a multi-record entity: `"Order": [{"id": "O-1", ...}, {"id": "O-2", ...}]`.
- **Actions are bound to a record** and named `ship_order@O-2`. Their conditions, effects, tool inputs and tool updates apply to that record only. Tools receive the record ID as `call.target`.
- **Quantifiers:** `all_of(...)`, `any_of(...)` and `count_of(...)` range over the records of one multi-record entity. Validation rejects references to such an entity outside a quantifier, unless the action is bound to it.
- **Mandatory steps are tracked per record** when the step and the gated action are bound to the same entity. In the example, `clear_hazmat@O-2` unlocks `ship_order@O-2` only.
- **Planning** works one record at a time for `all_of` goals, using small exact searches, so many records don't explode the search. The combined plan is compliant, but not guaranteed to be the cheapest overall.
- **Delegation never pools roles.** An action is plannable only if one team member may perform it on its own. Explanations list each member's reason.

## The facts behind rules come from the system of record

Three safeguards stop a requester from steering which rules apply:

- **No hand-written cases.** A user with `run` starts runs from a case template and a root object, so amounts, regions and other facts come from the stored data. Posting a free-form `case` returns 403, unless the user is an admin or the server config sets `"simulation": true`, which is meant for test and training servers.
- **Types are checked.** Case data and graph data must match each attribute's declared type: `string`, `number`, `integer`, `boolean`, `date`. A string amount such as `"80000"` is rejected rather than compared as text. Missing values are allowed.
- **Unknown facts do not switch rules off.** A `human_review`, `prohibition`, `row_access` or `data_access` rule whose condition cannot be evaluated, because a value is missing or of the wrong type, applies. The decision says why, for example "(applied because Order.amount is unknown)". `mandatory_step`, `action_access` and `write_access` rules, and action preconditions, keep ordinary true-or-false evaluation. The planner is optimistic about facts that tools will set later; the check when the action is about to run is the one that holds.

## Failures are logged

**Headless.** The engine is the API. The review inbox in `autology/static/` is optional: without it the engine runs
unchanged and `GET /` answers 404 ("not installed"). No engine module imports a user interface or Hermes
(`tests/test_engine_headless.py`).

Nothing fails silently. The scheduler, webhook deliveries, trace exports, automation firings, the access log and unexpected errors in any endpoint are logged with a traceback to the `autology` logger. `autology serve` prints the log to standard error, and `"log_file": "autology.log"` in the server config also writes it to a file. Clients still get only `internal error: <ExceptionType>`. `GET /api/health` shows the scheduler's last successful tick and its last error.

**Tool results are type-checked.** A value a tool returns must match the attribute's type (`number`, `integer`, `boolean`, ...; a boolean is not a number), and a returned `status` must be a state of the entity. Otherwise nothing from the result is applied, the run escalates to `it-integration`, and the audit records a `governance.reject_result` entry with the value.

**A bad stored record never stops a restart.** At start-up, every stored record is validated again. One that no longer validates (edited by hand, or written by an older version) is left out of the graph with its links, kept in the store for repair, logged, and reported to admins as a `quarantine` notification. `GET /api/health` then reads `"status": "degraded"` with `quarantined_records`, and the `autology_quarantined_records` metric counts them. Upserting the record with valid values brings it back.

## Agent suspension

An agent whose proposals governance refuses `settings.max_violations` times **within one run** is suspended. Violations are counted per run, so separate runs of the same agent never add up. The suspension is stored, so it survives restarts, and it applies to every later run of that agent until an admin lifts it:

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/agents` | read | Agents with their goals, roles and whether they are suspended, and why |
| `POST /api/agents/{name}/reinstate` | admin | `{"reason": "..."}` (at least 10 characters). The suspension, the reinstatement, who did it and why are kept in the store's suspension history |

## Reviews are decided by people

- **Automatic approvers need the simulation flag.** In a server config, an agent's `approver` of `auto`, or a policy file that can approve, is refused at start-up unless the config sets `"simulation": true`. `inbox` and `deny` are allowed. An **HTTP approver** (`{"type": "http", ...}`) is an outside system, so it counts as automatic too: refused on a real server, and in simulation its decisions are recorded as `automatic`, attributed to `http:<origin>`; the reviewer name the system returns is kept in the comment as a claim, never as the reviewer (H-1/F-02). A person decides through the inbox or `POST /api/v1/reviews/{id}/decision` with their own sign-in.
- **People and machines.** Each user may declare `"kind": "person"` (default) or `"kind": "service"` (a script, pipeline or integration). A service identity can never decide a human review or settle an external call (`reconcile`), whatever its permissions: 403. A step that no rule sends to review still runs with no person at all: autonomy is set by the policy, not by this check (D11). The flag shows in `GET /api/health`, at the top of `GET /api/report`, and as `"simulation": true` in `GET /api/score`.
- **Automatic decisions are flagged.** Every review decided by a script or policy is marked `automatic` in the audit log, and the compliance report warns how many there were, also for runs made with `autology run --approver auto`.
- **No self-approval by default.** Each run records who started it, on the run and in its `run.start` audit entry; automations record `automation:<name>`. That person may not decide the run's review. A `human_review` rule can allow it with `"allow_self_review": true`.

## Row-level access

A `row_access` rule hides the records of an entity matching its `when` condition from anyone without one of its `roles`:

- **Agents:** hidden records are left out of the agent's view, its LLM prompts and its review requests. Actions on them are denied, and if the goal needs them the run escalates, naming the rule.
- **API users:** hidden records are absent from listings, and fetching one returns 404, so its existence isn't revealed. A competency question that would aggregate over hidden records is refused.
- **Field rules still apply on top:** `data_access` redacts individual fields.

### Runs, reviews and answers

One policy (`autology/views.py`) decides what a user sees of runs and reviews, and every endpoint and assistant tool uses it:

- **People start and resume runs only on records they may see.** A run built from a case template is refused (403) if its case includes a record the requester may not see. The answer names no hidden record. Otherwise the agent, acting with its own roles, could change records the person cannot reach. Firing an automation by hand follows the same rule: such a firing is `skipped`. Resuming a run the caller may not see returns 404. Automations that fire on their own act with their configured agent's roles and are recorded as `automation:<name>`.
- **Runs over hidden records are hidden.** If a run's case holds a record the user may not see, the run is absent from their listings, reports and scores, and fetching it returns 404. If someone's access narrows after they started a run, they get a receipt with its id and status only.
- **Visible runs go through the user's field access.** State fields they may not read are redacted, and checkpoint-gated fields read `"***justification required***"`. Restricted facts are scrubbed from step explanations and escalation details. The message of a step whose action reads or writes a restricted field is withheld.
- **Reviews are readable only by** admins, holders of one of the review's reviewer roles, and the person who started the run. Each sees the case through their own field access. Anyone else gets 404, and the run summary shows them no review id.
- **Answers check the fields they use.** A competency question that filters or aggregates on a field the user may not read on some record is refused (403). A checkpoint-gated field needs a `"justification"` in the request.
- **Scenario diffs** show restricted before and after values as redacted, and **scenario comparisons** withhold the answer to any question that reads a field the user may not read or a checkpoint-gated field (see [What-if scenarios](#what-if-scenarios-tier-2)).
- **Admins** see every record and field, but they too must justify checkpoint-gated fields.

## One open run per record

A record that a case is built from (the case template's root, such as a claim or a contract) has **at most one open
run** at a time. "Open" means not yet finished: awaiting a review, deferred or paused. A second start on the same
record, by a person, a confirmed assistant proposal or an automation, is refused while the first is open:

- `POST /api/runs` answers **409** and names the open run (`active_run`, `active_status`);
- an automation's firing is recorded as **skipped**, with the open run's id, and is not retried;
- two simultaneous starts on the same record produce exactly one run.

The record is free again as soon as its run finishes (completed, declined in review, blocked, escalated).
Duplicates created before this rule, or while it was off, cannot both go ahead: **approving** a review is refused
while the same record has another open run (409 with `other_runs`); **declining** is always allowed, so decline
the duplicates first. Set `"one_active_run_per_record": false` in the server config only if your processes really
need parallel runs on one record.

This prevents a second run from repeating actions that the first already took (for example paying a claim twice).
It does not, on its own, make a single run safe against timeouts or crashes after an external action; see the
audit's GAP-001 to GAP-007.

## Persistent store

```python
from autology.store import Store
store = Store("autology.db")
store.save_graph(graph); graph = store.load_graph(ontology)
run_id = store.save_run(result, agent="fulfilment"); result = store.load_run(run_id)
```

- **The audit log is tamper-evident, not tamper-proof.** What protects it, and what does not:
  - **Keyed chain.** Each entry is chained to the one before with HMAC-SHA256 under a secret from `AUTOLOGY_AUDIT_KEY`. A server refuses to start without the key unless the config sets `"simulation": true`, and `GET /api/health` reports `audit_keyed`. Someone who can edit the database but lacks the key cannot rewrite an entry and recompute the chain.
  - **Recorded heads.** The store records every run's chain head (length, last hash and a keyed MAC), so deleting entries from the end is detected. Run files carry the head too.
  - **Resumable state is bound to the chain.** Before a parked run continues, its stored status and case state must equal what its last `run.end` entry recorded. Every stored review decision must point to the `review.decision` audit entry that granted it. Otherwise the run is escalated to `security` instead of acting.
  - **Sealed run records.** Each time Autology writes a run, it seals the whole stored row: the record (pending review, attempts, failures, ontology reference, state), its status, agent and starter, and its chain head, bound to the run id with HMAC-SHA256 under the audit key. An edit to any of them, or a chain and record copied onto another run id, makes `verify_audit` fail, counts in the `autology_audit_unverified_runs` metric and in `autology backup`, and escalates the run to `security` instead of resuming it. Stores from before schema 11 are sealed as they are when first opened by this version, so verify them before upgrading.
  - **Triggers** reject UPDATE and DELETE on audit rows, but anyone with direct database access can drop them. They guard against mistakes, not attackers.
  - **Not an external anchor.** Whoever holds the key can rewrite everything consistently. Publish the heads from `GET /api/audit-heads` (audit permission) to WORM storage or a timestamping service if third parties must be able to check them.
  - **Existing logs.** Logs recorded without a key do not verify once a key is set: verification cannot tell an old unkeyed log from a forged one.
- **Saving a run** appends only its new entries, and refuses if the stored history and the run's history diverge, or if the run's own chain doesn't verify.
- **Loaded runs** rebuild their audit trail from the audit table, not from the run record.
- **The CLI** writes to and reads from a store with `--db`: `autology run ... --db autology.db`, `autology report ONTOLOGY --db autology.db`, `autology score ONTOLOGY --db autology.db`.
- **Scale:** SQLite suits one server and pilots. File databases use WAL mode, and a lock makes the store thread-safe. The `Store` interface is small, so a PostgreSQL implementation is the path to larger deployments.

## Asynchronous reviews

`DeferredApprover` never decides inline. When governance requires a human review, the run stops with status `awaiting_review` and records exactly which action is waiting. Later, possibly in another process:

```python
result = agent.resume(stored_result, decision=ReviewDecision(True, "lena", "carrier confirmed"))
```

The decision applies to exactly the action that was waiting. The reviewer's identity and comment go into the audit trail. Reporting counts parked runs as *pending*, not as failures.

## REST API

Every request needs `Authorization: Bearer <token>` (an Autology API token, or a token from the company's identity
provider when `oidc` is configured: see [`integrations.md`](integrations.md)), except `/api/health`,
`GET /api/auth/config`, `POST /api/auth/token` (the inbox's sign-in) and the inbox's static files.

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/health` | any | Liveness, stage and integrity summary (no token needed) |
| `GET /api/openapi.json` | any | The API contract, OpenAPI 3.1, paths under `/api/v1` (no token needed; `autology/openapi.py`). Every route in this document is also served under `/api/v1/...`; see [`api-versioning.md`](api-versioning.md) |
| `GET /api/auth/config` | any | What a sign-in page needs to offer company sign-in (no token needed) |
| `POST /api/auth/token` | any | Exchange a company sign-in code for a token (no token needed) |
| `GET /api/justifications` | audit | Reasons people gave at checkpoints |
| `GET /api/audit-heads` | audit | The head of every run's audit chain |
| `GET /api/runs/{id}/trace` | audit | A run as an OpenTelemetry trace |
| `GET /api/runs/{id}/outcomes` | read | Recorded outcomes of a run |
| `POST /api/runs/{id}/outcomes` | review | Record a decision's outcome |
| `GET /api/outcomes` | read | Outcomes summary |
| `GET /api/sdk/{language}` | read | A typed client for this ontology (`python`, `typescript`) |
| `GET /api/model/draft` | read or configure | The model draft (or the active model if none), with the engine's validation and rule-based discovery questions. A draft never changes what runs |
| `POST /api/model/draft` | configure | `{"document", "expected_revision", "note"}`: save a new draft revision over the one you read; 409 if someone saved meanwhile |
| `GET /api/model/draft/history` | read or configure | Draft revisions (append-only) |
| `POST /api/model/validate` | read or configure | `{"document"}`: strict validation with the problem's location (`entities.X…`, `relationships.N`), plus discovery questions; nothing is saved |
| `POST /api/model/draft/simulate` | configure | `{"document", "case", "goal", "roles", "approvals"}` (all optional): a dry run of a model document (the draft by default) by the engine's planner and governance with **stub tools**. It parks at each human review and continues only with an explicit simulated decision (`{"action", "approved", "as": reviewer role}`). Nothing is stored, no record is read or written, nothing outside the engine is called; the answer says so and is not evidence of a real run |
| `GET /api/solution/draft` | read or configure | The **executable configuration** of the draft: agents (purpose, roles, goals, autonomy policy, one catalogue tool per permitted action) and synthetic sample records; its `state` (`none`, `invalid`, `validated`), the engine's `validation`, each agent's effective `permissions` per action, what runs now (`active`: Studio-managed, configured in files, or none) and the `changes` against it |
| `POST /api/solution/draft` | configure | `{"solution", "expected_revision", "note"}`: save the configuration as a new draft revision (the model is carried over; `null` withdraws the configuration). An invalid configuration is refused (400 with every problem); 409 on a stale revision, or when an operator configured this use case's agents in files |
| `GET /api/application` | read | The **application** designed for what runs, as this caller may use it: the manifest with the views and fields this caller can never see removed, what the caller may do (`you.may`), the stage, and the configuration it is bound to. 404 when none was designed; **409 when another configuration runs** than the one the design was saved for (a release was activated or rolled back), or when the design no longer validates. A manifest grants nothing: records, runs, reviews and audit are still asked from their own routes. See [application-builder](application-builder.md) |
| `POST /api/application/generate` | read or configure | `{"id"?}`: a draft manifest generated from the released model's structure and the approved agents. Deterministic, no language model, nothing saved. 409 while nothing is released |
| `POST /api/application/validate` | read or configure | `{"manifest"}`: every reason the manifest cannot be used with what runs (closed schema, entities, attributes, relationships, case templates, actions, rules, agents, binding, text that is not plain text). Nothing is repaired |
| `GET /api/application/draft` | read or configure | The saved application design (append-only revisions), its validation against what runs, and its history |
| `POST /api/application/draft` | configure | `{"manifest", "expected_revision", "note"}`: save a design, by a person, over the revision read. An invalid manifest is never stored (400 with the problems); 409 on a stale revision |
| `POST /api/solution/validate` | read or configure | `{"solution", "document"}`: the same answer for a configuration that is not saved |
| `POST /api/solution/suggest` | configure | `{"proposal"}` (optional): a starting configuration for the draft's model, from the approved template the proposal used when it has one, a plain one otherwise. Nothing is saved |
| `GET /api/tools/catalog` | read or configure | The approved catalogue: three simulated tools (complete, decision table, fail on purpose) and what is **not available** from Studio (connectors, custom code, model reasoners) with the reason |
| `POST /api/architect/proposals` | configure | `{"brief"}`: provisional additions from an approved industry blueprint, labelled `"ai": false`; nothing is applied. With `"generator": "model"`: through the AI gateway and the proposal contract, validated by the engine and **stored as a revision** (`id`, `revision`); `{"revises": id, "answers": [{"id", "answer"}]}` answers its clarification questions and stores the next revision. 409 when the use case has no architect provider |
| `GET /api/architect/proposals` | read or configure | Stored proposals (latest revision of each) and `architect`: whether a provider is configured and whether it is a language model or the sandbox test double |
| `GET /api/architect/proposals/{id}` | read or configure | One revision (`?revision=`; the latest by default) with its provenance, items, rejected items, questions, assumptions, validation, the revision `history` and the review `decisions` |
| `POST /api/architect/proposals/{id}/decision` | configure (a person) | `{"revision", "accepted": [item ids], "rejected": [item ids], "note"}`: record a review. It changes no model |
| `GET /api/me` | any | Who am I, with permissions and roles |
| `GET /api/ontology` | read or configure | Entities, actions, goals, rules, questions, agents |
| `GET /api/objects?type=&limit=&offset=` | read | Objects, row- and field-filtered for the caller |
| `GET /api/objects/{id}` | read | One object with its visible links |
| `POST /api/objects` | admin | Create or update an object and its outgoing links, validated against the ontology. Optional `"expected_revision"` (from the object's `revision`; 0 = must not exist yet): if the record changed since, 409 with the current revision and nothing written |
| `POST /api/questions/{id}` | read | Answer a competency question, with `{"params": {...}, "justification": "..."}` (the reason is needed when the question reads a checkpoint-gated field) |
| `POST /api/runs` | run | Start a run from the graph: `{"agent", "goal", "case_template", "root"}`. Free-form `{"case", "case_id"}` only for admins or with `"simulation": true` |
| `GET /api/runs?status=` | read | List runs |
| `GET /api/runs/{id}` | read | Steps, status, escalation, the caller's view of the state, audit verification |
| `GET /api/runs/{id}/audit` | audit | Raw audit entries |
| `POST /api/runs/{id}/resume` | run | Resume a deferred or paused run (`{"force": true}` skips the retry window) |
| `POST /api/runs/{id}/cancel` | run | `{"reason"}`: stop a run that is waiting for a review, a retry or a resume. What it did stays done; the cancellation joins its audit chain and its pending review is closed. A run that is acting, or whose external call is unresolved, is refused (409) |
| `GET /api/reviews?status=pending` | review | Reviews the caller may decide |
| `GET /api/reviews/{id}` | read | One review, for admins, its reviewers and the run's starter only |
| `POST /api/reviews/{id}/decision` | review | `{"approved": true/false, "comment": "..."}`. Resumes the run, and can be decided once only |
| `GET /api/reconciliation` | reconcile, audit or admin | External calls a person must settle: outcome unknown, accepted but unconfirmed, or made by a run that was never saved ([integrations](integrations.md#acting-in-other-systems-safely)) |
| `POST /api/mcp` | read, run, review, audit, ingest, reconcile or admin (tools filtered by permission) | One MCP JSON-RPC message, answered by the same MCP server as `autology mcp` over stdio, as the token's user: the same tools, permissions, redaction and execution gates. A notification answers 202. Behind the platform: `/w/<ws>/u/<uc>/api/mcp` (or the relay `autology mcp --url`) |
| `POST /api/runs/{id}/write-back` | reconcile | After a person resolved a write-back conflict: try the run's whole write set again, all or nothing. Answers `{"state": "committed" | "conflict" | "pending", "conflicts": [...]}` |
| `POST /api/reconciliation/{key}` | reconcile | `{"done": true/false, "comment": "...", "updates": {...}}`. Not the run's starter. The run then continues without repeating the call |
| `GET /api/report` | read | Compliance report (markdown) |
| `GET /api/score` | read | Readiness scorecard over all stored runs |
| `GET /api/objects/{id}/lineage` | read | Every data load that created or changed the object (Tier 3, [`integrations.md`](integrations.md)) |
| `GET /api/pipelines` | ingest | Data pipelines, their sources, watermarks and last load |
| `POST /api/pipelines/{name}/run` | ingest | Run a pipeline (`{"dry_run": true}` to check only), or push rows: `{"rows": {"source": [...]}}` |
| `GET /api/ingest-batches/{id}` | ingest | One load, with its quarantined rows |
| `GET /api/metrics` | audit | Operational metrics in the Prometheus text format (counts only) |
| `POST /api/reporting` | admin | Rewrite the governed reporting database for BI tools |
| `GET /api/settings/assistant` · `POST /api/settings/assistant` | configure | The Claude assistant's settings: on/off, model, effort, key (write-only; only its last four characters are ever returned) |
| `POST /api/settings/assistant/test` | configure | Check the key and model with Claude (a model lookup: no tokens spent) |

**Permissions:**

| Permission | Allows |
|---|---|
| `read` | Ontology, objects, runs, reports |
| `run` | Starting and resuming runs |
| `review` | Deciding reviews for the user's `reviewer_roles` |
| `audit` | Raw audit entries |
| `ingest` | Running data pipelines and reading quarantined rows (give it to the account a pipeline tool uses, and nothing else) |
| `reconcile` | Settling external calls whose outcome is unknown or unconfirmed ([integrations](integrations.md#acting-in-other-systems-safely)) |
| `configure` | Administration without data (IAM-3): the model summary, model drafts, validation, architect proposals, the assistant's settings. It reads no record, run, review or audit entry |
| `admin` | Everything on this engine: data upload, every record regardless of row and field rules, scheduler, scenario commit, and all the permissions above. Behind the platform it is given only by an explicit, approved grant, never by an administrative role |

A user's `roles` are ontology roles, and the row and field rules apply to everything returned to them.

**What an agent may do for a person.** A run acts with the intersection of the agent's roles and the requester's:
their own `roles` plus the roles an administrator lets them use through that agent (`run_as`). An agent with the
`finance` role does not run a credit check for an operations clerk unless the clerk is granted it:

```jsonc
{"name": "olivia", "roles": ["ops"], "run_as": {"fulfilment": ["finance"]}, ...}
```

The run keeps these roles for its whole life (sealed with the run record): a reviewer with wider roles who
approves a step does not widen the run. The agent's delegates are narrowed the same way. `run.start` in the
audit records the effective roles, the agent's own roles and whom the run acts for. Administrators use the
agent's roles. Users signed in through OpenID Connect use their mapped roles only (no `run_as` yet).

### Security notes

- **Tokens.** Generate them with `python -m autology token`. Only SHA-256 hashes go in the config, or tokens come from environment variables (`token_env`). Comparison is constant-time.
- **Token lifetimes (GAP-030).** Every API token expires: `security.tokens` gives the lifetime per kind (`person_days`, default 90; `service_days`, default 365; at most 3650), counted from the first time the engine saw the token. That date is kept beside a SQLite store (`<store>.credentials`, or `credentials_file`); with a memory or PostgreSQL store and no `credentials_file`, lifetimes count from each start and the engine says so in its log. A user may carry an earlier `"token_expires"`. A token that existed before this version gets one full lifetime from the upgrade. An expired or revoked token gets `401` (`reason: token_expired` / `token_revoked`); `GET /api/me` shows `token_expires_at`. To replace a token, put the new hash in the configuration. Behind the platform router, members' tokens are replaced and revoked through the API ([workspaces.md](workspaces.md)).
- **Rate limits and timeouts (GAP-030).** `security.rate_limits`, `security.trusted_proxies`, `security.server` and `security.run_seconds` work as described in [workspaces.md](workspaces.md) (the `tenant` class applies behind the platform only). Counters are in the memory of one process.
- **Network.** The server binds to `127.0.0.1` by default. Put it behind a reverse proxy with TLS before exposing it.
- **Requests.** Bodies are limited to 1 MB. Errors never include tracebacks.
- **The inbox** is served with a strict Content-Security-Policy (`script-src 'self'`, no inline scripts). It inserts data as text only, and keeps the token in the browser tab's session storage.
- **Concurrency.** Runs are serialised per agent, so governance counters such as suspensions stay consistent.
- **Decision-critical facts fail closed.** An attribute marked `"decision_critical": true` changes only for a writer holding the roles of a `write_access` rule on it, on every write path (ingestion, `POST /api/objects`, scenario commit, agent actions), the unrestricted `admin` permission included; with no such rule nobody changes it. Opt-in per field; see [integrations](integrations.md#who-may-change-the-facts-decisions-rest-on-gap-037).
- **What a model may decide (SEC-A, GAP-045).** A model reasoner names one of the actions the ontology allows now, and governance evaluates it again. Because text in the data can still steer a model *among* valid actions, a model's choice that differs from the deterministic plan is honoured only where policy lets a model choose: the action is under a `human_review` rule in that state (a person decides), or the agent's configuration lists it in `"model_may_choose": [...]`. Otherwise the plan's step runs and the refused choice is in the run's audit (`reasoner.deviation_refused`). `"model_discretion"` on an agent is `"governed"` (default), `"plan"` (the model never chooses) or `"open"` (any valid action: the behaviour before SEC-A, to be chosen deliberately). Both keys are governing settings: they are in the configuration fingerprint and in every release. Discretion nobody reviews is logged at start and listed by `GET /api/agents` (`model_findings`). Data goes to the model inside a marked block its content cannot close, and a reply with anything beyond an action and a reason is refused (`reasoner.refused`); those are hygiene, the policy above is the control. The tests use a model that obeys every instruction it finds in the data.
- **Notifications show each reader what they may read (GAP-035).** An automation's message is rendered per reader: a field a `data_access` rule hides from them, or one that needs a written justification, is shown as `[restricted]`; notifications about a record or a run they may not see are not listed. The stored text and what webhooks receive is the version every addressed role may read.

### Not yet included

- SAML sign-in (OpenID Connect is supported, Tier 3);
- rate limits shared between several server processes (counters are per process);
- multi-tenant separation within one engine server (several organisations behind one router is the platform's job:
  [workspaces.md](workspaces.md));
- a PostgreSQL store.

## Automations and notifications (Tier 2)

Automations start work when the knowledge graph changes, instead of waiting for someone to call an agent. They are deployment configuration, so they live in the server config and are validated against the ontology and the configured agents at start-up.

```jsonc
"automations": {
  "fulfil_signed_contracts": {
    "entity": "Contract", "when": "Contract.status == 'signed'", "trigger": "change",
    "run": {"agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case", "as": "fulfilment-bot"},
    "notify": {"roles": ["logistics_manager"], "message": "Contract {id} is signed: fulfilment started"}
  },
  "large_order_watch": {
    "entity": "Order", "when": "Order.amount > 50000 and Order.status == 'received'", "trigger": {"every": 3600},
    "notify": {"roles": ["finance"], "message": "Order {id} for {amount} is still waiting for a credit check"}
  }
},
"automation_interval": 60,
"webhooks": [{"url": "https://hooks.example.com/autology", "kinds": ["review", "automation"]}]
```

**Runs nobody asked for act as a service identity.** Every automation that starts runs names one with `"as"`.
Identities are declared once, with the least roles they need and the agents they may drive; the run acts with
the agent's roles narrowed to the identity's, and the audit records `acting_as: service:<identity>`:

```jsonc
"service_identities": {
  "fulfilment-bot": {"description": "Fulfils signed contracts", "agents": ["fulfilment"],
                     "roles": ["ops", "eu_ops", "finance"]}
}
```

A server refuses to start if an automation runs without an identity or with one not authorised for its agent. A
person firing an automation by hand acts as themselves (their own intersection), not as the identity.

**Triggers:**

| Trigger | Fires |
|---|---|
| `"change"` (default) | Once when the condition *becomes* true for an instance. It fires again only after the condition has been false in between. Checked on every API write, every write-back from a run, and every scheduled tick, so conditions on `Params.now` (epoch seconds) work as deadlines. Which instances have fired is stored, so a restart does not fire everything again |
| `{"every": seconds}` | On ticks, for every instance where the condition holds, at most once per interval per instance |

A condition refers to the automation's entity only, plus `Params.now`. When a change automation is first switched on, it fires for every instance where its condition already holds.

**When a firing fails.** A firing *errors* when firing itself raises, for example when the case cannot be built or the store is unavailable. A run that ends escalated or blocked is a normal result, not an error. An errored firing is not counted as done: the instance stays armed and is retried after `retry.after` seconds (default 300), up to `retry.max` attempts in all (default 5): `"retry": {"after": 300, "max": 5}`. Each failure is logged with its traceback and recorded as a firing with status `error`, saying which retry is next. After the last attempt the firing is recorded as `gave_up`, a warning is logged, and nothing more happens for that instance until its condition turns false and true again.

**Runs on graph data.** A `run` assembles its case from the graph with a *case template* declared in the ontology:

```jsonc
"case_templates": {
  "contract_case": {"root": "Contract",
                    "entities": {"Contract": "self", "Customer": "^hasContract", "Order": "covers"}}
}
```

Each entity is reached from the root instance by a relationship path (`^` follows a link backwards). Multi-record entities take every instance reached; others take the first. The run is governed like any other: rules, reviews, row access and audit all apply. With `write_back` (on by default), the fields the run changed are written back to the instances the case came from each time the run is saved, including after a review is decided later. Fields the run did not change are never touched, so edits made while a run waits for a review survive. If a field the run changed has also changed on the live record since the case was built, the live value is kept, the conflict is recorded on the run (`write_back_conflicts` in the run summary) and a `conflict` notification goes to admins. This is the same rule as a scenario commit. Write-backs count as changes, so one automation can trigger the next. A pass stops after 200 firings to guard against loops.

People can start the same kind of run from the API: `POST /api/runs` with `{"case_template": "contract_case", "root": "K-1"}` instead of `case`.

**Notifications** go to everyone holding one of the listed roles (data roles or reviewer roles). A notification is recorded whenever a review is opened, addressed to its reviewer roles, and whenever an automation with `notify` fires. Notifications about a record are hidden from people who may not see that record, so message text cannot leak a hidden row. Each notification is also POSTed as JSON (`{"autology": {...}}`) to every configured webhook whose `kinds` match, on a background thread, best effort. The stored notification is the record of truth.

**The scheduler.** `autology serve` ticks every `automation_interval` seconds. A tick resumes deferred runs whose retry time has come, then evaluates every automation. Admins can also tick by hand.

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/automations` | read | Automations with their recent firings and the current status of the runs they started |
| `POST /api/automations/{name}/run` | run | Fire now: `{"instance": "K-1"}` for one instance, or `{}` for every instance the caller may see where the condition holds. The condition must hold (otherwise the firing is `skipped`), the `start_run` checkpoint applies, the caller is recorded as the run's starter, so they cannot approve its reviews, and a case that includes records the caller may not see is `skipped` |
| `GET /api/notifications?since=&limit=` | read | Notifications for the caller's roles, newest first |
| `POST /api/tick` | admin | Run one scheduler pass now |

The inbox has an **Activity** tab with the caller's notifications and the automations, including a *Run now* button for users with the `run` permission.

**Store.** The schema moves to version 2 with tables for automation state, firings, notifications and the instances each run came from. A version 1 store is upgraded in place on start-up.

## What-if scenarios (Tier 2)

A scenario is a sandbox copy of the knowledge graph. You apply edits to the copy, compare the result with the live data, then commit or discard. Nothing reaches the live graph until a commit.

```jsonc
{
  "name": "Northwind adds a large turbine order",
  "edits": [
    {"op": "add", "type": "Order", "id": "O-6", "attributes": {"amount": 95000, ...},
     "links": [{"kind": "covers", "source": "K-1"}]},
    {"op": "action", "action": "credit_check", "case_template": "contract_case", "root": "K-1",
     "target": "O-6", "agent": "fulfilment"}
  ],
  "checks": [{"goal": "fulfil_contract", "case_template": "contract_case", "root": "K-1", "agent": "fulfilment"}]
}
```

| Edit | Effect on the copy |
|---|---|
| `set` | Change attributes of an instance. Validated against the ontology, including states |
| `add` | Add an instance, optionally with links (`{"kind", "target"}` or `{"kind", "source"}`) |
| `link` | Add a link |
| `action` | Simulate one ontology action on a case built from the copy. Governance decides as it would for an agent: a denied action is recorded and not applied; one that would need human review is applied and flagged with its reviewers. Mandatory steps done earlier in the scenario count. No tool is called |
| `event` | Apply an event's impact rules, such as a machine alert setting the machine down, and record what it affects |

**Comparison** against the unchanged live data covers:

- every competency question whose answer changes;
- for each check, the plan to a goal: its steps and which of them need human review, or which action and rule block it;
- with `schedule`, schedule KPIs: jobs scheduled, jobs on hold and why, makespan, late jobs and tardiness. Jobs that lose their only machine go on hold, so a shorter makespan with fewer jobs is not an improvement; the report shows both.

**Commit** writes the scenario's net changes. Each scenario records the live values it read when an edit first touched an instance. If any value it changes has moved since, the commit is refused with the list of conflicts, so a scenario can never silently overwrite newer data. Committed writes count as changes, so automations fire.

**From the command line**, no server needed:

```bash
python -m autology scenario examples/order_fulfilment/ontology.json examples/order_fulfilment/data.json \
    examples/order_fulfilment/scenario.json
python -m autology scenario examples/scheduling/ontology.json examples/scheduling/data.json \
    examples/scheduling/scenario_breakdown.json --schedule
```

`--json` prints the full comparison and `--commit OUT.json` writes the data with the scenario applied.

**Through the API:**

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/scenarios?status=` | read | List scenarios |
| `POST /api/scenarios` | run | Create: `{"name", "edits": [...]}` |
| `GET /api/scenarios/{id}` | read | Edit results, net changes and conflicts with the live data |
| `POST /api/scenarios/{id}/edits` | run (owner or admin) | Add edits: `{"edits": [...]}` |
| `POST /api/scenarios/{id}/compare` | read | `{"checks": [...], "schedule": true}` |
| `POST /api/scenarios/{id}/commit` | admin | Write to the live graph and store. 409 on conflicts |
| `POST /api/scenarios/{id}/discard` | run (owner or admin) | Close without writing |

Access rules apply throughout:

- Edits that name a record the caller may not see are refused as if the record did not exist.
- Simulated actions and plans use a configured agent's roles (`"agent": "fulfilment"`) or the caller's own roles. Only admins may name arbitrary roles.
- Comparisons hide records, plan steps and blocking rules the caller may not see, and withhold aggregate answers that include hidden rows.
- Comparisons withhold the answer to any competency question that reads a field the caller may not read on some record (`"withheld: depends on Customer.credit_limit, which you may not read"`). Comparing two answers would otherwise reveal the hidden values. Questions that read a checkpoint-gated field are withheld for everyone, admins included, because a comparison takes no justification: ask the question directly with a reason (`POST /api/questions/{id}` with `{"justification": "..."}`).
- Edits that change a field the caller may not read are refused (403), on existing and on new records.
- The assistant's `what_if` tool also withholds answers that read fields the deployment does not send to the model provider (`chat_redact`).

A scenario is stored as its edits and replayed on the current live data each time it is read. If an edit no longer applies, for example because an instance it adds now exists, reading the scenario returns 409.

## Typed client libraries (Tier 2)

Applications talk to a deployment through a client generated from its ontology, so a typo in an entity, state, goal or question name is a compile error rather than a runtime surprise.

```bash
python -m autology sdk examples/order_fulfilment/ontology.json --lang python --out autology_client.py
python -m autology sdk examples/order_fulfilment/ontology.json --lang typescript --out autologyClient.ts
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8800/api/sdk/typescript > autologyClient.ts
```

Each client is a single file with no dependencies: the Python one uses only the standard library, the TypeScript one uses `fetch` (browsers, Node 18 or later, Deno, Bun). It contains:

- a type per entity for its attributes, with its states as a union of literals, and a type for the case shape agents accept;
- literal unions of entity, action, goal and competency-question names;
- typed helpers per entity (`list_order`, `get_order` / `listOrder`, `getOrder`), per question (`ask_cq_01` / `askCq01`) and per goal (`run_fulfil_contract` / `runFulfilContract`);
- a method for every REST endpoint, and an error type carrying the HTTP status.

```python
from autology_client import AutologyClient
api = AutologyClient("http://127.0.0.1:8800", token)
assert api.check_compatibility() is None          # the server runs the ontology this client was built from
for order in api.list_order():
    print(order["id"], order["attributes"]["status"])   # status is typed: 'received' | 'credit_checked' | ...
run = api.run_fulfil_contract(case, case_id="K-42")
```

```typescript
import { AutologyClient } from "./autologyClient.ts";
const api = new AutologyClient("http://127.0.0.1:8800", token);
const orders = await api.listOrder();               // OrderObject[]
const run = await api.runFulfilContract(caseData, { caseId: "K-42" });
```

Fields a data-access rule hides arrive as `"***redacted***"`, and the attribute types include that value. Every client carries the fingerprint of the ontology it was generated from. `check_compatibility()` / `checkCompatibility()` compares it with the server's and describes any drift, so a CI job can fail when a client needs regenerating. A typed helper whose name would clash with an endpoint method gets a suffix, for example `get_run_object` for an entity called `Run`.

The generated code passes `mypy --strict` and `tsc --strict --erasableSyntaxOnly` for every example ontology.

## Governed assistant (Tier 2)

The inbox's **Assistant** tab, and `POST /api/chat`, give people a conversational way into the deployment. The assistant is a language model with tools, and the tools are the API itself, called as the signed-in person:

| Tool | Offered to | Does |
|---|---|---|
| `describe_ontology`, `list_objects`, `get_object`, `ask_question` | read | Explore the ontology and the knowledge graph |
| `list_runs`, `get_run`, `list_notifications` | read | Explain runs: steps, the rules behind each decision, escalations |
| `list_reviews` | review | Explain the reviews waiting for the person |
| `start_run` | run | *Propose* a governed run on graph data with a case template. Nothing runs until the person confirms |
| `what_if` | run | Simulate changes in a scenario and compare. Never commits |

What keeps it safe:

- **It acts as the person.** Every tool call goes through the same permission, row-access and field-access checks as an API request by that person, so the model never receives a record or value the person may not see.
- **Tools follow permissions.** A user without `run` is not offered `start_run` or `what_if`, and so on.
- **It cannot decide reviews.** There is no tool for it. The assistant explains what is waiting and points to the Reviews tab, where a person decides.
- **It proposes runs; the person starts them.** A run changes data (write-back), so the assistant's `start_run` only records a proposal. The person confirms or declines it in the Assistant tab or with `POST /api/proposals/{id}/decision` `{"confirm": true}`. Only that person can, once. A confirmed proposal is an ordinary governed run started by them: rules, reviews, checkpoints, write-back and audit all apply.
- **Confidential data stays on the server.** Tool results are scrubbed before they are sent to the model provider, whatever the user may see: attribute values, case states, review facts, scenario diffs and facts in free text. By default every attribute marked `"sensitivity": "confidential"` is withheld. `"chat_redact": {"sensitivities": [...], "fields": ["Entity.attr"]}` in the server config changes the list. Questions that filter or aggregate on such a field are refused to the assistant.
- **Failures are soft.** Any backend failure, such as missing credentials, an SDK that rejects a parameter or a dropped connection, gives the "assistant is unavailable" reply, and the details go to the server log.
- **Everything is recorded.** Each tool call goes to the access log, and conversations are stored per owner. Nobody else can read them through the API.

```jsonc
"chat": {"model": "claude-opus-5-5", "effort": "medium"}     // Claude through the anthropic package
"chat": {"backend": "my_module:factory"}                       // any object with turn(system, messages, tools)
```

With Claude, the backend runs the tool loop with the official SDK. It uses prompt caching on the system prompt, strict tool schemas where the parameters allow it, and the server-side refusal fallback. Thinking blocks go back to the model unchanged. If the `anthropic` package or credentials are missing, the server still starts and the assistant answers that it is unavailable. `ScriptedChatBackend` drives the same loop from a plain function, for tests, demos or another provider.

| Method and path | Permission | Purpose |
|---|---|---|
| `POST /api/chat` | read | `{"message", "chat_id"}`. Returns the reply, the tools used and token usage |
| `GET /api/chat/{id}` | read (owner) | The conversation's readable turns |
| `GET /api/proposals` | read | The caller's run proposals from the assistant |
| `POST /api/proposals/{id}/decision` | run (owner) | `{"confirm": true/false, "justification": "..."}`: start the proposed run, or decline it |

## One path to a language model (AI-1)

`autology/ai.py` is the single path a request to a language model takes, whatever the provider. Nothing is
configured by default. The AI Architect route uses it when a use case's configuration enables a provider (below).

```python
from autology.ai import AnthropicProvider, ChatCompletionsProvider, ModelGateway, ModelRequest, WorkspaceAI

gateway = ModelGateway(
    {"claude": AnthropicProvider(), "local": ChatCompletionsProvider("http://127.0.0.1:8080/v1")},
    {"acme": WorkspaceAI("local", "some-model")})          # explicit, per workspace
answer = gateway.invoke(ModelRequest(
    workspace="acme", purpose="demo", system="Classify the note.", prompt="Is it urgent?",
    data={"note": "..."},                                  # untrusted content, kept apart from the instructions
    schema={"type": "object", "properties": {"urgent": {"type": "boolean"}}, "required": ["urgent"],
            "additionalProperties": False},
    data_classes=("synthetic",), deadline_seconds=20))
answer.data, answer.usage, answer.cost_usd
```

| Concern | Where it is decided |
|---|---|
| Provider and model | The workspace's `WorkspaceAI`. A workspace without one gets `not_configured`; one workspace never uses another's provider, answers or accounting |
| What may be sent | A request declares its data classes (`synthetic`, `model_design`, `business_records`, `personal_data`); the workspace lists those it allows, `synthetic` only by default (owner decisions D7, D10). The declaration is made by the calling code; it is not content inspection |
| Form of the answer | The request's JSON Schema, checked by the gateway (`autology/schema.py`). Not JSON, not an object, a missing, mistyped or extra field: `invalid_response` |
| Tools | None are ever offered. A reply that asks for one is refused (`tool_request`) |
| Time | One deadline for the whole request, retries included, enforced by the gateway (an adapter that hangs cannot hold the caller); a caller can cancel. A late answer is discarded |
| Failures | `ProviderError.kind`: `rate_limited` and `unavailable` are retried (at most `max_attempts`, never past the deadline); `auth`, `invalid_request`, `refused`, `truncated`, `timeout`, `cancelled`, `failed` are not. `uncertain` says the provider may have processed the call anyway: its usage is then unknown |
| Repeats | A request id: repeating a request that succeeded returns the recorded answer; the same id with other content is refused; the id is sent as an idempotency key where the protocol has one |
| Accounting | Tokens, cost (registered prices) and unpriced tokens per workspace: `gateway.usage(workspace)` |
| Logs | One event per attempt on the `autology.ai` logger: outcome, duration, counts and the size of the prompt. Never the prompt, the data, the answer or a credential |

**The answer is untrusted, whichever provider produced it.** The gateway returns data; it writes no record,
activates no release and calls no business system. An agent's reasoner can use the gateway
(`GatewayChatModel(gateway, workspace, data_classes)`); governance then re-evaluates the model's choice exactly as
before ([security notes](#security-notes)), and any failure makes the agent follow its
plan.

**AI Architect proposals.** `autology.architect.propose(gateway, workspace, brief, document, sources, answers)`
asks a provider for additions to a model document: entities with properties and states, relationships, actions
with preconditions, rules, goals, clarification questions (each with an id, so that answers can come back),
assumptions, unknowns, sources, a confidence per item, and descriptions of the roles, agents and integrations the
solution would involve. The form of the answer has no place for permissions, grants, settings or tools. A proposal
only adds: an item named like something the model already contains is rejected. Every item is validated by the
engine's strict loader on the current model plus the proposed items; what the loader refuses is returned under
`rejected` with its message.

**Through the versioned API.** `POST /api/v1/architect/proposals` with `"generator": "model"` runs that path and
**stores the result as a revision** (who asked, the brief, the answers, provider and model, assumptions, rejected
items, validation). `{"revises": id, "answers": [...]}` stores the next revision; nothing is overwritten.
`POST .../proposals/{id}/decision` records which items a person accepted or rejected. None of this changes a
model: accepted items reach a draft only when a person with `configure` saves one, and a draft becomes active only
through an approved release.

**Which provider.** An engine has an architect provider only if its configuration says so:
`"ai": {"provider": "sandbox"}`. `sandbox` is a deterministic test double built on approved templates
(`autology/sandbox_ai.py`): it contacts nothing, holds no credential, and its proposals are labelled
`"ai": false`, generator `sandbox`. **An engine on its own accepts no other value.** The templates it knows are
Autology's own (three, in `autology/blueprints`) and those in the folders the use case's configuration names with
`"blueprints": "folder"` (or a list of folders, relative to the configuration). A domain's templates are thus
configuration of the use case that names them: no other use case sees them, the setting is part of a release's
governing settings, and a brief that matches no template gets a question, not a guess. See
`examples/domains/` for two packs built this way. Under a platform, a use case
may name a real provider with its exact model and the policy terms it is configured under
(`"ai": {"provider", "model", "policy", "data_classes", "content"}`); it is served only while the workspace has
an approved policy for that provider, model and terms, the owner's authorisation covers it, the key is installed
and the budget allows the call. The setting is governing, so every release names the model it may ask. The whole
procedure, the key included, is in [ai-provider-activation.md](ai-provider-activation.md); the acceptance criteria
are in the [evaluation protocol](../planning/AUTOLOGY_AI_PROVIDER_EVALUATION_PROTOCOL.md).

**What this is not.** The adapters are tested against a double of the SDK client, a local mock endpoint and, for
the Anthropic adapter, the official SDK itself over a local transport. The Anthropic adapter has also been used
with its provider once, on synthetic data, under one owner authorisation (17 November 2026: 24 answers from
`claude-opus-5-5`; the architect's evaluation **did not meet its thresholds**;
[report](../planning/AUTOLOGY_FIRST_REAL_CLAUDE_EVALUATION_REPORT.md)). The other adapter has met no provider. No
test contacts a provider. Connecting a provider and sending anything but synthetic data are owner decisions
(D7, D10).

**The answer's contract with a real provider.** The provider is asked to hold the answer to the request's schema.
When it refuses to compile that schema (the architect's contract is refused as too large), the adapter sends the
request once more with the schema written into the instructions. Either way the gateway checks the answer against
the contract and refuses, whole, an answer that does not keep it: such an answer has been paid for.

### What the architect keeps, and how a design session is resumed

Every proposal and every revision is stored by the engine, append-only: the brief, the answers, the elements with
their reasons, what the engine refused, the review decisions, and **who generated the revision** (the provider and
the exact model; a test double is said to be one). `GET /api/architect/proposals` lists them with what the
session already cost and the drafts saved from it; `GET /api/architect/proposals/{id}?revision=n` reads any
revision again. Reading asks no model and costs nothing: a person can leave and come back.

**Provenance.** Each element says what it rests on: `evidence` (canonical references: `brief`,
`answer:<question id>`, the id of a passage that was given) and `origin` in one word: `brief`, `answers`,
`sources`, `several`, `inference` (the architect's own reading), or `unknown` (presented as supplied, with nothing
that was given behind it). A reference is never guessed. `source_index` gives the text behind each reference (an
answer with the question it answered). A draft saved from a proposal records that revision
(`"origin": {"proposal", "revision"}`, checked by the engine), and a release names the draft it was published
from and the proposal behind it (`design`). Studio shows it as "Why was this proposed?".

**Workflow consistency.** Beside validation, `POST /api/model/validate` and the draft return `consistency`:
potential inconsistencies the engine found by reading the model (a goal nothing leads to; a case that can be
completed while something it owns is unsettled; an action that can never start; an obligation that can never be
met; an action always prohibited; an outside effect no rule names; a state never reached). Each says why it may
matter and what a person could do, including "leave it: this is intended". Nothing is changed and nothing is
blocked by a finding.

## Access log (Tier 2)

Every API request, except the health check and the inbox's static files, is written to an `access_log` table: time, who (or `-` when sign-in failed), method and path, and the response status. Assistant tool calls are logged the same way. Database triggers reject any UPDATE or DELETE. As with the audit log's triggers, this guards against mistakes, not against someone with direct database access.

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/access-log?principal=&limit=` | audit | Newest entries first |

## Checkpoints (Tier 2)

A `checkpoint` rule makes a person write down why before a sensitive operation. The reason is stored in a `justifications` table that rejects updates and deletes, with who, when and on what.

```jsonc
{"id": "CP-CREDIT", "type": "checkpoint", "on": "read_field", "field": "Customer.credit_limit", "min_length": 15,
 "description": "Credit limits are commercially sensitive. Say why you need to see them."},
{"id": "CP-DECLINE", "type": "checkpoint", "on": "decide", "action": "ship_order", "approved": false, "min_length": 15,
 "description": "Declining a shipment stops the order. Record the reason for the customer file."}
```

| `on` | Filters | Where the justification goes |
|---|---|---|
| `read_field` | `field` (required) | `?justification=` on `GET /api/objects` and `/api/objects/{id}`. Without it the field reads `"***justification required***"` |
| `start_run` | `goal` | `"justification"` in the request body |
| `resume_run` | — | `"justification"` in the body |
| `decide` | `action`, `approved` | `"justification"`, or the review `comment` |
| `upsert_object` | `entity` | `"justification"` in the body |
| `commit_scenario` | — | `"justification"` in the body |

- **Missing or too short.** The API answers `428 Precondition Required` with `{"checkpoint": {"rules", "prompt", "min_length"}}` and does nothing. The inbox asks the person and retries.
- **Order of checks.** Checkpoints come after access rules: a justification never reveals a field that a `data_access` rule hides from the person.
- **Admins** are asked too.
- **The assistant cannot justify for anyone.** Its tools never pass a justification, so a checkpointed operation fails there and the person has to act in the inbox.
- `GET /api/justifications` (audit permission) lists the record, newest first.

## Interfaces (Tier 2)

An interface is a shape that several entity types share:

```jsonc
"interfaces": {"Regional": {"description": "Anything that belongs to a sales region", "attributes": {"region": "string"}}},
"entities": {"Customer": {"implements": ["Regional"], ...}, "Order": {"implements": ["Regional"], ...}}
```

- **Validation.** Every implementer must have each interface attribute with the same type. An interface may not share a name with an entity.
- **Questions and listings** can address the interface. `{"find": "Regional", "where": "Regional.region == 'EU'"}` covers customers and orders alike, and `GET /api/objects?type=Regional` lists both. Row and field access still apply per record.
- **Generated clients** get a type per interface (the union of its implementers' object types) and a `list_regional` / `listRegional` helper.
- **Versioning.** `autology diff` reports interfaces added or removed and entities that stop implementing one, and treats a new interface attribute as breaking.
- **Not yet supported:** rules name concrete entity types, not interfaces.

## Tracing (Tier 2)

Each run's audit log can be exported as OpenTelemetry traces, so runs appear in Jaeger, Grafana Tempo, Honeycomb, Datadog or any OTLP collector:

- one trace per run; resumed runs stay in the same trace;
- a span per step, with the verdict, the rules that decided it, who proposed and executed it, the model and its cost, and the outcome;
- tool calls as child spans; tool failures, declined reviews, governance denials and failed runs marked as errors;
- reviews and deferrals as span events.

Spans carry identifiers, rule ids and outcomes only, never case data or the facts behind a decision. Span ids are derived from the run, so exporting a run twice produces the same spans.

```bash
python -m autology trace --db autology.db --endpoint http://localhost:4318/v1/traces
python -m autology trace runs.jsonl --out traces.json
```

- **Automatic export.** With `"tracing": {"endpoint": "...", "headers": {"x-api-key-env": "OTLP_KEY"}}` in the server config, each run is exported when it reaches a final status. A header ending in `-env` takes its value from that environment variable.
- **Over the API,** `GET /api/runs/{id}/trace` (audit permission) returns the OTLP/JSON payload.

## MCP interface

The same ontology can be used from any Model Context Protocol client, such as Claude Desktop or Claude Code. The MCP server runs over stdio, needs only the standard library, and signs in as one user with that user's API token:

```jsonc
{"mcpServers": {"autology": {"command": "python", "args": ["-m", "autology", "mcp", "/path/to/server.json"],
                             "env": {"AUTOLOGY_TOKEN": "atl_...", "AUTOLOGY_AUDIT_KEY": "..."}}}}
```

It offers exactly the governed assistant's tools, with the same guarantees:

- calls run as that user, with their permissions and row and field access;
- `start_run` only records a proposal, which the person confirms in the inbox;
- nothing decides a human review;
- values withheld from model providers (`chat_redact`, confidential by default) are withheld here too;
- every call is written to the access log as `mcp.tool`.

The server was checked against the official MCP Python SDK: handshake, tool listing and tool calls.
