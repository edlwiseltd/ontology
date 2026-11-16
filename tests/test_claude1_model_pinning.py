"""Claude activation, increment 1: a use case names its provider, its exact model and the policy terms.

No provider is contacted: the "real provider" is the counting double of the governance tests.

  M1 the setting is validated: a provider other than the sandbox is named with its model and the terms of the
     policy it is configured under; the sandbox keeps its one-word setting
  M2 a use case is served only when the workspace's approved policy names the same provider, the same exact model
     and the same terms; the model that answered stays on the proposal
  M3 a policy moved to another model (by two people, and authorised) serves this use case nothing: the model of a
     use case changes only with the use case's own configuration, which is what a release fixes
  M4 changed terms (what may be sent) serve nothing either; a changed budget or limit keeps serving
  M5 the release names provider, model and policy terms, says whether the workspace's policy serves it now, and
     holds no key and no key reference; two configurations with different models are different releases
  M6 an answer under a dated name of the model is priced as the model; an answer from another model is refused
     and its reservation stays charged
  M7 a use case declared synthetic sends its briefs as synthetic data; without the declaration a policy that
     allows synthetic data only refuses a typed brief
"""

import json
import unittest

from autology import ai_policy
from autology.ai import ModelGateway, ModelRequest, ProviderError, ProviderReply, WorkspaceAI, same_model
from autology.architecting import build_gateway, check_setting
from autology.reasoners import PRICES
from autology.releases import fingerprint_of
from autology.sandbox_ai import MODEL as SANDBOX_MODEL

from .test_arch2_ai_provider_governance import (AI, ANSWER, AUTHORISATION, KEY, MODEL, TERMS, UC, Double,
                                                GovernanceBase, policy)

OTHER = "double-model-2"


class SettingTests(unittest.TestCase):
    def test_a_real_provider_is_named_with_its_model_and_terms(self):  # M1
        for bad in ({"provider": "double"}, {"provider": "double", "model": MODEL},
                    {"provider": "double", "policy": TERMS}, {"provider": "double", "model": "", "policy": TERMS},
                    {"provider": "double", "model": MODEL, "policy": TERMS, "key": KEY},
                    {"provider": "double", "model": MODEL, "policy": TERMS, "content": "real"},
                    {"provider": "sandbox", "model": MODEL}, {"provider": "sandbox", "policy": TERMS},
                    {"model": MODEL}, "sandbox"):
            with self.assertRaises(ValueError, msg=bad) as caught:
                check_setting(bad)
            self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(check_setting({"provider": "sandbox"}), ("synthetic", "model_design"))
        self.assertEqual(check_setting({"provider": "sandbox", "model": SANDBOX_MODEL}), ("synthetic", "model_design"))
        self.assertEqual(check_setting({"provider": "double", "model": MODEL, "policy": TERMS,
                                        "data_classes": ["synthetic"], "content": "synthetic"}), ("synthetic",))
        # an engine on its own (no platform, so no grant) still cannot name a real provider at all
        with self.assertRaises(ValueError):
            build_gateway({"provider": "double", "model": MODEL, "policy": TERMS}, "engine", None)

    def test_the_terms_are_what_leaves_and_to_whom(self):  # M4 (pure)
        base = ai_policy.validate_policy(policy(), "ACME_")[1]
        same = [policy(budget={"per_period": 1.0}), policy(limits={"concurrency": 1, "timeout_seconds": 5}),
                policy(expires="2099-01-01"), policy(credential={"ref": "env:ACME_OTHER_KEY"}),
                policy(evaluation={"status": "evaluated", "reference": "run 1"})]
        for spec in same:
            self.assertEqual(ai_policy.terms_fingerprint(ai_policy.validate_policy(spec, "ACME_")[1]),
                             ai_policy.terms_fingerprint(base), spec)
        different = [policy(model=OTHER), policy(data_classes=["synthetic"]), policy(provider="other")]
        for spec in different:
            self.assertNotEqual(ai_policy.terms_fingerprint(ai_policy.validate_policy(spec, "ACME_")[1]),
                                ai_policy.terms_fingerprint(base), spec)
        self.assertEqual(ai_policy.describe(base)["terms"], TERMS)
        self.assertTrue(same_model("m-1", "m-1") and same_model("m-1", "m-1-20260101"))
        self.assertFalse(same_model("m-1", "m-10") or same_model("m-1", "m-1-mini") or same_model("m-1", "m-2"))


