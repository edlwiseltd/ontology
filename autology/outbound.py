"""Outbound HTTP for configured integrations (audit findings F-01 and F-08, 15 Nov 2026).

The operator configures where Autology may send requests (tool URLs, approvers, webhooks, pipelines, identity
providers, trace collectors); those destinations are trusted configuration. What is **not** trusted is a destination
chosen by the other side: a redirect, or a "next page" link in a reply. Such a destination is followed only when it
has the same origin (scheme, host and port) as the configured URL, or an origin the operator listed explicitly, so a
compromised or malicious service cannot make Autology forward credentials to another host or probe the internal
network on its behalf (SSRF).

Replies are read up to a size limit, and error texts never contain secret values: they are built from the
configured URL template, and :func:`redact` removes any known secret that still appears.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable, Optional, Sequence, Tuple

MAX_RESPONSE_BYTES = 16 * 1024 * 1024  # a reply larger than this is refused, not read into memory
_DEFAULT_PORTS = {"http": 80, "https": 443}


class OutboundError(Exception):
    """A reply that Autology refuses to use: too large, or redirected to an origin that was not allowed."""


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


def urlopen(req: urllib.request.Request, timeout: float, extra_origins: Sequence[str] = ()):
    """``urllib.request.urlopen`` with redirects confined to the request's origin (and ``extra_origins``)."""
    opener = urllib.request.build_opener(_SameOriginRedirects(extra_origins))
    return opener.open(req, timeout=timeout)  # noqa: S310 - destination comes from operator configuration


def read_limited(resp, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read a reply body, refusing one larger than ``limit`` bytes."""
    data = resp.read(limit + 1)
    if len(data) > limit:
        raise OutboundError(f"the reply is larger than {limit} bytes")
    return data
