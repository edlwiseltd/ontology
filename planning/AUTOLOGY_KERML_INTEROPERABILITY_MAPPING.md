# Autology — KerML interoperability: mapping assessment (not verified, not conformant)

*23 November 2026. Status: **feasibility notes; the KerML side is unverified.** The official OMG specification
could not be read from the engineering environment. Every KerML entry below is a construct named in the
user-supplied video summary, with its meaning **as that summary describes it**, to be checked against the
normative text before any use. Nothing here claims KerML, SysML v2 or XMI conformance, and no adapter was built.*

## 1. Matrix

| KerML construct (as named in the summary) | Normative reference | Closest Autology construct | Correspondence | Loss, ambiguity, what to check |
|---|---|---|---|---|
| Element | **Unverified** | Any model element (entity, relationship, action, rule) | Partial | Autology has no common supertype; identity is a name per section |
| Namespace / Package | **Unverified** | A model document; `modules`, `imports` | Partial | Nested namespaces and qualified names are not modelled |
| Membership, Import | **Unverified** | `imports` of a document | Partial | Visibility rules unknown here |
| Annotation, Comment, Metadata | **Unverified** | `description` fields | Partial | Structured metadata is not modelled; would be lost |
| Classifier / Class | **Unverified** | Entity | Partial | Autology entities carry states and governance; KerML classes do not, as far as the summary says |
| Feature (typed) | **Unverified** | Attribute (typed, with sensitivity) or relationship end | Partial | Multiplicity, redefinition, subsetting have no counterpart |
| Specialization (superclass) | **Unverified** | None between entities; `implements` an interface | **No exact match** | The document spike reports specialisation as unmapped for this reason |
| Association / Connector | **Unverified** | Relationship (from, to, type, cardinality) | Partial | Association classes, n-ary associations: no counterpart |
| Behavior, Function | **Unverified** | Action (preconditions, effects, capability) | Partial | Autology actions are governed operations, not computable functions |
| Succession, occurrences | **Unverified** | State lists, transitions through action effects | Partial | Time and occurrence semantics are not modelled |
| Kernel Model Library (data types, functions, semantic library) | **Unverified** | Attribute types; ontology functions | Partial | Units, vectors, collections: not modelled |
| (none) | — | Rules: human review, prohibition, data and write access, row access | **No KerML counterpart named** | Autology's governance has no place in the summary's KerML; an export would lose it |

## 2. Would an adapter create value?

| Direction | Value | Cost and risk |
|---|---|---|
| Import KerML or SysML v2 into a proposal | Possible for customers who already model equipment in SysML tools (for example manufacturing) | Needs the normative text, a parser for the textual syntax or XMI, and the same review as any proposal; specialisation and multiplicity would be lost |
| Export a model to KerML | Low today: Autology's value is governance, which KerML (per the summary) does not express | An export that drops the rules could be mistaken for the model |
| Turtle | Already exists (`autology/export.py`); it proves nothing about KerML | — |

**Recommendation:** no adapter now. Revisit only with a named customer use case and the normative text in hand.
