"""R2 security sprint, increment B: administrative roles stay administrative (hardening of IAM-1 / IAM-3, D22a).

  H1 an administrator who holds only the administrative role (workspace or tenant) reads no protected data through
     any entry point: REST (v1 and legacy paths), MCP over HTTP, MCP over stdio; the background scheduler gives
     them nothing either
  H2 an explicit, scoped grant to an administrator works only in its scope: row and field rules apply to them as
     to anyone, and the grant reaches no other use case, workspace or tenant
  H3 the engine's ``admin`` permission (unrestricted data access) is never given by accident: the proposer and the
     approver each acknowledge it; without that, nothing is recorded
  H4 access review: every data grant is listed with its origin; grants created by the IAM-3 migration need a
     person's review, with an explicit path (confirm, revoke, replace by a narrower one); nobody confirms their own
     grant; a confirmation does not carry over to a changed grant; all of it survives a restart
  H5 no single administrator takes over a member's access by re-keying them: a new token for a member who holds
     business data is requested by one person and issued by another, who alone sees it
  H6 a removed member's pending proposals end with them: a later namesake inherits nothing
  H7 service identities keep only what they were given: they approve, confirm, request and administer nothing
  H8 the members view states effective permissions and what the caller may do; the platform still decides
  H9 the migration is restart-safe and gives nothing that was not there before
  H10 another workspace's or tenant's administration paths answer 404
"""

import io
import json
import os
from pathlib import Path
from unittest import mock

from autology.mcp import run as mcp_run

from .test_iam3_privilege_separation import Base, DATA_ROUTES
from .test_workspaces import EX

ACME = "/platform/v1/workspaces/acme"


class EntryPointTests(Base):
    group = True

    def test_administrative_roles_read_nothing_through_any_entry_point(self):  # H1
        for token, ws in (("acme-ada", "acme"), ("group-tara", "acme"), ("group-tara", "acme-eu")):
            for prefix in (f"/w/{ws}/u/claims/api/v1", f"/w/{ws}/u/claims/api"):
                for method, path, body in DATA_ROUTES:
                    status, _ = self.call(method, prefix + path, token, body)
                    self.assertEqual(status, 403, (token, prefix, path))
        # MCP over stdio refuses to start a session for them (the platform file is opened by a second process in
        # real life; here the running one is closed first, as the single-writer rule requires)
        self.stop()
        spec_path = Path(self.data_dir) / "platform.json"
        from .test_iam3_privilege_separation import raw_spec

        spec_path.write_text(json.dumps(raw_spec(self.data_dir, True)))
        for token, workspace in (("acme-ada", "acme"), ("group-tara", "acme-eu")):
            with mock.patch.dict(os.environ, {"AUTOLOGY_TOKEN": token}), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                code = mcp_run(str(spec_path), reader=io.StringIO(""), writer=io.StringIO(), use_case="claims",
                               workspace=workspace)
            self.assertEqual(code, 2, err.getvalue())
            self.assertIn("no permission", err.getvalue())

    def test_the_scheduler_gives_administrators_nothing(self):  # H1 (background tasks)
        self.pf.start_background()
        try:
            for ws in self.pf.workspaces.values():
                for uc in ws.use_cases.values():
                    uc.service.tick()
        finally:
            self.pf.stop_background()
        for token, ws in (("acme-ada", "acme"), ("group-tara", "acme")):
            self.assertEqual(self.engine("GET", "/runs", token, ws=ws)[0], 403)
            self.assertEqual(self.engine("GET", "/notifications", token, ws=ws)[0], 403)
            self.assertEqual(self.engine("GET", "/me", token, ws=ws)[1]["permissions"], ["configure"])

    def test_a_scoped_grant_to_an_administrator_stays_in_scope(self):  # H2
        base = f"{ACME}/grants"
        _, g = self.call("POST", base, body={"member": "ada", "use_case": "orders", "permissions": ["read"],
                                             "roles": ["ops"], "reason": "supports order operations"})
        self.assertEqual(self.call("POST", f"{base}/{g['id']}/approve", "acme-maria", {"reason": "ok"})[0], 200)
        mine = self.engine("GET", "/objects?type=Order", uc="orders")[1]["items"]
        olivia = self.engine("GET", "/objects?type=Order", "acme-olivia", uc="orders")[1]["items"]
        lena = self.engine("GET", "/objects?type=Order", "acme-lena", uc="orders")[1]["items"]
        self.assertEqual([o["id"] for o in mine], [o["id"] for o in olivia])  # the same rows as any "ops" member
        self.assertLess(len(mine), len(lena))  # the row rule hides from her what it hides from olivia
        hidden = sorted({o["id"] for o in lena} - {o["id"] for o in mine})
        self.assertEqual(self.engine("GET", f"/objects/{hidden[0]}", uc="orders")[0], 404)
        customer = self.engine("GET", "/objects?type=Customer", uc="orders")[1]["items"][0]
        self.assertEqual(customer["attributes"]["credit_limit"], "***redacted***")  # the field rule applies to her
        self.assertEqual(self.engine("POST", "/objects", body={"type": "Order", "id": "O-X", "attributes": {}},
                                     uc="orders")[0], 403)  # read is read
        self.assertEqual(self.engine("GET", "/objects", uc="claims")[0], 403)  # another use case: nothing
        self.assertEqual(self.engine("GET", "/objects", "acme-ada", ws="northwind")[0], 404)  # another tenant
        self.assertEqual(self.engine("GET", "/objects", "acme-ada", ws="acme-eu")[0], 404)  # another workspace
        _, view = self.call("GET", f"{ACME}/members")
        ada = next(m for m in view["members"] if m["name"] == "ada")
        self.assertEqual(ada["effective"]["orders"], {"permissions": ["configure", "read"], "data_access": "scoped"})
        self.assertEqual(ada["effective"]["claims"], {"permissions": ["configure"], "data_access": "none"})


