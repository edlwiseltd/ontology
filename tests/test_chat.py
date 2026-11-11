"""Tier 2: the governed assistant and the append-only API access log."""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autology.chat import (AnthropicChatBackend, ChatTurn, GovernedChat, ScriptedChatBackend, _strict_ok,
                           echo_content, load_backend, tools_for)
from autology.server import ApiError

from .test_platform import TOKENS, _Api, service


def last_results(messages):
    """The tool results the backend received in the last user message."""
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], list):
            return {r["tool_use_id"]: r for r in m["content"]}
    return {}


def script(*steps):
    """A backend that plays ``steps`` in order; each step is a dict or a function of the messages."""
    seen = []

    def fn(messages, tools):
        seen.append((json.loads(json.dumps(messages, default=str)), [t["name"] for t in tools]))
        step = steps[min(len(seen), len(steps)) - 1]
        return step(messages) if callable(step) else step

    backend = ScriptedChatBackend(fn)
    backend.seen = seen
    return backend


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.svc = service(automations={})
        self.users = {u.name: u for u in self.svc.users}

    def chat(self, *steps):
        backend = script(*steps)
        return GovernedChat(self.svc, backend), backend

    def test_tools_follow_permissions(self):
        names = {u: [t["name"] for t in tools_for(self.svc, self.users[u])] for u in ("olivia", "lena", "audrey")}
        self.assertIn("start_run", names["olivia"])
        self.assertIn("what_if", names["olivia"])
        self.assertNotIn("list_reviews", names["olivia"])
        self.assertIn("list_reviews", names["lena"])
        self.assertNotIn("start_run", names["lena"])
        self.assertNotIn("what_if", names["audrey"])
        for tools in names.values():
            self.assertNotIn("decide_review", tools)  # people decide reviews, never the assistant

    def test_answers_with_the_users_access(self):
        chat, backend = self.chat(
            {"text": "Let me look.", "tool_calls": [{"name": "list_objects", "input": {"type": "Order"}},
                                                    {"name": "ask_question",
                                                     "input": {"question_id": "CQ-03", "params": {}}}]},
            {"text": "You can see orders O-1 and O-2. The EU total includes records hidden from you."})
        reply = chat.send(self.users["olivia"], "Which orders are there?")
        self.assertIn("O-1 and O-2", reply.reply)
        self.assertEqual([(c["name"], c["ok"]) for c in reply.tool_calls],
                         [("list_objects", True), ("ask_question", False)])
        messages, _ = backend.seen[1]
        results = list(last_results(messages).values())
        self.assertNotIn("O-3", results[0]["content"])  # row access applied to the tool result
        self.assertTrue(results[1]["is_error"])
        self.assertIn("error 403", results[1]["content"])
        self.assertIn("Signed in: olivia", chat.system_prompt(self.users["olivia"]))
        # the conversation continues, and belongs to olivia only
        chat2, backend2 = self.chat({"text": "Still two."})
        again = chat2.send(self.users["olivia"], "And now?", reply.chat_id)
        self.assertEqual(again.chat_id, reply.chat_id)
        self.assertEqual(len(backend2.seen[0][0]), 5)  # user, assistant, results, assistant, user
        with self.assertRaises(ApiError) as cm:
            chat2.send(self.users["lena"], "peek", reply.chat_id)
        self.assertEqual(cm.exception.status, 404)
        view = self.svc.chat_get(self.users["olivia"], reply.chat_id)
        self.assertEqual([t["role"] for t in view["turns"]], ["user", "assistant", "assistant", "user", "assistant"])
        self.assertEqual(view["turns"][1]["tools"], ["list_objects", "ask_question"])
        with self.assertRaises(ApiError):
            self.svc.chat_get(self.users["lena"], reply.chat_id)
        log = self.svc.store.access_log("olivia")
        self.assertEqual({(e["kind"], e["target"]) for e in log},
                         {("chat.tool", "list_objects"), ("chat.tool", "ask_question")})

    def test_starts_governed_runs_and_simulates(self):
        chat, _ = self.chat(
            {"tool_calls": [{"name": "start_run", "input": {"agent": "fulfilment", "goal": "fulfil_contract",
                                                             "case_template": "contract_case", "root": "K-1"}},
                            {"name": "what_if", "input": {"name": "x", "edits": [
                                {"op": "set", "id": "O-1", "attributes": {"amount": 1}}], "checks": []}},
                            {"name": "fly", "input": {}},
                            {"name": "get_object", "input": {}}]},
            {"text": "Run completed; the scenario changes O-1."})
        reply = chat.send(self.users["olivia"], "Fulfil K-1 and try a price change")
        self.assertEqual([c["ok"] for c in reply.tool_calls], [True, True, False, False])
        self.assertEqual(self.svc.store.list_runs(), [])  # proposed, not started
        pid = self.svc.list_proposals(self.users["olivia"])["items"][0]["proposal_id"]
        run = self.svc.confirm_proposal(self.users["olivia"], pid, {"confirm": True})  # the person confirms
        self.assertEqual(self.svc.store.load_run(run["run_id"]).status, "completed")
        self.assertEqual(self.svc.graph.get("O-3").attributes["status"], "invoiced")  # written back
        self.assertEqual(len(self.svc.store.list_scenarios("open")), 1)  # simulated, never committed
        chat2, backend = self.chat({"tool_calls": [{"name": "list_reviews", "input": {}},
                                                   {"name": "list_notifications", "input": {}},
                                                   {"name": "describe_ontology", "input": {}},
                                                   {"name": "list_runs", "input": {"status": ""}},
                                                   {"name": "get_run", "input": {"run_id": "nope"}},
                                                   {"name": "get_object", "input": {"id": "C-1"}}]},
                                   {"text": "done"})
        out = chat2.send(self.users["lena"], "What is waiting for me?")
        self.assertEqual([c["ok"] for c in out.tool_calls], [True, True, True, True, False, True])

    def test_stop_reasons(self):
        cases = [
            ({"stop_reason": "refusal"}, "declined"),
            ({"stop_reason": "max_tokens", "text": "partial"}, "cut off"),
            ({"stop_reason": "error", "error": "down"}, "unavailable right now (down)"),
        ]
        for step, expected in cases:
            with self.subTest(step):
                chat, _ = self.chat(step)
                self.assertIn(expected, chat.send(self.users["olivia"], "hi").reply)
        looping = GovernedChat(self.svc, script({"tool_calls": [{"name": "list_runs", "input": {"status": ""}}]}),
                               max_rounds=3)
        out = looping.send(self.users["olivia"], "loop")
        self.assertIn("maximum number of tool rounds", out.reply)
        self.assertEqual(len(out.tool_calls), 3)

        class Pausing:
            calls = 0

            def turn(self, system, messages, tools):
                Pausing.calls += 1
                if Pausing.calls == 1:
                    return ChatTurn([{"type": "text", "text": "…"}], "…", [], "pause_turn", {"output_tokens": 3})
                return ChatTurn([{"type": "text", "text": "done"}], "done", [], "end_turn", {"output_tokens": 2})

        out = GovernedChat(self.svc, Pausing()).send(self.users["olivia"], "long job")
        self.assertEqual((out.reply, out.usage), ("done", {"output_tokens": 5}))

    def test_big_results_are_truncated(self):
        self.svc.ontology_summary = lambda user: {"x": "y" * 50_000}
        chat, backend = self.chat({"tool_calls": [{"name": "describe_ontology", "input": {}}]}, {"text": "ok"})
        chat.send(self.users["olivia"], "describe")
        result = list(last_results(backend.seen[1][0]).values())[0]
        self.assertTrue(result["content"].endswith("...[truncated]"))


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.requests = response, error, []

    def create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


