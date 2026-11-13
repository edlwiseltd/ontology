"""Single sign-on with OpenID Connect: company accounts instead of (or beside) API tokens.

    "oidc": {
      "issuer": "https://login.example.com/realms/acme",
      "client_id": "autology-inbox",                 # the inbox's sign-in button (authorization code + PKCE)
      "audiences": ["autology-api"],                 # other accepted token audiences (machine clients)
      "username_claim": "preferred_username",
      "mappings": [
        {"claim": "groups", "value": "claims-handlers", "permissions": ["read", "run"], "roles": ["claims_handler"]},
        {"claim": "groups", "value": "claims-managers", "permissions": ["read", "review"],
         "roles": ["claims_handler"], "reviewer_roles": ["claims_manager"]}]}

A request may carry a signed JWT from the identity provider (Okta, Microsoft Entra ID, Keycloak, Auth0, Google...)
instead of an Autology API token. It is accepted only if:

* its signature verifies against the provider's published keys (JWKS, found by OIDC discovery). RS256, RS384 and
  RS512 are supported and nothing else (never ``none`` or a shared-secret algorithm); keys under 2048 bits are
  refused. The keys are re-fetched when a token names one not seen before, at most once a minute;
* the issuer matches exactly, the audience is the inbox's ``client_id`` or one of ``audiences``, and it is within
  its validity period (``leeway`` seconds of clock skew, default 60);
* the person maps to at least one permission: permissions, ontology roles and reviewer roles come from
  ``mappings`` over the token's claims (a claim may be a list, such as ``groups``). Signed in but unmapped means
  no access, never default access;
* the user name (``username_claim``, default ``sub``) is not also the name of an API-token user, so a provider
  account cannot take over a configured user's runs and reviews.

Everything else (permissions, row and field access, reviews, the access log) is the same as for token users.
The signature check is written with the standard library (RSA PKCS#1 v1.5 verification is one modular
exponentiation and a comparison); no cryptography package is needed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence

log = logging.getLogger("autology.oidc")

_HASHES = {"RS256": (hashlib.sha256, bytes.fromhex("3031300d060960864801650304020105000420")),
           "RS384": (hashlib.sha384, bytes.fromhex("3041300d060960864801650304020205000430")),
           "RS512": (hashlib.sha512, bytes.fromhex("3051300d060960864801650304020305000440"))}
MIN_KEY_BITS = 2048
REFETCH_AFTER = 60.0


class OidcError(Exception):
    """A token or a provider response was not acceptable. ``status`` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or any(c not in
                                        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in text):
        raise OidcError("malformed token")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int(b64: str) -> int:
    return int.from_bytes(b64url_decode(b64), "big")


