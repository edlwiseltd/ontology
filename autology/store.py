"""Persistent store (SQLite, standard library): knowledge graph, runs, append-only audit, reviews.

One file holds everything a deployment needs to survive restarts:

* ``instances`` / ``links`` - the knowledge graph (load with :meth:`Store.load_graph`);
* ``runs``                  - every agent run, including deferred / paused / awaiting-review runs
                              with what is needed to resume them;
* ``audit``                 - every audit entry of every run, in an HMAC-keyed hash chain whose head
                              is recorded in ``audit_heads``: tamper-evident (see autology.audit).
                              Triggers reject UPDATE and DELETE, which guards against mistakes, not
                              against someone with database access; saving a run refuses if its
                              history diverges from what is stored;
* ``reviews``               - human review requests and the decisions taken on them (who, when, why);
* ``automation_state`` / ``automation_firings`` - which automations fired for which instance, and when;
* ``notifications``         - messages for people holding given roles (reviews waiting, automations);
* ``run_sources``           - for runs built from the graph: the instances to write results back to;
* ``scenarios``             - what-if scenarios: their edits and the base values they read;
* ``chats``                 - assistant conversations, per owner;
* ``justifications``        - reasons people gave at checkpoints before sensitive operations (append-only);
* ``access_log``            - every API request and assistant tool call: who, what, when, result.
                              **Append-only**, like ``audit``.

SQLite suits a single-node deployment and pilots; the same interface can be implemented on
PostgreSQL for larger ones. File databases use WAL mode; a lock makes the store thread-safe.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from .agent import ReviewRequest, RunResult
from .audit import GENESIS, AuditLog
from .graph import KnowledgeGraph
from .ontology import Ontology, OntologyError

SCHEMA_VERSION = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS instances (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, attributes TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS instances_type ON instances(type);
CREATE TABLE IF NOT EXISTS links (
    source TEXT NOT NULL, kind TEXT NOT NULL, target TEXT NOT NULL, PRIMARY KEY (source, kind, target));
CREATE INDEX IF NOT EXISTS links_target ON links(target, kind);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, goal TEXT NOT NULL, ontology TEXT NOT NULL,
    agent TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, record TEXT NOT NULL,
    started_by TEXT, seal TEXT, run_key TEXT);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE TABLE IF NOT EXISTS external_calls (
    key TEXT PRIMARY KEY, run_key TEXT NOT NULL, run_id TEXT, case_id TEXT, root TEXT, agent TEXT, action TEXT,
    tool TEXT, attempt INTEGER NOT NULL DEFAULT 0, inputs_digest TEXT, state TEXT NOT NULL, outcome TEXT,
    updates TEXT, message TEXT, output TEXT, detail TEXT, resolved_by TEXT, resolved_comment TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS external_calls_root ON external_calls(root, state);
CREATE INDEX IF NOT EXISTS external_calls_run ON external_calls(run_key);
CREATE TABLE IF NOT EXISTS writer_lease (
    id INTEGER PRIMARY KEY CHECK (id = 1), instance TEXT NOT NULL, host TEXT NOT NULL, pid INTEGER NOT NULL,
    started_at TEXT NOT NULL, heartbeat REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, timestamp TEXT NOT NULL, event TEXT NOT NULL, data TEXT NOT NULL,
    prev_hash TEXT NOT NULL, hash TEXT NOT NULL, alg TEXT NOT NULL DEFAULT 'sha256', PRIMARY KEY (run_id, seq));
CREATE TABLE IF NOT EXISTS audit_heads (
    run_id TEXT PRIMARY KEY, length INTEGER NOT NULL, hash TEXT NOT NULL, mac TEXT, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_event ON audit(event);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
    BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, action TEXT NOT NULL, reviewers TEXT NOT NULL,
    status TEXT NOT NULL, request TEXT NOT NULL, decision TEXT, created_at TEXT NOT NULL,
    decided_at TEXT, decided_by TEXT);
CREATE INDEX IF NOT EXISTS reviews_status ON reviews(status);
CREATE TABLE IF NOT EXISTS automation_state (
    automation TEXT NOT NULL, instance TEXT NOT NULL, active INTEGER NOT NULL, last_fired REAL,
    failures INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (automation, instance));
CREATE TABLE IF NOT EXISTS automation_firings (
    firing_id TEXT PRIMARY KEY, automation TEXT NOT NULL, instance TEXT NOT NULL, trigger TEXT NOT NULL,
    fired_at TEXT NOT NULL, run_id TEXT, status TEXT NOT NULL, detail TEXT NOT NULL, notification_id TEXT);
CREATE INDEX IF NOT EXISTS firings_automation ON automation_firings(automation, fired_at);
CREATE TABLE IF NOT EXISTS notifications (
    notification_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL, roles TEXT NOT NULL,
    message TEXT NOT NULL, ref TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS notifications_created ON notifications(created_at);
CREATE TABLE IF NOT EXISTS scenarios (
    scenario_id TEXT PRIMARY KEY, name TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, status TEXT NOT NULL, edits TEXT NOT NULL, snapshot TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chats (
    chat_id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    messages TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS access_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, principal TEXT NOT NULL, kind TEXT NOT NULL,
    target TEXT NOT NULL, status INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS access_principal ON access_log(principal, timestamp);
CREATE TRIGGER IF NOT EXISTS access_no_update BEFORE UPDATE ON access_log
    BEGIN SELECT RAISE(ABORT, 'access log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS access_no_delete BEFORE DELETE ON access_log
    BEGIN SELECT RAISE(ABORT, 'access log is append-only'); END;
CREATE TABLE IF NOT EXISTS justifications (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, principal TEXT NOT NULL, rule_id TEXT NOT NULL,
    operation TEXT NOT NULL, target TEXT NOT NULL, text TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS justification_no_update BEFORE UPDATE ON justifications
    BEGIN SELECT RAISE(ABORT, 'justifications are append-only'); END;
CREATE TRIGGER IF NOT EXISTS justification_no_delete BEFORE DELETE ON justifications
    BEGIN SELECT RAISE(ABORT, 'justifications are append-only'); END;
CREATE TABLE IF NOT EXISTS suspensions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, suspended_at TEXT NOT NULL, reason TEXT NOT NULL,
    run_id TEXT, reinstated_at TEXT, reinstated_by TEXT, reinstate_reason TEXT);
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL,
    body TEXT NOT NULL, run_id TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS run_sources (
    run_id TEXT PRIMARY KEY, template TEXT NOT NULL, root TEXT NOT NULL, sources TEXT NOT NULL,
    write_back INTEGER NOT NULL, base TEXT, conflicts TEXT);
CREATE TABLE IF NOT EXISTS ingest_state (
    pipeline TEXT NOT NULL, source TEXT NOT NULL, watermark TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (pipeline, source));
CREATE TABLE IF NOT EXISTS ingest_batches (
    batch_id TEXT PRIMARY KEY, pipeline TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL, triggered_by TEXT NOT NULL, summary TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ingest_batches_pipeline ON ingest_batches(pipeline, started_at);
CREATE TABLE IF NOT EXISTS ingest_rejects (
    batch_id TEXT NOT NULL, seq INTEGER NOT NULL, source TEXT NOT NULL, row INTEGER NOT NULL, reason TEXT NOT NULL,
    data TEXT NOT NULL, PRIMARY KEY (batch_id, seq));
CREATE TABLE IF NOT EXISTS lineage (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL, entity TEXT NOT NULL, batch_id TEXT NOT NULL,
    pipeline TEXT NOT NULL, source TEXT NOT NULL, row INTEGER NOT NULL, action TEXT NOT NULL,
    attributes TEXT NOT NULL, links TEXT NOT NULL, loaded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS lineage_instance ON lineage(instance_id, seq);
CREATE TRIGGER IF NOT EXISTS lineage_no_update BEFORE UPDATE ON lineage
    BEGIN SELECT RAISE(ABORT, 'lineage is append-only'); END;
CREATE TRIGGER IF NOT EXISTS lineage_no_delete BEFORE DELETE ON lineage
    BEGIN SELECT RAISE(ABORT, 'lineage is append-only'); END;
"""


