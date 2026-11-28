"""GAP-018, directive 02: the remaining write paths and the concurrency evidence.

Found while re-verifying the repository against the directive:
  1. ``POST /api/scenarios/{id}/commit`` changed the live graph first, then wrote record by record with no
     revision or seal check: a stale or tampered row was overwritten and a failure left a partial commit;
  2. an interrupted schema-14 upgrade (columns added, rows not yet sealed) made every record look tampered at the
     next start;
  3. two API clients doing read-modify-write could lose an update: the server checked only its own revision.
Each is reproduced here (the tests fail on the earlier code) and fixed. Then a concurrency test drives parallel
writers, MCP readers and a governed run through the HTTP platform and checks nothing is lost or corrupted.
"""

import io
import json
import os
import sqlite3
import threading
import unittest
from unittest import mock

from autology.mcp import relay
from autology.platform import Platform
from autology.server import ApiError
from autology.store import SCHEMA_VERSION, Store

from .test_gap009_atomic_write_back import FlakyDb
from .test_platform import service
from .test_r2_use_case_lifecycle import close
from .test_scenarios import NEW_ORDER
from .test_workspaces import Client, EX, TOKENS, data_admins, simulate_all


def sql(path, statement, *args):
    db = sqlite3.connect(path)
    db.execute(statement, args)
    db.commit()
    db.close()


class ScenarioCommitTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}
        self.sid = self.svc.create_scenario(self.u["olivia"], {"edits": [
            {"op": "set", "id": "O-1", "attributes": {"amount": 5}}, NEW_ORDER]})["scenario_id"]

    def tearDown(self):
        self.svc.close()

    def commit(self):
        return self.svc.commit_scenario(self.u["admin"], self.sid)

    def test_a_commit_writes_every_record_in_one_go_with_new_revisions(self):
        before = self.svc.revisions["O-1"]
        done = self.commit()
        self.assertEqual(sorted(done["written"]), ["O-1", "O-6"])
        self.assertEqual(self.svc.store.read_instance("O-1")["revision"], before + 1)
        self.assertEqual(self.svc.revisions["O-1"], before + 1)
        self.assertEqual((self.svc.store.tampered_instances(), self.svc.store.instance_set_problem()), ([], None))

    def test_a_commit_never_overwrites_a_tampered_record(self):
        sql(self.svc.store.path, "UPDATE instances SET attributes=json_set(attributes, '$.quantity', 77) WHERE id='O-1'")
        with self.assertRaises(ApiError) as ctx:
            self.commit()
        self.assertEqual((ctx.exception.status, ctx.exception.extra["tampered"]), (409, True))
        self.assertEqual(self.svc.store.read_instance("O-1")["attributes"]["quantity"], 77)  # left for review
        self.assertNotIn("O-6", self.svc.graph._instances)  # nothing applied in memory either
        self.assertIsNone(self.svc.store.read_instance("O-6"))

    def test_a_commit_over_a_stale_record_is_refused_and_the_record_reloaded(self):
        other = Store(self.svc.store.path, audit_key=self.svc.audit_key)  # a legitimate writer elsewhere
        row = other.read_instance("O-1")
        other.upsert_instance(row["type"], "O-1", {**row["attributes"], "quantity": 9})
        other.close()
        with self.assertRaises(ApiError) as ctx:
            self.commit()
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.svc.store.read_instance("O-1")["attributes"]["amount"],
                         self.svc.graph.get("O-1").attributes["amount"])  # reloaded: memory = store
        self.assertEqual(self.svc.graph.get("O-1").attributes["quantity"], 9)

    def test_a_failure_during_the_commit_leaves_nothing_half_done(self):
        real = self.svc.store._db
        self.svc.store._db = FlakyDb(real, "INSERT INTO instances", 2)  # the second record's write fails
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.commit()
        finally:
            self.svc.store._db = real
        self.assertIsNone(self.svc.store.read_instance("O-6"))
        self.assertNotEqual(self.svc.store.read_instance("O-1")["attributes"]["amount"], 5)
        self.assertNotIn("O-6", self.svc.graph._instances)
        self.assertNotEqual(self.svc.graph.get("O-1").attributes["amount"], 5)
        self.assertEqual(self.commit()["status"], "committed")  # nothing was half-applied: it can be retried


