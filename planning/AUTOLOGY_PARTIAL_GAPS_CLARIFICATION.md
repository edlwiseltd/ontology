# Autology — GAP-009, GAP-018 and GAP-031: what is fixed, what is not, and how each closes

*14 November 2026. These three gaps are reported **Partly fixed** in the [defect register](AUTOLOGY_DEFECT_REGISTER.md).
None of them may be reported closed until every closure criterion below is met and evidenced. Sources: the audit's
register (`audit/04_AUTOLOGY_GAP_REGISTER.md`) for the defect and its remedy; the repository for what exists.*

## GAP-009 — Resumed runs act on stale data; write-back is partial (High)

> **Update (Increment A):** C1–C3 met; GAP-009 is now **Fixed** in the repository. Evidence: `tests/test_gap009_atomic_write_back.py` and the [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md).

The audit's remedy has three parts.

| Part | Status | Evidence |
|---|---|---|
| On resume, re-read the case's live records | **Done** | ACT-6, `c779566`; `tests/test_act6_revalidation.py` |
| If a reviewed fact changed, the approval is superseded and a new review is required (the audit's acceptance test, PoCs 11b and 11c) | **Done** | same tests: amount changed during review, claim rejected during review, conflicting field |
| Write-back all-or-nothing per run | **Not done** | `graph.write_back` and `AutologyService._write_back` |

**What remains, precisely.** When a run finishes, `write_back` writes each field the run changed unless the live
record moved meanwhile (a conflict: the live value is kept and a person is notified). Two consequences:

1. **Partial results.** In a run that changed two fields, one conflicting and one not, the clean field is written
   and the conflicting one is not: the record ends up with half of the run's result.
2. **Not atomic.** Each changed instance is written with its own store call. A crash between two calls leaves some
   records updated and others not.

**Risk today.** Lower than the original defect: no action executes on stale data any more. The residue is
inconsistent record state after a conflict or a crash during write-back.

**Closure criteria (all required).**
- C1: a run's write-back writes either all of the fields it changed or none; any conflict means none, and the
  conflict is recorded for a person (test: one conflicting and one clean field, neither written).
- C2: all of a run's record updates are committed in one store transaction (test: a failure injected between two
  instance writes leaves no record changed).
- C3: the full suite and the external-effects matrix still pass.

Estimated effort: about 1 day. Proposed as a small increment after the execution gates.

## GAP-018 — The server's graph is never refreshed from the store (High)

| Part of the audit's remedy | Status | Evidence |
|---|---|---|
| Short term: one writer per store; the CLI refuses while a server holds it | **Done** | MOD-4, `fd7ab77`, `f0a385a`; `tests/test_mod4_single_writer.py` (7): a second writing process is refused while the holder is alive; a crash frees the lease; backup and reporting open the store read-only |
| Long term: reload or version-check records on write | **Not done** | — |

**What remains, precisely.**
1. Divergence between two Autology processes is now prevented by refusing the second writer, not by detecting it.
   A change made to the SQLite file outside Autology (direct database access) is still neither detected nor
   reloaded: instance rows carry no version and no seal (run records do, since GOV-4).
2. **Operational consequence found while writing this note:** `autology mcp platform.json --use-case …` loads the
   use case as a writing process, so it is refused while the platform server runs. An MCP client and the platform
   server therefore cannot serve the same use case at the same time. This is safe (no divergence) but limits use.

**Closure criteria (all required).**
- C1: every instance row has a version, checked on each write; a mismatch reloads the record and reports a
  conflict instead of overwriting (test: a row changed outside the process is not overwritten).
- C2: an MCP client can reach a use case while the platform server runs, without a second writer (for example
  MCP as an HTTP client of the router), with the ISO-1 isolation tests unchanged.
- C3: the existing MOD-4 tests still pass.

If the owner decides that isolated single-node pilots are the only deployment for now (D1 and D2), C1 can be
scheduled with OPS-3 (PostgreSQL) instead; the gap then stays open with that decision recorded, it is not closed.

## GAP-031 — No licence; redistribution terms undefined (High, blocks customer use)

| Part | Status | Evidence |
|---|---|---|
| Licence file and package metadata (proprietary, D5) | **Done (engineering)** | LEG-1, `6a23ff5`; `LICENSE`, `pyproject.toml` |
| Third-party notices and a machine-readable inventory checked in CI | **Done** | `THIRD_PARTY_NOTICES.md`, `deploy/third_party_licences.json`, `tests/test_leg1_licences.py` |
| Legal review of the licence text, name of the legal entity | **Not done (external: counsel)** | `LICENSE` leaves the entity and final text to the IP review |
| LGPL-3.0 (`psycopg`, `psycopg-binary`) and MPL-2.0 (`certifi`) components shipped in the Docker image | **Not done (external: counsel)** | `THIRD_PARTY_NOTICES.md` rows marked "Confirm with counsel before distributing the image" |

**Closure criteria (all required).**
- C1: counsel's written sign-off on the licence text is recorded in the [decision register](AUTOLOGY_DECISION_REGISTER.md) (D5), with the
  legal entity's name, and `LICENSE` updated accordingly.
- C2: a recorded decision on the LGPL/MPL components in the image: either counsel confirms the obligations and
  how they are met, or the default image is built without the optional PostgreSQL extra. That is a product and
  legal choice; engineering can build either image.
- C3: `tests/test_leg1_licences.py` passes with the final texts.

Engineering cannot close GAP-031 alone. Until C1 and C2 are met, no image or package may be distributed to a
customer.
