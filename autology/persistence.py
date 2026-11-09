"""Store and reload agent runs (JSON / JSONL), independent of the process or project that made them.

Saved runs carry the full audit trail (hash chain intact, so tampering in
storage is still detected), the steps, final state, escalation, costs and -
for deferred or paused runs - everything needed to :meth:`WorkAgent.resume`
them in another process. ``autology score --runs`` and ``autology report``
work from these files, so any deployment can be scored without Python glue.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .agent import Escalation, RunResult, RunState, StepRecord
from .audit import AuditLog
from .governance import Decision, Verdict
from .state import WorldState

FORMAT = "autology.run/1"


def _decision_to_dict(d: Decision) -> Dict[str, Any]:
    return {"verdict": d.verdict.value, "action": d.action, "reasons": list(d.reasons), "rule_ids": list(d.rule_ids),
            "reviewers": list(d.reviewers), "satisfied": list(d.satisfied), "facts": dict(d.facts)}


def _decision_from_dict(d: Dict[str, Any]) -> Decision:
    return Decision(Verdict(d["verdict"]), d["action"], list(d.get("reasons", [])), list(d.get("rule_ids", [])),
                    tuple(d.get("reviewers", ())), list(d.get("satisfied", [])), dict(d.get("facts", {})))


def result_to_dict(result: RunResult) -> Dict[str, Any]:
    run = result.run
    return {
        "format": FORMAT,
        "status": result.status, "goal": result.goal, "case_id": result.case_id,
        "steps": [dict(s.__dict__) for s in result.steps],
        "state": result.state.snapshot(),
        "escalation": dict(result.escalation.__dict__) if result.escalation else None,
        "violations": [_decision_to_dict(d) for d in result.violations],
        "costs": dict(result.costs), "resume_at": result.resume_at,
        "audit": result.audit.to_list(),
        "run": None if run is None else {
            "history": list(run.history), "attempts": dict(run.attempts), "failures": dict(run.failures),
            "ontology_ref": run.ontology_ref, "update_noticed": run.update_noticed,
        },
    }


def result_from_dict(data: Dict[str, Any]) -> RunResult:
    if data.get("format") != FORMAT:
        raise ValueError(f"not an Autology run record (format {data.get('format')!r}, expected {FORMAT!r})")
    snap = data["state"]
    state = WorldState(json.loads(json.dumps(snap["entities"])), snap.get("steps", {}))
    steps = [StepRecord(**s) for s in data.get("steps", [])]
    escalation = Escalation(**data["escalation"]) if data.get("escalation") else None
    violations = [_decision_from_dict(d) for d in data.get("violations", [])]
    costs = dict(data.get("costs", {}))
    audit = AuditLog.from_list(data.get("audit", []))
    run = None
    if data.get("run") is not None:
        r = data["run"]
        run = RunState(data["goal"], data["case_id"], state, steps, list(r.get("history", [])),
                       Counter(r.get("attempts", {})), Counter(r.get("failures", {})), violations,
                       costs, data.get("resume_at"), r.get("ontology_ref", ""), bool(r.get("update_noticed")))
    return RunResult(data["status"], data["goal"], data["case_id"], steps, state, audit, escalation, violations,
                     costs, data.get("resume_at"), run)


def save_runs(results: Iterable[RunResult], path: str | Path, append: bool = False) -> int:
    """Write runs as JSON Lines (one run per line). Returns the number written."""
    n = 0
    with open(path, "a" if append else "w", encoding="utf-8") as fh:
        for result in results:
            fh.write(json.dumps(result_to_dict(result), default=str) + "\n")
            n += 1
    return n


def load_runs(path: str | Path) -> List[RunResult]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if line.strip():
                try:
                    out.append(result_from_dict(json.loads(line)))
                except (ValueError, KeyError, TypeError) as exc:
                    raise ValueError(f"{path}:{line_no}: invalid run record: {exc}") from None
    return out
