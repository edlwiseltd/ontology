"""Tamper-evident audit trail.

Every plan, decision, approval, tool call and state change is appended as an
entry whose hash covers the previous entry's hash, so any later edit breaks
the chain and is detected by :meth:`AuditLog.verify`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    timestamp: str
    event: str
    data: Dict[str, Any]
    prev_hash: str
    hash: str


def _digest(seq: int, timestamp: str, event: str, data: Dict[str, Any], prev_hash: str) -> str:
    payload = json.dumps([seq, timestamp, event, data, prev_hash], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditLog:
    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def record(self, event: str, **data: Any) -> AuditEntry:
        seq = len(self._entries)
        prev = self._entries[-1].hash if self._entries else GENESIS
        ts = datetime.now(timezone.utc).isoformat()
        data = json.loads(json.dumps(data, default=str))  # detach & normalise
        entry = AuditEntry(seq, ts, event, data, prev, _digest(seq, ts, event, data, prev))
        self._entries.append(entry)
        return entry

    def verify(self) -> bool:
        prev = GENESIS
        for i, e in enumerate(self._entries):
            if e.seq != i or e.prev_hash != prev or e.hash != _digest(e.seq, e.timestamp, e.event, e.data, e.prev_hash):
                return False
            prev = e.hash
        return True

    def events(self, event: str | None = None) -> List[AuditEntry]:
        return [e for e in self._entries if event is None or e.event == event]

    def __iter__(self) -> Iterator[AuditEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.__dict__, default=str) for e in self._entries)
