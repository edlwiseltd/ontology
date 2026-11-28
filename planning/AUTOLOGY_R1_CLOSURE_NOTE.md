# Autology — R1 closure note

*14 November 2026 · branch `claude/autology-ontology-agent-4ajjer` · R1 code state `dfe8b3f`, documents up to
`e6eeca9`. No production deployment is authorised or was made. Nothing in this note authorises one.*

## 1. What this note claims, and what it does not

R1 is **claimed complete in the repository**: every R1 story has code, a test written to fail first, and a green
CI run. The suite at `e6eeca9` is **559 tests, OK** (2 PostgreSQL tests skipped locally; CI runs them against
PostgreSQL 16). Line coverage was **95.9 %** when last measured (548 tests; CI gate 95 %, lines only).

R1 is **not** shown to be production-ready. Every result below is the engineering team's own, produced in the
repository, against simulated external systems. Section 4 lists what only independent reviewers, counsel and real
systems can establish.

Status vocabulary: Implemented and verified · Implemented but not fully verified · Partially implemented ·
Planned · Blocked · Not started. "Verified" here means *verified by repository tests and CI*, not independently.

## 2. Evidence per resolved gap

Links: commits `https://github.com/edlwiseltd/ontology/commit/<sha>`, CI runs
`https://github.com/edlwiseltd/ontology/actions/runs/<id>` (workflow `tests`: Python 3.10 and 3.13, PostgreSQL
service, coverage gate, wheel, Docker image smoke test), tests linked at the fixing commit.

