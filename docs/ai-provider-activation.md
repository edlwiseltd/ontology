# Activating a real AI provider for one workspace

*For the operator of an Autology platform. Status on 17 November 2026: everything below is implemented, tested
with test doubles and with the provider's SDK over a local transport, and **was followed once with the real
provider** (workspace `evaluation`, `claude-opus-5-5`, synthetic data; 33 requests, 24 answers, 4.42 USD recorded;
[report](../planning/AUTOLOGY_FIRST_REAL_CLAUDE_EVALUATION_REPORT.md)). Rate limits, overload and timeouts have
not been met with the real provider.*

A language model is reached only when five independent things are true at once. None of them implies another.

| # | What | Who | Where it lives |
|---|---|---|---|
| 1 | The owner's authorisation: workspace, provider, exact model, data classes, monthly ceiling, expiry, decision reference | The owner decides; the operator writes it down | `"ai_authorisations"` in the platform's deployment file. It cannot be set through the API |
| 2 | The workspace's AI policy: the same provider and model, limits, budget, where the key lives | One workspace administrator proposes, another person with authority approves | The workspace's signed administration log |
| 3 | The key | The owner creates it at the provider; the operator installs it | An environment variable of the platform's process, named under the workspace's prefix |
| 4 | The use case names the provider, the exact model and the policy terms | Whoever configures the use case; fixed by its release | The use case's `"ai"` setting (a governing setting: it is in every release) |
| 5 | An adapter for the provider is installed | Engineering | `autology/platform.py` (`PROVIDER_ADAPTERS`): today `anthropic` only |

Take any one away and nothing is sent: the use case's architect answers "provider unavailable" with the reason.

## The key

* It is **never** pasted into a chat, a ticket, a source file, a `.env` file in the repository, Studio or an API
  call. Autology stores the *name* of the variable (`{"ref": "env:EVALUATION_AI_KEY"}`) and refuses anything else
  in that place without echoing it.
* The variable's name must start with the workspace's prefix: the workspace `evaluation` may only name
  `EVALUATION_…`. A workspace cannot name another workspace's variable.
* Install it where the platform's process starts, the way that host keeps secrets (a secret store that sets the
  variable, a systemd `EnvironmentFile` readable by the service account only, a container secret):

  ```bash
  # the operator's shell, on the server; the value is typed or read from the secret store, not from a file in the repository
  read -r -s EVALUATION_AI_KEY && export EVALUATION_AI_KEY
  python deploy/evaluation_setup.py --check        # says "set" or "NOT set"; never prints the value
  ```
* It is read once, when the platform starts, and handed to the provider's SDK for that workspace only. The SDK is
  built with the provider's own address fixed in code and with no other credential: an `ANTHROPIC_BASE_URL`,
  `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` in the environment changes nothing
  (`tests/test_claude2_anthropic_adapter.py`).
* It is not in any log, audit event, release, backup, API answer or browser. Rotating it is: set the new value,
  restart the platform, revoke the old key at the provider.

## The steps

```bash
# 1. the deployment, from the owner's decision (written outside the repository; holds no key)
python deploy/evaluation_setup.py --out /srv/autology-eval --model <exact model id> \
    --monthly-usd <ceiling> --per-request-usd 1 --expires <YYYY-MM-DD> --decision "<decision reference>"

# 2. secrets of the process: the audit key, one token per person, the provider key
export AUTOLOGY_AUDIT_KEY=...  EVALUATION_TOKEN_OWNER=...  EVALUATION_TOKEN_REVIEWER=... \
       EVALUATION_TOKEN_OPERATOR=...  EVALUATION_TOKEN_SUPERVISOR=...
read -r -s EVALUATION_AI_KEY && export EVALUATION_AI_KEY

# 3. start
python -m autology platform /srv/autology-eval/platform.json --port 8700

# 4. two people: the owner proposes the policy that the setup wrote, the reviewer approves it
curl -s -X POST -H "Authorization: Bearer $EVALUATION_TOKEN_OWNER" -H "Content-Type: application/json" \
     -d @/srv/autology-eval/policy.json http://127.0.0.1:8700/platform/workspaces/evaluation/ai/policy
curl -s -X POST -H "Authorization: Bearer $EVALUATION_TOKEN_REVIEWER" -H "Content-Type: application/json" \
     -d '{"reason": "reviewed against the owner decision"}' \
     http://127.0.0.1:8700/platform/workspaces/evaluation/ai/policy/<id>/approve

# 5. what stands now (state, model, terms, budget used and left; never the key)
curl -s -H "Authorization: Bearer $EVALUATION_TOKEN_OWNER" http://127.0.0.1:8700/platform/workspaces/evaluation/ai
```

