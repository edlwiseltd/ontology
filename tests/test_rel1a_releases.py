"""REL-1a: immutable, content-addressed releases of a use case's governing configuration (master directive V2).

  R1 the configuration fingerprint is content-addressed: the same configuration has the same fingerprint in every
     workspace; a governing change (a tool declaration) changes it; deployment details (store, members) do not
  R2 a release is proposed by a workspace administrator who is a person; it is immutable (the database refuses
     updates and deletes) and the same configuration cannot be proposed twice
  R3 approval is independent (D11): never the proposer, never a service identity, only a person with release
     authority (an administrator or a named release approver, who may be an external approver without other
     grants); the approval is bound to the release's fingerprint and can be revoked until activation
  R4 activation needs an approval and is accepted only when the engine runs exactly the released configuration
  R5 drift: once a release is active, an engine running another configuration counts as draft (nothing runs)
     until a person activates the matching approved release; pilot needs an approved active release
  R6 rollback: re-activating an earlier approved release is recorded as a rollback
  R7 a run started on one configuration never continues on another: its review decision is refused and the
     activation reports it
  R8 a release history or snapshot changed outside Autology is detected and the use case counts as draft
  R9 approving a configuration release authorises no business action: a draft use case with an active release
     still runs nothing
  R10 isolation: another workspace gets the same 404 as for any unknown use case
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autology.platform import Platform
from autology.releases import ReleaseError, configuration_snapshot, fingerprint_of

from .helpers import ROOT
from .test_r2_use_case_lifecycle import close
from .test_workspaces import Client, EX, TOKENS, data_admins

AUTO = ROOT / "examples" / "auto_insurance"
REL = "/platform/v1/workspaces/acme/use-cases/claims/releases"


class ReleaseBase(unittest.TestCase):
    def setUp(self):
        os.environ.update(TOKENS)
        os.environ["ACME_TOKEN_BOT"] = "acme-bot"
        os.environ["ACME_TOKEN_QUINN"] = "acme-quinn"
        self.addCleanup(os.environ.pop, "ACME_TOKEN_BOT", None)
        self.addCleanup(os.environ.pop, "ACME_TOKEN_QUINN", None)
        self.config_dir = Path(tempfile.mkdtemp()) / "claims"
        shutil.copytree(AUTO, self.config_dir)
        self.data_dir = tempfile.mkdtemp()
        self.pf, self.c = None, None
        self.start()

    def spec(self):
        spec = data_admins(json.loads((EX / "platform.json").read_text()))
        spec["data_dir"] = self.data_dir
        acme = spec["workspaces"]["acme"]
        acme["use_cases"]["claims"]["config"] = str(self.config_dir / "server.json")
        acme["members"].append({"name": "bot", "kind": "service", "token_env": "ACME_TOKEN_BOT",
                                "use_cases": {"claims": {"permissions": ["read"]}}})
        acme["members"].append({"name": "quinn", "token_env": "ACME_TOKEN_QUINN"})  # an external approver
        acme["release_approvers"] = ["maria", "quinn"]
        return spec

    def start(self):
        self.stop()
        self.pf = Platform(self.spec(), EX)
        self.c = Client(self.pf)
        self.uc = self.pf.workspaces["acme"].use_cases["claims"]
        if self.pf.stage_of(self.uc)["stage"] == "draft" and not self.pf.stage_of(self.uc)["history"]:
            self.pf.lifecycle.move("acme", "claims", self.uc.service, "simulation", "operator@test", "tests")

    def stop(self):
        if self.c:
            self.c.server.shutdown()
            self.c.server.server_close()
        if self.pf:
            close(self.pf)
        self.pf, self.c = None, None

    def tearDown(self):
        self.stop()

    def call(self, method, path, token="acme-ada", body=None):
        return self.c.call(method, path, token, body)

    def propose(self, note="a release"):
        return self.call("POST", REL, body={"note": note})

    def approve(self, n, token="acme-maria"):
        return self.call("POST", f"{REL}/{n}/approve", token, {"reason": "reviewed the configuration"})

    def activate(self, n, token="acme-ada"):
        return self.call("POST", f"{REL}/{n}/activate", token, {"reason": "go"})

    def released(self):
        status, rel = self.propose()
        self.assertEqual(status, 201, rel)
        self.assertEqual(self.approve(rel["number"])[0], 200)
        status, out = self.activate(rel["number"])
        self.assertEqual(status, 200, out)
        return out

    def change_tools(self, cost):
        tools = json.loads((self.config_dir / "tools.json").read_text())
        tools["tools"][0]["cost"] = cost
        (self.config_dir / "tools.json").write_text(json.dumps(tools, indent=1))

    def start_run(self, root="CL-1"):
        return self.call("POST", "/w/acme/u/claims/api/v1/runs", "acme-hana",
                         {"case_template": "claim_case", "root": root})


class FingerprintTests(unittest.TestCase):  # R1
    def test_content_addressed_and_limited_to_what_governs(self):
        cfg = json.loads((AUTO / "server.json").read_text())
        doc = json.loads((AUTO / "ontology.json").read_text())

        def fp(c, base=AUTO):
            return fingerprint_of(configuration_snapshot(c, base, doc, "f", "r"))

        same = fp({**cfg, "store": "/elsewhere/a.db", "users": [{"name": "x"}], "secrets_file": "s", "audit_scope": "w"})
        self.assertEqual(fp(cfg), same)
        self.assertNotEqual(fp(cfg), fp({**cfg, "automation_interval": 1}))
        other = Path(tempfile.mkdtemp())
        shutil.copytree(AUTO, other / "a")
        self.assertEqual(fp(cfg, other / "a"), fp(cfg))
        tools = json.loads((other / "a" / "tools.json").read_text())
        tools["tools"][0]["cost"] = 9
        (other / "a" / "tools.json").write_text(json.dumps(tools))
        self.assertNotEqual(fp(cfg, other / "a"), fp(cfg))


class LifecycleOfAReleaseTests(ReleaseBase):
    def test_propose_is_for_administrators_who_are_people(self):  # R2
        self.assertEqual(self.call("POST", REL, "acme-hana", {"note": "x"})[0], 403)
        self.assertEqual(self.call("POST", REL, "acme-bot", {"note": "x"})[0], 403)
        self.assertEqual(self.call("POST", REL, body={})[0], 400)
        status, rel = self.propose()
        self.assertEqual((status, rel["number"], rel["status"]), (201, 1, "proposed"))
        self.assertEqual(rel["fingerprint"], self.uc.service.configuration_fingerprint)
        self.assertEqual(self.propose()[0], 409)  # the same configuration is already release 1
        db = sqlite3.connect(self.pf.releases.path)
        for sql in ("UPDATE releases SET note='x'", "DELETE FROM releases", "UPDATE release_events SET by='x'",
                    "DELETE FROM release_events"):
            with self.subTest(sql), self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
        db.close()

    def test_approval_is_independent_and_bound_to_the_fingerprint(self):  # R3
        _, rel = self.propose()
        status, out = self.approve(1, "acme-ada")
        self.assertEqual(status, 403)
        self.assertIn("proposer", out["error"]["message"])
        self.assertEqual(self.approve(1, "acme-hana")[0], 403)  # a member without release authority
        self.assertEqual(self.approve(1, "acme-bot")[0], 403)   # a service identity, whatever it is granted
        status, out = self.approve(1, "acme-quinn")              # an external approver with no other grant
        self.assertEqual((status, out["status"], out["approved_by"]), (200, "approved", "quinn@acme"))
        self.assertEqual(self.call("GET", "/platform/v1/workspaces/acme/use-cases/claims", "acme-quinn")[0], 404)
        self.assertEqual(self.approve(1)[0], 409)  # already approved
        _, state = self.call("GET", REL)
        approval = [e for e in state["history"] if e["event"] == "approved"][0]
        self.assertEqual((approval["fingerprint"], approval["by_kind"]), (rel["fingerprint"], "person"))
        status, out = self.call("POST", f"{REL}/1/revoke", "acme-quinn", {"reason": "found an issue"})
        self.assertEqual((status, out["status"]), (200, "proposed"))
        self.assertEqual(self.activate(1)[0], 409)  # no approval any more

    def test_activation_needs_approval_and_exactly_the_running_configuration(self):  # R4
        self.propose()
        status, out = self.activate(1)
        self.assertEqual(status, 409)
        self.assertIn("not approved", out["error"]["message"])
        self.approve(1)
        self.assertEqual(self.activate(1, "acme-maria")[0], 403)  # approvers do not activate: administrators do
        status, out = self.activate(1)
        self.assertEqual((status, out["status"], out["event"]), (200, "active", "activated"))
        self.assertEqual(self.activate(1)[0], 409)
        self.assertEqual(self.call("POST", f"{REL}/1/revoke", "acme-maria", {"reason": "late"})[0], 409)
        _, uc = self.call("GET", "/platform/v1/workspaces/acme/use-cases/claims")
        self.assertEqual((uc["release"]["active"]["number"], uc["release"]["drift"]), (1, False))
        self.assertEqual(uc["configuration"], self.uc.service.configuration_fingerprint)

    def test_drift_stops_execution_until_the_matching_release_is_activated_and_rollback(self):  # R5, R6, R9
        self.released()
        self.assertEqual(self.start_run()[1]["status"], "completed")
        self.stop()
        self.change_tools(0.75)  # someone changes a governing file and restarts
        self.start()
        self.assertTrue(self.pf.release_of(self.uc)["drift"])
        self.assertEqual(self.pf.effective_stage(self.uc), "draft")
        status, out = self.start_run()
        self.assertEqual(status, 409, out)  # nothing runs on an unreleased configuration
        self.assertIn("active release", out["error"]["message"])
        _, checks = self.call("GET", "/platform/v1/workspaces/acme/use-cases/claims/checks?to=pilot")
        failed = [c for c in checks["checks"] if c["id"] == "approved_release_active"][0]
        self.assertFalse(failed["passed"])
        self.assertEqual(self.activate(1)[0], 409)  # release 1 is not what runs
        _, rel2 = self.propose("cheaper fraud engine")
        self.approve(rel2["number"])
        self.assertEqual(self.activate(rel2["number"])[0], 200)
        self.assertEqual(self.start_run()[1]["status"], "completed")
        self.stop()
        self.change_tools(0.5)  # the operator restores release 1's files ...
        self.start()
        self.assertEqual(self.pf.effective_stage(self.uc), "draft")
        status, out = self.activate(1)  # ... and rolls back to it
        self.assertEqual((status, out["event"]), (200, "rolled_back"))
        self.assertEqual(self.pf.effective_stage(self.uc), "simulation")
        # R9: a release approval authorises no business action: back in draft, nothing runs
        self.pf.lifecycle.move("acme", "claims", self.uc.service, "draft", "ada@acme", "pause")
        self.assertEqual(self.start_run()[0], 409)

    def test_a_run_never_continues_on_another_configuration(self):  # R7
        self.released()
        status, run = self.start_run("CL-2")  # waits for an investigator's review
        self.assertEqual((status, run["status"]), (200, "awaiting_review"))
        self.stop()
        self.change_tools(0.75)
        self.start()
        _, rel2 = self.propose("changed while a run waited")
        self.approve(rel2["number"])
        status, out = self.activate(rel2["number"])
        self.assertEqual(status, 200)
        self.assertEqual(out["runs_on_other_configurations_count"], 1)
        self.assertIn(run["run_id"], out["runs_on_other_configurations"])  # ada holds an explicit data grant here
        status, out = self.call("POST", f"/w/acme/u/claims/api/v1/reviews/{run['pending_review']}/decision",
                                "acme-ivan", {"approved": True, "comment": "ok"})
        self.assertEqual(status, 409, out)
        self.assertIn("started on configuration", out["error"]["message"])

    def test_a_changed_history_or_snapshot_is_detected(self):  # R8
        self.released()
        self.assertEqual(self.pf.effective_stage(self.uc), "simulation")
        db = sqlite3.connect(self.pf.releases.path)
        db.execute("DROP TRIGGER releases_immutable_u")
        db.execute("UPDATE releases SET snapshot = replace(snapshot, 'fraud_engine', 'fraud_engin3')")
        db.commit()
        db.close()
        state = self.pf.release_of(self.uc)
        self.assertIn("changed outside Autology", state["integrity_problem"])
        self.assertEqual(self.pf.effective_stage(self.uc), "draft")
        self.assertEqual(self.propose("another")[0], 409)

    def test_isolation(self):  # R10
        self.propose()
        for token in ("nw-nadia", "nw-hana"):
            status, out = self.call("GET", REL, token)
            self.assertEqual(status, 404)
        unknown = self.call("GET", "/platform/v1/workspaces/acme/use-cases/nope/releases")
        self.assertEqual(unknown[0], 404)
        self.assertEqual(self.call("GET", f"{REL}/99")[0], 404)


class RegistryTests(unittest.TestCase):
    def test_reasons_are_required_and_events_are_known(self):
        from autology.releases import ReleaseRegistry

        reg = ReleaseRegistry(Path(tempfile.mkdtemp()) / "r.db", lambda ws: b"k")
        self.addCleanup(reg.close)
        reg.propose("w", "u", {"a": 1}, "p", "n")
        with self.assertRaises(ReleaseError):
            reg.record("w", "u", 1, "approved", "q", "", lambda i, s: None)
        with self.assertRaises(ReleaseError):
            reg.record("w", "u", 1, "proposed", "q", "r", lambda i, s: None)
        with self.assertRaises(ReleaseError):
            reg.record("w", "u", 2, "approved", "q", "r", lambda i, s: None)
        self.assertIsNone(reg.snapshot("w", "u", 9))
        self.assertEqual(reg.snapshot("w", "u", 1), {"a": 1})


if __name__ == "__main__":
    unittest.main()
