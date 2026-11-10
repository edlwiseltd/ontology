# Running Autology as a shared service

Tier 1 makes Autology usable by many projects and people at once. It adds five things (Tier 2 additions follow in later sections):

| Capability | What it gives you | Module |
|---|---|---|
| **Multiple records per case** | One case can hold many orders, lines or shipments. Actions run once per record, and rules and access apply per record | `state.py`, `planner.py`, `governance.py` |
| **Row-level access** | Records can be hidden from people and agents without the right role, such as EU orders visible to EU staff only | `governance.py` (`row_access` rule) |
| **Persistent store** | The knowledge graph, every run, an append-only audit log and review decisions survive restarts | `store.py` (SQLite) |
| **Asynchronous reviews** | A run pauses at a human review and resumes when someone decides, possibly hours later and after a restart | `agent.py` (`DeferredApprover`, `resume`) |
| **REST API and web inbox** | Token authentication, per-user permissions and data access, plus a browser inbox for reviews and monitoring | `server.py`, `static/` |

The core still needs no third-party dependencies. The store uses SQLite and the server uses `http.server`, both from the Python standard library.

## Quick start

```bash
cd examples/order_fulfilment
export AUTOLOGY_TOKEN_OLIVIA=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export AUTOLOGY_TOKEN_LENA=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export AUTOLOGY_TOKEN_AUDREY=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
export AUTOLOGY_TOKEN_ADMIN=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
echo "olivia: $AUTOLOGY_TOKEN_OLIVIA   lena: $AUTOLOGY_TOKEN_LENA"
python -m autology serve server.json --port 8800
```

Open `http://127.0.0.1:8800`, sign in with Olivia's token, and start a run from **Start a run**, pasting `case.json`. The run pauses because order O-4 is worth more than 50,000. Sign in as Lena, who holds the logistics-manager reviewer role: the review is in her inbox with the rule, the facts and the history. Approve it and the run completes.

The example has four users, each showing a different access level:

| User | Permissions | Data roles | Sees |
|---|---|---|---|
| olivia | read, run | ops | 2 of 3 orders: the EU order is hidden; credit limits are redacted |
| lena | read, review | ops, eu_ops | all orders; can decide logistics reviews |
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

## Row-level access

A `row_access` rule hides the records of an entity matching its `when` condition from anyone without one of its `roles`:

- **Agents:** hidden records are left out of the agent's view, its LLM prompts and its review requests. Actions on them are denied, and if the goal needs them the run escalates, naming the rule.
- **API users:** hidden records are absent from listings, and fetching one returns 404, so its existence isn't revealed. A competency question that would aggregate over hidden records is refused.
- **Field rules still apply on top:** `data_access` redacts individual fields.

## Persistent store

```python
from autology.store import Store
store = Store("autology.db")
store.save_graph(graph); graph = store.load_graph(ontology)
run_id = store.save_run(result, agent="fulfilment"); result = store.load_run(run_id)
```

- **The audit log is append-only.** Database triggers reject any UPDATE or DELETE on audit rows. Saving a run appends only its new entries, and refuses if the stored history and the run's history diverge, or if the run's own hash chain doesn't verify.
- **Loaded runs** rebuild their audit trail from the append-only table, not from the run record.
- **The CLI** writes to and reads from a store with `--db`: `autology run ... --db autology.db`, `autology report ONTOLOGY --db autology.db`, `autology score ONTOLOGY --db autology.db`.
- **Scale:** SQLite suits one server and pilots. File databases use WAL mode, and a lock makes the store thread-safe. The `Store` interface is small, so a PostgreSQL implementation is the path to larger deployments.

## Asynchronous reviews

`DeferredApprover` never decides inline. When governance requires a human review, the run stops with status `awaiting_review` and records exactly which action is waiting. Later, possibly in another process:

```python
result = agent.resume(stored_result, decision=ReviewDecision(True, "lena", "carrier confirmed"))
```

The decision applies to exactly the action that was waiting. The reviewer's identity and comment go into the audit trail. Reporting counts parked runs as *pending*, not as failures.

## REST API

