"""Server-side limits (GAP-030): request rates, concurrent connections, slow clients.

**Rate limits** are counted by the server, per fixed window (``window_seconds``, default 60), and enforced before
the work is done. A refused request gets ``429`` with a ``Retry-After`` header and nothing else happens:

==============  ==================================  =====================================================
class           counted per                         what it covers
==============  ==================================  =====================================================
auth_failures   client address                      requests refused for a missing, wrong, expired or
                                                    revoked credential; at the limit the address is
                                                    refused *before* its credential is looked at, so the
                                                    answer says nothing about a guessed token
anonymous       client address                      endpoints that need no credential (health, contracts,
                                                    sign-in configuration and code exchange)
api             identity (``name`` in a workspace)  every authenticated request
mcp             identity                            MCP messages, over HTTP and over stdio
admin           identity                            administrative changes (members, tokens, grants,
                                                    stages, releases, reloads, settings)
expensive       identity                            requests that start work: runs, resumes, chat,
                                                    comparisons, pipelines, automations, model proposals
tenant          tenant                              all authenticated requests of one tenant together
==============  ==================================  =====================================================

An identity's count is the same whichever use case, API version or entry point it uses, so no path gets around
it; one tenant reaching its limit takes nothing from another.

**Client address.** The address is the TCP peer's. ``X-Forwarded-For`` is believed only when that peer is listed
in ``security.trusted_proxies``; then the right-most address that is not itself a trusted proxy is used. A header
sent by anyone else is ignored, so a client cannot pick the address it is counted under.

**Single node.** Counters live in the memory of one server process: they restart with it and are not shared
between several processes. Behind several instances each counts on its own; put a shared limit at the load
balancer. This is stated in ``/api/health`` details and in the deployment guide.

**Connections.** :class:`BoundedHTTPServer` serves at most ``max_connections`` requests at once (others get an
immediate ``503`` with ``Retry-After``), and closes a connection that sends or reads nothing for
``request_timeout_seconds``. That timeout is about the socket only: work that has started (a run, a write to
another system) is never cancelled by it; it completes and is recorded, whether or not the client still listens.
"""

from __future__ import annotations

import ipaddress
import json
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any, Dict, Iterable, Optional, Tuple

DEFAULT_LIMITS: Dict[str, int] = {"auth_failures": 30, "anonymous": 600, "api": 1200, "mcp": 300, "admin": 120,
                                  "expensive": 120, "tenant": 12000}
DEFAULT_WINDOW = 60.0
DEFAULT_MAX_CONNECTIONS = 64
DEFAULT_REQUEST_TIMEOUT = 30.0
MAX_KEYS = 100_000  # counters kept at most; expired ones are dropped first, then the limiter refuses new keys

class LimitError(ValueError):
    pass


def monotonic() -> float:
    """The limiter's clock (one place, so tests can move time)."""
    return time.monotonic()


class RateLimiter:
    """Fixed-window counters in memory, safe across threads. ``limits`` maps a class to requests per window;
    a class set to 0 or ``null`` is not limited (an operator's explicit choice)."""

    def __init__(self, limits: Optional[Dict[str, Any]] = None, window: float = DEFAULT_WINDOW):
        self.limits: Dict[str, int] = dict(DEFAULT_LIMITS)
        for name, value in (limits or {}).items():
            if name not in DEFAULT_LIMITS:
                raise LimitError(f"security.rate_limits: unknown class {name!r} (known: {sorted(DEFAULT_LIMITS)})")
            if value is None:
                value = 0
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LimitError(f"security.rate_limits.{name}: a whole number of requests per window (0: no limit)")
            self.limits[name] = value
        if isinstance(window, bool) or not isinstance(window, (int, float)) or not (1 <= window <= 3600):
            raise LimitError("security.rate_limits.window_seconds: between 1 and 3600")
        self.window = float(window)
        self._counts: Dict[Tuple[str, str], Tuple[float, int]] = {}
        self._lock = threading.Lock()

    @classmethod
    def parse(cls, spec: Any) -> "RateLimiter":
        if spec is None:
            return cls()
        if not isinstance(spec, dict):
            raise LimitError("security.rate_limits: an object of class -> requests per window")
        spec = dict(spec)
        window = spec.pop("window_seconds", DEFAULT_WINDOW)
        return cls(spec, window)

    def _slot(self, name: str, key: str, at: float) -> Tuple[float, int]:
        start, count = self._counts.get((name, key), (at, 0))
        if at - start >= self.window:
            start, count = at, 0
        return start, count

    def _retry(self, start: float, at: float) -> int:
        return max(1, int(start + self.window - at + 0.999))

    def blocked(self, name: str, key: str) -> Optional[int]:
        """Seconds to wait if ``key`` is at the limit of ``name`` now; counts nothing."""
        limit = self.limits.get(name, 0)
        if not limit:
            return None
        at = monotonic()
        with self._lock:
            start, count = self._slot(name, key, at)
        return self._retry(start, at) if count >= limit else None

    def hit(self, name: str, key: str) -> Optional[int]:
        """Count one request. Returns None when it is within the limit, else the seconds to wait (the request is
        refused and not counted, so being refused does not extend the wait)."""
        limit = self.limits.get(name, 0)
        if not limit:
            return None
        at = monotonic()
        with self._lock:
            start, count = self._slot(name, key, at)
            if count >= limit:
                return self._retry(start, at)
            if (name, key) not in self._counts and len(self._counts) >= MAX_KEYS:
                self._counts = {k: v for k, v in self._counts.items() if at - v[0] < self.window}
                if len(self._counts) >= MAX_KEYS:  # under a flood of new keys, refuse rather than grow or forget
                    return int(self.window)
            self._counts[(name, key)] = (start, count + 1)
        return None

    def view(self) -> Dict[str, Any]:
        return {"window_seconds": self.window, "limits": dict(self.limits), "scope": "this server process only"}


