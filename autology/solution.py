"""A use case's executable configuration, as Studio edits it: agents, simulated tools and sample records.

Until now an engine's agents and tools were files an operator wrote. A **solution** is the same configuration in
a form a person can edit in Studio and the engine can check before anything is saved:

    {"agents": {"<name>": {"purpose": ..., "responsibilities": [...], "roles": [...], "goals": [...],
                           "autonomy": {"mode": "policy"} | {"mode": "supervised", "reviewer": role, "actions": [...]},
                           "tools": [{"action": name, "tool": "<catalogue id>", ...}]}},
     "sample_data": {"instances": [...], "links": [[source, relationship, target], ...]}}

This module is pure (no store, no engine): it validates a solution against a model document, compiles it into the
engine's own agent configuration, and explains what each agent may do. It adds no authority of its own:

* **What an agent may do** is still decided by the model's rules and by governance at run time. An agent performs
  an action only if it has a tool for the action's capability; assigning a tool is how an action is permitted.
  Roles are names the rules refer to; holding one grants nothing the rules do not say.
* **Autonomy can only be narrowed here.** ``policy`` leaves the decision to the model's rules (a person where a
  ``human_review`` rule asks for one, the agent otherwise). ``supervised`` adds reviews by a named role; it never
  removes one.
* **Tools come from a small approved catalogue, all simulated** (:data:`CATALOG`): they are compiled to decision
  tables, which reach no outside system. Connectors and model reasoners are listed as unavailable; nothing here can
  enable one.
* **Sample records are synthetic** and are loaded only into an empty store (see :mod:`autology.platform`).

Extension point: the catalogue is a mapping of entries with a ``compile`` rule. A future plugin runtime could
contribute entries, but only the engine validates and compiles them.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .expressions import compile_expression
from .graph import KnowledgeGraph
from .ontology import Ontology, OntologyError

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")
MAX_AGENTS, MAX_ROWS, MAX_INSTANCES, MAX_TEXT = 12, 20, 200, 500
AUTONOMY_MODES = ("policy", "supervised")
ACCESS_KINDS = ("action_access", "data_access", "write_access", "row_access")

# The approved catalogue. ``available`` False: shown so that people see what exists and why it cannot be assigned.
CATALOG: Dict[str, Dict[str, Any]] = {
    "simulated.succeed": {
        "name": "Simulated: completes the action", "environment": "simulated", "available": True,
        "description": "Answers with the action's expected outcome (or the one chosen). Nothing outside Autology "
                       "is contacted; only the state changes the action itself declares happen.",
        "parameters": ["outcome", "message"]},
    "simulated.decision_table": {
        "name": "Simulated: decision table", "environment": "simulated", "available": True,
        "description": "Answers from rows you write: a condition on the case, an outcome, values for the fields "
                       "the action may write. The first matching row wins. Nothing outside Autology is contacted.",
        "parameters": ["rows"]},
    "simulated.fail": {
        "name": "Simulated: fails on purpose", "environment": "simulated", "available": True,
        "description": "Fails with the message you give, always or when a condition holds: for rehearsing what "
                       "the solution does when a system is down.",
        "parameters": ["error", "when"]},
    "connector.http": {
        "name": "Connector to another system (HTTP)", "environment": "sandbox or production", "available": False,
        "description": "Calls a real system. Not available from Studio: connectors are configured by an operator "
                       "and gated by the use case's stage."},
    "connector.code": {
        "name": "Custom code tool", "environment": "production", "available": False,
        "description": "Runs code inside the engine. Not available from Studio."},
    "model.reasoner": {
        "name": "Language model choosing among valid actions", "environment": "external provider", "available": False,
        "description": "Blocked until the owner approves a provider and the data it may receive (D7, D10)."},
}


class SolutionError(ValueError):
    """A solution that cannot be compiled; ``problems`` lists every reason."""

    def __init__(self, problems: List[Dict[str, str]]):
        super().__init__("; ".join(p["message"] for p in problems[:5]))
        self.problems = problems


def catalog() -> List[Dict[str, Any]]:
    return [{"id": key, **entry} for key, entry in CATALOG.items()]


def _effects(action: Any) -> List[str]:
    return sorted({f"{e}.{a}" for o in action.outcomes for e, changes in o.effects.items() for a in changes})


def _expression(text: Any, onto: Ontology, where: str, problems: List[Dict[str, str]]) -> None:
    if not isinstance(text, str) or not text.strip():
        problems.append({"path": where, "message": "a condition such as Order.amount > 100"})
        return
    try:
        expr = compile_expression(text)
    except Exception as exc:  # the expression compiler raises its own errors: all mean "not an expression"
        problems.append({"path": where, "message": f"not a valid condition: {exc}"})
        return
    for entity, attribute in expr.references:
        etype = onto.entities.get(entity)
        if etype is None or not etype.has_attribute(attribute):
            problems.append({"path": where, "message": f"the model has no {entity}.{attribute}"})


def _rows(agent: str, action: Any, spec: Mapping[str, Any], onto: Ontology, where: str,
          problems: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """The decision-table rows a catalogue tool compiles to (every tool is a table: it reaches nothing)."""
    kind, outcomes = spec.get("tool"), [o.name for o in action.outcomes]

    def outcome_ok(value: Any, at: str) -> None:
        if value is not None and value not in outcomes:
            problems.append({"path": at, "message": f"{action.name} has the outcomes {outcomes}, not {value!r}"})

    note = "simulated: no other system was contacted"
    if kind == "simulated.succeed":
        outcome_ok(spec.get("outcome"), f"{where}.outcome")
        return [{"outcome": spec.get("outcome"), "message": str(spec.get("message") or note)[:MAX_TEXT]}]
    if kind == "simulated.fail":
        error = str(spec.get("error") or "simulated failure")[:MAX_TEXT]
        if spec.get("when") is None:
            return [{"error": error}]
        _expression(spec["when"], onto, f"{where}.when", problems)
        return [{"when": spec["when"], "error": error}, {"message": note}]
    rows = spec.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS or not all(isinstance(r, Mapping) for r in rows):
        problems.append({"path": f"{where}.rows", "message": f"1 to {MAX_ROWS} rows"})
        return []
    out = []
    for i, row in enumerate(rows):
        at = f"{where}.rows[{i}]"
        extra = sorted(set(row) - {"when", "outcome", "updates", "message"})
        if extra:
            problems.append({"path": at, "message": f"unknown keys {extra}"})
        if row.get("when") is not None:
            _expression(row["when"], onto, f"{at}.when", problems)
        outcome_ok(row.get("outcome"), f"{at}.outcome")
        updates = row.get("updates") or {}
        if not isinstance(updates, Mapping) or not all(isinstance(v, Mapping) for v in updates.values()):
            problems.append({"path": f"{at}.updates", "message": "{entity: {attribute: value}}"})
            updates = {}
        for entity, changes in updates.items():
            for attribute in changes:
                if f"{entity}.{attribute}" not in action.writes:
                    problems.append({"path": f"{at}.updates", "message":
                                     f"{action.name} may write {list(action.writes) or 'no field'}, not "
                                     f"{entity}.{attribute}"})
        out.append({k: row[k] for k in ("when", "outcome", "updates") if row.get(k) is not None}
                   | {"message": str(row.get("message") or note)[:MAX_TEXT]})
    return out


def check(solution: Any, document: Any) -> Tuple[List[Dict[str, str]], Optional[Dict[str, Any]]]:
    """``(problems, compiled)``: what is wrong with ``solution`` for the model ``document``, and, when nothing is,
    the engine's configuration for it: ``{"agents": {...}, "data": {...} or None}``."""
    problems: List[Dict[str, str]] = []

    def bad(path: str, message: str) -> None:
        problems.append({"path": path, "message": message})

    try:
        onto = Ontology.from_dict(dict(document)) if isinstance(document, Mapping) else None
    except OntologyError as exc:
        onto = None
        bad("model", f"the model does not validate: {exc}")
    if onto is None:
        if not problems:
            bad("model", "a model document is needed to check a configuration")
        return problems, None
    if not isinstance(solution, Mapping) or set(solution) - {"agents", "sample_data"}:
        bad("", "a configuration is {\"agents\": {...}, \"sample_data\": {...}}")
        return problems, None
    agents = solution.get("agents") or {}
    if not isinstance(agents, Mapping) or len(agents) > MAX_AGENTS:
        bad("agents", f"at most {MAX_AGENTS} agents, by name")
        return problems, None
    compiled: Dict[str, Any] = {}
    for name, spec in agents.items():
        where = f"agents.{name}"
        if not NAME.match(str(name)) or not isinstance(spec, Mapping):
            bad(where, "an agent has a simple name (letters, digits, _ or -) and a configuration")
            continue
        extra = sorted(set(spec) - {"purpose", "responsibilities", "roles", "goals", "autonomy", "tools"})
        if extra:
            bad(where, f"unknown keys {extra}")
        roles, goals = spec.get("roles") or [], spec.get("goals") or []
        if not isinstance(roles, list) or not all(isinstance(r, str) and NAME.match(r) for r in roles):
            bad(f"{where}.roles", "a list of role names")
            roles = []
        if not isinstance(goals, list) or not goals:
            bad(f"{where}.goals", f"at least one goal the agent pursues, among {sorted(onto.goals)}")
            goals = []
        for goal in goals:
            if goal not in onto.goals:
                bad(f"{where}.goals", f"the model has no goal {goal!r}")
        duties = spec.get("responsibilities") or []
        if not isinstance(duties, list) or not all(isinstance(d, str) for d in duties) or len(duties) > 20:
            bad(f"{where}.responsibilities", "a list of short sentences")
            duties = []
        autonomy = spec.get("autonomy") or {"mode": "policy"}
        tools = spec.get("tools") or []
        if not isinstance(tools, list) or not all(isinstance(t, Mapping) for t in tools):
            bad(f"{where}.tools", "a list of {\"action\": ..., \"tool\": catalogue id}")
            tools = []
        table, seen = [], set()
        for i, tool in enumerate(tools):
            at = f"{where}.tools[{i}]"
            action = onto.actions.get(str(tool.get("action")))
            entry = CATALOG.get(str(tool.get("tool")))
            if action is None:
                bad(at, f"the model has no action {tool.get('action')!r}")
                continue
            if entry is None:
                bad(at, f"unknown tool {tool.get('tool')!r}: choose one from the catalogue")
                continue
            if not entry["available"]:
                bad(at, f"{tool['tool']} is not available from Studio: {entry['description']}")
                continue
            unknown = sorted(set(tool) - {"action", "tool"} - set(entry["parameters"]))
            if unknown:
                bad(at, f"{tool['tool']} has no parameter {unknown}")
            if action.name in seen:
                bad(at, f"{action.name} already has a tool in this agent")
                continue
            seen.add(action.name)
            table.append({"name": f"{name}.{action.name}", "capability": action.capability, "type": "table",
                          "description": f"{entry['name']} ({tool['tool']})",
                          "rows": _rows(str(name), action, tool, onto, at, problems)})
        _autonomy(autonomy, seen, f"{where}.autonomy", problems)
        compiled[str(name)] = {"managed": "studio", "purpose": str(spec.get("purpose") or "")[:MAX_TEXT],
                               "responsibilities": [d[:MAX_TEXT] for d in duties], "roles": sorted(set(roles)),
                               "goals": list(goals), "approver": "inbox",
                               "autonomy": dict(autonomy) if isinstance(autonomy, Mapping) else {"mode": "policy"},
                               "tools": {"tools": table}}
    data = solution.get("sample_data")
    if data is not None:
        _sample(data, onto, problems)
    if problems:
        return problems, None
    return [], {"agents": compiled, "data": dict(data) if data else None}


