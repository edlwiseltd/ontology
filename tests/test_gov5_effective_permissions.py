"""GOV-5 (owner decision D4): a run acts with the intersection of the requester's permissions and the agent's;
scheduled runs act as an explicitly authorised, least-privilege service identity."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from autology import AutoApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.server import AutologyService

from .test_platform import CASE, EX, TOKENS, add_big_order

NO_GRANT = {"name": "olga", "token_env": "AUTOLOGY_TOKEN_OLGA", "permissions": ["read", "run"], "roles": ["ops"]}
FULFIL = {"entity": "Contract", "when": "Contract.status == 'signed'", "trigger": "change",
          "run": {"agent": "fulfilment", "goal": "fulfil_contract", "case_template": "contract_case",
                  "as": "fulfilment-bot"}}


def service(**overrides):
    os.environ.update({f"AUTOLOGY_TOKEN_{n.upper()}": t for n, t in TOKENS.items()}, AUTOLOGY_TOKEN_OLGA="tok-olga")
    cfg = json.loads((EX / "server.json").read_text())
    cfg.update(store=str(Path(tempfile.mkdtemp()) / "s.db"), automations={}, chat=None,
               users=cfg["users"] + [NO_GRANT])
    cfg.update(overrides)
    return AutologyService(cfg, EX)


def user(svc, name):
    return next(u for u in svc.users if u.name == name)


class RequesterIntersectionTests(unittest.TestCase):
    def setUp(self):
        self.svc = service()
        self.body = add_big_order(self.svc)  # K-2: an 85,000 US order; its credit check is finance's (R-FIN-002)

    def test_without_a_grant_the_agent_cannot_act_beyond_the_requester(self):
        out = self.svc.start_run(user(self.svc, "olga"), self.body)
        result = self.svc.store.load_run(out["run_id"])
        self.assertEqual(out["status"], "escalated")
        self.assertNotIn("credit_check@O-4:ok", result.path)
        self.assertIn("credit_check", " ".join(result.escalation.details))
        start = next(e for e in result.audit if e.event == "run.start")
        self.assertEqual((start.data["roles"], start.data["acting_as"]), (["ops"], "olga"))
        self.assertEqual(start.data["agent_roles"], ["eu_ops", "finance", "ops"])

    def test_an_administrator_grant_lets_the_agent_use_that_role_for_this_person(self):
        olivia = user(self.svc, "olivia")  # ops, with "run_as": {"fulfilment": ["finance"]}
        self.assertEqual(self.svc.run_roles(self.svc.agents["fulfilment"], olivia), ["finance", "ops"])
        out = self.svc.start_run(olivia, self.body)
        self.assertEqual(out["status"], "awaiting_review")  # credit check done; shipping waits for a manager
        self.assertIn("credit_check@O-4:ok", self.svc.store.load_run(out["run_id"]).path)

    def test_the_reviewer_does_not_widen_the_run(self):
        out = self.svc.start_run(user(self.svc, "olivia"), self.body)
        self.svc.decide(user(self.svc, "lena"), out["pending_review"], {"approved": True})  # lena has eu_ops
        stored = self.svc.store.load_run(out["run_id"])
        self.assertEqual(stored.run.roles, ["finance", "ops"])  # still the requester's intersection
        self.assertTrue(self.svc.store.verify_audit(out["run_id"]))  # and sealed with the run record

    def test_administrators_use_the_agents_roles(self):
        admin = user(self.svc, "admin")
        self.assertEqual(self.svc.run_roles(self.svc.agents["fulfilment"], admin), ["eu_ops", "finance", "ops"])


class ServiceIdentityTests(unittest.TestCase):
    def test_an_automation_must_name_an_authorised_identity(self):
        bare = {**FULFIL, "run": {k: v for k, v in FULFIL["run"].items() if k != "as"}}
        with self.assertRaises(ValueError) as cm:
            service(automations={"fulfil": bare})
        self.assertIn("service identity", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            service(automations={"fulfil": FULFIL},
                    service_identities={"fulfilment-bot": {"roles": ["ops"], "agents": []}})
        self.assertIn("not authorised for agent fulfilment", str(cm.exception))

    def test_automations_act_with_the_identitys_roles_only(self):
        svc = service(automations={"fulfil": FULFIL},
                      service_identities={"fulfilment-bot": {"roles": ["ops", "eu_ops"], "agents": ["fulfilment"]}})
        add_big_order(svc)
        admin = user(svc, "admin")
        inst = svc.graph.get("K-2")
        svc.upsert_object(admin, {"type": "Contract", "id": "K-2", "attributes": {
            **{k: v for k, v in inst.attributes.items() if v is not None}, "status": "signed"}})
        firing = [f for f in svc.store.list_firings() if f["instance"] == "K-2"][0]
        result = svc.store.load_run(firing["run_id"])
        self.assertNotIn("credit_check@O-4:ok", result.path)  # the identity has no finance role
        start = next(e for e in result.audit if e.event == "run.start")
        self.assertEqual((start.data["acting_as"], start.data["started_by"]),
                         ("service:fulfilment-bot", "automation:fulfil"))
        self.assertEqual(start.data["roles"], ["eu_ops", "ops"])


class DelegateTests(unittest.TestCase):
    def test_delegates_are_narrowed_too(self):
        onto = Ontology.load(EX / "ontology.json")
        finance = WorkAgent("finance-desk", onto, load_tools(EX / "tools.json"), roles=["finance", "eu_ops"])
        lead = WorkAgent("lead", onto, load_tools(EX / "tools.json"), roles=["ops", "eu_ops"], delegates=[finance],
                         approver=AutoApprover())
        self.assertTrue(lead.run("fulfil_contract", CASE, "K-1").completed)  # the delegate does the credit check
        narrowed = lead.run("fulfil_contract", CASE, "K-1", roles=["ops", "eu_ops"])
        self.assertFalse(narrowed.completed)  # a requester without finance cannot reach it through the delegate
        self.assertEqual(finance.principal.roles, frozenset({"finance", "eu_ops"}))  # restored after the run


if __name__ == "__main__":
    unittest.main()
