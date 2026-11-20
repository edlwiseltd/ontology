# Autology — next sprint: baseline and authorization matrix

*20 November 2026. Status: **preparation. No owner decision is recorded for any row below, and nothing here is one.**
Recommendations are engineering opinions. An unsigned decision form is not authorization. No provider was called, no
credential was read, the spending ledger was not written, nothing was deployed and nobody outside was contacted.*

## 1. Baseline

Two kinds of statement are kept apart: what the report of 19 November **claims**, and what was **observed on
20 November** in this sprint.

| Topic | Report claim (19 Nov) | Observed on 20 Nov | Same? |
|---|---|---|---|
| Source report | — | `planning/AUTOLOGY_R2_PROVENANCE_HUMAN_REVIEW_GOVERNED_OPERATIONS_REPORT.md`, SHA-256 `BBBD03B0…EDCDA6F`: equal to the hash named in the directive | Yes |
| Branch and commit | `claude/autology-ontology-agent-4ajjer`; final code `334b3e5` | Same branch; head `95e4442` (the report and log, committed after `334b3e5`); local = remote; clean working tree at the start | Yes. `95e4442` adds documents only |
| Later owner decisions | — | None: no commit, register row or message after `95e4442` records one | — |
| Store schema | 22 | `SCHEMA_VERSION = 22` (`autology/store.py`) | Yes |
| CI | Run 127 success on `334b3e5` | Run 127 success (five jobs); [run 128](https://github.com/edlwiseltd/ontology/actions/runs/44638411041) success on `95e4442`, read from GitHub today | Yes |
| Python suite | 1,155 passed, 2 skipped locally, 96.19 % | Run again today on `95e4442` with outside network denied: see the engineering report | See report |
| Permissions accepted | `records.create`, `records.update`, `operate` are not permissions | `server.PERMISSIONS` = read, run, review, audit, ingest, reconcile, configure, admin | Yes |
| Prototypes | Inactive | Nothing under `autology/` or `studio/web/` imports `operation_policy`, `design_governance` or `architect_elements`; `runtimeForwardable` is used by its test only | Yes |
| Draft writers | Two routes write a draft, one publishes | `ArchitectService.save_draft` (via `AutologyService.save_model_draft`), `ConfigurationService.save_solution_draft`, `Platform.publish_draft`. No other caller of `Store.save_draft`, no other insert into `model_drafts` | Yes. No new entry point |
| Production | Disabled | The lifecycle never grants the production stage (`autology/platform.py`) | Yes |

### Contradictions and corrections found (reported, not resolved by choosing a side)

| # | Finding | Effect |
|---|---|---|
| C1 | The report (F.1) asks to "approve the **three** record rights" under D24 a. The D24 proposal's question **a** covers **two**: `records.create` and `records.update`. The third proposed right, `records.archive`, is question **c**, and is not part of a | This package treats D24 a as the two rights. Archive and delete stay out |
| C2 | "D24 a" names two things. In the decision register, D24 option (a) is "keep `admin` as an explicit grant" (an applied default). In the application-permissions proposal §8, question a is the two record rights | The forms below quote the question text. A decision should name the document it answers |
| C3 | The report (D.1) and GAP-111 say the 40 elements of the kept ground-handling proposal have no source link. The stored file holds, per element, the citation the model gave at the time: **28 cite the brief as a whole, 12 cite nothing, none cites an answer**. What is absent is the structured evidence entry that the trace reads, which was introduced later. The same holds for the seven kept answers of run 2: every element cites the brief as a whole | The trace understates what is stored; it invents nothing. The stored labels are coarse ("brief"), not a passage. Recorded as GAP-113; the readiness package shows the stored labels as they are |
| C4 | The second person who publishes a draft is shown its revision number and author only (`GET …/releases`). The provenance record and its flags are returned to the designer (`GET /api/v1/model/draft`), not to the publisher | Relevant to D37 d: showing flags at publication is not built |
| C5 | Two review instruments exist: the form of proposed protocol V2 (one judgment per element, 1 to 5) and the rubric of Part C (six criteria, 0 to 3) | One must be chosen before any scoring: see the readiness package |
| C6 | The held-out cases (two reserved briefs with their reference answers, eight V2 cases) are files of the repository and are shipped inside the Python package (`pyproject.toml`, package data) | "Held out" rests on who can read the repository and the package. Recorded as GAP-114 |
| C7 | The assessment for D35 puts its three questions under "D35 d"; the register's D35 has defaults a to d | The forms below call them D35 d-a, d-b, d-c |

## 2. Authorization matrix

Approval status values: absent, proposed, approved, rejected, superseded. "Proposed" means a proposal exists for the
owner; it does not mean anyone agreed.

| Decision | Exact question | Alternatives | Behaviour verified in code today | Approval status | Decision-maker, record, date | Implementation scope recorded | Allowed now | Blocked | Separate activation gates |
|---|---|---|---|---|---|---|---|---|---|
| **D37 c** | What happens to a legacy draft (no provenance) that is saved again, and who answers for its content? | 1 as applied: classified again, the rest attributed to the saver. 2 an administrator's recorded acknowledgement first. 3 refuse legacy drafts | Not published (409, `Platform.publish_draft`); saved again, compared with the model that runs, unconfirmed proposal elements refused, the rest attributed to the saver, `reestablished_from_legacy` set | **Proposed** (default in force; not an owner decision) | None | None | Decision sheet, specification, proposed tests | Any change to `save_draft`, a new table or route, Studio changes | Second-person publication and release approval stay as they are under every option |
| **D37 d** | In a draft that names no proposal: an element with the identity of a proposal's unconfirmed element and other content | 1 as applied: saved as the author's own, flagged. 2 refuse. 3 also show the flags to the second person at publication | Saved, attributed, flagged in `provenance.flags`; refused when the draft names that proposal. The publisher is not shown the flags (C4) | **Proposed** | None | None | Decision sheet, patch plan, proposed tests | Changing the refusal; returning provenance to the publisher; any acknowledgement | None of the options proves origin (GAP-109) |
| **D24 a** (proposal §8 a) | "Add `records.create` and `records.update` as scoped grants, as in §2 to §4?" | Yes; no | A grant naming either is refused (400); an application user's write is 403; forms are previews; the policy function is called by nothing | **Proposed. Not approved** | None | None | Plan, test mapping, existing prototype tests run as they are | Registering the names, any call from `upsert_object`, a route, Studio or runtime forms that send | Even if approved: grants are per member and need two people; sandbox enablement and any use outside simulation are separate decisions |
| D24 b, c, d, e | Links in `records.update`; `records.archive`; operations 6 and 7 never a caller's; together with `operate` or apart | See the proposal | As above; no archive route exists | Proposed | None | None | Listed for completeness | All | Not requested in this sprint |
| **D34 Q1** | "Do application designs become release artifacts?" | A a named part of a release. B a governed artifact of its own, bound by reference. C no: designs stay drafts | A design is a draft; the Engine reports "approved release artifact: not supported"; nothing calls `design_governance` | **Proposed (recommendation A). Pending** | None | None | Decision sheet, dependency analysis, test mapping | The release structure, migration, routes, Studio | Q2, Q3 and Q7 are needed before A can be built; production is refused whatever is approved |
| D34 Q2 to Q7 | Who approves; a separate reviewer; versions; rollback; suspension; migration | See the proposal | The prototype has **no default** for any of them and refuses to run without | Proposed | None | None | Dependencies stated | All | — |
| **D35 d-a** | "Confirm that one origin is acceptable for simulation only?" | Yes; no | One web project, one origin, one kind of token | Proposed | None | None | Plan | — (a confirmation changes no code) | Production stays blocked on separation |
| **D35 d-b** | "Approve steps 2 and 3 (two roles, two origins) as the next deployment change?" | Yes; no | Not built. The narrow relay rule exists and is wired to nothing | Proposed | None | None | Architecture, migration and test plan | A start-up role, any hosting, DNS or policy change | Deployment is a further decision; local fixtures are not deployed-origin evidence |
| **D35 d-c** | "Take tokens for one plane (step 6) into the identity roadmap?" | Yes; no | Tokens are not plane-scoped | Proposed | None | None | Specification outline | Any change to tokens, audiences or identity policy | IAM-2, IAM-4 to IAM-6 are not to be implemented early |

**Result for this sprint:** every row is "proposed", none is approved. So no executable policy was changed, no
prototype was created or extended, and nothing was wired to a route. The work done is decision sheets, plans, test
mappings, a fresh baseline, and the preparation package for an independent semantic review.

## 3. What would count as an approval

An attributable statement by the owner, kept in the repository (the decision register, with the date and the
reference of the message or signed form), that names the question, the option chosen, the implementation scope and
the activation scope. Not sufficient: a recommendation, an existing default, a passing test, a directive that asks
for preparation, an administrator's action in the product, or silence.
