"""GAP-107: where a draft's model comes from is established by the Engine, on every way a draft can be written.

The requests are sent to the API directly; no screen is involved. A provider test double answers; nothing is paid.

Draft entry points (all of them): ``POST …/model/draft`` (the model; ``ArchitectService.save_draft``) and
``POST …/solution/draft`` (the configuration; the model is carried over unchanged). Nothing else writes a draft.

  N1  a draft that names no proposal and takes an unconfirmed inferred element          409
  N2  a draft that names another proposal than the one its elements come from           409
  N3  a proposal of another workspace, or one that does not exist                       400 / 403-404
  N4  the right proposal with a stale revision (recorded as found) or a modified element 200 as found / 409
  N5  an inferred element without a decision, with the proposal named                   409
  N6  an element explicitly rejected, then proposed again                               409
  N7  an element corrected, then changed again; the content from before the correction  409
  N8  a client's claim that the draft is manual                                         ignored; 409 or recorded as found
  N9  a model authored by hand through the authenticated route                          200, attributed
  N10 a draft of unknown provenance (legacy)                                            not published; re-established or refused
  N11 a service identity reviewing, saving or publishing                                403
  N12 forged decision fields; a member of another workspace                             ignored or refused; 403-404
  N13 a decision that leaves a relationship without its entity                          named, then refused at publication
  N14 publication without a second person                                               403
"""

import copy
import json
import unittest
from unittest import mock

from autology import proposal_review

from .test_arch2_ai_provider_governance import ENGINE, UC, WS
from .test_stab3_proposal_lifecycle import FIRST, SECOND, LifecycleBase

LINK = {"from": "Tug", "to": "Vessel", "type": "assists", "cardinality": "1..*", "rationale": "Tugs assist vessels",
        "basis": "inferred", "sources": [], "confidence": 0.6}
THIRD = {**SECOND, "relationships": [LINK]}


class OriginGate(LifecycleBase):
    def setUp(self):
        super().setUp()
        self.first, self.second = self.session()
        self.pid = self.first["id"]
        self.items = {i["name"]: i for i in self.second["items"]}
        review = {e["name"]: e for e in self.second["review"]["elements"]}
        self.stated = sorted(n for n, e in review.items() if not e["needs_confirmation"])
        self.assertTrue(review["Tug"]["needs_confirmation"] and len(self.stated) >= 2)
        self.base = self.call("GET", f"{ENGINE}/model/draft")[1]["document"]

    def doc(self, *names, **changed):
        out = copy.deepcopy(self.base)
        for name in names:
            out.setdefault("entities", {})[name] = copy.deepcopy(changed.get(name, self.items[name]["value"]))
        return out

    def save(self, document, origin=None, token="acme-ada", **extra):
        revision = self.call("GET", f"{ENGINE}/model/draft")[1]["revision"]
        body = {"document": document, "expected_revision": revision, "note": "x", **extra}
        if origin is not None:
            body["origin"] = origin
        return self.call("POST", f"{ENGINE}/model/draft", token, body)

    def decide(self, revision=2, token="acme-ada", **body):
        return self.call("POST", f"{ENGINE}/architect/proposals/{self.pid}/decision", token, {"revision": revision, **body})

    def refused(self, document, origin=None, why="", **extra):
        before = self.call("GET", f"{ENGINE}/model/draft")[1]["revision"]
        status, out = self.save(document, origin, **extra)
        self.assertEqual(status, 409, out)
        self.assertIn(why, json.dumps(out["error"]["details"]["unconfirmed"]))
        self.assertEqual(self.call("GET", f"{ENGINE}/model/draft")[1]["revision"], before)  # nothing was saved
        return out["error"]["details"]["unconfirmed"]


