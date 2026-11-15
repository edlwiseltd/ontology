# Autology — Gestion multi-tenant des identités et des accès (IAM) : cible et analyse de l'existant

*15 novembre 2026. Le modèle cible a été proposé par le propriétaire, qui recommande de le retenir comme exigence
cible ; il est enregistré comme **direction approuvée (D22)**. Ce document vérifie d'abord ce qui existe dans le
code, pour que la cible **étende** le système d'identité actuel sans en créer un second. Mise à jour du même jour :
**IAM-1 (tenants) et IAM-3 (séparation administration / données) sont implémentés** (directive IAM, D22a décidée :
moindre privilège par défaut) ; voir le journal d'implémentation. IAM-2, IAM-4, IAM-5 et IAM-6 ne sont pas
commencés. Les §2 et §3 décrivent l'état **avant** ces deux incréments.*

## 1. Modèle cible (propriétaire, 15 novembre)

Cinq profils. Ce sont des **catégories d'identité et de permissions, pas une hiérarchie** : aucun profil n'accède
automatiquement aux données d'un autre.

| Profil | Droits principaux |
|---|---|
| **Platform Administrator** | Gérer la plateforme, les tenants, les plugins autorisés et les opérations système. **Pas d'accès automatique aux données des clients** ; les accès exceptionnels sont limités, justifiés et audités |
| **Tenant Administrator** | Gérer les membres, les rôles, les applications, les politiques et les ressources de son tenant |
| **Internal User** | Employés, responsables, opérateurs, décideurs : tâches, données et actions explicitement autorisées |
| **Portal User** | Clients, fournisseurs, partenaires authentifiés : uniquement les ressources et services externes qui lui sont attribués |
| **Public Visitor** | Visiteur anonyme : contenus publics, recherches, demandes autorisées |

Trois décisions d'architecture :
1. **Le tenant est distinct du workspace.** Le tenant est l'organisation cliente ; il possède plusieurs workspaces,
   cas d'usage et applications publiques ou privées.
2. **Le Platform Administrator n'a pas accès par défaut aux données des clients.** Tout accès exceptionnel est
   justifié, limité et audité.
3. **Les agents IA et les plugins ont des identités de service distinctes**, avec leurs propres permissions et
   limites d'autonomie. Ils n'héritent jamais implicitement des droits d'un administrateur.

**Contrôle d'accès :** toutes les requêtes passent par les API de l'Engine, avec un contrôle par tenant, ressource,
action et contexte. Il combine RBAC (rôles), ABAC (attributs du sujet, de la ressource et du contexte) et les
politiques d'autonomie.

## 2. Existant vérifié dans le code (à préserver)

| Mécanisme | Ce qu'il fait | Où | Tests |
|---|---|---|---|
| Jetons d'API | Jeton aléatoire ; seul son SHA-256 est stocké ; comparaison en temps constant ; jetons uniques sur toute la plateforme | `server.py` (`new_token`, `hash_token`, `authenticate`), `platform.py` (`member_for`) | `test_platform`, `test_workspaces` |
| SSO OpenID Connect | Par moteur, ou **par workspace** (ISO-3) ; correspondance des claims vers permissions, rôles et rôles de revue ; vérifications strictes (RS*, iss, aud, exp, nonce, JWKS) | `oidc.py`, `platform.py` | `test_oidc`, `test_iso3_oidc_per_workspace` |
| Workspace | Isolation complète : stores, clés d'audit dérivées, préfixe de secrets ; 404 identiques hors périmètre | `platform.py` | `test_workspaces`, `test_iso1…4` |
| Membres et droits par cas d'usage | `workspace_admin` ou droits par cas d'usage : permissions, rôles, rôles de revue, `run_as` | `platform.py` (`Member`) | idem |
| Administration sans redémarrage | Ajout et retrait de membres, rotation de jetons ; droits **proposés puis approuvés par une autre personne** ; journal chaîné | `administration.py`, `platform.py` | `test_adm1_administration` |
| Personne / service | `kind: person / service` ; un service ne décide jamais une revue humaine et ne règle jamais un appel externe | `server.py`, `platform.py` | `test_h1_approval_identity` |
| Permissions (RBAC) | `read`, `run`, `review`, `audit`, `ingest`, `reconcile`, `admin` | `server.py` (`PERMISSIONS`, `User.can`) | `test_entry_point_matrix` |
| Rôles de l'ontologie (RBAC métier) | `action_access`, `data_access` et `write_access` (champs), `row_access` (lignes) | `governance.py` | `test_operations`, `test_visibility`, `test_multi_instance` |
| Conditions sur les ressources (ABAC partiel) | Les règles portent des conditions `when` sur les **attributs de la ressource** (ex. région) ; un fait inconnu applique la règle restrictive | `governance.py`, `expressions.py` | `test_review_integrity`, `test_visibility` |
| Contexte d'exécution | Stade du cas d'usage (draft, simulation, pilot) et environnement des outils | `lifecycle.py`, `server.py` | `test_r2_execution_gates` |
| Identités de service des automatisations | `service_identities` : rôles limités à des agents nommés (D4) | `server.py` | `test_gov5_effective_permissions` |
| Agents | Rôles effectifs = demandeur ∩ agent ; délégués restreints ; suspension | `agent.py`, `server.py` (`run_roles`) | `test_gov3_*`, `test_gov5_*`, `test_suspension` |
| Politiques d'autonomie | `human_review`, interdictions, approbateurs automatiques limités à la simulation, releases à quatre yeux | `governance.py`, `server.py`, `releases.py` | `test_core`, `test_approvals`, `test_rel1a_releases` |
| Applications clientes | Studio et Console n'ont **aucune identité propre** : ils transmettent le jeton de l'utilisateur, la plateforme décide | `studio/web/lib/forward.ts`, `console.py` | `test_studio_separation`, e2e |

