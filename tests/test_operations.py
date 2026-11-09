"""Agent operations: self-healing, delegation, ABAC, suspension, provenance, versions, reporting, cost."""

import json
import unittest
from types import SimpleNamespace

from autology import (AutoApprover, ClaudeReasoner, DecisionContext, GovernanceLayer, Ontology,
                      PlanFollowingReasoner, Principal, Proposal, ToolResult, WorkAgent, WorldState)
from autology.economics import TCOModel, evaluate, from_metrics
from autology.ontology import load_document
from autology.reasoners import RoutingReasoner, estimate_cost
from autology.reporting import compliance_report, metrics, ontology_gaps, rule_statistics
from autology.versioning import OntologyRegistry

from .helpers import MFG_ONTOLOGY, ONTOLOGY_PATH, build_registry, manufacturing_tools as mt, order_case, retail_case, \
    supplier_case


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)


def mfg():
    return Ontology.load(MFG_ONTOLOGY)


def procurement_agent(onto, faults=None, with_finance=True, **kw):
    kw.setdefault("approver", AutoApprover())
    kw.setdefault("sleep", lambda seconds: None)
    finance = WorkAgent("finance-agent", onto, mt.finance_tools(), roles=["finance"])
    return WorkAgent("procurement-agent", onto, mt.procurement_tools(faults), roles=["procurement"],
                     delegates=[finance] if with_finance else [], **kw)


def production_agent(onto, faults=None, clock=None, **kw):
    clock = clock or Clock()
    return WorkAgent("production-agent", onto, mt.production_tools(faults), roles=["production"],
                     approver=AutoApprover(), clock=clock, sleep=clock.sleep, **kw)


class PlanningTests(unittest.TestCase):
    def test_plans_through_non_default_outcome_when_needed(self):
        result = procurement_agent(mfg()).run("contract_supplier", supplier_case(late_delivery_penalty=False))
        self.assertTrue(result.completed, result.escalation)
        self.assertEqual(result.path, ["set_payment_terms:done", "check_clauses:missing_penalty",
                                       "escalate_to_legal:redlined", "check_clauses:compliant",
                                       "sign_supplier_contract:done"])

    def test_context_reroute(self):
        result = production_agent(mfg()).run("fulfil_order", order_case(on_time_rate=0.5))
        self.assertTrue(result.completed)
        self.assertIn("reroute_to_alternate_line:done", result.path)
        stuck = production_agent(mfg()).run("fulfil_order", order_case(on_time_rate=0.5, alternate=False))
        self.assertEqual(stuck.status, "escalated")
        self.assertTrue(any("R-PROD-001" in d or "ProductionLine" in d or "primary line" in d
                            for d in stuck.escalation.details))


