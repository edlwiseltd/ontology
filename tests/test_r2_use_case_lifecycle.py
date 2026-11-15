"""R2 slice: use-case management and the Draft -> Simulation -> Pilot lifecycle, with server-side checks.

Acceptance criteria (planning/AUTOLOGY_R2_SLICE_REPORT.md):
  L1 every use case starts in draft; its stage is a platform record its own configuration cannot set
  L2 stages advance one step at a time; production is refused from every stage and every caller
  L3 every forward move is checked on the server at the moment of the move; a failed check refuses it
  L4 moving back is always possible, with a reason; every move names its author and reason
  L5 only workspace administrators move stages or create use cases; other workspaces get the same 404
  L6 the stage history is tamper-evident and keyed per workspace
  L7 use cases are created only from the operator's approved templates, inside the workspace's credential scope,
     and come back after a restart
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autology.lifecycle import Lifecycle
from autology.platform import Platform, PlatformError

from .helpers import ROOT
from .test_workspaces import EX, TOKENS, Client

TEMPLATES = {"claims-starter": {"name": "Motor claims starter", "description": "Settle motor claims",
                                "config": "../auto_insurance/server.json"}}
STAGE = "/platform/workspaces/acme/use-cases/claims/stage"
CHECKS = "/platform/workspaces/acme/use-cases/claims/checks?to="


def make_platform(data_dir=None, **changes):
    os.environ.update(TOKENS)
    spec = json.loads((EX / "platform.json").read_text())
    spec["data_dir"] = data_dir or tempfile.mkdtemp()
    spec["templates"] = TEMPLATES
    spec.update(changes)
    return Platform(spec, EX)


def template_config(**changes):
    """A copy of the motor-claims configuration as a template file outside the examples folder."""
    cfg = json.loads((ROOT / "examples" / "auto_insurance" / "server.json").read_text())
    folder = Path(tempfile.mkdtemp())
    for key in ("ontology", "data"):
        cfg[key] = str(ROOT / "examples" / "auto_insurance" / cfg[key])
    cfg["agents"]["claims"]["tools"] = str(ROOT / "examples" / "auto_insurance" / "tools.json")
    cfg.pop("pipelines")
    cfg.update(changes)
    (folder / "server.json").write_text(json.dumps(cfg))
    return str(folder / "server.json")


def close(pf):
    for svc in pf.services():
        svc.close()
    pf.lifecycle.close()
    pf.releases.close()
    pf.admin.close()
    pf.tenancy.close()
    pf.log.close()


class LifecycleBase(unittest.TestCase):
    def setUp(self):
        self.pf = make_platform()
        self.c = Client(self.pf)

    def tearDown(self):
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)

    def move(self, to, reason="test", token="acme-ada", path=STAGE):
        return self.c.call("POST", path, token, {"to": to, "reason": reason})

    def complete_a_run(self):
        status, run = self.c.call("POST", "/w/acme/u/claims/api/runs", "acme-hana",
                                  {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual((status, run["status"]), (200, "completed"))
        return run

    def release(self, uc="claims"):
        """Four eyes on what goes to pilot (REL-1a, D11): ada proposes and activates, maria (a named release
        approver) approves the configuration the engine runs."""
        base = f"/platform/v1/workspaces/acme/use-cases/{uc}/releases"
        status, rel = self.c.call("POST", base, "acme-ada", {"note": "configuration for the pilot"})
        self.assertEqual(status, 201, rel)
        n = rel["number"]
        self.assertEqual(self.c.call("POST", f"{base}/{n}/approve", "acme-maria", {"reason": "reviewed"})[0], 200)
        status, out = self.c.call("POST", f"{base}/{n}/activate", "acme-ada", {"reason": "go"})
        self.assertEqual(status, 200, out)
        return out


class StageTests(LifecycleBase):
    def test_every_use_case_starts_in_draft_and_me_shows_the_stage(self):  # L1
        _, me = self.c.call("GET", "/platform/me", "acme-ada")
        self.assertEqual({u["id"]: u["stage"] for u in me["use_cases"]}, {"claims": "draft", "orders": "draft"})
        status, uc = self.c.call("GET", "/platform/workspaces/acme/use-cases/claims", "acme-hana")
        self.assertEqual((status, uc["stage"], uc["history"], uc["stale"]), (200, "draft", [], False))
        self.assertEqual(uc["stages"], ["draft", "simulation", "pilot", "production"])
        self.assertEqual(uc["fingerprint"], self.pf.workspaces["acme"].use_cases["claims"].service.ontology.fingerprint)

    def test_a_use_case_configuration_cannot_set_its_own_stage(self):  # L1
        cfg = json.loads((ROOT / "examples" / "auto_insurance" / "server.json").read_text())
        self.assertNotIn("stage", cfg)
        spec = json.loads((EX / "platform.json").read_text())
        spec["workspaces"]["acme"]["use_cases"]["claims"]["stage"] = "pilot"  # ignored: not a configuration key
        pf = Platform({**spec, "data_dir": tempfile.mkdtemp()}, EX)
        try:
            self.assertEqual(pf.stage_of(pf.workspaces["acme"].use_cases["claims"])["stage"], "draft")
        finally:
            close(pf)

    def test_stages_advance_one_step_at_a_time_and_production_is_always_refused(self):  # L2
        self.assertEqual(self.move("pilot"), (409, {"error": "stages advance one at a time: from draft the next is "
                                                             "simulation"}))
        self.assertEqual(self.move("production")[0], 403)
        self.assertEqual(self.move("simulation")[0], 200)
        self.assertEqual(self.move("simulation")[0], 409)  # already there
        self.assertEqual(self.move("unknown-stage")[0], 400)
        self.complete_a_run()
        self.release()
        self.assertEqual(self.move("pilot")[0], 200)
        for token in ("acme-ada", "acme-hana"):
            status, out = self.move("production", token=token)
            self.assertEqual(status, 403)
        self.assertIn("not authorised", self.move("production")[1]["error"])
        self.assertEqual(self.c.call("GET", CHECKS + "production", "acme-ada")[0], 403)
        _, uc = self.c.call("GET", "/platform/workspaces/acme/use-cases/claims", "acme-ada")
        self.assertEqual(uc["stage"], "pilot")

    def test_simulation_requires_audit_chains_signed_with_the_workspace_key(self):  # L3
        # only the engine's demo mode starts without an audit key; such a use case cannot leave draft
        demo = template_config(simulation=True)
        with mock.patch.dict(os.environ):
            os.environ.pop("AUTOLOGY_AUDIT_KEY", None)
            spec = json.loads((EX / "platform.json").read_text())
            spec["workspaces"] = {"acme": {**spec["workspaces"]["acme"],
                                           "use_cases": {"claims": {"name": "Demo", "config": demo}}}}
            for m in spec["workspaces"]["acme"]["members"]:
                m.get("use_cases", {}).pop("orders", None)
            pf = Platform({**spec, "data_dir": tempfile.mkdtemp()}, EX)
            c = Client(pf)
            try:
                _, checks = c.call("GET", CHECKS + "simulation", "acme-ada")
                self.assertFalse(checks["allowed"])
                self.assertEqual([x["id"] for x in checks["checks"] if not x["passed"]], ["audit_key"])
                status, out = c.call("POST", STAGE, "acme-ada", {"to": "simulation", "reason": "try"})
                self.assertEqual(status, 409)
                self.assertIn("no audit key", out["error"])
                self.assertEqual([x["id"] for x in out["checks"] if not x["passed"]], ["audit_key"])
                self.assertEqual(pf.stage_of(pf.workspaces["acme"].use_cases["claims"])["stage"], "draft")
            finally:
                c.server.shutdown()
                c.server.server_close()
                close(pf)

    def test_pilot_is_refused_while_the_engine_runs_in_its_own_simulation_mode(self):  # L3
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)
        self.pf = make_platform(templates={"demo": {"config": template_config(simulation=True)}})
        self.c = Client(self.pf)
        self.c.call("POST", "/platform/workspaces/acme/use-cases", "acme-ada", {"id": "demo", "template": "demo"})
        self.assertEqual(self.move("simulation", path="/platform/workspaces/acme/use-cases/demo/stage")[0], 200)
        _, dry = self.c.call("GET", "/platform/workspaces/acme/use-cases/demo/checks?to=pilot", "acme-ada")
        failed = [c["id"] for c in dry["checks"] if not c["passed"]]
        self.assertIn("engine_simulation_mode_off", failed)

    def test_pilot_needs_a_run_completed_after_entering_simulation(self):  # L3
        self.assertEqual(self.move("simulation", "first try")[0], 200)
        self.complete_a_run()
        self.assertEqual(self.move("draft", "rework")[0], 200)  # leaving simulation resets the evidence
        self.assertEqual(self.move("simulation", "exercise with test claims")[0], 200)
        self.release()
        status, out = self.move("pilot")
        self.assertEqual(status, 409)
        self.assertEqual([c["id"] for c in out["checks"] if not c["passed"]], ["simulated_run_completed"])
        self.complete_a_run()
        _, dry = self.c.call("GET", CHECKS + "pilot", "acme-hana")
        self.assertTrue(dry["allowed"])
        self.assertEqual({c["id"] for c in dry["checks"]}, {
            "configuration_valid", "audit_key", "no_quarantined_records", "engine_simulation_mode_off",
            "reviewers_assigned", "audit_chains_verify",
            "external_calls_reconciled", "simulated_run_completed", "configuration_unchanged_since_simulation",
            "approved_release_active"})
        status, out = self.move("pilot", "supervised pilot on test data")
        self.assertEqual((status, out["from"], out["to"], out["use_case"]["stage"]), (200, "simulation", "pilot", "pilot"))
        history = out["use_case"]["history"]
        self.assertEqual([(h["from_stage"], h["to_stage"], h["by"], h["reason"]) for h in history], [
            ("draft", "simulation", "ada@acme", "first try"), ("simulation", "draft", "ada@acme", "rework"),
            ("draft", "simulation", "ada@acme", "exercise with test claims"),
            ("simulation", "pilot", "ada@acme", "supervised pilot on test data")])
        self.assertTrue(all(c["passed"] for c in history[3]["checks"]))

    def test_pilot_is_refused_while_an_external_call_waits_for_reconciliation(self):  # L3
        self.move("simulation")
        self.complete_a_run()
        self.release()
        store = self.pf.workspaces["acme"].use_cases["claims"].service.store
        store.record_intent("k-1", run_key="rk", case_id="c", root="CL-9", agent="claims", action="pay_claim",
                            tool="payments", inputs_digest="d")
        store.record_call_result("k-1", "unknown")
        status, out = self.move("pilot")
        self.assertEqual(status, 409)
        self.assertEqual([c["id"] for c in out["checks"] if not c["passed"]], ["external_calls_reconciled"])

    def test_pilot_is_refused_when_an_audit_chain_does_not_verify(self):  # L3
        self.move("simulation")
        run = self.complete_a_run()
        svc = self.pf.workspaces["acme"].use_cases["claims"].service
        db = sqlite3.connect(svc.store.path)
        db.execute("DROP TRIGGER audit_no_update")  # someone with file access edits the history
        db.execute("UPDATE audit SET data='{}' WHERE run_id=? AND seq=1", (run["run_id"],))
        db.commit()
        db.close()
        status, out = self.move("pilot")
        self.assertEqual(status, 409)
        self.assertIn("audit_chains_verify", [c["id"] for c in out["checks"] if not c["passed"]])

    def test_moving_back_needs_a_reason_but_no_checks(self):  # L4
        self.move("simulation")
        self.assertEqual(self.move("draft", reason="  ")[0], 400)
        self.assertEqual(self.move("draft", reason="")[0], 400)
        status, out = self.move("draft", reason="ontology rework")
        self.assertEqual((status, out["forward"], out["checks"]), (200, False, []))

    def test_only_workspace_admins_move_stages_and_other_workspaces_get_404(self):  # L5
        self.assertEqual(self.move("simulation", token="acme-hana"),
                         (403, {"error": "workspace administrators only"}))
        self.assertEqual(self.c.call("GET", CHECKS + "simulation", "acme-hana")[0], 200)  # granted: may look
        not_found = (404, {"error": "not found"})
        self.assertEqual(self.move("simulation", token="nw-nadia"), not_found)  # another workspace's admin
        self.assertEqual(self.move("simulation", token="acme-hana",
                                   path="/platform/workspaces/acme/use-cases/orders/stage"), not_found)
        for path in ("/platform/workspaces/northwind/use-cases", "/platform/workspaces/nowhere/use-cases",
                     "/platform/workspaces/northwind/use-cases/claims", "/platform/workspaces/acme/use-cases/nope",
                     "/platform/workspaces/acme/use-cases/claims/other", "/platform/nothing"):
            self.assertEqual(self.c.call("GET", path, "acme-ada"), not_found, path)
        self.assertEqual(self.c.call("GET", "/platform/workspaces/acme/use-cases", None)[0], 401)
        _, hana = self.c.call("GET", "/platform/workspaces/acme/use-cases", "acme-hana")
        self.assertEqual([u["id"] for u in hana["items"]], ["claims"])
        refused = {r["target"] for r in self.pf.log.access_log(limit=50) if r["status"] in (403, 404)}
        self.assertIn(f"POST {STAGE}", refused)

    def test_an_edited_stage_history_is_detected_and_blocks_forward_moves(self):  # L6
        self.move("simulation")
        db = sqlite3.connect(self.pf.lifecycle.path)
        db.execute("UPDATE stage_events SET reason='edited' WHERE use_case='claims'")
        db.commit()
        db.close()
        _, uc = self.c.call("GET", "/platform/workspaces/acme/use-cases/claims", "acme-ada")
        self.assertEqual(uc["stage"], "draft")
        self.assertIn("changed outside Autology", uc["integrity_problem"])
        self.assertEqual(self.move("simulation")[0], 409)

    def test_a_history_entry_does_not_verify_in_another_workspace(self):  # L6
        self.move("simulation")
        db = sqlite3.connect(self.pf.lifecycle.path)
        db.execute("INSERT INTO stage_events SELECT 'northwind', use_case, seq, from_stage, to_stage, by, reason, "
                   "fingerprint, checks, at, prev, mac FROM stage_events WHERE workspace='acme'")
        db.commit()
        db.close()
        nw = self.pf.stage_of(self.pf.workspaces["northwind"].use_cases["claims"])
        self.assertEqual(nw["stage"], "draft")
        self.assertIsNotNone(nw["integrity_problem"])

    def test_a_stage_is_stale_when_the_configuration_changes(self):  # L6
        lc = Lifecycle(Path(tempfile.mkdtemp()) / "lifecycle.db", lambda ws: b"k")
        lc.append("acme", "x", "draft", "simulation", "ada@acme", "r", "fp-1", [])
        self.assertFalse(lc.status("acme", "x", "fp-1")["stale"])
        self.assertTrue(lc.status("acme", "x", "fp-2")["stale"])
        lc.close()

    def test_stages_survive_a_restart(self):  # L6
        self.move("simulation", "kept")
        data_dir = str(self.pf.data_dir)
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)
        self.pf = make_platform(data_dir)
        self.c = Client(self.pf)
        st = self.pf.stage_of(self.pf.workspaces["acme"].use_cases["claims"])
        self.assertEqual((st["stage"], st["history"][0]["reason"], st["integrity_problem"]), ("simulation", "kept", None))


class UseCaseManagementTests(LifecycleBase):
    def create(self, body, token="acme-ada", ws="acme"):
        return self.c.call("POST", f"/platform/workspaces/{ws}/use-cases", token, body)

    def test_an_admin_creates_a_use_case_from_an_approved_template(self):  # L7
        status, uc = self.create({"id": "claims-pilot", "name": "Claims pilot", "template": "claims-starter"})
        self.assertEqual((status, uc["stage"], uc["origin"], uc["template"], uc["history"]),
                         (201, "draft", "template", "claims-starter", []))
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims-pilot/api/health", "acme-ada")[0], 200)
        # nobody else was granted it: identical 404 for members and other workspaces
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims-pilot/api/health", "acme-hana")[0], 404)
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims-pilot/api/health", "nw-nadia")[0], 404)
        _, ada = self.c.call("GET", "/platform/me", "acme-ada")
        self.assertIn("claims-pilot", [u["id"] for u in ada["use_cases"]])
        _, nw = self.c.call("GET", "/platform/workspaces/northwind/use-cases", "nw-nadia")
        self.assertNotIn("claims-pilot", [u["id"] for u in nw["items"]])
        home = self.pf.data_dir / "acme" / "claims-pilot"
        self.assertTrue((home / "autology.db").exists())
        # its data is its own: an object written in the original claims use case is not there
        self.c.call("POST", "/w/acme/u/claims/api/objects", "acme-ada",
                    {"type": "Claim", "id": "CL-ONLY-HERE", "attributes": {"amount": 1, "status": "reported"}})
        self.assertEqual(self.c.call("GET", "/w/acme/u/claims-pilot/api/objects/CL-ONLY-HERE", "acme-ada")[0], 404)

    def test_a_created_use_case_cannot_reach_pilot_until_reviewers_are_named(self):  # L3, L7
        self.create({"id": "claims-pilot", "name": "Claims pilot", "template": "claims-starter"})
        path = "/platform/workspaces/acme/use-cases/claims-pilot/stage"
        self.assertEqual(self.move("simulation", path=path)[0], 200)
        _, dry = self.c.call("GET", "/platform/workspaces/acme/use-cases/claims-pilot/checks?to=pilot", "acme-ada")
        self.assertIn("reviewers_assigned", [c["id"] for c in dry["checks"] if not c["passed"]])

    def test_creation_is_refused_for_non_admins_other_workspaces_and_bad_input(self):  # L5, L7
        good = {"id": "x1", "name": "X", "template": "claims-starter"}
        self.assertEqual(self.create(good, token="acme-hana")[0], 403)
        self.assertEqual(self.create(good, token="nw-nadia"), (404, {"error": "not found"}))
        for body, status in (({**good, "id": "Bad_Id"}, 400), ({**good, "id": "../x"}, 400), ({**good, "id": 7}, 400),
                             ({**good, "template": "nope"}, 400), ({**good, "name": "n" * 121}, 400),
                             ({**good, "id": "claims"}, 409)):
            self.assertEqual(self.create(body)[0], status, body)
        self.assertEqual(self.create(good)[0], 201)
        self.assertEqual(self.create(good)[0], 409)
        self.assertEqual(self.c.call("POST", "/platform/workspaces/acme/use-cases", "acme-ada", [1])[0], 400)
        self.assertEqual(len(self.pf.lifecycle.created("acme")), 1)

    def test_an_id_used_before_is_never_given_to_a_new_use_case(self):  # L7
        old = self.pf.data_dir / "acme" / "retired"
        old.mkdir(parents=True)
        (old / "autology.db").write_text("earlier data")
        status, out = self.create({"id": "retired", "name": "R", "template": "claims-starter"})
        self.assertEqual(status, 409)
        self.assertIn("used before", out["error"])

    def test_templates_are_for_admins_and_do_not_reveal_paths(self):
        self.assertEqual(self.c.call("GET", "/platform/templates", "acme-hana")[0], 403)
        _, out = self.c.call("GET", "/platform/templates", "acme-ada")
        self.assertEqual(out["items"], [{"id": "claims-starter", "name": "Motor claims starter",
                                         "description": "Settle motor claims"}])

    def test_a_template_cannot_bring_another_workspace_credentials(self):  # L7 (ISO-4 scope applies)
        leaky = template_config(notes="${NORTHWIND_SECRET}")
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)
        self.pf = make_platform(templates={**TEMPLATES, "leaky": {"config": leaky}})
        self.c = Client(self.pf)
        status, out = self.create({"id": "leak", "name": "Leak", "template": "leaky"})
        self.assertEqual(status, 400)
        self.assertIn("NORTHWIND_SECRET", out["error"])
        self.assertEqual((self.pf.lifecycle.created("acme"), "leak" in self.pf.workspaces["acme"].use_cases),
                         ([], False))

    def test_created_use_cases_and_their_stages_come_back_after_a_restart(self):  # L7
        self.create({"id": "claims-pilot", "name": "Claims pilot", "template": "claims-starter"})
        self.move("simulation", path="/platform/workspaces/acme/use-cases/claims-pilot/stage")
        data_dir = str(self.pf.data_dir)
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)
        self.pf = make_platform(data_dir)
        self.c = Client(self.pf)
        uc = self.pf.workspaces["acme"].use_cases["claims-pilot"]
        self.assertEqual((uc.origin, uc.template, uc.name, self.pf.stage_of(uc)["stage"]),
                         ("template", "claims-starter", "Claims pilot", "simulation"))
        # a template removed from the configuration while use cases depend on it stops the platform loudly
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)
        with self.assertRaisesRegex(PlatformError, "no longer in the platform configuration"):
            make_platform(data_dir, templates={})
        self.pf = make_platform()
        self.c = Client(self.pf)

    def test_invalid_templates_are_refused_at_start(self):
        for templates in ({"Bad": {"config": "x.json"}}, {"t": {"config": "missing.json"}}, {"t": "x"}):
            with self.assertRaises(PlatformError):
                make_platform(templates=templates)

    def test_a_use_case_created_while_running_gets_its_scheduler(self):
        self.pf.start_background()
        before = len(self.pf._stops)
        self.create({"id": "live", "name": "Live", "template": "claims-starter"})
        self.assertEqual(len(self.pf._stops), before + 1)
        self.pf.stop_background()
        self.assertEqual((self.pf._stops, self.pf.running), ([], False))


if __name__ == "__main__":
    unittest.main()
