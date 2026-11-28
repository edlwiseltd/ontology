# Autology — D36 and D37: ratification package

*19 November 2026. Status: **prepared for the owner; nothing here is ratified.** D36 a–e are engineering defaults
applied in the governed-operations sprint. D37 a–e are the engineering defaults added by the provenance sprint.
All ten are in force in the code as reversible defaults. **No approval of any of them was found** in the
repository, in the directives, or in any message of the owner; the directive that asked for this package says
itself that it implies no decision. Running this sprint is not a ratification.*

How to read a sheet: what the default is and where it is enforced; whether it is still the actual behaviour
(verified in this sprint, with the tests that prove it); what it costs clients; how to undo it; what undoing it
would bring back.

## Summary

| # | Default | Still the actual behaviour? | Recommendation |
|---|---|---|---|
| D36 a | A draft may not take from a proposal an element that was rejected, or inferred and never confirmed | **Changed in this sprint: strengthened.** As recorded on 19 November it applied only to a draft that *named* a proposal. It now applies to every draft (D37 a) | Confirm together with D37 a |
| D36 b | Studio never selects an inferred element for the person | Yes | Confirm |
| D36 c | A decision is about the element as it was shown; a rejected element proposed again stays rejected | Yes | Confirm |
| D36 d | A person may correct an element; a correction is that person's confirmation of the corrected content | Yes; **extended**: Studio now offers it (same route, no second authority) | Confirm |
| D36 e | The application runtime draws manifest format 1 for Engine API 1, and nothing else | Yes | Confirm |
| D37 a | The Engine establishes the provenance of **every** draft; naming no proposal escapes nothing | New | Confirm |
| D37 b | A draft whose provenance was never established is not published | New | Confirm |
| D37 c | A legacy draft saved again is classified again; what is left is attributed to the person who saved it | New | **Owner's choice** (see the sheet) |
| D37 d | An element with a proposal element's identity and other content, in a draft that names no proposal, is saved as the author's own and flagged | New | **Owner's choice** |
| D37 e | A review decision may state the review version it was made over; Studio always does | New | Confirm, or make it mandatory |

---

## D36 a — What a draft may take from a proposal

| | |
|---|---|
| **Default** | An element identical to one a stored proposal holds enters a draft only if it is kept there: stated and not rejected, accepted, or corrected to exactly that content. Otherwise 409 and nothing is saved |
| **Enforced at** | `ArchitectService.save_draft` (`autology/architecting.py`) → `proposal_review.classify` (`autology/proposal_review.py`); reached only through `POST /api/v1/model/draft` |
| **Rationale** | An inference of a model is not a business fact until a person accepts it. Before this default a draft could carry unreviewed inferences into a release approved by people who never saw them flagged |
| **Verified** | `tests/test_rev1_proposal_review.py::test_review_through_the_api_persisted_attributed_and_enforced`, `::test_what_a_draft_may_take_from_the_proposal_it_names`; `tests/test_gap107_draft_origin.py::test_naming_no_proposal_changes_nothing`, `::test_rejected_then_proposed_again_and_corrected_then_changed`; `tests/test_stab3_proposal_lifecycle.py` |
| **Change since it was recorded** | The second half of the recorded text ("a draft that names no proposal is unaffected and records no provenance") is **no longer true**. That exemption was the bypass registered as GAP-107; see D37 a |
| **Compatibility** | A client that saved a proposal's content without recording a review now receives 409. This was real inside the project: 22 existing tests in four modules did exactly that in their fixtures and had to record the review first (`tests/test_act3_persistent_simulation.py`, `tests/test_arch3_architect_and_evaluation.py`). No stored data changes |
| **Rollback** | Remove the refusal in `ArchitectService.save_draft` (keep the classification and its record). No schema change is involved |
| **If reversed** | Unreviewed inferred elements and rejected elements can enter a draft again; the second person at publication becomes the only control, without any flag telling them what was inferred |

## D36 b — Studio selects nothing inferred

| | |
|---|---|
| **Default** | When a proposal is opened, inferred elements are not selected. Selecting them, one by one or all at once, is an explicit act |
| **Enforced at** | Presentation only: `studio/web/components/OnboardingView.tsx`. **Not a security control**: the control is D36 a, in the Engine |
| **Rationale** | A preselected box is a confirmation nobody gave |
| **Verified** | Browser, two domains: "what the architect inferred is not selected for the person…", "selecting the inferred elements is one explicit act…" (`studio/web/e2e/domains.mjs`) |
| **Compatibility** | One more click for a person who agrees with everything. None for the API |
| **Rollback** | Restore the preselection in the component. The Engine still refuses unconfirmed elements, so saving would then record the selection as that person's acceptance: the act would be less visible, not absent |
| **If reversed** | Acceptance by default returns to the screen. The recorded evidence (run 2: 41 of 114 elements inferred) shows how much would be accepted unseen |