class SelfHealingTests(unittest.TestCase):
    def test_fallback_tool_used_when_primary_fails(self):
        result = procurement_agent(mfg(), mt.Faults(clause_ai_down=True)).run("contract_supplier", supplier_case())
        self.assertTrue(result.completed)
        step = next(s for s in result.steps if s.action == "check_clauses")
        self.assertEqual(step.tool, "outside_counsel_review")
        # fallback_after=1: the cheap checker is retried once before the 400 fallback is paid for
        self.assertEqual(result.costs["tools"], 1.0 + 0.05 + 0.05 + 400.0 + 2.0)

    def test_cheap_retry_avoids_expensive_fallback(self):
        slept = []
        agent = procurement_agent(mfg(), mt.Faults(clause_ai_failures=1), sleep=slept.append)
        result = agent.run("contract_supplier", supplier_case())
        self.assertTrue(result.completed)
        self.assertEqual(next(s.tool for s in result.steps if s.action == "check_clauses"), "ai_clause_checker")
        self.assertEqual(slept, [1.0])
        self.assertNotIn("outside_counsel_review", [e.data["tool"] for e in result.audit.events("tool.call")])

    def test_cheapest_tool_preferred(self):
        result = procurement_agent(mfg()).run("contract_supplier", supplier_case())
        self.assertEqual(next(s.tool for s in result.steps if s.action == "check_clauses"), "ai_clause_checker")

    def test_defer_resume_and_escalate_to_policy_owner(self):
        clock = Clock()
        agent = production_agent(mfg(), mt.Faults(mes_down=1), clock)
        res = agent.run("fulfil_order", order_case())
        self.assertEqual(res.status, "deferred")
        self.assertEqual(res.resume_at, clock.now + 3600)
        self.assertIs(agent.resume(res), res)  # too early: still deferred
        clock.now += 3600
        res = agent.resume(res)
        self.assertTrue(res.completed)
        self.assertTrue(res.audit.verify())
        self.assertEqual(len(res.audit.events("run.resume")), 1)

        agent = production_agent(mfg(), mt.Faults(mes_down=9), clock)
        res = agent.run("fulfil_order", order_case())
        while res.status == "deferred":
            clock.now += 3600
            res = agent.resume(res)
        self.assertEqual(res.status, "escalated")
        self.assertEqual(res.escalation.to, "plant_manager")
        self.assertEqual(len(res.audit.events("tool.error")), 3)

    def test_short_backoff_waits_inline(self):
        doc = load_document(MFG_ONTOLOGY)
        doc["actions"]["start_production"]["on_failure"] = {"max_attempts": 4, "backoff_seconds": 2}
        clock = Clock()
        res = production_agent(Ontology.from_dict(doc), mt.Faults(mes_down=2), clock).run("fulfil_order", order_case())
        self.assertTrue(res.completed)
        self.assertEqual(clock.slept, [2.0, 2.0])

    def test_tool_allow_list(self):
        doc = load_document(MFG_ONTOLOGY)
        doc["actions"]["check_clauses"]["tools"] = ["outside_counsel_review"]
        res = procurement_agent(Ontology.from_dict(doc)).run("contract_supplier", supplier_case())
        self.assertEqual(next(s.tool for s in res.steps if s.action == "check_clauses"), "outside_counsel_review")
        doc["actions"]["check_clauses"]["tools"] = ["unregistered_tool"]
        res = procurement_agent(Ontology.from_dict(doc)).run("contract_supplier", supplier_case())
        self.assertEqual(res.status, "escalated")
        self.assertIn("allowed tools", res.escalation.reason)


class AccessControlTests(unittest.TestCase):
    def test_write_access_forces_delegation(self):
        res = procurement_agent(mfg()).run("contract_supplier", supplier_case())
        step = res.steps[0]
        self.assertEqual((step.action, step.executed_by), ("set_payment_terms", "finance-agent"))
        self.assertEqual(res.state.get("Contract", "payment_terms"), "net 30")
        self.assertEqual(len(res.audit.events("delegate")), 1)
        solo = procurement_agent(mfg(), with_finance=False).run("contract_supplier", supplier_case())
        self.assertEqual(solo.status, "escalated")
        self.assertTrue(any("may not modify Contract.payment_terms" in d for d in solo.escalation.details))

    def test_tool_cannot_write_restricted_field_for_wrong_principal(self):
        onto = mfg()
        tools = mt.procurement_tools()
        tools.register("sneaky_esign", "esign.send", lambda c: ToolResult(updates={"Contract": {"revision": 9}}),
                       priority=9)
        finance = WorkAgent("finance-agent", onto, mt.finance_tools(), roles=["finance"])
        agent = WorkAgent("p", onto, tools, roles=["procurement"], delegates=[finance], approver=AutoApprover())
        result = agent.run("contract_supplier", supplier_case())
        self.assertEqual(result.status, "escalated")
        self.assertIn("undeclared field Contract.revision", result.escalation.reason)

    def test_action_access(self):
        onto = mfg()
        case = {"Product": {"name": "B", "defect_rate": 0.05}, "Supplier": {"name": "X"}, "QualityCase": {}}
        intruder = WorkAgent("production-agent", onto, mt.quality_tools(), roles=["production"], approver=AutoApprover())
        res = intruder.run("resolve_quality_case", case)
        self.assertEqual(res.status, "escalated")
        self.assertTrue(any("may not execute initiate_recall" in d for d in res.escalation.details))
        quality = WorkAgent("quality-agent", onto, mt.quality_tools(), roles=["quality"], approver=AutoApprover())
        self.assertTrue(quality.run("resolve_quality_case", case).completed)

    def test_suspension_after_repeated_violations_persists(self):
        class Rogue:
            def propose(self, ctx):
                return Proposal("sign_supplier_contract", "now", "rogue")

        onto = mfg()
        agent = procurement_agent(onto, reasoner=Rogue())
        case = supplier_case(late_delivery_penalty=False)
        res = agent.run("contract_supplier", case)
        self.assertEqual(res.status, "suspended")
        self.assertEqual(agent.governance.violations["procurement-agent"], 3)
        self.assertNotIn("sign_supplier_contract:done", res.path)
        again = agent.run("contract_supplier", case)  # still suspended on the next case
        self.assertEqual(again.status, "suspended")
        self.assertEqual(again.steps, [])
        agent.governance.reinstate("procurement-agent")
        agent.reasoner = PlanFollowingReasoner()
        self.assertTrue(agent.run("contract_supplier", case).completed)


