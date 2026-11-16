"""Activation sprint, increment B: the executable configuration is part of the governed release.

  R1 a release names what it contains, part by part (model, rules, actions, workflows, agents, tools, governing
     settings), each with a fingerprint, and can be verified from its own snapshot
  R2 a draft never alters what runs; a published change is a configuration change: with an active release nothing
     runs until a release of it is approved by another person and activated
  R3 references are validated before anything is put in place: a configuration that no longer fits its model is
     not published; a release that could not execute is not activated
  R4 separation of duties holds for configurations too: the author does not publish, the proposer does not approve
  R5 activation is all or nothing: if it fails, the model, the agent configuration and the engine are put back
  R6 a rollback restores the previous release's model and agents together, including "no agent"
  R7 every activation, refusal and rollback leaves evidence
  R8 an operator's agents (files) are never replaced by a Studio configuration; another workspace sees nothing
"""

import copy
import json

from autology import solution
from autology.platform import ONTOLOGY_OVERRIDE, SOLUTION_OVERRIDE
from autology.releases import fingerprint_of

from .test_act1_solution_configuration import good
from .test_adm1_administration import AdminBase
from .test_onb1_draft_simulation import proposed_model

WS = "/platform/v1/workspaces/acme"
UC = f"{WS}/use-cases/desk"
ENGINE = "/w/acme/u/desk/api/v1"


class ReleaseBase(AdminBase):
    def setUp(self):
        super().setUp()
        status, out = self.call("POST", f"{WS}/use-cases", body={"id": "desk", "name": "Service desk",
                                                                  "template": "blank-solution"})
        self.assertEqual(status, 201, out)
        self.home = self.pf.data_dir / "acme" / "desk"

    @property
    def desk(self):
        return self.pf.workspaces["acme"].use_cases["desk"].service

    def draft(self, document=None, configuration="keep"):
        """Save the model and/or the configuration as ada; the last revision saved."""
        revision = self.call("GET", f"{ENGINE}/solution/draft")[1]["revision"]
        if document is not None:
            status, out = self.call("POST", f"{ENGINE}/model/draft", body={"document": document,
                                                                           "expected_revision": revision, "note": "model"})
            self.assertEqual(status, 200, out)
            revision = out["revision"]
        if configuration != "keep":
            status, out = self.call("POST", f"{ENGINE}/solution/draft", body={"solution": configuration,
                                                                              "expected_revision": revision})
            self.assertEqual(status, 200, out)
            revision = out["revision"]
        return revision

    def publish(self, revision, token="acme-maria"):
        return self.call("POST", f"{UC}/publish-draft", token, {"revision": revision, "reason": "reviewed"})

    def propose(self, note="release"):
        status, r = self.call("POST", f"{UC}/releases", body={"note": note})
        self.assertEqual(status, 201, r)
        return r["number"]

    def approve(self, number, token="acme-maria"):
        return self.call("POST", f"{UC}/releases/{number}/approve", token, {"reason": "checked"})

    def activate(self, number, reason="go"):
        return self.call("POST", f"{UC}/releases/{number}/activate", body={"reason": reason})

    def released(self, document=None, configuration="keep", note="release"):
        """Draft → published by maria → proposed by ada → approved by maria → activated by ada."""
        status, out = self.publish(self.draft(document, configuration))
        self.assertEqual(status, 200, out)
        number = self.propose(note)
        self.assertEqual(self.approve(number)[0], 200)
        status, out = self.activate(number)
        self.assertEqual(status, 200, out)
        return number

    def admin_events(self, *names):
        return [e for e in self.call("GET", f"{WS}/members")[1]["history"] if e["event"] in names]


