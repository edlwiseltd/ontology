"""Review item 3: write-back only touches what the run wrote, and never overwrites newer live data."""

import unittest

from autology.graph import KnowledgeGraph, write_back
from autology.state import WorldState

from .test_platform import EX, add_big_order, service


class WriteBackTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}
        self.run = self.svc.start_run(self.u["olivia"], add_big_order(self.svc))
        self.review = self.svc.list_reviews(self.u["lena"], "pending")["items"][0]["review_id"]

    def edit(self, iid, **attrs):
        inst = self.svc.graph.get(iid)
        self.svc.upsert_object(self.u["admin"], {"type": inst.type, "id": iid,
                                                 "attributes": {**inst.attributes, **attrs}})

    def test_fields_the_run_did_not_write_are_left_alone(self):
        self.edit("C-2", credit_limit=750000, name="Contoso Power Ltd")  # changed while the run waits
        done = self.svc.decide(self.u["lena"], self.review, {"approved": True, "comment": "ok"})
        self.assertEqual(done["status"], "completed")
        live = self.svc.graph.get("C-2").attributes
        self.assertEqual((live["credit_limit"], live["name"]), (750000, "Contoso Power Ltd"))
        self.assertEqual(self.svc.graph.get("O-4").attributes["status"], "invoiced")  # the run's own work
        stored = self.svc.store.load_graph(self.svc.ontology).get("C-2").attributes
        self.assertEqual(stored["credit_limit"], 750000)

    def test_an_order_cancelled_during_the_review_is_not_shipped(self):
        # ACT-6 (audit GAP-009): the run re-reads its records before acting on the approval
        self.edit("O-4", status="cancelled")  # someone cancelled the order while it waited for review
        done = self.svc.decide(self.u["lena"], self.review, {"approved": True, "comment": "ok"})
        self.assertEqual(self.svc.graph.get("O-4").attributes["status"], "cancelled")  # not overwritten
        result = self.svc.store.load_run(self.run["run_id"])
        self.assertNotIn("ship_order@O-4:done", result.path)
        self.assertEqual(done["status"], "completed")  # all orders invoiced or cancelled
        self.assertIn("review.superseded", [e.event for e in result.audit])
        self.assertEqual(self.svc.store.run_sources(self.run["run_id"])["conflicts"], [])

    def test_repeated_saves_do_not_flag_the_runs_own_writes(self):
        # the first save (awaiting review) already wrote O-4 status 'picked'; the second must not see a conflict
        self.svc.decide(self.u["lena"], self.review, {"approved": True, "comment": "ok"})
        self.assertEqual(self.svc.store.run_sources(self.run["run_id"])["conflicts"], [])
        self.assertEqual(self.svc.graph.get("O-4").attributes["status"], "invoiced")


class GraphWriteBackTests(unittest.TestCase):
    def test_function(self):
        from autology import Ontology
        import json

        onto = Ontology.load(EX / "ontology.json")
        graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
        base = {"O-1": dict(graph.get("O-1").attributes)}
        state = WorldState.initial(onto, {"Order": [{"id": "O-1", **graph.get("O-1").attributes, "tracking": "T1"}]})
        graph.get("O-1").attributes["amount"] = 1  # live change to a field the run did not touch
        changed, conflicts = write_back(graph, state, {"Order": ["O-1"]}, base)
        self.assertEqual((changed, conflicts), (["O-1"], []))
        self.assertEqual((graph.get("O-1").attributes["tracking"], graph.get("O-1").attributes["amount"]), ("T1", 1))
        self.assertEqual(base["O-1"]["tracking"], "T1")  # the base advances with what was written


if __name__ == "__main__":
    unittest.main()
