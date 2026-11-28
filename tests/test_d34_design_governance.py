"""D34, governed application designs: the proposed lifecycle, tested without being in force (invented fixtures).

  G1 nothing that runs uses the proposal; in force a design is still a draft that no release contains
  G2 the owner's four choices have no default: a missing one is refused
  G3 the record of a design names everything a reviewer and an auditor need, and grants nothing
  G4 the whole path, under each way of approving, ends in a design shown in simulation, with its audit trail
  G5 what is refused whatever the choices: a step out of order, the author's own approval, a service identity,
     a design changed after it was submitted, a release that is not approved, that its proposer approved, or that
     is for something else; production; a release that is not the active one
  G6 suspension, resumption and revocation
  G7 a rollback shows the design of the release it restores, or nothing
  G8 existing drafts become records of the lifecycle: all of them, as drafts, none approved
"""

import json
import unittest
from pathlib import Path

from autology import applications, design_governance
from autology.design_governance import Refused, advance, artifact, digest, migrate, needs_new_release, policy, release_structure, served

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = {"manifest_version": 1, "id": "work-desk", "title": "Work desk",
            "binding": {"model": "work@0.1.0", "model_fingerprint": "m" * 64, "configuration": "c" * 64, "engine_api": "1",
                        "workspace": "w1", "use_case": "u1"},
            "roles": [], "navigation": [], "views": [], "unavailable": [], "presentation": {"accent": "blue", "density": "comfortable"}}
WITH = policy(approval="with_release", reviewer="release_approver", versioning="new_release", suspension="one_administrator")
APART = policy(approval="separate", reviewer="design_reviewer", versioning="design_revision", suspension="two_people")
ENGINE = {"kind": "engine"}
ADA = {"name": "ada", "kind": "person", "offices": ["administrator"]}
BO = {"name": "bo", "kind": "person", "offices": ["release_approver"]}
DEE = {"name": "dee", "kind": "person", "offices": ["design_reviewer"]}
BOT = {"name": "bot", "kind": "service", "offices": ["release_approver", "design_reviewer", "administrator"]}
T = "2026-11-17T10:00:00+00:00"


def release(number=1, **more):
    return {"number": number, "fingerprint": f"r{number}" * 16, "proposed_by": "ada", "approved_by": "bo",
            "configuration": "c" * 64, "model_fingerprint": "m" * 64, "parts": {"application": digest(MANIFEST)}, **more}


def path(rules, *events, design=None):
    """Advance a design through ``events``: names, or (name, actor, context)."""
    design = design or artifact(MANIFEST, 1, "ada", T, {"list-thing": "read"})
    defaults = {"validate": (ENGINE, {"check": {"valid": True, "digest": design["version"]["digest"]}}), "submit": (ADA, {}),
                "approve": (BO if rules["approval"] == "with_release" else DEE, {"release": release()}),
                "bind": (ADA, {"release": release()}),
                "simulate": (ADA, {"release_active": True, "active_release": 1, "stage": "simulation"}),
                "activate": (ADA, {"release_active": True, "active_release": 1, "stage": "pilot"})}
    for event in events:
        name, actor, context = (event, *defaults[event]) if isinstance(event, str) else event
        design = advance(design, name, actor, rules, T, context)
    return design


class NotInForceTests(unittest.TestCase):
    def test_nothing_that_runs_uses_the_proposal(self):  # G1
        package = ROOT / "autology"
        users = [p.name for p in package.glob("*.py")
                 if p.name != "design_governance.py" and "design_governance" in p.read_text(encoding="utf-8")]
        self.assertEqual(users, [])
        self.assertIn("not in force", design_governance.POLICY)
        self.assertIn("**not in force**", design_governance.__doc__)
        source = (package / "applications.py").read_text(encoding="utf-8")
        self.assertIn('"approved_release_artifact": {"supported": False, "value": False', source.replace("\n", " ").replace("  ", ""))
        self.assertEqual(applications.HEADER, "X-Autology-Configuration")
        self.assertFalse(artifact(MANIFEST, 1, "ada", T)["in_force"])

    def test_the_owners_choices_have_no_default(self):  # G2
        self.assertEqual(sorted(design_governance.OPTIONS), ["approval", "reviewer", "suspension", "versioning"])
        for missing in design_governance.OPTIONS:
            with self.assertRaisesRegex(Refused, "must be chosen by the owner"):
                policy(**{k: v for k, v in WITH.items() if k != missing})
        with self.assertRaisesRegex(Refused, "must be chosen"):
            policy(**{**WITH, "approval": "automatic"})
        with self.assertRaisesRegex(Refused, "unknown choice"):
            policy(**WITH, self_approval="yes")
        with self.assertRaisesRegex(Refused, "must be chosen"):
            advance(artifact(MANIFEST, 1, "ada", T), "submit", ADA, {}, T)
        self.assertEqual((needs_new_release(WITH), needs_new_release(APART),
                          needs_new_release({**APART, "versioning": "new_release"})), (True, False, True))


