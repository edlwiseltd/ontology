"""Outbound HTTP for configured integrations (audit findings F-01 and F-08, 15 Nov 2026).

The operator configures where Autology may send requests (tool URLs, approvers, webhooks, pipelines, identity
providers, trace collectors); those destinations are trusted configuration. What is **not** trusted is a destination
chosen by the other side: a redirect, or a "next page" link in a reply. Such a destination is followed only when it
has the same origin (scheme, host and port) as the configured URL, or an origin the operator listed explicitly, so a
compromised or malicious service cannot make Autology forward credentials to another host or probe the internal
network on its behalf (SSRF).

Replies are read up to a size limit, and error texts never contain secret values: they are built from the
configured URL template, and :func:`redact` removes any known secret that still appears.

**Deadlines (GAP-021, GAP-030).** ``timeout`` is the longest silence accepted on the connection; it does not bound
a reply that keeps trickling. Every call therefore also has a **deadline**: the total time from connecting to the
last byte of the reply (``deadline``, by default ``DEADLINE_FACTOR`` times the timeout). At the deadline the
connection is shut and the call fails with :class:`DeadlineExceeded`. Whether the other side acted is then not
known: callers that write to other systems record that as an unknown outcome, to be confirmed or reconciled,
never as a failure that is safe to repeat blindly.
"""

from __future__ import annotations

import http.client
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, List, Optional, Sequence, Tuple

MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # a reply larger than this is refused, not read into memory
_DEFAULT_PORTS = {"http": 80, "https": 443}


DEADLINE_FACTOR = 3.0  # default deadline of a call = this many times its timeout


class OutboundError(Exception):
    """A reply that Autology refuses to use: too large, or redirected to an origin that was not allowed."""


class DeadlineExceeded(OutboundError):
    """The call did not finish within its deadline; the connection was shut. The other side may have acted."""


class _Watch:
    """Shuts a call's connections at its deadline, whatever the other side is doing (a reply that trickles one
    byte at a time never reaches the per-read timeout)."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.expired = False
        self._socks: List[Any] = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(seconds, self._fire)
        self._timer.daemon = True
        self._timer.start()

    @staticmethod
    def _shut(sock: Any) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)  # wakes a read that is waiting; the owner still closes the socket
        except OSError:
            pass

    def add(self, sock: Any) -> None:
        with self._lock:
            self._socks.append(sock)
            expired = self.expired
        if expired:
            self._shut(sock)

    def _fire(self) -> None:
        with self._lock:
            self.expired = True
            socks = list(self._socks)
        for sock in socks:
            self._shut(sock)

    def cancel(self) -> None:
        self._timer.cancel()

    def error(self) -> DeadlineExceeded:
        return DeadlineExceeded(f"no complete reply within the deadline of {self.seconds:g} s")


def _watched(base: Any, watch: _Watch) -> Any:
    class Watched(base):  # type: ignore[misc, valid-type]
        def connect(self) -> None:
            super().connect()
            watch.add(self.sock)

    return Watched


class _WatchedHTTP(urllib.request.HTTPHandler):
    def __init__(self, watch: _Watch):
        super().__init__()
        self._watch = watch

    def http_open(self, req):  # noqa: D102
        return self.do_open(_watched(http.client.HTTPConnection, self._watch), req)


class _WatchedHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, watch: _Watch):
        super().__init__()
        self._watch = watch

    def https_open(self, req):  # noqa: D102
        return self.do_open(_watched(http.client.HTTPSConnection, self._watch), req,
                            context=getattr(self, "_context", None))


def origin(url: str) -> Tuple[str, str, int]:
    """``(scheme, host, port)`` of an http(s) URL, lower-cased, with the default port filled in."""
    parts = urllib.parse.urlsplit(str(url))
    scheme = (parts.scheme or "").lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        raise OutboundError(f"not an http(s) URL with a host: {safe_url(url)}")
    try:
        port = parts.port or _DEFAULT_PORTS[scheme]
    except ValueError:
        raise OutboundError(f"invalid port in {safe_url(url)}") from None
    return scheme, parts.hostname.lower(), port


def same_origin(a: str, b: str) -> bool:
    try:
        return origin(a) == origin(b)
    except OutboundError:
        return False


def allowed(url: str, base: str, extra_origins: Sequence[str] = ()) -> bool:
    """Whether ``url`` (chosen by the remote side) may be requested: same origin as ``base`` or an origin the
    operator listed in ``extra_origins`` (each a URL such as ``https://api2.example.com``)."""
    return same_origin(url, base) or any(same_origin(url, o) for o in extra_origins)


def safe_url(url: str) -> str:
    """The URL without its query string and user information, for messages: queries often carry tokens."""
    try:
        parts = urllib.parse.urlsplit(str(url))
        host = parts.hostname or ""
        netloc = f"{host}:{parts.port}" if parts.port else host
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        return "<invalid URL>"


def redact(text: str, secrets: Iterable[Optional[str]]) -> str:
    """``text`` with every secret value (at least 4 characters) replaced by ``***``."""
    out = str(text)
    for secret in sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True):
        out = out.replace(secret, "***")
    return out


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only within the request's origin (or an explicitly allowed one). A refused redirect is
    returned to the caller as the 3xx reply itself (``HTTPError``): nothing is sent to the other origin."""

    def __init__(self, extra_origins: Sequence[str] = ()):
        super().__init__()
        self.extra_origins = tuple(extra_origins)

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        if not allowed(newurl, req.full_url, self.extra_origins):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen(req: urllib.request.Request, timeout: float, extra_origins: Sequence[str] = (),
            deadline: Optional[float] = None):
    """``urllib.request.urlopen`` with redirects confined to the request's origin (and ``extra_origins``), and a
    deadline for the whole call (``deadline`` seconds; by default ``DEADLINE_FACTOR`` times ``timeout``). The
    deadline keeps running while the reply is read with :func:`read_limited`."""
    watch = _Watch(float(deadline) if deadline else float(timeout) * DEADLINE_FACTOR)
    opener = urllib.request.build_opener(_SameOriginRedirects(extra_origins), _WatchedHTTP(watch),
                                         _WatchedHTTPS(watch))
    try:
        resp = opener.open(req, timeout=timeout)  # noqa: S310 - destination comes from operator configuration
    except BaseException:
        watch.cancel()
        if watch.expired:
            raise watch.error() from None
        raise
    resp._autology_watch = watch
    return resp


def read_limited(resp, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read a reply body, refusing one larger than ``limit`` bytes or one that does not end within the call's
    deadline."""
    watch = getattr(resp, "_autology_watch", None)
    try:
        data = resp.read(limit + 1)
    except Exception:
        if watch is not None and watch.expired:
            raise watch.error() from None
        raise
    finally:
        if watch is not None:
            watch.cancel()
    if watch is not None and watch.expired:  # a reply cut at the deadline is never taken for a whole one
        raise watch.error()
    if len(data) > limit:
        raise OutboundError(f"the reply is larger than {limit} bytes")
    return data