**Conclusion :** il existe un seul système d'identité. La plateforme authentifie (jetons, OIDC), puis l'Engine
autorise (permissions, rôles, règles). La cible doit **étendre ce système**, pas en créer un second.

## 3. Écarts entre l'existant et la cible

| # | Exigence cible | Existant | Écart |
|---|---|---|---|
| I1 | Tenant distinct du workspace | Le workspace joue le rôle de l'organisation (D1 : un workspace par déploiement isolé) | **Absent :** aucun niveau tenant ; membres et administrateurs sont par workspace |
| I2 | Platform Administrator sans accès aux données | L'opérateur n'a **pas d'identité** dans Autology ; il édite `platform.json` et a un accès direct aux fichiers (stores SQLite non chiffrés, D3) | **Absent :** pas de rôle opérateur, pas d'accès exceptionnel audité ; l'accès aux fichiers n'est ni limité ni tracé |
| I3 | Tenant Admin gère sans voir forcément les données | `workspace_admin` donne `admin` sur **tous** les cas d'usage, et `admin` implique toutes les permissions, dont la lecture des données et de l'audit (`server.py:96`, `platform.py:74`) | **Partiel :** administration et accès aux données sont confondus |
| I4 | Internal User | Membres `person` avec droits explicites par cas d'usage | **Existant** (à rattacher au tenant) |
| I5 | Portal User | Aucune notion d'utilisateur externe ; aucune règle ne peut dire « ses propres enregistrements » (les conditions portent sur la ressource, pas sur le demandeur) | **Absent :** audience externe, inscription ou invitation, ABAC sur le sujet (propriétaire de la ressource) |
| I6 | Public Visitor | Seuls `health`, `openapi.json`, la config SSO et l'inbox statique sont anonymes ; aucune action métier publique | **Absent :** identité anonyme, actions publiques déclarées ; prérequis : limitation de débit (GAP-030) |
| I7 | Agents et plugins avec identités de service | Agents : rôles propres ∩ demandeur ; automatisations : `service_identities` ; `kind: service` | **Partiel :** pas d'identité de plugin (pas de runtime de plugins, B2) ; limites d'autonomie par identité non déclaratives (B6) |
| I8 | Contrôle par tenant, ressource, action et contexte | Workspace (isolation), cas d'usage, action et champs (rôles), conditions sur la ressource, stade | **Partiel :** il manque le tenant, les attributs du sujet (audience, organisation, propriétaire) et un contexte plus riche (canal public ou portail, heure, risque) |

## 4. Trajectoire proposée (incréments indépendants, chacun à autoriser)

Principe : **chaque incrément étend l'existant.** Mêmes jetons, même OIDC, même journal d'administration, même
`GovernanceLayer`. Pas de second annuaire.

