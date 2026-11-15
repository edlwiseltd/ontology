"""IAM-3: administrative roles carry no business-data access (owner decision D22a, IAM development directive).

  S1 a workspace administrator and a tenant administrator hold the administrative permission only (``configure``)
     in every use case: they design the model and change settings, and are refused every record, run, review,
     audit entry, report, data upload, scheduler pass and MCP message (403 from the engine, not from a screen)
  S2 the administrative powers themselves are intact (use cases, stages, releases, members, reload)
  S3 business data needs an explicit, scoped grant, approved by another person; it then obeys the same row and
     field rules as anyone's; revoking it takes effect at once; every step is in the administration log
  S4 no escalation through role assignment: nobody approves their own proposal or a grant to themselves, an
     administrator cannot use a member they created to approve, a service identity approves nothing, and no API
     call makes an administrator
  S5 migration: administrators of a workspace that already had data keep their access as explicit, revocable
     grants (one per existing use case), recorded once; new workspaces, new administrators and new use cases get
     none; an interrupted migration records nothing; a revoked migrated grant stays revoked after a restart
  S6 boundaries hold: a grant in one workspace gives nothing in another workspace of the tenant, or in another tenant
  S7 separation of duties is unchanged: an administrator with a data grant still cannot review a run they started
  S8 an administrator alone cannot change what members read: the author of a draft revision never publishes it,
     and a release nobody approved cannot be restored (GAP-061, found and reproduced during this increment)
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autology.platform import Platform

from .test_iam1_tenants import CLAIMS, GROUP_TOKENS, HANDLER
from .test_r2_use_case_lifecycle import close
from .test_workspaces import EX, TOKENS, Client

CLAIM = {"type": "Claim", "id": "CL-IAM3", "attributes": {"amount": 5, "status": "reported", "damage_type": "x",
                                                         "reported_days_after": 1}}


def raw_spec(data_dir, group=False):
    """The example platform exactly as configured: administrators have their role and no written-out data grant."""
    spec = json.loads((EX / "platform.json").read_text())
    spec["data_dir"] = data_dir
    for ws in spec["workspaces"].values():
        for uc in ws["use_cases"].values():
            uc["config"] = str((EX / uc["config"]).resolve())
    for t in spec.get("templates", {}).values():
        t["config"] = str((EX / t["config"]).resolve())
    if group:
        spec["workspaces"]["acme-eu"] = {"name": "Acme Europe", "env_prefix": "ACME_", "members": [],
                                         "use_cases": {"claims": {"name": "Motor claims (EU)", "config": CLAIMS}}}
        spec["tenants"] = {"group": {"name": "Acme Group", "workspaces": ["acme", "acme-eu"], "members": [
            {"name": "tara", "token_env": "GROUP_TOKEN_TARA", "tenant_admin": True},
            {"name": "sam", "token_env": "GROUP_TOKEN_SAM", "workspaces": {
                "acme": {"use_cases": {"claims": HANDLER}}, "acme-eu": {"use_cases": {"claims": HANDLER}}}}]}}
    return spec


class Base(unittest.TestCase):
    group = False

    def setUp(self):
        os.environ.update(TOKENS)
        os.environ.update(GROUP_TOKENS)
        self.data_dir = tempfile.mkdtemp()
        self.pf = self.c = None
        self.start()

    def tearDown(self):
        self.stop()

    def start(self):
        self.stop()
        self.pf = Platform(raw_spec(self.data_dir, self.group), EX)
        self.c = Client(self.pf)
        for ws in self.pf.workspaces.values():
            for uc in ws.use_cases.values():
                if not self.pf.stage_of(uc)["history"]:
                    self.pf.lifecycle.move(ws.id, uc.id, uc.service, "simulation", "operator@test", "tests")

    def stop(self):
        if self.c:
            self.c.server.shutdown()
            self.c.server.server_close()
        if self.pf:
            close(self.pf)
        self.pf = self.c = None

    def call(self, method, path, token="acme-ada", body=None):
        return self.c.call(method, path, token, body)

    def engine(self, method, path, token="acme-ada", body=None, ws="acme", uc="claims"):
        return self.call(method, f"/w/{ws}/u/{uc}/api/v1{path}", token, body)

    def grant(self, member, permissions, approver="acme-maria", proposer="acme-ada", ws="acme", **extra):
        status, g = self.call("POST", f"/platform/v1/workspaces/{ws}/grants", proposer, {
            "member": member, "use_case": "claims", "permissions": permissions, "reason": "needs it", **extra})
        self.assertEqual(status, 201, g)
        status, out = self.call("POST", f"/platform/v1/workspaces/{ws}/grants/{g['id']}/approve", approver,
                                {"reason": "checked the need"})
        return status, out, g["id"]


DATA_ROUTES = [("GET", "/objects", None), ("GET", "/objects/CL-1", None), ("GET", "/runs", None),
               ("GET", "/reviews", None), ("GET", "/notifications", None), ("GET", "/report", None),
               ("GET", "/audit-heads", None), ("GET", "/reconciliation", None),
               ("POST", "/objects", CLAIM), ("POST", "/runs", {"case_template": "claim_case", "root": "CL-1"}),
               ("POST", "/tick", {}), ("POST", "/reporting", {}),
               ("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})]


class AdministratorsTests(Base):
    group = True

    def test_administrators_configure_and_reach_no_business_data(self):  # S1
        for token, ws in (("acme-ada", "acme"), ("group-tara", "acme"), ("group-tara", "acme-eu"),
                          ("nw-nadia", "northwind")):
            with self.subTest(token=token, ws=ws):
                status, me = self.engine("GET", "/me", token, ws=ws)
                self.assertEqual((status, me["permissions"]), (200, ["configure"]))
                for method, path, body in DATA_ROUTES:
                    status, out = self.engine(method, path, token, body, ws=ws)
                    self.assertEqual(status, 403, (method, path, out))
                # the administrative side works: the model, its draft, validation, proposals, assistant settings
                status, draft = self.engine("GET", "/model/draft", token, ws=ws)
                self.assertEqual(status, 200)
                for method, path, body in (
                        ("GET", "/ontology", None), ("GET", "/model/draft/history", None),
                        ("POST", "/model/validate", {"document": draft["document"]}),
                        ("POST", "/architect/proposals", {"brief": "pumps and plants"}),
                        ("GET", "/settings/assistant", None)):
                    self.assertEqual(self.engine(method, path, token, body, ws=ws)[0], 200, (method, path))
        self.assertIn("CL-1", self.pf.workspaces["acme"].use_cases["claims"].service.graph._instances)
        self.assertNotIn("CL-IAM3", self.pf.workspaces["acme"].use_cases["claims"].service.graph._instances)
        _, uc = self.call("GET", "/platform/v1/workspaces/acme/use-cases/claims")
        self.assertEqual(uc["permissions"], ["configure"])

    def test_the_administrative_powers_are_intact(self):  # S2
        base = "/platform/v1/workspaces/acme"
        self.assertEqual(self.call("POST", f"{base}/use-cases", body={
            "id": "iam3-case", "name": "IAM-3", "template": "claims-starter"})[0], 201)
        self.assertEqual(self.engine("GET", "/objects", uc="iam3-case")[0], 403)  # created it, still no data
        self.assertEqual(self.call("POST", f"{base}/use-cases/iam3-case/stage", body={
            "to": "simulation", "reason": "try"})[0], 200)
        self.assertEqual(self.call("POST", f"{base}/use-cases/claims/releases", body={"note": "r1"})[0], 201)
        self.assertEqual(self.call("POST", f"{base}/use-cases/claims/reload", body={"reason": "check"})[0], 200)
        self.assertEqual(self.call("GET", f"{base}/members")[0], 200)
        status, draft = self.engine("GET", "/model/draft")
        status, saved = self.engine("POST", "/model/draft", body={
            "document": draft["document"], "expected_revision": draft["revision"], "note": "by the administrator"})
        self.assertEqual((status, saved["revision"]), (200, 1))
        # the tenant administrator administers the other workspace of the tenant the same way, and nothing else
        self.assertEqual(self.call("GET", "/platform/v1/workspaces/acme-eu/members", "group-tara")[0], 200)
        self.assertEqual(self.call("GET", "/platform/v1/workspaces/northwind/members", "group-tara")[0], 404)

    def test_data_access_is_an_explicit_approved_revocable_grant(self):  # S3, S6
        status, out, _ = self.grant("ada", ["read"], approver="acme-ada")
        self.assertEqual(status, 403)  # she proposed it, and it is for herself
        status, out, _ = self.grant("ada", ["read"], roles=["claims_handler"])  # another person approves
        self.assertEqual(status, 200, out)
        status, me = self.engine("GET", "/me")
        self.assertEqual(sorted(me["permissions"]), ["configure", "read"])
        status, items = self.engine("GET", "/objects?type=Claim")
        self.assertEqual(status, 200)
        # the grant is "read" with one role: the same row and field rules as for anyone with that role apply
        _, hana = self.engine("GET", "/objects?type=Claim", "acme-hana")
        self.assertEqual([i["id"] for i in items["items"]], [i["id"] for i in hana["items"]])
        self.assertEqual(self.engine("POST", "/objects", body=CLAIM)[0], 403)   # read is not write
        self.assertEqual(self.engine("GET", "/audit-heads")[0], 403)            # nor audit
        # scoped: this use case only; nothing in the other use case, the other workspace or the other tenant
        self.assertEqual(self.engine("GET", "/objects", uc="orders")[0], 403)
        self.assertEqual(self.engine("GET", "/objects", ws="acme-eu")[0], 404)
        self.assertEqual(self.engine("GET", "/objects", ws="northwind")[0], 404)
        self.assertEqual(self.engine("GET", "/objects", "group-tara", ws="acme")[0], 403)  # tara got no grant
        status, _ = self.call("POST", "/platform/v1/workspaces/acme/members/ada/revoke", body={
            "use_case": "claims", "reason": "no longer needed"})
        self.assertEqual(status, 200)
        self.assertEqual(self.engine("GET", "/objects")[0], 403)  # at the next request
        self.assertEqual(self.engine("GET", "/model/draft")[0], 200)  # the administrative role is untouched
        _, view = self.call("GET", "/platform/v1/workspaces/acme/members")
        events = [e["event"] for e in view["history"]]
        for expected in ("privileges_separated", "grant_proposed", "grant_approved", "grant_revoked"):
            self.assertIn(expected, events)
        self.assertEqual(events.count("grant_migrated"), 0)  # a new workspace: nothing was given automatically

    def test_no_escalation_through_role_assignment(self):  # S4
        base = "/platform/v1/workspaces/acme"
        # a member the administrator creates (and whose token she holds) cannot approve for her
        _, made = self.call("POST", f"{base}/members", body={"name": "puppet", "reason": "x"})
        _, g = self.call("POST", f"{base}/grants", body={"member": "ada", "use_case": "claims", "unrestricted": True,
                                                         "permissions": ["admin"], "reason": "x"})
        for token in ("acme-ada", made["token"], "acme-hana", "group-sam"):
            status, _ = self.call("POST", f"{base}/grants/{g['id']}/approve", token, {"reason": "x"})
            self.assertEqual(status, 403, token)
        # the puppet cannot be made an approver or an administrator through the API
        _, g2 = self.call("POST", f"{base}/grants", body={"member": "puppet", "use_case": "claims", "unrestricted": True,
                                                          "permissions": ["admin", "configure"], "reason": "x"})
        self.assertEqual(self.call("POST", f"{base}/grants/{g2['id']}/approve", "acme-ada", {"reason": "x"})[0], 403)
        _, view = self.call("GET", f"{base}/members")
        puppet = next(m for m in view["members"] if m["name"] == "puppet")
        self.assertEqual((puppet["workspace_admin"], puppet["approver"], puppet["use_cases"]), (False, False, {}))
        # a tenant administrator proposing for herself is refused the same way, in either workspace
        _, g3 = self.call("POST", "/platform/v1/workspaces/acme-eu/grants", "group-tara", {
            "member": "tara", "use_case": "claims", "permissions": ["admin"], "unrestricted": True, "reason": "x"})
        self.assertEqual(self.call("POST", f"/platform/v1/workspaces/acme-eu/grants/{g3['id']}/approve",
                                   "group-tara", {"reason": "x"})[0], 403)
        self.assertEqual(self.engine("GET", "/objects", "group-tara", ws="acme-eu")[0], 403)
        self.assertEqual(self.engine("GET", "/objects")[0], 403)  # nothing above gave ada any data
        # unknown permissions are refused; "admin" on a use case is itself an explicit grant, never implied
        self.assertEqual(self.call("POST", f"{base}/grants", body={"member": "ada", "use_case": "claims",
                                                                   "permissions": ["superuser"], "reason": "x"})[0], 400)

    def test_an_administrator_alone_cannot_change_what_members_read(self):  # S8 (GAP-061)
        """Reproduced before the fix: ada, with ``configure`` only, published a model without the row-access rule
        and olivia then saw the EU order hidden from her."""
        base, eng = "/platform/v1/workspaces/acme/use-cases/orders", dict(uc="orders")
        seen = [o["id"] for o in self.engine("GET", "/objects?type=Order", "acme-olivia", **eng)[1]["items"]]
        self.assertNotIn("O-3", seen)
        _, draft = self.engine("GET", "/model/draft", **eng)
        doc = draft["document"]
        doc["rules"] = [r for r in doc["rules"] if r.get("type") != "row_access"]
        status, saved = self.engine("POST", "/model/draft", body={
            "document": doc, "expected_revision": draft["revision"], "note": "drop the row rule"}, **eng)
        self.assertEqual((status, saved["validation"]["valid"]), (200, True))
        status, out = self.call("POST", f"{base}/publish-draft", body={"revision": saved["revision"], "reason": "alone"})
        self.assertEqual(status, 403)
        self.assertIn("another person", out["error"]["message"])
        after = [o["id"] for o in self.engine("GET", "/objects?type=Order", "acme-olivia", **eng)[1]["items"]]
        self.assertEqual(after, seen)  # nothing changed for anyone
        # a release nobody approved cannot be the way round either
        _, rel = self.call("POST", f"{base}/releases", body={"note": "as configured"})
        status, out = self.call("POST", f"{base}/releases/{rel['number']}/restore", body={"reason": "x"})
        self.assertEqual(status, 409)
        self.assertIn("never approved", out["error"]["message"])
        # members without release authority, and services, cannot publish at all
        for token in ("acme-olivia", "acme-hana"):
            self.assertEqual(self.call("POST", f"{base}/publish-draft", token, {
                "revision": saved["revision"], "reason": "x"})[0] in (403, 404), True)

    def test_separation_of_duties_is_unchanged_for_an_administrator_with_a_grant(self):  # S7
        status, out, _ = self.grant("ada", ["read", "run", "review"], roles=["claims_handler"],
                                    reviewer_roles=["special_investigations"],
                                    run_as={"claims": ["fraud_analytics", "finance"]})
        self.assertEqual(status, 200, out)
        status, run = self.engine("POST", "/runs", body={"case_template": "claim_case", "root": "CL-2"})
        self.assertEqual((status, run["status"]), (200, "awaiting_review"))
        status, out = self.engine("POST", f"/reviews/{run['pending_review']}/decision",
                                  body={"approved": True, "comment": "mine"})
        self.assertEqual(status, 403)
        self.assertIn("started this run", out["error"]["message"])
        status, done = self.engine("POST", f"/reviews/{run['pending_review']}/decision", "acme-ivan",
                                   {"approved": True, "comment": "checked"})
        self.assertEqual(status, 200, done)


class MigrationTests(Base):
    def as_before_iam3(self):
        """A data directory as the previous software left it: workspaces with data, no separation recorded."""
        self.assertEqual(self.call("POST", "/platform/v1/workspaces/acme/use-cases", body={
            "id": "older-case", "name": "Older", "template": "claims-starter"})[0], 201)
        self.stop()
        Path(self.data_dir, "admin.db").unlink()

    def test_existing_administrators_keep_their_access_as_explicit_revocable_grants(self):  # S5
        self.assertEqual(self.engine("GET", "/objects")[0], 403)  # a new workspace: nothing automatic
        self.as_before_iam3()
        self.start()
        for token, ws, uc in (("acme-ada", "acme", "claims"), ("acme-ada", "acme", "orders"),
                              ("acme-ada", "acme", "older-case"), ("nw-nadia", "northwind", "claims")):
            status, me = self.engine("GET", "/me", token, ws=ws, uc=uc)
            self.assertEqual((status, sorted(me["permissions"])), (200, ["admin", "configure"]), (token, uc))
            self.assertEqual(self.engine("GET", "/objects", token, ws=ws, uc=uc)[0], 200)
        _, view = self.call("GET", "/platform/v1/workspaces/acme/members")
        migrated = [e for e in view["history"] if e["event"] == "grant_migrated"]
        self.assertEqual(sorted((e["data"]["member"], e["data"]["use_case"]) for e in migrated),
                         [("ada", "claims"), ("ada", "older-case"), ("ada", "orders")])
        self.assertTrue(all(e["by"] == "autology" and "IAM-3 migration" in e["reason"] for e in migrated))
        marker = [e for e in view["history"] if e["event"] == "privileges_separated"]
        self.assertEqual([(m["data"]["existing_workspace"], m["data"]["grants_migrated"]) for m in marker], [(True, 3)])
        ada = next(m for m in view["members"] if m["name"] == "ada")
        self.assertEqual(sorted(ada["use_cases"]), ["claims", "older-case", "orders"])  # visible, not hidden in a role
        # a use case created after the migration gets nothing; neither do members who were not administrators
        self.assertEqual(self.call("POST", "/platform/v1/workspaces/acme/use-cases", body={
            "id": "newer-case", "name": "Newer", "template": "claims-starter"})[0], 201)
        self.assertEqual(self.engine("GET", "/objects", uc="newer-case")[0], 403)
        self.assertEqual(self.engine("GET", "/objects", "acme-hana", uc="orders")[0], 404)
        # revoked like any grant, at once, and it stays revoked: the migration runs once
        status, _ = self.call("POST", "/platform/v1/workspaces/acme/members/ada/revoke", body={
            "use_case": "orders", "reason": "ada does not work on orders"})
        self.assertEqual(status, 200)
        self.assertEqual(self.engine("GET", "/objects", uc="orders")[0], 403)
        self.start()
        self.assertEqual(self.engine("GET", "/objects", uc="orders")[0], 403)
        self.assertEqual(self.engine("GET", "/objects", uc="claims")[0], 200)
        _, view = self.call("GET", "/platform/v1/workspaces/acme/members")
        self.assertEqual(len([e for e in view["history"] if e["event"] == "privileges_separated"]), 1)

    def test_an_interrupted_migration_records_nothing_and_runs_again(self):  # S5
        self.as_before_iam3()
        from autology.administration import AdminLog

        real, calls = AdminLog._mac, []

        def failing(log, workspace, payload):
            calls.append(payload["event"])
            if len(calls) == 2:
                raise RuntimeError("power cut")
            return real(log, workspace, payload)

        with mock.patch.object(AdminLog, "_mac", failing), self.assertRaises(RuntimeError):
            Platform(raw_spec(self.data_dir), EX)
        probe = AdminLog(Path(self.data_dir) / "admin.db", lambda ws: None)
        self.assertEqual(probe.events("acme")[0], [])  # all or nothing
        probe.close()
        self.start()
        self.assertEqual(self.engine("GET", "/objects")[0], 200)

    def test_a_log_that_does_not_verify_gives_no_data_access(self):  # S5: fail closed
        import sqlite3

        self.as_before_iam3()
        self.start()
        self.assertEqual(self.engine("GET", "/objects")[0], 200)
        self.stop()
        db = sqlite3.connect(Path(self.data_dir) / "admin.db")
        db.execute("DROP TRIGGER admin_events_append_only_u")
        db.execute("UPDATE admin_events SET reason='edited' WHERE workspace='acme' AND seq=1")
        db.commit()
        db.close()
        self.start()
        self.assertEqual(self.engine("GET", "/objects")[0], 403)      # the administrative role only
        self.assertEqual(self.engine("GET", "/model/draft")[0], 200)


if __name__ == "__main__":
    unittest.main()