def rsa_pkcs1_verify(n: int, e: int, alg: str, message: bytes, signature: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 verification (RFC 8017, 8.2.2): recompute the encoded digest and compare."""
    hash_fn, prefix = _HASHES[alg]
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = prefix + hash_fn(message).digest()
    if k < len(t) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def _fetch_json(url: str, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
                timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class OidcProvider:
    def __init__(self, config: Dict[str, Any], fetch: Callable[..., Any] = _fetch_json, clock=time.time):
        self.issuer = str(config.get("issuer") or "").rstrip("/")
        if not self.issuer.startswith(("https://", "http://")):
            raise ValueError("oidc.issuer must be the provider's https URL")
        self.client_id = config.get("client_id")
        self.client_secret_env = config.get("client_secret_env")
        self.audiences = set(config.get("audiences") or []) | ({self.client_id} if self.client_id else set())
        if not self.audiences:
            raise ValueError("oidc: give client_id (for the inbox) or audiences (for API clients)")
        self.algorithms = list(config.get("algorithms") or ["RS256"])
        unknown = set(self.algorithms) - set(_HASHES)
        if unknown:
            raise ValueError(f"oidc.algorithms: unsupported {sorted(unknown)}; supported: {sorted(_HASHES)}")
        self.username_claim = str(config.get("username_claim") or "sub")
        self.leeway = float(config.get("leeway", 60))
        self.scopes = str(config.get("scopes") or "openid profile email")
        self.jwks_uri = config.get("jwks_uri")
        self.mappings = []
        for i, m in enumerate(config.get("mappings") or []):
            if not m.get("claim") or "value" not in m:
                raise ValueError(f"oidc.mappings[{i}]: claim and value are required")
            self.mappings.append({"claim": str(m["claim"]), "value": m["value"],
                                  "permissions": frozenset(m.get("permissions") or []),
                                  "roles": frozenset(m.get("roles") or []),
                                  "reviewer_roles": frozenset(m.get("reviewer_roles") or [])})
        self._fetch, self._clock = fetch, clock
        self._lock = threading.Lock()
        self._discovery: Optional[Dict[str, Any]] = None
        self._keys: Dict[str, Dict[str, Any]] = {}
        self._keys_at = 0.0

    def permissions_in_mappings(self) -> FrozenSet[str]:
        return frozenset().union(*(m["permissions"] for m in self.mappings)) if self.mappings else frozenset()

    # -- provider metadata ---------------------------------------------------------
    def discovery(self) -> Dict[str, Any]:
        if self._discovery is None:
            try:
                doc = self._fetch(self.issuer + "/.well-known/openid-configuration")
            except Exception as exc:  # network or JSON errors: no sign-in rather than a guess
                log.warning("OIDC discovery for %s failed: %s", self.issuer, exc)
                raise OidcError("the identity provider cannot be reached", 503) from None
            if not isinstance(doc, dict) or str(doc.get("issuer", "")).rstrip("/") != self.issuer:
                raise OidcError("the identity provider's discovery document names another issuer", 503)
            self._discovery = doc
        return self._discovery

    def _load_keys(self) -> None:
        uri = self.jwks_uri or self.discovery().get("jwks_uri")
        try:
            jwks = self._fetch(uri)
        except Exception as exc:
            log.warning("fetching OIDC keys from %s failed: %s", uri, exc)
            raise OidcError("the identity provider's keys cannot be fetched", 503) from None
        keys = {}
        for jwk in (jwks or {}).get("keys", []):
            if jwk.get("kty") == "RSA" and jwk.get("use", "sig") == "sig" and jwk.get("kid") and "n" in jwk:
                keys[jwk["kid"]] = jwk
        self._keys, self._keys_at = keys, self._clock()

    def key(self, kid: str) -> Dict[str, Any]:
        with self._lock:
            if kid not in self._keys and (not self._keys_at or self._clock() - self._keys_at >= REFETCH_AFTER):
                self._load_keys()  # first use, or a key we have not seen: the provider may have rotated keys
            jwk = self._keys.get(kid)
        if jwk is None:
            raise OidcError("token signed with an unknown key")
        return jwk

    # -- tokens ----------------------------------------------------------------------
    def verify(self, token: str, nonce: Optional[str] = None) -> Dict[str, Any]:
        """The token's claims, if and only if it is a valid, current token for this deployment."""
        parts = token.split(".")
        if len(parts) != 3:
            raise OidcError("malformed token")
        try:
            header = json.loads(b64url_decode(parts[0]))
            claims = json.loads(b64url_decode(parts[1]))
            signature = b64url_decode(parts[2])
        except (ValueError, UnicodeDecodeError):
            raise OidcError("malformed token") from None
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise OidcError("malformed token")
        alg = header.get("alg")
        if alg not in self.algorithms:
            raise OidcError(f"token algorithm {alg!r} is not accepted")
        if header.get("crit"):
            raise OidcError("token uses unsupported critical header parameters")
        jwk = self.key(str(header.get("kid") or ""))
        if jwk.get("alg") not in (None, alg):
            raise OidcError("token algorithm does not match its key")
        n, e = _int(jwk["n"]), _int(jwk.get("e", "AQAB"))
        if n.bit_length() < MIN_KEY_BITS:
            raise OidcError(f"the provider's key is shorter than {MIN_KEY_BITS} bits")
        if not rsa_pkcs1_verify(n, e, alg, f"{parts[0]}.{parts[1]}".encode(), signature):
            raise OidcError("token signature does not verify")
        now = self._clock()
        if str(claims.get("iss", "")).rstrip("/") != self.issuer:
            raise OidcError("token is from another issuer")
        aud = claims.get("aud")
        auds = set(aud) if isinstance(aud, list) else {aud}
        if not auds & self.audiences:
            raise OidcError("token is for another audience")
        if not isinstance(claims.get("exp"), (int, float)) or now > claims["exp"] + self.leeway:
            raise OidcError("token expired")
        if isinstance(claims.get("nbf"), (int, float)) and now < claims["nbf"] - self.leeway:
            raise OidcError("token not valid yet")
        if isinstance(claims.get("iat"), (int, float)) and claims["iat"] > now + self.leeway:
            raise OidcError("token issued in the future")
        if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise OidcError("sign-in response does not match this browser's request")
        return claims

    def grants(self, claims: Dict[str, Any]) -> Dict[str, FrozenSet[str]]:
        perms, roles, reviewer = set(), set(), set()
        for m in self.mappings:
            value = claims.get(m["claim"])
            values = value if isinstance(value, list) else [value]
            if m["value"] in values:
                perms |= m["permissions"]
                roles |= m["roles"]
                reviewer |= m["reviewer_roles"]
        return {"permissions": frozenset(perms), "roles": frozenset(roles), "reviewer_roles": frozenset(reviewer)}

    def username(self, claims: Dict[str, Any]) -> str:
        name = claims.get(self.username_claim)
        if not isinstance(name, str) or not name.strip():
            raise OidcError(f"token has no {self.username_claim!r} claim to name the user")
        return name.strip()

    # -- the inbox's sign-in (authorization code with PKCE) ----------------------------------------------------------
    def login_config(self) -> Dict[str, Any]:
        if not self.client_id:
            return {"oidc": False}
        doc = self.discovery()
        return {"oidc": True, "authorization_endpoint": doc.get("authorization_endpoint"),
                "client_id": self.client_id, "scopes": self.scopes}

    def exchange(self, code: str, verifier: str, redirect_uri: str, nonce: str) -> Dict[str, Any]:
        """Swap the authorization code for tokens at the provider and return the verified ID token."""
        import os

        if not self.client_id:
            raise OidcError("sign-in with the identity provider is not configured", 404)
        for name, value in (("code", code), ("code_verifier", verifier), ("redirect_uri", redirect_uri),
                            ("nonce", nonce)):
            if not isinstance(value, str) or not value or len(value) > 4096:
                raise OidcError(f"{name} is required", 400)
        if not redirect_uri.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise OidcError("redirect_uri must be https (or localhost)", 400)
        form = {"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                "redirect_uri": redirect_uri, "client_id": self.client_id}
        if self.client_secret_env:
            secret = os.environ.get(self.client_secret_env)
            if not secret:
                raise OidcError(f"environment variable {self.client_secret_env} is not set", 503)
            form["client_secret"] = secret
        endpoint = self.discovery().get("token_endpoint")
        try:
            tokens = self._fetch(endpoint, urllib.parse.urlencode(form).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
        except urllib.error.HTTPError as exc:
            log.info("OIDC code exchange refused: %s", exc.code)
            raise OidcError("the identity provider refused the sign-in", 401) from None
        except Exception as exc:
            log.warning("OIDC code exchange failed: %s", exc)
            raise OidcError("the identity provider cannot be reached", 503) from None
        id_token = (tokens or {}).get("id_token")
        if not isinstance(id_token, str):
            raise OidcError("the identity provider returned no ID token", 502)
        claims = self.verify(id_token, nonce=nonce)
        return {"token": id_token, "expires_at": claims.get("exp")}


def make_jwt(claims: Dict[str, Any], key: Sequence[int], kid: str, alg: str = "RS256") -> str:
    """Sign ``claims`` with an RSA private key ``(n, e, d)``: for tests and local tooling, not for production."""
    n, _, d = key
    header = b64url_encode(json.dumps({"alg": alg, "typ": "JWT", "kid": kid}).encode())
    payload = b64url_encode(json.dumps(claims).encode())
    hash_fn, prefix = _HASHES[alg]
    k = (n.bit_length() + 7) // 8
    t = prefix + hash_fn(f"{header}.{payload}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{header}.{payload}.{b64url_encode(sig)}"


def jwk_of(key: Sequence[int], kid: str) -> Dict[str, Any]:
    n, e, _ = key
    to_b64 = lambda i: b64url_encode(i.to_bytes((i.bit_length() + 7) // 8, "big"))  # noqa: E731
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": to_b64(n), "e": to_b64(e)}


def generate_rsa_key(bits: int = 2048) -> List[int]:
    """A fresh RSA key ``[n, e, d]`` from the standard library (for tests and local identity-provider stand-ins)."""
    import secrets

    def probable_prime(nbits: int) -> int:
        small = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** 0.5) + 1, 2))]
        while True:
            c = secrets.randbits(nbits) | (1 << (nbits - 1)) | (1 << (nbits - 2)) | 1
            if any(c % p == 0 for p in small):
                continue
            d, r = c - 1, 0
            while d % 2 == 0:
                d //= 2
                r += 1
            for _ in range(40):  # Miller-Rabin
                a = secrets.randbelow(c - 3) + 2
                x = pow(a, d, c)
                if x in (1, c - 1):
                    continue
                for _ in range(r - 1):
                    x = pow(x, 2, c)
                    if x == c - 1:
                        break
                else:
                    break
            else:
                return c

    e = 65537
    while True:
        p, q = probable_prime(bits // 2), probable_prime(bits // 2)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e:
            return [p * q, e, pow(e, -1, phi)]