class ProvenanceTests(unittest.TestCase):
    def test_decisions_explain_rules_and_facts(self):
        res = procurement_agent(mfg()).run("contract_supplier", supplier_case(value=1_500_000))
        sign = [e for e in res.audit.events("decision") if e.data["action"] == "sign_supplier_contract"][0].data
        self.assertIn("R-PROC-001", sign["satisfied_rules"])
        self.assertEqual(sign["rules"], ["R-FIN-002"])
        self.assertEqual(sign["facts"]["Contract.value"], 1_500_000)
        self.assertIn("requires human review", sign["explanation"])
        self.assertIn("Contract.value=1500000", sign["explanation"])

    def test_review_requests_are_context_rich(self):
        approver = AutoApprover()
        procurement_agent(mfg(), approver=approver).run("contract_supplier", supplier_case(value=2_000_000))
        req = approver.requests[-1]
        self.assertEqual(req.action, "sign_supplier_contract")
        self.assertEqual(req.rule_ids, ["R-FIN-002"])
        self.assertIn("check_clauses->compliant", req.history)
        self.assertIn("Contract.value", req.facts)
        self.assertIn("needs cfo approval", req.summary())

    def test_facts_are_redacted_for_principal(self):
        onto = Ontology.load(ONTOLOGY_PATH)
        gov = GovernanceLayer(onto)
        state = WorldState.initial(onto, retail_case())
        decision = gov.evaluate("verify_identity", state, Principal("sales", ["sales"]))
        self.assertNotIn("GB-1234", decision.explanation())


class OntologyLifecycleTests(unittest.TestCase):
    def test_pause_when_pinned_version_withdrawn_or_superseded(self):
        onto = mfg()
        reg = OntologyRegistry()
        reg.publish(onto)
        agent = production_agent(onto, registry=reg)
        self.assertTrue(agent.run("fulfil_order", order_case()).completed)
        doc = load_document(MFG_ONTOLOGY)
        doc["version"] = "1.1.0"
        doc["entities"]["Order"]["attributes"]["priority"] = "string"
        reg.publish(Ontology.from_dict(doc))
        res = agent.run("fulfil_order", order_case())  # default: continue on pinned version, note update
        self.assertTrue(res.completed)
        self.assertEqual(len(res.audit.events("ontology.update_available")), 1)
        agent.on_ontology_update = "pause"
        self.assertEqual(agent.run("fulfil_order", order_case()).status, "paused")
        agent.on_ontology_update = "continue"
        reg.withdraw(onto.name, onto.version)
        res = agent.run("fulfil_order", order_case())
        self.assertEqual(res.status, "paused")
        self.assertIn("withdrawn", res.escalation.reason)
        self.assertEqual(res.steps, [])

    def test_integrity_failure_pauses_instead_of_crashing(self):
        onto = mfg()
        agent = production_agent(onto)
        object.__setattr__(onto, "fingerprint", "tampered")
        res = agent.run("fulfil_order", order_case())
        self.assertEqual(res.status, "paused")
        self.assertEqual(res.escalation.to, "ontology-admin")


