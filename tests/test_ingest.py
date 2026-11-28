"""Tier 3: data ingestion pipelines - sources, type conversion, quality checks, quarantine, watermarks, lineage."""

import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from autology import Ontology
from autology.__main__ import main as cli
from autology.graph import KnowledgeGraph
from autology.ingest import Pipeline, PipelineError, ValueSpec, coerce
from autology.server import ApiError, AutologyService

from .helpers import ROOT
from .test_platform import _Api

EX = ROOT / "examples" / "auto_insurance"
TOKENS = {"hana": "tok-hana", "ivan": "tok-ivan", "maria": "tok-maria", "etl": "tok-etl", "admin": "tok-admin-ai"}


def service(**overrides):
    for name, token in TOKENS.items():
        os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
    cfg = json.loads((EX / "server.json").read_text())
    cfg["store"] = str(Path(tempfile.mkdtemp()) / "claims.db")
    cfg.update(overrides)
    return AutologyService(cfg, EX)


def onto():
    return Ontology.load(EX / "ontology.json")


def graph():
    return KnowledgeGraph.from_dict(onto(), json.loads((EX / "data.json").read_text()))


class ConversionTests(unittest.TestCase):
    def test_coerce(self):
        self.assertEqual(coerce("number", "3200"), 3200)
        self.assertEqual(coerce("number", "18.5"), 18.5)
        self.assertEqual(coerce("integer", "4.0"), 4)
        self.assertIs(coerce("boolean", "Yes"), True)
        self.assertIs(coerce("boolean", "0"), False)
        self.assertEqual(coerce("string", 42), "42")
        self.assertIsNone(coerce("number", None))
        for attr_type, value in (("integer", "4.5"), ("number", "abc"), ("boolean", "maybe"), ("number", "nan"),
                                 ("integer", True), ("string", {"a": 1})):
            with self.subTest(attr_type=attr_type, value=value), self.assertRaises(ValueError):
                coerce(attr_type, value)

    def test_value_specs(self):
        row = {"no": "7", "code": "A", "blank": ""}
        self.assertEqual(ValueSpec.parse("no", "x").read(row), "7")
        self.assertEqual(ValueSpec.parse({"template": "CL-{no}"}, "x").read(row), "CL-7")
        self.assertIsNone(ValueSpec.parse({"template": "CL-{missing}"}, "x").read(row))
        self.assertEqual(ValueSpec.parse({"column": "code", "map": {"A": "active"}}, "x").read(row), "active")
        self.assertEqual(ValueSpec.parse({"column": "blank", "default": 0}, "x").read(row), 0)
        self.assertEqual(ValueSpec.parse({"value": "reported"}, "x").read(row), "reported")
        for bad in ({"template": "{no.__class__}"}, {"template": "{no!r}"}, {"column": "a", "value": 1},
                    {"column": "a", "on": "sometimes"}, {"colum": "a"}, 7):
            with self.subTest(bad=bad), self.assertRaises(PipelineError):
                ValueSpec.parse(bad, "x")


