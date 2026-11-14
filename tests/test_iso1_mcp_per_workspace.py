"""ISO-1: an MCP client reaches one use case of its own workspace only."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autology.mcp import run

from .test_workspaces import EX, TOKENS

HANDSHAKE = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}


def platform_file():
    spec = json.loads((EX / "platform.json").read_text())
    spec["data_dir"] = tempfile.mkdtemp()
    path = Path(tempfile.mkdtemp()) / "platform.json"
    for ws in spec["workspaces"].values():  # keep the use-case configs reachable from the copied file
        for uc in ws["use_cases"].values():
            uc["config"] = str((EX / uc["config"]).resolve())
    path.write_text(json.dumps(spec))
    return str(path)


def call(path, token, use_case, *messages):
    out, err = io.StringIO(), io.StringIO()
    stdin = io.StringIO("\n".join(json.dumps(m) for m in (HANDSHAKE,) + messages) + "\n")
    with mock.patch.dict(os.environ, {**TOKENS, "MCP_TOKEN": token}), mock.patch("sys.stderr", err):
        code = run(path, "MCP_TOKEN", stdin, out, use_case=use_case)
    return code, [json.loads(line) for line in out.getvalue().splitlines()], err.getvalue()


def tool(name, **arguments):
    return {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


class McpPerWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.path = platform_file()

    def test_a_member_reaches_their_use_case(self):
        code, replies, _ = call(self.path, "acme-hana", "claims", tool("list_objects", type="Claim"))
        self.assertEqual(code, 0)
        listed = json.loads(replies[1]["result"]["content"][0]["text"])
        self.assertIn("CL-1", [o["id"] for o in listed["items"]])

    def test_other_workspaces_and_ungranted_use_cases_are_unreachable(self):
        for token, use_case in (("nw-hana", "orders"),   # Northwind has no orders use case
                                ("acme-hana", "orders"),  # hana has no grant for Acme's orders
                                ("wrong", "claims"),      # not a member at all
                                ("acme-olivia", "claims")):
            with self.subTest(token=token, use_case=use_case):
                code, replies, err = call(self.path, token, use_case)
                self.assertEqual((code, replies), (2, []))
                self.assertIn("no such use case for this token", err)  # the same answer in every case

    def test_a_platform_file_needs_a_use_case(self):
        code, _, err = call(self.path, "acme-hana", None)
        self.assertEqual(code, 2)
        self.assertIn("--use-case", err)

    def test_the_same_member_name_in_another_workspace_sees_only_its_data(self):
        from autology.platform import Platform

        with mock.patch.dict(os.environ, TOKENS):  # an Acme administrator records a claim in Acme's store
            acme = Platform.from_file(self.path).workspaces["acme"].use_cases["claims"].service
        admin = next(u for u in acme.users if u.name == "ada")
        acme.upsert_object(admin, {"type": "Claim", "id": "CL-ACME-9", "attributes": {
            "amount": 1200, "damage_type": "mirror", "reported_days_after": 1}})
        acme.store.close()
        listing = tool("list_objects", type="Claim")
        seen = {}
        for token in ("acme-hana", "nw-hana"):  # two different people who are both called hana
            code, replies, _ = call(self.path, token, "claims", listing)
            self.assertEqual(code, 0)
            seen[token] = [o["id"] for o in json.loads(replies[1]["result"]["content"][0]["text"])["items"]]
        self.assertIn("CL-ACME-9", seen["acme-hana"])
        self.assertNotIn("CL-ACME-9", seen["nw-hana"])


if __name__ == "__main__":
    unittest.main()
