"""STU-6 (engine side): a Studio draft becomes a governed release, and a release's model can be restored.

  P1 a person with release authority who did not save it publishes a saved, valid draft revision (never its
     author alone: its access rules would change what members read, IAM-3); it becomes the use case's own ontology
     (a file in the use case's data folder; shared configuration files are never written) and the engine reloads
  P2 publishing is a configuration change: with an active release, nothing runs until another person approves a
     release of the published configuration and it is activated
  P3 an invalid draft is never published; only administrators who are people publish
  P4 restoring a release puts its ontology back; when everything else is unchanged the fingerprint matches the
     release again and activating it is recorded as a rollback
"""

import json

from .test_adm1_administration import AdminBase

UC = "/platform/v1/workspaces/acme/use-cases/claims"
ENGINE = "/w/acme/u/claims/api/v1"


class PublishTests(AdminBase):
    def release(self, note):
        status, r = self.call("POST", f"{UC}/releases", body={"note": note})
        self.assertEqual(status, 201, r)
        self.assertEqual(self.call("POST", f"{UC}/releases/{r['number']}/approve", "acme-maria", {"reason": "ok"})[0], 200)
        status, out = self.call("POST", f"{UC}/releases/{r['number']}/activate", body={"reason": "go"})
        self.assertEqual(status, 200, out)
        return r["number"]

    def save_draft(self, change):
        _, draft = self.call("GET", f"{ENGINE}/model/draft")
        doc = json.loads(json.dumps(draft["document"]))
        change(doc)
        status, saved = self.call("POST", f"{ENGINE}/model/draft", body={
            "document": doc, "expected_revision": draft["revision"], "note": "studio edit"})
        self.assertEqual(status, 200, saved)
        return saved["revision"]

    def run_clean_claim(self):
        return self.call("POST", f"{ENGINE}/runs", "acme-hana", {"case_template": "claim_case", "root": "CL-1"})

    def test_publish_release_and_restore(self):  # P1, P2, P4
        first = self.release("as configured")
        shared = (self.config_dir / "ontology.json").read_text()
        revision = self.save_draft(lambda d: d["entities"]["Claim"].__setitem__("description", "A motor claim (v2)"))
        self.assertEqual(self.call("POST", f"{UC}/publish-draft", "acme-hana", {"revision": revision,
                                                                                  "reason": "x"})[0], 403)
        # the person who saved the revision never publishes it herself (IAM-3): another person with authority does
        status, out = self.call("POST", f"{UC}/publish-draft", body={"revision": revision, "reason": "mine"})
        self.assertEqual(status, 403)
        self.assertIn("another person", out["error"]["message"])
        status, view = self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": revision,
                                                                                "reason": "v2 wording"})
        self.assertEqual(status, 200, view)
        self.assertEqual((view["published_revision"], view["release"]["drift"], view["effective_stage"]),
                         (revision, True, "draft"))
        self.assertEqual((self.config_dir / "ontology.json").read_text(), shared)  # shared files untouched
        own = self.pf.data_dir / "acme" / "claims" / "ontology.json"
        self.assertIn("A motor claim (v2)", own.read_text())
        self.assertEqual(self.run_clean_claim()[0], 409)  # nothing runs on an unreleased configuration
        second = self.release("v2 wording")
        # a new model also makes the stage stale: it is simulated again before anything runs (lifecycle rule)
        self.assertEqual(self.run_clean_claim()[0], 409)
        self.assertEqual(self.call("POST", f"{UC}/stage", body={"to": "draft", "reason": "new model"})[0], 200)
        self.assertEqual(self.call("POST", f"{UC}/stage", body={"to": "simulation", "reason": "simulate v2"})[0], 200)
        status, run = self.run_clean_claim()
        self.assertEqual((status, run.get("status")), (200, "completed"), run)
        self.assertEqual(self.call("GET", f"{ENGINE}/model/draft")[1]["document"]["entities"]["Claim"]["description"],
                         "A motor claim (v2)")
        status, back = self.call("POST", f"{UC}/releases/{first}/restore", body={"reason": "back to v1"})
        self.assertEqual(status, 200, back)
        self.assertTrue(back["matches_release"])
        self.assertTrue(back["release"]["drift"])  # release 2 is active; release 1's configuration runs
        status, out = self.call("POST", f"{UC}/releases/{first}/activate", body={"reason": "roll back"})
        self.assertEqual((status, out["event"]), (200, "rolled_back"))
        self.call("POST", f"{UC}/stage", body={"to": "draft", "reason": "rolled back"})
        self.call("POST", f"{UC}/stage", body={"to": "simulation", "reason": "simulate v1 again"})
        self.assertEqual(self.run_clean_claim()[1]["status"], "completed")
        self.assertNotEqual(first, second)
        _, admin = self.call("GET", "/platform/v1/workspaces/acme/members")
        self.assertEqual([e["event"] for e in admin["history"] if e["event"] in ("draft_published", "release_restored")],
                         ["draft_published", "release_restored"])

    def test_an_invalid_draft_is_never_published(self):  # P3
        revision = self.save_draft(lambda d: d["entities"]["Claim"]["attributes"].__setitem__("amount", "currency!"))
        status, out = self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": revision, "reason": "try"})
        self.assertEqual(status, 409)
        self.assertIn("not valid", out["error"]["message"])
        self.assertFalse((self.pf.data_dir / "acme" / "claims" / "ontology.json").exists())
        self.assertEqual(self.call("POST", f"{UC}/publish-draft", body={"revision": 99, "reason": "x"})[0], 404)
        self.assertEqual(self.call("POST", f"{UC}/publish-draft", body={"reason": "x"})[0], 400)
        self.assertEqual(self.call("POST", f"{UC}/releases/9/restore", body={"reason": "x"})[0], 404)


if __name__ == "__main__":
    import unittest

    unittest.main()
