"""Review of an architect's proposal, element by element (synthetic; a provider test double; nothing is paid).

  R1 every inferred element can be reviewed on its own; none is confirmed by default, in bulk by omission or by a
     later revision repeating it
  R2 decisions and corrections are persisted, attributed and survive leaving the session and a restart
  R3 a rejected element that is proposed again stays rejected and is flagged; it never enters a draft that names
     the proposal
  R4 when an element is rejected, what depends on it is named, and the strict loader has the last word
  R5 a correction is a person's, needs no provider, replaces the element's content and is validated like any other
  R6 a decision is about the element as shown: unchanged, it carries to the next revision; changed, it does not
  R7 the Engine refuses a draft that takes an unconfirmed or rejected element from the proposal it names
  R8 nothing is activated by an answer or a decision; a service identity and a reader decide nothing
  R9 one line per element: what it rests on, what the Engine found, what a person decided
"""

import copy
import json
import unittest

from autology import proposal_review as pr

from .test_arch2_ai_provider_governance import ENGINE
from .test_stab3_proposal_lifecycle import SECOND, LifecycleBase

T1, T2, T3 = "2026-11-19T10:00:00+00:00", "2026-11-19T10:05:00+00:00", "2026-11-19T10:09:00+00:00"


def item(kind, name, value, basis="supplied"):
    return {"id": f"model:{kind}:{name}", "kind": kind, "name": name, "value": value, "basis": basis, "origin": "brief",
            "evidence": [{"ref": "brief", "kind": "brief"}], "rationale": "r", "validation": "passed"}


ITEMS = [
    item("entity", "Ticket", {"description": "Work", "states": ["open", "done"], "attributes": {"size": "number"}}),
    item("entity", "Owner", {"description": "Who", "states": ["active"], "attributes": {"label": "string"}}, "inferred"),
    item("relationship", "owns", {"from": "Owner", "to": "Ticket", "type": "owns", "cardinality": "1..*"}, "inferred"),
    item("action", "finish", {"description": "Finish", "capability": "ops.finish", "requires": ["Ticket.status == 'open'"],
                              "effects": {"Ticket": {"status": "done"}}, "side_effect": "none"}),
    item("rule", "R-BIG", {"id": "R-BIG", "type": "human_review", "description": "big", "action": "finish",
                           "reviewer": "lead", "when": "Ticket.size >= 5"}, "inferred"),
    item("goal", "finished", {"description": "done", "target": "Ticket.status == 'done'"}),
    item("case_template", "ticket_case", {"description": "one", "root": "Ticket",
                                          "entities": {"Ticket": "self", "Owner": "^owns"}}, "inferred")]
BASE = {"name": "work", "version": "0.1.0"}


def rows(*revisions):
    return [{"revision": n + 1, "result": {"items": items, "rejected": []}} for n, items in enumerate(revisions)]


def decision(revision, accepted=(), rejected=(), by="ada", at=T1):
    return {"revision": revision, "decided_by": by, "at": at, "accepted": list(accepted), "rejected": list(rejected), "note": ""}


def ids(*names):
    return [i["id"] for i in ITEMS if i["name"] in names]