class RecordTests(unittest.TestCase):
    def test_the_record_names_what_a_reviewer_needs_and_grants_nothing(self):  # G3
        record = artifact(MANIFEST, 3, "ada", T, {"list-thing": "read", "inbox": "review"})
        self.assertEqual(sorted(record), sorted([
            "manifest_id", "version", "workspace", "use_case", "ontology_fingerprint", "configuration_fingerprint", "author",
            "reviewers", "approval", "release", "effective_permissions", "compatible_runtime", "audit", "rollback", "state",
            "policy", "in_force"]))
        self.assertEqual((record["manifest_id"], record["version"], record["workspace"], record["use_case"]),
                         ("work-desk", {"design_revision": 3, "digest": digest(MANIFEST)}, "w1", "u1"))
        self.assertEqual((record["ontology_fingerprint"], record["configuration_fingerprint"]), ("m" * 64, "c" * 64))
        self.assertEqual(record["compatible_runtime"], {"manifest_version": 1, "engine_api": "1"})
        self.assertEqual(record["approval"]["status"], "none")
        self.assertEqual(record["effective_permissions"], {"granted_by_this_design": [], "needed_to_use": {"list-thing": "read", "inbox": "review"}})
        for rules in (WITH, APART):  # at every step of the path, a design still grants nothing
            design = artifact(MANIFEST, 1, "ada", T)
            for event in ("validate", "submit", "approve", "bind", "simulate", "activate"):
                design = path(rules, event, design=design)
                self.assertEqual(design["effective_permissions"]["granted_by_this_design"], [], event)
        self.assertEqual(digest(MANIFEST), digest(json.loads(json.dumps(MANIFEST))))