class ReportingTests(unittest.TestCase):
    def runs(self):
        onto = mfg()
        return onto, [
            procurement_agent(onto).run("contract_supplier", supplier_case()),
            procurement_agent(onto).run("contract_supplier", supplier_case(value=2_000_000)),
            procurement_agent(onto, approver=AutoApprover({"sign_supplier_contract": False})).run(
                "contract_supplier", supplier_case(value=2_000_000)),
            production_agent(onto, mt.Faults(partial_delivery=True)).run("fulfil_order", order_case()),
        ]

    def test_metrics(self):
        _, results = self.runs()
        m = metrics(results)
        self.assertEqual(m.tasks, 4)
        self.assertEqual(m.by_status, {"completed": 2, "blocked": 1, "escalated": 1})
        self.assertEqual(m.success_rate, 0.5)
        self.assertEqual(m.straight_through_rate, 0.25)
        self.assertEqual(m.human_intervention_rate, 0.75)
        self.assertEqual(m.reviews, 2)
        self.assertEqual(m.delegations, 3)
        self.assertGreater(m.tool_cost, 0)
        self.assertAlmostEqual(m.cost_per_completed_task, m.cost_per_task * 4 / 2, places=4)

    def test_rule_stats_and_report(self):
        onto, results = self.runs()
        stats = rule_statistics(results, onto)
        self.assertEqual(stats["R-PROC-001"].satisfied, 2)
        self.assertEqual((stats["R-FIN-002"].reviews_approved, stats["R-FIN-002"].reviews_declined), (1, 1))
        self.assertEqual(stats["R-FIN-001"].satisfied, 3)
        report = compliance_report(results, onto)
        self.assertIn("| R-FIN-002 | human_review | 2 |", report)
        self.assertIn("Audit trails intact: yes", report)
        self.assertIn("unmodelled outcome", report)

    def test_gap_analysis(self):
        _, results = self.runs()
        gaps = ontology_gaps(results)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].kind, "unmodelled outcome")
        self.assertIn("'partial_delivery'", gaps[0].suggestion)
        self.assertIn("check_material_supply", gaps[0].suggestion)


class EconomicsTests(unittest.TestCase):
    def test_roi_arithmetic(self):
        model = TCOModel(ontology_development=100_000, integration=20_000, ontology_maintenance_per_year=10_000,
                         llm_cost_per_task=0.1, tasks_per_month=1000, manual_hours_per_task=1, hourly_rate=100,
                         intervention_rate=0.1, human_hours_per_intervention=0.5, horizon_years=2)
        r = evaluate(model)
        self.assertEqual(r.tasks_per_year, 12_000)
        self.assertEqual(r.baseline_cost_per_year, 1_200_000)
        self.assertAlmostEqual(r.autology_run_cost_per_year, 1_200 + 60_000 + 10_000)
        self.assertAlmostEqual(r.net_savings_per_year, 1_128_800)
        self.assertAlmostEqual(r.payback_months, 120_000 / (1_128_800 / 12))
        self.assertAlmostEqual(r.roi, (2_400_000 - (120_000 + 2 * 71_200)) / (120_000 + 2 * 71_200))
        self.assertIsNone(evaluate(TCOModel(ontology_development=1)).payback_months)

    def test_from_metrics_uses_measurements(self):
        m = SimpleNamespace(tasks=10, human_intervention_rate=0.3, llm_cost_usd=0.5, llm_calls=4, tool_cost=20.0)
        model = from_metrics(TCOModel(llm_cost_per_task=9, intervention_rate=0.9), m)
        self.assertEqual((model.intervention_rate, model.llm_cost_per_task, model.tool_cost_per_task), (0.3, 0.05, 2.0))
        no_llm = from_metrics(TCOModel(llm_cost_per_task=9), SimpleNamespace(**{**m.__dict__, "llm_calls": 0}))
        self.assertEqual(no_llm.llm_cost_per_task, 9)

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ValueError):
            TCOModel.from_dict({"ontology_developmnet": 1})


