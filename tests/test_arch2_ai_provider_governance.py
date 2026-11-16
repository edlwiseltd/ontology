"""Architect sprint, increment B: AI provider configuration per workspace, and spending control.

No provider is contacted by these tests: the "real provider" is a counting test double registered as an adapter
for the test, with a registered price, so that budgets can be measured.

  G1 nothing is configured by default; a policy is validated field by field; a key is never accepted, stored or
     echoed: only a reference to where it lives, under the workspace's own prefix
  G2 a policy takes two people: the proposer cannot approve; a service identity can do neither; one person may
     always withdraw or disable; every step is in the signed administration log
  G3 a policy in the registry is not permission to transmit: without the owner's authorisation in the platform's
     deployment configuration the provider is never called; an authorisation that names another model, fewer data
     classes, a smaller budget or a past date does not cover the policy
  G4 the budget is enforced before a call, durably: per request, per period, concurrency; parallel requests cannot
     overspend; a duplicate request id is never charged twice; an uncertain outcome stays charged; a failure before
     any answer releases the reservation; an unpriced model is not called; if the ledger is unavailable nothing is
     sent; the ledger survives a restart
  G5 another workspace cannot see, use or spend anything of this one; the policy view never contains a key
  G6 the sandbox keeps answering without any policy, and may be bounded by one
"""

import json
import os
import threading
from unittest import mock

from autology import ai_policy, platform as platform_module
from autology.ai import Capabilities, ModelRequest, ProviderError, ProviderReply
from autology.architect import SCHEMA
from autology.reasoners import PRICES

from .test_act2_release_configuration import WS
from .test_adm1_administration import AdminBase
from .test_workspaces import EX, data_admins

AI = f"{WS}/ai"
UC = f"{WS}/use-cases/novel"
ENGINE = "/w/acme/u/novel/api/v1"
MODEL = "double-model-1"
KEY = "sk-test-NEVER-SHOWN-0123456789"
EMPTY = {k: [] for k in SCHEMA["required"]}  # the optional parts of the contract are left out
ANSWER = {**EMPTY, "questions": [{"id": "volume", "question": "How many cases a day?", "why": "sizing"}]}


class Double:
    """A provider double that counts calls and reports usage; ``plan`` scripts failures."""
    name = "double"

    def __init__(self):
        self.calls, self.plan, self.gate = [], [], None

    def capabilities(self):
        return Capabilities("double", "in-process double", "native", True, True, False, "a test double")

    def invoke(self, call):
        self.calls.append(call.request_id)
        if self.gate is not None:
            self.gate.wait(10)
        if self.plan:
            step = self.plan.pop(0)
            if isinstance(step, Exception):
                raise step
        return ProviderReply(json.dumps(ANSWER), "complete", {"input_tokens": 1000, "output_tokens": 500}, MODEL)


def policy(**changes):
    base = {"provider": "double", "model": MODEL, "data_classes": ["synthetic", "model_design"],
            "purposes": ["architect"],
            "limits": {"max_input_tokens": 50000, "max_output_tokens": 2000, "concurrency": 2, "timeout_seconds": 20,
                       "max_attempts": 2},
            "budget": {"currency": "USD", "per_request": 1.0, "per_period": 5.0, "period": "month"},
            "credential": {"ref": "env:ACME_AI_KEY"}, "retention": {"prompts": "none", "usage_days": 90},
            "evaluation": {"status": "not_evaluated"}}
    for key, value in changes.items():
        base[key] = {**base[key], **value} if isinstance(base.get(key), dict) and isinstance(value, dict) else value
    return base


AUTHORISATION = {"workspace": "acme", "provider": "double", "model": MODEL,
                 "data_classes": ["synthetic", "model_design"], "max_budget_usd_per_month": 50,
                 "expires": "2099-12-31", "decision": "test: an owner decision would be named here"}


