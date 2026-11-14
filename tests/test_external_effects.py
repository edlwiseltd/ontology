"""ACT-1 to ACT-5 (audit GAP-001 to GAP-007): external actions happen at most once and are never assumed done.

A fake bank executes each payment it receives (and records it), then answers in the way a test asks: normally,
after the client's timeout, by dropping the connection, with a 5xx, a 202, an empty body or a FAILED status.
A crash of the engine is a BaseException raised right after the bank executed the payment: nothing in the
process survives it, only what was committed to the store (as with SIGKILL).
"""

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from autology.server import ApiError, AutologyService

from .test_ingest import EX, TOKENS

TIMEOUT = 0.4


class Crash(BaseException):
    """The process dies: not an Exception, so nothing in the engine catches it."""


class Bank:
    """Executes every payment it receives; ``behaviour(n)`` says how call ``n`` (1-based) is answered."""

    def __init__(self):
        self.executed = []  # (idempotency key from header, key from payload)
        self.requests = 0
        self.behaviour = lambda n: "ok"
        self.dedupe = False  # an idempotent bank: the same key is executed once
        bank = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                key = self.headers.get("Idempotency-Key")
                bank.requests += 1
                mode = bank.behaviour(bank.requests)
                if mode == "429":
                    return self._reply(429, {})
                seen = bank.dedupe and any(k == key for k, _ in bank.executed)
                if not seen:
                    bank.executed.append((key, body.get("idempotency_key")))
                ref = f"TX-{[k for k, _ in bank.executed].index(key) + 1}"
                if mode == "timeout":
                    time.sleep(TIMEOUT * 3)
                elif mode == "reset":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                elif mode == "500":
                    return self._reply(500, {"error": "internal"})
                elif mode == "202":
                    return self._reply(202, {"message": "queued"})
                elif mode == "empty":
                    return self._reply(200, {})
                elif mode == "failed":
                    return self._reply(200, {"output": {"status": "FAILED"}})
                self._reply(200, {"updates": {"Payment": {"reference": ref}}, "message": "paid"})

            def _reply(self, code, data):
                raw = json.dumps(data).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/pay"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def config(folder: Path, bank_url: str, ontology=None, backoff=0, automations=False):
    tools = json.loads((EX / "tools.json").read_text())
    for t in tools["tools"]:
        if t["capability"] == "payments.pay":
            t.clear()
            t.update(name="bank", capability="payments.pay", type="http", url=bank_url, timeout=TIMEOUT)
    (folder / "tools.json").write_text(json.dumps(tools))
    cfg = json.loads((EX / "server.json").read_text())
    cfg["store"] = str(folder / "claims.db")
    cfg["agents"]["claims"]["tools"] = str(folder / "tools.json")
    cfg["pipelines"] = {}  # no claims feed: every payment in a test comes from the claim it starts
    if not automations:
        cfg["automations"] = {}
    if ontology is not None or backoff:
        doc = ontology or json.loads((EX / "ontology.json").read_text())
        if backoff:
            doc["actions"]["pay_claim"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": backoff}
        (folder / "ontology.json").write_text(json.dumps(doc))
        cfg["ontology"] = str(folder / "ontology.json")
    return cfg


class EffectsTestCase(unittest.TestCase):
    def setUp(self):
        os.environ.update({f"AUTOLOGY_TOKEN_{n.upper()}": t for n, t in TOKENS.items()})
        self.bank = Bank()
        self.addCleanup(self.bank.stop)
        self.folder = Path(tempfile.mkdtemp())

    def service(self, **kw):
        svc = AutologyService(config(self.folder, self.bank.url, **kw), EX)
        self.u = {x.name: x for x in svc.users}
        return svc

    def restart(self, **kw):
        return self.service(**kw)

    def crash_after_bank(self, svc):
        """The next payment call reaches the bank, then the process dies before it records the reply."""
        tool = next(t for t in svc.agents["claims"].agent.tools._tools if t.name == "bank")
        original = tool.handler

        def handler(call):
            original(call)
            raise Crash()

        tool.handler = handler

    def pay_calls(self, svc):
        return [c for c in svc.store.list_calls() if c["action"] == "pay_claim"]


class IntentLogTests(EffectsTestCase):  # ACT-1
    def test_the_intent_is_committed_before_the_call(self):
        svc = self.service()
        seen = []
        tool = next(t for t in svc.agents["claims"].agent.tools._tools if t.name == "bank")
        original = tool.handler

        def handler(call):
            seen.append(svc.store.get_call(call.idempotency_key))  # what a crash right now would leave
            return original(call)

        tool.handler = handler
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(run["status"], "completed")
        self.assertEqual(seen[0]["state"], "in_flight")
        self.assertEqual((seen[0]["action"], seen[0]["tool"], seen[0]["root"]), ("pay_claim", "bank", "CL-1"))
        done = self.pay_calls(svc)[0]
        self.assertEqual((done["state"], done["updates"]), ("done", {"Payment": {"reference": "TX-1"}}))
        self.assertEqual(done["run_id"], run["run_id"])
        events = [e.event for e in svc.store.load_run(run["run_id"]).audit]
        i = events.index("step.intent", events.index("step.intent") + 2)  # the payment's intent
        self.assertLess(i, len(events))
        self.assertIn("step.result", events[i:])
        self.assertTrue(svc.store.verify_audit(run["run_id"]))

    def test_after_a_crash_every_call_made_is_listed_with_its_state(self):
        svc = self.service()
        self.crash_after_bank(svc)
        with self.assertRaises(Crash):
            svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(svc.store.list_runs(), [])  # the run itself was never saved (audit GAP-007)
        svc = self.restart()
        self.assertEqual(len(self.bank.executed), 1)
        items = svc.list_reconciliation(self.u["admin"])["items"]
        # the payment (cut off) and the claim approval the lost run made in the claims system; the fraud score
        # has no side effect ("side_effect": "none") and needs nobody's attention
        self.assertEqual(sorted((i["action"], i["state"], i["root"], i["orphan"]) for i in items),
                         [("approve_claim", "done", "CL-1", True), ("pay_claim", "unknown", "CL-1", True)])
        self.assertTrue(all("was never saved" in i["question"] for i in items))
        self.assertTrue(all(i["key"] for i in items))


class IdempotencyKeyTests(EffectsTestCase):  # ACT-2
    def test_the_same_key_on_every_retry_and_in_header_and_payload(self):
        self.bank.behaviour = lambda n: "429" if n <= 2 else "ok"  # rate limited twice: not processed
        svc = self.service()
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(self.bank.executed), 1)
        header, payload = self.bank.executed[0]
        self.assertEqual(header, payload)
        self.assertEqual(self.pay_calls(svc)[0]["key"], header)
        self.assertEqual(self.pay_calls(svc)[0]["attempt"], 3)

    def test_different_steps_and_runs_have_different_keys(self):
        svc = self.service()
        svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-3"})
        keys = [c["key"] for c in svc.store.list_calls()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len({k for k, _ in self.bank.executed}), len(self.bank.executed))

    def test_the_same_key_after_a_deferral_and_a_restart(self):
        self.bank.behaviour = lambda n: "429" if n == 1 else "ok"
        svc = self.service(backoff=600)
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertEqual(run["status"], "deferred")
        first = self.pay_calls(svc)[0]["key"]
        svc = self.restart(backoff=600)
        svc.agents["claims"].agent.clock = lambda: 10 ** 12
        self.assertEqual(svc.tick()["resumed"], [{"run_id": run["run_id"], "status": "completed"}])
        self.assertEqual([k for k, _ in self.bank.executed], [first])


