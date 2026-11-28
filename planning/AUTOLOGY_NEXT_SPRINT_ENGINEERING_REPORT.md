# Autology — next sprint: engineering report

**Sprint:** owner decision readiness, governed operations and independent semantic validation readiness
*20 November 2026. Preparation only. **No owner decision was found, so nothing was implemented.** No provider was
called, no credential was read, the spending ledger was not written, nothing was deployed and nobody outside the
project was contacted. **R2 is not closed.***

## In one page

| Asked | Delivered |
|---|---|
| A baseline that does not rest on the report | Repository, CI and the full test suite checked again today; the report's claims hold, with three corrections (§1) |
| An authorization matrix | One row per decision. Every row is "proposed"; none is approved |
| D37 c and d | A decision package with the three options of each, a recommendation, the exact effect, the tests and a blank form |
| D24 a, D34 Q1, D35 | A plan that says what each approval would have to cover, what it unblocks, and which tests exist, pass, or are only planned |
| Independent semantic validation | A package a review can start from: frozen inventory with hashes, rubric, blank form, completeness check, synthetic rehearsal. **No review took place** |

What was built: one local tool for the review package, and eight tests. No behaviour of the Engine, Studio or the
runtime changed. Nothing in `autology/` or `studio/` was touched.

Three things the owner should know:

* **"D24 a" is two rights, not three.** Yesterday's report said three. Question a of the proposal is
  `records.create` and `records.update`; archive is question c.
* **Yesterday's report understated what is stored about sources.** It said the 40 elements of the kept
  ground-handling proposal have no source link. The file holds a coarse citation for 28 of them ("the brief").
  The trace does not read that older field. Nothing was invented; a figure was too low.
* **The person who publishes a draft does not see its provenance flags.** They see the revision number and the
  author. That is what D37 d, option 3, would change.

The five decisions that would unblock work are at the end.

---

## 1. What was verified against the report, and what changed since

Two columns are kept apart throughout: what the report of 19 November claims, and what was observed on 20 November.

