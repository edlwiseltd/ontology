"""MOD-1 (audit GAP-016): a misspelled key or an unknown type in an ontology is an error, never silently ignored."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from autology import Ontology, OntologyError
from autology.ontology import json_schema

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted(p for p in (ROOT / "examples").glob("*/*.json")
                  if p.name in ("ontology.json", "enterprise.json"))
CLAIMS = ROOT / "examples" / "auto_insurance" / "ontology.json"


def misspell(key: str) -> str:
    return key[:-1] + key[-1].upper() if key[-1].isalpha() else key + "x"


def paths_of(doc):
    """Every (container path, key) in an ontology document that the strict schema checks."""
    out = []

    def mapping(path, value):
        if isinstance(value, dict):
            for k in value:
                out.append((path, k))

    mapping((), doc)
    mapping(("settings",), doc.get("settings") or {})
    for kind in ("entities", "interfaces"):
        for name, spec in (doc.get(kind) or {}).items():
            mapping((kind, name), spec)
            for aname, aspec in (spec.get("attributes") or {}).items():
                mapping((kind, name, "attributes", aname), aspec)
    for name, spec in (doc.get("actions") or {}).items():
        mapping(("actions", name), spec)
        mapping(("actions", name, "on_failure"), spec.get("on_failure") or {})
        for oname, ospec in (spec.get("outcomes") or {}).items():
            mapping(("actions", name, "outcomes", oname), ospec)
    for kind in ("goals", "functions", "case_templates"):
        for name, spec in (doc.get(kind) or {}).items():
            mapping((kind, name), spec)
    for kind in ("rules", "relationships", "competency_questions", "impact_rules"):
        for i, spec in enumerate(doc.get(kind) or []):
            mapping((kind, i), spec)
    return out


def get(doc, path):
    for p in path:
        doc = doc[p]
    return doc


class StrictSchemaTests(unittest.TestCase):
    def test_every_example_still_loads(self):
        self.assertTrue(EXAMPLES)
        for path in EXAMPLES:
            with self.subTest(path.name, folder=path.parent.name):
                Ontology.load(path)

    def test_the_audit_case_requries_is_refused(self):
        doc = json.loads(CLAIMS.read_text())
        action = next(a for a in doc["actions"].values() if a.get("requires"))
        action["requries"] = action.pop("requires")
        with self.assertRaises(OntologyError) as cm:
            Ontology.from_dict(doc)
        self.assertIn("requries", str(cm.exception))
        self.assertIn("did you mean 'requires'", str(cm.exception))

    def test_every_key_misspelled_once_fails_with_its_path(self):
        checked = 0
        for path in EXAMPLES:
            base = json.loads(path.read_text())
            if "imports" in base:
                continue  # modules are checked file by file below
            for container, key in paths_of(base):
                if key in ("$schema",):
                    continue
                doc = copy.deepcopy(base)
                target = get(doc, container)
                target[misspell(key)] = target.pop(key)
                with self.subTest(file=path.parent.name, at=".".join(map(str, container)), key=key):
                    with self.assertRaises(OntologyError) as cm:
                        Ontology.from_dict(doc)
                    message = str(cm.exception)
                    self.assertIn(misspell(key), message)
                    if container:
                        self.assertIn(".".join(map(str, container)), message)
                checked += 1
        self.assertGreater(checked, 400)

    def test_unknown_attribute_types_are_refused(self):
        doc = json.loads(CLAIMS.read_text())
        entity = next(iter(doc["entities"].values()))
        name = next(iter(entity["attributes"]))
        entity["attributes"][name] = "nmber"
        with self.assertRaises(OntologyError) as cm:
            Ontology.from_dict(doc)
        self.assertIn("nmber", str(cm.exception))

    def test_rule_keys_depend_on_the_rule_type(self):
        doc = json.loads(CLAIMS.read_text())
        rule = next(r for r in doc["rules"] if r["type"] == "human_review")
        rule["roles"] = ["x"]  # valid for access rules, meaningless on a review rule
        with self.assertRaises(OntologyError) as cm:
            Ontology.from_dict(doc)
        self.assertIn("roles", str(cm.exception))

    def test_a_misspelled_key_in_an_imported_module_is_refused(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "module.json").write_text(json.dumps({"name": "m", "entitis": {}}))
        (folder / "root.json").write_text(json.dumps({"name": "r", "imports": ["module.json"], "entities": {
            "A": {"states": ["new"], "attributes": {}}}}))
        with self.assertRaises(OntologyError) as cm:
            Ontology.load(folder / "root.json")
        self.assertIn("entitis", str(cm.exception))

    def test_extension_keys_are_allowed(self):
        doc = json.loads(CLAIMS.read_text())
        doc["$schema"] = "https://example.invalid/autology.schema.json"
        next(iter(doc["entities"].values()))["x-owner"] = "claims team"
        Ontology.from_dict(doc)

    def test_the_published_json_schema_matches_the_loader(self):
        published = json.loads((ROOT / "docs" / "ontology.schema.json").read_text())
        self.assertEqual(published, json_schema())


if __name__ == "__main__":
    unittest.main()
