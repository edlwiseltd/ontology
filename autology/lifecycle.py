"""Use-case lifecycle: Draft -> Simulation -> Pilot, with server-side gates (R2 slice of REL-1/REL-2).

Every use case of a workspace has a **stage**. It is a governance record, kept by the platform (not by the use
case, whose configuration cannot set it), in ``<data_dir>/lifecycle.db``:

* ``draft``: being configured; nothing is claimed about it.
* ``simulation``: its configuration loads under the strict schema, its audit chains are signed with the workspace's
  key and no stored record is quarantined. It may be exercised with test data.
* ``pilot``: the simulation checks still hold, the engine's own ``simulation`` mode (automatic approvals,
  free-form cases) is off, every reviewer role its rules require is held by a named member,
  every audit chain verifies, no external call is waiting to be reconciled, at least one run completed since the
  use case entered simulation, and the configuration is the one that was simulated (same ontology fingerprint).
* ``production``: **always refused** in this release (owner decision PROD: no production deployment is
  authorised). Nothing in this module can grant it.

Rules:

* forward moves go one step at a time and only when every check of the target stage passes, evaluated on the
  server at the moment of the move; a high score or a client's say-so cannot replace a check;
* moving back to a safer stage is always allowed (it never needs checks), with a reason;
* every move names the person and a reason, records the checks and the ontology fingerprint, and is appended to a
  chain keyed with the workspace's audit key: an edited or deleted history entry is detected, and the use case is
  then reported in ``draft`` with an integrity problem and cannot move forward until an operator repairs it;
* if the configuration changes after a stage was granted (another ontology fingerprint), the stage is reported
  ``stale``: the checks that granted it no longer describe what runs.

**Execution gates.** The stage governs what the use case's engine does, at every entry point (REST, the
assistant and MCP through the same service, manual and automatic automation firings, deferred retries, review
decisions, recovery), read afresh at every check:

========== ======================== ===========================================================
stage      runs start or continue   tools the runs may call (by declared environment)
========== ======================== ===========================================================
draft      no                       none
simulation yes                      ``simulated`` only (decision tables, declared stubs)
pilot      yes                      ``simulated`` and ``sandbox``
========== ======================== ===========================================================

``production`` tools are called by no stage in this release (owner decision D15 is pending). A stage whose
history does not verify, or that is stale (the configuration changed since it was granted), counts as
``draft``. A step whose every tool is refused is not called at all: nothing is sent, the run escalates and the
audit chain records ``step.blocked``. A standalone engine (no platform) is not governed by stages.
A ``pilot`` stage authorises no real customer or data (D16 is pending).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STAGES = ("draft", "simulation", "pilot", "production")
REFUSED_STAGES = {"production": "production is not authorised in this release (owner decision PROD)"}
GENESIS = "0" * 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS created_use_cases (
    workspace TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, template TEXT NOT NULL,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (workspace, id));
CREATE TABLE IF NOT EXISTS stage_events (
    workspace TEXT NOT NULL, use_case TEXT NOT NULL, seq INTEGER NOT NULL, from_stage TEXT NOT NULL,
    to_stage TEXT NOT NULL, by TEXT NOT NULL, reason TEXT NOT NULL, fingerprint TEXT NOT NULL,
    checks TEXT NOT NULL, at TEXT NOT NULL, prev TEXT NOT NULL, mac TEXT NOT NULL,
    PRIMARY KEY (workspace, use_case, seq));
"""


POLICIES = {
    "draft": {"runs": False, "environments": frozenset()},
    "simulation": {"runs": True, "environments": frozenset({"simulated"})},
    "pilot": {"runs": True, "environments": frozenset({"simulated", "sandbox"})},
}


def policy_for(stage: Optional[str]) -> Dict[str, Any]:
    """What a stage allows at run time. Anything unknown (or unreadable) is treated as draft: fail closed."""
    stage = stage if stage in POLICIES else "draft"
    refusal = (f"this use case is in {stage}: no run may start or continue; a workspace administrator moves it to "
               "simulation first") if not POLICIES[stage]["runs"] else None
    return {"stage": stage, **POLICIES[stage], "refusal": refusal}


class LifecycleError(ValueError):
    def __init__(self, status: int, message: str, checks: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.status = status
        self.checks = checks or []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Check:
    id: str
    passed: bool
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "passed": self.passed, "detail": self.detail}


