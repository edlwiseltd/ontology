# Reference demonstration: from a business description to governed, stored simulation runs

**Supplier disruption and operational decision** — an industry-neutral scenario on synthetic data, done entirely
in Studio: no command line after the two start commands, no configuration file edited by hand.

> "A critical supplier has delayed a delivery. Evaluate the operational impact, compare available alternatives and
> select an authorized response."

What it is, plainly:

* The proposal comes from the **sandbox architect**, a deterministic test double that fills an approved template.
  **It is not a language model.** A description outside the templates' vocabulary gets a question back, not a
  solution; free natural-language briefs need a real provider, which waits for the owner (D7, D10).
* Every tool is **simulated**: it answers from a table inside Autology and contacts nothing. A completed run shows
  that the governed flow works; it is **not evidence that any real system was changed**.
* **Production is not available.** The runs happen in the Simulation stage.
* The scenario is a template (`autology/blueprints/supplier_disruption.json`): the model, a starting agent
  configuration and synthetic sample records. Nothing about it is built into the engine.

## Start it

```bash
export AUTOLOGY_AUDIT_KEY=demo-key ACME_TOKEN_ADA=acme-ada ACME_TOKEN_HANA=acme-hana ACME_TOKEN_IVAN=acme-ivan \
       ACME_TOKEN_MARIA=acme-maria ACME_TOKEN_OLIVIA=acme-olivia ACME_TOKEN_LENA=acme-lena \
       NORTHWIND_TOKEN_NADIA=nw-nadia NORTHWIND_TOKEN_HANA=nw-hana
python -m autology platform examples/platform/platform.json --port 8700
# in another terminal
cd studio/web && npm ci && npm run build
AUTOLOGY_PLATFORM_URL=http://127.0.0.1:8700 npm start          # Studio on http://127.0.0.1:8960
```

The tokens are demonstration values for a local machine. Four people take part, because governance needs more
than one: **Ada** (`acme-ada`, workspace administrator, designs), **Maria** (`acme-maria`, release approver),
**Hana** (`acme-hana`, runs the simulation) and **Lena** (`acme-lena`, reviewer). Use a separate browser window
or private window per person.

The same journey is scripted in the browser checks (`cd studio/web && npm run build && e2e/run.sh`, section 6 of
`e2e/run.mjs`; screenshots `e2e/screenshots/demo-*.png`) and through the API in
`tests/test_act3_persistent_simulation.py` and `tests/test_act4_readiness_subjects.py`.

## Walk through it

The **Onboarding** tab is one flow of nine steps. Each step can also be reached from its own tab.

| # | Step | Who | What to do | What you see |
|---|---|---|---|---|
| — | Create the use case | Ada | **New** → template *Blank solution (guided onboarding)* → identifier `supply` → **Create in Draft**; open it; **Onboarding** | An empty model, stage Draft |
| 1 | Describe | Ada | Paste the description above → **Propose a solution** | A stored proposal, labelled *Sandbox architect · test double · not a language model* |
| 2 | Questions | Ada | Read *What the architect understood* (the sandbox says it matched a template). Answer the five questions (major delay in days, cost above which a person approves expediting, approver role, planner role, order system) → **Update the proposal with my answers** | A new revision of the proposal; the earlier one is kept |
| 3 | Review | Ada | Read the graph (Supplier, Delivery, Alternative), the workflow, the rules; each element says whether it is *from your description* or *inferred*; optionally **Ask for a revised proposal** in your own words; untick what you do not want → **Validate my selection with the engine** | Proposed items drawn dashed; the prohibition "switch_supplier is prohibited when Supplier.exclusive == True" among the rules |
| 4 | Confirm | Ada | **Save … as a draft** → **Configure agents and tools** | "Draft revision n saved. It is not active" |
| 5 | Agents & tools | Ada | **Suggest a starting configuration** → look at each action's verdict → adjust if you wish → **Save the draft configuration** | One agent, five simulated tools, twelve synthetic records; per action: *acts on its own*, *depends on the case*, *a person decides*, with the rule that says so; connectors and model reasoners listed as unavailable |
| 6 | Dry run (optional) | Ada | **Run the simulation** | One synthetic case with stub tools; nothing stored |
| 7 | Release | Maria, then Ada, Maria, Ada | Maria (Releases tab of the use case, or the API): **Publish draft revision n**. Ada: **Propose release**. Maria: **Approve**. Ada: **Contents** to inspect, then **Activate**; then *Change stage* → **Simulation** → **Record the move** | The author cannot publish, the proposer cannot approve. *Contents* lists model, rules, actions, workflows, agents (*configured in Studio*), tools (*all simulated*), settings, each with a fingerprint, and the engine's verdict *Coherent* |
| — | Load the sample records | Ada | Step 7, card *Sample records*: type a reason → **Load the sample records** | A release brings no data with it. The twelve synthetic records are loaded only now, on Ada's recorded request, and marked as samples |
| — | Give access | Ada, then Maria | **Access** → *Request grant*: Hana on `supply` with `read`, `run`, `audit` and role `supply_planner`; Lena with `read`, `review` and reviewer role `operations_manager`. Maria approves both | A grant never takes effect on one person's say-so |
| 8 | Stored runs | Hana, Lena | Hana, tab **Simulation runs**: start a run per record (table below). Lena opens the waiting run and decides | Timeline, policy checks, simulated effects, the stored records, the signed audit chain |
| 9 | Readiness | Ada | **Readiness**: assess *what runs now*; **Rehearse a recovery now** (a reason is required); change the agent to *Supervised* in step 5 and save; assess *the saved draft* | Each report names its subject and configuration; recovery evidence is missing until a rehearsal succeeds, then recorded for the configuration that runs; the draft lacks execution evidence and a release; the differences are listed |

