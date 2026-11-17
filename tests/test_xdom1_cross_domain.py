"""R2 cross-domain validation: one Engine and one workflow, two independent applications (synthetic).

Two domain packs that share nothing but the platform (``examples/domains``): **crisis management** (a fictional
flood) and **network intelligence** (a fictional compliance investigation). Each is configuration: a blank model,
the sandbox architect and a folder of blueprints. The hypothesis under test is "one Engine, one Studio, several
independent applications"; the tests look for evidence of actual reuse, and for leaks between the two.

  X1 the same journey, made by the same code through the same routes, works for both domains: a proposal with its
     questions, a revision from the answers, a recorded decision, a draft that names its origin, validation and
     consistency findings, agents and simulated tools, publication by another person, a release approved by
     another person and activated, Simulation, sample records, and stored runs with a verified audit chain
  X2 each domain shows the three governed outcomes: the agent acts alone where the policy allows; it waits for the
     person the policy names; a prohibited action is refused before anything is done
  X3 the engine and Studio hold no vocabulary of either domain (their names, actions, rules, roles, agents), and
     neither pack lives in the engine package
  X4 without a domain's pack the sandbox architect proposes nothing for that domain: it asks. A proposal made from
     a pack says that it is a template and not a language model's reading
  X5 the packs are synthetic and simulated: every tool is a simulated one, every name is marked fictional, every
     link in the investigation data says how it is known, every hypothesis carries its competing explanation
  I1 a member of one workspace reaches nothing of the other: engine, platform, releases, records, runs, reviews
  I2 a permission is held in one workspace only, even by a person of the same name
  I3 a release belongs to its use case: the other workspace can neither approve nor activate it, and each use
     case runs its own release
  I4 nobody approves their own action: not the requester, not an administrator without the reviewer role, not a
     reviewer of the other domain; the named reviewer's decision continues the run and is in the audit chain
  I5 the same entity name and the same record identifier in both domains are two unrelated records
  I6 a configuration cannot reach beyond the simulated tools, nor name an action of the other domain
  I7 a workspace is offered its own templates only; a pack's blueprints answer in its own use cases only
  I8 a row rule hides the rows it names and nothing else: a run that holds no such record is not hidden (the
     general view rule this sprint corrected), and a run that holds one still is

Nothing here is evidence about a language model, and nothing here shows suitability for real emergency response or
for real investigations: every record is invented and every effect is simulated.
"""

import json
import os
import re
import tempfile
import unittest

from autology import architect
from autology.modeling import blueprints, library, match
from autology.platform import Platform
from autology.sandbox_ai import answer

from .helpers import ROOT
from .test_workspaces import Client

PACKS = ROOT / "examples" / "domains"
TOKENS = {f"{ws}_TOKEN_{name.upper()}": f"{ws.lower()}-{name}"
          for ws, names in (("CRISIS", ("carla", "rosa", "omar", "dana", "alex")),
                            ("NETINTEL", ("nora", "ravi", "alan", "cleo", "alex"))) for name in names}

DOMAINS = {
    "crisis": {
        "use_case": "flood", "template": "crisis-blank", "pack": "crisis_management", "blueprint": "flood_response",
        "admin": "crisis-carla", "approver": "crisis-rosa", "operator": "omar", "reviewer": "dana",
        "operator_role": "operations_officer", "reviewer_role": "duty_coordinator",
        "brief": "A regional coordination centre handles a river flood across several municipalities. Take each "
                 "incident report through validation, identify the response teams and equipment that could help, "
                 "propose an allocation and assign a response team; shelters and supply needs are tracked.",
        "answers": {"approval_people_threshold": 50, "coordinator_role": "duty_coordinator",
                    "operations_role": "operations_officer", "dispatch_system": "training dispatch system"},
        "agent": "response_coordinator", "case": "incident_case", "root_entity": "IncidentReport", "records": 25,
        "alone": ("INC-2001", ["validate_report", "identify_resources", "propose_allocation", "assign_response_team",
                               "publish_update"], "updated"),
        "waits": ("INC-2002", "assign_response_team", "R-ASSIGN-APPROVAL", "updated"),
        "refused": ("INC-2003", "assign_response_team", "prediction"),
        "restricted": None,
    },
    "netintel": {
        "use_case": "cases", "template": "netintel-blank", "pack": "network_intelligence",
        "blueprint": "network_investigation",
        "admin": "netintel-nora", "approver": "netintel-ravi", "operator": "alan", "reviewer": "cleo",
        "operator_role": "investigation_analyst", "reviewer_role": "compliance_officer",
        "brief": "Our compliance team reviews a network of companies: contracts, invoices and payments through "
                 "intermediaries, with beneficial ownership declarations. Investigate unusual patterns, record "
                 "competing explanations and let a person decide every escalation.",
        "answers": {"materiality_amount": 10000, "reviewer_role": "compliance_officer",
                    "analyst_role": "investigation_analyst", "financial_role": "financial_investigator",
                    "case_system": "training case system"},
        "agent": "case_analyst", "case": "investigation_case", "root_entity": "CaseFile", "records": 31,
        "alone": ("CASE-3001", ["extract_relationships", "close_without_finding"], "summarised"),
        "waits": ("CASE-3002", "escalate_for_investigation", "R-ESCALATION-REVIEW", "summarised"),
        "refused": ("CASE-3003", "escalate_for_investigation", "unverified"),
        "restricted": ("BankAccount", "ACC-1", "financial_investigator"),
    },
}
OTHER = {"crisis": "netintel", "netintel": "crisis"}