class UnrestrictedGrantTests(Base):
    def test_unrestricted_access_needs_two_acknowledgements(self):  # H3
        body = {"member": "hana", "use_case": "claims", "permissions": ["read", "admin"], "reason": "incident"}
        status, out = self.call("POST", f"{ACME}/grants", body=body)
        self.assertEqual(status, 400)
        self.assertIn("unrestricted", out["error"]["message"])
        self.assertIn("row and field rules do not apply", out["error"]["message"])
        for wrong in ("yes", 1, False):
            self.assertEqual(self.call("POST", f"{ACME}/grants", body={**body, "unrestricted": wrong})[0], 400)
        _, view = self.call("GET", f"{ACME}/members")
        self.assertEqual(view["pending_grants"], [])  # nothing was recorded
        status, g = self.call("POST", f"{ACME}/grants", body={**body, "unrestricted": True})
        self.assertEqual((status, g["data_access"]), (201, "unrestricted"))
        status, out = self.call("POST", f"{ACME}/grants/{g['id']}/approve", "acme-maria", {"reason": "ok"})
        self.assertEqual(status, 400)  # the approver acknowledges it too
        self.assertEqual(self.engine("GET", "/me", "acme-hana")[1]["permissions"], ["read", "run"])
        status, view = self.call("POST", f"{ACME}/grants/{g['id']}/approve", "acme-maria",
                                 {"reason": "incident 42, until Friday", "unrestricted": True})
        self.assertEqual(status, 200, view)
        self.assertEqual(self.engine("GET", "/me", "acme-hana")[1]["permissions"], ["admin", "read"])
        hana = next(m for m in view["members"] if m["name"] == "hana")
        self.assertEqual(hana["effective"]["claims"]["data_access"], "unrestricted")
        _, review = self.call("GET", f"{ACME}/access-review")
        item = next(i for i in review["items"] if (i["member"], i["use_case"]) == ("hana", "claims"))
        self.assertEqual((item["data_access"], item["origin"], item["granted_by"], item["approved_by"],
                          item["needs_review"]), ("unrestricted", "grant", "ada@acme", "maria@acme", False))
        self.assertTrue(any("row rules" in line for line in review["unrestricted_means"]))
        # a scoped grant needs no acknowledgement and carries none
        status, g2 = self.call("POST", f"{ACME}/grants", body={"member": "ivan", "use_case": "orders",
                                                               "permissions": ["read"], "reason": "x"})
        self.assertEqual((status, g2["data_access"]), (201, "scoped"))

    def test_a_removed_members_proposals_end_with_them(self):  # H6
        _, first = self.call("POST", f"{ACME}/members", body={"name": "zoe", "reason": "joins"})
        _, g = self.call("POST", f"{ACME}/grants", body={"member": "zoe", "use_case": "claims",
                                                         "permissions": ["read"], "reason": "for the first zoe"})
        _, t = self.call("POST", f"{ACME}/grants", body={"member": "hana", "use_case": "orders",
                                                         "permissions": ["read"], "reason": "unrelated"})
        self.assertEqual(self.call("POST", f"{ACME}/members/zoe/remove", body={"reason": "left"})[0], 200)
        _, second = self.call("POST", f"{ACME}/members", body={"name": "zoe", "reason": "another zoe"})
        status, _ = self.call("POST", f"{ACME}/grants/{g['id']}/approve", "acme-maria", {"reason": "late"})
        self.assertEqual(status, 404)
        _, view = self.call("GET", f"{ACME}/members")
        self.assertEqual([p["id"] for p in view["pending_grants"]], [t["id"]])  # the unrelated proposal stays
        self.assertEqual(next(m for m in view["members"] if m["name"] == "zoe")["use_cases"], {})
        self.assertEqual(self.call("GET", "/platform/v1/me", second["token"])[1]["use_cases"], [])
        self.assertEqual(self.call("GET", "/platform/v1/me", first["token"])[0], 401)
        self.start()  # the same after a restart (the log is replayed)
        self.assertEqual(self.call("GET", "/platform/v1/me", second["token"])[1]["use_cases"], [])


