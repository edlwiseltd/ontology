"""Vendor-, domain- and process-agnostic operation: model adapters, declarative tools/approvers, saved runs, CLI."""

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from autology import AutoApprover, DecisionContext, Ontology, ToolError, WorkAgent
from autology.__main__ import main as cli
from autology.adapters import (AdapterError, HttpApprover, http_tool, import_target, load_approver, load_reasoner,
                               load_tools)
from autology.agent import ReviewRequest
from autology.persistence import load_runs, result_from_dict, result_to_dict, save_runs
from autology.reasoners import (AnthropicChatModel, FunctionChatModel, LLMReasoner, PlanFollowingReasoner,
                                estimate_cost, register_price)
from autology.tools import ToolCall

from .helpers import EXAMPLE, MFG, MFG_ONTOLOGY, ONTOLOGY_PATH, build_registry, manufacturing_tools as mt, \
    order_case, retail_case


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli([str(a) for a in args])
    return code, out.getvalue(), err.getvalue()


class _Handler(BaseHTTPRequestHandler):
    routes = {}

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        status, reply = self.routes[self.path](body, self.headers)
        self.send_response(status)
        self.end_headers()
        self.wfile.write(reply if isinstance(reply, bytes) else json.dumps(reply).encode())

    def log_message(self, *args):
        pass


class HttpFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()


# -- model-agnostic reasoning ------------------------------------------------------
def ctx_for(onto):
    return DecisionContext(onto, onto.goals["onboard_customer"], ["verify_identity"],
                           [onto.actions["verify_identity"], onto.actions["enhanced_due_diligence"]], {"Customer": {}})


class ModelAgnosticTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(ONTOLOGY_PATH)

    def test_any_provider_via_function_adapter(self):
        seen = {}

        def other_vendor(system, prompt, schema):
            seen.update(system=system, schema=schema)
            first = schema["properties"]["action"]["enum"][0]
            return {"action": first, "rationale": "vendor-neutral"}, {"input_tokens": 2_000_000, "output_tokens": 0}

        register_price("acme-llm-1", 1.0, 2.0)
        reasoner = LLMReasoner(FunctionChatModel(other_vendor, "acme-llm-1"))
        proposal = reasoner.propose(ctx_for(self.onto))
        self.assertEqual((proposal.action, proposal.source, proposal.model), ("verify_identity", "llm", "acme-llm-1"))
        self.assertAlmostEqual(proposal.cost_usd, 2.0)
        self.assertIn("Ontology customer-onboarding", seen["system"])
        self.assertEqual(estimate_cost("unknown-model", {"input_tokens": 10**6}), 0.0)

    def test_function_adapter_failures_fall_back(self):
        cases = {
            "raises": lambda s, p, sc: 1 / 0,
            "not json": lambda s, p, sc: "not json",
            "json string ok": lambda s, p, sc: json.dumps({"action": "verify_identity", "rationale": "x"}),
            "not an object": lambda s, p, sc: ["verify_identity"],
            "bad choice": lambda s, p, sc: {"action": "launch_rocket", "rationale": "x"},
        }
        sources = {}
        for label, fn in cases.items():
            sources[label] = LLMReasoner(FunctionChatModel(fn)).propose(ctx_for(self.onto)).source
        self.assertEqual(sources, {"raises": "planner", "not json": "planner", "json string ok": "llm",
                                   "not an object": "planner", "bad choice": "planner"})

    def test_drives_a_whole_run(self):
        reasoner = LLMReasoner(FunctionChatModel(lambda s, p, sc: {
            "action": next(n for n in sc["properties"]["action"]["enum"] if n != "enhanced_due_diligence"),
            "rationale": "local model"}, "local"))
        res = WorkAgent("a", self.onto, build_registry(), roles=["sales", "kyc"], reasoner=reasoner,
                        approver=AutoApprover()).run("onboard_customer", retail_case())
        self.assertTrue(res.completed)
        self.assertTrue(any(s.proposed_by == "llm" for s in res.steps))

    def test_anthropic_adapter_edge_cases(self):
        def client(response):
            return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: response)))

        truncated = SimpleNamespace(stop_reason="max_tokens", content=[], usage=None)
        r = AnthropicChatModel(client(truncated)).complete_json(system="s", prompt="p", schema={})
        self.assertEqual((r.stop_reason, r.data, r.usage), ("max_tokens", None, {}))
        garbled = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="{oops")])
        self.assertIn("unparseable", AnthropicChatModel(client(garbled)).complete_json(
            system="s", prompt="p", schema={}).error)
        listy = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="[1]")])
        self.assertIsNone(AnthropicChatModel(client(listy)).complete_json(system="s", prompt="p", schema={}).data)
        no_candidates = DecisionContext(self.onto, self.onto.goals["onboard_customer"], ["verify_identity"], [], {})
        reasoner = LLMReasoner(FunctionChatModel(lambda *a: {}))
        self.assertIn("no candidates", reasoner.propose(no_candidates).rationale)