def pack(domain):
    d = DOMAINS[domain]
    return json.loads((PACKS / d["pack"] / "blueprints" / f"{d['blueprint']}.json").read_text())


def hosted():
    """The platform of ``examples/domains``: two workspaces, no use case yet, a fresh data folder."""
    os.environ.update(TOKENS)
    spec = json.loads((PACKS / "platform.json").read_text())
    spec["data_dir"] = tempfile.mkdtemp()
    return Platform(spec, PACKS)


class Journey:
    """The onboarding journey of one domain. The code is the same for every domain: only ``DOMAINS[ws]`` differs.
    ``trace`` is the sequence of routes used, with identifiers replaced, so that two journeys can be compared."""

    def __init__(self, test, client, ws):
        self.t, self.c, self.ws, self.d = test, client, ws, DOMAINS[ws]
        self.WS = f"/platform/v1/workspaces/{ws}"
        self.UC = f"{self.WS}/use-cases/{self.d['use_case']}"
        self.E = f"/w/{ws}/u/{self.d['use_case']}/api/v1"
        self.trace, self.runs = [], {}

    def token(self, name):
        return f"{self.ws}-{name}"

    def call(self, method, path, token=None, body=None, expect=200):
        status, out = self.c.call(method, path, token or self.d["admin"], body)
        shape = path.replace(self.E, "{engine}").replace(self.UC, "{use-case}").replace(self.WS, "{workspace}")
        self.trace.append((method, re.sub(r"/(P-[0-9a-f]+|g-[0-9a-f]+|[0-9a-f]{12}|\d+)(?=/|$)", "/{id}", shape), status))
        if expect is not None:
            self.t.assertEqual(status, expect, (self.ws, method, path, out))
        return out

    def grant(self, member, permissions, **extra):
        g = self.call("POST", f"{self.WS}/grants", body={"member": member, "use_case": self.d["use_case"],
                                                         "permissions": permissions, "reason": "the simulation needs it",
                                                         **extra}, expect=201)
        both = {"unrestricted": True} if extra.get("unrestricted") else {}  # an unrestricted grant is acknowledged twice
        self.call("POST", f"{self.WS}/grants/{g['id']}/approve", self.d["approver"], {"reason": "checked", **both})

    def design(self):
        d = self.d
        self.templates = self.call("GET", "/platform/v1/templates")["items"]
        self.call("POST", f"{self.WS}/use-cases", body={"id": d["use_case"], "name": f"{self.ws} demonstrator",
                                                        "template": d["template"]}, expect=201)
        draft = self.call("GET", f"{self.E}/model/draft")
        self.first = self.call("POST", f"{self.E}/architect/proposals",
                               body={"generator": "model", "brief": d["brief"], "document": draft["document"]})
        answers = [{"id": k, "answer": v} for k, v in d["answers"].items()]
        self.proposal = self.call("POST", f"{self.E}/architect/proposals",
                                  body={"generator": "model", "revises": self.first["id"], "answers": answers,
                                        "document": draft["document"]})
        ids = [i["id"] for i in self.proposal["items"]]
        self.decided = self.call("POST", f"{self.E}/architect/proposals/{self.proposal['id']}/decision",
                                 body={"accepted": ids, "note": "taken as proposed"})
        self.document = architect.apply(draft["document"], self.proposal["items"])
        self.checked = self.call("POST", f"{self.E}/model/validate", body={"document": self.document})
        origin = {"proposal": self.proposal["id"], "revision": self.proposal["revision"]}
        saved = self.call("POST", f"{self.E}/model/draft", body={"document": self.document, "note": "from the proposal",
                                                                 "expected_revision": draft["revision"], "origin": origin})
        self.suggested = self.call("POST", f"{self.E}/solution/suggest", body={"proposal": self.proposal["id"]})
        self.configuration = self.suggested["solution"]
        saved = self.call("POST", f"{self.E}/solution/draft", body={"solution": self.configuration,
                                                                    "expected_revision": saved["revision"]})
        self.revision = saved["revision"]
        return self

    def release(self):
        d = self.d
        # separation of duties: the author does not publish, the proposer does not approve
        self.own_publish = self.call("POST", f"{self.UC}/publish-draft", body={"revision": self.revision,
                                                                               "reason": "mine"}, expect=None)
        self.call("POST", f"{self.UC}/publish-draft", d["approver"], {"revision": self.revision, "reason": "reviewed"})
        self.number = self.call("POST", f"{self.UC}/releases", body={"note": "first release"}, expect=201)["number"]
        self.own_approval = self.call("POST", f"{self.UC}/releases/{self.number}/approve", body={"reason": "mine"},
                                      expect=None)
        self.call("POST", f"{self.UC}/releases/{self.number}/approve", d["approver"], {"reason": "checked"})
        self.call("POST", f"{self.UC}/releases/{self.number}/activate", body={"reason": "go"})
        self.released = self.call("GET", f"{self.UC}/releases/{self.number}")
        self.loaded = self.call("POST", f"{self.UC}/sample-data", body={"reason": "records to rehearse with"})
        self.call("POST", f"{self.UC}/stage", body={"to": "simulation", "reason": "rehearse the solution"})
        self.grant(d["operator"], ["read", "run", "audit"], roles=[d["operator_role"]])
        self.grant(d["reviewer"], ["read", "review"], reviewer_roles=[d["reviewer_role"]])
        return self

    def simulate(self):
        d, operator = self.d, self.token(self.d["operator"])
        for kind in ("alone", "waits", "refused"):
            self.runs[kind] = self.call("POST", f"{self.E}/runs", operator, {"case_template": d["case"],
                                                                             "root": d[kind][0]})
        self.route = list(self.trace)  # the journey as made: later calls of the tests are not part of it
        return self

    def audit(self, run_id):
        return self.call("GET", f"{self.E}/runs/{run_id}/audit", self.token(self.d["operator"]))

    def record(self, ident, token=None):
        return self.call("GET", f"{self.E}/objects/{ident}", token or self.token(self.d["operator"]))


