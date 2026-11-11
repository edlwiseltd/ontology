"""Review item 4: an unexpected tool exception cannot erase the record or strand a review."""

import unittest
from unittest import mock

from autology import AutoApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.server import ApiError

from .test_platform import CASE, EX, add_big_order, service


def crashing_tools(capability="logistics.ship", exc=RuntimeError("carrier API returned garbage")):
    tools = load_tools(EX / "tools.json")

    def boom(call):
        raise exc

    tools.register("broken", capability, boom, priority=99)
    return tools


class AgentTests(unittest.TestCase):
    def test_unexpected_exception_escalates_with_the_record_intact(self):
        onto = Ontology.load(EX / "ontology.json")
        agent = WorkAgent("a", onto, crashing_tools(onto.actions["ship_order"].capability), roles=["ops", "eu_ops", "finance"], approver=AutoApprover())
        result = agent.run("fulfil_contract", CASE, "K-1")
        self.assertEqual(result.status, "escalated")
        self.assertIn("RuntimeError: carrier API returned garbage", result.escalation.reason)
        self.assertEqual(result.escalation.to, "it-integration")
        self.assertTrue(any(s.action.startswith("pick_order") for s in result.steps))  # earlier work is kept
        events = [e for e in result.audit if e.event == "tool.exception"]
        self.assertEqual(len(events), 1)
        self.assertIn("RuntimeError", events[0].data["error"])
        self.assertTrue(result.audit.verify())


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}

    def test_run_is_saved_when_a_tool_crashes(self):
        cap = self.svc.ontology.actions["pick_order"].capability
        broken = crashing_tools(cap)
        self.svc.agents["fulfilment"].agent.tools = broken
        out = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        self.assertEqual(out["status"], "escalated")
        stored = self.svc.store.load_run(out["run_id"])
        self.assertEqual(stored.status, "escalated")
        self.assertTrue(self.svc.store.verify_audit(out["run_id"]))

    def test_decide_stays_consistent_when_resume_fails(self):
        run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        review_id = run["pending_review"]
        agent = self.svc.agents["fulfilment"].agent
        with mock.patch.object(agent, "resume", side_effect=RuntimeError("disk full")):
            with self.assertRaises(ApiError) as cm:
                self.svc.decide(self.u["lena"], review_id, {"approved": True, "comment": "ok"})
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(self.svc.store.get_review(review_id)["status"], "pending")  # can be decided again
        self.assertEqual(self.svc.store.load_run(run["run_id"]).status, "awaiting_review")
        done = self.svc.decide(self.u["lena"], review_id, {"approved": True, "comment": "ok"})
        self.assertEqual(done["status"], "completed")

    def test_decide_stays_consistent_when_saving_fails(self):
        run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        review_id = run["pending_review"]
        with mock.patch.object(self.svc.store, "save_run", side_effect=RuntimeError("database is locked")):
            with self.assertRaises(ApiError):
                self.svc.decide(self.u["lena"], review_id, {"approved": True, "comment": "ok"})
        self.assertEqual(self.svc.store.get_review(review_id)["status"], "pending")
        self.assertEqual(self.svc.store.load_run(run["run_id"]).status, "awaiting_review")

    def test_tool_crash_after_review_is_recorded(self):
        run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        cap = self.svc.ontology.actions["ship_order"].capability
        self.svc.agents["fulfilment"].agent.tools = crashing_tools(cap)
        out = self.svc.decide(self.u["lena"], run["pending_review"], {"approved": True, "comment": "ok"})
        self.assertEqual(out["status"], "escalated")
        self.assertEqual(self.svc.store.get_review(run["pending_review"])["status"], "approved")
        self.assertEqual(self.svc.store.load_run(run["run_id"]).status, "escalated")


if __name__ == "__main__":
    unittest.main()
