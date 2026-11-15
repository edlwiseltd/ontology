"""Immutable use-case releases (REL-1a, master directive V2; owner decision D11).

A **release** is an immutable, content-addressed snapshot of a use case's *governing configuration*: the
ontology document, the engine settings that decide what runs and who may do what (agents, approvers, automations,
service identities, webhooks, checkpoints...), and the tool declarations each agent uses. Its **fingerprint** is
the SHA-256 of the canonical JSON of that snapshot. Deployment details that do not change behaviour (store path,
members and their tokens, the workspace's sign-in, log and secrets files) are not part of it, so the same
configuration has the same fingerprint in every workspace.

The lifecycle of a release, recorded as an append-only chain keyed with the workspace's audit key:

``proposed`` -> ``approved`` (or ``approval_revoked``) -> ``activated`` / ``rolled_back``

* **propose**: a workspace administrator (a person) records the configuration the engine is running now;
* **approve**: a *separately authenticated person* with release authority (a workspace administrator, or a member
  the workspace names in ``release_approvers``, such as a designated external approver) who is **not** the proposer
  and not a service identity. The approval is bound to the release's fingerprint;
* **activate**: a workspace administrator makes an approved release the governed one. Activation is accepted only
  when the engine is running exactly that configuration (same fingerprint): nothing is activated that was not
  approved, and nothing approved is silently replaced. Activating an older approved release is a **rollback**;
* **drift**: while a release is active, an engine whose running configuration has another fingerprint counts as
  ``draft`` (nothing runs, nothing is sent) until a person activates the matching approved release.

Three approvals stay distinct: approving a **configuration release** (here) does not authorise any business
action; **business actions** stay governed by the ontology's rules and the use-case stage; **runtime approvals**
(human reviews) stay per run. A run is bound to the configuration it started on and does not continue on another
one (``WorkAgent.resume``).

The snapshot covers configuration files (ontology, server settings, tool declarations). Python code that tools or
reasoners import is not in it; a release fingerprint therefore attests the declared configuration, not the code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

FORMAT = "autology-release/1"
GENESIS = "0" * 64
# server settings that describe the deployment, not what runs: never part of a release
NON_GOVERNING = frozenset({"store", "users", "log_file", "secrets_file", "audit_scope", "oidc", "data", "ontology",
                           "writer", "reporting", "readiness"})
EVENTS = ("proposed", "approved", "approval_revoked", "activated", "rolled_back")

SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
    workspace TEXT NOT NULL, use_case TEXT NOT NULL, number INTEGER NOT NULL, fingerprint TEXT NOT NULL,
    ontology_ref TEXT NOT NULL, snapshot TEXT NOT NULL, proposed_by TEXT NOT NULL, note TEXT NOT NULL,
    at TEXT NOT NULL, PRIMARY KEY (workspace, use_case, number), UNIQUE (workspace, use_case, fingerprint));
CREATE TRIGGER IF NOT EXISTS releases_immutable_u BEFORE UPDATE ON releases
    BEGIN SELECT RAISE(ABORT, 'releases are immutable'); END;
CREATE TRIGGER IF NOT EXISTS releases_immutable_d BEFORE DELETE ON releases
    BEGIN SELECT RAISE(ABORT, 'releases are immutable'); END;
CREATE TABLE IF NOT EXISTS release_events (
    workspace TEXT NOT NULL, use_case TEXT NOT NULL, seq INTEGER NOT NULL, release INTEGER NOT NULL,
    event TEXT NOT NULL, by TEXT NOT NULL, by_kind TEXT NOT NULL, reason TEXT NOT NULL, fingerprint TEXT NOT NULL,
    at TEXT NOT NULL, prev TEXT NOT NULL, mac TEXT NOT NULL, PRIMARY KEY (workspace, use_case, seq));
CREATE TRIGGER IF NOT EXISTS release_events_append_only_u BEFORE UPDATE ON release_events
    BEGIN SELECT RAISE(ABORT, 'release history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS release_events_append_only_d BEFORE DELETE ON release_events
    BEGIN SELECT RAISE(ABORT, 'release history is append-only'); END;
"""