class MigrationRestartTests(unittest.TestCase):
    def schema_13_store(self):
        svc = service(automations={}, chat=None)
        path = svc.store.path
        svc.close()
        db = sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE old_i AS SELECT id, type, attributes, updated_at FROM instances;
            DROP TABLE instances; ALTER TABLE old_i RENAME TO instances;
            DELETE FROM meta WHERE key='instances_digest';
            UPDATE meta SET value='13' WHERE key='schema_version';""")
        db.commit()
        db.close()
        return path

    def test_an_interrupted_upgrade_is_rolled_back_and_run_again(self):
        path = self.schema_13_store()
        with mock.patch.object(Store, "_set_digest", side_effect=RuntimeError("power cut")):
            with self.assertRaises(RuntimeError):
                Store(path)
        db = sqlite3.connect(path)
        self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "13")
        self.assertNotIn("revision", [r[1] for r in db.execute("PRAGMA table_info(instances)")])  # old schema intact
        db.close()
        store = Store(path)  # the next start runs the whole upgrade again
        self.assertEqual(store._query("SELECT value FROM meta WHERE key='schema_version'")[0]["value"],
                         str(SCHEMA_VERSION))
        self.assertEqual(store.tampered_instances(), [])
        self.assertIsNone(store.instance_set_problem())
        store.close()


class ClientRevisionTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.admin = next(u for u in self.svc.users if "admin" in u.permissions)

    def tearDown(self):
        self.svc.close()

    def test_two_clients_cannot_lose_each_others_update(self):
        read_a = self.svc.get_object(self.admin, "O-1") if hasattr(self.svc, "get_object") else \
            self.svc.object_view(self.svc.graph.get("O-1"), self.admin)
        read_b = dict(read_a)
        attrs = {k: v for k, v in read_a["attributes"].items() if v is not None}
        self.svc.upsert_object(self.admin, {"type": "Order", "id": "O-1", "expected_revision": read_a["revision"],
                                            "attributes": {**attrs, "amount": 111}})
        with self.assertRaises(ApiError) as ctx:  # B read the same revision: its write would lose A's
            self.svc.upsert_object(self.admin, {"type": "Order", "id": "O-1", "expected_revision": read_b["revision"],
                                                "attributes": {**attrs, "quantity": 2}})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.extra["revision"], read_a["revision"] + 1)
        self.assertEqual(ctx.exception.extra["current"]["attributes"]["amount"], 111)
        self.assertEqual(self.svc.store.read_instance("O-1")["attributes"]["amount"], 111)
        with self.assertRaises(ApiError) as ctx:  # "must not exist yet" for an existing record
            self.svc.upsert_object(self.admin, {"type": "Order", "id": "O-1", "expected_revision": 0,
                                                "attributes": attrs})
        self.assertEqual(ctx.exception.status, 409)
        for bad in (-1, "3", True, 1.5):
            with self.assertRaises(ApiError) as ctx:
                self.svc.upsert_object(self.admin, {"type": "Order", "id": "O-1", "expected_revision": bad,
                                                    "attributes": attrs})
            self.assertEqual(ctx.exception.status, 400)


class ConcurrencyTests(unittest.TestCase):
    """Parallel writers, MCP readers and a governed run through the HTTP platform, at the same time."""

    def test_concurrent_requests_lose_nothing_and_corrupt_nothing(self):
        os.environ.update(TOKENS)
        import tempfile

        spec = data_admins(json.loads((EX / "platform.json").read_text()))
        spec["data_dir"] = tempfile.mkdtemp()
        pf = simulate_all(Platform(spec, EX))
        c = Client(pf)
        svc = pf.workspaces["acme"].use_cases["claims"].service
        start_amount = svc.graph.get("CL-3").attributes["amount"]
        start_revision = svc.revisions["CL-3"]
        writers, increments, errors, conflicts = 6, 5, [], []

        def writer():
            done = 0
            while done < increments:
                status, obj = c.call("GET", "/w/acme/u/claims/api/objects/CL-3", "acme-ada")
                if status != 200:
                    errors.append(("read", status))
                    return
                attrs = {k: v for k, v in obj["attributes"].items() if v is not None}
                status, out = c.call("POST", "/w/acme/u/claims/api/objects", "acme-ada", {
                    "type": "Claim", "id": "CL-3", "expected_revision": obj["revision"],
                    "attributes": {**attrs, "amount": attrs["amount"] + 1}})
                if status == 200:
                    done += 1
                elif status == 409:
                    conflicts.append(1)  # someone else won this revision: read again and retry
                else:
                    errors.append(("write", status, out))
                    return

        def mcp_reader():
            for _ in range(5):
                out = io.StringIO()
                stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                    "name": "list_objects", "arguments": {"type": "Claim"}}}) + "\n")
                relay(c.base + "/w/acme/u/claims", "acme-hana", stdin, out)
                reply = json.loads(out.getvalue())
                if "result" not in reply:
                    errors.append(("mcp", reply))

        def runner():
            status, run = c.call("POST", "/w/acme/u/claims/api/runs", "acme-hana",
                                 {"case_template": "claim_case", "root": "CL-1"})
            if status != 200 or run["status"] != "completed":
                errors.append(("run", status, run.get("status")))

        threads = [threading.Thread(target=writer) for _ in range(writers)]
        threads += [threading.Thread(target=mcp_reader) for _ in range(2)] + [threading.Thread(target=runner)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(120)
            self.assertEqual(errors, [])
            total = writers * increments
            row = svc.store.read_instance("CL-3")
            self.assertEqual(row["attributes"]["amount"], start_amount + total)  # no lost update
            # every write exactly once: the writers' increments plus any governed run that wrote CL-3 back (the
            # claims automation settles a claim when it changes); both are counted from their own records
            run_writes = sum(1 for r in svc.store.list_runs(limit=100)
                             for e in svc.store.write_back_log(r["run_id"])
                             if e["outcome"] == "committed" and "CL-3" in e["instances"])
            print(f"\n  concurrency: {total} increments, {len(conflicts)} refused stale writes retried, "
                  f"{run_writes} run write-back(s) on CL-3")
            self.assertEqual(row["revision"], start_revision + total + run_writes)
            self.assertEqual(svc.graph.get("CL-3").attributes["amount"], start_amount + total)  # memory = store
            self.assertGreater(len(conflicts), 0)  # the race really happened and was refused, not lost
            self.assertEqual((svc.store.tampered_instances(), svc.store.instance_set_problem()), ([], None))
            for iid, inst in svc.graph._instances.items():  # every record in memory equals the stored one
                stored = svc.store.read_instance(iid)
                self.assertEqual({k: v for k, v in stored["attributes"].items() if v is not None},
                                 {k: v for k, v in inst.attributes.items() if v is not None}, iid)
            self.assertEqual(len(svc.store._query("SELECT * FROM writer_lease")), 1)  # still one writer
        finally:
            c.server.shutdown()
            c.server.server_close()
            close(pf)


if __name__ == "__main__":
    unittest.main()