class ReleaseContentTests(ReleaseBase):
    def test_a_release_names_its_parts_and_verifies_from_its_own_snapshot(self):  # R1
        number = self.released(proposed_model(), good())
        self.assertEqual(sorted(self.desk.agents), ["request_handler"])
        status, release = self.call("GET", f"{UC}/releases/{number}")
        self.assertEqual(status, 200)
        parts = release["components"]
        self.assertEqual(sorted(parts), ["actions", "agents", "governance", "model", "rules", "tools", "workflows"])
        self.assertEqual((parts["agents"]["names"], parts["agents"]["managed"]), (["request_handler"], "studio"))
        self.assertEqual((parts["tools"]["count"], parts["tools"]["all_simulated"], parts["tools"]["other"]), (5, True, 0))
        self.assertEqual((parts["actions"]["count"], parts["workflows"]["goals"]), (6, ["request_closed"]))
        self.assertEqual(release["verification"], {"fingerprint_matches": True, "coherent": True, "problems": [],
                                                   "by": "the engine, from the release's own snapshot"})
        snapshot = release["snapshot"]
        self.assertEqual(fingerprint_of(snapshot), release["fingerprint"])  # anyone holding it can recompute it
        self.assertEqual(snapshot["settings"]["solution"], good())
        self.assertEqual(snapshot["settings"]["agents"], solution.compile_solution(good(), proposed_model())["agents"])
        self.assertTrue(all(t["type"] == "table" for t in snapshot["tools"]["request_handler"]["tools"]))
        # a member without release authority sees the parts and the verdict, never the snapshot itself
        token = self.add("zoe")
        status, limited = self.c.call("GET", f"{UC}/releases/{number}", token)
        self.assertIn(status, (200, 404))
        if status == 200:
            self.assertNotIn("snapshot", limited)

    def test_two_releases_share_exactly_the_parts_that_did_not_change(self):  # R1
        first = self.released(proposed_model(), good())
        second = self.released(None, good(autonomy={"mode": "supervised", "reviewer": "manager"}), "supervised")
        a = self.call("GET", f"{UC}/releases/{first}")[1]["components"]
        b = self.call("GET", f"{UC}/releases/{second}")[1]["components"]
        same = sorted(k for k in a if a[k]["fingerprint"] == b[k]["fingerprint"])
        self.assertEqual(same, ["actions", "governance", "model", "rules", "tools", "workflows"])
        self.assertNotEqual(a["agents"]["fingerprint"], b["agents"]["fingerprint"])

    def test_coherence_is_computed_from_the_snapshot_alone(self):  # R1, R3 (pure)
        doc = proposed_model()
        compiled = solution.compile_solution(good(), doc)
        tools = {"request_handler": compiled["agents"]["request_handler"]["tools"]}
        snap = {"ontology": doc, "settings": {"agents": compiled["agents"], "solution": good()}, "tools": tools}
        self.assertEqual(solution.release_problems(snap), [])
        tampered = copy.deepcopy(snap)
        tampered["settings"]["agents"]["request_handler"]["roles"] = ["manager", "service_agent"]  # more authority
        self.assertIn("not the ones its agent and tool configuration compiles to",
                      " ".join(solution.release_problems(tampered)))
        for change, expected in (
                (lambda s: s["settings"].update(agents={}, solution=None) or s.update(tools={}), "no agent is configured"),
                (lambda s: s["settings"].update(solution=None) or s["settings"]["agents"]["request_handler"]
                 .update(goals=["world_peace"]), "pursues the goal 'world_peace'"),
                (lambda s: s["settings"].update(solution=None) or s.update(tools={}), "no readable tool declaration"),
                (lambda s: s["settings"].update(solution=None) or s.update(tools={"request_handler": {"unreadable": "x"}}),
                 "no readable tool declaration"),
                (lambda s: s["settings"].update(solution=None) or s.update(tools={"request_handler": {"tools": []}}),
                 "has no tool"),
                (lambda s: s["settings"].update(solution=None) or s.update(tools={"request_handler": {"tools": [
                    {"name": "x", "capability": "elsewhere.do", "type": "table"}]}}), "serves an action"),
                (lambda s: s["ontology"].update(rules=[{"id": "R", "type": "magic"}]), "does not validate"),
                (lambda s: s["settings"].update(solution={"agents": {"a": {"goals": ["nope"]}}}), "agent and tool configuration"),
                (lambda s: s["settings"].update(agents={"request_handler": "?"}, solution=None), "not a configuration")):
            broken = copy.deepcopy(snap)
            change(broken)
            self.assertIn(expected, " ".join(solution.release_problems(broken)), expected)
        # tools built by code are known only when loaded: not judged here; an empty model needs no agent
        coded = copy.deepcopy(snap)
        coded["settings"]["solution"] = None
        coded["tools"] = {"request_handler": {"registries": ["pkg.mod:build"]}}
        self.assertEqual(solution.release_problems(coded), [])
        self.assertEqual(solution.release_problems({"ontology": {"name": "empty", "version": "1"}}), [])
        self.assertEqual(solution.release_problems(None), ["the release has no model document"])
        parts = solution.release_components(coded)
        self.assertEqual((parts["agents"]["managed"], parts["tools"]["all_simulated"], parts["tools"]["other"]), ("files", False, 1))
        self.assertEqual(solution.release_components(None)["agents"], {"names": [], "fingerprint": parts["agents"]["fingerprint"],
                                                                       "managed": "none"} | {"fingerprint": solution.release_components(None)["agents"]["fingerprint"]})


