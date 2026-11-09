# Autology: Ontology × Agent

A reference implementation of **ontology-driven workflow automation**. Business knowledge (entities, actions, rules) lives in one immutable **ontology**. **AI agents** work out how to reach a goal at run time. A **governance layer** makes sure they never skip a mandatory step, never read data they aren't entitled to, and hand critical decisions to humans.

It is **agnostic** in three ways:

- **Domain:** the framework knows no business vocabulary. Your ontology supplies it.
- **Model:** any LLM plugs in through a small `ChatModel` interface. Claude is the default adapter.
- **Systems:** tools are Python callables, HTTP services or declarative decision tables, wired up in a JSON config.

> Concept paper: [`docs/autology.md`](docs/autology.md) · Engineering methodology mapped to the code: [`docs/methodology.md`](docs/methodology.md)

```
            goal + case facts
                    │
   ┌────────────────▼─────────────────┐
   │          AI agent layer          │  WorkAgent: observe → plan → reason → govern → act → re-plan
   │  ┌───────────┐   ┌────────────┐  │
   │  │  Planner  │──▶│  Reasoner  │  │  deterministic, or any LLM choosing among valid moves
   │  └─────▲─────┘   └─────┬──────┘  │
   └────────┼───────────────┼─────────┘
            │      proposal │
   ┌────────┴──────┐ ┌──────▼─────────────┐    ┌───────────────────┐
   │ Ontology layer│ │  Governance layer  │──▶ │ human review gate │  policy file, console or HTTP
   │ entities      │ │ mandatory steps    │    └───────────────────┘
   │ actions       │─▶ prohibitions       │
   │ goals, rules  │ │ read/write/action  │──▶ hash-chained audit log → saved runs → report, score
   └───────────────┘ └──────┬─────────────┘
                            │ allowed
                  ┌─────────▼─────────┐
                  │   Tool registry   │  capability → context-selected tool (Python, HTTP, decision table)
                  └───────────────────┘
```

## Readiness of the three example deployments

Each example is a different domain. Each is run end to end through the generic CLI on a reproducible pilot batch that includes simulated tool outages, then scored. `tests/test_readiness.py` keeps every one at **95 or above with 100% of the evidence assessed**.

| Example | Domain | Code needed | Pilot | Score | Pilot gate |
|---|---|---|---|---|---|
| `customer_onboarding` | B2B onboarding (KYC, contracts, billing) | tool handlers | 120 cases | **100 (A)** | passed (ROI 1140%) |
| `manufacturing` | supplier contracting, production, quality | tool handlers | 150 contracts | **100 (A)** | passed (ROI 354%) |
| `care_referral` | healthcare referrals (consent, triage, booking) | **none**: decision tables | 100 patients | **96 (A)** | open: 4 entities (needs 5), ROI 91% |

ROI figures use the illustrative cost assumptions in each example's TCO file. Only the intervention rate and the tool and LLM cost per task are measured from the runs. The care-referral pilot gate is honestly open: the deployment is well built, but its business case is weak under those assumptions. The roadmap gates exist to show exactly that difference.

## What's in the box

| Area | Capability | Module |
|---|---|---|
| Ontology engineering | Entities, relationships, actions, goals, rules; validated, frozen, fingerprinted | `ontology.py` |
| | Modules via `imports`; externally set states; competency questions over a typed knowledge graph | `ontology.py`, `graph.py` |
| | Lint (security by design, bias hints, dead states, tool coverage); OWL/Turtle and JSON-LD export | `lint.py`, `export.py` |
| | Semantic diff, semver enforcement, publishing registry, version pinning | `versioning.py` |
| Agent orchestration | Run-time planning, including routes that need a non-default outcome | `planner.py` |
| | Self-healing: retry the cheap tool first (`fallback_after`), fallback tools, backoff, defer and resume, escalate | `agent.py` |
| | Cost-aware tool selection, allow-lists, multi-agent delegation, context-rich reviews, provenance | `agent.py`, `tools.py` |
| Governance | Mandatory steps, prohibitions, read/write/action access (ABAC), human review, suspension, fail-safe pause | `governance.py` |
| | Hash-chained audit, compliance report, outcome classes (completed / policy stop / unplanned), gap analysis | `audit.py`, `reporting.py` |
| Agnostic integration | `ChatModel` interface (Anthropic adapter, `FunctionChatModel` for any other model); `register_price` | `reasoners.py` |
| | Declarative tools (`python`, `http`, `table`), approvers (`policy` with conditions, `http`), reasoners | `adapters.py` |
| | Saved runs (JSONL) with intact hash chains, resumable in another process | `persistence.py` |
| Cost | Model routing (none / small / large), decision cache, prompt caching, token cost; TCO/ROI from measured rates | `reasoners.py`, `economics.py` |
| Readiness | Scorecard 0–100 (A–F), evidence coverage, roadmap gates, fixes ranked by points recovered | `scoring.py` |