class PipelineDefinitionTests(unittest.TestCase):
    BASE = {"name": "p", "sources": {"s": {"type": "jsonl", "path": "x.jsonl"}},
            "mappings": [{"source": "s", "entity": "Claim", "id": "no", "attributes": {"amount": "amt"}}]}

    def variant(self, **changes):
        spec = json.loads(json.dumps(self.BASE))
        for path, value in changes.items():
            target = spec
            *parents, last = path.split("__")
            for part in parents:
                target = target[int(part)] if part.isdigit() else target[part]
            target[last] = value
        return spec

    def test_valid_and_alias(self):
        Pipeline(self.BASE, onto())
        Pipeline(self.variant(mappings__0__entity="Case"), onto())  # another team's name for Claim

    def test_errors(self):
        cases = {
            "name": dict(name="bad name!"),
            "source type": dict(sources={"s": {"type": "ftp"}}),
            "path": dict(sources={"s": {"type": "csv"}}),
            "inline secret": dict(sources={"s": {"type": "sql", "driver": "psycopg", "query": "SELECT 1"}}),
            "url": dict(sources={"s": {"type": "http", "url": "file:///etc/passwd"}}),
            "entity": dict(mappings__0__entity="Spaceship"),
            "attribute": dict(mappings__0__attributes={"colour": "c"}),
            "source": dict(mappings__0__source="nope"),
            "relationship": dict(mappings__0__links=[{"kind": "flies", "target": "x"}]),
            "check rule": dict(mappings__0__checks=[{"attribute": "amount", "rule": "vibes"}]),
            "check attribute": dict(mappings__0__checks=[{"attribute": "fraud_score", "rule": "required"}]),
            "check value": dict(mappings__0__checks=[{"attribute": "amount", "rule": "min"}]),
            "every": dict(every=0),
            "no mappings": dict(mappings=[]),
        }
        for label, change in cases.items():
            with self.subTest(label), self.assertRaises(PipelineError):
                Pipeline(self.variant(**change), onto())


