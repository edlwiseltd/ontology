# Autology — spending ledger: durable deployment assessment (decision D31)

*17 November 2026. Status: **assessment for the owner's decision.** No infrastructure was created, changed or
ordered. No request was sent to a provider. Choosing an option below is one decision; authorising the
infrastructure it needs is another, and neither is taken here.*

## 1. What must be preserved

The evaluation of 17 November 2026 is recorded in the ledger `adopted-32ec21e0feedb3cf79b65e96`: **27 entries,
4.418875 USD settled, 5.581125 USD remaining of the 10 USD ceiling** of authorisation `D7D10-2026-11-16-EVAL`
(expiry 23 November 2026). Any option must carry this history forward entry by entry, and must refuse to start from
zero.

## 2. What exists today (implemented and tested: `tests/test_stab1_spending_ledger.py`, 18 tests)

| Requirement | Today | Limit |
|---|---|---|
| Durable storage | One SQLite file named by the platform's `"ai_ledger"` setting, **required to be outside the data directory**; the platform never creates it | The file lives on one machine's disk. In this engineering environment the machine itself is temporary: the ledger was lost once (GAP-085) and restored from the copy kept as evidence |
| Backup | `platform-backup` includes the ledger; `ai-ledger status` reports identity, entries and digest | A backup is as recent as its last run; nothing ships changes continuously |
| Recovery | `ai-ledger restore` copies a saved ledger into place read-only first, then verifies it against the authorisation's binding; a restore that is older than the binding is refused | Manual; recovery point is the last copy |
| Transactional reservations | A reservation is one SQLite transaction under a lock: ceiling checked and entry written together; concurrency 1 enforced | Single writer by design; correct for one platform process, not for several machines |
| Idempotent settlement | An entry is closed once; database triggers refuse a second close, a change of amount and any delete; an entry left open by a stopped process is closed as `uncertain` and **stays charged** | — |
| Workspace isolation | Every entry names its workspace; ceilings and history are per workspace; a workspace reads only its own | One file holds all workspaces of a platform |
| Tamper detection | The owner's authorisation carries a **binding** (ledger identity, entry count, digest of the entries, settled amount). A ledger that is missing, empty, replaced, truncated or holds less settled money than the binding is refused | Detects loss and substitution relative to the last binding. It does **not** detect a careful rewrite by someone who can change both the file and the authorisation: entries are not individually signed and checkpoints are not written to a store the operator cannot rewrite |
| Fail closed | No ledger, a damaged ledger, a ledger inside the deployment, an unbound or mismatching ledger: the provider is `unavailable` and nothing is sent | — |

## 3. Options

| | A. SQLite on a durable volume | B. A + continuous replication to object storage | C. Ledger in managed PostgreSQL | D. C + checkpoints in write-once storage |
|---|---|---|---|---|
| What it is | Today's file on a network-attached volume that outlives any machine; scheduled backups | The same file, with every change shipped to versioned object storage by a replication tool | The ledger's tables in a managed database with point-in-time recovery | C, plus a signed checkpoint written at each settlement to storage with object lock (cannot be changed or deleted before a retention date) |
| Survives the loss of a machine | Yes, if the volume is in another failure domain | Yes | Yes | Yes |
| Recovery point | Last backup (minutes to a day) | Seconds | Seconds (managed) | Seconds |
| Several platform machines | No (one writer) | No (one writer) | Yes: row locks and a unique constraint make the reservation atomic across machines | Yes |
| Tamper detection | As today | As today, plus object versions | As today, plus database audit and restricted roles (no `UPDATE`/`DELETE` privilege on closed entries) | Strongest: a rewrite contradicts a checkpoint nobody can alter |
| Code to write | None | None in Autology; a tool to operate | A PostgreSQL backend for `SpendLedger` (the engine's store already has one; the ledger does not), the triggers ported, the same tests run against it | C, plus checkpoint signing with the platform's audit key and a verifier |
| Operating burden | Low | Medium (a second moving part, restore drills) | Medium (a database to run or buy) | Medium-high |
| Cost order of magnitude | A few USD a month | A few USD a month | Tens of USD a month for the smallest managed instance | C plus cents |
| Main risk | A volume mounted on two machines at once corrupts a SQLite file; discipline needed | Restore procedure untested until it is drilled | A new backend in the path of every provider call: a defect there blocks or miscounts spending | Complexity before there is production spending to protect |

## 4. Migration requirements (whatever the option)

1. **Freeze.** Stop the platform; `ai-ledger status`; record identity, entries, digest and settled amount.
2. **Copy, never re-enter.** Entries are copied with their identifiers, times, amounts and states. Identity
   columns are never rewritten. For option C or D the import verifies that the digest of the imported entries
   equals the recorded digest before anything is served.
3. **Same identity or an explicit carry-forward.** Either the ledger keeps its identity (`adopted-32ec…`), or a
   new ledger opens with one carry-forward entry that names the old ledger, its digest and its settled amount
   (`evaluation_setup.py --new-ledger --opening-spent-usd --opening-reference` exists for this).
4. **Re-bind the authorisation.** The owner's authorisation is rewritten against the checkpoint of the ledger in
   its new place. This is an owner action: an authorisation is not changed by engineering.
5. **Prove fail-closed in place.** Before the first request: start once with the ledger absent, once with an older
   copy, once with a different ledger. Each must be refused. Record the three refusals.
6. **Restore drill.** Destroy the working copy on purpose and restore from the backup or the replica; verify
   against the binding; record the time it took.
7. **One writer.** Until option C or D is in place, exactly one platform process may hold the ledger. A second
   deployment against the same ceiling must be refused by configuration, not by convention.
8. **Rollback.** The old file is kept read-only until the first settlement in the new place has been verified.

## 5. Assessment (not a decision)

* For the **evaluation workspace** and the remaining 5.581125 USD: **option A** is sufficient and needs no code.
  What it needs is a place for the file that is not this engineering session's own disk. That is an
  infrastructure choice the owner has not made.
* For **any production use**, where several machines or a restart during a call are normal: **option C**, with
  **D** once real money is routinely spent. C is a bounded piece of engineering (a backend and the existing 18
  tests run against it) and should not be started before the owner chooses the hosting.
* **Option B** is a reasonable intermediate step if a database is not wanted yet, at the price of operating a
  replication tool.
* Independently of the option, two improvements are worth making and need no infrastructure: sign each checkpoint
  with the platform's audit key, and record each binding in the signed administration log.

## 6. What the owner is asked (D31)

| # | Question | If "yes" | If no answer |
|---|---|---|---|
| a | Where may the evaluation ledger live so that it survives this engineering environment (option A)? | The file is moved by the documented migration; the authorisation is re-bound by the owner | It stays where it is, restorable from the copy kept as evidence; a loss of the machine means a restore before any call |
| b | Is managed PostgreSQL the intended home of spending records for production (option C)? | The backend is built and tested; nothing is deployed without a further instruction | Not built |
| c | Should checkpoints be signed and logged now (no infrastructure)? | Implemented with tests in the next increment | Not done |

Not asked and not assumed: a third paid evaluation, the compile probe, any change of workspace, model, ceiling or
expiry.
