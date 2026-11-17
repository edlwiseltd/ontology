"""GAP-082: the element-level rejection design, validated and **not in force** (owner decision D30 f).

``autology.architect_elements.triage`` reads an answer the way option 4 of the decision record describes. The rule
in force is unchanged, and the first tests say so.

  E1 the policy in force is the whole-answer refusal: the gateway refuses the same answers as before, and nothing in
     the gateway, the architect or the API uses the proposed module
  E2 strict envelope: an unknown section, a missing section, a wrong type, any defect outside the model sections,
     or a property named like a permission, a release, a setting, a tool or a credential at any depth refuses the
     whole answer
  E3 an element with any defect is rejected whole, by name, with its reasons; nothing is repaired or stripped, and
     the answer given is not changed
  E4 dependency integrity: what refers to a rejected element is rejected with it, to a fixed point; an unnamed
     rejected entity or action refuses the whole answer
  E5 no silent defaults: a missing required property is a rejection, never a filled-in value
  E6 a partial answer is marked partial, lists what must happen before it is used, and activates nothing
  E7 too many rejections refuse the whole answer
  E8 audit: a digest of the answer as received, every rejection with its place, the classes, the decision
  E9 replay: the stored answers of the real evaluation (17 November 2026), put back in the contract's form, are
     accepted unchanged; with the two recorded defects put back at their recorded places, each loses exactly the
     named element (and what depends on it) under the proposed policy, and everything under the policy in force

The replay rebuilds contract-form answers from stored proposals: the two refused answers themselves were not kept
(that was GAP-082's lesson). Nothing here calls a provider, and nothing here measures a model.
"""

import copy
import json
import unittest

from autology import ai, architect, architect_elements
from autology.ai import ModelGateway, ProviderError, ProviderReply
from autology.sandbox_ai import answer

from .helpers import ROOT
from .test_xdom1_cross_domain import DOMAINS, PACKS

EVIDENCE = ROOT / "planning" / "evidence" / "claude-eval-2026-11-17"
triage = architect_elements.triage


def good():
    """A complete answer in the contract's form (the crisis pack through the sandbox: deterministic)."""
    d = DOMAINS["crisis"]
    data = answer({"brief": d["brief"], "answers": [{"id": k, "answer": v} for k, v in d["answers"].items()]},
                  [PACKS / d["pack"] / "blueprints"])
    assert not ai.schema_errors(data, dict(architect.SCHEMA)), "the fixture must satisfy the contract"
    return data


def in_force(data):
    """What the gateway does with this answer today: the data, or the refusal."""
    try:
        return ModelGateway._answer(ProviderReply(json.dumps(data), "complete", {}, "test"), architect.SCHEMA)
    except ProviderError as exc:
        return exc


def as_answer(stored):
    """A stored proposal of the real evaluation, put back in the contract's form (the inverse of
    ``architect._items`` for what was kept)."""
    out = {section: [] for _, section in architect.SECTIONS}
    out.update({"questions": [], "assumptions": [], "unknowns": [], "roles": [], "agents": [], "integrations": []})
    for item in stored["items"]:
        v = item["value"]
        common = {"rationale": item["rationale"], "sources": item["sources"], "confidence": item["confidence"],
                  "basis": item["basis"]}
        if item["kind"] == "entity":
            raw = {"name": item["name"], "description": v["description"], "states": v["states"],
                   "attributes": [{"name": a, "type": t} for a, t in v["attributes"].items()]}
        elif item["kind"] == "relationship":
            raw = dict(v)
        elif item["kind"] == "action":
            raw = {"name": item["name"], "description": v["description"], "capability": v["capability"],
                   "requires": v["requires"], "side_effect": v["side_effect"],
                   "effects": [{"entity": e, "attribute": a, "value": str(x)} for e, changes in v["effects"].items()
                               for a, x in changes.items()]}
        elif item["kind"] == "rule":
            raw = dict(v)
        elif item["kind"] == "goal":
            raw = {"name": item["name"], "description": v["description"], "target": v["target"]}
        else:
            raw = {"name": item["name"], "description": v["description"], "root": v["root"],
                   "entities": [{"entity": e, "path": p} for e, p in v["entities"].items()]}
        out[dict((k, s) for k, s in architect.SECTIONS)[item["kind"]]].append({**raw, **common})
    return out


