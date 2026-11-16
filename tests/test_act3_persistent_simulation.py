"""Activation sprint, increment C: a persistent, governed simulation of a solution designed through the API.

The whole chain uses what exists: the sandbox architect proposes, people accept and publish, a release is
approved and activated, the use case is moved to Simulation, members are granted what they need by two people,
and the engine's own run lifecycle stores each run. Nothing here is a second simulation engine.

  P1 the chain ends in a stored run with a durable identifier, on the active release (its configuration is the
     release's fingerprint), with stored state and a signed audit chain
  P2 where the policy authorises it the agent acts on its own: no unnecessary review
  P3 where the policy asks for a person the run waits; the requester and machines cannot decide; an authorised
     reviewer's approval continues the run; the decision is in the audit chain; the record is written back
  P4 a prohibited action is refused by policy before anything is done, and the refusal names the rule
  P5 a reviewer's refusal stops the action
  P6 a waiting run can be cancelled with a reason by someone who may run and see it; the cancellation is in the
     chain, the review is closed, the record is free for a new run; everything else is refused
  P7 a failing tool is deterministic: the same failure, the same retries, the same end; nothing is repeated
  P8 runs survive a restart: stored runs are still there and a waiting one continues after its review
  P9 replay protection: one open run per record; a review is decided once
  P10 authorisation: no ``run`` no run; no audit permission no audit chain; Draft refuses runs; Production is refused
  P11 every effect is simulated and the run says so; another workspace sees nothing
"""

import json

from autology import architect

from .test_act2_release_configuration import ENGINE, UC, WS, ReleaseBase

BRIEF = ("A critical supplier has delayed a delivery. Evaluate the operational impact, compare available "
         "alternatives and select an authorized response.")
CASE = {"case_template": "delivery_case"}


class SimulationBase(ReleaseBase):
    """A use case designed from the reference description, released, in Simulation, with a planner (hana) and a
    reviewer (zoe)."""

    def setUp(self):
        super().setUp()
        _, draft = self.call("GET", f"{ENGINE}/model/draft")
        status, proposal = self.call("POST", f"{ENGINE}/architect/proposals",
                                     body={"generator": "model", "brief": BRIEF, "document": draft["document"]})
        self.assertEqual(status, 200, proposal)
        self.proposal = proposal
        document = architect.apply(draft["document"], proposal["items"])
        self.draft(document)
        status, suggested = self.call("POST", f"{ENGINE}/solution/suggest", body={"proposal": proposal["id"]})
        self.assertEqual((status, suggested["source"], suggested["state"]), (200, "template supplier-disruption", "validated"))
        self.configuration = suggested["solution"]
        self.release = self.released(None, self.configuration)
        self.fingerprint = self.call("GET", f"{UC}/releases/{self.release}")[1]["fingerprint"]
        self.zoe = self.add("zoe")
        self.bot = self.add("pipeline", kind="service")
        self.grant("hana", ["read", "run", "audit"], roles=["supply_planner"])
        self.grant("zoe", ["read", "review"], reviewer_roles=["operations_manager"])

    def grant(self, member, permissions, **extra):
        status, g = self.call("POST", f"{WS}/grants", body={"member": member, "use_case": "desk", "permissions": permissions,
                                                            "reason": "the simulation needs it", **extra})
        self.assertEqual(status, 201, g)
        status, out = self.call("POST", f"{WS}/grants/{g['id']}/approve", "acme-maria", {"reason": "checked"})
        self.assertEqual(status, 200, out)

    def simulate(self):
        status, out = self.call("POST", f"{UC}/stage", body={"to": "simulation", "reason": "rehearse the solution"})
        self.assertEqual(status, 200, out)
        return out

    def begin(self, root, token="acme-hana"):
        return self.call("POST", f"{ENGINE}/runs", token, {**CASE, "root": root})

    def run_of(self, run_id, token="acme-hana"):
        return self.call("GET", f"{ENGINE}/runs/{run_id}", token)[1]

    def events(self, run_id):
        status, audit = self.call("GET", f"{ENGINE}/runs/{run_id}/audit", "acme-hana")
        self.assertEqual((status, audit["verified"]), (200, True), audit)
        return audit["entries"]

    def record(self, root):
        return self.call("GET", f"{ENGINE}/objects/{root}", "acme-hana")[1]["attributes"]