class PathTests(unittest.TestCase):
    def test_the_whole_path_under_each_way_of_approving(self):  # G4
        for rules, approver in ((WITH, "bo"), (APART, "dee")):
            design = path(rules, "validate", "submit", "approve", "bind", "simulate")
            self.assertEqual((design["state"], design["approval"]["status"], design["approval"]["by"], design["reviewers"]),
                             ("simulation", "approved", approver, [approver]))
            self.assertEqual(design["release"], {"number": 1, "fingerprint": "r1" * 16, "approved_by": "bo"})
            self.assertEqual([(e["event"], e["from"], e["to"]) for e in design["audit"]], [
                ("created", None, "draft"), ("validate", "draft", "validated"), ("submit", "validated", "in_review"),
                ("approve", "in_review", "approved"), ("bind", "approved", "bound"), ("simulate", "bound", "simulation")])
            self.assertEqual(path(rules, "activate", design=design)["state"], "active")
        # the input is never modified: every step returns a new record
        first = artifact(MANIFEST, 1, "ada", T)
        path(WITH, "validate", design=first)
        self.assertEqual(first["state"], "draft")

    def refused(self, text, rules, *events, design=None):
        with self.assertRaisesRegex(Refused, text):
            path(rules, *events, design=design)

    def test_what_is_refused_whatever_the_choices(self):  # G5
        for rules in (WITH, APART):
            # out of order
            self.refused("not possible from draft", rules, "submit")
            self.refused("not possible from draft", rules, "approve")
            self.refused("not possible from validated", rules, "validate", "bind")
            self.refused("not possible from approved", rules, "validate", "submit", "approve", "simulate")
            self.refused("not possible from bound", rules, "validate", "submit", "approve", "bind", "activate")
            self.refused("unknown step", rules, ("publish", ADA, {}))
            # validation is the Engine's, of this exact design
            self.refused("only the Engine", rules, ("validate", ADA, {"check": {"valid": True, "digest": digest(MANIFEST)}}))
            self.refused("only the Engine", rules, ("validate", ENGINE, {"check": {"valid": False, "digest": digest(MANIFEST)}}))
            self.refused("only the Engine", rules, ("validate", ENGINE, {"check": {"valid": True, "digest": "other"}}))
            # who
            self.refused("submitted by its author", rules, "validate", ("submit", BO, {}))
            self.refused("only a person", rules, "validate", ("submit", BOT, {}))
            self.refused("nobody decides on their own design", rules, "validate", "submit", ("approve", ADA, {"release": release()}))
            self.refused("only a person", rules, "validate", "submit", ("approve", BOT, {"release": release(approved_by="bot")}))
            # a design changed after it was submitted starts again, and its approval is gone
            changed = path(rules, "validate", "submit", "approve", ("change", ADA, {"digest": "d2"}))
            self.assertEqual((changed["state"], changed["approval"]["status"], changed["version"]), ("draft", "none", {"design_revision": 2, "digest": "d2"}))
            self.refused("not possible from draft", rules, "bind", design=changed)
            self.refused("not possible from bound", rules, "validate", "submit", "approve", "bind", ("change", ADA, {"digest": "d2"}))
            # the release
            approved = path(rules, "validate", "submit", "approve")
            for bad, text in (({"approved_by": None}, "not approved"), ({"approved_by": "ada"}, "approved by its proposer"),
                              ({"configuration": "x" * 64}, "another model or configuration"),
                              ({"model_fingerprint": "x" * 64}, "another model or configuration")):
                self.refused(text, rules, ("bind", ADA, {"release": release(**bad)}), design=approved)
            self.refused("not approved", rules, ("bind", ADA, {}), design=approved)
            for scope, text in (("workspace", "another workspace"), ("use_case", "another use case")):   # a foreign release
                self.refused(text, rules, ("bind", ADA, {"release": release(**{scope: "elsewhere"})}), design=approved)
            self.assertEqual(path(rules, ("bind", ADA, {"release": release(workspace="w1", use_case="u1")}), design=approved)["state"], "bound")
            swapped = {**approved, "version": {"design_revision": 1, "digest": "swapped-after-approval"}}  # edited behind the lifecycle
            self.refused("approval is of another version", rules, "bind", design=swapped)
            # stage and activation
            bound = path(rules, "bind", design=approved)
            self.refused("production execution is disabled", rules, ("simulate", ADA, {"release_active": True, "active_release": 1, "stage": "production"}), design=bound)
            self.refused("not the active one", rules, ("simulate", ADA, {"release_active": True, "active_release": 2, "stage": "simulation"}), design=bound)
            self.refused("not the active one", rules, ("simulate", ADA, {"release_active": False, "active_release": 1, "stage": "simulation"}), design=bound)
            self.refused("not possible in the stage draft", rules, ("simulate", ADA, {"release_active": True, "active_release": 1, "stage": "draft"}), design=bound)
            shown = path(rules, "simulate", design=bound)
            self.refused("production execution is disabled", rules, ("activate", ADA, {"release_active": True, "active_release": 1, "stage": "production"}), design=shown)
        # particular to each way of approving
        self.refused("does not contain this design", WITH, "validate", "submit", ("approve", BO, {"release": release(parts={"application": "other"})}))
        self.refused("approved by the approver of the release", WITH, "validate", "submit", ("approve", DEE, {"release": release()}))
        self.refused("needs the office of design reviewer", APART, "validate", "submit", ("approve", BO, {}))
        rejected = path(APART, "validate", "submit", ("reject", DEE, {"reason": "labels"}))
        self.assertEqual((rejected["state"], rejected["reviewers"], rejected["audit"][-1]["reason"]), ("draft", ["dee"], "labels"))

    def test_suspension_resumption_and_revocation(self):  # G6
        shown = path(WITH, "validate", "submit", "approve", "bind", "simulate")
        self.refused("administrator", WITH, ("suspend", BO, {}), design=shown)
        self.refused("only a person", WITH, ("suspend", BOT, {}), design=shown)
        self.refused("not possible from validated", WITH, "validate", ("suspend", ADA, {}))
        held = path(WITH, ("suspend", ADA, {"reason": "wrong label"}), design=shown)
        self.assertEqual((held["state"], served([held], 1)), ("suspended", None))
        self.refused("second person", APART, ("suspend", ADA, {}), design=shown)
        self.refused("second person", APART, ("suspend", ADA, {"second": "ada"}), design=shown)
        self.assertEqual(path(APART, ("suspend", ADA, {"second": "bo"}), design=shown)["state"], "suspended")
        for rules in (WITH, APART):  # widening again, and revoking, take two people whatever was chosen
            self.refused("nobody may resume a design alone", rules, ("resume", ADA, {}), design=held)
            self.refused("nobody may resume a design alone", rules, ("resume", ADA, {"second": ADA}), design=held)
            self.refused("nobody may resume a design alone", rules, ("resume", ADA, {"second": BOT}), design=held)
            self.refused("not possible from simulation", rules, ("resume", ADA, {"second": BO}), design=shown)
            self.assertEqual(path(rules, ("resume", ADA, {"second": BO}), design=held)["state"], "simulation")
            self.refused("nobody may revoke a design alone", rules, ("revoke", ADA, {}), design=shown)
            gone = path(rules, ("revoke", ADA, {"second": BO, "reason": "withdrawn"}), design=shown)
            self.assertEqual((gone["state"], gone["audit"][-1]["second"], served([gone], 1)), ("revoked", "bo", None))
            for event in ("resume", "simulate", "bind", "change", "revoke"):
                self.refused("revoked: nothing follows", rules, (event, ADA, {"second": BO, "digest": "x"}), design=gone)
        over = path(WITH, "activate", ("supersede", ENGINE, {"release": 2}), design=shown)
        self.assertEqual(over["state"], "superseded")
        self.refused("superseded: nothing follows", WITH, ("suspend", ADA, {}), design=over)


