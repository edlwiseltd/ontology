"""ARC-0 (audit GAP-026): responsibilities leave ``AutologyService`` one at a time, without a second authority.

  S1 notifications, ingestion, runs and reviews live in their own services; the engine's public methods are
     unchanged and delegate
  S2 a service holds no authority of its own: permissions, visibility and write rules are asked of its engine, so a
     call made on the service directly is refused exactly as through the engine
  S3 behaviour reached through the engine can still be intercepted on the engine (webhook delivery)
  S4 the engine class may only shrink: a ratchet on its size
  S5 runs and reviews called on their services are refused exactly as through the engine: permission, visibility,
     the person-only rule and self-review; no service defines an authority check of its own
  S6 a run and its review give the same answers over REST and MCP as before, and what the services reach through
     the engine can still be intercepted there (storing a result)
  S7 the services import the engine module, never each other, and the engine imports them only when it is built
"""

import ast
import inspect
import json
import unittest
from pathlib import Path

import autology
from autology.architecting import ArchitectService
from autology.configuring import ConfigurationService
from autology.ingestion import IngestionService
from autology.mcp import McpServer
from autology.notifications import NotificationService
from autology.reviews import ReviewService
from autology.runs import RunService
from autology.server import ApiError, ApiExchange, AutologyService

from .test_ingest import service

MOVED = {"notifications": ["_not_for_notifications", "_hidden_from_roles", "_notify_record", "_evidence_changed",
                           "_notify", "list_notifications"],
         "ingestion": ["ingest", "_due_pipelines", "list_pipelines", "run_pipeline", "ingest_batch", "object_lineage"],
         "runs": ["_summary", "_store_result", "_export_trace", "run_trace", "_write_back", "complete_write_backs",
                  "retry_write_back", "write_back_status", "run_roles", "_case_hides_records", "start_run",
                  "list_runs", "_visible_runs", "get_run", "run_audit", "_agent_for", "resume_run", "recover",
                  "_visible_run", "record_outcome", "list_outcomes", "outcomes_summary"],
         "reviews": ["list_reviews", "get_review", "decide", "_live_changes", "_continue_after_review"],
         "architect": ["architect_proposals"]}
SERVICES = {"notifications": NotificationService, "ingestion": IngestionService, "runs": RunService,
            "reviews": ReviewService, "architect": ArchitectService, "configuring": ConfigurationService}
SERVICE_MODULES = {"notifications": "notifications", "ingestion": "ingestion", "runs": "runs", "reviews": "reviews",
                   "architect": "architecting", "configuring": "configuring"}
AUTHORITY = ("require", "require_any", "require_person", "checkpoint", "visible", "field_hidden", "authenticate")
MAX_LINES, MAX_METHODS = 1714, 138  # lower these when more is extracted; never raise them


class ServiceExtractionTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})
        self.addCleanup(self.svc.close)
        self.u = {x.name: x for x in self.svc.users}

    def test_the_engine_delegates_and_keeps_its_interface(self):  # S1
        for attr, cls in SERVICES.items():
            self.assertIsInstance(getattr(self.svc, attr), cls)
            self.assertIs(getattr(self.svc, attr).engine, self.svc)
        for attr, names in MOVED.items():
            target = type(getattr(self.svc, attr))
            for name in names:
                on_engine = inspect.signature(getattr(AutologyService, name))
                on_service = inspect.signature(getattr(target, name))
                self.assertEqual(list(on_engine.parameters), list(on_service.parameters), name)
                delegate = inspect.getsource(getattr(AutologyService, name))
                self.assertIn(f"self.{attr}.{name}(", delegate, name)
                self.assertLessEqual(len(delegate.strip().splitlines()), 4, name)  # a delegate, not a second copy
        out = self.svc.run_pipeline(self.u["etl"], "claims_feed", {"dry_run": True})
        self.assertEqual(out["dry_run"], True)
        self.assertEqual(self.svc.list_notifications(self.u["hana"], None, 5), {"items": []})

    def test_a_service_has_no_authority_of_its_own(self):  # S2
        for call in (lambda: self.svc.ingestion.run_pipeline(self.u["hana"], "claims_feed", {}),
                     lambda: self.svc.ingestion.list_pipelines(self.u["hana"]),
                     lambda: self.svc.ingestion.ingest_batch(self.u["hana"], "x"),
                     lambda: self.svc.notifications.list_notifications(self.u["etl"], None, 5),
                     lambda: self.svc.ingestion.object_lineage(self.u["etl"], "CL-1")):
            with self.assertRaises(ApiError) as caught:
                call()
            self.assertEqual(caught.exception.status, 403)
        for klass in (NotificationService, IngestionService):
            source = inspect.getsource(klass)
            self.assertNotIn("PERMISSIONS", source)
            self.assertNotIn(".permissions -", source)  # no permission arithmetic outside the engine's own checks
            self.assertEqual([n for n in vars(klass) if n in ("require", "require_any", "visible", "field_hidden")], [])

    def test_delivery_is_still_intercepted_on_the_engine(self):  # S3
        sent = []
        self.svc.webhooks = [{"url": "http://127.0.0.1:9/hook", "kinds": set(), "environment": "simulated"}]
        self.svc._environment_refused = lambda environment, what: None
        self.svc._deliver = lambda url, note: sent.append((url, note["message"]))
        self.svc._notify("automation", ["claims_manager"], "hello", {})
        for t in self.svc.deliveries:
            t.join(5)
        self.assertEqual(sent, [("http://127.0.0.1:9/hook", "hello")])

    def test_the_engine_class_only_shrinks(self):  # S4
        source, start = inspect.getsourcelines(AutologyService)
        methods = [n for n, v in vars(AutologyService).items() if inspect.isfunction(v) or isinstance(v, (staticmethod, classmethod, property))]
        self.assertLessEqual(len(source), MAX_LINES, "AutologyService grew: extract, do not add (ARC-0)")
        self.assertLessEqual(len(methods), MAX_METHODS, "AutologyService gained methods: put new ones in a service")

    def test_runs_and_reviews_have_no_authority_of_their_own(self):  # S5
        case = {"case_template": "claim_case", "root": "CL-2"}
        for label, call, status in (
                ("no run permission", lambda: self.svc.runs.start_run(self.u["etl"], case), 403),
                ("no run permission (list)", lambda: self.svc.runs.list_runs(self.u["etl"], None, 10, 0), 403),
                ("no review permission", lambda: self.svc.reviews.list_reviews(self.u["hana"], None), 403),
                ("no reconcile permission", lambda: self.svc.runs.retry_write_back(self.u["hana"], "R-x"), 403)):
            with self.assertRaises(ApiError, msg=label) as on_service:
                call()
            self.assertEqual(on_service.exception.status, status, label)
        run = self.svc.runs.start_run(self.u["hana"], case)
        review = run["pending_review"]
        answers = []
        for target in (self.svc, self.svc.reviews):  # the same refusals, whichever object is asked
            row = []
            for user in ("hana", "etl"):  # no review permission
                with self.assertRaises(ApiError) as refused:
                    target.decide(self.u[user], review, {"approved": True})
                row.append(refused.exception.status)
            with self.assertRaises(ApiError) as hidden:  # a reviewer of another role does not see this review
                target.decide(self.u["maria"], review, {"approved": True})
            row.append(hidden.exception.status)
            answers.append(row)
        self.assertEqual(answers[0], answers[1])
        self.assertEqual(answers[0][:2], [403, 403])
        # a service identity never records a human approval, asked of the engine's own rule
        robot = type(self.u["ivan"])("robot", "", self.u["ivan"].permissions, self.u["ivan"].roles,
                                     self.u["ivan"].reviewer_roles, kind="service")
        with self.assertRaisesRegex(ApiError, "service identity"):
            self.svc.reviews.decide(robot, review, {"approved": True})
        self.assertEqual(self.svc.reviews.decide(self.u["ivan"], review, {"approved": True})["status"],
                         "awaiting_review")  # the next review of the same run (the payout threshold)
        for cls in SERVICES.values():
            self.assertEqual([n for n in vars(cls) if n in AUTHORITY], [], cls.__name__)

    def test_rest_and_mcp_behave_as_before_and_the_engine_can_still_be_intercepted(self):  # S6
        stored = []
        original = self.svc._store_result
        self.svc._store_result = lambda *a, **kw: stored.append(a[1]) or original(*a, **kw)
        ex = ApiExchange(self.svc, "POST", "/api/v1/runs", {"Authorization": "Bearer tok-hana"},
                         json.dumps({"case_template": "claim_case", "root": "CL-2"}).encode()).run()
        body = json.loads(ex.data)
        self.assertEqual((ex.status, body["status"], stored), (200, "awaiting_review", ["claims"]))
        listed = json.loads(ApiExchange(self.svc, "GET", "/api/v1/runs", {"Authorization": "Bearer tok-hana"},
                                        b"").run().data)
        self.assertEqual([r["run_id"] for r in listed["items"]], [body["run_id"]])
        text = McpServer(self.svc, self.u["hana"]).call("get_run", {"run_id": body["run_id"]})["content"][0]["text"]
        self.assertIn(body["run_id"], text)
        ex = ApiExchange(self.svc, "POST", f"/api/v1/reviews/{body['pending_review']}/decision",
                         {"Authorization": "Bearer tok-ivan"}, json.dumps({"approved": True}).encode()).run()
        self.assertEqual((ex.status, len(stored)), (200, 2))
        self.assertEqual(ApiExchange(self.svc, "GET", f"/api/v1/runs/{body['run_id']}",
                                     {"Authorization": "Bearer tok-etl"}, b"").run().status, 403)

    def test_services_depend_on_the_engine_module_only(self):  # S7
        root = Path(autology.__file__).parent
        files = set(SERVICE_MODULES.values())
        modules = {name: ast.parse((root / f"{name}.py").read_text()) for name in files}
        for name, tree in modules.items():
            local = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level and n.module}
            self.assertFalse(local & files, f"{name} imports another service: {local & files}")
            self.assertIn("server", local, name)
        engine = ast.parse((root / "server.py").read_text())
        top = {n.module for n in engine.body if isinstance(n, ast.ImportFrom) and n.level}
        self.assertFalse(top & files)  # imported where the engine is built: no import cycle at load


if __name__ == "__main__":
    unittest.main()
