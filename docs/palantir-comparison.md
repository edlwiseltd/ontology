# Palantir feature map: what Autology has, and what could be built here

This document lists the features of Palantir's platforms and compares each with Autology as it stands in this repository. For every gap it gives the potential to build it here, a rough effort, and a recommendation.

**Autology is independent.** It is not affiliated with, endorsed by, or built on any Palantir product, and it contains no Palantir code. The comparison is about concepts and capabilities only.

**How this was researched.** The feature list comes from Palantir's public documentation, read through web search in November 2026. Two caveats apply:

- `palantir.com` is blocked by this session's network policy, so the pages could not be opened directly. The descriptions rely on search summaries of the official docs, and some of those pages were one to three years old.
- Palantir renames and restructures products often. For example, AIP Agent Studio is now AIP Chatbot Studio. Check the current docs before relying on a detail.

**Effort sizes** are rough estimates for one or two engineers, not validated plans: **S** is days, **M** is two to four weeks, **L** is two to three months, **XL** is six months or more, or a product in its own right.

## Summary

Palantir sells four products. Only two overlap with what Autology does.

| Palantir product | What it is | Overlap with Autology |
|---|---|---|
| **Foundry** | Data and operations platform: pipelines, the Ontology, applications, analytics, security | Partial. Autology covers the Ontology, action, rule and audit concepts. It has none of the data platform or user interfaces |
| **AIP** | AI layer on Foundry: LLM functions, chatbots, evaluations, automations | Substantial. Governed agents over an ontology is Autology's core |
| **Apollo** | Continuous delivery of software to many environments, including air-gapped ones | None. Out of scope |
| **Gotham** | Defence and intelligence analysis platform | None. Out of scope |

Of the 58 feature areas compared below:

| Status | Count | Meaning |
|---|---|---|
| **Have** | 23 | Autology has a working equivalent |
| **Partial** | 17 | The concept exists but is narrower, or has no user interface |
| **Missing** | 14 | Not present |
| **Out of scope** | 4 | Not sensible to build here |

The pattern is clear. Autology is strongest where Palantir's *ideas* are: an ontology that agents act through, governed actions, human review, audit, impact analysis and scheduling. It is weakest where Palantir's *product mass* is: data pipelines, a scalable object store, end-user applications, analytics and fine-grained security.

**The practical conclusion:** do not try to rebuild Foundry. Build the missing pieces that make the ontology-and-agent core production-grade, and integrate existing open-source tools for the data platform and dashboards.

## 1. The Ontology

This is the heart of both systems.

| Palantir feature | What it does | Autology today | Status | Potential here | Effort |
|---|---|---|---|---|---|
| Object types and properties | Model entities and their attributes, mapped from datasets | Entities with typed attributes, lifecycle states and sensitivity tags | **Have** | — | — |
| Link types | Typed relationships between object types | Relationships with cardinality; traversed by queries and impact rules | **Have** | — | — |
| Action types | Governed, auditable changes to objects, with parameters and rules | Actions with preconditions, outcomes, effects, and read and write declarations | **Have** | — | — |
| Submission criteria | Conditions on the user, parameters and objects that decide whether an action may run | Governance rules: mandatory steps, prohibitions, read, write and action access, with conditions | **Have** | — | — |
| Side effects: notifications and webhooks | Notify people or call external systems when an action runs. A writeback webhook runs first and blocks the edit if it fails | HTTP tools call external systems, and a failed tool blocks the step. Notifications by role for reviews and automations, delivered to webhooks (Tier 2) | **Partial** | Medium. An explicit "call before commit" ordering | S |
| Functions | Code-based logic over objects, usable in actions and applications | Python tool handlers and decision tables. No reusable, versioned function registry | **Partial** | High. A function registry with typed inputs is a natural extension of the tool registry | M |
| Interfaces | Shared shape that several object types implement | `interfaces` with typed attributes; entities declare `implements`; validated, versioned, queryable (competency questions, API listings) and typed in the generated SDKs (Tier 2). Rules still name concrete entities | **Have** | — | — |
| Object storage and indexing | Scalable store for billions of objects, with search and incremental indexing | SQLite store for the graph, runs, audit and reviews (Tier 1). Single node, no search index | **Partial** | Medium. A PostgreSQL implementation of the same `Store` interface. Palantir-scale indexing is not realistic | L |
| Multiple objects per case | Actions operate on object sets of any size | Multi-record entities, per-record actions (`for_each`), quantified goals, per-record mandatory steps (Tier 1) | **Have** | — | — |
| Object sets and search | Filter, search and aggregate objects | `KnowledgeGraph.query` with filters, traversals and aggregates. No full-text search | **Partial** | High | M |
| Ontology Manager | Visual editor for the ontology | JSON files plus validate, lint and diff on the CLI | **Partial** | Medium. A web editor is a user-interface project | L |
| Ontology SDK (OSDK) | Generated, typed client libraries in TypeScript, Python and Java | Typed Python and TypeScript clients generated from the ontology (entities, states, case shape, per-entity, per-question and per-goal helpers, fingerprint check), from the CLI or the running server (Tier 2). No Java | **Have** | — | — |
| Scenarios (what-if) | Apply edits in a sandbox, compare outcomes, then commit or discard | Scenarios fork the graph; edits, governed simulated actions and impact events; comparison of answers, plans and schedule KPIs; commit with conflict detection (Tier 2). API and CLI, no visual editor | **Have** | — | — |
| Foundry Rules | Business users manage rule logic without code | Rules and decision-table tools are edited as JSON | **Partial** | Medium. Needs a rule-editing interface | M–L |

