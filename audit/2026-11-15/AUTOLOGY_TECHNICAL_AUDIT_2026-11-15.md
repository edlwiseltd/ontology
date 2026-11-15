# Autology — audit technique complet (15 novembre 2026)

*Audit en lecture seule. Aucun code applicatif, aucune configuration, aucune migration, aucun déploiement, aucun commit
ni push n'ont été effectués. Seuls les fichiers de `audit/2026-11-15/` ont été créés (rapports et journaux de preuve).*

**Indicateurs de confiance :** **VÉRIFIÉ** (lu dans le code et/ou observé à l'exécution aujourd'hui) ·
**INFÉRÉ** (déduit raisonnablement du code, non exécuté) · **NON VÉRIFIÉ** (affirmé ailleurs, non reproductible ici).

**Auteur et indépendance.** Cet audit est réalisé par le même agent IA (Claude Code) qui a écrit l'essentiel du code
audité. Il n'est donc **pas indépendant** au sens d'une revue humaine ou d'un tiers. Trois sous-agents en lecture
seule ont été utilisés pour des balayages (capacités 12–17, sécurité statique, trace bout en bout) ; leurs conclusions
les plus importantes ont été revérifiées dans le code (indiqué « revérifié »).

---

## 1. Base de référence reproductible

| Élément | Valeur | Confiance |
|---|---|---|
| Horodatage de l'audit | 2026-11-15T06:46:30Z (début) | VÉRIFIÉ |
| Répertoire | `/home/user/ontology` (conteneur cloud éphémère) | VÉRIFIÉ |
| Dépôt | `https://github.com/edlwiseltd/ontology` (un seul dépôt, pas de sous-module) | VÉRIFIÉ |
| Branche | `claude/autology-ontology-agent-4ajjer` | VÉRIFIÉ |
| HEAD | `a143ed378c11e5f9c71671acb360f994d52e2f06` (2026-11-15T06:24:51Z, « Record CI run 64 for API v1 ») | VÉRIFIÉ |
| État Git | propre avant l'audit ; clone complet (non superficiel), 102 commits, premier commit 2026-09-27 | VÉRIFIÉ |
| Tags | aucun | VÉRIFIÉ |
| CI du HEAD | run 65 (`43685325889`) **succès** ; run 64 (`43684759108`, `f059f2e`) **succès sur les 4 jobs** (test 3.10, test 3.13 avec PostgreSQL, package, studio) | VÉRIFIÉ (API GitHub Actions) |
| Branche par défaut / PR | non inspectées ; aucune PR créée | — |

### 1.1 Sources faisant autorité (par ordre de fiabilité)

1. **Code** (`autology/`, `studio/web/`) et **tests** (`tests/`, `studio/web/tests/`, `studio/web/e2e/`).
2. **CI** (`.github/workflows/tests.yml`, résultats GitHub Actions).
3. **Contrats** : `autology/openapi.py`, `studio/web/api/*.openapi.json`, `docs/ontology.schema.json`.
4. **Documentation utilisateur** : `README.md`, `docs/*.md` (dont `docs/api-versioning.md`).
5. **Planification** : `planning/AUTOLOGY_PRD.md`, `…_RELEASE_ROADMAP.md`, `…_DEFECT_REGISTER.md`,
   `…_DECISION_REGISTER.md`, `…_REQUIREMENTS_TRACEABILITY.md`, `…_IMPLEMENTATION_LOG.md`, rapports d'incrément.
6. **Audit antérieur** : `audit/01…06` (13 nov., révision `fdfaf01`).

### 1.2 Contradictions relevées (documentation vs code)

