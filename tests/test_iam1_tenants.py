"""IAM-1: tenants own workspaces (owner decision D22, IAM development directive).

  T1 backward compatibility: a configuration without tenants gives every workspace its own dedicated tenant, with
     the workspace's id; nothing else changes
  T2 migration: workspaces that already have data are recorded in dedicated tenants whatever the configuration
     says; a configuration that would merge them is refused at start-up (no implicit merging of customers); their
     data and histories are untouched
  T3 the explicit operator action (`tenancy assign`, with a reason) is the only way to move a workspace; it is
     recorded, can be reversed the same way, and the history is append-only and tamper-evident
  T4 an interrupted migration records nothing and is simply run again; a registry newer than the software is refused
  T5 rollback: without the registry (previous software, or a restored data directory) the dedicated tenants are
     rebuilt identically and no data file was changed by the migration
  T6 membership boundaries: belonging to a tenant gives no workspace access; a tenant-level identity reaches only
     the workspaces it explicitly belongs to; a tenant administrator administers every workspace of the tenant
  T7 no cross-tenant access: an identity of one tenant gets the same 404 for another tenant's workspaces, use cases
     and tenant as for ones that do not exist; one token is one identity of one tenant
  T8 MCP: a token reaches only its own memberships; several memberships need --workspace; never another tenant
  T9 background execution of one tenant never touches another tenant's stores
"""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from autology.__main__ import main as cli
from autology.audit import audit_key, workspace_key
from autology.mcp import run as mcp_run
from autology.platform import Platform, PlatformError
from autology.tenancy import Tenancy, TenancyError

from .test_iso1_mcp_per_workspace import HANDSHAKE, tool
from .test_r2_use_case_lifecycle import close
from .test_workspaces import EX, TOKENS, Client

GROUP_TOKENS = {"GROUP_TOKEN_TARA": "group-tara", "GROUP_TOKEN_SAM": "group-sam", "GROUP_TOKEN_ERIN": "group-erin",
                "GROUP_TOKEN_BOT": "group-bot"}
CLAIMS = str((EX / ".." / "auto_insurance" / "server.json").resolve())
HANDLER = {"permissions": ["read", "run"], "roles": ["claims_handler"],
           "run_as": {"claims": ["fraud_analytics", "finance"]}}


def legacy_spec(data_dir):
    """The example platform, as before tenants existed (absolute configuration paths, a given data directory)."""
    spec = json.loads((EX / "platform.json").read_text())
    spec["data_dir"] = data_dir
    for ws in spec["workspaces"].values():
        for uc in ws["use_cases"].values():
            uc["config"] = str((EX / uc["config"]).resolve())
    for t in spec.get("templates", {}).values():
        t["config"] = str((EX / t["config"]).resolve())
    return spec


def group_spec(data_dir):
    """Tenant ``group`` owns ``acme`` and a second workspace ``acme-eu``; ``northwind`` stays a dedicated tenant."""
    spec = legacy_spec(data_dir)
    spec["workspaces"]["acme-eu"] = {"name": "Acme Europe", "env_prefix": "ACME_", "members": [],
                                     "use_cases": {"claims": {"name": "Motor claims (EU)", "config": CLAIMS}}}
    spec["tenants"] = {"group": {"name": "Acme Group", "workspaces": ["acme", "acme-eu"], "members": [
        {"name": "tara", "token_env": "GROUP_TOKEN_TARA", "tenant_admin": True},
        {"name": "sam", "token_env": "GROUP_TOKEN_SAM", "workspaces": {
            "acme": {"use_cases": {"claims": HANDLER}}, "acme-eu": {"use_cases": {"claims": HANDLER}}}},
        {"name": "erin", "token_env": "GROUP_TOKEN_ERIN", "workspaces": {
            "acme-eu": {"use_cases": {"claims": {"permissions": ["read"], "roles": ["claims_handler"]}}}}},
        {"name": "bot", "kind": "service", "token_env": "GROUP_TOKEN_BOT", "workspaces": {
            "acme": {"use_cases": {"claims": {"permissions": ["read"]}}}}}]}}
    return spec


