"""Stabilisation C and D: a design session can be left and resumed (GAP-080), and an element keeps the reference to
what it rests on (GAP-081).

P1  every proposal of the use case is listed; a stored proposal is read again, revision by revision; nothing is
    asked of the model, and nothing is paid, to read it
P2  each revision keeps who generated it (provider and exact model), the brief, the answers, the findings and the
    review decisions; an earlier revision is never changed by a later one
P3  a draft records the proposal revision it was saved from; the engine checks the reference and never guesses one
P4  a release leads back to the draft it was published from and to the proposal behind that draft
P5  an element that cites an answer keeps the citation, however the model wrote it; what it cites is canonical;
    what cannot be established is "unknown", never invented
P6  provenance survives the whole path: brief, answers, proposal, validation, review, draft, release
P7  a store from before this change is upgraded; its drafts say nothing about an origin
"""

import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autology import architect
from autology.ai import ProviderReply
from autology.architect import canonical, origin_of
from autology.store import SCHEMA_VERSION, Store

from .test_arch2_ai_provider_governance import EMPTY, ENGINE, MODEL, UC, GovernanceBase

EVIDENCE = {"rationale": "stated", "confidence": 0.8}
ENTITY = {"name": "Vessel", "description": "a ship that calls at the port", "states": ["expected", "berthed"],
          "attributes": [{"name": "length", "type": "number"}], **EVIDENCE}
FIRST = {**EMPTY,
         "entities": [{**ENTITY, "sources": ["brief"], "basis": "supplied"}],
         "questions": [{"id": "volume", "question": "How many vessels call each day?", "why": "sizing"},
                       {"id": "pilot", "question": "Who assigns the pilot?", "why": "authority"}]}
SECOND = {**EMPTY,
          "entities": [
              {**ENTITY, "sources": ["brief"], "basis": "supplied"},
              # cited the way a model cites an answer it was given as {"id": "volume"}: by the bare id (GAP-081)
              {**ENTITY, "name": "Berth", "sources": ["volume"], "basis": "supplied"},
              {**ENTITY, "name": "Pilot", "sources": ["answer:pilot", "brief"], "basis": "supplied"},
              {**ENTITY, "name": "Tug", "sources": [], "basis": "inferred"},
              {**ENTITY, "name": "Crane", "sources": ["a-document-nobody-gave"], "basis": "supplied"},
              {**ENTITY, "name": "Gate", "sources": ["answer:never-asked"], "basis": "supplied"}],
          "assumptions": [{"statement": "about twelve calls a day", "sources": ["volume", "made-up"], "confidence": 0.5}],
          "questions": []}


class LifecycleBase(GovernanceBase):
    def setUp(self):
        super().setUp()
        self.approve_policy()
        self.answers = [FIRST, SECOND]
        real = self.double.invoke

        def invoke(call):
            reply = real(call)
            return ProviderReply(json.dumps(self.answers.pop(0)), reply.stop, reply.usage, reply.model)
        self.double.invoke = invoke

    def session(self):
        """A brief, a proposal with two questions, the answers, a revised proposal: two paid calls."""
        status, first = self.ask(brief="Coordinate vessel berthing at a container port.")
        self.assertEqual(status, 200, first)
        status, second = self.call("POST", f"{ENGINE}/architect/proposals", body={
            "generator": "model", "revises": first["id"],
            "answers": [{"id": "volume", "answer": "About twelve a day"}, {"id": "pilot", "answer": "The harbour master"}],
            "feedback": "Add the berth and the pilot."})
        self.assertEqual(status, 200, second)
        return first, second


