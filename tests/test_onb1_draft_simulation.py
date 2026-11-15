"""Onboarding, engine side: a dry run of a model document before it is published (``POST /api/v1/model/draft/simulate``).

The model simulated here is what the sandbox architect proposes from the industry-neutral template (synthetic).

  O1 the engine's planner and governance run one synthetic case of the document with stub tools; the run parks at
     a human review and says who must decide and why
  O2 it continues only with an explicit simulated decision given as one of the rule's reviewer roles; the trace
     says the decision was simulated; mandatory steps are honoured
  O3 where policy asks for no review the simulated agent completes on its own; without the role an action needs,
     it is refused
  O4 nothing is stored, no record is read or written, no configured tool is called, no connection is opened, and
     readiness does not count a simulation as a run
  O5 only ``configure`` may simulate; a document that does not validate, an unknown goal, or a malformed case or
     decision is refused
  O6 the default sample case is built to exercise the review thresholds of the model
"""

import json
import socket
import unittest
from unittest import mock

from autology import architect, readiness
from autology.ai import ModelGateway, WorkspaceAI
from autology.ontology import Ontology
from autology.sandbox_ai import SandboxArchitect
from autology.server import ApiError, ApiExchange
from autology.simulation import SimulationError, sample_case, simulate

from . import test_ingest

BRIEF = "Employees send service requests; a manager must approve expensive ones, then a team fulfils them."


