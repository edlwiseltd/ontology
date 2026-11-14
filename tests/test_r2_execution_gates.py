"""R2 increment 1: execution gates. A use case's lifecycle stage governs what its engine executes, at every entry
point, read afresh at every check.

Acceptance criteria (planning/AUTOLOGY_R2_INCREMENT1_EXECUTION_GATES.md):
  G1 in draft no run starts or continues, through any entry point: REST start, a confirmed assistant/MCP
     proposal, resume, manual automation firing, review decision, scheduled automations, deferred retries and
     recovery; reads, ingestion and proposals stay possible
  G2 a stage change applies at once, also when made by another process
  G3 in simulation only `simulated` tools are called: a sandbox or production system is never reached; a step
     whose every tool is refused is not sent at all (no journal intent), the run escalates and the audit chain
     records `step.blocked`
  G4 in pilot `simulated` and `sandbox` tools are called; `production` tools never (decision D15 pending)
  G5 a stale stage or a history that does not verify counts as draft; an unreadable stage fails closed
  G6 tool environments are declared and checked at load; a standalone engine is not governed by stages
"""

import json
import os
import sqlite3
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from autology.adapters import AdapterError, load_tools
from autology.lifecycle import Lifecycle, policy_for
from autology.platform import Platform

from .helpers import ROOT
from .test_r2_use_case_lifecycle import close
from .test_workspaces import EX, TOKENS, Client

AUTO = ROOT / "examples" / "auto_insurance"
BANK = textwrap.dedent('''
    import os
    from autology.tools import ToolResult
    LOG = os.path.join(os.path.dirname(__file__), "calls.log")

    def _paid(env, reference):
        with open(LOG, "a") as f:
            f.write(env + "\\n")
        return ToolResult(updates={"Payment": {"reference": reference}}, message="paid (" + env + ")")

    def production(call):
        return _paid("production", "PROD-1")

    def sandbox(call):
        return _paid("sandbox", "SBX-1")
''')


def gated_config(environments=("production", "sandbox", "simulated"), configure=None):
    """The motor-claims use case whose payment capability is served by a production bank, a sandbox bank and a
    simulated one (decision table), in that order of preference."""
    folder = Path(tempfile.mkdtemp())
    module = "gate_bank_" + folder.name.replace("-", "_")  # one module per folder: imports are cached
    (folder / f"{module}.py").write_text(BANK)
    tools = json.loads((AUTO / "tools.json").read_text())
    tools["tools"] = [t for t in tools["tools"] if t["name"] != "payments"]
    bank = {"production": {"name": "bank_live", "capability": "payments.pay", "type": "python",
                           "target": f"{module}:production", "environment": "production", "priority": 3},
            "sandbox": {"name": "bank_sandbox", "capability": "payments.pay", "type": "python",
                        "target": f"{module}:sandbox", "environment": "sandbox", "priority": 2},
            "simulated": {"name": "bank_simulated", "capability": "payments.pay", "type": "table", "priority": 1,
                          "rows": [{"updates": {"Payment": {"reference": "SIM-1"}}, "message": "payment simulated"}]}}
    tools["tools"] += [bank[e] for e in environments]
    (folder / "tools.json").write_text(json.dumps(tools))
    cfg = json.loads((AUTO / "server.json").read_text())
    cfg["ontology"], cfg["data"] = str(AUTO / "ontology.json"), str(AUTO / "data.json")
    cfg["agents"]["claims"]["tools"] = str(folder / "tools.json")
    cfg.pop("pipelines")
    if configure:
        configure(cfg)
    (folder / "server.json").write_text(json.dumps(cfg))
    return folder


def bank_calls(folder):
    log = folder / "calls.log"
    return log.read_text().split() if log.exists() else []