class Hosted(unittest.TestCase):
    """Both applications designed, released and simulated once, on one platform."""

    @classmethod
    def setUpClass(cls):
        cls.pf = hosted()
        cls.c = Client(cls.pf)
        probe = cls("run")  # assertions made while the journeys are prepared
        cls.j = {ws: Journey(probe, cls.c, ws).design().release().simulate() for ws in DOMAINS}

    @classmethod
    def tearDownClass(cls):
        cls.c.server.shutdown()

    def run(self, result=None):  # the probe instance is never run as a test
        return super().run(result) if self._testMethodName != "run" else None

    def service(self, ws):
        return self.pf.workspaces[ws].use_cases[DOMAINS[ws]["use_case"]].service


class SharedJourneyTests(Hosted):
    def test_both_domains_take_the_same_route_through_the_same_engine(self):  # X1
        crisis, netintel = self.j["crisis"].route, self.j["netintel"].route
        self.assertEqual(crisis, netintel)  # the same calls, in the same order, with the same answers
        self.assertGreater(len(crisis), 25)
        engines = {type(self.service(ws)) for ws in DOMAINS}
        self.assertEqual(len(engines), 1)  # one engine class serves both; no subclass per domain
        self.assertEqual({type(p).__name__ for ws in DOMAINS for p in self.service(ws).architect.gateway.providers.values()},
                         {"SandboxArchitect"})

    def test_each_step_of_the_journey_holds_for_each_domain(self):  # X1
        for ws, j in self.j.items():
            d, template = DOMAINS[ws], pack(ws)
            with self.subTest(domain=ws):
                # describe and clarify: the pack's questions, then none once they are answered
                self.assertEqual((j.first["ai"], j.first["generator"]), (False, "sandbox"))
                self.assertEqual([q["id"] for q in j.first["questions"]], list(d["answers"]))
                self.assertEqual((j.proposal["id"], j.proposal["revision"], j.proposal["questions"]),
                                 (j.first["id"], 2, []))
                kinds = {i["kind"] for i in j.proposal["items"]}
                self.assertEqual(kinds, {"action", "case_template", "entity", "goal", "relationship", "rule"})
                self.assertEqual(len(j.proposal["items"]), len(template["items"]))
                # inspect: every element says where it comes from, and none claims the brief as its source
                self.assertTrue(all(i["origin"] == "inference" for i in j.proposal["items"]),
                                {i["origin"] for i in j.proposal["items"]})
                self.assertEqual(j.decided["decisions"][-1]["accepted"], [i["id"] for i in j.proposal["items"]])
                # validate: the model loads; open questions and consistency findings are shown, not hidden
                self.assertEqual(j.checked["validation"]["valid"], True, j.checked["validation"])
                self.assertIn(f"reviewer:{d['reviewer_role']}", [q["id"] for q in j.checked["questions"]])
                self.assertTrue(all(f["a_person_could"][-1] == "leave it: this is intended"
                                    for f in j.checked["consistency"]))
                # the draft remembers the proposal it was made from
                drafts = j.call("GET", f"{j.E}/architect/proposals/{j.proposal['id']}")["drafts"]
                self.assertEqual([(x["draft_revision"], x["proposal_revision"]) for x in drafts], [(1, 2), (2, 2)])
                self.assertEqual(j.call("GET", f"{j.E}/model/draft")["origin"],
                                 {"proposal": j.proposal["id"], "revision": 2})
                # configure: the pack's agent and tools, validated against the model
                self.assertEqual((j.suggested["source"], j.suggested["state"]),
                                 (f"template {d['blueprint']}", "validated"))
                self.assertEqual(list(j.configuration["agents"]), [d["agent"]])
                # release: named parts with fingerprints; active; the engine runs it
                self.assertEqual((j.released["status"], j.released["verification"]["fingerprint_matches"],
                                  j.released["verification"]["coherent"]), ("active", True, True))
                tools = j.released["components"]["tools"]
                self.assertEqual((tools["all_simulated"], tools["other"]), (True, 0))
                self.assertEqual(j.released["components"]["agents"]["names"], [d["agent"]])
                self.assertEqual(j.released["components"]["ai"]["provider"], "sandbox")
                self.assertEqual((j.released["proposed_by"], j.released["approved_by"]),
                                 (f"{d['admin'].split('-')[1]}@{ws}", f"{d['approver'].split('-')[1]}@{ws}"))
                self.assertEqual(len(j.loaded["just_loaded"]), d["records"])
                self.assertEqual(sorted(self.service(ws).agents), [d["agent"]])
                self.assertEqual(self.service(ws).store.count_instances(), d["records"])

    def test_separation_of_duties_holds_in_both_domains(self):  # X1
        for ws, j in self.j.items():
            with self.subTest(domain=ws):
                refusals = [t for t in j.route if t[2] == 403]
                self.assertEqual([r[1] for r in refusals], ["{use-case}/publish-draft", "{use-case}/releases/{id}/approve"])
                self.assertIn("another", json.dumps(j.own_publish).lower())
                self.assertIn("another", json.dumps(j.own_approval).lower())

    def test_each_domain_shows_the_three_governed_outcomes(self):  # X2
        for ws, j in self.j.items():
            d = DOMAINS[ws]
            fingerprint = j.released["fingerprint"]
            with self.subTest(domain=ws, outcome="the agent acts alone"):
                run = j.runs["alone"]
                self.assertEqual((run["status"], run["agent"], run["started_by"], run["simulated"]),
                                 ("completed", d["agent"], d["operator"], True), run)
                self.assertEqual([(s["action"], s["verdict"], s["reviewer"]) for s in run["steps"]],
                                 [(a, "allow", None) for a in d["alone"][1]])
                self.assertEqual(run["configuration"], fingerprint)
                self.assertEqual(j.record(d["alone"][0])["attributes"]["status"], d["alone"][2])
            with self.subTest(domain=ws, outcome="the run waits for the person the policy names"):
                run = j.runs["waits"]
                self.assertEqual((run["status"], run["escalation"]["to"], run["escalation"]["action"]),
                                 ("awaiting_review", d["reviewer_role"], d["waits"][1]), run)
                self.assertNotIn(d["waits"][1], [s["action"] for s in run["steps"] if s["verdict"] == "allow"])
                self.assertTrue(run["pending_review"])
            with self.subTest(domain=ws, outcome="a prohibited action is refused before anything is done"):
                run = j.runs["refused"]
                self.assertEqual((run["status"], run["steps"], run["pending_review"]), ("escalated", [], None), run)
                detail = " ".join(run["escalation"]["details"])
                self.assertIn(f"{d['refused'][1]}: prohibited", detail)
                self.assertIn(d["refused"][2], detail)
                # the record is as it was: nothing was written
                self.assertEqual(j.record(d["refused"][0])["attributes"]["status"],
                                 pack(ws)["items"][[i.get("name") for i in pack(ws)["items"]].index(d["root_entity"])]
                                 ["value"]["states"][0])
            with self.subTest(domain=ws, outcome="every run leaves a verified decision trail"):
                for kind, run in j.runs.items():
                    trail = j.audit(run["run_id"])
                    self.assertEqual(trail["verified"], True, kind)
                    events = [e["event"] for e in trail["entries"]]
                    self.assertEqual(events[0], "run.start")
                    self.assertEqual(events.count("step"), len(run["steps"]))
                    start = trail["entries"][0]["data"]
                    self.assertEqual((start["agent"], start["acting_as"]), (d["agent"], d["operator"]))

    def test_everything_that_ran_was_simulated(self):  # X2, X5
        for ws, j in self.j.items():
            with self.subTest(domain=ws):
                steps = [s for run in j.runs.values() for s in run["steps"]]
                self.assertTrue(steps)
                self.assertEqual({s["environment"] for s in steps}, {"simulated"})
                self.assertTrue(all("simulated" in s["message"] for s in steps), [s["message"] for s in steps])
                catalogue = j.call("GET", f"{j.E}/tools/catalog")["items"]
                self.assertEqual(sorted(t["id"] for t in catalogue if t["available"]),
                                 ["simulated.decision_table", "simulated.fail", "simulated.succeed"])


