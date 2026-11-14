# Autology — implementation log

## 14 November 2026 — Phase 0 and Phase 1 (workspace foundation)

**Inputs read.** The repository at `5400ad8`, the audit of 13 November (`audit/`), the master instructions of
14 November. The historical PDF was compared through the audit and [current state](AUTOLOGY_CURRENT_STATE_AND_GAPS.md).

**Changed.**

| Commit | Change |
|---|---|
| `4509b97` | `ApiExchange`: the REST dispatcher no longer depends on the HTTP server; the engine refuses negative or malformed `Content-Length` (411, audit GAP-015) and answers unsupported methods with JSON 405 |
| (this commit) | `autology/platform.py`: workspaces, members, use cases, router `/w/<ws>/u/<uc>/api`, `/platform/me`, platform access log; dedicated store per use case and secrets file per workspace; `secrets_file` setting in the engine; Console accepts a use-case base URL; `autology platform` command; `examples/platform`; `docs/workspaces.md`; seven planning documents |

**Tests run.**

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -t .` | 449 tests, OK (2 PostgreSQL tests skipped locally because no database was running; CI runs them) |
| `python -m unittest tests.test_workspaces` | 11 tests OK: membership, router health, methods and body limits, reporting target kept inside the use case, identical 404s, data/run/review/audit/secrets isolation, per-use-case users, Console through the router, token uniqueness, invalid definitions |
| `python -m unittest tests.test_api_exchange` | 3 tests OK |

**Known limitations.** Members and use cases are loaded from `platform.json` at start (no admin API yet). MCP and
company sign-in are single-engine only. One audit key signs every workspace's chains. Each use case's engine holds
its graph in memory. The review inbox is still served by the single-engine server (not by the platform).

**Next increment.** P0-5 (MCP and OIDC per workspace, per-workspace audit keys) and P1-1 (OpenAPI contract), then
P0-1 (external action safety), which gates every connector write.

## 14 November 2026 — stories

| Story | Change | Tests | Behaviour change |
|---|---|---|---|
| GOV-1 (GAP-011) | Firing an automation by hand: the caller is recorded as the run's starter (self-review refused), the automation's condition must hold (else `skipped`), the `start_run` checkpoint applies, and only records the caller may see are fired | `tests/test_gov1_manual_firing.py` (4, written failing first: 3 failed before the fix); suite 453 OK | `POST /api/automations/{name}/run` with an instance no longer forces a run when the condition is false; `tests/test_automation.py` updated accordingly |
| GOV-2 (GAP-012) | Scenario comparisons withhold answers to questions that read a field the user may not read, or a checkpoint-gated field (for admins too); scenario edits to unreadable fields are refused; the assistant's `what_if` withholds answers over fields not sent to the model provider. One helper (`question_refs`) now decides which fields a question reads, for direct answers, comparisons and the assistant | `tests/test_gov2_scenario_fields.py` (5, written failing first: 4 failed before the fix); suite 458 OK | Admins' comparisons now withhold questions over gated fields; before, they were answered without a justification |
