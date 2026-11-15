"""API-token lifetimes and revocation (GAP-030).

An API token is a bearer secret; only its SHA-256 is ever stored. Until this module, a token worked for as long
as it stayed in the configuration. Now every token has a **lifetime**, enforced by the server on every request:

* the **policy** (``security.tokens`` in the platform or engine configuration) gives the lifetime per kind of
  identity: people (``person_days``, default 90) and service identities (``service_days``, default 365) are
  treated separately. A lifetime is always finite (at most ``MAX_DAYS``): no token is valid for ever;
* the **registry** records, once, when Autology first saw each token (its digest). A token expires at
  ``first seen + lifetime``, or earlier if the configuration gives it an explicit ``token_expires``. The registry
  is append-only and chained with the audit key, like the other governance records: changing a date in the file
  is detected, and the server then refuses to start rather than trust it;
* a token can be **revoked**: it is refused from then on, even if a configuration file still names it.

**Migration of existing credentials.** A token that existed before this version is neither invalidated at the
upgrade nor trusted indefinitely: it is registered the first time the new version starts, so it gets one full
lifetime from the upgrade, visible to its owner (``/platform/me``, ``/api/me``) and to administrators (the members
view). Replacing a token (rotation) registers the new one and gives no more than one lifetime again; it never
changes what the identity may do.

Company sign-in (OIDC) is unaffected: an ID token carries its own expiry, verified on every request.

Limits to know: the registry lives beside the data; whoever can delete files there can reset lifetimes, which is
an infrastructure control, not an application one. Clocks are the server's.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

DAY = 86400.0
MAX_DAYS = 3650.0  # a lifetime is always finite
GENESIS = "0" * 64
KINDS = ("person", "service")

SCHEMA = """
CREATE TABLE IF NOT EXISTS credential_events (
    seq INTEGER PRIMARY KEY, event TEXT NOT NULL, digest TEXT NOT NULL, identity TEXT NOT NULL, kind TEXT NOT NULL,
    at REAL NOT NULL, by TEXT NOT NULL, reason TEXT NOT NULL, prev TEXT NOT NULL, mac TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS credential_events_append_only_u BEFORE UPDATE ON credential_events
    BEGIN SELECT RAISE(ABORT, 'the credential registry is append-only'); END;
CREATE TRIGGER IF NOT EXISTS credential_events_append_only_d BEFORE DELETE ON credential_events
    BEGIN SELECT RAISE(ABORT, 'the credential registry is append-only'); END;
"""


class CredentialError(ValueError):
    pass


def now() -> float:
    """The server's clock, in seconds since the epoch (one place, so tests can move time)."""
    return time.time()


def iso(at: Optional[float]) -> Optional[str]:
    return None if at is None else datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds")


def parse_time(value: Any, where: str) -> float:
    """An explicit expiry from configuration: an ISO 8601 date or date-time (UTC when no offset is given)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise CredentialError(f"{where}: token_expires must be an ISO 8601 date or date-time") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass(frozen=True)
class TokenPolicy:
    """How long an API token lives, per kind of identity. People and machines are separate on purpose: a
    person's token is the weaker credential (copied, pasted, shared) and people can sign in again."""

    person_days: float = 90.0
    service_days: float = 365.0

    @classmethod
    def parse(cls, spec: Any) -> "TokenPolicy":
        if spec is None:
            return cls()
        if not isinstance(spec, dict) or set(spec) - {"person_days", "service_days"}:
            raise CredentialError("security.tokens: person_days and service_days only")
        values = {}
        for key, default in (("person_days", cls.person_days), ("service_days", cls.service_days)):
            days = spec.get(key, default)
            if isinstance(days, bool) or not isinstance(days, (int, float)) or not (0 < days <= MAX_DAYS):
                raise CredentialError(f"security.tokens.{key}: a number of days above 0 and at most {int(MAX_DAYS)} "
                                      "(a token never lives for ever)")
            values[key] = float(days)
        return cls(**values)

    def lifetime(self, kind: str) -> float:
        return (self.service_days if kind == "service" else self.person_days) * DAY

    def view(self) -> Dict[str, float]:
        return {"person_days": self.person_days, "service_days": self.service_days}


class CredentialRegistry:
    """When each token digest was first seen, and which were revoked. Append-only and chained."""

    def __init__(self, path: Union[str, Path], key: Optional[bytes]):
        self.path = str(path)
        self._key = key
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()
        self._seen: Dict[str, Dict[str, Any]] = {}
        self._last = GENESIS
        for i, row in enumerate(self._db.execute("SELECT * FROM credential_events ORDER BY seq")):
            r = dict(row)
            if r["seq"] != i + 1 or r["prev"] != self._last or r["event"] not in ("registered", "revoked") \
                    or not hmac.compare_digest(r["mac"], self._mac(r)):
                self._db.close()
                raise CredentialError(
                    f"the credential registry {self.path} was changed outside Autology (entry {i + 1} does not "
                    "verify): token lifetimes cannot be trusted. Restore it from a backup; if it is removed, every "
                    "token is registered again with a new lifetime, which is a decision for the operator")
            self._apply(r)
            self._last = r["mac"]

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _mac(self, row: Dict[str, Any]) -> str:
        payload = {k: row[k] for k in ("seq", "event", "digest", "identity", "kind", "at", "by", "reason", "prev")}
        data = json.dumps(["autology-credential-event", payload], sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self._key, data, hashlib.sha256).hexdigest() if self._key else hashlib.sha256(data).hexdigest()

    def _apply(self, row: Dict[str, Any]) -> None:
        entry = self._seen.setdefault(row["digest"], {"registered_at": row["at"], "identity": row["identity"],
                                                      "kind": row["kind"], "revoked_at": None})
        if row["event"] == "revoked" and entry["revoked_at"] is None:
            entry["revoked_at"] = row["at"]

    def _append(self, event: str, digest: str, identity: str, kind: str, by: str, reason: str) -> Dict[str, Any]:
        seq = self._db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM credential_events").fetchone()[0]
        row = {"seq": seq, "event": event, "digest": digest, "identity": identity, "kind": kind, "at": now(),
               "by": by, "reason": reason, "prev": self._last}
        row["mac"] = self._mac(row)
        self._db.execute("INSERT INTO credential_events VALUES (:seq, :event, :digest, :identity, :kind, :at, :by, "
                         ":reason, :prev, :mac)", row)
        self._last = row["mac"]
        self._apply(row)
        return row

    def register(self, digest: str, identity: str, kind: str, by: str = "autology",
                 reason: str = "first seen") -> float:
        """When this token was first seen; recorded now if it never was. Seeing it again changes nothing, so a
        restart, a reload or naming it in another file never extends a lifetime."""
        with self._lock:
            entry = self._seen.get(digest)
            if entry is None:
                self._append("registered", digest, identity, kind if kind in KINDS else "person", by, reason[:500])
                entry = self._seen[digest]
            return float(entry["registered_at"])

    def revoke(self, digest: str, by: str, reason: str) -> None:
        """Refuse this token from now on, for good."""
        with self._lock:
            entry = self._seen.get(digest)
            if entry is None:
                self._append("registered", digest, "unknown", "person", by, "registered to be revoked")
                entry = self._seen[digest]
            if entry["revoked_at"] is None:
                self._append("revoked", digest, entry["identity"], entry["kind"], by, reason[:500])

    def revoked(self, digest: str) -> bool:
        entry = self._seen.get(digest)
        return bool(entry and entry["revoked_at"] is not None)

    def registered_at(self, digest: str) -> Optional[float]:
        entry = self._seen.get(digest)
        return None if entry is None else float(entry["registered_at"])

    def events(self) -> list:
        """The registry's history without any digest: who, what kind, when (for administrators and audits)."""
        with self._lock:
            return [{"seq": r["seq"], "event": r["event"], "identity": r["identity"], "kind": r["kind"],
                     "at": iso(r["at"]), "by": r["by"], "reason": r["reason"]}
                    for r in self._db.execute("SELECT * FROM credential_events ORDER BY seq")]


def expires_at(registered: float, kind: str, policy: TokenPolicy, explicit: Optional[float] = None) -> float:
    """The moment a token stops working: its lifetime from first sight, or an earlier explicit date."""
    limit = registered + policy.lifetime(kind)
    return limit if explicit is None else min(limit, explicit)
