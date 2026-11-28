# Autology — R2 first slice: workspace shell, use-case management, Draft → Simulation → Pilot

> **Update (14 Nov, later):** the interim Python Studio shell (`studio/server.py`, `tests/test_studio_shell.py`) was replaced by the Next.js Studio (`studio/web`, owner decision D9); its separation guarantees moved to `tests/test_studio_separation.py`, `studio/web/tests` and `studio/web/e2e`. See [the Studio frontend ADR](AUTOLOGY_STUDIO_FRONTEND_ADR.md).

*14 November 2026 · branch `claude/autology-ontology-agent-4ajjer`. Scope set by the owner: "start R2 only with a
narrow slice: Workspace shell in Studio, use-case management, and draft-simulation-pilot states, with no ERP write
integrations or real deployments." Nothing here writes to an ERP, deploys anything or authorises production.*

## 1. What was built

| Part | Where | What it does |
|---|---|---|
| Lifecycle registry | `autology/lifecycle.py` (new) | Stage per use case in `<data_dir>/lifecycle.db`; checks per target stage; append-only history chained with the workspace's derived audit key |
| Use-case management and stage API | `autology/platform.py` | `GET /platform/templates`; `GET/POST /platform/workspaces/<ws>/use-cases`; `GET …/<uc>`; `GET …/<uc>/checks?to=`; `POST …/<uc>/stage`; stage in `/platform/me` |
| Use cases from templates | `autology/platform.py`, `examples/platform/platform.json` | The operator lists approved configurations (`"templates"`); a workspace administrator creates use cases from them only; created use cases reload at start |
| Studio shell (interim) | `studio/` (new, top level) | Separate process (`python -m studio --platform URL`); sign-in, workspace header, use-case list with stages, create from template, readiness checks, stage moves, history |
| Documentation | `docs/workspaces.md`, `studio/README.md` | Routes, checks, limits |

## 2. Acceptance criteria and evidence

Each criterion is checked by the named tests. "Verified" means by repository tests; nothing here was reviewed
independently or tried with real users.

| # | Criterion (measurable) | Tests | Status |
|---|---|---|---|
| L1 | Every use case starts in `draft`; a use case's configuration cannot set its stage | `test_r2_use_case_lifecycle.StageTests.test_every_use_case_starts_in_draft_and_me_shows_the_stage`, `…test_a_use_case_configuration_cannot_set_its_own_stage` | Implemented and verified |
| L2 | Forward moves go one step at a time (`draft → pilot` = 409); `production` = 403 from every stage, for every caller, including the dry-run check | `…test_stages_advance_one_step_at_a_time_and_production_is_always_refused` | Implemented and verified |
| L3 | A forward move is refused (409, failing checks returned) unless every check passes at the moment of the move. Simulation: valid configuration, workspace-keyed audit, no quarantined record. Pilot: those, engine demo mode off, every reviewer role held by a named member, every audit chain verifies, no external call awaiting reconciliation, ≥ 1 run completed since entering simulation, configuration unchanged since simulation | `…test_simulation_requires_audit_chains_signed_with_the_workspace_key`, `…test_pilot_is_refused_while_the_engine_runs_in_its_own_simulation_mode`, `…test_pilot_needs_a_run_completed_after_entering_simulation`, `…test_pilot_is_refused_while_an_external_call_waits_for_reconciliation`, `…test_pilot_is_refused_when_an_audit_chain_does_not_verify`, `UseCaseManagementTests.test_a_created_use_case_cannot_reach_pilot_until_reviewers_are_named` | Implemented and verified |
| L4 | Moving back needs a reason (400 without) and no checks; every move records author (`member@workspace`), reason, checks and fingerprint | `…test_moving_back_needs_a_reason_but_no_checks`, `…test_pilot_needs_a_run_completed_after_entering_simulation` | Implemented and verified |
| L5 | Only workspace administrators create use cases and move stages (403 for other members); another workspace, an ungranted or unknown use case all get the same 404; refusals go to the platform access log | `…test_only_workspace_admins_move_stages_and_other_workspaces_get_404`, `UseCaseManagementTests.test_creation_is_refused_for_non_admins_other_workspaces_and_bad_input` | Implemented and verified |
| L6 | The history is tamper-evident (an edited entry ⇒ reported `draft` with an integrity problem, forward moves 409); an entry copied to another workspace does not verify; a stage is `stale` when the fingerprint changes; stages survive a restart | `…test_an_edited_stage_history_is_detected_and_blocks_forward_moves`, `…test_a_history_entry_does_not_verify_in_another_workspace`, `…test_a_stage_is_stale_when_the_configuration_changes`, `…test_stages_survive_a_restart` | Implemented and verified |
| L7 | Use cases are created only from approved templates (bad id, unknown template, duplicate refused); they get their own store; the workspace credential scope (ISO-4) applies; an id whose directory holds data is never reused; they reload after a restart; a removed template stops the platform loudly; one created while running gets its scheduler | `UseCaseManagementTests` (8 tests) | Implemented and verified |
| S1 | Studio imports nothing from `autology`, the engine imports nothing from `studio`, and Studio is not in the engine's wheel | `test_studio_shell.SeparationTests` | Implemented and verified |
| S2 | Studio forwards only GET/POST under `/platform/` and `/w/`, only `Authorization` and `Content-Type`; no redirect followed; bodies need a valid length ≤ 1 MB; 502 when the platform is down | `test_studio_shell.ForwardingTests` (4 tests) | Implemented and verified |
| S3 | The page has a strict CSP (no `unsafe-*`), no inline script, style or handler; the script never parses platform data as markup | `ForwardingTests.test_the_page_has_a_strict_policy_and_no_inline_script` | Implemented and verified (static checks; no browser security test) |
| S4 | Through Studio, an administrator lists use cases, creates one from a template and moves it to simulation; every refusal (401, 403, 404, production 403) is the platform's | `test_studio_shell.EndToEndTests` (2 tests) | Implemented and verified (HTTP level) |
| S5 | The shell works in a real browser at desktop and phone widths | Manual Playwright run on 14 Nov (sign in, check, move, create, refused pilot shown with the failing check); not in CI | Implemented but not fully verified (no automated browser test in CI) |

