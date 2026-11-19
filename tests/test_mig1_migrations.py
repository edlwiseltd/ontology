"""MIG-1 (audit GAP-041): schema upgrades of the engine store are versioned, ordered and transactional.

  M1 stores at representative older schemas (3, 10, 13) upgrade to the current one: only the steps above their
     version run, in ascending order, and are recorded in the ledger; runs, audit chains, records, reviews and logs
     are all still there and verify
  M2 an upgrade interrupted at any step leaves the old schema intact (version, columns, even the new tables), and
     the next start runs it again
  M3 an upgrade whose result does not match the expected schema changes nothing
  M4 incompatible states are refused: a newer store, a store that claims the current version but lacks a column,
     steps that are not in ascending order
  M5 re-opening applies nothing; a step finds what is already there and leaves it
  M6 a new store has an empty ledger; the schema's statements (triggers included) are split correctly
"""

import contextlib
import os
import sqlite3
import unittest
from unittest import mock

from autology import migrations
from autology.store import SCHEMA, SCHEMA_VERSION, Store, StoreError

from .test_ingest import service

# what each later schema added, newest first: undoing these turns a current store into an older one
ADDED = [(14, ["ALTER TABLE instances DROP COLUMN seal", "ALTER TABLE instances DROP COLUMN revision",
               "DELETE FROM meta WHERE key='instances_digest'"]),
         (13, ["ALTER TABLE run_sources DROP COLUMN wb_state", "ALTER TABLE run_sources DROP COLUMN wb_version"]),
         (12, ["ALTER TABLE runs DROP COLUMN run_key"]),
         (11, ["ALTER TABLE runs DROP COLUMN seal"]),
         (6, ["ALTER TABLE audit DROP COLUMN alg"]),
         (5, ["ALTER TABLE automation_state DROP COLUMN failures", "ALTER TABLE run_sources DROP COLUMN conflicts",
              "ALTER TABLE run_sources DROP COLUMN base"]),
         (4, ["ALTER TABLE runs DROP COLUMN started_by"])]
LATER_TABLES = ["model_drafts", "schema_migrations"]


def populated():
    """A current store with runs (one completed, one awaiting review), audit chains, records and logs."""
    # without an audit key (a store older than keyed audit entries) the engine starts only as a test server
    svc = service(automations={}, pipelines={}, simulation=not os.environ.get("AUTOLOGY_AUDIT_KEY"))
    users = {u.name: u for u in svc.users}
    done = svc.start_run(users["hana"], {"case_template": "claim_case", "root": "CL-1"})
    waiting = svc.start_run(users["hana"], {"case_template": "claim_case", "root": "CL-2"})
    svc.log_access(users["hana"], "http", "GET /api/v1/me", 200)
    path = svc.store.path
    svc.close()
    return path, done["run_id"], waiting["run_id"]


def downgrade(path, version):
    """Make the store look as schema ``version`` left it (columns and tables added later are gone)."""
    db = sqlite3.connect(path)
    for added_in, undo in ADDED:
        if added_in > version:
            for statement in undo:
                db.execute(statement)
    for table in LATER_TABLES:
        db.execute(f"DROP TABLE IF EXISTS {table}")
    db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(version),))
    db.commit()
    db.close()


@contextlib.contextmanager
def before_keyed_audit():
    """Schemas before 6 had no keyed audit entries: a store of that age was written without an audit key, so the
    tests build and upgrade it that way (its entries are plain SHA-256 and stay so)."""
    with mock.patch.dict(os.environ):
        os.environ.pop("AUTOLOGY_AUDIT_KEY", None)
        yield


def snapshot(path):
    db = sqlite3.connect(path)
    try:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1")]
        return {"version": db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0],
                "tables": tables, "columns": {t: sorted(migrations.columns(db, t)) for t in tables},
                "rows": {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}}
    finally:
        db.close()


