# AUTOLOGY — AI ARCHITECT RELIABILITY & EVALUATION STABILIZATION REPORT

*17 November 2026. Branch `claude/autology-ontology-agent-4ajjer`. No request was sent to a provider in this
sprint and nothing was spent. Registers: [implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md),
[defects](AUTOLOGY_DEFECT_REGISTER.md), [decisions](AUTOLOGY_DECISION_REGISTER.md).*

## In one paragraph

The spending ledger now outlives a deployment: writing or starting a deployment again no longer hands spent money
back, and a missing, empty, older or different ledger serves nothing. A design session can be left and resumed in
Studio without paying again; every element says what it rests on, from the brief to the release. Answers refused
as outside the contract are now explained and classified, and a decision record compares four ways to lose fewer of
them: **the rule itself is unchanged and the choice is the owner's.** A second, separate evaluation protocol is
proposed (held-out cases, hostile instructions through four channels, an injection measure that judges behaviour):
**it is not in force.** The third paid evaluation was **not run**: it needs the owner's approval. R2 is not closed.

## 1. Engineering evidence

| | |
|---|---|
| Starting revision | `5585346` (CI runs 107 and 108 green on the two commits before it; verified) |
| Ending revision | the commit that carries this report (named in the implementation log with its CI run) |
| Python suite | Full suite on the tree before increment F and the evaluation protocol's last additions: **1009 tests, all passing** (2 PostgreSQL tests skipped locally), **95.89 %** line coverage (16,971 statements, 697 missed). The 5 tests added after it, and every suite touched since, pass; the full run on the final tree is recorded in the implementation log |
| Static analysis | ruff clean; mypy 198 errors, equal to the baseline (not raised) |
| Studio | typecheck clean; 58 unit tests (42 before); build; **135 of 135 browser checks** (119 before) |
| CI | recorded in the implementation log once the run of this commit has finished |
| Real provider calls | **None.** No test contacts a provider; no credential was added to CI |

**Commits.** The increments share files (the ledger, the proposal views and the contract touch the same
modules), so they are delivered as one commit whose message is organised by increment, followed by a commit that
records the CI result. Where each increment lives:

| Increment | Modules | Tests |
|---|---|---|
| A. Spending ledger | `ai_policy.py`, `platform.py`, `recovery.py`, `__main__.py` (`ai-ledger`), `deploy/evaluation_setup.py` | `tests/test_stab1_spending_ledger.py` (18) |
| B. Structured output | `ai.py`, `architect_eval.py`, `architecting.py` | `tests/test_stab2_structured_output.py` (8) |
| C. Proposal lifecycle | `store.py` (schema 19), `migrations.py`, `architecting.py`, `platform.py`, Studio `lib/proposals.ts`, `OnboardingView.tsx` | `tests/test_stab3_proposal_lifecycle.py` (8), Studio `proposals.test.ts` (10), 8 browser checks |
| D. Provenance | `architect.py`, Studio `lib/onboarding.ts` | same file (P5, P6) |
| E, G. Evaluation | `architect_eval_v2.py`, `evaluation_v2/` (8 cases), `deploy/make_evaluation_cases_v2.py` | `tests/test_stab4_evaluation_protocol.py` (11) |
| F. Simulation | `consistency.py`, Studio `RecordEditor.tsx`, `lib/records.ts` | `tests/test_stab5_workflow_consistency.py` (5), Studio `records.test.ts` (4), 8 browser checks |

**Defects found by this sprint's own verification, and fixed:** a rounding fault in the new ledger check, caught by
the real ledger of 17 November (4.4188746 stored, 4.418875 stated); validating a malformed model answered
"internal error" (GAP-086); Studio's graph could stay invisible after an unrelated refresh (GAP-087); the test
suite left 27 GB of temporary folders behind (GAP-088). **A correction to yesterday's report:** it gave the
spending as 4.418874 USD and 5.581126 left; the ledger and the platform's own view always said **4.418875 and
5.581125** (two rounded subtotals had been added by hand). The documents are corrected, with the correction said.

## 2. Reliability evidence

### 2.1 The spending ledger (P0, GAP-085: fixed)

| Requirement | State |
|---|---|
| Independent of the deployment | The ledger is a file outside the deployment, named by the configuration and by the owner's authorisation |
| A replacement deployment cannot reset spending | The authorisation records the ledger's identity, entry count, fingerprint and settled amount; an empty, older or different ledger **serves nothing** |
| No silent replacement by an empty database | A missing ledger is never created by the platform. A new one needs `--new-ledger` and a stated opening balance with its evidence |
| Transactional, concurrent, idempotent | One transaction per check-and-reserve; 24 parallel reservations from two connections reserve exactly the 5 the budget allows; a request id is charged once |
| Uncertain outcomes stay charged | Unchanged; in addition, a call a process died in is marked uncertain at the next start and no longer blocks the next call |
| Fails closed | Missing, empty, damaged, foreign, older: nothing is sent; the platform itself keeps working |
| Isolated by workspace | One workspace's entries never count for, or show in, another |
| History and remaining budget | Shown per period in the API and in Studio |
| Backup and recovery | A backup carries the ledger; a restore keeps a ledger that is ahead and stops on a different one |
| No credential or content | Amounts, counts, request identifiers, outcomes |

