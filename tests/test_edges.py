"""Edge cases: validation errors, version diffs, lint findings, expression/graph/tool/reasoner corners."""

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from autology import (AutoApprover, ConsoleApprover, DecisionContext, ExpressionError, Ontology, OntologyError,
                      ToolRegistry, WorkAgent, WorldState, compile_expression)
from autology.agent import ReviewRequest
from autology.graph import KnowledgeGraph
from autology.lint import lint, worst
from autology.reasoners import FunctionChatModel, LLMReasoner, PlanFollowingReasoner, RoutingReasoner
from autology.versioning import (OntologyRegistry, VersionError, actual_bump, check_release, diff, parse_version,
                                 required_bump)

from .helpers import ONTOLOGY_PATH, build_registry, retail_case

BASE = {
    "name": "mini", "version": "1.0.0", "description": "tiny test ontology",
    "entities": {
        "A": {"states": ["s", "t"], "attributes": {"x": "number", "secret": {"type": "string", "sensitivity": "pii"},
                                                     "terms": {"type": "string", "sensitivity": "restricted"}}},
        "B": {"states": ["u", "v", "w"], "attributes": {"y": "integer"}},
    },
    "relationships": [{"from": "A", "to": "B", "type": "r"}],
    "actions": {
        "go": {"description": "move A", "capability": "cap.go", "requires": "A.status == 's'",
               "writes": ["A.terms"], "outcomes": {"ok": {"effects": {"A": {"status": "t"}}},
                                                    "meh": {"effects": {"B": {"status": "v"}}}}},
    },
    "goals": {"g": {"description": "reach t", "target": "A.status == 't'"}},
    "rules": [{"id": "R1", "type": "data_access", "field": "A.secret", "roles": ["x"], "description": "d"},
              {"id": "R2", "type": "write_access", "field": "A.terms", "roles": ["x"], "description": "d"}],
    "competency_questions": [{"id": "Q1", "question": "which?", "find": "A", "follow": ["r"]}],
}


def doc(mutate=None):
    d = copy.deepcopy(BASE)
    if mutate:
        mutate(d)
    return d


def onto(mutate=None):
    return Ontology.from_dict(doc(mutate))


class ValidationEdgeTests(unittest.TestCase):
    def test_base_is_valid(self):
        o = onto()
        self.assertEqual(o.ref, "mini@1.0.0")
        with self.assertRaises(AttributeError):
            del o.name

    def test_invalid_documents(self):
        A = lambda d: d["entities"]["A"]  # noqa: E731
        go = lambda d: d["actions"]["go"]  # noqa: E731
        cases = {
            "no states": lambda d: A(d).update(states=[]),
            "bad initial": lambda d: A(d).update(initial="zz"),
            "bad external": lambda d: A(d).update(external_states=["zz"]),
            "relationship end": lambda d: d["relationships"].append({"from": "A", "to": "Q", "type": "q"}),
            "no outcomes": lambda d: go(d).update(outcomes={}),
            "attempts": lambda d: go(d).update(on_failure={"max_attempts": 0}),
            "fallback_after": lambda d: go(d).update(on_failure={"max_attempts": 2, "fallback_after": 2}),
            "field form": lambda d: go(d).update(reads=["Ax"]),
            "reset_by": lambda d: d["rules"].append({"id": "M", "type": "mandatory_step", "step": "go",
                                                     "before": "go", "reset_by": ["nope"]}),
            "review action": lambda d: d["rules"].append({"id": "H", "type": "human_review", "action": "nope",
                                                          "reviewer": "x"}),
            "reviewer": lambda d: d["rules"].append({"id": "H", "type": "human_review", "action": "go"}),
            "roles": lambda d: d["rules"].append({"id": "C", "type": "action_access", "action": "go", "roles": []}),
            "dup question": lambda d: d["competency_questions"].append(dict(d["competency_questions"][0])),
            "question entity": lambda d: d["competency_questions"].append({"id": "Q2", "find": "Nope"}),
            "aggregate fn": lambda d: d["competency_questions"].append(
                {"id": "Q2", "find": "B", "aggregate": {"median": "B.y"}}),
            "aggregate field": lambda d: d["competency_questions"].append(
                {"id": "Q2", "find": "B", "aggregate": {"sum": "A.x"}}),
            "settings": lambda d: d.update(settings={"max_violations": 0}),
            "malformed": lambda d: d["actions"].update(bad={"outcomes": {"x": {"effects": "oops"}}}),
            "missing goal target": lambda d: d["goals"].update(h={}),
        }
        for label, mutate in cases.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                onto(mutate)

    def test_module_rule_conflicts(self):
        from autology.ontology import merge_documents

        a = {"name": "a", "rules": [{"id": "R", "type": "prohibition", "action": "go"}]}
        b = {"name": "b", "rules": [{"id": "R", "type": "prohibition", "action": "stop"}]}
        with self.assertRaisesRegex(OntologyError, "redefines rule 'R'"):
            merge_documents({"name": "root"}, [a, b])
        same = merge_documents({"name": "root"}, [a, copy.deepcopy(a)])
        self.assertEqual(len(same["rules"]), 1)