# -- the checks of each stage, evaluated against a running use case's engine ----------------------------------
def _simulation_checks(service: Any) -> List[Check]:
    o = service.ontology
    checks = [Check("configuration_valid", True,
                    f"{o.ref} loaded under the strict schema (fingerprint {o.fingerprint[:12]})"),
              Check("audit_key", bool(service.audit_key),
                    "audit chains are signed with the workspace's key" if service.audit_key else
                    "no audit key: the platform runs without AUTOLOGY_AUDIT_KEY, so chains are not signed"),
              Check("no_quarantined_records", not service.quarantined,
                    f"{len(service.quarantined)} stored records no longer validate" if service.quarantined else
                    "every stored record validates")]
    return checks


def _pilot_checks(service: Any, entered_simulation: Optional[Dict[str, Any]]) -> List[Check]:
    checks = _simulation_checks(service)
    o = service.ontology
    checks.append(Check("engine_simulation_mode_off", not service.simulation,
                        "the engine's simulation mode (automatic approvals, free-form cases) is on" if service.simulation
                        else "the engine's simulation mode (automatic approvals, free-form cases) is off"))
    needed = sorted({str(r.params.get("reviewer")) for r in o.rules if r.kind == "human_review"})
    held = set().union(*[u.reviewer_roles for u in service.users]) if service.users else set()
    missing = [r for r in needed if r not in held]
    checks.append(Check("reviewers_assigned", not missing,
                        f"no member holds the reviewer roles {', '.join(missing)}" if missing else
                        f"every reviewer role is held by a named member ({', '.join(needed) or 'none required'})"))
    runs = service.store.list_runs(limit=10 ** 9)
    broken = [r["run_id"] for r in runs if not service.store.verify_audit(r["run_id"])]
    checks.append(Check("audit_chains_verify", not broken,
                        f"{len(broken)} run audit chains do not verify" if broken else
                        f"all {len(runs)} run audit chains verify"))
    open_calls = service.store.list_calls(["in_flight", "unknown", "pending_confirmation"])
    checks.append(Check("external_calls_reconciled", not open_calls,
                        f"{len(open_calls)} external calls wait for reconciliation" if open_calls else
                        "no external call is waiting for reconciliation"))
    since = entered_simulation["at"] if entered_simulation else None
    done = [r for r in runs if r["status"] == "completed" and since and r["created_at"] >= since]
    checks.append(Check("simulated_run_completed", bool(done),
                        f"{len(done)} runs completed since the use case entered simulation" if done else
                        "no run has completed since the use case entered simulation"))
    same = bool(entered_simulation) and entered_simulation["fingerprint"] == o.fingerprint
    checks.append(Check("configuration_unchanged_since_simulation", same,
                        "the configuration is the one that was simulated" if same else
                        "the configuration changed since the use case entered simulation"))
    return checks


def evaluate(stage: str, service: Any, entered_simulation: Optional[Dict[str, Any]] = None) -> List[Check]:
    if stage == "simulation":
        return _simulation_checks(service)
    if stage == "pilot":
        return _pilot_checks(service, entered_simulation)
    return []


