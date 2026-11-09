import unittest

from autology import (AuditLog, ExpressionError, GovernanceLayer, IntegrityError, Ontology, OntologyError, Principal,
                      Verdict, WorldState, compile_expression)

from .helpers import ONTOLOGY_PATH, load_doc, retail_case


class ExpressionTests(unittest.TestCase):
    def resolve(self, entity, attr):
        return {("C", "x"): 5, ("C", "s"): "Financial Services", ("C", "n"): None}.get((entity, attr))

    def test_evaluates_comparisons_and_booleans(self):
        cases = {
            "C.x == 5": True,
            "C.x > 3 and C.s == 'Financial Services'": True,
            "C.x < 3 or not C.s == 'Retail'": True,
            "C.s in ['Retail', 'Financial Services']": True,
            "C.s not in ('Retail',)": True,
            "C.n > 3": False,  # None comparisons simply do not hold
            "C.n == None": True,
        }
        for src, expected in cases.items():
            with self.subTest(src=src):
                self.assertEqual(compile_expression(src).evaluate(self.resolve), expected)

    def test_reports_references(self):
        self.assertEqual(compile_expression("A.b == 1 and C.d").references, {("A", "b"), ("C", "d")})

    def test_rejects_code_execution(self):
        for src in ("__import__('os').system('echo hi')", "C.x.__class__", "C._secret == 1",
                    "len(C.x) > 1", "C.x + 1 == 2", "lambda: 1", "[c for c in C.x]", ""):
            with self.subTest(src=src), self.assertRaises(ExpressionError):
                compile_expression(src)


