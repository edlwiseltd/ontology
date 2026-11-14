"""Studio increment 2, engine side: model drafts, located validation, discovery questions, blueprint proposals.

  M1 validation runs the engine's strict loader and locates the problem (node, field or edge) without saving
  M2 discovery questions come from real gaps in the model and the use case (rule-based, labelled as such)
  M3 proposals from a brief are provisional typed additions from an approved blueprint, labelled "ai": false,
     never applied by the engine, and skip what the model already has
  M4 drafts are versioned, append-only, saved only over the revision read (409 otherwise), by administrators;
     a draft never changes the active model or what runs
  M5 the synthetic water-treatment journey: brief -> proposal -> accepted -> valid draft -> questions -> saved
"""

import copy
import json
import os
import sqlite3
import tempfile
import unittest

from autology.modeling import propose, questions, validate
from autology.platform import Platform
from autology.server import ApiError

from .helpers import ROOT
from .test_platform import service
from .test_r2_use_case_lifecycle import close
from .test_workspaces import EX, TOKENS, Client

WATER = json.loads((ROOT / "examples" / "water_treatment" / "ontology.json").read_text())
BRIEF = ("We operate multiple treatment plants. Model our pump assets, maintenance process, technicians, "
         "supervisors and approval responsibilities.")


def apply(document, items):
    """What Studio does when a person accepts proposal items into the draft."""
    doc = copy.deepcopy(document)
    for item in items:
        if item["kind"] == "entity":
            doc.setdefault("entities", {})[item["name"]] = item["value"]
        elif item["kind"] == "action":
            doc.setdefault("actions", {})[item["name"]] = item["value"]
        elif item["kind"] == "relationship":
            doc.setdefault("relationships", []).append(item["value"])
        elif item["kind"] == "rule":
            doc.setdefault("rules", []).append(item["value"])
    return doc


class ValidationTests(unittest.TestCase):  # M1
    def test_a_valid_model(self):
        out = validate(WATER)
        self.assertTrue(out["valid"])
        self.assertEqual(out["summary"]["entities"], 1)

    def test_problems_are_located_on_a_node_field_or_edge(self):
        doc = copy.deepcopy(WATER)
        doc["entities"]["Plant"]["attributes"]["flow"] = "nmber"
        out = validate(doc)
        p = out["problems"][0]
        self.assertEqual((out["valid"], p["path"], p["node"], p["field"]),
                         (False, "entities.Plant.attributes.flow", "Plant", "attributes.flow"))
        self.assertIn("did you mean 'number'", p["message"])
        doc = copy.deepcopy(WATER)
        doc["relationships"] = [{"source": "Plant", "to": "Plant", "type": "x"}]
        p = validate(doc)["problems"][0]
        self.assertEqual((p["path"], p["edge"]), ("relationships.0", 0))
        self.assertFalse(validate([1])["valid"])
        doc = copy.deepcopy(WATER)
        doc["entities"]["Crew"] = {"attributes": {"name": "string"}}  # no state
        p = validate(doc)["problems"][0]
        self.assertEqual(p["node"], "Crew")


class QuestionTests(unittest.TestCase):  # M2
    def test_questions_come_from_real_gaps(self):
        doc = apply(WATER, propose(BRIEF, WATER)["items"])
        doc["entities"]["Orphan"] = {"attributes": {"x": "string"}}
        svc = service(automations={}, chat=None)
        try:
            ids = {q["id"]: q for q in questions(doc, svc)}
        finally:
            svc.close()
        self.assertIn("isolated:Orphan", ids)
        self.assertEqual(ids["reviewer:maintenance_supervisor"]["severity"], "high")  # nobody holds the role
        self.assertIn("capability:maintenance.approve", ids)  # no tool provides it
        self.assertIn("side-effect:schedule_work", ids)  # undeclared: treated as unsafe to repeat (D8)
        self.assertNotIn("side-effect:approve_work_order", ids)  # declared
        self.assertIn("goals", ids)
        self.assertNotIn("isolated:Pump", ids)
        self.assertEqual(questions("not a model"), [])


class ProposalTests(unittest.TestCase):  # M3
    def test_a_brief_gets_provisional_blueprint_items_labelled_not_ai(self):
        out = propose(BRIEF, WATER)
        self.assertEqual((out["generator"], out["ai"], out["blueprint"]["id"]), ("blueprint", False, "water-treatment"))
        self.assertIn("pump", out["matched_terms"])
        kinds = {i["kind"] for i in out["items"]}
        self.assertEqual(kinds, {"entity", "relationship", "action", "rule"})
        self.assertTrue(all(i["status"] == "provisional" and i["provenance"]["ai"] is False for i in out["items"]))
        self.assertNotIn("Plant", [i["name"] for i in out["items"]])  # already in the model
        self.assertEqual(len({i["id"] for i in out["items"]}), len(out["items"]))

    def test_an_unrelated_brief_gets_nothing_and_says_why(self):
        out = propose("We sell concert tickets online.", WATER)
        self.assertEqual(out["items"], [])
        self.assertIn("D7", out["message"])


