"""PoC 3: OIDC token forgery / confusion attempts against OidcProvider.verify (fetch stubbed, no network)."""
import json, time, hmac, hashlib
from harness import ROOT  # noqa
from autology.oidc import OidcError, OidcProvider, b64url_encode, generate_rsa_key, jwk_of, make_jwt

ISS = "https://idp.example"
KEY, EVIL = generate_rsa_key(2048), generate_rsa_key(2048)
jwks = {"keys": [jwk_of(KEY, "k1")]}
now = [time.time()]


def fetch(url, data=None, headers=None):
    if url.endswith("/.well-known/openid-configuration"):
        return {"issuer": ISS, "jwks_uri": ISS + "/jwks", "token_endpoint": ISS + "/token"}
    if url.endswith("/jwks"):
        return jwks
    raise RuntimeError("down")


p = OidcProvider({"issuer": ISS, "client_id": "autology-inbox", "mappings": [
    {"claim": "groups", "value": "g", "permissions": ["read"]}]}, fetch=fetch, clock=lambda: now[0])


def claims(**kw):
    c = {"iss": ISS, "aud": "autology-inbox", "sub": "u1", "groups": ["g"], "iat": now[0], "exp": now[0] + 300}
    c.update(kw)
    return {k: v for k, v in c.items() if v is not None}


def raw(header, payload, sig=b""):
    return ".".join([b64url_encode(json.dumps(header).encode()), b64url_encode(json.dumps(payload).encode()),
                     b64url_encode(sig)])


def attempt(label, tok):
    try:
        p.verify(tok)
        print(f"ACCEPTED  {label}")
    except OidcError as e:
        print(f"refused   {label}: {e} ({e.status})")
    except Exception as e:
        print(f"EXCEPTION {label}: {type(e).__name__}: {e}")


attempt("valid token (control)", make_jwt(claims(), KEY, "k1"))
attempt("alg none", raw({"alg": "none", "kid": "k1"}, claims()))
n_bytes = jwk_of(KEY, "k1")["n"].encode()
h = {"alg": "HS256", "kid": "k1"}
msg = f"{b64url_encode(json.dumps(h).encode())}.{b64url_encode(json.dumps(claims()).encode())}"
attempt("HS256 keyed with public n", msg + "." + b64url_encode(hmac.new(n_bytes, msg.encode(), hashlib.sha256).digest()))
attempt("attacker key, known kid", make_jwt(claims(), EVIL, "k1"))
attempt("attacker key, new kid", make_jwt(claims(), EVIL, "evil"))
attempt("wrong audience", make_jwt(claims(aud="other-client"), KEY, "k1"))
attempt("aud list incl. ours", make_jwt(claims(aud=["other", "autology-inbox"]), KEY, "k1"))
attempt("wrong issuer", make_jwt(claims(iss="https://evil"), KEY, "k1"))
attempt("issuer prefix", make_jwt(claims(iss=ISS + ".evil"), KEY, "k1"))
attempt("no exp", make_jwt(claims(exp=None), KEY, "k1"))
attempt("expired", make_jwt(claims(exp=now[0] - 3600), KEY, "k1"))
attempt("exp as string", make_jwt(claims(exp="9999999999"), KEY, "k1"))
attempt("nbf future", make_jwt(claims(nbf=now[0] + 3600), KEY, "k1"))
attempt("crit header", raw({"alg": "RS256", "kid": "k1", "crit": ["x"]}, claims()))
attempt("unhashable aud (signed)", make_jwt(claims(aud={"a": 1}), KEY, "k1"))
# key revocation: the IdP drops k1 (e.g. compromised) and publishes k2
jwks = {"keys": [jwk_of(EVIL, "k2")]}
now[0] += 3600
attempt("token signed by REMOVED key k1 after rotation (1h later)", make_jwt(claims(), KEY, "k1"))
