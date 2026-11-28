# D24 — the `operate` permission: specification for the owner's decision

*15 November 2026. Status: **blocked on the owner's approval. Nothing in this document is implemented.** The
engine's permissions are what they were; `tests/test_d24_operate_readiness.py` pins that, so a change cannot
arrive unapproved. This specification replaces the scope given in the first design
([IAM target §7](AUTOLOGY_IAM_TARGET.md)) where the two differ.*

## 1. The problem, as verified in the code

The engine permission `admin` on a use case does two unrelated things:

1. it lets its holder **operate** the engine (run a scheduler pass, refresh the reporting database);
2. it **exempts** its holder from the row and field rules of that use case: every record, run, review and
   notification can be read, and records can be written directly.

Whoever needs (1) therefore receives (2). `admin` is checked explicitly in five places
(`autology/server.py`) and used as an exemption from visibility rules in about seventeen others:

| Operation | Today | Touches business data? |
|---|---|---|
| `POST /api/v1/tick` (one scheduler pass) | `admin` | Triggers work that does, under other identities (see §2); the answer lists run ids and automation firings |
| `POST /api/v1/reporting` (refresh the reporting database) | `admin` | Triggers an export with the configured reporting roles; the answer is row counts |
| `POST /api/v1/agents/{name}/reinstate` | `admin` | No, but it **lifts a safety control** (an agent suspended after repeated violations) |
| `POST /api/v1/objects` (write a record) | `admin` | Yes |
| `POST /api/v1/scenarios/{id}/commit` | `admin` | Yes |

**Correction to the first design.** It listed `POST /api/v1/runs/{id}/write-back` as a fourth operation that
needs `admin`. It does not: it needs `reconcile` and that the run is visible to the caller, and it writes run
results to records. It is a data operation with its own permission and is **not** part of this proposal. The
readiness test was corrected accordingly.

## 2. Exact permitted operations

`operate` would allow exactly these, on the use case where it is granted:

| # | Operation | What it does | What the holder receives |
|---|---|---|---|
| O1 | `POST /api/v1/tick` | Resumes deferred runs whose time has come, completes interrupted write-backs, loads due pipelines, evaluates automations, refreshes reporting when due | **Counts only** for an `operate` holder: runs resumed, automations fired, rows loaded per pipeline, write-backs completed. (Today's answer names run ids and firings; an `admin` holder keeps it) |
| O2 | `POST /api/v1/reporting` | Rewrites the reporting database from the live records | The existing answer: target and row counts per table |

Nothing these operations do runs with the operator's own roles. A resumed run acts as its agent, with the
agent's roles and under governance; a pipeline loads with its own declared roles (decision-critical facts
included); an automation fires as configured; the export applies the configured reporting roles. The stage gate
still applies: where the use case's stage forbids runs, a tick resumes and starts none.

**One sub-decision is left to the owner:** O3, `POST /api/v1/agents/{name}/reinstate`. The first design included
it. It reads no data, but it removes a safety suspension. Recommendation: **do not include it**; keep it with
`admin` until a reviewed way to lift a suspension exists (for example a second person). The specification below
assumes O1 and O2 only.

## 3. Prohibited capabilities

An identity holding only `operate` could not:

- read any record, field, run, review, notification, audit entry, lineage, access log or scenario;
- write a record, edit or commit a scenario, upload or push data;
- start, resume or cancel a run; decide a review; reconcile an external effect; retry a write-back;
- reinstate a suspended agent (unless the owner chooses O3);
- read or change the model, drafts, settings, pipelines, agents' configuration;
- change members, grants, tokens, stages or releases (those belong to the platform's administrative roles);
- reach another use case, another workspace or another tenant;
- approve its own grant, or be granted `operate` by a service identity.

`operate` implies no other permission, and no other permission but `admin` implies it.

## 4. Relationship to the existing permissions

| Permission | Relationship |
|---|---|
| `admin` (unrestricted) | Unchanged. It keeps allowing O1 and O2, so nothing that works today stops working. Still granted by two people, acknowledged, and listed for review |
| `configure` | Independent. Configuring a use case does not let you operate it, and the reverse |
| `read`, `run`, `review`, `audit`, `ingest`, `reconcile` (data permissions, with roles) | Independent. Row and field rules apply to them as today. None of them implies `operate` |
| Workspace and tenant administrators (platform) | Independent. They manage access and carry no engine permission by themselves (IAM-3) |
| Service identities | May hold `operate` (the expected case: a scheduler job). They still cannot decide reviews or approve grants |

## 5. Migration and compatibility

- **Additive.** `operate` is added to the set of permissions. No existing grant is changed, narrowed, widened or
  removed, automatically or otherwise.
- **Granting.** Through the existing procedure only: proposed by one person, approved by another, never by the
  grantee, never by a service identity; recorded in the administration log.
- **Narrowing an existing `admin` grant is a human act.** The access review already shows, for each unrestricted
  grant, whether its recorded use was only operational (`narrower_would_do`). For those, a person proposes an
  `operate` grant and revokes `admin`. Nothing does it for them.
- **Compatibility.** Clients that call O1 or O2 with `admin` are unaffected. The API contract gains one value in
  the permissions enumeration and a reduced answer shape for O1 (a minor, backward-compatible revision); Studio's
  Access screen lists the new permission. A configuration that names `operate` is refused by engines older than
  the change (as an unknown permission is today), so the change is not silently ignored.
- **Reverting.** Revoke the `operate` grants; `admin` still covers O1 and O2.
- **Estimated work once approved:** one to two days, including the contract, Studio and the tests below.

## 6. Security tests to accompany the implementation

Present behaviour is pinned today (five tests: `operate` cannot be configured or granted; O1, O2 and O3 are
refused without `admin`; write-back retry needs `reconcile`; the access review's usage evidence). With the
change, these are added, and the first two are inverted:

| # | Test | Expected |
|---|---|---|
| T1 | An `operate` holder calls O1 and O2 | 200; O1's answer holds counts and no identifier |
| T2 | The same holder calls every other route of the contract (generated from the route table) | 403 on each; 404 for other use cases, workspaces, tenants |
| T3 | The holder calls O3 | 403 (or 200 if the owner chose to include it) |
| T4 | A tick started by an `operate` holder resumes a run that reaches a human review | The review is created for its reviewer role; the operator cannot list or decide it |
| T5 | A tick loads a pipeline that sets a decision-critical fact | Written only with the pipeline's declared roles; refused otherwise, whatever the operator holds |
| T6 | The holder's requests in the access log | Classified operational; none classified data |
| T7 | `operate` proposed by its own grantee, or approved by the proposer or a service identity | Refused |
| T8 | An `admin` holder after the change | Same answers as before on every route (compatibility) |
| T9 | Existing grants after the upgrade | Byte-identical administration log replay: nothing migrated |
| T10 | An `operate` holder through MCP | Only the corresponding tools are offered; all others refused and logged |
| T11 | Stage gate: use case in Draft | A tick resumes and starts nothing |
| T12 | Engine configuration naming `operate` on an older engine | Refused at start |

## 7. Decision requested

1. Approve `operate` with O1 and O2 as specified, `admin` unchanged? (recommended), or decline and keep the
   present state, in which operating the engine requires unrestricted data access.
2. If approved: include O3 (reinstating a suspended agent)? Recommended: no.

Until an explicit answer, the implementation stays blocked and current authorisation semantics are retained.
