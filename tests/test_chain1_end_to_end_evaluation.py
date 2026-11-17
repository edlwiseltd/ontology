"""End-to-end evaluation of the chain (protocol chain-v1): no provider is called, nothing is spent.

  C1 two reserved briefs in domains nothing covers: no blueprint proposes for them, no code names their vocabulary,
     and they are not cases of protocol V1 or V2
  C2 twelve steps, each attributed to a component; three results (architect, builder, engine) and no total
  C3 only authorised corrections: an inferred element nobody confirmed stays out; a decision that names nothing is
     reported and applied to nothing; nothing is repaired
  C4 the builder and the engine on the resulting draft: a valid, deterministic manifest; a run, a review that waits,
     a decision, a refusal
  C5 the report is reproducible: the same answer gives the same digest
  C6 answers kept from the authorised evaluation are replayed at no cost, and fail where they failed
  C7 protocols V1 and V2 are used, not changed; the module holds no provider, credential or network call
  C8 a reserved draft hosted on the platform through its API: released by two people, in Simulation, with an
     application; a run waits for a person; the requester and a member without the run permission are refused
"""

import hashlib
import json
import re
import unittest
from pathlib import Path

from autology import architect_eval, architect_eval_v2, chain_eval
from autology.ontology import Ontology
from autology.simulation import sample_case
from autology.solution import suggest

from .test_xdom1_cross_domain import Hosted, Journey

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "planning" / "evidence" / "claude-eval-2026-11-17" / "run2-after-correction"
WORDS = re.compile(r"museum|conservator|borrower|collectionobject|loanrequest|pilotage|harbour|vessel", re.I)


def host(test, client, result, workspace="venues", members=("venues-vera", "venues-vito", "viv", "val")):
    """A draft produced by the chain, hosted through the platform's API: saved, configured with the plain starting
    configuration the Engine suggests, released by two people, moved to Simulation, with a saved application."""
    document = result["draft"]
    onto = Ontology.from_dict(dict(document))
    solution = suggest(document, sample_case(onto, document))
    reviewers = sorted({r.params["reviewer"] for r in onto.rules if r.kind == "human_review"})
    roles = solution["agents"]["solution_agent"]["roles"]
    template = next(iter(onto.case_templates.values()))
    root = next(i["id"] for i in solution["sample_data"]["instances"] if i["type"] == template.root)
    spec = {"use_case": result["case"], "template": f"{workspace}-blank", "admin": members[0], "approver": members[1],
            "operator": members[2], "reviewer": members[3], "operator_role": (roles or ["operator"])[0],
            "reviewer_role": (reviewers or ["reviewer"])[0], "agent": "solution_agent",
            "records": len(solution["sample_data"]["instances"]), "case": template.name, "root": root}
    j = Journey(test, client, workspace, spec)
    j.call("POST", f"{j.WS}/use-cases", body={"id": spec["use_case"], "name": result["title"], "template": spec["template"]}, expect=201)
    saved = j.call("POST", f"{j.E}/model/draft", body={"document": document, "expected_revision": 0, "note": "from the chain evaluation"})
    saved = j.call("POST", f"{j.E}/solution/draft", body={"solution": solution, "expected_revision": saved["revision"]})
    j.revision, j.document, j.configuration = saved["revision"], document, solution
    j.release()
    manifest = j.call("POST", f"{j.E}/application/generate", body={})["manifest"]
    j.call("POST", f"{j.E}/application/draft", body={"manifest": manifest, "expected_revision": 0, "note": "generated"})
    return j


