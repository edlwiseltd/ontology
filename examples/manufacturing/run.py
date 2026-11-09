"""Autology in a manufacturing enterprise - end-to-end walkthrough of the methodology.

    python examples/manufacturing/run.py            # everything
    python examples/manufacturing/run.py agents     # just the agent scenarios
    python examples/manufacturing/run.py --report report.md   # also write the compliance report

Sections: 1 ontology engineering (modules, lint, competency questions, export),
2 agents (ProcurementAgent + FinanceAgent, ProductionAgent, QualityAgent),
3 feedback loop & versioning (PartialDelivery gap -> v1.1.0), 4 governance
report, 5 TCO / ROI from measured run metrics.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE)]

from autology import AutoApprover, Ontology, Proposal, WorkAgent  # noqa: E402
from autology.economics import TCOModel, evaluate, from_metrics  # noqa: E402
from autology.export import to_jsonld, to_turtle  # noqa: E402
from autology.graph import KnowledgeGraph  # noqa: E402
from autology.lint import lint  # noqa: E402
from autology.ontology import load_document  # noqa: E402
from autology.reporting import compliance_report, metrics, ontology_gaps  # noqa: E402
from autology.versioning import OntologyRegistry, VersionError, diff  # noqa: E402
from manufacturing_tools import Faults, finance_tools, procurement_tools, production_tools, quality_tools  # noqa: E402

ENTERPRISE = HERE / "enterprise.json"


class FakeClock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def printer(event: str, data: dict) -> None:
    if event == "decision":
        who = f" by {data['executed_by']}" if data.get("executed_by") else ""
        print(f"  [{data['step']:>2}] {data['action']:<26} {data['verdict'].upper():<6}{who}")
    elif event == "delegate":
        print(f"       ~ delegated by {data['from_agent']} to {data['to_agent']} (role required)")
    elif event == "governance.deny":
        print(f"       ! denied {data['action']} ({data['proposed_by']}): {'; '.join(data['reasons'])[:110]}")
    elif event == "review":
        print(f"       ? {data['reviewer']}: {'APPROVED' if data['approved'] else 'DECLINED'} ({', '.join(data['rules'])})")
    elif event == "tool.error":
        print(f"       x {data['tool']} round {data['attempt']}: {data['error']}")
    elif event == "step":
        print(f"       -> {data['tool']}: {data['outcome']} - {data['message']}")
    elif event == "deferred":
        print(f"       z deferred: retry at t+{data['resume_at'] - CLOCK.now:.0f}s")
    elif event == "run.resume":
        print("       > resumed")


CLOCK = FakeClock()


def build_agents(onto: Ontology, approvals=None, faults: Faults | None = None):
    approver = AutoApprover(approvals or {}, default=True)
    common = dict(approver=approver, observer=printer, clock=CLOCK, sleep=lambda s: None)
    finance = WorkAgent("finance-agent", onto, finance_tools(), roles=["finance"], **common)
    return {
        "procurement": WorkAgent("procurement-agent", onto, procurement_tools(faults), roles=["procurement"],
                                 delegates=[finance], **common),
        "procurement-solo": WorkAgent("procurement-agent", onto, procurement_tools(faults), roles=["procurement"],
                                      **common),
        "production": WorkAgent("production-agent", onto, production_tools(faults), roles=["production"], **common),
        "quality": WorkAgent("quality-agent", onto, quality_tools(), roles=["quality"], **common),
    }


CASES = {
    "supplier_contract": {
        "Supplier": {"name": "Supplier Y", "country": "PL", "on_time_rate": 0.81},
        "Contract": {"value": 1_200_000, "end_date": "2027-12-31", "late_delivery_penalty": False, "revision": 0},
    },
    "late_supplier": {
        "Supplier": {"name": "Supplier Y", "on_time_rate": 0.81},
        "ProductionLine": {"code": "LYON-1", "alternate_available": True},
        "Order": {"quantity": 1500, "amount": 750_000, "line": "primary"},
    },
    "on_time_supplier": {
        "Supplier": {"name": "Supplier X", "on_time_rate": 0.97},
        "ProductionLine": {"code": "LYON-1", "alternate_available": True},
        "Order": {"quantity": 1000, "amount": 500_000, "line": "primary"},
    },
    "defect_high": {
        "Supplier": {"name": "Supplier X"},
        "Product": {"name": "Product B", "defect_rate": 0.031},
        "QualityCase": {"description": "housing cracks reported by customer", "reported_by": "field service"},
    },
    "defect_low": {
        "Supplier": {"name": "Supplier Z"},
        "Product": {"name": "Product C", "defect_rate": 0.004},
        "QualityCase": {"description": "cosmetic scratches", "reported_by": "line inspection"},
    },
}


def banner(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


def outcome(result) -> None:
    line = f"  => {result.status.upper()}"
    if result.escalation:
        line += f": {result.escalation.reason} (to {result.escalation.to})"
    print(line)
    for detail in (result.escalation.details if result.escalation else [])[:3]:
        print(f"       - {detail}")


# -- 1. ontology engineering --------------------------------------------------
def section_ontology(onto: Ontology) -> None:
    banner("1. ONTOLOGY ENGINEERING - modules, validation, lint, competency questions, export")
    print(f"{onto.ref} composed from modules {', '.join(onto.modules)}")
    print(f"{len(onto.entities)} entities, {len(onto.relationships)} relationships, {len(onto.actions)} actions, "
          f"{len(onto.rules)} rules, {len(onto.questions)} competency questions; fingerprint {onto.fingerprint[:12]}")
    print("\nLint:")
    findings = lint(onto, tools=_all_tools())
    for f in findings or ["  (clean)"]:
        print(f"  {f}")
    graph = KnowledgeGraph.from_dict(onto, json.loads((HERE / "data.json").read_text()))
    print(f"\nCompetency questions against sample data ({len(graph.instances())} instances):")
    for q, answer, ok in graph.check_competency():
        print(f"  {q.id} {q.question:<58} -> {answer}  {'OK' if ok else 'MISMATCH' if ok is False else ''}")
    print(f"\nOpen-standard export: JSON-LD {len(json.dumps(to_jsonld(onto)))} bytes, "
          f"OWL/Turtle {len(to_turtle(onto).splitlines())} lines")


def _all_tools():
    from autology import ToolRegistry

    merged = ToolRegistry()
    for reg in (procurement_tools(), finance_tools(), production_tools(), quality_tools()):
        for t in reg:
            merged.register(t.name, t.capability, t.handler, when=str(t.when) if t.when else None,
                            priority=t.priority, cost=t.cost)
    return merged


# -- 2. agents -------------------------------------------------------------------
def section_agents(onto: Ontology) -> list:
    banner("2. AGENT ORCHESTRATION - goal-oriented, context-aware, self-healing, delegating")
    results = []

    def scenario(title, agent, goal, case, case_id):
        print(f"\n--- {title}")
        res = agent.run(goal, copy.deepcopy(case), case_id)
        outcome(res)
        results.append(res)
        return res

    agents = build_agents(onto)
    scenario("ProcurementAgent: Supplier Y contract lacks a LateDeliveryPenalty clause (1.2M)",
             agents["procurement"], "contract_supplier", CASES["supplier_contract"], "PROC-1")
    scenario("ProcurementAgent without a FinanceAgent: may not set payment terms itself",
             agents["procurement-solo"], "contract_supplier", CASES["supplier_contract"], "PROC-2")
    agents = build_agents(onto, faults=Faults(clause_ai_down=True))
    scenario("Clause-checking model is down: fall back to (costly) outside counsel",
             agents["procurement"], "contract_supplier",
             {**CASES["supplier_contract"], "Contract": {**CASES["supplier_contract"]["Contract"],
                                                         "late_delivery_penalty": True, "value": 400_000}}, "PROC-3")
    agents = build_agents(onto)
    scenario("ProductionAgent: Supplier Y will deliver late -> reroute to alternate line",
             agents["production"], "fulfil_order", CASES["late_supplier"], "PROD-1")

    agents = build_agents(onto, faults=Faults(mes_down=1))
    res = scenario("ProductionAgent: MES down -> retry in 1 hour (defer), then resume",
                   agents["production"], "fulfil_order", CASES["on_time_supplier"], "PROD-2")
    results.pop()
    CLOCK.now += 3600
    res = agents["production"].resume(res)
    outcome(res)
    results.append(res)

    agents = build_agents(onto, faults=Faults(mes_down=5))
    res = scenario("ProductionAgent: MES stays down -> escalate to plant manager after 3 rounds",
                   agents["production"], "fulfil_order", CASES["on_time_supplier"], "PROD-3")
    results.pop()
    while res.status == "deferred":
        CLOCK.now += 3600
        res = agents["production"].resume(res)
    outcome(res)
    results.append(res)

    agents = build_agents(onto)
    scenario("QualityAgent: defect rate 3.1% -> trace, quarantine, ProductRecall, suspend supplier",
             agents["quality"], "resolve_quality_case", CASES["defect_high"], "QUAL-1")
    scenario("QualityAgent: defect rate 0.4% -> trace, quarantine, release",
             agents["quality"], "resolve_quality_case", CASES["defect_low"], "QUAL-2")

    class RushToSign:
        """A misbehaving reasoner (e.g. a jail-broken LLM) that always wants to sign immediately."""

        def propose(self, ctx):
            return Proposal("sign_supplier_contract", "sign now, paperwork later", "rogue-llm")

    rogue = WorkAgent("rogue-agent", onto, procurement_tools(), roles=["procurement"], reasoner=RushToSign(),
                      delegates=[build_agents(onto)["procurement"].delegates[0]], approver=AutoApprover(),
                      observer=printer)
    scenario("Rogue reasoner keeps proposing to sign: denied, then suspended after 3 violations",
             rogue, "contract_supplier", CASES["supplier_contract"], "PROC-ROGUE")
    return results


# -- 3. feedback loop & versioning -------------------------------------------------
def section_feedback(onto: Ontology) -> tuple:
    banner("3. FEEDBACK LOOP & VERSION CONTROL - PartialDelivery is not in the ontology")
    registry = OntologyRegistry()
    registry.publish(onto)
    agents = build_agents(onto, faults=Faults(partial_delivery=True))
    print("\n--- v1.0.0: supplier portal reports a partial delivery")
    res = agents["production"].run("fulfil_order", copy.deepcopy(CASES["on_time_supplier"]), "PROD-PARTIAL")
    outcome(res)
    for gap in ontology_gaps([res]):
        print(f"  gap: {gap.kind}: suggestion: {gap.suggestion}")

    doc = load_document(ENTERPRISE)
    doc["actions"]["check_material_supply"]["outcomes"]["partial_delivery"] = {
        "description": "only part of the material arrives on time - treat like a late delivery",
        "effects": {"Supplier": {"on_time": False}, "Order": {"status": "scheduled"}}}
    for version in ("1.0.1", "1.1.0"):
        doc["version"] = version
        candidate = Ontology.from_dict(doc)
        try:
            changes = registry.publish(candidate)
            print(f"\npublished {candidate.ref}: " + "; ".join(str(c) for c in changes))
            v11 = candidate
        except VersionError as exc:
            print(f"\nregistry refused {candidate.ref}: {exc}")
    broken = copy.deepcopy(doc)
    del broken["entities"]["Contract"]["attributes"]["payment_terms"]
    broken["version"] = "1.2.0"
    broken["rules"] = [r for r in broken["rules"] if r["id"] != "R-FIN-001"]
    broken["actions"]["set_payment_terms"]["writes"] = []
    print("breaking change preview (1.1.0 -> 1.2.0): "
          + "; ".join(str(c) for c in diff(v11, Ontology.from_dict(broken)) if c.level == "major"))

    pinned = build_agents(onto)["production"]
    pinned.registry, pinned.on_ontology_update = registry, "pause"
    print("\n--- agent pinned to v1.0.0 with on_ontology_update='pause' (v1.1.0 is now live)")
    outcome(pinned.run("fulfil_order", copy.deepcopy(CASES["on_time_supplier"]), "PROD-PINNED"))

    agents = build_agents(v11, faults=Faults(partial_delivery=True))
    print(f"\n--- {v11.ref}: same partial delivery, now modelled")
    res2 = agents["production"].run("fulfil_order", copy.deepcopy(CASES["on_time_supplier"]), "PROD-PARTIAL-2")
    outcome(res2)
    return res, res2


def simulate_pilot(onto: Ontology, n: int = 200, seed: int = 7) -> list:
    """Phase-1 pilot in a simulated environment: a seeded, representative month of supplier contracts.

    Mix (assumptions - tune to your data): 15% lack the penalty clause, 20% are worth >= 1M (CFO review,
    95% approved), 3% hit a clause-model outage (fallback to outside counsel).
    """
    rng = random.Random(seed)
    results = []
    for i in range(n):
        value = rng.choice([60_000, 150_000, 300_000, 650_000]) if rng.random() > 0.2 else rng.choice(
            [1_200_000, 2_500_000])
        case = {"Supplier": {"name": f"Supplier {i:03d}", "on_time_rate": 0.95},
                "Contract": {"value": value, "end_date": "2027-12-31", "revision": 0,
                             "late_delivery_penalty": rng.random() > 0.15}}
        faults = Faults(clause_ai_down=rng.random() < 0.03)
        cfo_ok = rng.random() < 0.95
        finance = WorkAgent("finance-agent", onto, finance_tools(), roles=["finance"])
        agent = WorkAgent("procurement-agent", onto, procurement_tools(faults), roles=["procurement"],
                          delegates=[finance], approver=AutoApprover({"sign_supplier_contract": cfo_ok}))
        results.append(agent.run("contract_supplier", case, f"PILOT-{i:03d}"))
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sections", nargs="*", default=[], help="ontology | agents | feedback | report | roi")
    parser.add_argument("--report", help="write the compliance report (markdown) to this file")
    args = parser.parse_args(argv)
    wanted = set(args.sections) or {"ontology", "agents", "feedback", "report", "roi"}
    onto = Ontology.load(ENTERPRISE)

    if "ontology" in wanted:
        section_ontology(onto)
    results = section_agents(onto) if wanted & {"agents", "report"} else []
    if "feedback" in wanted:
        section_feedback(onto)

    if "report" in wanted or args.report:
        banner("4. GOVERNANCE - compliance report")
        report = compliance_report(results, onto, "ACME manufacturing - agent compliance report")
        print(report)
        if args.report:
            Path(args.report).write_text(report, encoding="utf-8")
            print(f"(written to {args.report})")
    if "roi" in wanted:
        banner("5. COST OPTIMISATION - pilot simulation, TCO and ROI")
        pilot = simulate_pilot(onto)
        pm = metrics(pilot)
        print(f"Pilot: {pm.tasks} simulated supplier contracts -> success {pm.success_rate:.0%}, "
              f"straight-through {pm.straight_through_rate:.0%}, human touch {pm.human_intervention_rate:.0%} "
              f"({pm.reviews} reviews, hand-offs {pm.escalations or 'none'}), tool cost/task "
              f"{pm.tool_cost / pm.tasks:.2f}, agent latency {pm.avg_latency_ms:.1f} ms")
        model = from_metrics(TCOModel.load(HERE / "roi.json"), pm)
        print("\nROI = assumptions in roi.json + rates measured in the pilot:\n")
        print(evaluate(model).render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
