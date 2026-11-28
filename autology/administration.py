"""Workspace administration without restarts (ADM-1, ADM-2; owner decision D11).

``platform.json`` stays the base: its workspace administrators, its members and their grants. On top of it, the
platform keeps an **administration log** per workspace, in ``<data_dir>/admin.db``: append-only (the database
refuses updates and deletes) and chained with the workspace's audit key (an edited or deleted entry is detected).
The members a workspace has at any moment are the configuration's, with the log replayed over them:

* ``member_added`` / ``member_removed`` / ``token_rotated``: a workspace administrator (a person) adds a person or a
  service identity (the platform generates its token and shows it once; only its SHA-256 is kept), removes a member,
  or replaces a member's token. Workspace administrators themselves are managed in ``platform.json`` only, so no API
  call can create an administrator;
* ``grant_proposed`` -> ``grant_approved`` | ``grant_withdrawn``: a workspace administrator proposes what a member
  may do on one use case; the grant takes effect only when **another person with authority** approves it (a
  workspace administrator or a named approver, ``release_approvers``), who is neither the proposer nor the member
  who receives it, and never a service identity;
* ``grant_revoked``: a workspace administrator takes a member's access to a use case away, at once (removing access
  needs no second person).
* ``token_revoked``: a workspace administrator makes a member's token stop working at once, without removing the
  member or their grants; the member has no credential until an administrator issues a new token (GAP-030).
* ``token_requested`` -> ``token_rotated`` | ``token_request_withdrawn``: a new token for a member who holds
  business-data access is requested by an administrator and issued by **another** person with authority, who is
  the only one to see it; so no single administrator can take over a member's access by re-keying them;
* ``grant_confirmed``: a person with authority, not the member concerned, reviewed an existing grant (for example
  one created by the IAM-3 migration) and kept it, with a reason.

Every change reaches the use cases' engines before the next request (no restart). If the log does not verify, the
workspace falls back to its configured administrators only (fail closed) until an operator repairs it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

GENESIS = "0" * 64
EVENTS = ("member_added", "member_removed", "token_rotated", "grant_proposed", "grant_approved", "grant_withdrawn",
          "grant_revoked", "engine_reloaded", "draft_published", "release_restored",
          # IAM-3: the data access an administrator had implicitly, converted once into explicit, revocable grants
          "grant_migrated", "privileges_separated",
          # GAP-030: a member's token refused from now on, until an administrator issues a new one
          "token_revoked",
          # R2 security sprint B: a person with authority looked at an existing grant and kept it; a new token for
          # a member who holds business data is requested by one person and issued by another
          "grant_confirmed", "token_requested", "token_request_withdrawn",
          # activation sprint B: an activation or rollback that was refused leaves evidence too
          "release_activation_refused",
          # architect sprint A2: sample records are loaded by a person's explicit request, never by a release
          "sample_data_loaded",
          # architect sprint A4: a backup was taken, verified and restored into a scratch folder, and each use
          # case's restored configuration was loaded: evidence, recorded only when every step succeeded
          "recovery_rehearsed",
          # architect sprint B: a workspace's AI provider policy is proposed by one person and approved by another;
          # one person may always withdraw a proposal or disable a policy (taking access away needs no second)
          "ai_policy_proposed", "ai_policy_approved", "ai_policy_withdrawn", "ai_policy_disabled")


def ai_policy_state(events: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """``(approved policy in force or None, pending proposals by id)`` from a workspace's events."""
    pending: Dict[str, Dict[str, Any]] = {}
    current: Optional[Dict[str, Any]] = None
    for e in events:
        if e["event"] == "ai_policy_proposed":
            pending[e["data"]["id"]] = {"id": e["data"]["id"], "policy": e["data"]["policy"], "proposed_by": e["by"],
                                        "proposed_at": e["at"], "reason": e["reason"]}
        elif e["event"] == "ai_policy_withdrawn":
            pending.pop(e["data"]["id"], None)
        elif e["event"] == "ai_policy_approved":
            proposal = pending.pop(e["data"]["id"], None)
            if proposal is not None:
                current = {**proposal, "approved_by": e["by"], "approved_at": e["at"]}
        elif e["event"] == "ai_policy_disabled":
            current = None
    return current, pending

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_events (
    workspace TEXT NOT NULL, seq INTEGER NOT NULL, event TEXT NOT NULL, by TEXT NOT NULL, reason TEXT NOT NULL,
    data TEXT NOT NULL, at TEXT NOT NULL, prev TEXT NOT NULL, mac TEXT NOT NULL, PRIMARY KEY (workspace, seq));