class OutcomeClassificationTests(EffectsTestCase):  # ACT-3: the audit's fault matrix
    def settle(self, svc, root="CL-1"):
        return svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": root})

    def test_ambiguous_failures_of_a_payment_are_never_repeated(self):
        for mode in ("timeout", "reset", "500"):
            with self.subTest(mode):
                self.bank.executed.clear()
                self.bank.requests = 0
                self.bank.behaviour = lambda n, mode=mode: mode
                self.folder = Path(tempfile.mkdtemp())
                svc = self.service()
                run = self.settle(svc)
                self.assertEqual(len(self.bank.executed), 1, "the bank must execute the payment once only")
                self.assertEqual(run["status"], "uncertain")
                call = self.pay_calls(svc)[0]
                self.assertEqual(call["state"], "unknown")
                stored = svc.store.load_run(run["run_id"])
                self.assertEqual(stored.run.pending_external["key"], call["key"])
                self.assertIn("step.result", [e.event for e in stored.audit])
                self.assertNotEqual(svc.graph.get("CL-1").attributes["status"], "paid")

    def test_a_refused_connection_is_retried_safely(self):
        svc = self.service()
        tool = next(t for t in svc.agents["claims"].agent.tools._tools if t.name == "bank")
        from autology.adapters import http_tool

        real, down = tool.handler, http_tool("http://127.0.0.1:9/pay", timeout=TIMEOUT)
        attempts = []

        def flaky(call):
            attempts.append(call.idempotency_key)
            return down(call) if len(attempts) == 1 else real(call)

        tool.handler = flaky
        self.assertEqual(self.settle(svc)["status"], "completed")
        self.assertEqual(len(self.bank.executed), 1)
        self.assertEqual(len(set(attempts)), 1)

    def test_an_idempotent_action_is_retried_with_the_same_key(self):
        doc = json.loads((EX / "ontology.json").read_text())
        doc["actions"]["pay_claim"]["side_effect"] = "idempotent"
        self.bank.dedupe = True
        self.bank.behaviour = lambda n: "timeout" if n == 1 else "ok"
        svc = self.service(ontology=doc)
        self.assertEqual(self.settle(svc)["status"], "completed")
        self.assertEqual(len(self.bank.executed), 1)  # the bank deduplicated the retry by its key

    def test_no_fallback_provider_after_an_unknown_outcome(self):
        svc = self.service()
        from autology import ToolResult

        second = []
        svc.agents["claims"].agent.tools.register("other_bank", "payments.pay",
                                                  lambda call: second.append(call) or ToolResult(), priority=-1)
        self.bank.behaviour = lambda n: "timeout"
        self.assertEqual(self.settle(svc)["status"], "uncertain")
        self.assertEqual((len(self.bank.executed), second), (1, []))

    def test_a_rejected_payment_is_not_retried(self):
        svc = self.service()
        tool = next(t for t in svc.agents["claims"].agent.tools._tools if t.name == "bank")
        from autology import Rejected

        calls = []

        def refuse(call):
            calls.append(call)
            raise Rejected("account closed")

        tool.handler = refuse
        run = self.settle(svc)
        self.assertEqual((run["status"], len(calls)), ("escalated", 1))
        self.assertEqual(self.pay_calls(svc)[0]["state"], "rejected")