class GateBase(unittest.TestCase):
    environments = ("production", "sandbox", "simulated")

    def setUp(self):
        os.environ.update(TOKENS)
        self.folder = gated_config(self.environments, getattr(self, "configure", None))
        spec = json.loads((EX / "platform.json").read_text())
        spec["data_dir"] = tempfile.mkdtemp()
        spec["workspaces"]["acme"]["use_cases"]["claims"]["config"] = str(self.folder / "server.json")
        self.pf = Platform(spec, EX)
        self.c = Client(self.pf)
        self.uc = self.pf.workspaces["acme"].use_cases["claims"]
        self.svc = self.uc.service

    def tearDown(self):
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)

    def set_stage(self, stage, reason="test"):
        """Move through the API when the checks allow it; record directly otherwise (test set-up only)."""
        current = self.pf.stage_of(self.uc)["stage"]
        self.pf.lifecycle.append("acme", "claims", current, stage, "operator@test", reason,
                                 self.svc.ontology.fingerprint, [])

    def call(self, method, path, token="acme-hana", body=None):
        return self.c.call(method, "/w/acme/u/claims/api" + path, token, body)

    def start(self, root="CL-1", token="acme-hana"):
        return self.call("POST", "/runs", token, {"case_template": "claim_case", "root": root})


class DraftTests(GateBase):
    def test_no_run_starts_or_continues_in_draft_through_any_entry_point(self):  # G1
        status, out = self.start()
        self.assertEqual(status, 409)
        self.assertIn("in draft", out["error"])
        self.assertEqual(self.svc.store.list_runs(limit=10), [])
        # a proposal (from the assistant or an MCP client) can be recorded, but confirming it runs nothing
        hana = self.svc.authenticate("Bearer acme-hana")
        proposal = self.svc.create_proposal(hana, {"agent": "claims", "goal": "settle_claim",
                                                   "case_template": "claim_case", "root": "CL-1"})
        status, _ = self.call("POST", f"/proposals/{proposal['proposal_id']}/decision", body={"confirm": True})
        self.assertEqual(status, 409)
        self.assertEqual(self.svc.store.get_proposal(proposal["proposal_id"])["status"], "pending")
        # firing an automation by hand
        self.assertEqual(self.call("POST", "/automations/settle_new_claims/run", body={"instance": "CL-1"})[0], 409)
        # reads still work
        self.assertEqual(self.call("GET", "/objects/CL-1")[0], 200)
        self.assertEqual(self.svc.store.list_runs(limit=10), [])
        self.assertEqual(bank_calls(self.folder), [])

    def test_a_run_waiting_for_review_does_not_continue_once_back_in_draft(self):  # G1, G2
        self.set_stage("simulation")
        status, run = self.start("CL-2")  # needs an investigator's review
        self.assertEqual((status, run["status"]), (200, "awaiting_review"))
        self.set_stage("draft", "rework")
        status, out = self.call("POST", f"/reviews/{run['pending_review']}/decision", "acme-ivan",
                                {"approved": True})
        self.assertEqual(status, 409)
        self.assertEqual(self.svc.store.get_review(run["pending_review"])["status"], "pending")
        self.assertEqual(self.call("POST", f"/runs/{run['run_id']}/resume")[0], 409)
        self.set_stage("simulation", "back")
        status, out = self.call("POST", f"/reviews/{run['pending_review']}/decision", "acme-ivan",
                                {"approved": True})
        self.assertEqual(status, 200)

    def test_scheduled_work_waits_while_in_draft(self):  # G1
        status, _ = self.call("POST", "/objects", "acme-ada", {
            "type": "Claim", "id": "CL-NEW", "attributes": {"amount": 500, "status": "reported"}})
        self.assertEqual(status, 200)
        out = self.svc.tick()
        self.assertEqual((out["firings"], out["resumed"]), ([], []))
        self.assertIn("in draft", out["paused"])
        self.assertEqual(self.svc.store.list_runs(limit=10), [])
        self.assertEqual(self.svc.recover(), [])
        self.assertFalse(self.svc.health()["runs_allowed"])

    def test_a_stage_change_from_another_process_applies_at_once(self):  # G2
        other = Lifecycle(self.pf.lifecycle.path, lambda ws: self.pf.lifecycle._key_for(ws))  # another process
        other.append("acme", "claims", "draft", "simulation", "ada@acme", "elsewhere", self.svc.ontology.fingerprint,
                     [])
        self.assertEqual(self.start()[1]["status"], "completed")
        other.append("acme", "claims", "simulation", "draft", "ada@acme", "stop", self.svc.ontology.fingerprint, [])
        self.assertEqual(self.start("CL-3")[0], 409)
        other.close()