class ReleaseError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def fingerprint_of(snapshot: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical(snapshot).encode("utf-8")).hexdigest()


def configuration_snapshot(config: Dict[str, Any], base_dir: Path, ontology_document: Dict[str, Any],
                           ontology_fingerprint: str, ontology_ref: str) -> Dict[str, Any]:
    """The governing configuration of one engine, as a JSON-ready dictionary (the release snapshot)."""
    base = Path(base_dir)
    governing = {k: v for k, v in config.items() if k not in NON_GOVERNING}
    tools: Dict[str, Any] = {}
    for name, spec in sorted((config.get("agents") or {}).items()):
        for owner, s in [(name, spec)] + [(f"{name}/{d.get('name')}", d) for d in spec.get("delegates") or []]:
            path = s.get("tools")
            if isinstance(path, str):
                try:
                    tools[owner] = json.loads((base / path).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    tools[owner] = {"unreadable": path}
            elif path is not None:
                tools[owner] = path
    return {"format": FORMAT, "ontology_ref": ontology_ref, "ontology_fingerprint": ontology_fingerprint,
            "ontology": ontology_document, "settings": governing, "tools": tools}


class ReleaseRegistry:
    """Releases and their history, per workspace and use case, in one SQLite file of the platform."""

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

    # -- chain ------------------------------------------------------------------------------------------------
    def _mac(self, workspace: str, payload: Dict[str, Any]) -> str:
        data = canonical(["autology-release-event", payload]).encode()
        key = self._key_for(workspace)
        return hmac.new(key, data, hashlib.sha256).hexdigest() if key else hashlib.sha256(data).hexdigest()

    @staticmethod
    def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: row[k] for k in ("workspace", "use_case", "seq", "release", "event", "by", "by_kind", "reason",
                                    "fingerprint", "at", "prev")}

    def _rows(self, workspace: str, use_case: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        with self._lock:
            rels = [dict(r) for r in self._db.execute(
                "SELECT * FROM releases WHERE workspace=? AND use_case=? ORDER BY number", (workspace, use_case))]
            events = [dict(r) for r in self._db.execute(
                "SELECT * FROM release_events WHERE workspace=? AND use_case=? ORDER BY seq", (workspace, use_case))]
        return rels, events

    def state(self, workspace: str, use_case: str) -> Dict[str, Any]:
        """Every release with its status, the active one, and an integrity problem if anything does not verify."""
        rels, events = self._rows(workspace, use_case)
        problem, prev = None, GENESIS
        by_number = {r["number"]: r for r in rels}
        for i, e in enumerate(events):
            if e["seq"] != i + 1 or e["prev"] != prev or not hmac.compare_digest(
                    e["mac"], self._mac(workspace, self._payload(e))):
                problem = f"the release history was changed outside Autology (entry {i + 1} does not verify)"
                break
            rel = by_number.get(e["release"])
            if rel is None or rel["fingerprint"] != e["fingerprint"]:
                problem = f"release {e['release']} does not match its history"
                break
            prev = e["mac"]
        for r in rels:
            if fingerprint_of(json.loads(r["snapshot"])) != r["fingerprint"]:
                problem = problem or f"release {r['number']}'s snapshot was changed outside Autology"
        proposed = {e["release"] for e in events if e["event"] == "proposed"}
        if not problem and proposed != set(by_number):
            problem = "a release has no proposal in the history"
        status: Dict[int, Dict[str, Any]] = {n: {"approved_by": None, "approved_at": None, "activations": []}
                                             for n in by_number}
        active: Optional[int] = None
        for e in events if not problem else []:
            st = status[e["release"]]
            if e["event"] == "approved":
                st["approved_by"], st["approved_at"] = e["by"], e["at"]
            elif e["event"] == "approval_revoked":
                st["approved_by"], st["approved_at"] = None, None
            elif e["event"] in ("activated", "rolled_back"):
                st["activations"].append(e["at"])
                active = e["release"]
        items = []
        for r in rels:
            st = status.get(r["number"], {})
            lifecycle = ("active" if r["number"] == active else
                         "superseded" if st.get("activations") else
                         "approved" if st.get("approved_by") else "proposed")
            items.append({"number": r["number"], "id": f"{use_case}@r{r['number']}", "fingerprint": r["fingerprint"],
                          "ontology_ref": r["ontology_ref"], "proposed_by": r["proposed_by"], "note": r["note"],
                          "at": r["at"], "status": lifecycle, "approved_by": st.get("approved_by"),
                          "approved_at": st.get("approved_at"), "activated_at": (st.get("activations") or [None])[-1]})
        history = [{k: e[k] for k in ("seq", "release", "event", "by", "by_kind", "reason", "fingerprint", "at")}
                   for e in events]
        active_item = next((i for i in items if i["number"] == active), None)
        return {"items": items, "active": active_item, "history": history, "integrity_problem": problem}

    def snapshot(self, workspace: str, use_case: str, number: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._db.execute("SELECT snapshot FROM releases WHERE workspace=? AND use_case=? AND number=?",
                                   (workspace, use_case, number)).fetchone()
        return json.loads(row["snapshot"]) if row else None

    def _append(self, db, workspace: str, use_case: str, release: int, event: str, by: str, by_kind: str,
                reason: str, fingerprint: str) -> Dict[str, Any]:
        last = db.execute("SELECT seq, mac FROM release_events WHERE workspace=? AND use_case=? ORDER BY seq DESC "
                          "LIMIT 1", (workspace, use_case)).fetchone()
        row = {"workspace": workspace, "use_case": use_case, "seq": (last["seq"] + 1) if last else 1,
               "release": release, "event": event, "by": by, "by_kind": by_kind, "reason": reason,
               "fingerprint": fingerprint, "at": _now(), "prev": last["mac"] if last else GENESIS}
        row["mac"] = self._mac(workspace, self._payload(row))
        db.execute("INSERT INTO release_events VALUES (:workspace, :use_case, :seq, :release, :event, :by, :by_kind, "
                   ":reason, :fingerprint, :at, :prev, :mac)", row)
        return row

    # -- operations (the platform checks who may call them) ----------------------------------------------------
    def propose(self, workspace: str, use_case: str, snapshot: Dict[str, Any], by: str, note: str) -> Dict[str, Any]:
        fp = fingerprint_of(snapshot)
        with self._lock:
            current = self.state(workspace, use_case)
            if current["integrity_problem"]:
                raise ReleaseError(409, current["integrity_problem"])
            same = next((i for i in current["items"] if i["fingerprint"] == fp), None)
            if same:
                raise ReleaseError(409, f"this configuration is already release {same['number']} ({same['status']})")
            number = len(current["items"]) + 1
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute("INSERT INTO releases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (workspace, use_case, number, fp, snapshot.get("ontology_ref", ""), canonical(snapshot),
                                  by, note, _now()))
                self._append(self._db, workspace, use_case, number, "proposed", by, "person", note, fp)
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return self.release(workspace, use_case, number)

    def release(self, workspace: str, use_case: str, number: int) -> Dict[str, Any]:
        st = self.state(workspace, use_case)
        item = next((i for i in st["items"] if i["number"] == number), None)
        if item is None:
            raise ReleaseError(404, f"no release {number}")
        return item

    def record(self, workspace: str, use_case: str, number: int, event: str, by: str, reason: str,
               check: Callable[[Dict[str, Any], Dict[str, Any]], None]) -> Dict[str, Any]:
        """Append ``event`` for release ``number`` after ``check(release, state)`` accepts it (under one lock, so
        the state the check saw is the state the event is appended to)."""
        if event not in EVENTS or event == "proposed":
            raise ReleaseError(400, f"unknown release event {event!r}")
        reason = (reason or "").strip()
        if not (1 <= len(reason) <= 500):
            raise ReleaseError(400, "give a reason (1 to 500 characters)")
        with self._lock:
            st = self.state(workspace, use_case)
            if st["integrity_problem"]:
                raise ReleaseError(409, st["integrity_problem"])
            item = next((i for i in st["items"] if i["number"] == number), None)
            if item is None:
                raise ReleaseError(404, f"no release {number}")
            check(item, st)
            self._append(self._db, workspace, use_case, number, event, by, "person", reason, item["fingerprint"])
        return self.release(workspace, use_case, number)