class PinnedBase(GovernanceBase):
    authorisations = [AUTHORISATION, {**AUTHORISATION, "model": OTHER}]

    def setUp(self):
        PRICES[OTHER] = (100.0, 200.0)
        self.addCleanup(PRICES.pop, OTHER, None)
        super().setUp()

    def novel(self):
        return next(u for u in self.call("GET", AI)[1]["use_cases"] if u["id"] == "novel")

    def replace_policy(self, **changes):
        self.assertEqual(self.call("POST", f"{AI}/disable", body={"reason": "replaced"})[0], 200)
        return self.approve_policy(**changes)


class PinningTests(PinnedBase):
    def test_served_only_under_the_named_model_and_terms(self):  # M2, M3, M4
        self.approve_policy()
        status, proposal = self.ask()
        self.assertEqual(status, 200, proposal)
        self.assertEqual((proposal["provider"], proposal["model"]), ("double", MODEL))  # who answered, kept
        state = self.novel()
        self.assertEqual((state["state"], state["model"], state["policy_terms"]), ("authorised", MODEL, TERMS))

        # two people move the workspace's policy to another model the owner also authorised
        self.replace_policy(model=OTHER)
        self.assertEqual(self.call("GET", AI)[1]["state"], "authorised")  # the policy itself is in order
        state = self.novel()
        self.assertEqual((state["state"], state["wanted"], state["wanted_model"]), ("not_authorised", "double", MODEL))
        self.assertIn(MODEL, state["reason"])
        self.assertIn(OTHER, state["reason"])
        status, out = self.ask()
        self.assertEqual((status, out["error"]["details"]["kind"]), (409, "not_configured"), out)
        self.assertEqual(len(self.double.calls), 1)  # nothing was sent to the other model

        # back to the model, with other terms: fewer data classes may leave
        self.replace_policy(data_classes=["synthetic"])
        state = self.novel()
        self.assertEqual(state["state"], "not_authorised")
        self.assertIn("terms", state["reason"])
        self.assertEqual(self.ask()[0], 409)
        self.assertEqual(len(self.double.calls), 1)

        # the same terms with a smaller budget and tighter limits: served again, no new release needed
        self.replace_policy(budget={"per_period": 4.0}, limits={"concurrency": 1})
        self.assertEqual(self.novel()["state"], "authorised")
        self.assertEqual(self.ask()[0], 200)
        self.assertEqual(len(self.double.calls), 2)

    def test_the_release_names_the_model_and_holds_no_key(self):  # M5
        self.approve_policy()
        status, release = self.call("POST", f"{UC}/releases", body={"note": "with the architect's provider"})
        self.assertEqual(status, 201, release)
        status, detail = self.call("GET", f"{UC}/releases/{release['number']}")
        self.assertEqual(status, 200, detail)
        named = detail["components"]["ai"]
        self.assertEqual((named["provider"], named["model"], named["policy_terms"]), ("double", MODEL, TERMS))
        self.assertEqual(detail["ai_standing"], {"served": True, "reason": ""})
        text = json.dumps(detail)
        for secret in (KEY, "ACME_AI_KEY", "env:"):  # neither the key nor where it lives is part of a release
            self.assertNotIn(secret, text)
        self.assertEqual(detail["snapshot"]["settings"]["ai"], {"provider": "double", "model": MODEL, "policy": TERMS})
        # the same configuration with another model is another configuration: a release fixes the model
        other = json.loads(json.dumps(detail["snapshot"]))
        other["settings"]["ai"]["model"] = OTHER
        self.assertNotEqual(fingerprint_of(other), detail["fingerprint"])

        self.replace_policy(model=OTHER)  # the release is unchanged; what stands behind it is not
        detail = self.call("GET", f"{UC}/releases/{release['number']}")[1]
        self.assertEqual(detail["components"]["ai"]["model"], MODEL)
        self.assertFalse(detail["ai_standing"]["served"])
        self.assertIn(OTHER, detail["ai_standing"]["reason"])
        self.call("POST", f"{AI}/disable", body={"reason": "stop"})
        self.assertFalse(self.call("GET", f"{UC}/releases/{release['number']}")[1]["ai_standing"]["served"])

    def test_a_sandbox_release_says_so_and_needs_no_policy(self):  # M5 (compatibility)
        claims = f"{UC.rsplit('/', 1)[0]}/claims"
        status, release = self.call("POST", f"{claims}/releases", body={"note": "as before"})
        self.assertEqual(status, 201, release)
        detail = self.call("GET", f"{claims}/releases/{release['number']}")[1]
        self.assertNotIn("ai_standing", detail)
        named = detail["components"]["ai"]  # a configuration that names the sandbox, or none at all
        self.assertTrue(named is None or named["provider"] == "sandbox", named)


