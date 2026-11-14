# Autology — Release R1 close-out

*14 November 2026 · branch `claude/autology-ontology-agent-4ajjer` · last commit `f0a385a` · no production deployment
is authorised or was made. Companion documents: [defect register](AUTOLOGY_DEFECT_REGISTER.md),
[R2 plan](AUTOLOGY_R2_PLAN.md), [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md), [PRD](AUTOLOGY_PRD.md).*

## 1. Summary

All R1 stories are done: GOV-1–5, MOD-1–4, ACT-1–6, ISO-1–3, LEG-1. Two items were added at close-out because the
audit's gate 80 requires them and the original story list missed them: **MOD-4** (GAP-018, High) and an
**entry-point matrix** with a **full fault-injection matrix**. Every repository-verifiable gate 80 criterion is met.
What remains for gate 80 is external: legal sign-off on the licence (80.7). Independent re-verification of the
fixes has not happened yet; every claim below cites the test that shows it.

## 2. Owner decisions applied

| Decision | Applied as | Evidence |
|---|---|---|
| D1 multi-tenancy, isolated pilots first | Workspaces with dedicated stores, keys (ISO-2), sign-in (ISO-3) and MCP scope (ISO-1); pilots run as isolated deployments | `tests/test_workspaces.py`, `tests/test_iso*.py` |
| D4 intersection of permissions; least-privilege service identities | GOV-3 (records) and GOV-5 (roles, `run_as`, `service_identities`, delegates narrowed, roles sealed with the run) | `tests/test_gov3_requester_scope.py`, `tests/test_gov5_effective_permissions.py` |
| D5 proprietary distribution, subject to review | LEG-1: `LICENSE`, `THIRD_PARTY_NOTICES.md`, inventory checked in CI | `tests/test_leg1_licences.py` |
| D6 Odoo 18 sandbox; no production ERP writes until action safety passes | Action safety (ACT-1–6) passes in the repository; INT-2/INT-3 scoped to a sandbox in R3; nothing writes to any ERP | PRD §7 |
| D7 provider independence, two adapters | Scheduled as AI-1 (R2) | PRD §7, R2 plan |
| openpyxl approved, subject to checks | Inventoried (MIT, with `et-xmlfile` MIT); used from XL-1 (R2) | `deploy/third_party_licences.json` |

## 3. Test evidence and CI commit mapping

Local results are `python -m unittest discover -s tests -t .` with an audit key (and also without one for the
store and audit stories). CI runs the suite on Python 3.10 and 3.13 with a real PostgreSQL, enforces ≥ 95 % line
coverage and no skipped test, builds the wheel and the Docker image and smoke-tests the image.

| Commit | Story | New tests | Suite (local) | CI run | CI result |
|---|---|---|---|---|---|
| `4509b97` | API dispatch, GAP-015 | `test_api_exchange.py` (3) | 449 | 18 | success |
| `e157e5b` | Phase 1 workspaces | `test_workspaces.py` (11) | 449 | 19 | success |
| `5a60d24` | PRD | — | 449 | 20 | success |
| `c2a6b3b` | GOV-1 (GAP-011) | `test_gov1_manual_firing.py` (4) | 453 | 21 | success |
| `467655f` | GOV-2 (GAP-012) | `test_gov2_scenario_fields.py` (5) | 458 | 22 | success |
| `beb970a` | GOV-3 (GAP-013) | `test_gov3_requester_scope.py` (6) | 464 | 23 | success |
| `e69f06d` | GOV-4 (GAP-014) | `test_gov4_run_record_seal.py` (8) | 472 | 24 | success |
| `a03ed96` | Evidence document | — | 472 | 25 | success |
| `f20ddc1` | MOD-1 (GAP-016) | `test_mod1_strict_schema.py` (8) | 480 | 26 | success |
| `636740f` | Owner decisions in the PRD | — | 480 | 27 | success |
| `b3a2deb` | MOD-2 (GAP-017) | `test_mod2_missing_records.py` (7) | 487 | 28 | success |
| `d480abe` | MOD-3 (GAP-010) | `test_mod3_typed_outputs.py` (4) | 491 | 29 | success |
| `ac07e66` | ACT-1–5 (GAP-001–007) | `test_external_effects.py` (17) | 509 | 30 | success |
| `c779566` | ACT-6 (GAP-009) | `test_act6_revalidation.py` (4) | 513 | 31 | success |
| `789a3c9` | GOV-5 (D4) | `test_gov5_effective_permissions.py` (7) | 520 | 32 | success |
| `421a76b` | ISO-2 | `test_iso2_workspace_audit_keys.py` (3) | 523 | 33 | success |
| `d517ffe` | ISO-1 | `test_iso1_mcp_per_workspace.py` (4) | 527 | 34 | success |
| `16616a5` | ISO-3 | `test_iso3_oidc_per_workspace.py` (5) | 532 | 35 | success |
| `6a23ff5` | LEG-1 (D5, GAP-031) | `test_leg1_licences.py` (5) | 537 | 36 | success |
| `fd7ab77` | MOD-4 (GAP-018) | `test_mod4_single_writer.py` (5) | 542 | 37 | **failure**: tests and coverage passed on both Pythons; the image smoke test failed (a restarted container was refused the store) |
| `d92b6da` | Gate 80.4 entry-point matrix | `test_entry_point_matrix.py` (3) | 545 | 38 | **failure**: same smoke-test cause |
| `6806549` | Gates 80.1–80.3 fault matrix | `test_external_effects_matrix.py` (112 combinations) | 546 | 39 | **failure**: same smoke-test cause |
| `f0a385a` | MOD-4 fix: release the lease on shutdown | `test_mod4_single_writer.py` (+2) | 548 | 40 | see the run; the smoke test passed locally on a freshly built image |