class DraftAndActiveTests(ReleaseBase):
    def test_a_draft_changes_nothing_and_a_published_change_needs_its_own_release(self):  # R2
        first = self.released(proposed_model(), good())
        running = self.desk.configuration_fingerprint
        supervised = good(autonomy={"mode": "supervised", "reviewer": "manager"})
        revision = self.draft(None, supervised)
        self.assertEqual(self.desk.configuration_fingerprint, running)  # saved, not running
        self.assertEqual(self.desk.agents["request_handler"].agent.autonomy, {"mode": "policy"})
        self.assertEqual(json.loads((self.home / SOLUTION_OVERRIDE).read_text()), good())
        _, view = self.call("GET", UC)
        self.assertEqual((view["release"]["drift"], view["release"]["active"]["number"]), (False, first))
        # published by another person: what runs differs from the active release, so nothing executes
        status, view = self.publish(revision)
        self.assertEqual((status, view["release"]["drift"], view["effective_stage"]), (200, True, "draft"))
        self.assertEqual(view["published_agents"], ["request_handler"])
        self.assertEqual(self.call("GET", f"{UC}/releases")[1]["active"]["number"], first)  # the release is untouched
        self.assertEqual(self.call("GET", f"{UC}/releases/{first}")[1]["snapshot"]["settings"]["solution"], good())
        second = self.propose("supervised")
        self.assertEqual(self.approve(second)[0], 200)
        status, out = self.activate(second)
        self.assertEqual((status, out["event"], out["reloaded"]), (200, "activated", False), out)
        self.assertEqual(self.desk.agents["request_handler"].agent.autonomy["mode"], "supervised")

    def test_separation_of_duties_holds_for_configurations(self):  # R4
        revision = self.draft(proposed_model(), good())
        status, out = self.publish(revision, "acme-ada")  # ada saved it
        self.assertEqual(status, 403)
        self.assertIn("another person", out["error"]["message"])
        self.assertFalse((self.home / SOLUTION_OVERRIDE).exists())
        self.assertEqual(self.publish(revision, "acme-hana")[0], 404)  # no access to the use case at all
        self.assertEqual(self.publish(revision)[0], 200)
        number = self.propose()
        status, out = self.approve(number, "acme-ada")  # ada proposed it
        self.assertEqual(status, 403)
        self.assertIn("proposer cannot approve", out["error"]["message"])
        self.assertEqual(self.activate(number)[0], 409)  # not approved: not activated
        self.assertEqual(self.desk.stage_gate()[0], "draft")