class ProposalBoundTests(OriginGate):
    def test_naming_no_proposal_changes_nothing(self):  # N1, N5, N8
        with_tug = self.doc(self.stated[0], "Tug")
        named = self.refused(with_tug, {"proposal": self.pid, "revision": 2}, "inferred and nobody confirmed it")
        silent = self.refused(with_tug, None, "inferred and nobody confirmed it")       # the bypass of GAP-107, closed
        self.assertEqual([(r["element"], r["proposal"], r["revision"]) for r in silent], [("entity:Tug", self.pid, 2)])
        self.assertEqual(named, silent)
        # a client that says "this is manual" is not believed: the claim is not an input
        self.refused(with_tug, None, "inferred and nobody confirmed it", provenance={"mode": "manual_authoring"}, manual=True)
        self.assertEqual(self.save(with_tug, "manual")[0], 400)
        self.assertEqual(self.save(with_tug, {"proposal": self.pid, "revision": 2, "mode": "manual_authoring"})[0], 400)
        # stated elements, no proposal named: saved, and the engine records the proposal it found by itself
        status, draft = self.save(self.doc(*self.stated[:2]), provenance={"mode": "manual_authoring"})
        self.assertEqual(status, 200, draft)
        found = draft["provenance"]
        self.assertEqual((found["mode"], draft["origin"], found["declared_origin"]), ("architect_proposal", {"proposal": self.pid, "revision": 2}, None))
        self.assertEqual(found["proposals"], [{"proposal": self.pid, "revision": 2}])
        self.assertEqual(sorted(c["element"] for c in found["confirmed"]), sorted(f"entity:{n}" for n in self.stated[:2]))
        self.assertIn("nothing a client says about origin is taken as proof", found["established_by"])
        # the next revision cannot drop the link: it is carried by the engine, whatever is sent
        by_hand = {**draft["document"], "entities": {**draft["document"]["entities"], "Quay": {"description": "By hand", "states": ["free"], "attributes": {}}}}
        status, later = self.save(by_hand)
        self.assertEqual((status, later["provenance"]["proposals"], later["provenance"]["mode"], later["origin"]),
                         (200, [{"proposal": self.pid, "revision": 2}], "manual_authoring", None))  # this revision's change is by hand, and says so

    def test_a_swapped_foreign_or_stale_reference(self):  # N2, N3, N4, N12
        self.answers.append(FIRST)
        status, other = self.ask(brief="An unrelated matter.")                              # a second proposal of this use case
        self.assertEqual(status, 200, other)
        mine = next(n for n in self.stated if f"entity:{n}" not in {f"entity:{i['name']}" for i in other["items"]})
        swapped = self.refused(self.doc(mine), {"proposal": other["id"], "revision": 1}, "nothing this draft adds or changes comes from the proposal it names")
        self.assertIn(f"those of proposal {self.pid}", swapped[0]["why"])
        for foreign in ({"proposal": "P-0000000000", "revision": 1}, {"proposal": self.pid, "revision": 9}):
            self.assertEqual(self.save(self.doc(mine), foreign)[0], 400, foreign)
        self.assertIn(self.save(self.doc(mine), {"proposal": self.pid, "revision": 2}, token="nw-nadia")[0], (403, 404))
        self.assertIn(self.call("GET", f"{ENGINE}/architect/proposals/{self.pid}", "nw-nadia")[0], (403, 404))
        # a modified element under the proposal's name: an edited element needs a recorded correction
        edited = {**self.items[mine]["value"], "description": "quietly changed"}
        self.refused(self.doc(mine, **{mine: edited}), {"proposal": self.pid, "revision": 2}, "differs from the element as it was reviewed")
        # a stale revision number with content that is the proposal's: saved, and recorded as the engine found it
        only_second = next(n for n in self.stated if n not in {i["name"] for i in self.first["items"]})
        status, draft = self.save(self.doc(only_second), {"proposal": self.pid, "revision": 1})
        self.assertEqual((status, draft["origin"], draft["provenance"]["declared_origin"]),
                         (200, {"proposal": self.pid, "revision": 2}, {"proposal": self.pid, "revision": 1}))

    def test_rejected_then_proposed_again_and_corrected_then_changed(self):  # N6, N7
        tug = self.items["Tug"]
        self.answers.append(THIRD)
        self.assertEqual(self.decide(rejected=[tug["id"]])[0], 200)
        status, third = self.call("POST", f"{ENGINE}/architect/proposals", "acme-ada", {"generator": "model", "revises": self.pid, "feedback": "again"})
        self.assertEqual((status, third["revision"]), (200, 3))
        for origin in (None, {"proposal": self.pid, "revision": 3}, {"proposal": self.pid, "revision": 2}):
            self.refused(self.doc("Tug"), origin, "it was rejected by ada")
        # corrected: the corrected content is the person's and may be saved; anything else under that name may not
        better = {**tug["value"], "description": "A harbour tug, as the harbour master describes it"}
        self.assertEqual(self.decide(revision=3, corrected=[{"id": tug["id"], "value": better}])[0], 200)
        self.refused(self.doc("Tug"), None, "the draft takes the content from before the correction")
        self.refused(self.doc("Tug", Tug={**better, "description": "changed once more"}), {"proposal": self.pid, "revision": 3},
                     "differs from the element as it was reviewed")
        status, draft = self.save(self.doc("Tug", Tug=better))
        self.assertEqual(status, 200, draft)
        self.assertEqual([(c["element"], c["decision"], c["by"], c["revision"]) for c in draft["provenance"]["confirmed"]],
                         [("entity:Tug", "corrected", "ada", 3)])

    def test_a_decision_that_leaves_a_relationship_without_its_entity(self):  # N13, N14
        self.answers.append(THIRD)
        status, third = self.call("POST", f"{ENGINE}/architect/proposals", "acme-ada", {"generator": "model", "revises": self.pid, "feedback": "links"})
        self.assertEqual(status, 200, third)
        link = next(i for i in third["items"] if i["kind"] == "relationship")
        tug = next(i for i in third["items"] if i["name"] == "Tug")
        status, after = self.decide(revision=3, accepted=[link["id"]], rejected=[tug["id"]])
        self.assertEqual(status, 200, after)
        self.assertEqual([(f["element"], f["because"]) for f in after["review"]["dependency_failures"]], [(link["id"], {tug["id"]: "rejected"})])
        self.assertFalse(after["review"]["ready_for_draft"])
        broken = {**self.doc("Vessel"), "relationships": [link["value"]]}
        status, draft = self.save(broken, {"proposal": self.pid, "revision": 3})   # a draft may be saved invalid: it is not active
        self.assertEqual((status, draft["validation"]["valid"]), (200, False))
        status, out = self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": draft["revision"], "reason": "x"})
        self.assertEqual(status, 409, out)                                           # and is never published so