class ChainTests(SimulationBase):
    def test_the_design_is_proposed_accepted_configured_released_and_run(self):  # P1, P2, P10, P11
        kinds = sorted({i["kind"] for i in self.proposal["items"]})
        self.assertEqual(kinds, ["action", "case_template", "entity", "goal", "relationship", "rule"])
        self.assertEqual((self.proposal["ai"], self.proposal["generator"]), (False, "sandbox"))
        self.assertEqual(sorted(self.desk.agents), ["disruption_agent"])
        self.assertEqual(self.desk.store.count_instances(), 12)  # the synthetic sample records
        # released and active, but in Draft: the engine refuses to run
        status, out = self.begin("DEL-1001")
        self.assertEqual(status, 409, out)
        self.assertIn("draft", out["error"]["message"].lower())
        moved = self.simulate()
        self.assertEqual(moved["use_case"]["effective_stage"], "simulation")
        status, run = self.begin("DEL-1001")
        self.assertEqual((status, run["status"]), (200, "completed"), run)
        # the policy authorises this response: the agent acted on its own, three steps, no reviewer
        self.assertEqual([(s["action"], s["verdict"], s["reviewer"]) for s in run["steps"]],
                         [("assess_impact", "allow", None), ("compare_alternatives", "allow", None),
                          ("accept_delay", "allow", None)])
        self.assertEqual((run["configuration"], run["agent"], run["started_by"], run["simulated"]),
                         (self.fingerprint, "disruption_agent", "hana", True))
        self.assertTrue(all(s["environment"] == "simulated" for s in run["steps"]))
        self.assertEqual(self.call("GET", f"{ENGINE}/reviews", self.zoe)[1]["items"], [])
        # durable: listed, readable again by its identifier, state stored and written back to the record
        listed = self.call("GET", f"{ENGINE}/runs", "acme-hana")[1]["items"]
        self.assertEqual([(r["run_id"], r["status"], r["started_by"]) for r in listed], [(run["run_id"], "completed", "hana")])
        again = self.run_of(run["run_id"])
        self.assertEqual((again["state"]["Delivery"]["status"], again["state"]["Delivery"]["response"], again["audit_verified"]),
                         ("resolved", "delay_accepted", True))
        self.assertEqual(self.record("DEL-1001")["response"], "delay_accepted")
        entries = self.events(run["run_id"])
        start = next(e for e in entries if e["event"] == "run.start")
        self.assertEqual((start["data"]["agent"], start["data"]["acting_as"]), ("disruption_agent", "hana"))
        self.assertEqual([e["event"] for e in entries if e["event"] == "step"], ["step"] * 3)
        # a cheaper expedite is within the agent's authority too; no person is asked
        status, cheap = self.begin("DEL-1005")
        self.assertEqual((cheap["status"], cheap["steps"][-1]["action"], cheap["steps"][-1]["reviewer"]),
                         ("completed", "expedite_shipment", None))
        # every released tool answers from a table: there is no connector to anything
        snapshot = self.call("GET", f"{UC}/releases/{self.release}")[1]
        self.assertTrue(snapshot["components"]["tools"]["all_simulated"])
        self.assertNotIn("http", json.dumps(snapshot["snapshot"]["tools"]))
        # production is not available, whatever the simulation showed
        self.assertEqual(self.call("POST", f"{UC}/stage", body={"to": "production", "reason": "it works"})[0], 403)

    def test_who_may_start_read_and_audit(self):  # P10, P11
        self.simulate()
        self.assertEqual(self.begin("DEL-1001", self.zoe)[0], 403)  # review, not run
        self.assertEqual(self.begin("DEL-1001", "acme-maria")[0], 404)  # no grant on this use case
        self.assertEqual(self.begin("DEL-1001", "nw-nadia")[0], 404)  # another workspace
        self.assertEqual(self.begin("DEL-1001", "acme-ada")[0], 403)  # administrators hold no run permission
        status, run = self.begin("DEL-1001")
        self.assertEqual(status, 200)
        self.assertEqual(self.call("GET", f"{ENGINE}/runs/{run['run_id']}/audit", self.zoe)[0], 403)
        self.assertEqual(self.call("GET", f"{ENGINE}/runs/{run['run_id']}", "nw-nadia")[0], 404)
        self.assertEqual(self.call("POST", f"{ENGINE}/runs", "acme-hana", {"case": {"Delivery": {"status": "delayed"}}})[0], 403)