class ValidationBeforeActivationTests(ReleaseBase):
    def test_a_configuration_that_no_longer_fits_its_model_is_not_published(self):  # R3
        self.draft(proposed_model(), good())
        renamed = proposed_model()
        renamed["goals"] = {"request_done": renamed["goals"]["request_closed"]}
        revision = self.draft(renamed)  # the model changes; the configuration is carried over as it was
        status, out = self.publish(revision)
        self.assertEqual(status, 409, out)
        self.assertIn("does not fit its model", out["error"]["message"])
        self.assertIn("request_closed", out["error"]["message"])
        self.assertFalse((self.home / ONTOLOGY_OVERRIDE).exists())
        self.assertFalse((self.home / SOLUTION_OVERRIDE).exists())
        self.assertEqual(self.desk.agents, {})

    def test_a_release_without_the_agents_its_model_needs_is_not_activated(self):  # R3, R7
        status, _ = self.publish(self.draft(proposed_model()))  # a model with goals and actions, no agent
        self.assertEqual(status, 200)
        number = self.propose("model only")
        self.assertEqual(self.approve(number)[0], 200)
        verdict = self.call("GET", f"{UC}/releases/{number}")[1]["verification"]
        self.assertEqual((verdict["coherent"], verdict["fingerprint_matches"]), (False, True))
        status, out = self.activate(number, "try it")
        self.assertEqual(status, 409, out)
        self.assertIn("no agent is configured", out["error"]["message"])
        self.assertIn("nothing was changed", out["error"]["message"])
        self.assertIsNone(self.call("GET", f"{UC}/releases")[1]["active"])
        refused = self.admin_events("release_activation_refused")
        self.assertEqual([(e["by"], e["reason"], e["data"]["release"], e["data"]["use_case"]) for e in refused],
                         [("ada@acme", "try it", number, "desk")])
        self.assertIn("no agent is configured", refused[0]["data"]["refusal"])
        # requests that name nothing real leave no evidence: there is nothing to refuse
        self.assertEqual(self.activate(99)[0], 404)
        self.assertEqual(self.activate(number, "")[0], 400)
        self.assertEqual(len(self.admin_events("release_activation_refused")), 1)

    def test_a_published_file_that_does_not_fit_stops_the_use_case_from_loading(self):  # R3 (fail closed)
        self.released(proposed_model(), good())
        path = self.home / SOLUTION_OVERRIDE
        path.write_text(json.dumps({"agents": {"ghost": {"goals": ["nope"], "roles": [], "tools": []}}}))
        status, out = self.call("POST", f"{UC}/reload", body={"reason": "pick up the file"})
        self.assertEqual(status, 400, out)
        self.assertIn("does not fit the model", out["error"]["message"])
        self.assertEqual(sorted(self.desk.agents), ["request_handler"])  # the engine that ran keeps running


