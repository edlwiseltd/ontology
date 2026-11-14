# Autology Studio — UI/UX specification (reconciled with the repository)

*14 November 2026. Source: the owner's package `AUTOLOGY_STUDIO_UI_UX_PRODUCT_SPEC_2026-11-14.md` and master prompt
(not copied here; this file records the decisions taken from them and where the repository differs).*

## 1. Product direction kept as given

Studio is an AI-first enterprise architecture workbench: *Describe → AI proposes → Visualise → Inspect/edit →
Validate → Gather evidence → Simulate → Governed release*. The engine is authoritative for schemas, rules,
permissions, execution, evidence, audit, scores and releases; Studio owns presentation and interaction only.
Next.js + React + TypeScript (D9, approved). One model, many synchronised views; AI output is provisional until a
person accepts it; every write is validated and authorised by the server; Production stays unavailable (PROD).

## 2. Differences between the package and the repository (verified 14 Nov)

| The package says | The repository shows | Consequence |
|---|---|---|
| "A Draft use case can currently still run" | Fixed: execution gates (R2 increment 1) and the HTTP-approver/webhook bypass fix; CI runs 50 and 54 | Studio shows the engine's execution state; it does not need to warn about this risk any more |
| Immutable releases and rollback not implemented | Still not implemented | Releases screen Blocked |
| Reported 592 tests, run 48 | Now 643+ tests (GAP-009, GAP-018, gates, API-1 since) | Figures in the [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md) |
| Versioned API with a generated client | API-1 contract for engine routes (OpenAPI 3.1, contract tests); no `/api/v1` yet (API-2); platform routes not in the contract | Hand-typed client for platform routes; generated client later |
| JSON Schema baseline `docs/ontology.schema.json` | Present (MOD-1) | Kept as the single source of truth |
| Existing minimal Studio shell | Was Python + plain JS | Migrated to Next.js and retired, all functions covered by browser tests |

## 3. Interaction rules (adopted)

- Loading, empty, unavailable, denied, stale and conflict states are first-class (sign-in refused, platform
  unavailable, stale stage and integrity-problem warnings exist today; revision conflicts arrive with editing).
- Hidden or disabled controls are conveniences; the browser tests prove the server refuses direct calls.
- AI suggestions (when built) are visually provisional (dashed), carry provenance and confidence, and are
  accepted or rejected individually through the engine.
- Node positions are presentation metadata, never business schema.
- Desktop-first editing; mobile supports overview, history, checks and stage moves (tested at 390 px).

## 4. Ontology and validation

JSON Schema (MOD-1) stays authoritative. An RDF/SHACL projection and a LinkML comparison are allowed only as a
separately labelled, reversible experiment on synthetic data; not started. SHACL never authorises execution or
promotion.

## 5. Increment plan

| Increment | Content | Status |
|---|---|---|
| 0 | This reconciliation, screen map, ADR, API matrix, D9 recorded | Verified (documents) |
| 1 | Next.js workbench: sign-in, catalogue, overview, stage moves, creation from templates, read-only ontology canvas with list and inspector, themes, relay, CI job | Verified (unit + browser tests; CI pending at writing) |
| 2 | Draft model editing with validation anchors; AI Architect proposals | **Blocked** on engine draft-model and architect APIs (and D7/D10 for real providers); a labelled demo-only prototype is possible meanwhile |
| 3 | Readiness score, releases, independent approval | Blocked on REL-1/2/3, D11 |
| 4 | Process/org/agent/data views, Excel (R3), Agent Factory (R4), Workspace UI (R5) | Planned |

## 6. Measured performance (Increment 1)

Browser test, Chromium headless, 1280×860, local platform: the Model tab rendered the 5-entity claims ontology in
93 ms (click to first node). Projection unit test: 300 entities laid out in under 250 ms (Node 22). Larger graphs
are not yet measured on screen; no claim beyond these figures.
