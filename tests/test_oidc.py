"""Tier 3: single sign-on with OpenID Connect - token verification, mappings, and the inbox's code exchange."""

import base64
import hashlib
import json
import os
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autology.oidc import (OidcError, OidcProvider, b64url_encode, generate_rsa_key, jwk_of, make_jwt,
                           rsa_pkcs1_verify)
from autology.server import ApiError

from .test_ingest import TOKENS, service as insurance_service
from .test_platform import _Api

KEY = generate_rsa_key(2048)
KEY2 = generate_rsa_key(2048)


class FakeIdP:
    """A minimal OpenID provider: discovery, JWKS, and a token endpoint that checks PKCE."""

    def __init__(self):
        self.keys = [jwk_of(KEY, "k1")]
        self.codes = {}  # code -> (challenge, claims)
        self.requests = []
        idp = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                idp.requests.append(self.path)
                if self.path == "/.well-known/openid-configuration":
                    return self.reply(200, {"issuer": idp.issuer, "jwks_uri": idp.issuer + "/jwks",
                                            "authorization_endpoint": idp.issuer + "/authorize",
                                            "token_endpoint": idp.issuer + "/token"})
                if self.path == "/jwks":
                    return self.reply(200, {"keys": idp.keys})
                return self.reply(404, {})

            def do_POST(self):  # noqa: N802
                form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
                idp.last_form = form
                challenge, claims = idp.codes.pop(form.get("code"), (None, None))
                verifier = form.get("code_verifier", "")
                computed = b64url_encode(hashlib.sha256(verifier.encode()).digest())
                if claims is None or computed != challenge:
                    return self.reply(400, {"error": "invalid_grant"})
                return self.reply(200, {"id_token": idp.token(**claims), "token_type": "Bearer"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.issuer = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def token(self, key=KEY, kid="k1", alg="RS256", **claims):
        now = time.time()
        base = {"iss": self.issuer, "aud": "autology-inbox", "sub": "u-1", "preferred_username": "nora",
                "groups": ["claims-managers"], "iat": now, "exp": now + 300}
        base.update(claims)
        return make_jwt({k: v for k, v in base.items() if v is not None}, key, kid, alg)

    def issue_code(self, verifier, **claims):
        code = os.urandom(8).hex()
        self.codes[code] = (b64url_encode(hashlib.sha256(verifier.encode()).digest()), claims)
        return code


OIDC = {"client_id": "autology-inbox", "audiences": ["autology-api"], "username_claim": "preferred_username",
        "mappings": [
            {"claim": "groups", "value": "claims-handlers", "permissions": ["read", "run"],
             "roles": ["claims_handler"]},
            {"claim": "groups", "value": "claims-managers", "permissions": ["read", "review"],
             "roles": ["claims_handler"], "reviewer_roles": ["claims_manager"]},
            {"claim": "email", "value": "ops@example.com", "permissions": ["admin"]}]}


class RsaTests(unittest.TestCase):
    def test_interoperates_with_the_cryptography_package(self):
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
        except ImportError:  # pragma: no cover - CI installs it
            self.skipTest("cryptography not installed")
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub = private.public_key().public_numbers()
        for alg, h in (("RS256", hashes.SHA256()), ("RS384", hashes.SHA384()), ("RS512", hashes.SHA512())):
            with self.subTest(alg):
                sig = private.sign(b"message", padding.PKCS1v15(), h)
                self.assertTrue(rsa_pkcs1_verify(pub.n, pub.e, alg, b"message", sig))
                self.assertFalse(rsa_pkcs1_verify(pub.n, pub.e, alg, b"messagE", sig))
                self.assertFalse(rsa_pkcs1_verify(pub.n, pub.e, alg, b"message", sig[:-1]))
        # and a token we sign verifies with the cryptography package
        n, e, d = KEY
        token = make_jwt({"a": 1}, KEY, "k1")
        head, payload, sig = token.split(".")
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        RSAPublicNumbers(e, n).public_key().verify(
            base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)), f"{head}.{payload}".encode(),
            padding.PKCS1v15(), hashes.SHA256())


class VerifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idp = FakeIdP()

    @classmethod
    def tearDownClass(cls):
        cls.idp.server.shutdown()

    def provider(self, **extra):
        return OidcProvider({"issuer": self.idp.issuer, **OIDC, **extra})

    def test_valid_token(self):
        claims = self.provider().verify(self.idp.token())
        self.assertEqual(claims["preferred_username"], "nora")
        self.assertEqual(self.provider().verify(self.idp.token(aud=["x", "autology-api"]))["sub"], "u-1")

    def test_rejections(self):
        p, now = self.provider(), time.time()
        unsigned = lambda header, claims: (b64url_encode(json.dumps(header).encode()) + "." +  # noqa: E731
                                           b64url_encode(json.dumps(claims).encode()) + ".")
        good = self.idp.token()
        h, body, sig = good.split(".")
        forged_body = b64url_encode(json.dumps({**json.loads(base64.urlsafe_b64decode(body + "==")),
                                                "groups": ["admins"]}).encode())
        cases = {
            "alg none": unsigned({"alg": "none", "kid": "k1"}, {"iss": self.idp.issuer}),
            "hmac": unsigned({"alg": "HS256", "kid": "k1"}, {"iss": self.idp.issuer}) + "abc",
            "issuer": self.idp.token(iss="https://evil.example"),
            "audience": self.idp.token(aud="someone-else"),
            "expired": self.idp.token(exp=now - 3600),
            "no exp": self.idp.token(exp=None),
            "not yet": self.idp.token(nbf=now + 3600),
            "future iat": self.idp.token(iat=now + 3600),
            "tampered claims": f"{h}.{forged_body}.{sig}",
            "tampered signature": f"{h}.{body}.{sig[:-4]}AAAA",
            "other key": self.idp.token(key=KEY2),
            "malformed": "a.b",
            "garbage": "!!.??.**",
            "crit": make_jwt({"iss": self.idp.issuer}, KEY, "k1").replace(
                b64url_encode(json.dumps({"alg": "RS256", "typ": "JWT", "kid": "k1"}).encode()),
                b64url_encode(json.dumps({"alg": "RS256", "kid": "k1", "crit": ["x"]}).encode())),
        }
        for label, token in cases.items():
            with self.subTest(label), self.assertRaises(OidcError):
                p.verify(token)
        with self.assertRaises(OidcError):
            p.verify(self.idp.token(nonce="abc"), nonce="xyz")

    def test_key_rotation_and_refetch_limit(self):
        clock = [1000.0]
        p = OidcProvider({"issuer": self.idp.issuer, **OIDC}, clock=lambda: clock[0])
        token = lambda kid, key: self.idp.token(key=key, kid=kid, iat=clock[0], exp=clock[0] + 300)  # noqa: E731
        p.verify(token("k1", KEY))
        self.idp.keys = [jwk_of(KEY, "k1"), jwk_of(KEY2, "k2")]  # the provider rotates in a new key
        self.addCleanup(setattr, self.idp, "keys", [jwk_of(KEY, "k1")])
        with self.assertRaises(OidcError):  # fetched less than a minute ago: no refetch (no fetch storms)
            p.verify(token("k2", KEY2))
        clock[0] += 61
        self.assertEqual(p.verify(token("k2", KEY2))["sub"], "u-1")

    def test_weak_or_mismatched_keys(self):
        weak = generate_rsa_key(1024)
        self.idp.keys = [jwk_of(weak, "weak"), {**jwk_of(KEY, "rs512only"), "alg": "RS512"}]
        self.addCleanup(setattr, self.idp, "keys", [jwk_of(KEY, "k1")])
        p = self.provider()
        with self.assertRaisesRegex(OidcError, "shorter than 2048"):
            p.verify(self.idp.token(key=weak, kid="weak"))
        with self.assertRaisesRegex(OidcError, "does not match its key"):
            p.verify(self.idp.token(kid="rs512only"))

    def test_provider_failures_fail_closed(self):
        broken = OidcProvider({"issuer": "http://127.0.0.1:9", **OIDC})
        with self.assertRaises(OidcError) as cm:
            broken.verify(self.idp.token())
        self.assertEqual(cm.exception.status, 503)
        liar = OidcProvider({"issuer": self.idp.issuer, **OIDC},
                            fetch=lambda url, *a: {"issuer": "https://other.example"})
        with self.assertRaisesRegex(OidcError, "another issuer"):
            liar.verify(self.idp.token())

    def test_configuration_errors(self):
        for bad in ({"issuer": "idp.example", "client_id": "c"}, {"issuer": "https://idp.example"},
                    {"issuer": "https://idp.example", "client_id": "c", "algorithms": ["HS256"]},
                    {"issuer": "https://idp.example", "client_id": "c", "mappings": [{"claim": "groups"}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                OidcProvider(bad)


class ServiceSsoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idp = FakeIdP()

    @classmethod
    def tearDownClass(cls):
        cls.idp.server.shutdown()

    def setUp(self):
        self.svc = insurance_service(automations={}, oidc={"issuer": self.idp.issuer, **OIDC})
        self.api = _Api(self.svc)
        self.addCleanup(self.api.server.shutdown)

    def test_company_accounts_get_mapped_access(self):
        status, me, _ = self.api.call("GET", "/api/me", self.idp.token())
        self.assertEqual(status, 200)
        self.assertEqual((me["name"], sorted(me["permissions"]), me["reviewer_roles"]),
                         ("nora", ["read", "review"], ["claims_manager"]))
        status, me, _ = self.api.call("GET", "/api/me", self.idp.token(
            preferred_username="olu", groups=[], email="ops@example.com", aud="autology-api"))
        self.assertEqual((status, me["permissions"]), (200, ["admin"]))
        status, body, _ = self.api.call("GET", "/api/me", self.idp.token(preferred_username="zed", groups=["x"]))
        self.assertEqual(status, 403)  # signed in, but nothing grants access
        self.assertIn("no oidc mapping", body["error"])
        status, body, _ = self.api.call("GET", "/api/me", self.idp.token(preferred_username="admin"))
        self.assertEqual(status, 401)  # would take over the API-token user "admin"
        status, _, _ = self.api.call("GET", "/api/me", self.idp.token(exp=time.time() - 3600))
        self.assertEqual(status, 401)
        self.assertEqual(self.api.call("GET", "/api/me", TOKENS["hana"])[0], 200)  # API tokens still work
        log = self.svc.store.access_log(limit=20)
        self.assertIn("nora", {r["principal"] for r in log})

    def test_sso_reviewer_decides_and_access_rules_apply(self):
        hana = next(u for u in self.svc.users if u.name == "hana")
        etl = next(u for u in self.svc.users if u.name == "etl")
        self.svc.run_pipeline(etl, "claims_feed", {})
        run = self.svc.start_run(hana, {"case_template": "claim_case", "root": "CL-2"})
        ivan = next(u for u in self.svc.users if u.name == "ivan")
        self.svc.decide(ivan, run["pending_review"], {"approved": True})
        pending = self.svc.get_run(hana, run["run_id"])["pending_review"]
        status, review, _ = self.api.call("GET", f"/api/reviews/{pending}", self.idp.token())
        self.assertEqual(status, 200)
        self.assertEqual(review["request"]["view"]["Policy"]["holder"], "Ben Okafor")  # claims_handler role
        status, out, _ = self.api.call("POST", f"/api/reviews/{pending}/decision", self.idp.token(),
                                       {"approved": True, "comment": "within limits"})
        self.assertEqual(status, 200)
        self.assertEqual(self.svc.get_run(hana, run["run_id"])["status"], "completed")
        self.assertEqual(self.svc.store.get_review(pending)["decided_by"], "nora")

    def test_inbox_code_exchange(self):
        status, cfg, _ = self.api.call("GET", "/api/auth/config")
        self.assertEqual((status, cfg["client_id"], cfg["authorization_endpoint"]),
                         (200, "autology-inbox", self.idp.issuer + "/authorize"))
        verifier = "v" * 43
        code = self.idp.issue_code(verifier, nonce="n-1")
        body = {"code": code, "code_verifier": verifier, "redirect_uri": "http://localhost:8800/", "nonce": "n-1"}
        status, out, _ = self.api.call("POST", "/api/auth/token", body=body)
        self.assertEqual((status, out["name"]), (200, "nora"))
        self.assertEqual(self.idp.last_form["client_id"], "autology-inbox")
        self.assertEqual(self.api.call("GET", "/api/me", out["token"])[1]["name"], "nora")
        cases = [
            ({**body, "code": self.idp.issue_code(verifier, nonce="n-1"), "code_verifier": "w" * 43}, 401),  # PKCE
            ({**body, "code": "used-or-unknown"}, 401),
            ({**body, "code": self.idp.issue_code(verifier, nonce="n-2")}, 401),  # nonce from another sign-in
            ({**body, "redirect_uri": "http://evil.example/"}, 400),
            ({**body, "code": ""}, 400),
            ({**body, "code": self.idp.issue_code(verifier, nonce="n-1", groups=[])}, 403),  # no access
        ]
        for request, expected in cases:
            with self.subTest(request=request, expected=expected):
                self.assertEqual(self.api.call("POST", "/api/auth/token", body=request)[0], expected)

    def test_confidential_client_secret_from_environment(self):
        svc = insurance_service(automations={}, oidc={"issuer": self.idp.issuer, **OIDC,
                                                      "client_secret_env": "TEST_OIDC_SECRET"})
        verifier = "v" * 43
        body = {"code": self.idp.issue_code(verifier, nonce="n"), "code_verifier": verifier,
                "redirect_uri": "https://autology.example/", "nonce": "n"}
        with self.assertRaises(ApiError) as cm:
            svc.sso_token(body)
        self.assertEqual(cm.exception.status, 503)
        os.environ["TEST_OIDC_SECRET"] = "s3cret"
        self.addCleanup(os.environ.pop, "TEST_OIDC_SECRET")
        body["code"] = self.idp.issue_code(verifier, nonce="n")
        self.assertEqual(svc.sso_token(body)["name"], "nora")
        self.assertEqual(self.idp.last_form["client_secret"], "s3cret")

    def test_not_configured_and_bad_mappings(self):
        svc = insurance_service(automations={})
        self.assertEqual(svc.sso_config(), {"oidc": False})
        with self.assertRaises(ApiError) as cm:
            svc.sso_token({})
        self.assertEqual(cm.exception.status, 404)
        with self.assertRaisesRegex(ValueError, "unknown permissions"):
            insurance_service(oidc={"issuer": self.idp.issuer, "client_id": "c",
                                    "mappings": [{"claim": "groups", "value": "x", "permissions": ["superuser"]}]})
        api_only = insurance_service(oidc={"issuer": self.idp.issuer, "audiences": ["autology-api"]})
        self.assertEqual(api_only.sso_config(), {"oidc": False})  # no client_id: no inbox button


if __name__ == "__main__":
    unittest.main()
