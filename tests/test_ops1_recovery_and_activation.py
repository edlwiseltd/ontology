"""R2 reliability sprint, increment C: platform backup and restore (GAP-033), release activation without restarts.

Recovery (executed, not described)
  B1 a backup taken while people and schedulers write is consistent: it verifies, restores into another directory,
     and a second platform starts on it while the first keeps running (an isolated restore drill)
  B2 after the restore, tenant mappings, members, approved grants, token lifetimes and revocations, releases,
     stages, runs and every audit chain are there and verify; the two platforms do not influence each other
  B3 copying the live database file is *not* a backup: it misses committed data the online backup contains
  B4 a damaged, incomplete, extended or foreign-key backup is refused and nothing is put in place; an existing data
     directory is never overwritten; the source backup is only read
  B5 a failure in the middle of a backup or of a restore leaves no partial result and does not touch the source
  B6 a source whose chain was changed is not backed up as if it were good
  B7 secrets are left out unless asked for; the backup is private (0700/0600)
  B8 the commands (``platform-backup``, ``platform-verify``, ``platform-restore``) do the same

Activation
  A1 an approved release becomes active with one call: no restart, no reload, no manual stage steps; activating an
     older approved release is a one-step rollback that restores its model; approvals are never rewritten
  A2 a failed activation (the engine does not build, the registry refuses, the deployed files differ from the
     release) puts back the model and the engine that ran before; the previous release stays active
  A3 if even the previous configuration cannot be loaded, the use case serves nothing (503), other use cases are
     unaffected, and a reload brings it back
  A4 requests never see an intermediate configuration while releases are switched under load
  A5 a switch waits for requests in flight and gives up rather than cut them; requests wait for a switch
  A6 pilot is never granted automatically, production never at all; only authorised people activate
  A7 the scheduler does not tick while its engine is switched
"""

import json
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from autology import recovery
from autology.__main__ import main as cli
from autology.platform import Platform
from autology.releases import ReleaseError

from .test_adm1_administration import AdminBase, WS
from .test_r2_use_case_lifecycle import close
from .test_workspaces import Client, EX, data_admins

UC = "/platform/v1/workspaces/acme/use-cases/claims"
ENGINE = "/w/acme/u/claims/api/v1"
# a reported claim: loading one also starts its settlement run (an automation), so every write below is a record,
# a run and an audit chain
CLAIM = {"type": "Claim", "attributes": {"amount": 5, "status": "reported", "damage_type": "x",
                                         "reported_days_after": 1}}


class Base(AdminBase):
    def spec(self, data_dir=None):
        spec = data_admins(json.loads((EX / "platform.json").read_text()))
        spec["data_dir"] = data_dir or self.data_dir
        spec["workspaces"]["acme"]["use_cases"]["claims"]["config"] = str(self.config_dir / "server.json")
        return spec

    def release(self, note, activate=True):
        status, r = self.call("POST", f"{UC}/releases", body={"note": note})
        self.assertEqual(status, 201, r)
        self.assertEqual(self.call("POST", f"{UC}/releases/{r['number']}/approve", "acme-maria", {"reason": "ok"})[0], 200)
        if activate:
            status, out = self.call("POST", f"{UC}/releases/{r['number']}/activate", body={"reason": "go"})
            self.assertEqual(status, 200, out)
        return r["number"]

    def publish(self, text):
        _, draft = self.call("GET", f"{ENGINE}/model/draft")
        doc = json.loads(json.dumps(draft["document"]))
        doc["entities"]["Claim"]["description"] = text
        status, saved = self.call("POST", f"{ENGINE}/model/draft", body={
            "document": doc, "expected_revision": draft["revision"], "note": text})
        self.assertEqual(status, 200, saved)
        status, out = self.call("POST", f"{UC}/publish-draft", "acme-maria", {"revision": saved["revision"],
                                                                              "reason": text})
        self.assertEqual(status, 200, out)

    def model_text(self):
        """The description in the model that is in force (not in a draft)."""
        return self.pf.workspaces["acme"].use_cases["claims"].service.ontology.entities["Claim"].description

    def run_claim(self, root="CL-1"):
        return self.call("POST", f"{ENGINE}/runs", "acme-hana", {"case_template": "claim_case", "root": root})

    def view(self):
        return self.call("GET", UC)[1]


