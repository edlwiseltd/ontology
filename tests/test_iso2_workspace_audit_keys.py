"""ISO-2: each workspace's audit chains are keyed with its own key, derived from the platform's."""

import os
import unittest

from autology.audit import KEY_ENV, workspace_key
from autology.store import Store

from .test_workspaces import platform


class WorkspaceAuditKeyTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(os.environ.get(KEY_ENV))  # the suite runs with a platform audit key
        self.pf = platform()
        self.acme = self.pf.workspaces["acme"].use_cases["claims"].service
        self.nw = self.pf.workspaces["northwind"].use_cases["claims"].service
        hana = next(u for u in self.acme.users if u.name == "hana")
        self.run = self.acme.start_run(hana, {"case_template": "claim_case", "root": "CL-1"})

    def test_each_workspace_has_its_own_key(self):
        base = os.environ[KEY_ENV].encode()
        self.assertEqual(self.acme.audit_key, workspace_key(base, "acme"))
        self.assertEqual(self.nw.audit_key, workspace_key(base, "northwind"))
        self.assertNotEqual(self.acme.audit_key, self.nw.audit_key)
        self.assertNotIn(base, (self.acme.audit_key, self.nw.audit_key))
        self.assertTrue(self.acme.health()["audit_keyed"])

    def test_a_chain_verifies_in_its_workspace_only(self):
        rid = self.run["run_id"]
        self.assertTrue(self.acme.store.verify_audit(rid))
        path = self.acme.store.path
        as_northwind = Store(path, audit_key=self.nw.audit_key)  # the same rows, read with Northwind's key
        self.assertFalse(as_northwind.verify_audit(rid))
        with_platform_key = Store(path)  # nor with the platform key itself
        self.assertFalse(with_platform_key.verify_audit(rid))
        entry = self.acme.store.audit_log(rid).to_list()[0]
        self.assertEqual(entry["alg"].split(":")[0], "hmac-sha256")

    def test_a_chain_copied_into_another_workspace_does_not_verify(self):
        rid = self.run["run_id"]
        src, dst = self.acme.store, self.nw.store
        dst._db.execute("ATTACH DATABASE ? AS acme", (src.path,))
        for table in ("runs", "audit", "audit_heads"):
            dst._db.execute(f"INSERT INTO {table} SELECT * FROM acme.{table} WHERE run_id=?", (rid,))
        dst._db.execute("DETACH DATABASE acme")
        self.assertFalse(dst.verify_audit(rid))
        self.nw._verified = (0, 0)
        self.assertEqual(self.nw.unverified_runs(), 1)


if __name__ == "__main__":
    unittest.main()
