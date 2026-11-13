"""Tier 3: the governed reporting database for BI tools, and Prometheus metrics."""

import io
import json
import os
import re
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from autology.__main__ import main as cli
from autology.server import ApiError
from autology.warehouse import build_tables, export_reporting, table_name

from . import test_platform
from .test_ingest import EX as INSURANCE, TOKENS, service as insurance_service
from .test_platform import _Api, add_big_order


def rows(db, sql):
    return db.execute(sql).fetchall()


class InsuranceReportingTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.svc = insurance_service(reporting={"target": str(self.dir / "reporting.db"), "roles": ["claims_handler"]})
        self.u = {x.name: x for x in self.svc.users}
        self.svc.run_pipeline(self.u["etl"], "claims_feed", {})
        run = self.svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-2"})
        self.svc.decide(self.u["ivan"], run["pending_review"], {"approved": True, "comment": "photos check out"})
        self.svc.record_outcome(self.u["maria"], run["run_id"], {"action": "assess_fraud", "label": "fine",
                                                                 "good": True, "note": "secret note"})

    def test_tables_types_and_contents(self):
        meta = self.svc.refresh_reporting()
        db = sqlite3.connect(self.dir / "reporting.db")
        self.assertEqual(table_name("RepairShop"), "obj_repair_shop")
        cols = [r[1] for r in rows(db, "PRAGMA table_info(obj_claim)")]
        self.assertEqual(cols[:3], ["id", "status", "amount"])
        self.assertEqual(rows(db, "SELECT amount, reported_days_after FROM obj_claim WHERE id='CL-4'"), [(1850.0, 1)])
        self.assertEqual(rows(db, "SELECT approved_network FROM obj_repair_shop ORDER BY id"), [(1,), (0,)])
        self.assertIn(("CL-4", "against", "P-4", "Claim", "Policy"), rows(db, "SELECT * FROM links"))
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM runs")[0][0], 2)  # CL-4 settled by automation, CL-2
        self.assertEqual(rows(db, "SELECT status, approved FROM reviews ORDER BY created_at"),
                         [("approved", 1), ("pending", None)])
        self.assertEqual(rows(db, "SELECT label, good FROM outcomes"), [("fine", 1)])
        self.assertEqual(rows(db, "SELECT rejected FROM ingest_batches"), [(3,)])
        self.assertEqual(rows(db, "SELECT COUNT(*) FROM automation_firings")[0][0], 1)
        export = dict(rows(db, "SELECT key, value FROM _export"))
        self.assertEqual(json.loads(export["roles"]), ["claims_handler"])
        self.assertEqual(meta["rows"]["obj_claim"], 4)

    def test_pii_and_free_text_stay_out(self):
        self.svc.refresh_reporting()
        db = sqlite3.connect(self.dir / "reporting.db")
        policy_cols = [r[1] for r in rows(db, "PRAGMA table_info(obj_policy)")]
        self.assertNotIn("holder", policy_cols)  # pii, left out by default
        everything = " ".join(str(v) for t in rows(db, "SELECT name FROM sqlite_master WHERE type='table'")
                              for row in rows(db, f'SELECT * FROM "{t[0]}"') for v in row)
        for secret in ("Ana Ruiz", "photos check out", "secret note"):
            self.assertNotIn(secret, everything)
        meta = json.loads(dict(rows(db, "SELECT key, value FROM _export"))["left_out_fields"])
        self.assertEqual(meta, {"Policy.holder": "sensitivity pii"})
        # an explicit opt-in brings a field back
        export_reporting(self.svc, str(self.dir / "with.db"), ["claims_handler"], include_fields=["Policy.holder"])
        db2 = sqlite3.connect(self.dir / "with.db")
        self.assertIn(("Ana Ruiz",), rows(db2, "SELECT holder FROM obj_policy"))

    def test_atomic_replace_and_scheduled_refresh(self):
        target = self.dir / "reporting.db"
        target.write_text("old")
        self.svc.reporting["every"] = 3600
        out = self.svc.tick()  # the automation also settles the other reported claims in this pass
        self.assertEqual(out["reporting"]["runs"], len(self.svc.store.list_runs(limit=100)))
        self.assertNotIn("reporting", self.svc.tick())  # not due again within the hour
        self.assertEqual([p.name for p in self.dir.iterdir()], ["reporting.db"])  # no temporary files left
        sqlite3.connect(target).execute("SELECT * FROM runs")
        os.chmod(target, 0o640)
        self.svc.refresh_reporting()
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)  # a refresh keeps the file's permissions

    def test_new_file_is_readable_by_other_users(self):
        # a BI tool (e.g. Metabase in a container) usually runs as another user
        old = os.umask(0o022)
        try:
            self.svc.refresh_reporting()
        finally:
            os.umask(old)
        self.assertEqual((self.dir / "reporting.db").stat().st_mode & 0o777, 0o644)

    def test_admin_route_and_cli(self):
        api = _Api(self.svc)
        self.addCleanup(api.server.shutdown)
        status, body, _ = api.call("POST", "/api/reporting", TOKENS["admin"], {})
        self.assertEqual((status, body["rows"]["runs"]), (200, 2))
        status, _, _ = api.call("POST", "/api/reporting", TOKENS["hana"], {})
        self.assertEqual(status, 403)
        cfg = json.loads((INSURANCE / "server.json").read_text())
        cfg.update(store=self.svc.store.path, automations={})
        path = INSURANCE / f"_test_reporting_{os.getpid()}.json"
        path.write_text(json.dumps(cfg))
        self.addCleanup(path.unlink)
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli(["reporting", str(path), "--out", str(self.dir / "cli.db"),
                                  "--roles", "claims_handler"]), 0)
        self.assertIn("left out Policy.holder: sensitivity pii", out.getvalue())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli(["reporting", str(path)]), 1)  # no target configured or given

    def test_configuration_errors(self):
        for bad in ({"target": 5}, {"target": {"driver": "psycopg"}}, {"target": "r.db", "include_fields": ["X.y"]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                insurance_service(reporting=bad)
        svc = insurance_service()
        with self.assertRaises(ApiError):
            svc.refresh_reporting()


class AudienceTests(unittest.TestCase):
    """Row, field and checkpoint rules decide what a dashboard audience gets, as for an API user."""

    def setUp(self):
        self.svc = test_platform.service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}
        self.svc.start_run(self.u["olivia"], add_big_order(self.svc))  # a US contract

    def test_row_access_hides_records_and_their_runs(self):
        admin_view = {t.name: t for t in build_tables(self.svc, ["ops", "eu_ops", "finance"])[0]}
        ops_tables, meta = build_tables(self.svc, ["ops"])
        ops_view = {t.name: t for t in ops_tables}
        eu_orders = {r[0] for r in admin_view["obj_order"].rows} - {r[0] for r in ops_view["obj_order"].rows}
        self.assertTrue(eu_orders)  # EU orders exist, and the ops-only audience does not get them
        self.assertEqual(meta["hidden_records"], len(eu_orders))
        self.assertFalse(any(s in eu_orders or t in eu_orders for s, _, t, _, _ in ops_view["links"].rows))

    def test_gated_and_role_restricted_fields(self):
        tables, meta = build_tables(self.svc, ["finance"])
        customer = {t.name: t for t in tables}["obj_customer"]
        self.assertNotIn("credit_limit", [c for c, _ in customer.columns])  # checkpoint-gated: needs a reason
        self.assertEqual(meta["left_out_fields"]["Customer.credit_limit"], "checkpoint")
        tables, meta = build_tables(self.svc, ["ops"], include_fields=["Customer.credit_limit"])
        customer = {t.name: t for t in tables}["obj_customer"]
        index = [c for c, _ in customer.columns].index("credit_limit")
        self.assertTrue(all(r[index] is None for r in customer.rows))  # data_access: finance only
        self.assertEqual(meta["left_out_fields"]["Customer.credit_limit"], "data_access (some records)")


@unittest.skipUnless(os.environ.get("AUTOLOGY_TEST_PG_DSN"), "set AUTOLOGY_TEST_PG_DSN (CI runs PostgreSQL)")
class PostgresReportingTests(unittest.TestCase):
    def test_export_to_postgres(self):
        import psycopg

        svc = insurance_service()
        etl = next(u for u in svc.users if u.name == "etl")
        svc.run_pipeline(etl, "claims_feed", {})
        meta = export_reporting(svc, {"driver": "psycopg", "dsn_env": "AUTOLOGY_TEST_PG_DSN"}, ["claims_handler"])
        self.assertEqual(meta["rows"]["obj_claim"], 4)
        with psycopg.connect(os.environ["AUTOLOGY_TEST_PG_DSN"]) as db:
            self.assertEqual(db.execute("SELECT approved_network FROM obj_repair_shop ORDER BY id").fetchall(),
                             [(True,), (False,)])
            self.assertEqual(db.execute("SELECT amount FROM obj_claim WHERE id='CL-4'").fetchone()[0], 1850.0)


class MetricsTests(unittest.TestCase):
    LINE = re.compile(r'^(# (HELP|TYPE) [a-z_]+ .+|[a-z_]+(\{([a-z_]+="[^"\\]*(\\.[^"\\]*)*",?)*\})? -?[0-9.e+]+)$')

    def test_prometheus_text(self):
        svc = insurance_service()
        u = {x.name: x for x in svc.users}
        svc.run_pipeline(u["etl"], "claims_feed", {})
        svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
        text = svc.metrics(u["admin"])
        for line in text.strip().splitlines():
            self.assertRegex(line, self.LINE)
        for sample in ('autology_reviews_pending{reviewer="special_investigations"} 1',
                       'autology_objects{entity="Claim"} 4',
                       'autology_runs{agent="claims",status="completed"} 1',
                       'autology_ingest_rejected_rows_total{pipeline="claims_feed"} 3',
                       "autology_audit_unverified_runs 0", "autology_agents_suspended 0"):
            self.assertIn(sample, text)
        self.assertNotIn("CL-", text)  # counts only, no record ids
        with self.assertRaises(ApiError) as cm:
            svc.metrics(u["hana"])
        self.assertEqual(cm.exception.status, 403)

    def test_route(self):
        svc = insurance_service()
        api = _Api(svc)
        self.addCleanup(api.server.shutdown)
        status, body, headers = api.call("GET", "/api/metrics", TOKENS["admin"])
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/plain; version=0.0.4"))
        self.assertIn('autology_api_requests_total{status="2xx"}', api.call("GET", "/api/metrics",
                                                                             TOKENS["admin"])[1])


if __name__ == "__main__":
    unittest.main()