## Quick start

Requires Python 3.10 or later. No dependencies (`anthropic` is optional, for Claude).

```bash
python -m unittest discover -s tests -t .             # 122 tests, 98% line coverage
python examples/customer_onboarding/run.py financial  # narrated walkthrough
python examples/manufacturing/run.py                  # full methodology: modules, CQs, agents, versioning, report, ROI, score
```

### Any deployment, no Python glue: run → report → score

```bash
D=examples/care_referral
python -m autology validate $D/ontology.json --data $D/data.json              # validation, lint, competency questions
python -m autology run $D/ontology.json start_treatment $D/pilot_cases.json \
    --tools $D/tools_pilot.json --name care-coordinator --roles clinical \
    --delegate booking-agent:admin:$D/admin_tools.json \
    --approver $D/approvals.json --out runs.jsonl
python -m autology report $D/ontology.json runs.jsonl                          # compliance report
python -m autology score  $D/ontology.json --runs runs.jsonl --tools $D/all_tools.json \
    --data $D/data.json --budget 25 --tco $D/tco.json --min-score 95           # exit 4 below 95: CI gate
```

Other commands: `lint`, `describe`, `ask` (competency questions), `plan`, `diff` (exits 3 if the version bump is too small), `export --format jsonld|turtle`, `roi`.

### Connecting real systems

```jsonc
// tools.json
{
  "python_path": ["."],
  "registries": ["my_tools:build_registry"],
  "tools": [
    {"name": "clm", "capability": "contract.validate", "type": "http", "url": "https://clm.example.com/validate",
     "headers": {"Authorization": "Bearer ${CLM_TOKEN}"}, "cost": 0.2},
    {"name": "triage_rules", "capability": "clinical.triage", "type": "table", "rows": [
      {"when": "Patient.age >= 75", "outcome": "urgent"}, {"outcome": "routine"}]}
  ]
}
```

- **HTTP tools** receive `{action, capability, inputs, context, attempt}` and answer `{outcome, updates, message}`. Failures raise a tool error, so the action's failure policy applies (retry, fallback, escalate). `${VAR}` values are read from the environment.
- **Approvers:** `"auto"`, `"deny"`, `"console"`, a policy file whose decisions can be conditions (`"sign_contract": "Contract.value < 2000000"`), or `{"type": "http", "url": ...}`. An approver that can't be reached **declines**.

### Any model

```python
from autology import LLMReasoner, FunctionChatModel, ClaudeReasoner, RoutingReasoner
from autology.reasoners import register_price

reasoner = ClaudeReasoner()                               # Claude Opus 5.5 via the anthropic SDK (default)
reasoner = RoutingReasoner.with_claude()                  # no call / Claude Haiku 5.5 / Claude Opus 5.5 per decision
reasoner = LLMReasoner(FunctionChatModel(my_fn, "my-model"))  # any provider: my_fn(system, prompt, schema) -> dict
register_price("my-model", input_per_mtok=1.0, output_per_mtok=3.0)   # so its cost is tracked
```

Whatever the model, it can only choose among the actions valid at that moment, it sees only the redacted state, and governance re-checks every choice. Errors, refusals and invalid answers fall back to the deterministic planner.

## Readiness scorecard

`score_deployment(ontology, runs, tools=..., graph=..., cost_budget=..., roi=...)`, or `autology score`, scores three weighted pillars:

| Pillar | Weight | Criteria |
|---|---|---|
| Ontology quality | 40% | lint, competency questions declared and answered, sensitive fields guarded, tool coverage, semantic clarity, versioning and modules |
| Agent performance | 35% | resolution rate (completed, or correctly stopped by policy), unplanned hand-offs, straight-through rate, cost per completed task against budget, self-healing |
| Governance | 25% | rule families covered, suspension policy, audit integrity, denied proposals, ontology gaps |

Two rules keep the score honest:
- **Policy stops aren't failures.** A case stopped by a prohibition or a failed mandatory step (a sanctioned party, a PEP flag), or declined by a human reviewer, counts as *policy stop*: governance working as designed. Tool failures, unmodelled outcomes, missing permissions, loops and pauses count as *unplanned*.
- **Missing evidence is "not assessed", never guessed.** The scorecard reports evidence coverage and tells you what to add.

Separately, the **roadmap gates** check scope and business value. Pilot needs at least 90% resolution, under 10% unplanned hand-offs, ROI above 200%, and at least 5 entities and 10 rules. Scale needs 50 entities and 100 rules, more than 10 agents and more than 10k tasks a month.

## The narrated onboarding walkthrough

`python examples/customer_onboarding/run.py financial`: the agent adapts after a rejection and stops at the review gates.

