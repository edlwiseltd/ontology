"""GAP-030 (R2 security sprint, increment A): token lifetimes, revocation, rotation, rate limits, deadlines.

Tokens
  T1 an existing credential gets exactly one lifetime, counted from the first time this version sees it: it is
     not invalidated at the upgrade, a restart does not extend it, and after the lifetime it is refused everywhere
     (router, engine, MCP), with an explicit reason and the identity in the access log
  T2 people and service identities have separate lifetimes
  T3 a revoked token is refused at once and for good; the member and its grants stay; only administrators revoke;
     administrators' own tokens are not revoked through the API
  T4 rotation: the old token dies, the new one gets one lifetime and the same rights; a person may replace their
     own token; a service identity, a tenant-level identity, an expired token and another member may not
  T5 an explicit ``token_expires`` shortens a lifetime; a lifetime is always finite; a changed registry stops the
     start
  T6 a standalone engine enforces the same lifetimes (registry beside its store)
  T7 MCP follows: HTTP messages with an expired token are refused; a stdio session ends when its token expires,
     is revoked or replaced
  T8 automations keep running as their service identity whatever happens to API tokens

Rate limits
  R1 repeated failed sign-ins lock the address out before credentials are looked at (429 + Retry-After); a valid
     token from that address is refused too while it lasts (no oracle); the window ends by itself
  R2 an identity's limit holds across use cases, API versions and entry points; other identities are unaffected
  R3 a tenant's limit takes nothing from another tenant
  R4 ``X-Forwarded-For`` is ignored unless the peer is a trusted proxy
  R5 MCP messages are limited over HTTP and over stdio
  R6 requests that start work, administrative changes and anonymous endpoints have their own limits
  R7 the limiter itself: windows, disabled classes, floods of new keys, invalid configuration

Timeouts
  S1 a client that stalls is disconnected; S2 the server refuses connections beyond its limit with 503
  S3 a reply that trickles past the deadline ends the call as an *unknown outcome*: recorded, listed for
     reconciliation, never repeated blindly
  S4 a run that exceeds its time budget pauses between two steps; nothing in flight is cut; it can be resumed
"""

import http.client
import json
import os
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from autology import credentials, limits, outbound
from autology.mcp import McpServer
from autology.platform import Platform, PlatformError
from autology.server import ApiError, AutologyService, make_server

from .test_adm1_administration import AdminBase, WS
from .test_external_effects import EffectsTestCase, TIMEOUT
from .test_ingest import EX as CLAIMS, TOKENS as ENGINE_TOKENS
from .test_workspaces import Client, EX, data_admins

DAY = 86400.0
ENGINE = "/w/acme/u/claims/api/v1"


class SecurityBase(AdminBase):
    """The administration fixture with a ``security`` section and a clock the tests move."""

    security: dict = {}

    def setUp(self):
        self.now = 1_800_000_000.0
        self.tick = 1000.0
        for target, fn in (("autology.credentials.now", lambda: self.now),
                           ("autology.limits.monotonic", lambda: self.tick)):
            patcher = mock.patch(target, fn)
            patcher.start()
            self.addCleanup(patcher.stop)
        super().setUp()

    def start(self, change=None):
        self.stop()
        spec = data_admins(json.loads((EX / "platform.json").read_text()))
        spec["data_dir"] = self.data_dir
        spec["workspaces"]["acme"]["use_cases"]["claims"]["config"] = str(self.config_dir / "server.json")
        spec["security"] = json.loads(json.dumps(self.security))
        if change:
            change(spec)
        self.pf = Platform(spec, EX)
        self.c = Client(self.pf)
        uc = self.pf.workspaces["acme"].use_cases["claims"]
        if not self.pf.stage_of(uc)["history"]:
            self.pf.lifecycle.move("acme", "claims", uc.service, "simulation", "operator@test", "tests")

    def raw(self, method, path, token=None, body=None, headers=None):
        """(status, headers, body): like ``call``, with the response headers."""
        conn = http.client.HTTPConnection("127.0.0.1", self.c.server.server_port, timeout=10)
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["Authorization"] = f"Bearer {token}"
        conn.request(method, path, json.dumps(body) if body is not None else None, h)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), json.loads(data) if data else None

    def days(self, n):
        self.now += n * DAY

    def grant(self, name, permissions=("read",)):
        _, p = self.propose(name, list(permissions))
        self.assertEqual(self.call("POST", f"{WS}/grants/{p['id']}/approve", "acme-maria", {"reason": "ok"})[0], 200)

    def platform_log(self):
        return [(r["principal"], r["status"]) for r in self.pf.log.access_log(limit=50)]


