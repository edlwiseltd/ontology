# Autology — R2 Security & Reliability Sprint: Completion and Verification Report

*15 November 2026. Verification and reporting only: nothing was modified to produce the findings below (no code
change, no commit). HEAD is `bf8fb15` on `claude/autology-ontology-agent-4ajjer`, with a clean working tree,
identical to `origin`. Results marked "re-run" were executed at that HEAD for this report; CI statuses were
re-queried from GitHub. This is not an independent security certification and gives no maturity score.*

## Executive summary

- **All four increments are implemented, committed and pushed.** The Python suite, lint, type ratchet, Studio
  typecheck, unit tests, build and browser tests all pass in a fresh run at HEAD.
- **CI is green on HEAD (run 82) and on the commits of increments A, C and D.** The commit of increment B
  (`01228d3`) has no green run: its Studio browser job failed in run 79. The fix landed in increment C, and B's code
  passes in runs 80–82.
- **Coverage is slightly below the pre-sprint baseline:** 95.77 % against 95.93 %. The new error paths in recovery
  and activation are not all exercised.
- **The sprint is complete against its directive. R2 as a release is not.** The AI Solution Architect, readiness
  scoring, hard promotion gates, semantic diff, service split and several others are still open.
- **Three decisions from this sprint await the owner** (D23, D24, D25), plus the standing ones.

## 1. What the sprint implemented

### Increment A — GAP-030: tokens, rate limits, timeouts

| Status | Requirement |
|---|---|
| Completed | Every API token has a finite lifetime per identity kind (people 90 days, services 365, configurable, never infinite). |
| Completed | Expiry is enforced at the router, the engine and for every MCP message, over HTTP and stdio. |
| Completed | Revocation and rotation without restart, both audited. Only SHA-256 digests are stored. Rotation never changes rights. |
| Completed | Existing tokens get one lifetime from the upgrade: not cut off, not eternal. |
| Completed | Rate limits per client address, identity, tenant and endpoint class, with HTTP 429 and `Retry-After`. Forged `X-Forwarded-For` is ignored unless the peer is a configured trusted proxy. |
| Completed | Connection ceiling and slow-client timeout on both servers. Outbound calls have a whole-call deadline that maps to a tracked "unknown outcome". Runs pause between steps at a time budget. |
| Partial | Rate-limit counters live in one process (single node, documented). |
| Partial | Limits are per endpoint class, not per individual route. |
| Partial | Tenant-level identities and standalone engines are re-keyed in configuration only; there is no API for it. |
| Partial | GAP-021: the agent lock is still held for a whole run. |
| Partial | Studio's relay does not forward client addresses, so Studio users share one address for the failed-sign-in limit. |
| Unimplemented | Limits shared across several server processes. |

### Increment B — IAM administrative security

| Status | Requirement |
|---|---|
| Completed | Administrative roles read no business data through REST, MCP or the scheduler (re-verified). |
| Completed | The engine's `admin` permission is defined as unrestricted access inside one use case. A grant containing it needs an acknowledgement from the proposer and from the approver. |
| Completed | Access review per workspace: origin, proposer, approver, and whether a person still has to review each grant. Paths are confirm, narrow or revoke. No approved access was revoked. |
| Completed | GAP-062, found during the sprint: one administrator could take over a member's data access by re-keying them. A new token for a member with data now takes two people. |
| Completed | GAP-063, found during the sprint: a removed member's pending proposal could be approved for a later namesake. Removal now ends proposals. |
| Completed | Service identities approve, confirm, request and administer nothing (verified). |
| Partial | `admin` still bypasses row and field rules inside its use case (D24). |
| Partial | Whoever issues a token has seen it; a new member's first token is issued by one administrator (D25). |
| Blocked | Platform-operator identity and governed exceptional access (IAM-2, D22b): not authorised. |
| Unimplemented | A non-bypassing `operate` permission (proposed under D24, not built). |

### Increment C — Backup, restore and release activation

| Status | Requirement |
|---|---|
| Completed | `platform-backup`, `platform-verify`, `platform-restore`: consistent online copy of every store and registry in a fixed order, verified and signed manifest. |
| Completed | Restore goes into a new directory only and never overwrites. |
| Completed | Restore drill: a second platform starts on the restored data while the first keeps running. |
| Completed | Failure injection: damaged, incomplete or foreign backups are refused; a mid-way failure leaves nothing behind. |
| Completed | Release activation in one call: no restart, no reload, no manual stage steps. Rollback is the same call. |
| Completed | A failed activation puts back the previous model and engine. Requests never see an intermediate configuration. |
| Partial | Activation restores the release's model but only verifies agent settings and tool declarations; the operator deploys those files. |
| Partial | A switch gives up after 10 seconds rather than cut requests in flight. |
| Partial | Backup scheduling, retention, off-site copies and encryption are documented as the operator's job. |
| Unimplemented | PostgreSQL stores in the platform backup; point-in-time recovery. |
| Unimplemented | A "Suspended" release state. |
| Unimplemented | A new restore drill for the standalone single-engine `backup` command. |
| Unimplemented | Coordination across several platform processes. |