**Previous spending preserved.** The ledger of 17 November was put back from its file and reconciled: same
identity from the deployment's copy and from the evidence copy, 27 entries, 24 settled, 3 released, every entry
equal to the evidence export, **4.418875 USD spent, 5.581125 USD left of 10**; the evidence file is unchanged by
being read. The evaluation deployment is bound to it and reports `authorised` with those figures.

**Not reconciled:** the provider's invoice. It can only be read in the owner's account.

**What remains possible:** an operator who deliberately creates a new ledger and states a false opening balance.
That is now explicit and recorded, not silent. And the ledger does not survive the loss of the machine that holds
it: a durable location is decision D31.

### 2.2 Structured output (GAP-082: open, the owner's decision)

The two answers lost on 17 November each carried one property the contract does not name
(`$.relationships[2]: unexpected 'name_hint_removed'`, `$.rules[1]: unexpected 'name_placeholder_removed'`): one
stray property on one element. Neither was an attempt to obtain anything. 2 of 24 is too few to state a rate
(between about 2 % and 26 %).

Done, without changing the rule: every violation is classified (a stray property is told from an unknown section
or a property named like a permission, a release, a tool or an endpoint); the instructions end with the closed
list of allowed property names; the reservation covers them; an evaluation keeps a refused answer as evidence.
**The effect on the rate is not measured**: that needs paid calls.

| Option | Security | Extra AI cost | The two losses |
|---|---|---|---|
| 1. Refuse the whole answer (today) | Strongest, simplest | none per call; about 0.18 USD per lost answer | lost |
| 2. Normalise named formatting defects only | as 1 | none | still lost |
| 3. One bounded repair request | rule intact; a new path where the model reads about its own refused answer | about 0.2 USD per repair; every request reserves twice as much | probably recovered |
| 4. Strict envelope, then refuse per element | safe only if an unknown section or a sensitive property still refuses everything | none | recovered, minus one element each |

Recommendation (not a decision): option 4 with those conditions. Detail:
[decision record](AUTOLOGY_STRUCTURED_OUTPUT_DECISION_RECORD.md).

### 2.3 Proposal lifecycle and provenance (GAP-080, GAP-081: fixed)

A user leaves Studio, comes back, and resumes: the stored proposal is listed, reopened at any revision, compared
with another revision, and traced to the draft and the release it led to. Nothing is generated again. An element
that cites an answer keeps the citation however the model wrote it; what cannot be established is marked
**unknown**, never filled in. Both were demonstrated with the sandbox; **neither has been exercised with a real
model since** (no call was authorised).

### 2.4 Prompt injection (GAP-083: open, the owner's decision)

Version 1 of the measure and its recorded results are untouched (pinned by a test). Proposed beside it: judge
what was done with the instruction. Replaying the 17 saved real answers, without any call:

| | executed | incorporated | for a person to read | reported |
|---|---|---|---|---|
| 17 answers | **0** | **1** | 1 | 15 |

The one incorporated answer suggested a role named `workspace_admin`: a real fault under either version. A
caution stated in the protocol: the first word list for "says it was set aside" recognised 9 of the 15 reports
and was widened after reading them; this is why an ambiguous statement goes to a person instead of being scored.

### 2.5 Remaining failure modes

* An answer outside the contract is still refused whole (GAP-082), after being paid for.
* Answers take one to two minutes; rate limits and outages have never been met with the real provider.
* The provider still refuses the contract as a grammar; whether smaller schemas compile is untested (a probe is
  proposed, under 0.10 USD, within an authorised run).
* One provider, one model. No independent reviewer has judged any proposal.
* The record editor needs the unrestricted data permission (D24 undecided).
* The ledger's durable location (D31).

## 3. Studio evidence (sandbox; screenshots in `studio/web/e2e/screenshots/`)

| | Browser checks |
|---|---|
| **Reopened stored proposal** | After a page reload: the session is listed with its revisions, its generator and the draft saved from it; reopened at revision 2 of 2 with the brief and the answers (`desktop-onboarding-session.png`) |
| **Revision comparison** | "Revision 1 → revision 2": added, removed, changed (and how), the answers given in between |
| **Provenance of selected elements** | "Why was this proposed?": the reason, the origin, what is cited with its text, who accepted it. An element from a template says its origin is the architect's inference; nothing is invented |
| **Synthetic-record editing** | A person holding data administration (which two people each acknowledge as unrestricted) creates and changes a record; the form shows the change before sending; a wrong type is refused in the form; a save over a record changed meanwhile is refused by the engine in its own words; a member without the permission reads only (`desktop-record-editor.png`) |
| **Validation findings** | Workflow consistency findings are shown beside the engine's validation, each with why it may matter and what a person could do; nothing is blocked |
| **Release and simulation** | The existing journey still passes end to end: two-person release, stored runs (autonomous, approved, refused, cancelled), audit, readiness |
| **No regeneration** | Leaving, reopening, comparing and reading added no revision |

