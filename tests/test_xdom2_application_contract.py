"""R2 cross-domain validation: the contract by which a domain application consumes a released solution.

``examples/domains/reference_app.py`` is a synthetic reference client (not Studio, not an operational application).
The tests run it against both demonstrators with an identity of its own, a **service** member of the workspace:

  C1 an application connects with its own identity and learns what is released: model, fingerprint, case templates,
     actions, agents. It refuses to go on when the solution is not the one it was accepted with
  C2 being connected gives no administrative right: no record writes, no design, no release, no member list, no
     review decision, nothing in the other workspace
  C3 a governed action is asked for, never performed, by the application: the Engine acts, waits or refuses; a
     person decides a review with her own token, and the audit trail names her
  C4 the network-intelligence view is a graph in which every edge says how it is known, with its source; a
     restricted record is refused to the application as to anyone; the summary states no conclusion
  C5 the crisis view lists what the records link to an incident and keeps facts, assumptions, predictions and
     recommendations apart
  C6 the same client class serves both domains; the domain views use only its calls

Everything is invented and simulated. None of it is evidence of fitness for real investigations or emergencies.
"""

import importlib.util
import json

from .test_xdom1_cross_domain import DOMAINS, OTHER, PACKS, Hosted

spec = importlib.util.spec_from_file_location("reference_app", PACKS / "reference_app.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


class ApplicationContractTests(Hosted):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.apps, cls.people = {}, {}
        for ws, j in cls.j.items():
            d = DOMAINS[ws]
            added = j.call("POST", f"{j.WS}/members", body={"name": f"{ws}-app", "kind": "service",
                                                           "reason": "the domain application"}, expect=201)
            j.grant(f"{ws}-app", ["read", "run", "audit"], roles=[d["operator_role"]])
            expects = {"model": json.loads((PACKS / d["pack"] / "ontology.json").read_text())["name"],
                       "case_templates": [d["case"]], "actions": [d["waits"][1]]}
            cls.apps[ws] = ref.Application(cls.c.base, ws, d["use_case"], added["token"], expects)
            cls.people[ws] = {who: ref.Application(cls.c.base, ws, d["use_case"], j.token(d[who]))
                              for who in ("operator", "reviewer")}

    def test_an_application_connects_as_itself_and_checks_what_is_released(self):  # C1, C6
        for ws, app in self.apps.items():
            d = DOMAINS[ws]
            with self.subTest(domain=ws):
                found = app.connect()
                self.assertEqual((found["identity"], found["kind"]), (f"{ws}-app", "service"))
                self.assertEqual(found["permissions"], ["audit", "read", "run"])
                self.assertEqual(found["fingerprint"], self.service(ws).ontology.fingerprint)
                j = self.j[ws]
                self.assertEqual((found["release"]["number"], found["release"]["fingerprint"], found["stage"]),
                                 (1, j.released["fingerprint"], "simulation"))
                self.assertEqual({r["configuration"] for r in j.runs.values()}, {found["release"]["fingerprint"]})
                self.assertEqual(found["case_templates"], {d["case"]: d["root_entity"]})
                self.assertEqual(list(found["agents"]), [d["agent"]])
                self.assertIn(d["waits"][2], [r["id"] for r in found["rules"]])
                # the wrong solution: another model, another fingerprint, a missing action
                for wrong in ({"model": "some-other-model"}, {"fingerprint": "0" * 64}, {"release": "0" * 64},
                              {"stages": ["pilot"]},
                              {"actions": [DOMAINS[OTHER[ws]]["waits"][1]]}):
                    other = ref.Application(self.c.base, ws, d["use_case"], app.token, wrong)
                    with self.assertRaises(ref.ContractError):
                        other.connect()
                self.assertIs(type(app), type(self.apps[OTHER[ws]]))

    def test_being_connected_gives_no_administrative_right(self):  # C2
        for ws, app in self.apps.items():
            j, theirs, d = self.j[ws], self.j[OTHER[ws]], DOMAINS[ws]
            engine = [("POST", "/objects", {"type": d["root_entity"], "id": "NEW-1", "attributes": {}}),
                      ("POST", "/model/draft", {"document": {}, "expected_revision": 0}),
                      ("POST", "/solution/draft", {"solution": {}}),
                      ("POST", "/architect/proposals", {"generator": "model", "brief": "anything"}),
                      ("POST", "/tick", {})]
            with self.subTest(domain=ws):
                for method, path, body in engine:
                    status, out = app.call(method, path, body)
                    self.assertEqual(status, 403, (path, out))
                # known and reported (GAP-093): "read" also reads the design (the draft model and the design
                # sessions with their descriptions and answers). No record is in them and nothing can be changed,
                # but an application needs neither: a narrower permission is proposed, not applied
                self.assertEqual(app.call("GET", "/model/draft")[0], 200)
                self.assertEqual(app.call("GET", "/architect/proposals")[0], 200)
                # the releases of its own use case are readable (who proposed, who approved, what runs): never writable
                self.assertEqual(self.c.call("GET", f"{j.UC}/releases", app.token)[1]["active"]["approved_by"],
                                 f"{d['approver'].split('-')[1]}@{ws}")
                platform = [("GET", f"{j.WS}/members"), ("POST", f"{j.WS}/grants"), ("POST", f"{j.UC}/releases"), ("POST", f"{j.UC}/stage"),
                            ("POST", f"{j.UC}/sample-data"), ("POST", f"{j.UC}/releases/1/activate"),
                            ("GET", f"{theirs.E}/objects"), ("GET", f"{theirs.E}/me"), ("POST", f"{theirs.E}/runs")]
                for method, path in platform:
                    status, out = self.c.call(method, path, app.token, {} if method == "POST" else None)
                    self.assertIn(status, (401, 403, 404), (path, out))
                self.assertEqual(self.service(ws).store.count_instances(), d["records"])
                # every refusal is in the Engine's access log, under the application's own name
                logged = [(e["target"], e["status"]) for e in app.need("GET", "/access-log?limit=200")["items"]
                          if e["principal"] == f"{ws}-app" and e["status"] == 403]
                self.assertLessEqual({("POST /api/v1/objects", 403), ("POST /api/v1/model/draft", 403)}, set(logged))
                self.assertGreaterEqual(len(app.refused), len(engine))  # the client keeps what was refused

    def test_an_application_asks_and_the_engine_and_a_person_decide(self):  # C3
        for ws, app in self.apps.items():
            j, d = self.j[ws], DOMAINS[ws]
            with self.subTest(domain=ws):
                # the journey already ran these records once; a record whose work is finished or waiting is not run twice
                status, out = app.call("POST", "/runs", {"case_template": d["case"], "root": d["waits"][0]})
                self.assertEqual(status, 409, out)
                waiting = j.runs["waits"]
                review = waiting["pending_review"]
                # the application cannot decide; neither can the person who asked
                for who in (app, self.people[ws]["operator"]):
                    self.assertIn(who.decide(review, True, "let it through")[0], (403, 404))
                self.assertEqual(app.run(waiting["run_id"])["status"], "awaiting_review")
                status, done = self.people[ws]["reviewer"].decide(review, True, "checked the file")
                self.assertEqual((status, done["status"]), (200, "completed"), done)
                finished = app.run(waiting["run_id"])
                self.assertEqual((finished["status"], finished["simulated"]), ("completed", True))
                self.assertIn((d["waits"][1], d["reviewer"]), [(s["action"], s["reviewer"]) for s in finished["steps"]])
                trail = app.audit(waiting["run_id"])
                self.assertEqual(trail["verified"], True)
                self.assertEqual([e["data"]["reviewer"] for e in trail["entries"] if e["event"] == "review.decision"],
                                 [d["reviewer"]])
                # the policy's refusal is the same for an application as for a person
                refused = app.run(j.runs["refused"]["run_id"])
                self.assertEqual((refused["status"], refused["steps"]), ("escalated", []))

    def test_the_evidence_graph_says_how_every_edge_is_known(self):  # C4
        app, j = self.apps["netintel"], self.j["netintel"]
        graph = ref.evidence_graph(app)
        self.assertEqual(len(graph["nodes"]), 5)
        self.assertEqual({e["classification"] for e in graph["edges"]}, set(ref.CLASSES))
        self.assertEqual(graph["legend"], {c: 1 for c in ref.CLASSES})
        recorded = {r["id"] for r in app.records("Association")}
        self.assertEqual({e["id"] for e in graph["edges"]}, recorded)  # no edge without a record behind it
        ids = {n["id"] for n in graph["nodes"]}
        for edge in graph["edges"]:
            self.assertTrue(edge["from"] in ids and edge["to"] in ids, edge)
            self.assertTrue(edge["evidence_quality"])
            if edge["classification"] in ("observed_fact", "confirmed_assertion"):
                self.assertTrue(edge["source"], edge)
        unresolved = next(e for e in graph["edges"] if e["classification"] == "unresolved_hypothesis")
        self.assertEqual(((unresolved["from"], unresolved["to"]), unresolved["source"], unresolved["hypotheses"]),
                         (("ORG-2", "ORG-4"), None, ["HYP-2"]))
        self.assertTrue(any(e["valid_from"] and e["valid_to"] for e in graph["edges"]))  # a link bounded in time
        self.assertIn("No link", graph["caution"])
        # the unauthorised read: bank accounts are refused to the application as to any analyst
        before = len(app.refused)
        self.assertEqual(app.call("GET", "/objects/ACC-1")[0], 404)
        self.assertEqual(app.records("BankAccount"), [])
        self.assertEqual(app.refused[before]["path"], "/objects/ACC-1")
        self.assertNotIn("FICT-ACC", json.dumps(graph))
        # the summary of the flagged case: what is observed, what is inferred, the competing explanation, no conclusion
        waiting = j.runs["waits"]
        summary = ref.investigative_summary(app, DOMAINS["netintel"]["waits"][0], waiting["run_id"])
        self.assertEqual(([e["id"] for e in summary["observed"]], [e["id"] for e in summary["inferred"]]),
                         (["ASC-1"], ["ASC-3"]))
        self.assertEqual(len(summary["hypotheses"]), 1)
        self.assertIn("freight agent", summary["hypotheses"][0]["competing_explanation"])
        self.assertTrue(summary["conclusion"].startswith("none"))
        self.assertEqual(summary["audit"]["verified"], True)
        text = json.dumps(summary).lower()
        for word in ("guilty", "guilt", "fraudster", "criminal", "proven", "sanction"):
            self.assertNotIn(word, text)
        unverified = ref.investigative_summary(app, DOMAINS["netintel"]["refused"][0])
        self.assertEqual(([e["id"] for e in unverified["unresolved"]], unverified["observed"], unverified["status"]),
                         (["ASC-2"], [], "opened"))
        self.assertEqual(unverified["evidence"][0]["quality"], "unverified")

    def test_the_incident_view_keeps_facts_predictions_and_recommendations_apart(self):  # C5
        app, j, d = self.apps["crisis"], self.j["crisis"], DOMAINS["crisis"]
        around = ref.affected_resources(app, d["alone"][0])
        self.assertEqual((around["area"]["id"], [x["id"] for x in around["infrastructure"]],
                          [x["id"] for x in around["shelters"]]), ("AREA-NORTHMERE", ["INF-PUMP-1"], ["SH-1"]))
        self.assertEqual(([x["id"] for x in around["teams"]], [x["id"] for x in around["equipment"]]),
                         (["TEAM-2001"], ["RES-2001"]))
        self.assertIn("Not a forecast", around["caution"])
        observed = ref.situation_update(app, d["alone"][0], j.runs["alone"]["run_id"])
        self.assertEqual((len(observed["facts"]), observed["predictions"], observed["assumptions"]), (1, [], []))
        self.assertEqual((observed["run"]["status"], observed["run"]["simulated"], observed["run"]["performed"]),
                         ("completed", True, d["alone"][1]))
        predicted = ref.situation_update(app, d["refused"][0], j.runs["refused"]["run_id"])
        self.assertEqual((predicted["facts"], len(predicted["predictions"])), ([], 1))
        self.assertEqual(predicted["run"]["performed"], [])
        self.assertIn("prohibited", " ".join(predicted["run"]["refused"]))
        self.assertTrue(all("proposal" in r["note"] for r in predicted["recommendations"]))
        unverified = ref.situation_update(app, "INC-2004")
        self.assertEqual((unverified["facts"], len(unverified["assumptions"]), unverified["predictions"]), ([], 1, []))
        # the view is this domain's: the other application's solution has no such records
        with self.assertRaises(ref.ContractError):
            ref.affected_resources(self.apps["netintel"], d["alone"][0])

    def test_the_command_line_names_the_token_by_its_variable_only(self):  # the token is never an argument
        source = (PACKS / "reference_app.py").read_text()
        self.assertIn("--token-env", source)
        self.assertNotIn('"--token"', source)
        self.assertNotIn("print(app.token", source)
