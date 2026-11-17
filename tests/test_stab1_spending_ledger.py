"""Stabilisation A: the spending ledger is the authority for every AI ceiling, and it outlives a deployment.

Before (GAP-085, found by the first real evaluation): the ledger lived in the deployment's data directory. Writing
the deployment again, or starting it on an empty directory, started an empty ledger: the whole ceiling was
available again although part of it was spent.

Now: the owner's authorisation names one ledger, kept outside the deployment, as it stood when the deployment was
written. A missing, empty, damaged, older or different ledger serves nothing; a new one is only ever created
explicitly, with its opening balance; spending history is only added to; a restore never takes it back in time.

L1  writing or starting a deployment again never gives spent money back
L2  a lost ledger is not replaced silently: the setup refuses, or carries the stated balance forward
L3  missing, empty, damaged, foreign, older: nothing is sent, the platform still starts, no file is created
L4  an authorisation without a ledger, or a ledger kept with the data, serves no real provider
L5  parallel reservations, from one process or two, cannot spend the same money twice
L6  an interrupted write leaves nothing half-written; a call a process died in stays charged
L7  a request id is charged once; an exhausted budget refuses and records the refusal
L8  entries are never deleted, closed entries never change, the identity never changes
L9  one workspace's history is its own; the view shows amounts and the ledger's standing
L10 a backup carries the ledger; a restore keeps a ledger that is ahead and stops on a different one
L11 the command line: status, an explicit new ledger, a saved copy put back; the saved ledger of 17 November
    reconciles with the evidence of that day and is not modified by being read
"""

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from autology import ai_policy, recovery
from autology.__main__ import main as cli
from autology.ai import ModelRequest, ProviderError
from autology.ai_policy import LedgerError, SpendLedger
from autology.architect import SCHEMA
from autology.reasoners import PRICES

from .helpers import ROOT
from .test_arch2_ai_provider_governance import AI, MODEL, GovernanceBase, policy
from .test_claude3_evaluation_deployment import ARGS, evaluation_setup

EVIDENCE = ROOT / "planning" / "evidence" / "claude-eval-2026-11-17"
PERIOD = ai_policy.period_key("month")


def request(rid):
    return ModelRequest("acme", "architect.propose", "system", "a brief nobody may find in a ledger", SCHEMA,
                        max_output_tokens=100, request_id=rid)


def spend(ledger, workspace, rid, amount, pol=None):
    """One settled call of ``amount`` USD, as the gateway's budget records it."""
    entry = ledger.reserve(workspace, "uc", request(rid), pol or policy(budget={"per_request": 100, "per_period": 1000}),
                           amount)
    ledger.close_entry(entry["id"], ai_policy.SETTLED, amount, {"input_tokens": 10, "output_tokens": 5}, 1, "ok")
    return entry["id"]


def run_setup(out, ledger, *extra):
    text = io.StringIO()
    with redirect_stdout(text), redirect_stderr(text):
        try:
            code = evaluation_setup.main(["--out", str(out), "--ledger", str(ledger), *ARGS, *extra])
        except SystemExit as exc:
            code = exc.code
    return code, text.getvalue()


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli(list(argv))
    return code, out.getvalue(), err.getvalue()