class SessionTests(LifecycleBase):
    def test_a_session_is_left_and_resumed_without_asking_the_model_again(self):  # P1, P2
        first, second = self.session()
        paid = len(self.double.calls)
        self.assertEqual(paid, 2)
        self.start()  # the person leaves; the platform is even restarted
        status, listed = self.call("GET", f"{ENGINE}/architect/proposals")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["items"]), 1)
        row = listed["items"][0]
        self.assertEqual((row["id"], row["revisions"], row["revision"], row["items"], row["open_questions"]),
                         (first["id"], 2, 2, 6, 0))
        self.assertEqual((row["generator"], row["provider"], row["model"], row["ai"]), ("model", "double", MODEL, True))
        self.assertEqual((row["spent_usd"], row["drafts"]), (0.4, []))  # what the session already cost
        self.assertTrue(row["brief"].startswith("Coordinate vessel berthing"))

        status, latest = self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}")
        self.assertEqual(status, 200)
        for key in ("revision", "items", "rejected", "questions", "assumptions", "answers", "brief", "provider",
                    "model", "request_id", "validation", "feedback"):
            self.assertEqual(latest[key], second[key], key)  # the revision as it was answered, to the letter
        self.assertEqual(latest["answers"], [{"id": "volume", "answer": "About twelve a day"},
                                             {"id": "pilot", "answer": "The harbour master"}])
        status, earlier = self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}?revision=1")
        self.assertEqual(status, 200)
        self.assertEqual((earlier["revision"], earlier["latest_revision"], earlier["items"], earlier["questions"],
                          earlier["answers"]), (1, 2, first["items"], first["questions"], []))
        self.assertEqual(self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}?revision=7")[0], 404)
        self.assertEqual(len(self.double.calls), paid)  # reading asked the model nothing: nothing more was paid

        history = latest["history"]
        self.assertEqual([(h["revision"], h["items"], h["open_questions"], h["generator"], h["provider"], h["model"],
                           h["cost_usd"], h["created_by"]) for h in history],
                         [(1, 1, 2, "model", "double", MODEL, 0.2, "ada"), (2, 6, 0, "model", "double", MODEL, 0.2, "ada")])
        self.assertEqual((history[0]["feedback"], history[1]["feedback"]), ("", "Add the berth and the pilot."))
        # another workspace's member does not learn that this use case exists, let alone its proposals
        self.assertEqual(self.call("GET", f"{ENGINE}/architect/proposals", "nw-nadia")[0], 404)

    def test_review_decisions_are_kept_per_revision_and_never_rewrite_one(self):  # P2
        first, second = self.session()
        vessel = first["items"][0]["id"]
        status, out = self.call("POST", f"{ENGINE}/architect/proposals/{first['id']}/decision",
                                body={"revision": 1, "accepted": [vessel], "note": "the vessel is right"})
        self.assertEqual(status, 200, out)
        berth = next(i["id"] for i in second["items"] if i["name"] == "Berth")
        tug = next(i["id"] for i in second["items"] if i["name"] == "Tug")
        status, out = self.call("POST", f"{ENGINE}/architect/proposals/{first['id']}/decision",
                                body={"accepted": [berth], "rejected": [tug], "note": "no tug in scope"})
        self.assertEqual(status, 200, out)
        self.start()
        _, read = self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}")
        self.assertEqual([(d["revision"], d["decided_by"], d["accepted"], d["rejected"], d["note"])
                          for d in read["decisions"]],
                         [(1, "ada", [vessel], [], "the vessel is right"), (2, "ada", [berth], [tug], "no tug in scope")])
        _, one = self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}?revision=1")
        self.assertEqual(one["items"], first["items"])
        with self.assertRaises(sqlite3.DatabaseError):  # history is not rewritable, whatever the code does
            store = self.pf.workspaces["acme"].use_cases["novel"].service.store
            store._db.execute("UPDATE architect_proposals SET brief='changed'")