class GovernedDecisionTests(SimulationBase):
    def setUp(self):
        super().setUp()
        self.simulate()

    def test_a_costly_response_waits_for_an_authorised_person(self):  # P3, P9
        status, run = self.begin("DEL-1002")
        self.assertEqual((status, run["status"]), (200, "awaiting_review"), run)
        self.assertEqual([s["action"] for s in run["steps"]], ["assess_impact", "compare_alternatives"])
        self.assertEqual(self.record("DEL-1002")["response"], "")  # nothing was expedited
        review_id = self.run_of(run["run_id"], self.zoe)["pending_review"]
        _, review = self.call("GET", f"{ENGINE}/reviews/{review_id}", self.zoe)
        self.assertEqual((review["action"], review["reviewers"]), ("expedite_shipment", ["operations_manager"]))
        self.assertIn("5000", " ".join(review["request"]["reasons"]))
        decision = f"{ENGINE}/reviews/{review_id}/decision"
        # the requester, a member without the reviewer role and a machine cannot decide
        self.assertEqual(self.call("POST", decision, "acme-hana", {"approved": True})[0], 403)
        self.assertEqual(self.call("POST", decision, self.bot, {"approved": True})[0], 404)
        self.assertEqual(self.call("POST", decision, "nw-nadia", {"approved": True})[0], 404)
        self.assertEqual(self.run_of(run["run_id"])["status"], "awaiting_review")
        # one open run per record: the same action cannot be started twice
        status, out = self.begin("DEL-1002")
        self.assertEqual(status, 409, out)
        self.assertIn("already has an open run", out["error"]["message"])
        status, done = self.call("POST", decision, self.zoe, {"approved": True, "comment": "the line would stop"})
        self.assertEqual((status, done["status"]), (200, "completed"), done)
        last = done["steps"][-1]
        self.assertEqual((last["action"], last["verdict"], last["reviewer"], last["environment"]),
                         ("expedite_shipment", "review", "zoe", "simulated"))
        self.assertEqual(self.record("DEL-1002")["response"], "shipment_expedited")
        decided = [e for e in self.events(run["run_id"]) if e["event"] == "review.decision"]
        self.assertEqual([(e["data"]["approved"], e["data"]["reviewer"], e["data"]["comment"]) for e in decided],
                         [(True, "zoe", "the line would stop")])
        self.assertEqual(self.call("POST", decision, self.zoe, {"approved": True})[0], 409)  # decided once

    def test_a_prohibited_action_is_refused_by_policy(self):  # P4
        status, run = self.begin("DEL-1003")  # an exclusive supplier: the only response would be to replace it
        self.assertEqual((status, run["status"]), (200, "escalated"), run)
        self.assertEqual(run["steps"], [])  # refused before anything was done
        self.assertEqual(run["escalation"]["reason"], "no compliant path to the goal")
        self.assertEqual(run["escalation"]["details"],
                         ["switch_supplier: prohibited: A supplier under an exclusivity agreement is never replaced"])
        self.assertEqual((self.record("DEL-1003")["status"], self.record("DEL-1003")["response"]), ("delayed", ""))
        end = [e for e in self.events(run["run_id"]) if e["event"] == "run.end"][-1]
        self.assertIn("prohibited", json.dumps(end["data"]["escalation"]))
        self.assertIsNone(run["pending_review"])  # no person is asked to approve what the policy forbids

    def test_a_reviewers_refusal_stops_the_action(self):  # P5
        _, run = self.begin("DEL-1002")
        review_id = self.run_of(run["run_id"], self.zoe)["pending_review"]
        status, done = self.call("POST", f"{ENGINE}/reviews/{review_id}/decision", self.zoe,
                                 {"approved": False, "comment": "too expensive this quarter"})
        self.assertEqual((status, done["status"]), (200, "blocked"), done)
        self.assertEqual((done["escalation"]["action"], done["escalation"]["details"]),
                         ("expedite_shipment", ["too expensive this quarter"]))
        self.assertEqual(self.record("DEL-1002")["response"], "")
        self.assertNotIn("expedite_shipment", [s["action"] for s in done["steps"] if s["outcome"]])


