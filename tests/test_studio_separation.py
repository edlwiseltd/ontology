"""Studio is a separate application (Next.js, studio/web): the engine never depends on it, it is not shipped in
the engine's package, and it reaches Autology through the platform's HTTP API only. Studio's own tests
(studio/web: Vitest and Playwright browser tests) check the client side; these check the engine side."""

import ast
import json
import re
import unittest

from .helpers import ROOT

WEB = ROOT / "studio" / "web"


class StudioSeparationTests(unittest.TestCase):
    def test_the_engine_never_imports_or_serves_studio(self):
        for f in sorted((ROOT / "autology").glob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            self.assertNotIn("studio", names, f.name)

    def test_studio_is_not_in_the_engine_package(self):
        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertIn('packages = ["autology"]', pyproject)
        self.assertNotIn("studio", pyproject)
        self.assertFalse(list((ROOT / "studio").glob("*.py")))  # no Python left in Studio

    def test_studio_is_its_own_application(self):
        pkg = json.loads((WEB / "package.json").read_text())
        self.assertTrue(pkg["private"])
        self.assertIn("next", pkg["dependencies"])
        for name, version in {**pkg["dependencies"], **pkg["devDependencies"]}.items():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$", f"{name} must be pinned to an exact version")
        self.assertTrue((WEB / "package-lock.json").exists())

    def test_studio_reaches_the_platform_only_through_its_relay(self):
        relay = (WEB / "lib" / "forward.ts").read_text()
        self.assertIn('FORWARDED_PREFIXES = ["/platform/", "/w/"]', relay)
        # exactly three headers, and no other: the two it always forwarded, and the configuration a request was
        # written for (the Application Builder; the Engine refuses the request when another configuration runs)
        self.assertIn('FORWARDED_HEADERS = ["authorization", "content-type", "x-autology-configuration"]', relay)
        self.assertIn('redirect: "manual"', relay)
        routes = sorted(p.relative_to(WEB / "app").parts[0] for p in (WEB / "app").rglob("route.ts"))
        self.assertEqual(routes, ["platform", "w"])
        config = (WEB / "next.config.ts").read_text()
        self.assertTrue(re.search(r"connect-src 'self'", config) and "frame-ancestors 'none'" in config)


if __name__ == "__main__":
    unittest.main()