### The five sample deliveries

| Record | What happens | What it shows |
|---|---|---|
| `DEL-1001` (2 days late) | assess → compare → **accept_delay**, completed, no reviewer | An action the policy authorises is taken by the agent on its own: no unnecessary review |
| `DEL-1005` (8 days, expedite costs 2,500) | … → **expedite_shipment**, completed, no reviewer | Below the approval threshold the agent may expedite |
| `DEL-1002` (9 days, expedite costs 8,000) | … → waits for `operations_manager`. Hana cannot decide her own run. Lena **approves** → completed, "decided by lena" | A required approval is enforced, and given by an authorised person |
| `DEL-1003` (exclusive supplier, an alternative exists) | **escalated at once**: "switch_supplier: prohibited: A supplier under an exclusivity agreement is never replaced"; no step executed | A prohibited action is refused by policy, before anything is done |
| `DEL-1004` (synthetic outage switch) | assess → compare fails three times → escalated with the simulated error | Deterministic failure injection: the failure is retried, recorded and reported |

Also try: **Cancel the run** on a waiting run (a reason is required; the cancellation joins the audit chain, the
review is closed and the record is free for a new run); **Refuse** as Lena (the action is not performed);
starting a second run on a record that already has an open one (refused); restarting the platform (the runs are
still there, and a waiting one continues after its review).

## What is real and what is simulated

| Real (the engine's own mechanisms) | Simulated |
|---|---|
| Validation of the model and of the agent configuration | The architect (a test double, not a language model) |
| Draft revisions, publication by a second person, release approval, activation, rollback | Every tool: a decision table inside Autology |
| Stage gates (Draft refuses runs; Production is always refused) | The records: synthetic sample data |
| Run lifecycle: stored state, reviews, cancellation, retries, one open run per record | The "expedite", "switch" and "accept" effects: field changes on synthetic records only |
| Authorisation by permission, role, reviewer role; separation of duties | |
| Signed audit chain per run; signed release history and administration log | |
| Readiness conditions and scores (weights provisional, decision D26) | |

## Limits you will meet

* Two templates exist (service request, supplier disruption). Anything else gets a clarification question.
* The agent panel edits conditions and outcomes of a decision table; rows that write fields are kept but not
  editable there.
* Readiness of a draft or of a waiting release is measured on a throwaway engine: it has no runs, so execution
  evidence is reported as missing. That is intended.
* The architect is still the sandbox: onboarding says so, and says that it matched a template by its words rather
  understood your text. A workspace reaches a real provider only with an approved policy that the owner's
  authorisation covers; none exists.
* No timing with real users has been measured. The scripted journey takes about five seconds; that says nothing
  about a person.
