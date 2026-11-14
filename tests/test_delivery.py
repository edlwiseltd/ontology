"""Tier 3 delivery: online backups, the --store override, and the packaging the Docker image relies on."""

import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from autology import __version__
from autology.__main__ import main as cli
from autology.server import AutologyService
from autology.store import Store, StoreError

from .helpers import ROOT
from .test_ingest import EX, TOKENS, service


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()  # automations on: loading the feed settles CL-4 in a governed run
        etl = next(u for u in self.svc.users if u.name == "etl")
        self.svc.run_pipeline(etl, "claims_feed", {})
        self.dir = Path(tempfile.mkdtemp())

    def test_consistent_verified_copy_while_live(self):
        out = self.svc.store.backup(self.dir / "b" / "backup.db")
        self.assertEqual((out["runs"], out["unverified_runs"], out["schema"]), (1, [], 11))
        self.assertEqual([p.name for p in (self.dir / "b").iterdir()], ["backup.db"])  # one file, no temporaries
        copy = Store(self.dir / "b" / "backup.db")
        self.addCleanup(copy.close)
        self.assertEqual(copy.load_graph(self.svc.ontology).get("CL-4").attributes["status"], "paid")
        self.assertEqual(copy.lineage("CL-4")[0]["pipeline"], "claims_feed")
        with self.assertRaises(StoreError):
            self.svc.store.backup(self.svc.store.path)

    def test_backup_reports_tampered_audit(self):
        db = self.svc.store._db
        db.execute("DROP TRIGGER audit_no_update")  # someone with file access edits the history
        db.execute("UPDATE audit SET data = '{\"outcome\": \"fraud\"}' WHERE seq = 1")
        out = self.svc.store.backup(self.dir / "backup.db")
        self.assertEqual(len(out["unverified_runs"]), 1)

    def test_cli(self):
        for name, token in TOKENS.items():
            os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
        path = EX / f"_test_backup_{os.getpid()}.json"
        path.write_text((EX / "server.json").read_text())
        self.addCleanup(path.unlink)
        with redirect_stdout(io.StringIO()) as out:
            code = cli(["backup", str(path), str(self.dir / "cli.db"), "--store", self.svc.store.path])
        self.assertEqual(code, 0)
        self.assertIn("every audit chain verifies", out.getvalue())
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli(["backup", str(path), self.svc.store.path, "--store", self.svc.store.path]), 1)
        self.assertIn("must not overwrite the live store", err.getvalue())
        self.svc.store._db.execute("DROP TRIGGER audit_no_update")
        self.svc.store._db.execute("UPDATE audit SET data = '{}' WHERE seq = 1")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(cli(["backup", str(path), str(self.dir / "bad.db"), "--store", self.svc.store.path]), 2)
        self.assertIn("do not verify", err.getvalue())


class StoreOverrideTests(unittest.TestCase):
    def test_store_path_from_the_command_line(self):
        for name, token in TOKENS.items():
            os.environ[f"AUTOLOGY_TOKEN_{name.upper()}"] = token
        target = Path(tempfile.mkdtemp()) / "volume" / "autology.db"
        target.parent.mkdir()
        svc = AutologyService.from_file(str(EX / "server.json"), str(target))
        self.assertEqual(Path(svc.store.path), target.resolve())
        self.assertEqual(sqlite3.connect(target).execute("SELECT COUNT(*) FROM instances").fetchone()[0], 14)


class PackagingTests(unittest.TestCase):
    def test_versions_and_package_data_agree(self):
        text = (ROOT / "pyproject.toml").read_text()
        self.assertIn(f'version = "{__version__}"', text)
        self.assertIn('autology = ["static/*", "console_static/*"]', text)  # the inbox and the console ship inside
        for folder, names in (("static", ("index.html", "app.js", "app.css")),
                              ("console_static", ("index.html", "console.js", "commands.js", "console.css"))):
            for name in names:
                self.assertTrue((ROOT / "autology" / folder / name).exists(), f"{folder}/{name}")

    def test_dockerfile_runs_unprivileged_with_a_healthcheck(self):
        text = (ROOT / "Dockerfile").read_text()
        self.assertIn("USER autology", text)
        self.assertIn("HEALTHCHECK", text)
        self.assertIn('"--store", "/data/autology.db"', text)
        self.assertIn("required=false", text)  # the proxy CA secret is optional and never stored in the image


if __name__ == "__main__":
    unittest.main()
