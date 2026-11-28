"""Claude activation, increments 3 and 4: the evaluation deployment and the spending ceiling around it.

No provider is contacted: the adapter is replaced by the counting double, and the "key" is a made-up value.

  D1 the deployment is generated from the owner's decision, outside the repository, and holds no key: only the
     name of the variable; a model without a registered price, or a policy the authorisation would not cover,
     writes nothing
  D2 loaded as a platform it serves nothing until two people approved the policy and the key variable is set;
     then the use case is served by the named model, on synthetic data only, within the ceiling
  D3 the evaluation command refuses to fall back to a test double when the provider is not authorised
  S1 one workspace's spending never counts against another's, and a reservation covers the schema and the
     cache-writing surcharge of the request
"""

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from autology import ai_policy, platform as platform_module
from autology.ai import ModelRequest
from autology.architect import PROMPT, SCHEMA, SYSTEM
from autology.platform import Platform
from autology.reasoners import PRICES

from .test_arch2_ai_provider_governance import Double
from .test_r2_use_case_lifecycle import close
from .test_workspaces import Client

_spec = importlib.util.spec_from_file_location(
    "evaluation_setup", Path(__file__).resolve().parent.parent / "deploy" / "evaluation_setup.py")
evaluation_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluation_setup)

MODEL = "claude-opus-5-5"
KEY = "sk-ant-test-NEVER-A-REAL-KEY-0123456789"
TOKENS = {"AUTOLOGY_AUDIT_KEY": "test-audit", "EVALUATION_TOKEN_OWNER": "ev-owner", "EVALUATION_TOKEN_REVIEWER": "ev-reviewer",
          "EVALUATION_TOKEN_OPERATOR": "ev-operator", "EVALUATION_TOKEN_SUPERVISOR": "ev-supervisor"}
AI = "/platform/workspaces/evaluation/ai"
ARGS = ["--model", MODEL, "--monthly-usd", "25", "--per-request-usd", "1", "--expires", "2099-12-31",
        "--decision", "test: an owner decision would be named here"]


LEDGERS: dict = {}  # each deployment's spending ledger: outside the deployment, as the setup requires


def ledger_of(out):
    return LEDGERS.setdefault(str(out), Path(tempfile.mkdtemp()) / "ai_ledger.db")