class RedeploymentTests(GovernanceBase):
    def view(self):
        return self.call("GET", AI)[1]

    def test_a_deployment_written_or_started_again_never_gives_money_back(self):  # L1
        view = self.approve_policy()
        self.assertEqual((view["state"], view["ledger"]["available"], view["ledger"]["outside_deployment"],
                          view["ledger"]["bound_to_authorisation"]), ("authorised", True, True, True))
        self.assertEqual(self.ask()[0], 200)
        self.assertEqual(self.ask()[0], 200)
        before = self.view()
        self.assertEqual((before["usage"]["spent_usd"], before["remaining_usd"]), (0.4, 4.6))
        # the deployment is thrown away and written again on an empty data directory: only the ledger remains
        self.stop()
        shutil.rmtree(self.data_dir)
        self.data_dir = tempfile.mkdtemp()
        self.start()
        self.assertFalse((Path(self.data_dir) / "ai_ledger.db").exists())  # one ledger, in one place
        after = self.approve_policy()  # the new deployment has no policy yet: two people approve it again
        self.assertEqual((after["usage"]["spent_usd"], after["remaining_usd"], after["usage"]["settled"]),
                         (0.4, 4.6, 2))
        self.assertEqual(after["ledger"]["history"], [{"period": PERIOD, "entries": 2, "spent_usd": 0.4,
                                                       "reserved_usd": 0.0, "carried_forward_usd": 0.0}])
        self.assertEqual(after["ledger"]["id"], before["ledger"]["id"])

    def test_a_missing_empty_damaged_or_foreign_ledger_sends_nothing(self):  # L3
        self.approve_policy()
        self.assertEqual(self.ask()[0], 200)
        original = Path(self.ledger_path).read_bytes()
        point = self.pf.ai_ledger.checkpoint()

        def restart_with(prepare):
            self.stop()
            Path(self.ledger_path).unlink(missing_ok=True)
            prepare()
            self.ledger_binding = point  # the deployment still names the ledger it was written against
            self.start()

        calls = len(self.double.calls)
        cases = (
            ("no spending ledger", lambda: None),
            ("no spending ledger", lambda: Path(self.ledger_path).write_bytes(b"")),
            ("cannot be read", lambda: Path(self.ledger_path).write_bytes(b"this is not a database" * 400)),
            ("is not a spending ledger", lambda: sqlite3.connect(self.ledger_path).executescript(
                "CREATE TABLE other (x); INSERT INTO other VALUES (1);")),
            ("the one in place is", lambda: SpendLedger(self.ledger_path).close()),  # a brand-new, empty ledger
        )
        for expected, prepare in cases:
            with self.subTest(expected):
                restart_with(prepare)
                view = self.view()
                self.assertEqual((view["state"], view["transmits_externally"]), ("unavailable", False), view["reason"])
                self.assertIn(expected, view["reason"])
                self.assertIn("No request is sent", view["reason"])
                status, out = self.ask()
                self.assertEqual(status, 409, out)
                self.assertEqual(len(self.double.calls), calls)
                # and the health of the platform is not in question: other routes answer
                self.assertEqual(self.call("GET", "/platform/workspaces/acme/members")[0], 200)
        # nothing was started in place of a missing ledger
        restart_with(lambda: None)
        self.assertFalse(Path(self.ledger_path).exists())
        # the real ledger back in place: served again, with what was spent
        restart_with(lambda: Path(self.ledger_path).write_bytes(original))
        view = self.view()
        self.assertEqual((view["state"], view["usage"]["spent_usd"]), ("authorised", 0.2), view["reason"])

    def test_an_older_copy_of_the_ledger_serves_nothing(self):  # L3
        self.approve_policy()
        self.assertEqual(self.ask()[0], 200)
        older = Path(self.ledger_path).read_bytes()  # a copy kept after the first call
        self.assertEqual(self.ask()[0], 200)
        self.start()  # the deployment is written again: it now names the ledger with two entries
        self.assertEqual(self.view()["state"], "authorised")
        written_against = self.pf.ai_ledger.checkpoint()
        self.assertEqual(written_against["entries"], 2)
        self.stop()
        Path(self.ledger_path).write_bytes(older)  # the ledger goes back in time; the deployment is not rewritten
        self.ledger_binding = written_against
        self.start()
        view = self.view()
        self.assertEqual(view["state"], "unavailable")
        self.assertIn("older than, or different from", view["reason"])
        calls = len(self.double.calls)
        self.assertEqual(self.ask()[0], 409)
        self.assertEqual(len(self.double.calls), calls)

    def test_no_ledger_named_or_a_ledger_kept_with_the_data_serves_no_real_provider(self):  # L4
        bare = [{k: v for k, v in a.items() if k != "ledger"} for a in type(self).authorisations]

        def start_without(spec_change):
            self.stop()
            from autology.platform import Platform

            from .test_workspaces import EX, Client, data_admins

            spec = data_admins(json.loads((EX / "platform.json").read_text()))
            spec["data_dir"] = self.data_dir
            spec["workspaces"]["acme"]["use_cases"]["claims"]["config"] = str(self.config_dir / "server.json")
            spec["workspaces"]["acme"]["use_cases"]["novel"] = {"name": "Novel case",
                                                               "config": str(self.config_dir / "novel.json")}
            spec_change(spec)
            self.pf = Platform(spec, EX)
            self.c = Client(self.pf)

        start_without(lambda spec: spec.update(ai_authorisations=bare))  # the deployment of before this change
        view = self.approve_policy()
        self.assertEqual(view["state"], "unavailable")
        self.assertIn("names no spending ledger", view["reason"])
        self.assertEqual((self.ask()[0], self.double.calls), (409, []))
        # a binding to the ledger inside the data directory is not accepted either: it goes with the deployment
        inside = SpendLedger(Path(self.data_dir) / "ai_ledger.db", create=False)
        point = inside.checkpoint()
        inside.close()
        start_without(lambda spec: spec.update(ai_authorisations=[{**a, "ledger": point} for a in bare]))
        view = self.view()
        self.assertEqual(view["state"], "unavailable")
        self.assertIn("kept outside the deployment", view["reason"])
        self.assertEqual((self.ask()[0], self.double.calls), (409, []))
        from autology.platform import PlatformError

        with self.assertRaises(PlatformError):  # "outside" is checked, not taken on trust
            start_without(lambda spec: spec.update(ai_ledger=str(Path(self.data_dir) / "elsewhere.db")))
        self.pf = None

    def test_the_view_shows_the_ledger_and_only_this_workspaces_history(self):  # L9
        self.approve_policy()
        self.assertEqual(self.ask()[0], 200)
        spend(self.pf.ai_ledger, "northwind", "nw-1", 3.0)
        view = self.view()
        self.assertEqual([h["spent_usd"] for h in view["ledger"]["history"]], [0.2])
        self.assertEqual(view["ledger"]["entries"], 2)  # how far the ledger stands, not whose entries
        self.assertEqual(view["usage"]["spent_usd"], 0.2)
        self.assertNotIn("northwind", json.dumps(view))
        self.assertNotIn(os.environ["ACME_AI_KEY"], json.dumps(view))


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.ledger = self.home / "durable" / "ai_ledger.db"
        self.first = ("--new-ledger", "--opening-spent-usd", "0", "--opening-reference", "first deployment")

    def test_writing_the_deployment_again_binds_it_to_the_same_ledger(self):  # L1
        code, said = run_setup(self.home / "one", self.ledger, *self.first)
        self.assertEqual(code, 0, said)
        ledger = SpendLedger(self.ledger, create=False)
        spend(ledger, "evaluation", "r1", 4.418874)
        ledger.close()
        code, said = run_setup(self.home / "two", self.ledger)  # another deployment, the same ledger
        self.assertEqual(code, 0, said)
        self.assertIn("already there: what it holds stays counted", said)
        self.assertIn("4.418874 USD spent", said)
        spec = json.loads((self.home / "two" / "platform.json").read_text())
        binding = spec["ai_authorisations"][0]["ledger"]
        self.assertEqual((binding["entries"], binding["settled_usd"]), (1, 4.418874))
        self.assertEqual(spec["ai_ledger"], str(self.ledger.resolve()))
        from autology.platform import Platform

        with mock.patch.dict(os.environ, {"AUTOLOGY_AUDIT_KEY": "k", "EVALUATION_TOKEN_OWNER": "o",
                                          "EVALUATION_TOKEN_REVIEWER": "r", "EVALUATION_TOKEN_OPERATOR": "p",
                                          "EVALUATION_TOKEN_SUPERVISOR": "s"}):
            pf = Platform.from_file(str(self.home / "two" / "platform.json"))
        try:
            self.assertEqual(pf.ai_ledger.usage("evaluation", "month")["spent_usd"], 4.418874)
            pol = json.loads((self.home / "two" / "policy.json").read_text())["policy"]
            budget = ai_policy.Budget(pf.ai_ledger, "evaluation", "architect", {**pol, "budget": {
                **pol["budget"], "per_period": 5.0, "per_request": 5.0}})
            with self.assertRaises(ProviderError) as refused:  # 4.42 of 5 is spent whatever directory it runs in
                budget.ledger.reserve("evaluation", "architect", request("r2"), budget.policy, 1.0)
            self.assertEqual(refused.exception.kind, "budget_exceeded")
            self.assertFalse((self.home / "two" / "data" / "ai_ledger.db").exists())
        finally:
            pf.close()

    def test_a_lost_ledger_is_never_replaced_silently(self):  # L2
        self.assertEqual(run_setup(self.home / "one", self.ledger, *self.first)[0], 0)
        self.ledger.unlink()
        code, said = run_setup(self.home / "two", self.ledger)
        self.assertNotEqual(code, 0)
        self.assertIn("an empty one is never started in its place", said)
        self.assertFalse(self.ledger.exists())
        self.assertFalse((self.home / "two").exists())
        for extra in (("--new-ledger",), ("--new-ledger", "--opening-spent-usd", "4.4"),
                      ("--new-ledger", "--opening-reference", "evidence"),
                      ("--new-ledger", "--opening-spent-usd", "26", "--opening-reference", "more than the ceiling")):
            code, said = run_setup(self.home / "two", self.ledger, *extra)
            self.assertNotEqual(code, 0, extra)
            self.assertFalse(self.ledger.exists(), extra)
        code, said = run_setup(self.home / "two", self.ledger, "--new-ledger", "--opening-spent-usd", "4.418874",
                               "--opening-reference", "evidence of 17 November, 27 entries")
        self.assertEqual(code, 0, said)
        self.assertIn("4.418874 carried forward", said)
        ledger = SpendLedger(self.ledger, create=False)
        try:
            self.assertEqual(ledger.usage("evaluation", "month")["spent_usd"], 4.418874)
            entry = ledger.entries("evaluation")[0]
            self.assertEqual((entry["purpose"], entry["state"]), (ai_policy.OPENING, "settled"))
            self.assertIn("evidence of 17 November", entry["outcome"])
        finally:
            ledger.close()
        code, said = run_setup(self.home / "three", self.ledger, *self.first)  # never over an existing ledger
        self.assertNotEqual(code, 0)
        self.assertIn("never created over another", said)

    def test_the_ledger_is_outside_the_deployment_and_the_repository(self):  # L1
        for bad in (self.home / "one" / "ai_ledger.db", ROOT / "would-be-committed.db"):
            code, said = run_setup(self.home / "one", bad, *self.first)
            self.assertNotEqual(code, 0)
            self.assertIn("outside --out and outside the repository", said)
            self.assertFalse(bad.exists())
        code, said = run_setup(self.home / "one", "", *self.first)
        self.assertNotEqual(code, 0)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "ledger.db"
        self.ledger = SpendLedger(self.path)
        self.addCleanup(lambda: self.ledger.close())
        self.policy = policy(budget={"per_request": 2.0, "per_period": 5.0}, limits={"concurrency": 50})
        PRICES[MODEL] = (100.0, 200.0)
        self.addCleanup(PRICES.pop, MODEL, None)

    def test_parallel_reservations_cannot_spend_the_same_money_twice(self):  # L5
        other = SpendLedger(self.path, create=False)  # a second process on the same file
        self.addCleanup(other.close)
        outcomes = []

        def reserve(n):
            ledger = self.ledger if n % 2 else other
            try:
                ledger.reserve("acme", "uc", request(f"r{n}"), self.policy, 1.0)
                outcomes.append("reserved")
            except ProviderError as exc:
                outcomes.append(exc.kind)
            except Exception as exc:  # a locked database is a refusal too, never a reservation
                outcomes.append(type(exc).__name__)

        threads = [threading.Thread(target=reserve, args=(n,)) for n in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(outcomes.count("reserved"), 5)  # 5 USD, one dollar each: never a sixth
        usage = self.ledger.usage("acme", "month")
        self.assertEqual((usage["reserved_usd"], usage["in_progress"]), (5.0, 5))

    def test_an_interrupted_write_leaves_nothing_and_an_interrupted_call_stays_charged(self):  # L6
        with mock.patch.object(ai_policy, "_now", side_effect=OSError("the disk went away")):
            with self.assertRaises(OSError):
                self.ledger.reserve("acme", "uc", request("r1"), self.policy, 1.0)
        self.assertEqual(self.ledger.entries("acme"), [])
        entry = self.ledger.reserve("acme", "uc", request("r1"), self.policy, 1.0)  # the ledger is not left locked
        self.assertFalse(entry["duplicate"])
        # the process stops between the reservation and the answer; a new one starts on the same ledger
        self.ledger.close()
        self.ledger = SpendLedger(self.path, create=False)
        one = policy(budget={"per_request": 2.0, "per_period": 5.0}, limits={"concurrency": 1})
        with self.assertRaises(ProviderError):  # until recovery, the dead call still counts as running
            self.ledger.reserve("acme", "uc", request("r2"), one, 1.0)
        self.assertEqual(self.ledger.recover_interrupted(), 1)
        self.assertEqual(self.ledger.recover_interrupted(), 0)
        row = self.ledger.entries("acme")[0]
        self.assertEqual(row["state"], "uncertain")
        self.assertIn("interrupted", row["outcome"])
        usage = self.ledger.usage("acme", "month")
        self.assertEqual((usage["reserved_usd"], usage["uncertain"], usage["in_progress"]), (1.0, 1, 0))
        self.ledger.reserve("acme", "uc", request("r3"), one, 1.0)  # no longer blocked, and the dollar stays held
        with self.assertRaises(ProviderError):
            self.ledger.reserve("acme", "uc", request("r4"), policy(budget={"per_request": 5, "per_period": 5.0},
                                                                    limits={"concurrency": 9}), 3.5)

    def test_a_request_is_charged_once_and_an_exhausted_budget_refuses(self):  # L7
        first = self.ledger.reserve("acme", "uc", request("same"), self.policy, 1.0)
        again = self.ledger.reserve("acme", "uc", request("same"), self.policy, 1.0)
        self.assertEqual((first["duplicate"], again["duplicate"], again["id"]), (False, True, first["id"]))
        self.assertEqual(len(self.ledger.entries("acme")), 1)
        budget = ai_policy.Budget(self.ledger, "acme", "uc", self.policy)
        with self.assertRaises(ProviderError) as repeated:  # never sent, and so never charged, a second time
            budget.admit(request("same"))
        self.assertEqual(repeated.exception.kind, "invalid_request")
        for n in range(4):
            spend(self.ledger, "acme", f"s{n}", 1.0, self.policy)
        with self.assertRaises(ProviderError) as refused:
            self.ledger.reserve("acme", "uc", request("one-too-many"), self.policy, 0.01)
        self.assertEqual(refused.exception.kind, "budget_exceeded")
        usage = self.ledger.usage("acme", "month")
        self.assertEqual((usage["spent_usd"], usage["reserved_usd"], usage["refused"]), (4.0, 1.0, 1))
        self.assertEqual(len(self.ledger.entries("acme")), 5)  # the refused request left no entry to charge
        # another month starts its own count; the history keeps both
        january = datetime(2031, 1, 5, tzinfo=timezone.utc)
        self.ledger.reserve("acme", "uc", request("next-year"), self.policy, 1.0, clock=lambda: january)
        self.assertEqual([h["period"] for h in self.ledger.history("acme")], [PERIOD, "2031-01"])

    def test_history_is_only_added_to(self):  # L8
        done = spend(self.ledger, "acme", "r1", 1.0)
        open_entry = self.ledger.reserve("acme", "uc", request("r2"), self.policy, 1.0)["id"]
        db = sqlite3.connect(self.path)
        for sql in ("DELETE FROM ai_ledger", f"DELETE FROM ai_ledger WHERE id={open_entry}",
                    f"UPDATE ai_ledger SET actual_usd=0 WHERE id={done}",
                    f"UPDATE ai_ledger SET state='released' WHERE id={done}",
                    f"UPDATE ai_ledger SET reserved_usd=0.01 WHERE id={open_entry}",
                    f"UPDATE ai_ledger SET workspace='northwind' WHERE id={open_entry}",
                    f"UPDATE ai_ledger SET period='1999-01' WHERE id={open_entry}",
                    "UPDATE ai_ledger_meta SET value='another-ledger' WHERE key='ledger_id'",
                    "DELETE FROM ai_ledger_meta"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                db.execute(sql)
                db.commit()
            db.rollback()
        db.close()
        self.ledger.close_entry(done, ai_policy.RELEASED, 0.0, {}, 0, "an attempt to settle twice")  # no effect
        self.assertEqual(self.ledger.usage("acme", "month")["spent_usd"], 1.0)
        point = self.ledger.checkpoint()
        self.assertEqual((point["entries"], point["settled_usd"], self.ledger.verify(point)), (2, 1.0, []))
        spend(self.ledger, "acme", "r3", 1.0)  # a ledger that went on is still the ledger the checkpoint names
        self.assertEqual(self.ledger.verify(point), [])
        # amounts are stored as computed and stated to a millionth: a total such as 4.4188746 is the 4.418875 its
        # checkpoint states (the saved ledger of 17 November was refused for this before the check rounded)
        spend(self.ledger, "acme", "r4", 0.4188746)
        stated = self.ledger.checkpoint()
        self.assertEqual((stated["settled_usd"], self.ledger.verify(stated)), (2.418875, []))
        self.assertIn("settled", self.ledger.verify({**stated, "settled_usd": 2.5})[0])  # less than was stated: no
        fresh = SpendLedger(Path(tempfile.mkdtemp()) / "fresh.db")
        self.addCleanup(fresh.close)
        self.assertNotEqual(fresh.id, self.ledger.id)
        self.assertIn("the one in place is", fresh.verify(point)[0])
        self.assertEqual(fresh.verify({**fresh.checkpoint(), "entries": 3}), [
            "the spending ledger in place does not hold the 3 entries the authorisation was written against: it is "
            "older than, or different from, the authorised one"])

    def test_a_damaged_or_foreign_file_is_never_taken_for_a_ledger(self):  # L3
        self.ledger.close()
        self.ledger = SpendLedger(Path(tempfile.mkdtemp()) / "keep.db")
        for prepare, expected in ((lambda p: p.write_bytes(b"\0garbage" * 900), "cannot be read"),
                                  (lambda p: p.write_bytes(self.path.read_bytes()[:3000]), "cannot be read|damaged"),
                                  (lambda p: sqlite3.connect(p).executescript("CREATE TABLE t (x)"), "not a spending")):
            target = Path(tempfile.mkdtemp()) / "bad.db"
            prepare(target)
            for create in (True, False):
                with self.assertRaisesRegex(LedgerError, expected):
                    SpendLedger(target, create=create)
        missing = Path(tempfile.mkdtemp()) / "none.db"
        with self.assertRaisesRegex(LedgerError, "an empty one is never started"):
            SpendLedger(missing, create=False)
        self.assertFalse(missing.exists())
        stand_in = ai_policy.UnavailableLedger(missing, "it is not there")
        with self.assertRaises(LedgerError):
            stand_in.reserve("acme", "uc", request("r"), self.policy, 0.1)
        with self.assertRaises(ProviderError) as refused:  # the budget turns it into a refusal: nothing is sent
            ai_policy.Budget(stand_in, "acme", "uc", self.policy).admit(request("r"))
        self.assertEqual(refused.exception.kind, "budget_exceeded")
        self.assertEqual((stand_in.history("acme"), stand_in.entries("acme"), stand_in.verify({})),
                         ([], [], ["it is not there"]))

    def test_workspaces_are_counted_apart(self):  # L9
        spend(self.ledger, "acme", "r1", 4.5, policy(budget={"per_request": 5, "per_period": 5.0}))
        spend(self.ledger, "northwind", "r1", 1.0)  # the same request id in another workspace is another request
        self.assertEqual((self.ledger.usage("acme", "month")["spent_usd"],
                          self.ledger.usage("northwind", "month")["spent_usd"]), (4.5, 1.0))
        self.assertEqual([len(self.ledger.entries(w)) for w in ("acme", "northwind", "nobody")], [1, 1, 0])
        self.ledger.reserve("northwind", "uc", request("r2"), self.policy, 2.0)  # acme's 4.5 does not count here
        with self.assertRaises(ProviderError):
            self.ledger.reserve("acme", "uc", request("r2"), self.policy, 2.0)
        self.assertEqual(self.ledger.workspaces(), ["acme", "northwind"])
        text = json.dumps([self.ledger.entries("acme"), self.ledger.history("acme")])
        self.assertNotIn("nobody may find", text)  # amounts, counts and identifiers: never what was asked


class RecoveryTests(GovernanceBase):
    def setUp(self):
        super().setUp()
        self.approve_policy()
        self.assertEqual(self.ask()[0], 200)  # 0.20 USD in the ledger, outside the data directory
        self.home = Path(tempfile.mkdtemp())
        self.data = Path(self.data_dir)

    def spent(self):
        ledger = SpendLedger(self.ledger_path, create=False)
        try:
            return ledger.usage("acme", "month")["spent_usd"]
        finally:
            ledger.close()

    def test_a_backup_carries_the_ledger_and_a_restore_never_takes_it_back(self):  # L10
        taken = recovery.backup(self.data, self.home / "backup", ledger=self.ledger_path)
        self.assertTrue((self.home / "backup" / "ai_ledger.db").is_file())
        self.assertIn("ai_ledger.db", [f["path"] for f in recovery.read_manifest(self.home / "backup")["files"]])
        self.assertGreaterEqual(taken["files"], 2)
        self.assertEqual(self.ask()[0], 200)  # the platform goes on spending after the backup
        self.stop()
        out = recovery.restore(self.home / "backup", self.home / "restored", ledger=self.ledger_path)
        self.assertIn("kept", out["ledger"])
        self.assertFalse((self.home / "restored" / "ai_ledger.db").exists())
        self.assertEqual(self.spent(), 0.4)  # not back to 0.2
        # the ledger is lost with the machine: the backup's copy is put in place, and the report says what it is
        Path(self.ledger_path).unlink()
        out = recovery.restore(self.home / "backup", self.home / "again", ledger=self.ledger_path)
        self.assertIn("put in place from the backup", out["ledger"])
        self.assertIn("is not in it", out["ledger"])
        self.assertEqual(self.spent(), 0.2)
        self.assertFalse((self.home / "again" / "ai_ledger.db").exists())
        # the platform's own recovery rehearsal carries the ledger too
        self.pf = None

    def test_a_restore_stops_on_another_ledger_and_a_backup_on_a_missing_one(self):  # L10
        recovery.backup(self.data, self.home / "backup", ledger=self.ledger_path)
        self.stop()
        Path(self.ledger_path).unlink()
        other = SpendLedger(self.ledger_path)  # some other ledger now stands in its place
        spend(other, "acme", "zz", 0.5)
        other.close()
        with self.assertRaisesRegex(recovery.RecoveryError, "a restore never replaces a ledger"):
            recovery.restore(self.home / "backup", self.home / "restored", ledger=self.ledger_path)
        self.assertFalse((self.home / "restored").exists())
        self.assertEqual(self.spent(), 0.5)  # untouched
        Path(self.ledger_path).unlink()
        with self.assertRaisesRegex(recovery.RecoveryError, "is missing: no backup was written"):
            recovery.backup(self.data, self.home / "second", ledger=self.ledger_path)
        self.assertFalse((self.home / "second").exists())
        config = self.home / "platform.json"
        config.write_text(json.dumps({"workspaces": {}, "ai_ledger": "durable/ai_ledger.db"}))
        self.assertEqual(recovery.ledger_of(str(config)), (self.home / "durable" / "ai_ledger.db").resolve())
        config.write_text(json.dumps({"workspaces": {}}))
        self.assertIsNone(recovery.ledger_of(str(config)))
        self.pf = None


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def test_status_create_and_restore(self):  # L11
        path = self.home / "ledger.db"
        code, out, err = run_cli("ai-ledger", "status", str(path))
        self.assertEqual(code, 2)
        self.assertIn("an empty one is never started", err)
        self.assertFalse(path.exists())
        self.assertEqual(run_cli("ai-ledger", "create", str(path))[0], 0)
        code, out, err = run_cli("ai-ledger", "create", str(path))
        self.assertEqual(code, 2)
        self.assertIn("never created over another", err)
        ledger = SpendLedger(path, create=False)
        spend(ledger, "acme", "r1", 1.25)
        ledger.close()
        code, out, err = run_cli("ai-ledger", "status", str(path), "--json")
        report = json.loads(out)
        self.assertEqual((code, report["entries"], report["settled_usd"]), (0, 1, 1.25))
        self.assertEqual(report["workspaces"]["acme"][0]["spent_usd"], 1.25)
        code, out, err = run_cli("ai-ledger", "restore", str(path), str(path))
        self.assertEqual(code, 2)
        self.assertIn("never replaced by a copy", err)
        self.assertEqual(run_cli("ai-ledger", "restore", str(path))[0], 2)
        code, out, err = run_cli("ai-ledger", "restore", str(path), str(self.home / "back" / "ledger.db"))
        self.assertEqual(code, 0, err)
        self.assertIn("1.250000 USD spent", out)
        garbage = self.home / "garbage.db"
        garbage.write_bytes(b"not a ledger" * 500)
        code, out, err = run_cli("ai-ledger", "restore", str(garbage), str(self.home / "from-garbage.db"))
        self.assertEqual(code, 2)
        self.assertFalse((self.home / "from-garbage.db").exists())

    def test_the_saved_ledger_of_17_november_reconciles_with_that_days_evidence(self):  # L11
        saved = EVIDENCE / "ai_ledger.db"
        before = hashlib.sha256(saved.read_bytes()).hexdigest()
        target = self.home / "durable" / "ai_ledger.db"
        code, out, err = run_cli("ai-ledger", "restore", str(saved), str(target))
        self.assertEqual(code, 0, err)
        self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), before)  # evidence is read, never written
        ledger = SpendLedger(target, create=False)
        try:
            entries = ledger.entries("evaluation")
            exported = json.loads((EVIDENCE / "spending-ledger.json").read_text())
            keys = ("id", "use_case", "purpose", "provider", "model", "state", "outcome", "reserved_usd",
                    "actual_usd", "input_tokens", "output_tokens", "attempts", "reserved_at", "closed_at")
            def same(e):  # the export of that day rounded amounts to a millionth of a dollar
                return {k: round(e[k], 6) if isinstance(e[k], float) else e[k] for k in keys}

            self.assertEqual([same(e) for e in entries], [same(e) for e in exported])
            self.assertEqual(len(entries), 27)
            self.assertEqual(ledger.history("evaluation"), [{
                "period": "2026-11", "entries": 27, "spent_usd": 4.418875, "reserved_usd": 0.0,
                "carried_forward_usd": 0.0}])
            # what the platform itself reported that day (the report of 17 November wrote 4.418874 and 5.581126:
            # two rounded subtotals added by hand; the ledger and the view always said 4.418875 and 5.581125)
            shown = json.loads((EVIDENCE / "ai-view-after.json").read_text())
            usage = ledger.usage("evaluation", "month", datetime(2026, 11, 17, tzinfo=timezone.utc))
            self.assertEqual((usage["spent_usd"], round(10 - usage["spent_usd"], 6)), (4.418875, 5.581125))
            self.assertEqual((shown["usage"]["spent_usd"], shown["remaining_usd"], shown["usage"]["settled"]),
                             (usage["spent_usd"], 5.581125, usage["settled"]))
            self.assertEqual({e["model"] for e in entries}, {"claude-opus-5-5"})
            self.assertEqual([e["state"] for e in entries].count("settled"), 24)
            first = ledger.id
            self.assertTrue(first.startswith("adopted-"))  # a ledger from before identities: derived from its history
        finally:
            ledger.close()
        again = self.home / "second" / "ai_ledger.db"
        self.assertEqual(run_cli("ai-ledger", "restore", str(saved), str(again))[0], 0)
        ledger = SpendLedger(again, create=False)
        self.assertEqual(ledger.id, first)  # the same history is the same ledger, however often it is put back
        ledger.close()
        # and a deployment written on it has 5.58 USD left of 10, not 10
        code, said = run_setup(self.home / "deployment", target)
        self.assertEqual(code, 0, said)
        self.assertIn("4.418875 USD spent", said)


if __name__ == "__main__":
    unittest.main()
