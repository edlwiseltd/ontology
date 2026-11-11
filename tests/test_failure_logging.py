"""Review item 9: failures in the background and at the edges are logged with a traceback, and visible."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from .test_platform import _Api, service


class FailureLoggingTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(chat=None)

    def test_scheduler_errors_are_logged_and_shown_in_health(self):
        with mock.patch.object(self.svc, "tick", side_effect=RuntimeError("store unavailable")):
            with self.assertLogs("autology.server", "ERROR") as logs:
                stop = self.svc.start_background(0.01)
                for _ in range(300):
                    if self.svc.scheduler_status["last_error"]:
                        break
                    threading.Event().wait(0.01)
                stop.set()
        self.assertIn("Traceback", "\n".join(logs.output))
        self.assertIn("store unavailable", "\n".join(logs.output))
        api = _Api(self.svc)
        try:
            health = api.call("GET", "/api/health")[1]
            self.assertIn("RuntimeError: store unavailable", health["scheduler"]["last_error"]["error"])
        finally:
            api.server.shutdown()

    def test_unexpected_endpoint_errors_are_logged(self):
        api = _Api(self.svc)
        try:
            with mock.patch.object(self.svc, "list_runs", side_effect=KeyError("boom")):
                with self.assertLogs("autology.server", "ERROR") as logs:
                    status, body, _ = api.call("GET", "/api/runs", "olivia")
            self.assertEqual((status, body["error"]), (500, "internal error: KeyError"))  # no traceback to clients
            self.assertIn("GET /api/runs", "\n".join(logs.output))
            self.assertIn("Traceback", "\n".join(logs.output))
        finally:
            api.server.shutdown()

    def test_webhook_and_trace_export_failures_are_logged(self):
        svc = service(chat=None, webhooks=[{"url": "http://127.0.0.1:1/hook"}],
                      tracing={"endpoint": "http://127.0.0.1:1/v1/traces"})
        with self.assertLogs("autology.server", "WARNING") as logs:
            svc.tick()  # fires the K-1 automation: a notification (webhook) and a completed run (trace export)
            for t in list(svc.deliveries):
                t.join(10)
        text = "\n".join(logs.output)
        self.assertIn("webhook delivery to 127.0.0.1:1 failed", text)
        self.assertIn("trace export", text)

    def test_server_log_file(self):
        log = Path(tempfile.mkdtemp()) / "autology.log"
        svc = service(chat=None, log_file=str(log))
        with mock.patch.object(svc, "tick", side_effect=RuntimeError("disk on fire")):
            stop = svc.start_background(0.01)
            for _ in range(300):
                if svc.scheduler_status["last_error"]:
                    break
                threading.Event().wait(0.01)
            stop.set()
        root = __import__("logging").getLogger("autology")
        for handler in list(root.handlers):
            if getattr(handler, "baseFilename", None) == str(log.resolve()):
                handler.flush()
                root.removeHandler(handler)
                handler.close()
        self.assertIn("disk on fire", log.read_text())


if __name__ == "__main__":
    unittest.main()
