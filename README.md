# Autology: Ontology × Agent

A reference implementation of **ontology-driven workflow automation**. Business knowledge (entities, actions, rules) lives in one immutable **ontology**. **AI agents** work out how to reach a goal at run time. A **governance layer** makes sure they never skip a mandatory step, never read data they aren't entitled to, and hand critical decisions to humans.

> Concept paper: [`docs/autology.md`](docs/autology.md) · Engineering methodology mapped to the code: [`docs/methodology.md`](docs/methodology.md)

```
            goal + case facts
                    │
   ┌────────────────▼─────────────────┐
   │          AI agent layer          │  WorkAgent: observe → plan → reason → govern → act → re-plan
   │  ┌───────────┐   ┌────────────┐  │
   │  │  Planner  │──▶│  Reasoner  │  │  deterministic, or Claude choosing among valid moves
   │  └─────▲─────┘   └─────┬──────┘  │
   └────────┼───────────────┼─────────┘
            │      proposal │
   ┌────────┴──────┐ ┌──────▼─────────────┐    ┌───────────────────┐
   │ Ontology layer│ │  Governance layer  │──▶ │ human review gate │
   │ entities      │ │ mandatory steps    │    └───────────────────┘
   │ actions       │─▶ prohibitions       │
   │ goals, rules  │ │ data access / PII  │──▶ hash-chained audit log
   └───────────────┘ └──────┬─────────────┘
                            │ allowed
                  ┌─────────▼─────────┐
                  │   Tool registry   │  capability → context-selected tool (KYC, CLM, ERP, CRM…)
                  └───────────────────┘
```

## What's in the box

| Methodology area | Capability | Module |
|---|---|---|
| Ontology engineering | Entities, relationships, actions, goals, rules; validated, frozen, fingerprinted | `ontology.py` |
| | Modules via `imports` (de-duplicated, conflict and cycle checks) | `ontology.py` |
| | Competency questions answered over a typed knowledge graph | `graph.py` |
| | Lint: security by design, bias hints, dead states, tool coverage | `lint.py` |
| | OWL/Turtle and JSON-LD export | `export.py` |
| | Semantic diff, semver enforcement, publishing registry, version pinning | `versioning.py` |
| Agent orchestration | Run-time planning that also plans through non-default outcomes | `planner.py` |
| | Self-healing: fallback tools, backoff, defer and resume, escalate to the policy owner | `agent.py` |
| | Tool allow-lists, cost-aware tool selection | `tools.py` |
| | Multi-agent delegation (e.g. payment terms → FinanceAgent) | `agent.py` |
| | Context-rich human review requests; decision provenance | `agent.py`, `governance.py` |
| Governance | Mandatory steps, prohibitions, read/write/action access (ABAC), human review | `governance.py` |
| | Suspension of agents after repeated violations; fail-safe pause on ontology problems | `governance.py`, `agent.py` |
| | Hash-chained audit log, compliance report, ontology-gap analysis | `audit.py`, `reporting.py` |
| Cost optimisation | Model routing (none / Claude Haiku 5.5 / Claude Opus 5.5), decision cache, prompt caching, token cost tracking | `reasoners.py` |
| | KPIs (success, straight-through, intervention, latency, cost per task), TCO/ROI from measured rates | `reporting.py`, `economics.py` |
| Readiness | Scorecard 0-100 and grade A-F across ontology quality, agent performance and governance; pilot and scale gate checks; fixes ranked by points recovered | `scoring.py` |

## Quick start

Requires Python 3.10 or later. No dependencies.

```bash
python examples/customer_onboarding/run.py            # concept walkthrough (7 scenarios)
python examples/customer_onboarding/run.py financial  # customer XYZ
python examples/manufacturing/run.py                  # full methodology: modules, CQs, 3 agents, versioning, report, ROI
python -m unittest discover -s tests -t .             # 86 tests

python -m autology validate examples/manufacturing/enterprise.json --data examples/manufacturing/data.json
python -m autology ask examples/manufacturing/enterprise.json examples/manufacturing/data.json CQ-02 --param line=PL-1
python -m autology diff OLD.json NEW.json             # exits 3 if the version bump is too small
python -m autology export examples/manufacturing/enterprise.json --format turtle
python -m autology roi examples/manufacturing/roi.json
python -m autology score examples/manufacturing/enterprise.json --data examples/manufacturing/data.json --min-score 80
```

### Readiness scorecard

`score_deployment(ontology, runs, tools=..., graph=..., cost_budget=..., roi=...)` scores a deployment from 0 to 100 and grades it from A to F. There are three weighted pillars:

| Pillar | Weight | Criteria |
|---|---|---|
| Ontology quality | 40% | lint findings, competency questions declared and answered, sensitive fields guarded, tool coverage, semantic clarity, versioning and modules |
| Agent performance | 35% | success rate, unplanned hand-offs, straight-through rate, cost per completed task against a budget, self-healing after tool failures |
| Governance | 25% | rule families covered, suspension policy, audit-trail integrity, denied proposals, ontology gaps found in the logs |