# -- the registry -----------------------------------------------------------------------------------------------
class Lifecycle:
    """The platform's record of created use cases and of every stage move, in one SQLite file."""

    def __init__(self, path: Path, key_for):
        self.path = Path(path)
        self._key_for = key_for  # workspace id -> bytes or None (the workspace's derived audit key)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # created use cases
    def created(self, workspace: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM created_use_cases WHERE workspace=? ORDER BY created_at, id",
                                    (workspace,)).fetchall()
        return [dict(r) for r in rows]

    def record_created(self, workspace: str, uc_id: str, name: str, template: str, by: str) -> Dict[str, Any]:
        row = {"workspace": workspace, "id": uc_id, "name": name, "template": template, "created_by": by,
               "created_at": _now()}
        with self._lock:
            self._db.execute("INSERT INTO created_use_cases VALUES (:workspace, :id, :name, :template, "
                             ":created_by, :created_at)", row)
        return row

    # stage history
    def _mac(self, workspace: str, payload: Dict[str, Any]) -> str:
        data = json.dumps(["autology-stage", payload], sort_keys=True, default=str).encode()
        key = self._key_for(workspace)
        return hmac.new(key, data, hashlib.sha256).hexdigest() if key else hashlib.sha256(data).hexdigest()

    @staticmethod
    def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
        return {k: row[k] for k in ("workspace", "use_case", "seq", "from_stage", "to_stage", "by", "reason",
                                    "fingerprint", "checks", "at", "prev")}

    def history(self, workspace: str, use_case: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """The stage moves, oldest first, and an integrity problem if the chain does not verify."""
        with self._lock:
            rows = [dict(r) for r in self._db.execute(
                "SELECT * FROM stage_events WHERE workspace=? AND use_case=? ORDER BY seq",
                (workspace, use_case)).fetchall()]
        prev, problem = GENESIS, None
        for i, row in enumerate(rows):
            if row["seq"] != i + 1 or row["prev"] != prev or not hmac.compare_digest(
                    row["mac"], self._mac(workspace, self._payload(row))):
                problem = f"the stage history was changed outside Autology (entry {i + 1} does not verify)"
                break
            if i and row["from_stage"] != rows[i - 1]["to_stage"]:
                problem = f"the stage history is inconsistent at entry {i + 1}"
                break
            prev = row["mac"]
        return [{**{k: r[k] for k in ("seq", "from_stage", "to_stage", "by", "reason", "fingerprint", "at")},
                 "checks": json.loads(r["checks"])} for r in rows], problem

    def status(self, workspace: str, use_case: str, fingerprint: str) -> Dict[str, Any]:
        events, problem = self.history(workspace, use_case)
        stage = "draft" if problem or not events else events[-1]["to_stage"]
        granted = next((e for e in reversed(events) if e["to_stage"] == stage), None) if not problem else None
        return {"stage": stage, "stale": bool(granted) and stage != "draft" and granted["fingerprint"] != fingerprint,
                "integrity_problem": problem, "history": events,
                "entered_simulation": self._entered(events, "simulation") if not problem else None}

    @staticmethod
    def _entered(events: List[Dict[str, Any]], stage: str) -> Optional[Dict[str, Any]]:
        """The move that started the current, uninterrupted stretch at or beyond ``stage`` (None if not there)."""
        order = {s: i for i, s in enumerate(STAGES)}
        found = None
        for e in events:
            if order[e["to_stage"]] < order[stage]:
                found = None
            elif e["to_stage"] == stage and order[e["from_stage"]] < order[stage]:
                found = e
        return found

    def append(self, workspace: str, use_case: str, from_stage: str, to_stage: str, by: str, reason: str,
               fingerprint: str, checks: List[Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            last = self._db.execute("SELECT seq, mac FROM stage_events WHERE workspace=? AND use_case=? "
                                    "ORDER BY seq DESC LIMIT 1", (workspace, use_case)).fetchone()
            row = {"workspace": workspace, "use_case": use_case, "seq": (last["seq"] + 1) if last else 1,
                   "from_stage": from_stage, "to_stage": to_stage, "by": by, "reason": reason,
                   "fingerprint": fingerprint, "checks": json.dumps(checks, sort_keys=True), "at": _now(),
                   "prev": last["mac"] if last else GENESIS}
            row["mac"] = self._mac(workspace, self._payload(row))
            self._db.execute("INSERT INTO stage_events VALUES (:workspace, :use_case, :seq, :from_stage, :to_stage, "
                             ":by, :reason, :fingerprint, :checks, :at, :prev, :mac)", row)
        return row

    # the move itself
    def move(self, workspace: str, use_case: str, service: Any, to_stage: str, by: str, reason: str,
             dry_run: bool = False) -> Dict[str, Any]:
        """Check and (unless ``dry_run``) record one stage move. Raises :class:`LifecycleError` when refused."""
        if to_stage not in STAGES:
            raise LifecycleError(400, f"unknown stage {to_stage!r}: one of {', '.join(STAGES)}")
        if to_stage in REFUSED_STAGES:
            raise LifecycleError(403, REFUSED_STAGES[to_stage])
        reason = (reason or "").strip()
        if not dry_run and not (1 <= len(reason) <= 500):
            raise LifecycleError(400, "give a reason (1 to 500 characters)")
        with self._lock:
            current = self.status(workspace, use_case, service.ontology.fingerprint)
            if current["integrity_problem"]:
                raise LifecycleError(409, current["integrity_problem"])
            here = current["stage"]
            order = {s: i for i, s in enumerate(STAGES)}
            if to_stage == here:
                raise LifecycleError(409, f"the use case is already in {here}")
            if order[to_stage] > order[here] + 1:
                raise LifecycleError(409, f"stages advance one at a time: from {here} the next is "
                                          f"{STAGES[order[here] + 1]}")
            forward = order[to_stage] > order[here]
            checks = [c.to_dict() for c in evaluate(to_stage, service, current["entered_simulation"])] if forward \
                else []
            passed = all(c["passed"] for c in checks)
            result = {"from": here, "to": to_stage, "forward": forward, "checks": checks, "allowed": passed}
            if dry_run:
                return result
            if not passed:
                raise LifecycleError(409, f"{to_stage} refused: "
                                          + "; ".join(c["detail"] for c in checks if not c["passed"]), checks)
            self.append(workspace, use_case, here, to_stage, by, reason, service.ontology.fingerprint, checks)
            return result