CREATE TRIGGER IF NOT EXISTS admin_events_append_only_u BEFORE UPDATE ON admin_events
    BEGIN SELECT RAISE(ABORT, 'the administration log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS admin_events_append_only_d BEFORE DELETE ON admin_events
    BEGIN SELECT RAISE(ABORT, 'the administration log is append-only'); END;
"""


class AdminError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class AdminLog:
    def __init__(self, path: Path, key_for: Callable[[str], Optional[bytes]]):
        self.path = Path(path)
        self._key_for = key_for
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _mac(self, workspace: str, payload: Dict[str, Any]) -> str:
        data = _canonical(["autology-admin-event", payload]).encode()
        key = self._key_for(workspace)
        return hmac.new(key, data, hashlib.sha256).hexdigest() if key else hashlib.sha256(data).hexdigest()

    @staticmethod
    def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: row[k] for k in ("workspace", "seq", "event", "by", "reason", "data", "at", "prev")}

    def events(self, workspace: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """The workspace's administration events, oldest first, and an integrity problem if they do not verify."""
        with self._lock:
            rows = [dict(r) for r in self._db.execute(
                "SELECT * FROM admin_events WHERE workspace=? ORDER BY seq", (workspace,))]
        prev, problem = GENESIS, None
        for i, row in enumerate(rows):
            if row["seq"] != i + 1 or row["prev"] != prev or row["event"] not in EVENTS or not hmac.compare_digest(
                    row["mac"], self._mac(workspace, self._payload(row))):
                problem = f"the administration log was changed outside Autology (entry {i + 1} does not verify)"
                break
            prev = row["mac"]
        return [{"seq": r["seq"], "event": r["event"], "by": r["by"], "reason": r["reason"],
                 "data": json.loads(r["data"]), "at": r["at"]} for r in rows], problem

    def append(self, workspace: str, event: str, by: str, reason: str, data: Dict[str, Any],
               check: Optional[Callable[[List[Dict[str, Any]]], None]] = None) -> Dict[str, Any]:
        """Append one event after ``check(events)`` accepts it, under one lock (so the check sees what is appended
        to)."""
        if event not in EVENTS:
            raise AdminError(400, f"unknown administration event {event!r}")
        reason = (reason or "").strip()
        if not (1 <= len(reason) <= 500):
            raise AdminError(400, "give a reason (1 to 500 characters)")
        with self._lock:
            events, problem = self.events(workspace)
            if problem:
                raise AdminError(409, problem)
            if check is not None:
                check(events)
            last = self._db.execute("SELECT seq, mac FROM admin_events WHERE workspace=? ORDER BY seq DESC LIMIT 1",
                                    (workspace,)).fetchone()
            row = {"workspace": workspace, "seq": (last["seq"] + 1) if last else 1, "event": event, "by": by,
                   "reason": reason, "data": _canonical(data), "at": _now(), "prev": last["mac"] if last else GENESIS}
            row["mac"] = self._mac(workspace, self._payload(row))
            self._db.execute("INSERT INTO admin_events VALUES (:workspace, :seq, :event, :by, :reason, :data, :at, "
                             ":prev, :mac)", row)
        return {"seq": row["seq"], "event": event, "by": by, "reason": reason, "data": data, "at": row["at"]}

    def append_batch(self, workspace: str, items: List[Tuple[str, str, str, Dict[str, Any]]]) -> int:
        """Append several events ``(event, by, reason, data)`` in one transaction: all of them, or none (a
        migration interrupted half-way leaves the log as it was and is simply run again)."""
        with self._lock:
            _, problem = self.events(workspace)
            if problem:
                raise AdminError(409, problem)
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for event, by, reason, data in items:
                    if event not in EVENTS:
                        raise AdminError(400, f"unknown administration event {event!r}")
                    last = self._db.execute("SELECT seq, mac FROM admin_events WHERE workspace=? ORDER BY seq DESC "
                                            "LIMIT 1", (workspace,)).fetchone()
                    row = {"workspace": workspace, "seq": (last["seq"] + 1) if last else 1, "event": event, "by": by,
                           "reason": reason, "data": _canonical(data), "at": _now(),
                           "prev": last["mac"] if last else GENESIS}
                    row["mac"] = self._mac(workspace, self._payload(row))
                    self._db.execute("INSERT INTO admin_events VALUES (:workspace, :seq, :event, :by, :reason, :data, "
                                     ":at, :prev, :mac)", row)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return len(items)


def pending_grants(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Grant proposals not yet approved or withdrawn, by id. Removing a member ends the proposals made for them:
    a later member with the same name never inherits one."""
    out: Dict[str, Dict[str, Any]] = {}
    for e in events:
        if e["event"] == "grant_proposed":
            out[e["data"]["id"]] = {**e["data"], "proposed_by": e["by"], "proposed_at": e["at"], "reason": e["reason"]}
        elif e["event"] in ("grant_approved", "grant_withdrawn"):
            out.pop(e["data"]["id"], None)
        elif e["event"] == "member_removed":
            out = {k: v for k, v in out.items() if v["member"] != e["data"]["name"]}
    return out


def pending_token_requests(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Requests for a member's new token that nobody has issued or withdrawn yet, by id."""
    out: Dict[str, Dict[str, Any]] = {}
    for e in events:
        d = e["data"]
        if e["event"] == "token_requested":
            out[d["id"]] = {"id": d["id"], "name": d["name"], "requested_by": e["by"], "requested_at": e["at"],
                            "reason": e["reason"]}
        elif e["event"] == "token_request_withdrawn" or (e["event"] == "token_rotated" and d.get("request")):
            out.pop(d.get("request") or d.get("id"), None)
        elif e["event"] == "member_removed":
            out = {k: v for k, v in out.items() if v["name"] != d["name"]}
    return out


def new_grant_id() -> str:
    return "g-" + uuid.uuid4().hex[:12]