On the real evidence of 17 November, without any call: the consistency check finds, in the ground-handling model
as first released, that `complete_turnaround` can complete a turnaround whatever the state of its operational
conflict, which is what the stored run exposed; it finds nothing of that kind in release 3.

**Not demonstrated:** any of this with a real model. A completed simulated run is not evidence of a change in a
real system; Production stays unavailable.

## 4. Evaluation evidence

| | |
|---|---|
| Original benchmark | **Preserved.** The five cases, thirteen measures, thresholds and the two recorded results are byte for byte what they were (fingerprints pinned by `tests/test_stab4_evaluation_protocol.py`) |
| New protocol | [Version 2, proposed](AUTOLOGY_ARCHITECT_EVALUATION_PROTOCOL_V2.md): 17 automated measures, expert judgement apart. **Not in force** |
| Held-out scenarios | Eight: building permits, pharmaceutical batch release, telecom outage restoration, scholarship awards, and four adversarial variants (hostile instruction in a clarification answer, a document, a business record, a tool result) |
| Automated results | Reference answers: 17 of 17 (they check the scorers). Template test double: 8 of 17. **No language model was run under version 2** |
| Human review | [Form prepared](AUTOLOGY_ARCHITECT_EXPERT_REVIEW_FORM.md) for two independent domain reviewers; a blank form per proposal and an agreement calculation exist. **No reviewer engaged, no score** |
| Real-provider results | **None in this sprint.** Tokens and cost: zero |

### Third real-model evaluation: Ready for controlled re-evaluation — Awaiting owner authorization

| Condition | State |
|---|---|
| D7/D10 authorisation still valid | Yes, until 23 November 2026 |
| Exact model and workspace unchanged | Yes: `claude-opus-5-5`, workspace `evaluation` |
| Authoritative ledger includes all prior spending | Yes: 27 entries, 4.418875 USD, reconciled with the evidence |
| Remaining ceiling against the provider's billing | **Not done**: the invoice is in the owner's account |
| Owner approved the additional evaluation | **No** |
| Test matrix and criteria frozen | **No**: GAP-082 and GAP-083 are undecided |
| Provider's retention terms still acceptable | **To be confirmed by the owner** (accepted on 16 November for synthetic data) |
| Synthetic data only | Yes |

## 5. Decisions for the owner (nothing is ratified by implication)

| # | Decision | Recommendation |
|---|---|---|
| D30 f (GAP-082) | An answer with a stray property: refuse whole, or refuse per element inside a strict envelope? | Per element, with an unknown section or a sensitive property still refusing everything |
| D30 g (GAP-083) | Ratify evaluation protocol version 2 and its behaviour-based injection measure, beside version 1? | Yes, after reading its thresholds |
| D30 h | Approve one third paid evaluation (about 1.8 USD for version 1's five cases; about 2.9 USD more for version 2's eight; 5.58 USD left; before 23 November)? And the compile probe (under 0.10 USD)? | After f and g, once, on a frozen system |
| D31 | Where the authoritative ledger lives durably | A volume or database server that outlives any machine |
| D32 | May a run involve several governed agents? ([design](AUTOLOGY_MULTI_AGENT_COORDINATION_DESIGN.md)) | After the architect is stable |
| D24 | The narrower `operate` permission (the record editor needs the unrestricted one today) | Unchanged from its specification |
| D26 | Readiness weights | Unchanged |
| D27, D28, D29, D30 a–e | Engineering defaults awaiting confirmation | Unchanged |
| — | Two independent domain reviewers for the expert form | To be named |
| — | Compare the ledger (4.418875 USD) with the provider's invoice | Owner |

## 6. R2 assessment

**R2 is not closed.** The live Studio demonstration of 17 November does not close it.

| Exit criterion | State |
|---|---|
| A real provider that meets the evaluation thresholds | **Open.** Run once: 5 of 13, then 3 of 13. No run since (GAP-052 partly fixed) |
| Independent judgement of proposals | **Open.** Form prepared, no reviewer |
| Ratified readiness weights (D26) | **Open** |
| Documents as input to the architect | **Open** (passages can be given to the architect in code and in the proposed protocol; no upload in Studio) |
| The two named industry blueprints | **Open** |
| Engine decomposition (ARC-0) | **Partial** (the engine class did not grow in this sprint: its size limit held) |
| Spending control across deployments | **Met in the repository** (this sprint); durable location open (D31) |
| A design session that survives leaving Studio | **Met with the sandbox** (this sprint) |

## Classification

| Capability | Status |
|---|---|
| Ledger that outlives a deployment | **Implemented and tested; reconciled with real spending** |
| Proposal lifecycle, provenance, record editor, consistency findings | **Demonstrated in Studio with the sandbox**; not with a real model |
| Classified refusals of answers | **Tested with doubles**; effect on the loss rate not measured |
| Evaluation protocol version 2 | **Proposed**; checked on reference answers and on the saved real answers; no real run |
| Third real evaluation | **Not run: awaiting owner authorization** |
| Several agents on one case | **Design only** |