## D36 c — A decision is about the element as it was shown

| | |
|---|---|
| **Default** | A decision holds in a later revision only while the element is unchanged; a changed element is undecided again. A rejected element that a later revision proposes again is still rejected and flagged; it is never confirmed by reappearing |
| **Enforced at** | `proposal_review.standing` (computed from the append-only history on every read; never stored) |
| **Rationale** | Otherwise a model could obtain a confirmation for one content and change it in the next revision, or wear a reviewer down by repetition |
| **Verified** | `tests/test_rev1_proposal_review.py::test_a_decision_is_about_the_element_as_it_was_shown`, `::test_the_last_decision_wins_and_every_one_is_kept`; `tests/test_gap107_draft_origin.py::test_rejected_then_proposed_again_and_corrected_then_changed`, `::test_a_swapped_foreign_or_stale_reference` |
| **Compatibility** | A reviewer decides again when a later revision changes an element. Histories are kept; nothing is migrated |
| **Rollback** | A change to one pure function. No stored data depends on it, because the standing is never stored |
| **If reversed** | Stale confirmations would carry over to content nobody reviewed |

## D36 d — A person may correct an element

| | |
|---|---|
| **Default** | `POST /api/v1/architect/proposals/{id}/decision` accepts `corrected: [{id, value}]`. The correction replaces the element's content, is attributed to the person, needs no provider, and is validated like any element. It counts as that person's confirmation of the corrected content, and of that content only |
| **Enforced at** | `ArchitectService.decide_proposal`; `architect_corrections` (append-only; store schema 21) |
| **Rationale** | Without it a reviewer who disagrees with one field can only reject the element or pay for another provider call |
| **Verified** | `tests/test_rev1_proposal_review.py::test_a_correction_is_the_persons_and_is_validated_like_any_other`; `tests/test_gap107_draft_origin.py::test_rejected_then_proposed_again_and_corrected_then_changed` (the content before the correction is refused); browser: "a correction is made in fields beside the proposed content…" |
| **Extended in this sprint** | Studio now has the editor (GAP-108). It uses this route and adds no authority: `studio/web/components/ElementEditor.tsx`, `studio/web/lib/correction.ts` |
| **Compatibility** | Additive: a request without `corrected` behaves as before. Schema 21 is additive |
| **Rollback** | Stop accepting `corrected` (400). Recorded corrections stay in the table and in the history; elements corrected earlier would stand as "corrected" until decided again |
| **If reversed** | Reviewers lose the cheapest fix, and the pressure to accept an almost-right element returns |

## D36 e — The runtime draws only what it knows

| | |
|---|---|
| **Default** | The application runtime draws manifest format 1 bound to Engine API 1. Anything else is refused with the reason, before anything is drawn |
| **Enforced at** | `studio/web/runtime/model.ts` `incompatibility` (a correctness guard in the browser, **not a security boundary**; the Engine authorises every request whatever is drawn) |
| **Rationale** | A renderer that guesses at a newer format shows wrong screens that look right |
| **Verified** | `studio/web/tests/runtime.test.ts` (compatibility cases); browser: `studio/web/e2e/apps.mjs` |
| **Compatibility** | A future manifest format needs a runtime that states it draws it |
| **Rollback** | Remove the check in the shell |
| **If reversed** | Unknown formats would be drawn on a best-effort basis |

---

## D37 a — The Engine establishes the provenance of every draft

| | |
|---|---|
| **Default** | Every draft is classified when saved, by comparing what it adds or changes with every stored proposal. The mode (`architect_proposal`, `manual_authoring`, `derived_revision`) and its record are written by the Engine with the revision. A client's `origin` is checked and proves nothing; leaving it out changes no answer |
| **Enforced at** | `ArchitectService.save_draft`; `ConfigurationService.save_solution_draft` for a configuration saved before any model draft; `model_drafts.provenance` (store schema 22) |
| **Rationale** | Closes GAP-107: the earlier check applied only when the draft named a proposal, so leaving the reference out escaped it |
| **Verified** | `tests/test_gap107_draft_origin.py` (10 tests; the 14 negative cases of the directive are mapped in its header) |
| **Compatibility** | See D36 a. `GET /api/v1/model/draft` gains `provenance` (additive). Schema 22 adds one nullable column |
| **Rollback** | Software: restore the earlier `save_draft`. Data: the column can stay (unused); a store at schema 22 is refused by software that knows only 21, so going back means restoring the backup taken before the upgrade (the rule for every schema step) |
| **If reversed** | GAP-107 reopens |