# -- declarative tools, approvers, reasoners --------------------------------------
class AdapterTests(HttpFixture):
    def test_python_tools_registries_and_kwargs(self):
        reg = load_tools(EXAMPLE / "tools_pilot.json")
        self.assertIn("kyc.verify", reg.capabilities())
        inline = load_tools({"python_path": [str(MFG)], "registries": [
            {"target": "manufacturing_tools:production_tools"}],
            "tools": [{"name": "extra_trace", "capability": "qms.trace", "type": "python",
                       "target": "manufacturing_tools:quality_tools", "cost": 3, "priority": 2}]})
        self.assertIn("qms.trace", inline.capabilities())
        self.assertEqual([t.cost for t in inline if t.name == "extra_trace"], [3.0])

    def test_config_errors(self):
        bad = [
            {"registries": ["not_a_module_xyz:factory"]},
            {"registries": ["json:dumps"]},  # does not return a ToolRegistry
            {"tools": [{"name": "x", "capability": "c", "type": "ftp"}]},
            {"tools": [{"capability": "c", "type": "python", "target": "json:dumps"}]},
            {"tools": [{"name": "x", "capability": "c", "type": "python", "target": "json"}]},
            {"tools": [{"name": "x", "capability": "c", "type": "python", "target": "json:nope"}]},
        ]
        for spec in bad:
            with self.subTest(spec=spec), self.assertRaises((AdapterError, TypeError)):
                load_tools(spec)

    def test_http_tool(self):
        os.environ["AUTOLOGY_TEST_TOKEN"] = "s3cret"
        _Handler.routes = {
            "/ok": lambda body, h: (200, {"outcome": "approved", "message": f"{h['Authorization']}:{body['action']}",
                                         "updates": {"Contract": {"revision": 2}}}),
            "/boom": lambda body, h: (500, {"error": "down"}),
            "/garbage": lambda body, h: (200, b"<html>"),
            "/list": lambda body, h: (200, [1, 2]),
        }
        call = ToolCall("legal_review", "contract.validate", {"Contract.value": 1}, {}, 1)
        result = http_tool(self.base + "/ok", {"Authorization": "Bearer ${AUTOLOGY_TEST_TOKEN}"})(call)
        self.assertEqual((result.outcome, result.message), ("approved", "Bearer s3cret:legal_review"))
        self.assertEqual(result.updates, {"Contract": {"revision": 2}})
        for path in ("/boom", "/garbage", "/list"):
            with self.subTest(path), self.assertRaises(ToolError):
                http_tool(self.base + path)(call)
        with self.assertRaises(ToolError):
            http_tool("http://127.0.0.1:9/unreachable", timeout=0.5)(call)
        with self.assertRaises(AdapterError):
            http_tool(self.base + "/ok", {"X": "${AUTOLOGY_UNSET_VAR_XYZ}"})(call)
        reg = load_tools({"tools": [{"name": "remote_validator", "capability": "contract.validate", "type": "http",
                                     "url": self.base + "/ok", "timeout": 2}]})
        self.assertEqual(next(iter(reg)).name, "remote_validator")

    def test_http_tool_inside_an_agent_with_fallback(self):
        tools = build_registry()
        tools.register("remote_esign", "esign.send", http_tool("http://127.0.0.1:9/sign", timeout=0.5), priority=9)
        onto = Ontology.load(ONTOLOGY_PATH)
        res = WorkAgent("a", onto, tools, roles=["sales", "kyc"], approver=AutoApprover()).run(
            "onboard_customer", retail_case())
        self.assertTrue(res.completed)  # remote service unreachable (not sent) -> fallback to the local tool
        self.assertEqual(next(s.tool for s in res.steps if s.action == "sign_contract"), "esign_gateway")

    def test_no_fallback_after_a_reply_that_leaves_the_outcome_unknown(self):
        _Handler.routes = {"/sign": lambda body, h: (503, {})}  # it may have sent the contract for signature
        tools = build_registry()
        tools.register("remote_esign", "esign.send", http_tool(self.base + "/sign"), priority=9)
        onto = Ontology.load(ONTOLOGY_PATH)
        res = WorkAgent("a", onto, tools, roles=["sales", "kyc"], approver=AutoApprover()).run(
            "onboard_customer", retail_case())
        self.assertEqual(res.status, "uncertain")  # a person confirms; another provider is never tried
        self.assertNotIn("esign_gateway", [s.tool for s in res.steps if s.action == "sign_contract"])

    def test_approvers(self):
        req = ReviewRequest("c1", "sign_contract", "", ("cfo",), ["big"],
                            {"Contract": {"value": 3_000_000}, "Customer": {"tax_id": "***redacted***"}})
        self.assertFalse(load_approver(None).review(req).approved)
        self.assertFalse(load_approver("deny").review(req).approved)
        self.assertTrue(load_approver("auto").review(req).approved)
        policy = load_approver({"decisions": {"sign_contract": "Contract.value < 2000000"}, "default": True})
        self.assertFalse(policy.review(req).approved)
        req.view["Contract"]["value"] = 10
        self.assertTrue(policy.review(req).approved)
        redacted = load_approver({"decisions": {"sign_contract": "Customer.tax_id != None"}})
        self.assertFalse(redacted.review(req).approved)  # conditions on data the reviewer can't see fail closed
        self.assertTrue(load_approver(str(EXAMPLE / "approvals.json")).review(req).approved)
        self.assertEqual(type(load_approver("console")).__name__, "ConsoleApprover")
        for bad in ("maybe", {"type": "carrier-pigeon"}):
            with self.assertRaises(AdapterError):
                load_approver(bad)

    def test_http_approver_fails_closed(self):
        _Handler.routes = {"/review": lambda body, h: (200, {"approved": body["action"] == "sign_contract",
                                                             "reviewer": "jane@legal", "comment": "ok"})}
        req = ReviewRequest("c1", "sign_contract", "", ("legal",), [], {})
        decision = load_approver({"type": "http", "url": self.base + "/review"}).review(req)
        self.assertEqual((decision.approved, decision.reviewer), (True, "jane@legal"))
        down = HttpApprover("http://127.0.0.1:9/review", timeout=0.5).review(req)
        self.assertFalse(down.approved)
        self.assertIn("unavailable", down.comment)

    def test_reasoner_specs(self):
        self.assertIsInstance(load_reasoner(None), PlanFollowingReasoner)
        self.assertIsInstance(load_reasoner("autology.reasoners:PlanFollowingReasoner"), PlanFollowingReasoner)
        with self.assertRaises(AdapterError):
            load_reasoner("json:dumps")
        with self.assertRaises(AdapterError):
            import_target("no-colon")