class GovernanceBase(AdminBase):
    authorisations = [AUTHORISATION]

    def setUp(self):
        self.double = Double()
        PRICES[MODEL] = (100.0, 200.0)  # USD per million tokens: 1000 in + 500 out = 0.20 USD a call
        self.addCleanup(PRICES.pop, MODEL, None)
        patcher = mock.patch.dict(platform_module.PROVIDER_ADAPTERS, {"double": lambda p, key: self.double})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ["ACME_AI_KEY"] = KEY
        self.addCleanup(os.environ.pop, "ACME_AI_KEY", None)
        super().setUp()

    def start(self):  # the platform of AdminBase, with the owner's authorisations of this test class
        self.stop()
        from autology.platform import Platform

        from .test_workspaces import Client

        spec = data_admins(json.loads((EX / "platform.json").read_text()))
        spec["data_dir"] = self.data_dir
        spec["workspaces"]["acme"]["use_cases"]["claims"]["config"] = str(self.config_dir / "server.json")
        spec["ai_authorisations"] = list(self.authorisations)
        # a use case whose configuration asks for the provider (a governing setting of the use case)
        config = json.loads((EX.parent / "onboarding" / "server.json").read_text())
        config["ai"] = {"provider": "double"}
        (self.config_dir / "novel.json").write_text(json.dumps(config))
        (self.config_dir / "ontology.json.novel").write_text(json.dumps({"name": "novel", "version": "0.1.0"}))
        config["ontology"] = "ontology.json.novel"
        (self.config_dir / "novel.json").write_text(json.dumps(config))
        spec["workspaces"]["acme"]["use_cases"]["novel"] = {"name": "Novel case", "config": str(self.config_dir / "novel.json")}
        self.pf = Platform(spec, EX)
        self.c = Client(self.pf)

    def approve_policy(self, **changes):
        status, out = self.call("POST", f"{AI}/policy", body={"policy": policy(**changes), "reason": "evaluation"})
        self.assertEqual(status, 201, out)
        status, view = self.call("POST", f"{AI}/policy/{out['proposed']}/approve", "acme-maria", {"reason": "reviewed"})
        self.assertEqual(status, 200, view)
        return view

    def ask(self, token="acme-ada", brief="Coordinate vessel berthing at a container port."):
        return self.call("POST", f"{ENGINE}/architect/proposals", token, {"generator": "model", "brief": brief})