def _autonomy(spec: Any, assigned: set, where: str, problems: List[Dict[str, str]]) -> None:
    if not isinstance(spec, Mapping) or spec.get("mode") not in AUTONOMY_MODES \
            or set(spec) - {"mode", "reviewer", "actions"}:
        problems.append({"path": where, "message": "{\"mode\": \"policy\"} or {\"mode\": \"supervised\", "
                                                   "\"reviewer\": role, \"actions\": [...]}"})
        return
    if spec["mode"] == "policy":
        if set(spec) - {"mode"}:
            problems.append({"path": where, "message": "policy takes no reviewer: the model's rules decide"})
        return
    if not isinstance(spec.get("reviewer"), str) or not NAME.match(spec["reviewer"]):
        problems.append({"path": where, "message": "supervised needs the reviewer role that decides"})
    actions = spec.get("actions")
    if actions is not None and (not isinstance(actions, list) or set(actions) - assigned):
        problems.append({"path": f"{where}.actions", "message": "actions this agent has a tool for"})


def _sample(data: Any, onto: Ontology, problems: List[Dict[str, str]]) -> None:
    if not isinstance(data, Mapping) or set(data) - {"instances", "links"} \
            or not isinstance(data.get("instances", []), list) or not isinstance(data.get("links", []), list):
        problems.append({"path": "sample_data", "message": "{\"instances\": [...], \"links\": [[source, relationship, "
                                                           "target], ...]}"})
        return
    if len(data.get("instances", [])) > MAX_INSTANCES:
        problems.append({"path": "sample_data", "message": f"at most {MAX_INSTANCES} sample records"})
        return
    try:
        KnowledgeGraph.from_dict(onto, {"instances": [dict(i) for i in data.get("instances", [])],
                                        "links": [tuple(link) for link in data.get("links", [])]})
    except (OntologyError, KeyError, TypeError, ValueError) as exc:
        problems.append({"path": "sample_data", "message": f"the sample records do not fit the model: {exc}"})


