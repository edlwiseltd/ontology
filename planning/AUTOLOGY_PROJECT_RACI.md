# Autology — RACI du projet et contrôle d'accès

*15 novembre 2026. Gouvernance du **projet** Autology : qui décide de quoi, qui réalise, qui est consulté et qui est
informé. Ce n'est pas le RACI du produit, c'est-à-dire ce que la plateforme applique aux utilisateurs ; celui-ci est
dans `docs/workspaces.md` et `docs/platform.md`. Les rôles « à nommer » n'existent pas encore. Les recommandations
sont signalées comme telles : le propriétaire décide.*

**Légende**

| Lettre | Sens |
|---|---|
| **R** | Réalise |
| **A** | Approuve et rend compte (une seule personne par ligne) |
| **C** | Consulté avant |
| **I** | Informé après |

## 1. Rôles

| Code | Rôle | Qui aujourd'hui | Statut |
|---|---|---|---|
| **PO** | Propriétaire du produit / direction | Le titulaire du compte GitHub `edlwiseltd` | En place (seule personne ayant accès) |
| **ING** | Ingénierie : agent IA de développement (Claude Code) | Sessions Claude Code | En place. Développe, teste, documente, pousse sur sa branche de travail. **Ne décide rien** à la place du PO (registre des décisions) |
| **REV** | Relecteur technique humain | — | **À nommer.** Aujourd'hui, aucun humain ne relit le code avant sa publication |
| **JUR** | Conseil juridique (avocat) | — | **À nommer** (D19 : licences L1–L9) |
| **SEC** | Revue de sécurité indépendante / test d'intrusion | — | **À nommer** (GAP-054) |
| **DPO** | Protection des données | — | **À nommer** (D10, D18, données du pilote) |
| **APP** | Approbateur indépendant des releases et des droits (D11) | Exemple uniquement (`maria` dans les données de démonstration) | **À nommer** pour chaque espace de travail réel |
| **CLI** | Client pilote : sponsor métier et DSI | — | **À identifier** (D16) |
| **OPS** | Exploitation et hébergement | — | **À nommer** (aucune production : décision PROD) |

## 2. Matrice RACI

### 2.1 Pilotage et développement

| Activité | PO | ING | REV | JUR | SEC | DPO | APP | CLI | OPS |
|---|---|---|---|---|---|---|---|---|---|
| Priorités, autorisation de chaque incrément | **A** | C | C | | | | | I | |
| Conception et réalisation du code | I | **R** | C | | | | | | |
| Tests automatiques et CI verte | I | **R** | C | | | | | | |
| Relecture humaine du code avant fusion | **A** | C | **R** | | C | | | | |
| Fusion dans la branche principale | **A** | C | R | | | | | | |
| Publication d'une version (tag, package, image) | **A** | R | C | C | C | | | I | R |
| Documentation et registres (défauts, décisions, journal) | I | **R** | C | | | | | | |
| Signalement d'un défaut ou d'un risque | **A** (décide de la suite) | R | R | | R | R | | R | R |

### 2.2 Décisions ouvertes du registre

| Décision | PO | ING | REV | JUR | SEC | DPO | APP | CLI | OPS |
|---|---|---|---|---|---|---|---|---|---|
| D2 Base opérationnelle (SQLite / PostgreSQL) | **A** | C | C | | | | | C | R |
| D3 Chiffrement au repos | **A** | C | | | C | C | | C | R |
| D7/D10 Fournisseurs d'IA, données transmises, résidence | **A** | C | | C | C | **R** | | C | |
| D11 Approbateur indépendant par espace | **A** | I | | | C | | R | C | |
| D13 Coffre-fort de secrets | **A** | C | | | C | | | | R |
| D15 Écritures ERP en production | **A** | C | | C | C | C | | C | R |
| D16 Pilote client et données | **A** | C | | C | | C | | **R** | |
| D17, D18, D20 (valeurs par défaut appliquées, à confirmer) | **A** | R | | | | C | | I | |
| D19 Licences, entité légale, propriété intellectuelle (L1–L9) | **A** | C (faits techniques) | | **R** | | | | | |
| PROD Autorisation d'une mise en production | **A** | C | C | C | C | C | | C | R |

