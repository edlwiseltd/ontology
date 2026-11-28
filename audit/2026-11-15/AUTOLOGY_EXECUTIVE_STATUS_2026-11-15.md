# Autology — point de situation pour la direction (15 novembre 2026)

**Base auditée :** branche `claude/autology-ontology-agent-4ajjer`, commit `a143ed3` (15/11, 06:24 UTC). Intégration
continue verte (runs 64 et 65). Audit en lecture seule : aucun code n'a été modifié.

**Avertissement :** cet audit a été réalisé par l'agent IA qui a écrit l'essentiel du code. Il **n'est pas
indépendant**. Le score de 47/100 du 13 novembre a lui aussi été établi par des agents IA ; aucun score n'est donc
« indépendant » au sens d'une revue humaine. L'audit ne donne pas de nouveau score.

## 1. Où en est-on ?

Autology est un **moteur fonctionnel et bien testé** qui transforme une décision métier en action gouvernée et
auditable, **sur des données synthétiques et des systèmes simulés ou sandbox**. Il n'est **ni en production, ni prêt
pour un pilote client, ni distribuable commercialement**.

- **Code :** environ 16 900 lignes de moteur Python, une application Studio séparée (Next.js).
- **Tests :** 661 tests automatisés, tous réussis aujourd'hui ; couverture de 96 %.
- **Studio :** 25 vérifications dans un vrai navigateur, toutes réussies.

## 2. Travail le plus récent (14–15 novembre)

- **API v1** (dernier lot, `f059f2e`) : chemins versionnés `/api/v1` et `/platform/v1`, une seule forme d'erreur,
  pagination, contrats OpenAPI publiés. Le Studio utilise des types générés automatiquement à partir de ces contrats.
  Fonctionne et est vérifié.
- **Avant cela :**
  - barrières d'exécution par stade (rien ne part en Draft ; la Simulation n'atteint que des systèmes simulés ; le
    Pilot n'atteint que la sandbox ; la Production est toujours refusée) ;
  - écriture de retour atomique (GAP-009) ;
  - cohérence des enregistrements et accès concurrents (GAP-018) ;
  - préparation technique des licences (GAP-031) ;
  - Studio : consultation du modèle, édition visuelle des entités et relations, validation par le moteur.
- **Directive en cours :** sur ses 6 incréments, seul le premier (l'API v1) est réalisé.

## 3. Ce qui fonctionne réellement (vérifié aujourd'hui)

1. **Gouvernance à chaque étape.** Une IA propose, mais ne peut ni contourner une règle ni exécuter seule.
   L'intervention humaine n'est requise que lorsque la politique l'exige.
2. **Isolation entre clients (espaces de travail).** Une réponse identique est renvoyée que l'espace soit étranger,
   inexistant ou non accordé.
3. **Actions externes sûres.** Un paiement n'est jamais fait deux fois, même après un crash, et un résultat incertain
   est confié à un humain.
4. **Audit infalsifiable.** Chaînes signées, enregistrements scellés, une clé par espace de travail.
5. **Cycle de vie Draft → Simulation → Pilot** avec contrôles côté serveur.
6. **Studio séparé** qui ne peut rien contourner : les appels directs sont refusés par la plateforme.
7. **API v1 versionnée** avec tests de contrat.

## 4. Ce qui ne fonctionne pas encore

- **Releases immuables, rollback et approbation par une deuxième personne : absents.** Conséquence : une revue
  approuvée reste valable même si la politique change sans changement de numéro de version.
- **Administration des membres et des droits : absente** (fichier de configuration et redémarrage).
- **Score de readiness par cas d'usage (6 dimensions) : documenté seulement.**
- **Architecte IA : prototype par modèles prédéfinis, sans IA.** Le moteur n'a jamais été exécuté avec un vrai
  modèle d'IA.
- **Absents :**
  - import Excel, PDF et Word ; Agent Factory ;
  - RAG et normes sectorielles ;
  - connecteur Odoo ou ERP ;
  - interface opérationnelle complète pour les utilisateurs finaux.
- **Exploitation :** pas d'exercice de restauration, pas d'alertes, pas de haute disponibilité, pas de chiffrement au
  repos, jetons sans expiration.

## 5. Cinq risques et bloqueurs principaux

| # | Risque / bloqueur | Gravité | Impact |
|---|---|---|---|
| 1 | Licences et cadre juridique non signés (D19) | Haute | **Aucune distribution à un client possible** |
| 2 | Pas de releases liées au contenu exact ni d'approbation à quatre yeux (GAP-020, D11) | Haute pour la confiance | La promesse « décision vérifiable » n'est pas complète |
| 3 | Deux failles moyennes trouvées aujourd'hui : (a) l'import de données peut renvoyer un secret vers un serveur désigné par la source ; (b) un service d'approbation externe peut lever une revue « humaine » sans humain identifié | Moyenne | Fuite d'identifiants ; contournement d'une revue |
| 4 | Aucun pilote client, aucun vrai modèle d'IA, aucun connecteur ERP (D16, D7/D10, D15) | Haute | Impossible de prouver la valeur sur un cas réel |
| 5 | Pas de revue de sécurité humaine indépendante ni de test d'intrusion (GAP-054) | Moyenne | Exigence probable de tout client industriel |

## 6. Décisions à prendre par le propriétaire

- **Maintenant :**
  - **D11** : qui approuve quand un espace n'a qu'un administrateur ;
  - **D19** : avocat, licences L1–L6 ;
  - **D7/D10** : deux fournisseurs d'IA et les données autorisées.
- **Ensuite :** D16 (pilote), D3 (chiffrement), D13 (secrets), D2 (base de données), D15 (écritures ERP en
  production, à garder interdites).
- **Confirmations de défauts appliqués :** D17, D18, D20, D8, D12, D14.

## 7. Recommandation

**Prochain incrément recommandé : releases immuables liées à l'empreinte du contenu, avec rollback (REL-1a).** C'est
ce qui manque pour que chaque décision approuvée soit liée à la règle exacte en vigueur. C'est aussi le prérequis de
l'activation des modèles conçus dans le Studio, du rollback, du score de readiness et de l'administration.

**Alternative rapide, d'environ deux jours (H-1) :** corriger les deux failles du jour et figer la chaîne
d'approvisionnement.

**Rien ne sera développé sans votre autorisation explicite.**

*Détails : `audit/2026-11-15/AUTOLOGY_TECHNICAL_AUDIT_2026-11-15.md`, `…_GAP_DECISION_REGISTER_…`,
`…_NEXT_INCREMENTS_…`, `…_AUDIT_MACHINE_SUMMARY_….json`.*