class PlanTests(unittest.TestCase):
    def plan(self, rows, mapping=None, source=None, g=None):
        spec = {"name": "t", "sources": {"s": source or {"type": "push"}},
                "mappings": [mapping or {"source": "s", "entity": "RepairShop", "id": "id",
                                         "attributes": {"name": "name", "approved_network": "net"}}]}
        pipe = Pipeline(spec, onto())
        g = g or graph()
        return pipe.plan(g, pipe.read({}, {"s": rows} if (source or {"type": "push"})["type"] == "push" else None))

    def test_create_update_unchanged(self):
        plan = self.plan([{"id": "RS-3", "name": "Bay", "net": "yes"},
                          {"id": "RS-1", "name": "Northside Motors", "net": "true"},  # identical to the graph
                          {"id": "RS-2", "name": "QuickFix Garage", "net": "yes"}])  # joins the network
        self.assertEqual(plan.creates["RS-3"], ("RepairShop", {"name": "Bay", "approved_network": True}))
        self.assertEqual(plan.updates, {"RS-2": ("RepairShop", {"approved_network": True})})
        self.assertEqual(plan.unchanged, 1)
        self.assertEqual([e["instance_id"] for e in plan.lineage], ["RS-3", "RS-2"])

    def test_rejections(self):
        plan = self.plan([{"id": "RS-9", "name": "A", "net": "perhaps"},  # not a boolean
                          {"id": "", "name": "B", "net": "no"},  # no id
                          {"id": "CL-1", "name": "C", "net": "no"},  # id of a Claim
                          {"id": "RS-8", "name": "D", "net": "no"},
                          {"id": "RS-8", "name": "E", "net": "no"}])  # duplicate in the batch
        reasons = [r.reason for r in plan.rejected]
        self.assertEqual(len(reasons), 4, reasons)
        self.assertIn("not a boolean", reasons[0])
        self.assertIn("no id", reasons[1])
        self.assertIn("already belongs to a Claim", reasons[2])
        self.assertIn("duplicate id 'RS-8'", reasons[3])
        self.assertEqual(list(plan.creates), ["RS-8"])

    def test_states_and_links(self):
        claim = {"source": "s", "entity": "Claim", "id": "id",
                 "attributes": {"amount": "amt", "status": "st"},
                 "links": [{"kind": "repairedAt", "target": "shop"}]}
        plan = self.plan([{"id": "CL-8", "amt": "10", "st": "lost", "shop": "RS-1"},  # not a state
                          {"id": "CL-9", "amt": "10", "st": "reported", "shop": "P-1"},  # wrong target type
                          {"id": "CL-10", "amt": "10", "st": "reported", "shop": "RS-404"},  # unknown target
                          {"id": "CL-11", "amt": "10", "st": "reported", "shop": "RS-1"}], claim)
        reasons = " | ".join(r.reason for r in plan.rejected)
        self.assertIn("'lost' is not a state of Claim", reasons)
        self.assertIn("no relationship Claim -repairedAt-> Policy", reasons)
        self.assertIn("unknown object 'RS-404'", reasons)
        self.assertEqual(list(plan.creates), ["CL-11"])
        self.assertEqual(plan.links, [("CL-11", "repairedAt", "RS-1")])

    def test_link_to_object_in_same_batch_and_reverse_links(self):
        spec = {"name": "t", "sources": {"s": {"type": "push"}, "c": {"type": "push"}},
                "mappings": [
                    {"source": "c", "entity": "Claim", "id": "id", "attributes": {"amount": "amt"},
                     "links": [{"kind": "repairedAt", "target": "shop"}]},
                    {"source": "s", "entity": "RepairShop", "id": "id", "attributes": {"name": "name"},
                     "links": [{"kind": "repairedAt", "target": "claim", "reverse": True}]}]}
        pipe = Pipeline(spec, onto())
        plan = pipe.plan(graph(), pipe.read({}, {"c": [{"id": "CL-20", "amt": 5, "shop": "RS-7"}],
                                                  "s": [{"id": "RS-7", "name": "New", "claim": "CL-1"}]}))
        self.assertEqual(plan.rejected, [])
        self.assertEqual(sorted(plan.links), [("CL-1", "repairedAt", "RS-7"), ("CL-20", "repairedAt", "RS-7")])

    def test_rejected_row_cascades_to_rows_linking_to_it(self):
        spec = {"name": "t", "sources": {"s": {"type": "push"}, "c": {"type": "push"}},
                "mappings": [
                    {"source": "s", "entity": "RepairShop", "id": "id", "attributes": {"approved_network": "net"}},
                    {"source": "c", "entity": "Claim", "id": "id", "attributes": {"amount": "amt"},
                     "links": [{"kind": "repairedAt", "target": "shop"}]}]}
        pipe = Pipeline(spec, onto())
        plan = pipe.plan(graph(), pipe.read({}, {"s": [{"id": "RS-7", "net": "?"}],
                                                  "c": [{"id": "CL-20", "amt": 5, "shop": "RS-7"}]}))
        self.assertEqual(len(plan.rejected), 2)
        self.assertEqual(plan.creates, {})

    def test_checks(self):
        mapping = {"source": "s", "entity": "Claim", "id": "id", "attributes": {"amount": "amt", "damage_type": "d"},
                   "checks": [{"attribute": "amount", "rule": "required"},
                              {"attribute": "amount", "rule": "max", "value": 100000},
                              {"attribute": "damage_type", "rule": "in", "value": ["hail", "theft"]},
                              {"attribute": "damage_type", "rule": "pattern", "value": "[a-z]+"}]}
        plan = self.plan([{"id": "CL-30", "amt": "", "d": "hail"}, {"id": "CL-31", "amt": "500000", "d": "hail"},
                          {"id": "CL-32", "amt": "5", "d": "flood"}, {"id": "CL-33", "amt": "5", "d": "theft"}],
                         mapping)
        reasons = [r.reason for r in plan.rejected]
        self.assertEqual(len(reasons), 3, reasons)
        for reason, expected in zip(reasons, ("amount is required", "amount fails max (500000)",
                                              "damage_type fails in ('flood')")):
            self.assertTrue(reason.endswith(expected), reason)
        self.assertEqual(list(plan.creates), ["CL-33"])


class FileAndDatabaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def pipe(self, source, mapping_extra=None):
        spec = {"name": "t", "sources": {"s": source},
                "mappings": [{"source": "s", "entity": "RepairShop", "id": "id", "attributes": {"name": "name"},
                              **(mapping_extra or {})}]}
        return Pipeline(spec, onto(), self.dir)

    def test_csv_json_jsonl(self):
        (self.dir / "a.csv").write_text("id;name\nRS-5;Five\n", encoding="utf-8")
        (self.dir / "a.json").write_text(json.dumps({"data": {"shops": [{"id": "RS-6", "name": "Six"}]}}))
        (self.dir / "a.jsonl").write_text('{"id": "RS-7", "name": "Seven"}\n\n')
        for source, iid in (({"type": "csv", "path": "a.csv", "delimiter": ";"}, "RS-5"),
                            ({"type": "json", "path": "a.json", "items": "data.shops"}, "RS-6"),
                            ({"type": "jsonl", "path": "a.jsonl"}, "RS-7")):
            with self.subTest(source["type"]):
                pipe = self.pipe(source)
                self.assertEqual(list(pipe.plan(graph(), pipe.read({})).creates), [iid])
        with self.assertRaisesRegex(PipelineError, "cannot read"):
            self.pipe({"type": "csv", "path": "missing.csv"}).read({})
        with self.assertRaisesRegex(PipelineError, "list of records"):
            self.pipe({"type": "json", "path": "a.json", "items": "data"}).read({})

    def staging(self):
        db = sqlite3.connect(self.dir / "staging.db")
        db.execute("CREATE TABLE shops (id TEXT, name TEXT, updated_at TEXT)")
        db.executemany("INSERT INTO shops VALUES (?, ?, ?)",
                       [("RS-5", "Five", "2026-01-01"), ("RS-6", "Six", "2026-01-02")])
        db.commit()
        return db

    def test_sql_incremental(self):
        db = self.staging()
        source = {"type": "sql", "database": "staging.db",
                  "query": "SELECT * FROM shops WHERE updated_at > {watermark} ORDER BY updated_at",
                  "incremental": {"column": "updated_at", "initial": ""}}
        pipe = self.pipe(source)
        plan = pipe.plan(graph(), pipe.read({}))
        self.assertEqual((list(plan.creates), plan.watermarks), (["RS-5", "RS-6"], {"s": "2026-01-02"}))
        db.execute("INSERT INTO shops VALUES ('RS-7', 'Seven', '2026-01-03')")
        db.commit()
        self.assertEqual([r["id"] for r in pipe.read({"s": "2026-01-02"}).rows["s"]], ["RS-7"])
        with self.assertRaisesRegex(PipelineError, "query failed"):
            self.pipe({"type": "sql", "database": "staging.db", "query": "SELECT * FROM nope"}).read({})
        with self.assertRaisesRegex(PipelineError, "does not exist"):
            self.pipe({"type": "sql", "database": "other.db", "query": "SELECT 1"}).read({})

    def test_any_db_api_driver(self):
        self.staging()
        os.environ["TEST_STAGING_DSN"] = str(self.dir / "staging.db")
        pipe = self.pipe({"type": "sql", "driver": "sqlite3", "dsn_env": "TEST_STAGING_DSN",
                          "query": "SELECT id, name FROM shops WHERE updated_at > {watermark}",
                          "incremental": {"column": "updated_at", "initial": "2026-01-01"}})
        self.assertEqual([r["id"] for r in pipe.read({}).rows["s"]], ["RS-6"])
        del os.environ["TEST_STAGING_DSN"]
        with self.assertRaisesRegex(PipelineError, "TEST_STAGING_DSN is not set"):
            pipe.read({})

    def test_http_with_pages_and_secret_header(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):  # noqa: N802
                seen.append(self.headers.get("Authorization"))
                port = self.server.server_port
                pages = {"/shops": {"items": [{"id": "RS-5", "name": "Five"}],
                                    "next": f"http://127.0.0.1:{port}/shops?page=2"},
                         "/shops?page=2": {"items": [{"id": "RS-6", "name": "Six"}], "next": None}}
                data = json.dumps(pages[self.path]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        os.environ["TEST_SHOPS_KEY"] = "s3cret"
        self.addCleanup(os.environ.pop, "TEST_SHOPS_KEY")
        pipe = self.pipe({"type": "http", "url": f"http://127.0.0.1:{server.server_port}/shops", "items": "items",
                          "next": "next", "headers": {"Authorization": {"env": "TEST_SHOPS_KEY", "prefix": "Bearer "}}})
        self.assertEqual([r["id"] for r in pipe.read({}).rows["s"]], ["RS-5", "RS-6"])
        self.assertEqual(seen, ["Bearer s3cret", "Bearer s3cret"])


@unittest.skipUnless(os.environ.get("AUTOLOGY_TEST_PG_DSN"), "set AUTOLOGY_TEST_PG_DSN to a PostgreSQL database "
                                                           "(CI runs one)")
class PostgresSourceTests(unittest.TestCase):
    """A real PostgreSQL through psycopg: pyformat parameters, numeric and timestamp columns, watermarks."""

    def test_incremental_load_from_postgres(self):
        import psycopg

        dsn = os.environ["AUTOLOGY_TEST_PG_DSN"]
        with psycopg.connect(dsn) as db:
            db.execute("DROP TABLE IF EXISTS autology_test_claims")
            db.execute("CREATE TABLE autology_test_claims (claim_no INT, amount NUMERIC(12, 2), days INT, "
                       "updated_at TIMESTAMPTZ)")
            db.execute("INSERT INTO autology_test_claims VALUES (40, 1850.50, 2, '2026-11-10T09:00:00Z'), "
                       "(41, 900, 1, '2026-11-10T10:00:00Z')")
        spec = {"name": "pg", "sources": {"claims": {
                    "type": "sql", "driver": "psycopg", "dsn_env": "AUTOLOGY_TEST_PG_DSN",
                    "query": "SELECT * FROM autology_test_claims WHERE updated_at > {watermark} ORDER BY updated_at",
                    "incremental": {"column": "updated_at", "initial": "1970-01-01T00:00:00Z"}}},
                "mappings": [{"source": "claims", "entity": "Claim", "id": {"template": "CL-{claim_no}"},
                              "attributes": {"amount": "amount", "reported_days_after": "days"}}]}
        pipe = Pipeline(spec, onto())
        plan = pipe.plan(graph(), pipe.read({}))
        self.assertEqual(plan.creates["CL-40"][1], {"amount": 1850.5, "reported_days_after": 2})
        mark = plan.watermarks["claims"]
        with psycopg.connect(dsn) as db:
            db.execute("INSERT INTO autology_test_claims VALUES (42, 10, 0, '2026-11-11T08:00:00Z')")
        self.assertEqual([r["claim_no"] for r in pipe.read({"claims": mark}).rows["claims"]], [42])
        with psycopg.connect(dsn) as db:
            db.execute("DROP TABLE autology_test_claims")


class ServiceIngestTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})
        self.u = {x.name: x for x in self.svc.users}

    def run_feed(self, **body):
        return self.svc.run_pipeline(self.u["etl"], "claims_feed", body)

    def test_dry_run_writes_nothing(self):
        before = self.svc.store.count_instances()
        out = self.run_feed(dry_run=True)
        self.assertEqual((out["created"], out["rejected"]), (3, 3))
        self.assertEqual(self.svc.store.count_instances(), before)
        self.assertNotIn("CL-4", self.svc.graph._instances)
        self.assertEqual(self.svc.store.ingest_watermarks("claims_feed"), {})
        self.assertEqual(self.svc.store.ingest_batches("claims_feed")[0]["status"], "dry_run")

    def test_load_quarantine_lineage_and_watermark(self):
        out = self.run_feed()
        self.assertEqual((out["created"], out["updated"], out["unchanged"], out["rejected"]), (3, 0, 1, 3))
        self.assertIn("CL-4", self.svc.graph._instances)
        self.assertEqual(self.svc.store.load_graph(self.svc.ontology).get("CL-4").attributes["amount"], 1850)
        self.assertEqual(self.svc.graph.get("P-5").attributes["status"], "lapsed")
        batch = self.svc.ingest_batch(self.u["etl"], out["batch_id"])
        self.assertEqual(sorted(r["reason"] for r in batch["rejects"])[0], "Claim: a claim amount cannot be negative (-40)")
        lineage = self.svc.object_lineage(self.u["hana"], "CL-4")["loads"]
        self.assertEqual((lineage[0]["source"], lineage[0]["action"]), ("claims", "created"))
        self.assertIn("against:P-4", lineage[0]["links"])
        # the watermark stops before the first rejected claim, so it is read again once fixed
        self.assertEqual(out["watermarks"], {"claims": "2026-11-10T09:00:00Z"})
        self.assertEqual(out["held_at"], {"claims": "2026-11-10T09:05:00Z"})
        again = self.run_feed()
        # three claims read again (all still rejected); the three policies are unchanged
        self.assertEqual((again["read"]["claims"], again["created"], again["unchanged"], again["rejected"]),
                         (3, 0, 3, 3))
        # the missing policy arrives: the claim that referred to it now loads
        self.svc.upsert_object(self.u["admin"], {"type": "Policy", "id": "P-9", "attributes": {
            "holder": "Fay Lin", "deductible": 100, "coverage_limit": 10000}})
        third = self.run_feed()
        self.assertIn("CL-6", self.svc.graph._instances)
        self.assertEqual(third["rejected"], 2)
        with self.assertRaises(sqlite3.DatabaseError):
            self.svc.store._db.execute("UPDATE lineage SET pipeline='x'")

    def test_status_set_on_create_survives_reloads(self):
        self.run_feed()
        admin = self.u["admin"]
        self.svc.upsert_object(admin, {"type": "Claim", "id": "CL-4", "attributes": {
            **{k: v for k, v in self.svc.graph.get("CL-4").attributes.items()}, "status": "paid"}})
        feed = EX / "feeds" / "claims.jsonl"
        tmp = Path(tempfile.mkdtemp())
        rows = [json.loads(line) for line in feed.read_text().splitlines()]
        rows[0].update(amount="1900", updated_at="2026-11-11T08:00:00Z")
        (tmp / "claims.jsonl").write_text("\n".join(json.dumps(r) for r in rows[:1]))
        self.svc.pipelines["claims_feed"].sources["claims"]["path"] = str(tmp / "claims.jsonl")
        out = self.run_feed()
        self.assertEqual(out["updated"], 1)
        attrs = self.svc.graph.get("CL-4").attributes
        self.assertEqual((attrs["amount"], attrs["status"]), (1900, "paid"))  # data refreshed, decision kept

    def test_push_and_permissions(self):
        out = self.run_feed(rows={"shops": [{"shop_id": "RS-3", "name": "Bay Autos", "in_network": "yes"}]})
        self.assertEqual((out["read"], out["created"]), ({"shops": 1}, 1))  # a push loads only what was pushed
        self.assertIs(self.svc.graph.get("RS-3").attributes["approved_network"], True)
        with self.assertRaises(ApiError) as cm:
            self.run_feed(rows={"claims": []})
        self.assertEqual(cm.exception.status, 400)
        for name, call in (("hana", lambda u: self.svc.run_pipeline(u, "claims_feed", {})),
                           ("hana", lambda u: self.svc.list_pipelines(u)),
                           ("maria", lambda u: self.svc.ingest_batch(u, "x")),
                           ("etl", lambda u: self.svc.list_objects(u, None, 10, 0))):
            with self.subTest(name), self.assertRaises(ApiError) as cm:
                call(self.u[name])
            self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(ApiError) as cm:
            self.svc.run_pipeline(self.u["etl"], "nope", {})
        self.assertEqual(cm.exception.status, 404)
        listed = self.svc.list_pipelines(self.u["etl"])["items"][0]
        self.assertEqual((listed["name"], listed["sources"]["shops"]), ("claims_feed", "push"))

    def test_failed_read_is_recorded(self):
        self.svc.pipelines["claims_feed"].sources["policies"]["path"] = "missing.csv"
        with self.assertRaises(ApiError) as cm:
            self.run_feed()
        self.assertEqual(cm.exception.status, 502)
        self.assertEqual(self.svc.store.ingest_batches("claims_feed")[0]["status"], "failed")

    def test_scheduled_pipeline_runs_when_due(self):
        first = self.svc.tick()["ingested"]
        self.assertEqual(first[0]["created"], 3)
        self.assertEqual(self.svc.tick()["ingested"], [])  # not due again for five minutes


