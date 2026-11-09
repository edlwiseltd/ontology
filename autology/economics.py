"""Total cost of ownership and ROI for an Autology deployment (methodology section 4).

The model has three cost layers - ontology (build + maintain), agents (LLM
inference, tools, integration) and operations (residual human work) - and
compares them with the manual baseline. Measured figures from real runs
(intervention rate, LLM and tool cost per task) can be plugged in with
:func:`from_metrics`, so ROI is computed from evidence, not assumptions.

All money values share one currency; figures you feed in are estimates
unless they come from :func:`autology.reporting.metrics`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TCOModel:
    # ontology layer
    ontology_development: float = 0.0  # one-off
    ontology_maintenance_per_year: float = 0.0
    # agent layer
    integration: float = 0.0  # one-off: APIs, connectors, testing
    platform_per_year: float = 0.0  # hosting, graph DB, observability
    llm_cost_per_task: float = 0.0
    tool_cost_per_task: float = 0.0
    # operations
    tasks_per_month: float = 0.0
    manual_hours_per_task: float = 0.0  # baseline: fully manual effort per task
    hourly_rate: float = 0.0
    intervention_rate: float = 0.0  # share of tasks that still need a human
    human_hours_per_intervention: float = 0.0
    horizon_years: int = 3

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TCOModel":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known - {"notes"}
        if unknown:
            raise ValueError(f"unknown TCO fields: {sorted(unknown)}")
        return cls(**{k: v for k, v in data.items() if k in known})

    @classmethod
    def load(cls, path: str) -> "TCOModel":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


@dataclass(frozen=True)
class ROIReport:
    tasks_per_year: float
    baseline_cost_per_year: float
    autology_run_cost_per_year: float  # inference + tools + residual human work + maintenance + platform
    one_off_investment: float
    net_savings_per_year: float
    total_cost_over_horizon: float
    total_savings_over_horizon: float
    roi: float  # (savings - cost) / cost over the horizon
    payback_months: Optional[float]
    human_hours_saved_per_year: float
    breakdown: Dict[str, float]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        b = self.breakdown
        rows = [
            ("Tasks per year", f"{self.tasks_per_year:,.0f}"),
            ("Manual baseline cost / year", f"{self.baseline_cost_per_year:,.0f}"),
            ("  LLM inference / year", f"{b['llm']:,.0f}"),
            ("  Tool calls / year", f"{b['tools']:,.0f}"),
            ("  Residual human work / year", f"{b['human']:,.0f}"),
            ("  Ontology maintenance / year", f"{b['maintenance']:,.0f}"),
            ("  Platform / year", f"{b['platform']:,.0f}"),
            ("Autology run cost / year", f"{self.autology_run_cost_per_year:,.0f}"),
            ("One-off investment (ontology + integration)", f"{self.one_off_investment:,.0f}"),
            ("Net savings / year", f"{self.net_savings_per_year:,.0f}"),
            ("Human hours saved / year", f"{self.human_hours_saved_per_year:,.0f}"),
            ("ROI over horizon", f"{self.roi:.0%}"),
            ("Payback", f"{self.payback_months:.1f} months" if self.payback_months is not None else "never"),
        ]
        width = max(len(r[0]) for r in rows)
        return "\n".join(f"{k.ljust(width)}  {v}" for k, v in rows)


def evaluate(m: TCOModel) -> ROIReport:
    tasks = m.tasks_per_month * 12
    baseline = tasks * m.manual_hours_per_task * m.hourly_rate
    human_hours = tasks * m.intervention_rate * m.human_hours_per_intervention
    breakdown = {
        "llm": tasks * m.llm_cost_per_task,
        "tools": tasks * m.tool_cost_per_task,
        "human": human_hours * m.hourly_rate,
        "maintenance": m.ontology_maintenance_per_year,
        "platform": m.platform_per_year,
    }
    run_cost = sum(breakdown.values())
    one_off = m.ontology_development + m.integration
    net = baseline - run_cost
    total_cost = one_off + m.horizon_years * run_cost
    total_savings = m.horizon_years * baseline  # avoided manual cost
    roi = (total_savings - total_cost) / total_cost if total_cost else 0.0
    payback = (one_off / (net / 12)) if net > 0 else None
    return ROIReport(tasks, baseline, run_cost, one_off, net, total_cost, total_savings, roi, payback,
                     tasks * m.manual_hours_per_task - human_hours, breakdown)


def from_metrics(model: TCOModel, measured) -> TCOModel:
    """Replace assumptions with values measured from runs (see :func:`autology.reporting.metrics`).

    The intervention rate and tool cost per task are always taken from the runs; the LLM cost per
    task only when the runs actually called a model (deterministic runs keep the assumed figure).
    """
    if not measured.tasks:
        return model
    llm = measured.llm_cost_usd / measured.tasks if measured.llm_calls else model.llm_cost_per_task
    return replace(model, intervention_rate=measured.human_intervention_rate, llm_cost_per_task=llm,
                   tool_cost_per_task=measured.tool_cost / measured.tasks)