class SimulationTests(GateBase):
    def test_only_simulated_systems_are_reached_in_simulation(self):  # G3
        self.set_stage("simulation")
        status, run = self.start()
        self.assertEqual((status, run["status"]), (200, "completed"))
        self.assertEqual(bank_calls(self.folder), [])  # neither the production nor the sandbox bank
        calls = self.svc.store.list_calls()
        self.assertEqual({c["tool"] for c in calls if c["action"] == "pay_claim"}, {"bank_simulated"})
        self.assertEqual(self.svc.health()["tool_environments"], ["simulated"])


class SimulationWithoutStubTests(GateBase):
    environments = ("production", "sandbox")

    def test_a_step_with_no_allowed_system_is_not_sent_and_the_run_escalates(self):  # G3
        self.set_stage("simulation")
        status, run = self.start()
        self.assertEqual((status, run["status"]), (200, "escalated"))
        self.assertIn("nothing was sent", run["escalation"]["reason"])
        self.assertEqual(bank_calls(self.folder), [])
        self.assertFalse([c for c in self.svc.store.list_calls() if c["action"] == "pay_claim"])  # no intent
        blocked = [e for e in self.svc.store.audit_events(event="step.blocked")]
        self.assertEqual(len(blocked), 1)
        self.assertIn("does not allow", blocked[0]["data"]["reason"])
        self.assertTrue(self.svc.store.verify_audit(run["run_id"]))


class PilotTests(GateBase):
    def test_pilot_reaches_the_sandbox_and_never_production(self):  # G4
        self.set_stage("simulation")
        self.set_stage("pilot")
        status, run = self.start()
        self.assertEqual((status, run["status"]), (200, "completed"))
        self.assertEqual(bank_calls(self.folder), ["sandbox"])
        self.assertEqual(self.svc.health()["tool_environments"], ["sandbox", "simulated"])
        self.assertIsNone(policy_for("pilot")["refusal"])
        self.assertNotIn("production", policy_for("pilot")["environments"])


class EffectiveStageTests(GateBase):
    def test_a_stale_stage_counts_as_draft(self):  # G5
        self.pf.lifecycle.append("acme", "claims", "draft", "simulation", "ada@acme", "old configuration",
                                 "another-fingerprint", [])
        view = self.pf.use_case_view(self.uc, self.pf.workspaces["acme"].members["ada"])
        self.assertEqual((view["stage"], view["stale"], view["effective_stage"]), ("simulation", True, "draft"))
        self.assertEqual(self.start()[0], 409)

    def test_an_edited_history_counts_as_draft(self):  # G5
        self.set_stage("simulation")
        self.assertEqual(self.start()[1]["status"], "completed")
        db = sqlite3.connect(self.pf.lifecycle.path)
        db.execute("UPDATE stage_events SET to_stage='pilot' WHERE use_case='claims'")
        db.commit()
        db.close()
        self.assertEqual(self.start("CL-3")[0], 409)

    def test_an_unreadable_stage_fails_closed(self):  # G5
        self.set_stage("simulation")
        with mock.patch.object(self.pf, "effective_stage", side_effect=RuntimeError("disk")):
            self.svc.stage_gate = lambda: self.pf.effective_stage(self.uc)
            self.assertEqual(self.start()[0], 409)
        self.assertEqual(policy_for("anything-else")["stage"], "draft")


