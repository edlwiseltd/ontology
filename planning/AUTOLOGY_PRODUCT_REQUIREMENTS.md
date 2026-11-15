# Autology — product requirements

> *Status 14 Nov 2026: requirement-by-requirement status and evidence are in [AUTOLOGY_REQUIREMENTS_TRACEABILITY.md](AUTOLOGY_REQUIREMENTS_TRACEABILITY.md).*

Each requirement has an ID used by the [backlog](AUTOLOGY_IMPLEMENTATION_BACKLOG.md). "Accept" lines are the
acceptance tests; numbers in brackets refer to the master instructions' §13 acceptance tests.

## Workspaces and use cases (R-WS)

- **R-WS-1** Workspaces are isolated server-side at every entry point. *Accept:* two workspaces cannot read or
  modify each other's cases, people, files, agent state, integrations or audit through REST, MCP, SDK, CLI,
  events or exports [1]. **REST: done and tested; others planned.**
- **R-WS-2** A workspace holds several use cases with their own ontology, actors and readiness [2]. **Done** for
  ontology and actors; readiness per use case pending R-RG.
- **R-WS-3** Workspace administration (members, grants, use cases) through an authenticated API with audit, no
  restart. Planned.

## Studio: AI Solution Architect (R-SA)

- **R-SA-1** An administrator describes a business in natural language; the architect proposes a provisional,
  editable model (objects, properties, states, relationships, processes, rules, risks, systems, roles, candidate
  agents), every element labelled with its provenance: AI proposed, user supplied, document extracted, system
  synchronised, human verified [3].
- **R-SA-2** Follow-up questions are generated from the model's gaps (missing facts, unresolved references,
  uncovered risks), each naming the fact it resolves and the evidence expected; never a fixed list [4].
- **R-SA-3** Bulk inputs (template packs, documents, read-only connectors) are preferred to long interviews;
  contradictions are surfaced and safety-relevant ambiguity must be resolved before release.
- **R-SA-4** Every accepted change produces a versioned diff (reusing `versioning.py`), re-validation and a
  readiness update.
- **R-SA-5** The same generic architect handles an upstream Oil & Gas brief and a pharma brief, with no
  sector-specific engine code [3].

## Excel Template Factory (R-XL)

- **R-XL-1** Template packs are generated from the use case's ontology and open questions: instructions, template
  ID and version, stable record IDs, typed columns, required flags, sample rows, dropdowns, units, reference
  columns, owner/source metadata [4].
- **R-XL-2** Upload pipeline: quarantine → safe parse (no formulas or macros executed) → schema, type, unit, ID,
  reference and duplicate checks → diff preview → human confirmation → transactional commit into the authorised
  use case → provenance → readiness update. Row- and cell-level error reports [5]. Reuses `ingest.py`
  (validation, quarantine, lineage, dry run).
- **R-XL-3** Uploads cannot target another workspace; spreadsheet text is never treated as instructions.

## Organisation and agents (R-ORG, R-AG)

- **R-ORG-1** Human organisation (departments, positions, reporting lines, approval limits, substitutes) as data,
  imported from templates or synchronised read-only from an HRIS.
- **R-ORG-2** Recommended access mappings never activate by themselves: grants require an authorised approver;
  requesters cannot approve their own sensitive changes [6].
- **R-AG-1** Agent specifications (mission, scope, contracts, entities, tools, model, limits, triggers, supervisor,
  permitted and forbidden actions, gates, failure policy, tests, success criteria) are proposed, versioned and
  approved before activation; linked to accountable human roles [6].
- **R-AG-2** Skills, executable tools and credentials are distinct; no capability implies authorisation.

## Integration Hub (R-IH)

- **R-IH-1** Capability registry: name, version, provider, schema, read/write effects, scopes, sensitivity,
  idempotency, timeout policy, health, provenance, workspace authorisation, test status.
- **R-IH-2** Read-only connectors first (Odoo 18 first); writes only after the action-safety gates (R-AS).
- **R-IH-3** Hermes optional: its outage does not stop planning, approvals, scheduling or audit [9].

## Action safety (R-AS)

- **R-AS-1** Intent log, idempotency keys, outcome classification, confirmation contracts, `uncertain` state and
  reconciliation; no duplicate execution after timeouts, crashes, retries or resumes [10]. (Audit GAP-001–007.)

## Readiness and releases (R-RG)

- **R-RG-1** Two separate assessments: platform maturity and per-use-case readiness (see
  [readiness doc](AUTOLOGY_READINESS_AND_RELEASE_GATES.md)).
- **R-RG-2** Draft → Simulation → Pilot → Production with immutable releases, approvals and rollback; promotion
  refused server-side when a hard gate fails, whatever the score, including by direct API call [7, 8].
- **R-RG-3** (V2, D11) A configuration release is an immutable, content-addressed snapshot; it is approved by a
  separately authenticated person with release authority who is not the proposer and not a service identity; the
  approval is bound to the fingerprint; activation only of exactly what runs; drift stops execution; rollback is a
  recorded re-activation; runs and review decisions are bound to the configuration they started on.
- **R-RG-4** (V2) Release approval, business-action authorisation and runtime approval stay three distinct
  approvals; a release approval never authorises a business action.

## Governance, identity and autonomy (R-GV, V2)

- **R-GV-1** Governance is evaluated for every step of every run; human involvement is set by policy (rules, risk,
  obligations), not imposed on every action; fully autonomous governed execution stays possible.
- **R-GV-2** Human principals and machine identities are distinguished; a machine never records a human approval
  or settles an external call meant for a person (D11, audit F-02).
- **R-GV-3** Outbound credentials go only to the destinations the operator configured; destinations chosen by the
  other side (redirects, next-page links) stay within the configured origin unless explicitly allowed; secrets never
  appear in errors, logs or audit (audit F-01).
- **R-GV-4** (direction) Criticality-aware autonomy: each action is classified by impact, risk, obligations and
  required evidence, giving ALLOW / REQUIRE APPROVAL / DENY (and possibly simulation-only or deferred); Autology never
  replaces certified safety functions ([architecture B6](AUTOLOGY_ARCHITECTURE_TARGET.md)).

## Extensibility and knowledge (R-EX, R-KN; directions and candidates, V2)

- **R-EX-1** (approved direction) Core + Plugin Runtime: everything extensible except the Core governance and
  security kernel; untrusted plugins run isolated; plugins request, the Core authorises ([B2](AUTOLOGY_ARCHITECTURE_TARGET.md)).
- **R-EX-2** (approved in principle, D7/D10) Multi-provider AI behind provider-neutral interfaces; no confidential
  data to an external provider without approved configuration.
- **R-KN-1** (candidate) Industry Standards & Compliance Hub with versioned, scoped knowledge packs and full source
  governance; only verified, approved requirements become enforceable rules ([B3](AUTOLOGY_ARCHITECTURE_TARGET.md)).
- **R-KN-2** (approved direction) Composable intelligence: no single LLM as sole source of knowledge or authority
  ([B4](AUTOLOGY_ARCHITECTURE_TARGET.md)).
- **R-KN-3** (approved direction) Decision & Action modelling as first-class ontology concepts, with compensation
  for multi-system operations ([B5](AUTOLOGY_ARCHITECTURE_TARGET.md)).

## User interfaces (R-UI)

- **R-UI-1** Studio and the Workspace UI are separately built and deployed; both use only the versioned public API.
- **R-UI-2** The Workspace UI renders the published use case: records, tasks, reviews, recommendations, states,
  explanations; role-aware; accessible; responsive.
- **R-UI-3** OpenAPI contract per API version with backward-compatibility tests and a deprecation policy.
