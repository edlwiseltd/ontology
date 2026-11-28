"""Gates 80.1 to 80.3 (audit): the full fault-injection matrix.

Every combination of
  bank reply   {ok, timeout after executing, connection reset after executing, 5xx after executing,
                202 accepted, empty body, FAILED status}
  context      {inline, after two reviews, deferred retry, automation}
  crash        {none, the engine dies right after the bank executed}
  action       {non-idempotent (the default), idempotent with a deduplicating bank}
must end with: at most one execution at the bank; a claim marked paid only when the bank confirmed it with a
reference and nothing crashed; and, after a crash, the payment visible in the journal with its key.
"""

import itertools
import json
import tempfile
import unittest
from pathlib import Path

from .test_external_effects import EX, Bank, EffectsTestCase

MODES = ("ok", "timeout", "reset", "500", "202", "empty", "failed")
CONTEXTS = ("inline", "after_review", "deferred", "automation")


class FaultMatrixTests(EffectsTestCase):
    def ontology(self, idempotent):
        doc = json.loads((EX / "ontology.json").read_text())
        doc["actions"]["pay_claim"]["confirmation"] = {"fields": ["Payment.reference"]}
        if idempotent:
            doc["actions"]["pay_claim"]["side_effect"] = "idempotent"
        return doc

    def build(self, context, idempotent):
        kw = {"ontology": self.ontology(idempotent)}
        if context == "deferred":
            kw["backoff"] = 600
        if context == "automation":
            kw["automations"] = True
        return kw

    def drive(self, svc, context, crash):
        """Run the claim to the point where it pays; returns the claim id."""
        u = self.u
        if context == "inline":
            if crash:
                self.crash_after_bank(svc)
            svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})
            return "CL-1"
        if context == "after_review":
            run = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
            svc.decide(u["ivan"], run["pending_review"], {"approved": True})
            review = [r for r in svc.store.list_reviews("pending") if r["run_id"] == run["run_id"]][0]
            if crash:
                self.crash_after_bank(svc)
            svc.decide(u["maria"], review["review_id"], {"approved": True})
            return "CL-2"
        if context == "deferred":
            svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})  # 429 first: deferred
            svc.agents["claims"].agent.clock = lambda: 10 ** 12
            if crash:
                self.crash_after_bank(svc)
            svc.tick()
            return "CL-1"
        inst = svc.graph.get("CL-1")  # automation: the claim is reported, the automation settles it
        if crash:
            self.crash_after_bank(svc)
        svc.upsert_object(u["admin"], {"type": "Claim", "id": "CL-1", "attributes": {
            **{k: v for k, v in inst.attributes.items() if v is not None}, "status": "reported"}})
        return "CL-1"

    def test_the_whole_matrix(self):
        combos = list(itertools.product(MODES, CONTEXTS, (False, True), (False, True)))
        for mode, context, crash, idempotent in combos:
            with self.subTest(mode=mode, context=context, crash=crash, idempotent=idempotent):
                self.bank.stop()
                self.bank = Bank()
                self.bank.dedupe = idempotent
                first = "429" if context == "deferred" else None
                self.bank.behaviour = lambda n, mode=mode, first=first: first if (first and n == 1) else mode
                self.folder = Path(tempfile.mkdtemp())
                kw = self.build(context, idempotent)
                svc = self.service(**kw)
                crashed = False
                try:
                    claim = self.drive(svc, context, crash)
                except BaseException as exc:  # noqa: B036 - the simulated crash
                    if type(exc).__name__ != "Crash":
                        raise
                    crashed, claim = True, ("CL-2" if context == "after_review" else "CL-1")
                if crashed:
                    svc = self.restart(**kw)  # start-up recovery
                    if context == "deferred":
                        svc.agents["claims"].agent.clock = lambda: 10 ** 12
                    svc.tick()
                    svc.tick()
                executed = len(self.bank.executed)
                self.assertLessEqual(executed, 1, "the bank executed the payment more than once")
                if mode == "ok" and not crash:  # every context really reaches the bank and settles the claim
                    self.assertEqual((executed, svc.graph.get(claim).attributes["status"]), (1, "paid"))
                paid = svc.graph.get(claim).attributes["status"] == "paid"
                if paid:  # 80.1: never marked paid without the bank's confirmation
                    self.assertEqual(mode, "ok")
                    self.assertFalse(crashed and executed and not self.confirmed(svc, claim))
                    self.assertTrue(svc.graph.get(claim.replace("CL", "PAY")).attributes["reference"])
                if executed:  # 80.3: every call that reached the bank is visible with its key and state
                    calls = [c for c in self.pay_calls(svc) if c["root"] == claim]
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(calls[0]["key"], self.bank.executed[0][0])
                    if crashed:
                        self.assertIn(calls[0]["state"], ("unknown", "pending_confirmation", "done"))
                svc.store.close()
        self.assertEqual(len(combos), 112)

    def confirmed(self, svc, claim):
        return any(c["state"] in ("done", "resolved_done") for c in self.pay_calls(svc) if c["root"] == claim)


if __name__ == "__main__":
    unittest.main()