class TokenLifetimeTests(SecurityBase):
    security = {"tokens": {"person_days": 30, "service_days": 300}}

    def test_an_existing_token_gets_one_lifetime_from_first_sight(self):  # T1
        status, me = self.call("GET", "/platform/v1/me", "acme-hana")
        self.assertEqual(status, 200)
        expires = me["token_expires_at"]
        self.assertEqual(expires, credentials.iso(self.now + 30 * DAY))
        self.assertEqual(self.engine("acme-hana")[1]["token_expires_at"], expires)
        self.days(20)
        self.start()  # a restart, a reload or naming the token again never extends it
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[1]["token_expires_at"], expires)
        self.assertEqual(self.engine("acme-hana")[0], 200)
        self.days(11)  # day 31
        for path in ("/platform/v1/me", f"{ENGINE}/me", f"{ENGINE}/objects", "/w/acme/u/claims/api/objects"):
            status, out = self.call("GET", path, "acme-hana")
            self.assertEqual(status, 401, path)
            text = json.dumps(out)
            self.assertIn("expired", text)
            self.assertIn("token_expired", text)
        status, out = self.call("POST", f"{ENGINE}/mcp", "acme-hana", {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(status, 401)  # MCP over HTTP follows (T7)
        self.assertIn(("hana@acme", 401), self.platform_log())  # whose token it was is on record
        # the engine refuses it by itself too, not only the router in front of it
        svc = self.pf.workspaces["acme"].use_cases["claims"].service
        with self.assertRaises(ApiError) as caught:
            svc.authenticate("Bearer acme-hana")
        self.assertEqual((caught.exception.status, caught.exception.extra["reason"]), (401, "token_expired"))
        self.start()  # still expired after a restart: the first sight is a record, not a start-up time
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 401)

    def test_people_and_services_have_separate_lifetimes(self):  # T2
        bot = self.add("bot", "service")
        zoe = self.add("zoe")
        _, view = self.call("GET", f"{WS}/members")
        by = {m["name"]: m for m in view["members"]}
        self.assertEqual(by["bot"]["token_expires_at"], credentials.iso(self.now + 300 * DAY))
        self.assertEqual(by["zoe"]["token_expires_at"], credentials.iso(self.now + 30 * DAY))
        self.assertEqual(view["token_policy"], {"person_days": 30.0, "service_days": 300.0})
        self.days(31)
        self.assertEqual(self.call("GET", "/platform/v1/me", zoe)[0], 401)
        self.assertEqual(self.call("GET", "/platform/v1/me", bot)[0], 200)
        self.days(270)
        status, out = self.call("GET", "/platform/v1/me", bot)
        self.assertEqual(status, 401)
        self.assertIn("service token expired", out["error"]["message"])

    def test_a_revoked_token_is_refused_at_once_and_for_good(self):  # T3
        zoe = self.add("zoe")
        self.grant("zoe")
        self.assertEqual(self.engine(zoe)[0], 200)
        for token in ("acme-hana", zoe):  # only administrators revoke
            self.assertEqual(self.call("POST", f"{WS}/members/zoe/revoke-token", token, {"reason": "x"})[0], 403)
        self.assertEqual(self.call("POST", f"{WS}/members/ada/revoke-token", body={"reason": "x"})[0], 403)
        status, view = self.call("POST", f"{WS}/members/zoe/revoke-token", body={"reason": "laptop lost"})
        self.assertEqual(status, 200, view)
        member = next(m for m in view["members"] if m["name"] == "zoe")
        self.assertEqual((member["token"], member["token_expires_at"]), ("none", None))
        self.assertEqual(member["use_cases"]["claims"]["permissions"], ["read"])  # membership and grants stay
        self.assertEqual(view["history"][-1]["event"], "token_revoked")
        self.assertEqual(view["history"][-1]["by"], "ada@acme")
        for path in ("/platform/v1/me", f"{ENGINE}/me"):
            self.assertEqual(self.call("GET", path, zoe)[0], 401)
        self.assertEqual(self.call("POST", f"{WS}/members/zoe/revoke-token", body={"reason": "again"})[0], 409)
        # zoe holds business data: her new token is requested by one person and issued by another (sprint B)
        status, asked = self.call("POST", f"{WS}/members/zoe/token", body={"reason": "new laptop"})
        self.assertEqual(status, 202, asked)
        status, out = self.call("POST", f"{WS}/token-requests/{asked['id']}/approve", "acme-maria", {"reason": "ok"})
        self.assertEqual(status, 200, out)
        self.assertEqual(self.engine(out["token"])[1]["permissions"], ["read"])  # same rights, nothing more
        self.start()
        self.assertEqual(self.call("GET", "/platform/v1/me", zoe)[0], 401)
        self.assertEqual(self.call("GET", "/platform/v1/me", out["token"])[0], 200)
        self.assertTrue(self.pf.credentials.revoked(credentials_digest(zoe)))
        events = [(e["event"], e["identity"]) for e in self.pf.credentials.events()]
        self.assertIn(("revoked", "zoe@acme"), events)
        self.assertNotIn(zoe, json.dumps(self.pf.credentials.events()))

    def test_rotation_keeps_rights_and_gives_one_lifetime(self):  # T4
        zoe, yan = self.add("zoe"), self.add("yan")
        self.grant("zoe")
        self.days(25)
        status, out = self.call("POST", f"{WS}/my-token", zoe, {"reason": "expires soon"})
        self.assertEqual(status, 200, out)
        fresh = out["token"]
        self.assertEqual(out["token_expires_at"], credentials.iso(self.now + 30 * DAY))  # one lifetime, not more
        self.assertEqual(self.call("GET", "/platform/v1/me", zoe)[0], 401)  # the old token died
        _, me = self.call("GET", "/platform/v1/me", fresh)
        self.assertEqual((me["member"], me["workspace_admin"], me["use_cases"][0]["permissions"]),
                         ("zoe", False, ["read"]))
        self.assertEqual(self.call("POST", f"{WS}/my-token", zoe, {"reason": "again"})[0], 401)  # replaced token
        _, view = self.call("GET", f"{WS}/members")
        self.assertEqual([e["by"] for e in view["history"] if e["event"] == "token_rotated"], ["zoe@acme"])
        # a service identity never renews itself; an administrator re-keys it
        bot = self.add("bot", "service")
        status, out = self.call("POST", f"{WS}/my-token", bot, {"reason": "renew"})
        self.assertEqual(status, 403)
        self.assertIn("service identity", out["error"]["message"])
        self.assertEqual(self.call("GET", "/platform/v1/me", bot)[0], 200)
        # nobody replaces another member's token without being an administrator
        self.assertEqual(self.call("POST", f"{WS}/members/bot/token", fresh, {"reason": "x"})[0], 403)
        self.assertEqual(self.call("POST", f"{WS}/members/bot/token", "acme-hana", {"reason": "x"})[0], 403)
        # another workspace's member gets the usual 404
        self.assertEqual(self.call("POST", f"{WS}/my-token", "nw-nadia", {"reason": "x"})[0], 404)
        # an administrator who is a person replaces her own token the same way: still an administrator, no more
        status, out = self.call("POST", f"{WS}/my-token", "acme-ada", {"reason": "expires soon"})
        self.assertEqual(status, 200, out)
        ada = out["token"]
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-ada")[0], 401)
        _, me = self.call("GET", "/platform/v1/me", ada)
        self.assertEqual((me["member"], me["workspace_admin"]), ("ada", True))
        self.days(6)  # day 31: tokens first seen on day 0 are over; the ones replaced on day 25 are not
        status, out = self.call("POST", f"{WS}/my-token", yan, {"reason": "too late"})
        self.assertEqual(status, 401)  # an expired token renews nothing
        self.assertIn("expired", out["error"]["message"])
        self.assertEqual(self.call("GET", "/platform/v1/me", fresh)[0], 200)
        status, out = self.call("POST", f"{WS}/members/yan/token", ada, {"reason": "expired"})
        self.assertEqual(status, 200, out)
        self.assertEqual(self.call("GET", "/platform/v1/me", out["token"])[0], 200)
        self.start()  # the replaced tokens stay replaced after a restart, whatever the configuration still names
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-ada")[0], 401)
        self.assertEqual(self.call("GET", "/platform/v1/me", ada)[0], 200)

    def test_explicit_expiry_and_finite_lifetimes(self):  # T5
        soon = credentials.iso(self.now + 2 * DAY)

        def explicit(spec):
            next(m for m in spec["workspaces"]["acme"]["members"] if m["name"] == "hana")["token_expires"] = soon
        self.start(explicit)
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[1]["token_expires_at"], soon)
        self.days(3)
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 401)
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-ivan")[0], 200)
        self.stop()
        for bad in ({"person_days": 0}, {"person_days": 99999}, {"service_days": True}, {"forever": 1}, "never"):
            with self.subTest(bad), self.assertRaises(PlatformError):
                Platform({**data_admins(json.loads((EX / "platform.json").read_text())),
                          "data_dir": tempfile.mkdtemp(), "security": {"tokens": bad}}, EX)
        with self.assertRaises(PlatformError):
            Platform({**data_admins(json.loads((EX / "platform.json").read_text())),
                      "data_dir": tempfile.mkdtemp(), "security": {"anything": 1}}, EX)

    def test_a_changed_registry_stops_the_start(self):  # T5
        self.stop()
        db = sqlite3.connect(str(Path(self.data_dir) / "credentials.db"))
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE credential_events SET at = at + 1e9")  # append-only: the database refuses
        db.executescript("DROP TRIGGER credential_events_append_only_u; UPDATE credential_events SET at = at + 1e9")
        db.commit()
        db.close()
        with self.assertRaises(PlatformError) as caught:
            self.start()
        self.assertIn("changed outside Autology", str(caught.exception))

    def test_tenant_level_identities_follow_the_same_rules(self):  # T1, T4
        def tenant(spec):
            spec["tenants"] = {"acme-group": {"name": "Acme", "workspaces": ["acme"], "members": [
                {"name": "tess", "token_sha256": credentials_digest("tess-token"), "tenant_admin": True}]}}
            # a new deployment for the registry: the tenancy record of the fixture's data folder is separate
            spec["data_dir"] = self.data_dir = tempfile.mkdtemp()
        self.start(tenant)
        status, me = self.call("GET", "/platform/v1/me", "tess-token")
        self.assertEqual((status, me["token_expires_at"]), (200, credentials.iso(self.now + 30 * DAY)))
        status, out = self.call("POST", f"{WS}/my-token", "tess-token", {"reason": "renew"})
        self.assertEqual(status, 403)  # configured identities are re-keyed in the configuration
        self.assertEqual(self.call("POST", f"{WS}/members/tess/revoke-token", body={"reason": "x"})[0], 403)
        self.days(31)
        self.assertEqual(self.call("GET", "/platform/v1/tenants/acme-group", "tess-token")[0], 401)