Each story's tests were written to fail first; the implementation log records how many failed before the fix.
For the external-effects suite and the isolation stories that introduced new APIs, the test modules could not run
on the old code; the audit's proofs of concept on the old code are the "before" evidence there.

## 4. R1 acceptance criteria

| Story | Acceptance criterion (PRD §8) | Evidence | Status |
|---|---|---|---|
| GOV-1 | A person firing an automation by hand cannot approve its review; the condition must hold; the `start_run` checkpoint applies; only visible records are fired | `test_gov1_manual_firing.py` | ✅ |
| GOV-2 | Questions over hidden or gated fields are withheld in comparisons; edits to unreadable fields refused; the assistant's `what_if` applies provider redaction | `test_gov2_scenario_fields.py` | ✅ |
| GOV-3 | A run whose case holds a record the requester cannot see is refused; automations keep a service identity | `test_gov3_requester_scope.py` | ✅ |
| GOV-4 | Editing pending review, status, steps or ontology reference fails verification and blocks resume; a chain copied to another run id does not verify | `test_gov4_run_record_seal.py` | ✅ |
| GOV-5 | Runs use requester ∩ agent roles; scheduled runs use authorised least-privilege service identities | `test_gov5_effective_permissions.py` | ✅ |
| MOD-1 | Every documented key misspelled once fails to load with its path; unknown types fail | `test_mod1_strict_schema.py` (400+ cases) | ✅ |
| MOD-2 | A missing record's fields and state are unknown; preconditions fail; unknown computed effects block the action | `test_mod2_missing_records.py` | ✅ |
| MOD-3 | Wrong-typed tool results refused and audited; a bad stored row is quarantined with an alert, the server starts | `test_mod3_typed_outputs.py` | ✅ |
| MOD-4 | A second process cannot write a store a live server holds; crashes and clean stops free it | `test_mod4_single_writer.py`, image smoke test | ✅ (short-term remedy; reload-on-write is R3) |
| ACT-1 | Intent committed before each call, result after; after a crash every call is listed with its state | `IntentLogTests`, fault matrix | ✅ |
| ACT-2 | The same key across retries, resumes and restarts; header and payload; Python tools get it | `IdempotencyKeyTests` | ✅ |
| ACT-3 | Outcomes classed; only not-sent and retryable rejections retried; unknown → `uncertain`; no fallback after unknown | `OutcomeClassificationTests`, fault matrix | ✅ |
| ACT-4 | Declared confirmation fields and statuses; `202`/`{}` → `pending_confirmation`; only a confirmed reply applies effects | `ConfirmationTests`, fault matrix | ✅ |
| ACT-5 | Resume, deferred retries and automation retries never re-execute; `GET /api/reconciliation`; a person resolves, audited; the run continues | `RecoveryTests`, fault matrix | ✅ |
| ACT-6 | Records re-read on resume; a changed reviewed fact requires a new review | `test_act6_revalidation.py` | ✅ |
| ISO-1 | MCP serves one use case of the member's own workspace | `test_iso1_mcp_per_workspace.py` | ✅ |
| ISO-2 | Per-workspace derived audit keys; a chain from one workspace does not verify in another | `test_iso2_workspace_audit_keys.py` | ✅ |
| ISO-3 | Per-workspace OIDC; workspace A's tokens refused by B | `test_iso3_oidc_per_workspace.py` | ✅ |
| LEG-1 | Licence and third-party notices | `test_leg1_licences.py` | ✅ in the repository; legal sign-off external |