class PolicyInForceTests(unittest.TestCase):
    def test_the_gateway_still_refuses_the_whole_answer(self):  # E1
        data = good()
        self.assertEqual(in_force(data), data)
        data["rules"][1]["name_placeholder_removed"] = True  # the defect recorded on 17 November
        refusal = in_force(data)
        self.assertIsInstance(refusal, ProviderError)
        self.assertEqual((refusal.kind, refusal.violation_classes), ("invalid_response", {"stray_property": 1}))
        self.assertEqual(refusal.violations, ["$.rules[1]: unexpected 'name_placeholder_removed'"])

    def test_nothing_that_runs_uses_the_proposed_module(self):  # E1
        package = ROOT / "autology"
        users = [p.name for p in package.glob("*.py")
                 if p.name != "architect_elements.py" and "architect_elements" in p.read_text(encoding="utf-8")]
        self.assertEqual(users, [])
        self.assertIn("not in force", architect_elements.POLICY)
        self.assertIn("**not in force**", architect_elements.__doc__)


class EnvelopeTests(unittest.TestCase):
    def refused(self, data, text):
        out = triage(data)
        self.assertEqual((out["decision"], out["kept"], out["partial"]), ("refuse_whole", None, False), out["envelope"])
        self.assertIn(text, " | ".join(out["envelope"]))
        self.assertEqual(out["audit"]["decision"], "refuse_whole")
        if isinstance(data, dict):  # the policy in force refuses it too
            self.assertIsInstance(in_force(data), ProviderError)
        return out

    def test_a_clean_answer_is_accepted_as_it_is(self):
        data = good()
        out = triage(data)
        self.assertEqual((out["decision"], out["partial"], out["rejected"], out["requires"]), ("accept", False, [], []))
        self.assertEqual(out["kept"], data)
        self.assertEqual(out["audit"]["elements"], sum(len(data[s]) for _, s in architect.SECTIONS))

    def test_the_envelope_is_strict(self):  # E2
        for bad in ([], "text", None, 3):
            self.refused(bad, "not a JSON object")
        data = good()
        data["grants"] = [{"member": "architect", "permissions": ["admin"]}]
        self.refused(data, "unexpected section 'grants'")
        data = good()
        data["notes"] = "harmless"
        self.refused(data, "unexpected section 'notes'")
        data = good()
        del data["rules"]
        self.refused(data, "missing section 'rules'")
        data = good()
        data["entities"] = {"IncidentReport": {}}
        self.refused(data, "$.entities: expected a list")

    def test_a_defect_outside_the_model_sections_refuses_everything(self):  # E2
        for section, change in (("questions", lambda q: q.append({"id": "x"})),
                                ("roles", lambda r: r.append({"name": "auditor", "description": "x", "may": "all"})),
                                ("unknowns", lambda u: u.append(7)),
                                ("understanding", lambda u: u.update(verdict="approved")),
                                ("agents", lambda a: a.append({"name": "x", "description": "y", "actions": "all"}))):
            data = good()
            change(data[section])
            self.refused(data, f"$.{section}")

    def test_a_sensitive_property_anywhere_refuses_everything(self):  # E2
        places = (lambda d: d["rules"][0].update(allow_self_review=True),
                  lambda d: d["entities"][0].update(permissions=["admin"]),
                  lambda d: d["actions"][0]["effects"][0].update(release="activate"),
                  lambda d: d["entities"][0]["attributes"][0].update(api_token="x"),
                  lambda d: d["goals"][0].update(autonomy="full"),
                  lambda d: d["case_templates"][0]["entities"][0].update(endpoint_url="http://example.invalid"))
        for place in places:
            data = good()
            place(data)
            out = self.refused(data, "is named like a permission")
            self.assertEqual(out["rejected"], [])  # not even a partial reading of such an answer


