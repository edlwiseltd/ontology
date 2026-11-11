"""Review item 5: a human review must be decided by a human other than the requester."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from autology import AutoApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.reporting import compliance_report
from autology.server import ApiError, AutologyService, hash_token

from .test_platform import CASE, EX, _Api, add_big_order, service

SAM = {"name": "sam", "token_sha256": hash_token("tok-sam"), "permissions": ["read", "run", "review"],
       "roles": ["ops"], "reviewer_roles": ["logistics_manager"]}


def with_sam(**overrides):
    cfg = json.loads((EX / "server.json").read_text())
    return service(users=cfg["users"] + [SAM], automations={}, chat=None, **overrides)


class ApproverConfigTests(unittest.TestCase):
    def test_automatic_approvers_need_the_simulation_flag(self):
        for approver in ("auto", "approvals.json"):
            agents = {"fulfilment": {"roles": ["ops", "eu_ops", "finance"], "tools": "tools.json",
                                     "approver": approver}}
            with self.subTest(approver), self.assertRaises(ValueError) as cm:
                service(agents=agents, automations={}, chat=None)
            self.assertIn("simulation", str(cm.exception))
            sim = service(agents=agents, automations={}, chat=None, simulation=True)
            self.assertTrue(sim.simulation)
        deny = service(agents={"fulfilment": {"roles": ["ops"], "tools": "tools.json", "approver": "deny"}},
                       automations={}, chat=None)
        self.assertFalse(deny.simulation)  # declining everything never approves anything: allowed

    def test_the_flag_is_visible(self):
        sim = service(automations={}, chat=None, simulation=True)
        api = _Api(sim)
        try:
            self.assertTrue(api.call("GET", "/api/health")[1]["simulation"])
            report = api.call("GET", "/api/report", "olivia")[1]
            self.assertIn("SIMULATION", report)
            self.assertTrue(api.call("GET", "/api/score", "olivia")[1]["simulation"])
        finally:
            api.server.shutdown()
        real = service(automations={}, chat=None)
        api = _Api(real)
        try:
            self.assertFalse(api.call("GET", "/api/health")[1]["simulation"])
            self.assertNotIn("SIMULATION", api.call("GET", "/api/report", "olivia")[1])
        finally:
            api.server.shutdown()

    def test_reports_flag_automatic_decisions(self):
        onto = Ontology.load(EX / "ontology.json")
        agent = WorkAgent("a", onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops", "finance"],
                          approver=AutoApprover())
        result = agent.run("fulfil_contract", CASE, "K-1")
        review = next(e for e in result.audit if e.event == "review")
        self.assertTrue(review.data["automatic"])
        self.assertIn("decided automatically", compliance_report([result], onto))


class SelfReviewTests(unittest.TestCase):
    def test_starter_cannot_approve_their_own_run(self):
        svc = with_sam()
        sam = next(u for u in svc.users if u.name == "sam")
        lena = next(u for u in svc.users if u.name == "lena")
        run = svc.start_run(sam, add_big_order(svc))
        start = next(e for e in svc.store.audit_log(run["run_id"]) if e.event == "run.start")
        self.assertEqual(start.data["started_by"], "sam")
        self.assertEqual(svc.store.run_starter(run["run_id"]), "sam")
        with self.assertRaises(ApiError) as cm:
            svc.decide(sam, run["pending_review"], {"approved": True, "comment": "mine, looks fine"})
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("started this run", cm.exception.message)
        self.assertEqual(svc.decide(lena, run["pending_review"], {"approved": True, "comment": "ok"})["status"],
                         "completed")

    def test_rule_can_allow_self_review(self):
        doc = json.loads((EX / "ontology.json").read_text())
        for rule in doc["rules"]:
            if rule["id"] == "R-LOG-001":
                rule["allow_self_review"] = True
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ontology.json").write_text(json.dumps(doc))
        svc = with_sam(ontology=str(tmp / "ontology.json"))
        sam = next(u for u in svc.users if u.name == "sam")
        run = svc.start_run(sam, add_big_order(svc))
        self.assertEqual(svc.decide(sam, run["pending_review"], {"approved": True, "comment": "ok"})["status"],
                         "completed")


if __name__ == "__main__":
    unittest.main()
