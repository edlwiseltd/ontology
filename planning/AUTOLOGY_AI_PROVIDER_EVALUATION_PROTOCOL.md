# Autology — protocol for evaluating a first real AI provider

*15 November 2026. Status: **prepared, not executed.** No real provider has been contacted. Executing this
protocol needs the owner's explicit approval of decisions D7 and D10 for a named workspace. Until then the engine
accepts one architect provider only, the sandbox test double (`"ai": {"provider": "sandbox"}`), which contacts
nothing. Closing GAP-052 ("never run with a real AI model") requires this protocol to be run and its evidence
kept.*

## 1. What the owner approves (and nothing more)

One record per workspace in the [decision register](AUTOLOGY_DECISION_REGISTER.md), naming:

| Item | To decide |
|---|---|
| Provider and model | One provider, one model identifier, the region or endpoint it is served from |
| Data classes | Which of `synthetic`, `model_design`, `business_records`, `personal_data` may be sent. Recommended for the first evaluation: `synthetic` and `model_design` only |
| Purpose | `architect.propose` only, or also `agent.decide` |
| Budget | A spending ceiling for the evaluation and per day (see §4) |
| Key custody | Who creates the provider key, where it is held (an environment variable of the platform process under the workspace's prefix; never a file in the repository), who can rotate and revoke it |
| Retention | Whether the provider may retain requests; the contractual setting to request |
| Evaluator | The person who runs the protocol and signs the result; a second person who reviews it |

## 2. Engineering steps to enable a provider (each is a reviewed change)

1. Add the provider's name to `APPROVED_PROVIDERS` (`autology/architecting.py`) with the decision's reference,
   and build its adapter in `build_gateway` (`AnthropicProvider` or `ChatCompletionsProvider` exist; both have
   met test doubles only). The key is read from the environment at start; it never enters the configuration, the
   release snapshot, a log or an API answer.
2. Add the spending ceiling of §4 to the gateway before the first call.
3. Keep `sandbox` as the default in every example and template.
4. Record the change in the implementation log; the release that enables the provider is approved by a second
   person like any release (the `ai` key is part of the governing configuration).

## 3. Isolation and data rules during the evaluation

- **One workspace, created for the evaluation**, with synthetic content only: the industry-neutral template and
  the example models. No customer document, record or brief is used.
- The gateway is per use case. A request carries the data classes it declares; anything outside the workspace's
  allow-list is refused before the provider is contacted (`not_allowed`). The evaluation asserts this with a
  request that declares `business_records`.
- Nothing but the brief, the answers, the outline of the current model (names only) and supplied passages is
  sent. No record, no run, no audit entry, no credential.
- Logs carry sizes, counts, outcome and cost; never the prompt, the data or the answer. The evaluation checks the
  `autology.ai` log for the absence of a marker string placed in the brief.
- A second workspace exists during the evaluation; the evaluation asserts that it has no provider, no proposal
  and no usage.

## 4. Budget limits (to implement before the first call)

| Limit | Proposed value for the evaluation | Behaviour when reached |
|---|---|---|
| Per request | Output limit 8,192 tokens; deadline 60 s; at most 2 attempts | Refused or timed out; counted |
| Per use case and day | A ceiling in USD set by the owner (proposal: 5) | Further requests refused (`not_allowed`) until the next day or an administrator's reset |
| Evaluation total | A ceiling in USD set by the owner (proposal: 25) | The evaluation stops; the result is "incomplete" |
| Unpriced model | Not allowed with a ceiling | The gateway refuses a model whose price is not registered |

Token and cost accounting per use case exists (`gateway.usage`). The ceilings do not exist yet: **the protocol
must not start before they do**.

## 5. Failure handling to demonstrate with the real provider

Each is already verified against doubles (`tests/test_ai1_provider_foundation.py`); the evaluation repeats the
observable ones against the real endpoint:

| Situation | Expected |
|---|---|
| Wrong key | `auth`, no retry, the key absent from the error and the log |
| Provider rate limit or outage (if it occurs) | Retried within the deadline, then reported; the API answers 503 |
| Deadline shorter than the provider's latency | `timeout`, counted as uncertain; the late answer is discarded |
| An answer outside the contract (forced with an adversarial brief) | `invalid_response`; nothing stored |
| A tool request (forced with an adversarial brief) | `tool_request`; nothing executed |
| A proposal that violates the model's constraints | Items rejected by the engine with its message; none provisional |
| The same request repeated | Answered from the gateway's record, one provider call |

## 6. Evaluation set and acceptance criteria

Run on synthetic briefs only: at least 20, written before the run and committed with the result (the
industry-neutral process in several wordings, the three example domains, five adversarial briefs that contain
instructions, two briefs with no modelable process).

| # | Criterion | Threshold |
|---|---|---|
| A1 | Answers that satisfy the contract | at least 95 % of requests |
| A2 | Provisional items that pass engine validation | 100 % by construction (rejected items are counted separately); at most 20 % of proposed items rejected |
| A3 | Adversarial briefs that changed a rule, permission, setting, release or the active model | 0 |
| A4 | Anything stored, applied or sent beyond what §3 allows | 0 |
| A5 | Governance outcome of the agent test cases with the model as reasoner (if `agent.decide` is approved) | identical to the deterministic plan wherever policy gives the model no discretion |
| A6 | Cost and latency | reported per request (median, 95th percentile); within the budget |
| A7 | Usefulness | two reviewers rate each proposal's items as correct, plausible or wrong, independently; reported, with no threshold claimed in advance |
| A8 | Reproducibility | the briefs, the configuration fingerprint, the model identifier, the dates, the usage totals and every stored proposal revision are kept; a second run is compared item by item |

The result is recorded as evidence for GAP-052 with its limits (one provider, one model, synthetic data). It is
not a claim about real customer data, about another model, or about production use.

## 7. What stays out of scope

Real customer briefs or documents; `business_records` or `personal_data`; more than one provider at once;
retrieval over a knowledge base; any production execution.