| # | Contradiction | Source la plus fiable | Statut |
|---|---|---|---|
| C1 | `planning/AUTOLOGY_DEFECT_REGISTER.md` (paragraphe sous le tableau de synthèse) dit que GAP-009 et GAP-018 sont « partly fixed » ; leurs lignes disent **Fixed** | Lignes + tests (`tests/test_gap009_atomic_write_back.py`, `tests/test_gap018_*.py`, exécutés aujourd'hui : OK) | Paragraphe périmé |
| C2 | GAP-041 « Open » (migrations hors transaction) | Code : `autology/store.py:243-262` — toutes les étapes et le changement de version dans **une** transaction `BEGIN IMMEDIATE` ; test `tests/test_gap018_directive02.py::MigrationRestartTests` | **Partiellement corrigé** en réalité (pas de migrations numérotées ordonnées) |
| C3 | GAP-056 « Open » (aucun éditeur d'ontologie) | `studio/web/components/DesignView.tsx` + `tests/test_studio2_modeling.py` + e2e | **Partiellement corrigé** (entités/relations ; pas de règles/actions visuelles ; pas d'activation) |
| C4 | GAP-051, R2 slice report, traçabilité, journal citent `tests/test_studio_shell.py` | Le fichier n'existe plus (remplacé par `tests/test_studio_separation.py`) | Références périmées |
| C5 | GAP-025 : « 165 erreurs mypy » | mypy 2.4.1 aujourd'hui : **201 erreurs** (`audit/2026-11-15/evidence/mypy.log`) | Dette en hausse |
| C6 | Roadmap §1 : R2 « Planned » | R2 en cours (API-2 fait, STU-1 fait, plusieurs stories partielles) | Tableau périmé |
| C7 | « Score indépendant 47/100 » (`planning/AUTOLOGY_MATURITY_SCORECARD.md:8`) | `audit/README.md` : l'audit du 13 nov. « was performed by AI agents (one of which wrote the code) » | Non indépendant au sens humain |
| C8 | `planning/AUTOLOGY_STUDIO_UI_UX_SPEC.md:46` : incrément 1 « CI pending at writing » | CI runs 58 puis 62/64 verts | Mention périmée |

Aucune contradiction n'affecte une affirmation de sécurité : les documents ont tendance à **sous-déclarer** l'état réel
(C2, C3), sauf C7 qui sur-qualifie l'indépendance d'un score.

### 1.3 Carte du dépôt (tel que construit)

| Répertoire / module | Technologie | Responsabilité | Taille |
|---|---|---|---|
| `autology/` | Python 3.10+ **sans dépendance d'exécution** (`pyproject.toml:15`, extras `llm`, `yaml`, `postgres`) | Moteur : ontologie, gouvernance, agents, store, API REST, routeur plateforme, MCP, ingest, ordonnancement | 42 modules, 16 895 lignes |
| `autology/server.py` | `http.server.ThreadingHTTPServer` | `AutologyService` (service unique) + `ApiExchange` (dispatcher REST) + inbox optionnelle | 2 451 lignes |
| `autology/platform.py` | idem | Routeur multi-espaces `/w/<ws>/u/<uc>/api/...`, `/platform/...`, isolation, cycle de vie | 534 lignes |
| `autology/store.py` | SQLite (stdlib), WAL | Store opérationnel : graphe, runs, audit append-only, journal d'effets, révisions/sceaux, brouillons | 1 243 lignes, schéma 15 |
| `autology/warehouse.py`, `reporting.py` | SQLite ou PostgreSQL (psycopg) | Base de reporting BI (lecture), métriques Prometheus | — |
| `autology/static/` | HTML/JS sans framework | Inbox web (revues, runs, objets, activité, assistant) — optionnelle | — |
| `autology/console.py`, `console_static/` | Python + JS | Console conversationnelle séparée (proxy vers le moteur) | — |
| `studio/web/` | Next.js 16.4.6, React 19.3.1, TypeScript 5.9.3, @xyflow/react 12.12.1 | **Studio** (application séparée) ; relais `lib/forward.ts` ; types générés (`openapi-typescript` 7.13.0) | ~1 510 lignes hors générés |
| `tests/` | `unittest` | 78 fichiers, 661 tests exécutés | — |
| `deploy/`, `Dockerfile` | Docker, compose, Prometheus | Image, contraintes figées, inventaire de licences, smoke test | — |
| `examples/` | JSON | 8 exemples synthétiques (assurance auto, onboarding client, commandes, maintenance, eau…) | — |
| `docs/`, `planning/`, `audit/` | Markdown | Documentation, planification, audits | — |

**Hors dépôt / non inspectable :** aucun service externe réel (ERP, IdP, fournisseur LLM, hébergement). Aucun
environnement de production n'existe (décision PROD).

---

## 2. Ce qui vient d'être réalisé (dernière session de travail)

**Demande la plus récente** : « MASTER DEVELOPMENT DIRECTIVE — R2 Completion, Enterprise Governance and AI-First
Studio » (6 incréments). **Seul l'incrément 1 (API v1) a été réalisé** ; les incréments 2 à 6 n'ont pas été commencés.
Aucun travail non commité avant l'audit.

### 2.1 Journal des changements par lot de travail (14–15 nov.)

| Lot | Commits (SHA complet, date) | Fichiers principaux | Preuve de vérification | État | Suite |
|---|---|---|---|---|---|
| R1 closure note | `6df09114fd1c9206cf8f8724a67bd0df8ff60c1e` (14/11 16:30) | `planning/AUTOLOGY_R1_CLOSURE_NOTE.md` | Document | Fait | — |
| R2 slice : cycle de vie Draft/Simulation/Pilot, cas d'usage depuis modèles | `77b9a59e6c0c655bd0ee819f0ad15ff32a63aee2` | `autology/lifecycle.py`, `platform.py` | `tests/test_r2_use_case_lifecycle.py` (23) — OK aujourd'hui | VÉRIFIÉ | Releases immuables (REL-1) |
| Barrières d'exécution par stade | `40f778093acc7663a44b846ee6c5b15fbeed4114`, `22211ccb41720b476b4046da3e1bc075cb2b19c6` | `server.py` (`_tool_refused`, `_environment_refused`, `_require_runs`), `tools.py` | `tests/test_r2_execution_gates.py` (13) — OK | VÉRIFIÉ | — |
| GAP-009 write-back atomique | `ceb9c24219caf6e02e0088cb219ef208388003f8` | `store.py` (`commit_write_set`), `graph.py` (`plan_write_back`) | `tests/test_gap009_atomic_write_back.py` (10) — OK | VÉRIFIÉ (local) | Pas de compensation externe |
| GAP-018 cohérence des enregistrements | `118f8bc6e1f1733a135f8489765d691a6551f074`, `5a90fa85a57f5c7a10944fa53e6e56c32050e07c` | `store.py` (révisions, sceaux, schéma 14), `mcp.py`, `scenarios.py` | `tests/test_gap018_record_consistency.py` (15), `test_gap018_directive02.py` (7) — OK | VÉRIFIÉ | Détection, pas prévention, des écritures directes en base |
| GAP-031 ingénierie licences | `2939b00612680ecadd221e468e232b47759a8327`, `4f8de468d440135398a04ed46ec2d440aee7f060` | `deploy/image-constraints.txt`, `deploy/image_licences.py`, `Dockerfile` | CI job `package` vert (run 64) | VÉRIFIÉ (ingénierie) ; **juridique ouvert** (D19) | Avocat |
| API-1 contrat OpenAPI | `8bfec1cc91197c9ce824c45ba85de7bd0e513cd5` | `autology/openapi.py` | `tests/test_api_contract.py` (5) — OK | VÉRIFIÉ | — |
| Studio Next.js (incrément 1) | `ddc8095f09a936f2a367a6e12a87b70ad572c839` | `studio/web/**` | Vitest + e2e — OK | VÉRIFIÉ | — |
| Studio incrément 2 (modélisation) | `f8db2eefa9b2baf105a8aa2f5a6c5f1810298c97` | `autology/modeling.py`, `blueprints/water_treatment.json`, `DesignView.tsx` | `tests/test_studio2_modeling.py` (7), e2e — OK | VÉRIFIÉ ; générateur **non IA** | Activation (releases) ; IA bloquée D7/D10 |
| **API v1 (dernier lot)** | `f059f2e95227212c91ae47a5081fe1d3d2812e5e` (15/11 06:17) | `server.py` (`ApiExchange.run`), `platform.py` (`handle`), `openapi.py` (`versioned_response`, `page_window`, `SCHEMAS`, `platform_spec`), `__main__.py` (`openapi`), `docs/api-versioning.md`, `studio/web/lib/{api,types}.ts`, `lib/generated/*.ts`, `api/*.openapi.json`, `tests/test_api_v1.py`, `tests/schema_check.py` | `tests/test_api_v1.py` (10 méthodes ; 11 avec sous-tests) — OK aujourd'hui ; CI run 64 vert | VÉRIFIÉ | Console, relais MCP et SDK restent sur les chemins legacy |
| Enregistrements CI | `ba774ef5…`, `1f3ce3a6…`, `4f8223d2…`, `1f5bf8a8…`, `d43837b2…`, `a143ed37…` | `planning/AUTOLOGY_IMPLEMENTATION_LOG.md` | — | Documentaire | — |

**Résultats affirmés par la session et reproduits aujourd'hui :** 661 tests Python OK (2 ignorés : PostgreSQL),
96,32 % de couverture, Studio 17 tests Vitest et 25/25 vérifications navigateur. **Reproduits à l'identique**
(§9). Les runs CI 50–62 sont cités dans le journal avec URL ; seuls 63, 64 et 65 ont été revérifiés aujourd'hui.

**Défauts trouvés pendant le dernier lot et corrigés avant commit** (journal, §15 nov.) : objets libres générés
comme `Record<string, never>` ; import local qui masquait `json` et cassait `autology export`/`plan` (attrapé par la
suite complète) ; lien `successor-version` non joignable derrière le routeur.

---

## 3. Inventaire des capacités (une par une)

Statuts : **WORKING & VERIFIED / IMPLEMENTED BUT UNVERIFIED / PARTIAL / MOCK OR PROTOTYPE / DOCUMENTED ONLY / ABSENT /
BLOCKED / UNKNOWN**.

| # | Capacité | Statut | Implémentation (chemin + symbole) | Comportement observé / tests | Manques et risques | Décisions / dépendances |
|---|---|---|---|---|---|---|
| 1 | Moteur : objets, propriétés, relations, contraintes, états, événements, décisions, actions, exécution | **WORKING & VERIFIED** | `ontology.py` (`Ontology`, `SCHEMA_KEYS:89-100`, schéma strict `docs/ontology.schema.json`), `graph.py:46` `KnowledgeGraph`, `planner.py:99`, `agent.py` `WorkAgent`, `automation.py` (événements de données, échéances, planifications), `expressions.py` | `test_core`, `test_engineering`, `test_mod1_strict_schema`, `test_auto_insurance`, `test_automation` — OK | Pas de modèle de processus (BPMN) ; ontologie immuable mais référencée `name@version` (`ontology.py:615`) | — |
| 2 | Espaces de travail, isolation, identité, rôles, permissions, délégation, administration | **PARTIAL** | `platform.py` (routeur, `member_for:250`, `NOT_FOUND` identiques `:330-349,446`), `governance.py` (accès lignes/champs), `agent.py:692-703` (intersection demandeur ∩ agent), délégués | `test_workspaces`, `test_iso1…iso4`, `test_gov3`, `test_gov5` — OK | **Administration absente** : membres/accords seulement par fichier de config + redémarrage (GAP-051, ADM-1/2) ; un seul admin peut tout faire (stades) | D11, D14 |
| 3 | Authentification, comptes de service, secrets, chiffrement, journal d'audit, preuves | **PARTIAL** | Jetons SHA-256 + `hmac.compare_digest` (`server.py:107-113,350-363`) ; OIDC (`oidc.py:173-214`) ; `service_identities` (`server.py:233-261`) ; secrets par préfixe d'environnement (`platform.py:93,108-131`) ; audit HMAC chaîné (`audit.py`) | `test_oidc`, `test_audit_integrity`, `test_iso2`, `test_gov4`, `test_settings` — OK | Jetons sans expiration ni rotation, pas de limitation de débit (GAP-030) ; clé API Console en clair (0600) (`settings.py:47-57`) ; **pas de chiffrement au repos** (SQLite) ; pas de rotation de clé d'audit ; journal d'accès non chaîné | D3, D13 |
| 4 | Évaluation de politique, risque/criticité, intervention humaine configurable | **WORKING & VERIFIED** (règles) ; criticité comme notion de premier rang **ABSENT** | `governance.py:229` `evaluate` (ALLOW/REVIEW/DENY, intégrité d'abord `:99`), règles `human_review` avec seuils `when`, faits inconnus → règle restrictive | `test_core.GovernanceTests`, `test_review_integrity.UnknownFactTests`, `test_auto_insurance` (CL-1 payé sans humain, CL-2 deux revues) — OK | Pas de classification de criticité/risque déclarative distincte des règles | — |
| 5 | Actions autonomes, approbations, simulation, garde-fous, idempotence, exécution durable | **WORKING & VERIFIED** | `agent.py:376` `_execute` (journal d'intention avant appel `:433`, clé d'idempotence `effects.py:44`, classification des résultats `:442-480`), `DeferredApprover`, reprise (`agent.py:535`), récupération (`server.py:1615`) | `test_external_effects` (17), `test_external_effects_matrix`, `test_tool_failures`, `test_one_run_per_record` — OK | **`HttpApprover` approuve des revues humaines hors simulation** (voir §8, F-02) ; journal d'audit d'un segment en mémoire jusqu'à `save_run` | D8 |
| 6 | Actions inter-systèmes : write-back fiable, reprises, échecs partiels, réconciliation, compensation, rollback | **PARTIAL** | Write-back local atomique (`store.py:916` `commit_write_set`) ; réconciliation humaine (`server.py:1707`) | `test_gap009_atomic_write_back`, `test_external_effects.RecoveryTests` — OK | **Aucune compensation ni saga** vers les systèmes externes ; succès partiel → escalade humaine ; l'atomicité ne dépasse pas SQLite (documenté `server.py:728-729`) | D15 |
| 7 | Cycle de vie : draft, simulation, pilot, production ; snapshots immuables, releases, approbation indépendante, rollback | **PARTIAL** | `lifecycle.py` (stades, `policy_for:81`, contrôles `:113-151`, historique HMAC `:246-258`) ; production **toujours refusée** (`:59`) | `test_r2_use_case_lifecycle` (23) — OK | **Pas de releases immuables, pas de rollback, pas d'approbation indépendante** (REL-1/2) ; décision de revue liée à `name@version`, pas à l'empreinte (GAP-020, revérifié `server.py:1554`) | D11, PROD |
| 8 | API v1, OpenAPI, clients/SDK, versionnement, erreurs, pagination, compatibilité, tests de contrat | **WORKING & VERIFIED** | `server.py` `ApiExchange.run`, `platform.py` `handle`, `openapi.py` (`spec`, `platform_spec`, `versioned_response`, `page_window`), `sdk.py` (SDK Python/TS générés depuis l'ontologie) | `test_api_v1`, `test_api_contract`, `test_entry_point_matrix`, `test_sdk` — OK ; dérive contrat/types vérifiée en CI | Schémas typés seulement pour les routes cœur et Studio ; seules `objects` et `runs` paginées ; Console/MCP/SDK sur chemins legacy (dépréciés) | D20 |
| 9 | Studio : écrans, éditeur d'entités, graphes, inspecteur, validation, historique, UX responsive | **WORKING & VERIFIED** (périmètre actuel) / **PARTIAL** (vs spécification) | `studio/web/components/{Workbench,StageOverview,OntologyView,DesignView}.tsx`, `lib/model.ts`, relais `lib/forward.ts` | Vitest 17, e2e 25/25 (390 px mobile, contraste, refus directs 403/404) — OK aujourd'hui | Pas d'écran releases/approbations/readiness/membres ; historique des brouillons exposé par l'API mais pas d'écran dédié ; CSP avec `'unsafe-inline'` | D9 (fait), D11 |
| 10 | AI Solution Architect (vrais appels LLM vs modèles) | **MOCK OR PROTOTYPE** (générateur par blueprint, `ai: false`) ; IA réelle **BLOCKED** | `modeling.py:120` `propose` (blueprint `water_treatment.json`), questions règles `modeling.py` ; adaptateurs LLM existants `reasoners.py:322` `ClaudeReasoner`, `chat.py` (assistant) | `test_studio2_modeling` (ProposalTests, QuestionTests) — OK ; adaptateurs LLM testés **uniquement avec des faux clients** | **Jamais exécuté contre un vrai modèle** (GAP-052) ; un seul adaptateur fournisseur (GAP-029) ; pas de tests d'injection de prompt (GAP-045) | **D7, D10** |
| 11 | Score de readiness par cas d'usage (6 dimensions) | **DOCUMENTED ONLY** | Définition : `planning/AUTOLOGY_MATURITY_SCORECARD.md:84-90` (6 dimensions, 20/15/15/20/15/15) ; existant : `scoring.py` (score de **déploiement**, 3 piliers) et contrôles de stade `lifecycle.py:113-151` | `test_scoring`, `test_readiness`, `test_honest_scores` (score de déploiement) — OK | Aucune implémentation par cas d'usage, aucun historique, aucune distinction consultatif/obligatoire (REL-3) | Validation des poids par le propriétaire |
| 12 | Concepteurs processus, organisation, agents, données, décisions, actions | Entités/relations **WORKING & VERIFIED** ; actions/règles **PARTIAL** (API seulement, via document complet) ; processus/organisation/agents/décisions **ABSENT** | `DesignView.tsx:186-284`, `server.py:2267-2276` (`model/draft`, `model/validate`) | e2e conception — OK | Pas d'activation d'un brouillon (« needs releases ») | REL-1 |
| 13 | Excel Template Factory, import de documents, traçabilité de source, erreurs de ré-import | Ingest CSV/JSON/JSONL/SQL/HTTP/push **WORKING & VERIFIED** ; Excel/PDF/Word/upload **ABSENT** | `ingest.py:47` `SOURCE_TYPES`, quarantaine `Rejected:175`, lignée `server.py:2318` | `test_ingest` (24) — OK | `openpyxl` approuvé (XL) mais non utilisé ; **faille : en-têtes secrets réutilisés vers l'URL `next` fournie par la source** (F-01) | XL, D18 |
| 14 | Agent Factory : cycle de vie, outils, skills, exécution gouvernée | Agents par config + suspension/réintégration **WORKING & VERIFIED** ; outils gouvernés **WORKING & VERIFIED** ; usine/versionnement d'agents, skills **ABSENT** | `adapters.py:185` `load_tools`, `tools.py:105` `ToolRegistry`, `governance.py:105-120` (suspension), `server.py:1971` (réintégration motivée) | `test_suspension`, `test_agnostic`, `test_r2_execution_gates` — OK | Pas d'API de création/version d'agent | R4 |
| 15 | Connaissance : RAG, recherche, graphe, validation sémantique, normes | Graphe + requêtes + export RDF/JSON-LD **WORKING & VERIFIED** ; RAG/embeddings/recherche, SHACL, packs de normes **ABSENT** | `graph.py:123-161`, `export.py:26,90,124` | `test_engineering`, `test_scheduling` — OK | Export JSON-LD lossy (GAP-027) | — |
| 16 | Intégrations : Odoo sandbox, API externes, connecteurs, files, webhooks, ERP/MES/SCADA | Outils HTTP, webhooks, MCP, barrières d'environnement **WORKING & VERIFIED** ; Odoo **DOCUMENTED ONLY** ; ERP/MES/SCADA, files de messages **ABSENT** | `adapters.py:135` `http_tool`, `server.py:988-1009` (webhooks), `mcp.py`, `lifecycle.py:58-77` | `test_mcp`, `test_automation.test_webhooks`, `test_r2_execution_gates` — OK | Aucun connecteur ERP (GAP-032) ; pas d'allow-list sortante ni de blocage d'adresses privées | D6, D13, D15 |
| 17 | Workspace UI utilisateur final : tâches, approbations, supervision, notifications | Inbox web **IMPLEMENTED BUT UNVERIFIED** (comportement JS non testé) ; API revues/notifications **WORKING & VERIFIED** ; Console **WORKING & VERIFIED** ; Workspace UI générée (R5) **ABSENT** | `autology/static/` (`app.js:126,221,313-335,362`), `console.py` | `test_platform.test_http_hygiene_and_inbox` (service seulement), `test_approvals`, `test_console` — OK | Pas de tableaux de bord, pas de notifications push/e-mail | R5 |
| 18 | Préparation production : déploiement, config, sauvegarde/restauration, supervision, alerting, reprise, performance | **PARTIAL** | `Dockerfile` (non-root, healthcheck), `deploy/docker-compose.yml`, `autology backup` (copie vérifiée), `/api/metrics` | `test_delivery` (6), smoke test CI — OK | **Restauration jamais exercée** (GAP-033) ; pas d'alerting ; SQLite mono-nœud (GAP-055) ; serveur threadé sans limites ; aucune preuve d'hébergement | D2, D3, PROD |
| 19 | Licences, restrictions de distribution, obligations tierces, revue de sécurité | **BLOCKED** (juridique) ; ingénierie **WORKING & VERIFIED** | `LICENSE`, `THIRD_PARTY_NOTICES.md`, `deploy/image_licences.py`, `studio/web/licences.json` | `test_leg1_licences`, CI `package` — OK | Entité légale, texte de licence, LGPL (psycopg), paquets Debian, CC-BY-4.0, `sharp`/libvips (L1–L6) ; aucune revue de sécurité humaine (GAP-054) | **D19**, D5 |
| 20 | Documentation, expérience développeur, extensibilité, maintenabilité | **PARTIAL** | `docs/` (13 docs), `planning/` (24 docs), points d'extension (§6) | — | Pas de lint/typage/scan en CI (GAP-025 ; 201 erreurs mypy) ; objet-dieu `AutologyService` (GAP-026) ; registres partiellement périmés (§1.2) | — |

---

## 4. Architecture telle que construite (et non cible)

```
                 navigateur (Studio)                navigateur (inbox web)        client MCP / script
                        │ HTTPS (proxy inverse, hors dépôt)       │                        │
                        ▼                                         │                        │
   Studio Next.js (studio/web) ── relais lib/forward.ts ──┐       │                        │
   (GET/POST sous /platform/ et /w/ ; 2 en-têtes ;        │       │                        │
    pas de base de données, pas de règle métier)          ▼       ▼                        ▼
                                         Routeur plateforme (autology/platform.py)  ◄─ autology mcp --url (relais)
                                         /platform/v1/... (cas d'usage, stades, modèles)
                                         /w/<ws>/u/<uc>/api/v1/... → moteur du cas d'usage
                                         404 identiques ; jetons par espace ; lifecycle.db (HMAC)
                                                         │ appel en processus (ApiExchange)
                                                         ▼
                              Moteur (autology/server.py: AutologyService) — un par cas d'usage
                              gouvernance → agents → outils (barrière de stade) → write-back
                                     │                      │                   │
                         SQLite autology.db         outils HTTP / webhooks / approbateur HTTP
                         (audit append-only,        (simulated / sandbox ; production refusée
                          journal d'effets,          par tout stade)
                          sceaux, brouillons)
                                     │
                         warehouse.py → base de reporting (SQLite/PostgreSQL), lecture BI
```

| Question | Constat | Confiance |
|---|---|---|
| Le moteur est-il la seule autorité ? | Oui. Studio et la Console n'ont ni base de données ni règle d'autorisation propre ; les contrôles côté UI sont décoratifs et les e2e prouvent que les appels directs sont refusés (`studio/web/e2e/run.mjs`, 403/404/404/403/403 en v1 et legacy) | VÉRIFIÉ |
| Règles métier dupliquées en frontend ? | `studio/web/lib/model.ts` manipule le document d'ontologie (ajout/suppression) mais **toute** validation est demandée au moteur (`POST /api/v1/model/validate`) ; la sauvegarde exige `expected_revision` | VÉRIFIÉ |
| Accès direct à la base ? | Aucun frontend. Le store SQLite est accessible à quiconque a le fichier : écritures détectées par sceaux (GAP-018), pas empêchées | VÉRIFIÉ |
| Chemins d'autorisation contournables ? | (a) `HttpApprover` contourne l'exigence d'un humain (F-02) ; (b) un moteur autonome (`stage_gate=None`) n'est pas soumis aux stades (par conception, `test_a_standalone_engine_is_not_governed_by_stages`) ; (c) mode `simulation: true` autorise données libres et approbateurs automatiques | VÉRIFIÉ |
| Frontières de locataire | Fortes au niveau routeur (404 identiques, jetons uniques, clés d'audit dérivées par espace, préfixes de secrets) | VÉRIFIÉ |
| Bus d'événements / jobs | Aucun bus ; automatisations synchrones dans les threads de requête sous un verrou (GAP-057) ; ordonnanceur par `tick` | VÉRIFIÉ |
| Couplage | `AutologyService` concentre la plupart des responsabilités (GAP-026) ; le routeur appelle le moteur en processus | VÉRIFIÉ |
| Workspace UI utilisateur final | Inbox web embarquée (optionnelle) + Console ; pas d'application Workspace séparée | VÉRIFIÉ |

**Architecture future proposée (non construite)** : releases immuables, service d'administration, service
d'architecte IA, readiness, Workspace UI générée, connecteurs ERP, file de travail asynchrone — voir
`planning/AUTOLOGY_ARCHITECTURE_TARGET.md`. Rien de cela n'est à considérer comme existant.

---

## 5. De la décision à l'action, de bout en bout

Exemple synthétique : `examples/auto_insurance` (sinistres CL-1 propre, CL-2 suspect). Six tests exécutés
individuellement par un sous-agent et à nouveau dans la suite complète : OK.

| Étape | Chemin implémenté | Preuve | Manque / risque de contournement |
|---|---|---|---|
| Contexte métier → cas | `AutologyService.start_run` (`server.py:1397`), `graph.build_case` (`graph.py:174`) | `test_review_integrity.FreeFormCaseTests.test_requester_cannot_supply_the_facts` | Admin ou mode simulation peut fournir des faits libres |
| Ontologie | `examples/auto_insurance/ontology.json` ; `Ontology` gelée, empreinte SHA-256 | `test_auto_insurance.SemanticLayerTests`, `test_core.OntologyTests.test_fingerprint_is_content_addressed` | Référence de run = `name@version`, pas l'empreinte |
| Proposition de décision | `Planner.plan` (`planner.py:99`) ; `reasoner.propose` sur vue expurgée (`agent.py:731-743`) | `test_agent.GuardrailTests.test_rogue_reasoner_cannot_skip_legal_review` | Le LLM propose seulement ; repli sur le plan conforme |
| Politique / criticité | `GovernanceLayer.evaluate` (`governance.py:229`) appelé à chaque étape (`agent.py:749`) | `test_core.GovernanceTests.*`, `test_auto_insurance.KineticLayerTests.test_fraud_is_never_paid` | Fail closed |
| Niveau d'autonomie | Humain seulement si une règle `human_review` s'applique ; approbateurs automatiques refusés hors simulation (`server.py:189-191`) | `test_clean_claim_is_paid_the_computed_payout` (aucun humain) ; `test_approvals.ApproverConfigTests.test_automatic_approvers_need_the_simulation_flag` | **F-02 : `HttpApprover`** |
| Autorisation / approbation | `AutologyService.decide` (`server.py:1523-1561`) : rôle, anti-auto-revue, stade, `ontology_ref` ; liaison au hash d'audit (`agent.py:592-595`) ; revalidation des faits (`agent.py:610`) | `test_approvals.SelfReviewTests.*`, `test_act6_revalidation.*` | Décision non liée à l'empreinte (GAP-020) |
| Demande d'exécution | `WorkAgent._execute` (`agent.py:376`), barrière de stade (`:403-411`, `server.py:970`) | `test_r2_execution_gates.*` | Environnement d'outil par défaut `production` (donc refusé en plateforme) |
| Résultat externe | Intention journalisée avant l'appel, clé d'idempotence, classification, réconciliation humaine (`server.py:1707`, starter exclu `:1722`) | `test_external_effects.*`, `test_external_effects_matrix.test_the_whole_matrix` | — |
| Réconciliation / write-back | `_write_back` (`server.py:720`) → `commit_write_set` (`store.py:916`) ; reprise des write-backs interrompus (`server.py:781`) | `test_gap009_atomic_write_back.*` | Sauvegarde du run et write-back = 2 transactions (comblé par la récupération) |
| Audit / preuve | Chaîne HMAC + tête MAC (`audit.py:90-145`), sceau du run (`store.py:523,693`) | `test_audit_integrity.*`, `test_gov4_run_record_seal.*`, `test_iso2_workspace_audit_keys.*` | Entrées d'un segment en mémoire jusqu'à `save_run` |

**Où le flux s'arrête :** au stade *pilot*, sur des outils `simulated` ou `sandbox`. Aucun stade n'atteint la
production (décision PROD, `lifecycle.py:59`) et aucun connecteur ERP réel n'existe. **Blocs minimaux manquants pour
aller plus loin :** releases immuables liées à l'empreinte, approbation indépendante (D11), connecteur sandbox Odoo
(D6), décision D15, preuves d'hébergement et de reprise.

### 5.1 Cas défavorables

| Cas | Couvert ? | Preuve |
|---|---|---|
| Action non autorisée | Oui | `test_operations.AccessControlTests.test_action_access`, `test_gov5_effective_permissions.*` |
| Mauvais locataire | Oui | `test_workspaces.test_foreign_or_unknown_workspaces_are_indistinguishable`, `test_iso4_isolation_matrix.*`, `test_api_v1` (v1) |
| Politique périmée après approbation | **Partiel** | Stades liés à l'empreinte (`test_a_stage_is_stale_when_the_configuration_changes`) ; **décision de revue non liée à l'empreinte**, aucun test « ontologie modifiée à version égale puis décision » |
| Mises à jour concurrentes | Oui | `test_gap018_record_consistency.RevisionTests.*`, `test_gap018_directive02.ConcurrencyTests` |
| Intégration en échec | Oui | `test_tool_failures.*`, `test_external_effects.test_a_rejected_payment_is_not_retried` |
| Reprise dupliquée | Oui | `test_external_effects.IdempotencyKeyTests.*`, `RecoveryTests.test_an_automation_retry_never_starts_a_second_payment` |
| Succès partiel multi-effets | **Non : pas de compensation** | Escalade humaine uniquement |
| Crash / redémarrage | Oui | `test_external_effects.RecoveryTests.test_a_crash_after_approval_never_pays_twice`, `test_platform.AsyncReviewTests.test_park_survive_restart_and_resume` |
| Release modifiée après approbation | **Non** (pas de releases) | — |
| Escalade de privilèges par un agent | Oui | `test_agent.GuardrailTests.*`, `test_suspension.*`, `test_gap018_record_consistency.McpThroughThePlatformTests.test_mcp_cannot_decide_reviews_or_run_anything` |
| Store d'audit indisponible | **Partiel** (fail closed par construction, non testé par injection) | `test_tool_failures.ServiceTests.test_a_failed_save_never_repeats_the_calls_already_made` ; aucun test n'injecte d'échec dans `record_intent` |

**Gouvernance obligatoire, humain optionnel selon la politique :** **appliqué par le code**, pas seulement documenté :
la seule invocation d'outil (`agent.py:441`) n'est atteignable qu'après `_authorize` (`agent.py:749`) ; un humain
n'intervient que si une règle le demande ; un approbateur automatique est refusé hors simulation. **Exception :**
F-02 (`HttpApprover`). VÉRIFIÉ.

---

## 6. Architecture de plugins : réalité actuelle vs option future

*« Autology Core + Plugin Runtime » est traité comme une **direction stratégique en évaluation**, non approuvée et non
implémentée.*

**Points d'extension existants (réutilisables) :**
- `adapters.py:82` `import_target("module:attr")` : import en processus, **sans bac à sable** ;
- `adapters.py:185` `load_tools` : types `python`, `http`, `table`, plus fabriques `registries` ; types inconnus refusés
  (`:220`) ;
- `tools.py:105-147` `ToolRegistry` et le décorateur `@tool`, avec un `environment` déclaré et validé ;
- `adapters.py:281` `load_approver` et `adapters.py:304` `load_reasoner` ; protocoles `Reasoner` et `ChatModel`
  (`reasoners.py:92,114`) ;
- pilotes de base de données par nom de module (`ingest.py:332`, `warehouse.py:202`) ;
- générateurs de SDK `sdk.py:540` ; blueprints découverts par glob (`modeling.py:26`) ;
- composition d'ontologies par `imports` et `modules` (`ontology.py:1174`) ; `OntologyRegistry` (`versioning.py:181`).

**Manquant pour un vrai runtime de plugins :** découverte (entry points), manifeste, contrat de version et de
compatibilité, permissions déclarées, isolation (processus séparé ou sandbox), signature et vérification,
cycle de vie (installer, activer, désactiver), observabilité par plugin, contrat de connecteur.

**Catégories qui gagneraient à être modulaires :**
- fournisseurs LLM (D7) ;
- connecteurs ERP, MES et SCADA ;
- packs sectoriels et blueprints ;
- RAG et retrieval ;
- extensions d'UI (Studio).

Les « business apps » sont à évaluer plus tard.

**Ce qui doit rester obligatoire dans le cœur et non contournable :**
- authentification et isolation des locataires ;
- `GovernanceLayer.evaluate` et le contrôle d'intégrité ;
- barrières de stade et d'environnement ;
- journal d'intention, idempotence et réconciliation ;
- audit HMAC et sceaux ;
- anti-auto-revue ;
- refus de la production.

**Risques de migration :** casser l'invariant « seule invocation d'outil après `_authorize` » ; un plugin en
processus peut tout faire, faute d'isolation.

**Preuve de concept minimale (non implémentée) :** un manifeste pour un adaptateur LLM fictif, chargé par entry
point, et un test prouvant qu'il ne peut ni appeler un outil ni écrire dans le store sans passer par la gouvernance.

---

## 7. Intelligence sectorielle et normes

| Élément | Constat |
|---|---|
| Packs de connaissance sectoriels | **ABSENT** : un blueprint synthétique, `water_treatment.json`, et des exemples ; aucun pack réglementaire |
| Licences, provenance, version et date d'effet des sources | **ABSENT** pour les documents. La lignée existe pour les données ingérées (`/api/objects/{id}/lineage`) |
| RAG hybride, GraphRAG | **ABSENT**. Le graphe de connaissances est opérationnel (requêtes, questions de compétence), sans retrieval textuel |
| Exigence citée → politique exécutoire revue | **ABSENT** comme flux. Les règles sont écrites à la main dans l'ontologie ; un brouillon ne devient jamais actif sans releases |

Le « Standards & Compliance Hub » reste une **hypothèse produit**. Récupérer le texte d'une règle ne prouve pas la
conformité. Aucune ingestion de normes propriétaires sans droits n'est proposée.

---

## 8. Sécurité, sûreté, gouvernance des données

*Revue statique non intrusive. Ce n'est **pas** un test d'intrusion. Constats datés d'aujourd'hui, distincts des
constats historiques déjà clos.*

### 8.1 Nouveaux constats (15 nov.)

| ID | Constat | Gravité | Preuve | Confiance |
|---|---|---|---|---|
| **F-01** | Ingest HTTP paginé : l'URL `next` vient de la réponse distante, et les en-têtes configurés, **secrets compris**, lui sont renvoyés sur n'importe quel hôte. Une source compromise peut ainsi capter le secret ou viser des hôtes internes (SSRF) | **Moyenne** | `autology/ingest.py:362-384` (revérifié) ; aucun test de pagination inter-hôtes | VÉRIFIÉ |
| **F-02** | `HttpApprover` n'a pas d'attribut `can_approve`, donc la garde « approbateurs automatiques seulement en simulation » ne s'applique pas. Une réponse `{"approved": true}` d'un service externe approuve une revue humaine, avec un nom de relecteur fourni par ce service et sans contrôle d'auto-revue. Seule la barrière d'environnement s'applique en plateforme ; aucune en moteur autonome | **Moyenne** | `adapters.py:232-257`, `server.py:186-191` (revérifié) | VÉRIFIÉ |
| F-03 | Changements de stade sans deuxième personne : un administrateur peut créer un cas d'usage et le mener seul jusqu'en pilot | Moyenne | `platform.py:356-361`, `lifecycle.py:261-293` | VÉRIFIÉ (lié à D11) |
| F-04 | Décision de revue liée à `name@version`, pas à l'empreinte : une ontologie modifiée sans changement de version n'invalide pas une revue en attente. La gouvernance est réévaluée à la reprise, donc un nouveau DENY l'emporte | Moyenne | `server.py:1554`, `ontology.py:615-617` | VÉRIFIÉ (= GAP-020) |
| F-05 | Clé API de la Console stockée en clair (mode 0600) ; SQLite non chiffré | Moyenne | `settings.py:47-57`, `store.py:230-234` | VÉRIFIÉ (D3, D13) |
| F-06 | Chaîne d'approvisionnement : image de base `python:3.13-slim` sans digest ; actions CI épinglées par tag, pas par SHA ; `pip` mis à jour sans version ; contraintes sans hachages ; extras `anthropic` non épinglés dans `pyproject.toml` | Moyenne / faible | `Dockerfile:6`, `.github/workflows/tests.yml:30-43`, `pyproject.toml:16-18` | VÉRIFIÉ (= GAP-040 partiel) |
| F-07 | Pas d'expiration de jeton, pas de limitation de débit ni de verrouillage, pas de timeouts ni de plafond de threads côté serveur | Faible / moyenne | `server.py:2418`, `platform.py:503` | VÉRIFIÉ / INFÉRÉ (DoS) (= GAP-030) |
| F-08 | Les redirections HTTP sortantes sont suivies par défaut, en conservant les en-têtes (outils, approbateur, webhooks, OIDC, ingest). Les corps de réponse sont lus sans limite de taille | Faible | `adapters.py:126`, `ingest.py:375` | INFÉRÉ |
| F-09 | OIDC : la vérification de `redirect_uri` par `startswith("http://localhost")` accepte `localhost.<domaine>` ; émetteur `http://` accepté ; pas de contrôle `azp` | Faible | `oidc.py:105,251` | VÉRIFIÉ (le contrôle de l'IdP limite le risque, INFÉRÉ) |
| F-10 | Le relais Studio lit tout le corps avant d'appliquer la limite de 1 Mo ; CSP `'unsafe-inline'` | Faible | `studio/web/lib/forward.ts:46-48`, `next.config.ts:8` | VÉRIFIÉ |
| F-11 | Les écritures du journal d'accès échouent ouvertes (la réponse part quand même) ; le journal d'accès n'est pas chaîné | Faible | `server.py:2207`, `platform.py:457` | VÉRIFIÉ |

**Points solides vérifiés :**
- jetons hachés et comparés en temps constant ;
- OIDC strict : RS*, `none`/HS* refusés, `aud`/`iss`/`exp` vérifiés, nonce, taille de clé, re-fetch JWKS limité
  (`test_oidc`) ;
- 404 identiques entre locataires ;
- secrets isolés par préfixe d'espace de travail ;
- clés d'audit dérivées par espace ;
- tables append-only protégées par triggers ;
- chaînes HMAC avec tête ;
- sceaux de runs et d'enregistrements ;
- outils MCP et assistant sans pouvoir de décision ;
- production refusée en premier ;
- limite de corps de 1 Mo ;
- erreurs 500 sans détails internes.

Aucun secret réel trouvé dans le dépôt : les préfixes `sk-ant-api03-` sont des fixtures incomplètes, et les clés
d'audit des fichiers d'exemple ou de CI sont factices. Les valeurs ne sont pas reproduites ici.

**Analyse statique (ruff 0.17.5, règles E, F, W, B, S)** : 3 558 avertissements, dont 3 483 lignes trop longues.
Les règles S608 (« SQL par chaîne », 7) et B023 (14) ont été examinées une par une : **faux positifs**. Les colonnes
viennent de tuples fixes ou d'un identifiant validé (`warehouse.py:41`), les valeurs sont paramétrées, et les lambdas
sont appelées dans la même itération. 14 imports inutilisés. Détail : `evidence/ruff_*.txt`.

### 8.2 Statut des gaps GAP-009, GAP-018, GAP-031

| Gap | Statut du registre | Évaluation de l'audit |
|---|---|---|
| GAP-009 | Fixed | **Maintenu « Fixed » pour le périmètre local** (write-back atomique, revalidation ; tests OK). L'atomicité ne s'étend pas aux systèmes externes : aucune compensation. C'est un périmètre à documenter, pas un défaut de la correction. Le paragraphe contradictoire du registre est à corriger (C1) |
| GAP-018 | Fixed (vérification indépendante ouverte) | **Maintenu**. Révisions, sceaux, migrations transactionnelles et test de concurrence sont OK. Limite : les écritures directes dans la base sont détectées, pas empêchées |
| GAP-031 | Partly fixed | **Correct**. L'ingénierie est faite ; L1–L6 et D19 restent en attente. Aucune distribution n'est possible |

Aucun gap clos ne nécessite d'être rouvert sur la base des preuves d'aujourd'hui. F-01 et F-02 sont **nouveaux**.

---

## 9. API, base de données, infrastructure, qualité

### 9.1 Pile technique

| Couche | Choix | Version / contrainte |
|---|---|---|
| Moteur | Python, stdlib uniquement à l'exécution | ≥ 3.10 ; CI 3.10 et 3.13 ; image 3.13 |
| Store opérationnel | SQLite (WAL), schéma 15 | Mono-nœud (D2 en attente) |
| Reporting | SQLite ou PostgreSQL (psycopg 3.3.9 dans l'image) | — |
| LLM (optionnel) | `anthropic` 2.8.0 (image) ; adaptateur `ClaudeReasoner` | non exécuté contre un vrai modèle |
| Studio | Next.js 16.4.6, React 19.3.1, TypeScript 5.9.3, @xyflow/react 12.12.1, Vitest 5.1.0, Playwright 1.63.0, openapi-typescript 7.13.0 | lock file, `npm ci` |
| Image | `python:3.13-slim` (tag), contraintes `==` | — |

**API :**
- REST v1 sous `/api/v1` et `/platform/v1`, avec les chemins legacy dépréciés ;
- authentification Bearer, plus OIDC par espace ;
- validation : schéma d'ontologie strict ; corps JSON limité à 1 Mo ;
- erreurs : enveloppe v1 unique ;
- pagination `page`, sur `objects` et `runs` uniquement ;
- compatibilité : politique additive, `docs/api-versioning.md`.

**Point faible :** les schémas de réponse typés ne couvrent qu'environ 10 routes moteur sur 57 chemins.

### 9.2 Inventaire des tests (exécutés aujourd'hui)

| Catégorie | Exemples | Nombre approx. |
|---|---|---|
| Unitaires (ontologie, règles, expressions, ordonnancement, scoring) | `test_core`, `test_functions`, `test_scheduling*`, `test_scoring` | ~250 |
| Intégration HTTP (serveur, plateforme, Console, MCP) | `test_platform`, `test_workspaces`, `test_console`, `test_mcp`, `test_oidc` | ~150 |
| Contrat | `test_api_contract`, `test_api_v1`, `test_entry_point_matrix` | 18 |
| Sécurité et isolation (non intrusifs, déterministes) | `test_iso1…4`, `test_gov1…5`, `test_audit_integrity`, `test_chat_safety`, `test_review_integrity` | ~80 |
| Reprise et pannes | `test_external_effects*`, `test_tool_failures`, `test_gap009*`, `test_gap018*` | ~60 |
| Concurrence (charge légère) | `test_gap018_directive02.ConcurrencyTests` (6 écrivains × 5 incréments) | 1 |
| E2E navigateur (Studio) | `studio/web/e2e/run.mjs` | 25 vérifications + 2 contrôles moteur sans Studio |
| Unitaires Studio | `studio/web/tests/*.test.ts` | 17 |
| **Absents** | tests de charge et de performance réels, restauration, pénétration, tests JS de l'inbox, fuzzing | — |

*Les catégories et les nombres approximatifs sont INFÉRÉS à partir des noms de fichiers ; les totaux sont VÉRIFIÉS.*

### 9.3 Commandes exécutées pendant l'audit (environnement : conteneur Linux, Python 3.13, Node 22.23.4, npm 10.9.9)

| Commande | Précaution | Durée | Résultat |
|---|---|---|---|
| `ANTHROPIC_BASE_URL=http://127.0.0.1:9 ANTHROPIC_API_KEY= python -m coverage run --source=autology -m unittest discover -s tests -t . -v` | Variable LLM pointée vers un port fermé : aucun appel LLM possible ; SQLite temporaires ; serveurs locaux sur 127.0.0.1 | 259 s | **661 tests, OK (2 ignorés : PostgreSQL non configuré localement ; exécutés en CI)** |
| `python -m coverage report` | — | — | **96 %** (10 981 instructions, 404 manquées ; 96,32 %) |
| `npx tsc --noEmit` (studio/web) | — | 2 s | OK |
| `npx vitest run` | — | 1 s | **17/17** |
| `npm run build` | `NEXT_TELEMETRY_DISABLED=1` | 3 s | OK |
| `e2e/run.sh` | Plateforme d'exemple locale (ports 8701, 8961) | 6 s | **25/25**, plus « Studio arrêté » et « moteur répond sans Studio » |
| `npm audit --omit=dev` | Lecture seule, requête au registre npm | — | 0 vulnérabilité |
| `ruff check --select E,F,W,B,S autology` (venv temporaire hors dépôt) | Analyse statique | — | 3 558 avertissements ; aucun défaut de sécurité confirmé |
| `mypy --ignore-missing-imports autology` | idem | — | **201 erreurs** |
| `pip-audit -r deploy/image-constraints.txt --no-deps` | Lecture seule (base OSV/PyPI) | — | Aucune vulnérabilité connue |
| `python -m compileall -q autology` | — | — | OK |

**Non exécutés et pourquoi :**
- construction de l'image Docker : déjà verte en CI run 64 ; risque de limite de débit Docker Hub ;
- tests PostgreSQL : pas de base locale ;
- tout appel à un vrai LLM, IdP ou ERP : interdit, et inexistant.

Journaux : `audit/2026-11-15/evidence/`.

### 9.4 CI/CD, exploitation

- **CI** : 4 jobs (test 3.10, test 3.13 avec PostgreSQL, package avec image, licences et image sans LGPL, studio avec
  dérive de contrat et e2e). La couverture minimale est de 95 %. **Absents** : lint, typage, scan de dépendances
  (GAP-025).
- **Release** : `.github/workflows/release.yml` existe ; aucun tag ni release publiée.
- **Exploitation** :
  - existe : sauvegarde vérifiée à chaud (`autology backup`), healthcheck Docker, métriques Prometheus ;
  - n'existe pas : exercice de restauration (GAP-033), RPO/RTO définis, alerting, haute disponibilité (GAP-055).
- **Goulots** : automatisations synchrones sous verrou (GAP-057), scans complets de tables (GAP-023), serveur threadé
  sans plafond.
- **Points uniques de défaillance** : fichier SQLite par cas d'usage ; processus unique de la plateforme.
- **Dette** :
  - objet-dieu `AutologyService` (GAP-026) ;
  - diff sémantique incomplet (GAP-028) ;
  - export JSON-LD lossy (GAP-027) ;
  - 201 erreurs mypy ;
  - registres partiellement périmés.

---

## 10. Feuille de route, décisions ouvertes, bloqueurs externes

### 10.1 Réconciliation de la feuille de route (source : `planning/AUTOLOGY_RELEASE_ROADMAP.md`)

| Release | Périmètre selon le dépôt | État réel |
|---|---|---|
| R1 | Fondation ingénierie | Fait. Signature juridique et revérification indépendante ouvertes |
| **R2** | Studio et gouvernance : API, ARC-0, MIG-1, QA-1, AI-1, UI-1, ADM-1/2, REL-1–4, ARC-1–4, BP-1, SEC-A, STU-1–6 | **En cours**. Faits : API-2, STU-1. Partiels : API-1, MIG-1, ADM-1, REL-1, REL-2, ARC-1 (prototype), ARC-3 (questions par règles), STU-2, STU-3. Non commencés : ARC-0, QA-1, AI-1, UI-1, ADM-2, REL-3, REL-4, ARC-2, ARC-4, BP-1, SEC-A, STU-5, STU-6 |
| R3 | Onboarding structuré : Excel, documents, organisation, systèmes | Non commencé |
| R4 | Agent Factory et intégrations, Odoo 18 sandbox | Non commencé |
| R5 | Expérience opérationnelle, Workspace UI | Non commencé |
| R6 | Préparation produit, gates 90 et 95 | Non commencé ; essentiellement des preuves externes |

### 10.2 Décisions et bloqueurs

Voir `AUTOLOGY_GAP_DECISION_REGISTER_2026-11-15.md` : question exacte, options, preuves, impact et
recommandation (étiquetée) pour D2, D3, D7, D10, D11, D13, D15, D16, D17, D18, D19 et D20.

**Bloqueurs externes**, séparés des bloqueurs d'ingénierie :
- client pilote et données utilisables (D16) ;
- signature juridique et entité légale (D19) ;
- licences tierces (LGPL psycopg, paquets Debian, CC-BY-4.0, `sharp`/libvips) ;
- revue de sécurité humaine et test d'intrusion (GAP-054) ;
- choix de fournisseurs LLM et résidence des données (D7, D10) ;
- autorité d'écriture ERP en production (D15) ;
- preuves d'hébergement de production (PROD).

---

## 11. Maturité produit et préparation commerciale

**Aucun nouveau score chiffré n'est donné.** Les scores existants :
- 47/100 (audit du 13 nov., `audit/03`, méthode pondérée) : réalisé par des agents IA dont l'auteur du code ;
- ≈ 65/100 (auto-évaluation, `planning/AUTOLOGY_MATURITY_SCORECARD.md:9`) : non vérifiée.

Aucun ne doit être présenté comme un score indépendant actuel. Cadre reproductible proposé : réutiliser la méthode
de `audit/03` (sous-critères, poids, plafonds de preuve), mais faire calculer le score par une personne ou une
organisation indépendante sur un commit figé.

| Évaluation | Gates go/no-go vérifiables | État |
|---|---|---|
| **A. Complétude ingénierie R2** | (1) contrat versionné ; (2) releases immuables et rollback ; (3) approbation indépendante ; (4) readiness 6 dimensions ; (5) administration des membres ; (6) adaptateurs LLM ×2 ; (7) Studio releases et readiness ; (8) lint, typage et scan en CI | (1) **Go** ; (2)–(8) **No-go** |
| **B. Sécurité et gouvernance** | gouvernance à chaque étape ; isolation ; audit infalsifiable ; séparation des tâches pour promotions et accords ; chiffrement au repos ; rotation et expiration des jetons ; revue humaine indépendante ; F-01 et F-02 corrigés | Les 3 premiers **Go** ; les autres **No-go** |
| **C. Fonctionnement décision → action** | flux synthétique de bout en bout, avec revue, effets idempotents, write-back et audit ; liaison décision–release ; compensation | Flux **Go** (synthétique, sandbox) ; liaison et compensation **No-go** |
| **D. Pilote non-production autorisé** | D16 (client, données) ; connecteur sandbox (D6) ; hébergement et TLS ; sauvegarde et restauration exercées ; F-01, F-02 et F-03 traités ; D11 | **No-go** : externe et ingénierie |
| **E. Distribution commerciale** | D19 / L1–L6 ; revue de sécurité indépendante ; release publiée ; support | **No-go** (bloqué juridiquement) |

---

## 12. Options de développement suivantes

Voir `AUTOLOGY_NEXT_INCREMENTS_2026-11-15.md`.

**Recommandation unique : REL-1a, releases immuables liées à l'empreinte.** Elle couvre le rollback, et lie les runs
et décisions de revue à la release. Elle ferme F-04/GAP-020 et le cas « release modifiée après approbation » ; elle
est le prérequis de l'activation des brouillons, du rollback, de la readiness et de l'écran Releases.

**Alternative si l'on veut d'abord des gains rapides, ou si la conception de REL-1a attend une décision :** H-1,
durcissement (F-01, F-02, épinglage de la chaîne d'approvisionnement, mise à jour des registres).

**Aucune implémentation n'est commencée.** Le travail attend une autorisation explicite du propriétaire.
