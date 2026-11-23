# Autology — document intelligence: owner decisions

*23 November 2026. Only the decisions the spike shows are needed. Every answer field is blank. **An unsigned form is
not authorization.** Until decided, nothing changes: the spike is called by nothing in force.*

| # | Decision | Options | Recommendation (not a decision) | Why it is the owner's |
|---|---|---|---|---|
| DI-1 | May an element that a document states, read by an automatic extractor, count as **stated** (no confirmation required), or must every extracted element be confirmed by a person? | (a) Always confirm (the spike's default). (b) Stated when a sentence pattern read it and the paragraph is cited. (c) Stated only for elements a person marks as taken from an authoritative document | (a) for now | It decides how much a machine's reading may enter a model without a person |
| DI-2 | May Autology **store documents** (and their excerpts) per workspace, and under which retention and access classes? | (a) No storage: documents stay outside, only anchors and quotes are kept with a proposal. (b) Store documents per workspace with `public`/`internal`/`restricted` and a retention period. (c) Store anchors and hashes only | (c) to start | Data retention and confidentiality of customer documents |
| DI-3 | Should the proposal route and Studio **accept documents** and show evidence beside each element? | (a) No. (b) API only: passages with a proposal request. (c) API and a Studio evidence panel with document-level visibility | (b), then (c) after DI-2 | It widens the API contract and what reviewers see |
| DI-4 | Should the 20-passage bound of the proposal contract be raised, or documents be split per proposal? | (a) Keep 20. (b) Raise (cost and prompt size grow if a model is used). (c) Split documents into several proposals | (a) until a real document needs more | It changes provider cost once a model is used |
| DI-5 | May documents be **sent to an AI provider** (an extraction step by a model)? | (a) No. (b) Under the existing D7/D10 authorisation, for synthetic documents only. (c) For customer documents, with a separate data-processing decision | (a) until a model-based extraction is proposed and costed | External processing and spending (D7/D10, D30 h) |
| DI-6 | Integrate the pipeline? | Go / revise / no-go | **Revise** (see the engineering report) | Product direction |

| Field | DI-1 | DI-2 | DI-3 | DI-4 | DI-5 | DI-6 |
|---|---|---|---|---|---|---|
| Option selected | | | | | | |
| Scope | | | | | | |
| Decision-maker | | | | | | |
| Date | | | | | | |
| Durable reference | | | | | | |