| Incrément | Contenu | Réutilise | Taille (hypothèses) |
|---|---|---|---|
| **IAM-1 Tenant** (fait le 15 nov.) | Niveau `tenants` au-dessus des workspaces ; Tenant Admins ; membres rattachés au tenant avec des droits par workspace et par cas d'usage. **Compatibilité :** un workspace sans tenant devient un tenant à un seul workspace, de même identifiant, sans changement de comportement | Routeur, journal d'administration (ADM-1), OIDC par workspace étendu au tenant | M (5 à 7 j) |
| **IAM-2 Opérateurs de plateforme** | Identités d'opérateur distinctes (jetons ou OIDC propre) ; API de cycle de vie des tenants ; **aucune route de données**. Accès exceptionnel (« break-glass ») : demande justifiée, limitée dans le temps, approuvée selon D22b, enregistrée dans le journal **du tenant** et visible par lui | Jetons, journal chaîné, approbation indépendante (D11) | M (4 à 6 j). Les accès directs aux fichiers relèvent de l'exploitation (D3) |
| **IAM-3 Séparer administration et données** (fait le 15 nov.) | `workspace_admin` / Tenant Admin n'implique plus l'accès aux données ; les droits sur les données deviennent des droits explicites, approuvés comme les autres. Comportement actuel conservé par défaut tant que D22a n'est pas tranchée | `Member.grant`, `User.can` | S (2 à 3 j) |
| **IAM-4 Portal User** | Audience `portal` ; invitation ou inscription via un fournisseur d'identité externe (pas de mots de passe stockés par Autology, recommandé) ; ABAC sur le sujet : `row_access` avec `$principal` (ex. `Reservation.customer == $principal.id`) ; seules les actions déclarées pour le portail | OIDC, `row_access`, `action_access`, API v1 | L (8 à 12 j) |
| **IAM-5 Public Visitor** | Identité anonyme ; actions et champs déclarés `public` dans l'ontologie (recherche, soumission de demande) ; limitation de débit et quotas ; les demandes publiques deviennent des cas traités par des Internal Users | Ontologie, gouvernance, automatisations | M (5 à 7 j) après GAP-030 |
| **IAM-6 Identités d'agents et de plugins** | Chaque agent et chaque plugin a une identité de service avec ses permissions et ses limites d'autonomie (B6), intersectées avec celles du demandeur ; jamais d'héritage implicite d'un administrateur | `service_identities`, `run_roles`, `kind: service` | M, avec le runtime de plugins (B2) |

**Ordre recommandé :**
1. IAM-1 (tenant) et IAM-3 (séparation administration / données) ;
2. IAM-2 (opérateurs de plateforme) ;
3. GAP-030 (expiration des jetons, limitation de débit) ;
4. IAM-4 (portail) ;
5. IAM-5 (public) ;
6. IAM-6 (avec le runtime de plugins).

Chaque incrément doit garder vertes les matrices d'isolation (`test_iso4_isolation_matrix`,
`test_entry_point_matrix`) et ajouter ses propres tests négatifs, comme ceux de H-1.

## 5. Exemple : application de réservation (cible)

| Acteur | Profil | Ce que la plateforme permettra | Contrôles |
|---|---|---|---|
| Visiteur | Public Visitor | Rechercher des disponibilités, soumettre une demande | Actions `public` uniquement, champs publics, limitation de débit (IAM-5) |
| Client | Portal User | Créer un compte, suivre **ses** réservations | Audience `portal`, ABAC propriétaire (IAM-4) |
| Agent de réservation | Internal User | Traiter les demandes et les opérations | Droits par cas d'usage, revues selon la politique (existant) |
| Responsable | Tenant Admin | Configurer règles, équipes et workflows | Releases à quatre yeux, droits approuvés (existant) ; données selon D22a |
| Exploitant | Platform Admin | Maintenir l'infrastructure | Aucune route de données ; accès exceptionnel audité (IAM-2) |

Tout passe par les API v1 de l'Engine : le Studio, le portail et les pages publiques n'ont aucun accès direct aux
stores.

## 6. Décisions à prendre (propriétaire)

| ID | Question | Recommandation |
|---|---|---|
| **D22a** | Un Tenant Admin voit-il par défaut les données métier de ses cas d'usage ? | **Décidé le 15 nov. : non.** Moindre privilège par défaut, droit explicite, limité et auditable (appliqué par IAM-3) |
| **D22b** | Qui approuve un accès exceptionnel d'un Platform Admin aux données d'un tenant ? | Un Tenant Admin du tenant concerné, pour une durée limitée ; accès d'urgence sans approbation préalable seulement s'il est notifié immédiatement et revu après |
| **D22c** | Comment s'authentifient les Portal Users ? | Fournisseur d'identité externe (OIDC du tenant, ou service d'identité grand public choisi par le tenant), sans mots de passe stockés par Autology |
| **D22d** | Quelles protections pour les actions publiques ? | Limitation de débit et quotas obligatoires (GAP-030) ; protection anti-robot à choisir ; aucune donnée personnelle renvoyée aux visiteurs |
| D22e | Données personnelles des Portal Users et des visiteurs (consentement, conservation) | À voir avec le DPO avant IAM-4 et IAM-5 |
