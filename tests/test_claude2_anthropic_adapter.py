"""Claude activation, increment 2: the Anthropic adapter against the official SDK itself.

Until now the adapter had only met a hand-written client double. Here the real ``anthropic`` SDK client runs, with
its HTTP transport replaced by a local function: every request the SDK would put on the wire is inspected, and
every answer is parsed by the SDK's own code. **Nothing leaves the machine and no key exists**: what these tests
establish is that the adapter and the installed SDK agree, not that the provider accepts the request. That needs
one authorised call.

  A1 the request the SDK builds: one model, the answer's schema, no tools, no fallback to another model, the
     key only in its header
  A2 an answer with a thinking block and a text block is read, counted and priced, cache tokens included
  A3 a cut answer, a refusal, a tool request and an unknown stop are failures, never partial answers; a tool
     request executes nothing
  A4 the provider's errors are classified from the SDK's own exceptions: authentication, rate limit, overload,
     server error, bad request, timeout, no connection; the SDK retries nothing by itself; no error text carries
     the key or the prompt
  A5 the gateway's deadline reaches the SDK as its timeout
  A6 the architect's contract uses only what the provider's structured output supports
"""

import json
import unittest

from autology import platform as platform_module
from autology.ai import PROMPTED, AnthropicProvider, ModelGateway, ModelRequest, ProviderError, WorkspaceAI, unfenced
from autology.architect import SCHEMA
from autology.reasoners import PRICES

try:
    import anthropic
    import httpx2 as httpx  # the HTTP library the SDK itself uses
except ImportError:  # the optional "llm" extra is not installed
    anthropic = httpx = None

MODEL = "claude-opus-5-5"
KEY = "sk-ant-test-NEVER-SENT-ANYWHERE-0123456789"
PROMPT = "Describe the claims process of Northwind Mutual."
ANSWER = {"summary": "ok"}
ANSWER_SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"],
                 "additionalProperties": False}


TEXT = json.dumps(ANSWER)


def message(text=TEXT, stop="end_turn", content=None, model=MODEL, usage=None):
    blocks = content if content is not None else [
        {"type": "thinking", "thinking": "", "signature": "sig"}, {"type": "text", "text": text}]
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": model, "content": blocks,
            "stop_reason": stop, "stop_sequence": None,
            "usage": usage or {"input_tokens": 1200, "output_tokens": 800, "cache_creation_input_tokens": 400,
                               "cache_read_input_tokens": 0}}


def error(status, kind, headers=None):
    return httpx.Response(status, headers=headers or {}, json={
        "type": "error", "error": {"type": kind, "message": f"{kind}: detail from the provider"}})


@unittest.skipIf(anthropic is None, "the anthropic SDK is not installed")
class AdapterBase(unittest.TestCase):
    def setUp(self):
        self.seen, self.plan, self.events = [], [], []

        def handler(request):
            self.seen.append(request)
            step = self.plan.pop(0) if self.plan else message()
            if isinstance(step, Exception):
                raise step
            return step if isinstance(step, httpx.Response) else httpx.Response(200, json=step)

        self.transport = httpx.MockTransport(handler)
        # built the way the platform builds it for a workspace (the key from the policy's reference)
        self.provider = platform_module.PROVIDER_ADAPTERS["anthropic"]({}, KEY, http_client=httpx.Client(transport=self.transport))
        self.assertIsInstance(self.provider, AnthropicProvider)
        self.gateway = ModelGateway({"anthropic": self.provider},
                                    {"eval": WorkspaceAI("anthropic", MODEL, ("synthetic",), 2, 30.0, 16000)},
                                    sink=self.events.append, backoff_seconds=0.01)

    def ask(self, schema=ANSWER_SCHEMA, **changes):
        return self.gateway.invoke(ModelRequest("eval", "architect.propose", "You design business models.", PROMPT,
                                                schema, {"brief": "synthetic"}, ("synthetic",), 30.0, 16000,
                                                **changes))

    def body(self, index=-1):
        return json.loads(self.seen[index].content)