class RecoveryTests(Base):
    def populate(self):
        """Governance and data worth losing: a member with an approved grant, a replaced token, an active release,
        a completed run."""
        zoe = self.add("zoe")
        _, g = self.propose("zoe", ["read"])
        self.assertEqual(self.call("POST", f"{WS}/grants/{g['id']}/approve", "acme-maria", {"reason": "ok"})[0], 200)
        _, gone = self.call("POST", f"{WS}/members", body={"name": "temp", "reason": "short stay"})
        self.assertEqual(self.call("POST", f"{WS}/members/temp/revoke-token", body={"reason": "left"})[0], 200)
        self.release("as configured")
        status, run = self.run_claim()
        self.assertEqual((status, run["status"]), (200, "completed"), run)
        return zoe, gone["token"], run["run_id"]

    def second_platform(self, data_dir):
        pf = Platform(self.spec(str(data_dir)), EX)
        client = Client(pf)

        def stop():
            client.server.shutdown()
            client.server.server_close()
            close(pf)
        self.addCleanup(stop)
        return pf, client

    def test_a_backup_under_write_activity_restores_into_an_isolated_platform(self):  # B1, B2
        zoe, revoked, run_id = self.populate()
        out = Path(tempfile.mkdtemp()) / "backup"
        stop, written, errors = threading.Event(), [], []

        def writer():  # an administrator keeps loading records while the backup runs
            n = 0
            while not stop.is_set() and n < 400:
                n += 1
                status, out = self.call("POST", f"{ENGINE}/objects", body={**CLAIM, "id": f"CL-W{n}"})
                (written if status == 200 else errors).append((n, status) if status != 200 else n)
        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        while not written and not errors:
            time.sleep(0.01)
        seen = []

        def during(path):  # between the stores and the registries: governance changes too
            seen.append(path)
            if path == "tenancy.db":
                self.assertEqual(self.call("POST", f"{WS}/members", body={"name": "late", "reason": "x"})[0], 201)
            time.sleep(0.05)
        try:
            result = recovery.backup(self.data_dir, out, on_file=during)
        finally:
            stop.set()
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertGreater(len(written), 3, "the store was being written during the backup")
        self.assertLess(seen.index("acme/claims/autology.db"), seen.index("admin.db"))  # stores before registries
        self.assertEqual(seen[-1], "platform.db")
        self.assertGreaterEqual(result["counts"]["runs"], 1)
        self.assertEqual(recovery.verify(out)["counts"], result["counts"])  # verifying changes nothing
        self.assertEqual(recovery.verify(out)["counts"], result["counts"])
        target = Path(tempfile.mkdtemp()) / "restored"
        restored = recovery.restore(out, target)
        self.assertEqual(restored["counts"], result["counts"])
        self.assertLess(restored["seconds"] + result["seconds"], 60)

        # a second platform on the restored data, while the first keeps running: nothing is shared
        pf2, c2 = self.second_platform(target)
        self.assertEqual(pf2.tenancy.current(), self.pf.tenancy.current())  # tenant mappings
        status, view2 = c2.call("GET", f"{WS}/members", "acme-ada")
        self.assertEqual(status, 200, view2)
        _, view1 = self.call("GET", f"{WS}/members")
        by2 = {m["name"]: m for m in view2["members"]}
        by1 = {m["name"]: m for m in view1["members"]}
        self.assertEqual(sorted(by2), sorted(by1))  # "late", added during the backup, is in the registries
        for name in by1:  # members, grants, token state and lifetimes are exactly the source's
            self.assertEqual(by2[name], by1[name], name)
        self.assertEqual(view2["history"], view1["history"])
        self.assertIsNone(view2["integrity_problem"])
        self.assertEqual(c2.call("GET", f"{ENGINE}/me", zoe)[1]["permissions"], ["read"])  # an approved grant
        self.assertEqual(c2.call("GET", "/platform/v1/me", revoked)[0], 401)  # a revocation
        self.assertEqual(c2.call("GET", "/platform/v1/me", "acme-hana")[1]["token_expires_at"],
                         self.call("GET", "/platform/v1/me", "acme-hana")[1]["token_expires_at"])
        uc2 = c2.call("GET", UC, "acme-ada")[1]
        uc1 = self.view()
        self.assertEqual((uc2["release"]["active"]["number"], uc2["release"]["drift"], uc2["effective_stage"]),
                         (1, False, "simulation"))
        self.assertEqual(uc2["release"]["active"], uc1["release"]["active"])  # who approved it, and when
        self.assertEqual(uc2["history"], uc1["history"])  # stage history
        store2 = pf2.workspaces["acme"].use_cases["claims"].service.store
        self.assertTrue(store2.verify_audit(run_id))
        self.assertEqual(c2.call("GET", f"{ENGINE}/runs/{run_id}", "acme-hana")[1]["status"], "completed")
        ids2 = {o["id"] for o in c2.call("GET", f"{ENGINE}/objects?type=Claim&limit=1000", "acme-ada")[1]["items"]}
        ids1 = {o["id"] for o in self.call("GET", f"{ENGINE}/objects?type=Claim&limit=1000")[1]["items"]}
        self.assertLessEqual(ids2, ids1)  # a snapshot: nothing that the source does not have
        self.assertIn("CL-W1", ids2)
        # the restored platform works, and the two do not influence each other
        status, run = c2.call("POST", f"{ENGINE}/runs", "acme-hana", {"case_template": "claim_case", "root": "CL-2"})
        self.assertIn(run["status"], ("completed", "awaiting_review"), run)
        self.assertEqual(self.call("GET", f"{ENGINE}/runs/{run['run_id']}", "acme-hana")[0], 404)
        self.assertEqual(c2.call("POST", f"{WS}/members", "acme-ada", {"name": "only-there", "reason": "x"})[0], 201)
        self.assertNotIn("only-there", [m["name"] for m in self.call("GET", f"{WS}/members")[1]["members"]])
        self.assertEqual(self.call("POST", f"{ENGINE}/objects", body={**CLAIM, "id": "CL-AFTER"})[0], 200)
        self.assertEqual(c2.call("GET", f"{ENGINE}/objects/CL-AFTER", "acme-ada")[0], 404)

    def test_copying_the_live_file_is_not_a_backup(self):  # B3
        self.assertEqual(self.call("POST", f"{ENGINE}/objects", body={**CLAIM, "id": "CL-LIVE"})[0], 200)
        live = Path(self.data_dir) / "acme" / "claims" / "autology.db"
        self.assertTrue(Path(str(live) + "-wal").exists())  # committed data still in the write-ahead log
        naive = Path(tempfile.mkdtemp()) / "autology.db"
        shutil.copyfile(live, naive)

        def has_claim(path):
            db = sqlite3.connect(str(path))
            try:
                return db.execute("SELECT COUNT(*) FROM instances WHERE id='CL-LIVE'").fetchone()[0] == 1
            except sqlite3.OperationalError:  # not even the table: everything was still in the write-ahead log
                return False
            finally:
                db.close()
        self.assertFalse(has_claim(naive), "the copied main file alone does not contain the committed record")
        out = Path(tempfile.mkdtemp()) / "backup"
        recovery.backup(self.data_dir, out)
        self.assertTrue(has_claim(out / "acme" / "claims" / "autology.db"))
        self.assertFalse(list(out.rglob("*-wal")) + list(out.rglob("*-shm")))  # self-contained files
        db = sqlite3.connect(str(out / "acme" / "claims" / "autology.db"))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM writer_lease").fetchone()[0], 0)  # nobody holds a copy
        db.close()

    def test_a_damaged_or_foreign_backup_is_refused_and_nothing_is_put_in_place(self):  # B4
        self.populate()
        folder = Path(tempfile.mkdtemp())
        good = folder / "good"
        recovery.backup(self.data_dir, good)

        def damaged(name, change):
            copy = folder / name
            shutil.copytree(good, copy)
            change(copy)
            return copy

        def flip(path):
            raw = bytearray(path.read_bytes())
            raw[len(raw) // 2] ^= 0xFF
            path.write_bytes(bytes(raw))

        def manifest(copy, change):
            data = json.loads((copy / "MANIFEST.json").read_text())
            change(data)
            (copy / "MANIFEST.json").write_text(json.dumps(data))
        cases = {
            "a store was changed": damaged("c1", lambda c: flip(c / "acme" / "claims" / "autology.db")),
            "a registry was changed": damaged("c2", lambda c: flip(c / "admin.db")),
            "the manifest was edited": damaged("c3", lambda c: manifest(c, lambda m: m["counts"].update(runs=0))),
            "a file is missing": damaged("c4", lambda c: (c / "releases.db").unlink()),
            "a file was added": damaged("c5", lambda c: (c / "acme" / "extra.db").write_bytes(b"x")),
            "the manifest is gone": damaged("c6", lambda c: (c / "MANIFEST.json").unlink()),
            "a hash was fixed up after a change": damaged("c7", lambda c: (
                flip(c / "tenancy.db"),
                manifest(c, lambda m: [f.update(sha256=recovery._sha256(c / f["path"])) for f in m["files"]]))),
            "a path leaves the backup": damaged("c8", lambda c: manifest(
                c, lambda m: m["files"][0].update(path="../good/admin.db"))),
        }
        for what, copy in cases.items():
            target = folder / f"target-{copy.name}"
            with self.subTest(what), self.assertRaises(recovery.RecoveryError):
                recovery.restore(copy, target)
            self.assertFalse(target.exists(), what)
            with self.subTest(what + " (verify)"), self.assertRaises(recovery.RecoveryError):
                recovery.verify(copy)
        self.assertEqual([p.name for p in folder.iterdir() if "restoring" in p.name or "partial" in p.name], [])
        # another audit key: the manifest's signature does not verify (and the chains would not either)
        with self.assertRaises(recovery.RecoveryError) as caught:
            recovery.read_manifest(good, key=b"another key")
        self.assertIn("audit key", str(caught.exception))
        # an existing data directory is never overwritten: not the live one, not any other
        occupied = folder / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("mine")
        for target in (occupied, Path(self.data_dir)):
            with self.assertRaises(recovery.RecoveryError) as caught:
                recovery.restore(good, target)
            self.assertIn("never overwrites", str(caught.exception))
        self.assertEqual((occupied / "keep.txt").read_text(), "mine")
        for bad_target in (good, Path(self.data_dir) / "inside", occupied):
            with self.assertRaises(recovery.RecoveryError):
                recovery.backup(self.data_dir, bad_target)
        with self.assertRaises(recovery.RecoveryError):
            recovery.backup(folder / "no-such-dir", folder / "x")
        with self.assertRaises(recovery.RecoveryError):
            recovery.backup(occupied, folder / "y")  # not a platform data directory
        # the good backup was only read, and the source platform never noticed any of this
        self.assertEqual(recovery.verify(good)["files"], len(json.loads((good / "MANIFEST.json").read_text())["files"]))
        empty = folder / "empty-target"
        empty.mkdir()
        self.assertEqual(recovery.restore(good, empty)["path"], str(empty))  # an empty folder is a fine target
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 200)
        self.assertEqual(self.run_claim("CL-2")[0], 200)

    def test_a_failure_in_the_middle_leaves_nothing_behind(self):  # B5
        self.populate()
        folder = Path(tempfile.mkdtemp())

        def fail_at(n):
            calls = []

            def hook(path):
                calls.append(path)
                if len(calls) == n:
                    raise OSError("disk full")
            return hook
        for n in (1, 3, 6):
            with self.subTest(backup_fails_at=n), self.assertRaises(OSError):
                recovery.backup(self.data_dir, folder / "b", on_file=fail_at(n))
            self.assertEqual(list(folder.iterdir()), [])
        recovery.backup(self.data_dir, folder / "b")
        before = {p.name: recovery._sha256(p) for p in (folder / "b").rglob("*") if p.is_file()}
        for n in (2, 5):
            with self.subTest(restore_fails_at=n), self.assertRaises(OSError):
                recovery.restore(folder / "b", folder / "t", on_file=fail_at(n))
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["b"])
        self.assertEqual({p.name: recovery._sha256(p) for p in (folder / "b").rglob("*") if p.is_file()}, before)
        self.assertEqual(recovery.restore(folder / "b", folder / "t")["counts"]["stores"], 3)
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 200)  # the source runs on

    def test_a_source_that_does_not_verify_is_not_backed_up_as_good(self):  # B6
        self.populate()
        self.stop()
        db = sqlite3.connect(str(Path(self.data_dir) / "admin.db"))
        db.executescript("DROP TRIGGER admin_events_append_only_u; "
                         "UPDATE admin_events SET reason='rewritten' WHERE seq=1 AND workspace='acme'")
        db.commit()
        db.close()
        out = Path(tempfile.mkdtemp()) / "backup"
        with self.assertRaises(recovery.RecoveryError) as caught:
            recovery.backup(self.data_dir, out)
        self.assertIn("admin.db (acme)", str(caught.exception))
        self.assertFalse(out.exists())

    def test_secrets_are_left_out_unless_asked_and_the_backup_is_private(self):  # B7
        secret = Path(self.data_dir) / "acme" / "secrets.json"
        secret.write_text(json.dumps({"anthropic_api_key": "sk-ant-not-a-real-key"}))
        folder = Path(tempfile.mkdtemp())
        out = recovery.backup(self.data_dir, folder / "plain")
        self.assertEqual(out["not_included"], ["acme/secrets.json"])
        self.assertFalse((folder / "plain" / "acme" / "secrets.json").exists())
        manifest = json.loads((folder / "plain" / "MANIFEST.json").read_text())
        self.assertTrue(any("Claude key" in need for need in manifest["needs"]))
        self.assertNotIn("sk-ant", "".join(p.read_text(errors="ignore") for p in (folder / "plain").rglob("*.json")))
        recovery.backup(self.data_dir, folder / "full", include_secrets=True)
        copied = folder / "full" / "acme" / "secrets.json"
        self.assertEqual(json.loads(copied.read_text())["anthropic_api_key"], "sk-ant-not-a-real-key")
        self.assertEqual(stat.S_IMODE(copied.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((folder / "full").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((folder / "full" / "acme" / "claims" / "autology.db").stat().st_mode), 0o600)
        restored = recovery.restore(folder / "full", folder / "restored")
        self.assertEqual(restored["not_included"], [])
        self.assertTrue((folder / "restored" / "acme" / "secrets.json").is_file())

    def test_the_commands_back_up_verify_and_restore(self):  # B8
        self.populate()
        folder = Path(tempfile.mkdtemp())
        config = folder / "platform.json"
        spec = self.spec()
        for ws in spec["workspaces"].values():
            for uc in ws["use_cases"].values():
                uc["config"] = str((EX / uc["config"]).resolve())
        for t in spec["templates"].values():
            t["config"] = str((EX / t["config"]).resolve())
        config.write_text(json.dumps(spec))
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.assertEqual(cli(["platform-backup", str(config), str(folder / "b")]), 0)
            self.assertEqual(cli(["platform-verify", str(folder / "b")]), 0)
            self.assertEqual(cli(["platform-restore", str(folder / "b"), str(folder / "r")]), 0)
            self.assertEqual(cli(["platform-restore", str(folder / "b"), str(folder / "r")]), 2)  # never overwrites
            self.assertEqual(cli(["platform-backup", str(config), str(folder / "b")]), 2)
            self.assertEqual(cli(["platform-verify", str(folder / "nothing")]), 2)
            (folder / "bad.json").write_text("{}")
            self.assertEqual(cli(["platform-backup", str(folder / "bad.json"), str(folder / "x")]), 2)
            self.assertEqual(cli(["platform-backup", str(folder / "missing.json"), str(folder / "x")]), 2)
        self.assertEqual(recovery.data_dir_of(str(config)), Path(self.data_dir).resolve())
        pf2, c2 = self.second_platform(folder / "r")
        self.assertEqual(c2.call("GET", UC, "acme-ada")[1]["release"]["active"]["number"], 1)


class ActivationTests(Base):
    def two_releases(self):
        """Release 1 (the configured model) and release 2 (a published draft), both approved; 2 is active."""
        first = self.release("v1")
        fp1 = self.view()["configuration"]
        self.publish("A motor claim (v2)")
        second = self.release("v2")
        fp2 = self.view()["configuration"]
        self.assertNotEqual(fp1, fp2)
        return first, second, fp1, fp2

    def activate(self, number, token="acme-ada"):
        return self.call("POST", f"{UC}/releases/{number}/activate", token, {"reason": f"activate {number}"})

    def test_activation_needs_no_reload_and_rollback_is_one_step(self):  # A1
        first, second, fp1, fp2 = self.two_releases()
        view = self.view()
        self.assertEqual((view["release"]["active"]["number"], view["release"]["drift"], view["effective_stage"]),
                         (second, False, "simulation"))  # activated and running, with no stage step by hand
        self.assertEqual(self.run_claim()[1]["status"], "completed")
        # rollback: one call. The older release's model is put back, the engine switched, the stage re-granted
        status, out = self.activate(first)
        self.assertEqual(status, 200, out)
        self.assertEqual((out["event"], out["reloaded"], out["configuration"], out["stage"]["revalidated"],
                          out["stage"]["stage"]), ("rolled_back", True, fp1, True, "simulation"))
        view = self.view()
        self.assertEqual((view["configuration"], view["release"]["active"]["number"], view["release"]["drift"],
                          view["effective_stage"]), (fp1, first, False, "simulation"))
        self.assertNotEqual(self.model_text(), "A motor claim (v2)")
        self.assertEqual(self.run_claim("CL-2")[0], 200)
        # and forward again, the same way
        status, out = self.activate(second)
        self.assertEqual((status, out["event"], out["reloaded"], out["configuration"]), (200, "activated", True, fp2))
        self.assertEqual(self.model_text(), "A motor claim (v2)")
        self.assertEqual(self.activate(second)[0], 409)  # already active
        # approvals were never rewritten: activation only appended to the history
        _, rel = self.call("GET", f"{UC}/releases")
        self.assertIsNone(rel["integrity_problem"])
        self.assertEqual([(i["number"], i["approved_by"]) for i in rel["items"]],
                         [(first, "maria@acme"), (second, "maria@acme")])
        events = [h["event"] for h in rel["history"]]
        self.assertEqual(events, ["proposed", "approved", "activated", "proposed", "approved", "activated",
                                  "rolled_back", "activated"])
        _, members = self.call("GET", f"{WS}/members")
        admin = [(e["event"], e["data"].get("by")) for e in members["history"] if e["event"] in (
            "engine_reloaded", "release_restored")]
        self.assertEqual([e for e in admin if e[0] == "release_restored"],
                         [("release_restored", "activation"), ("release_restored", "activation")])
        self.assertEqual(len([e for e in admin if e[0] == "engine_reloaded"]), 1)  # the publication's, none by hand
        self.start()  # after a restart the platform comes back on the active release, still without a manual step
        view = self.view()
        self.assertEqual((view["configuration"], view["release"]["drift"], view["effective_stage"]),
                         (fp2, False, "simulation"))

    def expect_unchanged(self, fp, active, text):
        view = self.view()
        self.assertEqual((view["configuration"], view["release"]["active"]["number"], view["release"]["drift"],
                          view["effective_stage"]), (fp, active, False, "simulation"))
        self.assertEqual(self.model_text(), text)
        self.assertEqual(self.call("GET", f"{ENGINE}/objects", "acme-hana")[0], 200)
        _, rel = self.call("GET", f"{UC}/releases")
        self.assertEqual([h["event"] for h in rel["history"]].count("rolled_back"), 0)
        self.assertIsNone(rel["integrity_problem"])

    def test_a_failed_activation_puts_back_what_ran_before(self):  # A2
        first, second, fp1, fp2 = self.two_releases()
        real = Platform._load_use_case

        def failing_build(fail_on):
            calls = []

            def load(pf, ws, uc_id, spec, base_dir, validate_only=False):
                if ws.id == "acme" and uc_id == "claims" and not validate_only:
                    calls.append(1)
                    if len(calls) in fail_on:
                        raise OSError("the engine cannot be built")
                return real(pf, ws, uc_id, spec, base_dir, validate_only)
            return load
        # the new engine cannot be built: the previous model and engine are put back
        with mock.patch.object(Platform, "_load_use_case", failing_build({1})):
            status, out = self.activate(first)
        self.assertEqual(status, 500, out)
        self.assertIn("put back", out["error"]["message"])
        self.expect_unchanged(fp2, second, "A motor claim (v2)")
        # the registry refuses to record the activation after the engine was switched: switched back
        with mock.patch.object(type(self.pf.releases), "record", side_effect=ReleaseError(409, "registry says no")):
            status, out = self.activate(first)
        self.assertEqual(status, 409, out)
        self.expect_unchanged(fp2, second, "A motor claim (v2)")
        with mock.patch.object(type(self.pf.releases), "record", side_effect=RuntimeError("disk")):
            status, out = self.activate(first)
        self.assertEqual(status, 500, out)
        self.expect_unchanged(fp2, second, "A motor claim (v2)")
        # the deployed files are no longer those of the release (a setting outside the model changed)
        config = self.config_dir / "server.json"
        original = config.read_text()
        changed = json.loads(original)
        changed["agents"]["claims"]["roles"] = ["fraud_analytics", "finance"]
        config.write_text(json.dumps(changed))
        status, out = self.activate(first)
        self.assertEqual(status, 409, out)
        self.assertIn("deploy that release's files", out["error"]["message"])
        self.assertIn("Nothing was changed", out["error"]["message"])
        self.expect_unchanged(fp2, second, "A motor claim (v2)")
        # the operator deploys the release's files: activation picks them up by itself, no reload, no restart
        config.write_text(original)
        status, out = self.activate(first)
        self.assertEqual((status, out["event"], out["configuration"]), (200, "rolled_back", fp1), out)
        self.assertEqual(self.run_claim()[1]["status"], "completed")
        # a release that does not load at all with the deployed files changes nothing either
        config.write_text(original.replace('"tools.json"', '"missing-tools.json"'))
        status, out = self.activate(second)
        self.assertEqual(status, 409, out)
        self.assertIn("does not load", out["error"]["message"])
        config.write_text(original)
        self.assertEqual(self.view()["configuration"], fp1)

    def test_if_nothing_loads_the_use_case_serves_nothing_until_reloaded(self):  # A3
        first, second, fp1, fp2 = self.two_releases()
        real = Platform._load_use_case

        def load(pf, ws, uc_id, spec, base_dir, validate_only=False):
            if ws.id == "acme" and uc_id == "claims" and not validate_only:
                raise OSError("no engine can be built")
            return real(pf, ws, uc_id, spec, base_dir, validate_only)
        with mock.patch.object(Platform, "_load_use_case", load):
            status, out = self.activate(first)
        self.assertEqual(status, 500, out)
        status, headers, body = self.raw("GET", f"{ENGINE}/objects", "acme-hana")
        self.assertEqual((status, headers["Retry-After"], body["error"]["code"]), (503, "2", "unavailable"))
        self.assertIn("unavailable", body["error"]["message"])
        self.assertEqual(self.call("GET", "/w/acme/u/orders/api/v1/me", "acme-olivia")[0], 200)  # others unaffected
        self.assertEqual(self.call("GET", "/platform/v1/me", "acme-hana")[0], 200)
        _, rel = self.call("GET", f"{UC}/releases")
        self.assertEqual(rel["active"]["number"], second)  # nothing was recorded as active that does not run
        status, view = self.call("POST", f"{UC}/reload", body={"reason": "files repaired"})
        self.assertEqual(status, 200, view)
        self.assertEqual(self.call("GET", f"{ENGINE}/objects", "acme-hana")[0], 200)
        self.assertEqual((view["configuration"], view["release"]["drift"]), (fp2, False))

    def raw(self, method, path, token=None, body=None):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.c.server.server_port, timeout=30)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), json.loads(data) if data else None

    def test_requests_never_see_an_intermediate_configuration(self):  # A4
        first, second, fp1, fp2 = self.two_releases()
        stop, seen, views, problems = threading.Event(), [], [], []

        def reader(token, path):
            while not stop.is_set():
                try:
                    status, _, body = self.raw("GET", path, token)
                except Exception as exc:  # a dropped connection would be a failure too
                    problems.append(repr(exc))
                    continue
                if status != 200:
                    problems.append((path, status, body))
                elif path.endswith("/health"):
                    seen.append((body["configuration"], body.get("stage"), body.get("runs_allowed")))
                elif path == UC:
                    views.append((body["configuration"], body["release"]["drift"], body["effective_stage"]))
        threads = [threading.Thread(target=reader, args=a, daemon=True) for a in (
            ("acme-hana", f"{ENGINE}/health"), ("acme-ivan", f"{ENGINE}/health"),
            ("acme-hana", f"{ENGINE}/objects?limit=5"), ("acme-ada", UC))]
        for t in threads:
            t.start()
        try:
            for number in (first, second) * 6:
                status, out = self.activate(number)
                self.assertEqual(status, 200, out)
        finally:
            stop.set()
            for t in threads:
                t.join(15)
        self.assertEqual(problems, [])
        self.assertGreater(len(seen), 10)
        self.assertGreater(len(views), 3)
        # every answer came from one of the two approved configurations, active and allowed to run: never a model
        # without its release (which would have shown as draft), never an engine that was closing
        self.assertEqual({s[0] for s in seen}, {fp1, fp2})
        self.assertEqual({(s[1], s[2]) for s in seen}, {("simulation", True)})
        self.assertEqual({v[1:] for v in views}, {(False, "simulation")})  # the administrator's view agrees
        self.assertLessEqual({v[0] for v in views}, {fp1, fp2})

    def test_a_switch_waits_for_requests_and_requests_wait_for_a_switch(self):  # A5
        first, second, fp1, fp2 = self.two_releases()
        gate = self.pf.workspaces["acme"].gates["claims"]
        with mock.patch("autology.platform.SWAP_WAIT", 0.3):
            self.assertTrue(gate.enter())  # a request in flight (a long run, say)
            try:
                started = time.monotonic()
                status, out = self.activate(first)
                self.assertEqual(status, 409, out)
                self.assertIn("still in progress", out["error"]["message"])
                self.assertLess(time.monotonic() - started, 3)
                self.assertEqual(self.call("GET", f"{ENGINE}/me", "acme-hana")[0], 200)  # others are not held up
            finally:
                gate.leave()
            self.assertEqual(self.view()["configuration"], fp2)  # nothing was changed
            holder = threading.Thread(target=lambda: (gate.acquire(5), time.sleep(1.0), gate.release()), daemon=True)
            holder.start()
            time.sleep(0.2)  # a switch is in progress
            status, headers, body = self.raw("GET", f"{ENGINE}/me", "acme-hana")
            self.assertEqual((status, headers["Retry-After"]), (503, "2"))
            self.assertIn("being switched", body["error"]["message"])
            status, headers, body = self.raw("GET", UC, "acme-ada")
            self.assertEqual((status, headers["Retry-After"], body["error"]["code"]), (503, "2", "unavailable"))
            holder.join(5)
        self.assertEqual(self.call("GET", f"{ENGINE}/me", "acme-hana")[0], 200)
        self.assertEqual(self.activate(first)[0], 200)

    def test_pilot_is_never_automatic_and_only_authorised_people_activate(self):  # A6
        first, second, fp1, fp2 = self.two_releases()
        uc = self.pf.workspaces["acme"].use_cases["claims"]
        # the use case is in pilot (recorded directly: the pilot checks themselves are tested elsewhere)
        self.pf.lifecycle.append("acme", "claims", "simulation", "pilot", "ada@acme", "pilot granted",
                                 uc.service.ontology.fingerprint, [])
        self.assertEqual(self.view()["effective_stage"], "pilot")
        status, out = self.activate(first)
        self.assertEqual(status, 200, out)
        self.assertEqual((out["stage"]["stage"], out["stage"]["was"], out["stage"]["revalidated"]),
                         ("simulation", "pilot", True))
        self.assertIn("person", out["stage"]["next"])
        self.assertEqual(self.view()["stage"], "simulation")  # a person decides pilot again
        self.assertEqual(self.call("POST", f"{UC}/stage", body={"to": "production", "reason": "x"})[0], 403)
        for token in ("acme-hana", "acme-maria", "nw-nadia"):  # no administrator of this workspace: no activation
            self.assertIn(self.activate(second, token)[0], (403, 404), token)
        bot = self.add("bot", "service")
        self.assertIn(self.activate(second, bot)[0], (403, 404))
        self.assertEqual(self.call("POST", f"{UC}/releases/{second}/activate", body={})[0], 400)  # a reason is needed
        self.assertEqual(self.activate(99)[0], 404)
        self.publish("A motor claim (v3)")
        third = self.release("v3", activate=False)
        self.assertEqual(self.call("POST", f"{UC}/releases/{third}/revoke", "acme-maria", {"reason": "wait"})[0], 200)
        status, out = self.activate(third)
        self.assertEqual(status, 409)
        self.assertIn("not approved", out["error"]["message"])
        self.assertEqual(self.view()["release"]["active"]["number"], first)

    def test_the_scheduler_does_not_tick_while_its_engine_is_switched(self):  # A7
        svc = self.pf.workspaces["acme"].use_cases["claims"].service
        gate = self.pf.workspaces["acme"].gates["claims"]
        ticks = []
        with mock.patch.object(svc, "tick", lambda: ticks.append(time.monotonic()) or {}), \
                mock.patch("autology.platform.SWAP_WAIT", 0.05):
            stop = svc.start_background(interval=0.02)
            try:
                time.sleep(0.2)
                self.assertGreater(len(ticks), 2)
                gate.acquire(2)
                try:
                    time.sleep(0.1)  # a tick that was waiting for the gate has given up by now
                    held = len(ticks)
                    time.sleep(0.3)
                    self.assertEqual(len(ticks), held)
                finally:
                    gate.release()
                time.sleep(0.2)
                self.assertGreater(len(ticks), held)
            finally:
                stop.set()


if __name__ == "__main__":
    import unittest

    unittest.main()