class DraftTests(unittest.TestCase):  # M4
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}

    def tearDown(self):
        self.svc.close()

    def test_drafts_are_versioned_checked_and_never_active(self):
        before = (self.svc.ontology.ref, self.svc.ontology.fingerprint)
        first = self.svc.model_draft(self.u["olivia"])
        self.assertEqual((first["revision"], first["validation"]["valid"]), (0, True))  # the active model
        doc = copy.deepcopy(first["document"])
        doc["entities"]["Order"]["attributes"]["notes"] = "string"
        saved = self.svc.save_model_draft(self.u["admin"], {"document": doc, "expected_revision": 0, "note": "notes"})
        self.assertEqual((saved["revision"], saved["author"]), (1, "admin"))
        with self.assertRaises(ApiError) as ctx:  # someone saved meanwhile
            self.svc.save_model_draft(self.u["admin"], {"document": doc, "expected_revision": 0})
        self.assertEqual((ctx.exception.status, ctx.exception.extra["revision"]), (409, 1))
        with self.assertRaises(ApiError) as ctx:
            self.svc.save_model_draft(self.u["olivia"], {"document": doc, "expected_revision": 1})
        self.assertEqual(ctx.exception.status, 403)
        for bad in ({"document": [], "expected_revision": 1}, {"document": doc}, {"document": doc, "expected_revision": True}):
            with self.assertRaises(ApiError) as ctx:
                self.svc.save_model_draft(self.u["admin"], bad)
            self.assertEqual(ctx.exception.status, 400)
        # an invalid draft can be saved (work in progress) and says so
        broken = copy.deepcopy(doc)
        broken["entities"]["Order"]["attributes"]["notes"] = "txt"
        out = self.svc.save_model_draft(self.u["admin"], {"document": broken, "expected_revision": 1})
        self.assertEqual((out["revision"], out["validation"]["valid"]), (2, False))
        self.assertEqual([h["revision"] for h in self.svc.model_draft_history(self.u["lena"])["items"]], [1, 2])
        self.assertEqual((self.svc.ontology.ref, self.svc.ontology.fingerprint), before)  # nothing became active
        self.assertFalse(out["active_model_changed"])
        with self.assertRaises(sqlite3.DatabaseError):
            self.svc.store._db.execute("UPDATE model_drafts SET note='x'")
        with self.assertRaises(ApiError) as ctx:
            self.svc.architect_proposals(self.u["olivia"], {"brief": BRIEF})
        self.assertEqual(ctx.exception.status, 403)


class WaterTreatmentJourneyTests(unittest.TestCase):  # M5, through the platform router
    def test_brief_to_saved_valid_draft_through_the_platform(self):
        os.environ.update(TOKENS)
        spec = json.loads((EX / "platform.json").read_text())
        spec["data_dir"] = tempfile.mkdtemp()
        pf = Platform(spec, EX)
        c = Client(pf)
        try:
            status, uc = c.call("POST", "/platform/workspaces/acme/use-cases", "acme-ada",
                                {"id": "water-ops", "name": "Water operations", "template": "industrial-starter"})
            self.assertEqual((status, uc["stage"]), (201, "draft"))
            base = "/w/acme/u/water-ops/api"
            _, draft = c.call("GET", f"{base}/model/draft", "acme-ada")
            _, proposal = c.call("POST", f"{base}/architect/proposals", "acme-ada", {"brief": BRIEF})
            self.assertGreater(len(proposal["items"]), 8)
            doc = apply(draft["document"], proposal["items"])
            _, checked = c.call("POST", f"{base}/model/validate", "acme-ada", {"document": doc})
            self.assertTrue(checked["validation"]["valid"], checked["validation"])
            self.assertIn("reviewer:maintenance_supervisor", [q["id"] for q in checked["questions"]])
            status, saved = c.call("POST", f"{base}/model/draft", "acme-ada",
                                   {"document": doc, "expected_revision": 0, "note": "from the water blueprint"})
            self.assertEqual((status, saved["revision"], saved["validation"]["summary"]["entities"]), (200, 1, 5))
            # another workspace cannot read or write it; the active model is unchanged
            self.assertEqual(c.call("GET", f"{base}/model/draft", "nw-nadia")[0], 404)
            _, onto = c.call("GET", f"{base}/ontology", "acme-ada")
            self.assertEqual(list(onto["entities"]), ["Plant"])
        finally:
            c.server.shutdown()
            c.server.server_close()
            close(pf)


if __name__ == "__main__":
    unittest.main()