def setup(out, *extra):
    text = io.StringIO()
    ledger = ledger_of(out)
    first = [] if ledger.exists() else ["--new-ledger", "--opening-spent-usd", "0", "--opening-reference", "test"]
    with redirect_stdout(text), redirect_stderr(text):
        try:
            code = evaluation_setup.main(["--out", str(out), "--ledger", str(ledger), *first, *ARGS, *extra])
        except SystemExit as exc:
            code = exc.code
    return code, text.getvalue()


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp()) / "deployment"
        patcher = mock.patch.dict(os.environ, TOKENS)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("EVALUATION_AI_KEY", None)
        self.pf = self.c = None
        self.addCleanup(self.stop)

    def stop(self):
        if self.c:
            self.c.server.shutdown()
            self.c.server.server_close()
        if self.pf:
            close(self.pf)
        self.pf = self.c = None

    def start(self):
        self.stop()
        self.pf = Platform.from_file(str(self.out / "platform.json"))
        self.c = Client(self.pf)

    def test_the_deployment_is_written_from_the_decision_and_holds_no_key(self):  # D1
        with mock.patch.dict(os.environ, {"EVALUATION_AI_KEY": KEY}):
            code, said = setup(self.out)
        self.assertEqual(code, 0, said)
        written = "".join(p.read_text() for p in self.out.rglob("*") if p.is_file())
        self.assertNotIn(KEY, written + said)  # the key was in the environment the whole time; it went nowhere
        self.assertIn("EVALUATION_AI_KEY (set here)", said)
        spec = json.loads((self.out / "platform.json").read_text())
        binding = spec["ai_authorisations"][0].pop("ledger")
        self.assertEqual(spec["ai_authorisations"], [{
            "workspace": "evaluation", "provider": "anthropic", "model": MODEL, "data_classes": ["synthetic"],
            "max_budget_usd_per_month": 25.0, "expires": "2099-12-31", "decision": "test: an owner decision would be named here"}])
        # the ceiling is counted in a ledger kept outside the deployment, which the authorisation names
        self.assertEqual(spec["ai_ledger"], str(ledger_of(self.out).resolve()))
        self.assertEqual((binding["entries"], binding["settled_usd"]), (0, 0.0))
        self.assertFalse(any(p.name == "ai_ledger.db" for p in self.out.rglob("*")))
        setting = json.loads((self.out / "usecase" / "server.json").read_text())["ai"]
        policy = json.loads((self.out / "policy.json").read_text())["policy"]
        self.assertEqual(policy["credential"], {"ref": "env:EVALUATION_AI_KEY"})
        self.assertEqual((policy["data_classes"], policy["limits"]["concurrency"], policy["retention"]["prompts"]),
                         (["synthetic"], 1, "none"))
        normal = ai_policy.validate_policy(policy, "EVALUATION_")[1]
        self.assertEqual(setting, {"provider": "anthropic", "model": MODEL, "policy": ai_policy.terms_fingerprint(normal),
                                   "data_classes": ["synthetic"], "content": "synthetic"})
        # refusals write nothing
        for extra, expected in ((["--model", "an-unpriced-model"], "no price"), (["--monthly-usd", "0.5", "--per-request-usd", "1"], None),
                                (["--expires", "2020-01-01"], "expired")):
            target = Path(tempfile.mkdtemp()) / "refused"
            code, said = setup(target, *extra)
            if expected is None:
                continue  # a smaller ceiling is the owner's to choose; nothing to refuse
            self.assertNotEqual(code, 0, said)
            self.assertIn(expected, said)
            self.assertFalse(target.exists())
        inside = Path(evaluation_setup.ROOT) / "would-be-committed"
        code, said = setup(inside)
        self.assertNotEqual(code, 0)
        self.assertFalse(inside.exists())
        with redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(evaluation_setup.main(["--check"]), 1)
        self.assertIn("NOT set", shown.getvalue())
        with mock.patch.dict(os.environ, {"EVALUATION_AI_KEY": KEY}), redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(evaluation_setup.main(["--check"]), 0)
        self.assertNotIn(KEY, shown.getvalue())

    def test_nothing_is_served_before_two_people_and_a_key(self):  # D2
        self.assertEqual(setup(self.out)[0], 0)
        double = Double()
        PRICES.setdefault(MODEL, (4.0, 20.0))
        original = double.invoke

        def invoke(call):  # the double answers as the model it stands for
            reply = original(call)
            reply.model = MODEL
            return reply

        double.invoke = invoke
        with mock.patch.dict(platform_module.PROVIDER_ADAPTERS, {"anthropic": lambda policy, key: double}):
            self.start()
            call = self.c.call
            status, view = call("GET", AI, "ev-owner")
            self.assertEqual((status, view["state"], view["transmits_externally"]), (200, "none", False))
            body = json.loads((self.out / "policy.json").read_text())
            status, out = call("POST", f"{AI}/policy", "ev-owner", body)
            self.assertEqual(status, 201, out)
            self.assertEqual(call("POST", f"{AI}/policy/{out['proposed']}/approve", "ev-owner", {"reason": "mine"})[0], 403)
            status, view = call("POST", f"{AI}/policy/{out['proposed']}/approve", "ev-reviewer", {"reason": "reviewed"})
            self.assertEqual(status, 200, view)
            self.assertEqual(view["state"], "unavailable")  # approved and authorised, and still no key: nothing is served
            self.assertIn("credential", view["reason"])
            ask = {"generator": "model", "brief": "An invented ground-handling company coordinates aircraft servicing."}
            engine = "/w/evaluation/u/architect/api/v1"
            self.assertEqual(call("POST", f"{engine}/architect/proposals", "ev-owner", ask)[0], 409)
            self.assertEqual(double.calls, [])

            with mock.patch.dict(os.environ, {"EVALUATION_AI_KEY": KEY}):
                self.start()  # the key is read when the platform starts: an operator's act, like the file itself
                view = self.c.call("GET", AI, "ev-owner")[1]
                self.assertEqual((view["state"], view["transmits_externally"], view["owner_authorisation"]["present"]),
                                 ("authorised", True, True))
                served = next(u for u in view["use_cases"] if u["id"] == "architect")
                self.assertEqual((served["state"], served["model"], served["content"], served["data_classes"]),
                                 ("authorised", MODEL, "synthetic", ["synthetic"]))
                status, proposal = self.c.call("POST", f"{engine}/architect/proposals", "ev-owner", ask)
                self.assertEqual(status, 200, proposal)
                self.assertEqual((proposal["provider"], proposal["model"]), ("anthropic", MODEL))  # kept on the proposal
                view = self.c.call("GET", AI, "ev-owner")[1]
                self.assertEqual(view["usage"]["settled"], 1)
                self.assertLess(view["remaining_usd"], 25.0)
                self.assertNotIn(KEY, json.dumps(view) + json.dumps(proposal))
                # a member with no grant on the use case asks nothing; another workspace does not exist here
                self.assertIn(self.c.call("POST", f"{engine}/architect/proposals", "ev-operator", ask)[0], (403, 404))
                self.assertEqual(len(double.calls), 1)

    def test_the_evaluation_never_falls_back_to_a_test_double(self):  # D3
        from autology.__main__ import main

        self.assertEqual(setup(self.out)[0], 0)
        said = io.StringIO()
        with redirect_stdout(said), redirect_stderr(said):
            code = main(["architect-eval", "--platform", str(self.out / "platform.json"), "--workspace", "evaluation",
                         "--use-case", "architect"])
        self.assertEqual(code, 2)
        self.assertIn("blocked", said.getvalue())
        self.assertNotIn("met ", said.getvalue())  # no scores were printed: nothing answered


