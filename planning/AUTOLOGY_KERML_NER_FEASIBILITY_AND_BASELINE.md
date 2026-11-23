# Autology — KerML-informed document intelligence: baseline, claims audit and gap map

*23 November 2026. Increment 0 of the document-to-ontology spike. Facts observed today are marked as such; the
directive's historical figures were checked, not assumed.*

## 1. Repository baseline (observed 23 November)

| Item | Observed |
|---|---|
| Branch, head | `claude/autology-ontology-agent-4ajjer`, `bf6ab9a`, equal to the remote; clean working tree |
| Latest CI | [Run 135](https://github.com/edlwiseltd/ontology/actions/runs/44893009144) on `bf6ab9a`: success. (The directive cites run 127 on `334b3e5`; later commits and runs exist: 128 to 135, all success) |
| Store schema | 22 |
| Decisions | D24 not approved; D30 f inactive, g proposed, h not authorised; D31 to D37 pending; nothing recorded since 20 November |

## 2. KerML claims of the video summary: verification status

The official OMG specification **could not be reached** from the engineering environment (the request to
`omg.org` was refused by the network; the public GitHub release repository answered 403). No normative text was
read, so **no claim below is verified**, and none is used as a design requirement or a test truth.

| Claim (from the user-supplied summary) | Status |
|---|---|
| KerML is an OMG standard, "formal/2025-09-01", the kernel language of SysML v2 | Unverified here |
| A three-layer metamodel: Root, Core, Kernel, with the constructs listed for each | Unverified here |
| Four conformance levels (abstract syntax, concrete syntax, model interchange in XMI 2.5.1, semantic) | Unverified here |
| The Kernel Model Library's three parts (data types, functions, semantic library) | Unverified here |
| `Relationship` has the highest connection density; `Succession Union` and `Metadata` have no outgoing edge | Claims about one demonstration graph; unverifiable without it |
| 183 nodes, 287 edges, 3 layers, 17 entity types from the v1.0 specification | The video's result; not reproduced; **not used as a threshold** (graph size is not quality) |
| The reference "ISO 19019" | Unverified, and not recognised by engineering as a standard referenced by KerML; to check against the text |

## 3. What Autology already had (question 1)

| Capability | Already there | Where |
|---|---|---|
| Passage-level citation in proposals | **Yes, in the contract**: `architect.propose(…, sources=[{id, text}])` takes up to 20 passages; an element may cite a passage id; citations are checked against what was given | `autology/architect.py` (`canonical`, `origin_of`, `_items`) |
| … through the API and Studio | **No**: the proposal route accepts a brief, answers and feedback, never passages | `autology/architecting.py` |
| Stated / inferred, with refusal of unconfirmed inferences | Yes, element by element, append-only, gated at every draft writer | `proposal_review`, GAP-107 |
| Synonyms | Yes: entity `aliases` in the model (one vocabulary for several teams' words) | `autology/ontology.py` |
| Turtle (RDF) export of a model and of a graph | Yes | `autology/export.py` (`to_turtle`, `graph_to_turtle`) |
| Data ingestion | Yes, for **records** from files and databases (pipelines, lineage); not for documents | `autology/ingest.py`, `ingestion.py` |
| Document reading, entity extraction from text, normalisation of mentions | **No** | — |

## 4. Gap map

| Current pipeline | Missing capability | Minimal extension point | Validation evidence |
|---|---|---|---|
| A brief of up to 4,000 characters | Long documents, located paragraphs | `docintel.read_source`: anchors with section, span, hash, flags | `test_a_source_is_read_as_located_content_addressed_anchors` |
| The model answers from the brief | A deterministic reading to measure against and to give candidates with evidence | `docintel.extract` (offline patterns), behind the same gateway as any answer | Benchmark, per case |
| Names as the model writes them | Grouping of written forms; proposed merges a person decides | `docintel.graph` with decisions | `test_merges_are_proposed_with_a_reason_and_applied_only_by_a_person` |
| Passages exist in the contract, unused | Citations of paragraphs on every element | `docintel.passages` + `architect.propose(sources=…)` | 100 % of accepted candidate elements cite a paragraph, in every case |
| — | Evidence beside an element in Studio; storing documents with access control | Not built: owner decisions DI-2, DI-3 | — |
| — | KerML import or export | Not built; assessment only | `AUTOLOGY_KERML_INTEROPERABILITY_MAPPING.md` |

## 5. Architectural decision of the spike

A separate, non-authoritative module that ends where the existing proposal path begins. No new acceptance rule, no
graph database, no KerML runtime, no RDF store. The Engine stays the only authority; the spike is called by nothing
in force.