class ManualAndLegacyTests(OriginGate):
    QUAY = {"description": "A quay, written by hand", "states": ["free", "occupied"], "attributes": {"length_m": "number"}}

    def manual(self):
        document = copy.deepcopy(self.base)
        document.setdefault("entities", {})["Quay"] = self.QUAY
        return document

    def test_a_model_authored_by_hand_is_saved_attributed_and_published_by_another_person(self):  # N9, N11, N14
        status, draft = self.save(self.manual())
        self.assertEqual(status, 200, draft)
        found = draft["provenance"]
        self.assertEqual((found["mode"], found["author"], found["authored"], found["proposals"], draft["origin"]),
                         ("manual_authoring", "ada", ["entity:Quay"], [], None))
        self.assertEqual((found["parent"], found["includes_unknown"]), ({"revision": 0, "mode": "active_model"}, False))
        self.assertIn("copied from outside Autology", found["cannot_prove"])        # what cannot be proven is said
        # the same element as an unconfirmed proposal element, with other content: the author's own, and flagged
        own = {**self.items["Tug"]["value"], "description": "My own wording"}
        status, flagged = self.save({**draft["document"], "entities": {**draft["document"]["entities"], "Tug": own}})
        self.assertEqual((status, flagged["provenance"]["mode"]), (200, "manual_authoring"))
        self.assertIn(f"same element as one of proposal {self.pid} (not confirmed there)", flagged["provenance"]["flags"][0]["note"])
        # a configuration saved on top of it derives from it: the model's provenance is carried, not restated
        robot = self.add("intake", kind="service")
        publish = f"{UC}/publish-draft"
        for who, token in (("the author", "acme-ada"), ("a reader", "acme-hana"), ("a service identity", robot)):
            self.assertIn(self.call("POST", publish, token, {"revision": flagged["revision"], "reason": "x"})[0], (403, 404), who)
        self.assertIn(self.save(self.manual(), token=robot)[0], (403, 404))
        self.assertIn(self.decide(token=robot, accepted=[self.items["Tug"]["id"]])[0], (403, 404))
        # the same service identity, now holding the design permission (granted by two people): it still reviews
        # nothing and publishes nothing, because both need a person. A draft it saves is classified like any other
        status, g = self.call("POST", f"{WS}/grants", body={"member": "intake", "use_case": "novel", "permissions": ["configure"], "reason": "an integration"})
        self.assertEqual(status, 201, g)
        self.assertEqual(self.call("POST", f"{WS}/grants/{g['id']}/approve", "acme-maria", {"reason": "checked"})[0], 200)
        status, out = self.decide(token=robot, accepted=[self.items["Tug"]["id"]])
        self.assertEqual((status, "person" in json.dumps(out)), (403, True), out)
        self.assertEqual(self.call("POST", publish, robot, {"revision": flagged["revision"], "reason": "x"})[0], 403)
        with_tug = {**flagged["document"], "entities": {**flagged["document"]["entities"], "Tug": self.items["Tug"]["value"]}}
        status, out = self.call("POST", f"{ENGINE}/model/draft", robot, {"document": with_tug, "expected_revision": flagged["revision"]})
        self.assertEqual((status, "inferred and nobody confirmed it" in json.dumps(out)), (409, True), out)
        self.assertEqual(self.call("POST", publish, "acme-maria", {"revision": flagged["revision"], "reason": "reviewed"})[0], 200)

    def test_a_draft_of_unknown_provenance_is_not_published_and_not_built_upon(self):  # N10
        store = self.pf.workspaces["acme"].use_cases["novel"].service.store
        legacy = self.manual()
        legacy["entities"]["Tug"] = self.items["Tug"]["value"]                      # holds an element nobody confirmed
        store.save_draft(legacy, "someone", "written before the engine classified drafts", 0)   # no provenance: as an old row
        status, shown = self.call("GET", f"{ENGINE}/model/draft")
        self.assertEqual((shown["provenance"]["mode"], shown["provenance"]["includes_unknown"]), ("legacy_unknown", True))
        status, out = self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": 1, "reason": "x"})
        self.assertEqual(status, 409, out)
        self.assertIn("provenance of this draft revision was never established", out["error"]["message"])
        # saved again as it is: every element beyond what runs is classified, and the unconfirmed one refuses it
        self.refused(legacy, None, "inferred and nobody confirmed it")
        # without it: re-established, attributed to the person who saved, and said to come from a legacy draft
        status, again = self.save(self.manual())
        self.assertEqual(status, 200, again)
        found = again["provenance"]
        self.assertEqual((found["mode"], found["author"], found["reestablished_from_legacy"], found["includes_unknown"], found["authored"]),
                         ("manual_authoring", "ada", True, False, ["entity:Quay"]))
        self.assertEqual(self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": again["revision"], "reason": "reviewed"})[0], 200)
        history = self.pf.workspaces["acme"].use_cases["novel"].service.store.draft_history()   # the engine was reloaded by publishing
        self.assertEqual([h["provenance"] is None for h in history], [True, False])   # the old row is as it was: nothing was added to it

    def test_forged_decision_fields_are_not_taken(self):  # N12
        tug = self.items["Tug"]
        status, out = self.decide(accepted=[tug["id"]], decided_by="maria", at="2020-01-01T00:00:00+00:00", seq=1, id="P-other")
        if status == 200:
            last = out["decisions"][-1]
            self.assertEqual((last["decided_by"], last["revision"]), ("ada", 2))
            self.assertFalse(last["at"].startswith("2020"))
        else:
            self.assertEqual(status, 400, out)
        self.assertEqual(self.decide(accepted=["model:entity:Tug", "model:entity:Invented"])[0], 400)


class RuleTests(OriginGate):
    def test_the_modes_and_what_a_configuration_save_records(self):
        self.assertEqual(proposal_review.MODES, ("architect_proposal", "manual_authoring", "derived_revision", "imported_configuration", "legacy_unknown"))
        status, draft = self.save(self.doc(*self.stated[:1]))
        self.assertEqual(status, 200, draft)
        store = self.pf.workspaces["acme"].use_cases["novel"].service.store
        store.save_draft(None, "ada", "configuration only", draft["revision"], solution={"agents": {}})   # what the configuration route does
        carried = store.draft()["provenance"]
        self.assertEqual((carried["mode"], carried["parent"], carried["proposals"], carried["model_changed"], carried["includes_unknown"]),
                         ("derived_revision", {"revision": draft["revision"], "mode": "architect_proposal"}, [{"proposal": self.pid, "revision": 2}], False, False))
        # through the route itself, as a person does
        status, routed = self.call("POST", f"{ENGINE}/solution/draft", body={"solution": {"agents": {}}, "expected_revision": store.draft()["revision"]})
        self.assertEqual((status, self.call("GET", f"{ENGINE}/model/draft")[1]["provenance"]["mode"]), (200, "derived_revision"), routed)
        same = self.save(store.draft()["document"])                                 # the model saved again, unchanged
        self.assertEqual((same[0], same[1]["provenance"]["mode"], same[1]["provenance"]["proposals"]),
                         (200, "derived_revision", [{"proposal": self.pid, "revision": 2}]))

    def test_a_configuration_saved_before_any_model_draft_derives_from_the_model_that_runs(self):
        """The configuration route writes the first draft itself when there is none: the model in it is the active
        one, unchanged. Its provenance is established as that, and another person can publish it."""
        status, out = self.call("POST", f"{WS}/use-cases", body={"id": "plain", "name": "Plain", "template": "blank-solution"})
        self.assertEqual(status, 201, out)
        engine = "/w/acme/u/plain/api/v1"
        self.assertEqual(self.call("GET", f"{engine}/model/draft")[1]["revision"], 0)
        status, out = self.call("POST", f"{engine}/solution/draft", body={"solution": {"agents": {}}, "expected_revision": 0})
        self.assertEqual(status, 200, out)
        found = self.call("GET", f"{engine}/model/draft")[1]["provenance"]
        self.assertEqual((found["mode"], found["parent"], found["includes_unknown"], found["elements"]["authored_by_hand"], found["author"]),
                         ("derived_revision", {"revision": 0, "mode": "active_model"}, False, 0, "ada"))
        publish = "/platform/v1/workspaces/acme/use-cases/plain/publish-draft"
        self.assertEqual(self.call("POST", publish, "acme-ada", {"revision": 1, "reason": "mine"})[0], 403)  # not by its author
        status, out = self.call("POST", publish, "acme-maria", {"revision": 1, "reason": "configuration reviewed"})
        self.assertEqual(status, 200, out)


class ExistingStoreTests(unittest.TestCase):
    def test_a_store_of_the_schema_before_is_upgraded_without_inventing_any_provenance(self):
        """Schema 21 had no ``provenance`` column. Upgrading adds it and writes nothing into the rows that exist:
        they are reported as of unknown provenance. A store already upgraded is refused by the software before."""
        import os
        import sqlite3
        import tempfile

        from autology import migrations
        from autology.store import SCHEMA, SCHEMA_VERSION, Store, StoreError

        path = os.path.join(tempfile.mkdtemp(), "old.db")
        store = Store(path)
        store.save_draft({"name": "x", "version": "0.1.0", "entities": {}}, "ada", "first", 0)
        store.save_draft({"name": "x", "version": "0.2.0", "entities": {}}, "ada", "second", 1,
                         origin={"proposal": "P-1", "revision": 1})
        store.close()
        db = sqlite3.connect(path)          # as schema 21 left it: the column is not there
        db.execute("ALTER TABLE model_drafts DROP COLUMN provenance")
        db.execute("UPDATE meta SET value='21' WHERE key='schema_version'")
        db.execute("DELETE FROM schema_migrations WHERE version=22")
        before = db.execute("SELECT revision, document, author, note, at, solution, origin FROM model_drafts ORDER BY 1").fetchall()
        db.commit()
        db.close()
        upgraded = Store(path)
        self.addCleanup(upgraded.close)
        self.assertEqual((upgraded.migrated, SCHEMA_VERSION), ([22], 22))
        self.assertEqual(migrations.layout_problems(upgraded._db, SCHEMA), [])
        after = upgraded._db.execute("SELECT revision, document, author, note, at, solution, origin, provenance FROM model_drafts ORDER BY 1").fetchall()
        self.assertEqual([tuple(r)[:7] for r in after], [tuple(r) for r in before])       # every earlier value as it was
        self.assertEqual([r["provenance"] for r in after], [None, None])                  # and no provenance invented
        self.assertEqual([h["provenance"] for h in upgraded.draft_history()], [None, None])
        self.assertEqual(upgraded.draft()["origin"], {"proposal": "P-1", "revision": 1})  # an earlier link is kept, not promoted to proof
        # going back: the software before refuses a store it does not know, instead of reading it wrongly
        with mock.patch("autology.store.SCHEMA_VERSION", 21), self.assertRaises(StoreError) as newer:
            Store(path)
        self.assertIn("newer than this Autology", str(newer.exception))
