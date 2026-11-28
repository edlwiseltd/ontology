# Document intelligence: contract `docintel-1`

*Status: **research spike, not in force.** Implemented in `autology/docintel.py`; nothing in the Engine, the API or
Studio calls it (a test checks that no other module of `autology/` names it). No document is stored, no route
exists, and no provider is involved. This page is the contract the spike implements and measures.*

## 1. Four layers, never confused

| Layer | What it is | Authority |
|---|---|---|
| **Source** | A document's text cut into anchored paragraphs | None: a reading of a file |
| **Candidate** | A concept, relation, state list, transition, rule, action, value or reference read from a paragraph | None: `requires_review` is always true |
| **Evidence graph** | Candidates grouped by normalised name, with proposed merges, ambiguities and skipped paragraphs | None: `authoritative` is always false |
| **Proposal** | What the current model contract can hold, in the form of `architect.SCHEMA`, validated by `architect.propose` | The existing proposal lifecycle: provisional until a person decides; a draft and a release follow the existing gates |

A graph about a standard (its constructs and references), a domain ontology for a business, and the governed
operational model the Engine runs are three different things. The spike produces the first two kinds of candidate
and hands the Engine a proposal; it never writes the third.

## 2. Source

`read_source(text, source_id, *, workspace, title, source_type, version, use_case, access, ingested_at, ingestion)`

| Field | Content |
|---|---|
| `id`, `title`, `type`, `version` | As given |
| `workspace`, `use_case`, `access` | Scope and classification (`public`, `internal`, `restricted`). A source belongs to one workspace |
| `content_sha256`, `characters`, `language` | Of the normalised text; language `en`, `fr` or `unknown` (stop-word counts) |
| `ingestion` | Method, time, tool and contract version |
| `quality` | Document-level notes, e.g. "words cut at a line end were joined" |
| `anchors[]` | One per paragraph or list item: `id` (source id `#` hash of the paragraph's text), `section`, `paragraph` (position), `span` (character offsets in the normalised text), `language`, `flags`, `text` |
| `limits` | What the reading cannot do (plain text only; no page numbers unless the text has them) |

An anchor's identifier is derived from its text, so inserting a paragraph elsewhere does not move it. A repeated
paragraph gets its own identifier and the flag `duplicate of …`.

**Refused before anything is read:** text with binary content (a PDF must be turned into text first), more than
200,000 characters or 2,000 paragraphs, a source id outside `[A-Za-z0-9._-]`, no workspace, an unknown access class.

**Flags, never silent repairs:** duplicate paragraph; table-like text (columns may be mis-read); a link (kept as
text, **never followed**); text that reads like an instruction to a program (English and French phrasings): kept as
data and **not extracted from**; very short paragraph.

## 3. Candidates

`extract(sources)` reads every anchor that is neither flagged as an instruction nor a duplicate, sentence by
sentence and clause by clause, with generic English and French patterns: definition, specialisation ("is a kind
of"), composition ("consists of", "comprend"), association with cardinality ("has one or more", "possède un ou
plusieurs"), state lists, transitions, approvals ("must be approved by"), access ("only the X may"), prohibitions
("must never"), actions (a closed list of generic workflow verbs), values with units (kept as written), references
to standards, acronyms. The patterns hold no business vocabulary.

Every candidate carries: `kind`, the written `label`, the `method` (pattern and language), `basis`, and
`evidence[]` with the anchor, the span within the paragraph and the quoted text.

| Basis in the graph | Meaning | In a proposal (default) |
|---|---|---|
| `stated` | A sentence pattern read it from the text | `inferred`, citing the paragraph (fail-closed, see §5) |
| `inferred` | Read from context (a role read from the subject of a workflow verb) | `inferred` |
| `derived` | One concept from several written forms, grouped by the normaliser | `inferred` |
| `person` | A person's decision (a merge accepted or rejected) | Recorded on the graph; the proposal's own decision history is the existing one |
| `unsupported` | Nothing in the text supports it | Not produced by the extractor; such elements come only from a model, and the architect already marks them |

No confidence number is given: there is no calibrated estimator, so `confidence` is `null` with the reason. The
proposal contract requires a number; the mapping writes 0.5 there and says in the rationale which pattern read it.

## 4. Evidence graph and normalisation

`graph(extracted, decisions)` groups mentions by a normalised key (case, accents, simple plurals). Grouping by an
identical key is done, and the node says so (`basis: derived` when several written forms meet). Everything less
certain is **proposed**: an acronym and its long form, two names that differ by one letter or of which one contains
the other. Each merge has an identifier, its members, the reason and the evidence. A merge is applied only when
`decisions[merge_id] == "accept"`; members of different kinds (a role and a concept) are never merged; sources of
different workspaces are never read into one graph. Competing readings are kept as ambiguities: a word read as a
role and as a concept, state lists that differ, a pair related in two ways.

`redact(graph, sources, may_read)` withholds the quoted excerpts of sources the caller may not read; the candidates
stay.

## 5. Mapping into a proposal

`to_answer(graph)` writes what the current model can hold: entities (with the states the text gives),
relationships with cardinality, actions (no effect unless one is stated and tied to the verb, which the spike
never assumes), roles as descriptions, questions. `propose(sources, brief)` passes that answer, and the cited
paragraphs as `sources`, through `architect.propose` with an in-process provider that is declared as not a language
model. The architect's own checks apply: the schema, the citations against the passages given, the strict loader.

**Not mapped, reported as unmapped findings with the reason:** specialisation (the model has no subclassing;
interfaces are the nearest construct), transitions that no verb can be tied to with certainty, every rule about
approval, access or prohibition (never made enforceable by extraction: its action, condition and role are a
person's to state), document references, concepts that nothing relates to.

**Fail-closed default.** Every element is presented as `inferred`, so the Engine keeps it out of a draft until a
person confirms it, even when a document states it. Taking a document's statements as stated is owner decision
DI-1; the switch exists to measure it and nothing in force passes it.

**The contract's own limit.** `architect.propose` takes at most 20 passages; elements citing only paragraphs beyond
that read as unsupported. The spike reports this rather than working around it.

## 6. What this contract does not do

Store documents; serve them through the API; show them in Studio; read PDF layout, tables or images; follow links;
call a provider; detect copied or reworded content (GAP-109 applies unchanged); prove that a concept is right for a
business.