class SyntheticTests(PinnedBase):
    setting = {"provider": "double", "model": MODEL, "content": "synthetic",
               "policy": ai_policy.terms_fingerprint(policy(data_classes=["synthetic"]))}

    def test_a_declared_synthetic_use_case_sends_synthetic_data(self):  # M7
        self.approve_policy(data_classes=["synthetic"])
        state = self.novel()
        self.assertEqual((state["state"], state["content"], state["data_classes"]), ("authorised", "synthetic", ["synthetic"]))
        self.assertEqual(self.ask()[0], 200)
        self.assertEqual(len(self.double.calls), 1)


class UndeclaredTests(PinnedBase):
    setting = {"provider": "double", "model": MODEL,
               "policy": ai_policy.terms_fingerprint(policy(data_classes=["synthetic"]))}

    def test_without_the_declaration_a_typed_brief_is_a_model_design(self):  # M7
        self.approve_policy(data_classes=["synthetic"])
        status, out = self.ask()
        self.assertEqual((status, out["error"]["details"]["kind"]), (409, "not_allowed"), out)
        self.assertEqual(self.double.calls, [])


class ServedModelTests(unittest.TestCase):
    """The gateway alone, with a budget: who answered decides whether the answer is used, never what it cost."""

    def setUp(self):
        import tempfile

        PRICES[MODEL] = (100.0, 200.0)
        self.addCleanup(PRICES.pop, MODEL, None)
        self.double = Double()
        self.policy = ai_policy.validate_policy(policy(), "ACME_")[1]
        self.ledger = ai_policy.SpendLedger(f"{tempfile.mkdtemp()}/ledger.db")
        self.addCleanup(self.ledger.close)
        budget = ai_policy.Budget(self.ledger, "acme", "novel", self.policy)
        self.gateway = ModelGateway({"double": self.double}, {"acme": WorkspaceAI("double", MODEL, ("synthetic",), 1)},
                                    budget=budget, sink=lambda event: None)

    def request(self):
        return ModelRequest("acme", "architect.propose", "s", "p", {"type": "object"}, None, ("synthetic",))

    def test_a_dated_name_is_priced_and_another_model_is_refused(self):  # M6
        self.double.invoke = lambda call: ProviderReply(json.dumps(ANSWER), "complete",
                                                        {"input_tokens": 1000, "output_tokens": 500}, f"{MODEL}-20261101")
        response = self.gateway.invoke(self.request())
        self.assertEqual((response.model, response.unpriced_tokens), (f"{MODEL}-20261101", 0))
        self.assertAlmostEqual(response.cost_usd, 0.2)  # 1000 in + 500 out at the registered price of the model
        entry = self.ledger.entries("acme")[0]
        self.assertEqual((entry["state"], round(entry["actual_usd"], 4)), ("settled", 0.2))

        self.double.invoke = lambda call: ProviderReply(json.dumps(ANSWER), "complete",
                                                        {"input_tokens": 1000, "output_tokens": 500}, "another-model")
        with self.assertRaises(ProviderError) as caught:
            self.gateway.invoke(self.request())
        self.assertEqual(caught.exception.kind, "invalid_response")
        self.assertIn("another-model", str(caught.exception))
        states = sorted(e["state"] for e in self.ledger.entries("acme"))
        self.assertEqual(states, ["settled", "uncertain"])  # what the other model cost is unknown: it stays charged
        usage = self.ledger.usage("acme", "month")
        self.assertGreater(usage["reserved_usd"], 0)


if __name__ == "__main__":
    unittest.main()
