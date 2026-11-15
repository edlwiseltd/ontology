# Autology — prochains incréments proposés (15 novembre 2026)

*Propositions issues de l'audit du HEAD `a143ed378c11e5f9c71671acb360f994d52e2f06`. **Ce ne sont pas des
autorisations.** Aucun de ces incréments n'est commencé ; chacun attend l'accord explicite du propriétaire. Les
tailles S/M/L sont des ordres de grandeur, avec leurs hypothèses : S = un module et ses tests, moins de 2 jours ;
M = plusieurs modules, un schéma de store, 3 à 6 jours ; L = plus.*

L'ordre suit les écarts trouvés et non la directive précédente : celle-ci plaçait l'administration avant les
releases, mais l'audit montre que l'absence de releases liées à l'empreinte est l'écart d'intégrité le plus
structurant (F-04/GAP-020, « release modifiée après approbation » non couvert), et qu'il conditionne l'administration,
la readiness et l'activation des brouillons.

---

## Recommandation unique : **REL-1a — releases immuables liées à l'empreinte**

**Pourquoi maintenant.** C'est le seul écart qui touche directement la promesse « décision gouvernée et vérifiable » :
une revue approuvée reste valide si la politique change sans changement de version. Les releases sont aussi le
prérequis de l'activation des brouillons de Studio, du rollback, de la readiness (REL-3) et de l'écran Releases
(STU-6). L'incrément n'exige **aucune** décision externe pour sa partie technique. Seule la règle d'approbation
indépendante des promotions dépend de D11 ; elle est séparée en REL-2a.

**Alternative si le propriétaire préfère d'abord des gains rapides, ou si la conception de REL-1a doit attendre une
décision : H-1, durcissement** (ci-dessous). Il est indépendant de tout et de taille S.

---

## Incrément 1 — REL-1a : releases immuables, runs et décisions liés à l'empreinte, rollback (M à L)

| Rubrique | Contenu |
|---|---|
| Résultat métier | Chaque cas d'usage s'exécute sur une release figée et adressée par son contenu. Une décision de revue n'est valable que pour la release sur laquelle elle a été prise. On peut revenir à la release précédente |
| Prérequis | Aucun externe ; MIG (migrations transactionnelles, déjà en place) |
| Modules et contrats | `autology/lifecycle.py` (table `releases` append-only, empreinte SHA-256 du document d'ontologie et de la configuration gouvernante) ; `store.py` (schéma 16, avec la référence de release sur les runs et les revues) ; `server.py` (`decide`, `resume` : comparer l'empreinte, pas seulement `name@version`) ; `platform.py` (`/platform/v1/.../releases`, `POST .../releases` depuis un brouillon validé, `POST .../rollback`) ; `openapi.py` (schémas) ; Studio en lecture seule (liste des releases) |
| Critères d'acceptation | (1) Une release est immuable : aucune route ne la modifie et un trigger l'empêche. (2) Modifier l'ontologie à version égale invalide toute revue en attente (409 ou escalade), test qui échoue sur le code actuel. (3) Un run démarré sur la release N continue sur N après la publication de N+1, ou s'arrête explicitement selon la politique documentée. (4) Le rollback réactive N−1, il est audité, et les runs en cours suivent la règle (3). (5) Un brouillon invalide ne peut pas devenir une release. (6) Isolation : release d'un autre espace → 404 identique. (7) Contrats v1 et types Studio régénérés, sans dérive en CI |
| Preuves exigées | Nouveaux tests Python, dont au moins un qui échoue sur `a143ed3` ; suite complète ; couverture ≥ 95 % ; CI verte sur les 4 jobs ; e2e Studio avec une vérification de la liste des releases |
| Sécurité et gouvernance | Ferme F-04/GAP-020. Production toujours refusée (PROD). Aucune promotion supplémentaire n'est permise : la création d'une release n'est pas une promotion de stade |
| Complexité | **M à L** (hypothèse : 5 à 8 jours ; schéma de store et sémantique des runs en cours) |
| Décisions avant travail | Aucune décision bloquante. À confirmer : la politique des runs en cours lors d'un rollback (continuer sur N ou s'arrêter). La recommandation de l'audit est de les arrêter, d'escalader, et de ne jamais les migrer silencieusement |

## Incrément 2 — H-1 : durcissement ciblé (S)

| Rubrique | Contenu |
|---|---|
| Résultat métier | Corrige les deux constats Moyens du jour et réduit le risque d'approvisionnement, sans fonctionnalité nouvelle |
| Prérequis | Aucun |
| Modules | `ingest.py` (`_http` : `next` limité au même schéma, hôte et port, sinon refus ; pas d'envoi d'en-têtes secrets ailleurs) ; `adapters.py` (`HttpApprover` : `can_approve = True`, donc refusé hors simulation sauf drapeau explicite et audité ; relecteur vérifié contre les membres, anti-auto-revue) ; redirections sortantes désactivées ou limitées au même hôte, avec plafond de taille de réponse ; `Dockerfile` (digest) ; workflows (actions par SHA) ; mise à jour documentaire des registres (F-13), sans changer aucune décision |
| Critères d'acceptation | (1) Une page `next` vers un autre hôte est refusée et le serveur de test ne reçoit jamais le secret. (2) Un moteur non simulé configuré avec `HttpApprover` refuse de démarrer sans le drapeau explicite ; avec le drapeau, un relecteur égal à l'initiateur est refusé. (3) Une redirection vers un autre hôte n'est pas suivie. (4) CI verte, avec les actions épinglées par SHA |
| Preuves | Tests qui échouent sur `a143ed3` ; suite complète ; CI |
| Sécurité | Ferme F-01, F-02 (et F-08 en partie) ; GAP-040 en partie |
| Complexité | **S** (2 jours ; hypothèse : aucune configuration d'exemple n'utilise `HttpApprover` en production) |
| Décisions | Le propriétaire confirme qu'un approbateur HTTP externe ne doit **pas** compter comme revue humaine par défaut |