class AnthropicBackendTests(unittest.TestCase):
    def response(self, content, stop="tool_use"):
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=7,
                                cache_creation_input_tokens=0)
        return SimpleNamespace(content=content, stop_reason=stop, usage=usage, model="claude-opus-5-5")

    def test_request_and_response(self):
        blocks = [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": "Checking."},
                  SimpleNamespace(to_dict=lambda: {"type": "tool_use", "id": "t1", "name": "get_object",
                                                   "input": {"id": "C-1"}})]
        fake = FakeMessages(self.response(blocks))
        backend = AnthropicChatBackend(SimpleNamespace(beta=SimpleNamespace(messages=fake)))
        tools = [{"name": "get_object", "description": "d", "input_schema": {"type": "object", "properties": {},
                                                                              "additionalProperties": False}},
                 {"name": "free", "description": "d", "input_schema": {"type": "object", "properties": {
                     "p": {"type": "object", "additionalProperties": True}}}}]
        turn = backend.turn("SYS", [{"role": "user", "content": "hi"}], tools)
        req = fake.requests[0]
        self.assertEqual(req["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual((req["fallbacks"], req["betas"]), ("default", ["server-side-fallback-2026-07-01"]))
        self.assertEqual(req["output_config"], {"effort": "medium"})
        self.assertNotIn("thinking", req)  # adaptive by default on this model
        self.assertTrue(req["tools"][0]["strict"])
        self.assertNotIn("strict", req["tools"][1])  # free-form parameters cannot be strict
        self.assertEqual((turn.text, turn.stop_reason, turn.tool_calls[0].input), ("Checking.", "tool_use",
                                                                                   {"id": "C-1"}))
        self.assertEqual(turn.content[0]["type"], "thinking")  # thinking blocks go back unchanged
        self.assertEqual(turn.usage["cache_read_input_tokens"], 7)
        other = AnthropicChatBackend(SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(
            self.response([], "end_turn")))), model="claude-haiku-5-5")
        other.turn("S", [], [])
        self.assertNotIn("fallbacks", other.client.beta.messages.requests[0])

    def test_errors(self):
        import importlib.util

        if importlib.util.find_spec("anthropic") is None:
            backend = AnthropicChatBackend()
            turn = backend.turn("S", [], [])
            self.assertEqual((turn.stop_reason, turn.error), ("error", "the anthropic package is not installed"))

    def test_fallback_echo(self):
        blocks = [{"type": "thinking", "thinking": ""}, {"type": "tool_use", "id": "a"}, {"type": "text", "text": "x"},
                  {"type": "fallback"}, {"type": "thinking", "thinking": ""}, {"type": "text", "text": "y"}]
        self.assertEqual([b["type"] for b in echo_content(blocks)], ["text", "fallback", "thinking", "text"])
        self.assertEqual(echo_content(blocks[:3]), blocks[:3])
        self.assertTrue(_strict_ok([{"a": 1}]))
        self.assertFalse(_strict_ok([{"additionalProperties": True}]))