class RuleTests(unittest.TestCase):
    def test_nothing_inferred_is_confirmed_by_default(self):  # R1
        out = pr.report(BASE, rows(ITEMS), [], [], 1)
        self.assertEqual(out["counts"], {"elements": 7, "stated": 3, "inferred": 4, "confirmed": 0, "corrected": 0, "rejected": 0,
                                         "unresolved": 4, "proposed_again_after_rejection": 0, "kept": 3, "dependency_failures": 0})
        self.assertEqual(out["unresolved"], ids("Owner", "owns", "R-BIG", "ticket_case"))
        self.assertEqual([e["id"] for e in out["elements"] if e["kept"]], ids("Ticket", "finish", "finished"))
        self.assertEqual(sorted(out["document"]), ["actions", "entities", "goals", "name", "version"])
        self.assertTrue(out["validation"]["valid"] and out["ready_for_draft"])
        # one by one: each acceptance confirms that element and no other
        one = pr.report(BASE, rows(ITEMS), [decision(1, ids("R-BIG"))], [], 1)
        self.assertEqual((one["counts"]["confirmed"], one["counts"]["unresolved"], [r["id"] for r in one["document"]["rules"]]),
                         (1, 3, ["R-BIG"]))
        self.assertEqual(one["decided_by"], ["ada"])
        self.assertIn("only when a person accepted or corrected it", pr.POLICY)

    def test_what_depends_on_a_rejected_or_unconfirmed_element_is_named(self):  # R4
        # the relationship and the case template are confirmed; the entity they need is not
        waiting = pr.report(BASE, rows(ITEMS), [decision(1, ids("owns", "ticket_case"))], [], 1)
        self.assertEqual([(f["element"], f["needs"], list(f["because"].values())) for f in waiting["dependency_failures"]], [
            ("model:relationship:owns", ids("Owner"), ["inferred and not confirmed"]),
            ("model:case_template:ticket_case", ids("Owner", "owns")[:1], ["inferred and not confirmed"])])
        self.assertFalse(waiting["ready_for_draft"])
        self.assertFalse(waiting["validation"]["valid"])            # and the strict loader says so too, in its own words
        self.assertIn("Owner", waiting["validation"]["problems"][0])
        self.assertEqual(len(waiting["why_not"]), 2)
        gone = pr.report(BASE, rows(ITEMS), [decision(1, ids("owns", "ticket_case"), ids("Owner"))], [], 1)
        self.assertEqual(gone["dependency_failures"][0]["because"], {"model:entity:Owner": "rejected"})
        whole = pr.report(BASE, rows(ITEMS), [decision(1, ids("Owner", "owns", "ticket_case", "R-BIG"))], [], 1)
        self.assertEqual((whole["dependency_failures"], whole["validation"]["valid"], whole["ready_for_draft"]), ([], True, True))
        # an element the model being designed already holds is not missing
        held = pr.report({**BASE, "entities": {"Owner": ITEMS[1]["value"]}}, rows(ITEMS), [decision(1, ids("owns"))], [], 1)
        self.assertEqual(held["dependency_failures"], [])
        by = {e["id"]: e["depends_on"] for e in whole["elements"]}
        self.assertEqual((by["model:action:finish"], by["model:rule:R-BIG"], by["model:goal:finished"], by["model:entity:Ticket"]),
                         (ids("Ticket"), sorted(ids("Ticket", "finish")), ids("Ticket"), []))
        self.assertEqual(by["model:case_template:ticket_case"], sorted(ids("Ticket", "Owner", "owns")))

    def test_the_last_decision_wins_and_every_one_is_kept(self):  # R2
        out = pr.report(BASE, rows(ITEMS), [decision(1, ids("Owner")), decision(1, rejected=ids("Owner"), by="bo", at=T2)], [], 1)
        owner = next(e for e in out["elements"] if e["name"] == "Owner")
        self.assertEqual((owner["decision"], owner["by"], owner["kept"]), ("rejected", "bo", False))
        self.assertEqual([(h["decision"], h["by"]) for h in owner["history"]], [("accepted", "ada"), ("rejected", "bo")])
        self.assertEqual(out["decided_by"], ["ada", "bo"])
        stated = pr.report(BASE, rows(ITEMS), [decision(1, rejected=ids("Ticket"))], [], 1)  # a stated element can be rejected
        self.assertFalse(next(e for e in stated["elements"] if e["name"] == "Ticket")["kept"])

    def test_a_decision_is_about_the_element_as_it_was_shown(self):  # R3, R6
        changed = copy.deepcopy(ITEMS)
        changed[1]["value"]["attributes"]["salary"] = "number"   # the next revision proposes Owner differently
        both = rows(ITEMS, changed)
        accepted = [decision(1, ids("Owner", "owns"))]
        again = {e["name"]: e for e in pr.standing(both, accepted, [], 2)}
        self.assertEqual((again["owns"]["decision"], again["owns"]["kept"], again["owns"]["decided_on_revision"]), ("accepted", True, 1))
        self.assertEqual(again["owns"]["flags"], ["decision carried from revision 1: the element is unchanged"])
        self.assertEqual((again["Owner"]["decision"], again["Owner"]["kept"]), (None, False))
        self.assertEqual(again["Owner"]["flags"], ["changed since it was accepted in revision 1: undecided again"])
        # rejected, then proposed again: unchanged or changed, it stays rejected, and says so
        rejected = [decision(1, rejected=ids("Owner", "owns"))]
        back = {e["name"]: e for e in pr.standing(both, rejected, [], 2)}
        self.assertEqual((back["owns"]["decision"], back["owns"]["kept"], back["owns"]["flags"]),
                         ("rejected", False, ["proposed again after it was rejected"]))
        self.assertEqual((back["Owner"]["decision"], back["Owner"]["kept"], back["Owner"]["flags"]),
                         ("rejected", False, ["proposed again, changed, after it was rejected"]))
        self.assertEqual(pr.report(BASE, both, rejected, [], 2)["counts"]["proposed_again_after_rejection"], 2)
        # only a new decision on the new revision brings it back, and it is in the history beside the rejection
        fresh = {e["name"]: e for e in pr.standing(both, rejected + [decision(2, ids("Owner"), by="bo", at=T2)], [], 2)}
        self.assertEqual((fresh["Owner"]["decision"], fresh["Owner"]["by"], len(fresh["Owner"]["history"])), ("accepted", "bo", 2))
        # a decision recorded on a later revision says nothing about an earlier one
        self.assertIsNone({e["name"]: e for e in pr.standing(both, [decision(2, ids("Owner"))], [], 1)}["Owner"]["decision"])

    def test_a_correction_is_the_persons_and_is_validated_like_any_other(self):  # R5
        better = {"description": "Who owns tickets", "states": ["active", "retired"], "attributes": {"label": "string"}}
        fix = [{"revision": 1, "item": "model:entity:Owner", "value": better, "corrected_by": "bo", "at": T2, "note": "two states"}]
        out = pr.report(BASE, rows(ITEMS), [decision(1, ids("owns", "ticket_case", "R-BIG"))], fix, 1)
        owner = next(e for e in out["elements"] if e["name"] == "Owner")
        self.assertEqual((owner["decision"], owner["by"], owner["kept"], owner["value"]), ("corrected", "bo", True, better))
        self.assertEqual((out["document"]["entities"]["Owner"], out["counts"]["corrected"], out["counts"]["confirmed"]), (better, 1, 4))
        self.assertTrue(out["validation"]["valid"])
        broken = [{**fix[0], "value": {"description": "x", "states": [], "attributes": {"label": "no-such-type"}}}]
        bad = pr.report(BASE, rows(ITEMS), [], broken, 1)
        self.assertEqual((bad["validation"]["valid"], bad["ready_for_draft"]), (False, False))  # a person's content is checked too
        later = pr.report(BASE, rows(ITEMS), [decision(1, rejected=ids("Owner"), at=T3)], fix, 1)   # and can be rejected afterwards
        self.assertEqual(next(e for e in later["elements"] if e["name"] == "Owner")["decision"], "rejected")

    def test_what_a_draft_may_take_from_the_proposal_it_names(self):  # R7
        elements = pr.standing(rows(ITEMS), [decision(1, ids("R-BIG"), ids("owns"))], [], 1)
        everything = pr.resolve(BASE, [{**e, "kept": True} for e in elements])
        self.assertEqual(pr.draft_problems(everything, elements), [
            {"element": "model:entity:Owner", "why": "it is inferred and nobody confirmed it"},
            {"element": "model:relationship:owns", "why": "it was rejected by ada"},
            {"element": "model:case_template:ticket_case", "why": "it is inferred and nobody confirmed it"}])
        self.assertEqual(pr.draft_problems(pr.resolve(BASE, elements), elements), [])
        own = copy.deepcopy(everything)  # the same name with content the person wrote themselves is theirs, not the proposal's
        own["entities"]["Owner"]["description"] = "written by hand"
        self.assertNotIn("model:entity:Owner", [p["element"] for p in pr.draft_problems(own, elements)])
        twice = pr.resolve(pr.resolve(BASE, [{**e, "kept": True} for e in elements]), [{**e, "kept": True} for e in elements])
        self.assertEqual((len(twice["rules"]), len(twice["relationships"])), (1, 1))  # nothing is added twice

    def test_one_line_per_element_from_the_text_to_the_decision(self):  # R9
        row = {"revision": 1, "result": {"items": ITEMS, "rejected": [{"kind": "rule", "name": "R-X", "problem": "no such action"}]}}
        review = pr.report(BASE, [row], [decision(1, ids("R-BIG"), ids("owns"))], [], 1)
        lines = {line["element"]: line for line in pr.traceability(row, review)}
        self.assertEqual(len(lines), 8)
        self.assertEqual(lines["model:rule:R-BIG"], {
            "element": "model:rule:R-BIG", "basis": "inferred", "origin": "brief", "cites": ["brief"], "rationale": "r",
            "engine": "passed", "decision": "accepted", "decided_by": "ada", "in_the_model": True, "flags": []})
        self.assertEqual((lines["model:entity:Ticket"]["decision"], lines["model:entity:Owner"]["decision"],
                          lines["model:relationship:owns"]["decision"]), ("none needed", "none", "rejected"))
        self.assertEqual((lines["rule:R-X"]["engine"], lines["rule:R-X"]["in_the_model"]), ("refused: no such action", False))

    def test_no_name_means_anything_and_no_provider_is_near(self):  # R1
        source = open(pr.__file__, encoding="utf-8").read().split('"""', 2)[2]
        for word in ("gateway", "provider", "anthropic", "urllib", "environ", "architect_elements"):
            self.assertNotIn(word, source, word)
        opaque = json.loads(json.dumps(ITEMS).replace("Ticket", "E1").replace("Owner", "E2").replace("finish", "a1"))
        a, b = pr.report(BASE, rows(ITEMS), [], [], 1), pr.report(BASE, rows(opaque), [], [], 1)
        self.assertEqual((a["counts"], [len(e["depends_on"]) for e in a["elements"]]), (b["counts"], [len(e["depends_on"]) for e in b["elements"]]))


