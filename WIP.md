# Work in progress — Autology

*Updated 15 November 2026. Branch `claude/autology-ontology-agent-4ajjer`, HEAD `a143ed3`; CI runs 64 and 65 green.*

## Current state

- **Last delivered:** API v1 (`f059f2e`): `/api/v1` and `/platform/v1`, one error envelope, pagination, OpenAPI
  contracts, and a Studio client generated from them. Python suite 661 OK (96.32 % lines); Studio 17 unit tests and
  25/25 browser checks.
- **Master directive (R2 completion):** increment 1 of 6 done. Not started: workspace administration, releases and
  approval, readiness, AI Solution Architect, Studio visual editors.
- **Audit of 15 November (read-only):** reports in [`audit/2026-11-15/`](audit/2026-11-15/). They are not committed
  yet. Start with the
  [executive status](audit/2026-11-15/AUTOLOGY_EXECUTIVE_STATUS_2026-11-15.md).

## Waiting for the owner

Nothing is being implemented until the owner authorises an increment.

| Next step | Size | Needs |
|---|---|---|
| **REL-1a** (recommended): immutable fingerprint-bound releases; runs and review decisions bound to them; rollback | M–L | Owner authorisation; confirm the policy for in-flight runs on rollback |
| **H-1** (alternative): fix F-01 (ingest secrets sent to remote `next` URL) and F-02 (HTTP approver satisfies human reviews); pin base image and CI actions; refresh stale registers | S | Owner authorisation |

## Open owner decisions

- **Needed now:** D11 (second approver when a workspace has a single admin), D19 (licensing L1–L6), D7/D10 (AI
  providers and data residency).
- **Later:** D2, D3, D13, D15 (keep production ERP writes disabled), D16.
- **Applied defaults to confirm:** D8, D12, D14, D17, D18, D20.

## Known issues found on 15 November (not fixed)

| ID | Issue | Location |
|---|---|---|
| F-01 | Ingest HTTP pagination forwards secret headers to any host named by the source | `autology/ingest.py:362-384` |
| F-02 | `HttpApprover` can approve human reviews outside simulation, with no self-review check | `autology/adapters.py:232-257` |
| F-03 | Stage moves need no second person | linked to D11 |
| F-04 | Review decisions bound to `name@version`, not to the content fingerprint | GAP-020 |
| F-12 | 201 mypy errors; no lint, type checking or dependency scan in CI | — |

Full list: [gap and decision register](audit/2026-11-15/AUTOLOGY_GAP_DECISION_REGISTER_2026-11-15.md).

## Hard limits (unchanged)

- No production deployment.
- No real ERP writes.
- No commercial distribution.
- No commercial AI provider and no confidential data sent to one without D7/D10.
- No self-approval of Production releases.
