"""The MCP interface: the same governed tools, for any MCP client."""

import io
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from autology.mcp import McpServer, run

from .helpers import ROOT
from .test_platform import EX, TOKENS, add_big_order, service


def rpc(server, method, params=None, mid=1):
    return server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


class McpTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        add_big_order(self.svc)
        self.u = {x.name: x for x in self.svc.users}

    def test_handshake_and_tools(self):
        server = McpServer(self.svc, self.u["olivia"])
        init = rpc(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
        self.assertEqual((init["protocolVersion"], init["serverInfo"]["name"]), ("2025-06-18", "autology"))
        self.assertIn("tools", init["capabilities"])
        self.assertEqual(rpc(server, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"],
                         "2025-06-18")
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(rpc(server, "ping")["result"], {})
        tools = {t["name"]: t for t in rpc(server, "tools/list")["result"]["tools"]}
        self.assertIn("start_run", tools)
        self.assertNotIn("list_reviews", tools)  # olivia has no review permission
        self.assertNotIn("decide_review", tools)
        self.assertEqual(tools["get_object"]["inputSchema"]["required"], ["id"])
        self.assertEqual(rpc(server, "resources/list")["error"]["code"], -32601)

    def test_calls_are_governed(self):
        server = McpServer(self.svc, self.u["olivia"])
        listed = rpc(server, "tools/call", {"name": "list_objects", "arguments": {"type": "Order"}})["result"]
        self.assertFalse(listed["isError"])
        self.assertNotIn("O-3", listed["content"][0]["text"])  # EU order hidden from olivia
        hidden = rpc(server, "tools/call", {"name": "get_object", "arguments": {"id": "O-3"}})["result"]
        self.assertTrue(hidden["isError"])
        self.assertIn("404", hidden["content"][0]["text"])
        proposed = rpc(server, "tools/call", {"name": "start_run", "arguments": {
            "agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case", "root": "K-2"}})
        self.assertIn("Proposed, not started", proposed["result"]["content"][0]["text"])
        self.assertEqual(self.svc.store.list_runs(), [])
        self.assertTrue(rpc(server, "tools/call", {"name": "fly", "arguments": {}})["result"]["isError"])
        self.assertTrue(rpc(server, "tools/call", {"name": "get_object", "arguments": {}})["result"]["isError"])
        log = {(e["kind"], e["target"]) for e in self.svc.store.access_log("olivia")}
        self.assertIn(("mcp.tool", "start_run"), log)

    def test_confidential_values_are_withheld(self):
        server = McpServer(self.svc, self.u["admin"])  # even an admin's client is a model provider
        text = rpc(server, "tools/call", {"name": "get_object", "arguments": {"id": "C-2"}})["result"]["content"][0]["text"]
        self.assertNotIn("500000", text)

    def test_errors_do_not_end_the_session(self):
        server = McpServer(self.svc, self.u["olivia"])
        with mock.patch.object(self.svc, "list_runs", side_effect=RuntimeError("store gone")):
            out = rpc(server, "tools/list")  # unaffected
            self.assertIn("result", out)
            with self.assertLogs("autology.server", "ERROR"):
                broken = server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                        "params": {"name": "list_runs", "arguments": {"status": ""}}})
        self.assertEqual(broken["error"]["code"], -32603)
        reader = io.StringIO('not json\n\n{"jsonrpc": "2.0", "id": 2, "method": "ping"}\n[{"jsonrpc": "2.0", '
                             '"id": 3, "method": "ping"}]\n"x"\n')
        writer = io.StringIO()
        server.serve(reader, writer)
        replies = [json.loads(line) for line in writer.getvalue().splitlines()]
        self.assertEqual([r.get("id") for r in replies], [None, 2, 3, None])
        self.assertEqual(replies[0]["error"]["code"], -32700)


def temp_config():
    import tempfile

    cfg = json.loads((EX / "server.json").read_text())
    cfg.update(ontology=str(EX / "ontology.json"), data=str(EX / "data.json"),
               store=str(os.path.join(tempfile.mkdtemp(), "mcp.db")), automations={}, chat=None)
    cfg["agents"]["fulfilment"]["tools"] = str(EX / "tools.json")
    path = os.path.join(tempfile.mkdtemp(), "server.json")
    with open(path, "w") as fh:
        json.dump(cfg, fh)
    return path


USER_TOKENS = {f"AUTOLOGY_TOKEN_{n.upper()}": t for n, t in TOKENS.items()}


class McpProcessTests(unittest.TestCase):
    def test_stdio_end_to_end(self):
        env = {**os.environ, **USER_TOKENS,
               "AUTOLOGY_TOKEN": TOKENS["lena"], "PYTHONPATH": str(ROOT)}
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"}}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "ask_question", "arguments": {"question_id": "CQ-01", "params": {}}}}]
        path = temp_config()
        proc = subprocess.run([sys.executable, "-m", "autology", "mcp", path], input="\n".join(
            json.dumps(m) for m in messages) + "\n", capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertEqual(json.loads(replies[1]["result"]["content"][0]["text"])["answer"], ["O-1", "O-2", "O-3"])

    def test_bad_token(self):
        path = temp_config()
        with mock.patch.dict(os.environ, {**USER_TOKENS, "MCP_TEST_TOKEN": "wrong"}):
            err = io.StringIO()
            with mock.patch("sys.stderr", err):
                self.assertEqual(run(path, "MCP_TEST_TOKEN"), 2)
            self.assertIn("sign-in failed", err.getvalue())
            os.environ.pop("MCP_TEST_TOKEN")
            with mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(run(path, "MCP_TEST_TOKEN"), 2)


if __name__ == "__main__":
    unittest.main()