### Increment D — Studio tenant and membership administration

| Status | Requirement |
|---|---|
| Completed | Access screen: tenant and workspaces, members with effective permissions per use case, token state. |
| Completed | Add and remove members; request, approve and withdraw grants; revoke grants and tokens. |
| Completed | Pending approvals, access review summary, administration history, replace one's own token. |
| Completed | Clear "permission denied" and "approval required" states. |
| Completed | No new library; the Engine is the only authority. |
| Partial | The workspace switcher and the multi-workspace tenant table exist but were not exercised in the browser tests (the example identities each belong to one workspace). |
| Partial | The access review's "Confirm" button has no direct browser check (its route is covered by Python tests). |
| Partial | Tenant-level identities and administrators are shown, not edited. `run_as` is not in the grant form. |
| Unimplemented | Creating tenants or workspaces from Studio; a full WCAG audit. |

## 2. Technical evidence

### Commits

| Increment | Commit | Files | Code and tests touched |
|---|---|---|---|
| A | `940c04f` | 27 | New `credentials.py`, `limits.py`, `tests/test_gap030_security.py`; changed `server.py`, `platform.py`, `outbound.py`, `adapters.py`, `ingest.py`, `mcp.py`, `agent.py`, `administration.py`, `openapi.py` |
| B | `01228d3` | 16 | New `tests/test_iamb_admin_hardening.py`; changed `platform.py`, `administration.py`, `openapi.py`, four existing test modules |
| C | `8111d7f` | 19 | New `recovery.py`, `tests/test_ops1_recovery_and_activation.py`; changed `platform.py`, `server.py`, `__main__.py`, `openapi.py`, Studio `ReleasesView.tsx`, `Workbench.tsx` |
| D | `0e9967a` | 15 | New `AccessView.tsx`, `lib/access.ts`, `tests/access.test.ts`; changed `Workbench.tsx`, `lib/api.ts`, `lib/types.ts`, `lib/forward.ts`, `globals.css`, `e2e/run.mjs` |
| Log | `bf8fb15` | 2 | Implementation log and `WIP.md` only |

Since baseline `8135abd`: 46 files, +11,948 / −357 lines, of which about +4,670 are code and tests (the rest is
generated contracts, docs and registers).

### New APIs, commands and storage

- **Six platform routes** under `/platform/v1/workspaces/{ws}/`:
  - `access-review`
  - `members/{name}/confirm-grant`
  - `members/{name}/revoke-token`
  - `my-token`
  - `token-requests/{id}/approve`
  - `token-requests/{id}/withdraw`
- **Changed responses:**
  - `members/{name}/token` now answers 200 or 202.
  - The members view gained effective permissions, token state and caller hints.
  - The activation result gained `reloaded`, `configuration` and `stage`.
  - 429 and 503 are declared on operations.
- **Three CLI commands:** `platform-backup`, `platform-verify`, `platform-restore`.
- **Storage:**
  - One new append-only SQLite registry, `credentials.db` (or `<store>.credentials` for a standalone engine),
    created on first start.
  - Four new event types in the existing administration log.
  - No schema migration of existing tables.

### Results re-run at HEAD for this report

| Check | Result |
|---|---|
| Python suite | 770 tests, OK, 2 skipped locally (PostgreSQL; CI runs them) |
| Line coverage | 95.77 % (13,270 statements, 561 missed); baseline 95.93 % |
| ruff | Clean |
| mypy ratchet | 198 errors, equal to the accepted baseline; none new |
| Studio typecheck | Pass |
| Studio unit tests | 23 passed |
| Studio build | Pass |
| Browser tests against a real platform | 56/56, plus the two post-checks (Studio stopped, engine still answers) |
| `npm audit` (production dependencies) | 0 vulnerabilities |

`pip-audit` was not re-run locally; it runs in CI's quality job.

Tests added in the sprint: 53 Python (27 + 12 + 14), 6 Studio unit, 23 browser checks.

### CI runs (statuses re-queried for this report)