class RollbackAndMigrationTests(unittest.TestCase):
    def test_a_rollback_shows_the_design_of_the_release_it_restores_or_nothing(self):  # G7
        one = path(WITH, "validate", "submit", "approve", "bind", "simulate")
        second = {**MANIFEST, "title": "Work desk, second"}
        two = artifact(second, 2, "ada", T)
        rel2 = release(2, parts={"application": digest(second)})
        two = path(WITH, "validate", "submit", ("approve", BO, {"release": rel2}), ("bind", ADA, {"release": rel2}),
                   ("simulate", ADA, {"release_active": True, "active_release": 2, "stage": "simulation"}), design=two)
        self.assertEqual(served([one, two], 2)["version"]["design_revision"], 2)
        self.assertEqual(served([one, two], 1)["version"]["design_revision"], 1)   # rolled back: the older design, never the newer
        self.assertIsNone(served([one, two], 3))                                    # a release with no design: nothing is shown
        self.assertIsNone(served([one, two], None))
        draft = artifact(MANIFEST, 3, "ada", T)
        self.assertIsNone(served([draft], 1))                                       # a draft is never shown as governed
        self.assertIn("never shown", one["rollback"])

    def test_existing_drafts_become_records_all_as_drafts(self):  # G8
        rows = [{"revision": 2, "manifest": {**MANIFEST, "title": "Second"}, "author": "bo", "at": T, "note": "again", "configuration": "c" * 64},
                {"revision": 1, "manifest": MANIFEST, "author": "ada", "at": T, "note": "first", "configuration": "c" * 64}]
        records = migrate(rows)
        self.assertEqual([(r["version"]["design_revision"], r["author"], r["state"], r["approval"]["status"], r["release"]) for r in records],
                         [(1, "ada", "draft", "none", None), (2, "bo", "draft", "none", None)])
        self.assertEqual([r["audit"] for r in records][0], [{"event": "migrated", "by": "ada", "at": T, "from": None, "to": "draft", "note": "first"}])
        self.assertEqual(migrate([]), [])
        self.assertIsNone(served(records, 1))


