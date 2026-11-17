"""Application Builder: from a released model to a manifest a renderer can show (synthetic, simulation only).

Three unrelated domains on one Engine: crisis management and network intelligence (the two demonstrators) and
venue booking, a third one that has **no template**: its model and configuration are saved through the API as they
are. Nothing here asks a language model anything.

  B1 generation is deterministic and reads structure only: the same model gives the same manifest, byte for byte;
     a model whose every name is replaced by an opaque token gives a manifest of the same shape
  B2 every generated manifest validates, covers the model (a list, a record view and a form per entity, a workflow
     per case template, a review inbox when a rule asks for a person) and says for every choice where it comes from
  B3 the three applications are produced by the same functions through the same routes; no domain word is in them
  B4 validation is closed and repairs nothing: unknown properties, unknown view types, things the model does not
     have, text that is not plain text, roles the model does not have, a missing "what this cannot do"
  B5 a design is saved by a person with ``configure``, over the revision read, never when invalid; revisions are kept
  B6 a manifest is bound to one configuration of one use case: another release, a rollback, another use case or
     another workspace is refused by the Engine (409, 400); a request may name the configuration it expects
  B7 a manifest grants nothing: the Engine removes what a caller can never see and marks what the caller may not
     do; listing a view or a role in a manifest shows nobody a record they could not read
  B8 nobody anonymous and nobody of another workspace reads an application
  B9 writing records stays behind the unrestricted permission: an application user cannot create or change one;
     the nine operations of the D24 proposal are distinct and none of the proposed permissions exists yet
"""

import copy
import json
import re
import unittest

from autology import appspec
from autology.ontology import Ontology

from .helpers import ROOT
from .test_xdom1_cross_domain import DOMAINS, OTHER, PACKS, Hosted, Journey

VENUE = PACKS / "venue_booking"
THIRD = {"use_case": "bookings", "template": "venues-blank", "admin": "venues-vera", "approver": "venues-vito",
         "operator": "viv", "reviewer": "val", "operator_role": "booking_clerk", "reviewer_role": "facilities_manager",
         "case": "booking_case", "root_entity": "BookingRequest", "agent": "booking_agent", "records": 8}


def venue(test, client):
    """The third domain, hosted without any template: the model and the configuration are saved as they are."""
    j = Journey(test, client, "venues", THIRD)
    j.call("POST", f"{j.WS}/use-cases", body={"id": THIRD["use_case"], "name": "Bookings", "template": THIRD["template"]},
           expect=201)
    model, solution = (json.loads((VENUE / name).read_text()) for name in ("model.json", "solution.json"))
    saved = j.call("POST", f"{j.E}/model/draft", body={"document": model, "expected_revision": 0, "note": "written by hand"})
    saved = j.call("POST", f"{j.E}/solution/draft", body={"solution": solution, "expected_revision": saved["revision"]})
    j.revision, j.document, j.configuration = saved["revision"], model, solution
    return j.release()


