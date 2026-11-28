# Autology — decision record: answers outside the architect's contract (GAP-082)

*17 November 2026. Status: **for the owner's decision (D30 f).** Nothing below changes what is refused today.
The rule in force is unchanged: an answer that does not match the contract is refused whole, whatever it cost.*

## 1. What happened

The provider refuses the architect's contract as a grammar ("The compiled grammar is too large", GAP-072), so the
schema travels in the instructions and nothing but Autology's own check holds a model to it. On 17 November,
**2 of 24 paid answers (8 %) were refused whole**, each for one property the contract does not name:

| Answer | Violation, as recorded | Class | Cost |
|---|---|---|---|
| Run 2, `airline-disruption`, first answer | `$.relationships[2]: unexpected 'name_hint_removed'` | one stray property on one element | 0.35 USD for the two |
| Run 2, `global-logistics`, second answer | `$.rules[1]: unexpected 'name_placeholder_removed'` | one stray property on one element | |

Neither answer was kept: the gateway discards what it refuses. What is known is the message. **Two answers are
too few to state a rate**: with 2 of 24, the true proportion lies anywhere between about 2 % and 26 % (95 %).

Neither violation was an attempt to obtain anything: no section, permission, release, tool or endpoint. But the
check did its job the only way it could: it cannot know intent, and it refused.

## 2. What has been done without changing the rule (this sprint)

| Change | Effect |
|---|---|
| Every violation is classified (`ai.violation_classes`): `stray_property`, `unknown_section` (top level), `sensitive_property` (named like a permission, grant, release, setting, policy, tool, endpoint, credential, budget, self-review, anywhere), `missing`, `wrong_type`, `not_allowed_value` | A lost answer is told from an unsafe one, in the error, the API (`details.violations`) and the evaluation report (`failures`) |
| The instructions now end with the **closed list of property names, object by object**, derived from the schema (`ai.allowed_keys`) | Aims at the cause: a model inventing a key. **Not measured**: measuring needs paid calls |
| The reservation made before a call covers those instructions | The ceiling stays a ceiling |
| An evaluation run with `--save` keeps a refused answer as it came (`<case>-<n>.refused.json`), marked refused, with every violation | The next loss can be examined and replayed against any option below, at no further cost |

Tests: `tests/test_stab2_structured_output.py` (8), `tests/test_claude2_anthropic_adapter.py`.

## 3. The four options

Common to all: the engine's validation of every element stays (`modeling.validate`); nothing is applied without a
person; a proposal only adds. A stray key cannot reach a model document under any option, because elements are
rebuilt from the contract's own keys (`architect._items`, `_value`), never copied.

| | 1. Refuse the whole answer (today) | 2. Normalise named harmless defects | 3. One bounded repair request | 4. Strict envelope, then refuse per element |
|---|---|---|---|---|
| What it does | Any violation refuses everything | Before the check, undo a closed list of *formatting* defects only: a code fence (already done), a byte-order mark, surrounding whitespace | On a refusal whose violations are all `stray_property`, ask once more, giving the list of violations; check the new answer whole | The top level must match exactly; inside a section, an element with a violation is rejected with the reason, like an element the engine rejects; the rest stand |
| The two losses of 17 Nov | Lost | **Still lost** (a stray property is not formatting) | Probably recovered | Recovered, minus one relationship and one rule |
| Security | Strongest and simplest: no judgement about which violation matters | Same as 1 if the list stays formatting. It must never grow into deleting properties: that would be silent stripping | The rule itself is intact (each answer is checked whole). New surface: the model reads a description of its own refused answer; a hostile text could try to steer the repair. Mitigation: only the violation list is sent, never the refused text; one attempt; never for `unknown_section` or `sensitive_property` | The contract is no longer all-or-nothing. Safe only with three conditions: an unknown top-level section refuses everything; any `sensitive_property`, anywhere, refuses everything; a rejected element is shown with its reason, never repaired or half-kept |
| Extra AI cost | None per call; about 0.18 USD lost per refused answer, plus the repeat | None | About 0.2 USD per repair (a second full answer), only when it happens; the reservation must cover two answers, so **the per-request ceiling of 1 USD allows it but each request reserves twice as much** | None |
| Complexity | None | Very small | Medium: gateway retry path for one failure kind, a repair prompt, ledger accounting for two answers under one request, new failure modes | Medium: two-phase check (envelope, then element), reasons carried to Studio; no new call path |
| Expected reliability | As measured: 22 of 24 usable | As 1 | Higher than 1; not certain (the repair can fail too) and slower by one answer when it happens | Highest for this failure: the answer is always usable when the envelope is; elements may be missing |
| What a user sees | "The architect gave no usable proposal", after a minute or two | Same | A longer wait, then a proposal | A proposal, with "1 relationship rejected: property not allowed" |

## 4. Other approaches examined