class TokenCustodyTests(Base):
    def test_a_member_with_data_is_re_keyed_by_two_people(self):  # H5
        status, out = self.call("POST", f"{ACME}/members/hana/token", body={"reason": "laptop lost"})
        self.assertEqual((status, out["status"]), (202, "pending"))
        self.assertNotIn("token", {k for k in out if k != "note"})  # the requester sees no token
        rid = out["id"]
        self.assertEqual(self.engine("GET", "/me", "acme-hana")[0], 200)  # nothing changed yet
        _, made = self.call("POST", f"{ACME}/members", body={"name": "puppet", "reason": "x"})
        for token in ("acme-ada", made["token"], "acme-ivan", "nw-nadia"):
            status, _ = self.call("POST", f"{ACME}/token-requests/{rid}/approve", token, {"reason": "x"})
            self.assertIn(status, (403, 404), token)
        self.assertEqual(self.engine("GET", "/me", "acme-hana")[0], 200)
        _, view = self.call("GET", f"{ACME}/members")
        self.assertEqual([(r["id"], r["name"], r["requested_by"]) for r in view["pending_token_requests"]],
                         [(rid, "hana", "ada@acme")])
        status, issued = self.call("POST", f"{ACME}/token-requests/{rid}/approve", "acme-maria",
                                   {"reason": "hana confirmed by phone"})
        self.assertEqual(status, 200, issued)
        self.assertEqual(self.engine("GET", "/me", "acme-hana")[0], 401)
        self.assertEqual(self.engine("GET", "/me", issued["token"])[1]["permissions"], ["read", "run"])
        _, view = self.call("GET", f"{ACME}/members")
        hana = next(m for m in view["members"] if m["name"] == "hana")
        self.assertEqual(hana["token_issued_by"], "maria@acme")  # who has seen the token is on record
        self.assertEqual(view["pending_token_requests"], [])
        events = [(e["event"], e["by"]) for e in view["history"] if e["event"].startswith("token_")]
        self.assertEqual(events, [("token_requested", "ada@acme"), ("token_rotated", "maria@acme")])
        self.assertNotIn(issued["token"], json.dumps(view))
        status, _ = self.call("POST", f"{ACME}/token-requests/{rid}/approve", "acme-maria", {"reason": "again"})
        self.assertEqual(status, 404)  # one request, one token
        # once the member replaces it herself, nobody else has seen her token
        _, own = self.call("POST", f"{ACME}/my-token", issued["token"], {})
        _, view = self.call("GET", f"{ACME}/members")
        self.assertEqual(next(m for m in view["members"] if m["name"] == "hana")["token_issued_by"], "self")
        self.assertEqual(self.engine("GET", "/me", own["token"])[0], 200)

    def test_withdrawn_and_orphaned_requests_issue_nothing(self):  # H5
        _, r1 = self.call("POST", f"{ACME}/members/hana/token", body={"reason": "x"})
        status, _ = self.call("POST", f"{ACME}/token-requests/{r1['id']}/withdraw", "acme-maria", {"reason": "x"})
        self.assertEqual(status, 403)  # withdrawing is the administrators'
        self.assertEqual(self.call("POST", f"{ACME}/token-requests/{r1['id']}/withdraw", body={"reason": "found"})[0],
                         200)
        self.assertEqual(self.call("POST", f"{ACME}/token-requests/{r1['id']}/approve", "acme-maria",
                                   {"reason": "x"})[0], 404)
        _, r2 = self.call("POST", f"{ACME}/members/ivan/token", body={"reason": "x"})
        self.assertEqual(self.call("POST", f"{ACME}/members/ivan/remove", body={"reason": "left"})[0], 200)
        self.assertEqual(self.call("POST", f"{ACME}/token-requests/{r2['id']}/approve", "acme-maria",
                                   {"reason": "x"})[0], 404)
        self.assertEqual(self.call("POST", f"{ACME}/token-requests/nope/approve", "acme-maria", {"reason": "x"})[0],
                         404)
        self.assertEqual(self.engine("GET", "/me", "acme-hana")[0], 200)  # untouched throughout
        # a member without business data is re-keyed at once, as before
        _, made = self.call("POST", f"{ACME}/members", body={"name": "zoe", "reason": "x"})
        status, out = self.call("POST", f"{ACME}/members/zoe/token", body={"reason": "x"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", "/platform/v1/me", out["token"])[0], 200)
        self.assertEqual(self.call("GET", "/platform/v1/me", made["token"])[0], 401)

    def test_service_identities_keep_only_what_they_were_given(self):  # H7
        _, bot = self.call("POST", f"{ACME}/members", body={"name": "bot", "kind": "service", "reason": "feed"})
        status, _, _ = self.grant("bot", ["read", "run"], roles=["claims_handler"])
        self.assertEqual(status, 200)
        token = bot["token"]
        self.assertEqual(self.engine("GET", "/me", token)[1]["permissions"], ["read", "run"])
        _, g = self.call("POST", f"{ACME}/grants", body={"member": "ivan", "use_case": "orders",
                                                         "permissions": ["read"], "reason": "x"})
        _, r = self.call("POST", f"{ACME}/members/hana/token", body={"reason": "x"})
        refused = [("POST", f"{ACME}/grants", {"member": "bot", "use_case": "orders", "permissions": ["read"],
                                               "reason": "more"}),
                   ("POST", f"{ACME}/grants/{g['id']}/approve", {"reason": "x"}),
                   ("POST", f"{ACME}/token-requests/{r['id']}/approve", {"reason": "x"}),
                   ("POST", f"{ACME}/members/hana/confirm-grant", {"use_case": "claims", "reason": "x"}),
                   ("POST", f"{ACME}/members/hana/revoke", {"use_case": "claims", "reason": "x"}),
                   ("POST", f"{ACME}/members", {"name": "bot2", "kind": "service", "reason": "x"}),
                   ("GET", f"{ACME}/members", None), ("GET", f"{ACME}/access-review", None),
                   ("POST", f"{ACME}/use-cases/claims/stage", {"to": "pilot", "reason": "x"}),
                   ("POST", f"{ACME}/use-cases/claims/releases", {"note": "x"}),
                   ("POST", f"{ACME}/use-cases/claims/reload", {"reason": "x"})]
        for method, path, body in refused:
            self.assertEqual(self.call(method, path, token, body)[0], 403, path)
        self.assertEqual(self.engine("GET", "/objects", token, uc="orders")[0], 404)
        self.assertEqual(self.engine("GET", "/me", token)[1]["permissions"], ["read", "run"])  # nothing was added
        # a service identity that is made an approver in the configuration still approves nothing
        ws = self.pf.workspaces["acme"]
        self.assertFalse(self.pf.may_approve_releases(ws, ws.members["bot"]))


class AccessReviewTests(Base):
    def migrated(self):
        """A data directory as the software before IAM-3 left it: the administrators' implicit access becomes
        explicit grants at the next start (see test_iam3_privilege_separation.MigrationTests)."""
        self.stop()
        Path(self.data_dir, "admin.db").unlink()
        self.start()

    def review(self, token="acme-ada"):
        status, out = self.call("GET", f"{ACME}/access-review", token)
        self.assertEqual(status, 200, out)
        return out

    def test_migrated_grants_are_reported_and_resolved_by_another_person(self):  # H4
        clean = self.review()
        self.assertEqual(clean["summary"]["needs_review"], 0)  # a new workspace: nothing was given automatically
        self.assertEqual(clean["summary"]["administrators_with_data_access"], 0)
        self.migrated()
        report = self.review()
        mine = [i for i in report["items"] if i["member"] == "ada"]
        self.assertEqual([(i["use_case"], i["origin"], i["data_access"], i["needs_review"], i["granted_by"])
                          for i in mine],
                         [("claims", "migration", "unrestricted", True, "autology"),
                          ("orders", "migration", "unrestricted", True, "autology")])
        self.assertEqual(report["summary"], {"grants": len(report["items"]), "unrestricted": 2,
                                             "administrators_with_data_access": 1, "needs_review": 2})
        others = [i for i in report["items"] if i["member"] != "ada"]
        self.assertTrue(others and all(i["origin"] == "configuration" and not i["needs_review"] for i in others))
        self.assertIn("confirm-grant", report["how_to_resolve"])
        confirm = {"use_case": "claims", "reason": "ada runs claims operations", "unrestricted": True}
        # nobody confirms their own grant; no authority, no confirmation; unrestricted is acknowledged again
        self.assertEqual(self.call("POST", f"{ACME}/members/ada/confirm-grant", "acme-ada", confirm)[0], 403)
        self.assertEqual(self.call("POST", f"{ACME}/members/ada/confirm-grant", "acme-hana", confirm)[0], 403)
        self.assertEqual(self.call("POST", f"{ACME}/members/ada/confirm-grant", "acme-maria",
                                   {**confirm, "unrestricted": None})[0], 400)
        self.assertEqual(self.call("POST", f"{ACME}/members/ada/confirm-grant", "acme-maria",
                                   {**confirm, "use_case": "nope"})[0], 409)
        self.assertEqual(self.review()["summary"]["needs_review"], 2)
        status, report = self.call("POST", f"{ACME}/members/ada/confirm-grant", "acme-maria", confirm)
        self.assertEqual(status, 200, report)
        claims = next(i for i in report["items"] if (i["member"], i["use_case"]) == ("ada", "claims"))
        self.assertEqual((claims["needs_review"], claims["review"]["by"], claims["review"]["reason"]),
                         (False, "maria@acme", "ada runs claims operations"))
        self.assertEqual(self.engine("GET", "/objects")[0], 200)  # confirmed: the approved access is preserved
        # the other one is replaced by a narrower grant (proposed by ada, approved by maria): no longer unrestricted
        status, _, _ = self.grant_on("orders", ["read"], roles=["ops"])
        self.assertEqual(status, 200)
        report = self.review()
        orders = next(i for i in report["items"] if (i["member"], i["use_case"]) == ("ada", "orders"))
        self.assertEqual((orders["origin"], orders["data_access"], orders["needs_review"], orders["approved_by"]),
                         ("grant", "scoped", False, "maria@acme"))
        self.assertEqual(report["summary"]["needs_review"], 0)
        self.assertEqual(report["summary"]["unrestricted"], 1)
        self.start()  # reviews, replacements and origins survive a restart
        again = self.review()
        self.assertEqual([{k: v for k, v in i.items()} for i in again["items"]], report["items"])
        # a confirmation is about the grant as it was: when the grant changes, the review does not carry over
        status, _, _ = self.grant_on("claims", ["read", "admin"], unrestricted=True, approve={"unrestricted": True})
        self.assertEqual(status, 200)
        claims = next(i for i in self.review()["items"] if (i["member"], i["use_case"]) == ("ada", "claims"))
        self.assertEqual((claims["origin"], claims["review"], claims["needs_review"]), ("grant", None, False))
        # revoking is the third path, at once
        self.assertEqual(self.call("POST", f"{ACME}/members/ada/revoke", body={"use_case": "claims",
                                                                               "reason": "not needed"})[0], 200)
        self.assertEqual([i["use_case"] for i in self.review()["items"] if i["member"] == "ada"], ["orders"])
        self.assertEqual(self.engine("GET", "/objects")[0], 403)
        _, view = self.call("GET", f"{ACME}/members")
        confirmed = [e for e in view["history"] if e["event"] == "grant_confirmed"]
        self.assertEqual([(e["by"], e["data"]["member"], e["data"]["use_case"]) for e in confirmed],
                         [("maria@acme", "ada", "claims")])

    def grant_on(self, uc, permissions, approve=None, **extra):
        status, g = self.call("POST", f"{ACME}/grants", body={"member": "ada", "use_case": uc,
                                                              "permissions": permissions, "reason": "x", **extra})
        self.assertEqual(status, 201, g)
        status, out = self.call("POST", f"{ACME}/grants/{g['id']}/approve", "acme-maria",
                                {"reason": "ok", **(approve or {})})
        return status, out, g["id"]

    def test_an_unrestricted_grant_written_in_the_configuration_needs_review(self):  # H4
        self.stop()
        from .test_iam3_privilege_separation import raw_spec
        from .test_r2_use_case_lifecycle import close
        from autology.platform import Platform

        spec = raw_spec(self.data_dir)
        hana = next(m for m in spec["workspaces"]["acme"]["members"] if m["name"] == "hana")
        hana["use_cases"]["claims"]["permissions"] = ["admin"]
        pf = Platform(spec, EX)
        try:
            report = pf.access_review(pf.workspaces["acme"])
            item = next(i for i in report["items"] if i["member"] == "hana")
            self.assertEqual((item["origin"], item["data_access"], item["needs_review"]),
                             ("configuration", "unrestricted", True))
        finally:
            close(pf)

    def test_the_migration_is_restart_safe_and_adds_nothing(self):  # H9
        self.migrated()
        first = self.review()
        for _ in range(2):
            self.start()
        self.assertEqual(self.review()["items"], first["items"])
        _, view = self.call("GET", f"{ACME}/members")
        events = [e["event"] for e in view["history"]]
        self.assertEqual((events.count("grant_migrated"), events.count("privileges_separated")), (2, 1))
        # an administrator of another tenant got nothing here, and nobody who was not an administrator got anything
        self.assertEqual({i["member"] for i in first["items"] if i["origin"] == "migration"}, {"ada"})
        self.assertEqual(self.engine("GET", "/objects", "nw-nadia", ws="acme")[0], 404)

    def test_the_members_view_states_effective_permissions_and_what_the_caller_may_do(self):  # H8, H10
        _, view = self.call("GET", f"{ACME}/members")
        self.assertEqual(view["you"], {"member": "ada", "may_administer": True, "may_approve": True})
        self.assertEqual([u["id"] for u in view["use_cases"]], ["claims", "orders"])
        self.assertIn("admin", view["permissions"])
        by = {m["name"]: m for m in view["members"]}
        self.assertEqual(by["ada"]["effective"], {"claims": {"permissions": ["configure"], "data_access": "none"},
                                                  "orders": {"permissions": ["configure"], "data_access": "none"}})
        self.assertEqual(by["hana"]["effective"]["claims"], {"permissions": ["read", "run"], "data_access": "scoped"})
        self.assertEqual(by["hana"]["effective"]["orders"], {"permissions": [], "data_access": "none"})
        self.assertEqual(by["hana"]["token_issued_by"], "configuration")
        _, view = self.call("GET", f"{ACME}/members", "acme-maria")
        self.assertEqual(view["you"], {"member": "maria", "may_administer": False, "may_approve": True})
        # "you" is information for a screen; the platform decides again on every call
        self.assertEqual(self.call("POST", f"{ACME}/members", "acme-maria", {"name": "x", "reason": "x"})[0], 403)
        for token in ("acme-hana", "acme-olivia"):
            self.assertEqual(self.call("GET", f"{ACME}/members", token)[0], 403)
            self.assertEqual(self.call("GET", f"{ACME}/access-review", token)[0], 403)
        for path in ("members", "access-review"):  # another tenant's administrator: the same answer as "not there"
            self.assertEqual(self.call("GET", f"{ACME}/{path}", "nw-nadia")[0], 404)
        for path, body in (("members/hana/confirm-grant", {"use_case": "claims", "reason": "x"}),
                           ("members/hana/token", {"reason": "x"}), ("token-requests/t-1/approve", {"reason": "x"}),
                           ("grants", {"member": "hana", "use_case": "claims", "permissions": ["read"],
                                       "reason": "x"})):
            self.assertEqual(self.call("POST", f"{ACME}/{path}", "nw-nadia", body)[0], 404, path)


if __name__ == "__main__":
    import unittest

    unittest.main()
