# Autology — Claude activation: engineering report

*16 November 2026. Branch `claude/autology-ontology-agent-4ajjer`. Sources of truth: the
[implementation log](AUTOLOGY_IMPLEMENTATION_LOG.md), the [defect register](AUTOLOGY_DEFECT_REGISTER.md), the
[decision register](AUTOLOGY_DECISION_REGISTER.md), the [requirements traceability](AUTOLOGY_REQUIREMENTS_TRACEABILITY.md)
and the [roadmap](AUTOLOGY_RELEASE_ROADMAP.md). Operator's guide: [docs/ai-provider-activation.md](../docs/ai-provider-activation.md).*

## Where this stands

**No request has been sent to a provider. The milestone is not reached and is not claimed.**

The owner's decision is now recorded as one statement (authorisation `D7D10-2026-11-16-EVAL`, section 5). **One
thing is missing: the key in the platform's environment.** The engineering session has no such variable
(`python deploy/evaluation_setup.py --check` → not set), and a key that exists at the provider is not a key
installed in Autology.

Everything that could safely be done before the first call is done and is in CI: the model is pinned in the use
case and the release, the adapter is checked against the provider's own SDK without a network, the spending
ceiling is tightened, and a dedicated evaluation deployment is generated from the decision's values.

Status words: **Implemented**, **Tested with doubles**, **Demonstrated with a real provider**, **Demonstrated in
Studio**, **Partial**, **Blocked**, **Not started**.

## 1. Repository evidence

| | Revision |
|---|---|
| Start | `50517f4`. The directive names `70a060c` (CI run 101): the two commits after it are documentation and the record of the owner's first authorisation; CI run 102 was green on `54a4840`. No other mismatch was found |
| End (code) | `28d0356` |

