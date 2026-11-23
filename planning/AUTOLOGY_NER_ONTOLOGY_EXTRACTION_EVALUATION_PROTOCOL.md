# Autology — document-to-ontology extraction: evaluation protocol `docintel-benchmark-1`

*23 November 2026. A protocol for the research spike only. It is separate from the AI evaluation protocol V1 (in
force) and from the proposed V2 (D30 g), and it changes neither. It uses none of the reserved held-out briefs
(`museum-loans`, `harbour-pilotage`).*

## 1. Cases

Four synthetic documents, written for the spike, mutually unrelated, kept in
`planning/evidence/document-ontology-spike/cases/`:

| Case | Language | Kind | Set |
|---|---|---|---|
| `pump-cell` | English | Industrial technical specification (assembly, inspection, release) | Tuning |
| `reclamations` | French | Process / workflow procedure (customer complaints) | Tuning |
| `garden-plots` | English | Non-industrial domain (allocation rules of a community garden) | Tuning |
| `clinic-bookings` | English | Non-industrial domain (appointments and treatment) | **Held out for this spike** |

Each document carries deliberate difficulties: plurals and acronyms, a duplicated paragraph, a table, a word cut at
a line end, an instruction addressed to a program, compound names, a role that reads like a thing, terms that look
alike but differ, a state list in an unusual form, an attribute listed beside entities.

**Order of work, recorded:** the three tuning documents and their labels were written first; the extractor was run
once (`results/first-run-before-fixes.json`); the fourth document and its labels were written and frozen **before**
any change to the extractor; generic reading bugs were then fixed on the tuning documents only (French articles,
noun-phrase boundaries, clauses joined by "and", quantifiers, the subject of an approval); the extractor was frozen
and run on the held-out document for the first time. Later changes touched only merge application and the
mapping's defaults, and a check showed the benchmark output unchanged by them.

## 2. Reference labels

One `*.labels.json` per case: entities (with aliases and the sentence that states each), relations (endpoints,
direction, type: composition, association or specialisation), state lists, rules (approval, access, prohibition,
with role), roles, references, expected merges and look-alikes that must not merge. **They were written by the
engineering team with the documents; they are synthetic labels, not an independent expert's judgment.** The same
team wrote the extractor, which favours it.

## 3. Pipelines compared

| | Baseline | Candidate |
|---|---|---|
| What | The existing offline proposal path: the sandbox architect (template test double) behind the same gateway | `autology.docintel`: sources, candidates, graph, mapping, then the same `architect.propose` |
| Input | The document's text as the brief (first 4,000 characters) | The same brief, plus the anchored paragraphs as sources |
| Not compared | A real model behind the architect: **not run**, no provider call is authorised | — |

## 4. Measures, reported apart (no total)

| Component | Measure |
|---|---|
| Extraction | Entity precision and recall; relation precision and recall; relation type correct; direction reversed; state lists exact; rules found (a rule's subject counts when one contains the other); role precision and recall; references found; merges proposed right and wrong, missed, and applied without a person (must be 0); relation anchors that contain the stating sentence; quotes inside their anchor; paragraphs flagged and skipped; ambiguities left for review |
| Ontology / architect | Elements proposed and accepted by the Engine; the Engine's refusals in its words; entities matching the reference; elements citing a paragraph; elements citing only the brief; inferred elements needing confirmation; questions; draft validity with no confirmation and, as a labelled counterfactual, with everything confirmed |
| Builder and Engine | The existing chain harness: elements in the draft, manifest valid and deterministic, screens, draft accepted, simulation, for: no confirmation; all confirmed (counterfactual); and an illustrative run in which each stateless entity is given one state as if a person had answered (no person did) |

Schema acceptance, semantic correctness and renderability are different claims. The protocol measures the first
and the third; nobody qualified measured the second.

## 5. Reproduction

    python deploy/make_docintel_benchmark.py

writes `results/benchmark.json` and `.txt`. A test compares the kept file with a fresh run
(`tests/test_docint1_document_intelligence.py::BoundaryTests::test_the_kept_benchmark_is_what_the_benchmark_gives`).
No network is needed; the results were produced with outside network denied.

## 6. Limits

Four short documents, written by the same team as the extractor and the labels; one held-out case; synthetic
labels; no independent semantic review; no real-model comparison; plain text only.
