"""LEG-1 (owner decision D5): Autology is proprietary, and every third-party component is inventoried with
the licence its own metadata states, under an allowed licence."""

import json
import re
import unittest
from importlib import metadata

from .helpers import ROOT

INVENTORY = json.loads((ROOT / "deploy" / "third_party_licences.json").read_text())
PACKAGES = INVENTORY["packages"]


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def family(text: str) -> str:
    """The licence family of a metadata licence string or classifier."""
    t = text.lower()
    if re.search(r"\bagpl|affero|\bgpl\b|gnu general public", t) and "lesser" not in t and "lgpl" not in t:
        return "strong-copyleft"
    if "lgpl" in t or "lesser general public" in t or "mpl" in t or "mozilla" in t:
        return "weak-copyleft"
    if re.search(r"\bmit\b|bsd|apache|psf|python software foundation|isc|zlib|0bsd|cc0|mit-0|dual license", t):
        return "permissive"
    return "unknown"


def declared():
    """Every component the project declares: pyproject extras, the CI workflow's and the image's installs."""
    names = set()
    pyproject = (ROOT / "pyproject.toml").read_text()
    for spec in re.findall(r'"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?[^"]*"', pyproject.split("[project.optional-dependencies]")[1]
                           .split("[project.scripts]")[0]):
        names.add(norm(spec))
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in path.read_text().splitlines():
            if "pip install" in line:
                for spec in re.findall(r'"([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==', line):
                    names.add(norm(spec))
    return names


def installed_closure(roots):
    seen = {}

    def walk(name):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            return
        key = norm(dist.metadata["Name"])
        if key in seen:
            return
        seen[key] = dist
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            walk(re.split(r"[ ;<>=!~\[(]", req, maxsplit=1)[0])

    for root in roots:
        walk(root)
    return seen


class LicenceTests(unittest.TestCase):
    def test_autology_is_proprietary(self):
        text = (ROOT / "LICENSE").read_text()
        self.assertIn("All rights reserved", text)
        self.assertIn("proprietary", text.lower())
        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertIn('license = {text = "Proprietary. See LICENSE."}', pyproject)
        self.assertIn("License :: Other/Proprietary License", pyproject)
        self.assertIn("Private :: Do Not Upload", pyproject)  # PyPI refuses an accidental public upload

    def test_no_source_file_claims_an_open_source_licence(self):
        for path in list((ROOT / "autology").rglob("*.py")) + list((ROOT / "autology").rglob("*.js")):
            with self.subTest(path.name):
                head = path.read_text(encoding="utf-8")[:2000]
                self.assertNotRegex(head, r"SPDX-License-Identifier|MIT License|Apache License|GNU General")

    def test_every_declared_component_is_inventoried(self):
        missing = sorted(declared() - set(PACKAGES))
        self.assertEqual(missing, [], "add them to deploy/third_party_licences.json and THIRD_PARTY_NOTICES.md")

    def test_installed_dependencies_match_the_inventory_and_the_policy(self):
        closure = installed_closure(declared() | {"openpyxl"})
        self.assertTrue(closure)  # at least some declared components are installed here
        allowed = set(INVENTORY["_policy"]["allowed"]) | set(INVENTORY["_policy"]["needs_legal_review"])
        for name, dist in sorted(closure.items()):
            with self.subTest(name):
                self.assertTrue(name in PACKAGES, f"{name} is installed by a declared component but not inventoried")
                meta = dist.metadata
                stated = " ".join(filter(None, [meta.get("License-Expression"), (meta.get("License") or "")[:200]]
                                         + [c for c in (meta.get_all("Classifier") or []) if c.startswith("License")]))
                self.assertEqual(family(stated), PACKAGES[name]["family"], stated)
                self.assertIn(PACKAGES[name]["family"], allowed)
                if PACKAGES[name]["family"] != "permissive":
                    self.assertTrue(PACKAGES[name].get("review"), f"{name} needs a recorded legal-review note")

    def test_the_notices_list_every_inventoried_component(self):
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
        for name in PACKAGES:
            self.assertIn(f"| {name} |", notices)
        self.assertIn("COPY LICENSE THIRD_PARTY_NOTICES.md", (ROOT / "Dockerfile").read_text())


if __name__ == "__main__":
    unittest.main()
