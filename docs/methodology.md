# In-depth approach to Autology: ontology-driven agent workflow automation

This is an engineering methodology for designing, building and scaling Autology solutions. It covers ontology engineering, agent orchestration, enterprise governance and cost optimisation. It draws on Palantir's Ontology architecture, common industry practice and real ToB procurement problems.

Each section has a **"In this repo"** box that names the code implementing it. Run the whole method end to end with:

```bash
python examples/manufacturing/run.py
```

> Money figures in this document (build costs, savings, ROI targets) are planning estimates from the original framework. They are not measurements. The repo's ROI tool (§4) takes such estimates as inputs and replaces the operational ones with rates measured from agent runs.

---

## 1. Foundation: ontology engineering (the "brain" of Autology)

The ontology is the single source of truth for business logic, data and rules. It must be machine-readable, human-auditable and future-proof.

### 1.1 Design principles

- **Nouns + verbs + rules.** Model the entities (`Customer`, `Contract`, `Order`), the actions (`ApproveContract`, `UpdateOrderStatus`) and the immutable rules ("contracts must be approved by Legal before execution").
- **Semantic clarity.** Make relationships first-class, e.g. `Customer → hasContract → Contract → hasOrder → Order`, so nothing is ambiguous.
- **Modularity.** Split the ontology into domain modules (`ProcurementOntology`, `CustomerOntology`) so no single model becomes unmanageable.
- **Security by design.** Put role- and attribute-based access control and data lineage in the ontology itself ("only Finance can modify payment terms").

> **In this repo**
> - *Nouns, verbs, rules:* `entities`, `actions` (preconditions → outcomes → effects) and `rules` in the ontology JSON (`autology/ontology.py`).
> - *Relationships:* `relationships`, which competency questions traverse (`autology/graph.py`).
> - *Modularity:* `"imports": [...]`. `examples/manufacturing/enterprise.json` is composed from `core`, `procurement`, `production` and `quality` modules. Shared definitions are de-duplicated, conflicting ones are rejected and cycles are detected.
> - *Security by design:* `data_access` (read), `write_access` ("only Finance can modify payment terms", rule `R-FIN-001`), `action_access` and attribute tags (`pii`, `restricted`, `protected`). The linter flags sensitive fields that no rule guards.

### 1.2 Development lifecycle

1. **Discovery.** Interview domain experts to map processes, pain points and decision points. Analyse existing sources (ERP, CRM, spreadsheets) for entity schemas and relationships.
2. **Modelling.** Use a formal representation (OWL, JSON-LD). Validate with **competency questions**, such as "Which contracts expire in 30 days?" and "What is the total revenue for Customer X in Q3?"
3. **Implementation.** Deploy on a graph database (Neo4j, Amazon Neptune) or an ontology engine (Palantir Foundry), with ETL to sync operational data.
4. **Validation.** Test edge cases, such as overlapping contracts, for rule consistency. Audit compliance (GDPR, SOX).

> **In this repo**
> - *Modelling:* authoring happens in JSON/YAML. `python -m autology export ONTOLOGY --format jsonld|turtle` emits OWL. Both outputs parse as valid RDF.
> - *Competency questions:* `competency_questions` are declared in the ontology. They are checked statically when the ontology loads, and answered against sample data by `python -m autology validate ONTOLOGY --data data.json`. The manufacturing ontology answers all six of its questions, covering expiring contracts, supplier dependencies, missing clauses, open order value, recall blast radius and line counts.
> - *Implementation:* `KnowledgeGraph` is the in-memory reference store that enforces the ontology's types, states and relationship directions. Back the same interface with Neo4j or Neptune in production.
> - *Validation:* load-time validation catches unknown references, invalid states, unsafe expressions, dangling rules and bad questions. `python -m autology lint` adds security, bias and dead-state findings and goals no action can change. The scenario tests cover the edge cases.

### 1.3 Maintenance

- **Version control.** Track every change (`v1.0 → v1.1` for a new contract type) so existing agents don't break.
- **Feedback loops.** Use agent execution logs to find ontology gaps, e.g. "agent failed to process `PartialDelivery` because it isn't defined in the ontology".
- **Continuous improvement.** Update the ontology as rules change (new regulation, product launches).

> **In this repo**
> - `autology/versioning.py` classifies each change as major, minor or patch.
> - `OntologyRegistry.publish` **refuses a release whose version bump understates its changes**. `python -m autology diff OLD NEW` exits non-zero in that case, so it can gate CI.
> - Agents pin a version. Pass `on_ontology_update="pause"` to stop when a newer version is published mid-run. A withdrawn version always pauses the agent.
> - `reporting.ontology_gaps(results)` turns escalations into concrete modelling suggestions. The manufacturing demo replays the exact `PartialDelivery` example: v1.0.0 escalates, the gap report says *add outcome 'partial_delivery' to check_material_supply*, a 1.0.1 release is refused as too small a bump, 1.1.0 is published, and the same case completes.