class PolicyTests(GovernanceBase):
    def test_nothing_by_default_and_a_policy_is_validated(self):  # G1
        status, view = self.call("GET", AI)
        self.assertEqual((status, view["state"], view["policy"], view["transmits_externally"], view["pending"]),
                         (200, "none", None, False, []))
        self.assertEqual(self.ask()[0], 409)  # the use case asks for a provider; nothing may serve it
        self.assertEqual(self.double.calls, [])
        novel = next(u for u in view["use_cases"] if u["id"] == "novel")
        self.assertEqual((novel["state"], novel["wanted"]), ("not_authorised", "double"))
        bad = [({"provider": "Double!"}, "provider"), ({"model": ""}, "model"), ({"data_classes": ["secrets"]}, "data_classes"),
               ({"purposes": ["agent"]}, "purposes"), ({"limits": {"concurrency": 0}}, "limits.concurrency"),
               ({"budget": {"currency": "EUR"}}, "budget.currency"), ({"budget": {"period": "year"}}, "budget.period"),
               ({"retention": {"prompts": "keep"}}, "retention"), ({"evaluation": {"status": "great"}}, "evaluation"),
               ({"expires": "soon"}, "expires"), ({"credential": {"ref": "env:NORTHWIND_AI_KEY"}}, "prefix"),
               ({"credential": {"ref": KEY}}, "never the key"), ({"credential": {"key": KEY}}, "never the key"),
               ({"credential": None}, "never the key")]
        for change, expected in bad:
            status, out = self.call("POST", f"{AI}/policy", body={"policy": policy(**change), "reason": "x"})
            self.assertEqual(status, 400, (change, out))
            self.assertIn(expected, out["error"]["message"], change)
            self.assertNotIn(KEY, json.dumps(out))  # what was sent where a reference belongs is never echoed
        status, out = self.call("POST", f"{AI}/policy", body={"policy": {**policy(), "api_key": KEY}, "reason": "x"})
        self.assertEqual(status, 400)
        self.assertNotIn(KEY, json.dumps(out))
        self.assertEqual(self.call("POST", f"{AI}/policy", body={"policy": policy()})[0], 400)  # a reason is required
        self.assertEqual(self.call("GET", AI)[1]["pending"], [])

    def test_a_policy_takes_two_people_and_can_always_be_taken_away(self):  # G2, G5
        bot = self.add("pipeline", kind="service")
        for token, expected in (("acme-hana", 403), (bot, 403), ("nw-nadia", 404)):
            self.assertEqual(self.call("GET", AI, token)[0], expected, token)
            self.assertEqual(self.call("POST", f"{AI}/policy", token, {"policy": policy(), "reason": "x"})[0], expected)
        self.assertEqual(self.call("POST", f"{AI}/policy", "acme-maria", {"policy": policy(), "reason": "x"})[0], 403)
        status, out = self.call("POST", f"{AI}/policy", body={"policy": policy(), "reason": "for the evaluation"})
        self.assertEqual((status, out["state"], len(out["pending"])), (201, "none", 1), out)
        pid = out["proposed"]
        self.assertEqual(self.ask()[0], 409)  # proposed is not approved
        status, refused = self.call("POST", f"{AI}/policy/{pid}/approve", body={"reason": "mine"})
        self.assertEqual(status, 403)
        self.assertIn("proposer cannot approve", refused["error"]["message"])
        self.assertEqual(self.call("POST", f"{AI}/policy/{pid}/approve", bot, {"reason": "x"})[0], 403)
        self.assertEqual(self.call("POST", f"{AI}/policy/nope/approve", "acme-maria", {"reason": "x"})[0], 404)
        status, view = self.call("POST", f"{AI}/policy/{pid}/approve", "acme-maria", {"reason": "reviewed"})
        self.assertEqual((status, view["state"], view["transmits_externally"], view["approved_by"]),
                         (200, "authorised", True, "maria@acme"), view)
        self.assertEqual(view["policy"]["credential"]["ref"], "env:ACME_AI_KEY")
        self.assertNotIn(KEY, json.dumps(view))  # the view names where the key lives, never the key
        self.assertNotIn(KEY, json.dumps(self.call("GET", f"{WS}/members")[1]))
        self.assertEqual(self.ask()[0], 200)
        # one person takes it away, at once
        status, off = self.call("POST", f"{AI}/disable", body={"reason": "evaluation over"})
        self.assertEqual((status, off["state"]), (200, "none"))
        self.assertEqual(self.ask()[0], 409)
        self.assertEqual(self.call("POST", f"{AI}/disable", body={"reason": "again"})[0], 409)
        events = [e["event"] for e in self.call("GET", f"{WS}/members")[1]["history"] if e["event"].startswith("ai_")]
        self.assertEqual(events, ["ai_policy_proposed", "ai_policy_approved", "ai_policy_disabled"])
        # a proposal can be withdrawn by one person
        _, again = self.call("POST", f"{AI}/policy", body={"policy": policy(), "reason": "second try"})
        self.assertEqual(self.call("POST", f"{AI}/policy/{again['proposed']}/withdraw", body={"reason": "no"})[0], 200)
        self.assertEqual(self.call("POST", f"{AI}/policy/{again['proposed']}/approve", "acme-maria", {"reason": "x"})[0], 404)


class NoAuthorisationTests(GovernanceBase):
    authorisations: list = []

    def test_an_approved_policy_is_not_permission_to_transmit(self):  # G3
        view = self.approve_policy()
        self.assertEqual((view["state"], view["transmits_externally"], view["owner_authorisation"]["present"]),
                         ("not_authorised", False, False))
        self.assertIn("D7", view["reason"])
        status, out = self.ask()
        self.assertEqual(status, 409, out)
        self.assertEqual(self.double.calls, [])  # nothing left the platform


