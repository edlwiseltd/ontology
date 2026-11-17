# Two synthetic domain packs on one engine

This folder holds the configuration of the cross-domain validation (R2): two independent applications hosted by
one Autology platform, each in its own workspace.

| Folder | Application | What it rehearses |
|---|---|---|
| `crisis_management/` | Autology Crisis Management (synthetic) | a fictional river flood: an incident report is validated, equipment is proposed, a team is assigned (a person approves above a limit), an update is published |
| `network_intelligence/` | Autology Network Intelligence (synthetic) | a fictional compliance case: relationships are extracted, an unusual pattern is flagged with its competing explanation, a person decides every escalation, a summary is written |

Each pack is **configuration only**: `server.json` (a blank model, the sandbox architect and the pack's blueprint
folder), `ontology.json` (empty) and `blueprints/*.json` (a template with its questions, simulated tools and
invented records). `platform.json` declares the two workspaces, their people and which template each workspace is
offered. `build_packs.py` writes all of it; the JSON files are what the engine reads.

What this is not:

* **Not AI.** The sandbox architect is a test double. It recognises a template by its vocabulary and fills in the
  answers; it reads nothing and understands nothing. The templates were written by an engineer.
* **Not operational.** Every tool is simulated. Nothing is dispatched, nobody is warned, no account is consulted,
  nobody is accused. All places, organisations, people, accounts and amounts are invented.
* **Not validated.** A passing synthetic test proves nothing about suitability for real emergency response or for
  real investigations. Both need expert review (see `planning/AUTOLOGY_ARCHITECT_EVALUATION_PROTOCOL_V2.md`).

Tests: `tests/test_xdom1_cross_domain.py`. Contract for an application that consumes a released solution:
`docs/application-contract.md`.