**R1 exit criteria (PRD §6).** G1 (duplicates or false confirmations) = 0 in the 112-combination fault matrix;
G2 (unauthorised actions or disclosures) = 0 in the entry-point matrix and the audit's PoC tests; G3
(cross-workspace access) = 0 in the workspace and ISO tests; licence decided (D5). **Met in the repository.**

## 5. Gate 80 review (audit's criteria)

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 80.1 | No external action falsely reported as confirmed | `test_external_effects_matrix.py`: 0 in 112 combinations | ✅ Repo |
| 80.2 | No duplicate after timeout, crash, retry, fallback, resume or concurrency | Same matrix: ≤ 1 bank execution everywhere; `test_one_run_per_record.py` for concurrency | ✅ Repo |
| 80.3 | Every in-flight action traceable after a crash | Same matrix: the executed call is in the journal with the bank's key | ✅ Repo |
| 80.4 | Zero unauthorised actions or disclosures | `test_entry_point_matrix.py` (150+ refusals, 0 unauthorised 2xx; it found one over-broad tool list, fixed) and the PoC tests | ✅ Repo |
| 80.5 | No known open Critical or High defect | All Critical fixed. High: residual parts of GAP-009 (atomic write-back) and GAP-018 (reload on write) are lower-risk; GAP-031 waits for legal; GAP-032/052/053 are evidence gaps that gate 90 measures | ⚠️ Repo met for defects; see register |
| 80.6 | Strict ontology validation | `test_mod1_strict_schema.py` | ✅ Repo |
| 80.7 | Licence and notices; legal sign-off | Files present and checked in CI | ⚠️ Legal sign-off external |
| 80.8 | Existing suite green, nothing skipped, CI on 3.10 and 3.13 | 548 tests locally; CI test jobs green on every commit | ✅ Repo |

**Conclusion.** The R1 safety and isolation gates (80.1–80.4, 80.6, 80.8 and G3) are satisfied by repository
evidence. Studio work in R2 may start on that basis. The legal item and an independent re-verification remain
open and are not prerequisites for building, only for distributing.

## 6. Maturity assessment (self-assessed)

Same method, subcriteria, weights and evidence caps as the audit ([03](../audit/03_AUTOLOGY_MATURITY_SCORECARD.md));
credit is restored only where the cause of a deduction was removed and a test shows it. **This is a self-assessment
by the same AI agent that wrote the fixes**: the audit's **47 / 100 remains the last independently verified
score** until a re-audit.

| # | Subcriterion | Max | Audit | Now | Why |
|---|---|---|---|---|---|
| 1.1 | Ontology model and validation | 8 | 5.5 | 6.4 | GAP-016 fixed (capped at 80 % for B evidence); GAP-027/028 open |
| 1.2 | Agent engine | 8 | 5.5 | 6.0 | GAP-017 fixed; no real-model evidence; GAP-029 open |
| 1.3 | State, persistence, recovery | 6 | 2.5 | 4.2 | Intent journal, typed outputs, one writer; GAP-041 open |
| 1.4 | Maintainability | 4 | 2.0 | 2.0 | Unchanged; the service grew (GAP-026) |
| 1.5 | Agnosticism | 4 | 3.0 | 3.0 | Unchanged; one provider adapter |
| 2.1 | Governance across entry points | 8 | 4.0 | 6.4 | GAP-011/012/013 fixed, D4 intersection, entry-point matrix |
| 2.2 | Auditability | 5 | 3.0 | 3.7 | GAP-014 and GAP-007 fixed; GAP-020 open |
| 2.3 | Test depth | 5 | 3.5 | 3.9 | Fault-injection and entry-point matrices; no load tests |
| 2.4 | Quality gates | 2 | 0.5 | 0.6 | Licence gate added; still no mypy, linting, vulnerability audit |
| 3.1 | Outbound execution reliability | 8 | 1.0 | 5.6 | Core requirement met against a simulated bank; no real ERP; no automated confirmation polling |
| 3.2 | Recovery and reconciliation | 4 | 0.5 | 2.8 | Recovery and reconciliation API |
| 3.3 | Inbound integration | 4 | 3.0 | 3.0 | Unchanged |
| 3.4 | Consistency under concurrency | 4 | 1.0 | 2.8 | GAP-008 and GAP-009 fixed; write-back not atomic |
| 4.1 | Authentication | 4 | 3.0 | 3.0 | Per-workspace OIDC added; GAP-019/030 open |
| 4.2 | Authorization and data protection | 4 | 2.0 | 2.8 | GAP-011/012/013 fixed; no encryption at rest (D3) |
| 4.3 | Input hardening | 2 | 0.5 | 1.1 | GAP-015 fixed; GAP-038 open |
| 4.4 | Deployment, backup, observability | 5 | 3.0 | 3.0 | Unchanged; restore never exercised |
| 5.1 | Real end-to-end process | 5 | 0.5 | 0.5 | None yet |
| 5.2 | Real AI provider validation | 2 | 0.0 | 0.0 | None yet |
| 5.3 | Legal and distribution | 3 | 1.0 | 1.8 | Licence and notices; legal sign-off and a real release pending |
| 5.4 | Reuse and isolation | 3 | 1.0 | 1.8 | Organisation isolation built and tested; no real external system |
| 5.5 | Documentation and support | 2 | 1.0 | 1.0 | Unchanged |
| | **Total** | **100** | **47.0** | **≈ 65** | |

