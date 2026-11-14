"""Tamper-evident audit trail.

Every plan, decision, approval, tool call and state change is appended as an entry whose hash covers
the previous entry's hash, so a later edit breaks the chain and :meth:`AuditLog.verify` detects it.

What this does and does not guarantee:

* **Keyed.** With ``AUTOLOGY_AUDIT_KEY`` set in the environment, entries are chained with HMAC-SHA256
  under that secret, so someone who can edit the stored log but does not hold the key cannot rewrite an
  entry and recompute the chain. Without a key the chain is plain SHA-256 and only detects accidental or
  naive edits. A deployment that has a key rejects unkeyed entries.
* **Head.** :meth:`AuditLog.head` gives the chain's length and last hash, with a keyed MAC. Stores and run
  files record it, so cutting entries off the end is detected too.
* **Not an external anchor.** Anyone holding the key can rewrite everything consistently. Publish the heads
  (``GET /api/audit-heads``) to a system the operators cannot edit if that matters.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

GENESIS = "0" * 64
KEY_ENV = "AUTOLOGY_AUDIT_KEY"
PLAIN = "sha256"


def audit_key() -> Optional[bytes]:
    value = os.environ.get(KEY_ENV)
    return value.encode() if value else None


def key_id(key: bytes) -> str:
    """Identifies which key signed an entry, without revealing it."""
    return "hmac-sha256:" + hashlib.sha256(b"autology-key-id:" + key).hexdigest()[:12]


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    timestamp: str
    event: str
    data: Dict[str, Any]
    prev_hash: str
    hash: str
    alg: str = PLAIN


def _digest(seq: int, timestamp: str, event: str, data: Dict[str, Any], prev_hash: str,
            key: Optional[bytes] = None) -> str:
    payload = json.dumps([seq, timestamp, event, data, prev_hash], sort_keys=True, default=str).encode()
    if key:
        return hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def record_seal(run_id: str, fields: List[Any], key: Optional[bytes] = None) -> str:
    """MAC over a stored run record and the columns that steer it (status, starter, chain head...), bound to its
    run id: the resumable state lives outside the chain, so it is sealed as a whole each time Autology writes it."""
    payload = json.dumps(["autology-run", run_id, *fields], default=str).encode()
    if key:
        return hmac.new(key, payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def _head_mac(length: int, last: str, key: bytes) -> str:
    return hmac.new(key, f"autology-head:{length}:{last}".encode(), hashlib.sha256).hexdigest()


class AuditLog:
    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []
        self.recorded_head: Optional[Dict[str, Any]] = None  # set when loaded from a store or run file
        self.loaded = False  # rebuilt from storage: then only a recorded head rules out truncation
        self.broken = False  # appended to after failing verification: stays failed

    def record(self, event: str, **data: Any) -> AuditEntry:
        if self.loaded:  # continuing a stored log: it must match its recorded head before anything is added
            self.broken = self.broken or not self.verify()
            self.loaded, self.recorded_head = False, None
        key = audit_key()
        seq = len(self._entries)
        prev = self._entries[-1].hash if self._entries else GENESIS
        ts = datetime.now(timezone.utc).isoformat()
        data = json.loads(json.dumps(data, default=str))  # detach & normalise
        entry = AuditEntry(seq, ts, event, data, prev, _digest(seq, ts, event, data, prev, key),
                           key_id(key) if key else PLAIN)
        self._entries.append(entry)
        return entry

    def head(self) -> Dict[str, Any]:
        """Length and last hash of the chain, with a MAC under the audit key (``None`` without one)."""
        key = audit_key()
        last = self._entries[-1].hash if self._entries else GENESIS
        return {"length": len(self._entries), "hash": last,
                "mac": _head_mac(len(self._entries), last, key) if key else None}

    def verify(self, head: Optional[Dict[str, Any]] = None) -> bool:
        """Check every entry's hash and link; with a ``head`` (or a recorded one) also check nothing was cut off.

        With an audit key configured, every entry must be keyed with it and the head must carry a valid MAC.
        """
        if self.broken:
            return False
        key = audit_key()
        expected_alg = key_id(key) if key else PLAIN
        prev = GENESIS
        for i, e in enumerate(self._entries):
            if e.alg != expected_alg:
                return False  # unkeyed entries in a keyed deployment, or a different key
            if e.seq != i or e.prev_hash != prev or \
                    not hmac.compare_digest(e.hash, _digest(e.seq, e.timestamp, e.event, e.data, e.prev_hash, key)):
                return False
            prev = e.hash
        head = head if head is not None else self.recorded_head
        if head is None:  # a keyed log read back from storage needs its recorded head to rule out truncation
            return key is None or not self.loaded or not self._entries
        if head.get("length") != len(self._entries) or head.get("hash") != prev:
            return False
        if key is not None:
            return bool(head.get("mac")) and hmac.compare_digest(head["mac"], _head_mac(len(self._entries), prev, key))
        return True

    def entry(self, seq: int) -> Optional[AuditEntry]:
        return self._entries[seq] if 0 <= seq < len(self._entries) else None

    def events(self, event: str | None = None) -> List[AuditEntry]:
        return [e for e in self._entries if event is None or e.event == event]

    def __iter__(self) -> Iterator[AuditEntry]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e.__dict__, default=str) for e in self._entries)

    def to_list(self) -> List[Dict[str, Any]]:
        return [dict(e.__dict__) for e in self._entries]

    @classmethod
    def from_list(cls, entries: List[Dict[str, Any]], head: Optional[Dict[str, Any]] = None) -> "AuditLog":
        """Rebuild a log from stored entries; :meth:`verify` still detects any tampering in storage."""
        log = cls()
        log._entries = [AuditEntry(int(e["seq"]), e["timestamp"], e["event"], dict(e["data"]), e["prev_hash"],
                                   e["hash"], e.get("alg") or PLAIN) for e in entries]
        log.recorded_head = head
        log.loaded = True
        return log
