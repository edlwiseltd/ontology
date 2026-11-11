"""Review item 7: suspension is counted per run, survives restarts, and is lifted only by an admin, with a reason."""

import sys
import tempfile
import unittest
from pathlib import Path

from autology import Ontology, WorkAgent
from autology.reasoners import PlanFollowingReasoner, Proposal
from autology.server import ApiError

from .test_operations import mfg, procurement_agent, supplier_case
from .test_platform import _Api, add_big_order, service


class Sometimes:
    """Proposes an illegal action twice per run, then behaves."""

    def __init__(self):
        self.bad = 0

    def propose(self, ctx):
        if self.bad < 2:
            self.bad += 1
            return Proposal("sign_supplier_contract", "hurry", "rogue")
        return PlanFollowingReasoner().propose(ctx)


class PerRunTests(unittest.TestCase):
    def test_violations_in_one_run_do_not_count_against_the_next(self):
        onto = mfg()
        agent = procurement_agent(onto, reasoner=Sometimes())
        case = supplier_case(late_delivery_penalty=False)
        first = agent.run("contract_supplier", case)
        self.assertEqual((first.status, len(first.violations)), ("completed", 2))
        agent.reasoner = Sometimes()
        second = agent.run("contract_supplier", case)  # max_violations is 3: two more here must not suspend
        self.assertEqual((second.status, len(second.violations)), ("completed", 2))


ROGUE = '''
from autology.reasoners import Proposal

class Rogue:
    def propose(self, ctx):
        return Proposal("invoice_order@O-4", "skip ahead", "rogue")
'''


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "rogue_reasoner_mod.py").write_text(ROGUE)
        sys.path.insert(0, str(self.tmp))
        self.store = str(self.tmp / "s.db")

    def tearDown(self):
        sys.path.remove(str(self.tmp))
        sys.modules.pop("rogue_reasoner_mod", None)

    def svc(self, reasoner="rogue_reasoner_mod:Rogue"):
        agents = {"fulfilment": {"roles": ["ops", "eu_ops", "finance"], "tools": "tools.json",
                                 "goals": ["fulfil_contract"], "reasoner": reasoner}}
        return service(agents=agents, store=self.store, automations={}, chat=None)

    def test_suspension_survives_a_restart_and_needs_a_reasoned_reinstatement(self):
        svc = self.svc()
        u = {x.name: x for x in svc.users}
        body = add_big_order(svc)
        self.assertEqual(svc.start_run(u["olivia"], body)["status"], "suspended")
        restarted = self.svc(reasoner="planner")  # a new process with a fixed reasoner: still suspended
        u = {x.name: x for x in restarted.users}
        self.assertEqual(restarted.start_run(u["olivia"], body)["status"], "suspended")
        listing = restarted.list_agents(u["olivia"])["items"]
        self.assertTrue(listing["fulfilment"]["suspended"])
        for who, payload, status in [("olivia", {"reason": "fixed the reasoner"}, 403),
                                     ("admin", {}, 400), ("admin", {"reason": "ok"}, 400)]:
            with self.subTest(who=who, payload=payload), self.assertRaises(ApiError) as cm:
                restarted.reinstate_agent(u[who], "fulfilment", payload)
            self.assertEqual(cm.exception.status, status)
        out = restarted.reinstate_agent(u["admin"], "fulfilment", {"reason": "reasoner replaced by the planner"})
        self.assertFalse(out["suspended"])
        history = restarted.store.suspension_history("fulfilment")
        self.assertEqual(history[0]["reinstated_by"], "admin")
        self.assertEqual(history[0]["reinstate_reason"], "reasoner replaced by the planner")
        self.assertEqual(restarted.start_run(u["olivia"], body)["status"], "awaiting_review")
        again = self.svc(reasoner="planner")  # the reinstatement persists too
        self.assertFalse(again.list_agents(u["olivia"])["items"]["fulfilment"]["suspended"])

    def test_http(self):
        svc = self.svc()
        u = {x.name: x for x in svc.users}
        svc.start_run(u["olivia"], add_big_order(svc))
        api = _Api(svc)
        try:
            self.assertTrue(api.call("GET", "/api/agents", "olivia")[1]["items"]["fulfilment"]["suspended"])
            self.assertEqual(api.call("POST", "/api/agents/fulfilment/reinstate", "admin",
                                      {"reason": "investigated, reasoner fixed"})[0], 200)
            self.assertEqual(api.call("POST", "/api/agents/ghost/reinstate", "admin", {"reason": "whatever x"})[0], 404)
        finally:
            api.server.shutdown()


if __name__ == "__main__":
    unittest.main()