class ActivationAndRollbackTests(ReleaseBase):
    def test_a_failed_activation_puts_the_model_the_agents_and_the_engine_back(self):  # R5
        first = self.released(proposed_model(), good())
        two = good()
        two["agents"]["second_agent"] = copy.deepcopy(two["agents"]["request_handler"])
        second = self.released(None, two, "two agents")
        files = {name: (self.home / name).read_bytes() for name in (ONTOLOGY_OVERRIDE, SOLUTION_OVERRIDE)}
        swap, calls = self.pf._swap, []

        def failing(ws, uc):
            calls.append(uc.id)
            if len(calls) == 1:
                raise RuntimeError("disk full")
            return swap(ws, uc)
        self.pf._swap = failing
        status, out = self.activate(first, "roll back")
        self.pf._swap = swap
        self.assertEqual(status, 500, out)
        self.assertIn("put back", out["error"]["message"])
        self.assertEqual({name: (self.home / name).read_bytes() for name in files}, files)
        self.assertEqual(sorted(self.desk.agents), ["request_handler", "second_agent"])
        self.assertEqual(self.call("GET", f"{UC}/releases")[1]["active"]["number"], second)
        self.assertEqual(self.call("GET", UC)[1]["release"]["drift"], False)
        self.assertEqual(len(self.admin_events("release_activation_refused")), 1)

    def test_a_rollback_restores_the_model_and_the_agents_together(self):  # R6, R7
        empty = self.propose("empty model")  # the blank use case: no goal, so no agent is needed
        self.assertEqual(self.approve(empty)[0], 200)
        self.assertEqual(self.activate(empty)[0], 200)
        first = self.released(proposed_model(), good())
        two = good()
        two["agents"]["second_agent"] = copy.deepcopy(two["agents"]["request_handler"])
        second = self.released(None, two, "two agents")
        self.assertEqual(sorted(self.desk.agents), ["request_handler", "second_agent"])
        status, out = self.activate(first, "the second agent misbehaves")
        self.assertEqual((status, out["event"], out["reloaded"]), (200, "rolled_back", True), out)
        self.assertEqual(sorted(self.desk.agents), ["request_handler"])
        self.assertEqual(json.loads((self.home / SOLUTION_OVERRIDE).read_text()), good())
        self.assertEqual(self.desk.configuration_fingerprint, self.call("GET", f"{UC}/releases/{first}")[1]["fingerprint"])
        status, out = self.activate(empty, "start again")  # back to a release with no agent at all
        self.assertEqual((status, out.get("event")), (200, "rolled_back"), out)
        self.assertEqual(self.desk.agents, {})
        self.assertFalse((self.home / SOLUTION_OVERRIDE).exists())
        self.assertEqual(self.desk.ontology.entities, {})
        # restoring a release's files without activating it brings both back too
        status, back = self.call("POST", f"{UC}/releases/{second}/restore", body={"reason": "look at it again"})
        self.assertEqual((status, back["matches_release"]), (200, True), back)
        self.assertEqual(sorted(self.desk.agents), ["request_handler", "second_agent"])
        history = self.call("GET", f"{UC}/releases")[1]["history"]
        self.assertEqual([(e["release"], e["event"]) for e in history if e["event"] in ("activated", "rolled_back")],
                         [(empty, "activated"), (first, "activated"), (second, "activated"), (first, "rolled_back"),
                          (empty, "rolled_back")])
        self.assertTrue(all(e["by"] == "ada@acme" and e["reason"] for e in history if e["event"] == "rolled_back"))
        published = self.admin_events("draft_published")
        self.assertEqual([e["data"].get("agents") for e in published], [["request_handler"], ["request_handler", "second_agent"]])

    def test_sample_records_come_with_the_configuration_and_only_into_an_empty_store(self):  # R6 (data is not configuration)
        doc = proposed_model()
        cfg = good()
        cfg["sample_data"] = {"instances": [
            {"type": "Requester", "id": "EMP-1", "name": "Sam (synthetic)", "department": "Finance"},
            {"type": "Request", "id": "REQ-1", "status": "submitted", "title": "Laptop", "category": "hardware",
             "amount": 400, "priority": "normal"},
            {"type": "Team", "id": "TEAM-1", "status": "available", "name": "Service desk"}],
            "links": [["EMP-1", "submits", "REQ-1"], ["TEAM-1", "fulfils", "REQ-1"]]}
        self.released(doc, cfg)
        seeded = self.desk.store.count_instances()
        self.assertEqual(seeded, len(cfg["sample_data"]["instances"]))
        self.assertGreater(seeded, 0)
        more = copy.deepcopy(cfg)
        more["sample_data"]["instances"].append({**more["sample_data"]["instances"][0], "id": "EXTRA-1"})
        self.released(None, more, "more samples")
        self.assertEqual(self.desk.store.count_instances(), seeded)  # records people may have changed are never reloaded


