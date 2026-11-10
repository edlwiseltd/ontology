"""Tier 2: ontology interfaces, justification checkpoints, OpenTelemetry trace export."""

import copy
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from autology import AutoApprover, Ontology, OntologyError, WorkAgent
from autology.__main__ import main as cli
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph
from autology.persistence import save_runs
from autology.server import ApiError
from autology.tracing import _ns, resolve_headers, run_spans, to_otlp
from autology.versioning import diff

from .test_platform import CASE, EX, _Api, service

DOC = json.loads((EX / "ontology.json").read_text())
DATA = json.loads((EX / "data.json").read_text())


def onto_with(mutate):
    doc = copy.deepcopy(DOC)
    mutate(doc)
    return Ontology.from_dict(doc)


class InterfaceTests(unittest.TestCase):
    def test_queries_and_listings_cover_every_implementer(self):
        onto = Ontology.load(EX / "ontology.json")
        graph = KnowledgeGraph.from_dict(onto, DATA)
        self.assertEqual(onto.implementers("Regional"), ("Customer", "Order"))
        self.assertEqual(onto.implementers("Order"), ("Order",))
        self.assertEqual(sorted(i.id for i in graph.instances("Regional")), ["C-1", "O-1", "O-2", "O-3"])
        self.assertEqual(graph.query("Regional", "Regional.region == 'US'").ids, ["C-1", "O-1", "O-2"])
        self.assertEqual(graph.ask("CQ-04").answer, ["O-3"])

    def test_validation(self):
        def iface(attrs):
            return lambda d: d.update(interfaces={"Regional": {"attributes": attrs}})

        bad = {
            "unknown interface": lambda d: d["entities"]["Contract"].update(implements=["Ghost"]),
            "missing attribute": lambda d: d["entities"]["Contract"].update(implements=["Regional"]),
            "type mismatch": iface({"region": "number"}),
            "name clash": lambda d: d.update(interfaces={"Order": {"attributes": {}}}),
            "unknown attribute": lambda d: d["competency_questions"].append(
                {"id": "Q", "question": "?", "find": "Regional", "where": "Regional.colour == 'x'"}),
            "follow": lambda d: d["competency_questions"].append(
                {"id": "Q", "question": "?", "find": "Regional", "follow": ["covers"]}),
        }
        for label, mutate in bad.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                onto_with(mutate)
        ok = onto_with(lambda d: d["competency_questions"].append(
            {"id": "Q", "question": "?", "find": "Regional", "where": "Regional.status == 'approved'"}))
        self.assertIn("Regional", ok.interfaces)

    def test_versioning_sees_interfaces(self):
        old = Ontology.load(EX / "ontology.json")
        new = onto_with(lambda d: (d["interfaces"]["Regional"]["attributes"].update(sku="string"),
                                   d["entities"]["Customer"]["attributes"].update(sku="string"),
                                   d["entities"]["Customer"].update(implements=["Regional"])))
        kinds = {(c.kind, c.level) for c in diff(old, new)}
        self.assertIn(("interface_attribute.added", "major"), kinds)  # implementers must now have it
        dropped = onto_with(lambda d: d["entities"]["Order"].pop("implements"))
        self.assertIn(("implements.removed", "major"), {(c.kind, c.level) for c in diff(old, dropped)})

    def test_api_lists_interfaces(self):
        svc = service(automations={}, chat=None)
        users = {u.name: u for u in svc.users}
        listed = svc.list_objects(users["olivia"], "Regional", 100, 0)
        self.assertEqual([i["id"] for i in listed["items"]], ["C-1", "O-1", "O-2"])  # EU order still hidden
        self.assertEqual(svc.ontology_summary(users["olivia"])["interfaces"]["Regional"]["implementers"],
                         ["Customer", "Order"])


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.users = {u.name: u for u in self.svc.users}

    def test_validation(self):
        bad = [{"on": "dance"}, {"on": "read_field", "field": "Ghost.x"}, {"on": "start_run", "goal": "ghost"},
               {"on": "decide", "min_length": 0}, {"on": "decide", "when": "Order.amount > 1"}]
        for params in bad:
            with self.subTest(params), self.assertRaises(OntologyError):
                onto_with(lambda d: d["rules"].append({"id": "CP-X", "type": "checkpoint", **params}))

    def test_sensitive_fields_need_a_justification(self):
        audrey = self.users["audrey"]
        self.assertEqual(self.svc.get_object(audrey, "C-1")["attributes"]["credit_limit"],
                         "***justification required***")
        with self.assertRaises(ApiError) as cm:
            self.svc.get_object(audrey, "C-1", "because")  # too short
        self.assertEqual(cm.exception.status, 428)
        self.assertEqual(cm.exception.extra["checkpoint"]["rules"], ["CP-CREDIT"])
        shown = self.svc.get_object(audrey, "C-1", "annual credit limit review")
        self.assertEqual(shown["attributes"]["credit_limit"], 250000)
        listed = self.svc.list_objects(audrey, "Customer", 10, 0, "annual credit limit review")
        self.assertEqual(listed["items"][0]["attributes"]["credit_limit"], 250000)
        orders = self.svc.list_objects(audrey, "Order", 10, 0, "x")  # nothing gated: no checkpoint, no record
        self.assertEqual(len(orders["items"]), 2)
        olivia = self.svc.get_object(self.users["olivia"], "C-1", "annual credit limit review")
        self.assertEqual(olivia["attributes"]["credit_limit"], "***redacted***")  # access rules still come first
        log = self.svc.justifications(self.users["audrey"], 10)["items"]
        self.assertEqual([(j["principal"], j["rule_id"], j["operation"]) for j in log][-1],
                         ("audrey", "CP-CREDIT", "read_field"))
        with self.assertRaises(ApiError):
            self.svc.justifications(self.users["olivia"], 10)

    def test_declining_a_shipment_needs_a_reason(self):
        olivia, lena = self.users["olivia"], self.users["lena"]
        self.svc.start_run(olivia, {"case": CASE})
        review = self.svc.list_reviews(lena, "pending")["items"][0]
        with self.assertRaises(ApiError) as cm:
            self.svc.decide(lena, review["review_id"], {"approved": False, "comment": "no"})
        self.assertEqual(cm.exception.status, 428)
        self.assertEqual(self.svc.get_review(lena, review["review_id"])["status"], "pending")  # nothing decided
        out = self.svc.decide(lena, review["review_id"], {"approved": False,
                                                          "comment": "carrier cannot take a turbine this week"})
        self.assertEqual(out["status"], "blocked")

    def test_other_operations(self):
        doc = copy.deepcopy(DOC)
        doc["rules"] += [{"id": f"CP-{op}", "type": "checkpoint", "on": op, "description": f"Why {op}?"}
                         for op in ("start_run", "resume_run", "upsert_object", "commit_scenario")]
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ontology.json").write_text(json.dumps(doc))
        svc = service(ontology=str(tmp / "ontology.json"), automations={}, chat=None)
        u = {x.name: x for x in svc.users}
        api = _Api(svc)
        try:
            status, body, _ = api.call("POST", "/api/runs", "olivia", {"case": CASE})
            self.assertEqual((status, body["checkpoint"]["prompt"]), (428, "Why start_run?"))
            status, run, _ = api.call("POST", "/api/runs", "olivia", {"case": CASE, "justification": "monthly batch"})
            self.assertEqual(status, 200)
            with self.assertRaises(ApiError):
                svc.resume_run(u["olivia"], run["run_id"])
            with self.assertRaises(ApiError):
                svc.upsert_object(u["admin"], {"type": "Order", "id": "O-8", "attributes": {}})
            sid = svc.create_scenario(u["admin"], {})["scenario_id"]
            self.assertEqual(api.call("POST", f"/api/scenarios/{sid}/commit", "admin", {})[0], 428)
            done = api.call("POST", f"/api/scenarios/{sid}/commit", "admin", {"justification": "approved change"})
            self.assertEqual(done[1]["status"], "committed")
            status, log, _ = api.call("GET", "/api/justifications", "audrey")
            self.assertEqual([j["operation"] for j in log["items"]], ["commit_scenario", "start_run"])
        finally:
            api.server.shutdown()
        store_path = Path(tempfile.mkdtemp()) / "j.db"
        from autology.store import Store

        store = Store(store_path)
        store.add_justification("a", "CP", "op", "t", "text")
        raw = sqlite3.connect(store_path)
        for sql in ("UPDATE justifications SET text='x'", "DELETE FROM justifications"):
            with self.subTest(sql), self.assertRaises(sqlite3.DatabaseError):
                raw.execute(sql)

    def test_the_assistant_cannot_justify_for_a_person(self):
        from autology.chat import GovernedChat, ScriptedChatBackend

        doc = copy.deepcopy(DOC)
        doc["rules"].append({"id": "CP-RUN", "type": "checkpoint", "on": "start_run"})
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ontology.json").write_text(json.dumps(doc))
        svc = service(ontology=str(tmp / "ontology.json"), automations={}, chat=None)
        olivia = next(u for u in svc.users if u.name == "olivia")
        step = iter([{"tool_calls": [{"name": "start_run", "input": {
            "agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case", "root": "K-1",
            "justification": "the model made this up"}}]}, {"text": "You need to give a reason in the inbox."}])
        reply = GovernedChat(svc, ScriptedChatBackend(lambda m, t: next(step))).send(olivia, "run K-1")
        self.assertEqual(reply.tool_calls[0]["ok"], False)
        self.assertEqual(svc.store.list_runs(), [])


