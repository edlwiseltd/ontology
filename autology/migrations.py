"""Schema migrations of the engine store: explicit versions, ordered steps, one transaction (MIG-1, GAP-041).

A store carries its schema version (``meta.schema_version``). Opening an older store upgrades it:

* the steps in :data:`MIGRATIONS` whose version is above the store's run **in order**;
* new tables, every step, the ledger rows, the validation and the new version number are **one transaction**
  (SQLite's DDL is transactional): an upgrade that is interrupted, or fails, or does not validate leaves the store
  exactly as it was, and the next start runs the whole upgrade again;
* each step is **idempotent** (it checks what is there before changing it), so re-running is always safe;
* after the steps the store is **validated** against the schema this version expects (every table and column);
* a store **newer** than this software is refused, and so is a store whose version says it is current while a
  table or column is missing (an incompatible state nobody should run on);
* migrations only **add** (tables, columns, seals of existing rows): nothing is dropped or rewritten, so tenant,
  authorisation, audit and release records are untouched. There is no downgrade: going back means restoring the
  backup taken before the upgrade (docs/deployment.md).

``schema_migrations`` is the ledger: one row per step applied, with the version the store came from.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Set, Tuple

LEDGER = ("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, "
          "applied_at TEXT NOT NULL, from_version INTEGER NOT NULL)")


class MigrationError(Exception):
    pass


def statements(script: str) -> List[str]:
    """The SQL statements of a script (triggers contain semicolons, so splitting on ';' is not enough)."""
    out, buffer = [], ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                out.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        out.append(buffer.strip())
    return out


def columns(db: Any, table: str) -> Set[str]:
    return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}


def expected_layout(schema: str) -> Dict[str, Set[str]]:
    """Table -> columns of a store created by this version (read from the schema itself, so it is never stale)."""
    ref = sqlite3.connect(":memory:")
    try:
        ref.executescript(schema)
        ref.execute(LEDGER)
        tables = [r[0] for r in ref.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: columns(ref, t) for t in tables}
    finally:
        ref.close()


def layout_problems(db: Any, schema: str) -> List[str]:
    """What a store lacks compared with this version's schema (extra tables and columns are tolerated)."""
    problems = []
    present = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, wanted in sorted(expected_layout(schema).items()):
        if table not in present:
            if table != "schema_migrations":  # stores created before the ledger existed get it at their next upgrade
                problems.append(f"table {table} is missing")
            continue
        missing = sorted(wanted - columns(db, table))
        if missing:
            problems.append(f"table {table} lacks column(s) {', '.join(missing)}")
    return problems


# -- the steps: (version reached, description, apply(store, db)); ascending; each one idempotent ---------------------
def _add(db: Any, table: str, column: str, definition: str) -> bool:
    if column in columns(db, table):
        return False
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def _v4(store: Any, db: Any) -> None:
    _add(db, "runs", "started_by", "TEXT")


def _v5(store: Any, db: Any) -> None:
    _add(db, "run_sources", "base", "TEXT")
    _add(db, "run_sources", "conflicts", "TEXT")
    _add(db, "automation_state", "failures", "INTEGER NOT NULL DEFAULT 0")


def _v6(store: Any, db: Any) -> None:
    _add(db, "audit", "alg", "TEXT NOT NULL DEFAULT 'sha256'")


def _v11(store: Any, db: Any) -> None:
    if _add(db, "runs", "seal", "TEXT"):  # every run record is sealed; existing ones are sealed as they are
        for r in db.execute("SELECT run_id FROM runs").fetchall():
            db.execute("UPDATE runs SET seal=? WHERE run_id=?", (store._seal_of(db, r["run_id"]), r["run_id"]))


def _v12(store: Any, db: Any) -> None:
    _add(db, "runs", "run_key", "TEXT")


def _v13(store: Any, db: Any) -> None:
    added = _add(db, "run_sources", "wb_version", "TEXT")
    _add(db, "run_sources", "wb_state", "TEXT")
    if added:  # existing runs were written back field by field already: mark them done, never replay them
        db.execute("UPDATE run_sources SET wb_version=(SELECT updated_at FROM runs WHERE runs.run_id="
                   "run_sources.run_id), wb_state=CASE WHEN conflicts IS NULL OR conflicts='[]' THEN "
                   "'committed' ELSE 'conflict' END")