class OntologyTests(unittest.TestCase):
    def test_loads_example(self):
        onto = Ontology.load(ONTOLOGY_PATH)
        self.assertIn("Customer", onto.entities)
        self.assertEqual(onto.actions["legal_review"].expected_outcome.name, "approved")
        self.assertEqual(len(onto.fingerprint), 64)

    def test_fingerprint_is_content_addressed(self):
        doc = load_doc()
        a, b = Ontology.from_dict(doc), Ontology.from_dict(load_doc())
        self.assertEqual(a.fingerprint, b.fingerprint)
        doc["rules"] = doc["rules"][1:]
        self.assertNotEqual(Ontology.from_dict(doc).fingerprint, a.fingerprint)

    def test_is_immutable(self):
        onto = Ontology.load(ONTOLOGY_PATH)
        with self.assertRaises(AttributeError):
            onto.rules = ()
        with self.assertRaises(TypeError):
            onto.actions["sign_contract"] = None  # type: ignore[index]
        with self.assertRaises(TypeError):
            onto.actions["sign_contract"].outcomes[0].effects["Contract"]["status"] = "approved"  # type: ignore

    def test_validation_errors(self):
        def broken(mutate):
            doc = load_doc()
            mutate(doc)
            return doc

        bad_docs = {
            "unknown entity in precondition": broken(
                lambda d: d["actions"]["sign_contract"]["requires"].append("Invoice.status == 'x'")),
            "unknown attribute": broken(
                lambda d: d["actions"]["sign_contract"]["requires"].append("Contract.colour == 'red'")),
            "invalid state in effect": broken(
                lambda d: d["actions"]["sign_contract"]["effects"]["Contract"].update(status="teleported")),
            "tool may not write status": broken(
                lambda d: d["actions"]["sign_contract"].update(writes=["Contract.status"])),
            "rule names unknown action": broken(lambda d: d["rules"][0].update(before="fly_to_moon")),
            "unknown rule kind": broken(lambda d: d["rules"][0].update(type="suggestion")),
            "duplicate rule id": broken(lambda d: d["rules"].append(dict(d["rules"][0]))),
            "unknown outcome": broken(lambda d: d["rules"][0].update(outcome="maybe")),
            "unsafe expression": broken(lambda d: d["rules"][1].update(when="__import__('os')")),
        }
        for label, doc in bad_docs.items():
            with self.subTest(label), self.assertRaises(OntologyError):
                Ontology.from_dict(doc)

    def test_case_data_is_checked_against_ontology(self):
        onto = Ontology.load(ONTOLOGY_PATH)
        with self.assertRaises(OntologyError):
            WorldState.initial(onto, {"Customer": {"shoe_size": 42}})
        with self.assertRaises(OntologyError):
            WorldState.initial(onto, {"Spaceship": {}})


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.onto = Ontology.load(ONTOLOGY_PATH)
        self.gov = GovernanceLayer(self.onto)
        self.agent = Principal("agent", ["kyc"])

    def state(self, **statuses):
        state = WorldState.initial(self.onto, retail_case())
        for entity, status in statuses.items():
            state.set(entity, "status", status)
        return state

    def test_cannot_sign_without_legal_approval(self):
        state = self.state(Customer="verified", Contract="approved")  # status forged, no review on record
        decision = self.gov.evaluate("sign_contract", state, self.agent)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertIn("R-LEGAL-001", decision.rule_ids)
        state.steps["legal_review"] = "approved"
        self.assertEqual(self.gov.evaluate("sign_contract", state, self.agent).verdict, Verdict.ALLOW)

    def test_revision_resets_prior_legal_review(self):
        state = self.state(Contract="rejected")
        state.steps["legal_review"] = "approved"
        self.gov.record_completion(self.onto.actions["revise_contract"], "resubmitted", state)
        self.assertNotIn("legal_review", state.steps)

    def test_unknown_action_and_unmet_precondition_denied(self):
        state = self.state()
        self.assertEqual(self.gov.evaluate("wire_money", state, self.agent).verdict, Verdict.DENY)
        decision = self.gov.evaluate("activate_customer", state, self.agent)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertTrue(any("precondition" in r for r in decision.reasons))

    def test_human_review_is_context_dependent(self):
        state = self.state(Customer="verified", Contract="approved")
        state.steps["legal_review"] = "approved"
        self.assertEqual(self.gov.evaluate("sign_contract", state, self.agent).verdict, Verdict.ALLOW)
        state.set("Contract", "value", 1_000_000)
        decision = self.gov.evaluate("sign_contract", state, self.agent)
        self.assertEqual(decision.verdict, Verdict.REVIEW)
        self.assertEqual(decision.reviewers, ("finance_director",))

    def test_data_access_and_redaction(self):
        state = self.state()
        sales = Principal("sales-bot", ["sales"])
        self.assertEqual(self.gov.evaluate("verify_identity", state, sales).verdict, Verdict.DENY)
        self.assertEqual(self.gov.redacted_view(state, sales)["Customer"]["tax_id"], "***redacted***")
        self.assertEqual(self.gov.redacted_view(state, self.agent)["Customer"]["tax_id"], "GB-1234")

    def test_prohibition(self):
        state = self.state(Customer="verified", Contract="approved")
        state.steps["legal_review"] = "approved"
        state.set("Customer", "sanctions_hit", True)
        decision = self.gov.evaluate("sign_contract", state, self.agent)
        self.assertEqual(decision.verdict, Verdict.DENY)
        self.assertIn("R-SANC-001", decision.rule_ids)

    def test_integrity_check(self):
        object.__setattr__(self.onto, "fingerprint", "tampered")  # simulate out-of-band mutation
        with self.assertRaises(IntegrityError):
            self.gov.evaluate("verify_identity", self.state(), self.agent)


class AuditTests(unittest.TestCase):
    def test_hash_chain_detects_tampering(self):
        log = AuditLog()
        log.record("a", x=1)
        log.record("b", y=2)
        self.assertTrue(log.verify())
        log._entries[0].data["x"] = 999  # edit history
        self.assertFalse(log.verify())


if __name__ == "__main__":
    unittest.main()