### 2.3 Sécurité, données et exploitation

| Activité | PO | ING | REV | JUR | SEC | DPO | APP | CLI | OPS |
|---|---|---|---|---|---|---|---|---|---|
| Revue de sécurité indépendante et test d'intrusion | **A** | C | I | | **R** | | | I | C |
| Correction des failles trouvées | **A** | R | C | | C | | | | |
| Gestion des clés (`AUTOLOGY_AUDIT_KEY`, clés d'IA, identifiants d'intégration) | **A** | C | | | C | | | | **R** |
| Approbation des releases et des droits dans un espace réel | I | | | | | | **R/A** | C | |
| Données personnelles du pilote | C | C | | C | | **A** | | **R** | C |
| Incident en production (quand elle existera) | **A** | C | | | C | C | | I | **R** |

## 3. Contrôle d'accès du projet

### 3.1 État vérifié le 15 novembre 2026

| Ressource | Accès constaté | Source |
|---|---|---|
| Dépôt GitHub `edlwiseltd/ontology` | Un seul collaborateur : `edlwiseltd`, rôle **admin** | API GitHub (collaborateurs) |
| Branches | Deux branches : `claude/autology-ontology-agent-4ajjer` (travail courant) et `claude/new-session-aee75a`. **Aucune n'est protégée** et il n'existe pas de branche `main` | API GitHub (branches) |
| Agent IA (Claude Code) | Lecture et écriture limitées à ce dépôt ; il pousse uniquement sur sa branche de travail, sans pull request ni fusion sans demande explicite | Consignes de la session |
| CI (GitHub Actions) | Droits du workflow : `contents: read` ; aucun secret du dépôt n'est utilisé ; la clé d'audit de la CI est une valeur de test | `.github/workflows/tests.yml` |
| Paternité du code | Les 104 commits ont été produits par l'agent IA ; aucune relecture humaine n'est enregistrée | `git log` (voir L7 du dossier juridique) |
| Plateforme (produit) | Administrateurs d'espace dans `platform.json` ; membres et droits par API avec approbation indépendante (ADM-1) | `docs/workspaces.md` |
| Production, données clients, ERP | **Aucun accès** : rien de tout cela n'existe (décisions PROD et D15) | Registre des décisions |

### 3.2 Écarts

| # | Écart | Risque |
|---|---|---|
| E1 | Aucune branche protégée : toute personne ayant accès en écriture peut réécrire l'historique | Perte ou altération du code sans trace |
| E2 | Aucune relecture humaine : le code est écrit et publié par l'agent IA, et seule la CI le vérifie | Qualité, sécurité, et propriété intellectuelle (L7) |
| E3 | Un seul administrateur : aucune séparation des tâches au niveau du dépôt, aucun suppléant | Personne clé ; pas de quatre yeux |
| E4 | APP, JUR, SEC, DPO, OPS non nommés | Les décisions D11, D19, D10, D3 et PROD ne peuvent pas aboutir |

### 3.3 Recommandations (à décider par le PO)

1. **Créer une branche principale protégée** : CI verte obligatoire (5 jobs), pas de force-push, pas de suppression.
   L'agent IA continue de travailler sur ses branches `claude/*` et ouvre des pull requests.
2. **Nommer un relecteur technique humain (REV).** Exiger une approbation humaine avant chaque fusion : le
   relecteur ne doit pas être l'auteur, ce qui exclut l'agent IA.
3. **Ajouter un second administrateur de confiance** du dépôt et activer l'authentification à deux facteurs pour
   tous les comptes. Je ne peux pas vérifier la 2FA d'ici.
4. **Nommer, pour chaque espace de travail réel, un approbateur indépendant (APP)** dans `release_approvers` (D11).
5. **Mandater JUR (D19) et SEC (GAP-054)** avant tout pilote client.
6. Conserver les clés hors du dépôt : variables d'environnement aujourd'hui, coffre-fort de secrets après D13.

Ces recommandations n'ont pas été appliquées : modifier les protections du dépôt ou les comptes relève du PO. La
décision correspondante est enregistrée comme **D21** dans le registre des décisions.