class ProvenanceTests(LifecycleBase):
    def test_canonical_references(self):  # P5
        passages, answers = ["doc-1", "volume-report"], ["volume", "pilot", "doc-1"]
        self.assertEqual(canonical("brief", passages, answers), {"ref": "brief", "kind": "brief"})
        self.assertEqual(canonical("answer:volume", passages, answers), {"ref": "answer:volume", "kind": "answer"})
        self.assertEqual(canonical("volume", passages, answers), {"ref": "answer:volume", "kind": "answer"})
        self.assertEqual(canonical("volume-report", passages, answers), {"ref": "volume-report", "kind": "source"})
        # an id that names both a passage and an answer means the passage, exactly as it was written
        self.assertEqual(canonical("doc-1", passages, answers), {"ref": "doc-1", "kind": "source"})
        self.assertEqual(canonical("answer:doc-1", passages, answers), {"ref": "answer:doc-1", "kind": "answer"})
        for unknown in ("answer:never-asked", "Volume", "the brief", "", "answer:", 7, None):
            self.assertIsNone(canonical(unknown, passages, answers), unknown)
        self.assertEqual(origin_of("supplied", [{"ref": "brief", "kind": "brief"}]), "brief")
        self.assertEqual(origin_of("supplied", [{"ref": "answer:a", "kind": "answer"}]), "answers")
        self.assertEqual(origin_of("supplied", [{"ref": "d", "kind": "source"}]), "sources")
        self.assertEqual(origin_of("supplied", [{"ref": "brief", "kind": "brief"}, {"ref": "d", "kind": "source"}]), "several")
        self.assertEqual(origin_of("supplied", []), "unknown")  # claimed, not established: said, never invented
        self.assertEqual(origin_of("inferred", []), "inference")
        self.assertEqual(origin_of("inferred", [{"ref": "brief", "kind": "brief"}]), "inference")
        self.assertEqual(origin_of(None, []), "inference")

    def test_an_element_keeps_what_it_cites_and_says_unknown_when_nothing_supports_it(self):  # P5
        first, second = self.session()
        by = {i["name"]: i for i in second["items"]}
        self.assertEqual({n: (i["origin"], i["basis"], i["sources"]) for n, i in by.items()}, {
            "Vessel": ("brief", "supplied", ["brief"]),
            "Berth": ("answers", "supplied", ["answer:volume"]),  # before: the citation was dropped, "inferred"
            "Pilot": ("several", "supplied", ["answer:pilot", "brief"]),
            "Tug": ("inference", "inferred", []),
            "Crane": ("unknown", "inferred", []),
            "Gate": ("unknown", "inferred", [])})
        self.assertEqual(by["Berth"]["evidence"], [{"ref": "answer:volume", "kind": "answer"}])
        self.assertEqual(by["Pilot"]["evidence"], [{"ref": "answer:pilot", "kind": "answer"},
                                                   {"ref": "brief", "kind": "brief"}])
        self.assertNotIn("cites a source that was not given", by["Berth"]["attention"])
        for name in ("Crane", "Gate"):
            self.assertIn("cites a source that was not given", by[name]["attention"])
            self.assertIn("presented as supplied, but nothing that was given is cited: treated as inferred",
                          by[name]["attention"])
        self.assertEqual(second["assumptions"][0]["sources"], ["answer:volume"])
        # what a reference points to can be read back: the answer with the question it answered
        self.assertEqual(second["source_index"], {
            "brief": {"kind": "brief", "text": "Coordinate vessel berthing at a container port."},
            "answer:volume": {"kind": "answer", "question": "How many vessels call each day?", "text": "About twelve a day"},
            "answer:pilot": {"kind": "answer", "question": "Who assigns the pilot?", "text": "The harbour master"}})
        self.assertEqual(first["source_index"], {"brief": second["source_index"]["brief"]})
        self.assertEqual(first["items"][0]["origin"], "brief")

    def test_the_model_is_told_how_an_answer_is_cited(self):  # P5
        seen = []
        real = self.double.invoke

        def invoke(call):
            seen.append(call)
            return real(call)
        self.double.invoke = invoke
        self.session()
        self.assertIn('"cite_as": "answer:volume"', seen[1].prompt)
        self.assertIn('"cite_as"', architect.PROMPT)
        self.assertNotIn("cite_as", seen[0].prompt.split("DATA", 1)[1])  # no answer yet: nothing to cite