class ConfirmationTests(EffectsTestCase):  # ACT-4
    def test_accepted_or_empty_replies_are_not_done(self):
        for mode, detail in (("202", "has not confirmed"), ("empty", "does not confirm Payment.reference")):
            with self.subTest(mode):
                self.bank.behaviour = lambda n, mode=mode: mode
                self.folder = Path(tempfile.mkdtemp())
                svc = self.service()
                run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
                self.assertEqual(run["status"], "pending_confirmation")
                call = self.pay_calls(svc)[0]
                self.assertEqual(call["state"], "pending_confirmation")
                self.assertIn(detail, call["detail"])
                self.assertNotEqual(svc.graph.get("CL-1").attributes["status"], "paid")
                self.assertIsNone(svc.graph.get("PAY-1").attributes.get("reference"))

    def test_a_failed_status_is_never_completed(self):
        doc = json.loads((EX / "ontology.json").read_text())
        doc["actions"]["pay_claim"]["confirmation"]["accepted"] = ["SETTLED"]
        self.bank.behaviour = lambda n: "failed"
        svc = self.service(ontology=doc)
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        self.assertNotIn(run["status"], ("completed", "pending_confirmation"))
        self.assertEqual(self.pay_calls(svc)[0]["state"], "rejected")
        self.assertNotEqual(svc.graph.get("CL-1").attributes["status"], "paid")

    def test_a_confirmation_field_must_be_written_by_the_action(self):
        from autology import Ontology, OntologyError

        doc = json.loads((EX / "ontology.json").read_text())
        doc["actions"]["pay_claim"]["confirmation"]["fields"] = ["Payment.amount"]
        with self.assertRaises(OntologyError):
            Ontology.from_dict(doc)


