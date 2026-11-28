"""H-1 / F-01: outbound credentials and destinations chosen by the other side (audit of 15 Nov 2026).

  O1 a "next page" link to another origin is refused; the other host never receives the pipeline's secret
  O2 an explicitly allowed second origin still works (legitimate paginated APIs spread over two hosts)
  O3 a redirect to another origin is never followed, for pipelines, HTTP tools, the HTTP approver and webhooks;
     a redirect inside the same origin still is
  O4 error texts (run records, audit, pipeline errors) never contain the secret value
  O5 a reply larger than the limit is refused instead of being read into memory
  O6 an HTTP tool that is redirected elsewhere after the request was sent is an unknown outcome (may have acted),
     never retried as "not sent"
"""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from autology import outbound
from autology.adapters import HttpApprover, http_tool
from autology.agent import ReviewRequest
from autology.ingest import Pipeline, PipelineError
from autology.tools import NotSent, OutcomeUnknown, ToolCall

from .test_ingest import onto

SECRET = "s3cret-value-h1"


class Recorder:
    """A local HTTP server; ``routes`` maps a path to (status, headers, body). Records every request it gets."""

    def __init__(self, routes=None):
        self.routes, self.seen = routes or {}, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                outer.seen.append((self.command, self.path, self.headers.get("Authorization"),
                                   self.headers.get("X-Api-Key")))
                status, headers, body = outer.routes.get(self.path.split("?")[0], (404, {}, b"{}"))
                body = body(outer) if callable(body) else body
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v(outer) if callable(v) else v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _answer  # noqa: N815

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        os.environ["H1_SECRET"] = SECRET
        self.addCleanup(os.environ.pop, "H1_SECRET", None)
        self.dir = Path(tempfile.mkdtemp())
        self.evil = Recorder({"/steal": (200, {"Content-Type": "application/json"},
                                         b'{"items": [], "next": null, "outcome": "ok"}')})
        self.addCleanup(self.evil.close)

    def server(self, routes):
        r = Recorder(routes)
        self.addCleanup(r.close)
        return r

    def pipe(self, source):
        spec = {"name": "t", "sources": {"s": source},
                "mappings": [{"source": "s", "entity": "RepairShop", "id": "id", "attributes": {"name": "name"}}]}
        return Pipeline(spec, onto(), self.dir)

    def assertEvilGotNothing(self):
        self.assertEqual(self.evil.seen, [], "the other origin must receive nothing")


def page(items, nxt):
    return json.dumps({"items": items, "next": nxt}).encode()


