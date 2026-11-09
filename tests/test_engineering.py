"""Ontology engineering: modules, competency questions, lint, export, versioning."""

import json
import tempfile
import unittest
from pathlib import Path

from autology import Ontology, OntologyError
from autology.export import to_jsonld, to_turtle
from autology.graph import KnowledgeGraph
from autology.lint import lint
from autology.ontology import load_document
from autology.versioning import OntologyRegistry, VersionError, check_release, diff, required_bump

from .helpers import MFG, MFG_ONTOLOGY, ONTOLOGY_PATH, load_doc, manufacturing_tools


def write(tmp: Path, name: str, doc: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(doc))
    return path


class ModuleTests(unittest.TestCase):
    def test_enterprise_composes_modules_once(self):
        onto = Ontology.load(MFG_ONTOLOGY)
        self.assertEqual(onto.modules, ("core@1.0.0", "procurement@1.0.0", "production@1.0.0", "quality@1.0.0"))
        self.assertIn("Contract", onto.entities)  # from core, imported by three modules
        self.assertEqual(len([r for r in onto.relationships if r.kind == "hasSupplier"]), 1)
        self.assertIn("R-QUAL-001", {r.id for r in onto.rules})

    def test_conflicting_definitions_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            write(tmp, "a.json", {"name": "a", "version": "1.0.0", "entities": {"X": {"states": ["s"]}}})
            write(tmp, "b.json", {"name": "b", "version": "1.0.0", "entities": {"X": {"states": ["t"]}}})
            root = write(tmp, "root.json", {"name": "r", "version": "1.0.0", "imports": ["a.json", "b.json"]})
            with self.assertRaisesRegex(OntologyError, "redefines entity 'X'"):
                Ontology.load(root)

    def test_circular_imports_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            write(tmp, "a.json", {"name": "a", "imports": ["b.json"]})
            write(tmp, "b.json", {"name": "b", "imports": ["a.json"]})
            with self.assertRaisesRegex(OntologyError, "circular import"):
                Ontology.load(tmp / "a.json")


class CompetencyTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(MFG_ONTOLOGY)
        self.graph = KnowledgeGraph.from_dict(self.onto, json.loads((MFG / "data.json").read_text()))

    def test_all_questions_answered_as_expected(self):
        report = self.graph.check_competency()
        self.assertEqual(len(report), 6)
        for q, answer, ok in report:
            with self.subTest(q.id):
                self.assertTrue(ok, f"{q.id} answered {answer}")

    def test_parameters_override(self):
        self.assertEqual(self.graph.ask("CQ-02", line="PL-3").answer, ["S-Z"])
        self.assertEqual(self.graph.ask("CQ-01", horizon="2027-07-01").answer, ["C-101", "C-104"])

    def test_graph_enforces_ontology(self):
        with self.assertRaises(OntologyError):
            self.graph.add("Spaceship", "X-1")
        with self.assertRaises(OntologyError):
            self.graph.add("Supplier", "S-Q", shoe_size=3)
        with self.assertRaises(OntologyError):
            self.graph.add("Supplier", "S-Q", status="bankrupt")
        with self.assertRaises(OntologyError):
            self.graph.link("S-X", "manufactures", "P-A")  # wrong direction / types

    def test_invalid_question_rejected_at_load(self):
        doc = load_document(MFG_ONTOLOGY)
        doc["competency_questions"].append({"id": "CQ-BAD", "find": "Supplier", "follow": ["flies_to"]})
        with self.assertRaises(OntologyError):
            Ontology.from_dict(doc)
        doc["competency_questions"][-1] = {"id": "CQ-BAD", "find": "Supplier", "where": "Contract.value > 1"}
        with self.assertRaisesRegex(OntologyError, "may only reference Supplier"):
            Ontology.from_dict(doc)


