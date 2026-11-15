"""ARC-0 (audit GAP-026): responsibilities leave ``AutologyService`` one at a time, without a second authority.

  S1 notifications and ingestion live in their own services; the engine's public methods are unchanged and delegate
  S2 a service holds no authority of its own: permissions, visibility and write rules are asked of its engine, so a
     call made on the service directly is refused exactly as through the engine
  S3 behaviour reached through the engine can still be intercepted on the engine (webhook delivery)
  S4 the engine class may only shrink: a ratchet on its size
"""

import inspect
import unittest

from autology.ingestion import IngestionService
from autology.notifications import NotificationService
from autology.server import ApiError, AutologyService

from .test_ingest import service

MOVED = {"notifications": ["_not_for_notifications", "_hidden_from_roles", "_notify_record", "_evidence_changed",
                           "_notify", "list_notifications"],
         "ingestion": ["ingest", "_due_pipelines", "list_pipelines", "run_pipeline", "ingest_batch", "object_lineage"]}
MAX_LINES, MAX_METHODS = 2142, 139  # lower these when more is extracted; never raise them


class ServiceExtractionTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})
        self.addCleanup(self.svc.close)
        self.u = {x.name: x for x in self.svc.users}

    def test_the_engine_delegates_and_keeps_its_interface(self):  # S1
        self.assertIsInstance(self.svc.notifications, NotificationService)
        self.assertIsInstance(self.svc.ingestion, IngestionService)
        self.assertIs(self.svc.notifications.engine, self.svc)
        for attr, names in MOVED.items():
            target = type(getattr(self.svc, attr))
            for name in names:
                on_engine = inspect.signature(getattr(AutologyService, name))
                on_service = inspect.signature(getattr(target, name))
                self.assertEqual(list(on_engine.parameters), list(on_service.parameters), name)
                self.assertIn(f"self.{attr}.{name}(", inspect.getsource(getattr(AutologyService, name)), name)
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


if __name__ == "__main__":
    unittest.main()