def _process_alive(host: str, pid: int) -> bool:
    """Is process ``pid`` still running? Only answerable on this host and where signals are supported;
    otherwise assume it is (the heartbeat's age decides)."""
    import os
    import socket

    if host != socket.gethostname() or os.name == "nt":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class StoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Union[str, Path] = ":memory:", audit_key: Any = None):
        from .audit import ENV_KEY

        self.path = str(path)
        self.audit_key = ENV_KEY if audit_key is None else audit_key  # the key its chains and seals use
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.executescript(SCHEMA)
            row = self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                self._db.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(row["value"]) > SCHEMA_VERSION:
                raise StoreError(f"store schema {row['value']} is newer than this Autology ({SCHEMA_VERSION})")
            elif int(row["value"]) < SCHEMA_VERSION:  # older store: the new tables were just created
                columns = {r["name"] for r in self._db.execute("PRAGMA table_info(runs)")}
                if "started_by" not in columns:  # schema 4: who started each run
                    self._db.execute("ALTER TABLE runs ADD COLUMN started_by TEXT")
                source_columns = {r["name"] for r in self._db.execute("PRAGMA table_info(run_sources)")}
                for col in ("base", "conflicts"):  # schema 5: write-back snapshots and conflicts
                    if col not in source_columns:
                        self._db.execute(f"ALTER TABLE run_sources ADD COLUMN {col} TEXT")
                if "failures" not in {r["name"] for r in self._db.execute("PRAGMA table_info(automation_state)")}:
                    self._db.execute("ALTER TABLE automation_state ADD COLUMN failures INTEGER NOT NULL DEFAULT 0")
                if "alg" not in {r["name"] for r in self._db.execute("PRAGMA table_info(audit)")}:  # schema 6
                    self._db.execute("ALTER TABLE audit ADD COLUMN alg TEXT NOT NULL DEFAULT 'sha256'")
                if "run_key" not in columns:  # schema 12: the run's identity, which its journal rows carry
                    self._db.execute("ALTER TABLE runs ADD COLUMN run_key TEXT")
                if "seal" not in columns:  # schema 11: every run record is sealed; existing ones are sealed now
                    self._db.execute("ALTER TABLE runs ADD COLUMN seal TEXT")
                    for r in self._db.execute("SELECT run_id FROM runs").fetchall():
                        self._db.execute("UPDATE runs SET seal=? WHERE run_id=?",
                                         (self._seal_of(self._db, r["run_id"]), r["run_id"]))
                self._db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _tx(self):
        store = self

        class _Tx:
            def __enter__(self):
                store._lock.acquire()
                store._db.execute("BEGIN IMMEDIATE")
                return store._db

            def __exit__(self, exc_type, exc, tb):
                try:
                    store._db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store._lock.release()
                return False

        return _Tx()

    def _query(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # -- knowledge graph ------------------------------------------------
    def save_graph(self, graph: KnowledgeGraph) -> int:
        """Upsert every instance and link of ``graph``. Returns the number of instances written."""
        now = _now()
        with self._tx() as db:
            for inst in graph.instances():
                db.execute("INSERT INTO instances VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                           "type=excluded.type, attributes=excluded.attributes, updated_at=excluded.updated_at",
                           (inst.id, inst.type, json.dumps(inst.attributes, default=str), now))
            for source, kind, target in graph._links:
                db.execute("INSERT OR IGNORE INTO links VALUES (?, ?, ?)", (source, kind, target))
        return len(graph.instances())

    def upsert_instance(self, entity_type: str, instance_id: str, attributes: Dict[str, Any]) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO instances VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                       "type=excluded.type, attributes=excluded.attributes, updated_at=excluded.updated_at",
                       (instance_id, entity_type, json.dumps(attributes, default=str), _now()))

    def add_link(self, source: str, kind: str, target: str) -> None:
        with self._tx() as db:
            db.execute("INSERT OR IGNORE INTO links VALUES (?, ?, ?)", (source, kind, target))

    def load_graph(self, ontology: Ontology, quarantine: Optional[List[Dict[str, Any]]] = None) -> KnowledgeGraph:
        """Rebuild the graph; every instance and link is re-validated against ``ontology``.

        With a ``quarantine`` list, a row that fails validation is left out of the graph (with its links) and
        described in the list instead of stopping the load (audit GAP-010). The row stays in the store for repair.
        """
        graph = KnowledgeGraph(ontology)
        for row in self._query("SELECT id, type, attributes FROM instances ORDER BY id"):
            try:
                attrs = json.loads(row["attributes"])
                graph.add(row["type"], row["id"], **attrs)
            except (OntologyError, ValueError, TypeError) as exc:
                if quarantine is None:
                    raise
                quarantine.append({"id": row["id"], "type": row["type"], "reason": str(exc)})
        for row in self._query("SELECT source, kind, target FROM links ORDER BY source, kind, target"):
            if quarantine is not None and {row["source"], row["target"]} - set(graph._instances):
                continue  # a link to a quarantined record
            graph.link(row["source"], row["kind"], row["target"])
        return graph

    def count_instances(self, entity_type: Optional[str] = None) -> int:
        if entity_type:
            return self._query("SELECT COUNT(*) c FROM instances WHERE type=?", (entity_type,))[0]["c"]
        return self._query("SELECT COUNT(*) c FROM instances")[0]["c"]

    # -- runs and audit ---------------------------------------------------
    def save_run(self, result: RunResult, run_id: Optional[str] = None, agent: Optional[str] = None,
                 started_by: Optional[str] = None) -> str:
        """Insert or update a run; append its new audit entries. Returns the run id."""
        from .persistence import result_to_dict

        run_id = run_id or getattr(result, "run_id", None) or uuid.uuid4().hex[:12]
        record = result_to_dict(result)
        entries = record.pop("audit")
        if not result.audit.verify():
            raise StoreError(f"run {run_id}: audit chain does not verify; refusing to store it")
        now = _now()
        ontology_ref = (record.get("run") or {}).get("ontology_ref", "")
        with self._tx() as db:
            stored = db.execute("SELECT seq, hash FROM audit WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()
            for row in stored:
                if row["seq"] >= len(entries) or entries[row["seq"]]["hash"] != row["hash"]:
                    raise StoreError(f"run {run_id}: audit history diverges from the stored log at entry {row['seq']}")
            for e in entries[len(stored):]:
                db.execute("INSERT INTO audit (run_id, seq, timestamp, event, data, prev_hash, hash, alg) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (run_id, e["seq"], e["timestamp"], e["event"], json.dumps(e["data"], default=str),
                            e["prev_hash"], e["hash"], e.get("alg") or "sha256"))
            head = result.audit.head()
            db.execute("INSERT INTO audit_heads VALUES (?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET "
                       "length=excluded.length, hash=excluded.hash, mac=excluded.mac, updated_at=excluded.updated_at",
                       (run_id, head["length"], head["hash"], head["mac"], now))
            exists = db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if exists:
                db.execute("UPDATE runs SET status=?, updated_at=?, record=?, agent=COALESCE(?, agent) WHERE run_id=?",
                           (result.status, now, json.dumps(record, default=str), agent, run_id))
            else:
                db.execute("INSERT INTO runs (run_id, case_id, goal, ontology, agent, status, created_at, updated_at, "
                           "record, started_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (run_id, result.case_id, result.goal, ontology_ref, agent, result.status, now, now,
                            json.dumps(record, default=str), started_by))
            db.execute("UPDATE runs SET seal=? WHERE run_id=?", (self._seal_of(db, run_id), run_id))
            run_key = (record.get("run") or {}).get("run_key")
            if run_key:  # the journal's calls now belong to a stored run
                db.execute("UPDATE runs SET run_key=? WHERE run_id=?", (run_key, run_id))
                db.execute("UPDATE external_calls SET run_id=? WHERE run_key=? AND run_id IS NULL", (run_id, run_key))
        result.run_id = run_id
        return run_id

    # -- one writer per store (audit GAP-018) ------------------------------------------------
    def acquire_lease(self, instance: str, ttl: float) -> None:
        """Become the store's only writer, or raise :class:`StoreError` naming the process that is.

        The server keeps its graph in memory, so a second process writing the same store (a CLI ingest next to a
        running server) would diverge from it. A lease is free when its holder's heartbeat is older than ``ttl``
        seconds, when its process is gone (same host), or when it belongs to this very process."""
        import os
        import socket
        import time

        host, pid, now = socket.gethostname(), os.getpid(), time.time()
        with self._tx() as db:
            row = db.execute("SELECT * FROM writer_lease WHERE id=1").fetchone()
            if row is not None and row["instance"] != instance and not (row["host"] == host and row["pid"] == pid):
                fresh = now - row["heartbeat"] < ttl
                if fresh and _process_alive(row["host"], row["pid"]):
                    expires = datetime.fromtimestamp(row["heartbeat"] + ttl, timezone.utc).isoformat(timespec="seconds")
                    raise StoreError(f"the store is in use by another Autology process (pid {row['pid']} on "
                                     f"{row['host']}, since {row['started_at']}): one writer per store. While the "
                                     "server runs, write through its API (for example POST /api/pipelines/{name}/run). "
                                     f"If that process stopped without shutting down, the store is freed at {expires}")
            db.execute("INSERT INTO writer_lease VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                       "instance=excluded.instance, host=excluded.host, pid=excluded.pid, "
                       "started_at=excluded.started_at, heartbeat=excluded.heartbeat",
                       (instance, host, pid, _now(), now))

    def refresh_lease(self, instance: str) -> bool:
        """Renew the lease; False if another process holds it now."""
        import time

        with self._tx() as db:
            cur = db.execute("UPDATE writer_lease SET heartbeat=? WHERE id=1 AND instance=?", (time.time(), instance))
            return cur.rowcount == 1

    def release_lease(self, instance: str) -> None:
        with self._tx() as db:
            db.execute("DELETE FROM writer_lease WHERE id=1 AND instance=?", (instance,))

    def lease(self) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM writer_lease WHERE id=1")
        return dict(rows[0]) if rows else None

    # -- external calls journal (see autology.effects) ----------------------------------
    _JSON_COLS = ("updates", "output")

    def _call_row(self, row) -> Dict[str, Any]:
        out = dict(row)
        for col in self._JSON_COLS:
            out[col] = json.loads(out[col]) if out.get(col) else None
        return out

    def get_call(self, key: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM external_calls WHERE key=?", (key,))
        return self._call_row(rows[0]) if rows else None

    def record_intent(self, key: str, **fields: Any) -> None:
        """Commit the intent to call before the call is made (state ``in_flight``)."""
        now = _now()
        cols = ("run_key", "case_id", "root", "agent", "action", "tool", "inputs_digest")
        values = [fields.get(c) for c in cols]
        with self._tx() as db:
            if db.execute("SELECT 1 FROM external_calls WHERE key=?", (key,)).fetchone():
                db.execute("UPDATE external_calls SET tool=?, inputs_digest=?, attempt=attempt+1, state='in_flight', "
                           "detail=NULL, updated_at=? WHERE key=?", (fields.get("tool"), fields.get("inputs_digest"),
                                                                   now, key))
            else:
                db.execute(f"INSERT INTO external_calls (key, {', '.join(cols)}, attempt, state, created_at, "
                           f"updated_at) VALUES (?, {', '.join('?' for _ in cols)}, 1, 'in_flight', ?, ?)",
                           [key] + values + [now, now])

    def record_call_result(self, key: str, state: str, **fields: Any) -> None:
        cols = [c for c in ("outcome", "updates", "message", "output", "detail") if c in fields]
        vals = [json.dumps(fields[c], default=str) if c in self._JSON_COLS else fields[c] for c in cols]
        with self._tx() as db:
            db.execute(f"UPDATE external_calls SET state=?, updated_at=?{''.join(f', {c}=?' for c in cols)} "
                       "WHERE key=?", [state, _now()] + vals + [key])

    def resolve_call(self, key: str, done: bool, by: str, comment: str, **fields: Any) -> Dict[str, Any]:
        from .effects import RESOLVED_DONE, RESOLVED_NOT_DONE

        cols = [c for c in ("outcome", "updates", "message", "output") if c in fields]
        vals = [json.dumps(fields[c], default=str) if c in self._JSON_COLS else fields[c] for c in cols]
        with self._tx() as db:
            db.execute(f"UPDATE external_calls SET state=?, resolved_by=?, resolved_comment=?, updated_at=?"
                       f"{''.join(f', {c}=?' for c in cols)} WHERE key=?",
                       [RESOLVED_DONE if done else RESOLVED_NOT_DONE, by, comment, _now()] + vals + [key])
        return self.get_call(key)

    def list_calls(self, states: Optional[Iterable[str]] = None, root: Optional[str] = None,
                   run_key: Optional[str] = None, orphans: bool = False) -> List[Dict[str, Any]]:
        sql, where, args = "SELECT * FROM external_calls", [], []
        if states is not None:
            states = list(states)
            where.append(f"state IN ({', '.join('?' for _ in states)})" if states else "0")
            args += states
        if root is not None:
            where.append("root=?")
            args.append(root)
        if run_key is not None:
            where.append("run_key=?")
            args.append(run_key)
        if orphans:
            where.append("run_id IS NULL")
        if where:
            sql += " WHERE " + " AND ".join(where)
        return [self._call_row(r) for r in self._query(sql + " ORDER BY created_at, key", tuple(args))]

    def blocking_calls(self, root: str) -> List[Dict[str, Any]]:
        """Calls on ``root`` that may have acted and that nobody has confirmed: those waiting for a person, and
        calls that may have happened in a run that was never saved (a crash or a failed save)."""
        rows = self._query(
            "SELECT c.*, NOT EXISTS (SELECT 1 FROM runs r WHERE r.run_key = c.run_key) AS orphan "
            "FROM external_calls c WHERE c.root=? AND (c.state IN ('in_flight', 'unknown', 'pending_confirmation') "
            "OR (c.state='done' AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.run_key = c.run_key))) "
            "ORDER BY c.created_at", (root,))
        return [self._call_row(r) for r in rows]

    def mark_interrupted_calls(self) -> List[Dict[str, Any]]:
        """At start-up nothing is executing: a call still ``in_flight`` was cut off by a crash. Its outcome is
        unknown, so it becomes ``unknown`` and waits for a person."""
        rows = self.list_calls(["in_flight"])
        with self._tx() as db:
            db.execute("UPDATE external_calls SET state='unknown', detail='the process stopped while this call "
                       "was in flight', updated_at=? WHERE state='in_flight'", (_now(),))
        return rows

    def _seal_of(self, db, run_id: str) -> Optional[str]:
        """The seal the run's stored row and chain head should carry (None if there is no such run)."""
        from .audit import record_seal, resolve_key

        key = self.audit_key
        row = db.execute("SELECT case_id, goal, ontology, agent, status, started_by, record FROM runs WHERE run_id=?",
                         (run_id,)).fetchone()
        if row is None:
            return None
        head = db.execute("SELECT length, hash FROM audit_heads WHERE run_id=?", (run_id,)).fetchone()
        return record_seal(run_id, [row["case_id"], row["goal"], row["ontology"], row["agent"], row["status"],
                                    row["started_by"], row["record"], head and head["length"], head and head["hash"]],
                           resolve_key(key))

    def seal_ok(self, run_id: str) -> bool:
        """Does the stored run record still match the seal Autology gave it? (True when there is no record.)"""
        import hmac

        with self._lock:
            expected = self._seal_of(self._db, run_id)
            row = self._db.execute("SELECT seal FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if expected is None:
            return True
        return bool(row["seal"]) and hmac.compare_digest(row["seal"], expected)

    def audit_log(self, run_id: str) -> AuditLog:
        rows = self._query("SELECT * FROM audit WHERE run_id=? ORDER BY seq", (run_id,))
        heads = self._query("SELECT length, hash, mac FROM audit_heads WHERE run_id=?", (run_id,))
        return AuditLog.from_list([{"seq": r["seq"], "timestamp": r["timestamp"], "event": r["event"],
                                    "data": json.loads(r["data"]), "prev_hash": r["prev_hash"], "hash": r["hash"],
                                    "alg": r["alg"]} for r in rows],
                                  dict(heads[0]) if heads else None, key=self.audit_key)

    def audit_heads(self) -> List[Dict[str, Any]]:
        """Every run's chain head (length, last hash, MAC): publish these somewhere the operators cannot edit."""
        return [dict(r) for r in self._query("SELECT * FROM audit_heads ORDER BY run_id")]

    def load_run(self, run_id: str) -> RunResult:
        from .persistence import result_from_dict

        rows = self._query("SELECT record FROM runs WHERE run_id=?", (run_id,))
        if not rows:
            raise KeyError(run_id)
        record = json.loads(rows[0]["record"])
        record["audit"] = self.audit_log(run_id).to_list()  # the append-only table is authoritative
        result = result_from_dict(record)
        result.audit.key = self.audit_key
        result.run_id = run_id
        if not self.seal_ok(run_id):  # an edit outside Autology: the run must not resume (audit GAP-014)
            result.integrity_problem = "the stored run record was changed outside Autology (its seal does not match)"
        return result

    def list_runs(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        sql = "SELECT run_id, case_id, goal, ontology, agent, status, created_at, updated_at, started_by FROM runs"
        args: tuple = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY created_at DESC, run_id LIMIT ? OFFSET ?"
        return [dict(r) for r in self._query(sql, args + (int(limit), int(offset)))]

    def all_runs(self, status: Optional[str] = None) -> List[RunResult]:
        return [self.load_run(r["run_id"]) for r in self.list_runs(status, limit=10 ** 9)]

    def verify_audit(self, run_id: str) -> bool:
        log = self.audit_log(run_id)
        return log.verify() and (len(log) == 0 or list(log)[0].prev_hash == GENESIS) and self.seal_ok(run_id)

    def audit_events(self, event: Optional[str] = None, run_id: Optional[str] = None,
                     limit: int = 200) -> List[Dict[str, Any]]:
        sql, args, where = "SELECT * FROM audit", [], []
        if event:
            where.append("event=?")
            args.append(event)
        if run_id:
            where.append("run_id=?")
            args.append(run_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY timestamp DESC, run_id, seq DESC LIMIT ?"
        args.append(int(limit))
        return [{**dict(r), "data": json.loads(r["data"])} for r in self._query(sql, tuple(args))]

    # -- reviews ------------------------------------------------------------
    def create_review(self, run_id: str, request: ReviewRequest) -> str:
        review_id = uuid.uuid4().hex[:12]
        with self._tx() as db:
            db.execute("INSERT INTO reviews VALUES (?, ?, ?, ?, 'pending', ?, NULL, ?, NULL, NULL)",
                       (review_id, run_id, request.action, json.dumps(list(request.reviewers)),
                        json.dumps(request.__dict__, default=str), _now()))
        return review_id

    def _review(self, row) -> Dict[str, Any]:
        out = dict(row)
        out["reviewers"] = json.loads(out["reviewers"])
        out["request"] = json.loads(out["request"])
        out["decision"] = json.loads(out["decision"]) if out["decision"] else None
        return out

    def get_review(self, review_id: str) -> Dict[str, Any]:
        rows = self._query("SELECT * FROM reviews WHERE review_id=?", (review_id,))
        if not rows:
            raise KeyError(review_id)
        return self._review(rows[0])

    def list_reviews(self, status: Optional[str] = "pending", reviewer_roles: Optional[Iterable[str]] = None,
                     limit: int = 100) -> List[Dict[str, Any]]:
        sql, args = "SELECT * FROM reviews", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        rows = [self._review(r) for r in self._query(sql + " ORDER BY created_at, review_id", args)]
        if reviewer_roles is not None:
            roles = set(reviewer_roles)
            rows = [r for r in rows if roles & set(r["reviewers"])]
        return rows[:limit]

    def reopen_review(self, review_id: str) -> None:
        """Undo a decision whose run could not be saved, so the review can be decided again."""
        with self._tx() as db:
            db.execute("UPDATE reviews SET status='pending', decision=NULL, decided_at=NULL, decided_by=NULL "
                       "WHERE review_id=?", (review_id,))

    def decide_review(self, review_id: str, approved: bool, reviewer: str, comment: str = "") -> Dict[str, Any]:
        """Record a decision on a pending review exactly once."""
        with self._tx() as db:
            row = db.execute("SELECT status FROM reviews WHERE review_id=?", (review_id,)).fetchone()
            if row is None:
                raise KeyError(review_id)
            if row["status"] != "pending":
                raise StoreError(f"review {review_id} was already decided ({row['status']})")
            decision = {"approved": bool(approved), "reviewer": reviewer, "comment": comment}
            db.execute("UPDATE reviews SET status=?, decision=?, decided_at=?, decided_by=? WHERE review_id=?",
                       ("approved" if approved else "declined", json.dumps(decision), _now(), reviewer, review_id))
        return self.get_review(review_id)

    # -- automations and notifications --------------------------------------
    def automation_state(self, automation: str, instance: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT active, last_fired, failures FROM automation_state WHERE automation=? AND "
                           "instance=?", (automation, instance))
        return dict(rows[0]) if rows else None

    def set_automation_state(self, automation: str, instance: str, active: bool,
                             fired_at: Optional[float] = None) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO automation_state (automation, instance, active, last_fired) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(automation, instance) DO UPDATE "
                       "SET active=excluded.active, last_fired=COALESCE(excluded.last_fired, last_fired)",
                       (automation, instance, int(active), fired_at))

    def set_automation_failures(self, automation: str, instance: str, failures: int) -> None:
        with self._tx() as db:
            db.execute("UPDATE automation_state SET failures=? WHERE automation=? AND instance=?",
                       (failures, automation, instance))

    def record_firing(self, firing: Any) -> str:
        firing_id = uuid.uuid4().hex[:12]
        with self._tx() as db:
            db.execute("INSERT INTO automation_firings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (firing_id, firing.automation, firing.instance, firing.trigger, _now(), firing.run_id,
                        firing.status, firing.detail, firing.notification_id))
        return firing_id

    def list_firings(self, automation: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        sql, args = "SELECT * FROM automation_firings", ()
        if automation:
            sql, args = sql + " WHERE automation=?", (automation,)
        return [dict(r) for r in self._query(sql + " ORDER BY fired_at DESC, firing_id LIMIT ?", args + (int(limit),))]

    def add_notification(self, kind: str, roles: Iterable[str], message: str,
                         ref: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        note = {"notification_id": uuid.uuid4().hex[:12], "created_at": _now(), "kind": kind,
                "roles": sorted(set(roles)), "message": message, "ref": dict(ref or {})}
        with self._tx() as db:
            db.execute("INSERT INTO notifications VALUES (?, ?, ?, ?, ?, ?)",
                       (note["notification_id"], note["created_at"], kind, json.dumps(note["roles"]), message,
                        json.dumps(note["ref"], default=str)))
        return note

    def list_notifications(self, roles: Optional[Iterable[str]] = None, since: Optional[str] = None,
                           limit: int = 100) -> List[Dict[str, Any]]:
        """Newest first. ``roles`` = None returns all; otherwise those addressed to one of ``roles``."""
        sql, args = "SELECT * FROM notifications", ()
        if since:
            sql, args = sql + " WHERE created_at > ?", (since,)
        rows = self._query(sql + " ORDER BY created_at DESC, notification_id", args)
        out = []
        wanted = None if roles is None else set(roles)
        for r in rows:
            note = {**dict(r), "roles": json.loads(r["roles"]), "ref": json.loads(r["ref"])}
            if wanted is None or wanted & set(note["roles"]):
                out.append(note)
            if len(out) >= limit:
                break
        return out

    def link_run_sources(self, run_id: str, template: str, root: str, sources: Dict[str, Any],
                         write_back: bool, base: Optional[Dict[str, Any]] = None) -> None:
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO run_sources (run_id, template, root, sources, write_back, base, "
                       "conflicts) VALUES (?, ?, ?, ?, ?, ?, '[]')",
                       (run_id, template, root, json.dumps(sources), int(write_back),
                        json.dumps(base, default=str) if base is not None else None))

    def active_runs_for_root(self, root: str, final: Iterable[str]) -> List[Dict[str, Any]]:
        """Runs built from ``root`` (a case template's root object) that have not reached a final status."""
        final = list(final)
        marks = ", ".join("?" * len(final))
        rows = self._query(
            f"SELECT r.run_id, r.status, r.goal, r.started_by, r.created_at FROM runs r JOIN run_sources s "
            f"ON s.run_id = r.run_id WHERE s.root = ? AND r.status NOT IN ({marks}) ORDER BY r.created_at, r.run_id",
            (root, *final))
        return [dict(r) for r in rows]

    def update_write_back(self, run_id: str, base: Dict[str, Any], conflicts: List[Dict[str, Any]]) -> None:
        with self._tx() as db:
            db.execute("UPDATE run_sources SET base=?, conflicts=? WHERE run_id=?",
                       (json.dumps(base, default=str), json.dumps(conflicts, default=str), run_id))

    def run_sources(self, run_id: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM run_sources WHERE run_id=?", (run_id,))
        if not rows:
            return None
        out = dict(rows[0])
        out["sources"] = json.loads(out["sources"])
        out["write_back"] = bool(out["write_back"])
        out["base"] = json.loads(out["base"]) if out.get("base") else None
        out["conflicts"] = json.loads(out["conflicts"]) if out.get("conflicts") else []
        return out

    # -- scenarios ------------------------------------------------------------
    def save_scenario(self, scenario_id: Optional[str], name: str, created_by: str, edits: List[Dict[str, Any]],
                      snapshot: Dict[str, Any], status: str = "open") -> str:
        scenario_id = scenario_id or uuid.uuid4().hex[:12]
        now = _now()
        with self._tx() as db:
            db.execute("INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(scenario_id) DO UPDATE SET "
                       "name=excluded.name, updated_at=excluded.updated_at, status=excluded.status, "
                       "edits=excluded.edits, snapshot=excluded.snapshot",
                       (scenario_id, name, created_by, now, now, status, json.dumps(edits, default=str),
                        json.dumps(snapshot, default=str)))
        return scenario_id

    def get_scenario(self, scenario_id: str) -> Dict[str, Any]:
        rows = self._query("SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,))
        if not rows:
            raise KeyError(scenario_id)
        out = dict(rows[0])
        out["edits"], out["snapshot"] = json.loads(out["edits"]), json.loads(out["snapshot"])
        return out

    def list_scenarios(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql, args = "SELECT scenario_id, name, created_by, created_at, updated_at, status FROM scenarios", ()
        if status:
            sql, args = sql + " WHERE status=?", (status,)
        return [dict(r) for r in self._query(sql + " ORDER BY updated_at DESC, scenario_id", args)]

    # -- assistant conversations ---------------------------------------------
    def save_chat(self, chat_id: str, owner: str, messages: List[Dict[str, Any]]) -> None:
        now = _now()
        with self._tx() as db:
            db.execute("INSERT INTO chats VALUES (?, ?, ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET "
                       "updated_at=excluded.updated_at, messages=excluded.messages",
                       (chat_id, owner, now, now, json.dumps(messages, default=str)))

    def get_chat(self, chat_id: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM chats WHERE chat_id=?", (chat_id,))
        if not rows:
            return None
        out = dict(rows[0])
        out["messages"] = json.loads(out["messages"])
        return out

    # -- access log (append-only) -----------------------------------------------
    def log_access(self, principal: str, kind: str, target: str, status: int) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO access_log (timestamp, principal, kind, target, status) VALUES (?, ?, ?, ?, ?)",
                       (_now(), principal, kind, target[:500], int(status)))

    def access_log(self, principal: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        sql, args = "SELECT * FROM access_log", ()
        if principal:
            sql, args = sql + " WHERE principal=?", (principal,)
        return [dict(r) for r in self._query(sql + " ORDER BY seq DESC LIMIT ?", args + (int(limit),))]

    # -- checkpoint justifications (append-only) ---------------------------------------
    def add_justification(self, principal: str, rule_id: str, operation: str, target: str, text: str) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO justifications (timestamp, principal, rule_id, operation, target, text) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (_now(), principal, rule_id, operation, target[:500], text[:2000]))

    def list_justifications(self, limit: int = 200) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._query("SELECT * FROM justifications ORDER BY seq DESC LIMIT ?", (int(limit),))]

    def run_starter(self, run_id: str) -> Optional[str]:
        rows = self._query("SELECT started_by FROM runs WHERE run_id=?", (run_id,))
        return rows[0]["started_by"] if rows else None

    # -- agent suspensions ------------------------------------------------------
    def active_suspension(self, agent: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM suspensions WHERE agent=? AND reinstated_at IS NULL ORDER BY seq DESC",
                           (agent,))
        return dict(rows[0]) if rows else None

    def suspend(self, agent: str, reason: str, run_id: Optional[str] = None) -> None:
        with self._tx() as db:
            if db.execute("SELECT 1 FROM suspensions WHERE agent=? AND reinstated_at IS NULL", (agent,)).fetchone():
                return
            db.execute("INSERT INTO suspensions (agent, suspended_at, reason, run_id) VALUES (?, ?, ?, ?)",
                       (agent, _now(), reason, run_id))

    def reinstate(self, agent: str, by: str, reason: str) -> None:
        with self._tx() as db:
            db.execute("UPDATE suspensions SET reinstated_at=?, reinstated_by=?, reinstate_reason=? "
                       "WHERE agent=? AND reinstated_at IS NULL", (_now(), by, reason, agent))

    def suspension_history(self, agent: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._query("SELECT * FROM suspensions WHERE agent=? ORDER BY seq DESC", (agent,))]

    # -- run proposals from the assistant -----------------------------------------
    def add_proposal(self, owner: str, body: Dict[str, Any]) -> Dict[str, Any]:
        pid = uuid.uuid4().hex[:12]
        with self._tx() as db:
            db.execute("INSERT INTO proposals (proposal_id, owner, created_at, status, body) VALUES (?, ?, ?, ?, ?)",
                       (pid, owner, _now(), "pending", json.dumps(body)))
        return self.get_proposal(pid)

    def get_proposal(self, pid: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM proposals WHERE proposal_id=?", (pid,))
        return {**dict(rows[0]), "body": json.loads(rows[0]["body"])} if rows else None

    def list_proposals(self, owner: str, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self._query("SELECT * FROM proposals WHERE owner=? ORDER BY created_at DESC LIMIT ?", (owner, limit))
        return [{**dict(r), "body": json.loads(r["body"])} for r in rows]

    def claim_proposal(self, pid: str) -> bool:
        """Move a pending proposal to 'starting'; False if someone else got there first."""
        with self._tx() as db:
            return db.execute("UPDATE proposals SET status='starting' WHERE proposal_id=? AND status='pending'",
                              (pid,)).rowcount == 1

    def settle_proposal(self, pid: str, status: str, run_id: Optional[str] = None) -> None:
        with self._tx() as db:
            db.execute("UPDATE proposals SET status=?, run_id=?, decided_at=? WHERE proposal_id=?",
                       (status, run_id, _now() if status != "pending" else None, pid))

    # -- small settings (non-secret) -------------------------------------------
    def get_meta(self, key: str) -> Optional[Any]:
        rows = self._query("SELECT value FROM meta WHERE key=?", ("setting:" + key,))
        return json.loads(rows[0]["value"]) if rows else None

    def set_meta(self, key: str, value: Any) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("setting:" + key, json.dumps(value)))

    # -- ingestion ---------------------------------------------------------
    def ingest_watermarks(self, pipeline: str) -> Dict[str, str]:
        return {r["source"]: r["watermark"]
                for r in self._query("SELECT source, watermark FROM ingest_state WHERE pipeline=?", (pipeline,))}

    def apply_ingest(self, plan: Any, triggered_by: str, dry_run: bool = False) -> str:
        """Write a load in one transaction: objects, links, lineage, quarantined rows, watermarks and the batch."""
        batch_id = uuid.uuid4().hex[:12]
        now = _now()
        summary = plan.summary()
        summary["dry_run"] = dry_run
        with self._tx() as db:
            if not dry_run:
                for iid, (etype, values) in plan.creates.items():
                    db.execute("INSERT INTO instances VALUES (?, ?, ?, ?)",
                               (iid, etype, json.dumps(values, default=str), now))
                for iid, (etype, diff) in plan.updates.items():
                    row = db.execute("SELECT attributes FROM instances WHERE id=?", (iid,)).fetchone()
                    merged = {**json.loads(row["attributes"]), **diff} if row else dict(diff)
                    db.execute("INSERT INTO instances VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                               "attributes=excluded.attributes, updated_at=excluded.updated_at",
                               (iid, etype, json.dumps(merged, default=str), now))
                for source, kind, target in plan.links:
                    db.execute("INSERT OR IGNORE INTO links VALUES (?, ?, ?)", (source, kind, target))
                for entry in plan.lineage:
                    db.execute("INSERT INTO lineage (instance_id, entity, batch_id, pipeline, source, row, action, "
                               "attributes, links, loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (entry["instance_id"], entry["entity"], batch_id, plan.pipeline, entry["source"],
                                entry["row"], entry["action"], json.dumps(entry["attributes"]),
                                json.dumps(entry["links"]), now))
                for source, mark in plan.watermarks.items():
                    db.execute("INSERT INTO ingest_state VALUES (?, ?, ?, ?) ON CONFLICT(pipeline, source) DO "
                               "UPDATE SET watermark=excluded.watermark, updated_at=excluded.updated_at",
                               (plan.pipeline, source, mark, now))
            for seq, rej in enumerate(plan.rejected):
                db.execute("INSERT INTO ingest_rejects VALUES (?, ?, ?, ?, ?, ?)",
                           (batch_id, seq, rej.source, rej.row, rej.reason, json.dumps(rej.data, default=str)))
            db.execute("INSERT INTO ingest_batches VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (batch_id, plan.pipeline, now, _now(), "dry_run" if dry_run else "loaded", triggered_by,
                        json.dumps(summary, default=str)))
        return batch_id

    def record_ingest_failure(self, pipeline: str, triggered_by: str, error: str) -> str:
        batch_id = uuid.uuid4().hex[:12]
        now = _now()
        with self._tx() as db:
            db.execute("INSERT INTO ingest_batches VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (batch_id, pipeline, now, now, "failed", triggered_by, json.dumps({"error": error})))
        return batch_id

    def ingest_batches(self, pipeline: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        sql, args = "SELECT * FROM ingest_batches", ()
        if pipeline:
            sql, args = sql + " WHERE pipeline=?", (pipeline,)
        rows = self._query(sql + " ORDER BY started_at DESC, rowid DESC LIMIT ?", args + (limit,))
        return [{**{k: r[k] for k in r.keys() if k != "summary"}, "summary": json.loads(r["summary"])} for r in rows]

    def ingest_rejects(self, batch_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
        return [{"source": r["source"], "row": r["row"], "reason": r["reason"], "data": json.loads(r["data"])}
                for r in self._query("SELECT * FROM ingest_rejects WHERE batch_id=? ORDER BY seq LIMIT ?",
                                     (batch_id, limit))]

    def lineage(self, instance_id: str) -> List[Dict[str, Any]]:
        return [{"batch_id": r["batch_id"], "pipeline": r["pipeline"], "source": r["source"], "row": r["row"],
                 "action": r["action"], "attributes": json.loads(r["attributes"]), "links": json.loads(r["links"]),
                 "loaded_at": r["loaded_at"]}
                for r in self._query("SELECT * FROM lineage WHERE instance_id=? ORDER BY seq", (instance_id,))]

    # -- backups ------------------------------------------------------------
    def backup(self, target: Union[str, Path]) -> Dict[str, Any]:
        """A consistent copy of the live store (SQLite's online backup: safe while the server runs).

        The copy is written next to ``target`` and renamed into place, then opened and checked: schema version,
        and every run's audit chain. Returns counts and the runs that did not verify (should be none).
        """
        import os
        import tempfile

        path = Path(target).resolve()
        if path == Path(self.path).resolve():
            raise StoreError("the backup must not overwrite the live store")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".backup-", suffix=".db", dir=str(path.parent))
        os.close(fd)
        try:
            dest = sqlite3.connect(tmp)
            try:
                with self._lock:
                    self._db.backup(dest)
                dest.execute("PRAGMA journal_mode=DELETE")  # one self-contained file, no -wal sidecar
            finally:
                dest.close()
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        copy = Store(path, audit_key=self.audit_key)
        try:
            runs = [r["run_id"] for r in copy.list_runs(limit=10 ** 9)]
            bad = [r for r in runs if not copy.verify_audit(r)]
            return {"path": str(path), "bytes": path.stat().st_size, "instances": copy.count_instances(),
                    "runs": len(runs), "unverified_runs": bad,
                    "schema": int(copy._query("SELECT value FROM meta WHERE key='schema_version'")[0]["value"])}
        finally:
            copy.close()
            plain = sqlite3.connect(path)  # opening it as a store switched it to WAL: back to one file
            plain.execute("PRAGMA journal_mode=DELETE")
            plain.close()


class StoreJournal:
    """The external effects journal (see :mod:`autology.effects`) kept in the store, so it survives a crash."""

    def __init__(self, store: Store, agent: Optional[str] = None):
        self.store = store
        self.agent = agent

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self.store.get_call(key)

    def intent(self, key: str, **fields: Any) -> None:
        self.store.record_intent(key, agent=fields.pop("agent", None) or self.agent, **fields)

    def result(self, key: str, state: str, **fields: Any) -> None:
        self.store.record_call_result(key, state, **fields)

    def resolve(self, key: str, done: bool, by: str, comment: str, **fields: Any) -> Dict[str, Any]:
        return self.store.resolve_call(key, done, by, comment, **fields)

    def rows(self, run_key: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.list_calls(run_key=run_key)