class ReviewTests(Hosted):
    """I4: who may decide the action a run waits for."""

    def test_only_the_named_reviewer_decides_and_the_decision_is_kept(self):
        for ws, j in self.j.items():
            d, other = DOMAINS[ws], DOMAINS[OTHER[ws]]
            run = j.runs["waits"]
            decision = f"{j.E}/reviews/{run['pending_review']}/decision"
            with self.subTest(domain=ws):
                refused = {
                    "the person who started the run": j.token(d["operator"]),
                    "an administrator without the reviewer role": d["admin"],
                    "the release approver": d["approver"],
                    "a member without any grant": j.token("alex"),
                    "the reviewer of the other domain": f"{OTHER[ws]}-{other['reviewer']}",
                    "nobody": "not-a-token",
                }
                for who, token in refused.items():
                    status, out = self.c.call("POST", decision, token, {"approved": True, "comment": "let it through"})
                    self.assertIn(status, (401, 403, 404), (who, out))
                self.assertEqual(j.call("GET", f"{j.E}/runs/{run['run_id']}", j.token(d["operator"]))["status"],
                                 "awaiting_review")
                # the agent holds no identity of its own: there is no token it could decide with
                self.assertNotIn(d["agent"], [m["name"] for m in j.call("GET", f"{j.WS}/members")["members"]])
                done = j.call("POST", decision, j.token(d["reviewer"]), {"approved": True, "comment": "checked the file"})
                self.assertEqual(done["status"], "completed", done)
                self.assertEqual(j.record(d["waits"][0])["attributes"]["status"], d["waits"][3])
                trail = j.audit(run["run_id"])
                decided = [e for e in trail["entries"] if e["event"] == "review.decision"]
                self.assertEqual((trail["verified"], len(decided)), (True, 1))
                self.assertEqual((decided[0]["data"]["reviewer"], decided[0]["data"]["approved"]), (d["reviewer"], True))
                # decided once: a second decision is refused
                self.assertEqual(self.c.call("POST", decision, j.token(d["reviewer"]), {"approved": False})[0], 409)