class PipelineTests(Base):
    def source(self, url, **extra):
        return {"type": "http", "url": url, "items": "items", "next": "next",
                "headers": {"Authorization": {"env": "H1_SECRET", "prefix": "Bearer "}}, **extra}

    def test_next_page_on_another_origin_is_refused_and_never_receives_the_secret(self):  # O1
        evil = self.evil.base
        api = self.server({"/shops": (200, {}, page([{"id": "RS-1", "name": "One"}], f"{evil}/steal"))})
        with self.assertRaises(PipelineError) as ctx:
            self.pipe(self.source(f"{api.base}/shops")).read({})
        self.assertIn("another origin", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertEvilGotNothing()

    def test_an_explicitly_allowed_second_origin_is_followed(self):  # O2
        second = self.server({"/p2": (200, {}, page([{"id": "RS-2", "name": "Two"}], None))})
        api = self.server({"/shops": (200, {}, page([{"id": "RS-1", "name": "One"}], f"{second.base}/p2"))})
        rows = self.pipe(self.source(f"{api.base}/shops", next_origins=[second.base])).read({}).rows["s"]
        self.assertEqual([r["id"] for r in rows], ["RS-1", "RS-2"])
        self.assertEqual(second.seen[0][2], f"Bearer {SECRET}")

    def test_same_origin_pagination_still_works(self):
        api = self.server({"/shops": (200, {}, lambda s: page([{"id": "RS-1", "name": "One"}], f"{s.base}/p2")),
                           "/p2": (200, {}, page([{"id": "RS-2", "name": "Two"}], None))})
        rows = self.pipe(self.source(f"{api.base}/shops")).read({}).rows["s"]
        self.assertEqual([r["id"] for r in rows], ["RS-1", "RS-2"])

    def test_a_redirect_to_another_origin_is_not_followed(self):  # O3
        api = self.server({"/shops": (302, {"Location": f"{self.evil.base}/steal"}, b"")})
        with self.assertRaises(PipelineError) as ctx:
            self.pipe(self.source(f"{api.base}/shops")).read({})
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertEvilGotNothing()

    def test_a_redirect_inside_the_origin_is_followed(self):
        api = self.server({"/shops": (302, {"Location": "/v2/shops"}, b""),
                           "/v2/shops": (200, {}, page([{"id": "RS-1", "name": "One"}], None))})
        rows = self.pipe(self.source(f"{api.base}/shops")).read({}).rows["s"]
        self.assertEqual([r["id"] for r in rows], ["RS-1"])

    def test_errors_never_contain_the_secret(self):  # O4
        api = self.server({"/shops": (500, {}, f"internal error, token {SECRET}".encode())})
        url = f"{api.base}/shops?api_key={SECRET}"
        with self.assertRaises(PipelineError) as ctx:
            self.pipe({**self.source(url), "headers": {"X-Api-Key": {"env": "H1_SECRET"}}}).read({})
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_an_oversized_reply_is_refused(self):  # O5
        api = self.server({"/shops": (200, {}, b"[" + b" " * 2048 + b"]")})
        with self.assertRaises(PipelineError) as ctx:
            self.pipe(self.source(f"{api.base}/shops", max_bytes=1024)).read({})
        self.assertIn("larger than", str(ctx.exception))


class ToolAndApproverTests(Base):
    def call(self):
        return ToolCall(action="pay", capability="payments.pay", inputs={}, context={}, attempt=1,
                        idempotency_key="k1", target=None)

    def test_an_http_tool_redirected_elsewhere_is_an_unknown_outcome_and_sends_nothing_there(self):  # O3, O6
        api = self.server({"/pay": (302, {"Location": f"{self.evil.base}/steal"}, b"")})
        tool = http_tool(f"{api.base}/pay", headers={"Authorization": "Bearer ${H1_SECRET}"})
        with self.assertRaises(OutcomeUnknown) as ctx:
            tool(self.call())
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertEvilGotNothing()

    def test_a_secret_in_the_tool_url_never_appears_in_the_error(self):  # O4
        tool = http_tool("http://127.0.0.1:9/pay?key=${H1_SECRET}")
        with self.assertRaises(NotSent) as ctx:
            tool(self.call())
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_the_http_approver_is_not_redirected_elsewhere(self):  # O3
        api = self.server({"/review": (302, {"Location": f"{self.evil.base}/steal"}, b"")})
        approver = HttpApprover(f"{api.base}/review", headers={"Authorization": "Bearer ${H1_SECRET}"})
        decision = approver.review(ReviewRequest(case_id="c", action="pay", description="pay",
                                                 reviewers=("mgr",), reasons=["R"], view={}))
        self.assertFalse(decision.approved)
        self.assertEvilGotNothing()


class WebhookTests(Base):
    def test_a_webhook_is_not_redirected_elsewhere(self):  # O3
        from autology.server import AutologyService

        hook = self.server({"/hook": (302, {"Location": f"{self.evil.base}/steal"}, b"")})
        AutologyService._deliver(f"{hook.base}/hook", {"kind": "test"})
        self.assertEqual(len(hook.seen), 1)
        self.assertEvilGotNothing()


class HelperTests(unittest.TestCase):
    def test_origins(self):
        self.assertTrue(outbound.same_origin("https://a.example/x", "https://A.example:443/y"))
        self.assertFalse(outbound.same_origin("https://a.example", "http://a.example"))
        self.assertFalse(outbound.same_origin("https://a.example", "https://a.example.evil.test"))
        self.assertFalse(outbound.same_origin("https://a.example", "https://a.example:8443"))
        self.assertFalse(outbound.same_origin("file:///etc/passwd", "https://a.example"))
        self.assertEqual(outbound.safe_url("https://u:p@h.example:8443/a?token=x"), "https://h.example:8443/a")
        self.assertEqual(outbound.redact("a s3cr3t b", ["s3cr3t", None, "ab"]), "a *** b")


if __name__ == "__main__":
    unittest.main()