class BoundaryTests(ReleaseBase):
    def test_an_operators_agents_are_never_replaced_and_other_workspaces_see_nothing(self):  # R8
        claims = "/w/acme/u/claims/api/v1"
        _, draft = self.call("GET", f"{claims}/model/draft")
        status, saved = self.call("POST", f"{claims}/model/draft", body={"document": draft["document"],
                                                                         "expected_revision": draft["revision"], "note": "same"})
        self.assertEqual(status, 200)
        before = sorted(self.pf.workspaces["acme"].use_cases["claims"].service.agents)
        status, out = self.call("POST", f"{WS}/use-cases/claims/publish-draft", "acme-maria",
                                {"revision": saved["revision"], "reason": "same model"})
        self.assertEqual(status, 200, out)
        self.assertEqual(sorted(self.pf.workspaces["acme"].use_cases["claims"].service.agents), before)
        self.assertFalse((self.pf.data_dir / "acme" / "claims" / SOLUTION_OVERRIDE).exists())
        # a Studio configuration beside an operator's agents is refused when the use case loads
        (self.pf.data_dir / "acme" / "claims" / SOLUTION_OVERRIDE).write_text(json.dumps({"agents": {}}))
        status, out = self.call("POST", f"{WS}/use-cases/claims/reload", body={"reason": "try"})
        self.assertEqual(status, 400)
        self.assertIn("remove one of the two", out["error"]["message"])
        (self.pf.data_dir / "acme" / "claims" / SOLUTION_OVERRIDE).unlink()
        number = self.released(proposed_model(), good())
        for path in (f"{UC}/releases/{number}", f"{UC}/releases", UC):
            self.assertEqual(self.c.call("GET", path, "nw-nadia")[0], 404, path)
        self.assertEqual(self.c.call("GET", f"{ENGINE}/solution/draft", "nw-nadia")[0], 404)
        self.assertEqual(self.c.call("POST", f"{UC}/releases/{number}/activate", "nw-nadia", {"reason": "x"})[0], 404)

    def test_a_release_approver_works_from_the_identifier_and_sees_nothing_else(self):  # R4, R8
        me = {token: self.c.call("GET", "/platform/v1/me", token)[1].get("release_approver")
              for token in ("acme-ada", "acme-maria", "acme-hana")}
        self.assertEqual(me, {"acme-ada": True, "acme-maria": True, "acme-hana": False})
        self.assertIsNone(self.call("GET", f"{UC}/releases", "acme-maria")[1]["draft"])  # nothing saved yet
        revision = self.draft(proposed_model(), good())
        status, state = self.call("GET", f"{UC}/releases", "acme-maria")  # maria has no grant on this use case
        self.assertEqual((status, state["draft"], state["may_approve"], state["may_propose"]),
                         (200, {"revision": revision, "author": "ada"}, True, False))
        self.assertNotIn("document", str(state["draft"]))  # the revision to name, never the draft itself
        for path in (UC, f"{UC}/readiness?target=pilot", f"{ENGINE}/solution/draft", f"{ENGINE}/model/draft"):
            self.assertEqual(self.call("GET", path, "acme-maria")[0], 404, path)  # releases only, as before
        listed = [u["id"] for u in self.call("GET", f"{WS}/use-cases", "acme-maria")[1]["items"]]
        self.assertNotIn("desk", listed)
        self.assertEqual(self.publish(revision)[0], 200)  # which is all she needs to publish it
        # a member with no release authority gets no draft information, and no access where she has no grant
        self.assertNotIn("draft", self.call("GET", f"{WS}/use-cases/claims/releases", "acme-hana")[1])
        self.assertEqual(self.call("GET", f"{UC}/releases", "acme-hana")[0], 404)
        self.assertEqual(self.c.call("GET", f"{UC}/releases", "nw-nadia")[0], 404)


if __name__ == "__main__":
    import unittest

    unittest.main()