class LintTests(unittest.TestCase):
    def codes(self, doc, tools=None):
        return {f.code for f in lint(Ontology.from_dict(doc), tools)}

    def test_security_and_bias_findings(self):
        doc = load_doc()
        doc["rules"] = [r for r in doc["rules"] if r["id"] != "R-PII-001"]
        doc["entities"]["Customer"]["attributes"]["founder_gender"] = {"type": "string", "sensitivity": "protected"}
        doc["rules"].append({"id": "R-BIAS", "type": "human_review", "action": "sign_contract", "reviewer": "x",
                             "when": "Customer.founder_gender == 'female'"})
        codes = self.codes(doc)
        self.assertIn("SEC001", codes)  # tax_id (pii) unguarded
        self.assertIn("BIAS001", codes)

    def test_tool_coverage(self):
        onto = Ontology.load(MFG_ONTOLOGY)
        findings = lint(onto, manufacturing_tools.quality_tools())
        self.assertTrue(any(f.code == "TOOL001" and "mes.start" in f.message for f in findings))

    def test_examples_are_clean_of_warnings(self):
        for path in (ONTOLOGY_PATH, MFG_ONTOLOGY):
            with self.subTest(path.name):
                levels = {f.level for f in lint(Ontology.load(path))}
                self.assertNotIn("error", levels)
                self.assertNotIn("warning", levels)


class ExportTests(unittest.TestCase):
    def test_jsonld_structure(self):
        onto = Ontology.load(MFG_ONTOLOGY)
        doc = to_jsonld(onto)
        types = {}
        for node in doc["@graph"]:
            t = node["@type"]
            for x in (t if isinstance(t, list) else [t]):
                types[x] = types.get(x, 0) + 1
        self.assertGreaterEqual(types["owl:Class"], len(onto.entities))
        self.assertEqual(types["autology:Rule"], len(onto.rules))
        self.assertEqual(types["autology:CompetencyQuestion"], 6)
        json.dumps(doc)  # serialisable

    def test_turtle_mentions_every_entity(self):
        ttl = to_turtle(Ontology.load(ONTOLOGY_PATH))
        for entity in ("Customer", "Contract", "Order", "BillingAccount"):
            self.assertIn(f":{entity} a owl:Class", ttl)


def drop_sku(doc):
    doc["entities"]["Order"]["attributes"].pop("sku")
    doc["actions"]["place_order"]["reads"].remove("Order.sku")


class VersioningTests(unittest.TestCase):
    def v(self, version, mutate=None):
        doc = load_doc()
        doc["version"] = version
        if mutate:
            mutate(doc)
        return Ontology.from_dict(doc)

    def test_change_classification(self):
        base = self.v("1.0.0")
        removed = self.v("2.0.0", drop_sku)
        self.assertEqual(required_bump(diff(base, removed)), "major")
        added = self.v("1.1.0", lambda d: d["entities"]["Order"]["attributes"].update(qty="integer"))
        self.assertEqual(required_bump(diff(base, added)), "minor")
        policy = self.v("1.1.0", lambda d: d["rules"].pop())
        self.assertEqual([c.kind for c in diff(base, policy)], ["rule.removed"])
        wording = self.v("1.0.1", lambda d: d["actions"]["place_order"].update(description="Place it"))
        self.assertEqual(required_bump(diff(base, wording)), "patch")
        self.assertIsNone(required_bump(diff(base, self.v("1.0.0"))))

    def test_release_check(self):
        base = self.v("1.0.0")
        with self.assertRaises(VersionError):
            check_release(base, self.v("1.0.1", drop_sku))
        check_release(base, self.v("2.0.0", drop_sku))

    def test_registry(self):
        reg = OntologyRegistry()
        reg.publish(self.v("1.0.0"))
        with self.assertRaises(VersionError):
            reg.publish(self.v("1.0.0"))  # duplicate
        with self.assertRaises(VersionError):
            reg.publish(self.v("1.0.1", lambda d: d["entities"]["Order"]["attributes"].update(qty="integer")))
        reg.publish(self.v("1.1.0", lambda d: d["entities"]["Order"]["attributes"].update(qty="integer")))
        self.assertEqual(reg.latest("customer-onboarding").version, "1.1.0")
        reg.withdraw("customer-onboarding", "1.1.0")
        self.assertEqual(reg.latest("customer-onboarding").version, "1.0.0")
        with self.assertRaises(KeyError):
            reg.get("customer-onboarding", "1.1.0")


if __name__ == "__main__":
    unittest.main()
