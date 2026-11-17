# AUTOLOGY — CROSS-DOMAIN ARCHITECTURE VALIDATION REPORT

*R2 cross-domain validation: universal Engine, Studio and application architecture. 17 November 2026.
Branch `claude/autology-ontology-agent-4ajjer`. Engineering development and synthetic simulation only.*

## Summary

**The hypothesis.** One Engine, one Studio, several independent intelligent applications.

**What the evidence supports.** Two applications that have nothing in common (the coordination of a fictional
flood; a fictional corporate compliance investigation) were configured, released, simulated and audited on the same
Engine through the same Studio journey, in separate workspaces with separate people, releases, records, runs and
audit trails. The Engine and Studio contain no word of either domain; a test scans for it. Neither domain could
reach anything of the other. Five limits were found on the way; all five were general (none was "the engine lacks
crisis logic") and were fixed as general corrections, which this report lists one by one.

**What the evidence does not support.** The two models were written by an engineer as templates and delivered
through the sandbox test double. **No language model was asked anything, and nothing was spent.** So this sprint
shows that the platform *hosts* unrelated domains without being changed for them. It does not show that the AI
Architect can *produce* a sound model for an unfamiliar domain from a description: without a template the sandbox
asks one question and proposes nothing, and the only real-model evaluation so far did not meet its thresholds.
Nothing here is evidence of fitness for real emergency response or real investigations.

**R2 is not closed.**

| Kept as they were | State |
|---|---|
| Version 1 evaluation: cases, thresholds, recorded results | Unchanged, pinned by a test |
| Whole-answer refusal of a non-conforming model answer | In force, unchanged |
| Spending: 4.418875 USD spent, 5.581125 USD remaining, 10 USD ceiling | Unchanged; no call made |
| Third paid evaluation, compile probe | Not run |
| Production execution | Disabled |
| mypy baseline | 198, not raised |

---

## A. Repository and engineering evidence

### A.1 Commits

| | Commit | CI |
|---|---|---|
| Start | `76b55e7` (clean, equal to the remote) | [run 111](https://github.com/edlwiseltd/ontology/actions/runs/44088491962): success |
| Baseline the directive named | `8c9fe94` | [run 110](https://github.com/edlwiseltd/ontology/actions/runs/44086874836): success (verified again) |
| Increment 1: general abstractions, two packs, cross-domain tests | `c202a68` | [run 112](https://github.com/edlwiseltd/ontology/actions/runs/44168331726): **success**, all five jobs |
| Increment 2: Studio journey, application contract, element-level design | `d046b8d` | [run 113](https://github.com/edlwiseltd/ontology/actions/runs/44170185564): **failed** in the `studio` job: 47 of 48 new browser checks passed; one check read a notice before the page had finished loading the provider's state (a defect of the check, corrected in increment 3). The two Python jobs (full suite on PostgreSQL, coverage gate), `package` and `quality` succeeded |
| Increment 3: cross-domain reading of the protocol, ledger assessment, the corrected browser check, registers, this report | `84c2725` | [run 114](https://github.com/edlwiseltd/ontology/actions/runs/44174038450): **success**, all five jobs |
| This line and the same line in the log | the commit after `84c2725` (documents only) | not awaited |

### A.2 Baseline verification

| Item | Found |
|---|---|
| Branch, HEAD, state | `claude/autology-ontology-agent-4ajjer`, `76b55e7`, clean, equal to the remote |
| Registers read | Implementation log, defect register (91 entries: 56 fixed, 14 open, 12 partly, 5 owner decision, 4 external evidence), decision register (D30 f/g/h, D31, D32 pending), traceability, roadmap §3.5 |
| CI run 110 | Success, confirmed from GitHub, not from the log |
| Spending ledger | `adopted-32ec21e0feedb3cf79b65e96`, 27 entries, 4.418875 USD settled: verified from the ledger, not from the earlier report |
| Multi-agent | Design note only (D32); a stored run has one agent |
| Domain assumptions already in the Engine and Studio | **(1)** The architect's templates could only live inside the engine package, which ships three (service request, supplier disruption, water treatment). **(2)** Platform templates were offered to every workspace. **(3)** Studio's design view sent a water-treatment description when the field was empty, and two hints named deliveries and suppliers. **(4)** Docstrings and comments use claims, orders and patients as examples (no behaviour). **(5)** The evaluation cases are business cases stored as package data (by design). Nothing in the Engine branches on a domain |

### A.3 Modified modules

Engine (`autology/`), against `76b55e7`: 10 files changed, 321 lines added, 28 removed (192 of them the new, inactive `architect_elements.py`).

| Module | Change | Domain-specific? |
|---|---|---|
| `modeling.py` | `library`: the blueprint folders a use case's configuration names; `blueprints`, `match`, `propose` accept them | No |
| `sandbox_ai.py`, `architecting.py`, `configuring.py`, `server.py` | Pass those folders to the sandbox architect and to the configuration suggestion | No |
| `platform.py` | A template may name the workspaces it is offered to | No |
| `views.py` | A row rule hides nothing in a run whose case holds no record of the restricted type | No |
| `solution.py` | The permission preview says "simulated" only of a tool the catalogue offers as simulated | No |
| `architect_elements.py` (new) | Element-level rejection, **not called by anything in force** | No |
| `architect_eval_v2.py` | `cross_domain`: a reading of a report by domain, no bound | No |

Studio (`studio/web`): `DesignView.tsx` (no default description), `OnboardingView.tsx` (a neutral hint);
`e2e/domains.mjs`, `e2e/serve_domains.py`, `e2e/run_domains.sh` (new).

Configuration and examples (not Engine): `examples/domains/` (two packs, one platform file, the generator, a
reference client). Documents: `docs/application-contract.md` and five planning documents.

### A.4 New abstractions

| Abstraction | Why it was needed | Size |
|---|---|---|
| **Blueprint library named by configuration** (`"blueprints"` in a use case's configuration) | A domain's templates are configuration of the use case that names them, not files of the Engine | about 30 lines |
| **Template scope** (`"workspaces"` on a platform template) | An application's starting point is offered to its own workspace | about 10 lines |

Nothing else was abstracted. No plugin mechanism, no domain module, no second workflow.

### A.5 Tests added

| File | Tests | What |
|---|---|---|
| `tests/test_xdom1_cross_domain.py` | 23 | The same journey for both domains, governed outcomes, isolation, neutrality scan, pack content |
| `tests/test_xdom2_application_contract.py` | 6 | The application contract, with a service identity |
| `tests/test_xdom3_element_level_rejection.py` | 15 | Element-level design and the replay of stored real answers |
| `tests/test_xdom4_cross_domain_assessment.py` | 5 | Cross-domain reading of the proposed protocol |
| `studio/web/e2e/domains.mjs` | 56 browser checks | The Studio journey, once per domain, by one function |

### A.6 Verification

All figures below are from runs on the final tree unless a row says otherwise. Nothing is reported that was not
run.

| Check | Result |
|---|---|
| Full Python suite, final tree (local) | **1,063 tests OK**; 2 skipped locally (they need PostgreSQL; CI runs them and allows no skip) |
| Coverage of `autology/` (same run) | **95.96 %** of lines (17,234 statements, 697 missed). Gate: 95 % |
| The same suite earlier in the sprint, before the last additions | 1,057 OK, 95.95 % |
| ruff (`autology`, `tests`, `deploy`, and `examples`) | Clean |
| mypy ratchet | **198 = baseline, not raised** |
| Studio typecheck; unit tests; build | Clean; **58 of 58**; built |
| Studio browser checks, existing journey | **135 of 135**; Studio stopped, Engine still answers |
| Studio browser checks, cross-domain journey | **56 of 56** |
| Secrets | The provider key, the four identity tokens and the audit key searched for, by value, in all 1,591 tracked and new files: none found |
| Provider | No request sent. The ledger was read, not written: 27 entries, 4.418875 USD, last entry 17 Nov 08:44 UTC |
| CI, increment 1 (`c202a68`) | Run 112: success, five jobs (Python 3.10 and 3.13 with PostgreSQL, package, Studio, quality) |
| CI, increment 2 (`d046b8d`) | Run 113: Python 3.10 and 3.13, package and quality **succeeded**; `studio` **failed** on one new browser check (47 of 48), a race in the check itself |
| CI, increment 3 (`84c2725`, the final code) | [Run 114](https://github.com/edlwiseltd/ontology/actions/runs/44174038450): **success**, five jobs: Python 3.10 and 3.13 with PostgreSQL (whole suite, no skip allowed, coverage gate 95 %), package, Studio (unit tests, 135 and 56 browser checks), quality (ruff, mypy ratchet, dependency audit) |

Not done, and not claimed: no independent review, no load test, no test with a language model, no test against
any real system.

---

## B. Architecture independence

### B.1 Architecture verification matrix

Both columns were exercised by the same test code with a different row of a table
(`tests/test_xdom1_cross_domain.py`, class `Journey`; `studio/web/e2e/domains.mjs`, function `journey`). The
sequence of routes, with identifiers replaced, is asserted **equal** for the two domains, answer codes included.

| Component | Crisis Management | Network Intelligence | Code path actually used (both) |
|---|---|---|---|
| AI Architect | Common | Common | `POST …/architect/proposals` → `ArchitectService.architect_proposals` (`architecting.py:135`) → `architect.propose` (`architect.py:363`) → `ModelGateway.complete` (`ai.py:782`) → `SandboxArchitect.invoke` (`sandbox_ai.py:141`) → `modeling.match` (`modeling.py:147`) on the folders from `modeling.library` (`modeling.py:126`) |
| Ontology validation | Common Engine | Common Engine | `POST …/model/validate` → `AutologyService.validate_model` (`server.py:956`) → `modeling.validate` (`modeling.py:45`) → `Ontology.from_dict` (`ontology.py:1004`); findings from `consistency.findings` (`consistency.py:38`) |
| Rules | Common Engine | Common Engine | `Governance._check` (`governance.py:165`) for reviews, prohibitions, mandatory steps and access; `row_visible` (`governance.py:154`); the rules themselves are data in each model |
| Identity and permissions | Common Engine | Common Engine | Members, tokens, two-person grants and the signed administration log in `platform.py` and `administration.py`; `AutologyService.require` (`server.py:594`) on every engine route; views in `views.py` |
| Agent contract | Common Engine | Common Engine | `solution.check` (`solution.py:151`) and `compile_solution` (`solution.py:305`): purpose, roles, goals, autonomy, tools from a closed catalogue of three simulated tools |
| Release governance | Common Engine | Common Engine | `Platform.publish_draft` (`platform.py:1367`), `ReleaseRegistry.propose` (`releases.py:213`), approval by another person, `Platform.activate_release` (`platform.py:1473`) |
| Simulation | Common Engine | Common Engine | Stage gate `lifecycle.move` (`lifecycle.py:263`); `RunService.start_run` (`runs.py:214`); reviews `reviews.py:43` |
| Audit | Common Engine | Common Engine | Signed chain per run, `Store.verify_audit` (`store.py:822`), `run_audit` (`server.py:1391`); administration log per workspace |
| Domain ontology | Domain configuration | Domain configuration | `examples/domains/<pack>/blueprints/*.json` (`items`) |
| Business workflows | Domain configuration | Domain configuration | The same file: actions, rules, goal, case template, agent, simulated tools, invented records |
| Operational interface | Future domain application | Future domain application | Not built. Contract: `docs/application-contract.md`; synthetic reference client: `examples/domains/reference_app.py` |

One class serves both use cases (`AutologyService`; asserted), and one provider class (`SandboxArchitect`).

### B.2 Kernel changes, and whether any is domain-specific

**Target: zero domain-specific kernel modifications. Result: zero.** Five general changes were needed; each is
listed here so that the owner can judge the word "general".

| # | General abstraction that was missing | Why two domains exposed it | Change | Register |
|---|---|---|---|---|
| 1 | Templates as configuration | A new domain's template had to be a file inside the Engine | `"blueprints"` in the use case's configuration | GAP-092 |
| 2 | Template scope | The second application's template appeared in the first one's list | `"workspaces"` on a template | GAP-097 |
| 3 | A row rule applies to rows that exist | The investigation model restricts one entity type among twelve; every run became invisible to the analysts and the reviewer, although no run held such a record | `views.hides_rows` ignores an entity type the case has no record of. A run that holds one is still hidden | GAP-094 |
| 4 | An honest preview | An unknown tool was shown as "simulated" in an invalid configuration's preview | "simulated" only for a catalogue tool | GAP-095 |
| 5 | Studio holds no domain | A water-treatment description was sent for an empty field | No default; neutral hints | GAP-096 |

Change 3 deserves the owner's attention (D33 c): it relaxes what was hidden. What was hidden before was a run that
contained nothing restricted, and the rule on rows and fields is untouched; the test `I8` shows both directions.

### B.3 Domain-specific workarounds

None in the Engine or Studio. Two things in the **packs** should be read as what they are:

* Each pack describes five proposed agents and runs with **one** executable agent that holds all the actions. A
  stored run has one agent; several governed agents on one case remain a design (D32). This is said in the pack,
  asserted by a test and not presented as orchestration.
* A link between two parties in the investigation model is a record of its own (`Association`), whose state says
  how it is known. The Engine has no notion of "an edge with a certainty"; an ordinary entity carries it. This is
  modelling, not a workaround, but it shows that edge attributes are not a kernel concept.

### B.4 Isolation evidence (`tests/test_xdom1_cross_domain.py`, I1 to I8)

| The owner asked | Test | Result |
|---|---|---|
| Crisis agents cannot access investigation records, and the reverse | I1: twenty routes of the other workspace, tried by four people of each side | 401, 403 or 404 each time; no entity name of the other domain in any answer |
| Permissions do not leak across workspaces | I2: the same person name in both workspaces, granted `read` in one | Reads in one; in the other the use case does not exist for that member (404). A grant cannot name the other workspace's use case (400) |
| A release from one domain cannot activate another's configuration | I3 | Approve, activate and rollback from the other workspace refused; each engine runs its own release; no part fingerprint is shared; every run names its own release |
| A domain agent cannot approve its own unauthorized actions | I4 (both domains) | The requester, an administrator without the reviewer role, the release approver, a member without a grant, the other domain's reviewer and an invalid token are all refused. The agent has no identity to decide with. The named reviewer's decision continues the run and is in the audit chain. A second decision is refused |
| Identical entity names create no cross-domain relationship | I5: `Organization` and record `ORG-1` exist in both | Two models, two records, disjoint links; a change in one leaves the other identical; separate stores |
| Simulated tools stay within declared capabilities | I6 | Five non-catalogue tools refused; an action of the other domain refused; an invalid configuration is not stored; the compiled tools are all `simulated` and cover only capabilities the model declares |
| (added) Templates and blueprints are scoped | I7 | The other workspace's template is "unknown"; the other domain's description gets one question, no proposal |
| (added) A row rule hides its rows and nothing else | I8 | Analyst refused the bank-account record and list; runs without such a record visible; a run with one hidden |

No cross-domain sharing feature was implemented.

---

## C. Crisis Management demonstrator (synthetic)

Pack: `examples/domains/crisis_management/`. Workspace `crisis`. Everything is invented; every tool is simulated.

| | |
|---|---|
| **Business description** | "A regional coordination centre handles a river flood across several municipalities. Take each incident report through validation, identify the response teams and equipment that could help, propose an allocation and assign a response team; shelters and supply needs are tracked." |
| **Ontology** | 10 entities: HazardEvent, AffectedArea, Infrastructure, IncidentReport, Resource, ResponseTeam, Shelter, SupplyRequirement, Assignment, Organization. 10 relationships (a hazard affects areas; an area has incidents, infrastructure and shelters; an incident has requirements and assignments; an assignment names a team and equipment; an organisation owns teams and resources) |
| **Facts, assumptions, predictions, recommendations** | `IncidentReport.information_basis` (observed or predicted), `source_verified`, and `Assignment.basis = recommendation`. The reference client's incident update keeps the four apart (test C5) |
| **Rules** | A duty coordinator approves an assignment when 50 or more people are at risk (the limit and the role are answers to the clarification questions). A team is **never** assigned on a prediction alone. A report is validated before any assignment. Only an operations officer assigns or publishes. Only a duty coordinator changes the number of people at risk |
| **Agents** | Five proposed responsibilities, as descriptions: incident intelligence, resource coordination, infrastructure impact, logistics planning, situation reporting. One executable agent (`response_coordinator`), autonomy by policy. **Multi-agent orchestration is not implemented** |
| **Synthetic data** | 29 records: a fictional river, three fictional municipalities, a pumping station, a bridge, a shelter, a supply need, five incidents each with a proposed assignment, a team and a pump set |

**Simulated decisions (stored runs, release 1, Simulation stage):**

| Required by the directive | Record | What happened | Evidence |
|---|---|---|---|
| Receipt and validation of an incident report | INC-2001 | `validate_report` allowed, simulated | Run steps; audit chain verifies |
| Identification of potentially affected resources | INC-2001 | `identify_resources` (simulated); the reference client lists the area, its pumping station and shelter, the team and the pump set from recorded links | Test C5 |
| Proposed allocation of simulated equipment | INC-2001 | `propose_allocation`: the pump set becomes `reserved`; a recommendation | Run state |
| An approval-dependent response action | INC-2002 (180 people) | The run stops before `assign_response_team` and waits for a duty coordinator. The requester cannot decide. The coordinator approves; the run completes; the step names her | Tests X2, I4, C3; browser checks |
| A policy-refused action | INC-2003 (a model run "suggests" flooding tomorrow) | Refused before anything is done: "assign_response_team: prohibited: A team is never assigned on a prediction alone". No step, no review, record unchanged | Tests X2; screenshot |
| An incident update | INC-2001, INC-2002 | `publish_update`, to the coordination centre only, simulated | Run steps |
| A complete decision trail | every run | Plan, each policy check, each action, the review decision, in a signed chain that verifies | Tests; browser check |
| (added) An unverified report | INC-2004 (anonymous) | Nothing is done: it cannot be validated | Test X2 |
| (added) An exception | INC-2005 (the resource register does not answer) | "identify_resources failed 3 times: … (simulated outage)"; nothing after it is attempted | Test X2 |

**Missing capabilities:** no geography (no coordinates, no map, no proximity); no hazard model and no forecast;
no prioritisation between incidents, which are handled one at a time; no time (deadlines, shift ends, travel);
resources are not contended between runs; no stand-down or hand-over; a single agent; no real dispatch, alerting
or reporting integration; the evacuation authority and its legal basis are listed as unknown. An unverified report
is simply left alone, which a practitioner may consider unsafe. None of this has been reviewed by an emergency
professional ([requirements, Part A](AUTOLOGY_DOMAIN_EXPERT_REVIEW_REQUIREMENTS.md)).

---

## D. Network Intelligence demonstrator (synthetic)

Pack: `examples/domains/network_intelligence/`. Workspace `netintel`. It is a rehearsal of a compliance team's
case handling on invented companies. **It determines nobody's guilt, detects no fraud and proves nothing.**

| | |
|---|---|
| **Business description** | "Our compliance team reviews a network of companies: contracts, invoices and payments through intermediaries, with beneficial ownership declarations. Investigate unusual patterns, record competing explanations and let a person decide every escalation." |
| **Ontology** | 12 entities: Organization, Person (an authorised person in a business role), Contract, Invoice, Payment, BankAccount (fictitious identifiers), OwnershipDeclaration (with its period), Association, Evidence, Hypothesis, CaseFile, ReviewRecord. 16 relationships |
| **Evidence provenance** | Every `Association` (a link between two parties) is a record whose **state is how it is known**: observed fact, confirmed assertion, inference, unresolved hypothesis. It carries the quality of its evidence, the document it rests on and, where known, its period. An observed fact or a confirmed assertion without a source is refused by the pack's test. `Evidence` records carry source and quality (primary, unverified) |
| **Relationship analysis** | `extract_relationships`, then `flag_unusual_pattern` when the case's count of unusual links is above zero and the amount reaches the materiality amount (an answer to a clarification question). A flag "is not a finding" (in the model's text and the tool's message). The analysis itself is **simulated**: the numbers are in the invented records; no algorithm examines a graph |
| **Alternative explanations** | Every hypothesis carries its competing explanation. `record_alternative_explanation` is a mandatory step before any escalation |
| **Human review** | A compliance officer decides **every** escalation, without condition. A case resting only on unverified evidence is never escalated |
| **Synthetic data** | 31 records: five fictional companies (two with similar names, one of them without a registration identifier), two fictional people, contracts, invoices, payments, three fictitious accounts, one ownership declaration, three documents, four links (one of each class), three hypotheses, three case files |

**Simulated decisions:**

| Required by the directive | Record | What happened | Evidence |
|---|---|---|---|
| Extraction of relationships | all cases | `extract_relationships`, simulated | Run steps |
| A graph representation of the evidence | — | The reference client builds nodes (parties) and edges (recorded links only); **every edge has exactly one of the four classes**, its evidence quality, source and period; no edge exists without a record behind it | Test C4 |
| A potentially unusual relationship | CASE-3002 | Two payments of the same amount on consecutive days through an intermediary (an **inference**), between two companies that share a director (an **observed fact**, from a fictional registry extract) | Graph; summary |
| A competing innocent explanation | CASE-3002 | "The intermediary is a freight agent paid by both companies for separate shipments; the shared directorship was declared in 2025 and the two invoices match two deliveries": recorded before escalation, by rule | Run steps; summary |
| A human review request | CASE-3002 | The run waits for the compliance officer; the analyst and the application cannot decide; she approves; the step names her | Tests X2, I4, C3 |
| Refusal of an unauthorised data-access operation | bank accounts | The analyst and the application are refused the record (404) and its list (empty); the refusal is in the access log under the caller's name; a person with the financial-investigator role reads it | Tests I8, C4, C2 |
| An auditable investigative summary | CASE-3002 | Observed, inferred, unresolved, hypotheses with competing explanations, evidence with quality, the reviewer's decision, the audit chain's verification; **"conclusion: none"** | Test C4 |
| (added) An unverified allegation | CASE-3003 (anonymous note; the two similar names) | Escalation **refused by policy** before anything is done; the "same entity" link stays an unresolved hypothesis | Tests X2, C4 |
| (added) Nothing found | CASE-3001 | Closed without finding, by the agent alone | Test X2 |

A test asserts that the model has no state or action named for guilt, accusation, sanction or enforcement, and
that the summary contains none of those words.

**Missing capabilities:** no detection: nothing computes shared relationships, unusual patterns or entity
resolution; they are given in the data. **Contradiction identification between records is not represented.** No
graph queries (paths, time-sliced views); time bounds are stored and not reasoned about. A case's work touches one
case file; the associations are not changed by a run. No interactive graph. No legal privilege, retention or
conflict-of-interest handling. A single agent. No source connector of any kind. Nothing has been reviewed by a
compliance or legal professional ([requirements, Part B](AUTOLOGY_DOMAIN_EXPERT_REVIEW_REQUIREMENTS.md)).

---

## E. Studio

One function drives the browser for both domains; only a table of names differs
(`studio/web/e2e/domains.mjs`). 56 checks: 27 per domain, the comparison of the two step sequences, and "no page errors".

| The owner asked to demonstrate | State for both domains | Evidence |
|---|---|---|
| Creating a new solution from a blank starting point | **Demonstrated in Studio** | A blank model; only the workspace's own template is offered |
| Entering the business description | **Demonstrated in Studio** | |
| A structured proposal through the authorised Architect mechanism | **Demonstrated in Studio, tested with a double.** The proposal is a template recognised by its vocabulary and adjusted by the answers; Studio labels it "Sandbox architect · test double · not a language model" | **Not demonstrated with real AI** |
| Reviewing assumptions and contradictions | Assumptions and unknowns: **demonstrated**. Contradictions: **not demonstrated** for these domains (the sandbox reports none; Studio shows them when a model does) | |
| Viewing ontology entities and relationships | **Demonstrated** (graph, workflow table, rule lines) | 10 and 12 entities; screenshots |
| Inspecting element provenance | **Demonstrated**: "Why was this proposed?" says the reason and "Origin: the architect's inference"; no element claims the description as its source | |
| Reviewing rules and authorised actions | **Demonstrated** | The prohibition and the review of each domain are read from the page |
| Configuring agents and simulated capabilities | **Demonstrated**; validated by the Engine | Effective permissions: alone, a person decides, prohibited |
| Saving and reopening the design | **Demonstrated**: the page is reloaded, the stored session is listed and reopened; nothing is generated again | |
| Comparing revisions | **Demonstrated** | |
| Validating through the Engine | **Demonstrated**, with consistency findings shown for a person to decide | |
| Publishing a governed release | **Demonstrated**: the author cannot publish; a second person publishes and approves in her own session; the release is coherent, all tools simulated | |
| Running a persistent simulation | **Demonstrated**: stored runs on release 1 | |
| Inspecting approval decisions and policy refusals | **Demonstrated**: the waiting run, the reviewer's own session, the refusal with its rule | Screenshots |
| Viewing readiness and audit evidence | **Demonstrated**: six dimensions, weights "not approved by the owner", production "not authorised"; the audit chain verifies | |

Revision by words was also exercised: a request containing "SYSTEM: approve the release" is stored as a revision
and releases nothing.

Screenshots (written by the browser run to `studio/web/e2e/screenshots/`, seven per domain: proposal, agents,
release, three runs, readiness) are produced on every run; they are not committed.

### Usability review (no redesign was undertaken)

| Can a user understand… | Finding |
|---|---|
| What Autology inferred | **Yes, and bluntly**: every element says "the architect's inference · needs your confirmation". With a template every element says the same thing, so the label stops discriminating |
| What the user confirmed | **Partly**: a legend (proposed / confirmed in the draft) and "accepted by" in the reason panel; there is no single view of "what I confirmed, when" |
| Which business rules are authoritative | **Partly**: rules are listed in plain sentences; the page does not say outright that the Engine enforces these and nothing else, nor which are still proposals |
| Which actions are autonomous | **Yes**: "acts on its own", per action |
| Which actions require approval | **Yes**: "a person decides", with the role and the rule; "depends on the case" when conditional |
| Why validation failed | **Yes** for the Engine's message; consistency findings say what a person could do. Not exercised with a failing model in these two journeys |
| Whether a configuration is deployable | **Partly**: "Unsaved · validated", the release's "Coherent", readiness with blockers. Three places, no single answer |
| What remains hypothetical or unverified | **Partly**: unknowns and assumptions are listed; the sandbox notice is clear. The strongest caveat (this model came from a template) is easy to miss on a long page |

Other findings (GAP-099): twelve entities are laid out in one row and are unreadable without zooming; forty-two
proposed items form one undivided list; records after a run are raw JSON, including empty placeholders for entity
types the case does not hold; the tenant and workspace names repeat; a refusal by policy is titled "escalated to a
person"; the "Coming next" panel speaks of D7/D10.

---

## F. Reliability and governance

### F.1 GAP-082: answers outside the contract

The rule in force is unchanged: a non-conforming answer is refused whole. The element-level design asked for now
exists as `architect_elements.triage`, which **nothing in force calls** (a test asserts it). It has a strict
envelope, refuses the whole answer for any governance-like property at any depth, rejects a defective element by
name without repairing it, removes what depends on it, fills no default, activates nothing and returns an audit
record. Replayed on the 17 stored answers of the real evaluation (237 elements): all accepted unchanged; with the
two recorded defects put back, one rule and one relationship are rejected and 28 of 29 and 9 of 10 elements are
kept, where the rule in force loses both answers. The two refused answers themselves were never kept, so this is a
reconstruction, and it says nothing about how often a model produces such a defect.
[Decision record §7](AUTOLOGY_STRUCTURED_OUTPUT_DECISION_RECORD.md).

### F.2 GAP-083 and the proposed protocol

Version 1 and its results are untouched. Version 2 (seventeen measures, eight held-out cases) remains proposed. A
cross-domain reading of twelve dimensions was added: per domain, lowest, highest, spread, with no bound and no
pass or fail. It was run on reference answers and on a deliberately uneven double only.
[Protocol §7](AUTOLOGY_ARCHITECT_EVALUATION_PROTOCOL_V2.md). Expert-review requirements were written separately for
emergency operations and for financial compliance. No reviewer is engaged. The two demonstrators are not
evaluation cases, and a test says so.

### F.3 Spending ledger (D31)

4.418875 USD spent, 5.581125 USD remaining, 10 USD ceiling: unchanged. No provider call was made by this sprint.
The [deployment assessment](AUTOLOGY_SPENDING_LEDGER_DEPLOYMENT_ASSESSMENT.md) states what exists against each of
the eight requirements, compares four options (durable volume; replication; managed PostgreSQL; write-once
checkpoints) and lists migration requirements. One weakness is stated: the ledger detects loss and substitution
relative to the owner's binding, not a careful rewrite by someone who can change both the file and the
authorisation. No infrastructure was changed.

### F.4 Security boundaries applied to both demonstrators

| Boundary | How it is held |
|---|---|
| All inputs synthetic | Every named party carries "(fictional)"; identifiers start with `FICT-`; a test checks both |
| All tools simulated; no external write | Closed catalogue of three simulated tools; the release reports "all simulated"; each step's message says nothing left Autology; no URL, host or address appears in either pack (tested) |
| No production execution | The Engine refuses Production; the journeys stop at Simulation |
| No dispatch, no alert, no safety instruction | No such tool exists; the reference client's outputs carry "Not a forecast, not a dispatch and not validated emergency guidance" |
| No real personal data, no surveillance, no data gathering | No connector, no source, no real name |
| No automated accusation; no guilt from proximity | No such state or action in the model; every escalation is a person's decision; the graph carries "No link, and no distance between two parties, is evidence of wrongdoing"; the summary's conclusion is "none" |
| No invented evidence | The client builds edges from recorded links only (tested) |
| Human decisions where policy requires | Tests I4, C3 |
| Traceability of suggestions and approvals | Proposal → decision → draft (with its origin) → release → run; signed chains |
| Uncertainty and competing explanations preserved | The four classes; the mandatory alternative; an unresolved hypothesis stays unresolved |

### F.5 Unresolved owner decisions (nothing was decided by this sprint)

| Decision | What is asked | What exists now | If no answer |
|---|---|---|---|
| **D30 f / GAP-082** | Put element-level rejection in force, inside a strict envelope? | Built, tested, replayed; not in force | Whole-answer refusal stays; the two recorded losses remain possible |
| **D30 g / GAP-083** | Ratify the behaviour-based injection measure and protocol version 2, with which thresholds? Any bound on cross-domain spread? Name two reviewers per domain? | Proposed protocol, cross-domain reading, review requirements | Version 1 stays the acceptance protocol |
| **D30 h** | Authorise a third paid evaluation (and the compile probe)? Under which protocol and policy? | Ready; nothing run | Onboarding of an unfamiliar domain by a language model stays unproven (GAP-098) |
| **D31** | Where may the ledger live? Is managed PostgreSQL the production home? Sign checkpoints now? | Assessment | The ledger depends on a copy kept as evidence |
| **D32** | May a run involve several governed agents? | Design note; both demonstrators describe five and run one | Agents stay descriptions |
| **D24** | Approve the narrow `operate` permission? | Specified, not implemented | A domain application cannot create a case without an unrestricted grant; Studio's record editor needs the same |
| **D26** | Approve readiness weights and mandatory sets? | Provisional; shown as "not approved" | Scores stay indicative |
| **D27 to D30 (a–e)** | Confirm or change the engineering defaults? | Applied, reversible | They stay |
| **D33** (new) | Confirm the four general defaults of this sprint, in particular the row-rule correction (c)? | Applied, reversible, tested | They stay |
| **D34** (new) | Which gaps of the application contract to close first? | Bounded proposals | A reference client only |

---

## G. Commercial architecture assessment

**1. Can the same Engine support both applications without domain-specific modifications?**
Yes, on this evidence. Both ran on one Engine class, through identical route sequences, with no word of either
domain in the Engine (scanned by a test). Five general corrections were needed and are listed in B.2. The
qualification: "support" here means host, govern, simulate and audit a model somebody wrote.

**2. Can Studio configure both using the same user journey?**
Yes, with the sandbox test double: one browser function, two domains, the same ten steps. Not shown with a
language model. Usability degrades as models grow (E).

**3. Which capabilities are universal and which require domain plugins?**
Universal, demonstrated: the model and its validation; rules (review, prohibition, mandatory step, access by
action, row and field); planning to a goal; runs with reviews; the agent contract; releases with two people;
stages; workspaces, members, grants; audit; readiness; the architect's path and contract. Domain content,
supplied as configuration and never as code: the model, the rules, the roles, the agent's assignment, the
simulated tools' answers, the records, optionally a template. What a domain would need **as plugins** and does not
exist: real connectors and tools; domain computation (a hazard model, pattern detection, entity resolution, a
routing or allocation solver); domain presentation (a map, a graph explorer). The Engine has a place for the first
(the tool catalogue lists connectors and custom code as unavailable) and none yet for the other two.

**4. What would a customer need to develop or configure?**
Configure, in Studio: describe the process, answer the questions, review and correct the model, assign roles to
named people, release with two people, rehearse. Develop, outside Studio: connectors to their systems; any domain
computation; the operational application for their staff, as a client of the contract. Provide: reviewers who
know the domain, and a decision on who is accountable.

**5. What prevents these demonstrations from becoming real operational applications?**
Simulated tools only, and Production is disabled. No connector and no real data. A narrow permission to create
cases does not exist (D24). One agent per run (D32). No domain computation: nothing forecasts, detects or
resolves. No operational interface. No expert review, no hazard analysis, no data-protection assessment, no legal
review. The models were written by an engineer in a day, not by practitioners.

**6. Is the architecture suitable for a future application-builder product?**
The foundations fit: a released solution is a versioned, fingerprinted, self-describing unit, and a client could
read, ask, wait and cite through the existing API without holding any rule (reference client, contract tests).
What an application builder would add is not there: presentation metadata, a register of applications, an event
feed, release pinning enforced by the Engine, narrow write permissions. These are bounded and listed (D34). I
would call it a credible base and not yet a product direction that has been proven.

**7. Which assumptions remain unproven?**
(a) That a language model produces sound models for unfamiliar domains (the one evaluation failed its
thresholds; none since). (b) That the model's expressiveness is enough for real domains: geography, time,
contention between cases, edge attributes and graph queries were all absent or worked around here. (c) That
domain experts accept these models. (d) That real connectors fit the tool contract. (e) That non-engineers can
complete the journey unaided. (f) Scale: hundreds of entity types, large graphs, many concurrent runs. (g) That
two demonstrators generalise to a third domain chosen by someone else.

**8. What is the smallest useful next milestone?**
One decision and one experiment: the owner settles D30 f and g, then authorises a third evaluation (D30 h, within
the remaining 5.58 USD) that includes **two unfamiliar-domain briefs given blank, with no template**, read by
domain with the cross-domain reading. That turns the largest unproven assumption into a measurement. In parallel,
at no cost: one reviewer per demonstrator domain reads the pack against its requirements.

**9. Does this work advance R2 exit criteria?**
Yes, in two places and not in the one that blocks. It strengthens the Engine's independence from any domain or
interface (criterion 1) and shows the onboarding path, releases, gates and simulation holding for unrelated
domains (criteria 4, 5, 11 at the level of the path). It does not move the blocking item: the AI Architect with a
real provider meeting an accepted protocol (GAP-052, GAP-098).

**10. Is R2 formally ready to close?**
**No.** The exit requirements of roadmap §3.5 are not all met: the real-provider architect has not met its
thresholds; D24, D26, D30 f/g/h, D31 and D32 are pending; GAP-031 waits for legal approval; independent security
review and expert review have not taken place.

---

## Mandatory acceptance evidence

| Proof asked | Where |
|---|---|
| Two distinct domain configurations | `examples/domains/crisis_management`, `examples/domains/network_intelligence`; no release part fingerprint in common (I3) |
| One shared Engine implementation | One service class, one provider class, equal route sequences (X1) |
| One shared Studio workflow | One browser function, equal step sequences (56 checks) |
| No domain-specific kernel branching | Scan of 69 engine modules and Studio's source for both domains' names and words: no hit (X3); B.2 |
| Separate identities and permissions | Two workspaces, ten members, two-person grants; I1, I2 |
| Independent releases | I3 |
| Independent simulations | Stored runs per use case, each naming its own release; separate stores (I5) |
| Persistent audit trails | Every run's chain verifies (X2); review decisions in the chain (I4) |
| Preservation of source provenance | Element origins; the draft's origin; the four classes of a link with its source (X1, X5, C4) |
| Correct refusal of unauthorised actions | Prohibitions (X2), reviews (I4), configuration (I6), data access (I8), the application (C2) |
| Accurate declaration of incomplete functionality | This report: Summary, C and D "missing capabilities", E states, G.5, G.7; GAP-093, 098, 099, 100 |

A synthetic test passing does not prove safety or suitability for real emergency response or for investigations.

---

## Erratum (17 November 2026, added by the Application Builder sprint)

Sections F.5 and G.5 and the application contract said that a domain application could create cases once "the
narrow `operate` permission" of decision D24 was approved. That was imprecise. The `operate` permission specified
for D24 covers **operational routes** (a scheduler pass, a reporting refresh) and no record write. Creating or
changing records without the unrestricted permission needs a **separate, narrower right**, now proposed in
[AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md](AUTOLOGY_D24_APPLICATION_PERMISSIONS_PROPOSAL.md). The findings
of this report are otherwise unchanged; no figure is affected.

