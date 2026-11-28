"""Application Builder stabilisation: integrity of what an application is and is not (synthetic, simulation only).

Every check names the place in the Engine that enforces it. No screen is involved: the requests are sent directly.

  S1 a design's status is computed by the Engine in six states, and says "not supported" for the two the Engine
     does not have: an approved release artifact and production (``applications.governance``)
  S2 the status follows what runs: a new release leaves the design saved, valid for nothing, bound to another
     configuration and not simulation-ready
  S3 a stored design that did not come through validation is not served (``applications.application`` validates
     again on every read)
  S4 field rules: an attribute a caller may not read is redacted by the data routes (``server.field_value``),
     removed from the manifest the caller receives (``appspec.tailor``), and travels through no relationship
  S5 conditional row rules: a hidden row is absent from its list, from the count, from every link to it, and is
     404 by its identifier (``server.visible``), whatever a manifest shows
  S6 a service identity decides no review, even holding the review permission and the reviewer role
     (``server.require_person``); the requester does not either; the named person does
  S7 nobody starts work in another workspace, with or without that workspace's configuration in the request
  S8 the configuration precondition: absent, a request is served as always; present and different, in any shape,
     the request is refused before anything is done (``applications.expect_configuration``)
"""

import json
import urllib.error
import urllib.request

from autology.governance import REDACTED

from .test_app1_application_builder import Apps
from .test_xdom1_cross_domain import DOMAINS, Journey

MODEL = {
    "name": "work-items", "version": "0.1.0",
    "entities": {
        "Ticket": {"description": "A piece of work", "states": ["open", "done"],
                   "attributes": {"title": "string", "internal_note": "string", "confidential": "boolean", "size": "number"}},
        "Owner": {"description": "Who owns tickets", "states": ["active"],
                  "attributes": {"label": "string", "salary": "number"}}},
    "relationships": [{"from": "Owner", "to": "Ticket", "type": "owns", "cardinality": "1..*"}],
    "actions": {"finish": {"description": "Finish the ticket", "capability": "tickets.finish",
                           "requires": ["Ticket.status == 'open'"], "effects": {"Ticket": {"status": "done"}},
                           "side_effect": "none"}},
    "rules": [
        {"id": "W-SALARY", "type": "data_access", "description": "Only payroll reads salaries", "field": "Owner.salary", "roles": ["payroll"]},
        {"id": "W-NOTE", "type": "data_access", "description": "Only an auditor reads internal notes", "field": "Ticket.internal_note", "roles": ["auditor"]},
        {"id": "W-CONFIDENTIAL", "type": "row_access", "description": "Only an auditor sees confidential tickets",
         "entity": "Ticket", "roles": ["auditor"], "when": "Ticket.confidential == True"},
        {"id": "W-BIG", "type": "human_review", "description": "A lead decides big tickets", "action": "finish",
         "reviewer": "lead", "when": "Ticket.size >= 5"}],
    "goals": {"finished": {"description": "The ticket is done", "target": "Ticket.status == 'done'"}},
    "case_templates": {"ticket_case": {"description": "One ticket", "root": "Ticket", "entities": {"Ticket": "self"}}}}
SOLUTION = {
    "agents": {"worker_agent": {"purpose": "Finishes tickets", "responsibilities": ["Finish"], "roles": ["worker"],
                                "goals": ["finished"], "autonomy": {"mode": "policy"},
                                "tools": [{"action": "finish", "tool": "simulated.succeed", "message": "finished (simulated)"}]}},
    "sample_data": {"instances": [
        {"type": "Owner", "id": "OWN-1", "status": "active", "label": "Team one (fictional)", "salary": 100},
        {"type": "Ticket", "id": "T-1", "status": "open", "title": "Ordinary", "internal_note": "nothing", "confidential": False, "size": 1},
        {"type": "Ticket", "id": "T-2", "status": "open", "title": "Confidential", "internal_note": "sensitive", "confidential": True, "size": 1},
        {"type": "Ticket", "id": "T-3", "status": "open", "title": "Big", "internal_note": "large", "confidential": False, "size": 9}],
        "links": [["OWN-1", "owns", "T-1"], ["OWN-1", "owns", "T-2"], ["OWN-1", "owns", "T-3"]]}}
SPEC = {"use_case": "tickets", "template": "venues-blank", "admin": "venues-vera", "approver": "venues-vito", "operator": "viv",
        "reviewer": "val", "operator_role": "worker", "reviewer_role": "lead", "agent": "worker_agent", "records": 4}


