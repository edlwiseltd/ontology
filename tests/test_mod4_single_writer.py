"""MOD-4 (audit GAP-018): one writer per store, so a server's in-memory graph never silently diverges."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from autology.server import AutologyService
from autology.store import Store

from .test_ingest import EX, TOKENS
from .helpers import ROOT


def config(store):
    cfg = json.loads((EX / "server.json").read_text())
    cfg.update(store=str(store), automations={})
    return cfg


class SingleWriterTests(unittest.TestCase):
    def setUp(self):
        os.environ.update({f"AUTOLOGY_TOKEN_{n.upper()}": t for n, t in TOKENS.items()})
        self.store = Path(tempfile.mkdtemp()) / "claims.db"
        self.svc = AutologyService(config(self.store), EX)

    def fake_holder(self, pid, age=0.0):
        """Make the lease look held by another process."""
        self.svc.store._db.execute("UPDATE writer_lease SET instance='other', pid=?, heartbeat=? WHERE id=1",
                                   (pid, time.time() - age))

    def test_a_cli_ingest_next_to_a_running_server_is_refused(self):
        # a real second process: the CLI, while this process holds the store as its server
        cfg = Path(tempfile.mkdtemp()) / "server.json"
        cfg.write_text(json.dumps({**config(self.store), "ontology": str(EX / "ontology.json"),
                                   "data": str(EX / "data.json"),
                                   "agents": {k: {**v, "tools": str(EX / v["tools"])}
                                              for k, v in config(self.store)["agents"].items()},
                                   "pipelines": {k: str(EX / v) for k, v in config(self.store)["pipelines"].items()}}))
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        proc = subprocess.run([sys.executable, "-m", "autology", "ingest", str(cfg), "claims_feed"],
                              capture_output=True, text=True, env=env, timeout=120)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("in use by another Autology process", proc.stderr)
        self.assertIn(f"pid {os.getpid()}", proc.stderr)
        self.assertEqual(self.svc.store.count_instances(), len(self.svc.graph._instances))  # nothing diverged

    def test_a_second_server_on_the_same_store_is_refused(self):
        self.fake_holder(os.getppid())  # a live process
        with self.assertRaises(ValueError) as cm:
            AutologyService(config(self.store), EX)
        self.assertIn("one writer per store", str(cm.exception))

    def test_a_crashed_holder_does_not_block_a_restart(self):
        self.fake_holder(os.getppid(), age=10 ** 6)  # heartbeat long expired
        AutologyService(config(self.store), EX)
        dead = 2 ** 22 + 12345  # no such process on this host
        self.fake_holder(dead)
        AutologyService(config(self.store), EX)

    def test_a_server_that_stops_cleanly_frees_the_store_at_once(self):
        # a container restarted on the same volume gets a new hostname: it must not wait for the lease to expire
        self.svc.close()
        self.assertIsNone(Store(self.store).lease())
        other = dict(config(self.store))
        with unittest.mock.patch("socket.gethostname", return_value="another-container"):
            AutologyService(other, EX)

    def test_the_refusal_says_when_a_crashed_holders_lease_expires(self):
        self.fake_holder(os.getppid())
        with self.assertRaises(ValueError) as cm:
            AutologyService(config(self.store), EX)
        self.assertIn("the store is freed at", str(cm.exception))

    def test_read_only_tools_run_next_to_the_server(self):
        self.fake_holder(os.getppid())
        cfg = dict(config(self.store), writer=False)
        reader = AutologyService(cfg, EX)  # backup and reporting open the store this way
        self.assertEqual(reader.store.lease()["instance"], "other")  # it did not take the lease

    def test_the_scheduler_keeps_the_lease_alive(self):
        before = self.svc.store.lease()["heartbeat"]
        time.sleep(0.01)
        self.svc.tick()
        self.assertGreater(self.svc.store.lease()["heartbeat"], before)


if __name__ == "__main__":
    unittest.main()