# -- persistence -----------------------------------------------------------------------
class PersistenceTests(unittest.TestCase):
    def test_roundtrip_and_tamper_evidence(self):
        onto = Ontology.load(ONTOLOGY_PATH)
        res = WorkAgent("a", onto, build_registry(), roles=["sales", "kyc"], approver=AutoApprover()).run(
            "onboard_customer", retail_case(Contract={"value": 1_500_000}), "C-1")
        back = result_from_dict(json.loads(json.dumps(result_to_dict(res))))
        self.assertEqual((back.status, back.path, back.costs), (res.status, res.path, res.costs))
        self.assertTrue(back.audit.verify())
        path = Path(tempfile.mkdtemp()) / "runs.jsonl"
        save_runs([res, res], path)
        save_runs([res], path, append=True)
        self.assertEqual(len(load_runs(path)), 3)
        tampered = path.read_text().replace('"approved": true', '"approved": false', 1)
        path.write_text(tampered)
        self.assertFalse(load_runs(path)[0].audit.verify())
        path.write_text('{"format": "something-else"}\n')
        with self.assertRaisesRegex(ValueError, "runs.jsonl:1"):
            load_runs(path)

    def test_resume_in_another_process(self):
        onto = Ontology.load(MFG_ONTOLOGY)
        clock = SimpleNamespace(now=100.0)
        agent = WorkAgent("p", onto, mt.production_tools(mt.Faults(mes_down=1)), roles=["production"],
                          approver=AutoApprover(), clock=lambda: clock.now)
        deferred = agent.run("fulfil_order", order_case())
        stored = json.loads(json.dumps(result_to_dict(deferred)))
        clock.now += 3600
        fresh_agent = WorkAgent("p", onto, mt.production_tools(), roles=["production"], approver=AutoApprover(),
                                clock=lambda: clock.now)
        done = fresh_agent.resume(result_from_dict(stored))
        self.assertTrue(done.completed)
        self.assertTrue(done.audit.verify())
        with self.assertRaises(ValueError):
            fresh_agent.resume(done)