class AuthorisationCoverageTests(GovernanceBase):
    def test_an_authorisation_covers_exactly_what_it_names(self):  # G3 (pure)
        covered = ai_policy.validate_policy(policy(), "ACME_")[1]
        self.assertEqual(ai_policy.authorisation_for(covered, "acme", [AUTHORISATION])[1], "")
        for change, expected in (({"model": "another-model"}, "names the model"),
                                 ({"data_classes": ["synthetic"]}, "does not cover"),
                                 ({"expires": "2020-01-01"}, "expired"),
                                 ({"max_budget_usd_per_month": 1}, "could spend"),
                                 ({"workspace": "northwind"}, "has not authorised")):
            found, reason = ai_policy.authorisation_for(covered, "acme", [{**AUTHORISATION, **change}])
            self.assertIsNone(found, change)
            self.assertIn(expected, reason)
        daily = ai_policy.validate_policy(policy(budget={"period": "day", "per_period": 2}), "ACME_")[1]
        self.assertIn("could spend 62", ai_policy.authorisation_for(daily, "acme", [AUTHORISATION])[1])
        with self.assertRaises(ValueError):
            ai_policy.validate_authorisations([{**AUTHORISATION, "expires": None}], {"acme": {}})
        with self.assertRaises(ValueError):
            ai_policy.validate_authorisations([{**AUTHORISATION, "decision": " "}], {"acme": {}})
        with self.assertRaises(ValueError):
            ai_policy.validate_authorisations([{**AUTHORISATION, "workspace": "nowhere"}], {"acme": {}})

    def test_a_missing_key_or_an_expired_policy_serves_nothing(self):  # G3
        os.environ.pop("ACME_AI_KEY")
        view = self.approve_policy()
        self.assertEqual(view["state"], "unavailable")
        self.assertEqual(self.ask()[0], 409)
        os.environ["ACME_AI_KEY"] = KEY
        self.call("POST", f"{AI}/disable", body={"reason": "retry"})
        self.assertEqual(self.approve_policy(expires="2020-01-01")["state"], "not_authorised")
        self.assertEqual(self.double.calls, [])