class IsolationTests(Hosted):
    def test_a_member_of_one_workspace_reaches_nothing_of_the_other(self):  # I1
        for ws, j in self.j.items():
            theirs, d = self.j[OTHER[ws]], DOMAINS[ws]
            run = theirs.runs["alone"]["run_id"]
            paths = [("GET", f"{theirs.E}/me"), ("GET", f"{theirs.E}/ontology"), ("GET", f"{theirs.E}/objects"),
                     ("GET", f"{theirs.E}/objects/ORG-1"), ("GET", f"{theirs.E}/runs"), ("GET", f"{theirs.E}/runs/{run}"),
                     ("GET", f"{theirs.E}/runs/{run}/audit"), ("GET", f"{theirs.E}/reviews"),
                     ("GET", f"{theirs.E}/architect/proposals"), ("GET", f"{theirs.E}/model/draft"),
                     ("GET", f"{theirs.E}/solution/draft"), ("POST", f"{theirs.E}/runs"),
                     ("POST", f"{theirs.E}/objects"), ("GET", theirs.UC), ("GET", f"{theirs.UC}/releases"),
                     ("GET", f"{theirs.UC}/readiness?target=pilot"), ("GET", f"{theirs.WS}/members"),
                     ("POST", f"{theirs.UC}/sample-data"), ("POST", f"{theirs.UC}/stage"), ("POST", f"{theirs.WS}/grants")]
            for name in ("admin", "approver", "operator", "reviewer"):
                token = d[name] if name in ("admin", "approver") else j.token(d[name])
                for method, path in paths:
                    with self.subTest(member=f"{ws}:{name}", path=path):
                        status, out = self.c.call(method, path, token, {} if method == "POST" else None)
                        self.assertIn(status, (401, 403, 404), out)
                        self.assertNotIn(DOMAINS[OTHER[ws]]["root_entity"], json.dumps(out))
            mine = self.c.call("GET", "/platform/v1/me", d["admin"])[1]
            self.assertEqual([w["id"] for w in mine["workspaces"]], [ws])

    def test_a_permission_is_held_in_one_workspace_only(self):  # I2
        crisis, netintel = self.j["crisis"], self.j["netintel"]
        # alex is a member of both workspaces (two memberships, two tokens) and is granted "read" in crisis only
        crisis.grant("alex", ["read"])
        self.assertEqual(self.c.call("GET", f"{crisis.E}/objects/ORG-1", "crisis-alex")[0], 200)
        for path in (f"{netintel.E}/objects/ORG-1", f"{netintel.E}/objects", f"{netintel.E}/runs"):
            self.assertEqual(self.c.call("GET", path, "netintel-alex")[0], 404, path)   # a member, with no grant
            self.assertIn(self.c.call("GET", path, "crisis-alex")[0], (401, 403, 404), path)  # not a member at all
        # a grant names a use case of its own workspace: the other workspace's use case is not one of them
        status, out = self.c.call("POST", f"{crisis.WS}/grants", DOMAINS["crisis"]["admin"],
                                  {"member": "alex", "use_case": DOMAINS["netintel"]["use_case"], "permissions": ["read"],
                                   "reason": "reach the other application"})
        self.assertEqual(status, 400, out)
        self.assertIn("of this workspace", json.dumps(out))
        # without a grant the use case does not exist for this member: not even its name is confirmed
        self.assertEqual(self.c.call("GET", f"{netintel.E}/me", "netintel-alex")[0], 404)
        mine = self.c.call("GET", "/platform/v1/me", "netintel-alex")[1]
        self.assertEqual([(w["id"], [u["id"] for u in w.get("use_cases", [])]) for w in mine["workspaces"]],
                         [("netintel", [])])

    def test_a_release_belongs_to_its_use_case(self):  # I3
        for ws, j in self.j.items():
            theirs, d = self.j[OTHER[ws]], DOMAINS[ws]
            with self.subTest(domain=ws):
                again = theirs.call("POST", f"{theirs.UC}/releases", body={"note": "second"}, expect=None)
                for verb in ("approve", "activate", "rollback"):
                    for token in (d["admin"], d["approver"]):
                        status, out = self.c.call("POST", f"{theirs.UC}/releases/{theirs.number}/{verb}", token,
                                                  {"reason": "from the other workspace"})
                        self.assertIn(status, (401, 403, 404), (verb, out))
                # a release cannot be named across use cases: this workspace has no such use case
                status, out = self.c.call("POST", f"{j.WS}/use-cases/{DOMAINS[OTHER[ws]]['use_case']}/releases/1/activate",
                                          d["admin"], {"reason": "theirs, here"})
                self.assertEqual(status, 404, out)
                del again
        crisis, netintel = (self.j[ws].released for ws in ("crisis", "netintel"))
        self.assertNotEqual(crisis["fingerprint"], netintel["fingerprint"])
        for part in ("model", "rules", "actions", "workflows", "agents", "tools"):  # no part is shared
            self.assertNotEqual(crisis["components"][part]["fingerprint"], netintel["components"][part]["fingerprint"], part)
        for ws, j in self.j.items():  # each engine runs its own release, and each run says which
            self.assertEqual(self.service(ws).ontology.name, json.loads(
                (PACKS / DOMAINS[ws]["pack"] / "ontology.json").read_text())["name"])
            self.assertEqual({r["configuration"] for r in j.runs.values()}, {j.released["fingerprint"]})

    def test_the_same_names_are_unrelated_records(self):  # I5
        crisis, netintel = self.j["crisis"], self.j["netintel"]
        a, b = crisis.record("ORG-1"), netintel.record("ORG-1")
        self.assertEqual((a["type"], b["type"]), ("Organization", "Organization"))
        self.assertIn("Civil Protection", a["attributes"]["name"])
        self.assertIn("Brightwater", b["attributes"]["name"])
        self.assertEqual(set(a["attributes"]) & {"registration_id", "jurisdiction"}, set())  # two models, one name
        self.assertIn("registration_id", b["attributes"])
        links = {ws: {(x["kind"], x["direction"], x["id"], x["type"]) for x in record["links"]}
                 for ws, record in (("crisis", a), ("netintel", b))}
        self.assertFalse(links["crisis"] & links["netintel"])
        self.assertEqual({x[3] for x in links["crisis"]}, {"ResponseTeam", "Resource"})
        self.assertLessEqual({x[3] for x in links["netintel"]}, {"CaseFile", "Contract", "Person", "BankAccount", "Association"})
        # a change in one engine is not a change in the other
        crisis.grant(DOMAINS["crisis"]["operator"], ["read", "run", "audit", "admin"], roles=["operations_officer"],
                     unrestricted=True)
        changed = crisis.call("POST", f"{crisis.E}/objects", crisis.token("omar"),
                              {"type": "Organization", "id": "ORG-1", "attributes": {"kind": "renamed in crisis only"},
                               "expected_revision": a.get("revision")}, expect=None)
        self.assertEqual(crisis.record("ORG-1")["attributes"]["kind"], "renamed in crisis only", changed)
        self.assertEqual(netintel.record("ORG-1")["attributes"], b["attributes"])
        self.assertEqual(self.service("netintel").store.count_instances(), DOMAINS["netintel"]["records"])
        self.assertNotEqual(self.service("crisis").store.path, self.service("netintel").store.path)

    def test_a_configuration_stays_within_simulated_tools_and_its_own_model(self):  # I6
        for ws, j in self.j.items():
            d, foreign = DOMAINS[ws], DOMAINS[OTHER[ws]]
            agent = j.configuration["agents"][d["agent"]]
            first = agent["tools"][0]

            def problems(tools):
                out = j.call("POST", f"{j.E}/solution/validate",
                             body={"solution": {"agents": {d["agent"]: {**agent, "tools": tools}}}})
                self.assertFalse(any(row["simulated"] for rows in out["permissions"].values() for row in rows
                                     if row["tool"] and not str(row["tool"]).startswith("simulated.")))
                return out["state"], json.dumps(out["validation"]["problems"])

            with self.subTest(domain=ws):
                for tool in ("http.request", "connector.erp", "python.code", "model.reasoner", "simulated.unknown"):
                    state, why = problems([{**first, "tool": tool}])
                    self.assertEqual(state, "invalid", tool)
                    self.assertIn(tool, why)
                state, why = problems([{"action": foreign["waits"][1], "tool": "simulated.succeed"}])
                self.assertEqual(state, "invalid")
                self.assertIn(foreign["waits"][1], why)
                # an invalid configuration is never stored, so it can never be released
                revision = j.call("GET", f"{j.E}/solution/draft")["revision"]
                status, out = self.c.call("POST", f"{j.E}/solution/draft", d["admin"],
                                          {"solution": {"agents": {d["agent"]: {**agent, "tools": [{**first, "tool": "http.request"}]}}},
                                           "expected_revision": revision})
                self.assertEqual(status, 400, out)
                self.assertEqual(j.call("GET", f"{j.E}/solution/draft")["revision"], revision)
                # the compiled tools of the running agent: decision tables inside the engine, nothing else
                tools = self.service(ws).agents[d["agent"]].agent.tools
                self.assertEqual({t.environment for t in tools}, {"simulated"})
                declared = {a["value"]["capability"] for a in pack(ws)["items"] if a["kind"] == "action"}
                self.assertLessEqual({t.capability for t in tools}, declared)

    def test_templates_and_blueprints_are_scoped(self):  # I7
        for ws, j in self.j.items():
            d, foreign = DOMAINS[ws], DOMAINS[OTHER[ws]]
            with self.subTest(domain=ws):
                self.assertEqual([t["id"] for t in j.templates], [d["template"]])
                status, out = self.c.call("POST", f"{j.WS}/use-cases", d["admin"],
                                          {"id": "borrowed", "name": "borrowed", "template": foreign["template"]})
                self.assertEqual(status, 400, out)
                self.assertIn("unknown template", json.dumps(out))
                self.assertNotIn("borrowed", self.pf.workspaces[ws].use_cases)
                # the other domain's description, asked here: this use case has no such template, so it asks
                asked = j.call("POST", f"{j.E}/architect/proposals", body={"generator": "model", "brief": foreign["brief"],
                                                                           "document": {"name": "x", "version": "0.1.0"}})
                self.assertEqual((asked["items"], [q["id"] for q in asked["questions"]]), ([], ["process"]))
                self.assertEqual([p.name for p in self.service(ws).architect.folders], ["blueprints"])
                self.assertEqual(self.service(ws).architect.folders[0].parent.name, d["pack"])

    def test_a_row_rule_hides_its_rows_and_nothing_else(self):  # I8
        j, d = self.j["netintel"], DOMAINS["netintel"]
        entity, ident, role = d["restricted"]
        analyst, reviewer = j.token(d["operator"]), j.token(d["reviewer"])
        # the unauthorised read: the analyst does not hold the role the rule names
        self.assertEqual(self.c.call("GET", f"{j.E}/objects/{ident}", analyst)[0], 404)
        listed = j.call("GET", f"{j.E}/objects?type={entity}", analyst)
        self.assertEqual(listed["items"], [])
        self.assertNotIn("FICT-ACC", json.dumps(j.call("GET", f"{j.E}/objects", analyst)))
        # the runs of the journey hold no such record: the analyst and the reviewer see them
        for kind, run in j.runs.items():
            self.assertNotIn("hidden", run, kind)
            self.assertEqual(self.c.call("GET", f"{j.E}/runs/{run['run_id']}", analyst)[0], 200)
        # with the role, the same person reads the rows; the rule itself is unchanged
        j.grant(d["reviewer"], ["read", "review"], reviewer_roles=[d["reviewer_role"]], roles=[role])
        self.assertEqual(j.call("GET", f"{j.E}/objects/{ident}", reviewer)["attributes"]["identifier"], "FICT-ACC-0001")
        # a run whose state holds a record of the restricted type is still hidden from those without the role
        service = self.service("netintel")
        stored = service.store.load_run(j.runs["alone"]["run_id"])
        users = {u.name: u for u in service.users}
        self.assertFalse(service.views.hides_rows(users[d["operator"]], stored.state))
        stored.state.entities[entity]["status"] = "active"
        self.assertTrue(service.views.hides_rows(users[d["operator"]], stored.state))
        self.assertFalse(service.views.hides_rows(users[d["reviewer"]], stored.state))