class ReservedTests(unittest.TestCase):
    def test_two_reserved_briefs_that_nothing_covers(self):  # C1
        cases = chain_eval.reserved()
        self.assertEqual([c["id"] for c in cases], ["harbour-pilotage", "museum-loans"])
        earlier = {c["id"] for c in architect_eval.cases()} | {p.stem for p in (ROOT / "autology" / "evaluation_v2").glob("*.json")}
        for case in cases:
            self.assertTrue(case["synthetic"] and case["reserved"])
            self.assertNotIn(case["id"], earlier)
            self.assertIn("never used to answer a request", case["reference_answer_note"])
            self.assertTrue(set(case["authorised_decisions"]) >= {"by", "confirm", "drop"})
        # no code, blueprint, example or screen names their vocabulary: nothing was built for them
        searched = [p for folder, patterns in (("autology", ("*.py",)), ("autology/blueprints", ("*.json",)), ("examples", ("**/*.json", "**/*.py")),
                                               ("studio/web/runtime", ("*.ts", "*.tsx")), ("studio/web/components", ("*.tsx",)),
                                               ("studio/web/lib", ("*.ts",)))
                    for pattern in patterns for p in (ROOT / folder).glob(pattern) if "node_modules" not in p.parts]
        self.assertGreater(len(searched), 80)
        for path in searched:
            hit = WORDS.search(path.read_text(encoding="utf-8"))
            self.assertIsNone(hit, (str(path.relative_to(ROOT)), hit and hit.group(0)))
        from autology import modeling

        packs = [ROOT / "examples" / "domains" / "blueprints"]
        # No blueprint of a domain recognises either brief. The one that does is the industry-neutral "request and
        # approval" template, by two generic words; it holds none of the briefs' concepts (scanned above), so the
        # template-based architect would answer with a generic model, not with a model of the domain.
        for case in cases:
            for found, _ in (modeling.match(case["brief"]), modeling.match(case["brief"], packs)):
                self.assertEqual((found or {}).get("id"), "service-request", case["id"])
                self.assertIn("Industry-neutral", found["description"])


class ChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {c["id"]: c for c in chain_eval.reserved()}
        cls.result = chain_eval.evaluate(list(cls.cases.values()), chain_eval.reference, source="reference answers")
        cls.rows = {r["case"]: r for r in cls.result["cases"]}

    def test_twelve_steps_three_results_and_no_total(self):  # C2
        self.assertEqual((len(chain_eval.STEPS), chain_eval.PROTOCOL), (12, "chain-v1"))
        for row in self.rows.values():
            self.assertEqual([s["step"] for s in row["steps"]], list(range(1, 13)))
            self.assertEqual([s["name"] for s in row["steps"]], chain_eval.STEPS)
            self.assertTrue(all(s["component"] in ("A", "B", "C", "harness") for s in row["steps"]))
            self.assertEqual({k: row[k]["component"] for k in "ABC"}, chain_eval.COMPONENTS)
        self.assertIsNone(self.result["aggregate"])

        def keys(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield str(k)
                    yield from keys(v)
            elif isinstance(value, list):
                for v in value:
                    yield from keys(v)

        for key in keys({k: v for k, v in self.result.items() if k != "aggregate"}):
            self.assertIsNone(re.search(r"overall|total|aggregate|maturity|\bscore\b", key), key)
        text = chain_eval.render(self.result)
        self.assertIn("No total is computed", text)
        self.assertEqual([line[:2] for line in text.splitlines() if re.match(r"[ABC]\. ", line)], ["A.", "B.", "C."])

    def test_only_authorised_corrections_are_applied(self):  # C3
        row = self.rows["museum-loans"]
        self.assertEqual(row["corrections"]["confirmed"], ["model:case_template:loan_case", "model:rule:R-VALUE"])
        self.assertEqual(row["corrections"]["not_applied_unconfirmed"], ["model:rule:R-VALUATION"])
        self.assertEqual([r["id"] for r in row["draft"]["rules"]], ["R-VALUE", "R-FRAGILE"])
        self.assertEqual(self.rows["harbour-pilotage"]["corrections"]["not_applied_unconfirmed"], ["model:rule:R-REST"])
        case = self.cases["museum-loans"]
        nobody = chain_eval.run_case(case, chain_eval.reference, decisions={})
        self.assertEqual(nobody["corrections"]["by"], "nobody: no decision was given")
        self.assertEqual(len(nobody["corrections"]["not_applied_unconfirmed"]), 3)
        self.assertNotIn("case_templates", nobody["draft"])  # the inferred case template stayed out: nothing filled it in
        everything = chain_eval.run_case(case, chain_eval.reference, decisions=chain_eval.CONFIRM_ALL)
        self.assertIn("an assumption of the replay", everything["corrections"]["by"])
        self.assertEqual(len(everything["draft"]["rules"]), 3)
        stray = chain_eval.run_case(case, chain_eval.reference, decisions={"confirm": ["model:rule:R-INVENTED"], "drop": [], "by": "x"})
        self.assertEqual(stray["corrections"]["decisions_naming_no_element"], ["model:rule:R-INVENTED"])
        self.assertIs(stray["steps"][5]["ok"], False)
        # nothing is repaired: without an entity that others refer to, the Engine refuses the draft and the chain stops
        broken = chain_eval.run_case(case, chain_eval.reference, decisions={"confirm": [], "drop": ["model:entity:Borrower"], "by": "x"})
        self.assertEqual((broken["C"]["draft_accepted"], broken["B"]["generated"], broken["C"]["governed_work"]), (False, False, None))
        self.assertIn("Borrower", broken["C"]["problems"][0])
        self.assertEqual([s["ok"] for s in broken["steps"][6:11]], [False, None, None, None, None])

    def test_the_builder_and_the_engine_on_the_draft(self):  # C4
        loans, pilotage = self.rows["museum-loans"], self.rows["harbour-pilotage"]
        for row in (loans, pilotage):
            b = row["B"]
            self.assertEqual((b["generated"], b["valid"], b["deterministic"], b["problems"], b["cannot_do"]), (True, True, True, [], 7))
            self.assertEqual((b["screens"], b["menu_entries"], b["every_screen_is_of_a_type_the_renderer_draws"]), (16, 7, True))
            self.assertEqual(b["browser"], "not run by this harness")
            self.assertEqual((row["C"]["draft_accepted"], row["C"]["refused_elements"]), (True, 0))
        work = loans["C"]["governed_work"]
        self.assertEqual((work["default"], work["review_requested"], work["reviewers"]), ("awaiting_review", True, ["director"]))
        self.assertEqual((work["with_approval"], work["with_refusal"], work["decision_by_another_role_refused"]), ("completed", "blocked", True))
        self.assertEqual(pilotage["C"]["governed_work"]["default"], "completed")
        a = loans["A"]
        self.assertEqual((a["answered"], a["language_model"], a["provider"], a["questions"], a["proposed"], a["accepted_by_engine"]),
                         (True, False, "reference", 3, 13, 13))
        self.assertEqual((a["approval_requirements"], a["missing_concepts"], a["planted_instruction_found"], a["cost_usd"]),
                         (["R-VALUE"], [], [], 0.0))
        self.assertEqual(self.result["A"]["language_model_answers"], 0)
        self.assertEqual((self.result["B"]["manifests_valid"], self.result["C"]["drafts_accepted"]), ("2 of 2", "2 of 2"))

    def test_the_report_is_reproducible(self):  # C5
        again = chain_eval.evaluate(list(self.cases.values()), chain_eval.reference, source="reference answers")
        self.assertEqual([r["reproducibility"]["digest"] for r in again["cases"]],
                         [r["reproducibility"]["digest"] for r in self.result["cases"]])
        self.assertIn("elapsed time", self.rows["museum-loans"]["reproducibility"]["excludes"])
        other = chain_eval.run_case(self.cases["museum-loans"], chain_eval.reference, decisions=chain_eval.CONFIRM_ALL)
        self.assertNotEqual(other["reproducibility"]["digest"], self.rows["museum-loans"]["reproducibility"]["digest"])

    def test_what_the_engine_does_is_reported_as_it_is_including_when_it_is_wrong(self):  # C4
        from unittest import mock

        case = self.cases["museum-loans"]
        goalless = chain_eval.run_case(case, chain_eval.reference, decisions={"confirm": ["model:case_template:loan_case"],
                                                                             "drop": ["model:goal:loan_agreed"], "by": "x"})
        work = goalless["C"]["governed_work"]  # a model with no goal: accepted as a draft, and nothing can be planned
        self.assertEqual((goalless["C"]["draft_accepted"], work["default"], goalless["steps"][10]["ok"]), (True, None, False))
        self.assertIn("no goal", work["why"])
        real = chain_eval.simulate

        def lenient(document, case=None, goal=None, roles=None, approvals=()):
            if roles == []:
                raise chain_eval.SimulationError("nobody to act")
            if approvals and approvals[0]["as"] == "a-role-the-rule-does-not-name":  # an engine that accepted any reviewer
                return real(document, approvals=[{**approvals[0], "as": "director"}])
            return real(document, case, goal, roles, approvals)

        with mock.patch.object(chain_eval, "simulate", lenient):
            wrong = chain_eval.run_case(case, chain_eval.reference)["C"]["governed_work"]
        self.assertIs(wrong["decision_by_another_role_refused"], False)  # it would be reported, not hidden
        self.assertEqual(wrong["without_any_role"], "not run: nobody to act")

    def test_a_failed_answer_stops_the_case_and_is_never_left_out(self):  # C2
        def failing(case):
            raise RuntimeError("the provider did not answer")

        out = chain_eval.evaluate(list(self.cases.values()), failing, source="a failing double")
        self.assertEqual((out["A"]["answered"], out["C"]["drafts_accepted"], len(out["cases"])), ("0 of 2", "0 of 0", 2))
        for row in out["cases"]:
            self.assertEqual((row["A"]["answered"], [s["ok"] for s in row["steps"]]), (False, [True, False] + [None] * 10))
            self.assertIn("did not answer", row["A"]["failure"])


class EvidenceTests(unittest.TestCase):
    def test_kept_answers_are_replayed_at_no_cost_and_fail_where_they_failed(self):  # C6
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVIDENCE.glob("*.json"))}
        cases = architect_eval.cases()
        strict = chain_eval.evaluate(cases, chain_eval.replay(EVIDENCE), decisions={}, source="run 2, no decision")
        assumed = chain_eval.evaluate(cases, chain_eval.replay(EVIDENCE), decisions=chain_eval.CONFIRM_ALL, source="run 2, confirm all")
        for out in (strict, assumed):
            self.assertEqual((out["A"]["answered"], out["A"]["language_model_answers"]), ("4 of 5", 4))
            failed = next(r for r in out["cases"] if r["case"] == "airline-disruption")
            self.assertIn("refused or never received", failed["A"]["failure"])
            kept = sum(json.loads((EVIDENCE / f"{c['id']}-1.json").read_text())["cost_usd"] for c in cases if (EVIDENCE / f"{c['id']}-1.json").is_file())
            self.assertEqual(out["A"]["cost_usd_recorded_with_the_answers"], round(kept, 6))  # what was spent then; nothing now
        # with no person's decision, three of four answers give no draft the Engine accepts; assuming every confirmation, four do
        self.assertEqual((strict["C"]["drafts_accepted"], assumed["C"]["drafts_accepted"]), ("1 of 4", "4 of 4"))
        self.assertEqual((assumed["B"]["manifests_valid"], assumed["C"]["runs_that_proceed"]), ("4 of 4", "3 of 4"))
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(EVIDENCE.glob("*.json"))})

    def test_the_protocols_are_used_not_changed_and_nothing_is_asked_of_a_provider(self):  # C7
        source = (ROOT / "autology" / "chain_eval.py").read_text(encoding="utf-8")
        code = source.split('"""', 2)[2]
        for word in ("anthropic", "EVALUATION_AI_KEY", "environ", "urllib", "socket", "requests", "http", "api_key", "THRESHOLDS ="):
            self.assertNotIn(word, code, word)
        self.assertEqual(len(architect_eval.THRESHOLDS), 13)
        self.assertEqual(len(architect_eval_v2.CROSS_DOMAIN), 12)
        case = chain_eval.reserved()[0]
        row = chain_eval.run_case(case, chain_eval.reference)
        direct = architect_eval.score(case, chain_eval.reference(case))
        direct.pop("details")
        self.assertEqual(row["A"]["v1_measures"], direct)  # V1's scorer, called as it is
        self.assertEqual(set(row["A"]["v1_measures"]), set(architect_eval.THRESHOLDS) - {"repeatability"})