| Score | Audit | Self-assessed now |
|---|---|---|
| A — Technical framework | 59 | 72 |
| B — Enterprise operational readiness | 44 | 71 |
| C — Commercial product readiness | 41 | 47 |
| **Overall** | **47** | **≈ 65 (not independently verified)** |
| Use case / workspace readiness (scorecard of §10 of the instructions) | not measurable | **not yet measurable** (REL-3, R2) |

Score C barely moves on purpose: it rests on real-world evidence (a pilot, real models, a release, legal), which
no repository change can supply. The path to 95 still needs gates 90 and 95, whose criteria are mostly external.

## 7. Known limitations carried into R2

- People confirm uncertain and pending calls; no automated status polling yet.
- Write-back is still field by field (GAP-009 residual); reload-on-write for GAP-018 is not built.
- One AI provider adapter; no real-model evaluation.
- `AutologyService` grew during R1 (GAP-026); store migrations still run outside a transaction (GAP-041).
- The fault matrix uses a simulated bank: it proves Autology's side of the contract, not any real ERP's.

## 8. Résumé exécutif (français)

La release R1 est terminée. Tous ses récits sont livrés et testés :
- **Gouvernance (GOV-1 à 5) :** notamment l'intersection des droits de l'utilisateur et de l'agent (D4).
- **Modèle (MOD-1 à 4) :** schéma strict, enregistrements absents traités comme inconnus, sorties typées, un seul écrivain par base.
- **Sûreté des actions externes (ACT-1 à 6) :** journal d'intention, clés d'idempotence, aucun rejeu à l'aveugle, contrat de confirmation, réconciliation humaine, re-vérification après revue.
- **Isolation par workspace (ISO-1 à 3) :** MCP, clés d'audit et connexion d'entreprise.
- **Licence propriétaire (LEG-1).**

Deux points manquaient à la liste R1 et ont été ajoutés pour satisfaire la porte 80 de l'audit : GAP-018 et une matrice des points d'entrée. La matrice d'injection de pannes (112 combinaisons) ne montre aucun doublon et aucune fausse confirmation. La matrice des points d'entrée ne montre aucun accès non autorisé ; elle a révélé et fait corriger une liste d'outils trop large.

Une erreur réelle n'a été visible qu'en CI : un conteneur redémarré se voyait refuser l'accès à sa base. Elle est corrigée (`f0a385a`) et le test du conteneur passe localement sur une image reconstruite.

Bilan :
- **Tests :** 548 passent.
- **Portes de sûreté et d'isolation R1 :** satisfaites par les preuves du dépôt.
- **Reste ouvert :** la validation juridique de la licence et une revérification indépendante.
- **Maturité :** environ 65/100 en auto-évaluation, contre 47 à l'audit. Ce chiffre n'est pas vérifié de façon indépendante ; le 47 reste le dernier score vérifié.
- **Maturité par cas d'usage :** pas encore mesurable.

Aucun déploiement en production n'a été effectué. Le plan R2 est dans [AUTOLOGY_R2_PLAN.md](AUTOLOGY_R2_PLAN.md).
