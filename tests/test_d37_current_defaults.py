"""D37 c and d are the owner's to decide. Until then the defaults of 19 November stay as they are, and two of their
limits are pinned here so that no document can claim more than the Engine does.

  L1 an unconfirmed proposal element copied under another name is saved as the author's own, with no flag: the
     Engine compares identity and content, and cannot know where retyped or renamed content comes from (GAP-109)
  L2 the second person who publishes a draft is shown its revision number and its author, and nothing of its
     provenance record: showing the flags at publication (D37 d, option 3) is not built
  L3 a legacy draft is re-established by saving it again, with no acknowledgement of any kind asked (D37 c, option 1)
"""

from .test_arch2_ai_provider_governance import ENGINE, UC
from .test_gap107_draft_origin import OriginGate


class CurrentDefaultTests(OriginGate):
    def test_a_copy_under_another_name_is_not_detected(self):  # L1
        tug = self.items["Tug"]                                   # inferred, and nobody confirmed it
        refused = self.save(self.doc("Tug"))
        self.assertEqual(refused[0], 409, refused)                # under its own name and content: found, with or without an origin
        renamed = self.doc()
        renamed.setdefault("entities", {})["Towboat"] = tug["value"]
        status, draft = self.save(renamed)
        self.assertEqual(status, 200, draft)
        found = draft["provenance"]
        self.assertEqual((found["mode"], found["authored"], found["flags"], found["proposals"]), ("manual_authoring", ["entity:Towboat"], [], []))
        self.assertIn("copied from outside Autology", found["cannot_prove"])   # the record says what it cannot establish

    def test_the_publisher_sees_the_revision_and_its_author_and_nothing_of_the_provenance(self):  # L2
        own = {**self.items["Tug"]["value"], "description": "My own wording"}
        status, flagged = self.save({**self.base, "entities": {**self.base.get("entities", {}), "Tug": own}})
        self.assertEqual((status, len(flagged["provenance"]["flags"])), (200, 1), flagged)
        status, shown = self.call("GET", f"{UC}/releases", "acme-maria")
        self.assertEqual((status, shown["draft"]), (200, {"revision": flagged["revision"], "author": "ada"}), shown)
        self.assertEqual(self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": flagged["revision"], "reason": "reviewed"})[0], 200)

    def test_a_legacy_draft_is_re_established_without_any_acknowledgement(self):  # L3
        store = self.pf.workspaces["acme"].use_cases["novel"].service.store
        legacy = {**self.base, "entities": {**self.base.get("entities", {}), "Quay": {"description": "A quay", "states": ["free"], "attributes": {"name": "string"}}}}
        store.save_draft(legacy, "someone", "written before the engine classified drafts", store.draft()["revision"] if store.draft() else 0)
        row = self.call("GET", f"{ENGINE}/model/draft")[1]
        self.assertEqual(row["provenance"]["mode"], "legacy_unknown")
        self.assertEqual(self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": row["revision"], "reason": "x"})[0], 409)
        status, again = self.save(legacy)
        self.assertEqual((status, again["provenance"]["reestablished_from_legacy"], again["provenance"]["author"]), (200, True, "ada"), again)
        self.assertNotIn("acknowledg", str(again["provenance"]).lower())   # nobody was asked to acknowledge anything
