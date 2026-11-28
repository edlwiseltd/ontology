"""D24 (least-privilege operations): what is ready, and what waits for the owner's approval.

The proposed ``operate`` permission is **not** implemented: these tests pin the present authorisation, so that a
change of semantics cannot slip in unapproved, and verify the evidence the access review now gives for the decision.

  D1 ``operate`` is not a permission today: it cannot be configured or granted
  D2 the operations it could cover (scheduler pass, reporting refresh, agent reinstatement) are refused to
     everyone who does not hold the engine's unrestricted ``admin`` permission. Retrying a write-back is not one
     of them: it already has its own permission (``reconcile``) and never needed ``admin`` (a correction to the
     first version of the D24 design, which listed it)
  D3 the access review shows, for every unrestricted grant, what it was used for; a holder whose recorded use never
     read business data is reported as one a narrower grant would serve
  D4 requests are classified from the access log's own targets
"""

import json
import os

from autology.platform import Platform
from autology.server import PERMISSIONS, ApiError, AutologyService

from . import test_ingest
from .test_adm1_administration import AdminBase, WS

ENGINE = "/w/acme/u/claims/api/v1"


class OperateReadinessTests(AdminBase):
    def test_operate_is_not_a_permission_until_the_owner_approves_it(self):  # D1
        self.assertNotIn("operate", PERMISSIONS)
        status, out = self.propose("hana", ["operate"])
        self.assertEqual(status, 400, out)
        cfg = json.loads((test_ingest.EX / "server.json").read_text())
        cfg["store"] = ":memory:"
        cfg["users"][0]["permissions"] = ["read", "operate"]
        with self.assertRaises(ValueError):
            AutologyService(cfg, test_ingest.EX)

    def test_operational_routes_need_the_unrestricted_permission_today(self):  # D2
        routes = [("POST", "/tick", {}), ("POST", "/reporting", {}),
                  ("POST", "/agents/claims/reinstate", {"reason": "a reason long enough"})]
        for token in ("acme-hana", "acme-ivan", "acme-maria"):  # read, run, review: none of them operates the engine
            for method, path, body in routes:
                status, _ = self.call(method, ENGINE + path, token, body)
                self.assertEqual(status, 403, (token, path))
        self.assertEqual(self.call("POST", f"{ENGINE}/tick", body={})[0], 200)  # ada holds an explicit admin grant

    def test_a_write_back_retry_needs_reconcile_not_the_unrestricted_permission(self):  # D2 (correction)
        os.environ["AUTOLOGY_TOKEN_RITA"] = "tok-rita"
        users = json.loads((test_ingest.EX / "server.json").read_text())["users"]
        users.append({"name": "rita", "token_env": "AUTOLOGY_TOKEN_RITA", "permissions": ["reconcile"]})
        svc = test_ingest.service(users=users)
        self.addCleanup(svc.close)
        users = {u.name: u for u in svc.users}
        with self.assertRaises(ApiError) as refused:  # no reconcile permission: refused before anything is read
            svc.retry_write_back(users["hana"], "R-none")
        with self.assertRaises(ApiError) as missing:  # reconcile without admin passes the permission check
            svc.retry_write_back(users["rita"], "R-none")
        self.assertEqual((refused.exception.status, missing.exception.status), (403, 404))
        self.assertNotIn("admin", users["rita"].permissions)

    def test_the_review_shows_what_unrestricted_access_was_used_for(self):  # D3
        def mine():
            _, review = self.call("GET", f"{WS}/access-review", "acme-maria")
            item = next(i for i in review["items"] if (i["member"], i["use_case"]) == ("ada", "claims"))
            return item, review["summary"]
        item, summary = mine()
        self.assertEqual((item["data_access"], item["usage"]["data"], item["narrower_would_do"]),
                         ("unrestricted", 0, True))
        self.assertEqual(self.call("POST", f"{ENGINE}/tick", body={})[0], 200)
        self.assertEqual(self.call("GET", f"{ENGINE}/model/draft")[0], 200)
        self.assertEqual(self.call("GET", f"{ENGINE}/me")[0], 200)
        item, summary = mine()
        self.assertEqual((item["usage"]["operational"], item["usage"]["configuration"], item["usage"]["data"]), (1, 1, 0))
        self.assertTrue(item["narrower_would_do"])  # everything she did could be done without reading data
        self.assertGreaterEqual(summary["unrestricted_without_data_use"], 1)
        self.assertIsNotNone(item["usage"]["last_request_at"])
        self.assertEqual(self.call("GET", f"{ENGINE}/objects")[0], 200)  # now she reads business records
        self.assertEqual(self.call("GET", f"{ENGINE}/objects/NOPE")[0], 404)  # a refusal is not a use
        item, _ = mine()
        self.assertEqual((item["usage"]["data"], item["narrower_would_do"]), (1, False))
        scoped = next(i for i in self.call("GET", f"{WS}/access-review")[1]["items"] if i["member"] == "hana")
        self.assertNotIn("usage", scoped)  # only unrestricted grants are examined
        # the review changes nothing: ada's permission is what it was
        self.assertEqual(self.call("GET", f"{ENGINE}/me")[1]["permissions"], ["admin", "configure"])

    def test_requests_are_classified_from_the_access_log(self):  # D4
        kind = Platform._usage_kind
        self.assertEqual([kind(t) for t in ("POST /api/v1/tick", "POST /api/reporting", "POST /api/v1/agents/a/reinstate",
                                            "POST /api/v1/runs/R-1/write-back")], ["operational"] * 4)
        self.assertEqual([kind(t) for t in ("GET /api/v1/model/draft", "POST /api/v1/settings/assistant",
                                            "POST /api/architect/proposals")], ["configuration"] * 3)
        self.assertEqual([kind(t) for t in ("GET /api/v1/objects", "POST /api/v1/runs", "GET /api/v1/runs/R-1",
                                            "POST /api/v1/reviews/V-1/decision", "POST /api/v1/objects")], ["data"] * 5)
        self.assertEqual([kind(t) for t in ("GET /api/v1/me", "GET /api/health", "GET /api/v1/agents", "GET /")],
                         [None] * 4)


if __name__ == "__main__":
    import unittest

    unittest.main()
