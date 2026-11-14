"""GOV-1 (audit GAP-011): firing an automation by hand is governed like starting a run by hand."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from autology.server import ApiError, AutologyService

from .test_platform import EX, TOKENS, add_big_order

RITA = {"name": "rita", "token_env": "AUTOLOGY_TOKEN_RITA", "permissions": ["read", "run", "review"],
        "roles": ["ops", "eu_ops"], "reviewer_roles": ["logistics_manager"]}
OPS_ONLY = {"name": "otto", "token_env": "AUTOLOGY_TOKEN_OTTO", "permissions": ["read", "run"], "roles": ["ops"]}
FULFIL = {"description": "Fulfil signed contracts (checked daily here, so only manual firing runs in the test)",
          "entity": "Contract", "when": "Contract.status == 'signed'", "trigger": {"every": 86400},
          "run": {"agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case",
                  "write_back": False}}


def service(ontology_rules=None):
    os.environ.update({f"AUTOLOGY_TOKEN_{n.upper()}": t for n, t in TOKENS.items()},
                      AUTOLOGY_TOKEN_RITA="tok-rita", AUTOLOGY_TOKEN_OTTO="tok-otto")
    cfg = json.loads((EX / "server.json").read_text())
    folder = Path(tempfile.mkdtemp())
    cfg.update(store=str(folder / "s.db"), automations={"fulfil": FULFIL}, chat=None,
               users=cfg["users"] + [RITA, OPS_ONLY])
    base = EX
    if ontology_rules:
        onto = json.loads((EX / "ontology.json").read_text())
        onto["rules"] = onto["rules"] + ontology_rules
        for name in ("tools.json", "data.json"):
            (folder / name).write_text((EX / name).read_text())
        (folder / "ontology.json").write_text(json.dumps(onto))
        base = folder
    return AutologyService(cfg, base)


def user(svc, name):
    return next(u for u in svc.users if u.name == name)


def sign(svc, contract):
    admin = user(svc, "admin")
    inst = svc.graph.get(contract)
    svc.upsert_object(admin, {"type": "Contract", "id": contract,
                              "attributes": {**{k: v for k, v in inst.attributes.items() if v is not None},
                                             "status": "signed"}})


class ManualFiringTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        add_big_order(self.svc)  # K-2 covers an 85,000 order: shipping it needs a logistics_manager review
        self.rita = user(self.svc, "rita")

    def test_the_person_who_fires_it_cannot_approve_its_review(self):
        sign(self.svc, "K-2")
        out = self.svc.run_automation(self.rita, "fulfil", {"instance": "K-2"})
        firing = out["firings"][0]
        self.assertEqual(firing["status"], "awaiting_review")
        self.assertEqual(self.svc.store.run_starter(firing["run_id"]), "rita")
        review = [r for r in self.svc.store.list_reviews("pending") if r["run_id"] == firing["run_id"]][0]
        with self.assertRaises(ApiError) as cm:
            self.svc.decide(self.rita, review["review_id"], {"approved": True})
        self.assertEqual(cm.exception.status, 403)
        self.assertIn("you started this run", cm.exception.message)
        # another logistics manager may decide it
        lena = user(self.svc, "lena")
        self.assertNotEqual(self.svc.decide(lena, review["review_id"], {"approved": True})["status"], "awaiting_review")

    def test_the_condition_must_hold(self):
        out = self.svc.run_automation(self.rita, "fulfil", {"instance": "K-2"})  # K-2 is a draft
        firing = out["firings"][0]
        self.assertEqual((firing["status"], firing["run_id"]), ("skipped", None))
        self.assertIn("condition", firing["detail"])
        self.assertEqual(self.svc.store.list_runs(limit=10), [])

    def test_only_records_the_caller_may_see(self):
        otto = user(self.svc, "otto")  # ops only: EU orders are hidden from him
        sign(self.svc, "K-1")  # K-1 covers EU order O-3
        sign(self.svc, "K-2")
        out = self.svc.run_automation(otto, "fulfil", {})
        fired = {f["instance"] for f in out["firings"]}
        self.assertTrue(fired <= {i.id for i in self.svc.graph.instances("Contract") if self.svc.visible(i, otto)})
        self.assertNotIn("O-3", json.dumps(out))

    def test_the_start_run_checkpoint_applies(self):
        svc = service([{"id": "CP-START", "type": "checkpoint", "on": "start_run", "min_length": 12,
                        "description": "Say why you are starting work by hand"}])
        add_big_order(svc)
        sign(svc, "K-2")
        rita = user(svc, "rita")
        with self.assertRaises(ApiError) as cm:
            svc.run_automation(rita, "fulfil", {"instance": "K-2"})
        self.assertEqual(cm.exception.status, 428)
        out = svc.run_automation(rita, "fulfil", {"instance": "K-2", "justification": "customer escalation"})
        self.assertEqual(out["firings"][0]["status"], "awaiting_review")
        self.assertEqual(svc.store.list_justifications()[0]["principal"], "rita")


if __name__ == "__main__":
    unittest.main()