class CancellationAndFailureTests(SimulationBase):
    def setUp(self):
        super().setUp()
        self.simulate()

    def test_a_waiting_run_is_cancelled_with_evidence(self):  # P6
        _, run = self.begin("DEL-1002")
        cancel = f"{ENGINE}/runs/{run['run_id']}/cancel"
        review_id = self.run_of(run["run_id"], self.zoe)["pending_review"]
        self.assertEqual(self.call("POST", cancel, "acme-hana", {})[0], 400)  # a reason is required
        self.assertEqual(self.call("POST", cancel, self.zoe, {"reason": "x"})[0], 403)  # may not run
        self.assertEqual(self.call("POST", cancel, "nw-nadia", {"reason": "x"})[0], 404)
        self.assertEqual(self.call("POST", f"{ENGINE}/runs/nope/cancel", "acme-hana", {"reason": "x"})[0], 404)
        status, out = self.call("POST", cancel, "acme-hana", {"reason": "the order was withdrawn"})
        self.assertEqual((status, out["status"], out["pending_review"]), (200, "cancelled", None), out)
        self.assertEqual(out["escalation"]["reason"], "cancelled by hana: the order was withdrawn")
        self.assertEqual([s["action"] for s in out["steps"]], ["assess_impact", "compare_alternatives"])  # what it did stays
        entries = self.events(run["run_id"])  # the chain still verifies, and says who stopped the run and why
        cancelled = [e["data"] for e in entries if e["event"] == "run.cancelled"]
        self.assertEqual([(c["by"], c["reason"], c["was"], c["pending_action"]) for c in cancelled],
                         [("hana", "the order was withdrawn", "awaiting_review", "expedite_shipment")])
        self.assertEqual(entries[-1]["data"]["status"], "cancelled")
        # the review is closed: not pending, not decidable, and recorded as a cancellation, not as a decision
        self.assertEqual(self.call("GET", f"{ENGINE}/reviews", self.zoe)[1]["items"], [])
        self.assertEqual(self.call("POST", f"{ENGINE}/reviews/{review_id}/decision", self.zoe, {"approved": True})[0], 409)
        closed = self.desk.store.get_review(review_id)
        self.assertEqual((closed["status"], closed["decision"]["cancelled"], closed["decided_by"]), ("cancelled", True, "hana"))
        self.assertEqual(self.record("DEL-1002")["response"], "")  # nothing further happened
        self.assertEqual(self.call("POST", cancel, "acme-hana", {"reason": "again"})[0], 409)  # only a waiting run
        status, again = self.begin("DEL-1002")  # the record is free for a new run
        self.assertEqual((status, again["status"]), (200, "awaiting_review"), again)
        done = self.begin("DEL-1001")[1]
        self.assertEqual(self.call("POST", f"{ENGINE}/runs/{done['run_id']}/cancel", "acme-hana", {"reason": "late"})[0], 409)

    def test_a_failing_tool_fails_the_same_way_every_time(self):  # P7
        status, run = self.begin("DEL-1004")  # its record carries the synthetic outage switch
        self.assertEqual((status, run["status"]), (200, "escalated"), run)
        self.assertEqual(run["escalation"]["reason"],
                         "compare_alternatives failed 3 times: the sourcing catalogue is not reachable (simulated outage)")
        self.assertEqual([(s["action"], s["outcome"]) for s in run["steps"]], [("assess_impact", "done"), ("compare_alternatives", None)])
        errors = [e["data"] for e in self.events(run["run_id"]) if e["event"] == "tool.error"]
        self.assertEqual(len(errors), 3)
        self.assertTrue(all("simulated outage" in json.dumps(e) for e in errors))
        self.assertEqual(self.record("DEL-1004")["status"], "assessed")  # what succeeded stays; nothing else happened
        status, second = self.begin("DEL-1004")  # the first run ended: a new one meets the same failure
        self.assertEqual((second["status"], second["escalation"]["reason"]), ("escalated", run["escalation"]["reason"]))
        self.assertEqual([s["action"] for s in second["steps"]], ["compare_alternatives"])  # the assessment is not repeated

    def test_runs_survive_a_restart_and_continue(self):  # P8
        _, waiting = self.begin("DEL-1002")
        _, done = self.begin("DEL-1001")
        review_id = self.run_of(waiting["run_id"], self.zoe)["pending_review"]
        self.start()  # stop the platform and start it again on the same data
        listed = {r["run_id"]: r["status"] for r in self.call("GET", f"{ENGINE}/runs", "acme-hana")[1]["items"]}
        self.assertEqual(listed, {waiting["run_id"]: "awaiting_review", done["run_id"]: "completed"})
        self.assertEqual(self.call("GET", UC)[1]["effective_stage"], "simulation")
        self.assertEqual(self.run_of(done["run_id"])["audit_verified"], True)
        status, out = self.call("POST", f"{ENGINE}/reviews/{review_id}/decision", self.zoe, {"approved": True})
        self.assertEqual((status, out["status"], out["configuration"]), (200, "completed", self.fingerprint), out)
        self.assertEqual(len(self.events(waiting["run_id"])) > 5, True)


if __name__ == "__main__":
    import unittest

    unittest.main()
