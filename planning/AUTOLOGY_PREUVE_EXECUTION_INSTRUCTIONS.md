# Preuve d'exécution — instructions maîtresses du 14 novembre 2026

> **Mise à jour :** la release R1 est terminée depuis ce document ; voir [AUTOLOGY_R1_CLOSEOUT.md](AUTOLOGY_R1_CLOSEOUT.md) pour les preuves à jour.

*Établi le 14 novembre 2026 sur la branche `claude/autology-ontology-agent-4ajjer`, commit `e69f06d`.
Document : `AUTOLOGY_CLAUDE_CODE_MASTER_INSTRUCTIONS_2026-11-14.md` (186 lignes, MD5 `c1efa262f6c1c59219ab02a39f162f00`).*

## 0. Réponse courte

Le fichier a été suivi **dans l'ordre qu'il impose** (§12 : « audit d'abord, puis tranche verticale ») :

- **Phase 0 (vérité du dépôt et contrats)** : faite.
- **Phase 1 (fondation des workspaces)** : faite pour l'API REST, avec tests d'isolation adverses.
- **Correctifs de gouvernance P0** exigés avant toute donnée client : GAP-008, 011, 012, 013, 014 et 015 corrigés.
- **Phases 2 à 6** (Studio et AI Solution Architect, Excel Factory, organisation et Agent Factory, Integration Hub,
  portes de mise en production) : **non commencées**. Elles sont planifiées dans le PRD et le backlog.

Le fichier n'est donc **pas exécuté en entier**. Ce document montre ce qui l'est, avec des preuves vérifiables, et
ce qui ne l'est pas.

## 1. Preuves vérifiables par n'importe qui

| Preuve | Où la vérifier |
|---|---|
| 8 commits depuis la réception des instructions (10:18 → 11:44) | `git log --oneline 5400ad8^..e69f06d` |
| CI GitHub verte sur chaque commit (Python 3.10 et 3.13, PostgreSQL réel, couverture ≥ 95 % imposée) | Actions, runs n° 18 à 24 (dernier : run 43591491413, `success`) |
| Suite complète : **472 tests, 0 échec** (2 tests PostgreSQL ignorés localement, exécutés en CI) | `AUTOLOGY_AUDIT_KEY=k python -m unittest discover -s tests -t .` |
| Tests propres à ce travail : **37 tests, OK** (relancés pour ce document en 4,1 s) | `python -m unittest -v tests.test_workspaces tests.test_api_exchange tests.test_gov1_manual_firing tests.test_gov2_scenario_fields tests.test_gov3_requester_scope tests.test_gov4_run_record_seal` |
| Chaque correctif écrit « test d'abord » : les nouveaux tests échouaient avant la correction | Journal (`AUTOLOGY_IMPLEMENTATION_LOG.md`) : GOV-1 3 échecs, GOV-2 4, GOV-3 4, GOV-4 5 |
| Les 7 documents exigés au §14 existent, plus le PRD | `planning/` (8 fichiers, 660 lignes) |

## 2. Traçabilité section par section

Statuts : **Fait** · **Partiel** · **Non commencé** · **Non vérifiable ici**.

| § | Exigence | Statut | Preuve ou raison |
|---|---|---|---|
| 1 | Lire le dépôt, comparer au PDF, classer chaque capacité | **Fait** | `AUTOLOGY_CURRENT_STATE_AND_GAPS.md` §1 (PDF contre code) et §2 (classement Vérifié / Partiel / Manquant avec sources) ; audit du 13 nov. dans `audit/` |
| 1 | Ne pas reprendre 60/100 comme base | **Fait** | Score mesuré 47/100 (audit) ; non re-mesuré depuis, écrit tel quel |
| 2.1 | Un seul moteur, agnostique | **Fait** (préservé) | Aucun nouveau moteur ; la plateforme réutilise `AutologyService` tel quel (`autology/platform.py`) |
| 2.4 | Hermes optionnel, jamais une dépendance | **Fait** (par absence) | Aucune dépendance Hermes ajoutée ; adaptateur non commencé (§8) |
| 2.5 | Isolation des workspaces côté serveur | **Fait (REST)** / **Partiel** | Base dédiée par cas d'usage, secrets par workspace, 404 identiques : `tests/test_workspaces.py` (11 tests). MCP, OIDC et événements par workspace : non faits |
| 2.6 | Cas d'usage indépendants | **Fait** | `examples/platform` : un workspace, deux cas d'usage, deux ontologies |
| 2.7 | Rien d'approuvé implicitement par l'IA | **Fait** (renforcé) | GOV-1 : qui déclenche ne peut pas approuver ; l'assistant propose, la personne confirme (`tests/test_governance_extras.py`) |
| 2A | Moteur sans interface, UI séparées | **Partiel** | Moteur testé sans UI ; Console = processus séparé via l'API publique. Reste : boîte de revue servie par le moteur, UI dans le même paquet Python |
| 2A | Contrat OpenAPI versionné | **Non commencé** | Backlog P1-1 |
| 3 | Modèle Platform / Blueprint / Workspace / Use Case / Release | **Partiel** | Workspace et Use Case faits ; Blueprint et Release non faits |
| 4 | AI Solution Architect, questions dynamiques | **Non commencé** | Phase 2 |
| 5 | Excel Template Factory et import gouverné | **Non commencé** (base existante) | Ingestion CSV/JSON/SQL avec quarantaine et traçabilité déjà présente ; pas de `.xlsx` (décision `openpyxl` en attente) |
| 6 | Organisation humaine et agents | **Non commencé** | Phase 4 |
| 7 | Agent Factory | **Non commencé** | Phase 4 |
| 8 | Integration Hub, sûreté des actions externes | **Non commencé** | GAP-001 à 007 encore ouverts : aucune écriture ERP réelle n'est autorisée tant qu'ils le sont |
| 9 | Studio et UI utilisateur | **Partiel** | Console avec onglet Configuration ; pas de Studio |
| 10 | Scores (A) et (B), portes de production | **Partiel** | (A) 47/100 mesuré, non re-mesuré ; (B) **non mesurable** ; aucune porte de promotion |
| 11 | Sécurité : contexte workspace partout, entrées sûres | **Partiel** | REST fait ; corps de requête sûrs (GAP-015) ; MCP, recherche, exports par workspace non faits |
| 12 | Phases 0 et 1 avant les données client | **Fait** | Commits `4509b97`, `e157e5b` |
| 12 | Petits commits réversibles, branche dédiée | **Fait** | 1 commit par récit, poussés sur la branche désignée uniquement |
| 14 | Les 7 documents | **Fait** | `planning/` |
| 14 | Résumé exécutif en français | **Fait** | Fin de chaque rapport, et §5 ci-dessous |

## 3. Les 11 tests d'acceptation (§13)

| # | Test | Statut | Preuve |
|---|---|---|---|
| 1 | Deux workspaces ne se lisent ni ne se modifient | **Partiel** | REST : `test_data_written_in_one_workspace_never_appears_in_the_other`, `test_runs_reviews_and_audit_stay_inside_the_workspace`, `test_foreign_or_unknown_workspaces_are_indistinguishable`. Pas encore « par tous les points d'entrée » (MCP, OIDC) |
| 2 | Un workspace, deux cas d'usage différents | **Partiel** | Ontologies et acteurs différents : `test_members_see_only_their_workspace_and_granted_use_cases` ; états de maturité distincts non démontrés |
| 3 | Brief Oil & Gas puis pharma, même moteur | **Non commencé** | Phase 2 |
| 4 | Questions dynamiques et pack Excel | **Non commencé** | Phases 2–3 |
| 5 | Import de modèles avec erreurs par ligne | **Non commencé** | Phase 3 |
| 6 | Organigrammes liés, aucun droit activé sans approbation | **Non commencé** | Phase 4 |
| 7 | Recalcul de la maturité | **Non commencé** | Phase 6 |
| 8 | 97/100 avec un échec critique ne passe pas en production | **Non commencé** | Phase 6 (aucune API de promotion encore) |
| 9 | Panne Hermes sans effet | **Non commencé** | Pas d'adaptateur Hermes |
| 10 | Pas de succès annoncé avant confirmation, pas de doublon | **Partiel** | GAP-008 corrigé (un seul run ouvert par dossier : `tests/test_one_run_per_record.py`) ; GAP-001 à 007 ouverts |
| 11 | Comportement existant préservé | **Fait** | 472 tests OK, couverture ≥ 95 % en CI. Six tests modifiés parce qu'ils encodaient le défaut GAP-013, listés dans le journal |

## 4. Ce qui a été corrigé, avec le test qui le prouve

| Récit / écart | Défaut avant | Test |
|---|---|---|
| GAP-015 | Un `Content-Length` négatif contournait la limite de 1 Mo sans authentification | `tests/test_api_exchange.py` |
| GAP-008 | Deux runs ouverts pouvaient payer le même sinistre | `tests/test_one_run_per_record.py` |
| GOV-1 / GAP-011 | Déclencher une automatisation à la main permettait d'approuver sa propre revue | `tests/test_gov1_manual_firing.py` |
| GOV-2 / GAP-012 | Les scénarios « et si » révélaient des champs masqués | `tests/test_gov2_scenario_fields.py` |
| GOV-3 / GAP-013 | Un utilisateur pouvait faire agir l'agent sur des enregistrements qu'il ne voit pas | `tests/test_gov3_requester_scope.py` |
| GOV-4 / GAP-014 | Modifier `pending_review.action` en base permettait de sauter une revue, sans détection | `tests/test_gov4_run_record_seal.py` |

## 5. Limites honnêtes

- **Pas de validation avec un vrai modèle** enregistrée comme preuve : votre connexion Claude du 14 novembre est
  manuelle, sur votre PC.
- **Aucun système réel** (Odoo, SAP, Power BI, Hermes) n'a été testé : non disponible ici, et interdit en écriture
  par les instructions sans environnement isolé.
- **Le score 47/100 n'a pas été re-mesuré** : six écarts sont fermés, mais seul un nouvel audit peut donner un
  chiffre. Je n'en invente pas.
- **Décisions en attente de votre part** : D1 (modèle de déploiement), D4 (rôles du demandeur ∩ rôles de l'agent),
  D5 (licence), D6 (pilote et accès Odoo), D7 (fournisseurs d'IA), `openpyxl`.

## 6. Prochaine étape

Finir la release R1 du PRD : MOD-1 (schéma d'ontologie strict, GAP-016), MOD-2, MOD-3, puis ACT-1 à ACT-6 (sûreté
des actions externes, GAP-001 à 007), condition de toute intégration ERP.
