"""API v1 foundation (master directive, increment 1).

  V1 /api/v1 and /platform/v1 are served by the same handlers as the unversioned paths (no second implementation)
  V2 every v1 response carries X-Autology-API-Version: 1; unversioned responses say "legacy" and link to their v1
     successor, and keep their exact legacy shape (compatibility policy: docs/api-versioning.md)
  V3 every v1 error has one envelope {error: {status, code, message, details}}, including the router's own
     refusals, and refusals stay identical whether a workspace is foreign, unknown or not granted
  V4 paginated lists carry {page: {limit, offset, returned, next_offset}} and walking next_offset returns every
     item once
  V5 real responses validate against the published schemas (engine and platform contracts)
  V6 the contracts Studio generates its client from are the ones the engine publishes (no drift)
"""

import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from autology.openapi import PLATFORM_RESPONSES, PLATFORM_SCHEMAS, RESPONSES, SCHEMAS, platform_spec, spec
from autology.platform import Platform

from .helpers import ROOT
from .schema_check import errors
from .test_r2_use_case_lifecycle import close
from .test_workspaces import EX, TOKENS, Client, simulate_all

E = "/w/acme/u/claims/api"


class V1Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update(TOKENS)
        s = json.loads((EX / "platform.json").read_text())
        s["data_dir"] = tempfile.mkdtemp()
        cls.pf = simulate_all(Platform(s, EX))
        cls.c = Client(cls.pf)

    @classmethod
    def tearDownClass(cls):
        cls.c.server.shutdown()
        cls.c.server.server_close()
        close(cls.pf)

    def raw(self, method, path, token="acme-ada", body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.c.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, dict(r.headers), json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read() or b"null")


class VersioningTests(V1Base):
    def test_both_contracts_are_published_without_a_token(self):
        status, _, doc = self.raw("GET", "/platform/openapi.json", token=None)
        self.assertEqual((status, doc), (200, json.loads(json.dumps(platform_spec()))))
        status, _, doc = self.raw("GET", f"{E}/openapi.json", "acme-hana")  # behind the router: members only
        self.assertEqual((status, sorted(doc["paths"])), (200, sorted(spec()["paths"])))

    def test_v1_and_legacy_are_the_same_handlers(self):  # V1
        _, _, legacy = self.raw("GET", f"{E}/objects/CL-1")
        _, _, v1 = self.raw("GET", f"{E}/v1/objects/CL-1")
        self.assertEqual(legacy, v1)
        _, _, a = self.raw("GET", "/platform/me")
        _, _, b = self.raw("GET", "/platform/v1/me")
        self.assertEqual(a, b)

    def test_version_headers_and_successor_links(self):  # V2
        _, h, _ = self.raw("GET", f"{E}/v1/ontology")
        self.assertEqual(h["X-Autology-API-Version"], "1")
        _, h, _ = self.raw("GET", f"{E}/ontology")
        self.assertEqual((h["X-Autology-API-Version"], h["Link"]),
                         ("legacy", f'<{E}/v1/ontology>; rel="successor-version"'))  # reachable through the router
        status, h2, _ = self.raw("GET", h["Link"][1:h["Link"].index(">")])
        self.assertEqual((status, h2["X-Autology-API-Version"]), (200, "1"))
        _, h, _ = self.raw("GET", "/platform/me")
        self.assertEqual(h["Link"], '</platform/v1/me>; rel="successor-version"')
        status, _, body = self.raw("POST", f"{E}/objects", "acme-hana", {})  # legacy errors keep their shape
        self.assertEqual((status, body), (403, {"error": "hana lacks the 'admin' permission"}))

    def test_one_error_envelope_everywhere(self):  # V3
        cases = [("GET", f"{E}/v1/objects/NOPE", "acme-ada", None, 404),
                 ("POST", f"{E}/v1/objects", "acme-hana", {}, 403),
                 ("GET", f"{E}/v1/me", None, None, 401),
                 ("POST", f"{E}/v1/model/draft", "acme-ada", {"document": {}}, 400),
                 ("POST", "/platform/v1/workspaces/acme/use-cases/claims/stage", "acme-ada",
                  {"to": "production", "reason": "x"}, 403),
                 ("GET", "/platform/v1/workspaces/acme/use-cases/zzz", "acme-ada", None, 404)]
        for method, path, token, body, status in cases:
            with self.subTest(path=path):
                got, _, out = self.raw(method, path, token, body)
                self.assertEqual(got, status)
                self.assertEqual(errors(out, SCHEMAS["Error"], SCHEMAS), [])
                self.assertEqual(out["error"]["status"], status)
        refused = {json.dumps(self.raw("GET", p, "acme-hana")[2]) for p in (
            "/w/northwind/u/claims/api/v1/me", "/w/nowhere/u/x/api/v1/me", "/w/acme/u/orders/api/v1/me")}
        self.assertEqual(len(refused), 1)  # foreign, unknown and ungranted: one identical answer

    def test_paging_returns_every_item_once(self):  # V4
        seen, offset = [], 0
        while offset is not None:
            status, _, page = self.raw("GET", f"{E}/v1/objects?limit=4&offset={offset}")
            self.assertEqual(status, 200)
            self.assertEqual(errors(page, SCHEMAS["ObjectList"], SCHEMAS), [])
            seen += [o["id"] for o in page["items"]]
            offset = page["page"]["next_offset"]
        _, _, everything = self.raw("GET", f"{E}/v1/objects?limit=1000")
        self.assertEqual(sorted(seen), sorted(o["id"] for o in everything["items"]))
        self.assertEqual(len(seen), len(set(seen)))
        self.assertGreater(len(seen), 4)


