# Autology: Ontology × Agent

*Ontology-driven workflow automation: a conceptual framework for AI agents that run business processes on their own while keeping enterprise knowledge, rules and context intact.*

This document describes the concept. Each section notes where the idea lives in the reference implementation in this repository (`autology/`).

---

## 1. Core definition

**Autology** pairs an **ontology** (structured business knowledge) with **AI agents** (engines that act on their own) to get workflow automation that adapts but stays inside the rules.

Traditional "hard-coded" workflow tools such as Dify or n8n store business logic as a fixed graph of steps. Autology **separates business logic from execution paths**. The ontology says what exists, what can be done and what is never allowed. Agents work out the path at run time and can change it as conditions change, while the enterprise rules stay fixed.

## 2. Key components

| Component | Description | In this repo |
|---|---|---|
| **Ontology layer** | A formal, machine-readable model of business entities, relationships and rules. Examples: the Customer → Contract → Order lifecycle, approval workflows, data access policies. | `autology/ontology.py`, `examples/customer_onboarding/ontology.json` |
| **AI agent layer** | Agents (Coding Agent, Work Agent, Personal Agent) that read the ontology, pick tools and carry out tasks without a human driving each step. | `autology/agent.py` (`WorkAgent`), `autology/reasoners.py`, `autology/tools.py` |
| **Workflow orchestration** | An execution layer that adapts the process to real-time conditions instead of following fixed, pre-defined steps. | `autology/planner.py`: plans each path at run time and re-plans after every step |
| **Governance layer** | Enforces the immutable rules, such as "critical decisions require human review" and "data access is role-based", so the process stays compliant and accountable. | `autology/governance.py`, `autology/audit.py` |

## 3. How Autology works: customer onboarding

1. **Ontology setup.** Define the entities (`Customer`, `Contract`, `Order`, `BillingAccount`), the rules ("contracts must be approved by Legal") and the context that matters (`Customer.industry == "Financial Services"`).
2. **Agent initialisation.** A `WorkAgent` gets the goal *"Onboard new customer XYZ"* (`onboard_customer`, target `Customer.status == 'active'`).
3. **Dynamic execution.**
   - The agent queries the ontology for the steps it needs. Because XYZ is a financial-services firm, rule `R-FS-001` adds *enhanced due diligence* before contracting.
   - It chooses tools by context. The regulated KYC provider handles a financial-services customer. Invoice billing is used when the account bills by invoice.
   - If the contract is **rejected**, the agent **changes the workflow** instead of failing. The next plan becomes *revise_contract* (escalate to Legal for revision) followed by a fresh *legal_review*.
4. **Governance enforcement.** The agent cannot skip a mandatory step. A revision voids the earlier legal review, so the contract must be re-approved. A 2.5M contract waits for Finance Director sign-off. Tax IDs are visible only to KYC and compliance roles, and the LLM never sees them either.

Run it with `python examples/customer_onboarding/run.py financial`.

## 4. Advantages over traditional workflow tools

| Feature | Traditional tools (Dify / n8n) | Autology |
|---|---|---|
| Process adaptability | Rigid, pre-defined steps | The agent picks the path; re-planning happens on every outcome |
| Knowledge retention | Logic is buried inside each workflow and hard to update | One central, versioned, fingerprinted ontology |
| Scalability | Each new use case needs manual reconfiguration | Agents reuse the same ontology across goals and cases |
| Governance | Little rule enforcement | Immutable rules checked before *every* action, whoever proposed it |
| Cost efficiency | Complex workflows are expensive to maintain | Fewer human touches on routine work; humans step in only at review gates |

## 5. Real-world applications

- **Enterprise procurement:** vendor onboarding, contract negotiation and invoice processing under compliance rules.
- **Healthcare:** care pathways (diagnosis, treatment, follow-up) bound by clinical guidelines and privacy law.
- **Financial services:** loan approval, risk assessment and fraud detection against complex regulatory ontologies.

## 6. Challenges and considerations

- **Ontology engineering.** A complete business ontology takes deep domain knowledge and ongoing upkeep. *Mitigation here:* validation at load time catches unknown entities and attributes, impossible states, unsafe expressions and dangling rule references (`python -m autology validate`).
- **Agent reliability.** Agents must read the ontology correctly and cope with edge cases. *Mitigation here:* the reasoner, LLM or not, can only **propose** actions. Governance checks every proposal, tool outputs are checked against declared outcomes and writable fields, loops are bounded, and when the agent is unsure it escalates instead of guessing.
- **Integration with legacy systems.** ERP and CRM need solid APIs and data mapping. *Mitigation here:* tools are adapters keyed by capability. Ontology fields are mapped explicitly through `reads` and `writes`, so an adapter receives only the data it declared.

## 7. Future outlook

Autology moves automation from *human-in-the-loop* to *agent-in-the-loop*. People set strategy and own the critical decisions, and agents carry out the process. As agents improve, enterprises can:

- grow operations without growing headcount at the same rate;
- keep institutional knowledge in a central ontology;
- respond to market changes by updating ontology rules instead of rebuilding workflows.

**In short:** Autology makes business knowledge the base layer for AI execution, so agents act on their own *and* responsibly. It fits best in regulated industries with complex processes (finance, healthcare, legal), where following the rules and adapting both matter.

---

## Appendix A: design principles of the reference implementation

1. **No stored workflows.** Paths are searched from action preconditions and effects (`Planner.plan`, a cheapest-path search). A new rule or action changes behaviour without anyone touching a process diagram.
2. **Propose ≠ dispose.** `Reasoner.propose` → `GovernanceLayer.evaluate` → tool. A denied proposal is logged as a violation and replaced by the compliant planned step.
3. **Expected outcome for planning, actual outcome for state.** Plans assume the first listed outcome, such as `approved`. Reality can differ, such as `rejected`, and the agent then re-plans.
4. **Fail closed.** The default approver declines. Missing roles, missing tools, unknown outcomes and undeclared writes all lead to escalation.
5. **Immutability and evidence.** Ontologies are deeply frozen and content-hashed, so changing one means publishing a new version. Every decision goes into a hash-chained audit log.
6. **Safe rule language.** Conditions use a small whitelisted expression grammar. Ontology files cannot run code.

## Appendix B: known limitations and next steps

- One instance per entity type per *case*. The `KnowledgeGraph` holds many instances for competency questions, but an agent run still binds one Customer, one Contract and so on. Multi-instance cases, such as many orders per contract, would need instance identifiers in state and expressions.
- Planning is an exhaustive cost-ordered search. That suits processes with tens of actions. Larger domains would need heuristics or a hierarchy of goals.
- Escalations and deferrals are returned to the caller. Production use would route them to ticketing, on-call and scheduler systems.
- The knowledge graph is in memory. A Neo4j or Neptune backend would implement the same `add` / `link` / `query` interface.
- CodingAgent and PersonalAgent roles are not implemented. They would reuse the ontology, governance and audit layers unchanged.
- Only the Anthropic adapter ships for LLMs. Other providers plug in through `FunctionChatModel` (or your own `ChatModel`), but no other vendor SDK is bundled.

The engineering methodology (modules, competency questions, versioning, self-healing, ABAC, compliance reporting and cost/ROI) is covered in [`methodology.md`](methodology.md).