def _v14(store: Any, db: Any) -> None:
    if _add(db, "instances", "revision", "INTEGER NOT NULL DEFAULT 0"):
        _add(db, "instances", "seal", "TEXT")
        # existing rows are sealed as they are: a change made before this upgrade cannot be told apart
        for r in db.execute("SELECT id, type, attributes, revision FROM instances").fetchall():
            db.execute("UPDATE instances SET seal=? WHERE id=?",
                       (store._instance_seal(r["id"], r["type"], r["attributes"], r["revision"]), r["id"]))
        store._set_digest(db, store._compute_digest(db))


def _v15(store: Any, db: Any) -> None:
    """New tables only (created with the rest of the schema inside the same transaction)."""


def _v16(store: Any, db: Any) -> None:
    """New tables only: architect proposals and their review decisions."""


def _v17(store: Any, db: Any) -> None:
    """A draft carries the executable configuration next to the model."""
    if "solution" not in columns(db, "model_drafts"):
        db.execute("ALTER TABLE model_drafts ADD COLUMN solution TEXT")


def _v18(store: Any, db: Any) -> None:
    """Which records were loaded as synthetic samples (explicitly, never by a release)."""
    db.execute("CREATE TABLE IF NOT EXISTS sample_records (instance_id TEXT PRIMARY KEY, loaded_by TEXT NOT NULL, "
               "loaded_at TEXT NOT NULL, configuration TEXT NOT NULL)")


def _v19(store: Any, db: Any) -> None:
    """Which architect proposal, and which revision of it, a draft's model was saved from (GAP-080)."""
    _add(db, "model_drafts", "origin", "TEXT")


MIGRATIONS: List[Tuple[int, str, Callable[[Any, Any], None]]] = [
    (4, "who started each run", _v4),
    (5, "write-back snapshots and conflicts; automation failure counts", _v5),
    (6, "audit algorithm per entry", _v6),
    (11, "sealed run records", _v11),
    (12, "run identity carried by journal rows", _v12),
    (13, "atomic write-back state", _v13),
    (14, "record revisions and seals", _v14),
    (15, "model drafts and later tables", _v15),
    (16, "architect proposals and review decisions", _v16),
    (17, "executable configuration in model drafts", _v17),
    (18, "synthetic sample records are marked", _v18),
    (19, "a draft records the architect proposal it was saved from", _v19),
]


def upgrade(store: Any, db: Any, schema: str, current: int, target: int) -> List[int]:
    """Bring ``db`` from schema ``current`` to ``target`` in one transaction; returns the versions applied."""
    if [v for v, _, _ in MIGRATIONS] != sorted({v for v, _, _ in MIGRATIONS}) or MIGRATIONS[-1][0] != target:
        raise MigrationError("the migration steps are not in ascending order up to the current schema version")
    script = statements(schema)
    tables = [s for s in script if s.upper().startswith("CREATE TABLE")]
    rest = [s for s in script if not s.upper().startswith("CREATE TABLE")]
    applied: List[int] = []
    db.execute("BEGIN IMMEDIATE")
    try:
        for statement in tables:  # tables first: the steps may add columns that indexes and triggers refer to
            db.execute(statement)
        db.execute(LEDGER)
        now = datetime.now(timezone.utc).isoformat()
        for version, description, apply in MIGRATIONS:
            if version <= current:
                continue
            apply(store, db)
            db.execute("INSERT OR REPLACE INTO schema_migrations VALUES (?, ?, ?, ?)",
                       (version, description, now, current))
            applied.append(version)
        for statement in rest:
            db.execute(statement)
        problems = layout_problems(db, schema)
        if problems:
            raise MigrationError("the upgraded store does not match schema "
                                 f"{target}, nothing was changed: {'; '.join(problems)}")
        db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(target),))
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")
    return applied
