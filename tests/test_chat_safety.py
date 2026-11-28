"""Review item 8: the assistant proposes runs instead of starting them, fails soft, and keeps confidential data home."""

import json
import unittest
from types import SimpleNamespace

from autology.chat import AnthropicChatBackend, GovernedChat, ScriptedChatBackend
from autology.server import ApiError

from .test_chat import FakeMessages, last_results, script
from .test_platform import _Api, add_big_order, service

START = {"name": "start_run", "input": {"agent": "fulfilment", "goal": "fulfil_contract",
                                        "case_template": "contract_case", "root": "K-2"}}


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.u = {x.name: x for x in self.svc.users}
        add_big_order(self.svc)

    def test_start_run_becomes_a_proposal_the_person_confirms(self):
        chat = GovernedChat(self.svc, script({"tool_calls": [START]}, {"text": "I have proposed the run."}))
        reply = chat.send(self.u["olivia"], "fulfil K-2")
        self.assertEqual(self.svc.store.list_runs(), [])  # nothing ran yet
        proposals = self.svc.list_proposals(self.u["olivia"])["items"]
        self.assertEqual(len(proposals), 1)
        pid = proposals[0]["proposal_id"]
        self.assertEqual(reply.tool_calls[0]["ok"], True)
        self.assertEqual(self.svc.list_proposals(self.u["lena"])["items"], [])  # only the person who asked
        with self.assertRaises(ApiError) as cm:
            self.svc.confirm_proposal(self.u["admin"], pid, {"confirm": True})  # not even an admin, for someone else
        self.assertEqual(cm.exception.status, 404)
        run = self.svc.confirm_proposal(self.u["olivia"], pid, {"confirm": True})
        self.assertEqual(run["status"], "awaiting_review")
        self.assertEqual(self.svc.store.run_starter(run["run_id"]), "olivia")
        with self.assertRaises(ApiError) as cm:
            self.svc.confirm_proposal(self.u["olivia"], pid, {"confirm": True})
        self.assertEqual(cm.exception.status, 409)  # once only

    def test_declining_a_proposal(self):
        chat = GovernedChat(self.svc, script({"tool_calls": [START]}, {"text": "proposed"}))
        chat.send(self.u["olivia"], "fulfil K-2")
        pid = self.svc.list_proposals(self.u["olivia"])["items"][0]["proposal_id"]
        self.assertEqual(self.svc.confirm_proposal(self.u["olivia"], pid, {"confirm": False})["status"], "declined")
        self.assertEqual(self.svc.store.list_runs(), [])

    def test_http(self):
        chat = GovernedChat(self.svc, script({"tool_calls": [START]}, {"text": "proposed"}))
        chat.send(self.u["olivia"], "fulfil K-2")
        api = _Api(self.svc)
        try:
            pid = api.call("GET", "/api/proposals", "olivia")[1]["items"][0]["proposal_id"]
            status, run, _ = api.call("POST", f"/api/proposals/{pid}/decision", "olivia", {"confirm": True})
            self.assertEqual((status, run["status"]), (200, "awaiting_review"))
        finally:
            api.server.shutdown()


class BackendFailureTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={}, chat=None)
        self.olivia = next(u for u in self.svc.users if u.name == "olivia")

    def test_sdk_rejecting_a_parameter_is_unavailable_not_a_crash(self):
        fake = FakeMessages(error=TypeError("create() got an unexpected keyword argument 'fallbacks'"))
        backend = AnthropicChatBackend(SimpleNamespace(beta=SimpleNamespace(messages=fake)))
        reply = GovernedChat(self.svc, backend).send(self.olivia, "hello")
        self.assertEqual(reply.stop_reason, "error")
        self.assertIn("unavailable", reply.reply)

    def test_missing_credentials_are_unavailable(self):
        class NoKey:
            @property
            def beta(self):
                raise RuntimeError("Could not resolve authentication method")

        reply = GovernedChat(self.svc, AnthropicChatBackend(NoKey())).send(self.olivia, "hello")
        self.assertIn("unavailable", reply.reply)

    def test_any_backend_exception_is_unavailable(self):
        def boom(messages, tools):
            raise ConnectionResetError("peer went away")

        reply = GovernedChat(self.svc, ScriptedChatBackend(boom)).send(self.olivia, "hello")
        self.assertIn("unavailable", reply.reply)


class RedactionTests(unittest.TestCase):
    def test_confidential_fields_never_reach_the_provider(self):
        import tempfile
        from pathlib import Path

        from .test_platform import EX

        doc = json.loads((EX / "ontology.json").read_text())
        doc["rules"] = [r for r in doc["rules"] if r["id"] != "CP-CREDIT"]  # no checkpoint masking it first
        tmp = Path(tempfile.mkdtemp())
        (tmp / "ontology.json").write_text(json.dumps(doc))
        svc = service(ontology=str(tmp / "ontology.json"), automations={}, chat=None)
        self.assertEqual(svc.get_object(next(u for u in svc.users if u.name == "audrey"), "C-1")["attributes"]
                         ["credit_limit"], 250000)  # audrey herself may read it...
        audrey = next(u for u in svc.users if u.name == "audrey")  # finance: may read credit limits herself
        backend = script({"tool_calls": [{"name": "get_object", "input": {"id": "C-1"}},
                                         {"name": "list_objects", "input": {"type": "Customer"}}]},
                         {"text": "done"})
        GovernedChat(svc, backend).send(audrey, "show C-1")
        sent = json.dumps(backend.seen[1][0])
        self.assertNotIn("250000", sent)  # ...but it is confidential, so it is not sent to the model provider
        self.assertIn("Northwind", sent)  # other fields still go

    def test_configured_fields_are_redacted_and_answers_withheld(self):
        svc = service(automations={}, chat=None)
        svc.chat_redact_fields = {"Order.amount"}
        lena = next(u for u in svc.users if u.name == "lena")
        backend = script({"tool_calls": [{"name": "get_object", "input": {"id": "O-1"}},
                                         {"name": "ask_question", "input": {"question_id": "CQ-03", "params": {}}}]},
                         {"text": "done"})
        GovernedChat(svc, backend).send(lena, "O-1?")
        results = list(last_results(backend.seen[1][0]).values())
        self.assertNotIn("9000", results[0]["content"])
        self.assertTrue(results[1]["is_error"])
        self.assertIn("not sent to the model provider", results[1]["content"])

    def test_config(self):
        svc = service(automations={}, chat=None)
        self.assertEqual(svc.chat_redact_sensitivities, {"confidential"})
        svc2 = service(automations={}, chat=None, chat_redact={"sensitivities": [], "fields": ["Customer.name"]})
        self.assertEqual((svc2.chat_redact_sensitivities, svc2.chat_redact_fields), (set(), {"Customer.name"}))
        with self.assertRaises(Exception):
            service(automations={}, chat=None, chat_redact={"fields": ["Ghost.x"]})


if __name__ == "__main__":
    unittest.main()