class SpendingTests(unittest.TestCase):
    def test_workspaces_do_not_share_a_ceiling_and_a_reservation_covers_the_whole_request(self):  # S1
        PRICES.setdefault(MODEL, (4.0, 20.0))
        spec = {"provider": "anthropic", "model": MODEL, "data_classes": ["synthetic"], "purposes": ["architect"],
                "limits": {"max_input_tokens": 20000, "max_output_tokens": 16000, "concurrency": 1, "timeout_seconds": 300,
                           "max_attempts": 1},
                "budget": {"currency": "USD", "per_request": 1.0, "per_period": 0.5, "period": "month"},
                "credential": {"ref": "env:EVALUATION_AI_KEY"}, "retention": {"prompts": "none", "usage_days": 90},
                "evaluation": {"status": "not_evaluated"}}
        policy = ai_policy.validate_policy(spec, "EVALUATION_")[1]
        ledger = ai_policy.SpendLedger(f"{tempfile.mkdtemp()}/ledger.db")
        self.addCleanup(ledger.close)

        def request():
            return ModelRequest("engine", "architect.propose", SYSTEM, PROMPT, SCHEMA, {"brief": "x" * 700},
                                ("synthetic",), 300.0, 16000)

        tokens, amount = ai_policy.estimate(request(), policy)
        plain = (len(SYSTEM) + len(request().text())) / 3
        self.assertGreater(tokens, plain + len(json.dumps(SCHEMA)) / 3 - 1)  # the schema is counted as input
        price_in, price_out = PRICES[MODEL]
        self.assertAlmostEqual(amount, (tokens * price_in * 1.25 + 16000 * price_out) / 1e6)  # cache-writing surcharge
        self.assertLess(amount, 0.5)

        first = ai_policy.Budget(ledger, "evaluation", "architect", policy)
        other = ai_policy.Budget(ledger, "another-workspace", "architect", policy)
        entry = first.admit(request())
        first.settle(entry, usage={"input_tokens": 3000, "output_tokens": 20000}, cost=0.41, attempts=1, outcome="ok",
                     uncertain=False)
        with self.assertRaises(Exception) as caught:  # 0.41 spent of 0.50: the next reservation does not fit
            first.admit(request())
        self.assertEqual(getattr(caught.exception, "kind", ""), "budget_exceeded")
        other.settle(other.admit(request()), usage={"input_tokens": 1, "output_tokens": 1}, cost=0.01, attempts=1,
                     outcome="ok", uncertain=False)  # the other workspace has its own, untouched ceiling
        self.assertEqual(ledger.usage("another-workspace", "month")["settled"], 1)
        self.assertEqual(ledger.usage("evaluation", "month")["settled"], 1)
        self.assertAlmostEqual(ledger.usage("evaluation", "month")["spent_usd"], 0.41)


if __name__ == "__main__":
    unittest.main()
