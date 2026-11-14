# Autology — security and tenancy

## 1. Threat model (summary)

| Asset | Threat | Control today | Status |
|---|---|---|---|
| Workspace data | Member of A reads or writes B's data | Token → one member of one workspace; router 404; per-use-case engine knows only its workspace's members; separate stores | **Tested** (`tests/test_workspaces.py`) |
| Workspace existence | Enumeration of other clients | Identical 404 for foreign, ungranted, unknown and malformed paths | **Tested** |
| Secrets (Claude key, connector credentials) | Leak across workspaces, to logs, to the browser, to the LLM | Per-workspace owner-only secrets file; key never returned or logged; `chat_redact` keeps confidential values from model providers | **Tested** (Claude key); connector secrets via env vars only |
| Approvals | Self-approval, approving through another path | Self-review refused; double decisions prevented; approvals bound to what the reviewer saw | Tested; **open bypass** via manual automation firing (GAP-011) |
| Hidden fields | Leak through derived endpoints | Row/field rules on most paths | **Open** leak via scenario comparison (GAP-012) |
| Agent authority | Agent acting on records the requester may not see | — | **Open** (GAP-013) |
| External actions | Duplicates, false success | One run per record (GAP-008 fixed) | **Open** GAP-001–007 |
| Audit | Undetected rewriting | HMAC-keyed chains, recorded heads, verify on backup | Partial: GAP-014 |
| Availability | Oversized bodies, slow integrations | Body limits incl. negative lengths (GAP-015 fixed) | Partial: GAP-021 |
| Prompt and document injection | Instructions hidden in data, spreadsheets, PDFs | LLM chooses only among governed valid actions; tools write only declared fields | Partial: GAP-045; Studio uploads planned with "data, never instructions" handling |

## 2. Roles

| Role | Scope | Can |
|---|---|---|
| Platform operator | Platform | Edit `platform.json`, hold the audit key, run backups; no business role in workspaces by default |
| Workspace admin | One workspace | `admin` in every use case of that workspace (settings, reporting, objects) |
| Member | One workspace, granted use cases | Per use case: `read`, `run`, `review`, `audit`, `ingest`, `admin`; ontology roles; reviewer roles |
| Agent | One use case | Its configured roles and tools; never decides reviews; never grants rights |

Planned: separation of duties checks on grants (R-ORG-2), substitute approvers, time-bound grants.

## 3. Tenancy

Decision ADR-001 ([target architecture §4](AUTOLOGY_TARGET_ARCHITECTURE.md)): dedicated store per use case, per
workspace secrets, membership enforced by the router and again by each engine. Remaining tenancy work:

| Path | Isolation status |
|---|---|
| REST through the router | Enforced and tested |
| Console (pointed at `/w/<ws>/u/<uc>`) | Enforced (it only forwards to that path) and tested |
| MCP | Single-engine only; per-workspace MCP is planned |
| Company sign-in (OIDC) | Disabled in platform mode; per-workspace issuers planned |
| Background work (automations, pipelines, reporting) | Runs inside each use case's engine, on its own store |
| Audit signing | One platform key for all chains; per-workspace keys planned |
| Exports, backups | Per use case store files; per-workspace backup command planned |

## 4. Tests that guard these properties

`tests/test_workspaces.py` (isolation), `tests/test_settings.py` (key handling), `tests/test_review_integrity.py`,
`tests/test_visibility.py`, `tests/test_oidc.py`, `tests/test_api_exchange.py` (body limits),
`tests/test_one_run_per_record.py`, and the audit's PoC scripts in `audit/evidence/` (several of which document
open gaps and must become regression tests when fixed).
