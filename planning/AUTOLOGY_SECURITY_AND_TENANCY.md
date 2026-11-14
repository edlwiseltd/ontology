# Autology — security and tenancy

*Updated 14 November 2026 at `dfe8b3f`. Statuses follow the master prompt's Rule 5; "Verified" means a test in
`tests/` passes in CI.*

## 1. Threat model

| Asset | Threat | Control | Status |
|---|---|---|---|
| Workspace data | Member of A reads or writes B's data | Token → one member of one workspace; identical 404s; per-use-case engine knows only its workspace's members; separate stores | Verified |
| Workspace existence | Enumeration of other customers | Identical 404 for foreign, ungranted, unknown and malformed paths | Verified |
| Integration credentials | One workspace's configuration names another's secret | Environment variables scoped by workspace prefix, checked at load (ISO-4) | Verified |
| Assistant key | Leak across workspaces, to logs, the browser, the model | Per-workspace owner-only secrets file; key never returned or logged | Verified |
| Model provider | Confidential values sent to the model | `chat_redact`; answers over redacted fields withheld (GOV-2) | Verified |
| Approvals | Self-approval, approval through another path | Self-review refused on every path incl. manual automation firing (GOV-1); decisions recorded once and never reopened (ACT-5) | Verified |
| Hidden fields | Leak through derived endpoints | Row/field rules incl. scenarios (GOV-2); entry-point matrix | Verified |
| Agent authority | Agent acting beyond the requester | Requester ∩ agent roles; hidden records refuse the run; least-privilege service identities (GOV-3, GOV-5) | Verified |
| External actions | Duplicates, false success, lost calls | Journal, idempotency keys, outcome classes, confirmation, reconciliation (ACT-1–6) | Verified against simulated systems |
| Audit | Undetected rewriting, chains moved between runs or workspaces | Keyed chains, sealed run records (GOV-4), per-workspace keys (ISO-2) | Verified; external anchoring not built |
| Store integrity | Two writers diverge | One writer per store (MOD-4) | Verified (short-term remedy) |
| Availability | Oversized bodies, slow integrations | Body limits (GAP-015) | Partial: GAP-021, GAP-057 open |
| Prompt and document injection | Instructions hidden in data, spreadsheets, documents | Models choose only among governed valid actions; tools write only declared, typed fields | Partial: GAP-045; uploads planned with "data, never instructions" handling (R2/R3) |
| Operator-installed code | Python tools read across workspaces | Trusted operator code; not sandboxed | Documented limitation |

## 2. Roles

| Role | Scope | Can |
|---|---|---|
| Platform operator | Platform | Edit `platform.json` and use-case configurations, hold the audit key, run backups |
| Workspace admin | One workspace | `admin` in every use case of that workspace |
| Member | One workspace, granted use cases | Per use case: `read`, `run`, `review`, `audit`, `ingest`, `reconcile`, `admin`; ontology roles; reviewer roles; `run_as` grants per agent |
| Agent | One use case | Its roles ∩ the requester's; or a service identity's roles for automations; never decides reviews or grants rights |
| Service identity | Named agents of one use case | The least roles an automation needs, declared by the operator |

Planned: approval of grant changes by a second administrator (ADM-1), substitute approvers, time-bound grants.

## 3. Isolation test matrix

Cross-workspace means workspace A ↔ B. Cross-use-case means two use cases of the same workspace: **no implicit
access** (defined policy; explicit sharing is planned with workspace administration).

| Path | Cross-workspace | Cross-use-case | Evidence |
|---|---|---|---|
| REST through the router | Refused (identical 404), every method | Refused unless granted | `test_workspaces.py`: `test_members_see_only_…`, `test_foreign_or_unknown_…`, `test_data_written_…` |
| Write paths (objects, runs, reviews, scenarios) | Refused | Refused | `test_workspaces.py`: `test_runs_reviews_and_audit_stay_inside_the_workspace` |
| Entry points by permission inside a use case | — | — | `test_entry_point_matrix.py` |
| MCP | Only the member's use case in their workspace | Only the named, granted use case | `test_iso1_mcp_per_workspace.py` |
| Console | Only the use case it points at | same | `test_workspaces.py`: `test_the_console_talks_to_one_use_case_through_the_router` |
| Company sign-in (OIDC) | A's issuer refused by B | Same workspace provider for all its use cases | `test_iso3_oidc_per_workspace.py` |
| Database (stores) | Separate file per use case | Separate file per use case | `test_workspaces.py`, `test_iso4_isolation_matrix.py` |
| Audit records and seals | Per-workspace key; a copied chain does not verify | Separate chains per store | `test_iso2_workspace_audit_keys.py` |
| Integration credentials | Only the workspace's environment prefix | Same prefix (operator-managed) | `test_iso4_isolation_matrix.py`: `CredentialScopeTests` |
| Assistant secrets | Per-workspace secrets file | Shared within the workspace (one key per workspace) | `test_workspaces.py`: `test_each_use_case_has_its_own_store_and_each_workspace_its_own_secrets` |
| Background jobs (scheduler, automations, recovery) | Run inside each use case's engine on its own store | same | `test_iso4_isolation_matrix.py`: `BackgroundJobTests` |
| Agents and their tools | An agent exists only in its use case's engine | No agent spans use cases | `test_iso4_isolation_matrix.py`: `UseCaseBoundaryTests` |
| Reporting database | Target forced inside the use case's directory | same | `test_workspaces.py`: `test_reporting_target_is_kept_inside_the_use_case` |
| Uploaded documents | Not applicable yet: no document upload exists | — | Requirement for XL-2 and document ingestion (R2/R3) |
| Python tools (operator code) | Not isolated by Autology | — | Documented limitation |

## 4. Tenancy model

Decision ADR-001 ([architecture §4](AUTOLOGY_ARCHITECTURE_TARGET.md)) with owner decision D1: a dedicated store per
use case, per-workspace secrets, keys, sign-in and credential scope, and membership enforced by the router and again
by each engine. The first pilots run as isolated deployments (one workspace per platform).