class BudgetTests(GovernanceBase):
    def usage(self):
        return self.call("GET", AI)[1]

    def test_calls_are_reserved_settled_and_reported(self):  # G4
        self.approve_policy()
        status, out = self.ask()
        self.assertEqual(status, 200, out)
        self.assertEqual((out["generator"], out["ai"], [q["id"] for q in out["questions"]]), ("model", True, ["volume"]))
        view = self.usage()
        self.assertEqual((view["usage"]["settled"], view["usage"]["spent_usd"], view["usage"]["reserved_usd"],
                          view["usage"]["input_tokens"], view["usage"]["output_tokens"]), (1, 0.2, 0.0, 1000, 500))
        self.assertEqual(view["remaining_usd"], 4.8)
        novel = next(u for u in view["use_cases"] if u["id"] == "novel")
        self.assertEqual((novel["state"], novel["provider"], novel["model"], novel["language_model"], novel["bounded"]),
                         ("authorised", "double", MODEL, True, True))
        entry = self.pf.ai_ledger.entries("acme")[0]
        self.assertEqual((entry["state"], entry["use_case"], entry["purpose"], entry["attempts"]),
                         ("settled", "novel", "architect.propose", 1))
        self.assertNotIn("berthing", json.dumps(self.pf.ai_ledger.entries("acme")))  # amounts and counts, no content

    def test_the_period_ceiling_holds_and_survives_a_restart(self):  # G4
        self.approve_policy()
        self.assertEqual(self.ask()[0], 200)  # costs 0.20; what is reserved beforehand is the worst case
        reserved = self.pf.ai_ledger.entries("acme")[0]["reserved_usd"]
        self.assertGreater(reserved, 0.2)  # computed from the request's size and limits, before any answer
        self.call("POST", f"{AI}/disable", body={"reason": "a tighter budget"})
        ceiling = round(0.4 + reserved - 0.01, 4)  # room for one more call of 0.20, not for a third
        self.approve_policy(budget={"per_period": ceiling})
        self.assertEqual(self.ask()[0], 200)
        status, out = self.ask()
        self.assertEqual(status, 409, out)
        self.assertEqual(out["error"]["details"]["kind"], "budget_exceeded")
        self.assertIn(f"{ceiling:g} USD", out["error"]["message"])
        self.assertEqual(len(self.double.calls), 2)  # the third request was never sent
        self.start()  # the ledger is durable: a restart does not hand the budget back
        self.assertEqual(self.ask()[0], 409)
        view = self.usage()
        self.assertEqual((view["usage"]["settled"], view["usage"]["refused"] >= 2, view["remaining_usd"]),
                         (2, True, round(ceiling - 0.4, 6)))
        self.assertTrue(view["usage"]["recent_refusals"])

    def test_one_request_cannot_cost_more_than_its_ceiling_or_its_token_limit(self):  # G4
        self.approve_policy(budget={"per_request": 0.01})
        status, out = self.ask()
        self.assertEqual((status, out["error"]["details"]["kind"]), (409, "budget_exceeded"), out)
        self.assertIn("per request", out["error"]["message"])
        self.call("POST", f"{AI}/disable", body={"reason": "next"})
        self.approve_policy(limits={"max_input_tokens": 10})
        status, out = self.ask()
        self.assertEqual((status, out["error"]["details"]["kind"]), (409, "not_allowed"), out)
        self.assertEqual(self.double.calls, [])

    def test_parallel_requests_cannot_overspend_or_exceed_the_concurrency_limit(self):  # G4
        self.approve_policy(budget={"per_period": 40, "per_request": 5})  # within what the owner authorised
        self.double.gate = threading.Event()  # every call waits: all requests are in flight together
        results = []

        def one():
            results.append(self.ask())
        threads = [threading.Thread(target=one) for _ in range(5)]
        for t in threads:
            t.start()
        for _ in range(200):
            if len(results) >= 3:
                break
            threading.Event().wait(0.05)
        self.assertEqual(sorted(r[0] for r in results), [409, 409, 409])  # the limit is 2: three were refused at once
        self.assertTrue(all("in progress" in r[1]["error"]["message"] for r in results))
        self.double.gate.set()
        for t in threads:
            t.join(30)
        self.assertEqual(sorted(r[0] for r in results), [200, 200, 409, 409, 409])
        self.assertEqual(len(self.double.calls), 2)
        self.assertEqual(self.usage()["usage"]["spent_usd"], 0.4)

    def test_failures_retries_and_uncertain_outcomes_are_accounted_as_what_they_are(self):  # G4
        self.approve_policy()
        # a refusal before any answer: nothing was billed, the reservation is released
        self.double.plan = [ProviderError("auth", "the provider refused the credential")]
        self.assertEqual(self.ask()[0], 502)
        # a retry inside one request: one reservation, settled once for what both attempts used
        self.double.plan = [ProviderError("rate_limited", "slow down", retry_after=0.01), None]
        self.assertEqual(self.ask()[0], 200)
        # an outcome nobody knows: the provider may have done the work, so the reservation stays charged
        self.double.plan = [ProviderError("unavailable", "connection reset"), ProviderError("unavailable", "again")]
        self.assertEqual(self.ask()[0], 503)
        states = [(e["state"], e["attempts"], e["outcome"]) for e in self.pf.ai_ledger.entries("acme")]
        self.assertEqual(states, [("released", 1, "auth"), ("settled", 2, "ok"), ("uncertain", 2, "unavailable")])
        view = self.usage()
        self.assertEqual((view["usage"]["spent_usd"], view["usage"]["uncertain"], view["usage"]["released"]), (0.2, 1, 1))
        self.assertGreater(view["usage"]["reserved_usd"], 0)  # the uncertain call still counts against the ceiling

    def test_a_repeated_request_id_is_never_charged_twice(self):  # G4
        self.approve_policy()
        gateway = self.pf.workspaces["acme"].use_cases["novel"].service.architect.gateway
        request = ModelRequest("engine", "architect.propose", "system", "prompt", SCHEMA, data_classes=("synthetic",),
                               request_id="same-id")
        first = gateway.invoke(request)
        again = gateway.invoke(request)  # identical: answered from the first one
        self.assertEqual((again.replayed, again.data), (True, first.data))
        gateway._answers.clear()  # the answer is no longer held (a restart, or many requests later)
        with self.assertRaises(ProviderError) as refused:
            gateway.invoke(request)
        self.assertEqual(refused.exception.kind, "invalid_request")
        self.assertEqual((len(self.double.calls), len(self.pf.ai_ledger.entries("acme"))), (1, 1))

    def test_an_unpriced_model_or_an_unavailable_ledger_sends_nothing(self):  # G4
        self.approve_policy()
        PRICES.pop(MODEL)
        status, out = self.ask()
        self.assertEqual((status, out["error"]["details"]["kind"]), (409, "not_allowed"), out)
        self.assertIn("no price is registered", out["error"]["message"])
        PRICES[MODEL] = (100.0, 200.0)
        with mock.patch.object(self.pf.ai_ledger, "reserve", side_effect=RuntimeError("disk full")):
            status, out = self.ask()
        self.assertEqual((status, out["error"]["details"]["kind"]), (409, "budget_exceeded"), out)
        self.assertIn("ledger is unavailable", out["error"]["message"])
        self.assertEqual(self.double.calls, [])

    def test_only_those_who_configure_may_ask_and_the_other_workspace_spends_nothing(self):  # G5
        self.approve_policy()
        self.assertEqual(self.ask("acme-hana")[0], 404)  # no grant on this use case
        self.assertEqual(self.ask("nw-nadia")[0], 404)
        self.assertEqual(self.call("GET", "/platform/v1/workspaces/northwind/ai", "nw-nadia")[1]["state"], "none")
        self.assertEqual(self.pf.ai_ledger.entries("northwind"), [])
        self.assertEqual(self.call("GET", AI, "nw-nadia")[0], 404)