class ReleaseStructureTests(unittest.TestCase):
    """A release with a design as one of its parts (directive D1): a structure for review, computed and not in force."""
    SNAPSHOT = {"ontology": {"name": "work", "version": "0.1.0", "entities": {"Ticket": {}}, "rules": [{"id": "R-1"}]},
                "solution": {"agents": {"a": {}}}, "ai": None}

    def bound(self, **more):
        from autology.releases import fingerprint_of

        return {**MANIFEST, "binding": {**MANIFEST["binding"], "configuration": fingerprint_of(self.SNAPSHOT)}, **more}

    def test_a_release_without_a_design_is_the_release_it_is_today(self):
        from autology.releases import fingerprint_of

        plain = release_structure(self.SNAPSHOT)
        self.assertEqual((plain["fingerprint"], plain["same_as_today"]), (fingerprint_of(self.SNAPSHOT), True))
        self.assertEqual((plain["parts"]["application"], plain["parts"]["runtime"], plain["in_force"]), (None, None, False))
        self.assertEqual(sorted(plain["parts"]), sorted(design_governance.RELEASE_PARTS))
        self.assertTrue(all(plain["parts"][k] for k in ("ontology", "rules", "agents")))

    def test_the_combined_fingerprint_covers_the_design_and_each_part_has_its_own(self):
        one, same = release_structure(self.SNAPSHOT, self.bound()), release_structure(self.SNAPSHOT, self.bound())
        relabelled = release_structure(self.SNAPSHOT, self.bound(title="Work desk, renamed"))
        self.assertEqual(one["fingerprint"], same["fingerprint"])                 # deterministic
        self.assertNotEqual(one["fingerprint"], release_structure(self.SNAPSHOT)["fingerprint"])
        self.assertNotEqual(one["fingerprint"], relabelled["fingerprint"])        # a label change is a change of the release
        self.assertNotEqual(one["parts"]["application"], relabelled["parts"]["application"])
        for unchanged in ("ontology", "rules", "agents", "runtime"):               # and of no other part
            self.assertEqual(one["parts"][unchanged], relabelled["parts"][unchanged], unchanged)
        other_rules = {**self.SNAPSHOT, "ontology": {**self.SNAPSHOT["ontology"], "rules": [{"id": "R-2"}]}}
        changed = release_structure(other_rules, self.bound())
        self.assertNotEqual(changed["parts"]["rules"], one["parts"]["rules"])
        self.assertEqual(changed["parts"]["ontology"], one["parts"]["ontology"])
        self.assertEqual(changed["problems"], ["the design is bound to another configuration than this release's"])

    def test_approval_evidence_is_carried_and_checked_not_created(self):
        ok = release_structure(self.SNAPSHOT, self.bound(), {"proposed_by": "ada", "approved_by": "bo", "at": T, "audit": ["admin-log:41", "admin-log:42"]})
        self.assertEqual((ok["approval"], ok["audit"], ok["problems"]),
                         ({"proposed_by": "ada", "approved_by": "bo", "at": T}, ["admin-log:41", "admin-log:42"], []))
        own = release_structure(self.SNAPSHOT, self.bound(), {"proposed_by": "ada", "approved_by": "ada"})
        self.assertEqual(own["problems"], ["the release was approved by its proposer"])
        none = release_structure(self.SNAPSHOT, self.bound())
        self.assertEqual(none["approval"], {"proposed_by": None, "approved_by": None, "at": None})  # nothing is filled in

    def test_rollback_and_versioning_as_they_would_work(self):
        # release 1 without a design, release 2 with one, release 3 with a relabelled one: three identities
        r1, r2 = release_structure(self.SNAPSHOT), release_structure(self.SNAPSHOT, self.bound())
        r3 = release_structure(self.SNAPSHOT, self.bound(title="Second"))
        self.assertEqual(len({r1["fingerprint"], r2["fingerprint"], r3["fingerprint"]}), 3)
        self.assertTrue(needs_new_release(WITH))
        # rolling back to release 2 restores exactly its design: the fingerprint says which
        self.assertEqual(release_structure(self.SNAPSHOT, self.bound())["parts"]["application"], r2["parts"]["application"])
        # rolling back to release 1 restores a release with no design: nothing is shown as governed
        self.assertIsNone(served([], 1))