class Base(unittest.TestCase):
    def setUp(self):
        os.environ.update(TOKENS)
        os.environ.update(GROUP_TOKENS)
        self.data_dir = tempfile.mkdtemp()
        self.pf = self.c = None

    def tearDown(self):
        self.stop()

    def start(self, spec, serve=True):
        self.stop()
        self.pf = Platform(spec, EX)
        self.c = Client(self.pf) if serve else None
        return self.pf

    def stop(self):
        if self.c:
            self.c.server.shutdown()
            self.c.server.server_close()
        if self.pf:
            close(self.pf)
        self.pf = self.c = None

    def call(self, method, path, token, body=None):
        return self.c.call(method, path, token, body)

    def simulate(self, *workspaces):
        for ws in workspaces:
            uc = self.pf.workspaces[ws].use_cases["claims"]
            self.pf.lifecycle.move(ws, "claims", uc.service, "simulation", "operator@test", "tests")

    def platform_file(self, spec):
        path = Path(tempfile.mkdtemp()) / "platform.json"
        path.write_text(json.dumps(spec))
        return str(path)

    def tenancy(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli(["tenancy", *args])
        return code, out.getvalue(), err.getvalue()


class CompatibilityAndMigrationTests(Base):
    def test_without_tenants_every_workspace_is_its_own_tenant(self):  # T1
        pf = self.start(legacy_spec(self.data_dir))
        self.assertEqual({t.id: (t.workspaces, t.dedicated) for t in pf.tenants.values()},
                         {"acme": (["acme"], True), "northwind": (["northwind"], True)})
        self.assertEqual(pf.tenancy.current(), {"acme": "acme", "northwind": "northwind"})
        status, me = self.call("GET", "/platform/v1/me", "acme-hana")
        self.assertEqual((status, me["workspace"]["id"], me["tenant"], me["tenant_admin"]),
                         (200, "acme", {"id": "acme", "name": "Acme Insurance & Logistics"}, False))
        self.assertEqual(me["workspaces"], [{"id": "acme", "name": "Acme Insurance & Logistics",
                                             "workspace_admin": False}])
        status, view = self.call("GET", "/platform/v1/tenants/acme", "acme-hana")
        self.assertEqual((status, view["dedicated"], [w["id"] for w in view["workspaces"]]), (200, True, ["acme"]))
        self.assertNotIn("members", view)

    def test_existing_workspaces_migrate_to_dedicated_tenants_and_are_never_merged_implicitly(self):  # T2, T3, T5
        self.start(legacy_spec(self.data_dir))
        self.simulate("acme")
        status, _ = self.call("POST", "/w/acme/u/claims/api/v1/objects", "acme-ada", {
            "type": "Claim", "id": "CL-KEEP", "attributes": {"amount": 5, "status": "reported", "damage_type": "x",
                                                             "reported_days_after": 1}})
        self.assertEqual(status, 200)
        self.stop()
        registry = Path(self.data_dir) / "tenancy.db"
        untouched = {p: p.read_bytes() for p in Path(self.data_dir).glob("*.db") if p.name not in (
            "tenancy.db", "platform.db")}
        registry.unlink()  # the data directory as the previous software left it: no tenancy registry
        merged = legacy_spec(self.data_dir)
        merged["tenants"] = {"group": {"name": "G", "workspaces": ["acme", "northwind"]}}
        with self.assertRaises(PlatformError) as cm:  # the configuration alone never merges two customers
            Platform(merged, EX)
        self.assertIn("never merged or split implicitly", str(cm.exception))
        self.assertIn("tenancy assign", str(cm.exception))
        reg = Tenancy(registry, workspace_key(audit_key(), "platform:tenancy"))  # the platform's own registry key
        self.addCleanup(reg.close)
        events, problem = reg.history()
        self.assertIsNone(problem)
        self.assertEqual([(e["workspace"], e["tenant"], e["event"]) for e in events],
                         [("acme", "acme", "migrated"), ("northwind", "northwind", "migrated")])
        reg.close()
        pf = self.start(legacy_spec(self.data_dir))  # the unchanged configuration starts, data intact
        self.assertEqual(self.call("GET", "/w/acme/u/claims/api/v1/objects/CL-KEEP", "acme-hana")[0], 200)
        self.assertEqual(pf.stage_of(pf.workspaces["acme"].use_cases["claims"])["stage"], "simulation")
        self.stop()
        # T5: the migration added one file and rewrote none of the governance histories
        for path, before in untouched.items():
            self.assertEqual(path.read_bytes(), before, path.name)
        # T3: the explicit, reasoned operator action; then the grouped configuration starts
        cfg = self.platform_file(merged)
        self.assertEqual(self.tenancy("assign", cfg, "acme", "group", "--reason", "short")[0], 3)
        self.assertEqual(self.tenancy("assign", cfg, "nowhere", "group", "--reason", "owner asked on 15 Nov")[0], 2)
        for ws in ("acme", "northwind"):
            code, out, err = self.tenancy("assign", cfg, ws, "group", "--reason", "owner asked: one customer group")
            self.assertEqual(code, 0, err)
        pf = self.start(merged)
        self.assertEqual(pf.tenants["group"].workspaces, ["acme", "northwind"])
        # even merged on purpose, the two customers' people are not merged: each "hana" stays in her workspace
        self.assertEqual(self.call("GET", "/w/northwind/u/claims/api/v1/me", "acme-hana")[0], 404)
        self.assertEqual(self.call("GET", "/w/acme/u/claims/api/v1/me", "nw-hana")[0], 404)
        self.assertEqual(self.call("GET", "/platform/v1/workspaces/northwind/members", "acme-ada")[0], 404)
        self.stop()
        code, out, _ = self.tenancy("show", cfg)
        self.assertEqual(code, 0)
        self.assertIn("reassigned acme -> group", out)
        self.assertIn("owner asked: one customer group", out)
        with self.assertRaises(PlatformError):  # ... and the old configuration no longer matches the record
            Platform(legacy_spec(self.data_dir), EX)
        for ws in ("acme", "northwind"):  # reversed the same explicit way
            self.assertEqual(self.tenancy("assign", cfg, ws, ws, "--reason", "owner asked: separate again")[0], 0)
        self.start(legacy_spec(self.data_dir), serve=False)

    def test_the_history_is_append_only_and_tamper_evident(self):  # T3
        self.start(legacy_spec(self.data_dir), serve=False)
        self.stop()
        db = sqlite3.connect(Path(self.data_dir) / "tenancy.db")
        for sql in ("UPDATE assignments SET tenant='northwind' WHERE workspace='acme'", "DELETE FROM assignments"):
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(sql)
        db.execute("DROP TRIGGER assignments_append_only_u")
        db.execute("UPDATE assignments SET tenant='northwind' WHERE workspace='acme'")
        db.commit()
        db.close()
        with self.assertRaises(PlatformError) as cm:  # fail closed: the platform does not guess who owns what
            Platform(legacy_spec(self.data_dir), EX)
        self.assertIn("changed outside Autology", str(cm.exception))

    def test_an_interrupted_migration_records_nothing_and_a_newer_registry_is_refused(self):  # T4
        Path(self.data_dir, "acme").mkdir()
        Path(self.data_dir, "acme", "marker").write_text("existing data")
        Path(self.data_dir, "northwind").mkdir()
        Path(self.data_dir, "northwind", "marker").write_text("existing data")
        reg = Tenancy(Path(self.data_dir) / "tenancy.db", None)
        real, calls = reg._append, []

        def failing(*args):
            calls.append(args)
            if len(calls) == 2:
                raise RuntimeError("power cut")
            real(*args)

        with mock.patch.object(reg, "_append", failing), self.assertRaises(RuntimeError):
            reg.reconcile({"acme": "acme", "northwind": "northwind"}, {"acme", "northwind"})
        self.assertEqual(reg.current(), {})  # all or nothing
        self.assertEqual(reg.reconcile({"acme": "acme", "northwind": "northwind"}, {"acme", "northwind"}),
                         {"acme": "acme", "northwind": "northwind"})
        with self.assertRaises(TenancyError):
            reg.assign("acme", "acme", "op", "already there, nothing to do")
        reg.close()
        db = sqlite3.connect(Path(self.data_dir) / "tenancy.db")
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        db.commit()
        db.close()
        with self.assertRaises(TenancyError) as cm:
            Tenancy(Path(self.data_dir) / "tenancy.db", None)
        self.assertIn("newer than this Autology", str(cm.exception))

    def test_configuration_errors_are_refused(self):
        def bad(change):
            spec = group_spec(tempfile.mkdtemp())
            change(spec)
            with self.assertRaises(PlatformError):
                Platform(spec, EX)

        g = lambda s: s["tenants"]["group"]  # noqa: E731
        bad(lambda s: s["tenants"].update(other={"workspaces": ["acme"]}))            # a workspace in two tenants
        bad(lambda s: g(s)["workspaces"].append("nowhere"))                           # unknown workspace
        bad(lambda s: g(s)["members"][1]["workspaces"].update(northwind={}))          # membership outside the tenant
        bad(lambda s: g(s)["members"].append({"name": "hana", "token_env": "GROUP_TOKEN_ERIN",
                                              "tenant_admin": True}))                 # the name exists in acme
        bad(lambda s: g(s)["members"].append({"name": "x", "token_env": "ACME_TOKEN_HANA",
                                              "tenant_admin": True}))                 # another identity's token
        bad(lambda s: g(s)["members"].append({"name": "y", "token_env": "GROUP_TOKEN_ERIN"}))  # no membership
        bad(lambda s: g(s)["members"][3].update(tenant_admin=True))                   # a service as tenant admin
        bad(lambda s: s["tenants"].update(northwind={"workspaces": ["acme-eu"]})
            or g(s)["workspaces"].remove("acme-eu"))                                  # tenant id = unlisted workspace
        bad(lambda s: s["workspaces"]["northwind"]["members"][0].update(token_env="GROUP_TOKEN_TARA"))


class BoundaryTests(Base):
    def setUp(self):
        super().setUp()
        self.start(group_spec(self.data_dir))
        self.simulate("acme", "acme-eu", "northwind")

    def test_membership_is_explicit_inside_a_tenant(self):  # T6
        _, me = self.call("GET", "/platform/v1/me", "group-sam")
        self.assertEqual((me["tenant"]["id"], [w["id"] for w in me["workspaces"]]), ("group", ["acme", "acme-eu"]))
        _, eu = self.call("GET", "/platform/v1/me?workspace=acme-eu", "group-sam")
        self.assertEqual(eu["workspace"]["id"], "acme-eu")
        for token, path, status in (
                ("group-sam", "/w/acme/u/claims/api/v1/me", 200),
                ("group-sam", "/w/acme-eu/u/claims/api/v1/me", 200),
                ("group-erin", "/w/acme-eu/u/claims/api/v1/me", 200),
                ("group-erin", "/w/acme/u/claims/api/v1/me", 404),     # same tenant, no membership there
                ("acme-hana", "/w/acme-eu/u/claims/api/v1/me", 404),   # a workspace-level member stays in hers
                ("group-erin", "/platform/v1/me?workspace=acme", 404),
                ("group-erin", "/platform/v1/workspaces/acme/use-cases", 404),
                ("group-sam", "/platform/v1/workspaces/acme-eu/members", 403)):  # a member, not an administrator
            with self.subTest(token=token, path=path):
                self.assertEqual(self.call("GET", path, token)[0], status)
        # the tenant administrator administers both workspaces; nobody else sees the tenant's members
        for ws in ("acme", "acme-eu"):
            status, view = self.call("GET", f"/platform/v1/workspaces/{ws}/members", "group-tara")
            self.assertEqual(status, 200)
            self.assertIn("tara", [m["name"] for m in view["members"]])
        _, t = self.call("GET", "/platform/v1/tenants/group", "group-tara")
        self.assertEqual((t["tenant_admin"], [w["id"] for w in t["workspaces"]], [m["name"] for m in t["members"]]),
                         (True, ["acme", "acme-eu"], ["tara", "sam", "erin", "bot"]))
        _, t = self.call("GET", "/platform/v1/tenants/group", "group-erin")
        self.assertEqual(([w["id"] for w in t["workspaces"]], "members" in t), (["acme-eu"], False))
        # a tenant-level identity is not removed or re-keyed from one workspace; names stay unique in the tenant
        for action in ("remove", "token"):
            self.assertEqual(self.call("POST", f"/platform/v1/workspaces/acme/members/sam/{action}", "acme-ada",
                                       {"reason": "x"})[0], 403)
        status, out = self.call("POST", "/platform/v1/workspaces/acme/members", "group-tara",
                                {"name": "erin", "reason": "erin is a tenant-level identity (member of acme-eu)"})
        self.assertEqual(status, 409)
        self.assertIn("already an identity of tenant group", out["error"]["message"])
        # a workspace-level name stays an identity of its own workspace: acme-eu may have its own, different "hana"
        status, out = self.call("POST", "/platform/v1/workspaces/acme-eu/members", "group-tara",
                                {"name": "hana", "reason": "another person, in the EU workspace"})
        self.assertEqual(status, 201)
        self.assertEqual(self.call("GET", "/w/acme/u/claims/api/v1/me", out["token"])[0], 404)  # not acme's hana

    def test_no_identity_crosses_tenants(self):  # T7
        refused = set()
        for token, path in (
                ("group-tara", "/w/northwind/u/claims/api/v1/me"),          # a tenant administrator, another tenant
                ("group-tara", "/platform/v1/workspaces/northwind/use-cases"),
                ("group-tara", "/platform/v1/workspaces/northwind/members"),
                ("group-tara", "/platform/v1/tenants/northwind"),
                ("group-tara", "/platform/v1/tenants/does-not-exist"),
                ("group-tara", "/platform/v1/me?workspace=northwind"),
                ("group-tara", "/w/nowhere/u/claims/api/v1/me"),
                ("nw-nadia", "/w/acme-eu/u/claims/api/v1/me"),
                ("nw-nadia", "/platform/v1/workspaces/acme/members"),
                ("nw-nadia", "/platform/v1/tenants/group"),
                ("nw-hana", "/w/acme/u/claims/api/v1/objects")):
            status, body = self.call("GET", path, token)
            self.assertEqual(status, 404, (token, path))
            refused.add(json.dumps(body, sort_keys=True))
        self.assertEqual(len(refused), 1)  # one identical answer: nothing reveals that the other tenant exists
        status, _ = self.call("POST", "/platform/v1/workspaces/northwind/members", "group-tara",
                              {"name": "mole", "reason": "x"})
        self.assertEqual(status, 404)
        self.assertNotIn("mole", self.pf.workspaces["northwind"].members)
        # data written in one tenant is invisible in the other, and in the other workspace of the same tenant
        status, _ = self.call("POST", "/w/acme/u/claims/api/v1/objects", "acme-ada", {
            "type": "Claim", "id": "CL-GROUP-1", "attributes": {"amount": 5, "status": "reported",
                                                                "damage_type": "x", "reported_days_after": 1}})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/w/acme/u/claims/api/v1/objects/CL-GROUP-1", "group-sam")[0], 200)
        self.assertEqual(self.call("GET", "/w/acme-eu/u/claims/api/v1/objects/CL-GROUP-1", "group-sam")[0], 404)
        self.assertEqual(self.call("GET", "/w/northwind/u/claims/api/v1/objects/CL-GROUP-1", "nw-hana")[0], 404)

    def test_background_execution_stays_inside_its_workspace_and_tenant(self):  # T9
        services = {ws: self.pf.workspaces[ws].use_cases["claims"].service for ws in ("acme", "acme-eu", "northwind")}

        def state(svc):
            return (svc.store.count_instances(), len(svc.store.list_runs(limit=1000)), len(svc.store.list_firings()))

        for svc in services.values():  # let every workspace settle its own seed data first
            svc.tick()
        before = {ws: state(svc) for ws, svc in services.items()}
        status, _ = self.call("POST", "/w/acme/u/claims/api/v1/objects", "acme-ada", {
            "type": "Claim", "id": "CL-BG-1", "attributes": {"amount": 900, "damage_type": "mirror",
                                                             "reported_days_after": 1, "status": "reported"}})
        self.assertEqual(status, 200)
        for svc in services.values():  # every scheduler runs, as the platform's background threads do
            svc.tick()
        self.assertTrue(services["acme"].store.list_firings())  # the automation fired where the data changed
        self.assertGreater(len(services["acme"].store.list_runs(limit=1000)), before["acme"][1])
        for ws in ("acme-eu", "northwind"):  # the same tenant's other workspace, and the other tenant: untouched
            self.assertEqual(state(services[ws]), before[ws], ws)
            self.assertNotIn("CL-BG-1", services[ws].graph._instances)
        self.assertEqual(len({svc.store.path for svc in services.values()}), 3)
        self.assertEqual(len({svc.audit_key for svc in services.values()}), 3)  # per-workspace audit keys kept


class McpTests(Base):
    def mcp(self, spec_path, token, use_case, workspace=None, *messages):
        out, err = io.StringIO(), io.StringIO()
        stdin = io.StringIO("\n".join(json.dumps(m) for m in (HANDSHAKE,) + messages) + "\n")
        with mock.patch.dict(os.environ, {"MCP_TOKEN": token}), mock.patch("sys.stderr", err):
            code = mcp_run(spec_path, "MCP_TOKEN", stdin, out, use_case=use_case, workspace=workspace)
        return code, [json.loads(line) for line in out.getvalue().splitlines()], err.getvalue()

    def test_mcp_reaches_only_the_tokens_own_memberships(self):  # T8
        path = self.platform_file(group_spec(self.data_dir))
        code, _, err = self.mcp(path, "group-sam", "claims")
        self.assertEqual(code, 2)
        self.assertIn("--workspace", err)  # two memberships: the caller says which, nothing is guessed
        code, replies, _ = self.mcp(path, "group-sam", "claims", "acme-eu", tool("list_objects", type="Claim"))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(replies[1]["result"]["content"][0]["text"])["items"])
        code, replies, _ = self.mcp(path, "group-erin", "claims", None, tool("list_objects", type="Claim"))
        self.assertEqual(code, 0)  # one membership: no ambiguity
        for token, workspace in (("group-erin", "acme"),       # same tenant, no membership
                                 ("group-tara", "northwind"),  # a tenant administrator, another tenant
                                 ("nw-hana", "acme-eu"),       # another tenant's member
                                 ("made-up", None)):
            with self.subTest(token=token, workspace=workspace):
                code, replies, err = self.mcp(path, token, "claims", workspace)
                self.assertEqual((code, replies), (2, []))
                self.assertIn("no such use case for this token", err)


if __name__ == "__main__":
    unittest.main()