A criterion with no evidence (no runs, sample data, tools or budget) is marked *not assessed*. It doesn't count toward the score, and the scorecard says what evidence to add. Separately, the roadmap gates check scope and business targets: pilot needs success above 90%, unplanned intervention below 10%, ROI above 200%, and at least 5 entities and 10 rules. A high score with open gates means the deployment is well built but not yet big or valuable enough for the next phase. The CLI scores the ontology pillar, and `--min-score` exits with code 4, so it can gate CI.

Output of the `financial` scenario. The process changes after the rejection and stops at the review gates:

```
  [ 1] verify_identity          ALLOW  (planner)
       -> regulated_kyc: done - identity verified, no sanctions hit  [Customer: prospect->verified]
  [ 2] enhanced_due_diligence   ALLOW  (planner)
       -> edd_provider: cleared - beneficial owners verified
  [ 3] submit_contract          ALLOW  (planner)
       -> clm_portal: done - contract uploaded to CLM  [Contract: draft->submitted]
  [ 4] legal_review             ALLOW  (planner)
       -> contract_validator: rejected - non-standard liability clause violates playbook
  [ 5] revise_contract          REVIEW (planner) R-LEGAL-002
       ? human review by auto-reviewer[legal]: APPROVED
       -> legal_desk: resubmitted - liability clause replaced with standard wording (rev 1)
  [ 6] legal_review             ALLOW  (planner)
       -> contract_validator: approved - all clauses within playbook
  [ 7] sign_contract            REVIEW (planner) R-FIN-001
       ? human review by auto-reviewer[finance_director]: APPROVED
  ...
  [10] activate_customer        ALLOW  (planner)
  => COMPLETED
```

| Scenario | Result | What it shows |
|---|---|---|
| `retail` | completed | Straight-through processing with no human touch |
| `financial` | completed | Context-dependent mandatory step (EDD) and tool choice; re-planning after rejection; human review gates |
| `sanctioned` | escalated | A prohibition rule blocks signature; the escalation names the rule |
| `pep` | escalated | A failed mandatory step means no compliant path, so the case goes to a human |
| `unprivileged` | escalated | The agent lacks the role to read tax IDs, so it escalates instead of working around the rule |
| `declined` | blocked | The Finance Director declines a 2.5M contract |
| `flaky` | completed | A transient tool failure is retried |

Add `--interactive` to act as the human reviewer yourself. Add `--llm` to let Claude choose each step (`pip install anthropic` and API credentials needed).

## Writing an ontology

```jsonc
{
  "name": "customer-onboarding", "version": "1.0.0",
  "entities": {
    "Contract": {"states": ["draft", "submitted", "approved", "rejected", "signed"],
                 "attributes": {"value": "number", "nonstandard_terms": "boolean"}}
  },
  "actions": {
    "legal_review": {
      "capability": "contract.validate",            // which tool kind can do it
      "requires": ["Contract.status == 'submitted'"], // preconditions
      "reads": ["Contract.value"],                  // the only data the tool receives
      "outcomes": {                                 // first = expected (used for planning)
        "approved": {"effects": {"Contract": {"status": "approved"}}},
        "rejected": {"effects": {"Contract": {"status": "rejected"}}}
      }
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
  ]
}
```

Conditions use a small, sandboxed expression language: `Entity.attr`, literals, comparisons, `in`, `and`/`or`/`not`. Ontologies are validated when they load, then frozen and fingerprinted.

## Using it from code

```python
from autology import AutoApprover, Ontology, ToolRegistry, ToolResult, WorkAgent

ontology = Ontology.load("examples/customer_onboarding/ontology.json")
tools = ToolRegistry()

@tools.tool("contract.validate", when="Contract.value > 0")
def contract_validator(call):
    return ToolResult("rejected" if call.inputs["Contract.nonstandard_terms"] else "approved")
# ... register a tool for every capability ...

agent = WorkAgent("work-agent", ontology, tools, roles=["kyc"], approver=AutoApprover())
result = agent.run("onboard_customer", case={"Customer": {...}, "Contract": {...}})
result.status, result.path, result.escalation, result.audit.verify()
```

To let Claude reason, pass `reasoner=ClaudeReasoner()`. It defaults to `claude-opus-5-5`. Structured output limits its answer to the actions that are valid right now. It sees only the redacted state. On an API error or refusal it falls back to the planner, with server-side refusal fallbacks enabled where the model supports them.

For cost control, use `reasoner=RoutingReasoner.with_claude()`. It makes no model call when only one action is valid, uses Claude Haiku 5.5 for simple choices and Claude Opus 5.5 for complex ones. Decisions are cached, and token cost is reported per run.

## Layout

```
autology/                       framework (see table above) + CLI (python -m autology)
examples/customer_onboarding/   single-file ontology, simulated tools, 7 scenarios
examples/manufacturing/         modular enterprise ontology (core/procurement/production/quality),
                                sample knowledge graph, tools with costs, ROI assumptions, walkthrough
tests/                          78 unit + scenario tests (stdlib unittest)
docs/autology.md                the Autology concept and how it maps to this code
docs/methodology.md             the engineering methodology, section by section, with the code that implements it
```

This repository also has notes on video tooling (`video-skills.md`, `.claude/skills/`). They are unrelated to Autology.