def compile_solution(solution: Any, document: Any) -> Dict[str, Any]:
    problems, compiled = check(solution, document)
    if compiled is None:
        raise SolutionError(problems)
    return compiled


# -- what each agent may do, in the model's own terms -----------------------------------------------------------
def effective_permissions(solution: Any, document: Any) -> Dict[str, List[Dict[str, Any]]]:
    """For each agent and each action of the model: whether the agent can perform it, and under which conditions.
    A static reading of the configuration and the rules; governance decides each case when a run reaches it."""
    try:
        onto = Ontology.from_dict(dict(document))
    except (OntologyError, TypeError, ValueError):
        return {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    agents = solution.get("agents") if isinstance(solution, Mapping) else None
    for name, spec in (agents if isinstance(agents, Mapping) else {}).items():
        if not isinstance(spec, Mapping):
            continue
        roles = set(spec.get("roles") or [])
        tools = {str(t.get("action")): str(t.get("tool")) for t in spec.get("tools") or [] if isinstance(t, Mapping)}
        autonomy: Mapping[str, Any] = spec["autonomy"] if isinstance(spec.get("autonomy"), Mapping) else {"mode": "policy"}
        rows = []
        for action in onto.actions.values():
            written = set(action.writes) | set(_effects(action))
            refused: List[str] = []
            conditions: List[str] = []
            reviews: List[Dict[str, Any]] = []
            for rule in onto.rules:
                p, when = rule.params, (f" when {rule.when}" if rule.when is not None else "")
                if rule.kind == "action_access" and p["action"] == action.name and not roles & set(p["roles"]):
                    (conditions if when else refused).append(
                        f"{rule.id}: only {', '.join(p['roles'])} may perform it{when}")
                elif rule.kind == "write_access" and p["field"] in written and not roles & set(p["roles"]):
                    (conditions if when else refused).append(
                        f"{rule.id}: only {', '.join(p['roles'])} may change {p['field']}{when}")
                elif rule.kind == "prohibition" and p["action"] == action.name:
                    (conditions if when else refused).append(f"{rule.id}: prohibited{when}")
                elif rule.kind == "human_review" and p["action"] == action.name:
                    reviews.append({"reviewer": p["reviewer"], "when": str(rule.when) if rule.when is not None else None,
                                    "rule": rule.id})
            for ref in sorted(written & onto.critical_fields):
                if not any(r.params["field"] == ref and roles & set(r.params["roles"])
                           for r in onto.rules_of("write_access")):
                    refused.append(f"{ref} is decision-critical and no rule names one of this agent's roles")
            if autonomy.get("mode") == "supervised" and action.name in tools and (
                    action.name in (autonomy.get("actions") or []) or
                    (autonomy.get("actions") is None and action.side_effect != "none")):
                reviews.append({"reviewer": autonomy.get("reviewer"), "when": None, "rule": "agent autonomy"})
            if action.name not in tools:
                status = "not_assigned"
            elif refused:
                status = "refused"
            elif any(r["when"] is None for r in reviews):
                status = "review_required"
            elif reviews or conditions:
                status = "conditional"
            else:
                status = "autonomous"
            rows.append({"action": action.name, "status": status, "tool": tools.get(action.name),
                         "simulated": action.name in tools, "side_effect": action.side_effect,
                         "refused": refused, "conditions": conditions, "reviews": reviews})
        out[str(name)] = rows
    return out


# -- a starting point -------------------------------------------------------------------------------------------
def suggest(document: Any, sample: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """A plain starting configuration for a model: one agent holding the roles the access rules name, pursuing
    every goal, with a ``simulated.succeed`` tool for each action, and one sample case along the first case
    template. A person edits it; the engine validates whatever is saved."""
    onto = Ontology.from_dict(dict(document))
    roles = sorted({role for rule in onto.rules if rule.kind in ACCESS_KINDS for role in rule.params["roles"]})
    agent = {"purpose": "Pursues the model's goals within its rules", "responsibilities": [],
             "roles": roles, "goals": sorted(onto.goals), "autonomy": {"mode": "policy"},
             "tools": [{"action": name, "tool": "simulated.succeed"} for name in sorted(onto.actions)]}
    out: Dict[str, Any] = {"agents": {"solution_agent": agent} if onto.actions and onto.goals else {}}
    template = next(iter(onto.case_templates.values()), None)
    if template is not None and sample is not None:
        instances, links = [], []
        ids = {entity: f"{entity.upper()[:8]}-1" for entity in template.entities}
        for entity, steps in template.entities.items():
            if entity not in sample or len(steps) > 1:
                continue
            instances.append({"type": entity, "id": ids[entity], **dict(sample[entity])})
            if len(steps) == 1:
                step = steps[0]
                links.append([ids[entity], step[1:], ids[template.root]] if step.startswith("^")
                             else [ids[template.root], step, ids[entity]])
        out["sample_data"] = {"instances": instances, "links": links}
    return out


def changes(active: Any, draft: Any) -> List[Dict[str, Any]]:
    """What differs between two solutions (the running one and a draft), for review before release."""
    a = dict((active or {}).get("agents") or {}) if isinstance(active, Mapping) else {}
    d = dict((draft or {}).get("agents") or {}) if isinstance(draft, Mapping) else {}
    out: List[Dict[str, Any]] = []
    for name in sorted(set(a) | set(d)):
        if name not in a:
            out.append({"kind": "agent", "name": name, "change": "added", "fields": []})
        elif name not in d:
            out.append({"kind": "agent", "name": name, "change": "removed", "fields": []})
        elif a[name] != d[name]:
            fields = sorted(k for k in set(a[name]) | set(d[name]) if a[name].get(k) != d[name].get(k))
            out.append({"kind": "agent", "name": name, "change": "changed", "fields": fields})
    before = (active or {}).get("sample_data") if isinstance(active, Mapping) else None
    after = (draft or {}).get("sample_data") if isinstance(draft, Mapping) else None
    if before != after:
        out.append({"kind": "sample_data", "name": "sample records",
                    "change": "added" if before is None else "removed" if after is None else "changed", "fields": []})
    return out