Every request needs `Authorization: Bearer <token>`, except `/api/health` and the inbox's static files.

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/me` | any | Who am I, with permissions and roles |
| `GET /api/ontology` | read | Entities, actions, goals, rules, questions, agents |
| `GET /api/objects?type=&limit=&offset=` | read | Objects, row- and field-filtered for the caller |
| `GET /api/objects/{id}` | read | One object with its visible links |
| `POST /api/objects` | admin | Create or update an object and its outgoing links, validated against the ontology |
| `POST /api/questions/{id}` | read | Answer a competency question, with `{"params": {...}}` |
| `POST /api/runs` | run | Start a run: `{"agent", "goal", "case", "case_id"}` |
| `GET /api/runs?status=` | read | List runs |
| `GET /api/runs/{id}` | read | Steps, status, escalation, the caller's view of the state, audit verification |
| `GET /api/runs/{id}/audit` | audit | Raw audit entries |
| `POST /api/runs/{id}/resume` | run | Resume a deferred or paused run (`{"force": true}` skips the retry window) |
| `GET /api/reviews?status=pending` | review | Reviews the caller may decide |
| `GET /api/reviews/{id}` | read | One review |
| `POST /api/reviews/{id}/decision` | review | `{"approved": true/false, "comment": "..."}`. Resumes the run, and can be decided once only |
| `GET /api/report` | read | Compliance report (markdown) |
| `GET /api/score` | read | Readiness scorecard over all stored runs |

**Permissions:**

| Permission | Allows |
|---|---|
| `read` | Ontology, objects, runs, reports |
| `run` | Starting and resuming runs |
| `review` | Deciding reviews for the user's `reviewer_roles` |
| `audit` | Raw audit entries |
| `admin` | Everything |

A user's `roles` are ontology roles, and the row and field rules apply to everything returned to them.

### Security notes

- **Tokens.** Generate them with `python -m autology token`. Only SHA-256 hashes go in the config, or tokens come from environment variables (`token_env`). Comparison is constant-time.
- **Network.** The server binds to `127.0.0.1` by default. Put it behind a reverse proxy with TLS before exposing it.
- **Requests.** Bodies are limited to 1 MB. Errors never include tracebacks.
- **The inbox** is served with a strict Content-Security-Policy (`script-src 'self'`, no inline scripts). It inserts data as text only, and keeps the token in the browser tab's session storage.
- **Concurrency.** Runs are serialised per agent, so governance counters such as suspensions stay consistent.

### Not yet included

- single sign-on (OIDC or SAML);
- token rotation and expiry;
- rate limiting;
- multi-tenant separation within one server;
- a PostgreSQL store.

## Automations and notifications (Tier 2)

Automations start work when the knowledge graph changes, instead of waiting for someone to call an agent. They are deployment configuration, so they live in the server config and are validated against the ontology and the configured agents at start-up.

```jsonc
"automations": {
  "fulfil_signed_contracts": {
    "entity": "Contract", "when": "Contract.status == 'signed'", "trigger": "change",
    "run": {"agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case"},
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

**Triggers:**

| Trigger | Fires |
|---|---|
| `"change"` (default) | Once when the condition *becomes* true for an instance. It fires again only after the condition has been false in between. Checked on every API write, every write-back from a run, and every scheduled tick, so conditions on `Params.now` (epoch seconds) work as deadlines. Which instances have fired is stored, so a restart does not fire everything again |
| `{"every": seconds}` | On ticks, for every instance where the condition holds, at most once per interval per instance |

A condition refers to the automation's entity only, plus `Params.now`. When a change automation is first switched on, it fires for every instance where its condition already holds.

**Runs on graph data.** A `run` assembles its case from the graph with a *case template* declared in the ontology:

```jsonc
"case_templates": {
  "contract_case": {"root": "Contract",
                    "entities": {"Contract": "self", "Customer": "^hasContract", "Order": "covers"}}
}
```

Each entity is reached from the root instance by a relationship path (`^` follows a link backwards). Multi-record entities take every instance reached; others take the first. The run is governed like any other: rules, reviews, row access and audit all apply. With `write_back` (on by default), the run's resulting state is written back to the instances the case came from, after every step that is saved, including after a review is decided later. Write-backs count as changes, so one automation can trigger the next. A pass stops after 200 firings to guard against loops.

People can start the same kind of run from the API: `POST /api/runs` with `{"case_template": "contract_case", "root": "K-1"}` instead of `case`.

**Notifications** go to everyone holding one of the listed roles (data roles or reviewer roles). A notification is recorded whenever a review is opened, addressed to its reviewer roles, and whenever an automation with `notify` fires. Notifications about a record are hidden from people who may not see that record, so message text cannot leak a hidden row. Each notification is also POSTed as JSON (`{"autology": {...}}`) to every configured webhook whose `kinds` match, on a background thread, best effort. The stored notification is the record of truth.

**The scheduler.** `autology serve` ticks every `automation_interval` seconds. A tick resumes deferred runs whose retry time has come, then evaluates every automation. Admins can also tick by hand.

| Method and path | Permission | Purpose |
|---|---|---|
| `GET /api/automations` | read | Automations with their recent firings and the current status of the runs they started |
| `POST /api/automations/{name}/run` | run | Fire now: `{"instance": "K-1"}` for one instance (even if the condition is false), or `{}` for every instance where it holds |
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

A scenario is stored as its edits and replayed on the current live data each time it is read. If an edit no longer applies, for example because an instance it adds now exists, reading the scenario returns 409.