| Topic | Report claim | Observed 20 November | Result |
|---|---|---|---|
| The report itself | — | SHA-256 `BBBD03B02D38BA923CC831D20A5C9A95650A84A59E51C374A604EDD4EEDCDA6F`, equal to the directive's | Same file |
| Commit | Final code `334b3e5` | Head `95e4442` (documents added after `334b3e5`); local = remote; clean tree at the start | Consistent |
| Changes by anyone since | — | None: no later commit, no later decision record | Nothing changed |
| Schema | 22 | 22 | Holds |
| CI | Run 127, five jobs, success | Run 127 success; [run 128](https://github.com/edlwiseltd/ontology/actions/runs/44638411041) success on `95e4442`, read from GitHub today | Holds. Both are results of yesterday's commits, not of this sprint's changes |
| Python suite | 1,155 passed, 2 skipped, 96.19 % | Run again on `95e4442` with outside network denied: **1,155 passed, 2 skipped, 96.19 %** | Holds |
| mypy; ruff | 198; clean | 198; clean | Holds |
| Studio | 85 unit tests; browser 135, 76, 108 | 85 unit tests pass; browser suites: **135/135, 76/76 and 108/108 checks pass** | Holds |
| GAP-107, GAP-108 | Closed as described | `tests/test_gap107_draft_origin.py` (10) and `tests/test_rev1_proposal_review.py` (9) pass in the runs above | Holds |
| D24, D34 prototypes | Inactive | Imported by nothing; the names are not permissions | Holds |
| D35 | One origin, simulation only | One origin | Holds |
| Draft writers | Two routes write, one publishes | The same three; no new entry point | Holds |

### Corrections to the report

| # | The report said | What is the case |
|---|---|---|
| C1 | F.1: "D24 a: approve the three record rights" | Question a covers **two** rights. The third, `records.archive`, is question c |
| C3 | D.1 and H.5: source and evidence missing for all 40 elements of the ground-handling proposal | Structured evidence entries: missing for all 40, as said. But a citation recorded at the time exists for **28 of 40** (the brief as a whole); 12 cite nothing; none cites an answer. The seven kept run 2 answers cite the brief for every element. Recorded as GAP-113 |
| C4 | (Not stated) | The publisher of a draft is shown revision and author, not the provenance flags |

Other findings: "D24 a" also names an option of the D24 row in the decision register (C2); two review instruments
with different scales exist (C5); the held-out cases are shipped inside the Python package (C6, GAP-114). Details:
`planning/AUTOLOGY_NEXT_SPRINT_AUTHORIZATION_MATRIX.md`.

The report was not edited: its hash is the one the directive names.

## 2. What changed in the repository

| Path | Kind | Content |
|---|---|---|
| `planning/AUTOLOGY_NEXT_SPRINT_AUTHORIZATION_MATRIX.md` | New document | Baseline, corrections, one row per decision |
| `planning/AUTOLOGY_D37_CD_OWNER_DECISION_PACKAGE.md` | New document | D37 c and d |
| `planning/AUTOLOGY_GOVERNED_OPERATIONS_NEXT_SPRINT_PLAN.md` | New document | D24 a, D34 Q1 and its dependencies, D35 |
| `planning/AUTOLOGY_INDEPENDENT_SEMANTIC_REVIEW_READINESS_PACKAGE.md` | New document | The review package |
| `planning/AUTOLOGY_NEXT_SPRINT_ENGINEERING_REPORT.md` | New document | This report |
| `deploy/make_review_package.py` | New tool | Inventory, blank form, completeness check, synthetic rehearsal. Reads repository files, writes files; no network, no credential, no provider |
| `planning/review-package/` | Generated | `inventory.json`, `inventory.txt`, `rehearsal.json` |
| `tests/test_semrev1_review_package.py` | 5 new tests | The tool, the kept files, and that nothing held out is copied |
| `tests/test_d37_current_defaults.py` | 3 new tests | The defaults in force, and two of their limits, pinned as they are |
| Defect register, decision register, roadmap §3.5, traceability, WIP, log | Updated | GAP-113, GAP-114; the state of each decision; no status changed |

**Where the changes are.** The directive asked to keep the deliverables local. This session runs in a temporary cloud container, so the owner was asked, and chose on 20 November to commit and push to the working branch: commit `cc175d8` on `claude/autology-ontology-agent-4ajjer`. No pull request was opened, nothing was deployed, nothing was sent anywhere else.

Not changed: anything under `autology/` or `studio/`; any prototype; any permission, route, schema or policy; the
report of 19 November; the held-out cases; the evidence kept on 17 and 19 November.

## 3. Checks

All runs on 20 November 2026 (UTC), in this session's container, Python 3.13. "Network denied" means the process
ran in a network namespace that has only a loopback interface: an outside host, a provider included, cannot be
reached from it (checked before use: a connection to an outside address fails).

| Check | Command | Tree | Environment | Result |
|---|---|---|---|---|
| Python suite, baseline | `coverage run -m unittest discover -v -s tests -t .` | `95e4442`, as committed | Network denied | **1,155 passed**, 2 skipped; coverage **96.19 %** (18,391 statements, 701 missed) |
| Python suite, final | The same | `95e4442` plus the changes of §2: the tree committed as `cc175d8` | Network denied | ****1,163 passed** (the 1,155 and the 8 new tests), 2 skipped; coverage **96.19 %** (18,391 statements, 701 missed)** |
| The two skipped tests | — | `cc175d8` | They need a PostgreSQL server; none runs in this container | **Not run locally. Run in CI**: [run 129](https://github.com/edlwiseltd/ontology/actions/runs/44716559702) on `cc175d8`, where the suite runs against PostgreSQL and no test may be skipped |
| ruff | `ruff check autology tests deploy examples studio/web/e2e` | Final | Local | Clean |
| mypy ratchet | `python deploy/mypy_ratchet.py` | Final | Local | 198 = baseline (not raised) |
| API contract in step | `python -m autology openapi --write …`, compared with the kept contract | Final | Network denied | Identical |
| Studio type-check; unit tests | `npm run typecheck`; `npm test` | Final | Network denied | Clean; **85 passed** |
| Studio build | `npm run build` | Final | Network denied | Succeeds |
| Browser suites | `e2e/run.sh` | Final | Network denied | **135/135, 76/76 and 108/108 checks pass** |
| Prototypes unreachable | Search for imports of `operation_policy`, `design_governance`, `architect_elements` outside themselves; the prototypes' own tests | Final | Local | None found; tests pass |
| CI on this sprint's changes | — | — | — | **Success**: [run 129](https://github.com/edlwiseltd/ontology/actions/runs/44716559702) on `cc175d8`, five jobs (quality, studio, package, test 3.10, test 3.13), read from GitHub after it finished. **Run after the owner chose to push (see §2)** |

Coverage gate (95 %) and mypy allowance (198) are unchanged. No test was removed or weakened.

**Provider, credentials, ledger.** What can be said from the execution record: the test processes could not reach
any outside host; the wrapper removed the provider key variables from their environment without reading them; no
command read a credential, a token store or a provider dashboard; the ledger file was not opened (its modification
time is still 17 November). This is the agent's own record of what it ran. It is not independent proof.

## 4. The ten answers

| # | Question | Answer |
|---|---|---|
| 1 | What was verified against the report, and what changed since? | §1. The report's claims hold on today's runs, with corrections C1, C3 and C4. Nothing in the repository changed between the report and this sprint |
| 2 | Which decisions are approved, by whom, for what scope, and where is the evidence? | **None.** For D37 c, D37 d, D24 a, D34 Q1 to Q7 and the three D35 questions, no approval exists in the repository or in any message. Each has a proposal and a blank form. The matrix lists them |
| 3 | What was prepared, what was implemented, what remains blocked? | **Prepared:** five documents, six decision forms, test mappings, the review package. **Implemented:** one local tool and eight tests; no product behaviour. **Blocked on the owner:** every change to how drafts, writes, designs or origins behave; the choice of review instrument and thresholds; reviewers |
| 4 | Are D24 permissions or D34 governed designs active anywhere, and under which approval? | **No, nowhere, and under no approval.** The names are not permissions (a grant naming one is refused), a write by an application user is refused, forms are previews, designs are drafts, and nothing calls either prototype |
| 5 | Is D35 actually isolated, or only planned or simulated? | **Not isolated. Planned only.** One origin, one kind of token. Separate storage keys and an opener-free link are conventions, not a boundary. The Engine's authorization is the boundary. No separation test has been run, because none can pass on one origin |
| 6 | Has an independent expert reviewed a model, or is only the package ready? | **Only the package is ready.** No expert was contacted. The rehearsal used synthetic judgments on a synthetic case and says nothing about any model |
| 7 | Which provenance links remain missing, and which uncertainty is unavoidable? | **Missing:** in every answer kept from 17 November, no structured evidence entry and no citation of a passage; in the ground-handling proposal, 12 elements cite nothing and none shows the answer it came from; the chain evaluation releases nothing, so the release link is missing there by construction; a simulated run leaves audit events for executed steps only. **Unavoidable:** content retyped, renamed or brought from outside cannot be shown to come from a proposal (GAP-109), under every option of D37 d |
| 8 | What tests passed on which commit, and what was not run? | §3. Baseline on `95e4442`: 1,155 passed. Final tree: 1,163 passed, 2 skipped, 96.19 %; Studio 85 unit tests; browser 135, 76 and 108 checks. CI [run 129](https://github.com/edlwiseltd/ontology/actions/runs/44716559702) on `cc175d8`: success, PostgreSQL tests included. **Not run:** the two PostgreSQL tests locally; any test of the planned D24, D34 or D35 integrations (they do not exist) |
| 9 | Were provider calls, credentials, spending or production touched? | No provider call. No credential read. No ledger write; the ledger was not opened. Production stays refused by the Engine. See the note in §3 on what this statement rests on |
| 10 | Is R2 formally closed? | **No.** This sprint closes nothing. Open as before: decisions D19, D23, D24, D26, D30 f/g/h, D31 to D37; ARC-0 partial; no independent security review; no independent semantic review; origin and token separation not built; no production-sized restore drill; no real integration in a sandbox of a real system; the architect's path on a real provider beyond the one authorised evaluation |

## 5. Tracks, one line each

| Track | State |
|---|---|
| A — D37 c | Three options specified; recommendation: an administrator's recorded acknowledgement before a legacy draft is re-established. Current protection kept and pinned by a test. **Awaiting the owner** |
| B — D37 d | Three options specified; recommendation: show the Engine's flags to the publisher, no mandatory acknowledgement. No option closes GAP-109. **Awaiting the owner** |
| C — D24 a | Two rights; four scopes an approval must name; ten items mapped to prototype tests (passed, semantics only) and to API and browser tests (planned). **Not approved** |
| D — D34 Q1 | Quoted; Q2, Q3 and Q7 are needed with it before anything can be built; eight negative cases mapped. **Pending** |
| E — D35 | Three separate decisions; staged plan; fifteen boundaries with their true test status (six passed, nine planned). **Awaiting the owner; nothing deployed** |
| F — Semantic review | Package ready; instrument, thresholds, reviewers and sharing are the owner's. **No review** |

## 6. The smallest decisions that unblock work

Each has a form with empty fields in the document named. An unsigned form authorises nothing.

| # | Decision | Options | Unblocks | Form in |
|---|---|---|---|---|
| 1 | **D37 c** — a legacy draft saved again | As applied / an administrator's acknowledgement first / refuse | Either nothing to build, or one small Engine change | D37 package |
| 2 | **D37 d** — a reworded element | As applied / refuse / show the flags to the publisher | The publisher seeing what the Engine knows | D37 package |
| 3 | **D24 a** — `records.create` and `records.update` | Yes or no, **and which scopes**: definitions, enforcement, sandbox grants, forms that send | The first real write by an ordinary user, in simulation | Operations plan §1.7 |
| 4 | **D34 Q1, with Q2, Q3 and Q7** | A, B or C for each | Designs as part of a governed release; Q1 alone unblocks nothing | Operations plan §2.6 |
| 5 | **Semantic review** — instrument, thresholds, first cases, reviewers, agreement to share | See the readiness package §11 | The first independent judgment of a model | Readiness package |

D35 can wait without blocking the others: confirming "one origin, simulation only" changes no code, and separation
is needed before production, not before the work above.
