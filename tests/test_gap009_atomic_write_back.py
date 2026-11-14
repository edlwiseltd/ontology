"""Audit GAP-009 (rest): a run's local write-back is all or nothing.

Before the fix, a run that changed two fields, one of which had moved on the live record, still wrote the other
one, and each changed record was written in its own transaction, so a failure between two writes left some
records updated and others not. Now the run's whole write set is planned without changing anything, refused as a
whole on any conflict, and committed in one store transaction that first checks every stored record is the one
the server holds; the in-memory graph changes only after the commit. A failed or interrupted write-back changes
nothing and is completed by recovery. These are local records only: effects in other systems keep going through
the external-effects journal, confirmation and reconciliation.
"""

import copy
import json
import sqlite3
import unittest

from autology import Ontology
from autology.graph import KnowledgeGraph, write_back
from autology.state import WorldState
from autology.store import Store

from .test_platform import EX, add_big_order, service


def stored(svc, iid):
    return Store(svc.store.path).load_graph(svc.ontology).get(iid).attributes


class FlakyDb:
    """Delegates to a SQLite connection; raises on the n-th statement that matches ``needle``."""

    def __init__(self, db, needle, n):
        self._db, self.needle, self.n, self.seen = db, needle, n, 0

    def execute(self, sql, *args):
        if self.needle in sql:
            self.seen += 1
            if self.seen == self.n:
                raise sqlite3.OperationalError("disk I/O error (injected)")
        return self._db.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._db, name)


class AtomicWriteBackTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}
        self.run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        self.run_id = self.run["run_id"]

    def tearDown(self):
        self.svc.close()

    def result_changing(self, **changes):
        """The stored run with its state changed on several records: {"K-2": {...}, "O-4": {...}}."""
        result = self.svc.store.load_run(self.run_id)
        for iid, fields in changes.items():
            if iid == "O-4":
                result.state.collections["Order"]["O-4"].update(fields)
            else:
                result.state.entities[{"K-2": "Contract", "C-2": "Customer"}[iid]].update(fields)
        self.svc.store.save_run(result, self.run_id)  # as the service always does before writing back
        return result

    def edit_live(self, iid, **attrs):
        inst = self.svc.graph.get(iid)
        self.svc.upsert_object(self.u["admin"], {"type": inst.type, "id": iid,
                                                 "attributes": {**inst.attributes, **attrs}})

    def write(self, result):
        return self.svc._write_back(self.run_id, result, self.svc.store.run_sources(self.run_id))

    # -- the defect --------------------------------------------------------------------------------------
    def test_two_changed_fields_one_conflicting_neither_is_written(self):
        result = self.result_changing(**{"C-2": {"credit_limit": 600000, "name": "Contoso Power AG"}})
        self.edit_live("C-2", credit_limit=550000)  # someone changed one of the two fields meanwhile
        self.assertEqual(self.write(result), [])
        for attrs in (self.svc.graph.get("C-2").attributes, stored(self.svc, "C-2")):
            self.assertEqual((attrs["credit_limit"], attrs["name"]), (550000, "Contoso Power"))
        status = self.svc.write_back_status(self.run_id)
        self.assertEqual(status["state"], "conflict")
        self.assertEqual([c["attribute"] for c in status["conflicts"]], ["credit_limit"])
        log = self.svc.store.write_back_log(self.run_id)
        self.assertEqual(log[-1]["outcome"], "rejected")
        self.assertEqual(log[-1]["conflicts"][0]["live"], 550000)
        notes = [n for n in self.svc.store.list_notifications(limit=50) if n["kind"] == "conflict"]
        self.assertIn("wrote nothing back", notes[0]["message"])

    def test_the_graph_function_itself_writes_nothing_on_a_conflict(self):
        onto = Ontology.load(EX / "ontology.json")
        graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
        a = graph.get("O-1").attributes
        base = {"O-1": dict(a)}
        state = WorldState.initial(onto, {"Order": [{"id": "O-1", **a, "tracking": "T1", "status": "shipped"}]})
        graph.get("O-1").attributes["status"] = "cancelled"
        changed, conflicts = write_back(graph, state, {"Order": ["O-1"]}, base)
        self.assertEqual((changed, [c["attribute"] for c in conflicts]), ([], ["status"]))
        self.assertNotEqual(graph.get("O-1").attributes.get("tracking"), "T1")

    def test_several_records_commit_together_or_not_at_all(self):
        result = self.result_changing(**{"K-2": {"value": 130000}, "O-4": {"amount": 86000}})
        self.edit_live("O-4", amount=90000)  # a conflict on the second record blocks the first one too
        self.write(result)
        self.assertEqual((stored(self.svc, "K-2")["value"], stored(self.svc, "O-4")["amount"]), (120000, 90000))
        self.edit_live("O-4", amount=85000)  # a person resolves it: the live value is back to what the run read
        status = self.svc.retry_write_back(self.u["admin"], self.run_id)
        self.assertEqual(status["state"], "committed")
        self.assertEqual((stored(self.svc, "K-2")["value"], stored(self.svc, "O-4")["amount"]), (130000, 86000))
        self.assertEqual(self.svc.store.write_back_log(self.run_id)[-1]["instances"],
                         {"K-2": ["value"], "O-4": ["amount"]})

    def test_an_injected_failure_between_two_instance_writes_rolls_everything_back(self):
        result = self.result_changing(**{"K-2": {"value": 130000}, "O-4": {"amount": 86000}})
        real = self.svc.store._db
        self.svc.store._db = FlakyDb(real, "UPDATE instances", 2)  # the second record's write fails
        try:
            self.assertEqual(self.write(result), [])
        finally:
            self.svc.store._db = real
        self.assertEqual((stored(self.svc, "K-2")["value"], stored(self.svc, "O-4")["amount"]), (120000, 85000))
        self.assertEqual((self.svc.graph.get("K-2").attributes["value"],
                          self.svc.graph.get("O-4").attributes["amount"]), (120000, 85000))
        self.assertEqual(self.svc.write_back_status(self.run_id)["state"], "pending")
        self.assertIn(self.run_id, self.svc.store.pending_write_backs())
        done = self.svc.complete_write_backs()  # recovery (start-up and every tick) completes it
        self.assertEqual(done, [{"run_id": self.run_id, "write_back": "committed", "changed": ["K-2", "O-4"]}])
        self.assertEqual((stored(self.svc, "K-2")["value"], stored(self.svc, "O-4")["amount"]), (130000, 86000))

    def test_a_record_changed_just_before_the_commit_refuses_the_whole_set(self):
        result = self.result_changing(**{"K-2": {"value": 130000}, "O-4": {"amount": 86000}})
        original = self.svc.store.commit_write_set

        def racing(*args, **kwargs):  # another writer slips in between the plan and the commit
            db = sqlite3.connect(self.svc.store.path)
            db.execute("UPDATE instances SET attributes=json_set(attributes, '$.amount', 99999) WHERE id='O-4'")
            db.commit()
            db.close()
            return original(*args, **kwargs)

        self.svc.store.commit_write_set = racing
        self.assertEqual(self.write(result), [])
        self.assertEqual((stored(self.svc, "K-2")["value"], stored(self.svc, "O-4")["amount"]), (120000, 99999))
        self.assertEqual(self.svc.graph.get("K-2").attributes["value"], 120000)  # memory unchanged too
        status = self.svc.write_back_status(self.run_id)
        self.assertEqual(status["state"], "conflict")
        self.assertIn("differs from the server's copy", status["conflicts"][0]["reason"])

    def test_duplicate_commit_attempts_change_nothing_more(self):
        result = self.result_changing(**{"K-2": {"value": 130000}})
        self.assertEqual(self.write(result), ["K-2"])
        before = stored(self.svc, "K-2")
        self.assertEqual(self.write(result), [])  # the same write set again: nothing to write, no conflict
        self.assertEqual(self.svc.retry_write_back(self.u["admin"], self.run_id)["state"], "committed")
        self.assertEqual(stored(self.svc, "K-2"), before)
        self.assertEqual(self.svc.write_back_status(self.run_id)["conflicts"], [])

    def test_the_run_summary_says_whether_its_results_are_written(self):
        self.assertEqual(self.run["write_back"], {"state": "committed", "conflicts": 0})
        with self.assertRaises(Exception):
            self.svc.retry_write_back(self.u["olivia"], self.run_id)  # needs the reconcile permission