## Incrément 3 — QA-1 : lint, typage, scan en CI avec cliquet (S à M)

| Rubrique | Contenu |
|---|---|
| Résultat métier | Les régressions de type et les dépendances vulnérables sont détectées avant la fusion |
| Prérequis | Aucun |
| Modules | `.github/workflows/tests.yml` (ruff avec règles F et B, mypy avec une base figée à 201 erreurs qui ne peut que baisser, pip-audit sur les contraintes, `npm audit --omit=dev`) ; outils épinglés |
| Critères | (1) CI échoue sur une nouvelle erreur mypy ou un nouvel import inutilisé. (2) CI échoue sur une vulnérabilité connue de gravité haute. (3) La base d'erreurs est versionnée et ne peut que diminuer |
| Preuves | Un commit de démonstration qui introduit une erreur et fait échouer la CI (sur une branche jetable, non fusionnée) |
| Sécurité | Ferme GAP-025 dans sa forme minimale |
| Complexité | **S à M** (1 à 3 jours ; hypothèse : on n'exige pas zéro erreur mypy) |
| Décisions | Aucune |

## Incrément 4 — ADM-1a : administration des membres et accords, proposée puis approuvée (M)

| Rubrique | Contenu |
|---|---|
| Résultat métier | Un administrateur ajoute ou retire des membres et propose des accords sans éditer de fichier ni redémarrer. Un accord ne devient actif qu'après approbation par une autre personne |
| Prérequis | REL-1a recommandé (l'audit des changements suit le même modèle append-only) ; **D11 pour l'espace à admin unique** |
| Modules | `platform.py` (table append-only `admin_changes`, `/platform/v1/workspaces/{ws}/members`, `/grants`, `/grants/{id}/approve`) ; rechargement à chaud (ADM-2 minimal) ; Studio (écran Membres) |
| Critères | (1) Le proposeur ne peut jamais approuver son propre accord. (2) Une tentative inter-espaces renvoie un 404 identique. (3) La révocation prend effet à la requête suivante. (4) Chaque changement est chaîné en HMAC. (5) Sans D11, un espace à admin unique **ne peut pas** activer d'accord (fail closed, message explicite) |
| Preuves | Tests de séparation des tâches ; e2e Studio ; CI |
| Sécurité | Ferme une partie de GAP-051 ; pas d'auto-escalade |
| Complexité | **M** (4 à 6 jours) |
| Décisions | **D11** (mécanisme pour l'admin unique) ; D14 confirmé |

## Incrément 5 — REL-3a : readiness par cas d'usage, 6 dimensions, mode consultatif (M)

| Rubrique | Contenu |
|---|---|
| Résultat métier | Chaque cas d'usage a un score de 0 à 100 sur les 6 dimensions canoniques (`planning/AUTOLOGY_MATURITY_SCORECARD.md:84-90`), avec des preuves, des bloqueurs et un historique. Les gates obligatoires restent les contrôles serveur existants |
| Prérequis | REL-1a (le score est calculé par release et invalidé quand la release change) |
| Modules | nouveau `readiness.py` réutilisant `scoring.py` et les contrôles de `lifecycle.py` ; `/platform/v1/.../readiness` ; Studio (tableau de bord en lecture seule) |
| Critères | (1) Chaque métrique a une formule, un dénominateur, une source de preuve et une confiance. (2) Un critère sans preuve est « non évalué », ni récompensé ni pénalisé. (3) Une modification de la release invalide les preuves concernées. (4) Le score ne débloque jamais une gate obligatoire |
| Preuves | Tests de formules ; exemple calculé sur `examples/platform` ; CI |
| Sécurité | Aucune élévation possible : consultatif uniquement |
| Complexité | **M** (4 à 6 jours) |
| Décisions | Validation des poids de départ (20/15/15/20/15/15) et de la liste consultatif / obligatoire par le propriétaire |

---

## Non recommandés pour l'instant (et pourquoi)

| Option | Raison |
|---|---|
| AI-1 / ARC-1 avec un vrai fournisseur | Bloqué par **D7/D10**. Seule une interface neutre avec un fournisseur fictif serait possible ; elle a moins de valeur que REL-1a aujourd'hui |
| Connecteur Odoo sandbox (R4) | Dépend de D6/D13 et gagne à arriver après les releases (liaison décision ↔ release) |
| Runtime de plugins | Direction stratégique non approuvée ; une preuve de concept minimale est décrite dans l'audit technique (§6) |
| Workspace UI (R5), Excel (R3) | Hors priorité R2 |

**Attente :** aucune implémentation tant que le propriétaire n'a pas autorisé explicitement un incrément.