`state` is then `authorised`, `transmits_externally` is `true`, and the use case `architect` is served by the
named model. Stop the platform before running the evaluation from the command line (it opens the same data):

```bash
python -m autology architect-eval --platform /srv/autology-eval/platform.json --workspace evaluation --use-case architect
```

Exit code 0: all thirteen thresholds met; 1: not met; 2: not authorised (it never falls back to a test double).
For Studio, start the platform again and `AUTOLOGY_PLATFORM_URL=http://127.0.0.1:8700 npm start` in `studio/web`;
create a use case from the template *Blank solution with the authorised architect*.

## What a use case and its release say

```json
"ai": {"provider": "anthropic", "model": "<exact model id>", "policy": "<policy terms>",
       "data_classes": ["synthetic"], "content": "synthetic"}
```

* `model` and `policy` are required for any provider but the sandbox. `policy` is the fingerprint of the policy's
  **terms**: provider, model, data classes, purposes and the retention rule (`GET …/ai` shows it as
  `policy.terms`; Studio shows it on the Access screen). Budgets, limits, the expiry date and the key's variable
  name are not part of it.
* The setting is governing: every release contains it, the release's contents name the provider, the model and
  the terms, and say whether the workspace's policy serves them now (`ai_standing`).
* If the workspace's policy later names another model, or other terms, this use case is served **nothing** until
  a new release of the use case names them. A smaller budget or a tighter limit keeps serving.
* A release can still be activated or rolled back when the policy no longer serves it: the architect is a
  design-time helper, and stopping it must never stop a rollback. Runs do not call the architect.
* `content: synthetic` is the operator's statement that everything typed into this use case is invented. Its
  briefs are then sent as `synthetic` data. Without it a typed brief is a `model_design`, which a policy that
  allows only `synthetic` refuses.

## Spending

Before a call the gateway reserves the most the request could cost (its size, the answer's schema, the
cache-writing surcharge, the output ceiling, every attempt) in a durable ledger; after it, the reservation is
replaced by what the provider reported, at the registered price of the **configured** model. A request that would
pass the per-request or the monthly ceiling, or exceed the concurrency, is refused and nothing is sent. An
outcome nobody can know (a timeout, a lost connection, an answer from another model) keeps its reservation
charged. A model with no registered price is not called. If the ledger cannot be read or written, nothing is
sent. One workspace's spending never counts against another's.

The price table (`autology/reasoners.py`, `PRICES`) is Autology's bound, not the provider's invoice: compare the
two after an evaluation.

## What the first use showed (17 November 2026)

* **The key reaches a cloud session only when its machine starts.** A variable added to the environment is read
  when the machine is created or restored after a pause, not by a session that is already running.
* **The provider refuses the architect's contract as a grammar** ("The compiled grammar is too large", HTTP 400,
  nothing billed). The adapter then sends the request once more with the schema written into the instructions.
  Expect one refused request per process and schema, and no guarantee from the provider that the answer keeps
  the contract: the gateway checks it, and an answer outside it is refused whole after being paid for (2 of 24).
* **A refused request names its reason**: the provider's error type, and its message for an invalid request, with
  anything shaped like a credential removed. The key is never in a log, an answer or an audit entry.
* **Answers take 16 to 104 seconds** for the architect; the deadline is 300 seconds and nothing is retried.
* **Keep the answers**: `python -m autology architect-eval --platform <platform.json> --workspace evaluation --use-case <id> --save <dir>`
  writes every answer as it was scored, and the result.

## What the provider keeps

Autology keeps no prompt and no answer in the gateway (`retention.prompts: none`); a proposal a person asked for
is stored as a revision in the use case, like any other design record. What the **provider** retains is governed
by the terms of the owner's account with it, which the owner confirms before authorising. From the provider's
published "API and data retention" page (read 16 November 2026): prompts and outputs are not used for training
without express permission; a structured-output schema is cached for up to 24 hours since last use (Autology's
schema contains no business data); a prompt cache holds representations for its lifetime only; some models
("Covered Models") require 30-day retention. The standard retention period of an ordinary commercial account is
on the provider's privacy pages, which could not be read from the engineering environment.