def credentials_digest(token):
    from autology.server import hash_token

    return hash_token(token)


class EngineTokenTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        patcher = mock.patch("autology.credentials.now", lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, token in ENGINE_TOKENS.items():
            os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
        self.folder = Path(tempfile.mkdtemp())
        self.opened = []

    def service(self, **overrides):
        cfg = json.loads((CLAIMS / "server.json").read_text())
        cfg["store"] = str(self.folder / "claims.db")
        cfg["security"] = {"tokens": {"person_days": 10, "service_days": 100}}
        cfg.update(overrides)
        svc = AutologyService(cfg, CLAIMS)
        self.opened.append(svc)
        return svc

    def stop(self, svc):
        self.opened.remove(svc)
        svc.close()

    def tearDown(self):
        for svc in self.opened:
            svc.close()

    def test_a_standalone_engine_enforces_lifetimes(self):  # T6
        svc = self.service()
        user = svc.authenticate("Bearer tok-hana")
        self.assertEqual(svc.me(user)["token_expires_at"], credentials.iso(self.now + 10 * DAY))
        self.assertTrue((self.folder / "claims.db.credentials").is_file())
        self.now += 6 * DAY
        self.stop(svc)
        svc = self.service()  # a restart does not extend anything
        self.assertEqual(svc.me(svc.authenticate("Bearer tok-hana"))["token_expires_at"],
                         credentials.iso(self.now + 4 * DAY))
        self.now += 5 * DAY
        with self.assertRaises(ApiError) as caught:
            svc.authenticate("Bearer tok-hana")
        self.assertEqual(caught.exception.status, 401)
        self.assertIn("expired", caught.exception.message)
        self.stop(svc)
        users = json.loads((CLAIMS / "server.json").read_text())["users"]
        users[0]["token_expires"] = "not a date"
        with self.assertRaises(ValueError):
            self.service(users=users)
        users[0]["token_expires"] = credentials.iso(self.now + DAY)
        users[1]["kind"] = "service"
        svc = self.service(users=users, store=str(self.folder / "other.db"))
        by = {u.name: u for u in svc.users}
        self.assertEqual(by[users[0]["name"]].expires_at, self.now + DAY)  # explicit and earlier
        self.assertEqual(by[users[1]["name"]].expires_at, self.now + 100 * DAY)  # a service identity
        svc.credentials.revoke(by["admin"].token_sha256, "operator", "leaked")
        with self.assertRaises(ApiError) as caught:
            svc.authenticate("Bearer tok-admin-ai")
        self.assertEqual(caught.exception.extra["reason"], "token_revoked")

    def test_registry_details(self):  # T5, T6
        self.assertEqual(credentials.parse_time(12.5, "x"), 12.5)
        self.assertEqual(credentials.parse_time("2027-01-31", "x"), credentials.parse_time("2027-01-31T00:00:00Z", "x"))
        self.assertIsNone(credentials.iso(None))
        registry = credentials.CredentialRegistry(self.folder / "r.db", b"key")
        self.addCleanup(registry.close)
        self.assertIsNone(registry.registered_at("a" * 64))
        self.assertFalse(registry.revoked("a" * 64))
        registry.revoke("a" * 64, "operator", "seen in a log")  # a token never seen can still be refused for good
        self.assertTrue(registry.revoked("a" * 64))
        self.assertEqual(registry.register("a" * 64, "late@x", "person"), self.now)  # naming it later changes nothing
        self.assertTrue(registry.revoked("a" * 64))
        self.assertEqual(registry.register("b" * 64, "bot", "robot"), self.now)  # an unknown kind counts as a person
        self.assertEqual([e["event"] for e in registry.events()], ["registered", "revoked", "registered"])
        self.assertEqual(credentials.TokenPolicy.parse({"person_days": 1}).view(),
                         {"person_days": 1.0, "service_days": 365.0})

    def test_without_a_file_lifetimes_count_from_the_start(self):  # T6: stated, not silent
        with self.assertLogs("autology.server", "WARNING") as logged:
            svc = self.service(store=":memory:")
        self.assertIn("lifetimes count from this start", "\n".join(logged.output))
        self.assertFalse(svc.credentials_persistent)
        self.now += 11 * DAY
        with self.assertRaises(ApiError):
            svc.authenticate("Bearer tok-hana")

    def test_a_stdio_mcp_session_ends_with_its_token(self):  # T7
        svc = self.service()
        user = svc.authenticate("Bearer tok-hana")
        session = McpServer(svc, user)
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual(session.handle(ping)["result"], {})
        self.now += 11 * DAY
        out = session.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(out["error"]["code"], -32001)
        self.assertIn("expired", out["error"]["message"])
        # replaced or removed in the meantime: the session ends too
        self.now -= 11 * DAY
        self.assertEqual(session.handle(ping)["result"], {})
        svc.set_users([u for u in json.loads((CLAIMS / "server.json").read_text())["users"] if u["name"] != "hana"])
        self.assertIn("replaced or its member removed", session.handle(ping)["error"]["message"])
        ivan = McpServer(svc, svc.authenticate("Bearer tok-ivan"))
        svc.credentials.revoke(ivan.user.token_sha256, "operator", "leaked")
        self.assertIn("revoked", ivan.handle(ping)["error"]["message"])
        self.assertIn(("ivan", 401), [(r["principal"], r["status"]) for r in svc.store.access_log(limit=5)])

    def test_automations_run_as_their_service_identity_whatever_tokens_do(self):  # T8
        svc = self.service()
        self.now += 5000 * DAY  # every API token is long expired
        with self.assertRaises(ApiError):
            svc.authenticate("Bearer tok-admin-ai")
        out = svc.tick()
        fired = [f for f in out["firings"] if f["automation"] == "settle_new_claims"]
        self.assertTrue(fired, out)
        self.assertTrue(all(f.get("run_id") for f in fired), fired)
        run = svc.store.load_run(fired[0]["run_id"])
        self.assertIsNotNone(run)


class RateLimitTests(SecurityBase):
    security = {"rate_limits": {"auth_failures": 3, "api": 6, "tenant": 14, "mcp": 2, "expensive": 2, "admin": 2,
                                "anonymous": 5, "window_seconds": 60}}

    def test_failed_sign_ins_lock_the_address_out_without_an_oracle(self):  # R1
        for _ in range(3):
            self.assertEqual(self.call("GET", "/platform/v1/me", "guess")[0], 401)
        status, headers, out = self.raw("GET", "/platform/v1/me", "guess")
        self.assertEqual((status, out["error"]["code"]), (429, "rate_limited"))
        self.assertEqual(int(headers["Retry-After"]), out["error"]["details"]["retry_after_seconds"])
        self.assertTrue(1 <= int(headers["Retry-After"]) <= 60)
        # the right token from the same address is refused the same way: the answer says nothing about a guess
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 429)
        self.assertEqual(self.call("GET", f"{ENGINE}/me", "acme-hana")[0], 429)
        status, headers, out = self.raw("GET", "/w/acme/u/claims/api/me", "acme-hana")  # legacy shape, same refusal
        self.assertEqual((status, out["retry_after_seconds"], headers["Retry-After"]),
                         (429, int(headers["Retry-After"]), str(out["retry_after_seconds"])))
        self.assertIn(("anonymous", 429), self.platform_log())
        self.tick += 61  # the window ends by itself
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 200)
        self.assertEqual(self.call("GET", "/platform/v1/me", "guess")[0], 401)

    def test_an_identity_cannot_get_around_its_limit(self):  # R2
        paths = ["/platform/v1/me", f"{ENGINE}/me", "/w/acme/u/claims/api/me", "/platform/me",
                 f"{ENGINE}/objects", "/platform/v1/workspaces/acme/use-cases"]
        for path in paths:  # 6 requests through every door: all counted on the same identity
            self.assertEqual(self.call("GET", path, "acme-hana")[0], 200, path)
        for path in paths + ["/w/acme/u/orders/api/v1/me"]:
            status, headers, out = self.raw("GET", path, "acme-hana")
            self.assertEqual(status, 429, path)
            self.assertIn("Retry-After", headers)
        self.assertEqual(self.call("GET", f"{ENGINE}/me", "acme-ivan")[0], 200)  # another identity is unaffected
        self.assertIn(("hana@acme", 429), self.platform_log())  # refusals are on record
        self.tick += 61
        self.assertEqual(self.call("GET", f"{ENGINE}/me", "acme-hana")[0], 200)

    def test_one_tenant_at_its_limit_takes_nothing_from_another(self):  # R3
        seen = []
        for i in range(16):
            token = ("acme-hana", "acme-ivan", "acme-maria", "acme-olivia")[i % 4]
            seen.append(self.call("GET", f"{ENGINE}/me", token)[0])
        self.assertEqual(len([s for s in seen if s != 429]), 14)  # refusals (a 404) count like any request
        self.assertEqual(seen[-2:], [429, 429])
        status, out = self.call("GET", "/platform/v1/me", "acme-lena")  # the same tenant, any door
        self.assertEqual(status, 429)
        self.assertIn("tenant", out["error"]["message"])
        for _ in range(3):  # the other tenant is served
            self.assertEqual(self.call("GET", "/platform/v1/me", "nw-nadia")[0], 200)
            self.assertEqual(self.call("GET", "/w/northwind/u/claims/api/v1/me", "nw-nadia")[0], 200)
        # unauthenticated requests naming a tenant's workspace never used up its allowance
        self.tick += 61
        for _ in range(3):
            self.call("GET", f"{ENGINE}/me", "guess")
        self.tick += 61
        self.assertEqual([self.call("GET", f"{ENGINE}/me", "acme-hana")[0] for _ in range(6)], [200] * 6)

    def test_forwarded_addresses_are_believed_only_from_trusted_proxies(self):  # R4
        spoof = lambda n: {"X-Forwarded-For": f"203.0.113.{n}"}  # noqa: E731
        for n in range(3):
            self.assertEqual(self.raw("GET", "/platform/v1/me", "guess", headers=spoof(n))[0], 401)
        # a new "address" in the header changes nothing: the peer is what is counted
        self.assertEqual(self.raw("GET", "/platform/v1/me", "guess", headers=spoof(99))[0], 429)
        self.assertEqual(self.raw("GET", "/platform/v1/me", "acme-hana", headers=spoof(100))[0], 429)
        self.security = {**self.security, "trusted_proxies": ["127.0.0.1"]}
        self.tick += 61
        self.start()
        for _ in range(3):  # now the proxy vouches for the client address: each client has its own count
            self.assertEqual(self.raw("GET", "/platform/v1/me", "guess", headers=spoof(1))[0], 401)
        self.assertEqual(self.raw("GET", "/platform/v1/me", "guess", headers=spoof(1))[0], 429)
        self.assertEqual(self.raw("GET", "/platform/v1/me", "acme-hana", headers=spoof(2))[0], 200)
        addr = limits.client_address
        nets = limits.parse_proxies(["10.0.0.0/8", "127.0.0.1"])
        self.assertEqual(addr("198.51.100.7", "1.2.3.4", nets), "198.51.100.7")  # not a proxy: header ignored
        self.assertEqual(addr("10.1.1.1", "1.2.3.4, 10.2.2.2", nets), "1.2.3.4")
        self.assertEqual(addr("10.1.1.1", "9.9.9.9, 1.2.3.4", nets), "1.2.3.4")  # right-most untrusted hop
        self.assertEqual(addr("10.1.1.1", "evil, 1.2.3.4", nets), "1.2.3.4")
        self.assertEqual(addr("10.1.1.1", "1.2.3.4, evil", nets), "10.1.1.1")  # malformed chain: the peer
        self.assertEqual(addr("10.1.1.1", "10.2.2.2", nets), "10.1.1.1")
        self.assertEqual(addr(None, None, nets), "-")
        with self.assertRaises(limits.LimitError):
            limits.parse_proxies(["not an address"])
        with self.assertRaises(limits.LimitError):
            limits.parse_proxies("127.0.0.1")

    def test_mcp_messages_are_limited_over_http_and_stdio(self):  # R5
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        for _ in range(2):
            self.assertEqual(self.call("POST", f"{ENGINE}/mcp", "acme-hana", ping)[0], 200)
        status, headers, out = self.raw("POST", f"{ENGINE}/mcp", "acme-hana", ping)
        self.assertEqual((status, out["error"]["code"]), (429, "rate_limited"))
        self.assertIn("MCP", out["error"]["message"])
        self.assertEqual(self.call("GET", f"{ENGINE}/me", "acme-hana")[0], 200)  # the rest of the API still answers
        svc = self.pf.workspaces["acme"].use_cases["claims"].service
        session = McpServer(svc, svc.authenticate("Bearer acme-ivan"))
        self.assertEqual([("result" in session.handle(ping)) for _ in range(2)], [True, True])
        refused = session.handle(ping)
        self.assertEqual(refused["error"]["code"], -32029)
        self.assertEqual(refused["error"]["data"]["retry_after_seconds"], 60)
        self.assertIsNone(session.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.tick += 61
        self.assertIn("result", session.handle(ping))

    def test_work_administration_and_anonymous_endpoints_have_their_own_limits(self):  # R6
        run = {"case_template": "claim_case", "root": "CL-1"}
        codes = [self.call("POST", f"{ENGINE}/runs", "acme-hana", run)[0] for _ in range(3)]
        self.assertEqual(codes[2], 429)
        self.assertNotIn(429, codes[:2])
        self.assertEqual(self.call("GET", f"{ENGINE}/runs", "acme-hana")[0], 200)  # reading is not "starting work"
        self.tick += 61
        added = [self.call("POST", f"{WS}/members", body={"name": f"m{i}", "reason": "joins"})[0] for i in range(3)]
        self.assertEqual(added, [201, 201, 429])
        _, view = self.call("GET", f"{WS}/members")
        self.assertNotIn("m2", [m["name"] for m in view["members"]])  # refused before anything happened
        self.tick += 61
        health = [self.raw("GET", "/platform/health")[0] for _ in range(6)]
        self.assertEqual(health, [200] * 5 + [429])
        self.assertEqual(self.raw("GET", "/platform/openapi.json")[0], 429)
        self.assertEqual(self.raw("GET", "/w/acme/u/claims/api/health", "acme-hana")[0], 429)
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 200)  # signed-in work goes on
        self.assertEqual(limits.engine_class("POST", ["runs", "R-1", "resume"]), "expensive")
        self.assertEqual(limits.engine_class("POST", ["reviews", "V-1", "decision"]), "expensive")
        self.assertEqual(limits.engine_class("POST", ["settings", "assistant"]), "admin")
        self.assertEqual(limits.engine_class("POST", ["agents", "claims", "reinstate"]), "admin")
        self.assertEqual(limits.engine_class("GET", ["mcp"]), "mcp")
        self.assertIsNone(limits.engine_class("GET", ["runs"]))
        self.assertIsNone(limits.engine_class("POST", ["objects"]))
        self.assertIsNone(limits.engine_class("GET", []))


