"""Review item 14: breaking ontology changes are detected, and releases are checked against every version."""

import copy
import json
import unittest

from autology import Ontology
from autology.versioning import OntologyRegistry as Registry, VersionError, diff, required_bump

from .test_platform import EX

DOC = json.loads((EX / "ontology.json").read_text())
# isolated pieces: an entity and an action that nothing else refers to, so each can change alone
DOC["entities"]["Note"] = {"states": ["open"], "attributes": {"text": "string"}}
DOC["actions"]["tag_order"] = {"for_each": "Order", "capability": "crm.tag"}


def changed(mutate, version="1.1.0"):
    doc = copy.deepcopy(DOC)
    mutate(doc)
    doc["version"] = version
    return Ontology.from_dict(doc)


class BreakingChangeTests(unittest.TestCase):
    def setUp(self):
        self.old = Ontology.from_dict(DOC)

    def level(self, mutate):
        return required_bump(diff(self.old, changed(mutate)))

    def test_major_changes(self):
        def card(d):
            d["relationships"][1]["cardinality"] = "1"

        def template_root(d):
            d["case_templates"]["contract_case"] = {"root": "Customer", "entities": {
                "Customer": "self", "Contract": "hasContract", "Order": "hasContract.covers"}}

        def template_entities(d):
            d["case_templates"]["contract_case"]["entities"].pop("Customer")

        def iface_type(d):
            d["interfaces"]["Regional"]["attributes"]["region"] = "integer"
            for e in ("Customer", "Order"):
                d["entities"][e]["attributes"]["region"] = "integer"

        def for_each(d):
            d["actions"]["tag_order"].pop("for_each")

        def multiple(d):
            d["entities"]["Note"]["multiple"] = True

        def downgrade(d):
            d["entities"]["Customer"]["attributes"]["credit_limit"] = {"type": "number"}

        cases = {"cardinality": card, "template root": template_root, "template entities": template_entities,
                 "interface attribute type": iface_type, "for_each": for_each, "multiple": multiple,
                 "sensitivity removed": downgrade}
        for label, mutate in cases.items():
            with self.subTest(label):
                self.assertEqual(self.level(mutate), "major", [c.kind for c in diff(self.old, changed(mutate))])

    def test_adding_sensitivity_stays_minor(self):
        def tighten(d):
            d["entities"]["Order"]["attributes"]["amount"] = {"type": "number", "sensitivity": "confidential"}

        self.assertEqual(self.level(tighten), "minor")


class RegistryTests(unittest.TestCase):
    def test_withdrawn_versions_still_bound_the_next_release(self):
        def narrower_goal(d):
            d["goals"]["fulfil_contract"]["target"] = "Contract.status == 'signed'"

        reg = Registry()
        reg.publish(Ontology.from_dict(DOC))  # 1.1.0
        reg.publish(changed(narrower_goal, version="2.0.0"))  # a breaking change
        reg.withdraw("order-fulfilment", "2.0.0")
        with self.assertRaises(VersionError):  # lower than a version that was published, even if withdrawn
            reg.publish(changed(lambda d: None, version="1.2.0"))
        # 2.0.1 restores the 1.1.0 goal: against 1.1.0 nothing changed, but against 2.0.0 (which consumers
        # may have pinned before it was withdrawn) the goal changed again, a breaking change
        with self.assertRaises(VersionError):
            reg.publish(changed(lambda d: None, version="2.0.1"))
        reg.publish(changed(lambda d: None, version="3.0.0"))


if __name__ == "__main__":
    unittest.main()