---

## 2. Agent orchestration: from fixed flows to dynamic execution

### 2.1 Agent design principles

- **Goal-oriented.** An agent starts from an objective ("Onboard Customer X") and uses the ontology to break it into steps.
- **Context-aware.** It reads real-time context, e.g. "Customer X is in healthcare, so contract approval needs Legal + Compliance".
- **Self-healing.** If a step fails ("payment gateway is down"), it reroutes: "retry in 1 hour, escalate to Finance after 3 failures".
- **Auditable.** Every action is logged with provenance: "approved Contract #1234 because it met Rule #5.2 and the credit score is above 800".

> **In this repo**
> - *Goal-oriented:* `ontology.goals` plus the planner (`autology/planner.py`). The plan is re-derived after every real outcome. The planner prefers expected outcomes but can plan through others when the goal requires it, e.g. *clause check finds a missing clause → Legal redline → re-check*.
> - *Context-aware:* rule and tool `when` conditions. Examples: `R-FS-001` adds enhanced due diligence for financial-services customers, and `R-PROD-001` forces a reroute when the supplier is late.
> - *Self-healing:* each action has an `on_failure` policy: `max_attempts`, `backoff_seconds`, `fallback_tools` and `escalate_to`. Short backoffs wait inline. Long ones (an hour) **defer** the case with a `resume_at` time, and `WorkAgent.resume()` continues it. After the last attempt the agent escalates to the policy's owner, for example `plant_manager`.
> - *Auditable:* each decision records `satisfied_rules`, the `facts` relied on (redacted for the acting principal) and a sentence such as *"sign_supplier_contract requires human review; satisfied R-PROC-001; pending R-FIN-002; facts Contract.value=1500000"*. Entries are written to a hash-chained `AuditLog`.

### 2.2 Orchestration patterns

1. **Ontology-driven planning.** The agent generates the workflow from the ontology. Example: "healthcare customers require HIPAA checks" adds that step.
2. **Tool orchestration.** The ontology defines which tools an action may use. Agents choose among them, e.g. "ToolA if cost < $100, else ToolB".
3. **Human in the loop.** Escalation rules ("Legal if value > $1M") plus context-rich requests that include history, risk and the rule justification.

> **In this repo**
> - *Planning:* see §2.1. `python -m autology plan ONTOLOGY GOAL CASE.json` shows the plan, with the outcome assumed for each step.
> - *Tools:* an action's `tools` allow-list restricts which tools may be used. Among eligible tools, context-specific ones come first, then higher priority, then **cheapest**. Fallbacks follow the same order. In the demo the 0.05 AI clause checker is used, and the 400 outside-counsel review only when it is down.
> - *Human in the loop:* `human_review` rules, optionally with `when`. A `ReviewRequest` carries the rule IDs and justifications, the facts, the step history, the provenance sentence and the redacted case view. The default approver **declines**, so the system fails closed.

### 2.3 Agent development workflow

1. **Define roles.** CodingAgent (software tasks), WorkAgent (business workflows), PersonalAgent (individual assistance).
2. **Implement logic.** Use LLMs for language understanding and planning, wrapped in ontology guardrails ("cannot modify `ContractStatus` unless it is in `AllowedActions`").
3. **Test.** Use simulated environments for edge cases ("what if the ontology changes mid-execution?") and measure success rate, latency, human-intervention rate and cost per task.

> **In this repo**
> - *Roles:* `WorkAgent` principals with roles. **Multi-agent teams:** `WorkAgent(..., delegates=[finance_agent])`. The lead plans with the team's combined permissions, and each action runs under the identity of a member allowed to perform it. Delegation is audited, and the lead still sees only its own redacted view. CodingAgent and PersonalAgent are not implemented. They would use the same ontology and governance layers.
> - *LLM guardrails:* the reasoner, whether `ClaudeReasoner` or any `Reasoner`, can only **propose** from the actions valid at that moment. Structured output constrains its answer. Governance re-checks every proposal, tools can write only declared fields (`writes`, plus `write_access`), and status changes only through declared outcomes. Repeated useless-but-valid choices are cut off by `max_repeats`.
> - *Testing:* there are 78 tests, and `simulate_pilot()` in the manufacturing example runs a seeded batch of 200 contracts. A mid-run ontology change is a tested case, and the agent pauses safely. `reporting.metrics()` reports success rate, straight-through rate, human-intervention rate, average latency and cost per task.

