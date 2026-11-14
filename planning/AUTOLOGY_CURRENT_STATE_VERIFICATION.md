# Autology — current state verification

*Verified 14 November 2026 at commit `dfe8b3f` on branch `claude/autology-ontology-agent-4ajjer` (the only working
branch; the other branch, `claude/new-session-aee75a`, is an ancestor from 27 September holding unrelated
video-skill notes). No pull request exists. Every result below was produced again for this document; nothing is
copied from an earlier report without being re-run.*

## 1. How it was verified

| Check | Command or source | Result |
|---|---|---|
| Full suite, current code | `AUTOLOGY_AUDIT_KEY=k python -m unittest discover -s tests -t .` | **559 tests, OK** (2 skipped: PostgreSQL tests; CI runs them against a real PostgreSQL 16) |
| Coverage, current code (before the R1-C increment's tests were added) | `coverage run --branch --source=autology -m unittest discover …; coverage report` | 548 tests; **95.9 % lines** (9,971 statements, 404 missed); 95 % lines + branches |
| The earlier report's commit, re-run in a separate worktree | `git worktree add … a03ed96`, same commands | **472 tests, OK**; coverage **96.8 % lines** (9,228 / 294 missed); the 37 targeted tests **OK** |
| CI runs for every commit | GitHub Actions, workflow `tests`, branch above | runs 18–44; see §3 |
| Code size | `cat autology/*.py \| wc -l` | **15,071 lines in 39 modules**; 64 test files |
| Master instructions file | the uploaded `AUTOLOGY_CLAUDE_CODE_MASTER_INSTRUCTIONS_2026-11-14.md` (two identical uploads, MD5 `c1efa262…`) | first received **11:00:30 UTC** |
| Historical PDF | `Autology-explained.pdf` (produced 12–13 Nov; not in the repository) | claims ~11,000 lines in 32 files and 355 tests |

## 2. The earlier report's claims, checked

The claims come from `planning/AUTOLOGY_PREUVE_EXECUTION_INSTRUCTIONS.md` (commit `a03ed96`, 11:59 UTC).

| Claim | Verified at `a03ed96` | Today | Notes |
|---|---|---|---|
| Phase 0 (repository audit) done | ✅ | ✅ | Planning documents and the 13 Nov audit (`audit/`) |
| Phase 1 (workspace isolation) done or partly done | ✅ partly: REST only | ✅ REST, MCP, OIDC, audit keys, credentials, background jobs | ISO-1–4 since |
| GAP-008, 011, 012, 013, 014, 015 fixed | ✅ each has a passing test | ✅ | `test_one_run_per_record`, `test_gov1`–`gov4`, `test_api_exchange` |
| Phases 2–6 not started | ✅ | ✅ still true | R1 work only; Studio not started (owner condition) |
| 472 passing tests | ✅ 472, OK (re-run) | 559 | |
| 37 relevant tests re-run successfully | ✅ 37, OK (re-run) | — | |
| CI green on Python 3.10 and 3.13 with PostgreSQL | ✅ runs 18–25 success | runs 37–39 failed, 40–44 success (§3) | |
| Coverage ≥ 95 % | ✅ 96.8 % lines locally; CI gate `--fail-under=95` (line coverage) passed | 95.9 % lines (thin margin) | CI measures lines only, not branches |
| Eight commits after receiving the instructions | ⚠️ **Inaccurate** | — | The report counted 10:18–11:44. `5400ad8` (GAP-008, 10:18) **predates** the instructions (received 11:00:30). After receipt and before the evidence commit there were **7** commits (`4509b97` … `e69f06d`); the evidence commit `a03ed96` itself is the 8th |
| Evidence committed as `a03ed96` | ✅ | ✅ | |
| GAP-001–007 open | ✅ then | Fixed (`ac07e66`) | |
| MOD-1–3 not done | ✅ then | Done (`f20ddc1`, `b3a2deb`, `d480abe`) | |
| ACT-1–6 not done | ✅ then | Done (`ac07e66`, `c779566`) | |
| Acceptance tests: 1 passed, 3 partial, 7 not started | ✅ then | 2 verified, 2 partial, 7 not started (§4) | |
| Maturity 47 / 100, not recalculated | ✅ then | Self-assessed ≈ 65, **not independently verified** ([scorecard](AUTOLOGY_MATURITY_SCORECARD.md)) | |

## 3. Commits and CI runs reconciled

Since the instructions arrived, **every commit has exactly one CI run** (runs 18–44, one per push). Before that:
commits made before the workflow existed (before 11 November 08:36) have no run; after it existed, three commits
(`5553822`, `87ac8a8`, `bde1f7e`) were pushed together with a later commit and share its run; run 1 (`9513573`)
failed while CI was being set up. The 44 runs therefore match the pushes, not the commits.

| Runs | Commits | Result |
|---|---|---|
| 18–36 | `4509b97` … `6a23ff5` (Phase 1, GOV-1–5, MOD-1–3, ACT-1–6, ISO-1–3, LEG-1) | success |
| 37–39 | `fd7ab77` (MOD-4), `d92b6da`, `6806549` | **failure**: test jobs and coverage passed on both Pythons; the container smoke test failed (a restarted container was refused its store) |
| 40 | `f0a385a` (fix: release the store lease on shutdown) | success (all jobs) |
| 41–43 | close-out documents | success |
| 44 | `dfe8b3f` (R1-C increment) | success (all jobs, coverage gate included) |
| 45 | `d7de163` (verification documents) | see the run |

Full table per commit: [R1 completion report §3](AUTOLOGY_R1_COMPLETION_REPORT.md).

## 4. Status by capability (statuses as defined in the master prompt, Rule 5)

| Capability | Status | Evidence |
|---|---|---|
| Engine: ontology, planning, governance, approvals, audit, REST, MCP, CLI | Implemented and verified | 559 tests |
| Engine runs without any UI and without Hermes | Implemented and verified | `tests/test_engine_headless.py` |
| UI separation: Console as a separate process | Implemented and verified | `tests/test_console.py` |
| UI separation: review inbox outside the engine | Partially implemented (optional, still served by the engine) | UI-1 (R2) |
| Versioned API contract (OpenAPI, `/api/v1`) | Not started | API-1/2 (R2) |
| Workspace isolation (REST, MCP, OIDC, audit keys, credentials, jobs, stores) | Implemented and verified | [isolation matrix](AUTOLOGY_SECURITY_AND_TENANCY.md) |
| Use cases with independent configuration | Implemented and verified | `examples/platform`, `test_workspaces.py` |
| Use cases with independent readiness status | Not started | REL-3 |
| Ontology integrity (MOD-1–4) | Implemented and verified | R1 report |
| External action safety (ACT-1–6) | Implemented and verified against simulated systems | fault matrix; no real ERP yet |
| Governance closure (GOV-1–5) | Implemented and verified | R1 report |
| Releases Draft → Production, server-side gates | Not started | REL-1/2 |
| Studio, AI Solution Architect, dynamic discovery | Not started | R2 |
| Excel Template Factory | Not started (`openpyxl` approved; evaluated) | R3 |
| Organisational intelligence, Agent Factory | Not started | R3/R4 |
| Integration Hub, Odoo sandbox, Hermes adapter | Not started (tools and pipelines exist) | R4 |
| Generated Workspace UI | Not started (Console exists) | R5 |
| Real AI provider validation | Blocked: needs API keys | AI-1 |
| Real business process / pilot | Blocked: needs a customer and system access | R4–R6 |

**Master acceptance tests (§13 of the instructions):** 10 (external actions) and 11 (existing behaviour kept)
verified; 1 (workspace isolation through every entry point) and 2 (two use cases with different readiness states)
partial; 3–9 not started. Details: [traceability](AUTOLOGY_REQUIREMENTS_TRACEABILITY.md).

## 5. Discrepancies between documentation and code

| Where | Said | Code / truth | Action |
|---|---|---|---|
| Earlier evidence document | 8 commits "since receiving the instructions (10:18 → 11:44)" | `5400ad8` predates the instructions | Corrected here |
| `README.md` | 408 tests, 97 % coverage | 559 tests; 95.9 % | Fixed in `dfe8b3f` |
| `docs/methodology.md` | 122 tests, 98 % coverage | historical | Marked historical in `dfe8b3f` |
| `docs/platform.md` | "multi-tenant separation" not yet included | the platform router provides it | Fixed in `dfe8b3f` |
| `planning/AUTOLOGY_SECURITY_AND_TENANCY.md` | GAP-011–014 and MCP/OIDC/audit-key isolation open | fixed | Rewritten in this pass |
| PRD R2–R4 releases | four releases | the owner's six-release sequence (14 Nov) | [Roadmap](AUTOLOGY_RELEASE_ROADMAP.md) follows the owner's sequence |
| Historical PDF | 11,000 lines, 32 files, 355 tests | 15,071 lines, 39 modules, 559 tests | Background only |

## 6. Known weak points found during verification

- **Coverage margin:** 95.9 % lines against a 95 % gate; `platform.py` is at 65 % (mostly its blocking server loop).
- **The service class grew** from 1,232 to 2,119 lines during R1 (GAP-026), which raises the cost of every R2 change.
- **Migrations:** three schema changes (11, 12, lease table) were added without the ordered, transactional
  migrations GAP-041 asks for.