## 2. AI and agents (AIP)

| Palantir feature | What it does | Autology today | Status | Potential here | Effort |
|---|---|---|---|---|---|
| AIP Logic | No-code builder for LLM-powered functions that read the Ontology and call actions | Reasoners choose among ontology-valid actions under governance. Code and config only | **Partial** | Medium. The engine exists. The no-code builder is the missing part | L |
| AIP Chatbot Studio | Build chat assistants that use Ontology data and tools | A governed assistant in the API and inbox: tools run as the signed-in user with their permissions and row and field access; it can start governed runs and simulate scenarios but never decide reviews; provider-neutral backend, Claude by default (Tier 2). No builder interface | **Have** | — | — |
| AIP Evals | Test suites for LLM functions: compare models and prompts, analyse failures | Evaluation suites for reasoners: expectations on status, actions, order, reviews and final state; pass rate, agreement, fallbacks, cost, latency and consistency per reasoner; failure analysis; CI gate (Tier 2, [`evals.md`](evals.md)) | **Have** | — | — |
| Bring your own model | Register external or self-hosted models; many providers supported | `ChatModel` interface. The Anthropic adapter ships; others plug in through a function wrapper | **Have** | Add tested adapters for other providers | S each |
| AIP Observability | Tracing, logs and run history for functions, actions and models | Hash-chained audit log, metrics, saved runs, API access log, and OpenTelemetry export: each run as a trace with step, tool, review and denial spans, to any OTLP collector (Tier 2). No built-in trace viewer | **Have** | — | — |
| Automate | Run actions or send notifications when Ontology data changes | Automations on data changes, deadlines and schedules start governed runs on cases built from the graph, write results back and notify people (Tier 2) | **Have** | — | — |
| Human review of AI edits | Stage AI-proposed changes for a person to approve | Human-review rules with context-rich requests; policy, console and HTTP approvers | **Have** | — | — |
| AIP Threads and AIP Analyst | Ad-hoc chat with documents and data exploration | Not present | **Missing** | Low priority. Generic chat tools already do this | M |
| AIP Assist | In-product help assistant | Not present | **Out of scope** | — | — |
| Model cost and usage tracking | Track model usage per workload | Token usage and cost per decision, rolled into metrics | **Have** | — | — |

## 3. Process, automation and scheduling

