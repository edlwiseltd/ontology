"""Persistent store (SQLite, standard library): knowledge graph, runs, append-only audit, reviews.

One file holds everything a deployment needs to survive restarts:

* ``instances`` / ``links`` - the knowledge graph (load with :meth:`Store.load_graph`);
* ``runs``                  - every agent run, including deferred / paused / awaiting-review runs
                              with what is needed to resume them;
* ``audit``                 - every audit entry of every run, hash-chained. **Append-only**:
                              database triggers reject any UPDATE or DELETE, and saving a run
                              refuses if its history diverges from what is stored;
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
from .ontology import Ontology

SCHEMA_VERSION = 4

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
    started_by TEXT);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
CREATE TABLE IF NOT EXISTS audit (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, timestamp TEXT NOT NULL, event TEXT NOT NULL, data TEXT NOT NULL,
    prev_hash TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY (run_id, seq));
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
    PRIMARY KEY (automation, instance));
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
CREATE TABLE IF NOT EXISTS run_sources (
    run_id TEXT PRIMARY KEY, template TEXT NOT NULL, root TEXT NOT NULL, sources TEXT NOT NULL,
    write_back INTEGER NOT NULL);
"""


class StoreError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Union[str, Path] = ":memory:"):
        self.path = str(path)
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

    def load_graph(self, ontology: Ontology) -> KnowledgeGraph:
        """Rebuild the graph; every instance and link is re-validated against ``ontology``."""
        graph = KnowledgeGraph(ontology)
        for row in self._query("SELECT id, type, attributes FROM instances ORDER BY id"):
            attrs = json.loads(row["attributes"])
            graph.add(row["type"], row["id"], **attrs)
        for row in self._query("SELECT source, kind, target FROM links ORDER BY source, kind, target"):
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
                db.execute("INSERT INTO audit VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (run_id, e["seq"], e["timestamp"], e["event"], json.dumps(e["data"], default=str),
                            e["prev_hash"], e["hash"]))
            exists = db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if exists:
                db.execute("UPDATE runs SET status=?, updated_at=?, record=?, agent=COALESCE(?, agent) WHERE run_id=?",
                           (result.status, now, json.dumps(record, default=str), agent, run_id))
            else:
                db.execute("INSERT INTO runs (run_id, case_id, goal, ontology, agent, status, created_at, updated_at, "
                           "record, started_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (run_id, result.case_id, result.goal, ontology_ref, agent, result.status, now, now,
                            json.dumps(record, default=str), started_by))
        result.run_id = run_id
        return run_id

    def audit_log(self, run_id: str) -> AuditLog:
        rows = self._query("SELECT * FROM audit WHERE run_id=? ORDER BY seq", (run_id,))
        return AuditLog.from_list([{"seq": r["seq"], "timestamp": r["timestamp"], "event": r["event"],
                                    "data": json.loads(r["data"]), "prev_hash": r["prev_hash"], "hash": r["hash"]}
                                   for r in rows])

    def load_run(self, run_id: str) -> RunResult:
        from .persistence import result_from_dict

        rows = self._query("SELECT record FROM runs WHERE run_id=?", (run_id,))
        if not rows:
            raise KeyError(run_id)
        record = json.loads(rows[0]["record"])
        record["audit"] = self.audit_log(run_id).to_list()  # the append-only table is authoritative
        result = result_from_dict(record)
        result.run_id = run_id
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
        return log.verify() and (len(log) == 0 or list(log)[0].prev_hash == GENESIS)

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
        rows = self._query("SELECT active, last_fired FROM automation_state WHERE automation=? AND instance=?",
                           (automation, instance))
        return dict(rows[0]) if rows else None

    def set_automation_state(self, automation: str, instance: str, active: bool,
                             fired_at: Optional[float] = None) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO automation_state VALUES (?, ?, ?, ?) ON CONFLICT(automation, instance) DO UPDATE "
                       "SET active=excluded.active, last_fired=COALESCE(excluded.last_fired, last_fired)",
                       (automation, instance, int(active), fired_at))

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
                         write_back: bool) -> None:
        with self._tx() as db:
            db.execute("INSERT OR REPLACE INTO run_sources VALUES (?, ?, ?, ?, ?)",
                       (run_id, template, root, json.dumps(sources), int(write_back)))

    def run_sources(self, run_id: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM run_sources WHERE run_id=?", (run_id,))
        if not rows:
            return None
        out = dict(rows[0])
        out["sources"] = json.loads(out["sources"])
        out["write_back"] = bool(out["write_back"])
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