class ElementTests(unittest.TestCase):
    def test_one_defective_element_is_rejected_by_name_and_nothing_is_repaired(self):  # E3, E6, E8
        data = good()
        data["goals"][0]["name_hint_removed"] = "x"
        before = copy.deepcopy(data)
        out = triage(data)
        self.assertEqual(data, before)  # the answer given is never changed
        self.assertEqual((out["decision"], out["partial"]), ("accept_with_rejections", True))
        self.assertEqual([(r["section"], r["index"], r["name"], r["problems"]) for r in out["rejected"]],
                         [("goals", 0, "incident_handled", ["$.goals[0]: unexpected 'name_hint_removed'"])])
        self.assertEqual(out["kept"]["goals"], [])  # rejected whole: not kept with the property removed
        for section in ("entities", "relationships", "actions", "rules", "case_templates", "questions", "roles"):
            self.assertEqual(out["kept"][section], before[section])
        self.assertNotIn("name_hint_removed", json.dumps(out["kept"]))
        self.assertFalse(ai.schema_errors(out["kept"], dict(architect.SCHEMA)))  # what is kept satisfies the contract
        self.assertEqual(len(out["requires"]), 4)
        self.assertIn("nothing is applied, published or released", out["requires"][-1])
        audit = out["audit"]
        self.assertEqual((audit["decision"], audit["rejected"], audit["classes"], audit["policy"]),
                         ("accept_with_rejections", 1, {"stray_property": 1}, architect_elements.POLICY))
        self.assertEqual(len(audit["received_sha256"]), 64)
        self.assertNotEqual(audit["received_sha256"], triage(before | {"unknowns": []})["audit"]["received_sha256"])

    def test_a_missing_or_mistyped_property_is_a_rejection_never_a_default(self):  # E5
        for change, kind in ((lambda r: r.pop("confidence"), "missing"), (lambda r: r.update(confidence="high"), "wrong_type"),
                             (lambda r: r.pop("description"), "missing"), (lambda r: r.update(type="suggestion"), "not_allowed_value")):
            data = good()
            change(data["rules"][5])
            out = triage(data)
            self.assertEqual(out["decision"], "accept_with_rejections")
            self.assertEqual([(r["name"], list(r["classes"])) for r in out["rejected"]], [("R-RISK-FIGURE", [kind])])
            self.assertEqual(len(out["kept"]["rules"]), 5)
            self.assertNotIn("R-RISK-FIGURE", json.dumps(out["kept"]["rules"]))

    def test_what_refers_to_a_rejected_element_goes_with_it(self):  # E4
        data = good()
        data["actions"][3]["note"] = "x"  # assign_response_team
        out = triage(data, max_rejected_share=1.0)
        gone = {(r["section"], r["name"]): r["reason"] for r in out["rejected"]}
        self.assertEqual(gone[("actions", "assign_response_team")], "does not match the contract")
        for rule in ("R-ASSIGN-APPROVAL", "R-NO-PREDICTION", "R-VALIDATE-FIRST", "R-ASSIGN-ROLE"):
            self.assertEqual(gone[("rules", rule)], "refers to rejected assign_response_team")
        self.assertEqual(len(gone), 5)
        self.assertEqual([r["id"] for r in out["kept"]["rules"]], ["R-UPDATE-ROLE", "R-RISK-FIGURE"])
        # an entity: its relationships, the actions, rules, goals and case templates that name it, then theirs
        data = good()
        data["entities"][7]["extra"] = 1  # SupplyRequirement: one relationship refers to it
        out = triage(data)
        self.assertEqual([(r["section"], r["name"], r["reason"]) for r in out["rejected"]],
                         [("entities", "SupplyRequirement", "does not match the contract"),
                          ("relationships", "IncidentReport-requirements-SupplyRequirement",
                           "refers to rejected SupplyRequirement")])
        data = good()
        data["entities"][3]["extra"] = 1  # IncidentReport, the root: almost everything depends on it
        out = triage(data, max_rejected_share=1.0)
        self.assertEqual(out["kept"]["actions"], [])
        self.assertEqual(out["kept"]["goals"], [])
        self.assertEqual(out["kept"]["case_templates"], [])
        self.assertEqual(out["kept"]["rules"], [])  # every rule names an action that fell with the entity
        self.assertTrue(all("IncidentReport" not in json.dumps(e) for s in ("relationships",) for e in out["kept"][s]))

    def test_a_case_template_that_follows_a_rejected_relationship_goes_with_it(self):  # E4
        data = good()
        index = next(i for i, r in enumerate(data["relationships"]) if r["type"] == "assignments")
        data["relationships"][index]["hint"] = "x"
        out = triage(data)
        self.assertEqual([(r["section"], r["name"], r["reason"]) for r in out["rejected"]],
                         [("relationships", "IncidentReport-assignments-Assignment", "does not match the contract"),
                          ("case_templates", "incident_case", "refers to rejected assignments")])

    def test_an_unnamed_rejected_entity_or_action_refuses_everything(self):  # E4
        for section in ("entities", "actions"):
            data = good()
            del data[section][0]["name"]
            out = triage(data)
            self.assertEqual((out["decision"], out["kept"]), ("refuse_whole", None))
            self.assertIn("cannot be named", out["envelope"][0])
        data = good()
        data["entities"].append("just a string")
        self.assertEqual(triage(data)["decision"], "refuse_whole")

    def test_too_many_rejections_refuse_everything(self):  # E7
        data = good()
        data["entities"][3]["extra"] = 1
        out = triage(data)
        self.assertEqual((out["decision"], out["kept"]), ("refuse_whole", None))
        self.assertIn("more than 25 %", out["envelope"][0])
        self.assertGreater(len(out["rejected"]), 10)  # the rejections are still reported

    def test_the_kept_part_goes_through_the_same_validation_as_any_proposal(self):  # E6
        data = good()
        data["relationships"][9]["hint"] = "x"
        kept = triage(data)["kept"]
        items, refused = architect._items(kept, {"name": "x", "version": "0.1.0"}, ["brief"], {"generator": "test"})
        self.assertEqual((len(items), refused), (sum(len(kept[s]) for _, s in architect.SECTIONS), []))
        document = architect.apply({"name": "x", "version": "0.1.0"}, items)
        from autology.ontology import Ontology

        self.assertEqual(len(Ontology.from_dict(document).entities), 10)


