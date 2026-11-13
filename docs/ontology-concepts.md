# Ontology concepts and where they live in Autology

A common way to explain an enterprise ontology (Palantir's in particular) uses five elements, three layers,
two comparisons (with a data warehouse and with RAG), an implementation path and a list of pitfalls. This
page maps each of those to Autology's code, and says plainly where Autology falls short. The running example
is motor insurance claims: [`examples/auto_insurance`](../examples/auto_insurance).

## Five elements

| Element | Question it answers | In Autology | Example |
|---|---|---|---|
| Object type | What exists? | `entities` with lifecycle `states` (`ontology.py`) | `Claim`, `Policy`, `RepairShop` |
| Property | What is it like? | Typed `attributes`, with `sensitivity` tags | `Claim.amount`, `Policy.holder` (PII) |
| Link type | How are things related? | `relationships` with cardinality; traversed by queries, case templates and impact rules | `Claim -repairedAt-> RepairShop` |
| Action type | What can be done? | `actions` with preconditions, outcomes, effects and declared reads and writes; executed by tools | `approve_claim`, `pay_claim` |
| Function | How is it calculated? | `functions`: named, typed expressions over an object and its linked objects, usable in every rule, goal, precondition, question and effect (`{"compute": ...}`) | `Claim.payout` |

Functions are deliberately not code: they are expressions in the same safe language as rules (comparisons,
arithmetic, `min`/`max`/`abs`/`round`, quantifiers over multi-record cases), so they are validated with the
ontology, versioned by `diff`, and evaluate to *unknown* rather than a guess when a fact is missing. Anything
that needs real code (a model call, a lookup in another system) is a tool behind an action.

## Three layers

| Layer | What it is for | In Autology |
|---|---|---|
| Semantic: what the world is | Objects, properties and links; one shared vocabulary | Entities, relationships, aliases, interfaces, competency questions with expected answers, the knowledge graph (`graph.py`), OWL/JSON-LD export |
| Kinetic: what the world can do | Actions, functions and interfaces that read and write | Actions and tools (`agent.py`, `adapters.py`), functions, write-back to the graph with conflict checks, automations on data changes (`automation.py`), the REST API, typed SDKs, the governed assistant and the MCP server (`mcp.py`) |
| Dynamic: how decisions get made and get better | Agents, decision history, decision-to-result links, continuous improvement | Agents that plan under governance (`planner.py`), human review, the tamper-evident audit of every decision, **recorded outcomes** linked to the decisions that caused them, `outcome_analysis` suggesting which rules to widen or tighten, what-if scenarios (`scenarios.py`) and reasoner evaluations (`evals.py`) |

The dynamic layer closes the loop like this: a run's decisions are in its audit chain; a person later records
what happened (`POST /api/runs/{id}/outcomes`, e.g. "repair cost exceeded the estimate", `good: false`); the
outcome is appended to the same chain; `GET /api/outcomes` and the compliance report then show, per action and
per rule, how often decisions went wrong, and suggest a change: add a review where none exists, widen a review
condition that let a bad decision through, or revisit a review that approved decisions which then went wrong.
The suggestions are for a person to act on through a versioned ontology change; nothing rewrites rules itself.

## Compared with a data warehouse

| | Data warehouse | Autology |
|---|---|---|
| Models | Facts and dimensions: results | Objects, states, rules and actions: behaviour |
| Answers | What was the result? | What is true now, what may be done next, and why was it done? |
| Writes | Loaded by pipelines, read by dashboards | Changed only through governed actions, with an audit entry for each |
| Scope | Schema designed up front | Grows by modules and versioned changes, checked by competency questions |

Autology is **not** a replacement for a warehouse and has no data platform: no connectors, pipelines,
versioned datasets or lineage. Data reaches the graph through the API, tools or files. Keep the warehouse for
analysis and feed the ontology from the same sources.

## Compared with RAG

Retrieval-augmented generation finds passages of text that look relevant and lets a model write an answer
from them. It cannot tell a model which actions are allowed, and nothing it returns is checked. In Autology a
model never retrieves free text to decide: it reads typed objects through tools that apply the user's row and
field access, chooses among the actions whose preconditions hold, and every choice passes governance and is
audited. Competency questions are answered by the graph, not by the model. Autology does **not** search
documents; for document question-answering, use a RAG tool next to it.

## Implementation path

| Step | In Autology |
|---|---|
| 1. Objects | Entities and attributes; `validate` checks types and sample data |
| 2. Relationships | Relationships and case templates; competency questions prove the model answers real questions |
| 3. Actions | Actions with tools; `plan` shows the compliant path before anything runs |
| 4. Decision logic | Rules (reviews, prohibitions, access) and functions |
| 5. Continuous improvement | Outcomes, scenarios, evaluations, readiness score and semantic diff between versions |

**Minimum Viable Ontology.** Start with the fewest objects, links and actions that settle a real case end to
end. The auto-insurance example is one: five entities, four actions, seven rules, 97/100 on the readiness
score, and still failing the pilot *scope* gate, because an MVO is meant to be small. The score says it is
well built; the gate says it is not yet big enough to roll out.

**Discovery, formalisation, activation.** Discovery is a workshop, not software: list the objects people
talk about and the decisions they make, and write the questions the model must answer as competency
questions. Formalisation is the JSON ontology, checked by `validate` and `lint`. Activation is the API, the
inbox, automations, SDKs, the assistant and the MCP server, all over the same governed actions
([`methodology.md`](methodology.md) has the detailed lifecycle).

## The three pits

| Pit | What goes wrong | How Autology addresses it | What remains |
|---|---|---|---|
| Semantic fragmentation | Teams use different words for the same thing ("claim" and "case") or the same word for different things | `aliases` map every team's term to one entity, everywhere expressions and data are read; alias clashes are errors; lint `DUP001` flags entities that look like duplicates; interfaces give shared shapes across entities | Aliases are per entity type; there is no matching of individual records across systems (entity resolution) |
| Action fragmentation | Approval rules in one system, payment rules in another | Every change is an ontology action under the same rules, whichever door it comes through: agent, API, automation, assistant or MCP | Rules that still live inside connected systems are invisible unless modelled; Autology cannot discover them |
| Auditability gaps | Nobody can say why a claim was approved | Keyed, hash-chained audit of every decision with the facts and rules that led to it; reviews bound to what was shown to the reviewer; outcomes in the same chain; access log of who read what | Single node; the audit key must be managed outside Autology |

Memory fragmentation (decisions forgotten between sessions) is handled by the store: runs, reviews, audit and
outcomes persist, and a paused run resumes in another process with its history intact.

## The five hurdles

| Hurdle | What Autology offers | Honest limit |
|---|---|---|
| Resistance to change | Works beside existing systems (tools call them; write-back updates the graph), people review in a web inbox or from any MCP client | Adoption is an organisational problem; software only lowers the cost of trying |
| Data quality | Type checks on every load and write; competency questions with expected answers; rules evaluate missing facts as unknown and fail closed for reviews, prohibitions and access | No declarative data-quality checks on instances and no deduplication |
| Complexity overload | The MVO pattern, lint for dead states and duplicate entities, modules, and roadmap gates that ask for value before scope | Nothing stops a team from modelling too much; the gates only make it visible |
| Integration effort | `http`, `python` and decision-table tools, write-back with conflict detection, REST API, typed SDKs, MCP | No data connectors or pipelines; each system is wired by hand |
| Skill gaps | A plain JSON format, `describe`, actionable lint messages, `validate`, and worked examples in six domains | No visual ontology editor or rule editor |