| Run | Commit | Outcome |
|---|---|---|
| [78](https://github.com/edlwiseltd/ontology/actions/runs/43755274397) | `940c04f` (A) | Success |
| [79](https://github.com/edlwiseltd/ontology/actions/runs/43756581206) | `01228d3` (B) | **Failure**: studio job, one browser check. The other four jobs passed (seen during the sprint, not re-queried for this report). |
| [80](https://github.com/edlwiseltd/ontology/actions/runs/43758498960) | `8111d7f` (C) | Success |
| [81](https://github.com/edlwiseltd/ontology/actions/runs/43758659079) | `0e9967a` (D) | Success |
| [82](https://github.com/edlwiseltd/ontology/actions/runs/43759596129) | `bf8fb15` (HEAD) | Success |

Run 79 failed on a display race in Studio that predates the sprint: a late refresh answer overwrote a newer
use-case selection. The browser tests had not been run locally before increment B was pushed. The fix is in
`8111d7f`.

## 3. Security assessment

| Control | Enforced? | Basis and limits |
|---|---|---|
| Tenant and workspace isolation | Yes, application level | Other tenants and workspaces answer 404 everywhere, including the new routes. A tenant's rate limit takes nothing from another's. One store and one audit key per workspace. |
| Administrative privilege separation | Yes | Administrators hold `configure` only. The re-keying take-over is closed. Remaining exception: an explicit `admin` grant. |
| Token expiration and revocation | Yes | Router, engine, MCP. Whoever can delete files in the data directory can reset lifetimes; that is an infrastructure control. |
| Rate limiting and abuse protection | Yes, single process | Lockout happens before the credential is examined. Not shared across processes. |
| Row- and field-level permissions | Yes for scoped grants | An administrator with a scoped grant sees the same rows and redactions as any member. Bypassed by `admin` by design. |
| Service identity restrictions | Yes | Cannot approve, confirm, administer or renew their own token. Scheduled automations are unaffected by token expiry. |
| Governance and approval | Yes | Never the proposer, never the grantee, never a service. Two colluding people defeat any four-eyes rule. |
| Backup integrity and recovery | Yes | Signed manifest, hash and chain verification, isolated restore drill in CI. Backup storage and encryption are the operator's. |
| Release activation and rollback | Yes | Verified before the switch, undone on failure. Pilot is never automatic; production is always refused. |

**Remaining vulnerabilities and limitations:**

- `admin` is a full bypass inside its use case; the migrated administrator grants are `admin` grants until reviewed.
- An issuing administrator has seen the token they issue.
- Open defects with security impact:
  - GAP-037: the `ingest` permission can change facts that rules depend on.
  - GAP-035: restricted fields can appear in notification text.
  - GAP-045: text in data can steer a model's choice among valid actions.
  - GAP-046 and GAP-019: OIDC edge cases.
  - GAP-036: every reader can read every scenario.
- No encryption at rest (GAP-034, D3).
- No independent security review (GAP-054).

## 4. Functional demonstration

**A workspace administrator, in Studio, with no command line or raw API call, can:**

- Sign in with an API token and see the tenant, workspace and use cases.
- Create a use case from an approved template.
- Run readiness checks and move a use case between Draft, Simulation and Pilot.
- View the active model on a canvas; design a draft, get engine validation and gap questions, and save revisions.
- Propose a release, have another person approve it, activate it or roll back in one step, and publish a draft.
- Do all of the Access screen (section 1, increment D).

**Still outside Studio** (configuration files, API or CLI):

- Creating tenants and workspaces; naming administrators and release approvers.
- Configuring agents, tools, pipelines and AI providers.
- Backups; reloading an engine.

**An internal user (not an administrator) can:**

- In Studio, see the overview and model of the use cases granted to them.
- Start runs and decide reviews through the engine's review inbox, the separate Console, MCP clients or the REST
  API and SDKs.
- There is no end-user Workspace UI (R5).

**Still mock, synthetic, manual or incomplete:**

- All example data is synthetic.
- The "architect" is a rule-based blueprint generator, labelled "not AI".
- No real AI model has been run (GAP-052).
- There is no ERP connector (GAP-032).
- Tools run only in simulation or against sandboxes.
- Only one blueprint exists (water treatment).

## 5. Roadmap status

| Release | Status |
|---|---|
| R1 — Engine foundation | Done at repository level. Legal sign-off (D19) and independent re-verification remain open. |
| R2 — Studio, governance, IAM, reliability | In progress; see the list below. |
| R3 — Data and knowledge onboarding | Not started; needs authorisation. |
| R4 — Agents, integrations, plugins | Not started; needs authorisation and an Odoo sandbox. |
| R5 — End-user Workspace UI | Not started. |
| R6 — Production readiness | Not started, except the restore drill (OPS-1), delivered early in increment C. |

**Remaining R2 requirements:**

1. API-1: typed schemas for the remaining generic routes.
2. ARC-0: split `AutologyService` (GAP-026).
3. MIG-1: ordered, transactional schema migrations (GAP-041).
4. AI-1: provider-neutral model adapter with two adapters (GAP-029).
5. UI-1: move the review inbox out of the engine process.
6. ADM-1 residual: tenants, workspaces, administrators and approvers through the API.
7. REL-1 residual: Suspended state. The Production stage stays refused by instruction.
8. REL-2: the full list of hard promotion gates. Today only the stage checks and the approved-release check exist.
9. REL-3: readiness scorecard.
10. REL-4: complete semantic diff (GAP-028).
11. ARC-1 to ARC-4: the real AI Solution Architect, provenance labels, model-worded questions, contradiction
    handling.
12. BP-1: oil and gas and pharma blueprints.
13. SEC-A: prompt-injection and data-boundary tests.
14. STU-2 and STU-3: partly done on the rule-based generator. STU-5: readiness dashboard, not started.
15. IAM-2, IAM-4, IAM-5, IAM-6: not authorised.
16. The R2 exit tests.

**The registers lag the code in three places** (not corrected, because this report was produced under a
no-modification rule):

- The roadmap's overview table still shows R2 as "Planned".
- The REL-1 and ADM-1 rows still list "activation without restart" and "a Studio screen" as open.
- GAP-051 (no administration UI) is still "Partly fixed" although increment D delivered the screen.

## 6. Open decisions and defects

**Defect register:** 63 entries. 28 fixed, 9 partly fixed, 19 open, 5 open pending external evidence, 2 open
pending an owner decision.

- **Critical:** none open.
- **High, not fully fixed:** GAP-031 (licence; blocks distribution), GAP-032 (no ERP connector), GAP-052 (never run
  with a real model), GAP-053 (no real end-to-end process).
- **Partly fixed:** GAP-021, 025, 029, 031, 040, 043, 050, 051, 056.

**Decisions needing the owner:**

- From this sprint: D23 (default token lifetimes and limits), D24 (keep `admin` as an acknowledged grant; add
  `operate`?), D25 (company sign-in for people).
- Standing: D2, D3, D8, D10 (per-workspace AI configuration and keys), D11 (approver per workspace), D12 to D18,
  D19 (legal), D20, D21 (protected branch and human review), D22b–e.

**External dependencies:** counsel (D19), AI provider keys, an Odoo sandbox, an independent security review, a
customer process.

**Security and legal blockers:** no licence (commercial distribution blocked); no independent review; no encryption
at rest; the repository has one administrator and no protected branch (D21).

**Technical debt affecting the next stage:** the `AutologyService` god object (GAP-026); 198 accepted type errors;
non-transactional migrations (GAP-041); the Console, MCP relay and SDKs still on legacy API paths; the agent lock
(GAP-021); automations running inside request threads (GAP-057).

## 7. Recommended next five priorities

These are engineering necessities, not product ideas. Plugin runtime, knowledge hub, retrieval and marketplace
remain unapproved concepts.

1. **Close the least-privilege exception:** add the `operate` permission (D24 b) and have each workspace run its
   access review. About 1–2 days. It removes the reason to hand `admin` to operations staff.
2. **SEC-A before any real model:** prompt-injection and data-boundary tests, with GAP-045 and GAP-037. About 2–3
   days. This is a hard precondition for the AI Solution Architect.
3. **AI-1 adapter contract**, with two adapters and the evaluation suite on fakes first (GAP-029). About 3 days
   plus API cost. Real-provider runs wait for D7/D10 configuration and keys.
4. **MIG-1 and ARC-0:** transactional migrations, then the service split. About 6–9 days. Every later R2 service
   (architect, readiness, imports) lands on this.
5. **REL-2 and REL-3:** hard promotion gates and the readiness scorecard. About 10 days. They are R2 exit criteria
   and the owner must validate the weights.

Housekeeping to do alongside: update the lagging register entries, raise coverage on the recovery and activation
error paths, and finish GAP-021.

## 8. Final assessment

1. **Is the R2 sprint fully complete?** Yes against the sprint directive: all four increments are delivered. The
   partial items in section 1 are documented limits, not unfinished increments.
2. **Are all four increments supported by passing tests and verified CI?** Tests: yes, all pass at HEAD. CI: A, C
   and D have green runs on their own commits. B's commit has a failed run (studio job), and B is covered by the
   green runs 80, 81 and 82 on its descendants.
3. **Is Autology R2 ready for formal closure?** No. The sprint can be closed; the R2 release cannot. Sixteen
   requirement groups remain, including the AI Solution Architect, readiness scoring and hard gates, which are R2
   exit criteria.
4. **Can we safely begin AI-1?** The adapter contract and its tests on fake models: yes, now. Runs with a real
   provider or real documents: not yet. They need SEC-A, the per-workspace D7/D10 configuration, API keys, and no
   confidential data without authorisation.
5. **What must the owner decide before the next sprint?**
   - D23, D24 and D25.
   - Authorisation and order for the next increment.
   - AI provider configuration and keys (D7/D10) if AI-1 is to reach a real model.
   - The release approver per workspace (D11).
   - D21 (protected branch, human review).
   - D19 remains with counsel.
