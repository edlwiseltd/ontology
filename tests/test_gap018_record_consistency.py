"""Audit GAP-018: one writer per store (MOD-4), MCP next to the platform server, and record consistency.

Before: an MCP client could serve a platform use case only by opening its store itself, so it was refused while
the platform server ran; and instance rows carried no revision or seal, so a stale write or a change made
directly in the SQLite file was neither refused nor detected.

Now:
* MCP reaches a use case through the platform's authenticated API (``/api/mcp``, or the stdio relay
  ``autology mcp --url``): no second store is opened, and every permission, workspace boundary and execution gate
  of the engine applies;
* every record has a revision and a seal (HMAC under the workspace's audit key over id, type, content and
  revision). Writes from the API, run write-backs and ingestion name the revision they read: a stale one is
  refused (409) and the authoritative record is reloaded; a row changed outside Autology no longer matches its
  seal, even if its revision was bumped: writes over it are refused, it is reported in ``/api/health`` and left
  out of the graph at the next start.
"""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autology.mcp import relay, run
from autology.platform import Platform
from autology.server import ApiError
from autology.store import RecordConflict, Store

from .test_ingest import service as ingest_service
from .test_platform import service
from .test_r2_use_case_lifecycle import close
from .test_workspaces import Client, EX, TOKENS, data_admins, simulate_all

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}


def tool(name, mid=2, **arguments):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


def sql(path, statement, *args):
    db = sqlite3.connect(path)  # someone with access to the database file, outside Autology
    db.execute(statement, args)
    db.commit()
    db.close()