```
  [ 1] verify_identity          ALLOW  (planner)
       -> regulated_kyc: done - identity verified, no sanctions hit  [Customer: prospect->verified]
  [ 2] verify_signatory         ALLOW  (planner)
  [ 3] enhanced_due_diligence   ALLOW  (planner)
       -> edd_provider: cleared - beneficial owners verified
  [ 4] submit_contract          ALLOW  (planner)
  [ 5] legal_review             ALLOW  (planner)
       -> contract_validator: rejected - non-standard liability clause violates playbook
  [ 6] revise_contract          REVIEW (planner) R-LEGAL-002
       ? human review by auto-reviewer[legal]: APPROVED
       -> legal_desk: resubmitted - liability clause replaced with standard wording (rev 1)
  [ 7] legal_review             ALLOW  (planner)
       -> contract_validator: approved - all clauses within playbook
  [ 8] sign_contract            REVIEW (planner) R-FIN-001
       ? human review by auto-reviewer[finance_director]: APPROVED
  ...
  [11] activate_customer        ALLOW  (planner)
  => COMPLETED
```

The other scenarios: `retail` (no human touch), `sanctioned` (a prohibition blocks signing), `pep` (failed due diligence), `unprivileged` (agent lacks the role to read tax IDs), `declined` (the Finance Director says no), `flaky` (transient tool failure retried). Add `--interactive` to be the reviewer, or `--llm` to let Claude choose the steps.

## Writing an ontology

```jsonc
{
  "name": "customer-onboarding", "version": "1.2.0",
  "imports": ["modules/fulfilment.json"],                // modules compose; shared definitions de-duplicate
  "entities": {
    "Contract": {"states": ["draft", "submitted", "approved", "rejected", "signed"],
                 "attributes": {"value": "number", "nonstandard_terms": "boolean"}}
  },
  "actions": {
    "legal_review": {
      "capability": "contract.validate",                  // which kind of tool can do it
      "requires": ["Contract.status == 'submitted'"],     // preconditions
      "reads": ["Contract.value"],                        // the only data the tool receives
      "outcomes": {                                       // first = expected (preferred when planning)
        "approved": {"effects": {"Contract": {"status": "approved"}}},
        "rejected": {"effects": {"Contract": {"status": "rejected"}}}
      },
      "on_failure": {"max_attempts": 3, "fallback_after": 1, "backoff_seconds": 60, "escalate_to": "legal"}
    }
  },
  "goals": {"onboard_customer": {"target": "Customer.status == 'active'"}},
  "rules": [
    {"id": "R-LEGAL-001", "type": "mandatory_step", "step": "legal_review", "outcome": "approved",
     "before": "sign_contract", "reset_by": ["revise_contract"]},
    {"id": "R-FIN-001", "type": "human_review", "action": "sign_contract", "reviewer": "finance_director",
     "when": "Contract.value >= 1000000"},
    {"id": "R-PII-001", "type": "data_access", "field": "Customer.tax_id", "roles": ["kyc", "compliance"]},
    {"id": "R-SANC-001", "type": "prohibition", "action": "sign_contract", "when": "Customer.sanctions_hit == True"}
  ],
  "settings": {"max_violations": 3},
  "competency_questions": [{"id": "CQ-02", "question": "Which contracts await legal review?",
                            "find": "Contract", "where": "Contract.status == 'submitted'"}]
}
```

Conditions use a small, sandboxed expression language: `Entity.attr`, literals, comparisons, `in`, `and`/`or`/`not`. Ontology files cannot run code.

## Using it from code

```python
from autology import AutoApprover, Ontology, WorkAgent, score_deployment
from autology.adapters import load_tools

ontology = Ontology.load("examples/customer_onboarding/ontology.json")
tools = load_tools("examples/customer_onboarding/tools.json")
agent = WorkAgent("work-agent", ontology, tools, roles=["sales", "kyc"], approver=AutoApprover())
result = agent.run("onboard_customer", case={"Customer": {...}, "Contract": {...}})
result.status, result.path, result.escalation, result.audit.verify()
print(score_deployment(ontology, [result], tools=tools).render())
```

## Layout

```
autology/                      framework (see table above) + CLI (python -m autology)
examples/customer_onboarding/  modular ontology (customer/contracting/fulfilment), tools, pilot batch, narrated scenarios
examples/manufacturing/        modular enterprise ontology (core/procurement/production/quality), knowledge graph, walkthrough
examples/care_referral/        configuration-only deployment: ontology, decision-table tools, policy, pilot batch
tests/                         122 tests (stdlib unittest), including the >= 95 readiness gate for every example
docs/autology.md               the Autology concept and how it maps to this code
docs/methodology.md            the engineering methodology, section by section, with the code that implements it
```

This repository also has notes on video tooling (`video-skills.md`, `.claude/skills/`). They are unrelated to Autology.
