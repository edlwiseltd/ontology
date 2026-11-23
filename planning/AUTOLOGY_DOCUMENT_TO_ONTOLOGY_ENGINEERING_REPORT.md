# Autology — document intelligence and evidence-backed ontology generation: engineering report

*23 November 2026. A research spike. **Nothing in force changed**: the new module is called by nothing in the
Engine, the API or Studio. No provider was called, no credential read, the spending ledger not opened, nothing
deployed, no reviewer contacted. All documents and labels are synthetic. **R2 is not closed.***

## In one page

| Question | Answer |
|---|---|
| Did Autology already have part of this? | **Yes.** The proposal contract already takes passages and checks paragraph citations; only the API route never passes any (GAP-115). Stated/inferred review, aliases and Turtle export already exist |
| What was built? | `autology/docintel.py`: anchored sources, an offline English/French extractor, normalisation with merges a person decides, a non-authoritative evidence graph, and a mapping that goes through the architect's own validation. A benchmark and 11 tests |
| Does it read documents well? | On four short synthetic documents, at candidate level: entity recall 6/7 to 10/10, relation recall 4/5 to 9/10, rules 3/3 in every case, every relation cited the right paragraph. On the held-out document: entities 8/9, relations 6/7 |
| Does it give usable models? | **Not by itself.** The Engine accepts 3 to 5 of 14 to 19 proposed elements per document, because the loader requires a state on every entity and documents rarely list them. With one state per entity (illustrative, no person) every element passes |
| Is it better than the current offline path? | The current offline path (template test double) does not read documents: it matched a wrong template on two documents and nothing on the other two (0 to 1 matching entities). The spike matches 1 to 2 entities at proposal level and 6 to 10 at candidate level, and every accepted element cites its paragraph |
| Semantic quality? | **Not assessed.** No independent expert reviewed anything. The labels were written by the team that wrote the extractor |
| KerML? | The official specification could not be read; no claim is verified. Mapping assessment only; no adapter |
| Recommendation | **Revise**: keep paragraph-level evidence and the review of candidates; do not integrate the pattern extractor as the producer of models |

---

## 1. Baseline and engineering evidence

