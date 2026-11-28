# Autology — D37 c and D37 d: owner decision package

*20 November 2026. Status: **for the owner. Nothing in this package is decided, and nothing in it was implemented.**
The defaults of 19 November stay in force as they are. Recommendations are engineering opinions; an unsigned form
is not authorization.*

Both decisions come from the same fact: the Engine can establish where a draft's content comes from only when it
is **identical** to content it stored. D37 c is about drafts written before it recorded anything. D37 d is about
content a person reworded.

---

## D37 c — Who answers for a legacy draft

A **legacy draft** is a draft revision with no provenance record: one written before store schema 22.

### What the Engine does today (verified 20 November)

| Situation | Behaviour | Evidence |
|---|---|---|
| Reading it | Reported as `legacy_unknown`; nothing is written into the old row | `tests/test_gap107_draft_origin.py::test_a_store_of_the_schema_before_is_upgraded_without_inventing_any_provenance` |
| Publishing it | Refused, 409 | `::test_a_draft_of_unknown_provenance_is_not_published_and_not_built_upon` |
| Saving it again | Compared with the model that runs, not with the legacy row. Elements of a proposal that nobody confirmed are refused. The rest is attributed to the person who saves, and the record says `reestablished_from_legacy`. **Nobody is asked to acknowledge anything** | The same test; `tests/test_d37_current_defaults.py::test_a_legacy_draft_is_re_established_without_any_acknowledgement` |
| Releases already approved | Untouched: the gate is on publishing a draft | The migration adds one nullable column |

### The three options

| | 1. As applied | 2. An administrator's acknowledgement first | 3. Refuse legacy drafts |
|---|---|---|---|
| Rule | Saving again re-establishes the draft; the saver answers for what is left | The same, but only after a named administrator recorded an acknowledgement for that exact revision | A legacy draft can never be re-established or published. Work restarts from the model that runs |
| Who answers for content of unknown origin | The person who saves it again | That person, **and** the administrator who allowed it to be taken on | Nobody: the content is not taken on |
| What it cannot do | Prove origin | Prove origin | — |
| Effort per legacy draft | None | One administrative act | The draft's work is redone |
| Risk | One person takes on unknown content by an ordinary save, perhaps without noticing | An acknowledgement becomes a routine click | Legitimate work is lost; pressure to copy it back by hand, which the Engine cannot detect (GAP-109) |
| Build | Nothing | One table, one route, one check, one screen | One check, one message |

**Recommendation for the owner's review: option 2.** It keeps the work, and it makes taking on content of unknown
origin a deliberate, attributable act by someone with authority, instead of a side effect of saving. This is a
proposal, not approval to build it.

### Option 2, specified (not built)

**What the acknowledgement attests.** Exactly this, shown to the administrator and stored with the record:

> Draft revision *N* of use case *U* (document hash *H*) was written before the Engine recorded where a draft's
> content comes from. Its origin is unknown and is not established by this acknowledgement. I allow it to be
> classified again by the Engine and attributed to the person who saves it.

It attests nothing about where the content came from, and nothing about whether it is right. It is not a review of
a proposal, not a validation of the model, and not a publication.

| Aspect | Proposal |
|---|---|
| Who may give it | A **person** who is a workspace administrator. Never a service identity. Sub-question for the owner: must it be a different person from the one who then saves the draft? (Recommended: yes) |
| What it covers | One draft revision of one use case, by number and by the hash of its document. A later revision needs its own |
| Where it is enforced | The Engine: `ArchitectService.save_draft`, when the draft before is a legacy one. Studio shows the Engine's state and adds no rule |
| Record | A new append-only table (store schema 23, additive): revision, document hash, who, when, the statement's version, an optional note. Who and when come from the token and the Engine's clock |
| Without it | 409: "this draft was written before the Engine recorded provenance; an administrator must acknowledge revision N before it can be re-established. Nothing was saved." |
| A way out without it | Saving the model that runs, unchanged, is always allowed: it carries nothing of the legacy draft |
| After it | Exactly today's classification. The provenance record gains who acknowledged, and when |
| What it never replaces | The review of proposal elements, the loader's validation, publication by a second person, the approval of a release |