## D37 b — No publication without an established provenance

| | |
|---|---|
| **Default** | `Platform.publish_draft` refuses (409) a draft revision that has no provenance record |
| **Rationale** | Rows written before schema 22 carry none. Nothing is written into them: an approval, an origin or a link that never existed is not fabricated. They are reported as `legacy_unknown` |
| **Verified** | `tests/test_gap107_draft_origin.py::test_a_draft_of_unknown_provenance_is_not_published_and_not_built_upon`, `::test_a_store_of_the_schema_before_is_upgraded_without_inventing_any_provenance` |
| **Compatibility** | A draft left unpublished before the upgrade must be saved once more before it can be published. **Releases already approved, and their fingerprints, are untouched**: the gate is on publication of a draft, not on releases |
| **Rollback** | Remove the check in `publish_draft` |
| **If reversed** | A draft of unknown origin could be published on the second person's review alone |

## D37 c — What happens to a legacy draft that is saved again (**owner's choice**)

| | |
|---|---|
| **Default (fail-closed prototype)** | The draft is compared with the model that runs, not with the legacy row. Elements of a proposal that nobody confirmed are refused. Everything else is attributed to the person who saves it again, and the record says `reestablished_from_legacy` |
| **Why it is the owner's** | It decides who answers for content of unknown origin. Attributing it to the person who re-saves is one policy; others are legitimate |
| **Alternatives** | (1) As applied. (2) Require an administrator's recorded acknowledgement before a legacy draft may be re-established. (3) Refuse legacy drafts altogether: they are discarded and rebuilt |
| **Verified** | The same test as D37 b |
| **Until decided** | The default stays: nothing of unknown origin is published without a person taking it on by name and a second person publishing it |

## D37 d — The same element, reworded by hand (**owner's choice**)

| | |
|---|---|
| **Default** | In a draft that names no proposal, an element with the identity of a proposal's unconfirmed element and *other* content is saved as the author's own and **flagged** in the record. In a draft that names the proposal it is refused: an edit needs a recorded correction |
| **What cannot be proven** | That hand-typed content was not copied or paraphrased from a proposal, or from any tool outside Autology. No server-side check can establish that, and the record says so (`cannot_prove`). The proportionate controls are: attribution to an authenticated person, the flag, and publication by a second person |
| **Alternatives** | (1) As applied. (2) Refuse any element whose identity matches an unconfirmed proposal element, whatever its content: stricter, and it stops a person from legitimately modelling "Supplier" by hand because a proposal once inferred a "Supplier". (3) Show the flags to the second person at publication (a Studio change; the data is already in the record) |
| **Verified** | `tests/test_gap107_draft_origin.py::test_a_model_authored_by_hand_is_saved_attributed_and_published_by_another_person` |

## D37 e — Deciding over the review one has read

| | |
|---|---|
| **Default** | A decision may carry `expected_version`. If the review moved on, nothing is recorded: 409 with the current review. Studio always sends it; the API does not require it |
| **Rationale** | Two reviewers at once must not overwrite each other silently. The history is append-only either way: without the field the last decision wins and both are kept |
| **Alternative** | Make the field mandatory: stricter, and it breaks API clients that do not send it |
| **Verified** | `tests/test_rev1_proposal_review.py::test_review_through_the_api_persisted_attributed_and_enforced`; browser: "when someone else reviewed meanwhile, the decision made here is refused…" |

---

## What ratification would change

Nothing in the code. Each row of the decision register would move from "applied default, awaiting confirmation" to
"confirmed by the owner on <date>", or to the alternative chosen, which would then be implemented.

## Requested

| # | Question |
|---|---|
| 1 | Confirm D36 a (as strengthened), b, c, d, e? |
| 2 | Confirm D37 a and b? |
| 3 | D37 c: alternative 1, 2 or 3? |
| 4 | D37 d: alternative 1, 2 or 3? |
| 5 | D37 e: optional as applied, or mandatory? |
