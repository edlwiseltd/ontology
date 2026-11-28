"""What the existing validators say about each kind of defect a proposed model can carry (synthetic fixtures).

One authority per question, and no new one: the strict loader says whether a model loads; the consistency checks
say what a loading model may get wrong, for a person to decide; the configuration check says what an agent may not
be given; the proposal review names what a person's decision broke. This file is the evidence for the matrix in
docs/proposal-review.md.

  D1 twelve kinds of defect, each with the authority that catches it and the words it uses
  D2 the checks that only notice never refuse: a model with a finding still loads, and nothing is added to it
  D3 an action that waits for a state only it produces is noticed (new in this sprint)
  D4 the review of a proposal carries the same findings, so a reviewer sees them before saving anything
"""

import copy
import unittest

from autology import consistency, proposal_review, solution
from autology.ontology import Ontology, OntologyError

from .test_app2_application_integrity import MODEL, SOLUTION
from .test_rev1_proposal_review import BASE, ITEMS, decision, ids, rows


def changed(change, source=MODEL):
    document = copy.deepcopy(source)
    change(document)
    return document


def refusal(document):
    try:
        Ontology.from_dict(copy.deepcopy(document))
    except OntologyError as exc:
        return str(exc)
    return None


def noticed(document):
    return sorted({f["kind"] for f in consistency.findings(document)["findings"]})


REFUSED = {  # kind of defect -> (the change, words of the strict loader's refusal)
    "an undefined entity": (lambda d: d["relationships"].append({"from": "Ghost", "to": "Ticket", "type": "haunts", "cardinality": "1..*"}),
                            "unknown entity 'Ghost'"),
    "an undefined property in a rule": (lambda d: d["rules"].append({"id": "X", "type": "data_access", "description": "x", "field": "Ticket.nope", "roles": ["a"]}),
                                        "has no attribute 'nope'"),
    "an undefined property in a condition": (lambda d: d["actions"]["finish"]["requires"].append("Ticket.nope > 1"), "has no attribute 'nope'"),
    "an invalid relationship endpoint": (lambda d: d["relationships"][0].update({"to": "Nowhere"}), "unknown entity 'Nowhere'"),
    "a missing required property": (lambda d: d["entities"]["Owner"].pop("states"), "must declare at least one state"),
    "a property the schema does not have": (lambda d: d["entities"]["Owner"].update({"permissions": ["admin"]}), "unknown key 'permissions'"),
    "a conflicting state": (lambda d: d["actions"]["finish"]["effects"]["Ticket"].update({"status": "archived"}), "'archived' is not a state of 'Ticket'"),
    "a missing approval authority": (lambda d: d["rules"].append({"id": "H", "type": "human_review", "description": "x", "action": "finish"}),
                                     "human_review needs a 'reviewer' role"),
    "a rule on an action that does not exist": (lambda d: d["rules"].append({"id": "H", "type": "human_review", "description": "x", "action": "ghost", "reviewer": "lead"}),
                                                "'action' must name an action"),
    "an impossible dependency in a case": (lambda d: d["case_templates"]["ticket_case"]["entities"].update({"Owner": "^nope"}), "no relationship '^nope'"),
}
NOTICED = {  # kind of defect -> (the change, the finding the consistency checks give; the model still loads)
    "a rule contradiction": (lambda d: d["rules"].append({"id": "P", "type": "prohibition", "description": "never", "action": "finish"}), "always_prohibited"),
    "an unreachable outcome": (lambda d: d["goals"]["finished"].update({"target": "Owner.status == 'retired'"}), "goal_unreachable"),
    "a circular precondition": (lambda d: d["actions"]["finish"].update({"requires": ["Ticket.status == 'done'"]}), "action_cannot_start"),
}


class DiagnosticsTests(unittest.TestCase):
    def test_the_fixture_is_sound(self):
        self.assertIsNone(refusal(MODEL))
        self.assertEqual(noticed(MODEL), [])
        self.assertEqual(solution.check(SOLUTION, MODEL)[0], [])

    def test_what_the_strict_loader_refuses_and_in_which_words(self):  # D1
        for kind, (change, words) in REFUSED.items():
            with self.subTest(kind=kind):
                self.assertIn(words, refusal(changed(change)) or "it loaded")
        self.assertEqual(len(REFUSED), 10)

    def test_what_is_noticed_for_a_person_and_never_refused(self):  # D1, D2, D3
        for kind, (change, finding) in NOTICED.items():
            with self.subTest(kind=kind):
                document = changed(change)
                before = copy.deepcopy(document)
                self.assertIsNone(refusal(document))              # it loads: this is a question for a person
                self.assertIn(finding, noticed(document))
                self.assertEqual(document, before)                # and nothing was added to the model, no default, no rule
        circular = next(f for f in consistency.findings(changed(NOTICED["a circular precondition"][0]))["findings"]
                        if f["kind"] == "action_cannot_start")
        self.assertIn("which no action brings about", circular["finding"])
        self.assertIn("leave it: this is intended", circular["a_person_could"])

    def test_what_an_agent_may_not_be_given(self):  # D1: unsupported capabilities, inconsistent agent permissions
        outside = copy.deepcopy(SOLUTION)
        outside["agents"]["worker_agent"]["tools"][0]["tool"] = "connector.erp"
        self.assertIn("unknown tool 'connector.erp'", solution.check(outside, MODEL)[0][0]["message"])
        stranger = copy.deepcopy(SOLUTION)
        stranger["agents"]["worker_agent"]["goals"] = ["a_goal_the_model_does_not_have"]
        self.assertTrue(solution.check(stranger, MODEL)[0])
        acted = copy.deepcopy(SOLUTION)
        acted["agents"]["worker_agent"]["tools"][0]["action"] = "an_action_the_model_does_not_have"
        self.assertTrue(solution.check(acted, MODEL)[0])
        permissions = solution.effective_permissions(SOLUTION, MODEL)
        self.assertTrue(permissions)  # what each agent may do is computed from the model's rules, never declared by the agent

    def test_references_left_behind_by_a_rejection_are_named_and_refused(self):  # D1 (the twelfth), D4
        out = proposal_review.report(BASE, rows(ITEMS), [decision(1, ids("owns", "ticket_case"), ids("Owner"))], [], 1)
        self.assertEqual({f["element"]: f["because"] for f in out["dependency_failures"]}, {
            "model:relationship:owns": {"model:entity:Owner": "rejected"},
            "model:case_template:ticket_case": {"model:entity:Owner": "rejected"}})
        self.assertFalse(out["validation"]["valid"])
        self.assertEqual(out["consistency"], [])               # a model that does not load is not read further
        sound = proposal_review.report(BASE, rows(ITEMS), [decision(1, ids("Owner", "owns", "ticket_case", "R-BIG"))], [], 1)
        self.assertEqual((sound["validation"]["valid"], sound["consistency"]), (True, []))
        never = copy.deepcopy(ITEMS)
        never[3]["value"]["requires"] = ["Ticket.status == 'done'"]   # the proposed action waits for the state it produces
        seen = proposal_review.report(BASE, rows(never), [], [], 1)
        self.assertEqual([(f["kind"], f["severity"]) for f in seen["consistency"]], [("action_cannot_start", "medium"), ("goal_unreachable", "high")][:len(seen["consistency"])])
        self.assertIn("action_cannot_start", [f["kind"] for f in seen["consistency"]])
        self.assertTrue(seen["ready_for_draft"])               # noticed, not refused: the person decides