class VersioningEdgeTests(unittest.TestCase):
    def test_parse(self):
        for bad in ("1.0", "1.x.0", "v1"):
            with self.subTest(bad), self.assertRaises(VersionError):
                parse_version(bad)
        self.assertEqual(actual_bump("1.2.3", "1.2.3"), None)
        self.assertEqual(actual_bump("1.2.3", "1.2.4"), "patch")

    def test_every_change_kind(self):
        base = onto()
        A = lambda d: d["entities"]["A"]  # noqa: E731
        go = lambda d: d["actions"]["go"]  # noqa: E731
        expected = {
            "attribute.type_changed": ("major", lambda d: A(d)["attributes"].update(x="string")),
            "attribute.sensitivity_changed": ("minor", lambda d: A(d)["attributes"].update(
                x={"type": "number", "sensitivity": "confidential"})),
            "entity.initial_state_changed": ("major", lambda d: A(d).update(initial="t")),
            "state.removed": ("major", lambda d: d["entities"]["B"].update(states=["u", "v"])),
            "relationship.added": ("minor", lambda d: d["relationships"].append({"from": "B", "to": "A", "type": "q"})),
            "outcome.removed": ("major", lambda d: go(d)["outcomes"].pop("meh")),
            "action.capability_changed": ("major", lambda d: go(d).update(capability="cap.other")),
            "action.preconditions_changed": ("minor", lambda d: go(d).update(requires=["A.x > 1"])),
            "action.expected_outcome_changed": ("minor", lambda d: go(d).update(outcomes=dict(
                reversed(list(go(d)["outcomes"].items()))))),
            "action.contract_changed": ("minor", lambda d: go(d).update(cost=5)),
            "goal.target_changed": ("major", lambda d: d["goals"]["g"].update(target="B.status == 'v'")),
            "rule.changed": ("minor", lambda d: d["rules"][0].update(roles=["y"])),
            "rule.description_changed": ("patch", lambda d: d["rules"][0].update(description="new words")),
            "competency_question.added": ("minor", lambda d: d["competency_questions"].append(
                {"id": "Q2", "find": "B"})),
            "ontology.description_changed": ("patch", lambda d: d.update(description="other")),
        }
        for kind, (level, mutate) in expected.items():
            with self.subTest(kind):
                changes = diff(base, onto(mutate))
                self.assertIn((level, kind), {(c.level, c.kind) for c in changes})
                self.assertTrue(str(changes[0]))

    def test_release_rules(self):
        base = onto()
        same_older = onto(lambda d: d.update(version="0.9.0"))
        with self.assertRaises(VersionError):
            check_release(base, same_older)
        self.assertEqual(check_release(base, onto()), [])
        self.assertIsNone(required_bump([]))
        with self.assertRaises(VersionError):  # changes but version unchanged
            check_release(base, onto(lambda d: d["entities"]["A"]["attributes"].update(z="string")))

    def test_registry_edges(self):
        reg = OntologyRegistry()
        with self.assertRaises(KeyError):
            reg.get("mini")
        self.assertIsNone(reg.latest("mini"))
        reg.publish(onto(lambda d: d.update(version="1.1.0")))
        with self.assertRaises(VersionError):
            reg.publish(onto())  # older than latest
        self.assertEqual(reg.get("mini").version, "1.1.0")
        with self.assertRaises(VersionError):
            reg.publish(onto(lambda d: d.update(version="banana")))


class LintEdgeTests(unittest.TestCase):
    def test_findings(self):
        def mutate(d):
            d["rules"] = [d["rules"][0]]  # restricted A.terms writable without write_access
            d["entities"]["C"] = {"states": ["c"]}  # unrelated entity
            d["entities"]["B"]["attributes"]["revenue"] = "number"
            d["rules"].append({"id": "P", "type": "prohibition", "action": "go", "when": "B.revenue < 1000000"})
            d["goals"]["h"] = {"target": "B.y == 1"}  # nothing changes B.y
            d["actions"]["go"]["tools"] = ["ghost"]
            d.pop("competency_questions")

        tools = ToolRegistry()
        tools.register("real", "cap.go", lambda c: None)
        findings = lint(onto(mutate), tools)
        codes = {f.code for f in findings}
        self.assertTrue({"SEC002", "BIAS002", "STR002", "STR003", "TOOL002", "CQ001"} <= codes, codes)
        self.assertEqual(worst(findings), "warning")
        self.assertIsNone(worst([]))
        self.assertTrue(str(findings[0]).startswith(findings[0].level.upper()))