class TracingTests(unittest.TestCase):
    def run_case(self, approver=None):
        onto = Ontology.load(EX / "ontology.json")
        agent = WorkAgent("tracer", onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops", "finance"],
                          approver=approver or AutoApprover())
        return agent.run("fulfil_contract", CASE, "K-1")

    def test_spans(self):
        result = self.run_case()
        spans = run_spans(result, "run-1")
        root = spans[0]
        self.assertEqual(root["name"], "autology.run fulfil_contract")
        self.assertEqual(len({s["traceId"] for s in spans}), 1)
        self.assertEqual(len({s["spanId"] for s in spans}), len(spans))
        self.assertTrue(all(s.get("parentSpanId") for s in spans[1:]))
        ship = next(s for s in spans if s["name"] == "ship_order@O-4")
        self.assertEqual([e["name"] for e in ship["events"]], ["review"])
        attrs = {a["key"]: a["value"] for a in ship["attributes"]}
        self.assertEqual(attrs["autology.rules"]["arrayValue"]["values"][0]["stringValue"], "R-LOG-001")
        self.assertEqual(attrs["autology.outcome"], {"stringValue": "done"})
        tool = next(s for s in spans if s["name"] == "tool credit_engine")
        self.assertIn(tool["parentSpanId"], {s["spanId"] for s in spans if s["name"].startswith("credit_check")})
        self.assertEqual(run_spans(result, "run-1"), spans)  # deterministic ids: re-export is idempotent
        self.assertEqual(_ns("1970-01-01T00:00:01.000002+00:00"), 1_000_002_000)
        self.assertEqual(_ns("1970-01-01T00:00:01"), 1_000_000_000)
        no_audit = type("R", (), {"audit": [], "case_id": "x", "goal": "g"})()
        self.assertEqual(run_spans(no_audit), [])

    def test_failures_become_error_spans(self):
        from autology import ReviewDecision
        from autology.agent import DeferredApprover

        onto = Ontology.load(EX / "ontology.json")
        agent = WorkAgent("tracer", onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops", "finance"],
                          approver=DeferredApprover())
        parked = agent.run("fulfil_contract", CASE, "K-1")
        blocked = agent.resume(parked, decision=ReviewDecision(False, "lena", "no carrier"))
        spans = run_spans(blocked, "r")
        self.assertEqual(spans[0]["status"]["code"], 2)
        parked, declined = [s for s in spans if s["name"] == "ship_order@O-4"]
        self.assertEqual([e["name"] for e in parked["events"]], ["review.requested"])
        self.assertEqual(declined["status"], {"code": 2, "message": "declined in human review"})
        self.assertEqual([e["name"] for e in spans[0]["events"]], ["run.start", "run.resume"])
        ops_only = WorkAgent("ops", onto, load_tools(EX / "tools.json"), roles=["ops"])
        escalated = ops_only.run("fulfil_contract", CASE, "x")
        self.assertEqual(run_spans(escalated, "e")[0]["status"]["code"], 2)

    def test_deferred_and_tool_errors(self):
        from autology import ToolError, ToolRegistry

        doc = copy.deepcopy(DOC)
        doc["actions"]["pick_order"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": 3600,
                                                      "fallback_tools": False}
        onto = Ontology.from_dict(doc)
        tools = load_tools(EX / "tools.json")

        def down(call):
            raise ToolError("warehouse down")

        tools.register("broken_wms", "warehouse.pick", down, priority=99)
        result = WorkAgent("t", onto, tools, roles=["ops", "eu_ops", "finance"]).run("fulfil_contract", CASE, "K-1")
        self.assertEqual(result.status, "deferred")
        spans = run_spans(result, "d")
        broken = next(s for s in spans if s["name"] == "tool broken_wms")
        self.assertEqual(broken["status"]["message"], "warehouse down")
        pick = next(s for s in spans if s["name"].startswith("pick_order"))
        self.assertEqual(pick["events"][0]["name"], "deferred")

    def test_cli_endpoint_and_server_export(self):
        received = []

        class Collector(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                received.append((self.path, self.headers.get("x-api-key"),
                                 json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        collector = HTTPServer(("127.0.0.1", 0), Collector)
        threading.Thread(target=collector.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{collector.server_port}/v1/traces"
        try:
            tmp = Path(tempfile.mkdtemp())
            save_runs([self.run_case()], tmp / "runs.jsonl")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(cli(["trace", str(tmp / "runs.jsonl")]), 0)
            self.assertIn("resourceSpans", json.loads(out.getvalue()))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(cli(["trace", str(tmp / "runs.jsonl"), "--out", str(tmp / "t.json"),
                                      "--endpoint", endpoint]), 0)
                self.assertEqual(cli(["trace"]), 2)
            self.assertEqual(received[0][0], "/v1/traces")
            self.assertTrue(json.loads((tmp / "t.json").read_text())["resourceSpans"])

            import os

            os.environ["OTLP_TEST_KEY"] = "k-123"
            svc = service(automations={}, chat=None, tracing={"endpoint": endpoint,
                                                              "headers": {"x-api-key-env": "OTLP_TEST_KEY"}})
            api = _Api(svc)
            try:
                _, run, _ = api.call("POST", "/api/runs", "olivia", {"case": CASE})  # parks for review: not final
                for t in list(svc.deliveries):
                    t.join(5)
                self.assertEqual(len(received), 1)
                review = api.call("GET", "/api/reviews", "lena")[1]["items"][0]
                api.call("POST", f"/api/reviews/{review['review_id']}/decision", "lena", {"approved": True})
                for t in list(svc.deliveries):
                    t.join(5)
                self.assertEqual(received[-1][1], "k-123")
                spans = received[-1][2]["resourceSpans"][0]["scopeSpans"][0]["spans"]
                self.assertEqual(spans[0]["name"], "autology.run fulfil_contract")
                self.assertEqual(api.call("GET", f"/api/runs/{run['run_id']}/trace", "olivia")[0], 403)
                status, trace, _ = api.call("GET", f"/api/runs/{run['run_id']}/trace", "audrey")
                self.assertEqual(trace["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"], spans[0]["traceId"])
                self.assertEqual(api.call("GET", "/api/runs/nope/trace", "audrey")[0], 404)
                db_out = io.StringIO()
                with redirect_stdout(db_out):
                    cli(["trace", "--db", svc.store.path, "--run", run["run_id"]])
                self.assertEqual(len(json.loads(db_out.getvalue())["resourceSpans"][0]["scopeSpans"][0]["spans"]),
                                 len(spans))
            finally:
                api.server.shutdown()
            with self.assertRaises(ValueError):
                service(tracing={"endpoint": "ftp://x"})
            self.assertEqual(resolve_headers({"a": "b", "c-env": "NOPE_NOT_SET"}), {"a": "b", "c": ""})
            self.assertEqual(to_otlp([])["resourceSpans"][0]["scopeSpans"][0]["spans"], [])
        finally:
            collector.shutdown()


if __name__ == "__main__":
    unittest.main()