class InterruptedWriteBackTests(unittest.TestCase):
    def test_a_crash_between_saving_the_run_and_writing_back_is_completed_at_restart(self):
        svc = service(automations={}, chat=None)
        u = {x.name: x for x in svc.users}
        run = svc.start_run(u["olivia"], add_big_order(svc))
        review = svc.list_reviews(u["lena"], "pending")["items"][0]["review_id"]

        def crash(*args, **kwargs):
            raise SystemExit("the process stopped")  # not an ordinary error: nothing catches it

        svc.store.commit_write_set = crash
        with self.assertRaises(SystemExit):
            svc.decide(u["lena"], review, {"approved": True, "comment": "ok"})
        self.assertEqual(svc.store.load_run(run["run_id"]).status, "completed")  # saved, not yet written back
        self.assertNotEqual(stored(svc, "O-4").get("status"), "invoiced")
        path = svc.store.path
        svc.close()
        restarted = service(automations={}, chat=None, store=path)  # start-up runs recovery
        self.assertEqual(restarted.graph.get("O-4").attributes["status"], "invoiced")
        self.assertEqual(stored(restarted, "O-4")["status"], "invoiced")
        self.assertEqual(restarted.write_back_status(run["run_id"])["state"], "committed")
        self.assertEqual(restarted.store.pending_write_backs(), [])
        restarted.close()


class SupersededApprovalTests(unittest.TestCase):
    def test_a_superseded_approval_still_never_acts_and_writes_atomically(self):
        svc = service(automations={}, chat=None)
        u = {x.name: x for x in svc.users}
        run = svc.start_run(u["olivia"], add_big_order(svc))
        review = svc.list_reviews(u["lena"], "pending")["items"][0]["review_id"]
        inst = svc.graph.get("O-4")
        svc.upsert_object(u["admin"], {"type": "Order", "id": "O-4", "attributes": {**inst.attributes,
                                                                                   "status": "cancelled"}})
        done = svc.decide(u["lena"], review, {"approved": True, "comment": "ok"})
        result = svc.store.load_run(run["run_id"])
        self.assertIn("review.superseded", [e.event for e in result.audit])  # ACT-6 unchanged
        self.assertNotIn("ship_order@O-4:done", result.path)
        self.assertEqual(stored(svc, "O-4")["status"], "cancelled")
        self.assertEqual(done["write_back"]["state"], "committed")
        svc.close()


class MigrationTests(unittest.TestCase):
    def test_a_schema_12_store_is_upgraded_without_replaying_or_losing_history(self):
        svc = service(automations={}, chat=None)
        u = {x.name: x for x in svc.users}
        run = svc.start_run(u["olivia"], add_big_order(svc))
        path = svc.store.path
        audit_rows = svc.store._query("SELECT COUNT(*) AS n FROM audit")[0]["n"]
        svc.close()
        db = sqlite3.connect(path)  # make it a schema-12 store, as written by the previous release
        db.executescript("""
            CREATE TABLE old AS SELECT run_id, template, root, sources, write_back, base, conflicts FROM run_sources;
            DROP TABLE run_sources; ALTER TABLE old RENAME TO run_sources;
            DROP TRIGGER write_back_log_no_update; DROP TRIGGER write_back_log_no_delete;
            DROP TABLE write_back_log; UPDATE meta SET value='12' WHERE key='schema_version';""")
        db.commit()
        db.close()
        store = Store(path)
        self.assertEqual(store._query("SELECT value FROM meta WHERE key='schema_version'")[0]["value"], "13")
        self.assertEqual(store.pending_write_backs(), [])  # earlier runs are not written back a second time
        self.assertEqual(store.run_sources(run["run_id"])["wb_state"], "committed")
        self.assertEqual(store._query("SELECT COUNT(*) AS n FROM audit")[0]["n"], audit_rows)
        self.assertTrue(store.verify_audit(run["run_id"]))
        store.record_write_back_conflict(run["run_id"], [], [], None)
        with self.assertRaises(sqlite3.DatabaseError):  # the new log is append-only
            store._db.execute("DELETE FROM write_back_log")
        store.close()


if __name__ == "__main__":
    unittest.main()
