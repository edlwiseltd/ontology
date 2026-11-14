"""External effects journal: every call to an outside system is recorded before it is made.

Audit gaps GAP-001 to GAP-007: a payment, an order or an email sent by a tool must happen at most once per
step, survive a crash at any point, and never be reported done without confirmation. The journal makes that
possible:

* Each step that calls a tool has an **idempotency key**, stable across retries, resumes and restarts
  (``run_key | action | occurrence``). Tools receive it (``call.idempotency_key``; HTTP tools send it as the
  ``Idempotency-Key`` header and in the payload).
* Before the call, an **intent** is committed (state ``in_flight``); after it, the **result** (``done`` with
  what the tool returned, or how it failed).
* Before calling, the agent looks the key up. ``done`` (or resolved as done by a person) is **replayed**
  without calling again. ``in_flight`` after a crash, ``unknown`` and ``pending_confirmation`` stop the run:
  a person reconciles them (``GET /api/reconciliation``). ``not_sent``, ``failed`` and ``rejected`` (nothing
  happened) may be called again, with the same key.

:class:`MemoryJournal` serves library use; :class:`StoreJournal` (in :mod:`autology.store`) persists it.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

IN_FLIGHT = "in_flight"
DONE = "done"
NOT_SENT = "not_sent"  # never reached the system (connection refused, DNS, send failure): safe to retry
FAILED = "failed"  # the tool reported a definite failure: nothing was done
REJECTED = "rejected"  # the system refused the request (e.g. HTTP 4xx, a FAILED status): nothing was done
UNKNOWN = "unknown"  # sent, outcome unknown (read timeout, reset, 5xx, invalid reply, crash)
PENDING = "pending_confirmation"  # accepted but not confirmed (HTTP 202, missing confirmation fields)
RESOLVED_DONE = "resolved_done"  # a person confirmed it happened
RESOLVED_NOT_DONE = "resolved_not_done"  # a person confirmed it did not happen

REPLAY = frozenset({DONE, RESOLVED_DONE})
RETRYABLE = frozenset({NOT_SENT, FAILED, REJECTED, RESOLVED_NOT_DONE})
NEEDS_PERSON = frozenset({IN_FLIGHT, UNKNOWN, PENDING})
SIDE_EFFECTS = ("none", "idempotent", "non_idempotent")


def idempotency_key(run_key: str, action: str, occurrence: int) -> str:
    """The key of one step: the same for every retry, resume and restart of that step, different for others."""
    return hashlib.sha256(f"autology-step:{run_key}|{action}|{occurrence}".encode()).hexdigest()[:32]


def inputs_digest(inputs: Any) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryJournal:
    """The journal for a process without a store. It still replays completed calls within the process."""

    def __init__(self) -> None:
        self._rows: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._rows.get(key)
            return dict(row) if row else None

    def intent(self, key: str, **fields: Any) -> None:
        with self._lock:
            row = self._rows.setdefault(key, {"key": key, "created_at": _now(), "attempt": 0})
            row.update(fields, state=IN_FLIGHT, updated_at=_now(), attempt=int(row.get("attempt", 0)) + 1)

    def result(self, key: str, state: str, **fields: Any) -> None:
        with self._lock:
            self._rows[key].update(fields, state=state, updated_at=_now())

    def resolve(self, key: str, done: bool, by: str, comment: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            row = self._rows[key]
            row.update(fields, state=RESOLVED_DONE if done else RESOLVED_NOT_DONE, resolved_by=by,
                       resolved_comment=comment, updated_at=_now())
            return dict(row)

    def rows(self, run_key: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._rows.values() if run_key is None or r.get("run_key") == run_key]
