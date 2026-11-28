# Autology — AI provider configuration per workspace and spending control: design

*16 November 2026. Written as a design in the activation sprint; **implemented in the architect sprint** (same
day) as far as it can be without an owner decision: see "Implementation status" at the end. No provider was
contacted, no credential exists in the repository or the environment, and no owner authorisation is deployed
anywhere, so the only thing that answers is still the sandbox test double. It complements the
[evaluation protocol](AUTOLOGY_AI_PROVIDER_EVALUATION_PROTOCOL.md) and the AI gateway of AI-1 (`autology/ai.py`),
which stays the only path to a model.*

## 1. What exists today (verified in the code)

| Element | State |
|---|---|
| Provider-neutral contract (`ModelGateway`, `ModelRequest`, `ProviderCall`, `ProviderReply`, `Capabilities`) | Implemented, tested with test doubles (`test_ai1_provider_foundation.py`) |
| Per-engine setting `"ai": {"provider": ...}` and the list `APPROVED_PROVIDERS = ("sandbox",)` | Implemented: any other provider name is refused when the engine loads |
| Adapters for two real provider protocols | Present as code, **never enabled, never run against a real service** (GAP-052) |
| Request limits, token and cost accounting per use case (`gateway.usage`) and an audit entry per gateway call | Implemented in the gateway (AI-1; see the implementation log). Ceilings are **not** implemented |
| Per-workspace configuration, budgets, key custody | **Not implemented**: this design |

## 2. Principles

1. **The workspace decides, the owner authorises.** A provider is usable in a workspace only if (a) the owner's
   decision names that workspace, provider, model and data classes, and (b) a workspace administrator then enables
   it. Neither alone is enough. No default provider, no fallback to another provider, no platform-wide switch.
2. **Configuration is governed like any other.** The provider setting is a governing setting of a use case: it is
   part of the release snapshot and fingerprint, so changing it needs a release approved by another person.
3. **Keys are never configuration.** A setting names where a key lives; it never contains it. Keys do not reach
   Studio, the audit log, the release snapshot, a report or a test fixture.
4. **Spending has a hard stop.** A budget is checked before a call is sent. When it is exhausted the call is
   refused; it is never sent "just this once". A refusal is an ordinary, visible state in Studio.
5. **Provider-neutral.** Everything below is expressed in the gateway's own terms; an adapter maps them.

## 3. Configuration model

Two levels, both read by the engine through the platform (Studio never talks to a provider):