class SandboxTests(AdminBase):
    def test_the_sandbox_needs_no_policy_and_can_be_bounded_by_one(self):  # G6
        status, made = self.call("POST", f"{WS}/use-cases", body={"id": "desk", "name": "Desk", "template": "blank-solution"})
        self.assertEqual(status, 201, made)
        engine = "/w/acme/u/desk/api/v1"
        brief = "Employees send service requests. A manager must approve the expensive ones, then a team fulfils them."
        self.assertEqual(self.call("POST", f"{engine}/architect/proposals", body={"generator": "model", "brief": brief})[0], 200)
        view = self.call("GET", AI)[1]
        desk = next(u for u in view["use_cases"] if u["id"] == "desk")
        self.assertEqual((view["state"], desk["state"], desk["language_model"], desk["bounded"]), ("none", "sandbox", False, False))
        sandbox = {**policy(provider="sandbox", model="sandbox-architect", credential=None),
                   "limits": {"max_input_tokens": 50000, "max_output_tokens": 2000, "concurrency": 1,
                              "timeout_seconds": 20, "max_attempts": 1}}
        _, out = self.call("POST", f"{AI}/policy", body={"policy": sandbox, "reason": "bound the double"})
        status, view = self.call("POST", f"{AI}/policy/{out['proposed']}/approve", "acme-maria", {"reason": "ok"})
        self.assertEqual((status, view["state"], view["transmits_externally"], view["owner_authorisation"]["present"]),
                         (200, "sandbox", False, True), view)
        self.assertEqual(self.call("POST", f"{engine}/architect/proposals", body={"generator": "model", "brief": brief})[0], 200)
        after = self.call("GET", AI)[1]
        self.assertEqual((after["usage"]["settled"], after["usage"]["spent_usd"]), (1, 0.0))
        self.assertTrue(next(u for u in after["use_cases"] if u["id"] == "desk")["bounded"])


if __name__ == "__main__":
    import unittest

    unittest.main()