| Palantir feature | What it does | Autology today | Status | Potential here | Effort |
|---|---|---|---|---|---|
| Machinery | Model processes as flows of automations and manual steps; mine event logs; monitor performance | Processes are derived from the ontology at run time. Metrics and gap analysis come from audit logs. No process-mining views | **Partial** | Medium. Process metrics per step and bottleneck reports from the audit data | M |
| Dynamic Scheduling | Build scheduling and resource-allocation workflows on the Ontology | `ScheduleAgent`: ontology-driven job-shop scheduling with OR-Tools CP-SAT, validation and Gantt output | **Have** | Add calendars, downtime windows and schedule stability | M |
| Change impact analysis | Trace what an event affects through the Ontology | `ImpactAgent` with declared impact rules and reasoning chains | **Have** | Incremental analysis for high event rates | M |
| Approvals | Request, approve and then apply changes, with a decision record | Human-review gates on actions. No general request-and-approve workflow for ontology or config changes | **Partial** | High. Reuse the review mechanism for ontology releases | S–M |
| Checkpoints | Ask for a justification before sensitive actions | `checkpoint` rules require a written justification before revealing a field, starting or resuming a run, declining or approving a review, writing data or committing a scenario; recorded in a tamper-evident table; the assistant cannot supply one (Tier 2) | **Have** | — | — |

## 4. Security and governance

| Palantir feature | What it does | Autology today | Status | Potential here | Effort |
|---|---|---|---|---|---|
| Projects and roles | Discretionary access: owner, editor, viewer per project | API users with tokens, permissions (read, run, review, audit, admin) and data roles (Tier 1). No projects or single sign-on | **Partial** | Medium. Projects and OIDC sign-in on top of the API | M |
| Markings | Mandatory, all-or-nothing access labels that travel with derived data | Sensitivity tags on attributes and role-based read rules. Nothing propagates to derived data | **Missing** | Medium. Propagation needs data lineage, which is also missing | L |
| Restricted views and granular policies | Row-level access by comparing user attributes with data values | `row_access` rules hide records from agents and API users; field rules redact attributes (Tier 1) | **Have** | — | — |
| Classification-based access controls | Clearance-level controls for government use | Not present | **Out of scope** | — | — |
| Audit logging | Append-only log of every read, write and permission change | HMAC-keyed hash chain of every agent decision, review and tool call, with recorded chain heads and reviewer identities: tamper-evident, not tamper-proof (Tier 1, hardened after review). Every API request, including failed sign-ins, and every assistant tool call in an access log whose tables reject updates and deletes (Tier 2). Configuration changes are not logged | **Have** | — | — |
| Sensitive Data Scanner | Scan datasets for sensitive patterns and apply markings | Lint flags tagged sensitive fields without access rules. No scanning of actual data | **Partial** | High. A regex and model-based scanner over graph data | S–M |
| Download and export controls | Restrict and record data leaving the platform | Not present | **Missing** | Low until there is a service and user interface | M |
| Agent suspension | Not a named Palantir feature | Agents that repeatedly propose forbidden actions are suspended | **Have** | — | — |

## 5. Data integration

This is Foundry's largest area and Autology's largest gap.

| Palantir feature | What it does | Autology today | Status | Potential here | Effort |
|---|---|---|---|---|---|
| Data Connection | Connectors and credential management for external sources | HTTP tool adapters with secrets from environment variables. No data connectors | **Missing** | Integrate, do not build: use an open-source ingestion tool | M to integrate |
| Pipeline Builder and Code Repositories | Build batch and streaming transformation pipelines, visually or in code | Not present | **Missing** | Integrate an existing transformation and orchestration stack | M to integrate |
| Datasets, transactions and versioning | Versioned datasets with transactional updates | Ontology versions are tracked. Data is not versioned | **Missing** | Low. This is a data-platform feature | XL |
| Data Lineage | Graph of how every dataset and object was derived | Reasoning chains for impact and decisions. No data lineage | **Missing** | Medium. Record the source of each graph instance at load time | M |
| Data health checks | Automated quality checks on datasets | Ontology lint, schema validation of graph data, competency questions with expected answers | **Partial** | High. Declarative data-quality checks on graph instances | S–M |
| Streaming | Real-time pipelines | Not present | **Missing** | Low priority | L |
| Time series | Time-series storage and analysis | Not present | **Missing** | Medium, if a project needs sensor or telemetry data | L |
| Media sets | Documents, images and video as first-class data | Not present | **Missing** | Low priority | L |

## 6. Applications and analytics

Autology has no graphical interface at all. Its output is a CLI, files and one static Gantt chart.