class FakeClaude:
    def __init__(self, picker=None):
        self.requests = []
        self.picker = picker or (lambda names: names[-1])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        names = kw["output_config"]["format"]["schema"]["properties"]["action"]["enum"]
        usage = SimpleNamespace(input_tokens=1000, output_tokens=50, cache_read_input_tokens=3000,
                                cache_creation_input_tokens=0)
        text = json.dumps({"action": self.picker(names), "rationale": "ok"})
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], usage=usage,
                               content=[SimpleNamespace(type="text", text=text)])


class CostOptimisationTests(unittest.TestCase):
    def test_cost_estimate(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
        self.assertAlmostEqual(estimate_cost("claude-opus-5-5", usage), 4 + 20 + 0.4)
        self.assertAlmostEqual(estimate_cost("claude-haiku-5-5", usage), 0.1 + 0.5 + 0.01)

    def test_valid_but_useless_llm_choices_are_bounded(self):
        client = FakeClaude(picker=lambda names: names[0])  # keeps re-running due diligence
        onto = Ontology.load(ONTOLOGY_PATH)
        agent = WorkAgent("a", onto, build_registry(), roles=["sales", "kyc"], reasoner=ClaudeReasoner(client),
                          approver=AutoApprover())
        res = agent.run("onboard_customer", retail_case())
        self.assertEqual(res.status, "escalated")
        self.assertIn("enhanced_due_diligence attempted 3 times", res.escalation.reason)

    def test_routing_skips_model_for_trivial_choices_and_right_sizes(self):
        client = FakeClaude(picker=lambda names: next(n for n in names if n != "enhanced_due_diligence"))
        router = RoutingReasoner(ClaudeReasoner(client, "claude-haiku-5-5", effort="low"),
                                 ClaudeReasoner(client, "claude-opus-5-5"), simple_max_candidates=1)
        onto = Ontology.load(ONTOLOGY_PATH)
        agent = WorkAgent("a", onto, build_registry(), roles=["sales", "kyc"], reasoner=router, approver=AutoApprover())
        res = agent.run("onboard_customer", retail_case())
        self.assertTrue(res.completed)
        self.assertGreater(router.routes["deterministic"], 0)
        self.assertEqual(router.routes["deterministic"] + router.routes["complex"], len(res.steps))
        self.assertEqual(len(client.requests), router.routes["complex"])
        self.assertTrue(all(r["model"] == "claude-opus-5-5" for r in client.requests))
        self.assertGreater(res.costs["llm_usd"], 0)

    def test_request_shape_per_model(self):
        onto = Ontology.load(ONTOLOGY_PATH)
        ctx = DecisionContext(onto, onto.goals["onboard_customer"], ["verify_identity"],
                              [onto.actions["verify_identity"], onto.actions["submit_contract"]], {"Customer": {}})
        client = FakeClaude()
        ClaudeReasoner(client, "claude-opus-5-5").propose(ctx)
        ClaudeReasoner(client, "claude-haiku-5-5", effort="low").propose(ctx)
        opus, haiku = client.requests
        self.assertEqual(opus["fallbacks"], "default")
        self.assertEqual(opus["betas"], ["server-side-fallback-2026-07-01"])
        self.assertNotIn("fallbacks", haiku)  # no server-side fallback on Haiku
        self.assertEqual(haiku["output_config"]["effort"], "low")
        self.assertEqual(opus["cache_control"], {"type": "ephemeral"})
        self.assertIn("Ontology customer-onboarding@1.2.0", opus["system"])  # stable, cacheable prefix
        self.assertNotIn("CASE STATE", opus["system"])

    def test_decision_cache(self):
        onto = Ontology.load(ONTOLOGY_PATH)
        ctx = DecisionContext(onto, onto.goals["onboard_customer"], ["verify_identity"],
                              [onto.actions["verify_identity"], onto.actions["submit_contract"]], {"Customer": {}})
        client = FakeClaude()
        reasoner = ClaudeReasoner(client)
        first, second = reasoner.propose(ctx), reasoner.propose(ctx)
        self.assertEqual((first.source, second.source), ("llm", "llm-cache"))
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(second.cost_usd, 0.0)
        self.assertGreater(first.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
