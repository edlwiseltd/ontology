"""R2 cross-domain validation: the cross-domain assessment added to the **proposed** evaluation protocol (GAP-083).

  V1 the assessment has the twelve dimensions the owner listed, in that order, and each says which automated
     measures feed it and whether a reviewer is needed
  V2 it reads a version 2 report by domain: lowest, highest and spread; it applies no bound, passes and fails nothing
  V3 an uneven architect shows as a wide spread that the average hides; a case with no answer is listed, not scored
  V4 it adds no measure and changes none: version 2 still has seventeen, version 1 and its recorded results are as
     they were (pinned by tests/test_stab4_evaluation_protocol.py)
  V5 a test double's report says it proves nothing about a language model; the two demonstrators are not cases of
     either protocol
"""

import json
import unittest

from autology import architect_eval as v1
from autology import architect_eval_v2 as v2

from .test_xdom1_cross_domain import DOMAINS

OWNERS_LIST = ["model_completeness", "domain_independence", "relationship_accuracy", "traceability", "rule_consistency",
               "authority_boundaries", "appropriate_autonomy", "unsupported_assumptions", "conflicting_evidence",
               "security_sensitive_inference", "repeatability", "cost_and_latency"]


class CrossDomainAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = v2.evaluate(v2.reference_proposal)
        cls.read = v2.cross_domain(cls.reference)

    def test_the_twelve_dimensions_are_the_owners(self):  # V1
        self.assertEqual(list(v2.CROSS_DOMAIN), OWNERS_LIST)
        self.assertEqual(list(self.read["dimensions"]), OWNERS_LIST)
        for name, spec in v2.CROSS_DOMAIN.items():
            self.assertLessEqual(set(spec["measures"]), set(v2.MEASURES), name)
            self.assertTrue(spec["measures"] or spec.get("derived"), name)  # fed by a measure, or says how it is read
        self.assertEqual(self.read["dimensions"]["unsupported_assumptions"]["by_domain"], {})
        self.assertTrue(self.read["dimensions"]["unsupported_assumptions"]["needs_expert"])
        self.assertIn("no automated measure", self.read["dimensions"]["unsupported_assumptions"]["derived"])

    def test_it_reads_by_domain_and_judges_nothing(self):  # V2
        self.assertEqual(len(self.read["domains"]), 8)
        self.assertIn("not in force", self.read["status"])
        text = json.dumps(self.read)
        for word in ('"met"', '"minimum"', '"maximum"', '"passed"', '"threshold"'):
            self.assertNotIn(word, text)
        completeness = self.read["dimensions"]["model_completeness"]
        self.assertEqual(set(completeness["by_domain"]), set(self.read["domains"]))
        self.assertEqual(completeness["spread"], round(completeness["highest"] - completeness["lowest"], 3))
        self.assertEqual(self.read["dimensions"]["cost_and_latency"]["cost_usd"]["highest"], 0.0)  # no call was paid
        self.assertEqual(set(self.read["dimensions"]["security_sensitive_inference"]["behaviour_by_domain"]),
                         set(self.read["domains"]))

    def test_an_uneven_architect_shows_as_a_spread_and_a_silent_case_is_listed(self):  # V3
        weak, silent = "building-permit", "batch-release"

        def uneven(case):
            if case["id"] == silent:
                raise RuntimeError("no answer")
            result = v2.reference_proposal(case)
            if case["id"] == weak:  # an architect that finds almost nothing in one business
                result = {**result, "items": [i for i in result["items"] if i["kind"] == "entity"][:1]}
            return result

        report = v2.evaluate(uneven, repeats=1)
        read = v2.cross_domain(report)
        self.assertEqual(read["unanswered"], [silent])
        self.assertNotIn(silent, read["domains"])
        independence = read["dimensions"]["domain_independence"]
        self.assertEqual(min(independence["by_domain"], key=independence["by_domain"].get), weak)
        self.assertGreater(independence["spread"], 0.3)
        self.assertLess(self.read["dimensions"]["domain_independence"]["spread"], independence["spread"])
        self.assertGreater(read["dimensions"]["model_completeness"]["spread"], 0.5)
        # the average alone would still look acceptable on some measures: that is what the spread is for
        self.assertGreater(report["measures"]["semantic_completeness"]["value"], 0.7)

    def test_nothing_is_added_to_or_changed_in_either_protocol(self):  # V4
        self.assertEqual(len(v2.MEASURES), 17)
        self.assertEqual(len(v2.cases()), 8)
        self.assertEqual(len(v1.cases()), 5)
        self.assertTrue(v2.PROTOCOL["status"].startswith("proposed: the owner has not approved it"))
        before = json.dumps(self.reference, sort_keys=True)
        v2.cross_domain(self.reference)
        self.assertEqual(json.dumps(self.reference, sort_keys=True), before)  # reading a report changes nothing in it
        self.assertNotIn("cross_domain", self.reference)

    def test_what_it_cannot_show_is_said(self):  # V5
        self.assertEqual(self.read["answered_by_a_language_model"], False)
        self.assertIn("proves nothing about a language model", self.read["reading"])
        ids = {c["id"] for c in v2.cases()} | {c["id"] for c in v1.cases()}
        briefs = " ".join(c["brief"] for c in v2.cases() + v1.cases())
        for d in DOMAINS.values():  # the demonstrators are demonstrations: they are not evaluation cases
            self.assertNotIn(d["blueprint"], ids)
            self.assertNotIn(d["brief"][:60], briefs)