class MigrationTests(unittest.TestCase):
    def test_older_stores_upgrade_in_order_and_keep_everything(self):  # M1, M5
        for old in (3, 10, 13):
            with self.subTest(schema=old), (before_keyed_audit() if old < 6 else contextlib.nullcontext()):
                path, done, waiting = populated()
                downgrade(path, old)
                before = snapshot(path)
                store = Store(path)
                self.addCleanup(store.close)
                expected = [v for v, _, _ in migrations.MIGRATIONS if v > old]
                self.assertEqual(store.migrated, expected)
                self.assertEqual(expected, sorted(expected))
                history = store.migration_history()
                self.assertEqual([(h["version"], h["from_version"]) for h in history], [(v, old) for v in expected])
                after = snapshot(path)
                self.assertEqual(after["version"], str(SCHEMA_VERSION))
                self.assertEqual(migrations.layout_problems(store._db, SCHEMA), [])
                for table, count in before["rows"].items():  # nothing was dropped or lost
                    if table != "meta":
                        self.assertEqual(after["rows"][table], count, table)
                self.assertTrue(store.verify_audit(done))
                self.assertTrue(store.verify_audit(waiting))
                self.assertTrue(store.seal_ok(done))
                self.assertEqual(store.tampered_instances(), [])
                self.assertIsNone(store.instance_set_problem())
                self.assertEqual(store.load_run(done).status, "completed")
                self.assertEqual(len(store.list_reviews("pending")), 1)
                self.assertTrue(store.access_log(limit=5))
                store.close()
                again = Store(path)  # a second start has nothing to do
                self.assertEqual((again.migrated, len(again.migration_history())), ([], len(expected)))
                again.close()

    def test_an_upgrade_interrupted_at_any_step_changes_nothing(self):  # M2
        unkeyed = before_keyed_audit()
        unkeyed.__enter__()
        self.addCleanup(unkeyed.__exit__, None, None, None)
        path, done, _ = populated()
        downgrade(path, 3)
        before = snapshot(path)
        for index, (version, description, real) in enumerate(migrations.MIGRATIONS):
            def crash(store, db, real=real):
                real(store, db)  # the step did its work, then the process died before the commit
                raise RuntimeError("power cut")
            steps = list(migrations.MIGRATIONS)
            steps[index] = (version, description, crash)
            with self.subTest(step=version), mock.patch.object(migrations, "MIGRATIONS", steps):
                with self.assertRaises(RuntimeError):
                    Store(path)
                self.assertEqual(snapshot(path), before)  # version, tables, columns and rows: all as they were
        store = Store(path)  # the next start runs the whole upgrade again
        self.addCleanup(store.close)
        self.assertEqual(store.migrated, [v for v, _, _ in migrations.MIGRATIONS if v > 3])
        self.assertTrue(store.verify_audit(done))
        self.assertEqual(store.tampered_instances(), [])

    def test_a_result_that_does_not_match_the_schema_changes_nothing(self):  # M3
        path, _, _ = populated()
        downgrade(path, 10)
        before = snapshot(path)
        steps = [(v, d, (lambda store, db: None) if v == 12 else fn) for v, d, fn in migrations.MIGRATIONS]
        with mock.patch.object(migrations, "MIGRATIONS", steps):
            with self.assertRaises(StoreError) as caught:
                Store(path)
        self.assertIn("runs lacks column(s) run_key", str(caught.exception))
        self.assertIn("nothing was changed", str(caught.exception))
        self.assertEqual(snapshot(path), before)

    def test_incompatible_states_are_refused(self):  # M4
        path, _, _ = populated()
        db = sqlite3.connect(path)
        db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION + 1),))
        db.commit()
        db.close()
        with self.assertRaises(StoreError) as caught:
            Store(path)
        self.assertIn("newer than this Autology", str(caught.exception))
        path, _, _ = populated()
        db = sqlite3.connect(path)
        db.execute("ALTER TABLE runs DROP COLUMN run_key")  # the version still says "current"
        db.commit()
        db.close()
        with self.assertRaises(StoreError) as caught:
            Store(path)
        self.assertIn("does not match it", str(caught.exception))
        self.assertIn("run_key", str(caught.exception))
        path, _, _ = populated()
        downgrade(path, 13)
        with mock.patch.object(migrations, "MIGRATIONS", list(reversed(migrations.MIGRATIONS))):
            with self.assertRaises(StoreError) as caught:
                Store(path)
        self.assertIn("ascending order", str(caught.exception))
        self.assertEqual(snapshot(path)["version"], "13")

    def test_a_step_leaves_what_is_already_there(self):  # M5
        path, done, _ = populated()
        downgrade(path, 11)
        db = sqlite3.connect(path)
        db.execute("ALTER TABLE runs ADD COLUMN run_key TEXT")  # someone already added what step 12 adds
        db.execute("UPDATE runs SET run_key='kept' WHERE run_id=?", (done,))
        db.commit()
        db.close()
        store = Store(path)
        self.addCleanup(store.close)
        self.assertEqual(store.migrated, [12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22])
        self.assertEqual(store._query("SELECT run_key FROM runs WHERE run_id=?", (done,))[0]["run_key"], "kept")

    def test_a_new_store_and_the_statement_splitter(self):  # M6
        store = Store(":memory:")
        self.addCleanup(store.close)
        self.assertEqual((store.migrated, store.migration_history()), ([], []))
        self.assertEqual(migrations.layout_problems(store._db, SCHEMA), [])
        parts = migrations.statements(SCHEMA)
        self.assertEqual(sum(p.upper().startswith("CREATE TRIGGER") for p in parts), SCHEMA.upper().count("CREATE TRIGGER"))
        self.assertTrue(all(sqlite3.complete_statement(p) for p in parts))
        self.assertEqual(migrations.statements("SELECT 1;\nSELECT 2"), ["SELECT 1;", "SELECT 2"])
        versions = [v for v, _, _ in migrations.MIGRATIONS]
        self.assertEqual((versions, versions[-1]), (sorted(set(versions)), SCHEMA_VERSION))


if __name__ == "__main__":
    unittest.main()