def parse_proxies(spec: Any) -> Tuple[Any, ...]:
    """``security.trusted_proxies``: addresses or networks whose ``X-Forwarded-For`` is believed."""
    if spec is None:
        return ()
    if not isinstance(spec, list):
        raise LimitError("security.trusted_proxies: a list of addresses or networks (CIDR)")
    try:
        return tuple(ipaddress.ip_network(str(item), strict=False) for item in spec)
    except ValueError as exc:
        raise LimitError(f"security.trusted_proxies: {exc}") from None


def _trusted(address: str, proxies: Iterable[Any]) -> bool:
    try:
        ip = ipaddress.ip_address(address.strip())
    except ValueError:
        return False
    return any(ip in net for net in proxies)


def client_address(peer: Optional[str], forwarded: Optional[str], proxies: Iterable[Any] = ()) -> str:
    """The address a request is counted under: the TCP peer, unless that peer is a trusted proxy, in which case
    the right-most ``X-Forwarded-For`` entry that is not a trusted proxy. Anything unparsable falls back to the
    peer: a client never chooses its own address."""
    peer = (peer or "-").strip() or "-"
    proxies = tuple(proxies)
    if not proxies or not forwarded or not _trusted(peer, proxies):
        return peer
    for hop in reversed([h.strip() for h in str(forwarded).split(",")]):
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            return peer  # a malformed chain is not trusted at all
        if not _trusted(hop, proxies):
            return hop
    return peer


def engine_class(method: str, parts: list) -> Optional[str]:
    """The extra class an engine request is counted in, beyond ``api``: ``mcp``, ``expensive`` (it starts work:
    a run, a resume or a decision that continues one, chat, a comparison, a pipeline, an automation, a model
    proposal, a question) or ``admin`` (it changes how the engine behaves), or None. ``parts`` is the path after
    ``/api/``."""
    if not parts:
        return None
    if parts[0] == "mcp":
        return "mcp"
    if method != "POST":
        return None
    first, last, n = parts[0], parts[-1], len(parts)
    if (n == 1 and first in ("runs", "chat", "tick", "reporting")) or (n == 2 and first == "questions") \
            or parts in (["architect", "proposals"], ["settings", "assistant", "test"]) \
            or (n == 3 and (first, last) in {("runs", "resume"), ("runs", "write-back"), ("scenarios", "compare"),
                                             ("scenarios", "commit"), ("pipelines", "run"), ("automations", "run"),
                                             ("reviews", "decision")}):
        return "expensive"
    if parts == ["settings", "assistant"] or (n == 3 and (first, last) == ("agents", "reinstate")) \
            or (n == 2 and first == "reconciliation"):
        return "admin"
    return None


def too_many(wait: int, what: str) -> Dict[str, Any]:
    """The body of a 429 (the same shape everywhere)."""
    return {"error": f"too many requests ({what}): retry in {wait} s", "retry_after_seconds": wait}


class BoundedHTTPServer(ThreadingHTTPServer):
    """A threading HTTP server with a ceiling on concurrent requests and a socket timeout for slow clients."""

    daemon_threads = True

    def __init__(self, address, handler, max_connections: int = DEFAULT_MAX_CONNECTIONS,
                 request_timeout: float = DEFAULT_REQUEST_TIMEOUT):
        handler.timeout = request_timeout  # StreamRequestHandler applies it to the connection
        super().__init__(address, handler)
        self.max_connections = max_connections
        self._slots = threading.BoundedSemaphore(max_connections)
        self.refused = 0

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.refused += 1
            body = json.dumps({"error": "the server is at its limit of concurrent requests: retry shortly",
                               "retry_after_seconds": 1}).encode()
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
                                b"Retry-After: 1\r\nConnection: close\r\nContent-Length: "
                                + str(len(body)).encode() + b"\r\n\r\n" + body)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def parse_server(spec: Any) -> Dict[str, Any]:
    """``security.server``: ``max_connections`` and ``request_timeout_seconds`` of the HTTP server."""
    spec = spec or {}
    if not isinstance(spec, dict) or set(spec) - {"max_connections", "request_timeout_seconds"}:
        raise LimitError("security.server: max_connections and request_timeout_seconds only")
    connections = spec.get("max_connections", DEFAULT_MAX_CONNECTIONS)
    timeout = spec.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT)
    if isinstance(connections, bool) or not isinstance(connections, int) or not (1 <= connections <= 10000):
        raise LimitError("security.server.max_connections: between 1 and 10000")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not (0.1 <= timeout <= 3600):
        raise LimitError("security.server.request_timeout_seconds: between 0.1 and 3600")
    return {"max_connections": connections, "request_timeout": float(timeout)}