class DraftAndReleaseTests(LifecycleBase):
    def save(self, document, origin=None, expected=None, token="acme-ada"):
        _, draft = self.call("GET", f"{ENGINE}/model/draft")
        body = {"document": document, "expected_revision": draft["revision"] if expected is None else expected,
                "note": "from the proposal"}
        if origin is not None:
            body["origin"] = origin
        return self.call("POST", f"{ENGINE}/model/draft", token, body)

    def accepted_document(self, proposal):
        """What Studio saves: the active model plus the accepted elements, with their provenance beside them."""
        _, draft = self.call("GET", f"{ENGINE}/model/draft")
        document = copy.deepcopy(draft["document"])
        record = document.setdefault("x-studio", {}).setdefault("provenance", {})
        for item in proposal["items"]:
            if item["name"] in ("Vessel", "Berth", "Tug"):
                document.setdefault("entities", {})[item["name"]] = item["value"]
                record[f"entity:{item['name']}"] = {
                    "proposal": proposal["id"], "revision": proposal["revision"], "generator": proposal["generator"],
                    "ai": proposal["ai"], "provider": proposal["provider"], "model": proposal["model"],
                    "basis": item["basis"], "origin": item["origin"], "evidence": item["evidence"],
                    "accepted_by": "ada"}
        return document

    def test_a_draft_records_the_proposal_it_was_saved_from(self):  # P3
        first, second = self.session()
        document = self.accepted_document(second)
        for bad in ({"proposal": "P-nothing", "revision": 1}, {"proposal": first["id"], "revision": 9},
                    {"proposal": first["id"]}, {"proposal": first["id"], "revision": True},
                    {"proposal": first["id"], "revision": 2, "note": "extra"}, "P-1"):
            status, out = self.save(document, bad)
            self.assertEqual(status, 400, bad)
        status, draft = self.save(document, {"proposal": first["id"], "revision": 2})
        self.assertEqual(status, 200, draft)
        self.assertEqual((draft["revision"], draft["origin"]), (1, {"proposal": first["id"], "revision": 2}))
        _, read = self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}")
        self.assertEqual([(d["draft_revision"], d["proposal_revision"], d["saved_by"]) for d in read["drafts"]],
                         [(1, 2, "ada")])
        _, listed = self.call("GET", f"{ENGINE}/architect/proposals")
        self.assertEqual(listed["items"][0]["drafts"], [1])
        # the same model saved again (agents were configured meanwhile) is still that proposal's
        store = self.pf.workspaces["acme"].use_cases["novel"].service.store
        store.save_draft(None, "ada", "agents added", 1, solution={"agents": {}})
        self.assertEqual(store.draft()["origin"], {"proposal": first["id"], "revision": 2})
        # a model changed by hand, with no proposal named, has no recorded origin: unknown, not inherited
        changed = copy.deepcopy(document)
        changed["entities"]["Quay"] = changed["entities"]["Berth"]
        status, third = self.save(changed)
        self.assertEqual((status, third["revision"], third["origin"]), (200, 3, None))
        _, history = self.call("GET", f"{ENGINE}/model/draft/history")
        self.assertEqual([h["origin"] for h in history["items"]],
                         [{"proposal": first["id"], "revision": 2}, {"proposal": first["id"], "revision": 2}, None])
        _, read = self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}")
        self.assertEqual([d["draft_revision"] for d in read["drafts"]], [1, 2])

    def test_provenance_survives_from_the_brief_to_the_release(self):  # P4, P6
        first, second = self.session()
        berth = next(i for i in second["items"] if i["name"] == "Berth")
        self.call("POST", f"{ENGINE}/architect/proposals/{first['id']}/decision",
                  body={"accepted": [berth["id"]], "note": "confirmed with the harbour master"})
        status, draft = self.save(self.accepted_document(second), {"proposal": first["id"], "revision": 2})
        self.assertEqual(status, 200, draft)
        self.assertTrue(draft["validation"]["valid"], draft["validation"])  # the engine's check, on the saved model
        status, view = self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": 1, "reason": "reviewed"})
        self.assertEqual(status, 200, view)
        status, release = self.call("POST", f"{UC}/releases", body={"note": "first model from the architect"})
        self.assertEqual(status, 201, release)
        status, shown = self.call("GET", f"{UC}/releases/{release['number']}")
        self.assertEqual(status, 200, shown)
        design = shown["design"]
        self.assertEqual((design["draft_revision"], design["proposal"], design["published_by"]),
                         (1, {"proposal": first["id"], "revision": 2}, "maria@acme"))
        _, listed = self.call("GET", f"{UC}/releases")
        self.assertEqual(listed["items"][0]["design"]["proposal"], {"proposal": first["id"], "revision": 2})
        # the released model itself carries, element by element, what it rests on
        kept = shown["snapshot"]["ontology"]["x-studio"]["provenance"]
        self.assertEqual((kept["entity:Berth"]["origin"], kept["entity:Berth"]["evidence"], kept["entity:Berth"]["model"]),
                         ("answers", [{"ref": "answer:volume", "kind": "answer"}], MODEL))
        self.assertEqual((kept["entity:Tug"]["origin"], kept["entity:Tug"]["basis"]), ("inference", "inferred"))
        # and from the release one reads back, without asking any model, why the berth was proposed
        _, read = self.call("GET", f"{ENGINE}/architect/proposals/{design['proposal']['proposal']}"
                                   f"?revision={design['proposal']['revision']}")
        why = next(i for i in read["items"] if i["name"] == "Berth")
        self.assertEqual(read["source_index"][why["evidence"][0]["ref"]]["text"], "About twelve a day")
        self.assertEqual(read["decisions"][0]["accepted"], [berth["id"]])
        self.assertEqual(len(self.double.calls), 2)
        # a configuration nobody published from a draft says so: no design is recorded, none is made up
        claims = self.call("GET", "/platform/v1/workspaces/acme/use-cases/claims/releases")[1]
        self.assertTrue(all(item["design"] is None for item in claims["items"]))