class SchemaConformanceTests(V1Base):  # V5
    def test_engine_responses_match_the_published_schemas(self):
        _, _, draft = self.raw("GET", f"{E}/v1/model/draft")
        calls = {
            ("GET", "/api/health"): ("GET", f"{E}/v1/health", None),
            ("GET", "/api/me"): ("GET", f"{E}/v1/me", None),
            ("GET", "/api/objects"): ("GET", f"{E}/v1/objects?limit=3", None),
            ("GET", "/api/objects/{id}"): ("GET", f"{E}/v1/objects/CL-1", None),
            ("POST", "/api/objects"): ("POST", f"{E}/v1/objects", {"type": "Claim", "id": "CL-V1", "attributes": {
                "amount": 10, "status": "reported", "damage_type": "x", "reported_days_after": 1}}),
            ("GET", "/api/ontology"): ("GET", f"{E}/v1/ontology", None),
            ("GET", "/api/model/draft"): ("GET", f"{E}/v1/model/draft", None),
            ("POST", "/api/model/draft"): ("POST", f"{E}/v1/model/draft", {
                "document": draft["document"], "expected_revision": draft["revision"], "note": "v1"}),
            ("POST", "/api/model/validate"): ("POST", f"{E}/v1/model/validate", {"document": draft["document"]}),
            ("POST", "/api/architect/proposals"): ("POST", f"{E}/v1/architect/proposals", {
                "brief": "pumps and treatment plants with maintenance"}),
        }
        self.assertEqual(set(calls), set(RESPONSES))  # every typed engine response is exercised
        for key, (method, path, body) in calls.items():
            with self.subTest(route=key):
                status, _, out = self.raw(method, path, body=body)
                self.assertEqual(status, 200, out)
                self.assertEqual(errors(out, SCHEMAS[RESPONSES[key]], SCHEMAS), [])

    def test_platform_responses_match_the_published_schemas(self):
        base = "/platform/v1/workspaces/acme/use-cases"
        calls = [(("GET", "/platform/health"), "GET", "/platform/v1/health", None, 200),
                 (("GET", "/platform/me"), "GET", "/platform/v1/me", None, 200),
                 (("GET", "/platform/templates"), "GET", "/platform/v1/templates", None, 200),
                 (("GET", "/platform/workspaces/{ws}/use-cases"), "GET", base, None, 200),
                 (("POST", "/platform/workspaces/{ws}/use-cases"), "POST", base,
                  {"id": "v1-case", "name": "V1", "template": "claims-starter"}, 201),
                 (("GET", "/platform/workspaces/{ws}/use-cases/{uc}"), "GET", f"{base}/claims", None, 200),
                 (("GET", "/platform/workspaces/{ws}/use-cases/{uc}/checks"), "GET", f"{base}/claims/checks?to=pilot",
                  None, 200),
                 (("POST", "/platform/workspaces/{ws}/use-cases/{uc}/stage"), "POST", f"{base}/v1-case/stage",
                  {"to": "simulation", "reason": "v1 contract"}, 200)]
        rel, n = f"{base}/v1-case/releases", "1"  # REL-1a: ada proposes and activates, maria approves
        calls += [(("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases"), "POST", rel, {"note": "v1"}, 201),
                  (("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/approve"), "POST",
                   f"{rel}/{n}/approve", {"reason": "ok"}, 200, "acme-maria"),
                  (("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/revoke"), "POST",
                   f"{rel}/{n}/revoke", {"reason": "recheck"}, 200, "acme-maria"),
                  (("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/approve"), "POST",
                   f"{rel}/{n}/approve", {"reason": "ok now"}, 200, "acme-maria"),
                  (("POST", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}/activate"), "POST",
                   f"{rel}/{n}/activate", {"reason": "go"}, 200),
                  (("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases"), "GET", rel, None, 200),
                  (("GET", "/platform/workspaces/{ws}/use-cases/{uc}/releases/{n}"), "GET", f"{rel}/{n}", None, 200),
                  (("GET", "/platform/workspaces/{ws}/use-cases/{uc}"), "GET", f"{base}/v1-case", None, 200)]
        self.assertEqual({c[0] for c in calls}, set(PLATFORM_RESPONSES))
        for key, method, path, body, status, *who in calls:
            with self.subTest(route=key, path=path):
                got, _, out = self.raw(method, path, who[0] if who else "acme-ada", body)
                self.assertEqual(got, status, out)
                self.assertEqual(errors(out, PLATFORM_SCHEMAS[PLATFORM_RESPONSES[key]], PLATFORM_SCHEMAS), [])


class ContractTests(unittest.TestCase):
    def test_platform_contract_structure(self):
        doc = platform_spec()
        ids = [op["operationId"] for ops in doc["paths"].values() for op in ops.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(p.startswith("/platform/v1/") for p in doc["paths"]))
        self.assertTrue(all(p.startswith("/api/v1/") for p in spec()["paths"]))

    def test_the_cli_writes_and_prints_the_contracts(self):
        import contextlib
        import io

        from autology.__main__ import main
        out = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["openapi", "--write", out]), 0)
        self.assertEqual(json.loads((Path(out) / "platform.openapi.json").read_text()), platform_spec())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(main(["openapi", "engine"]), 0)
        self.assertEqual(json.loads(buf.getvalue())["openapi"], "3.1.0")

    def test_the_studio_client_is_generated_from_the_published_contracts(self):  # V6
        for name, doc in (("engine", spec()), ("platform", platform_spec())):
            committed = json.loads((ROOT / "studio" / "web" / "api" / f"{name}.openapi.json").read_text())
            self.assertEqual(committed, json.loads(json.dumps(doc)),
                             f"studio/web/api/{name}.openapi.json is stale: run python -m autology openapi --write")


if __name__ == "__main__":
    unittest.main()
