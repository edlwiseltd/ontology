# Work in progress — Autology

*Updated 15 November 2026 (decision-integrity sprint). Branch `claude/autology-ontology-agent-4ajjer`.*

## Done in this directive

| Item | Commit | Evidence |
|---|---|---|
| Owner decisions D11, D7/D10, D19 recorded | `5516358` | `planning/AUTOLOGY_DECISION_REGISTER.md` |
| H-1 / F-01: outbound credentials confined to the configured origin (GAP-058) | `5516358` | `tests/test_h1_outbound.py` (7 of 12 failed before the fix); CI run 67 |
| H-1 / F-02: machines never record human approvals (GAP-059) | `5516358` | `tests/test_h1_approval_identity.py` (6 of 6 failed before the fix); CI run 67 |
| REL-1a: immutable releases, independent approval, drift, rollback, run binding (GAP-020) | `c2ea711` | `tests/test_rel1a_releases.py`; CI run 68 |
| Architecture Part B: plugin runtime, knowledge hub, composable intelligence, decision and action modelling, autonomy | `c2ea711` | `planning/AUTOLOGY_ARCHITECTURE_TARGET.md` |
| Legal decision package D19 (not counsel's approval) | `c2ea711` | `planning/AUTOLOGY_LEGAL_DECISION_PACKAGE_D19.md` |
| ADM-1/ADM-2: members, tokens, grants (independent approval) without restarts; engine reload | `839e9d3` | `tests/test_adm1_administration.py`; CI run 70 |
| STU-6: Releases tab in Studio; publish a draft; restore a release's model | `839e9d3` | `tests/test_stu6_publish.py`; 31/31 browser checks; CI run 70 |
| QA-1: ruff, mypy ratchet (201), pip-audit, npm audit; base image by digest, actions by SHA | `cb91221` | CI run 71 (five jobs, incl. `quality`) |
| IAM-1: tenants own workspaces; versioned tenancy registry; migration into dedicated tenants | `0008ae4` | `tests/test_iam1_tenants.py`; CI run 75 |
| IAM-3: administrators carry no business-data access; explicit approved grants; migration; GAP-061 fixed | `88e5fd7` | `tests/test_iam3_privilege_separation.py`; 33/33 browser checks; CI run 76 |

## R2 security and reliability sprint (15 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| A — GAP-030: token lifetimes, revocation, rotation, rate limits, timeouts | Done, `940c04f`, CI run 78 | `tests/test_gap030_security.py` (27 tests); see the implementation log |
| B — IAM administrative security | Done, `01228d3` (CI run 79: Python jobs green, one Studio browser check failed on a UI race fixed in C) | `tests/test_iamb_admin_hardening.py` (12 tests); GAP-062, GAP-063 found and fixed |
| C — Backup, restore and release activation | Done, `8111d7f`, CI run 80 | `tests/test_ops1_recovery_and_activation.py` (14 tests); GAP-033 fixed |
| D — Studio tenant and membership administration | Done, `0e9967a`, CI run 81 | Access screen in Studio; 23 Vitest, 56/56 browser checks |

## Decision integrity, AI security boundaries and architecture foundations (15 November 2026)

| Increment | Status | Evidence |
|---|---|---|
| A — SEC-A: GAP-045, GAP-037, GAP-035 | Done, `4093749`, CI run 84 | `tests/test_seca_decision_integrity.py` (18 tests, with a model that obeys what it reads) |
| B — D24 least-privilege `operate` | **Blocked on the owner's approval**; design, tests of present behaviour and access-review evidence done, `6f25695` (CI run 85 failed on a race in one browser check, fixed in `8c5a44c`; the commit is part of green run 86) | `tests/test_d24_operate_readiness.py` (4 tests); [IAM target §7](planning/AUTOLOGY_IAM_TARGET.md) |
| C — MIG-1 and a first step of ARC-0 | MIG-1 done, ARC-0 partial, `846a3cc`, CI run 86 | `tests/test_mig1_migrations.py` (6), `tests/test_arc0_services.py` (4); GAP-041 fixed, GAP-026 partly |
| D — AI-1 provider-neutral AI foundation | Foundation done **with test doubles only**, `744deae`, CI run 88; no real provider, GAP-052 open | `tests/test_ai1_provider_foundation.py` (18 tests); see the implementation log |

## Waiting for the owner

| Item | Needs |
|---|---|
| Name the release approver per workspace (D11 operational detail) | A single-administrator workspace cannot activate a release until it has one |
| Configure AI providers per workspace, data classes and keys (D7/D10 details), and authorise an evaluation protocol | AI-1 real-provider runs; closing GAP-052; exposing model proposals in Studio |
| D24: approve (or decline) the narrower `operate` permission as designed | Implementation is about 1–2 days once approved; nothing changes until then |
| Counsel's answers L1–L9 (D19) | GAP-031 closure; distribution stays blocked |
| Review the migrated administrator grants (IAM-3) in each existing workspace | Revoke those not needed |
| D22b–e; authorisation for IAM-2, IAM-4, IAM-5, IAM-6 | Not started, by instruction |
| D24: keep the engine's unrestricted `admin` permission as an acknowledged, reviewed grant? D25: company sign-in for people | See the decision register; migrated administrator grants wait for confirm / narrow / revoke in each workspace's access review |
| D23: confirm default token lifetimes (90 d people, 365 d services) and rate limits | Existing tokens expire one lifetime after the upgrade: plan re-keying |
| Next increment authorisation | Readiness (REL-3), AI-1 once D7/D10 are configured |

## Hard limits (unchanged)

- No production deployment.
- No production ERP writes.
- No commercial distribution.
- No confidential data sent to an external AI provider without approved configuration.
- No self-approval of releases.