class KernelNeutralityTests(unittest.TestCase):
    """X3, X4: the engine and Studio carry neither domain."""

    WORDS = ("flood", "shelter", "hazard", "evacuat", "municipal", "disaster", "emergenc", "fraud", "criminal",
             "beneficial", "laundering", "guilt", "intermediar", "ownership declaration")
    # generic English in engine comments, read and kept: (file, text)
    KNOWN = {("limits.py", "under a flood of new keys")}

    def names(self):
        out = set()
        for ws in DOMAINS:
            template = pack(ws)
            out |= {template["id"], DOMAINS[ws]["template"], DOMAINS[ws]["pack"]}
            for item in template["items"]:
                name = item.get("name") or item["value"].get("id")
                if name and (item["kind"] != "entity" or re.search(r"[a-z][A-Z]", name)):  # CaseFile, not Person
                    out.add(name)
            out |= set(template["solution"]["agents"]) | {a["name"] for a in template["agents"]}
            out |= {p["default"] for p in template["parameters"] if p["type"] == "name"}
        return out

    def sources(self):
        engine = [p for p in (ROOT / "autology").rglob("*.py")]
        studio = [p for folder in ("components", "lib", "app") for p in (ROOT / "studio" / "web" / folder).rglob("*.ts*")
                  if ".test." not in p.name and "generated" not in p.parts]
        self.assertGreater(len(engine), 60)
        self.assertGreater(len(studio), 20)
        return engine + studio

    def test_no_domain_name_or_word_appears_in_the_engine_or_studio(self):
        names = self.names()
        self.assertGreater(len(names), 50)
        exact = re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b")
        words = re.compile("|".join(self.WORDS), re.I)
        hits = []
        for path in self.sources():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if exact.search(line) or words.search(line):
                    if not any(path.name == f and text in line for f, text in self.KNOWN):
                        hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
        self.assertEqual(hits, [])

    def test_the_packs_are_configuration_outside_the_engine_package(self):
        shipped = {b["id"] for b in blueprints()}
        for ws in DOMAINS:
            self.assertNotIn(DOMAINS[ws]["blueprint"], shipped)
            self.assertFalse(list((ROOT / "autology").rglob(f"*{DOMAINS[ws]['blueprint']}*")))
            folder = PACKS / DOMAINS[ws]["pack"]
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["blueprints", "ontology.json", "server.json"])
            server = json.loads((folder / "server.json").read_text())
            self.assertEqual((server["blueprints"], server["ai"]), ("blueprints", {"provider": "sandbox"}))
            self.assertEqual(set(json.loads((folder / "ontology.json").read_text())), {"name", "version"})  # blank
            self.assertIn(DOMAINS[ws]["blueprint"], {b["id"] for b in blueprints([folder / "blueprints"])})

    def test_without_its_pack_the_sandbox_proposes_nothing_for_a_domain(self):
        for ws, d in DOMAINS.items():
            with self.subTest(domain=ws):
                self.assertIsNone(match(d["brief"])[0])  # Autology's own templates: none fits
                alone = answer({"brief": d["brief"], "answers": []})
                self.assertEqual(sum(len(alone[k]) for k in ("entities", "actions", "rules", "goals")), 0)
                self.assertEqual([q["id"] for q in alone["questions"]], ["process"])
                with_pack = answer({"brief": d["brief"], "answers": []}, [PACKS / d["pack"] / "blueprints"])
                self.assertGreater(len(with_pack["entities"]), 9)
                said = with_pack["understanding"]["summary"]
                self.assertIn("not a language model", said)
                self.assertIn("template", said)
                self.assertEqual({e["basis"] for e in with_pack["entities"]}, {"inferred"})


