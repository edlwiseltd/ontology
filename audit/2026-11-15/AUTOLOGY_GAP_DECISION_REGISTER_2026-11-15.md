# Autology — registre des écarts et des décisions (15 novembre 2026)

*Registre actionnable produit par l'audit en lecture seule du HEAD `a143ed378c11e5f9c71671acb360f994d52e2f06`. Il ne
remplace pas `planning/AUTOLOGY_DEFECT_REGISTER.md` ni `planning/AUTOLOGY_DECISION_REGISTER.md` : il les reprend,
signale ce qui y est périmé et ajoute les constats du jour (préfixe **F-**). Les recommandations sont étiquetées
« Recommandation (audit) » ; elles ne sont **pas** des décisions.*

**Catégories :**
- **Bloqueur** : empêche le prochain incrément sûr.
- **Risque critique** : peut invalider la déployabilité, la sûreté ou la confiance.
- **Dette** : à planifier.
- **Opportunité** : intéressante, non engagée.

## 1. Constats nouveaux (aujourd'hui)

| ID | Catégorie | Description | Preuve actuelle | Gravité | Effet métier | Dépendance | Responsable | Recommandation (audit) | Prochaine vérification |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | Risque critique (sécurité) | Ingest HTTP paginé : les en-têtes secrets sont envoyés à l'URL `next` fournie par la source distante, quel que soit l'hôte | `autology/ingest.py:362-384` | Moyenne | Fuite d'identifiants d'intégration ; SSRF vers le réseau interne | — | Ingénierie | Restreindre `next` au même schéma, hôte et port que l'URL configurée (ou à une allow-list explicite) ; sinon refuser | Test : une page `next` vers un autre hôte est refusée et le secret n'y est jamais envoyé |
| F-02 | Risque critique (gouvernance) | `HttpApprover` approuve des revues humaines hors simulation ; le relecteur est désigné par le service distant, sans contrôle d'auto-revue | `adapters.py:232-257`, `server.py:186-191` | Moyenne | Une revue « humaine » peut être levée sans humain identifié | D11 (indirectement) | Ingénierie, puis le propriétaire pour la politique | Le traiter comme un approbateur automatique (`can_approve`) sauf configuration explicite ; exiger un relecteur connu du moteur, appliquer l'anti-auto-revue et l'auditer | Test : refus au démarrage hors simulation ; relecteur = initiateur refusé |
| F-03 | Risque critique (séparation des tâches) | Les changements de stade (draft → simulation → pilot) n'exigent pas une seconde personne | `platform.py:356-361`, `lifecycle.py:261-293` | Moyenne | Un administrateur seul peut mettre un cas en pilote | **D11** | Propriétaire | Approbation à deux personnes pour pilot et au-delà, avec un mécanisme pour l'espace à admin unique (D11) | Test : le demandeur ne peut pas approuver sa propre promotion |
| F-04 | Risque critique (intégrité) | Une décision de revue est liée à `name@version`, pas à l'empreinte du contenu | `server.py:1554`, `ontology.py:615-617` | Moyenne | Une politique modifiée sans changement de version n'invalide pas une revue en attente | REL-1 | Ingénierie | Lier les runs et les décisions à l'empreinte de release (REL-1a) | Test : ontologie modifiée à version égale → revue en attente invalidée |
| F-05 | Dette (sécurité) | Clé API de la Console en clair (fichier 0600) ; SQLite non chiffré | `settings.py:47-57`, `store.py:230-234` | Moyenne | Exigence de sécurité client non satisfaite | **D3, D13** | Propriétaire | Chiffrement de volume documenté (D3) ; magasin de secrets (D13) | Revue de déploiement |
| F-06 | Dette (chaîne d'approvisionnement) | Image de base sans digest ; actions CI sans SHA ; `pip` non épinglé ; contraintes sans hachages ; extras non épinglés | `Dockerfile:6`, `.github/workflows/tests.yml:30-43`, `pyproject.toml:16-18` | Moyenne / faible | Build non reproductible, risque d'approvisionnement | — | Ingénierie | Épingler par digest et SHA ; `--require-hashes` | CI : build reproductible |
| F-07 | Dette (disponibilité) | Pas d'expiration de jeton, pas de rate limiting ni de timeouts serveur, pas de plafond de threads | `server.py:2418`, `platform.py:503` | Faible / moyenne | DoS et jetons durables | — | Ingénierie | R3 : expiration, rotation, limites (GAP-030) | Tests de limite de débit |
| F-08 | Dette (SSRF) | Redirections suivies en conservant les en-têtes ; corps de réponse lus sans taille maximale | `adapters.py:126`, `ingest.py:375` | Faible | SSRF et mémoire | — | Ingénierie | Désactiver les redirections ou les limiter au même hôte ; plafond de taille | Test de redirection |
| F-09 | Dette (OIDC) | `startswith("http://localhost")` sur `redirect_uri` ; émetteur `http://` accepté ; pas de contrôle `azp` | `oidc.py:105,251` | Faible | Durcissement SSO | — | Ingénierie | Comparer l'hôte exactement ; exiger `https` hors localhost | Test unitaire |
| F-10 | Dette | Relais Studio : corps entièrement lu avant la limite ; CSP `'unsafe-inline'` | `studio/web/lib/forward.ts:46-48`, `next.config.ts:8` | Faible | Mémoire, XSS en défense en profondeur | D9 (topologie) | Ingénierie | Lire en flux avec plafond ; CSP à nonce | Test relais |
| F-11 | Dette | Journal d'accès en échec ouvert et non chaîné | `server.py:2207`, `platform.py:457` | Faible | Preuves d'accès incomplètes possibles | — | Ingénierie | Chaîner ou au moins compter les échecs dans la santé | Test d'injection |
| F-12 | Dette (qualité) | 201 erreurs mypy (contre 165 au registre) ; pas de lint, de typage ni de scan en CI | `audit/2026-11-15/evidence/mypy.log` | Moyenne | Régressions non détectées | — | Ingénierie | QA-1 avec un seuil cliquet (pas de nouvelle erreur) | CI échoue sur une nouvelle erreur |
| F-13 | Dette (documentation) | Registres périmés : paragraphe GAP-009/018, GAP-041, GAP-051 (référence à un test supprimé), GAP-056, roadmap R2 « Planned », indépendance du score 47 | `AUTOLOGY_TECHNICAL_AUDIT_2026-11-15.md` §1.2 | Faible | Mauvaise lecture de l'état réel | — | Ingénierie, puis le propriétaire | Mise à jour documentaire (sans changer les décisions) | Relecture |
| F-14 | Opportunité | Pas de compensation inter-systèmes (sagas) | `server.py:728-729` | — (périmètre) | Succès partiels gérés manuellement | D15 | Propriétaire | Spécifier la compensation par action avant tout connecteur ERP | Conception |

## 2. Écarts historiques ouverts ou partiels (extrait priorisé du registre du dépôt)

| ID | Catégorie | Description | Statut au registre → évaluation de l'audit | Gravité | Dépendance | Responsable | Recommandation (audit) |
|---|---|---|---|---|---|---|---|
| GAP-020 | Bloqueur (pour R2 gouvernance) | Runs non liés à l'empreinte ; changements silencieux | Open → **Open** (= F-04) | Haute pour la confiance | REL-1 | Ingénierie | REL-1a |
| GAP-031 | Bloqueur (commercial) | Licence et redistribution | Partly fixed → **Partly fixed** (ingénierie OK) | Haute | **D19** | Propriétaire et avocat | Engager le conseil (L1–L6) |
| GAP-032 | Bloqueur (pilote ERP) | Aucun connecteur ERP | Open → **Open** (Odoo seulement documenté) | Haute pour le marché visé | D6, D13, D15 | Propriétaire puis ingénierie | Sandbox Odoo après REL-1 |
| GAP-052 | Bloqueur (affirmations IA) | Jamais exécuté avec un vrai modèle | Open (externe) → **Open** | Haute | **D7, D10** | Propriétaire | Choisir 2 fournisseurs et la politique de données |
| GAP-053 | Bloqueur (pilote) | Aucun processus réel de bout en bout | Open (externe) → **Open** | Haute | **D16** | Propriétaire | Identifier un pilote non-production |
| GAP-054 | Risque critique | Pas de revue de sécurité humaine indépendante | Open (externe) → **Open** | Moyenne | Budget | Propriétaire | Mandater une revue et un test d'intrusion avant le pilote |
| GAP-051 | Bloqueur (ADM-1) | Pas d'administration (membres, accords) | Partly fixed → **Partly fixed** (référence de test périmée) | Moyenne | **D11** | Ingénierie | ADM-1 après REL-1a |
| GAP-041 | Dette | Migrations | Open → **Partiellement corrigé** (transaction unique : `store.py:243-262`) | Faible | — | Ingénierie | Mettre à jour le registre ; étapes numérotées |
| GAP-056 | Dette | Pas d'éditeur pour métiers | Open → **Partiellement corrigé** (entités et relations) | Moyenne | REL-1 | Ingénierie | Mettre à jour le registre |
| GAP-025 | Dette | Pas de lint, typage ni scan | Open → **Open, aggravé** (201 erreurs) | Moyenne | — | Ingénierie | QA-1 (= F-12) |
| GAP-026 | Dette | Objet-dieu `AutologyService` | Open → **Open** (`server.py` 2 451 lignes) | Moyenne | — | Ingénierie | ARC-0 avant de nouveaux services |
| GAP-033 | Risque critique (exploitation) | Restauration jamais exercée | Open → **Open** | Moyenne | — | Ingénierie | Exercice de restauration en CI |
| GAP-030 | Dette | Jetons, limites | Open → **Open** (= F-07) | Moyenne | — | Ingénierie | R3 |
| GAP-040 | Dette | Épinglage | Partly fixed → **Partly fixed** (= F-06) | Moyenne | — | Ingénierie | H-1 |
| GAP-045 | Risque critique (IA) | Injection de prompt via les données | Open → **Open** | Moyenne | AI-1 | Ingénierie | SEC-A avec AI-1 |
| GAP-055 | Dette | SQLite mono-nœud | Open (décision) → **Open** | — | **D2** | Propriétaire | SQLite pour pilotes isolés |
| GAP-057 | Dette | Automatisations synchrones | Open → **Open** | Moyenne | — | Ingénierie | R3 |
| GAP-009 | — | Write-back atomique | Fixed → **Fixed (local)** ; pas de compensation externe | — | — | — | Corriger le paragraphe contradictoire |
| GAP-018 | — | Cohérence | Fixed → **Fixed** (détection, pas prévention) | — | — | — | Vérification indépendante |

## 3. Décisions ouvertes

| ID | Question exacte | Options | Preuves actuelles | Impact | Recommandation (audit) | Approbation du propriétaire obligatoire ? |
|---|---|---|---|---|---|---|
| **D2** | Store opérationnel : SQLite ou PostgreSQL ? | SQLite par pilote isolé ; PostgreSQL partagé ou HA | SQLite seul implémenté (`store.py`) ; PostgreSQL seulement pour le reporting | HA, multi-locataire mutualisé | SQLite pour les pilotes isolés ; PostgreSQL si mutualisation ou HA | Oui |
| **D3** | Chiffrement au repos ? | Volume chiffré par déploiement ; chiffrement applicatif ; SQLCipher | Aucun chiffrement applicatif | Revues de sécurité client | Volume chiffré documenté comme exigence de déploiement | Oui |
| **D7** | Indépendance des fournisseurs : quels 2 adaptateurs valider ? | Fournisseurs commerciaux ou modèle auto-hébergé | 1 adaptateur, testé uniquement avec de faux clients | Bloque AI-1 et GAP-052 | Choisir deux fournisseurs, et fournir les clés pour une suite d'évaluation sur données synthétiques | Oui (fournisseur et coût) |
| **D10** | Quelles données peuvent être envoyées aux fournisseurs (résidence) ? | Aucune ; synthétiques seulement ; briefs sans documents ; tout | Les champs confidentiels sont déjà retenus (`server.py:302-307`) | Bloque ARC-1 | Par espace de travail, désactivé par défaut pour les documents | **Oui (juridique et données)** |
| **D11** | Second approbateur quand l'espace n'a qu'un administrateur | Approbateur externe nommé ; administrateur plateforme ; délai de carence plus journal ; interdiction de promouvoir | Aucune approbation indépendante n'existe (F-03) | Bloque ADM-1, REL-2 et la promotion en pilote à quatre yeux | Rôle d'approbateur externe nommé, distinct du demandeur, audité ; pas d'auto-approbation de la production | **Oui** |
| **D13** | Magasin de secrets des intégrations | Variables d'environnement (aujourd'hui) ; Vault ; KMS cloud | Préfixe par espace (D12) | Bloque l'auto-service des intégrations | Choisir avant la configuration des connecteurs par les clients | Oui |
| **D15** | Écritures ERP en production | Interdites (aujourd'hui) ; au cas par cas après sandbox | Aucun stade n'atteint la production | Valeur client finale | Garder interdites ; décider par client et par système après preuves sandbox | **Oui** |
| **D16** | Pilote client réel et données | Système de test ou de préproduction ; données synthétiques uniquement | Aucun | Gates 90.4 et 95.5 impossibles | Un processus, en environnement de test | **Oui** |
| **D17** | Systèmes atteignables par stade | Défaut appliqué : simulation → simulated ; pilot → sandbox ; production → aucun | `lifecycle.py:58-77`, tests | Portée du pilote | Confirmer le défaut | Oui (confirmation) |
| **D18** | Ingestion de données réelles en draft et simulation | Défaut appliqué : oui, lecture seule | Ingest sans effet sortant | Données personnelles | Confirmer, avec une limite pour les données personnelles en attendant D10/D16 | Oui (confirmation) |
| **D19** | Licences L1–L6 | Voir le dossier GAP-031 | Ingénierie prête ; image sans LGPL construite en CI | Aucune distribution possible | Engager un avocat | **Oui (juridique)** |
| D20 | Retrait des chemins API legacy | Défaut appliqué : dépréciés, aucun retrait sans préavis | `docs/api-versioning.md` | Clients non migrés | Confirmer | Oui (confirmation) |
| D8, D12, D14 | Défauts appliqués (non-idempotence par défaut, préfixe de secrets, pas de partage entre cas d'usage) | — | Implémentés | — | Confirmer | Oui (confirmation) |

## 4. Bloqueurs externes (séparés)

| Bloqueur | État | Débloqué par |
|---|---|---|
| Client pilote et données utilisables | Aucun | D16 |
| Licence, entité légale, signature | En attente | D19, avocat |
| Licences tierces (LGPL psycopg, Debian, CC-BY-4.0, `sharp`/libvips) | Inventoriées | D19 (L3–L6) |
| Revue de sécurité et test d'intrusion indépendants | Aucun | Mandat du propriétaire |
| Fournisseurs LLM et résidence des données | En attente | D7, D10 |
| Autorité d'écriture ERP en production | Non accordée | D15 |
| Preuves d'hébergement de production | Aucune (PROD) | Décision de déploiement |
