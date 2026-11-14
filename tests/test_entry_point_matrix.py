"""Gate 80.4 (audit): every permission against every documented entry point. A user without the permission a
route requires never gets a 2xx answer, and the assistant/MCP tools a user is given never exceed their permissions.

The routes come from the documentation's tables (docs/platform.md), so the documentation and the code are checked
against each other: a documented route that answers a user lacking its permission fails here.
"""

import os
import re
import unittest

from autology.chat import tools_for
from autology.server import PERMISSIONS, ApiExchange, hash_token

from .helpers import ROOT
from .test_ingest import TOKENS, service

ROUTE = re.compile(r"^\| `(GET|POST) (/api/[^`]+)`(?: · `(GET|POST) (/api/[^`]+)`)? \| ([^|]+) \|", re.M)


def documented_routes():
    text = (ROOT / "docs" / "platform.md").read_text()
    out = []
    for m in ROUTE.finditer(text):
        need = m.group(5).strip()
        for method, path in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
            if method:
                out.append((method, path.split("?")[0], need))
    return out


def allowed(need: str, perms: frozenset) -> bool:
    if "admin" in perms or need == "any":
        return True
    options = [p.strip() for p in re.split(r",| or ", need.split("(")[0]) if p.strip()]
    return any(p in perms for p in options)


class EntryPointMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        users = [{"name": f"only-{p}", "token_sha256": hash_token(f"tok-{p}"), "permissions": [p],
                  "roles": ["claims_handler", "fraud_analytics", "finance"],
                  "reviewer_roles": ["special_investigations", "claims_manager"]} for p in sorted(PERMISSIONS)]
        users.append({"name": "nobody", "token_sha256": hash_token("tok-nobody"), "permissions": []})
        for name, token in TOKENS.items():
            os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
        base = __import__("json").loads((ROOT / "examples" / "auto_insurance" / "server.json").read_text())
        cls.svc = service(automations=base["automations"], users=base["users"] + users)
        u = {x.name: x for x in cls.svc.users}
        done = cls.svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        waiting = cls.svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
        scenario = cls.svc.create_scenario(u["hana"], {"name": "probe", "edits": []})
        batch = cls.svc.ingest("claims_feed", "matrix", True)
        cls.ids = {"{id}": done["run_id"], "{name}": "claims", "{key}": "nokey"}
        cls.specific = {  # real ids, so that "not found" cannot hide a missing permission check
            "/api/runs/{id}": done["run_id"], "/api/runs/{id}/audit": done["run_id"],
            "/api/runs/{id}/resume": done["run_id"], "/api/reviews/{id}": waiting["pending_review"],
            "/api/reviews/{id}/decision": waiting["pending_review"], "/api/objects/{id}": "CL-1",
            "/api/objects/{id}/lineage": "CL-1", "/api/questions/{id}": "CQ-01",
            "/api/scenarios/{id}": scenario["scenario_id"], "/api/scenarios/{id}/edits": scenario["scenario_id"],
            "/api/scenarios/{id}/compare": scenario["scenario_id"],
            "/api/scenarios/{id}/commit": scenario["scenario_id"],
            "/api/scenarios/{id}/discard": scenario["scenario_id"],
            "/api/pipelines/{name}/run": "claims_feed", "/api/agents/{name}/reinstate": "claims",
            "/api/automations/{name}/run": "settle_new_claims", "/api/ingest-batches/{id}": batch["batch_id"],
        }

    def path(self, template):
        value = self.specific.get(template)
        return re.sub(r"\{[a-z]+\}", value or "x", template)

    def test_the_documented_routes_are_found(self):
        routes = documented_routes()
        self.assertGreater(len(routes), 40)

    def test_no_route_answers_a_user_without_its_permission(self):
        checked = 0
        for method, template, need in documented_routes():
            for perm in sorted(PERMISSIONS) + [None]:
                name = f"only-{perm}" if perm else "nobody"
                perms = frozenset([perm]) if perm else frozenset()
                if allowed(need, perms):
                    continue
                with self.subTest(route=f"{method} {template}", user=name):
                    headers = {"Authorization": f"Bearer tok-{perm or 'nobody'}", "Content-Type": "application/json"}
                    ex = ApiExchange(self.svc, method, self.path(template), headers,
                                     b"{}" if method == "POST" else None, None).run()
                    self.assertFalse(200 <= ex.status < 300, f"{name} got {ex.status} from {method} {template}")
                    checked += 1
        self.assertGreater(checked, 150)

    def test_assistant_and_mcp_tools_never_exceed_the_users_permissions(self):
        for perm in sorted(PERMISSIONS) + [None]:
            user = next(u for u in self.svc.users if u.name == (f"only-{perm}" if perm else "nobody"))
            with self.subTest(user=user.name):
                for tool in tools_for(self.svc, user):
                    self.assertTrue(user.can(tool["permission"]), (user.name, tool["name"]))
                    self.assertNotIn(tool["name"], ("decide_review", "commit_scenario", "reconcile"))


if __name__ == "__main__":
    unittest.main()