class ReplayTests(unittest.TestCase):
    """E9: the stored proposals of the real evaluation, read under both policies."""

    RECORDED = {"global-logistics": ("rules", 1, "name_placeholder_removed"),
                "airline-disruption": ("relationships", 2, "name_hint_removed")}

    def stored(self):
        files = sorted(p for run in ("run1-original", "run2-after-correction") for p in (EVIDENCE / run).glob("*-[12].json"))
        self.assertEqual(len(files), 17)
        return files

    def test_every_stored_answer_is_accepted_unchanged(self):
        elements = 0
        for path in self.stored():
            data = as_answer(json.loads(path.read_text()))
            out = triage(data)
            self.assertEqual((out["decision"], out["rejected"]), ("accept", []), path.name)
            self.assertEqual(out["kept"], data)
            elements += out["audit"]["elements"]
        self.assertEqual(elements, 237)  # every element of the 17 stored answers was read

    def test_the_two_recorded_defects_cost_one_element_each_instead_of_the_answer(self):
        for case, (section, index, prop) in self.RECORDED.items():
            data = next(a for a in (as_answer(json.loads(p.read_text())) for p in self.stored() if p.name.startswith(case))
                        if len(a[section]) > index)  # a stored answer of that case with an element at that place
            data[section][index][prop] = True
            with self.subTest(case=case):
                refusal = in_force(data)  # today: everything is lost
                self.assertIsInstance(refusal, ProviderError)
                self.assertEqual(refusal.violations, [f"$.{section}[{index}]: unexpected {prop!r}"])
                out = triage(data)  # proposed: the named element, and what refers to it
                self.assertEqual(out["decision"], "accept_with_rejections")
                self.assertEqual((out["rejected"][0]["section"], out["rejected"][0]["index"], out["rejected"][0]["problems"]),
                                 (section, index, [f"$.{section}[{index}]: unexpected {prop!r}"]))
                # what refers to the rejected element goes with it, and says so; nothing else is touched
                self.assertTrue(all(r["reason"].startswith("refers to rejected") for r in out["rejected"][1:]))
                self.assertLessEqual(out["audit"]["rejected"], 2)
                self.assertEqual(out["audit"]["elements"] - out["audit"]["rejected"],
                                 sum(len(out["kept"][s]) for _, s in architect.SECTIONS))
                self.assertNotIn(prop, json.dumps(out["kept"]))


if __name__ == "__main__":
    unittest.main()