---

## 3. Enterprise governance: compliance and control

### 3.1 Framework

- **Policy enforcement.** Non-negotiable rules live in the ontology, and agents check them before *every* action.
- **Audit trail.** Every action, ontology query and human intervention goes into a tamper-evident ledger. Compliance reports follow from it ("95% of approvals followed Rule #5.2").
- **Access control.** ABAC limits agents ("only FinanceAgents see PaymentTerms"). Agents that break rules lose access.

> **In this repo**
> - *Enforcement:* `GovernanceLayer.evaluate` runs on every proposal, whoever made it. It checks preconditions, mandatory steps (with `reset_by`), prohibitions, data, write and action access, and human review.
> - *Audit:* `AuditLog` chains SHA-256 hashes, so any edit breaks `verify()`. That gives the same tamper evidence as a blockchain without a consensus network. Anchor the head hash in an external timestamping service or WORM storage if third parties must be able to verify it.
> - *Reports:* `reporting.compliance_report(results, ontology)` produces markdown with KPIs, per-rule counts (applied, satisfied, reviewed, denied), hand-offs and ontology gaps. Executed actions show 100% adherence because nothing can run with an unsatisfied rule. The meaningful signals are the **denials and reviews**.
> - *Access revocation:* with `settings.max_violations`, a principal that keeps proposing forbidden actions is **suspended**. Suspension persists across cases until `governance.reinstate()`. The demo's rogue reasoner is suspended after three attempts to sign early.

### 3.2 Risk mitigation

- **Bias detection.** Audit the ontology for built-in bias, e.g. "approve if revenue > $1M" disadvantages small businesses.
- **Failure resilience.** Fail safely: if the ontology is unavailable, pause and alert instead of deciding.
- **Vendor lock-in.** Use open standards (OWL, JSON-LD) so the model is portable.

> **In this repo**
> - *Bias:* lint rule `BIAS001` flags rules and preconditions that decide on attributes tagged `protected`. `BIAS002` flags prohibitions that exclude cases by a numeric threshold, so a person can review them. Linting cannot prove fairness. It tells reviewers where to look.
> - *Resilience:* a fingerprint mismatch, or a withdrawn or superseded pinned version, makes the agent return `paused` to `ontology-admin` before any action. Tool failures follow the action's failure policy. No compliant path means escalation with the blocking rule named, never a guess.
> - *Lock-in:* `export.to_jsonld` and `export.to_turtle` (OWL 2) put entities, attributes, relationships and states in standard vocabulary. Actions, rules and goals go in an `autology:` vocabulary, so nothing is lost.

---

## 4. Cost optimisation: maximising ROI in ToB AI procurement

### 4.1 TCO model

| Layer | Item | Planning range (framework estimate) |
|---|---|---|
| Ontology | Development | 50k–200k |
| | Maintenance | 10k–50k / year |
| Agents | LLM inference | 0.01–0.10 per task |
| | Tool integration | 20k–100k |
| Operations | Human intervention | 50–200 / hour (expected to fall 70–90%) |
| | Downtime | 10k–100k / hour (reduced by self-healing) |

### 4.2 Optimisation strategies

- **Right-size models.** Small models for simple decisions, large models for complex reasoning.
- **Reuse results.** Cache frequent queries and decisions instead of re-asking the model.
- **Negotiate pricing.** Volume discounts or outcome-based pricing ("pay per successful task").

> **In this repo**
> - *TCO / ROI:* `autology/economics.py` (`TCOModel`, `evaluate`) and `python -m autology roi TCO.json`. It reports run cost per year by layer, one-off investment, net savings, hours saved, ROI over the horizon and payback. `from_metrics()` replaces the assumed intervention rate and per-task tool and LLM costs with **values measured from runs**.
> - *Right-sizing:* `RoutingReasoner.with_claude()` makes **no model call when only one action is valid**. It sends simple choices to Claude Haiku 5.5 at low effort and complex ones to Claude Opus 5.5. Measure first, because one capable model at lower effort can be as good.
> - *Caching:* `ClaudeReasoner` caches decisions for identical redacted situations. These are keyed exactly, which suits governed decisions. A vector database is for semantic retrieval, not for replaying decisions. It also keeps the ontology description in a stable system prompt with prompt caching. Every proposal reports token usage and estimated cost, and these roll up into `metrics()`.
> - *Pricing:* `metrics()` gives cost per **completed** task (success rate × cost per task), which is the number you need to negotiate outcome-based pricing.

### 4.3 ROI measurement

- **Hard savings:** direct cost reductions, e.g. contract review time from 40 to 5 hours a week.
- **Soft savings:** indirect benefits, e.g. faster approvals improve retention.
- **Long-term value:** knowledge retention, e.g. new agents reuse the ontology without rework.