class Apps(Hosted):
    """The two demonstrators and the third domain, each released and in Simulation, each with a generated manifest."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        probe = cls("run")
        cls.j["venues"] = venue(probe, cls.c)
        cls.generated = {ws: j.call("POST", f"{j.E}/application/generate", body={}) for ws, j in cls.j.items()}

    def manifest(self, ws):
        return copy.deepcopy(self.generated[ws]["manifest"])

    def check(self, ws, manifest):
        j = self.j[ws]
        return j.call("POST", f"{j.E}/application/validate", body={"manifest": manifest})["validation"]

    def save(self, ws, manifest, token=None, expect=200):
        j = self.j[ws]
        revision = j.call("GET", f"{j.E}/application/draft")["revision"]
        return j.call("POST", f"{j.E}/application/draft", token, {"manifest": manifest, "expected_revision": revision,
                                                                  "note": "test"}, expect=expect)


def shape(manifest):
    """What a manifest looks like when names are forgotten: types, sizes and where each choice comes from."""
    return [(v["type"], v["basis"], len(v.get("columns", [])), len(v.get("fields", [])), len(v.get("related", [])),
             len(v.get("actions", [])), len(v.get("rules", [])), len(v.get("tiles", [])), len(v.get("states", [])))
            for v in manifest["views"]] + [len(manifest["navigation"]), len(manifest["roles"])]


class GeneratorTests(Apps):
    def test_the_same_model_gives_the_same_manifest(self):  # B1
        for ws, j in self.j.items():
            again = j.call("POST", f"{j.E}/application/generate", body={})
            self.assertEqual(json.dumps(again["manifest"], sort_keys=True),
                             json.dumps(self.generated[ws]["manifest"], sort_keys=True), ws)
            self.assertEqual(again["validation"]["digest"], self.generated[ws]["validation"]["digest"])
            self.assertEqual((again["generator"]["kind"], again["generator"]["ai"], again["saved"]),
                             ("deterministic", False, False))

    def test_a_model_with_every_name_replaced_gives_a_manifest_of_the_same_shape(self):  # B1
        model = json.loads((VENUE / "model.json").read_text())
        text = json.dumps(model)
        names = (list(model["entities"]) + list(model["actions"]) + list(model["goals"]) + list(model["case_templates"])
                 + sorted({a for e in model["entities"].values() for a in e["attributes"]})
                 + sorted({r["type"] for r in model["relationships"]}) + [r["id"] for r in model["rules"]]
                 + sorted({s for e in model["entities"].values() for s in e["states"]})
                 + ["booking_clerk", "facilities_manager"])
        for i, name in enumerate(sorted(set(names), key=len, reverse=True)):
            token = f"Zq{i}x" if name in model["entities"] else f"zq{i}x"
            text = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", token, text)
        opaque = json.loads(text)
        binding = {"model": "m@1", "model_fingerprint": "f", "configuration": "c", "engine_api": "1"}
        agents = {"a": {"goals": list(model["goals"]), "roles": ["booking_clerk"]}}
        opaque_agents = {"a": {"goals": list(opaque["goals"]), "roles": [r["roles"][0] for r in opaque["rules"] if r.get("roles")]}}
        plain = appspec.generate(Ontology.from_dict(model), agents, binding)
        blind = appspec.generate(Ontology.from_dict(opaque), opaque_agents, binding)
        self.assertEqual(shape(blind), shape(plain))
        self.assertNotIn("Booking", json.dumps(blind))
        self.assertEqual(appspec.validate(blind, Ontology.from_dict(opaque), opaque_agents, binding), [])

    def test_every_manifest_validates_covers_its_model_and_says_where_each_choice_comes_from(self):  # B2
        for ws, out in self.generated.items():
            manifest, onto = out["manifest"], self.service(ws).ontology
            with self.subTest(domain=ws):
                self.assertEqual((out["validation"]["valid"], out["validation"]["problems"]), (True, []))
                by_type = {}
                for view in manifest["views"]:
                    by_type.setdefault(view["type"], []).append(view)
                    self.assertIn(view["basis"], appspec.BASES)
                for kind in ("EntityListView", "EntityDetailView", "RecordFormView"):
                    self.assertEqual(sorted(v["entity"] for v in by_type[kind]), sorted(onto.entities), kind)
                self.assertEqual([v["case_template"] for v in by_type["WorkflowView"]], list(onto.case_templates))
                self.assertEqual(len(by_type["ApprovalInboxView"]), 1)
                self.assertEqual(by_type["ApprovalInboxView"][0]["rules"],
                                 [r.id for r in onto.rules if r.kind == "human_review"])
                self.assertEqual(len(by_type["AuditTimelineView"]), 1)
                detail = next(v for v in by_type["EntityDetailView"] if v["entity"] == by_type["WorkflowView"][0]["entity"])
                self.assertEqual([f["field"] for f in detail["fields"]][0], "status")
                self.assertEqual(len(detail["fields"]) - 1, len(onto.entities[detail["entity"]].attributes) - (
                    1 if "status" in onto.entities[detail["entity"]].attributes else 0))
                choices = [c for v in manifest["views"] for key in ("columns", "fields", "related", "actions", "tiles")
                           for c in v.get(key, [])] + manifest["navigation"]
                self.assertTrue(all(c["basis"] in ("ontology", "configuration", "default") for c in choices))
                self.assertIn("default", {c["basis"] for c in choices})   # presentation defaults are named as such
                self.assertIn("ontology", {c["basis"] for c in choices})
                self.assertNotIn("confirmed", {v["basis"] for v in manifest["views"]})  # nobody confirmed anything yet
                # what it cannot do is part of every application
                self.assertEqual(sorted(u["feature"] for u in manifest["unavailable"]), sorted(appspec.UNAVAILABLE))
                self.assertEqual(manifest["binding"]["workspace"], ws)
                # the workflow names the review and prohibition rules of its actions, for a screen to explain
                rules = {r for a in by_type["WorkflowView"][0]["actions"] for r in a["rules"]}
                self.assertTrue(rules & {r.id for r in onto.rules if r.kind == "human_review"})
                self.assertTrue(rules & {r.id for r in onto.rules if r.kind == "prohibition"})

    def test_three_applications_one_builder_no_domain_in_it(self):  # B3
        self.assertEqual(len({m["manifest"]["id"] for m in self.generated.values()}), 3)
        self.assertEqual(len({json.dumps(shape(m["manifest"])) for m in self.generated.values()}), 3)  # three different apps
        self.assertEqual({type(self.service(ws)).__name__ for ws in self.j}, {"AutologyService"})
        source = "".join((ROOT / "autology" / f).read_text() for f in ("appspec.py", "applications.py"))
        words = set()
        for model in (self.service(ws).ontology for ws in self.j):
            words |= set(model.entities) | set(model.actions) | {r.id for r in model.rules} | set(model.case_templates)
        words -= {"Organization", "Person", "Evidence", "Resource", "Payment", "Contract", "Invoice", "Assignment", "Room",
                  "Deposit", "Shelter", "Hypothesis", "Association", "Infrastructure"}  # single common words
        self.assertEqual(sorted(w for w in words if re.search(rf"\b{re.escape(w)}\b", source)), [])
        self.assertGreater(len(words), 40)
        # the third domain used no template: nothing in the engine or its configuration knows it
        self.assertEqual(self.service("venues").architect.folders, ())
        self.assertFalse(list((ROOT / "autology").rglob("*venue*")))

    def test_nothing_released_nothing_generated(self):  # an application is generated from what runs, never from a draft
        j = self.j["crisis"]
        j.call("POST", f"{j.WS}/use-cases", body={"id": "empty", "name": "Empty", "template": "crisis-blank"}, expect=201)
        status, out = self.c.call("POST", "/w/crisis/u/empty/api/v1/application/generate", DOMAINS["crisis"]["admin"], {})
        self.assertEqual(status, 409, out)
        self.assertIn("nothing is released", out["error"]["message"])


class ValidationTests(Apps):
    def refused(self, ws, change, text):
        manifest = self.manifest(ws)
        change(manifest)
        out = self.check(ws, manifest)
        self.assertEqual(out["valid"], False, text)
        self.assertIn(text, json.dumps(out["problems"]))
        self.save(ws, manifest, expect=400)  # and it is never stored
        return out

    def test_the_schema_is_closed(self):  # B4
        ws = "venues"
        self.refused(ws, lambda m: m.update(permissions=["admin"]), "unexpected 'permissions'")
        self.refused(ws, lambda m: m.update(manifest_version=2), "manifest_version")
        self.refused(ws, lambda m: m["views"][0].update(type="ScriptView"), "ScriptView")
        self.refused(ws, lambda m: m["views"][0].update(onClick="alert(1)"), "unexpected 'onClick'")
        self.refused(ws, lambda m: m["views"][2].update(actions=[]), "has no ['actions']")
        self.refused(ws, lambda m: m["views"][2].pop("columns"), "needs ['columns']")
        self.refused(ws, lambda m: m["views"][2]["columns"][0].update(render="<b>"), "unexpected 'render'")
        self.refused(ws, lambda m: m["presentation"].update(accent="#ff0000"), "accent")
        self.refused(ws, lambda m: m["presentation"].update(stylesheet="x"), "unexpected 'stylesheet'")
        self.refused(ws, lambda m: m["binding"].update(engine_api="9"), "engine_api")
        for bad in ([], "manifest", None, 7):
            self.assertEqual(self.check(ws, bad)["valid"], False)

    def test_only_what_the_model_has_can_be_shown(self):  # B4
        ws = "venues"
        listing = next(i for i, v in enumerate(self.manifest(ws)["views"]) if v["type"] == "EntityListView")
        detail = next(i for i, v in enumerate(self.manifest(ws)["views"]) if v["type"] == "EntityDetailView" and v["related"])
        work = next(i for i, v in enumerate(self.manifest(ws)["views"]) if v["type"] == "WorkflowView")
        inbox = next(i for i, v in enumerate(self.manifest(ws)["views"]) if v["type"] == "ApprovalInboxView")
        self.refused(ws, lambda m: m["views"][listing].update(entity="Salary"), "no entity 'Salary'")
        self.refused(ws, lambda m: m["views"][listing]["columns"][1].update(field="password"), "no attribute 'password'")
        self.refused(ws, lambda m: m["views"][listing].update(title_field="secret"), "no attribute 'secret'")
        self.refused(ws, lambda m: m["views"][detail]["related"][0].update(relationship="owns"), "no relationship")
        self.refused(ws, lambda m: m["views"][detail]["related"][0].update(direction="in" if m["views"][detail]["related"][0]["direction"] == "out" else "out"), "no relationship")
        self.refused(ws, lambda m: m["views"][work].update(case_template="other_case"), "no case template")
        self.refused(ws, lambda m: m["views"][work].update(agent="root_agent"), "no agent 'root_agent'")
        self.refused(ws, lambda m: m["views"][work]["actions"][0].update(action="delete_everything"), "no action")
        self.refused(ws, lambda m: m["views"][work]["actions"][0].update(rules=["R-NONE"]), "no rule 'R-NONE'")
        self.refused(ws, lambda m: m["views"][work].update(states=["approved_by_me"]), "not states of")
        self.refused(ws, lambda m: m["views"][inbox].update(rules=["V-CLOSED-ROOM"]), "is not a review rule")
        self.refused(ws, lambda m: m["navigation"][0].update(view="nowhere"), "no view 'nowhere'")
        self.refused(ws, lambda m: m["views"].append(dict(m["views"][0])), "unique")
        self.refused(ws, lambda m: m["roles"].append("admin"), "never creates or grants")
        self.refused(ws, lambda m: m["roles"].append("platform_admin"), "is not a role of this model")
        self.refused(ws, lambda m: m.update(unavailable=m["unavailable"][1:]), "says what it cannot do")
        self.refused(ws, lambda m: m.update(id="1 app"), "an identifier")

    def test_text_is_text(self):  # B4
        ws = "crisis"
        for hostile in ("<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)",
                        "https://example.invalid/steal", "//example.invalid", "data:text/html,x", "${user.token}",
                        "{{constructor.constructor('x')()}}", "line\x00break", "vbscript:x"):
            for place in (lambda m, t: m.update(title=t), lambda m, t: m["navigation"][0].update(label=t),
                          lambda m, t: m["views"][2]["columns"][0].update(label=t),
                          lambda m, t: m.update(description=t), lambda m, t: m["unavailable"][0].update(reason=t)):
                manifest = self.manifest(ws)
                place(manifest, hostile)
                out = self.check(ws, manifest)
                self.assertFalse(out["valid"], hostile)
                self.assertTrue(any("text only" in p["message"] or "length" in p["message"] for p in out["problems"]), out["problems"])
        manifest = self.manifest(ws)  # ordinary punctuation is ordinary text
        manifest["title"] = "Flood desk: north & south (50% of cases, \"urgent\" first)"
        self.assertTrue(self.check(ws, manifest)["valid"])
        self.assertEqual(self.manifest(ws), self.generated[ws]["manifest"])  # validating changes nothing


class DesignTests(Apps):
    def test_a_design_is_saved_by_a_person_who_may_over_the_revision_read(self):  # B5
        ws = "venues"
        j, manifest = self.j[ws], self.manifest(ws)
        self.assertEqual(j.call("GET", f"{j.E}/application/draft")["manifest"], None)
        self.assertEqual(self.c.call("GET", f"{j.E}/application", THIRD["admin"])[0], 403)  # an administrator has no data access
        operator = j.token(THIRD["operator"])
        self.assertEqual(self.c.call("GET", f"{j.E}/application", operator)[0], 404)  # nothing designed yet
        body = {"manifest": manifest, "expected_revision": 0, "note": "first"}
        self.assertEqual(self.c.call("POST", f"{j.E}/application/draft", operator, body)[0], 403)  # read is not configure
        added = j.call("POST", f"{j.WS}/members", body={"name": "designer-bot", "kind": "service", "reason": "x"}, expect=201)
        j.grant("designer-bot", ["read", "configure"])
        status, out = self.c.call("POST", f"{j.E}/application/draft", added["token"], body)
        self.assertEqual(status, 403, out)  # a service identity does not sign a design
        first = j.call("POST", f"{j.E}/application/draft", body=body)
        self.assertEqual((first["revision"], first["saved"], first["validation"]["valid"]), (1, True, True))
        self.assertEqual(self.c.call("POST", f"{j.E}/application/draft", THIRD["admin"], body)[0], 409)  # stale
        manifest["title"] = "Room bookings"
        manifest["navigation"][0]["basis"] = "confirmed"
        second = self.save(ws, manifest)
        self.assertEqual([(h["revision"], h["author"], h["note"]) for h in second["history"]],
                         [(1, "vera", "first"), (2, "vera", "test")])
        self.assertEqual({h["configuration"] for h in second["history"]}, {self.service(ws).configuration_fingerprint})
        shown = j.call("GET", f"{j.E}/application", operator)
        self.assertEqual((shown["manifest"]["title"], shown["revision"], shown["production"], shown["stage"]),
                         ("Room bookings", 2, False, "simulation"))
        self.assertIn("not part of a governed release", shown["status"])
        # the append-only table refuses a rewrite of history
        store = self.service(ws).store
        with self.assertRaises(Exception):
            with store._tx() as db:
                db.execute("UPDATE application_drafts SET author='someone'")
        self.assertEqual(store.application_draft(1)["author"], "vera")


class BindingTests(Apps):
    def test_another_configuration_another_use_case_another_workspace_are_refused(self):  # B6
        crisis, netintel = self.j["crisis"], self.j["netintel"]
        self.save("crisis", self.manifest("crisis"))
        operator = crisis.token(DOMAINS["crisis"]["operator"])
        before = crisis.call("GET", f"{crisis.E}/application", operator)
        fingerprint = before["running"]["configuration"]
        self.assertEqual(fingerprint, crisis.released["fingerprint"])  # the binding is the release's fingerprint
        # another domain's manifest, or this one renamed, is refused here: nothing is stored
        foreign = self.manifest("netintel")
        out = self.save("crisis", foreign, expect=400)
        told = json.dumps(out)
        for word in ("another model", "another configuration", "another workspace", "another use case"):
            self.assertIn(word, told)
        for key, value in (("configuration", "0" * 64), ("model_fingerprint", "0" * 64), ("workspace", "netintel"),
                           ("use_case", "cases"), ("model", "crisis-management@9.9.9")):
            manifest = self.manifest("crisis")
            manifest["binding"][key] = value
            self.assertFalse(self.check("crisis", manifest)["valid"], key)
        self.assertEqual(self.c.call("GET", f"{netintel.E}/application", netintel.token("alan"))[0], 404)
        # a request may name the configuration it expects: served when it runs, refused when another does
        for path in (f"{crisis.E}/objects", f"{crisis.E}/application", f"{crisis.E}/me"):
            self.assertEqual(self.call_with(path, operator, fingerprint)[0], 200, path)
            status, out = self.call_with(path, operator, "f" * 64)
            self.assertEqual((status, out["error"]["details"]["running"]), (409, fingerprint), path)
        status, out = self.call_with(f"{crisis.E}/runs", operator, "f" * 64, {"case_template": "incident_case", "root": "INC-2005"})
        self.assertEqual(status, 409, out)  # nothing was started for a solution the caller did not mean
        self.assertEqual(crisis.record("INC-2005")["attributes"]["status"], "received")
        # a new release: the model gains a state. The design saved for release 1 is no longer served
        document = json.loads(json.dumps(crisis.document))
        document["entities"]["Shelter"]["states"].append("evacuated")
        revision = crisis.call("GET", f"{crisis.E}/solution/draft")["revision"]
        saved = crisis.call("POST", f"{crisis.E}/model/draft", body={"document": document, "expected_revision": revision, "note": "v2"})
        crisis.call("POST", f"{crisis.UC}/publish-draft", DOMAINS["crisis"]["approver"], {"revision": saved["revision"], "reason": "ok"})
        number = crisis.call("POST", f"{crisis.UC}/releases", body={"note": "second"}, expect=201)["number"]
        crisis.call("POST", f"{crisis.UC}/releases/{number}/approve", DOMAINS["crisis"]["approver"], {"reason": "ok"})
        crisis.call("POST", f"{crisis.UC}/releases/{number}/activate", body={"reason": "go"})
        status, out = self.c.call("GET", f"{crisis.E}/application", operator)
        self.assertEqual(status, 409, out)
        details = out["error"]["details"]
        self.assertEqual(details["designed_for"], fingerprint)
        self.assertNotEqual(details["running"], fingerprint)
        self.assertEqual(self.call_with(f"{crisis.E}/objects", operator, fingerprint)[0], 409)  # the old pin is refused too
        draft = crisis.call("GET", f"{crisis.E}/application/draft")
        self.assertEqual(draft["validation"]["valid"], False)  # the designer sees why
        self.assertIn("another configuration", json.dumps(draft["validation"]["problems"]))
        # generated again for what runs, saved, served
        fresh = crisis.call("POST", f"{crisis.E}/application/generate", body={})["manifest"]
        self.assertNotEqual(fresh["binding"]["configuration"], fingerprint)
        self.save("crisis", fresh)
        self.assertEqual(crisis.call("GET", f"{crisis.E}/application", operator)["running"]["configuration"], details["running"])
        # a rollback to release 1 is a change of configuration like any other: the newer design is not served on it
        crisis.call("POST", f"{crisis.UC}/releases/1/activate", body={"reason": "back"})
        status, out = self.c.call("GET", f"{crisis.E}/application", operator)
        self.assertEqual((status, out["error"]["details"]["running"]), (409, fingerprint), out)

    def call_with(self, path, token, configuration, body=None):
        import urllib.error
        import urllib.request

        request = urllib.request.Request(self.c.base + path, method="POST" if body is not None else "GET",
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                                  "X-Autology-Configuration": configuration})
        try:
            with urllib.request.urlopen(request) as answer:
                return answer.status, json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())


class AuthorityTests(Apps):
    def test_the_engine_removes_what_a_caller_can_never_see_and_grants_nothing(self):  # B7
        j, d = self.j["netintel"], DOMAINS["netintel"]
        manifest = self.manifest("netintel")
        manifest["roles"] = sorted(set(manifest["roles"]) | {"financial_investigator"})  # naming a role gives it to nobody
        self.save("netintel", manifest)
        analyst, reviewer = j.token(d["operator"]), j.token(d["reviewer"])
        mine = j.call("GET", f"{j.E}/application", analyst)
        entities = {v.get("entity") for v in mine["manifest"]["views"]}
        self.assertNotIn("BankAccount", entities)
        self.assertIn("BankAccount", {v.get("entity") for v in manifest["views"]})
        self.assertNotIn("BankAccount", json.dumps(mine["manifest"]["navigation"]) + json.dumps(
            [v.get("related", []) for v in mine["manifest"]["views"]]))
        self.assertEqual(mine["you"]["may"], {"read_records": True, "start_runs": True, "decide_reviews": False,
                                              "read_audit": True, "write_records": False})
        by_type = {v["type"]: v for v in mine["manifest"]["views"]}
        self.assertEqual((by_type["ApprovalInboxView"]["available"], by_type["AuditTimelineView"]["available"]), (False, True))
        self.assertIn("'review' permission", by_type["ApprovalInboxView"]["unavailable_because"])
        # the data routes answer the same whatever a manifest shows: no row, no count, no link
        listed = j.call("GET", f"{j.E}/objects?type=BankAccount", analyst)
        self.assertEqual((listed["items"], listed["total"]), ([], 0))
        self.assertEqual(self.c.call("GET", f"{j.E}/objects/ACC-1", analyst)[0], 404)
        payment = j.call("GET", f"{j.E}/objects/PAY-1", analyst)
        self.assertEqual([x for x in payment["links"] if x["type"] == "BankAccount"], [])
        # the reviewer decides reviews and reads no audit; with the role, a person gets the restricted views
        theirs = j.call("GET", f"{j.E}/application", reviewer)
        self.assertEqual((theirs["you"]["may"]["decide_reviews"], theirs["you"]["may"]["start_runs"],
                          theirs["you"]["may"]["read_audit"]), (True, False, False))
        j.grant(d["reviewer"], ["read", "review"], reviewer_roles=[d["reviewer_role"]], roles=["financial_investigator"])
        self.assertIn("BankAccount", {v.get("entity") for v in j.call("GET", f"{j.E}/application", reviewer)["manifest"]["views"]})
        self.assertNotIn("BankAccount", {v.get("entity") for v in j.call("GET", f"{j.E}/application", analyst)["manifest"]["views"]})
        # a service identity is told it decides nothing
        added = j.call("POST", f"{j.WS}/members", body={"name": "app", "kind": "service", "reason": "x"}, expect=201)
        j.grant("app", ["read", "review"], reviewer_roles=[d["reviewer_role"]])
        self.assertEqual(j.call("GET", f"{j.E}/application", added["token"])["you"]["may"]["decide_reviews"], False)

    def test_nobody_anonymous_and_nobody_of_another_workspace(self):  # B8
        routes = (("GET", "/application"), ("GET", "/application/draft"), ("POST", "/application/draft"),
                  ("POST", "/application/generate"), ("POST", "/application/validate"))
        j = self.j["venues"]  # a few refused sign-ins only: an address that fails too often is locked out for a minute
        for token, (method, path) in ((None, routes[0]), ("not-a-token", routes[0]), (None, routes[2]), (None, routes[3])):
            self.assertEqual(self.c.call(method, j.E + path, token, {} if method == "POST" else None)[0], 401, path)
        for ws in ("crisis", "netintel"):
            mine, theirs = self.j[ws], self.j[OTHER[ws]]
            for method, path in routes:
                status, out = self.c.call(method, theirs.E + path, mine.d["admin"], {} if method == "POST" else None)
                self.assertIn(status, (403, 404), (ws, path, out))
                self.assertNotIn("manifest", out)

    def test_writing_records_stays_behind_the_unrestricted_permission(self):  # B9
        j, d = self.j["crisis"], DOMAINS["crisis"]
        operator = j.token(d["operator"])
        for body in ({"type": "IncidentReport", "id": "INC-9", "attributes": {"reference": "INC-9"}},
                     {"type": "IncidentReport", "id": "INC-2001", "attributes": {"people_at_risk": 1}}):
            status, out = self.c.call("POST", f"{j.E}/objects", operator, body)
            self.assertEqual(status, 403, out)
        self.assertEqual(self.c.call("GET", f"{j.E}/objects/INC-9", operator)[0], 404)
        operations = appspec.PROPOSED_OPERATIONS
        self.assertEqual(list(operations), ["create_case", "read_case", "update_allowed_fields", "perform_workflow_action",
                                            "request_approval", "review_or_approve", "administer_ontology",
                                            "administer_security", "manage_releases"])
        self.assertEqual({o["today"] for k, o in operations.items() if k in ("create_case", "update_allowed_fields")}, {"admin"})
        proposed = {operations[k]["proposed"] for k in ("create_case", "update_allowed_fields")}
        self.assertEqual(proposed, {"operate:create", "operate:update"})
        for permission in sorted(proposed) + ["operate"]:  # proposed only: the platform knows none of them
            status, out = self.c.call("POST", f"{j.WS}/grants", d["admin"], {"member": d["operator"], "use_case": d["use_case"],
                                                                           "permissions": ["read", permission], "reason": "x"})
            self.assertEqual(status, 400, out)
        self.assertEqual(len({o["proposed"] for o in operations.values()}), 8)  # nine operations, eight distinct rights, never one


if __name__ == "__main__":
    unittest.main()