class AutomationAndApiTests(unittest.TestCase):
    def test_loaded_claims_start_settlement_runs(self):
        svc = service()
        etl = next(u for u in svc.users if u.name == "etl")
        out = svc.run_pipeline(etl, "claims_feed", {})
        fired = {f["instance"]: f["status"] for f in out["triggered"]}
        self.assertEqual(fired, {"CL-4": "completed"})  # 1,850 less a 250 deductible: settled with no review

    def test_http_routes(self):
        svc = service(automations={})
        api = _Api(svc)
        self.addCleanup(api.server.shutdown)
        status, body, _ = api.call("POST", "/api/pipelines/claims_feed/run", TOKENS["etl"], {"dry_run": True})
        self.assertEqual((status, body["created"]), (200, 3))
        status, body, _ = api.call("GET", "/api/pipelines", TOKENS["etl"])
        self.assertEqual(body["items"][0]["last_batch"]["status"], "dry_run")
        api.call("POST", "/api/pipelines/claims_feed/run", TOKENS["etl"], {})
        status, body, _ = api.call("GET", "/api/objects/CL-4/lineage", TOKENS["hana"])
        self.assertEqual((status, body["loads"][0]["pipeline"]), (200, "claims_feed"))
        status, body, _ = api.call("GET", "/api/objects/CL-404/lineage", TOKENS["hana"])
        self.assertEqual(status, 404)
        batch = svc.store.ingest_batches("claims_feed")[0]["batch_id"]
        status, body, _ = api.call("GET", f"/api/ingest-batches/{batch}", TOKENS["etl"])
        self.assertEqual((status, len(body["rejects"])), (200, 3))
        status, _, _ = api.call("GET", f"/api/ingest-batches/{batch}", TOKENS["hana"])
        self.assertEqual(status, 403)


class CliTests(unittest.TestCase):
    def test_ingest_command(self):
        for name, token in TOKENS.items():
            os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
        cfg = json.loads((EX / "server.json").read_text())
        cfg.update(store=str(Path(tempfile.mkdtemp()) / "c.db"), automations={})
        path = EX / f"_test_server_{os.getpid()}.json"
        path.write_text(json.dumps(cfg))
        self.addCleanup(path.unlink)
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli(["ingest", str(path), "claims_feed", "--dry-run"])
        self.assertEqual(code, 2)  # rows were rejected
        self.assertIn("dry run: nothing written", out.getvalue())
        self.assertIn("a claim amount cannot be negative", out.getvalue())
        rows = Path(tempfile.mkdtemp()) / "rows.json"
        rows.write_text(json.dumps({"shops": [{"shop_id": "RS-3", "name": "Bay", "in_network": "no"}]}))
        with redirect_stdout(io.StringIO()) as out2:
            self.assertEqual(cli(["ingest", str(path), "claims_feed", "--rows", str(rows)]), 0)
        self.assertIn("created 1", out2.getvalue())
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli(["ingest", str(path), "nope"]), 1)
        self.assertIn("no pipeline", err.getvalue())


if __name__ == "__main__":
    unittest.main()