| Topic | Effect |
|---|---|
| Migration | One new table. No existing row is rewritten; no provenance, approval or origin is added to old drafts; releases and fingerprints are unchanged |
| Compatibility | A client that re-saves a legacy draft receives 409 until the acknowledgement exists. Drafts that already have a provenance record are unaffected |
| Operational effort | One administrative act per legacy draft that someone wants to keep. Only the latest draft of a use case matters. The number in a given deployment is a read-only count of use cases whose latest draft has no provenance |
| Audit | The acknowledgement row; the provenance record of the re-established revision names it |
| Rollback | Remove the requirement; the acknowledgements stay as history. Software from before refuses a schema-23 store, as it refuses schema 22 today: going back means restoring the backup taken before the upgrade. No downgrade is promised |

### Required cases

| Case | Today | Under option 2 | Status of the test |
|---|---|---|---|
| A draft from before schema 22 | Read as `legacy_unknown`; older software refuses the upgraded store | Unchanged | **Passed** (existing) |
| Rejected or unconfirmed content when saved again | Refused, 409 | Unchanged, after the acknowledgement | **Passed** (existing) |
| No acknowledgement where one is required | Not applicable | 409, nothing saved | Planned |
| Acknowledgement by a member without the office, or by a service identity | Not applicable | 403 | Planned |
| Acknowledgement of a revision that is no longer the latest | Not applicable | 409 | Planned |
| A member of another workspace | Sees nothing (404) | 404 for the acknowledgement as well | Existing for drafts; planned for the new route |
| Attribution after re-establishment | The saver; `reestablished_from_legacy` | The saver, with the acknowledger named | **Passed** for today's behaviour; planned for the addition |
| An approved release | Unchanged by migration and by re-establishment | Unchanged | Planned as an explicit test (today: covered only by the migration tests keeping every row) |
| Restore from a backup | Rows come back as they were, legacy ones included | Acknowledgements come back with them | Planned (backup and restore are tested in `tests/test_ops1_recovery_and_activation.py`, not with legacy drafts) |

### Decision form — D37 c

| | |
|---|---|
| Question | When a draft with no provenance record is saved again, what is required, and who answers for its content? |
| Option selected (1, 2 or 3) | |
| If 2: must the acknowledger differ from the person who saves? | |
| Implementation scope authorised | |
| Activation scope (where it applies; none outside simulation is implied) | |
| Limitations accepted (origin is never proven) | |
| Decision-maker | |
| Date | |
| Durable reference (register row, message or signed copy) | |

---

## D37 d — The same element, reworded by hand

### What the Engine does today (verified 20 November)

| A draft adds or changes an element that… | With a proposal named | With no proposal named |
|---|---|---|
| …is identical to a kept element of a stored proposal | Saved, linked to the decision | Saved, linked to the decision |
| …is identical to a rejected or unconfirmed one | 409 | 409 |
| …has that element's **identity** and **other content** | 409: an edit needs a recorded correction | **Saved as the author's own, and flagged** in the record |
| …has **another identity** (renamed, split, retyped) | Saved as the author's own | Saved as the author's own, **no flag** |

Evidence: `tests/test_gap107_draft_origin.py` (the search over all stored proposals, whatever the request names);
`tests/test_d37_current_defaults.py::test_a_copy_under_another_name_is_not_detected`.

**What the second person sees when publishing: the revision number and the author. Not the flags.**
(`::test_the_publisher_sees_the_revision_and_its_author_and_nothing_of_the_provenance`). The flags exist in the
record and are returned to the designer.

### What no option can do

Prove where typed text came from. The Engine compares identity and content. An unconfirmed element copied under
another name, split in two, or brought from a tool outside Autology is indistinguishable from a person's own work.
**GAP-109 stays open under every option.** A similarity heuristic would not close it:

| Heuristic | False positives | False negatives |
|---|---|---|
| Same name, any content (option 2 below) | Any person who legitimately models "Supplier" after a proposal once inferred a "Supplier" | A rename |
| Similar content under another name | Common shapes: two entities with a name, a status and a date look alike in every domain | Rewording, reordering, splitting, translating |
| Text similarity of descriptions | Stock phrases | Any paraphrase |

