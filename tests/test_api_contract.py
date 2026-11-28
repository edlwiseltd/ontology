"""API-1: the engine's API contract (autology/openapi.py) is authoritative and matches the engine.

  C1 the contract is a structurally valid OpenAPI 3.1 document (unique operation ids, every path parameter
     declared, public routes marked as such) and is served at GET /api/openapi.json without a token
  C2 every route in the contract is served by the engine (never the dispatcher's bare "not found" or 405)
  C3 every path segment the engine's dispatcher matches belongs to a route in the contract (no hidden route)
  C4 the contract and docs/platform.md list the same routes with the same permission; the entry-point matrix
     (tests/test_entry_point_matrix.py) checks those permissions against the engine
"""

import json
import re
import unittest

from autology.openapi import ROUTES, spec
from autology.server import ApiExchange

from .helpers import ROOT
from .test_entry_point_matrix import EntryPointMatrixTests, documented_routes

EXTRA_IDS = {"/api/runs/{id}/trace": "{run}", "/api/runs/{id}/outcomes": "{run}", "/api/sdk/{language}": "python",
             "/api/chat/{id}": "nochat", "/api/reconciliation/{key}": "nokey"}


class ContractStructureTests(unittest.TestCase):
    def test_a_valid_openapi_3_1_document(self):  # C1
        doc = spec()
        self.assertEqual(doc["openapi"], "3.1.0")
        ids = [op["operationId"] for ops in doc["paths"].values() for op in ops.values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), len(ROUTES))
        for path, ops in doc["paths"].items():
            self.assertTrue(path.startswith("/api/"))
            for method, op in ops.items():
                declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
                self.assertEqual(declared, set(re.findall(r"\{([a-z]+)\}", path)), (method, path))
                self.assertIn("x-autology-permission", op)
                if op["x-autology-permission"] == "none":
                    self.assertEqual(op["security"], [])
        json.dumps(doc)  # serialisable

    def test_served_without_a_token(self):  # C1
        from .test_platform import service

        svc = service(automations={}, chat=None)
        ex = ApiExchange(svc, "GET", "/api/openapi.json", {}, None, None).run()
        self.assertEqual(ex.status, 200)
        self.assertEqual(json.loads(ex.data)["info"]["title"], "Autology engine API")
        svc.close()


class ContractMatchesTheEngineTests(EntryPointMatrixTests):
    """Reuses the entry-point matrix's service, with real ids, and calls every route as an administrator."""

    def test_every_contract_route_is_served(self):  # C2
        run_id = self.ids["{id}"]
        for method, path, permission, _summary, _query in ROUTES:
            with self.subTest(route=f"{method} {path}"):
                template = EXTRA_IDS.get(path)
                concrete = re.sub(r"\{[a-z]+\}", template.replace("{run}", run_id), path) if template \
                    else self.path(path)
                headers = {"Content-Type": "application/json"}
                if permission != "none":
                    headers["Authorization"] = "Bearer tok-admin"
                ex = ApiExchange(self.svc, method, concrete, headers, b"{}" if method == "POST" else None, None).run()
                self.assertNotEqual(ex.status, 405, ex.data)
                body = ex.data.decode(errors="replace")
                self.assertFalse(ex.status == 404 and json.loads(body or "{}").get("error") == "not found",
                                 f"{method} {concrete} is in the contract but the engine does not serve it")

    def test_every_route_the_dispatcher_matches_is_in_the_contract(self):  # C3
        source = (ROOT / "autology" / "server.py").read_text()
        start = source.index("    def _dispatch(")
        body = source[start:source.index("\n    def ", start + 10)]
        literals = set(re.findall(r'\("(?:GET|POST)", "([a-z\-]+)"\)', body))
        literals |= set(re.findall(r'(?:parts\[\d\]|kind|verb) == "([a-z\-]+)"', body))
        literals |= {w for group in re.findall(r'parts == \[([^\]]+)\]', body) for w in re.findall(r'"([a-z\-]+)"', group)}
        literals |= set(re.findall(r'path == "/api/([a-z\-/.]+)"', body))
        segments = {seg for _m, path, *_ in ROUTES for seg in path.replace("/api/", "", 1).split("/")}
        segments |= {path.replace("/api/", "", 1) for _m, path, *_ in ROUTES}
        missing = sorted(lit for lit in literals if lit not in segments)
        self.assertEqual(missing, [], "the dispatcher serves paths that are not in the contract")
        self.assertGreater(len(literals), 30)

    def test_the_contract_and_the_documentation_agree(self):  # C4
        documented = {(m, p): need.split("(")[0].strip() for m, p, need in documented_routes()}
        contract = {(m, p): perm for m, p, perm, *_ in ROUTES}
        for key, perm in contract.items():
            self.assertIn(key, documented, f"{key} is in the contract but not in docs/platform.md")
            expected = "any" if perm == "none" else perm
            self.assertEqual(documented[key], expected, key)
        self.assertEqual(sorted(set(documented) - set(contract)), [])


if __name__ == "__main__":
    unittest.main()