class McpThroughThePlatformTests(unittest.TestCase):
    def setUp(self):
        os.environ.update(TOKENS)
        spec = data_admins(json.loads((EX / "platform.json").read_text()))
        spec["data_dir"] = tempfile.mkdtemp()
        self.spec = spec
        self.pf = simulate_all(Platform(spec, EX))
        self.c = Client(self.pf)

    def tearDown(self):
        self.c.server.shutdown()
        self.c.server.server_close()
        close(self.pf)

    def relay(self, token, path, *messages):
        out = io.StringIO()
        stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
        with mock.patch("autology.store.Store.__init__", side_effect=AssertionError("the relay opened a store")):
            code = relay(self.c.base + path, token, stdin, out)
        return code, [json.loads(line) for line in out.getvalue().splitlines()]

    def test_mcp_works_while_the_platform_server_holds_the_store(self):
        svc = self.pf.workspaces["acme"].use_cases["claims"].service
        lease = svc.store._query("SELECT * FROM writer_lease")
        code, replies = self.relay("acme-hana", "/w/acme/u/claims", INIT,
                                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                   {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                                   tool("list_objects", 3, type="Claim"))
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])  # the notification gets no answer
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "autology")
        self.assertIn("CL-1", [o["id"] for o in json.loads(replies[2]["result"]["content"][0]["text"])["items"]])
        self.assertEqual(svc.store._query("SELECT * FROM writer_lease"), lease)  # still the server's, alone
        # the call went through the engine as hana: it is in the use case's own access log
        self.assertIn(("hana", "mcp.tool"), {(r["principal"], r["kind"]) for r in svc.store.access_log(limit=50)})

    def test_mcp_over_http_directly(self):
        status, out = self.c.call("POST", "/w/acme/u/claims/api/mcp", "acme-hana", INIT)
        self.assertEqual((status, out["result"]["protocolVersion"]), (200, "2025-06-18"))

    def test_another_workspace_or_an_ungranted_use_case_is_unreachable(self):
        for token, path in (("acme-hana", "/w/northwind/u/claims"),  # another workspace, same use-case id
                            ("acme-hana", "/w/acme/u/orders"),       # her workspace, not granted
                            ("nw-hana", "/w/acme/u/claims"),         # the other hana
                            ("wrong", "/w/acme/u/claims")):
            with self.subTest(token=token, path=path):
                code, replies = self.relay(token, path, tool("list_objects", type="Claim"))
                self.assertIn("refused", replies[0]["error"]["message"])
                self.assertNotIn("result", replies[0])

    def test_mcp_cannot_decide_reviews_or_run_anything(self):
        svc = self.pf.workspaces["acme"].use_cases["claims"].service
        _, replies = self.relay("acme-ivan", "/w/acme/u/claims", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                tool("decide_review", review_id="x", approved=True),
                                tool("start_run", 3, agent="claims", goal="settle_claim", case_template="claim_case",
                                     root="CL-1"))
        names = {t["name"] for t in replies[0]["result"]["tools"]}
        self.assertNotIn("decide_review", names)
        self.assertNotIn("start_run", names)  # ivan has no run permission
        self.assertTrue(replies[1]["result"]["isError"])
        self.assertTrue(replies[2]["result"]["isError"])
        _, replies = self.relay("acme-hana", "/w/acme/u/claims",
                                tool("start_run", agent="claims", goal="settle_claim", case_template="claim_case",
                                     root="CL-1"))
        self.assertIn("proposal", replies[0]["result"]["content"][0]["text"])
        self.assertEqual(svc.store.list_runs(limit=10), [])  # only a proposal: a person confirms it

    def test_serving_the_platform_file_directly_is_refused_while_the_server_runs(self):
        path = Path(tempfile.mkdtemp()) / "platform.json"
        spec = json.loads(json.dumps(self.spec))
        for ws in spec["workspaces"].values():
            for uc in ws["use_cases"].values():
                uc["config"] = str((EX / uc["config"]).resolve())
        for t in (spec.get("templates") or {}).values():
            t["config"] = str((EX / t["config"]).resolve())
        path.write_text(json.dumps(spec))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, {"MCP_TOKEN": "acme-hana"}), mock.patch("sys.stderr", err), \
                mock.patch("os.getpid", return_value=os.getpid() + 100000):  # as a separate process would be
            code = run(str(path), "MCP_TOKEN", io.StringIO(""), out, use_case="claims")
        self.assertEqual(code, 2)
        self.assertIn("--url", err.getvalue())

    def test_the_relay_refuses_bad_urls(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stderr", err):
            self.assertEqual(relay("file:///etc/passwd", "t", io.StringIO(""), out), 2)


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.admin = next(u for u in self.svc.users if "admin" in u.permissions)

    def tearDown(self):
        self.svc.close()

    def put(self, iid, **attrs):
        inst = self.svc.graph.get(iid)
        return self.svc.upsert_object(self.admin, {"type": inst.type, "id": iid,
                                                   "attributes": {**inst.attributes, **attrs}})

    def test_every_write_bumps_the_revision(self):
        before = self.svc.revisions["O-1"]
        self.put("O-1", amount=1)
        self.put("O-1", amount=2)
        self.assertEqual(self.svc.revisions["O-1"], before + 2)
        self.assertEqual(self.svc.store.read_instance("O-1")["revision"], before + 2)

    def test_a_stale_write_never_overwrites_newer_data(self):
        # another legitimate writer (here: a second handle on the store, as after a restore) changed O-1
        other = Store(self.svc.store.path, audit_key=self.svc.audit_key)
        row = other.read_instance("O-1")
        other.upsert_instance(row["type"], "O-1", {**row["attributes"], "amount": 4242})
        other.close()
        with self.assertRaises(ApiError) as ctx:
            self.put("O-1", amount=1)
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("changed meanwhile", ctx.exception.message)
        self.assertEqual(self.svc.store.read_instance("O-1")["attributes"]["amount"], 4242)  # kept
        self.assertEqual(self.svc.graph.get("O-1").attributes["amount"], 4242)  # authoritative record reloaded
        self.put("O-1", amount=1)  # the retry, over the reloaded revision, succeeds
        self.assertEqual(self.svc.store.read_instance("O-1")["attributes"]["amount"], 1)

    def test_a_new_record_cannot_silently_replace_one_made_meanwhile(self):
        with self.assertRaises(RecordConflict):
            self.svc.store.upsert_instance("Order", "O-1", {"amount": 1}, expected=__import__(
                "autology.store", fromlist=["ABSENT"]).ABSENT)


class OutOfBandTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.admin = next(u for u in self.svc.users if "admin" in u.permissions)
        self.path = self.svc.store.path

    def tearDown(self):
        self.svc.close()

    def test_a_direct_sql_change_is_detected_even_with_its_revision_bumped(self):
        sql(self.path, "UPDATE instances SET attributes=json_set(attributes, '$.amount', 1), "
                       "revision=revision+1 WHERE id='O-1'")
        self.assertEqual([t["id"] for t in self.svc.store.tampered_instances()], ["O-1"])
        health = self.svc.health()
        self.assertEqual((health["status"], health["tampered_records"]), ("degraded", 1))
        inst = self.svc.graph.get("O-1")
        with self.assertRaises(ApiError) as ctx:  # nothing is written over it
            self.svc.upsert_object(self.admin, {"type": "Order", "id": "O-1",
                                                "attributes": {**inst.attributes, "amount": 7}})
        self.assertEqual((ctx.exception.status, ctx.exception.extra["tampered"]), (409, True))
        self.assertEqual(self.svc.store.read_instance("O-1")["attributes"]["amount"], 1)
        notes = [n for n in self.svc.store.list_notifications(limit=20) if n["kind"] == "quarantine"]
        self.assertIn("changed outside Autology", notes[0]["message"])

    def test_a_record_deleted_outside_autology_is_detected(self):
        self.assertIsNone(self.svc.store.instance_set_problem())
        sql(self.path, "DELETE FROM instances WHERE id='O-2'")
        self.assertIn("added or removed outside Autology", self.svc.store.instance_set_problem())
        self.assertEqual(self.svc.store.tampered_instances()[0]["id"], None)
        self.assertEqual(self.svc.health()["status"], "degraded")
        # and the sealed digest cannot be recomputed by someone without the key
        sql(self.path, "UPDATE meta SET value=json_set(value, '$.digest', '00') WHERE key='instances_digest'")
        self.assertIsNotNone(self.svc.store.instance_set_problem())

    def test_legitimate_writes_keep_the_record_set_sealed(self):
        admin = self.admin
        inst = self.svc.graph.get("O-1")
        self.svc.upsert_object(admin, {"type": "Order", "id": "O-1", "attributes": {**inst.attributes, "amount": 3}})
        self.svc.upsert_object(admin, {"type": "Order", "id": "O-77", "attributes": {
            "sku": "X", "quantity": 1, "amount": 5, "region": "US", "hazardous": False}})
        self.assertIsNone(self.svc.store.instance_set_problem())
        self.assertEqual(self.svc.store.tampered_instances(), [])

    def test_a_tampered_or_forged_record_is_left_out_at_the_next_start(self):
        sql(self.path, "UPDATE instances SET attributes=json_set(attributes, '$.amount', 1) WHERE id='O-1'")
        sql(self.path, "INSERT INTO instances (id, type, attributes, updated_at, revision, seal) "
                       "VALUES ('O-99', 'Order', '{\"amount\": 5}', 'now', 1, 'forged')")
        self.svc.close()
        cfg = json.loads((Path(__file__).resolve().parent.parent / "examples" / "order_fulfilment" /
                          "server.json").read_text())
        again = service(automations={}, chat=None, store=self.path)
        self.assertNotIn("O-1", again.graph._instances)
        self.assertNotIn("O-99", again.graph._instances)
        self.assertEqual({q["id"] for q in again.quarantined if q.get("tampered")}, {"O-1", "O-99"})
        self.assertEqual(again.health()["status"], "degraded")
        self.assertIsNotNone(cfg)
        again.close()
        self.svc = service(automations={}, chat=None)  # for tearDown

    def test_a_run_never_writes_back_over_a_tampered_record(self):
        from .test_platform import add_big_order

        u = {x.name: x for x in self.svc.users}
        self.svc.start_run(u["olivia"], add_big_order(self.svc))
        review = self.svc.list_reviews(u["lena"], "pending")["items"][0]["review_id"]
        sql(self.path, "UPDATE instances SET attributes=json_set(attributes, '$.quantity', 9) WHERE id='O-4'")
        done = self.svc.decide(u["lena"], review, {"approved": True, "comment": "ok"})
        self.assertEqual(done["write_back"]["state"], "conflict")
        row = self.svc.store.read_instance("O-4")
        self.assertEqual((row["attributes"]["quantity"], row["attributes"].get("status")), (9, "picked"))

    def test_ingestion_never_loads_over_a_record_made_meanwhile(self):
        svc = ingest_service()
        etl = next(u for u in svc.users if u.name == "etl")
        other = Store(svc.store.path, audit_key=svc.audit_key)  # the feed creates CL-4; another writer made it first
        other.upsert_instance("Claim", "CL-4", {"amount": 1, "status": "reported"})
        other.close()
        before = svc.store._query("SELECT COUNT(*) AS n FROM instances")[0]["n"]
        with self.assertRaises(ApiError) as ctx:
            svc.run_pipeline(etl, "claims_feed", {})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(svc.store._query("SELECT COUNT(*) AS n FROM instances")[0]["n"], before)  # nothing loaded
        self.assertEqual(svc.store.read_instance("CL-4")["attributes"]["amount"], 1)
        self.assertEqual(svc.graph.get("CL-4").attributes["amount"], 1)  # the authoritative record is reloaded
        svc.close()


if __name__ == "__main__":
    unittest.main()
