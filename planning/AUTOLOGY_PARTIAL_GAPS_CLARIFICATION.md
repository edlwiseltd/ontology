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

> **Update (Increment B):** C1–C3 met; GAP-018 is now **Fixed** in the repository. Limits that remain: detection, not prevention, of direct database writes; in the engine's demo mode (no audit key) seals are plain hashes and detect accidents only; changes made before the schema-14 upgrade are sealed as found; library and tooling writes that do not name a revision (`ANY_REVISION`) skip the revision check but not the seal check; MCP over HTTP answers JSON (no server-sent events). Evidence: `tests/test_gap018_record_consistency.py`, [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md).

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

**Status: engineering part done (Increment C); legal part open. GAP-031 stays Partly fixed.** Customer
distribution of any package or image stays prohibited until the written decisions below are recorded. Internal
engineering may continue. Nothing here is a legal conclusion: it is the factual input counsel asked for.

### What engineering verified (Increment C, 14 November 2026)

| Item | Finding | Evidence |
|---|---|---|
| The wheel (`pip install autology`) | No runtime dependency; extras are optional | `pyproject.toml` (`dependencies = []`) |
| Python packages in the default image (`EXTRAS=llm,postgres`) | 18 third-party packages; all permissive except **`psycopg` and `psycopg-binary` (LGPL-3.0-only)**. `psycopg-binary` bundles `libpq` (PostgreSQL licence, permissive) | Built and listed on 14 Nov; CI re-checks every build (`deploy/image_licences.py`) |
| MPL-2.0 `certifi` | **Not in the image any more**: the current `anthropic` resolution no longer installs it. Earlier builds contained it | same |
| Reproducibility | The image's Python packages were unpinned, so its contents (and licences) depended on the build date. **Now pinned** in `deploy/image-constraints.txt`; CI fails if the built image differs from the pins or contains an uninventoried or forbidden component | `tests/test_leg1_licences.py`, CI step "Licences of what the image really contains" |
| Image without the LGPL driver | `docker build --build-arg EXTRAS=llm` builds an image with **no weak-copyleft Python component**; it passes the full smoke test. It loses SQL pipelines and the PostgreSQL reporting target only | Built and smoke-tested locally on 14 Nov; CI builds, checks (`--no-weak-copyleft`) and smoke-tests it on every push |
| Engine-only image | `--build-arg EXTRAS=` installs no third-party Python package (no assistant, no SQL pipelines) | `pip --dry-run` report: 1 package (Autology) |
| Base image | `python:3.13-slim`: CPython (PSF) and **87 Debian packages**, among them GPL-2/GPL-3 tools and LGPL-2.1 libraries (for example glibc), each with its licence in `/usr/share/doc/<package>/copyright` | `deploy/image-os-packages.txt` (generated from the built image) |
| Licence file | `LICENSE` is proprietary with the legal entity left as a placeholder | `LICENSE` |

Obligations commonly associated with these licences, **to be confirmed by counsel** (not concluded here):
LGPL-3.0 for a bundled, unmodified library: provide the licence text and notices, and let the recipient replace
the library with a modified version; MPL-2.0 (only if `certifi` returns): file-level, keep notices and make the
source of the covered files available; GPL/LGPL Debian packages in a container image: whether shipping the base
image is "mere aggregation" and which source offers are needed.

### Decisions only the owner and counsel can take

| # | Exact question | Alternatives | Consequences | Recommended default (engineering) |
|---|---|---|---|---|
| L1 | Who is the copyright holder and licensor named in `LICENSE`? | The operating company; a holding entity | Contracts and notices name it | — (owner) |
| L2 | Is the proprietary licence text in `LICENSE` final? | Keep as is; counsel's EULA; per-customer agreements only | Every package and image carries it | Counsel's text |
| L3 | May the default image ship the LGPL `psycopg` driver? | (a) Yes, with the obligations counsel lists; (b) default image without it (`EXTRAS=llm`), PostgreSQL as a documented add-on the customer installs; (c) a separate PostgreSQL image | (b) removes the only weak-copyleft Python component from the default image; PostgreSQL features need the add-on | (b) until counsel answers, **if the owner agrees** (it changes what customers get by default) |
| L4 | How are the base image's Debian packages handled? | Distribute the image with source offers; let customers build the image from the Dockerfile; another base image | Affects every image distribution | Counsel |
| L5 | Is a written dependency-licence policy (allowed / review / forbidden families, already in `deploy/third_party_licences.json`) approved? | Approve; amend | CI enforces it on every build | Approve as written |

### Closure criteria (all required; unchanged in substance)

- C1: counsel's written sign-off on the licence text and the legal entity recorded in the decision register (L1, L2), `LICENSE` updated.
- C2: written decisions on L3 and L4, applied to the Dockerfile and the notices.
- C3: `tests/test_leg1_licences.py` and the CI image licence checks pass with the final texts and the chosen image.
