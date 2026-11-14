# Autology — état d'avancement (synthèse pour la direction)

*14 novembre 2026, commit `dfe8b3f`. Chaque affirmation renvoie à une preuve dans le dépôt.*

## En une phrase

Le socle d'ingénierie (R1) est terminé et vérifié par des tests. Le moteur est sûr pour un pilote supervisé dans le
dépôt, mais pas encore prouvé sur un système réel. Studio, l'architecte IA et l'usine Excel n'ont pas commencé.
Aucun déploiement en production n'a eu lieu.

## Ce qui a été vérifié aujourd'hui

- **Suite de tests :** 559 tests passent. La couverture des lignes est de 95,9 % (seuil CI : 95 %).
- **CI :** chaque commit depuis la réception des instructions a son exécution (runs 18 à 44). Les runs 37 à 39 ont échoué sur le test du conteneur ; c'est corrigé (run 40, vert).
- **Rapport précédent :** ses chiffres sont confirmés en le relançant (472 tests, 37 tests ciblés, couverture 96,8 %), avec une erreur. Le commit `5400ad8` précède la réception des instructions : il y a eu 7 commits après réception, plus le commit de preuve.
- **Écarts documentation / code :** trois documents donnaient des chiffres périmés (README, méthodologie, guide plateforme). Ils sont corrigés.

## Ce que R1 a livré

| Domaine | Résultat | Preuve |
|---|---|---|
| Sûreté des actions externes | 112 combinaisons de pannes : aucun doublon, aucune fausse confirmation, chaque appel retrouvable après un crash | `test_external_effects_matrix.py` |
| Gouvernance | Intersection des droits utilisateur et agent (D4) ; aucun accès non autorisé sur toutes les routes documentées | `test_gov5_*.py`, `test_entry_point_matrix.py` |
| Intégrité du modèle | Schéma strict, enregistrements absents inconnus, sorties typées, un seul écrivain par base | `test_mod1`–`mod4_*.py` |
| Isolation par workspace | REST, MCP, connexion d'entreprise, clés d'audit, identifiants d'intégration, tâches de fond | [matrice d'isolation](AUTOLOGY_SECURITY_AND_TENANCY.md) |
| Indépendance du moteur | Fonctionne sans aucune interface ni Hermes | `test_engine_headless.py` |
| Licence | Licence propriétaire et inventaire des licences tiers, vérifié en CI | `test_leg1_licences.py` |

## Maturité

- **Plateforme :** environ 65/100 en auto-évaluation, avec la méthode de l'audit. Ce chiffre n'est pas vérifié de façon indépendante ; le dernier score vérifié reste 47/100.
- **Cas d'usage :** pas encore mesurable.
- **Ce qui empêche 95/100 :** des preuves externes, qu'aucun travail de code ne peut remplacer :
  - un pilote réel ;
  - deux fournisseurs d'IA testés ;
  - un bac à sable Odoo ;
  - un test d'intrusion externe ;
  - la validation juridique ;
  - une version publiée.

## Blocages et décisions attendues

| Sujet | Ce qu'il faut |
|---|---|
| Licence | Validation par un juriste (entité juridique, composants LGPL/MPL dans l'image) |
| Fournisseurs d'IA (D7, D10) | Clés d'API pour deux fournisseurs ; règle d'envoi des documents d'un workspace vers un fournisseur |
| Odoo (D6) | Accès à un bac à sable Odoo 18. Les écritures en production restent désactivées |
| Studio (D9) | Choix de la technologie (recommandation : application TypeScript séparée) |
| Petits clients (D11) | Qui joue le second approbateur quand un workspace n'a qu'un administrateur |
| Base et chiffrement (D2, D3) | Encore ouverts, non bloquants pour R2 |

Le détail figure dans le [registre des décisions](AUTOLOGY_DECISION_REGISTER.md).

## Prochaine étape

R2, en commençant par :
1. le contrat d'API versionné (OpenAPI) ;
2. le découpage du service, passé de 1 232 à 2 119 lignes ;
3. les contrôles qualité en CI ;
4. les releases avec portes de mise en production côté serveur ;
5. ensuite seulement, l'architecte IA et Studio.

Voir la [feuille de route](AUTOLOGY_RELEASE_ROADMAP.md).
