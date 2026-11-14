# Autology Console

A separate user interface for **talking to the engine**: ask questions in plain language or with short commands,
start work on an object, follow what an agent did and why, and decide the reviews waiting for you.

It is not part of the engine. It is its own small web server, on its own address, that reaches the engine only
through the engine's public REST API, exactly like any other client. The engine's review inbox is unchanged.

```bash
python -m autology serve examples/auto_insurance/server.json --port 8800      # the engine
python -m autology console --engine http://127.0.0.1:8800 --port 8900         # the console
# open http://127.0.0.1:8900 and sign in with an API token (or your company account, if the engine has SSO)
```

With Docker Compose ([`deploy/docker-compose.yml`](../deploy/docker-compose.yml)) the console runs as its own
service next to the engine on `http://127.0.0.1:8900`.

## Connecting Claude (the AI assistant)

Without an assistant, the console matches what people type to the ontology's questions, objects and goals.

**From the Console (administrators):** sign in with an admin account and open the **Configuration** tab. Tick
*Let people talk to the engine in their own words through Claude*, choose the model and effort, paste a Claude API
key (console.anthropic.com → API Keys), and **Save**. **Test connection** checks the key and model with Claude
without spending tokens. Changes apply from the next message; no restart.

- The key goes to the engine, which is what talks to Claude. It is kept in the engine's memory and, with
  *Remember* ticked, in a per-user file on the engine's computer, readable only by that account
  (`%APPDATA%\Autology\secrets.json` on Windows, `~/.config/autology/secrets.json` elsewhere, or
  `AUTOLOGY_SECRETS_FILE`). It is never stored in the browser, never shown again in full (only its last four
  characters), never written to the engine's database or backups, and never written to the access log, which
  records only that the settings changed and by whom.
- Model, effort and on/off are saved in the engine's store and take precedence over the config file's `chat`
  section and `--assistant`.
- When the console and the engine are on different machines, put both behind HTTPS before entering a key.

**From the command line:** start the engine with Claude switched on:

```bash
python -m autology serve examples/auto_insurance/server.json --assistant              # Claude Opus 5.5, medium effort
python -m autology serve examples/auto_insurance/server.json --assistant claude-sonnet-5-5:low   # another model or effort
```

(or put `"chat": {"model": "claude-opus-5-5", "effort": "medium"}` in the server config). The engine needs the
`anthropic` package (`pip install anthropic`) and a Claude sign-in **on the machine where the engine runs**; the
console itself never sees Claude credentials. Either:

- **Sign in with your Anthropic account (no key to manage):** install the `ant` command-line tool and run
  `ant auth login`. It opens a browser, you sign in and pick the organisation and workspace, and the engine picks up
  the login automatically. `ant auth status` shows which sign-in is active. Install `ant` with
  `brew install anthropics/tap/ant` on macOS, from the releases at github.com/anthropics/anthropic-cli on Linux, or
  `go install github.com/anthropics/anthropic-cli/v2/cmd/ant@latest` anywhere Go is installed (including Windows).
- **Or use an API key** from the Claude Console: `export ANTHROPIC_API_KEY=...` (Windows: `set ANTHROPIC_API_KEY=...`)
  in the engine's terminal before starting it. A key that is set takes precedence over an `ant auth login` sign-in.

Usage is billed to that Anthropic account like any API use. If the engine has no sign-in, the assistant replies
with exactly this instruction instead of failing. The assistant acts as the signed-in person, sees only what they
may see, can only *propose* runs (the person confirms them with `/proposals`), never decides reviews, and values the
deployment marks as confidential are withheld from Claude.

## Talking to it

| You type | The engine does |
|---|---|
| *Which claims were reported late?* | Plain language. With an AI assistant configured on the engine, the assistant answers (acting as you, never deciding reviews). Without one, the console matches your words to the ontology's own questions, objects and goals, answers the best match and offers the others |
| `/ask CQ-03` · `/ask CQ-05 days=30` | Answers one of the ontology's competency questions, with parameters |
| `/objects Claim` · `/object CL-2` | Lists objects of a type (aliases work: `/objects Case`), or shows one with its calculated values, links and where its data came from |
| `/run CL-4` · `/run CL-4 goal=settle_claim` | Asks an agent to work on the object (the case template is chosen from the object's type) and shows each step, its verdict and why |
| `/runs` · `/explain <run id>` | Recent runs; one run step by step, with the rules behind each decision and who approved what |
| `/reviews` | Decisions waiting for you, with the facts and rules behind them; approve or decline in place |
| `/proposals` | Runs the assistant proposed, to confirm or decline |
| **Configuration** tab (administrators) | Switch the Claude assistant on or off, choose model and effort, enter or remove the key, test the connection |
| `/outcomes` · `/ontology` · `/help` · `/clear` | Outcome analysis; what the engine knows; the command list; a fresh conversation |

Any id in an answer is clickable. The left side lists the questions the engine can answer and the types it knows
about; the composer completes commands as you type `/`, and the up arrow recalls earlier messages.

## Security

- **The engine decides everything.** The console has no credentials and no data of its own. The person's token
  stays in their browser tab and is passed through; permissions, row and field access, checkpoints and reviews are
  enforced by the engine on every request.
- **Narrow forwarding.** Only `GET` and `POST` under `/api/` are forwarded, with only `Authorization` and
  `Content-Type`; redirects are never followed; requests need a valid `Content-Length` of at most 1 MB.
- **Strict page policy.** `script-src 'self'`, no inline scripts, and everything the engine returns is inserted as
  text, never as HTML.
- If the engine cannot be reached, the console says so (502) instead of failing silently.

## Checked

`tests/test_console.py`: the app is served with its security headers; requests reach the engine as the signed-in
person and the engine's refusals pass through unchanged; only API requests are forwarded; bad or oversized bodies
are refused; an unreachable engine gives 502; redirects are not followed and other headers are dropped; the command
parser and the plain-language matcher (run under Node).

In a real browser (Chromium) against a running engine: a claims handler asked "which claims were reported late?"
(answered from the matching question), listed claims by another team's word for them, started a run that paused
for review and opened the claim; an investigator asked what was waiting for him and approved the review; the layout
was checked at desktop and phone widths with no page errors.