# -- CLI: any ontology, any tools, no Python glue ----------------------------------------
class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_run_score_report_pipeline(self):
        runs = self.tmp / "runs.jsonl"
        cases = self.tmp / "cases.json"
        cases.write_text(json.dumps([{"case_id": "R-1", "case": retail_case()},
                                     retail_case(Customer={"name": "Shady Holdings Ltd"})]))
        code, out, _ = run_cli("run", ONTOLOGY_PATH, "onboard_customer", cases, "--tools", EXAMPLE / "tools.json",
                               "--roles", "sales,kyc", "--approver", "auto", "--out", runs)
        self.assertEqual(code, 1)  # one case escalated (sanctioned) -> non-zero for scripting
        self.assertIn("R-1: completed", out)
        self.assertIn("case-2: escalated", out)
        code, out, _ = run_cli("score", ONTOLOGY_PATH, "--runs", runs, "--tools", EXAMPLE / "tools.json", "--data",
                               EXAMPLE / "data.json", "--budget", "30", "--tco", EXAMPLE / "tco.json", "--json")
        card = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(card["pillars"]["Agent performance"]["criteria"][0]["name"], "Resolution rate")
        self.assertIn("100% completed or correctly stopped", card["pillars"]["Agent performance"]["criteria"][0]["detail"])
        code, out, _ = run_cli("report", ONTOLOGY_PATH, runs)
        self.assertIn("Resolution rate", out)
        code, out, _ = run_cli("score", ONTOLOGY_PATH, "--runs", runs, "--roi", "3", "--tasks-per-month", "20000")
        self.assertIn("| Pilot | ROI | 300% |", out)

    def test_run_with_delegate_and_policy(self):
        cases = self.tmp / "case.json"
        cases.write_text(json.dumps({"Supplier": {"name": "S"}, "Contract": {"value": 5_000_000,
                                     "late_delivery_penalty": True, "end_date": "2027-01-01", "revision": 0}}))
        code, out, _ = run_cli("run", MFG_ONTOLOGY, "contract_supplier", cases, "--tools", MFG / "tools.json",
                               "--roles", "procurement", "--delegate",
                               f"finance-agent:finance:{MFG / 'finance_tools.json'}",
                               "--approver", MFG / "approvals.json")
        self.assertEqual(code, 1)
        self.assertIn("blocked", out)  # 5M > the approval policy's 2M limit

    def test_run_errors(self):
        cases = self.tmp / "c.json"
        cases.write_text(json.dumps({"Customer": {"shoe_size": 1}}))
        code, _, err = run_cli("run", ONTOLOGY_PATH, "onboard_customer", cases, "--tools", EXAMPLE / "tools.json")
        self.assertEqual(code, 2)
        self.assertIn("invalid case", err)
        code, _, err = run_cli("run", ONTOLOGY_PATH, "onboard_customer", cases, "--tools", self.tmp / "missing.json")
        self.assertEqual(code, 2)
        code, _, err = run_cli("score", ONTOLOGY_PATH, "--runs", self.tmp / "missing.jsonl")
        self.assertEqual(code, 2)

    def test_inspection_commands(self):
        self.assertEqual(run_cli("lint", MFG_ONTOLOGY)[1].strip(), "clean")
        self.assertIn("Entities:", run_cli("describe", ONTOLOGY_PATH)[1])
        self.assertIn('"@graph"', run_cli("export", ONTOLOGY_PATH)[1])
        self.assertIn("owl:Class", run_cli("export", ONTOLOGY_PATH, "--format", "turtle")[1])
        self.assertEqual(run_cli("ask", MFG_ONTOLOGY, MFG / "data.json", "CQ-02", "--param", "line=PL-3")[1].strip(),
                         '["S-Z"]')
        self.assertIn("ROI over horizon", run_cli("roi", MFG / "roi.json")[1])
        code, out, _ = run_cli("validate", ONTOLOGY_PATH, "--data", EXAMPLE / "data.json")
        self.assertEqual(code, 0)
        self.assertIn("CQ-05", out)
        wrong = self.tmp / "wrong.json"
        data = json.loads((EXAMPLE / "data.json").read_text())
        data["instances"] = [i for i in data["instances"] if i["id"] != "CU-5"]
        data["links"] = [l for l in data["links"] if "CU-5" not in l]
        wrong.write_text(json.dumps(data))
        code, out, _ = run_cli("validate", ONTOLOGY_PATH, "--data", wrong)
        self.assertEqual(code, 1)
        self.assertIn("MISMATCH", out)

    def test_plan_and_diff_and_bad_input(self):
        case = self.tmp / "case.json"
        case.write_text(json.dumps(retail_case()))
        code, out, _ = run_cli("plan", ONTOLOGY_PATH, "onboard_customer", case, "--roles", "sales,kyc")
        self.assertEqual(code, 0)
        self.assertIn("(expects approved)", out)
        self.assertEqual(run_cli("plan", ONTOLOGY_PATH, "onboard_customer", case, "--roles", "sales")[0], 2)
        same = run_cli("diff", ONTOLOGY_PATH, ONTOLOGY_PATH)
        self.assertEqual(same[0], 0)
        self.assertIn("required bump none", same[1])
        doc = json.loads(json.dumps(__import__("autology.ontology", fromlist=["x"]).load_document(ONTOLOGY_PATH)))
        doc["entities"]["Order"]["attributes"].pop("sku")
        doc["actions"]["place_order"]["reads"].remove("Order.sku")
        doc["version"] = "1.2.1"
        newer = self.tmp / "newer.json"
        newer.write_text(json.dumps(doc))
        code, out, err = run_cli("diff", ONTOLOGY_PATH, newer)
        self.assertEqual(code, 3)
        self.assertIn("insufficient", err)
        broken = self.tmp / "broken.json"
        broken.write_text("{not json")
        with self.assertRaises(SystemExit):
            run_cli("lint", broken)


if __name__ == "__main__":
    unittest.main()