| Palantir feature | What it does | Autology today | Status | Potential here | Effort |
|---|---|---|---|---|---|
| Workshop | Low-code builder for operational applications on the Ontology | Not present | **Missing** | Medium. Building a low-code builder is a product in itself. A fixed set of screens is realistic | XL for a builder, L for fixed screens |
| Slate | Code-first custom applications | Not present | **Missing** | Unnecessary. With a REST API, any web framework serves this purpose | — |
| Review and operations inbox | Where people approve, reject and monitor work | Web inbox: pending reviews with rules, facts and history; runs with steps and audit verification; start runs; browse objects (Tier 1); notifications and automations (Tier 2) | **Have** | — | — |
| Object Explorer | Search and browse objects | Object listing and detail in the API and inbox, access-filtered (Tier 1). No full-text search | **Partial** | Medium. Search and filters | M |
| Vertex | Visual graph exploration and simulation | Graph queries and impact chains as text | **Partial** | Medium. A graph view of impact results would be valuable | M |
| Quiver and Contour | Point-and-click analysis of objects and large tables | Not present | **Missing** | Integrate an open-source business-intelligence tool | S to integrate |
| Notepad | Reports that embed live data | Markdown compliance and readiness reports | **Partial** | Low priority | S |
| Geospatial maps | Map-based applications | Not present | **Missing** | Low priority unless a project needs it | L |

## 7. Developer toolchain and delivery

| Palantir feature | What it does | Autology today | Status | Potential here | Effort |
|---|---|---|---|---|---|
| REST API | Programmatic access to objects, actions and queries | REST API: objects, questions, runs, reviews, audit, report and score, with token auth and per-user access (Tier 1) | **Have** | — | — |
| Foundry Branching | Change pipelines, ontology and applications on a branch, test, then merge | Ontology files live in git. Semantic diff and version checks exist. No branch-aware runtime | **Partial** | Medium. Git plus the diff tool covers most of the need | S–M |
| Foundry DevOps and Marketplace | Package resources into versioned products and install them across environments | Ontology modules with imports, a version registry and release checks. No packaging | **Partial** | High. Package an ontology, tools and policies as one installable unit | M |
| Compute modules | Run custom containers inside the platform | Not present | **Out of scope** | Use your own container platform | — |
| Apollo | Continuous delivery across many environments, including air-gapped ones | Not present | **Out of scope** | Use standard CI/CD | — |

## 8. What to build, in order

The gaps differ a great deal in value. This order follows what each step unlocks.

**Tier 1: make the core production-grade.** These remove the limits that block real projects. **Done** — see [`platform.md`](platform.md).

| # | Build | Why | Status |
|---|---|---|---|
| 1 | Persistent store for the graph, runs and audit log | Nothing survived a restart | Done: SQLite store with a tamper-evident audit log |
| 2 | Multiple objects per case, with row-level access | The largest functional gap against Palantir's object model | Done: multi-record entities, per-record actions, `row_access` |
| 3 | REST API service with authentication | Lets many projects and applications use one deployment | Done: token auth, permissions, per-user data access |
| 4 | Review and operations inbox (web) | People need somewhere to approve and monitor | Done: web inbox with asynchronous reviews |

**Tier 2: close the AIP gaps.** These are well-defined and build directly on existing code. **Done** — see [`platform.md`](platform.md) and [`evals.md`](evals.md).

| # | Build | Effort |
|---|---|---|
| 5 | Triggers and schedules (Automate) | Done: automations, case templates, write-back, notifications, webhooks |
| 6 | Evaluation harness for reasoners (Evals) | Done: `autology eval`, see [`evals.md`](evals.md) |
| 7 | Scenarios: fork, simulate, compare, commit | Done: API, CLI, conflict-checked commit |
| 8 | Generated typed SDK (OSDK) | Done: Python and TypeScript, `autology sdk` and `GET /api/sdk/{lang}` |
| 9 | Chat front end over governed tools (Chatbot Studio) | Done: governed assistant, API and inbox |
| 10 | Tracing export, justification checkpoints, notifications, interfaces | Done, plus an API access log |

**Tier 3: integrate, do not build.** Mature open-source tools already cover these.