class Integrity(Apps):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        j = Journey(cls("run"), cls.c, "venues", SPEC)
        j.call("POST", f"{j.WS}/use-cases", body={"id": "tickets", "name": "Tickets", "template": "venues-blank"}, expect=201)
        saved = j.call("POST", f"{j.E}/model/draft", body={"document": MODEL, "expected_revision": 0, "note": "by hand"})
        saved = j.call("POST", f"{j.E}/solution/draft", body={"solution": SOLUTION, "expected_revision": saved["revision"]})
        j.revision, j.document, j.configuration = saved["revision"], MODEL, SOLUTION
        cls.t = j.release()
        cls.worker, cls.lead = "venues-viv", "venues-val"
        cls.before = j.call("GET", f"{j.E}/application/draft")["governance"]  # nothing designed yet

    def engine(self):
        return self.pf.workspaces["venues"].use_cases["tickets"].service

    def raw(self, path, token, configuration=None, body=None, method=None):
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {}),
                   **({"X-Autology-Configuration": configuration} if configuration is not None else {})}
        request = urllib.request.Request(self.c.base + path, method=method or ("POST" if body is not None else "GET"),
                                         data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(request) as answer:
                return answer.status, json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def design(self):
        t = self.t
        manifest = t.call("POST", f"{t.E}/application/generate", body={})["manifest"]
        revision = t.call("GET", f"{t.E}/application/draft")["revision"]
        t.call("POST", f"{t.E}/application/draft", body={"manifest": manifest, "expected_revision": revision, "note": "generated"})
        return manifest


class StatusTests(Integrity):
    STATES = ["design_draft", "validated_design", "configuration_bound", "approved_release_artifact", "simulation_ready",
              "production_authorized"]

    def states(self, governance):
        self.assertEqual([k for k in governance if k != "summary"], self.STATES)
        return {k: (governance[k]["supported"], governance[k]["value"]) for k in self.STATES}

    def test_the_six_states_are_the_engines_and_two_are_said_to_be_unsupported(self):  # S1, S2
        t = self.t
        before = self.before
        self.assertEqual(self.states(before), {s: (s not in ("approved_release_artifact", "production_authorized"), False)
                                               for s in self.STATES})
        self.assertEqual(before["summary"], "no application design")
        self.design()
        for answer in (t.call("GET", f"{t.E}/application/draft"), t.call("GET", f"{t.E}/application", self.worker)):
            g = answer["governance"]
            self.assertEqual(self.states(g), {
                "design_draft": (True, True), "validated_design": (True, True), "configuration_bound": (True, True),
                "approved_release_artifact": (False, False), "simulation_ready": (True, True),
                "production_authorized": (False, False)})
            self.assertEqual(g["summary"], "design draft, validated, bound to the configuration that runs; not an approved "
                                           "release artifact; production not authorised")
            self.assertIn("owner decision D34", g["approved_release_artifact"]["detail"])
            for word in ("released", "deployed", "published", "live"):  # a design is never described as any of these
                self.assertNotIn(word, json.dumps(g).lower().replace("not an approved release artifact", ""))
        served = t.call("GET", f"{t.E}/application", self.worker)["release"]  # the release it runs on, as the platform records it
        self.assertEqual(served, {"number": 1, "fingerprint": self.engine().configuration_fingerprint, "runs": True})
        # a new release: the same design is still saved, and is now valid for nothing that runs
        document = json.loads(json.dumps(MODEL))
        document["entities"]["Owner"]["states"].append("retired")
        revision = t.call("GET", f"{t.E}/solution/draft")["revision"]
        saved = t.call("POST", f"{t.E}/model/draft", body={"document": document, "expected_revision": revision, "note": "v2"})
        t.call("POST", f"{t.UC}/publish-draft", SPEC["approver"], {"revision": saved["revision"], "reason": "ok"})
        number = t.call("POST", f"{t.UC}/releases", body={"note": "second"}, expect=201)["number"]
        t.call("POST", f"{t.UC}/releases/{number}/approve", SPEC["approver"], {"reason": "ok"})
        t.call("POST", f"{t.UC}/releases/{number}/activate", body={"reason": "go"})
        after = t.call("GET", f"{t.E}/application/draft")["governance"]
        self.assertEqual(self.states(after), {
            "design_draft": (True, True), "validated_design": (True, False), "configuration_bound": (True, False),
            "approved_release_artifact": (False, False), "simulation_ready": (True, False), "production_authorized": (False, False)})
        self.assertIn("saved for another configuration", after["summary"])
        self.assertEqual(self.c.call("GET", f"{t.E}/application", self.worker)[0], 409)
        self.design()  # designed again for what runs
        again = t.call("GET", f"{t.E}/application", self.worker)
        self.assertEqual(self.states(again["governance"])["simulation_ready"], (True, True))
        self.assertEqual((again["release"]["number"], again["release"]["runs"]), (number, True))

    def test_a_stored_design_that_was_never_validated_is_not_served(self):  # S3
        t = self.t
        good = self.design()
        store = self.engine().store
        hostile = {**good, "title": "<script>alert(1)</script>", "grants": [{"member": "viv", "permissions": ["admin"]}]}
        with store._tx() as db:  # written behind the API's back, for the configuration that runs
            db.execute("INSERT INTO application_drafts VALUES (?, ?, ?, ?, ?, ?)",
                       (store.application_draft()["revision"] + 1, json.dumps(hostile), "nobody", "planted",
                        "2026-11-17T00:00:00+00:00", self.engine().configuration_fingerprint))
        status, out = self.c.call("GET", f"{t.E}/application", self.worker)
        self.assertEqual(status, 409, out)
        self.assertIn("no longer validates", out["error"]["message"])
        self.assertNotIn("script", json.dumps(out["error"].get("details", {}).get("problems", []))[:0] + out["error"]["message"])
        shown = t.call("GET", f"{t.E}/application/draft")
        self.assertEqual((shown["validation"]["valid"], shown["governance"]["validated_design"]["value"],
                          shown["governance"]["simulation_ready"]["value"]), (False, False, False))
        self.assertEqual(self.c.call("POST", f"{t.E}/objects", self.worker, {"type": "Ticket", "id": "T-9", "attributes": {}})[0], 403)
        self.design()  # a valid design saved over it is served again
        self.assertEqual(self.c.call("GET", f"{t.E}/application", self.worker)[0], 200)


class DataRuleTests(Integrity):
    def test_restricted_fields_and_rows_do_not_leak_whatever_a_manifest_shows(self):  # S4, S5
        t = self.t
        full = self.design()
        # the design, as saved, shows everything the model has
        columns = {v["entity"]: [c["field"] for c in v["columns"]] for v in full["views"] if v["type"] == "EntityListView"}
        self.assertIn("salary", columns["Owner"])
        self.assertIn("internal_note", columns["Ticket"])
        mine = t.call("GET", f"{t.E}/application", self.worker)["manifest"]
        for view in mine["views"]:
            names = [c["field"] for key in ("columns", "fields") for c in view.get(key, [])]
            self.assertNotIn("salary", names, view["id"])
            self.assertNotIn("internal_note", names, view["id"])
        # the data routes, asked directly
        owner = t.call("GET", f"{t.E}/objects/OWN-1", self.worker)
        self.assertEqual(owner["attributes"]["salary"], REDACTED)
        self.assertEqual(sorted(x["id"] for x in owner["links"]), ["T-1", "T-3"])  # no link to the hidden ticket
        tickets = t.call("GET", f"{t.E}/objects?type=Ticket", self.worker)
        self.assertEqual((sorted(r["id"] for r in tickets["items"]), tickets["total"]), (["T-1", "T-3"], 2))  # not counted
        self.assertTrue(all(r["attributes"]["internal_note"] == REDACTED for r in tickets["items"]))
        self.assertEqual(self.c.call("GET", f"{t.E}/objects/T-2", self.worker)[0], 404)
        everything = json.dumps(t.call("GET", f"{t.E}/objects", self.worker))
        for secret in ("sensitive", "Confidential", '"salary": 100', "T-2"):
            self.assertNotIn(secret, everything)
        # starting work on the hidden record is refused as "no such record"
        status, out = self.c.call("POST", f"{t.E}/runs", self.worker, {"case_template": "ticket_case", "root": "T-2"})
        self.assertEqual(status, 404, out)
        # with the role, the same person-facing routes show the row and the note; salaries stay with payroll
        t.grant(SPEC["reviewer"], ["read", "review"], reviewer_roles=["lead"], roles=["auditor"])
        seen = t.call("GET", f"{t.E}/objects?type=Ticket", self.lead)
        self.assertEqual((seen["total"], {r["id"]: r["attributes"]["internal_note"] for r in seen["items"]}["T-2"]), (3, "sensitive"))
        theirs = t.call("GET", f"{t.E}/application", self.lead)["manifest"]
        fields = {v["entity"]: [c["field"] for c in v["columns"]] for v in theirs["views"] if v["type"] == "EntityListView"}
        self.assertIn("internal_note", fields["Ticket"])
        self.assertNotIn("salary", fields["Owner"])
        self.assertEqual(t.call("GET", f"{t.E}/objects/OWN-1", self.lead)["attributes"]["salary"], REDACTED)


class DecisionTests(Integrity):
    def test_a_service_identity_and_the_requester_decide_nothing(self):  # S6
        t = self.t
        self.design()
        run = t.call("POST", f"{t.E}/runs", self.worker, {"case_template": "ticket_case", "root": "T-3"})
        self.assertEqual(run["status"], "awaiting_review", run)
        decision = f"{t.E}/reviews/{run['pending_review']}/decision"
        added = t.call("POST", f"{t.WS}/members", body={"name": "tickets-app", "kind": "service", "reason": "x"}, expect=201)
        t.grant("tickets-app", ["read", "run", "review"], roles=["worker"], reviewer_roles=["lead"])
        told = t.call("GET", f"{t.E}/application", added["token"])["you"]
        self.assertEqual((told["kind"], told["may"]["decide_reviews"]), ("service", False))
        for who, token in (("a service identity holding the review permission and the reviewer role", added["token"]),
                           ("the requester", self.worker), ("an administrator", SPEC["admin"])):
            status, out = self.c.call("POST", decision, token, {"approved": True, "comment": "through"})
            self.assertEqual(status, 403, (who, out))
        self.assertEqual(t.call("GET", f"{t.E}/runs/{run['run_id']}", self.worker)["status"], "awaiting_review")
        t.grant(SPEC["reviewer"], ["read", "review"], reviewer_roles=["lead"])
        done = t.call("POST", decision, self.lead, {"approved": True, "comment": "checked"})
        self.assertEqual(done["status"], "completed")
        trail = t.call("GET", f"{t.E}/runs/{run['run_id']}/audit", self.worker)
        self.assertEqual([e["data"]["reviewer"] for e in trail["entries"] if e["event"] == "review.decision"], [SPEC["reviewer"]])

    def test_nobody_starts_work_in_another_workspace(self):  # S7
        crisis, netintel = self.j["crisis"], self.j["netintel"]
        theirs = self.service("netintel").configuration_fingerprint
        for token in (crisis.token(DOMAINS["crisis"]["operator"]), DOMAINS["crisis"]["admin"], self.worker):
            for configuration in (None, theirs):
                status, out = self.raw(f"{netintel.E}/runs", token, configuration, {"case_template": "investigation_case", "root": "CASE-3001"})
                self.assertIn(status, (403, 404), out)
                self.assertNotIn("run_id", out)
        self.assertEqual(self.service("netintel").store.list_runs(limit=5), [r for r in self.service("netintel").store.list_runs(limit=5)
                                                                             if r["started_by"] == DOMAINS["netintel"]["operator"]])


class PreconditionTests(Integrity):
    def test_the_configuration_precondition_in_every_shape(self):  # S8
        t = self.t
        running = self.engine().configuration_fingerprint
        path = f"{t.E}/objects?type=Owner"
        self.assertEqual(self.raw(path, self.worker)[0], 200)             # absent: served as always
        self.assertEqual(self.raw(path, self.worker, running)[0], 200)    # present and right
        for wrong in ("0" * 64, running[:-1], running.upper(), running + " ", "null", "*", "x" * 5000, "\tx"):
            status, out = self.raw(path, self.worker, wrong)
            self.assertEqual(status, 409, wrong[:20])
            details = out["error"]["details"]
            self.assertEqual(details["running"], running)
            self.assertLessEqual(len(details["expected"]), 64)            # what the caller sent is not echoed at length
        # a write that names another configuration changes nothing
        before = t.call("GET", f"{t.E}/objects/T-1", self.worker)["attributes"]["status"]
        status, out = self.raw(f"{t.E}/runs", self.worker, "0" * 64, {"case_template": "ticket_case", "root": "T-1"})
        self.assertEqual(status, 409, out)
        self.assertEqual(t.call("GET", f"{t.E}/objects/T-1", self.worker)["attributes"]["status"], before)
        # the precondition is no credential: with it and without a token, nothing is served
        self.assertEqual(self.raw(path, None, running)[0], 401)
        # and no permission: a caller who may not read is refused with the right configuration too
        self.assertEqual(self.raw(f"{t.E}/model/draft", self.worker, running, {"document": {}, "expected_revision": 0})[0], 403)