class ApiTests(LifecycleBase):
    def decide(self, proposal, token="acme-ada", **body):
        return self.call("POST", f"{ENGINE}/architect/proposals/{proposal['id']}/decision", token, body)

    def test_review_through_the_api_persisted_attributed_and_enforced(self):  # R1, R2, R3, R5, R7, R8
        self.answers.append(SECOND)                      # a third answer: the model proposes the same elements again
        first, second = self.session()
        review = second["review"]
        inferred = [e["id"] for e in review["elements"] if e["needs_confirmation"]]
        stated = [e["id"] for e in review["elements"] if not e["needs_confirmation"]]
        self.assertTrue(inferred and stated)
        self.assertEqual((review["unresolved"], review["counts"]["confirmed"], review["revision"]), (inferred, 0, 2))
        self.assertNotIn("document", review)
        tug = next(e for e in review["elements"] if e["name"] == "Tug")
        self.assertTrue(tug["needs_confirmation"])
        # a draft that names the proposal and takes the unconfirmed element is refused; nothing is saved
        values = {i["id"]: i for i in second["items"]}
        document = {"name": "port", "version": "0.1.0", "entities": {values[i]["name"]: values[i]["value"] for i in stated + [tug["id"]]
                                                                     if values[i]["kind"] == "entity"}}
        origin = {"proposal": first["id"], "revision": 2}
        save = {"document": document, "expected_revision": 0, "note": "x", "origin": origin}
        status, out = self.call("POST", f"{ENGINE}/model/draft", "acme-ada", save)
        self.assertEqual((status, out["error"]["details"]["unconfirmed"]), (409, [
            {"element": "entity:Tug", "proposal": first["id"], "revision": 2, "why": "it is inferred and nobody confirmed it"}]))
        # who may decide: a person who may configure; not a reader, not a service identity
        robot = self.add("intake", kind="service")
        for token in ("acme-hana", robot, "nw-nadia"):
            self.assertIn(self.decide(second, token, accepted=[tug["id"]])[0], (403, 404), token)
        # rejected, with a correction of another element, in one review
        other = next(e for e in review["elements"] if e["needs_confirmation"] and e["id"] != tug["id"] and e["kind"] == "entity")
        corrected = {**values[other["id"]]["value"], "description": "As the harbour master describes it"}
        status, after = self.decide(second, rejected=[tug["id"]], corrected=[{"id": other["id"], "value": corrected}], note="reviewed")
        self.assertEqual(status, 200, after)
        by = {e["id"]: e for e in after["review"]["elements"]}
        self.assertEqual((by[tug["id"]]["decision"], by[tug["id"]]["by"], by[tug["id"]]["kept"]), ("rejected", "ada", False))
        self.assertEqual((by[other["id"]]["decision"], by[other["id"]]["by"], by[other["id"]]["value"]), ("corrected", "ada", corrected))
        self.assertEqual(after["corrections"][0]["item"], other["id"])
        self.assertEqual(len(self.double.calls), 2)       # a correction asked no provider
        # two reviewers at once: a decision over a review that has moved on is not recorded, and the reviewer is shown why
        version = after["review"]["version"]
        self.assertEqual((second["review"]["version"], version), (0, 2))
        status, stale = self.decide(second, accepted=[tug["id"]], expected_version=0)
        self.assertEqual((status, stale["error"]["details"]["version"]), (409, version))
        self.assertEqual({e["id"]: e["decision"] for e in stale["error"]["details"]["review"]["elements"]}[tug["id"]], "rejected")
        self.assertEqual(self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}")[1]["review"]["version"], version)
        self.assertEqual(self.decide(second, accepted=[stated[0]], expected_version=True)[0], 409)
        status, fresh = self.decide(second, accepted=[stated[0]], expected_version=version)
        self.assertEqual((status, fresh["review"]["version"]), (200, version + 1))
        for bad in ({"corrected": [{"id": tug["id"], "value": {}}], "rejected": [tug["id"]]}, {"corrected": [{"id": "model:entity:Nope", "value": {}}]},
                    {"corrected": [{"id": tug["id"]}]}, {"corrected": "all"}, {}):
            self.assertEqual(self.decide(second, **bad)[0], 400, bad)
        status, out = self.call("POST", f"{ENGINE}/model/draft", "acme-ada", save)
        self.assertEqual(status, 409)
        self.assertEqual(out["error"]["details"]["unconfirmed"][0]["why"], "it was rejected by ada")
        # the person leaves; the platform restarts; the review is as it was left
        self.start()
        status, read = self.call("GET", f"{ENGINE}/architect/proposals/{first['id']}")
        self.assertEqual(status, 200)
        self.assertEqual({e["id"]: (e["decision"], e["by"]) for e in read["review"]["elements"]},
                         {e["id"]: (e["decision"], e["by"]) for e in fresh["review"]["elements"]})
        self.assertEqual([h["decision"] for h in next(e for e in read["review"]["elements"] if e["id"] == tug["id"])["history"]], ["rejected"])
        # the model proposes the same elements again: the rejected one is still rejected, and flagged; the correction carries
        status, third = self.call("POST", f"{ENGINE}/architect/proposals", "acme-ada", {"generator": "model", "revises": first["id"], "feedback": "again"})
        self.assertEqual((status, third["revision"]), (200, 3))
        again = {e["id"]: e for e in third["review"]["elements"]}
        self.assertEqual((again[tug["id"]]["decision"], again[tug["id"]]["kept"], again[tug["id"]]["flags"]),
                         ("rejected", False, ["proposed again after it was rejected"]))
        self.assertEqual((again[other["id"]]["decision"], again[other["id"]]["value"]), ("corrected", corrected))
        self.assertEqual(third["review"]["counts"]["proposed_again_after_rejection"], 1)
        status, out = self.call("POST", f"{ENGINE}/model/draft", "acme-ada", {**save, "origin": {"proposal": first["id"], "revision": 3}})
        self.assertEqual(status, 409, out)
        # nothing was activated or drafted by any of this
        status, draft = self.call("GET", f"{ENGINE}/model/draft")
        self.assertEqual((draft["revision"], draft["origin"]), (0, None))
        # with the element left out, and the corrected content, the draft is the person's to save
        ok = copy.deepcopy(document)
        del ok["entities"]["Tug"]
        ok["entities"][other["name"]] = corrected
        status, saved = self.call("POST", f"{ENGINE}/model/draft", "acme-ada", {**save, "document": ok})
        self.assertEqual((status, saved["revision"], saved["origin"]), (200, 1, origin))
