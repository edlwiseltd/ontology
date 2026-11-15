# Work in progress — Autology

*Updated 15 November 2026 (master directive V2). Branch `claude/autology-ontology-agent-4ajjer`.*

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

## Waiting for the owner

| Item | Needs |
|---|---|
| Name the release approver per workspace (D11 operational detail) | A single-administrator workspace cannot activate a release until it has one |
| Configure AI providers per workspace, data classes and keys (D7/D10 details) | AI-1 real-provider runs |
| Counsel's answers L1–L9 (D19) | GAP-031 closure; distribution stays blocked |
| Next increment authorisation | See the last report: members screen in Studio, readiness (REL-3), AI-1 once D7/D10 are configured |

## Hard limits (unchanged)

- No production deployment.
- No production ERP writes.
- No commercial distribution.
- No confidential data sent to an external AI provider without approved configuration.
- No self-approval of releases.