If one is ever wanted, it should stay advisory (a note for the reviewer), never a refusal, and that would be a
separate decision.

### The three options

| | 1. As applied | 2. Refuse | 3. Show the flags to the second person |
|---|---|---|---|
| Rule | Same identity, other content, no proposal named: saved, attributed, flagged | The same case is refused, 409: correct the element in the review, or name it differently | As 1, and the publisher is shown the flags, the differences and what cannot be established, before publishing |
| Legitimate manual modelling | Kept | **Blocked** for any name a proposal ever used and nobody confirmed | Kept |
| What the second person knows | Revision and author | Revision and author | Which elements coincide with unconfirmed proposal elements, how they differ, and that origin is unproven |
| Detects a rename | No | No | No |
| Build | Nothing | One branch in the classification | An addition to what the Engine returns to a publisher; a check that the publication is of what was shown; a panel in Studio |

**Recommendation for the owner's review: option 3, without a mandatory acknowledgement.** The independent
publisher is the control that exists for content whose origin cannot be proven, and today that person is not shown
what the Engine knows. A recorded acknowledgement of the flags should be added only if the owner asks for it: it
adds a click and proves nothing more. This is a proposal, not approval to build it.

### Option 3, patch plan (not built)

| Step | Where | What |
|---|---|---|
| 1 | Engine, `GET …/releases` (for members who may publish) | The draft entry gains a summary of the provenance record the Engine already holds: mode, counts, each flag (element, proposal, why), `includes_unknown`, `cannot_prove`. For a flagged element: which parts differ from the proposal's version. Sub-question: names of the differing parts only, or both contents? |
| 2 | Engine, `POST …/publish-draft` | The request names the revision (as today) and carries the digest of the provenance summary that was shown. A digest that does not match the stored record: 409, read again. The decision is bound to what was reviewed |
| 3 | Only if the owner selects it | `acknowledged_flags: true` is required when flags exist; who and when are recorded with the publication |
| 4 | Studio, release screen | Shows steps 1 to 3 from the Engine's answer. It adds no rule |
| Unchanged under every option | Engine | The author cannot publish; a service identity cannot publish; a draft without provenance is not published; the search over all stored proposals ignores what the client says about origin |

Showing the flags, or acknowledging them, is not evidence that the content is the author's own, and not evidence
that it is right.

### Required cases

| Case | Expected | Status |
|---|---|---|
| A legitimate manual draft | Saved, attributed, published by another person | **Passed** (`test_a_model_authored_by_hand_is_saved_attributed_and_published_by_another_person`) |
| Same identity, changed content | Flagged (option 1 and 3) or refused (option 2) | **Passed** for the flag; planned for a refusal or for display |
| Changed identity, unknowable origin | Saved, no flag; the record says what it cannot prove | **Passed** (`test_a_copy_under_another_name_is_not_detected`): the limit, pinned |
| Proposal omitted, swapped or stale | Found or refused whatever the request says | **Passed** (`test_naming_no_proposal_changes_nothing`, `test_a_swapped_foreign_or_stale_reference`) |
| Forged author, time or decision | Not taken from a request | **Passed** (`test_forged_decision_fields_are_not_taken`) |
| A concurrent edit | 409 on the draft revision read; under option 3, 409 when the provenance shown is no longer the stored one | **Passed** for drafts (`tests/test_act1_solution_configuration.py`); planned for the digest |
| An unpublished legacy draft | Not published | **Passed** |
| Publication by the author or by a service identity | 403 | **Passed** |
| The publisher is shown the flags | Shown, for the exact revision | **Not built.** Today's behaviour is pinned by a test |

### Decision form — D37 d

| | |
|---|---|
| Question | In a draft that names no proposal, what happens to an element that has the identity of a proposal's unconfirmed element and other content? |
| Option selected (1, 2 or 3) | |
| If 3: differing part names only, or both contents? | |
| If 3: is a recorded acknowledgement of the flags required to publish? | |
| Implementation scope authorised | |
| Activation scope | |
| Limitations accepted (GAP-109 stays open; no option proves origin) | |
| Decision-maker | |
| Date | |
| Durable reference | |