class RecoveryTests(EffectsTestCase):  # ACT-5
    def test_a_crash_after_approval_never_pays_twice(self):
        # the audit's 10a: the manager approves, the process dies during the payment, the run is recovered
        svc = self.service()
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-2"})
        svc.decide(self.u["ivan"], run["pending_review"], {"approved": True})
        review = [r for r in svc.store.list_reviews("pending") if r["run_id"] == run["run_id"]][0]
        self.crash_after_bank(svc)
        with self.assertRaises(Crash):
            svc.decide(self.u["maria"], review["review_id"], {"approved": True})
        svc = self.restart()  # recovers: the decision was recorded, the payment's outcome is unknown
        self.assertEqual(svc.store.get_review(review["review_id"])["status"], "approved")  # never reopened
        self.assertEqual(svc.store.load_run(run["run_id"]).status, "uncertain")
        self.assertEqual(len(self.bank.executed), 1)
        with self.assertRaises(ApiError) as cm:  # nobody can start another payment on the claim meanwhile
            svc.start_run(self.u["admin"], {"case_template": "claim_case", "root": "CL-2"})
        self.assertEqual(cm.exception.status, 409)
        key = svc.list_reconciliation(self.u["admin"])["items"][0]["key"]
        with self.assertRaises(ApiError) as cm:  # the person who started the run may not settle it
            svc.reconcile(self.u["hana"], key, {"done": True, "comment": "the bank says it was paid"})
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(ApiError):  # confirming a payment needs the bank's reference
            svc.reconcile(self.u["admin"], key, {"done": True, "comment": "checked the bank statement"})
        out = svc.reconcile(self.u["admin"], key, {"done": True, "comment": "checked the bank statement",
                                                    "updates": {"Payment": {"reference": "TX-1"}}})
        self.assertEqual(out["run"]["status"], "completed")
        self.assertEqual(len(self.bank.executed), 1)  # the run continued without paying again
        self.assertEqual(svc.graph.get("CL-2").attributes["status"], "paid")
        self.assertEqual(svc.graph.get("PAY-2").attributes["reference"], "TX-1")
        audit = svc.store.load_run(run["run_id"]).audit
        self.assertIn("external.reconciled", [e.event for e in audit])
        self.assertIn("step.replayed", [e.event for e in audit])
        self.assertTrue(svc.store.verify_audit(run["run_id"]))

    def test_confirmed_not_done_calls_again_with_the_same_key(self):
        self.bank.behaviour = lambda n: "timeout" if n == 1 else "ok"
        svc = self.service()
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        key = self.pay_calls(svc)[0]["key"]
        out = svc.reconcile(self.u["admin"], key, {"done": False, "comment": "no transfer on the statement"})
        self.assertEqual(out["run"]["status"], "completed")
        self.assertEqual([k for k, _ in self.bank.executed], [key, key])
        self.assertEqual(svc.store.load_run(run["run_id"]).status, "completed")

    def test_a_deferred_run_killed_in_flight_does_not_pay_again(self):
        # the audit's 10c
        self.bank.behaviour = lambda n: "429" if n == 1 else "ok"
        svc = self.service(backoff=600)
        run = svc.start_run(self.u["hana"], {"case_template": "claim_case", "root": "CL-1"})
        svc.agents["claims"].agent.clock = lambda: 10 ** 12
        self.crash_after_bank(svc)
        with self.assertRaises(Crash):
            svc.tick()
        svc = self.restart(backoff=600)
        svc.agents["claims"].agent.clock = lambda: 10 ** 12
        svc.tick()
        self.assertEqual(len(self.bank.executed), 1)
        self.assertEqual(svc.store.load_run(run["run_id"]).status, "uncertain")

    def test_an_automation_retry_never_starts_a_second_payment(self):
        # the audit's 10e: the firing fails after the run paid, and the automation retries
        svc = self.service(automations=True)
        real = svc.store.save_run
        failures = {"n": 1}

        def flaky(*a, **k):
            if failures["n"]:
                failures["n"] -= 1
                raise RuntimeError("database is locked")
            return real(*a, **k)

        with mock.patch.object(svc.store, "save_run", side_effect=flaky):
            svc.upsert_object(self.u["admin"], {"type": "Claim", "id": "CL-1", "attributes": {
                **{k: v for k, v in svc.graph.get("CL-1").attributes.items() if v is not None}, "status": "reported"}})
        self.assertEqual(len(self.bank.executed), 1)
        for _ in range(3):
            svc.tick()
        cl1 = [c for c in self.pay_calls(svc) if c["root"] == "CL-1"]
        self.assertEqual(len(cl1), 1)  # the retry was refused: CL-1 has a payment nobody has reconciled
        self.assertEqual(len(self.bank.executed), 1)
        items = svc.list_reconciliation(self.u["admin"])["items"]
        self.assertTrue(any(i["orphan"] and i["root"] == "CL-1" for i in items), items)


if __name__ == "__main__":
    unittest.main()
