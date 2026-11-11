# Evaluating reasoners

The reasoner decides which compliant action an agent takes next. It can be the deterministic planner, a language model, a router between models, or your own code. `autology eval` tests reasoners against a suite of cases with expected behaviour, so you can compare models and prompts before you change what runs in production.

Governance is the same in every run. A reasoner can only choose among actions the ontology allows, so an evaluation measures *quality*: does it reach the goal, in a sensible order, with few detours and little spend? It does not measure whether the agent stays compliant, because that is enforced for every reasoner.

## A suite

```jsonc
{
  "name": "order fulfilment",
  "ontology": "ontology.json", "tools": "tools.json", "goal": "fulfil_contract",
  "roles": ["ops", "eu_ops", "finance"], "approver": "auto",
  "reasoners": {"planner": "planner", "claude": "claude", "mine": "my_models:factory"},
  "prices": {"my-local-model": [0.2, 0.6]},
  "repeats": 1,
  "cases": [
    {"id": "five orders", "case_file": "case.json",
     "expect": {"status": "completed", "reviews": 1, "order": ["clear_hazmat@O-2", "ship_order@O-2"],
                "final": ["all_of(Order.status in ['invoiced', 'cancelled'])"]}},
    {"id": "no finance role", "case_file": "case.json", "roles": ["ops", "eu_ops"],
     "expect": {"status": "escalated", "escalation": "Only finance runs credit checks"}}
  ]
}
```

Paths are relative to the suite file. `approver` takes the same values as `autology run` (`auto`, `deny`, or a policy file). `delegates` lists helper agents as `{"name", "roles", "tools"}`. A case may override `roles` and `goal`.

| Expectation | Passes when |
|---|---|
| `status` | The run ends in this status, or one of a list |
| `contains` / `excludes` | These actions were / were not executed. `ship_order` matches any record, `ship_order@O-2` one |
| `order` | These actions were executed in this relative order |
| `max_steps` | At most this many steps were executed |
| `reviews` | Exactly this many human reviews took place |
| `final` | These conditions hold on the final state. Quantifiers work: `all_of(Order.status == 'invoiced')` |
| `escalation` | This text appears in the escalation reason or details |
| `max_fallbacks` | A model fell back to the planner at most this many times |
| `max_cost_usd` | Model spend stayed within this amount |

Without `expect`, a case must complete. Expectations are type-checked when the suite loads: a string where a list belongs, an empty list or a non-integer count is an error, never a vacuous pass. A case with nothing checked does not pass. `max_cost_usd` fails when any model used has no price, because an unknown cost cannot be shown to be within a limit.

## Running it

```bash
python -m autology eval examples/order_fulfilment/evals.json
python -m autology eval SUITE.json --reasoner claude=claude --reasoner routing=routing --repeats 3
python -m autology eval SUITE.json --min-pass 0.95       # exit 5 if any reasoner is below: CI gate
python -m autology eval SUITE.json --json > report.json
```

The example suite compares the planner with two scripted stand-ins for models (`examples/order_fulfilment/eval_models.py`), so it runs offline. Replace them with `claude` or your own provider adapter to evaluate a real model.

```
| Reasoner   | Pass rate | Passed | Mean steps | Agreement | Fallbacks | Overrides | Model calls | Cost (USD) | ...
| planner    | 100%      | 5/5    | 6          | 100%      | 0         | 0         | 0           | 0.0000     |
| contrarian | 100%      | 5/5    | 6          | 86%       | 0         | 0         | 30          | 0.0945     |
| unreliable | 100%      | 5/5    | 6          | 92%       | 16        | 0         | 30          | 0.0000     |
```

## The metrics

| Metric | Meaning |
|---|---|
| Pass rate | Share of runs where every expectation held |
| Mean steps | Executed steps per run. More than the planner means detours |
| Agreement | Share of decisions equal to the planner's next step. Low agreement is not wrong in itself, but it shows where a model's judgement differs |
| Fallbacks | Answers that were invalid, refused, truncated or failed, so the planner chose instead |
| Overrides | Proposals governance refused, replaced by the compliant plan |
| Model calls, cost | Calls made and spend, from the model's reported token usage and the price table (`prices` adds models) |
| p50 / p95 ms | Wall time per run |
| Consistency | With `repeats` > 1: share of cases where every attempt gave the same result and the same path |

The report ends with a failure analysis that groups failed expectations by name, with the case, reasoner and detail for each.

From Python:

```python
from autology.evals import load_suite, run_suite
report = run_suite(load_suite("evals.json"), {"planner": "planner", "mine": lambda: MyReasoner()}, repeats=3)
report.summary(); report.failures(); print(report.render())
```