| Item | Value |
|---|---|
| Starting point | `bf6ab9a` = remote; [CI run 135](https://github.com/edlwiseltd/ontology/actions/runs/44893009144) success |
| Final code commit | `b1c4bb2` |
| CI on it | [run 136](https://github.com/edlwiseltd/ontology/actions/runs/45233166452): **success**, five jobs (quality, tests on Python 3.10 and 3.13 with PostgreSQL, package, Studio) |

| Check (23 November, this session's container, outside network denied for the test processes) | Result |
|---|---|
| Full Python suite | **1,176 passed** (11 new), 2 skipped (PostgreSQL; run in CI), coverage 96.15 % (gate 95 %); `docintel.py` 95 % |
| New spike tests | `tests/test_docint1_document_intelligence.py`: 11 pass |
| ruff; mypy ratchet | Clean; 198 (= baseline, not raised) |
| Studio | Unchanged by the spike. Browser suites re-run: **135/135, 76/76, 108/108** (three domains: Crisis Management, Network Intelligence, Venue Booking) |
| API contract | Unchanged (no route added) |
| PostgreSQL tests | Two skipped locally (no server); run in CI |

Baseline details, the KerML claims audit and the gap map:
`planning/AUTOLOGY_KERML_NER_FEASIBILITY_AND_BASELINE.md`.

## 2. What was built

| Part | Where | State |
|---|---|---|
| Contract `docintel-1` | `docs/document-intelligence-contract.md` | Written |
| Sources and anchors | `docintel.read_source` | Prototype, tested |
| Offline extractor (English, French) | `docintel.extract` | Prototype, tested |
| Normalisation and evidence graph | `docintel.graph`, `docintel.redact` | Prototype, tested |
| Mapping into a proposal | `docintel.to_answer`, `docintel.propose` → `architect.propose` | Prototype, tested |
| Benchmark | `deploy/make_docintel_benchmark.py`; `planning/evidence/document-ontology-spike/` | Run; a test compares the kept results with a fresh run |
| Storage of documents, API route, Studio evidence panel | — | **Not built**: decisions DI-2, DI-3 |
| Provider-backed extraction | — | **Not built and not connected**: decision DI-5 |
| KerML adapter | — | **Not built**: assessment only |

## 3. Measured results (`results/benchmark.txt`)

### 3.1 Extraction, against engineer-written labels

| Case | Lang | Entities P | Entities R | Relations P | Relations R | Type right | Reversed | States exact | Rules | Roles R | Refs | Merges right/wrong/missed | Right anchor | Skipped |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `pump-cell` | en | 10/10 | 10/10 | 9/9 | 9/10 | 9/9 | 0 | 1/3 | 3/3 | 3/3 | 2/2 | 1/0/0 | 9/9 | 2 |
| `reclamations` | fr | 6/9 | 6/7 | 4/7 | 4/5 | 4/4 | 0 | 2/2 | 3/3 | 3/3 | 1/1 | 0/2/0 | 4/4 | 0 |
| `garden-plots` | en | 7/9 | 7/8 | 5/5 | 5/7 | 5/5 | 0 | 2/2 | 3/3 | 3/3 | — | 0/0/1 | 5/5 | 0 |
| **`clinic-bookings` (held out)** | en | 8/9 | 8/9 | 6/7 | 6/7 | 6/6 | 0 | 2/3 | 3/3 | 3/5 | 1/1 | 1/0/0 | 6/6 | 0 |

The two skipped paragraphs of `pump-cell` are the duplicated one and the instruction addressed to a program. The two
wrong merges of `reclamations` were only proposed ("dossier de réclamation" and "réclamation"; "client" and
"échanges avec le client"); none was applied without a person.

**Per-case failures:** `pump-cell` missed the states of the work order ("in progress" is two words) and of the
report ("passes through" is not a state pattern), and the test bench's relation. `reclamations` took the role
"chargé de clientèle" for a thing (it is also a role: kept as an ambiguity), read "décision" and "échanges avec le
client" as parts of the file, and missed "facture". `garden-plots` missed "is divided into" (a composition) and the
merge "plot holder = member" (stated as a definition at the end). `clinic-bookings` missed "examination", the
relation from owner to animals ("responsible for"), the invoice's states (only a transition is stated), two roles
("front desk", "receptionist": "confirms" is not in the verb list), and read "estimated cost" as a part of the plan.

**Read these numbers with their bias:** four short documents written by the same team as the extractor and the
labels, three of them used to fix reading bugs. The held-out document is one case. The figures say the approach can
work on clean prose; they do not predict real specifications.

### 3.2 Ontology proposals (what the Engine accepts)

| Case | Baseline accepted / proposed | Baseline entities matching | Baseline citing a paragraph | Candidate accepted / proposed | Candidate entities matching | Candidate citing a paragraph | Questions | Unmapped findings | With one state per entity (illustrative) |
|---|---|---|---|---|---|---|---|---|---|
| `pump-cell` | 12/12 | 1/10 | 0/12 | 3/19 | 1/10 | 3/3 | 9 | 8 | 19/19 |
| `reclamations` | 0/0 | 0/7 | — | 5/18 | 2/7 | 5/5 | 10 | 5 | 18/18 |
| `garden-plots` | 0/0 | 0/8 | — | 4/14 | 2/8 | 4/4 | 6 | 6 | 14/14 |
| `clinic-bookings` | 18/18 | 0/9 | 0/18 | 3/16 | 2/9 | 3/3 | 8 | 6 | 16/16 |

The baseline's accepted elements on `pump-cell` and `clinic-bookings` come from templates that matched two words of
the text; they describe other businesses. The candidate's refusals are all the loader's words "must declare at
least one state", and the relationships and actions that depend on those entities (GAP-117).

### 3.3 Builder and Engine (the existing chain harness)

| Treatment | Elements in the draft | Manifest | Engine | Simulation |
|---|---|---|---|---|
| Candidate, no confirmation (fail-closed default) | 0 in every case | Valid, 1 screen | Accepts an empty model | Not runnable: no goal |
| Candidate, all confirmed (**counterfactual**) | 3 to 5 | Valid, deterministic, 4 to 9 screens | Accepts | Not runnable: no goal |
| Candidate, one state per entity, all confirmed (**illustrative; no person**) | 14 to 19 | Valid, deterministic, 30 to 36 screens | Accepts | Not runnable: no goal |

No document states a goal in a form the extractor reads, and the spike invents none. So authorised, refused and
approval-dependent workflow behaviour could **not** be measured from these documents: approval rules are reported as
safety findings for a person, never made enforceable by extraction.

## 4. The fourteen explicit answers

| # | Question | Answer and evidence |
|---|---|---|
| 1 | Did the stack already contain some of this? | Yes: passage citations in the proposal contract (`architect.propose`, `canonical`), stated/inferred review and its gate, aliases, Turtle export. Missing: document reading, extraction, normalisation, and a route that passes passages (GAP-115) |
| 2 | Which KerML claims were verified? | None: the OMG specification could not be reached. All are listed as unverified in the baseline document; none was used as a requirement or a threshold |
| 3 | Is the evidence graph a second ontology authority? | No: `authoritative` is always false, nothing in force imports the module (tested), and everything it proposes goes through the existing architect validation and review |
| 4 | Per-case metrics | §3.1 and `results/benchmark.json` |
| 5 | Did it improve independently assessed semantic quality? | **No independent review occurred.** Only technical acceptance and agreement with engineer-written labels were measured |
| 6 | Stated, inferred, normalised, accepted, rejected, with what evidence? | In the graph per candidate (`basis`, `method`, `evidence` with paragraph, span and quote); merges with decision; skipped paragraphs with reason. In the proposal every element is inferred by default and cites its paragraph. No person accepted or rejected anything in this spike |
| 7 | Does the Engine still refuse unconfirmed inferred elements at every draft writer? | Yes, unchanged; and an extracted element is refused by the same classification until confirmed (`test_the_provenance_gate_holds_for_extracted_elements`) |
| 8 | Deterministic applications from accepted models? | Yes: manifests valid and deterministic in every treatment (§3.3). Workflow behaviour not measurable: no goals |
| 9 | Three-domain Application Builder regression? | 108/108 application checks; 135/135 and 76/76 for Studio and the cross-domain journeys |
| 10 | Decisions needed before activation | DI-1 to DI-6; and for any provider use D7/D10 and D30 h. D24, D34, D35 unaffected |
| 11 | Active, prototype, proposed | Active: nothing new. Prototype: `autology/docintel.py`, the benchmark. Proposed: storage, API, Studio panel, provider extraction, KerML adapter |
| 12 | CI on the final code | `b1c4bb2`, [run 136](https://github.com/edlwiseltd/ontology/actions/runs/45233166452): success |
| 13 | Go / revise / no-go | **Revise** (below) |
| 14 | Is R2 closed? | **No** |

## 5. Recommendation: revise

**Keep:** anchored sources with content hashes; paragraph-level citations on every proposed element (they exist in
the contract and are unused); candidates with their evidence and a person's decision on merges; the fail-closed
default; "unmapped" findings instead of improvised types; approval and access rules always left to a person.

**Do not integrate as is:** the pattern extractor. It reads clean, simple sentences well and misses ordinary
phrasings ("is divided into", "responsible for", "confirms"); it was tuned on three of the four documents by the
team that labelled them. As a producer of models it would put a heavy review load on people for little gain.

**Next step, in order:**
1. Let the proposal route take document passages (DI-3, DI-4): this alone gives every model-made proposal
   paragraph-level citations (closes GAP-115 and the cause of GAP-111/113).
2. Use the extractor as a **checker** beside a model's proposal, not as its producer: flag model elements that cite
   nothing, candidates the model left out, and merges to decide.
3. Ask the reviewer for states and goals explicitly; consider whether the model should allow a default state
   (GAP-117), which is a modelling decision.
4. Measure against a model only under an explicit authorisation (D7/D10, D30 h), on documents not written by the
   team, with an independent reviewer.

## 6. Security boundaries kept

Documents are data: instruction-like text is flagged and not read; links are never followed; binary content and
oversized documents are refused; sources of different workspaces are never read together; excerpts are withheld
from callers who may not read their source (`redact`); the module imports nothing that reaches the network, the
environment or the ledger (tested). Nothing extracted becomes a permission, a rule in force, a grant or a release.