class MigrationTests(unittest.TestCase):
    def test_a_store_from_before_is_upgraded_and_says_nothing_about_origins(self):  # P7
        path = Path(tempfile.mkdtemp()) / "store.db"
        store = Store(str(path))
        store.save_draft({"name": "m", "version": "0.1.0"}, "ada", "first", 0)
        store.close()
        db = sqlite3.connect(path)  # back to the layout of schema 18: no origin column
        db.executescript("DROP TRIGGER model_drafts_no_update; DROP TRIGGER model_drafts_no_delete;"
                         "CREATE TABLE old AS SELECT revision, document, author, note, at, solution FROM model_drafts;"
                         "DROP TABLE model_drafts;"
                         "CREATE TABLE model_drafts (revision INTEGER PRIMARY KEY, document TEXT NOT NULL, author TEXT "
                         "NOT NULL, note TEXT NOT NULL, at TEXT NOT NULL, solution TEXT);"
                         "INSERT INTO model_drafts SELECT * FROM old; DROP TABLE old;"
                         "UPDATE meta SET value='18' WHERE key='schema_version';"
                         "DELETE FROM schema_migrations WHERE version=19;")
        db.commit()
        db.close()
        store = Store(str(path))
        self.addCleanup(store.close)
        self.assertEqual((store.migrated, SCHEMA_VERSION), ([19, 20], 20))  # 20: application design drafts, a new table
        self.assertEqual((store.draft()["origin"], store.draft_history()[0]["origin"], store.drafts_from("P-1")),
                         (None, None, []))
        store.save_draft({"name": "m", "version": "0.2.0"}, "ada", "second", 1, origin={"proposal": "P-1", "revision": 3})
        self.assertEqual(store.drafts_from("P-1"), [{"draft_revision": 2, "proposal_revision": 3, "saved_by": "ada",
                                                     "at": store.draft()["at"]}])
        with self.assertRaises(sqlite3.DatabaseError):
            store._db.execute("UPDATE model_drafts SET origin=NULL")


if __name__ == "__main__":
    unittest.main()