Totals: 23 new lifecycle tests, 10 new Studio tests. Full-suite and coverage figures: §5.

## 3. What this slice does not do (and must not be read as doing)

| Item | Status | Where it belongs |
|---|---|---|
| Stages change what the engine allows at run time (e.g. a draft use case cannot act) | Not started: stages are governance records only | REL-1 |
| Immutable, content-addressed releases; Suspended; Rollback; runs pinned to a release (GAP-020) | Not started | REL-1 |
| Separation of duties: the person promoting is not the approver; second approver | Not started; blocked on **D11** (pending) | REL-2, ADM-1 |
| Gates of acceptance test 8 (a high score with a critical failure is refused) | Partially implemented: hard checks exist, no score yet | REL-2, REL-3 |
| Member and grant administration through the API; renaming or archiving use cases; creating workspaces | Not started (created use cases are open to administrators only) | ADM-1 |
| Studio built from a versioned OpenAPI client | Not started (API-1/2 not started) | STU-1 |
| Final Studio technology | **Open owner decision D9**; this shell is interim and replaceable | D9 |
| Production stage | Refused by design (**PROD**) | Owner decision |
| ERP writes, real deployments, real data, real pilot customer | Not done and not authorised (**D6** sandbox only, **D15**, **D16** pending) | R4 and owner decisions |

**Order change.** The roadmap placed API-1/2, ARC-0, MIG-1 and QA-1 before ADM/REL/STU. The owner asked for this
slice first; the prerequisites are still open, and this slice adds to the service-size problem only through
`platform.py` (+≈150 lines), not `server.py`.

## 4. Decisions kept open (not made here)

Deployment model beyond "isolated pilots first" (D1 detail, D2, D3), licensing review (D5), providers and data
residency (D7 adapters, D10), Studio technology (D9), second approver (D11), production ERP writes (D15), real
pilot (D16). The engineering choices made inside the slice are reversible defaults, listed so the owner can
overrule them:

| Default | Why | Reversible by |
|---|---|---|
| Pilot requires ≥ 1 completed run since simulation, and every reviewer role held | Minimum evidence that the use case was exercised and that approvals have owners | Changing `lifecycle.py` checks |
| Moving back never needs checks | Moving to a safer stage must never be blocked | Same |
| Use cases may only be created from operator-approved templates | A workspace-supplied configuration could name another workspace's files or credentials | ADM-1 design |
| Stage moves by workspace administrators alone | D11 (second approver) is pending | REL-2 once D11 is decided |

## 5. Evidence

| Item | Value |
|---|---|
| Full suite (local, before the push) | `AUTOLOGY_AUDIT_KEY=k coverage run --branch --source=autology -m unittest discover -s tests -t .`: **592 tests, OK** (2 PostgreSQL tests skipped locally; CI runs them) — 559 before the slice, +33 new |
| Coverage (engine package) | **96.4 % lines** (10,243 statements, 365 missed; 95.4 % lines + branches); `lifecycle.py` 98.0 %, `platform.py` 97.1 %. Studio is outside the engine package and not in this figure |
| Browser check | Playwright (Chromium), 1200 px and 390 px: sign-in, readiness checks, Simulation move, creation from template, refused Pilot move showing its one failing check; no console error other than that expected 409 |
| Commit and CI | [`77b9a59`](https://github.com/edlwiseltd/ontology/commit/77b9a59) → [run 48](https://github.com/edlwiseltd/ontology/actions/runs/43617826148): **success** on every job (tests and coverage gate on Python 3.10 and 3.13 with PostgreSQL, wheel, Docker image smoke test). The R1 closure note, [`6df0911`](https://github.com/edlwiseltd/ontology/commit/6df0911) → [run 47](https://github.com/edlwiseltd/ontology/actions/runs/43615992861): success |