class SmallPartsTests(unittest.TestCase):
    def test_expressions(self):
        for bad in ("A.x is None", "A.x == {1: 2}", "A.x in [B.y]", "A.x ==", "A.x == b'x'"):
            with self.subTest(bad), self.assertRaises(ExpressionError):
                compile_expression(bad)
        expr = compile_expression("A.x > 1")
        self.assertEqual(repr(expr), "Expression('A.x > 1')")
        self.assertEqual(str(expr), "A.x > 1")
        self.assertTrue(compile_expression("A.x < 2 < 3").evaluate(lambda e, a: 1))
        self.assertFalse(compile_expression("A.x < 2 < 1").evaluate(lambda e, a: 1))

    def test_state(self):
        o = onto()
        state = WorldState.initial(o, {"A": {"status": None, "x": 1}})
        self.assertEqual(state.get("A", "status"), "s")
        self.assertIn("A=s", repr(state))

    def test_graph(self):
        o = onto()
        g = KnowledgeGraph(o)
        g.add("B", "b1", y=2)
        g.add("B", "b2", y=4)
        with self.assertRaises(OntologyError):
            g.add("B", "b1")
        self.assertEqual(g.get("b1").get("y"), 2)
        self.assertEqual(g.query("B", aggregate=("avg", "B.y")).value, 3)
        self.assertEqual(g.query("B", aggregate=("max", "B.y")).value, 4)
        self.assertEqual(g.query("B", where="B.y > 9", aggregate=("min", "B.y")).value, None)
        with self.assertRaises(OntologyError):
            g.ask("Q-missing")

    def test_tool_select(self):
        reg = build_registry()
        state = WorldState.initial(Ontology.load(ONTOLOGY_PATH), retail_case())
        self.assertEqual(reg.select("kyc.verify", state).name, "standard_kyc")
        with self.assertRaisesRegex(LookupError, "among allowed tools"):
            reg.select("kyc.verify", state, allowed=["nope"])
        with self.assertRaises(LookupError):
            reg.select("teleport", state)

    def test_reasoner_corners(self):
        o = Ontology.load(ONTOLOGY_PATH)
        cands = [o.actions["verify_identity"], o.actions["enhanced_due_diligence"]]
        ctx = DecisionContext(o, o.goals["onboard_customer"], ["verify_identity"], cands, {"Customer": {"n": 1}})
        reasoner = LLMReasoner(FunctionChatModel(lambda s, p, sc: {"action": "verify_identity", "rationale": "r"}),
                               cache_size=1)
        reasoner.propose(ctx)
        ctx2 = DecisionContext(o, o.goals["onboard_customer"], ["verify_identity"], cands, {"Customer": {"n": 2}})
        reasoner.propose(ctx2)
        self.assertEqual(len(reasoner._cache), 1)  # LRU evicted the first entry
        router = RoutingReasoner(simple=PlanFollowingReasoner(), simple_max_candidates=2)
        router.propose(ctx)
        self.assertEqual(router.routes["simple"], 1)
        from autology import ClaudeReasoner

        marker = SimpleNamespace(beta=None)
        self.assertIs(ClaudeReasoner(client=marker).client, marker)

    def test_console_approver_and_human_touches(self):
        req = ReviewRequest("c", "sign_contract", "sign it", ("cfo",), ["big"], {}, ["a->b"], {"Contract.value": 5},
                            "", ["R-FIN-001"])
        with mock.patch("builtins.input", return_value="y"), redirect_stdout(io.StringIO()) as out:
            decision = ConsoleApprover().review(req)
        self.assertTrue(decision.approved)
        self.assertIn("needs cfo approval", out.getvalue())
        o = Ontology.load(ONTOLOGY_PATH)
        res = WorkAgent("a", o, build_registry(), roles=["sales", "kyc"], approver=AutoApprover()).run(
            "onboard_customer", retail_case(Contract={"value": 2_000_000}))
        self.assertEqual(res.human_touches, 1)
        with self.assertRaises(OntologyError):
            WorkAgent("a", o, build_registry()).run("no_such_goal", retail_case())
        with self.assertRaises(ValueError):
            WorkAgent("a", o, build_registry(), on_ontology_update="ignore")


if __name__ == "__main__":
    unittest.main()