class LoadBackendTests(unittest.TestCase):
    def test_load(self):
        self.assertIsNone(load_backend(None))
        self.assertIsInstance(load_backend({"model": "claude-opus-5-5"}), AnthropicChatBackend)
        tmp = Path(tempfile.mkdtemp())
        (tmp / "my_chat_backend.py").write_text(
            "from autology.chat import ScriptedChatBackend\n"
            "def make():\n    return ScriptedChatBackend(lambda m, t: {'text': 'hello'})\n"
            "def broken():\n    return 42\n")
        self.assertIsInstance(load_backend({"backend": "my_chat_backend:make"}, (str(tmp),)), ScriptedChatBackend)
        with self.assertRaises(ValueError):
            load_backend({"backend": "my_chat_backend:broken"}, (str(tmp),))
        sys.modules.pop("my_chat_backend", None)


class ChatHttpTests(unittest.TestCase):
    def test_endpoints_and_access_log(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "hello_backend.py").write_text(
            "from autology.chat import ScriptedChatBackend\n"
            "backend = ScriptedChatBackend(lambda m, t: {'text': 'hello ' + m[-1]['content']})\n")
        sys.path.insert(0, str(tmp))
        try:
            off = service(chat=None)
            api = _Api(off)
            self.assertEqual(api.call("POST", "/api/chat", "olivia", {"message": "hi"})[0], 404)
            api.server.shutdown()
            svc = service(chat={"backend": "hello_backend:backend"})
            api = _Api(svc)
            status, out, _ = api.call("POST", "/api/chat", "olivia", {"message": "there"})
            self.assertEqual((status, out["reply"]), (200, "hello there"))
            self.assertEqual(api.call("POST", "/api/chat", "olivia", {"message": " "})[0], 400)
            self.assertEqual(api.call("GET", f"/api/chat/{out['chat_id']}", "olivia")[1]["turns"][1]["text"],
                             "hello there")
            self.assertEqual(api.call("GET", f"/api/chat/{out['chat_id']}", "lena")[0], 404)
            self.assertEqual(api.call("GET", "/api/me", "wrong-token")[0], 401)
            self.assertEqual(api.call("GET", "/api/access-log", "olivia")[0], 403)
            status, log, _ = api.call("GET", "/api/access-log", "audrey")
            entries = [(e["principal"], e["target"], e["status"]) for e in log["items"]]
            self.assertIn(("-", "GET /api/me", 401), entries)  # failed sign-ins are recorded too
            self.assertIn(("olivia", "POST /api/chat", 200), entries)
            self.assertIn(("lena", f"GET /api/chat/{out['chat_id']}", 404), entries)
            only = api.call("GET", "/api/access-log?principal=lena", "audrey")[1]["items"]
            self.assertEqual({e["principal"] for e in only}, {"lena"})
            api.server.shutdown()
            db = sqlite3.connect(svc.store.path)
            for sql in ("UPDATE access_log SET status=200", "DELETE FROM access_log"):
                with self.subTest(sql), self.assertRaises(sqlite3.DatabaseError):
                    db.execute(sql)
        finally:
            sys.path.remove(str(tmp))
            sys.modules.pop("hello_backend", None)


if __name__ == "__main__":
    unittest.main()