class LimiterTests(unittest.TestCase):  # R7
    def setUp(self):
        self.tick = 0.0
        patcher = mock.patch("autology.limits.monotonic", lambda: self.tick)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_windows_and_refusals(self):
        limiter = limits.RateLimiter({"api": 2}, window=10)
        self.assertEqual([limiter.hit("api", "a") for _ in range(3)], [None, None, 10])
        self.tick = 4.2
        self.assertEqual(limiter.hit("api", "a"), 6)  # refused requests do not extend the wait
        self.assertEqual(limiter.blocked("api", "a"), 6)
        self.assertIsNone(limiter.hit("api", "b"))
        self.assertIsNone(limiter.blocked("api", "b"))
        self.tick = 10.0
        self.assertIsNone(limiter.blocked("api", "a"))
        self.assertIsNone(limiter.hit("api", "a"))
        self.assertEqual(limiter.view()["scope"], "this server process only")

    def test_disabled_classes_and_invalid_configuration(self):
        limiter = limits.RateLimiter.parse({"api": 0, "mcp": None, "window_seconds": 5})
        self.assertEqual([limiter.hit("api", "a") for _ in range(50)], [None] * 50)
        self.assertIsNone(limiter.blocked("mcp", "a"))
        self.assertEqual(limits.RateLimiter.parse(None).limits, limits.DEFAULT_LIMITS)
        for bad in ({"api": -1}, {"api": 1.5}, {"api": True}, {"unknown": 3}, {"window_seconds": 0}, [1]):
            with self.subTest(bad), self.assertRaises(limits.LimitError):
                limits.RateLimiter.parse(bad)
        for bad in ({"max_connections": 0}, {"request_timeout_seconds": 0}, {"other": 1}, [1]):
            with self.subTest(bad), self.assertRaises(limits.LimitError):
                limits.parse_server(bad)
        self.assertEqual(limits.parse_server({"max_connections": 3, "request_timeout_seconds": 2}),
                         {"max_connections": 3, "request_timeout": 2.0})

    def test_a_flood_of_new_keys_is_refused_not_remembered(self):
        limiter = limits.RateLimiter({"anonymous": 5}, window=10)
        with mock.patch("autology.limits.MAX_KEYS", 3):
            self.assertEqual([limiter.hit("anonymous", f"k{i}") for i in range(4)], [None, None, None, 10])
            self.assertIsNone(limiter.hit("anonymous", "k0"))  # known keys are still served
            self.tick = 11.0  # expired counters are dropped first
            self.assertIsNone(limiter.hit("anonymous", "k9"))