> **In this repo:** hard savings come from `evaluate()`. Soft savings stay with you: add them as reduced costs or extra revenue lines if you can quantify them. Ontology reuse is visible in the manufacturing example, where three agents share one `core` module and governance layer.

---

## 5. Implementation roadmap: pilot to enterprise scale

| Phase | Focus | Deliverables | Exit metrics | Repo tooling |
|---|---|---|---|---|
| **1. Pilot (0–6 months)** | One high-impact use case, e.g. small-business contract approval | Ontology with 5–10 entities and 10–15 rules; a WorkAgent handling 100+ contracts a month; cost-benefit analysis | Success > 90%, human intervention < 10%, ROI > 200% | `validate --data`, `lint`, `simulate_pilot()`, `metrics()`, `compliance_report()`, `roi` |
| **2. Scale (6–18 months)** | 2–3 more use cases (purchase orders, onboarding) | Modular ontology with 50+ entities and 100+ rules; an agent fleet; ERP/CRM/HRIS integration | Agents > 10, tasks > 10k a month, adoption > 30% | `imports` modules, `OntologyRegistry` and `diff` in CI, delegation teams, tool registries per system |
| **3. Optimise (18+ months)** | Analytics, predictive and multi-agent work | Gap analytics, proactive automation (flag contracts 30 days before expiry), multi-agent collaboration, generated drafts | Adoption > 70%, cost reduction > 50% vs manual, 10+ new use cases a year | `ontology_gaps()`, competency questions as triggers (CQ-01 finds expiring contracts), `RoutingReasoner` |

**About the pilot gate.** Use human-intervention rate as defined in `metrics()`: any review or hand-off. It is intentionally strict. The manufacturing pilot simulation reaches about 98% success, but its human-touch rate is about 34%, because 20% of contracts are worth 1M or more and need CFO review, and 15% need a Legal redline. That is the governance working as designed, not agent failure. Either set the target per *unplanned* hand-off, or decide consciously which review thresholds can move.

---

## 6. Worked example: a manufacturing enterprise

A global manufacturer with 10k+ employees and $5B revenue. See `examples/manufacturing/`.

| Framework element | Implementation |
|---|---|
| Entities: Factory, ProductionLine, Product, Supplier, Contract, Order | `modules/core.json` (shared) + `modules/production.json`, plus a `QualityCase` in `modules/quality.json` |
| Relationships: Factory → hasProductionLine → ProductionLine → manufactures → Product → hasSupplier → Supplier | Declared as written. CQ-02 traverses them to answer which suppliers line PL-1 depends on |
| Rule: "ProductionLine #1 can only manufacture Product A if Supplier X delivers on time" | `R-PROD-001` prohibits `start_production` on the primary line when the supplier is late, so the agent plans `reroute_to_alternate_line` |
| Rule: "Supplier contracts must include a `LateDeliveryPenalty` clause" | `R-PROC-001` (mandatory clause check before signing, reset by a Legal redline) plus `R-PROC-002` (prohibition as a backstop) |
| **ProductionAgent** monitors, predicts delays and reroutes | Supply check, then reroute, start and complete. A MES outage is deferred for an hour, resumed, and escalated to the plant manager after 3 rounds |
| **ProcurementAgent** checks clauses and escalates to Legal | Clause check, then a Legal redline (reviewed), a re-check and a CFO review for 1M+. Payment terms are **delegated to a FinanceAgent** under `R-FIN-001` |
| **QualityAgent** traces defects and triggers `ProductRecall` | Trace, quarantine, then a recall reviewed by the Quality Director (`action_access` allows only quality roles), followed by supplier suspension. A low defect rate releases the stock instead |

The framework estimated savings of $2M a year from 30% less downtime, $1M from 50% faster contract signature and $500k from 20% fewer defects. Treat these as the business case to test. Run the pilot simulation with your own case mix, put your cost assumptions in `roi.json`, and compare.

---

## 7. Conclusion

Autology moves enterprise automation from human-driven workflows to agent-driven execution that the ontology guides. It delivers:

- **Autonomy.** Agents run routine cases end to end, and the decision cache and model routing keep the cost per decision low.
- **Control.** The ontology governs every action, governance has provenance, and violators are suspended.
- **Scalability.** Modules, versions and teams of agents grow with the enterprise.
- **ROI.** Value is measured from runs, not assumed.

**Key takeaway.** Success depends on ontology quality (validation, lint, competency questions, versioning), agent design (propose/dispose separation, self-healing, delegation) and enterprise alignment (compliance reports, ROI from evidence). The tooling here makes each of those checkable.