| Approach | Finding |
|---|---|
| **A smaller schema the provider can compile** | The structural fix: with the provider's grammar a stray property cannot be produced at all. A first attempt (no optional property) was refused on 17 Nov. Whether per-section schemas compile can only be learnt from the provider: a refused request costs nothing, an accepted one is billed. **Proposed as a probe within an authorised run** (one request per section with a 16-token output limit: under 0.10 USD in all) |
| **One request per section, assembled deterministically** | Makes each schema small (may compile) and each loss small (one section). Costs more input (the brief is sent six times; cached after the first), and cross-references (an action naming an entity proposed in another call) need an ordering: entities, then relationships, then actions, rules, goals, the case template. A larger change to how the architect asks; not started. Worth deciding after the probe |
| **Keeping a refused answer in the use case** (quarantined, not a proposal) | Would let an owner-approved option recover it later without paying again. Stores text that failed the contract; needs retention and access rules. Not done: the evaluation's `--save` covers the evidence need |

## 5. Recommendation (not a decision)

1. **Option 4, with its three conditions**, for `stray_property` and for `missing`, `wrong_type` and
   `not_allowed_value` *inside one element*. It costs nothing, loses the least, and treats a malformed element
   exactly as the engine already treats an invalid one.
2. **Keep option 1 for the envelope**: an unknown section or a property named like something the contract must
   never carry refuses the whole answer, as today.
3. **Not option 3** for now: it buys less than option 4 and doubles what each request reserves.
4. **The compile probe** in the next authorised run, before deciding on per-section requests.

Until the owner decides, option 1 stays in force everywhere.

## 6. What the owner is asked

| # | Question | If "yes" | If "no" or no answer |
|---|---|---|---|
| a | Refuse per element inside a strict envelope (option 4, with its conditions)? | Implemented and tested before the next evaluation; the evaluation protocol states it | Option 1 stays; about one answer in twelve was lost on the evidence so far |
| b | Allow the compile probe (under 0.10 USD) in the next authorised run? | One refused-or-tiny request per section; results recorded | Not done; the per-section design stays untested |
| c | Consider one bounded repair request (option 3) later? | Designed for a separate decision, with its cost | Not designed further |

## 7. The element-level design, built and validated; **not in force** (R2 cross-domain validation, 17 November)

Option 4 now exists as code that nothing in force calls: `autology/architect_elements.py`, function `triage`.
The gateway still refuses a non-conforming answer whole, and a test asserts both that it does and that no module of
the engine imports the new one (`tests/test_xdom3_element_level_rejection.py`, 15 tests).

| What the owner asked for | What `triage` does | Test |
|---|---|---|
| Strict top-level envelope | An unknown section, a missing section, a section of the wrong type, or any defect outside the six model sections refuses the whole answer | E2 |
| Global rejection for sensitive or governance-related properties | A property named like a permission, a grant, a release, a setting, a policy, a tool, an endpoint, a credential, a budget or self-review, **at any depth**, refuses the whole answer; no partial reading is offered | E2 |
| Element-specific findings | Each element of the model sections is checked on its own; a rejected one is reported with its section, position, name and every reason | E3 |
| Dependency integrity | What refers to a rejected element is rejected with it, to a fixed point: a relationship of a rejected entity, an action or rule or goal that names it, a rule on a rejected action, a case template that follows a rejected relationship. A rejected entity or action that cannot be named refuses the whole answer | E4 |
| Explicit rejection | A defective element is dropped whole. No property is removed to make it pass; the answer given is never changed | E3 |
| No silent defaults | A missing or mistyped property is a rejection, never a filled-in value | E5 |
| No automatic activation | The result is marked partial and lists what must happen before use; the module applies and stores nothing; what is kept goes through the same validation as any proposal | E6 |
| A limit | More than a quarter of the elements rejected: the whole answer is refused (the rejections are still reported) | E7 |
| Full audit | A digest of the answer as received, each rejection with its place and reasons, the classes of violation, the decision and the policy's name | E8 |

**Replay on stored evidence (no call, no cost).** The 17 stored answers of the real evaluation, put back in the
contract's form (237 elements), are all accepted unchanged. With the two recorded defects put back at their
recorded places:

| Case | Defect as recorded | In force (option 1) | Proposed (option 4) |
|---|---|---|---|
| `global-logistics` | `$.rules[1]: unexpected 'name_placeholder_removed'` | whole answer refused (29 elements lost) | 1 rule rejected by name, 28 elements kept |
| `airline-disruption` | `$.relationships[2]: unexpected 'name_hint_removed'` | whole answer refused (10 elements lost) | 1 relationship rejected by name, 9 elements kept |

Limits of this evidence, stated plainly: the two refused answers themselves were not kept, so the replay rebuilds
contract-form answers from the stored proposals of the same cases and re-inserts the defect where the log says it
was. It shows what the policy would do with such a defect; it does not show how often a model produces one.

**What is still needed before it could be put in force**, if the owner says yes to question (a): the call from the
gateway behind a configuration switch that defaults to today's rule; the rejections carried into the stored
revision and shown in Studio beside the proposal; the evaluation protocols stating which policy a result was
obtained under; a decision on whether an answer accepted with rejections counts as "usable" in
`answer_reliability`.