def proposed_model(answers=()):
    """The document a person would get by accepting everything the sandbox architect proposes for BRIEF."""
    gateway = ModelGateway({"sandbox": SandboxArchitect()},
                           {"w": WorkspaceAI("sandbox", "sandbox", ("synthetic", "model_design"))},
                           sink=lambda event: None)
    out = architect.propose(gateway, "w", BRIEF, answers=answers)
    return architect.apply({"name": "service-desk", "version": "0.1.0"}, out["items"])


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.doc = proposed_model()

    def test_the_run_parks_at_a_review_and_says_who_decides(self):  # O1
        out = simulate(self.doc)
        self.assertEqual((out["status"], out["simulated"], out["persisted"]), ("awaiting_review", True, False))
        self.assertEqual([(s["action"], s["tool"], s["outcome"]) for s in out["steps"]],
                         [("review_request", "simulated:requests.review", "done")])
        self.assertEqual(out["pending_review"], {
            "action": "approve_request", "reviewers": ["manager"], "rules": ["R-APPROVAL"],
            "reasons": ["A manager approves requests of 1000 or more"],
            "facts": {"Request.amount": 1000, "Request.status": "under_review"}})
        self.assertEqual((out["goal"], out["agent"]["roles"]), ("request_closed", ["manager", "service_agent"]))
        self.assertIn("not evidence of a real run", out["notice"])
        self.assertIn("review.requested", [e["event"] for e in out["audit"]["events"]])
        self.assertIn("not a stored signed audit chain", out["audit"]["note"])
        self.assertEqual(out["model"]["fingerprint"], Ontology.from_dict(self.doc).fingerprint)

    def test_a_simulated_decision_continues_the_run(self):  # O2
        out = simulate(self.doc, approvals=[{"action": "approve_request", "approved": True, "as": "manager"}])
        self.assertEqual((out["status"], out["pending_review"]), ("completed", None))
        actions = [s["action"] for s in out["steps"]]
        self.assertEqual(actions, ["review_request", "approve_request", "fulfil_request", "notify_requester",
                                   "close_request"])
        self.assertLess(actions.index("notify_requester"), actions.index("close_request"))  # the mandatory step
        self.assertEqual(out["reviews"], [{"action": "approve_request", "approved": True, "as": "manager",
                                           "note": "simulated decision: no person reviewed anything"}])
        approve = next(s for s in out["steps"] if s["action"] == "approve_request")
        self.assertEqual(approve["reviewer"], "simulated:manager")
        self.assertEqual(out["final_state"]["Request"]["status"], "closed")
        # a reviewer who says no: the request is not fulfilled
        out = simulate(self.doc, approvals=[{"action": "approve_request", "approved": False}])
        self.assertNotEqual(out["status"], "completed")
        self.assertNotIn("fulfil_request", [s["action"] for s in out["steps"] if s["outcome"]])
        # the decision must come from a role the rule names, and be a decision
        for bad in ({"action": "approve_request", "approved": True, "as": "service_agent"},
                    {"action": "approve_request", "approved": "yes"}):
            with self.assertRaises(SimulationError):
                simulate(self.doc, approvals=[bad])
        # a decision for another action is not used: the run still waits
        waiting = simulate(self.doc, approvals=[{"action": "close_request", "approved": True}])
        self.assertEqual(waiting["status"], "awaiting_review")

    def test_autonomy_where_policy_allows_and_refusal_without_the_role(self):  # O3
        case = sample_case(Ontology.from_dict(self.doc), self.doc)
        case["Request"]["amount"] = 10  # below the threshold: no review rule applies
        out = simulate(self.doc, case=case)
        self.assertEqual((out["status"], out["reviews"], out["pending_review"]), ("completed", [], None))
        self.assertNotIn("review.requested", [e["event"] for e in out["audit"]["events"]])
        # an agent without the handling role may not fulfil: the engine refuses, the run does not complete
        out = simulate(self.doc, case=case, roles=[])
        self.assertNotEqual(out["status"], "completed")
        self.assertEqual((out["status"], out["steps"]), ("escalated", []))  # no compliant plan: nothing is started
        self.assertIn("no compliant path", out["escalation"]["reason"])
        self.assertIn("Only a service_agent fulfils requests", " ".join(out["escalation"]["details"]))
        # answers change the policy, and the simulation follows it
        strict = proposed_model([{"id": "approval_threshold", "answer": "5"}, {"id": "approver_role", "answer": "director"}])
        out = simulate(strict, case=case)
        self.assertEqual((out["status"], out["pending_review"]["reviewers"]), ("awaiting_review", ["director"]))

    def test_the_default_case_exercises_the_review_thresholds(self):  # O6
        doc = {"name": "t", "version": "1.0.0",
               "entities": {"Task": {"description": "x", "states": ["open", "done"],
                                     "attributes": {"size": "number", "urgent": "boolean", "label": "string"}}},
               "actions": {"finish": {"description": "x", "capability": "tasks.finish", "side_effect": "none",
                                      "requires": ["Task.status == 'open'"], "effects": {"Task": {"status": "done"}}}},
               "rules": [{"id": "R-BIG", "type": "human_review", "action": "finish", "reviewer": "lead",
                          "when": "Task.size > 7.5", "description": "A lead decides big tasks"}],
               "goals": {"done": {"description": "x", "target": "Task.status == 'done'"}}}
        case = sample_case(Ontology.from_dict(doc), doc)
        self.assertEqual(case, {"Task": {"status": "open", "size": 8.5, "urgent": False, "label": "sample"}})
        self.assertEqual(simulate(doc)["status"], "awaiting_review")
        self.assertEqual(simulate(doc, approvals=[{"action": "finish", "approved": True}])["status"], "completed")

    def test_what_cannot_be_simulated_is_refused(self):  # O5
        for document, kw in ((None, {}), ({"name": "x"}, {}), ({"name": "x", "version": "1.0.0"}, {}),
                             (self.doc, {"goal": "world_peace"}), (self.doc, {"case": "a request"}),
                             (self.doc, {"case": {"Request": "open"}}),
                             ({**self.doc, "rules": [{"id": "R", "type": "magic"}]}, {})):
            with self.assertRaises(SimulationError):
                simulate(document, **kw)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.svc = test_ingest.service(automations={})
        self.addCleanup(self.svc.close)
        self.u = {x.name: x for x in self.svc.users}
        self.clara = self.svc.parse_users([{"name": "clara", "token_env": "AUTOLOGY_TOKEN_HANA",
                                            "permissions": ["configure"]}])[0]
        self.doc = proposed_model()

    def state(self):
        s = self.svc
        return (len(s.store.list_runs(limit=10 ** 6)), s.store.draft(), s.ontology.fingerprint, s.configuration_fingerprint,
                {i: dict(v.attributes) for i, v in s.graph._instances.items()}, dict(s.revisions),
                len(s.store.list_calls()), len(s.store.list_reviews(None)))

    def test_nothing_is_stored_called_or_counted(self):  # O4
        before = self.state()
        calls = []
        for cfg in self.svc.agents.values():  # the use case's real tools must not be touched
            for tool in cfg.agent.tools:
                tool.handler = lambda call, name=tool.name: calls.append(name)
        with mock.patch.object(socket.socket, "connect", side_effect=AssertionError("no connection is expected")):
            out = self.svc.architect.simulate_draft(self.clara, {
                "document": self.doc, "approvals": [{"action": "approve_request", "approved": True}]})
            active = self.svc.architect.simulate_draft(self.clara, {})  # no draft: the active (insurance) model
        self.assertEqual((out["status"], out["requested_by"], calls), ("completed", "clara", []))
        self.assertEqual(active["model"]["fingerprint"], self.svc.ontology.fingerprint)
        self.assertTrue(all(str(s["tool"]).startswith("simulated:") for s in active["steps"] if s["tool"]))
        self.assertEqual(self.state(), before)
        blockers = {b["id"] for b in readiness.report(self.svc, "pilot")["gates"]["blockers"]}
        self.assertIn("simulated_run_completed", blockers)  # a dry run is not a run

    def test_only_configure_simulates_and_bad_requests_are_refused(self):  # O5
        for user in ("hana", "ivan", "etl"):
            with self.assertRaises(ApiError) as refused:
                self.svc.architect.simulate_draft(self.u[user], {"document": self.doc})
            self.assertEqual(refused.exception.status, 403, user)
        for body in ({"document": {"name": "x"}}, {"document": self.doc, "approvals": "yes"},
                     {"document": self.doc, "roles": "manager"}, {"document": self.doc, "goal": "nope"},
                     {"document": self.doc, "approvals": [{"action": "approve_request", "approved": True, "as": "x"}]}):
            with self.assertRaises(ApiError) as bad:
                self.svc.architect.simulate_draft(self.clara, body)
            self.assertEqual(bad.exception.status, 400, body)
        ex = ApiExchange(self.svc, "POST", "/api/v1/model/draft/simulate", {"Authorization": "Bearer tok-admin-ai"},
                         json.dumps({"document": self.doc}).encode()).run()
        body = json.loads(ex.data)
        self.assertEqual((ex.status, body["status"], body["persisted"]), (200, "awaiting_review", False))
        self.assertEqual(ApiExchange(self.svc, "POST", "/api/v1/model/draft/simulate",
                                     {"Authorization": "Bearer tok-hana"}, b"{}").run().status, 403)
        self.assertEqual(ApiExchange(self.svc, "GET", "/api/v1/model/draft/simulate",
                                     {"Authorization": "Bearer tok-admin-ai"}, b"").run().status in (404, 405), True)


if __name__ == "__main__":
    unittest.main()