**Changed modules.** Engine: `ai.py` (model identity, pricing, no fallback), `ai_policy.py` (estimate, terms
fingerprint), `architecting.py` (the use case's AI setting), `architect.py`, `architect_eval.py`, `reasoners.py`,
`platform.py` (adapter construction, `ai_standing`), `solution.py` (release contents), `openapi.py`,
`__main__.py`. New: `deploy/evaluation_setup.py`, `docs/ai-provider-activation.md`. Studio:
`ReleasesView.tsx`, `AiProviderCard.tsx`, `lib/onboarding.ts`. CI: the provider's SDK is installed in the test
job so that the adapter tests run; **no credential was added to CI**. No product dependency was added.

| Measure | Start | End |
|---|---|---|
| Python tests (2 PostgreSQL tests skipped locally in both) | 932 | **953**, all passing |
| Line coverage (local) | 95.79 % | **95.82 %** (16,334 statements, 683 missed) |
| ruff | clean | clean |
| mypy ratchet | 198 | 198 (baseline not raised) |
| Studio unit tests | 40 | **41** |
| Studio browser checks | 118 | **119** |

New test files: `test_claude1_model_pinning.py` (8), `test_claude2_anthropic_adapter.py` (9),
`test_claude3_evaluation_deployment.py` (4). The full run was made on a snapshot of the final code tree; the
edits after it were documentation, and the tests that read documentation were re-run.

### CI

| Commit | CI run | Result |
|---|---|---|
| `50517f4` | [run 103](https://github.com/edlwiseltd/ontology/actions/runs/43964624621) | Success (the starting point) |
| `28d0356` | [run 104](https://github.com/edlwiseltd/ontology/actions/runs/43969239343) | **Success**, all five jobs: Python 3.10 and 3.13 with PostgreSQL (953 tests, none skipped, the adapter tests included; coverage gate 95 % passed), `package`, `studio` (41 unit tests, 119 browser checks), `quality` |

### Defects

Found by validating the adapter against the provider's SDK, in code that had never run against anything but a
hand-written double; all fixed before any call:

| | What it would have done on the first real calls |
|---|---|
| GAP-068 | An answer under a dated model name was costed at **zero**: the ledger would have settled real calls at 0 USD |
| GAP-069 | The provider was asked to answer with **another model** on a refusal, and any model's answer was accepted |
| GAP-070 | The SDK would have taken its address and other credentials from the host's environment: a key could have gone to an address nobody chose |
| GAP-071 | The reservation before a call left out the schema and the cache-writing surcharge |

Still open and unchanged: **GAP-052** (never run with a real model), GAP-053 (no real business process), no
independent security review. Register totals: 71 (40 fixed, 14 open, 5 open on external evidence, 2 on owner
decisions, 10 partly fixed).

## 2. Provider evidence

| Asked for | State |
|---|---|
| Exact provider and model | Anthropic, `claude-opus-5-5` (authorised; not yet called) (a price is registered: 4 USD per million input tokens, 20 USD output; it matches the price in the provider's SDK reference available to the engineering session; to be compared with the invoice after the evaluation) |
| Named evaluation workspace | `evaluation`, a dedicated workspace written by `deploy/evaluation_setup.py` (key variable `EVALUATION_AI_KEY`) |
| Authorisation reference | `D7D10-2026-11-16-EVAL` (decision register); not deployed yet: the deployment is generated when the key is present |
| Credential-reference mechanism | `{"ref": "env:<WORKSPACE PREFIX>…"}` in the workspace policy; the key is read once at start for that workspace's SDK client; never stored, logged, exported, released or shown. Tested with made-up values |
| Number of real API calls | **0** |
| Token consumption, actual cost | None |
| Budget remaining | 10 USD of 10 USD |
| Provider failures and retries | None occurred. Classified in tests from the SDK's own exceptions |

One request did go to the provider's address earlier today: a request for the model list **with no key**, to learn
whether the engineering session was signed in to the provider on its own. It was refused (401). It carried no
data, called no model and cost nothing.

**What the SDK check established, and what it did not.** Established with the real SDK (2.8.0) over a local
transport: the request it would send (one model, the answer's schema unchanged, no tools, no sampling parameters,
no fallback, the key in one header, the provider's API version `2026-10-21`); how it parses an answer that has a
thinking block; every stop reason; its error classes; that it retries nothing itself; that the deadline reaches
it; that the environment cannot redirect it. **Not established:** that the provider accepts the request (the
schema's 18 optional properties, the output ceiling, the caching option), and anything about what a model
answers. The first authorised call settles the first; the evaluation settles the second.

## 3. AI architect evidence

| Asked for | State |
|---|---|
| Results of the five cases with a real model | **None: not run** |
| The 13 measures | Unchanged, thresholds unchanged. Met 13 of 13 by the hand-written reference answers (a check of the scorers) and 6 of 13 by the sandbox templates, as before |
| Generated entities and relations, contextual questions, contradictions | None from a model |
| Rejected proposals and reasons; prompt-injection results | Tested with scripted doubles only (previous sprint), unchanged |

Nothing here may be read as evidence about a language model.

## 4. Studio evidence

| Asked for | State |
|---|---|
| The ground-handling brief through Studio with a real model, and steps 1 to 16 of the journey | **Blocked.** Not started with a model |
| What Studio would show | Implemented, Tested with doubles: the provider and model that answer, a notice that a use case is synthetic-only, the release's AI line (provider, model, policy terms, whether it is served now), the policy terms on the Access screen |
| The same journey from a template with the sandbox | Demonstrated in Studio (119 browser checks); the sandbox is a test double, not a language model |

When the provider is authorised, the journey starts from the template *Blank solution with the authorised
architect*, which the evaluation deployment provides; nothing about ground handling is built in.

## 5. The owner's decision, and what is still open

**Authorisation `D7D10-2026-11-16-EVAL`**, given on 16 November 2026 in the directive and in three explicit
answers after it (decision register):

| Parameter | Decided |
|---|---|
| Provider | Anthropic |
| Workspace | `evaluation` (dedicated; generated by `deploy/evaluation_setup.py`) |
| Model | `claude-opus-5-5` |
| Allowed data | Synthetic only |
| Purpose | AI Solution Architect evaluation: the five cases, the ground-handling brief, the Studio journey |
| Monthly ceiling | 10 USD |
| Per-request ceiling | 1 USD (a call reserves about 0.34 USD at most at the registered price) |
| Concurrent calls | 1 |
| Key | A server-side environment reference: `EVALUATION_AI_KEY`, installed by the owner |
| Prompt and response storage in the gateway | None |
| Provider-side retention | The terms of the owner's account, accepted by the owner for synthetic data |
| Valid until | 23 November 2026 |
| External business writes, Production execution | Prohibited |

It replaces the first answers of the same day (workspace `acme`, 5 USD), which were never used.

**Still open: the key.** The owner adds the environment variable `EVALUATION_AI_KEY` to the cloud environment
`ontology` (environment menu → `ontology` → Edit → environment variables) and starts a new session on it. The
value is typed there by the owner and nowhere else. Note that this stores it in that environment's settings.

The workspace policy is proposed and approved by two identities (`owner`, `reviewer`). In this single-operator
evaluation both are operated on the owner's behalf: the two-person rule is exercised technically, not
organisationally.

Other decisions, untouched: D24 (`operate`), D26 (readiness weights), D27 and D28 (defaults of the two previous
sprints), D23, D25. New: **D29**, six engineering defaults of this sprint (decision register).

## 6. Classification

| Capability | Status |
|---|---|
| Use case names provider, exact model and policy terms; the release captures them; unauthorised model change refused | Implemented, Tested with doubles |
| Anthropic adapter | Implemented, Tested with doubles and with the provider's SDK offline; **not** demonstrated with a real provider |
| Spending ceiling (reservation, settlement, uncertain outcomes, unknown price, unavailable ledger, no cross-workspace spending) | Implemented, Tested with doubles |
| Secure key reference and evaluation deployment | Implemented, Tested with made-up values; Blocked on the key |
| Five-case evaluation with a real model | **Blocked** |
| Unfamiliar ground-handling case | **Blocked** |
| Studio journey with a real model | **Blocked** |
| Studio journey with the sandbox template | Demonstrated in Studio (a test double) |
| A second provider, a Studio form for the AI policy, budget alerts | Not started |
| R2 | **Not closed**: GAP-052 open |

## 7. Next

When `EVALUATION_AI_KEY` is present, in order, stopping at the first failure:

```bash
python deploy/evaluation_setup.py --check
python deploy/evaluation_setup.py --out <dir outside the repository> --model claude-opus-5-5 --monthly-usd 10 \
    --per-request-usd 1 --expires 2026-11-23 --decision "D7D10-2026-11-16-EVAL (owner, 16 Nov 2026)"
```

then the steps of [docs/ai-provider-activation.md](../docs/ai-provider-activation.md): two identities approve the
policy; one first call (which also tells whether the provider accepts the request); the five cases; a report of
what failed **before** any improvement, thresholds untouched; the ground-handling brief; the Studio journey;
actual cost against the 10 USD ceiling.