| Need | Approach |
|---|---|
| Data ingestion and pipelines | An open-source ingestion and transformation stack that loads the graph store |
| Dashboards and table analysis | An open-source business-intelligence tool reading the store |
| Delivery | Standard CI/CD and containers |

**Not worth pursuing:** a low-code application builder, a dataset versioning platform, Apollo, Gotham, and government classification controls. Each is a product that took Palantir years, and none is needed for the ontology-and-agent core to be useful.

## 9. Where Autology is already different

A few things in this repository have no direct counterpart in the Palantir docs reviewed. That is not a claim that Palantir lacks them, only that they were not found.

- **Processes are derived, not drawn.** The planner works out the path to a goal from the ontology at run time and replans after every outcome.
- **Readiness scorecard.** A scored assessment of a deployment with evidence coverage and roadmap gates.
- **TCO and ROI model** fed by measured run data.
- **Zero dependencies and open formats.** The core runs on the Python standard library, and ontologies export to OWL and JSON-LD.
- **Agent suspension** after repeated rule violations.

## Sources

Palantir documentation and publications found through search:

- [Foundry application reference](https://www.palantir.com/docs/foundry/getting-started/application-reference)
- [Ontology overview](https://palantir.com/docs/foundry/ontology/overview/) and [core concepts](https://www.palantir.com/docs/foundry/ontology/core-concepts)
- [Ontology-aware applications](https://www.palantir.com/docs/foundry/ontology/applications)
- [Action types overview](https://www.palantir.com/docs/foundry/action-types/overview), [submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria), [webhooks](https://www.palantir.com/docs/foundry/action-types/set-up-webhook)
- [Functions](https://www.palantir.com/docs/foundry/functions/use-functions) and [interfaces](https://www.palantir.com/docs/foundry/interfaces/interface-overview)
- [AIP overview](https://www.palantir.com/docs/foundry/aip/overview), [AIP features](https://www.palantir.com/docs/foundry/aip/aip-features), [AIP architecture](https://www.palantir.com/docs/foundry/architecture-center/aip-architecture)
- [AIP Logic](https://www.palantir.com/docs/foundry/logic/overview), [AIP Evals](https://www.palantir.com/docs/foundry/aip-evals/overview), [Chatbot Studio](https://palantir.com/docs/foundry/agent-studio/getting-started)
- [Supported LLMs](https://www.palantir.com/docs/foundry/aip/supported-llms) and [bring your own model](https://www.palantir.com/docs/foundry/aip/bring-your-own-model)
- [Vertex scenarios](https://www.palantir.com/docs/foundry/vertex/scenarios-overview)
- [Security overview](https://www.palantir.com/docs/foundry/security/overview), [markings](https://www.palantir.com/docs/foundry/security/markings), [projects and roles](https://www.palantir.com/docs/foundry/security/projects-and-roles), [restricted views](https://www.palantir.com/docs/foundry/platform-security-management/manage-restricted-views/index.html), [granular policies](https://www.palantir.com/docs/foundry/platform-security-management/manage-granular-policies)
- [Approvals](https://www.palantir.com/docs/foundry/approvals/overview) and [download controls](https://www.palantir.com/docs/foundry/security/download-controls)
- [Foundry DevOps](https://www.palantir.com/docs/foundry/foundry-devops/overview), [branching support](https://palantir.com/docs/foundry/foundry-branching/supported-functionality), [Developer Console and Marketplace](https://www.palantir.com/docs/foundry/developer-console/marketplace-installation)
- [Apollo technical whitepaper](https://www.palantir.com/assets/xrfr7uokpv1b/3B5KbQ9ujsiDCX4Tnfz3Hy/8d3ee9a6911665f036ce3d28c19cfa0d/PalantirApolloTechnicalWhitePaper.pdf)
- [Audit logging at Palantir](https://blog.palantir.com/building-trust-at-scale-33f6e2f5f8f9)
- Announcements: [October 2025](https://www.palantir.com/docs/foundry/announcements/2025-10), [November 2025](https://www.palantir.com/docs/foundry/announcements/2025-11), [May 2026](https://www.palantir.com/docs/foundry/announcements/2026-05)
