"""Tenants: the customer organisations that own workspaces (IAM-1; owner decision D22).

A **tenant** is one customer organisation. It owns one or more **workspaces**; a workspace belongs to exactly one
tenant. Identities belong to one tenant and never reach another tenant's workspaces.

Which tenant a workspace belongs to is a governance record, not just a line of configuration: it is kept in
``<data_dir>/tenancy.db``, a versioned registry whose assignment history is append-only (the database refuses
updates and deletes) and chained with a key derived from the platform's audit key. The platform configuration must
agree with it:

* **migration** (registry schema 1): a workspace that already has data when the registry first sees it is recorded
  in a **dedicated tenant** with the workspace's own id, whatever the configuration says. Existing customers are
  therefore never merged by an upgrade, and their behaviour does not change;
* a workspace with no data yet is recorded in the tenant the configuration gives it (or its dedicated tenant);
* afterwards, a configuration that places a workspace in another tenant than the recorded one is **refused at
  start-up**: tenants are merged or split only by an explicit, reasoned operator action
  (``python -m autology tenancy assign``), which is appended to the history.

The registry adds a file and changes no existing one (stores, stage, release and administration histories and the
per-workspace audit keys are untouched), so the previous software version still starts on the same data.

Limits, stated plainly: this is an application-level control. Whoever can write the data directory, the
configuration or the audit key is outside it (infrastructure controls: file permissions, backups, encryption, key
custody). Platform operators have no identity in Autology yet (IAM-2): the explicit action records the operating
system user as a claim, not as an authenticated principal.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 1
GENESIS = "0" * 64
EVENTS = ("migrated", "assigned", "reassigned")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignments (
    seq INTEGER PRIMARY KEY, workspace TEXT NOT NULL, tenant TEXT NOT NULL, event TEXT NOT NULL, by TEXT NOT NULL,
    reason TEXT NOT NULL, at TEXT NOT NULL, prev TEXT NOT NULL, mac TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS assignments_append_only_u BEFORE UPDATE ON assignments
    BEGIN SELECT RAISE(ABORT, 'the tenancy history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS assignments_append_only_d BEFORE DELETE ON assignments
    BEGIN SELECT RAISE(ABORT, 'the tenancy history is append-only'); END;
"""


class TenancyError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Tenancy:
    """The registry of workspace -> tenant assignments."""

    def __init__(self, path: Path, key: Optional[bytes]):
        self.path = Path(path)
        self._key = key
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")  # schema and version together: an interrupted creation leaves nothing
            try:
                for statement in SCHEMA.strip().split(";\n"):
                    if statement.strip():
                        self._db.execute(statement)
                row = self._db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                if row is None:
                    self._db.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
                elif int(row["value"]) > SCHEMA_VERSION:
                    raise TenancyError(f"the tenancy registry has schema {row['value']}, newer than this Autology "
                                       f"({SCHEMA_VERSION}): upgrade Autology, do not downgrade the registry")
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                self._db.close()
                raise

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- chain ------------------------------------------------------------------------------------------------
    def _mac(self, payload: Dict[str, Any]) -> str:
        data = json.dumps(["autology-tenancy", payload], sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self._key, data, hashlib.sha256).hexdigest() if self._key else hashlib.sha256(data).hexdigest()

    @staticmethod
    def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: row[k] for k in ("seq", "workspace", "tenant", "event", "by", "reason", "at", "prev")}

    def history(self) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Every assignment, oldest first, and an integrity problem if the history does not verify."""
        with self._lock:
            rows = [dict(r) for r in self._db.execute("SELECT * FROM assignments ORDER BY seq")]
        prev, problem = GENESIS, None
        for i, row in enumerate(rows):
            if row["seq"] != i + 1 or row["prev"] != prev or row["event"] not in EVENTS or not hmac.compare_digest(
                    row["mac"], self._mac(self._payload(row))):
                problem = f"the tenancy history was changed outside Autology (entry {i + 1} does not verify)"
                break
            prev = row["mac"]
        return [{k: r[k] for k in ("seq", "workspace", "tenant", "event", "by", "reason", "at")} for r in rows], problem

    def current(self) -> Dict[str, str]:
        """workspace -> tenant, as recorded. Raises :class:`TenancyError` if the history does not verify."""
        events, problem = self.history()
        if problem:
            raise TenancyError(problem)
        return {e["workspace"]: e["tenant"] for e in events}

    def _append(self, workspace: str, tenant: str, event: str, by: str, reason: str) -> None:
        last = self._db.execute("SELECT seq, mac FROM assignments ORDER BY seq DESC LIMIT 1").fetchone()
        row = {"seq": (last["seq"] + 1) if last else 1, "workspace": workspace, "tenant": tenant, "event": event,
               "by": by, "reason": reason, "at": _now(), "prev": last["mac"] if last else GENESIS}
        row["mac"] = self._mac(self._payload(row))
        self._db.execute("INSERT INTO assignments VALUES (:seq, :workspace, :tenant, :event, :by, :reason, :at, :prev, "
                         ":mac)", row)

    # -- operations -------------------------------------------------------------------------------------------
    def reconcile(self, configured: Dict[str, str], existing: Iterable[str]) -> Dict[str, str]:
        """Record the workspaces the registry does not know yet, then check the configuration against it.

        ``configured`` maps every workspace of the configuration to its tenant; ``existing`` names the workspaces
        that already have data. All new records are written in one transaction, or none."""
        existing = set(existing)
        with self._lock:
            recorded = self.current()
            fresh = [(ws, tenant) for ws, tenant in configured.items() if ws not in recorded]
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for ws, tenant in fresh:
                    if ws in existing:  # an existing customer: its own tenant, never merged by an upgrade
                        self._append(ws, ws, "migrated", "autology",
                                     "existing workspace recorded in its own dedicated tenant (tenancy schema 1)")
                    else:
                        self._append(ws, tenant, "assigned", "configuration", "first seen in the configuration")
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            recorded = self.current()
        wrong = sorted((ws, recorded[ws], tenant) for ws, tenant in configured.items() if recorded[ws] != tenant)
        if wrong:
            lines = "; ".join(f"workspace {ws} is recorded in tenant {have!r} but the configuration places it in "
                              f"{want!r}" for ws, have, want in wrong)
            raise TenancyError(
                f"{lines}. Tenants are never merged or split implicitly: either put the workspace back in its "
                "recorded tenant in the configuration, or record the change explicitly with "
                "`python -m autology tenancy assign PLATFORM.json WORKSPACE TENANT --reason \"...\"`")
        return recorded

    def assign(self, workspace: str, tenant: str, by: str, reason: str) -> Dict[str, str]:
        """The explicit operator action: move a workspace to another tenant, with a reason, in the history."""
        reason = (reason or "").strip()
        if not (10 <= len(reason) <= 500):
            raise TenancyError("give a reason of 10 to 500 characters: who asked for this change and why")
        with self._lock:
            recorded = self.current()
            if recorded.get(workspace) == tenant:
                raise TenancyError(f"workspace {workspace} is already recorded in tenant {tenant}")
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._append(workspace, tenant, "reassigned" if workspace in recorded else "assigned", by, reason)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            return self.current()
