"""Evaluation harness: test reasoners (models, prompts, routing) against expected agent behaviour.

A suite is a JSON file of cases with expectations. Every reasoner runs every case through a fresh,
fully governed agent, and the report compares them on the same footing::

    {
      "name": "order fulfilment",
      "ontology": "ontology.json", "tools": "tools.json", "goal": "fulfil_contract",
      "roles": ["ops", "eu_ops", "finance"], "approver": "auto",
      "reasoners": {"planner": "planner", "claude": "claude"},
      "prices": {"my-local-model": [0.2, 0.6]},     # optional, USD per million tokens (input, output)
      "cases": [
        {"id": "standard", "case_file": "case.json",
         "expect": {"status": "completed", "order": ["clear_hazmat@O-2", "ship_order@O-2"], "reviews": 2,
                    "final": ["all_of(Order.status in ['invoiced', 'cancelled'])"]}},
        {"id": "no finance role", "case_file": "case.json", "roles": ["ops"],
         "expect": {"status": "escalated", "escalation": "R-FIN-002"}}
      ]
    }

Expectations (all optional; the default is ``{"status": "completed"}``):

=================  =========================================================================
``status``         final status, or a list of acceptable statuses
``contains``       actions that must be executed (``ship_order@O-2`` or ``ship_order``)
``excludes``       actions that must not be executed
``order``          actions that must be executed in this relative order
``max_steps``      at most this many executed steps
``reviews``        exactly this many human reviews
``final``          conditions (the ontology expression language) that hold on the final state
``escalation``     text that must appear in the escalation reason or details
``max_fallbacks``  at most this many proposals where an LLM reasoner fell back to the planner
``max_cost_usd``   at most this much model spend
=================  =========================================================================

Metrics per reasoner: pass rate, steps, *agreement* (share of decisions equal to the planner's next
step), fallbacks, governance overrides, model calls, cost and latency. With ``repeats`` > 1 the report
adds *consistency*: the share of cases where every attempt gave the same pass/fail result and path.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from .expressions import compile_expression
from .ontology import Ontology, OntologyError

EXPECT_KEYS = {"status", "contains", "excludes", "order", "max_steps", "reviews", "final", "escalation",
               "max_fallbacks", "max_cost_usd"}


@dataclass
class EvalCase:
    id: str
    case: Dict[str, Any]
    expect: Dict[str, Any]
    goal: Optional[str] = None
    roles: Optional[List[str]] = None


@dataclass
class EvalSuite:
    name: str
    ontology: Ontology
    tools: Any
    goal: str
    cases: List[EvalCase]
    roles: List[str] = field(default_factory=list)
    approver: Any = None
    delegates: List[Dict[str, Any]] = field(default_factory=list)
    reasoners: Dict[str, Any] = field(default_factory=dict)
    repeats: int = 1
    base_dir: Path = Path(".")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    reasoner: str
    case_id: str
    attempt: int
    status: str
    checks: List[Check]
    steps: int
    path: List[str]
    agreement: float
    fallbacks: int
    overrides: int
    llm_calls: int
    cost_usd: float
    wall_ms: float
    escalation: Optional[str] = None

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def as_dict(self) -> Dict[str, Any]:
        out = dict(self.__dict__)
        out["checks"] = [c.__dict__ for c in self.checks]
        out["passed"] = self.passed
        return out


def load_suite(path: Union[str, Path]) -> EvalSuite:
    """Load a suite file; ``ontology``, ``tools``, ``case_file`` and approver policies are relative to it."""
    from .adapters import load_approver, load_tools

    p = Path(path).resolve()
    doc = json.loads(p.read_text(encoding="utf-8"))
    base = p.parent
    onto = Ontology.load(base / doc["ontology"])
    goal = doc.get("goal") or (next(iter(onto.goals)) if len(onto.goals) == 1 else None)
    if goal not in onto.goals:
        raise OntologyError(f"suite {p.name}: unknown goal {goal!r}")
    cases = []
    for i, spec in enumerate(doc.get("cases", [])):
        cid = str(spec.get("id") or f"case-{i + 1}")
        case = spec.get("case")
        if case is None and spec.get("case_file"):
            case = json.loads((base / spec["case_file"]).read_text(encoding="utf-8"))
        if not isinstance(case, dict):
            raise OntologyError(f"suite case {cid}: needs a case object or a case_file")
        expect = dict(spec.get("expect") or {"status": "completed"})
        unknown = set(expect) - EXPECT_KEYS
        if unknown:
            raise OntologyError(f"suite case {cid}: unknown expectations {sorted(unknown)}")
        for cond in expect.get("final", []):
            compile_expression(cond)  # fail at load time, not mid-run
        if spec.get("goal") and spec["goal"] not in onto.goals:
            raise OntologyError(f"suite case {cid}: unknown goal {spec['goal']!r}")
        cases.append(EvalCase(cid, case, expect, spec.get("goal"), spec.get("roles")))
    approver_spec = doc.get("approver", "auto")
    approver = load_approver(str(base / approver_spec) if str(approver_spec).endswith(".json") else approver_spec)
    from .reasoners import register_price

    for model, (price_in, price_out) in (doc.get("prices") or {}).items():  # USD per million tokens
        register_price(model, price_in, price_out)
    tools = load_tools(base / doc["tools"])
    delegates = [{"name": d["name"], "roles": d.get("roles", []), "tools": load_tools(base / d["tools"])}
                 for d in doc.get("delegates", [])]
    return EvalSuite(doc.get("name", p.stem), onto, tools, goal, cases, list(doc.get("roles", [])), approver,
                     delegates, dict(doc.get("reasoners") or {"planner": "planner"}), int(doc.get("repeats", 1)),
                     base)


def _make_reasoner(spec: Any, base: Path) -> Any:
    from .adapters import load_reasoner

    if isinstance(spec, str):
        return load_reasoner(spec, (str(base),))
    if hasattr(spec, "propose"):
        return spec
    if callable(spec):
        return spec()
    raise TypeError(f"cannot build a reasoner from {spec!r}")


def _matches(executed: Sequence[str], wanted: str) -> List[int]:
    return [i for i, a in enumerate(executed) if a == wanted or a.partition("@")[0] == wanted]


def check(expect: Mapping[str, Any], result: Any, metrics: Mapping[str, Any]) -> List[Check]:
    """Evaluate one run against its expectations."""
    executed = [s.action for s in result.steps if s.outcome]
    checks: List[Check] = []
    if "status" in expect:
        ok = result.status in (expect["status"] if isinstance(expect["status"], list) else [expect["status"]])
        checks.append(Check("status", ok, f"got {result.status}" + (
            f" ({result.escalation.reason})" if result.escalation and not ok else "")))
    for action in expect.get("contains", []):
        checks.append(Check(f"contains {action}", bool(_matches(executed, action)), "" if _matches(executed, action)
                            else "never executed"))
    for action in expect.get("excludes", []):
        hits = _matches(executed, action)
        checks.append(Check(f"excludes {action}", not hits, f"executed at step {hits[0] + 1}" if hits else ""))
    if expect.get("order"):
        positions, ok, detail = [], True, ""
        for action in expect["order"]:
            found = _matches(executed, action)
            if not found:
                ok, detail = False, f"{action} never executed"
                break
            positions.append(found[0])
        if ok and positions != sorted(positions):
            ok, detail = False, "executed as " + " -> ".join(a for _, a in sorted(zip(positions, expect["order"])))
        checks.append(Check("order " + " -> ".join(expect["order"]), ok, detail))
    if "max_steps" in expect:
        checks.append(Check(f"max_steps {expect['max_steps']}", len(executed) <= expect["max_steps"],
                            f"took {len(executed)}"))
    if "reviews" in expect:
        n = sum(1 for s in result.steps if s.reviewer)
        checks.append(Check(f"reviews {expect['reviews']}", n == expect["reviews"], f"got {n}"))
    for cond in expect.get("final", []):
        try:
            ok = bool(compile_expression(cond).evaluate(result.state.resolver()))
            detail = "" if ok else "does not hold on the final state"
        except Exception as exc:  # e.g. a type error on missing data: the expectation fails, the suite goes on
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        checks.append(Check(f"final {cond}", ok, detail))
    if "escalation" in expect:
        text = " ".join([result.escalation.reason] + list(result.escalation.details)) if result.escalation else ""
        checks.append(Check(f"escalation mentions {expect['escalation']!r}", expect["escalation"] in text,
                            text or "no escalation"))
    if "max_fallbacks" in expect:
        checks.append(Check(f"max_fallbacks {expect['max_fallbacks']}",
                            metrics["fallbacks"] <= expect["max_fallbacks"], f"got {metrics['fallbacks']}"))
    if "max_cost_usd" in expect:
        checks.append(Check(f"max_cost_usd {expect['max_cost_usd']}",
                            metrics["cost_usd"] <= expect["max_cost_usd"], f"spent {metrics['cost_usd']:.4f}"))
    return checks


def _metrics(result: Any) -> Dict[str, Any]:
    decisions, agree = 0, 0
    last_plan: Optional[List[str]] = None
    for entry in result.audit:
        if entry.event == "plan":
            last_plan = entry.data.get("plan")
        elif entry.event == "decision":
            decisions += 1
            if last_plan and entry.data.get("action") == last_plan[0]:
                agree += 1
    return {"agreement": round(agree / decisions, 4) if decisions else 1.0,
            "fallbacks": sum(1 for s in result.steps if "LLM fallback" in (s.rationale or "")),
            "overrides": sum(1 for s in result.steps if s.proposed_by == "override"),
            "llm_calls": int(result.costs.get("llm_calls", 0)),
            "cost_usd": round(float(result.costs.get("llm_usd", 0.0)), 6)}


def run_suite(suite: EvalSuite, reasoners: Optional[Mapping[str, Any]] = None, repeats: Optional[int] = None,
              observer: Optional[Callable[[CaseResult], None]] = None) -> "EvalReport":
    """Run every case with every reasoner (a fresh agent per run) and collect the results."""
    from .agent import WorkAgent

    specs = dict(reasoners or suite.reasoners)
    results: List[CaseResult] = []
    for name, spec in specs.items():
        for attempt in range(1, (repeats or suite.repeats) + 1):
            for case in suite.cases:
                reasoner = _make_reasoner(spec, suite.base_dir)
                delegates = [WorkAgent(d["name"], suite.ontology, d["tools"], roles=d["roles"])
                             for d in suite.delegates]
                agent = WorkAgent(f"eval-{name}", suite.ontology, suite.tools,
                                  roles=case.roles if case.roles is not None else suite.roles,
                                  delegates=delegates, reasoner=reasoner, approver=suite.approver,
                                  sleep=lambda s: None)
                started = time.perf_counter()
                result = agent.run(case.goal or suite.goal, json.loads(json.dumps(case.case)), case.id)
                wall = (time.perf_counter() - started) * 1000
                m = _metrics(result)
                if isinstance(getattr(reasoner, "calls", None), int):  # LLMReasoner counts every model call
                    m["llm_calls"] = reasoner.calls
                cr = CaseResult(name, case.id, attempt, result.status, check(case.expect, result, m),
                                len([s for s in result.steps if s.outcome]), result.path, m["agreement"],
                                m["fallbacks"], m["overrides"], m["llm_calls"], m["cost_usd"], round(wall, 1),
                                result.escalation.reason if result.escalation else None)
                results.append(cr)
                if observer:
                    observer(cr)
    return EvalReport(suite.name, list(specs), results)


@dataclass
class EvalReport:
    suite: str
    reasoners: List[str]
    results: List[CaseResult]

    def for_reasoner(self, name: str) -> List[CaseResult]:
        return [r for r in self.results if r.reasoner == name]

    def summary(self) -> Dict[str, Dict[str, Any]]:
        out = {}
        for name in self.reasoners:
            rs = self.for_reasoner(name)
            walls = sorted(r.wall_ms for r in rs)
            by_case: Dict[str, List[CaseResult]] = {}
            for r in rs:
                by_case.setdefault(r.case_id, []).append(r)
            consistent = sum(1 for attempts in by_case.values()
                             if len({(a.passed, tuple(a.path)) for a in attempts}) == 1)
            out[name] = {
                "runs": len(rs),
                "passed": sum(r.passed for r in rs),
                "pass_rate": round(sum(r.passed for r in rs) / len(rs), 4) if rs else 0.0,
                "mean_steps": round(statistics.mean(r.steps for r in rs), 2) if rs else 0.0,
                "agreement": round(statistics.mean(r.agreement for r in rs), 4) if rs else 0.0,
                "fallbacks": sum(r.fallbacks for r in rs),
                "overrides": sum(r.overrides for r in rs),
                "llm_calls": sum(r.llm_calls for r in rs),
                "cost_usd": round(sum(r.cost_usd for r in rs), 6),
                "p50_ms": walls[len(walls) // 2] if walls else 0.0,
                "p95_ms": walls[min(len(walls) - 1, int(len(walls) * 0.95))] if walls else 0.0,
                "consistency": round(consistent / len(by_case), 4) if by_case else 1.0,
            }
        return out

    def failures(self) -> Dict[str, List[Dict[str, Any]]]:
        """Failed checks grouped by check name: the failure analysis."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in self.results:
            for c in r.checks:
                if not c.passed:
                    out.setdefault(c.name, []).append({"reasoner": r.reasoner, "case": r.case_id,
                                                       "attempt": r.attempt, "detail": c.detail})
        return out

    def as_dict(self) -> Dict[str, Any]:
        return {"suite": self.suite, "summary": self.summary(), "failures": self.failures(),
                "results": [r.as_dict() for r in self.results]}

    def render(self) -> str:
        s = self.summary()
        lines = [f"# Evaluation: {self.suite}", "",
                 "| Reasoner | Pass rate | Passed | Mean steps | Agreement | Fallbacks | Overrides | Model calls "
                 "| Cost (USD) | p50 ms | Consistency |",
                 "|---|---|---|---|---|---|---|---|---|---|---|"]
        for name, m in s.items():
            lines.append(f"| {name} | {m['pass_rate']:.0%} | {m['passed']}/{m['runs']} | {m['mean_steps']} "
                         f"| {m['agreement']:.0%} | {m['fallbacks']} | {m['overrides']} | {m['llm_calls']} "
                         f"| {m['cost_usd']:.4f} | {m['p50_ms']:.0f} | {m['consistency']:.0%} |")
        lines += ["", "## Cases", "", "| Case | " + " | ".join(self.reasoners) + " |",
                  "|---|" + "---|" * len(self.reasoners)]
        for cid in dict.fromkeys(r.case_id for r in self.results):
            cells = []
            for name in self.reasoners:
                rs = [r for r in self.results if r.reasoner == name and r.case_id == cid]
                ok = sum(r.passed for r in rs)
                cells.append(("pass" if ok == len(rs) else "FAIL") + (f" {ok}/{len(rs)}" if len(rs) > 1 else ""))
            lines.append(f"| {cid} | " + " | ".join(cells) + " |")
        fails = self.failures()
        if fails:
            lines += ["", "## Failures", ""]
            for name, items in fails.items():
                lines.append(f"- **{name}** ({len(items)})")
                for it in items[:5]:
                    lines.append(f"  - {it['reasoner']} / {it['case']}: {it['detail']}")
                if len(items) > 5:
                    lines.append(f"  - and {len(items) - 5} more")
        return "\n".join(lines) + "\n"