class RequestTests(AdapterBase):
    def test_the_request_the_sdk_puts_on_the_wire(self):  # A1
        response = self.ask(effort="high")
        self.assertEqual(response.data, ANSWER)
        request, body = self.seen[0], self.body(0)
        self.assertEqual((request.method, request.url.host, request.url.path), ("POST", "api.anthropic.com", "/v1/messages"))
        # the key travels in one header and nowhere else (this SDK sends an API key as a bearer credential)
        self.assertEqual(request.headers["authorization"], f"Bearer {KEY}")
        self.assertEqual([name for name, value in request.headers.items() if KEY in value], ["authorization"])
        self.assertNotIn(KEY, request.content.decode())
        self.assertNotIn(KEY, str(request.url))
        self.assertEqual(request.headers["anthropic-version"], "2026-10-21")  # what SDK 2.x speaks; see the log
        self.assertNotIn("fallback", request.headers.get("anthropic-beta", ""))
        self.assertEqual((body["model"], body["max_tokens"]), (MODEL, 16000))
        self.assertEqual(body["output_config"], {"effort": "high", "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}})
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertIn("<<<UNTRUSTED_DATA", body["messages"][0]["content"])  # the brief travels as marked data
        self.assertIn("never", body["system"])
        self.assertIn("You have no tools", body["system"])
        # nothing a model could act through, no second model, nothing Autology did not decide
        for absent in ("tools", "tool_choice", "fallbacks", "mcp_servers", "thinking", "temperature", "stream"):
            self.assertNotIn(absent, body, absent)
        self.assertEqual(set(body), {"model", "max_tokens", "cache_control", "output_config", "system", "messages"})

    def test_the_architects_contract_is_within_the_structured_output_rules(self):  # A6
        supported = {"type", "properties", "required", "enum", "items", "additionalProperties"}
        optional, problems = [], []

        def walk(node, path):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    if node.get("additionalProperties") is not False:
                        problems.append(f"{path}: an object must close its properties")
                    optional.extend(sorted(set(node.get("properties", {})) - set(node.get("required", []))))
                for key, value in node.items():
                    if not path.endswith(".properties") and key not in supported:
                        problems.append(f"{path}: {key} is not supported")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for value in node:
                    walk(value, path)

        walk(SCHEMA, "$")
        self.assertEqual(problems, [])
        self.assertLessEqual(len(optional), 24, optional)  # the provider bounds optional properties per request
        self.plan = [message(json.dumps({k: [] for k in SCHEMA["required"]}))]
        self.ask(schema=SCHEMA)
        self.assertEqual(self.body()["output_config"]["format"]["schema"], json.loads(json.dumps(SCHEMA)))  # sent unchanged

    def test_a_schema_the_provider_will_not_compile_is_asked_for_in_the_instructions(self):  # A6
        """The first real requests were refused in a third of a second: "The compiled grammar is too large".
        Nothing is processed or billed for such a refusal. The same request then goes once with the schema in the
        instructions; the gateway checks the answer against the schema either way."""
        refusal = httpx.Response(400, json={"type": "error", "error": {
            "type": "invalid_request_error",
            "message": "The compiled grammar is too large, which would cause performance issues. Simplify your tool "
                       "schemas or reduce the number of strict tools."}})
        answer = {k: [] for k in SCHEMA["required"]}
        self.plan = [refusal, message("```json\n" + json.dumps(answer) + "\n```")]
        response = self.ask(schema=SCHEMA)
        self.assertEqual((response.data, response.attempts), (answer, 1))  # one attempt for the gateway and the ledger
        self.assertEqual(len(self.seen), 2)
        first, second = self.body(0), self.body(1)
        self.assertIn("format", first["output_config"])
        self.assertEqual(second["output_config"], {"effort": "medium"})  # no grammar asked for
        self.assertTrue(second["system"].startswith(first["system"]))
        self.assertIn(PROMPTED.strip(), second["system"])
        self.assertTrue(second["system"].endswith(json.dumps(SCHEMA)))  # the contract itself, as written
        self.assertEqual((second["model"], second["messages"]), (first["model"], first["messages"]))
        for absent in ("tools", "tool_choice", "fallbacks", "temperature"):
            self.assertNotIn(absent, second)

        self.plan = [message(json.dumps(answer))]
        self.ask(schema=SCHEMA)  # remembered: the doomed request is not sent again
        self.assertEqual(len(self.seen), 3)
        self.assertNotIn("format", self.body()["output_config"])
        self.ask()  # a small schema still gets the provider's grammar
        self.assertIn("format", self.body()["output_config"])

        # asked in the instructions, an answer is still only as good as the contract says
        for bad in ("Here is the proposal: {}", json.dumps({**answer, "grants": ["admin"]}), json.dumps(answer)[:-1]):
            self.plan = [message(bad)]
            with self.assertRaises(ProviderError) as caught:
                self.ask(schema=SCHEMA)
            self.assertEqual(caught.exception.kind, "invalid_response", bad)
        self.assertEqual(unfenced('```\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(unfenced(' {"a": 1} '), '{"a": 1}')

    def test_another_invalid_request_is_not_sent_twice(self):  # A6
        self.plan = [error(400, "invalid_request_error")]
        with self.assertRaises(ProviderError) as caught:
            self.ask(schema=SCHEMA)
        self.assertEqual((caught.exception.kind, len(self.seen)), ("invalid_request", 1))

    def test_the_environment_cannot_redirect_the_key_or_add_a_credential(self):  # A1
        import os
        from unittest import mock

        hostile = {"ANTHROPIC_BASE_URL": "https://collector.example.net", "ANTHROPIC_AUTH_TOKEN": "another-credential",
                   "ANTHROPIC_API_KEY": "a-key-from-the-environment"}
        with mock.patch.dict(os.environ, hostile):
            provider = platform_module.PROVIDER_ADAPTERS["anthropic"](
                {}, KEY, http_client=httpx.Client(transport=self.transport))
            gateway = ModelGateway({"anthropic": provider}, {"eval": WorkspaceAI("anthropic", MODEL, ("synthetic",))},
                                   sink=self.events.append)
            gateway.invoke(ModelRequest("eval", "architect.propose", "s", PROMPT, ANSWER_SCHEMA, None, ("synthetic",)))
        request = self.seen[-1]
        self.assertEqual(request.url.host, "api.anthropic.com")  # the provider's own address, whatever the environment says
        self.assertEqual(request.headers["authorization"], f"Bearer {KEY}")  # the workspace's key, not the environment's
        self.assertNotIn("x-api-key", request.headers)
        for value in hostile.values():
            self.assertNotIn(value.replace("https://", ""), json.dumps(dict(request.headers)) + str(request.url))
        with self.assertRaises(ValueError):  # no key: no client, rather than whatever the SDK finds by itself
            platform_module.PROVIDER_ADAPTERS["anthropic"]({}, None)

    def test_the_deadline_reaches_the_sdk(self):  # A5
        self.ask()
        timeout = self.seen[0].extensions["timeout"]
        self.assertTrue(all(0 < value <= 30.0 for value in timeout.values() if value is not None), timeout)


class AnswerTests(AdapterBase):
    def test_usage_and_cost_are_the_providers_figures_at_the_registered_price(self):  # A2
        response = self.ask()
        self.assertEqual(response.usage, {"input_tokens": 1200, "output_tokens": 800, "cache_creation_input_tokens": 400})
        price_in, price_out = PRICES[MODEL]
        self.assertAlmostEqual(response.cost_usd, (1200 * price_in + 400 * price_in * 1.25 + 800 * price_out) / 1e6)
        self.assertEqual((response.provider, response.model, response.attempts, response.unpriced_tokens),
                         ("anthropic", MODEL, 1, 0))
        attempt = self.events[-1]
        self.assertEqual((attempt["event"], attempt["outcome"], attempt["model"]), ("ai.attempt", "ok", MODEL))
        text = json.dumps(self.events)
        self.assertNotIn(KEY, text)
        self.assertNotIn(PROMPT, text)  # the log says how much was sent, never what

    def test_anything_but_a_complete_answer_is_a_failure(self):  # A3
        cases = [(message(stop="max_tokens"), "truncated"), (message(stop="refusal", content=[]), "refused"),
                 (message(stop="tool_use", content=[{"type": "tool_use", "id": "toolu_1", "name": "approve_release",
                                                     "input": {"release": 1}}]), "tool_request"),
                 (message(stop="pause_turn"), "invalid_response"), (message("not json"), "invalid_response"),
                 (message(json.dumps({"summary": 3})), "invalid_response"),
                 (message(content=[{"type": "thinking", "thinking": "", "signature": "s"}]), "invalid_response")]
        for reply, kind in cases:
            self.plan = [reply]
            with self.assertRaises(ProviderError) as caught:
                self.ask()
            self.assertEqual(caught.exception.kind, kind, reply)
            self.assertEqual(caught.exception.attempts, 1)  # none of these is tried again
        self.assertEqual(len(self.seen), len(cases))  # a tool request led to no second request: nothing ran

    def test_an_answer_from_another_model_is_not_used(self):  # A2 (identity)
        self.plan = [message(model="claude-haiku-5-5")]
        with self.assertRaises(ProviderError) as caught:
            self.ask()
        self.assertEqual((caught.exception.kind, caught.exception.uncertain), ("invalid_response", True))
        self.plan = [message(model=f"{MODEL}-20261101")]  # a dated name of the same model is the same model
        self.assertEqual(self.ask().model, f"{MODEL}-20261101")


class FailureTests(AdapterBase):
    def failure(self, *plan):
        self.plan, before = list(plan), len(self.seen)
        with self.assertRaises(ProviderError) as caught:
            self.ask()
        text = str(caught.exception)
        self.assertNotIn(KEY, text)
        self.assertNotIn(PROMPT, text)
        return caught.exception, len(self.seen) - before

    def test_provider_errors_are_classified_from_the_sdks_exceptions(self):  # A4
        for status, kind in ((401, "authentication_error"), (403, "permission_error")):
            exc, sent = self.failure(error(status, kind))
            self.assertEqual((exc.kind, exc.retryable, exc.uncertain, sent), ("auth", False, False, 1))
            self.assertIn(kind, str(exc))  # which kind of refusal, in the provider's own word
            self.assertNotIn("detail from the provider", str(exc))  # and no more than that
        for status, kind in ((400, "invalid_request_error"), (404, "not_found_error"), (413, "request_too_large")):
            exc, sent = self.failure(error(status, kind))
            self.assertEqual((exc.kind, sent), ("invalid_request", 1))
            # a request the provider calls invalid says why: nothing else tells the person what to correct
            self.assertIn(f"({kind}): {kind}: detail from the provider", str(exc))
        # a rate limit is tried again by the gateway (the SDK itself retries nothing), then given up
        exc, sent = self.failure(error(429, "rate_limit_error", {"retry-after": "0"}), error(429, "rate_limit_error"))
        self.assertEqual((exc.kind, exc.attempts, sent), ("rate_limited", 2, 2))
        for status, kind in ((500, "api_error"), (529, "overloaded_error")):
            exc, sent = self.failure(error(status, kind), error(status, kind))
            self.assertEqual((exc.kind, exc.uncertain, sent), ("unavailable", True, 2), status)
        exc, sent = self.failure(httpx.ReadTimeout("slow"))
        self.assertEqual((exc.kind, exc.uncertain, sent), ("timeout", True, 1))  # may have been processed: not retried
        exc, sent = self.failure(httpx.ConnectError("down"), httpx.ConnectError("down"))
        self.assertEqual((exc.kind, sent), ("unavailable", 2))

    def test_the_providers_reason_never_carries_a_credential_and_is_cut_short(self):  # A4
        leaky = httpx.Response(400, json={"type": "error", "error": {
            "type": "invalid_request_error",
            "message": f"Your credit balance is too low. key {KEY} header Bearer abc.def-123 other sk-ant-zzzzzzzzzzzz "
                       + "x" * 500}})
        exc, sent = self.failure(leaky)
        text = str(exc)
        self.assertIn("Your credit balance is too low", text)  # the reason reaches the person
        for secret in (KEY, "abc.def-123", "sk-ant-zzzzzzzzzzzz"):
            self.assertNotIn(secret, text)
        self.assertIn("[credential]", text)
        self.assertLessEqual(len(text), 310)
        for status in (429, 500, 529):  # other refusals: the kind, never the provider's text
            exc, _ = self.failure(error(status, "some_error"), error(status, "some_error"))
            self.assertNotIn("detail from the provider", str(exc))
        odd = httpx.Response(400, text="not json at all")  # a body that is not the provider's error object
        exc, _ = self.failure(odd)
        self.assertEqual(exc.kind, "invalid_request")

    def test_a_retry_that_succeeds_counts_every_attempt_once(self):  # A4
        self.plan = [error(529, "overloaded_error"), message()]
        response = self.ask()
        self.assertEqual((response.attempts, len(self.seen)), (2, 2))
        self.assertEqual(response.usage["output_tokens"], 800)  # the failed attempt reported no usage
        outcomes = [e["outcome"] for e in self.events if e["event"] == "ai.attempt"]
        self.assertEqual(outcomes, ["unavailable", "ok"])


if __name__ == "__main__":
    unittest.main()