class ServerLimitTests(unittest.TestCase):
    def setUp(self):
        for name, token in ENGINE_TOKENS.items():
            os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
        cfg = json.loads((CLAIMS / "server.json").read_text())
        cfg["store"] = ":memory:"
        cfg["security"] = {"server": {"max_connections": 2, "request_timeout_seconds": 0.5},
                           "rate_limits": {"auth_failures": 2, "anonymous": 4}}
        self.svc = AutologyService(cfg, CLAIMS)
        self.server = make_server(self.svc, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_port
        self.addCleanup(self.svc.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path="/api/health", token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={"Authorization": f"Bearer {token}"} if token else {})
        r = conn.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        conn.close()
        return out

    def stall(self, data=b"POST /api/runs HTTP/1.1\r\nContent-Length: 100\r\n\r\n{"):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        sock.sendall(data)
        self.addCleanup(sock.close)
        return sock

    def test_a_standalone_engine_limits_sign_ins_and_anonymous_requests(self):  # R1, R6 without the router
        self.assertEqual(self.get("/api/v1/me", "tok-hana")[0], 200)
        self.assertEqual([self.get("/api/v1/me", "guess")[0] for _ in range(2)], [401, 401])
        status, headers, body = self.get("/api/v1/me", "tok-hana")  # locked out before the token is looked at
        self.assertEqual((status, json.loads(body)["error"]["code"]), (429, "rate_limited"))
        self.assertTrue(1 <= int(headers["Retry-After"]) <= 60)
        self.assertEqual(self.get("/api/me")[0], 429)
        rows = [(r["principal"], r["status"]) for r in self.svc.store.access_log(limit=10)]
        self.assertIn(("-", 429), rows)  # refused before any identity is known
        self.assertEqual([self.get("/api/health")[0] for _ in range(5)], [200] * 4 + [429])
        self.assertEqual(self.get("/api/openapi.json")[0], 429)
        self.assertEqual(self.get("/api/auth/config")[0], 429)

    def test_a_stalled_client_is_disconnected(self):  # S1
        started = time.monotonic()
        sock = self.stall()  # promises 100 bytes, sends one, then nothing
        self.assertEqual(self.get()[0], 200)  # others are served meanwhile
        self.assertEqual(sock.recv(1000), b"")  # the server closed it, without an answer
        self.assertLess(time.monotonic() - started, 4)
        idle = self.stall(b"")  # connects and says nothing at all
        self.assertEqual(idle.recv(1000), b"")
        self.assertEqual(self.get()[0], 200)

    def test_connections_beyond_the_limit_get_503_at_once(self):  # S2
        self.stall()
        self.stall()
        time.sleep(0.1)
        started = time.monotonic()
        status, headers, body = self.get()
        self.assertEqual((status, headers["Retry-After"]), (503, "1"))
        self.assertIn("limit of concurrent requests", json.loads(body)["error"])
        self.assertLess(time.monotonic() - started, 0.4)  # refused at once, not queued
        self.assertEqual(self.server.refused, 1)
        time.sleep(0.7)  # the stalled connections timed out: capacity is back
        self.assertEqual(self.get()[0], 200)


class DripBank:
    """Executes the payment, then answers with a body that trickles: every read arrives well within the client's
    per-read timeout, so only a deadline for the whole call ends it."""

    def __init__(self, seconds):
        self.executed, self.stop_at = [], seconds
        bank = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                bank.executed.append(body.get("idempotency_key"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100000")
                self.end_headers()
                end = time.monotonic() + bank.stop_at
                try:
                    while time.monotonic() < end:
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(TIMEOUT / 8)
                except OSError:
                    pass

            do_GET = do_POST

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/pay"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class DeadlineTests(EffectsTestCase):
    def test_a_trickling_reply_ends_as_an_unknown_outcome(self):  # S3
        drip = DripBank(seconds=TIMEOUT * 12)
        self.addCleanup(drip.stop)
        self.bank.url = drip.url
        svc = self.service()
        self.addCleanup(svc.close)
        started = time.monotonic()
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        elapsed = time.monotonic() - started
        # the deadline is 3 x the timeout: far less than the 12 x the service would have kept the engine waiting
        self.assertLess(elapsed, TIMEOUT * 7, "the call must end at its deadline")
        self.assertEqual(len(drip.executed), 1, "the payment was executed once and never repeated")
        self.assertEqual(run["status"], "uncertain")
        call = self.pay_calls(svc)[0]
        self.assertEqual(call["state"], "unknown")
        self.assertIn("deadline", call["detail"])
        stored = svc.store.load_run(run["run_id"])
        self.assertEqual(stored.run.pending_external["key"], call["key"])  # durable: a restart finds it
        self.assertTrue(svc.store.verify_audit(run["run_id"]))
        items = svc.list_reconciliation(self.u["admin"])["items"]
        self.assertIn(("pay_claim", "unknown"), [(i["action"], i["state"]) for i in items])
        self.assertNotEqual(svc.graph.get("CL-1").attributes["status"], "paid")
        # a second run on the same claim does not pay again while the first payment is unresolved
        with self.assertRaises(ApiError):
            svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(len(drip.executed), 1)

    def test_the_deadline_bounds_reading_and_is_configurable(self):  # S3
        import urllib.request

        drip = DripBank(seconds=3)
        self.addCleanup(drip.stop)
        started = time.monotonic()
        with self.assertRaises(outbound.DeadlineExceeded):
            with outbound.urlopen(urllib.request.Request(drip.url), 0.5, deadline=0.6) as resp:
                outbound.read_limited(resp)
        self.assertLess(time.monotonic() - started, 2)
        from autology.adapters import OutcomeUnknown, http_tool
        from autology.tools import ToolCall

        tool = http_tool(drip.url, timeout=0.5, deadline=0.4)
        with self.assertRaises(OutcomeUnknown) as caught:
            tool(ToolCall("pay_claim", "payments.pay", {}, {}, 1, "k-1", None))
        self.assertIn("may have acted", str(caught.exception))
        # no reply at all before the deadline (the per-read timeout is longer): cut while waiting for the headers
        self.bank.behaviour = lambda n: "timeout"
        started = time.monotonic()
        with self.assertRaises(outbound.DeadlineExceeded):
            outbound.urlopen(urllib.request.Request(self.bank.url, data=b"{}", method="POST"), 5, deadline=0.3)
        self.assertLess(time.monotonic() - started, 1.0)
        with self.assertRaises(OutcomeUnknown) as caught:
            http_tool(self.bank.url, timeout=5, deadline=0.3)(ToolCall("pay_claim", "payments.pay", {}, {}, 1, "k-2",
                                                                         None))
        self.assertIn("deadline of 0.3 s", str(caught.exception))
        self.bank.behaviour = lambda n: "ok"
        # a normal reply is unaffected, and its watchdog is cancelled
        before = threading.active_count()
        with outbound.urlopen(urllib.request.Request(self.bank.url, data=b"{}", method="POST"), 2) as resp:
            self.assertIn(b"paid", outbound.read_limited(resp))
        time.sleep(0.05)
        self.assertLessEqual(threading.active_count(), before)

    def test_a_run_over_its_time_budget_pauses_between_steps(self):  # S4
        cfg_security = {"run_seconds": 1}
        svc = self.service()
        self.addCleanup(svc.close)
        self.assertEqual(svc.run_seconds, 900.0)  # the default
        for member in [svc.agents["claims"].agent] + svc.agents["claims"].agent.delegates:
            member.max_seconds = 0.0  # every step is "too late": the budget is checked before the first one
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(run["status"], "paused")
        stored = svc.store.load_run(run["run_id"])
        self.assertIn("time budget", stored.escalation["reason"] if isinstance(stored.escalation, dict)
                      else str(stored.escalation))
        self.assertIn("time_budget_exhausted", [e.event for e in stored.audit])
        self.assertEqual(self.bank.executed, [])  # nothing was started, so nothing was cut
        for member in [svc.agents["claims"].agent] + svc.agents["claims"].agent.delegates:
            member.max_seconds = 900.0
        resumed = svc.resume_run(self.u["hana"], run["run_id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(len(self.bank.executed), 1)
        cfg = json.loads((CLAIMS / "server.json").read_text())
        cfg.update(store=":memory:", security=cfg_security)
        other = AutologyService(cfg, CLAIMS)
        self.addCleanup(other.close)
        self.assertEqual(other.agents["claims"].agent.max_seconds, 1.0)
        for bad in ({"run_seconds": 0}, {"run_seconds": "long"}, {"nope": 1}):
            cfg["security"] = bad
            with self.subTest(bad), self.assertRaises(ValueError):
                AutologyService(cfg, CLAIMS)


if __name__ == "__main__":
    unittest.main()