class CommandTests(unittest.TestCase):
    def test_the_command_has_no_way_to_call_a_provider(self):  # C7
        import contextlib
        import io

        from autology.__main__ import main

        def run(*argv):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["chain-eval", *argv]), 0)
            return out.getvalue()

        text = run("--reference")
        self.assertIn("hand-written reference answers (not a model)", text)
        self.assertIn("No total is computed", text)
        self.assertEqual(json.loads(run("--reference", "--json"))["aggregate"], None)
        strict, assumed = run("--replay", str(EVIDENCE)), run("--replay", str(EVIDENCE), "--assume-confirmed")
        self.assertIn("drafts accepted 1 of 4", strict)
        self.assertIn("no decision of a person", strict)
        self.assertIn("drafts accepted 4 of 4", assumed)
        self.assertIn("an assumption of the replay", assumed)
        for flag in ("--platform", "--provider", "--workspace", "--model"):  # no such option exists
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                main(["chain-eval", "--reference", flag, "x"])


class HostedChainTests(Hosted):
    def test_a_reserved_draft_through_the_platform(self):  # C8
        case = next(c for c in chain_eval.reserved() if c["id"] == "museum-loans")
        result = chain_eval.run_case(case, chain_eval.reference)
        j = host(self, self.c, result)
        d = j.d
        self.assertEqual(j.released["approved_by"], "vito@venues")  # a second person: the author's own approval was refused
        self.assertIn(j.own_approval["status"] if isinstance(j.own_approval, dict) and "status" in j.own_approval else 403, (403, 409))
        operator, reviewer = j.token(d["operator"]), j.token(d["reviewer"])
        app = j.call("GET", f"{j.E}/application", operator)
        self.assertEqual((app["governance"]["simulation_ready"]["value"], app["governance"]["approved_release_artifact"]["supported"],
                          app["release"]["number"], app["release"]["runs"], app["stage"]), (True, False, 1, True, "simulation"))
        self.assertEqual((len(app["manifest"]["views"]), [v["type"] for v in app["manifest"]["views"]].count("EntityListView")),
                         (result["B"]["screens"], 3))  # the same screens the harness generated, served by the Engine
        run = j.call("POST", f"{j.E}/runs", operator, {"case_template": d["case"], "root": d["root"]})
        self.assertEqual(run["status"], "awaiting_review", run)  # as the draft simulation said it would
        decision = f"{j.E}/reviews/{run['pending_review']}/decision"
        self.assertEqual(self.c.call("POST", decision, operator, {"approved": True, "comment": "mine"})[0], 403)
        self.assertEqual(self.c.call("POST", f"{j.E}/runs", reviewer, {"case_template": d["case"], "root": d["root"]})[0], 403)
        done = j.call("POST", decision, reviewer, {"approved": True, "comment": "checked"})
        self.assertEqual(done["status"], "completed")
        trail = j.call("GET", f"{j.E}/runs/{run['run_id']}/audit", operator)
        self.assertTrue(trail["verified"])
        self.assertEqual(j.call("GET", f"{j.E}/objects/{d['root']}", operator)["attributes"]["status"], "agreed")
