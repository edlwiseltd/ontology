"""Stabilisation B: answers outside the contract (GAP-082). The rule is unchanged: such an answer is refused whole.

What changed is what is known about a refusal, and what the model is told beforehand:

S1  every violation is classified: a stray note on one element is told from a section, or a property named like a
    permission, a release, a tool or an endpoint, that the contract has no place for
S2  the refusal is still whole, still paid for, and now says why; the answer is held for the caller, not applied
S3  through the API: no proposal is stored, the error names the classes of violations and never the answer
S4  the evaluation records why a case failed and keeps the refused answer as evidence; the zeros stay zeros
S5  the reservation covers the instructions that spell the allowed keys out
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from autology import ai_policy, architect_eval
from autology.ai import (PROMPTED, Capabilities, ModelGateway, ModelRequest, ProviderError, ProviderReply, WorkspaceAI,
                         allowed_keys, violation_classes)
from autology.architect import SCHEMA
from autology.schema import errors as schema_errors

from .test_arch2_ai_provider_governance import ANSWER, ENGINE, GovernanceBase, policy
from .test_stab1_spending_ledger import request

GOOD = {k: [] for k in SCHEMA["required"]}
RELATIONSHIP = {"from": "Flight", "to": "Gate", "type": "uses", "cardinality": "many_to_one", "rationale": "r",
                "sources": [], "confidence": 0.5}
RULE = {"id": "r1", "type": "prohibition", "description": "d", "action": "a", "rationale": "r", "sources": [],
        "confidence": 0.5}


class Replies:
    name = "replies"

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), 0

    def capabilities(self):
        return Capabilities("anthropic-messages", True, False, True, False, True, "a test double")

    def invoke(self, call):
        self.calls += 1
        return ProviderReply(self.texts.pop(0), "complete", {"input_tokens": 100, "output_tokens": 50}, call.model)


class ClassificationTests(unittest.TestCase):
    def test_the_two_answers_lost_on_17_november_were_one_stray_property_each(self):  # S1
        """`$.relationships[2]: unexpected 'name_hint_removed'` and `$.rules[1]: unexpected
        'name_placeholder_removed'` (run 2 of the first real evaluation): rebuilt here from the recorded messages."""
        first = {**GOOD, "relationships": [RELATIONSHIP, RELATIONSHIP, {**RELATIONSHIP, "name_hint_removed": True}]}
        second = {**GOOD, "rules": [RULE, {**RULE, "name_placeholder_removed": ""}]}
        for answer, where, name in ((first, "$.relationships[2]", "name_hint_removed"),
                                    (second, "$.rules[1]", "name_placeholder_removed")):
            problems = schema_errors(answer, SCHEMA)
            self.assertEqual(problems, [f"{where}: unexpected {name!r}"])
            self.assertEqual(violation_classes(problems), {"stray_property": 1})

    def test_what_the_contract_has_no_place_for_is_told_apart(self):  # S1
        cases = (
            ({**GOOD, "grants": ["admin"]}, {"sensitive_property": 1}),
            ({**GOOD, "notes": "x"}, {"unknown_section": 1}),
            ({**GOOD, "release": {"approve": True}}, {"sensitive_property": 1}),
            ({**GOOD, "rules": [{**RULE, "allow_self_review": True}]}, {"sensitive_property": 1}),
            ({**GOOD, "actions": [{"name": "a", "description": "d", "capability": "c", "requires": [], "effects": [],
                                   "side_effect": "none", "rationale": "r", "sources": [], "confidence": 1,
                                   "tool_endpoint": "https://example.invalid"}]}, {"sensitive_property": 1}),
            ({**GOOD, "roles": [{"name": "r", "description": "d", "permissions": ["admin"]}]}, {"sensitive_property": 1}),
            ({k: v for k, v in GOOD.items() if k != "unknowns"}, {"missing": 1}),
            ({**GOOD, "entities": "none"}, {"wrong_type": 1}),
            ({**GOOD, "rules": [{**RULE, "type": "grant_everything"}]}, {"not_allowed_value": 1}),
            ({**GOOD, "rules": [{**RULE, "comment": "x", "todo": "y"}], "extra": 1},
             {"stray_property": 2, "unknown_section": 1}),
        )
        for answer, expected in cases:
            self.assertEqual(violation_classes(schema_errors(answer, SCHEMA)), expected, answer)
        self.assertEqual(violation_classes([]), {})
        self.assertEqual(violation_classes(["$: something nobody anticipated"]), {"other": 1})

    def test_the_allowed_keys_are_the_schemas_own(self):  # S1
        lines = allowed_keys(SCHEMA)
        self.assertEqual(lines[0], "the answer: " + ", ".join(SCHEMA["properties"]))
        by = {line.split(":")[0]: [k.strip() for k in line.split(":", 1)[1].split(",")] for line in lines}
        for section in ("entities", "relationships", "actions", "rules", "goals", "case_templates", "questions"):
            self.assertEqual(by[f"{section}[]"], list(SCHEMA["properties"][section]["items"]["properties"]))
        self.assertEqual(by["entities[].attributes[]"], ["name", "type"])
        self.assertEqual(by["understanding"], ["summary", "outcome", "actors", "out_of_scope"])
        for forbidden in ("grants", "permissions", "tools", "release", "settings", "allow_self_review"):
            self.assertNotIn(forbidden, " ".join(lines))
        self.assertEqual(allowed_keys({"type": "string"}), [])


class GatewayTests(unittest.TestCase):
    def ask(self, *texts):
        provider = Replies(*texts)
        gateway = ModelGateway({"replies": provider}, {"acme": WorkspaceAI("replies", "m", ("synthetic",))})
        req = ModelRequest("acme", "architect.propose", "system", "brief", SCHEMA, data_classes=("synthetic",))
        return gateway, provider, req

    def test_a_stray_property_still_refuses_the_whole_answer_and_says_why(self):  # S2
        stray = json.dumps({**GOOD, "relationships": [{**RELATIONSHIP, "name_hint_removed": True}]})
        gateway, provider, req = self.ask(stray)
        with self.assertRaises(ProviderError) as refused:
            gateway.invoke(req)
        exc = refused.exception
        self.assertEqual((exc.kind, exc.retryable, provider.calls), ("invalid_response", False, 1))  # never repaired
        self.assertEqual(exc.violations, ["$.relationships[0]: unexpected 'name_hint_removed'"])
        self.assertEqual(exc.violation_classes, {"stray_property": 1})
        self.assertIn("[1 stray_property]", str(exc))
        self.assertEqual(exc.rejected_text, stray)  # held for the caller that asked; nothing else keeps it
        self.assertEqual(exc.usage, {"input_tokens": 100, "output_tokens": 50})  # it was answered, so it is paid for
        self.assertNotIn("name_hint_removed", json.dumps(gateway.usage("acme")))

    def test_many_violations_are_all_counted_and_a_good_answer_has_none(self):  # S2
        bad = {**GOOD, "grants": ["admin"], "rules": [{**RULE, "note": 1}, {**RULE, "note": 2}, {**RULE, "x": 3}],
               "entities": 5}
        gateway, provider, req = self.ask(json.dumps(bad), json.dumps(GOOD))
        with self.assertRaises(ProviderError) as refused:
            gateway.invoke(req)
        self.assertEqual(refused.exception.violation_classes,
                         {"sensitive_property": 1, "stray_property": 3, "wrong_type": 1})
        self.assertEqual(len(refused.exception.violations), 5)
        self.assertIn("(+2 more)", str(refused.exception))
        again = ModelRequest("acme", "architect.propose", "system", "brief", SCHEMA, data_classes=("synthetic",))
        self.assertEqual(gateway.invoke(again).data, GOOD)
        for other in ("not json", "[]"):
            g, _, r = self.ask(other)
            with self.assertRaises(ProviderError) as plain:
                g.invoke(r)
            self.assertEqual((plain.exception.violations, plain.exception.rejected_text), ([], None))

    def test_the_reservation_covers_the_instructions_that_spell_the_keys_out(self):  # S5
        req = request("r1")
        pol = policy()
        tokens, _ = ai_policy.estimate(req, pol)
        sent = (len(req.system) + len(req.text()) + len(json.dumps(SCHEMA)) + len(PROMPTED)
                + len("\n".join(allowed_keys(SCHEMA))))
        self.assertGreaterEqual(tokens * ai_policy.CHARS_PER_TOKEN, sent)


class ApiTests(GovernanceBase):
    def test_a_refused_answer_is_paid_for_stored_nowhere_and_explained(self):  # S3
        self.approve_policy()
        original = self.double.invoke
        stray = copy.deepcopy(ANSWER)
        stray.setdefault("questions", [{"id": "q", "question": "?", "why": "w"}])
        stray["questions"] = [{**stray["questions"][0], "name_hint_removed": True}]

        def invoke(call):
            reply = original(call)
            return ProviderReply(json.dumps(stray), reply.stop, reply.usage, reply.model)

        self.double.invoke = invoke
        status, out = self.ask()
        self.assertEqual(status, 502, out)
        details = out["error"]["details"]
        self.assertEqual((details["kind"], details["retryable"], details["violations"]),
                         ("invalid_response", False, {"stray_property": 1}))
        self.assertIn("unexpected 'name_hint_removed'", out["error"]["message"])
        self.assertEqual(self.call("GET", f"{ENGINE}/architect/proposals")[1]["items"], [])
        entry = self.pf.ai_ledger.entries("acme")[0]
        self.assertEqual((entry["state"], entry["outcome"], entry["actual_usd"] > 0),
                         ("settled", "invalid_response", True))
        self.double.invoke = original
        self.assertEqual(self.ask()[0], 200)  # the next answer, inside the contract, is a proposal as before


class EvaluationTests(unittest.TestCase):
    def test_a_failed_case_says_why_and_its_refused_answer_is_kept(self):  # S4
        folder = Path(tempfile.mkdtemp()) / "kept"
        refused = ProviderError("invalid_response", "the answer does not match the schema that was asked for: "
                                                    "$.rules[1]: unexpected 'name_placeholder_removed'")
        refused.violations = ["$.rules[1]: unexpected 'name_placeholder_removed'"]
        refused.violation_classes = {"stray_property": 1}
        refused.rejected_text = '{"rules": [{}, {"name_placeholder_removed": ""}]}'
        seen = {}

        def ask(case):
            n = seen[case["id"]] = seen.get(case["id"], 0) + 1
            if case["id"] == "global-logistics" and n == 2:
                raise refused  # the second answer of the case, as on 17 November
            if case["id"] == "airline-disruption":
                raise ProviderError("timeout", "no answer")
            return architect_eval.reference_proposal(case)

        result = architect_eval.evaluate(architect_eval.keeping(ask, folder))
        self.assertEqual(result["failed_cases"], ["airline-disruption", "global-logistics"])
        self.assertEqual(result["failures"], [
            {"case": "airline-disruption", "kind": "timeout", "violations": {}, "answers_before_it": 0},
            {"case": "global-logistics", "kind": "invalid_response", "violations": {"stray_property": 1},
             "answers_before_it": 1}])
        rows = {r["case"]: r for r in result["cases"]}
        # the rule set before any model was evaluated is untouched: a case whose request fails scores zero
        self.assertEqual(set(rows["global-logistics"]["scores"].values()), {0.0})
        self.assertFalse(result["all_thresholds_met"])
        kept = sorted(p.name for p in folder.iterdir())
        self.assertIn("global-logistics-1.json", kept)
        self.assertIn("global-logistics-2.refused.json", kept)
        self.assertNotIn("global-logistics-2.json", kept)
        self.assertFalse(any(name.startswith("airline-disruption") for name in kept))  # nothing was received
        evidence = json.loads((folder / "global-logistics-2.refused.json").read_text())
        self.assertEqual((evidence["classes"], evidence["answer_as_received"]),
                         ({"stray_property": 1}, refused.rejected_text))
        self.assertIn("unexpected 'name_placeholder_removed'", evidence["refused"])


if __name__ == "__main__":
    unittest.main()
