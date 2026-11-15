"""ADM-1 / ADM-2: workspace administration through the API, applied without a restart (owner decision D11).

  A1 a workspace administrator (a person) adds a member; the token is shown once, only its hash is kept, and the
     member can sign in at the next request (no restart)
  A2 a grant is proposed, and takes effect only when another person with authority approves it: never the
     proposer, never the member who receives it, never a service identity, never someone without authority
  A3 revoking a grant or removing a member takes effect at the next request; a rotated token replaces the old one
  A4 nobody becomes a workspace administrator through the API, and administrators cannot be removed through it
  A5 members other than administrators and approvers cannot administer; another workspace gets the same 404
  A6 the administration log is append-only and chained: if it is changed outside Autology, only the configured
     administrators keep access (fail closed)
  A7 the changes survive a restart (the log is replayed over platform.json)
  A8 an engine reloads from its files without a restart; invalid files change nothing; a reload is not an
     activation (an active release then counts as drift)
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autology.platform import Platform

from .helpers import ROOT
from .test_r2_use_case_lifecycle import close
from .test_workspaces import EX, TOKENS, Client

AUTO = ROOT / "examples" / "auto_insurance"
WS = "/platform/v1/workspaces/acme"


class AdminBase(unittest.TestCase):
    def setUp(self):
        os.environ.update(TOKENS)
        self.config_dir = Path(tempfile.mkdtemp()) / "claims"
        shutil.copytree(AUTO, self.config_dir)
        self.data_dir = tempfile.mkdtemp()
        self.pf = self.c = None
        self.start()

    def start(self):
        self.stop()
        spec = json.loads((EX / "platform.json").read_text())
        spec["data_dir"] = self.data_dir
        spec["workspaces"]["acme"]["use_cases"]["claims"]["config"] = str(self.config_dir / "server.json")
        self.pf = Platform(spec, EX)
        self.c = Client(self.pf)
        uc = self.pf.workspaces["acme"].use_cases["claims"]
        if not self.pf.stage_of(uc)["history"]:
            self.pf.lifecycle.move("acme", "claims", uc.service, "simulation", "operator@test", "tests")

    def stop(self):
        if self.c:
            self.c.server.shutdown()
            self.c.server.server_close()
        if self.pf:
            close(self.pf)
        self.pf = self.c = None

    def tearDown(self):
        self.stop()

    def call(self, method, path, token="acme-ada", body=None):
        return self.c.call(method, path, token, body)

    def add(self, name, kind="person"):
        status, out = self.call("POST", f"{WS}/members", body={"name": name, "kind": kind, "reason": "joins"})
        self.assertEqual(status, 201, out)
        return out["token"]

    def propose(self, member, permissions, token="acme-ada", **extra):
        return self.call("POST", f"{WS}/grants", token, {"member": member, "use_case": "claims",
                                                          "permissions": permissions, "reason": "needs it", **extra})

    def engine(self, token, path="/me"):
        return self.c.call("GET", f"/w/acme/u/claims/api/v1{path}", token)


class MembershipTests(AdminBase):
    def test_a_member_added_signs_in_at_once_and_the_token_is_shown_once(self):  # A1
        token = self.add("zoe")
        self.assertTrue(token.startswith("atl_"))
        status, me = self.c.call("GET", "/platform/v1/me", token)
        self.assertEqual((status, me["member"], me["use_cases"]), (200, "zoe", []))
        _, view = self.call("GET", f"{WS}/members")
        zoe = next(m for m in view["members"] if m["name"] == "zoe")
        self.assertEqual((zoe["source"], zoe["kind"], zoe["use_cases"]), ("api", "person", {}))
        self.assertNotIn(token, json.dumps(view))  # never shown again, not even its value in the history
        self.assertEqual(self.call("POST", f"{WS}/members", body={"name": "zoe", "reason": "again"})[0], 409)

    def test_a_grant_needs_another_person_with_authority(self):  # A2
        token = self.add("zoe")
        bot = self.add("pipeline", kind="service")
        status, g = self.propose("zoe", ["read", "run"], roles=["claims_handler"])
        self.assertEqual((status, g["status"]), (201, "pending"))
        self.assertEqual(self.engine(token)[0], 404)  # pending: nothing yet
        approve = f"{WS}/grants/{g['id']}/approve"
        status, out = self.call("POST", approve, "acme-ada", {"reason": "mine"})
        self.assertEqual(status, 403)
        self.assertIn("proposer", out["error"]["message"])
        self.assertEqual(self.call("POST", approve, "acme-hana", {"reason": "x"})[0], 403)  # no authority
        self.assertEqual(self.call("POST", approve, bot, {"reason": "x"})[0], 403)  # a service, no authority
        status, view = self.call("POST", approve, "acme-maria", {"reason": "checked"})  # a named approver
        self.assertEqual(status, 200, view)
        status, me = self.engine(token)
        self.assertEqual((status, me["name"], sorted(me["permissions"])), (200, "zoe", ["read", "run"]))
        self.assertEqual(self.call("POST", approve, "acme-maria", {"reason": "twice"})[0], 404)  # no longer pending

    def test_nobody_approves_a_grant_to_themselves(self):  # A2
        status, g = self.propose("maria", ["read", "review", "run"])
        self.assertEqual(status, 201)
        status, out = self.call("POST", f"{WS}/grants/{g['id']}/approve", "acme-maria", {"reason": "for me"})
        self.assertEqual(status, 403)
        self.assertIn("themselves", out["error"]["message"])
        self.assertEqual(self.call("POST", f"{WS}/grants/{g['id']}/withdraw", body={"reason": "no"})[0], 200)

    def test_grants_are_checked_by_the_engine_before_they_are_recorded(self):
        self.add("zoe")
        self.assertEqual(self.propose("zoe", ["fly"])[0], 400)
        status, out = self.propose("zoe", ["run"], run_as={"no-such-agent": ["finance"]})
        self.assertEqual(status, 400)
        self.assertIn("unknown agent", out["error"]["message"])
        self.assertEqual(self.propose("ada", ["read"])[0], 409)  # an administrator already has every right
        self.assertEqual(self.call("POST", f"{WS}/grants", body={"member": "zoe", "use_case": "nope",
                                                                 "permissions": [], "reason": "x"})[0], 400)

    def test_revocation_removal_and_rotation_take_effect_at_once(self):  # A3
        self.assertEqual(self.engine("acme-hana")[0], 200)
        status, _ = self.call("POST", f"{WS}/members/hana/revoke", body={"use_case": "claims", "reason": "left"})
        self.assertEqual(status, 200)
        self.assertEqual(self.engine("acme-hana")[0], 404)  # no second person needed to take access away
        self.assertEqual(self.c.call("GET", "/platform/v1/me", "acme-ivan")[0], 200)
        status, out = self.call("POST", f"{WS}/members/ivan/token", body={"reason": "laptop lost"})
        self.assertEqual(status, 200)
        self.assertEqual(self.c.call("GET", "/platform/v1/me", "acme-ivan")[0], 401)
        self.assertEqual(self.engine(out["token"])[0], 200)
        self.assertEqual(self.call("POST", f"{WS}/members/ivan/remove", body={"reason": "left"})[0], 200)
        self.assertEqual(self.engine(out["token"])[0], 401)

    def test_no_administrator_through_the_api(self):  # A4
        status, out = self.call("POST", f"{WS}/members/ada/remove", body={"reason": "x"})
        self.assertEqual(status, 403)
        self.add("zoe")
        status, g = self.propose("zoe", ["admin"])  # engine admin on one use case is a grant, approved like any
        self.assertEqual(status, 201)
        _, view = self.call("GET", f"{WS}/members")
        self.assertFalse(next(m for m in view["members"] if m["name"] == "zoe")["workspace_admin"])
        unknown = self.call("POST", f"{WS}/members", body={"name": "x", "workspace_admin": True, "reason": "x"})
        self.assertEqual(unknown[0], 201)  # the flag is ignored: only platform.json makes administrators
        _, view = self.call("GET", f"{WS}/members")
        self.assertFalse(next(m for m in view["members"] if m["name"] == "x")["workspace_admin"])

    def test_only_administrators_and_approvers_administer_and_other_workspaces_get_404(self):  # A5
        self.assertEqual(self.call("GET", f"{WS}/members", "acme-hana")[0], 403)
        self.assertEqual(self.call("GET", f"{WS}/members", "acme-maria")[0], 200)  # an approver reads
        self.assertEqual(self.call("POST", f"{WS}/members", "acme-maria", {"name": "q", "reason": "x"})[0], 403)
        for token in ("nw-nadia", "nw-hana"):
            self.assertEqual(self.call("GET", f"{WS}/members", token)[0], 404)
        self.assertEqual(self.call("GET", "/platform/v1/workspaces/nowhere/members", "nw-nadia")[0], 404)

    def test_a_changed_log_fails_closed_and_changes_survive_a_restart(self):  # A6, A7
        token = self.add("zoe")
        _, g = self.propose("zoe", ["read"])
        self.call("POST", f"{WS}/grants/{g['id']}/approve", "acme-maria", {"reason": "ok"})
        self.start()  # restart: the log is replayed over platform.json
        self.assertEqual(self.engine(token)[0], 200)
        db = sqlite3.connect(self.pf.admin.path)
        db.execute("DROP TRIGGER admin_events_append_only_u")
        db.execute("UPDATE admin_events SET reason='edited' WHERE seq=1")
        db.commit()
        db.close()
        self.start()
        self.assertEqual(self.engine(token)[0], 401)
        self.assertEqual(self.c.call("GET", "/platform/v1/me", "acme-hana")[0], 401)  # configured, not an admin
        status, view = self.call("GET", f"{WS}/members")  # the configured administrator still administers
        self.assertEqual(status, 200)
        self.assertIn("does not verify", view["integrity_problem"])
        self.assertEqual(self.call("POST", f"{WS}/members", body={"name": "y", "reason": "x"})[0], 409)
        db = sqlite3.connect(self.pf.admin.path)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM admin_events")
        db.close()


class ReloadTests(AdminBase):
    def test_reload_without_restart_and_it_is_not_an_activation(self):  # A8
        rel = "/platform/v1/workspaces/acme/use-cases/claims/releases"
        _, r = self.call("POST", rel, body={"note": "first"})
        self.call("POST", f"{rel}/{r['number']}/approve", "acme-maria", {"reason": "ok"})
        self.assertEqual(self.call("POST", f"{rel}/{r['number']}/activate", body={"reason": "go"})[0], 200)
        before = self.pf.workspaces["acme"].use_cases["claims"].service.configuration_fingerprint
        tools = json.loads((self.config_dir / "tools.json").read_text())
        tools["tools"][0]["cost"] = 0.9
        (self.config_dir / "tools.json").write_text(json.dumps(tools))
        path = "/platform/v1/workspaces/acme/use-cases/claims/reload"
        self.assertEqual(self.call("POST", path, "acme-hana", {"reason": "x"})[0], 403)
        status, view = self.call("POST", path, body={"reason": "new fraud engine cost"})
        self.assertEqual(status, 200, view)
        self.assertNotEqual(view["configuration"], before)
        self.assertTrue(view["release"]["drift"])  # reloaded, but nothing runs until a release of it is active
        self.assertEqual(view["effective_stage"], "draft")
        _, hist = self.call("GET", f"{WS}/members")
        self.assertEqual(hist["history"][-1]["event"], "engine_reloaded")
        (self.config_dir / "tools.json").write_text("{not json")
        status, out = self.call("POST", path, body={"reason": "broken files"})
        self.assertEqual(status, 400)
        self.assertIn("nothing was changed", out["error"]["message"])
        self.assertEqual(self.engine("acme-hana", "/health")[0], 200)  # the running engine is untouched


if __name__ == "__main__":
    unittest.main()