class ConfiguredLibraryTests(unittest.TestCase):
    """The general abstraction the two packs rest on: a use case's configuration names its blueprint folders."""

    def test_a_library_is_named_by_configuration_and_must_exist(self):
        self.assertEqual(library(None, PACKS), ())
        one = library("crisis_management/blueprints", PACKS)
        self.assertEqual([p.name for p in one], ["blueprints"])
        both = library(["crisis_management/blueprints", "network_intelligence/blueprints"], PACKS)
        self.assertEqual(len(both), 2)
        with self.assertRaises(ValueError) as refused:
            library("no_such_folder", PACKS)
        self.assertIn("no_such_folder", str(refused.exception))

    def test_autologys_own_templates_stay_available_and_come_first(self):
        own = [b["id"] for b in blueprints()]
        with_pack = [b["id"] for b in blueprints(library("crisis_management/blueprints", PACKS))]
        self.assertEqual(with_pack[:len(own)], own)
        self.assertEqual(with_pack[len(own):], ["flood_response"])


class PackContentTests(unittest.TestCase):
    """X5: what the packs hold, read as data."""

    def test_every_tool_is_simulated_and_nothing_names_a_system_to_contact(self):
        for ws in DOMAINS:
            template = pack(ws)
            text = json.dumps(template)
            self.assertFalse(re.search(r"https?://|\bwww\.|@[a-z0-9-]+\.[a-z]{2,}", text), ws)
            for agent in template["solution"]["agents"].values():
                self.assertEqual(agent["autonomy"], {"mode": "policy"})
                self.assertTrue(all(t["tool"].startswith("simulated.") for t in agent["tools"]))
                self.assertTrue(all("simulated" in (t.get("message") or t.get("error")) for t in agent["tools"]))
            # five proposed responsibilities are descriptions; one executable agent holds the actions (D32)
            self.assertEqual((len(template["agents"]), len(template["solution"]["agents"])), (5, 1))
            self.assertTrue(all(a["description"].startswith("Proposed responsibility") for a in template["agents"]))

    def test_every_named_party_is_marked_fictional(self):
        for ws in DOMAINS:
            for row in pack(ws)["solution"]["sample_data"]["instances"]:
                if row["type"] in ("Organization", "Person", "AffectedArea", "HazardEvent", "Infrastructure", "Shelter",
                                   "ResponseTeam"):
                    self.assertIn("fictional", row["name"], row["id"])
                for key in ("identifier", "registration_id", "reference"):
                    if row.get(key) and row["type"] not in ("IncidentReport", "CaseFile"):
                        self.assertTrue(row[key].startswith("FICT-"), row)

    def test_the_crisis_data_keeps_facts_predictions_and_recommendations_apart(self):
        template = pack("crisis")
        rows = template["solution"]["sample_data"]["instances"]
        bases = {r["information_basis"] for r in rows if r["type"] == "IncidentReport"}
        self.assertEqual(bases, {"observed", "predicted"})
        self.assertEqual({r["basis"] for r in rows if r["type"] == "Assignment"}, {"recommendation"})
        rules = {i["value"]["id"]: i["value"] for i in template["items"] if i["kind"] == "rule"}
        self.assertEqual(rules["R-NO-PREDICTION"]["when"], "IncidentReport.information_basis == 'predicted'")
        self.assertEqual(rules["R-ASSIGN-APPROVAL"]["type"], "human_review")
        self.assertIn("Validated hazard models (none is used: nothing is forecast)", template["unknowns"])

    def test_every_link_says_how_it_is_known_and_every_hypothesis_has_its_alternative(self):
        template = pack("netintel")
        rows = template["solution"]["sample_data"]["instances"]
        links = [r for r in rows if r["type"] == "Association"]
        kinds = {"observed_fact", "confirmed_assertion", "inference", "unresolved_hypothesis"}
        self.assertEqual({r["status"] for r in links}, kinds)  # each class appears, and no other
        entity = next(i for i in template["items"] if i.get("name") == "Association")
        self.assertEqual(set(entity["value"]["states"]), kinds)
        for r in links:
            self.assertTrue(r["evidence_quality"])
            if r["status"] in ("observed_fact", "confirmed_assertion"):
                self.assertTrue(r["source_reference"], r["id"])  # a fact names the document it rests on
        hypotheses = [r for r in rows if r["type"] == "Hypothesis"]
        self.assertTrue(hypotheses)
        self.assertTrue(all(len(r["alternative_explanation"]) > 20 for r in hypotheses))
        self.assertTrue(any(r["valid_from"] and r["valid_to"] for r in links))  # a link bounded in time
        # the model has no word for guilt and no action that decides anything about a person
        names = " ".join(str(i.get("name")) + " " + " ".join(i["value"].get("states", [])) for i in template["items"])
        self.assertFalse(re.search(r"guilt|accus|sanction|convict|penal|arrest|enforce", names, re.I), names)
        rules = {i["value"]["id"]: i["value"] for i in template["items"] if i["kind"] == "rule"}
        self.assertEqual((rules["R-ESCALATION-REVIEW"]["type"], rules["R-ESCALATION-REVIEW"].get("when")),
                         ("human_review", None))  # every escalation, without condition
        self.assertEqual(rules["R-ALTERNATIVE-FIRST"]["step"], "record_alternative_explanation")


if __name__ == "__main__":
    unittest.main()