| Gap | Defect (short) | Status | Commit | CI run | Test |
|---|---|---|---|---|---|
| GAP-001 | Blind retry after an ambiguous failure | Implemented and verified (simulated systems) | [`ac07e66`](https://github.com/edlwiseltd/ontology/commit/ac07e66) | [30](https://github.com/edlwiseltd/ontology/actions/runs/43596284868) ✅ | [`test_external_effects.py`](https://github.com/edlwiseltd/ontology/blob/ac07e66/tests/test_external_effects.py) |
| GAP-002 | No idempotency key reaches the external system | Implemented and verified (simulated) | `ac07e66` | 30 ✅ | same, `IdempotencyKeyTests` |
| GAP-003 | Fallback tool runs after an ambiguous failure | Implemented and verified (simulated) | `ac07e66` | 30 ✅ | same, `test_no_fallback_provider_after_an_unknown_outcome` |
| GAP-004 | Resume after review re-executes after a crash | Implemented and verified (simulated) | `ac07e66` | 30 ✅ | same; [`test_tool_failures.py`](https://github.com/edlwiseltd/ontology/blob/ac07e66/tests/test_tool_failures.py) (rewritten: the old test asserted the defect) |
| GAP-005 | Deferred resumes / automation retries repeat actions | Implemented and verified (simulated) | `ac07e66` | 30 ✅ | same |
| GAP-006 | Any 2xx treated as confirmed success | Implemented and verified (simulated) | `ac07e66` | 30 ✅ | same, `ConfirmationTests` |
| GAP-007 | No write-ahead record of in-flight actions | Implemented and verified (simulated) | `ac07e66` | 30 ✅ | same, `IntentLogTests` |
| GAP-001–007 (matrix) | 112 fault combinations (gates 80.1–80.3) | Implemented and verified (simulated) | [`6806549`](https://github.com/edlwiseltd/ontology/commit/6806549) | [39](https://github.com/edlwiseltd/ontology/actions/runs/43600428890) ❌ smoke only → [40](https://github.com/edlwiseltd/ontology/actions/runs/43600909939) ✅ | [`test_external_effects_matrix.py`](https://github.com/edlwiseltd/ontology/blob/6806549/tests/test_external_effects_matrix.py) |
| GAP-008 | Two open runs on one record both execute | Implemented and verified | [`5400ad8`](https://github.com/edlwiseltd/ontology/commit/5400ad8) | [17](https://github.com/edlwiseltd/ontology/actions/runs/43584626220) ✅ | [`test_one_run_per_record.py`](https://github.com/edlwiseltd/ontology/blob/5400ad8/tests/test_one_run_per_record.py) |
| GAP-009 | Resumed runs act on stale data | **Partially implemented** (re-validation done; all-or-nothing write-back open) | [`c779566`](https://github.com/edlwiseltd/ontology/commit/c779566) | [31](https://github.com/edlwiseltd/ontology/actions/runs/43596711764) ✅ | [`test_act6_revalidation.py`](https://github.com/edlwiseltd/ontology/blob/c779566/tests/test_act6_revalidation.py) |
| GAP-010 | Tool outputs not type-checked | Implemented and verified | [`d480abe`](https://github.com/edlwiseltd/ontology/commit/d480abe) | [29](https://github.com/edlwiseltd/ontology/actions/runs/43594456524) ✅ | [`test_mod3_typed_outputs.py`](https://github.com/edlwiseltd/ontology/blob/d480abe/tests/test_mod3_typed_outputs.py) |
| GAP-011 | Self-review through manual automation firing | Implemented and verified | [`c2a6b3b`](https://github.com/edlwiseltd/ontology/commit/c2a6b3b) | [21](https://github.com/edlwiseltd/ontology/actions/runs/43589763211) ✅ | [`test_gov1_manual_firing.py`](https://github.com/edlwiseltd/ontology/blob/c2a6b3b/tests/test_gov1_manual_firing.py) |
| GAP-012 | Hidden fields leak through scenarios | Implemented and verified | [`467655f`](https://github.com/edlwiseltd/ontology/commit/467655f) | [22](https://github.com/edlwiseltd/ontology/actions/runs/43590165472) ✅ | [`test_gov2_scenario_fields.py`](https://github.com/edlwiseltd/ontology/blob/467655f/tests/test_gov2_scenario_fields.py) |
| GAP-013 | Confused deputy (requester ∩ agent) | Implemented and verified | [`beb970a`](https://github.com/edlwiseltd/ontology/commit/beb970a), [`789a3c9`](https://github.com/edlwiseltd/ontology/commit/789a3c9) (GOV-5, D4) | [23](https://github.com/edlwiseltd/ontology/actions/runs/43590850120) ✅, [32](https://github.com/edlwiseltd/ontology/actions/runs/43598055673) ✅ | [`test_gov3_requester_scope.py`](https://github.com/edlwiseltd/ontology/blob/beb970a/tests/test_gov3_requester_scope.py), [`test_gov5_effective_permissions.py`](https://github.com/edlwiseltd/ontology/blob/789a3c9/tests/test_gov5_effective_permissions.py) |
| GAP-014 | Run-record fields outside the audit chain | Implemented and verified | [`e69f06d`](https://github.com/edlwiseltd/ontology/commit/e69f06d) | [24](https://github.com/edlwiseltd/ontology/actions/runs/43591491413) ✅ | [`test_gov4_run_record_seal.py`](https://github.com/edlwiseltd/ontology/blob/e69f06d/tests/test_gov4_run_record_seal.py) |
| GAP-015 | Negative `Content-Length` memory exhaustion | Implemented and verified | [`4509b97`](https://github.com/edlwiseltd/ontology/commit/4509b97) | [18](https://github.com/edlwiseltd/ontology/actions/runs/43588225082) ✅ | [`test_api_exchange.py`](https://github.com/edlwiseltd/ontology/blob/4509b97/tests/test_api_exchange.py) |
| GAP-016 | Misspelled ontology keys silently ignored | Implemented and verified | [`f20ddc1`](https://github.com/edlwiseltd/ontology/commit/f20ddc1) | [26](https://github.com/edlwiseltd/ontology/actions/runs/43593339990) ✅ | [`test_mod1_strict_schema.py`](https://github.com/edlwiseltd/ontology/blob/f20ddc1/tests/test_mod1_strict_schema.py) |
| GAP-017 | Missing linked record treated as existing | Implemented and verified | [`b3a2deb`](https://github.com/edlwiseltd/ontology/commit/b3a2deb) | [28](https://github.com/edlwiseltd/ontology/actions/runs/43594171591) ✅ | [`test_mod2_missing_records.py`](https://github.com/edlwiseltd/ontology/blob/b3a2deb/tests/test_mod2_missing_records.py) |
| GAP-018 | Server graph never refreshed from the store | **Partially implemented** (single writer per store; reload/version check open) | [`fd7ab77`](https://github.com/edlwiseltd/ontology/commit/fd7ab77), [`f0a385a`](https://github.com/edlwiseltd/ontology/commit/f0a385a) | [37](https://github.com/edlwiseltd/ontology/actions/runs/43599915539) ❌ smoke → [40](https://github.com/edlwiseltd/ontology/actions/runs/43600909939) ✅ | [`test_mod4_single_writer.py`](https://github.com/edlwiseltd/ontology/blob/f0a385a/tests/test_mod4_single_writer.py) |
| GAP-031 | No licence | **Partially implemented** (licence files and CI check; legal sign-off open) | [`6a23ff5`](https://github.com/edlwiseltd/ontology/commit/6a23ff5) | [36](https://github.com/edlwiseltd/ontology/actions/runs/43599469171) ✅ | [`test_leg1_licences.py`](https://github.com/edlwiseltd/ontology/blob/6a23ff5/tests/test_leg1_licences.py) |
| GAP-044 | No organisation isolation in one deployment | Implemented and verified (repository); independent verification open | [`e157e5b`](https://github.com/edlwiseltd/ontology/commit/e157e5b) | [19](https://github.com/edlwiseltd/ontology/actions/runs/43588984474) ✅ | [`test_workspaces.py`](https://github.com/edlwiseltd/ontology/blob/e157e5b/tests/test_workspaces.py) |
| GAP-044 (ISO-2) | Per-workspace audit keys | Implemented and verified | [`421a76b`](https://github.com/edlwiseltd/ontology/commit/421a76b) | [33](https://github.com/edlwiseltd/ontology/actions/runs/43598633304) ✅ | [`test_iso2_workspace_audit_keys.py`](https://github.com/edlwiseltd/ontology/blob/421a76b/tests/test_iso2_workspace_audit_keys.py) |
| GAP-044 (ISO-1) | MCP scoped to one use case of one workspace | Implemented and verified | [`d517ffe`](https://github.com/edlwiseltd/ontology/commit/d517ffe) | [34](https://github.com/edlwiseltd/ontology/actions/runs/43598867905) ✅ | [`test_iso1_mcp_per_workspace.py`](https://github.com/edlwiseltd/ontology/blob/d517ffe/tests/test_iso1_mcp_per_workspace.py) |
| GAP-044 (ISO-3) | Company sign-in per workspace | Implemented and verified | [`16616a5`](https://github.com/edlwiseltd/ontology/commit/16616a5) | [35](https://github.com/edlwiseltd/ontology/actions/runs/43599122349) ✅ | [`test_iso3_oidc_per_workspace.py`](https://github.com/edlwiseltd/ontology/blob/16616a5/tests/test_iso3_oidc_per_workspace.py) |
| GAP-044 (ISO-4) | Credentials, background jobs, use-case boundary | Implemented and verified | [`dfe8b3f`](https://github.com/edlwiseltd/ontology/commit/dfe8b3f) | [44](https://github.com/edlwiseltd/ontology/actions/runs/43609104808) ✅ | [`test_iso4_isolation_matrix.py`](https://github.com/edlwiseltd/ontology/blob/dfe8b3f/tests/test_iso4_isolation_matrix.py) |
| Gate 80.4 | Every documented route refuses unauthorised callers | Implemented and verified | [`d92b6da`](https://github.com/edlwiseltd/ontology/commit/d92b6da) | [38](https://github.com/edlwiseltd/ontology/actions/runs/43600155640) ❌ smoke → 40 ✅ | [`test_entry_point_matrix.py`](https://github.com/edlwiseltd/ontology/blob/d92b6da/tests/test_entry_point_matrix.py) |
| ENG-1 | Engine runs with no UI and no Hermes | Implemented and verified | `dfe8b3f` | 44 ✅ | [`test_engine_headless.py`](https://github.com/edlwiseltd/ontology/blob/dfe8b3f/tests/test_engine_headless.py) |

**About runs 37–39.** They are marked failed. In each, the test jobs and the coverage gate passed on both Pythons;
the Docker smoke test failed because a restarted container was refused its own store (MOD-4's lease was never
released on shutdown). `f0a385a` fixed it; run 40 passed every job, including a stop-and-restart of the image.
Later runs 41–46 are all green; the latest are [45](https://github.com/edlwiseltd/ontology/actions/runs/43609944901)
(`d7de163`) and [46](https://github.com/edlwiseltd/ontology/actions/runs/43609981504) (`e6eeca9`).

**Commit window.** `5400ad8` (GAP-008) predates the master instructions (received 11:00:30 UTC); everything else
above was made after them. One CI run per commit from run 18 onward.

## 3. Gaps that R1 did not close

| Gap | Remaining part | Owner of the next step |
|---|---|---|
| GAP-009 | All-or-nothing write-back per run | Engineering (R2/R3) |
| GAP-018 | Reload or version check on write (long-term) | Engineering |
| GAP-031 | Legal sign-off, legal entity, LGPL/MPL components in the image | Counsel (D5) |
| GAP-040 | Exact version pins / lock file, SHA-pinned actions | Engineering (R2 QA-1) |
| GAP-026 | The service class grew from 1,232 to 2,119 lines during R1 | Engineering (R2 ARC-0) |
| GAP-041 | Three schema changes without ordered, transactional migrations | Engineering (R2 MIG-1) |

All other open gaps are listed in the [defect register](AUTOLOGY_DEFECT_REGISTER.md) (26 open, 5 open external,
2 open owner decision).

## 4. What still needs people or systems outside this repository

### 4.1 Independent review

| Item | Why the repository cannot settle it |
|---|---|
| Re-verification of GAP-001–018 fixes by someone other than the author | Each test was written by the same author as the fix; a reviewer may find cases the tests do not cover (GAP-054) |
| Workspace isolation review (GAP-044, ISO-1–4) | The isolation matrix covers every path the code has today; an external tester decides whether it covers every path an attacker would try |
| External penetration test | Gate 4.x evidence; requires an engagement (GAP-054) |
| Maturity score | ≈ 65 is a self-assessment; the last independently verified figure is 47 / 100 |
| Coverage margin | 95.9 % against a 95 % gate; `platform.py` at 65 % |

### 4.2 Legal validation

| Item | Decision / gap |
|---|---|
| Proprietary licence text, legal entity's name, redistribution terms | D5, GAP-031 |
| LGPL (`psycopg`) and MPL components shipped in the Docker image | GAP-031 |
| Whether workspace documents may be sent to model providers (data residency) | D10 (pending) |
| Encryption at rest as a contractual requirement | D3 (pending), GAP-034 |

### 4.3 Real-system trials

| Item | Blocked by |
|---|---|
| External action safety against a real ERP (all tests use simulated systems) | Odoo 18 sandbox access (D6); production ERP writes stay disabled (D15 pending) |
| Two real model providers (D7) | API access to two providers, provider choice (D10 pending) (GAP-052) |
| A real business process end to end | A pilot customer and data (D16 pending) (GAP-053) |
| Load, soak, restore | Agreed targets and an environment (GAP-024, GAP-033) |
| A released version | Release workflow never executed (GAP-049) |

## 5. Open owner decisions (not made by engineering)

Deployment model beyond the approved "isolated pilots first" (D1 detail, D2 store, D3 encryption), licensing
review (D5), model providers and data residency (D10), Studio technology (D9), second approver (D11), secret
store (D13), production ERP writes (D15), real pilot (D16). Applied defaults awaiting confirmation: D8, D12, D14.
See the [decision register](AUTOLOGY_DECISION_REGISTER.md).

## 6. How to re-check this note

```
git checkout e6eeca9
AUTOLOGY_AUDIT_KEY=k python -m unittest discover -s tests -t .      # 559 tests, OK (2 skipped)
coverage run --source=autology -m unittest discover -s tests -t . && coverage report   # ≥ 95 % lines
```

Each CI link above opens the run; each test link opens the test at the fixing commit.
