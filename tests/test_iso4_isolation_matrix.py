"""ISO-4: the isolation matrix paths not covered elsewhere — integration credentials, background jobs and the
use-case boundary inside a workspace.

Covered elsewhere: REST through the router and identical 404s (`test_workspaces.py`), MCP (`test_iso1_...`),
audit keys (`test_iso2_...`), company sign-in (`test_iso3_...`), dedicated stores and secrets files
(`test_workspaces.py`), the reporting target (`test_workspaces.py`).
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from autology.platform import Platform, PlatformError

from .test_workspaces import EX, TOKENS

EXAMPLES = EX.parent


def platform_with(claims_tools=None, env_prefix=None, pipelines=None):
    """A copy of the example platform whose Northwind claims use case can be given its own tools/pipelines."""
    os.environ.update(TOKENS)
    folder = Path(tempfile.mkdtemp())
    cfg = json.loads((EXAMPLES / "auto_insurance" / "server.json").read_text())
    for key in ("ontology", "data"):
        cfg[key] = str((EXAMPLES / "auto_insurance" / cfg[key]).resolve())
    tools = json.loads((EXAMPLES / "auto_insurance" / "tools.json").read_text())
    if claims_tools:
        tools["tools"].append(claims_tools)
    (folder / "tools.json").write_text(json.dumps(tools))
    cfg["agents"]["claims"]["tools"] = str(folder / "tools.json")
    cfg["pipelines"] = {}
    if pipelines:
        (folder / "feed.json").write_text(json.dumps(pipelines))
        cfg["pipelines"] = {"feed": str(folder / "feed.json")}
    (folder / "nw_claims.json").write_text(json.dumps(cfg))
    spec = json.loads((EX / "platform.json").read_text())
    spec["data_dir"] = tempfile.mkdtemp()
    for ws in spec["workspaces"].values():
        for uc in ws["use_cases"].values():
            uc["config"] = str((EX / uc["config"]).resolve())
    spec["workspaces"]["northwind"]["use_cases"]["claims"]["config"] = str(folder / "nw_claims.json")
    if env_prefix is not None:
        spec["workspaces"]["northwind"]["env_prefix"] = env_prefix
    return Platform(spec, EX)


HTTP_TOOL = {"name": "bank", "capability": "payments.pay", "type": "http", "url": "https://bank.example/pay",
             "headers": {"Authorization": "Bearer ${%s}"}}


class CredentialScopeTests(unittest.TestCase):
    def test_a_workspace_cannot_reference_another_workspaces_credentials(self):
        with self.assertRaises(PlatformError) as cm:
            platform_with(dict(HTTP_TOOL, headers={"Authorization": "Bearer ${ACME_BANK_TOKEN}"}))
        self.assertIn("ACME_BANK_TOKEN", str(cm.exception))
        self.assertIn("NORTHWIND_", str(cm.exception))

    def test_its_own_prefix_is_allowed(self):
        pf = platform_with(dict(HTTP_TOOL, headers={"Authorization": "Bearer ${NORTHWIND_BANK_TOKEN}"}))
        self.assertIn("claims", pf.workspaces["northwind"].use_cases)

    def test_every_reference_form_is_checked(self):
        mapping = [{"source": "s", "entity": "Claim", "id": "claim_no", "attributes": {"amount": "amount"}}]
        sources = ({"type": "sql", "driver": "psycopg", "dsn_env": "ACME_DB", "query": "select 1"},
                   {"type": "http", "url": "https://x.example/${ACME_URL}"},
                   {"type": "http", "url": "https://x.example", "headers": {"X-Key": {"env": "ACME_KEY"}}})
        for source in sources:
            pipelines = {"name": "feed", "sources": {"s": source}, "mappings": mapping}
            with self.subTest(source):
                with self.assertRaises(PlatformError) as cm:
                    platform_with(pipelines=pipelines)
                self.assertIn("ACME_", str(cm.exception))

    def test_a_workspace_may_declare_its_own_prefix(self):
        with self.assertRaises(PlatformError):
            platform_with(dict(HTTP_TOOL, headers={"Authorization": "Bearer ${NORTHWIND_BANK_TOKEN}"}),
                          env_prefix="NW_")
        platform_with(dict(HTTP_TOOL, headers={"Authorization": "Bearer ${NW_BANK_TOKEN}"}), env_prefix="NW_")


class BackgroundJobTests(unittest.TestCase):
    def test_a_workspaces_scheduler_never_touches_another_workspace(self):
        pf = platform_with()
        acme = pf.workspaces["acme"].use_cases["claims"].service
        nw = pf.workspaces["northwind"].use_cases["claims"].service
        before = (nw.store.count_instances(), len(nw.store.list_runs(limit=1000)), len(nw.store.list_firings()))
        admin = next(u for u in acme.users if u.name == "ada")
        acme.upsert_object(admin, {"type": "Claim", "id": "CL-ACME-1", "attributes": {
            "amount": 900, "damage_type": "mirror", "reported_days_after": 1, "status": "reported"}})
        acme.tick()  # Acme's scheduler: automations, deferred runs, recovery
        self.assertTrue(acme.store.list_firings())
        after = (nw.store.count_instances(), len(nw.store.list_runs(limit=1000)), len(nw.store.list_firings()))
        self.assertEqual(before, after)
        self.assertNotIn("CL-ACME-1", nw.graph._instances)
        self.assertNotEqual(acme.store.path, nw.store.path)
        self.assertNotEqual(acme.lease_instance, nw.lease_instance)


class UseCaseBoundaryTests(unittest.TestCase):
    """Within a workspace, use cases do not share data, agents or grants (the defined policy, ADR-001)."""

    def setUp(self):
        self.pf = platform_with()
        ws = self.pf.workspaces["acme"]
        self.claims, self.orders = ws.use_cases["claims"].service, ws.use_cases["orders"].service

    def test_use_cases_have_separate_stores_graphs_and_agents(self):
        self.assertNotEqual(self.claims.store.path, self.orders.store.path)
        self.assertFalse(set(self.claims.graph._instances) & set(self.orders.graph._instances))
        self.assertFalse(set(self.claims.agents) & set(self.orders.agents))

    def test_a_grant_on_one_use_case_gives_nothing_on_another(self):
        olivia = self.pf.workspaces["acme"].members["olivia"]  # granted orders only
        self.assertIsNone(olivia.grant("claims"))
        self.assertNotIn("olivia", {u.name for u in self.claims.users})


if __name__ == "__main__":
    unittest.main()