class Recorder:
    """A local HTTP endpoint standing for an outside system: it records what reaches it."""

    def __init__(self, answer=None):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        hits = self.hits = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):  # noqa: N802
                hits.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                data = json.dumps(answer or {}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class OutboundIntegrationTests(GateBase):
    """Webhooks and HTTP approvers reach outside systems too: the stage governs them like tools (G3, G4)."""

    def setUp(self):
        self.hooks = {env: Recorder() for env in ("sandbox", "production")}
        self.approver = Recorder({"approved": True, "reviewer": "siu-desk"})
        super().setUp()

    def tearDown(self):
        super().tearDown()
        for r in list(self.hooks.values()) + [self.approver]:
            r.close()

    def configure(self, cfg):
        cfg["webhooks"] = [{"url": r.url, "kinds": ["proposal", "review"], "environment": env}
                           for env, r in self.hooks.items()]
        cfg["agents"]["claims"]["approver"] = {"type": "http", "url": self.approver.url, "environment": "sandbox"}

    def propose(self):
        hana = self.svc.authenticate("Bearer acme-hana")
        self.svc.create_proposal(hana, {"agent": "claims", "goal": "settle_claim", "case_template": "claim_case",
                                        "root": "CL-1"})
        for t in self.svc.deliveries:
            t.join(5)

    def test_nothing_leaves_in_draft_or_simulation_and_only_the_sandbox_in_pilot(self):
        self.propose()  # draft
        self.set_stage("simulation")
        self.propose()
        status, run = self.start("CL-2")  # needs a review: the HTTP approver is a sandbox system
        self.assertEqual(status, 200)
        self.assertEqual(self.approver.hits, [])  # the review request was not sent
        self.assertEqual(run["status"], "blocked")  # declined, fail closed: the approval cannot happen
        self.assertIn("review request not sent", run["escalation"]["details"][0])
        reviews = [e for e in self.svc.store.load_run(run["run_id"]).audit if e.event == "review"]
        self.assertEqual((reviews[0].data["approved"], reviews[0].data["reviewer"]), (False, "autology"))
        self.assertEqual((self.hooks["sandbox"].hits, self.hooks["production"].hits), ([], []))
        self.set_stage("pilot")
        self.propose()
        self.assertEqual((len(self.hooks["sandbox"].hits), self.hooks["production"].hits), (1, []))
        self.start("CL-3")
        self.assertEqual(self.hooks["production"].hits, [])  # never, in any stage
        self.assertEqual(len(self.svc.store.list_notifications(limit=50)) > 0, True)  # still in the inbox


class DeclarationTests(unittest.TestCase):
    def test_tool_environments_are_declared_and_checked(self):  # G6
        reg = load_tools({"tools": [{"name": "t", "capability": "c", "type": "table", "rows": [{}]}]})
        self.assertEqual([t.environment for t in reg], ["simulated"])
        reg = load_tools({"tools": [{"name": "h", "capability": "c", "type": "http", "url": "https://x.invalid"}]})
        self.assertEqual([t.environment for t in reg], ["production"])  # default: anything reachable is real
        reg = load_tools({"tools": [{"name": "h", "capability": "c", "type": "http", "url": "https://x.invalid",
                                     "environment": "sandbox"}]})
        self.assertEqual([t.environment for t in reg], ["sandbox"])
        for bad in ({"name": "t", "capability": "c", "type": "table", "environment": "production"},
                    {"name": "h", "capability": "c", "type": "http", "url": "https://x", "environment": "live"}):
            with self.assertRaises(AdapterError):
                load_tools({"tools": [bad]})

    def test_a_standalone_engine_is_not_governed_by_stages(self):  # G6
        from autology.server import AutologyService

        svc = AutologyService({**json.loads((AUTO / "server.json").read_text()), "store": ":memory:", "users": []}, AUTO)
        self.assertIsNone(svc.execution_policy())
        self.assertNotIn("stage", svc.health())
        svc.close()


if __name__ == "__main__":
    unittest.main()