**Workspace policy** (in the platform's administration registry; changed by two people, like a data grant):

```json
{"ai": {"providers": {"<provider id>": {
    "authorised_by": "decision D7/D10 reference", "models": ["<model id>"],
    "data_classes": ["synthetic"], "key_ref": "env:ACME_AI_KEY",
    "budget": {"currency": "USD", "per_call": 0.50, "per_day": 5, "per_month": 50, "per_use_case_per_month": 20},
    "limits": {"max_input_tokens": 20000, "max_output_tokens": 4000, "requests_per_minute": 6},
    "expires": "2027-01-31"}}}}
```

**Use case setting** (in the use case's governing configuration, therefore in its releases):

```json
{"ai": {"provider": "<provider id>", "model": "<model id>", "purposes": ["architect"]}}
```

Rules: a use case may name only a provider and a model its workspace policy lists; `data_classes` bounds what the
gateway may send (a request carries the class of its data; anything else is refused before sending); `key_ref` must be an
environment variable under the workspace's own prefix (the existing ISO-4 rule) or, later, a secret-manager
reference; an expired or withdrawn authorisation disables the provider at once, for every use case.

## 4. Spending control

| Control | Where | Behaviour |
|---|---|---|
| Estimate before sending | Gateway | Input tokens counted, output bounded by `max_output_tokens`, priced from a price table kept with the adapter; an unknown price refuses the call |
| Per-call ceiling | Gateway | Estimated cost above `per_call`: refused |
| Day, month, per-use-case ceilings | A ledger in the platform (append-only, per workspace) | The estimate is reserved before the call and replaced by the actual usage after it; reservation and check are one transaction, so parallel calls cannot overspend |
| Rate | The existing limiter | `requests_per_minute`, per workspace |
| Uncertain outcome | Gateway (existing behaviour) | A call whose outcome is unknown is charged at its reservation until reconciled; it is never repeated automatically |
| Visibility | Platform API, Studio | Spent, reserved and remaining per period; each refusal with its reason; no prompt or completion text in the ledger |
| Alerts | Notifications | At 50 %, 80 % and 100 % of a ceiling, to workspace administrators |

Failure rule: if the ledger cannot be read or written, the call is refused (fail closed).

## 5. Authorisation and audit

* Enabling, changing or withdrawing a workspace's provider policy: proposed by a workspace administrator,
  approved by another person with authority, recorded in the signed administration log. A service identity can do
  neither.
* Selecting a provider for a use case: `configure`, then the normal release path.
* Using it: the existing permissions of the feature (today `configure` for the architect).
* Every call: the existing gateway audit entry, extended with the budget decision (allowed or refused, estimate,
  ledger entry); the content of prompts stays out of the administration log.

## 6. Studio

A read-mostly panel under the workspace's settings: which providers are authorised (and until when), for which
data classes, the budget and what is left, recent refusals. For a use case: which provider its draft and its
active release name. The onboarding screen keeps saying exactly what answers: "sandbox architect, not a language
model", or the provider and model of the active release.

## 7. Tests to write with the implementation (none exist yet)

Isolation (a workspace cannot use another's key, policy or budget); refusal of every unlisted provider, model and
data class; budget arithmetic under parallel calls; fail-closed ledger; expiry; no key in any API answer, log,
snapshot or error; release fingerprint changes when the setting changes; behaviour identical with a test double
that reports usage.

## 8. Open points for the owner (part of D7/D10)

1. The named workspace, provider, model and data classes for the first evaluation (the protocol assumes synthetic
   data only).
2. The ceilings (the figures above are placeholders, not proposals).
3. Key custody: an environment variable on the platform host for the evaluation, or a secret manager first.
4. Whether prompts and completions may be retained for evaluation, where, and for how long.
5. Who may approve a workspace's provider policy (the same people as data grants, or a narrower group).

## 9. Implementation status (architect and Claude activation sprints, 16 November 2026)

| Part of this design | State | Where |
|---|---|---|
| Workspace policy: provider, model, data classes, purposes, limits, budget, credential reference, retention, evaluation status, expiry | Implemented, Tested | `autology/ai_policy.py` (`validate_policy`); stored in the workspace's signed administration log |
| Two people: proposed by an administrator, approved by another person; one person may withdraw or disable | Implemented, Tested | `platform.py` (`_ai_routes`), events `ai_policy_*` |
| The owner's authorisation, separate from the policy | Implemented, Tested | `"ai_authorisations"` in the platform's deployment file (`validate_authorisations`, `authorisation_for`): workspace, provider, exact model, data classes, monthly ceiling, expiry, decision reference. It cannot be set through the API. **None is deployed** |
| Spending control: estimate before sending, per-request and per-period ceilings, concurrency, one reservation per request, uncertain outcomes stay charged, fail closed | Implemented, Tested | `ai_policy.SpendLedger`, `ai_policy.Budget`, `ModelGateway(budget=...)`; ledger `ai_ledger.db`, included in backups |
| Keys are never configuration | Implemented, Tested | A policy holds `env:NAME` under the workspace's prefix; anything else is refused and never echoed |
| Use case setting in the release | Implemented, Tested (Claude activation, 16 Nov) | The use case names provider, exact model and the policy *terms* (`ai_policy.terms_fingerprint`); the setting is governing, so every release names them, and the release detail says whether the workspace's policy serves them now (`ai_standing`). A policy that moved to another model or other terms serves the use case nothing until a new release names it (`tests/test_claude1_model_pinning.py`). The workspace's grant is still not part of a release |
| Studio | Read-only | Access screen card "AI provider"; onboarding names who answers. **No form** to propose a policy yet: the API is used |
| Alerts at 50/80/100 % | Not implemented | — |
| Requests-per-minute per policy | Not implemented | The platform's existing rate limits apply |
| A secret manager for keys | **Blocked** (open point 3): only an environment-variable reference is accepted | — |
| Endpoint for self-hosted or compatible providers | Not implemented: the policy has no endpoint field. The one installed adapter (`anthropic`) has its provider's address fixed in code and takes no credential from the environment; it is exercised against a client double and against the official SDK over a local transport (`tests/test_claude2_anthropic_adapter.py`), never against the provider |

The five open points of §8 are unchanged and still the owner's.
