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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

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
        table = _by_capability(str(name), table, f"{where}.tools", problems)
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


def _by_capability(agent: str, table: List[Dict[str, Any]], where: str,
                   problems: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """One tool per capability. A person assigns a tool to each action, but the engine chooses a tool by the
    action's *capability*: when a model gives several actions one capability, they are served by one tool. If
    they were given the same simulated behaviour, that one tool is declared under the capability's name (so a
    run's record does not name a tool after another action); if not, the configuration is refused, because one
    of the actions would silently get the other's behaviour."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for tool in table:
        groups.setdefault(tool["capability"], []).append(tool)
    out: List[Dict[str, Any]] = []
    for tool in table:
        group = groups[tool["capability"]]
        if len(group) == 1:
            out.append(tool)
            continue
        actions = [g["name"].split(".", 1)[1] for g in group]
        if any(g["rows"] != group[0]["rows"] or g["description"] != group[0]["description"] for g in group):
            if tool is group[0]:
                problems.append({"path": where, "message": (
                    f"{', '.join(actions)} share the capability {tool['capability']!r}, and the engine chooses a "
                    "tool by capability: give them the same tool, or give the actions different capabilities in "
                    "the model")})
            continue
        if tool is group[0]:
            out.append({**tool, "name": f"{agent}.{tool['capability']}",
                        "description": f"{tool['description']} for {', '.join(actions)}"})
    return out


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


# -- a release as a whole ---------------------------------------------------------------------------------------
def _part(container: Any, key: str) -> Mapping[str, Any]:
    value = container.get(key) if isinstance(container, Mapping) else None
    return value if isinstance(value, Mapping) else {}


def release_problems(snapshot: Any) -> List[str]:
    """Why the configuration in a release snapshot could not execute coherently. Computed from the snapshot alone,
    so anyone holding a release can verify it; the platform refuses to activate a release that has any.

    A release is coherent when its model loads, every agent pursues goals of that model and has tools that serve
    its actions, a Studio-managed configuration compiles to exactly the agents in the release, and a model that
    has work to do (goals and actions) has an agent to do it."""
    if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("ontology"), Mapping):
        return ["the release has no model document"]
    try:
        onto = Ontology.from_dict(dict(snapshot["ontology"]))
    except OntologyError as exc:
        return [f"the release's model does not validate: {exc}"]
    settings, agents, declared = _part(snapshot, "settings"), _part(_part(snapshot, "settings"), "agents"), _part(snapshot, "tools")
    out: List[str] = []
    managed = settings.get("solution")
    if managed is not None:
        problems, compiled = check(managed, snapshot["ontology"])
        out += [f"agent and tool configuration, {p['path'] or 'configuration'}: {p['message']}" for p in problems]
        if compiled is not None and compiled["agents"] != agents:
            out.append("the agents in the release are not the ones its agent and tool configuration compiles to")
    if not agents and onto.goals and onto.actions:
        out.append("the model has goals and actions but no agent is configured: nothing could run")
    capabilities = {a.capability for a in onto.actions.values()}
    for name, spec in sorted(agents.items()):
        if not isinstance(spec, Mapping):
            out.append(f"agent {name}: not a configuration")
            continue
        for goal in spec.get("goals") or []:
            if goal not in onto.goals:
                out.append(f"agent {name} pursues the goal {goal!r}, which the release's model does not have")
        tools = declared.get(name)
        if not isinstance(tools, Mapping) or "unreadable" in tools:
            out.append(f"agent {name} has no readable tool declaration")
            continue
        if tools.get("registries"):  # tools built by code: their capabilities are known only when loaded
            continue
        served = {t.get("capability") for t in tools.get("tools") or [] if isinstance(t, Mapping)}
        if not served:
            out.append(f"agent {name} has no tool: it could perform no action")
        elif capabilities and not served & capabilities:
            out.append(f"none of agent {name}'s tools serves an action of the release's model")
    return out


def release_components(snapshot: Any) -> Dict[str, Any]:
    """What a release contains, part by part, each with its own fingerprint: the model, its rules, its action
    definitions, its workflows (case templates and automations), the agents, the tool declarations and the
    governing settings. Two releases share a part exactly when the part's fingerprint is the same."""
    import hashlib
    import json

    def mark(value: Any) -> str:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    snap: Mapping[str, Any] = snapshot if isinstance(snapshot, Mapping) else {}
    doc, settings, tools = _part(snap, "ontology"), _part(snap, "settings"), _part(snap, "tools")
    agents = _part(settings, "agents")
    listed = [t for d in tools.values() if isinstance(d, Mapping) for t in d.get("tools") or [] if isinstance(t, Mapping)]
    code: int = sum([len(d.get("registries") or []) for d in tools.values() if isinstance(d, Mapping)])
    simulated = [t for t in listed if t.get("type") == "table"]
    workflows = {k: doc.get(k) for k in ("case_templates", "automations", "goals") if doc.get(k)}
    other = {k: v for k, v in settings.items() if k not in ("agents", "solution")}
    ai = _part(settings, "ai")
    return {
        # which model this configuration may ask, and under which policy terms: named, never a credential
        "ai": {"provider": ai.get("provider"), "model": ai.get("model"), "policy_terms": ai.get("policy"),
               "content": ai.get("content"), "fingerprint": mark(dict(ai))} if ai else None,
        "model": {"ref": snap.get("ontology_ref"), "fingerprint": str(snap.get("ontology_fingerprint") or "")[:16],
                  "entities": len(doc.get("entities") or {})},
        "rules": {"count": len(doc.get("rules") or []), "fingerprint": mark(doc.get("rules") or [])},
        "actions": {"count": len(doc.get("actions") or {}), "fingerprint": mark(doc.get("actions") or {})},
        "workflows": {"case_templates": sorted(doc.get("case_templates") or {}), "goals": sorted(doc.get("goals") or {}),
                      "automations": len(doc.get("automations") or []), "fingerprint": mark(workflows)},
        "agents": {"names": sorted(agents), "fingerprint": mark(agents),
                   "managed": "studio" if settings.get("solution") is not None else ("files" if agents else "none")},
        "tools": {"count": len(listed) + code, "simulated": len(simulated), "other": len(listed) - len(simulated) + code,
                  "all_simulated": bool(listed) and len(simulated) == len(listed) and not code,
                  "fingerprint": mark(tools)},
        "governance": {"settings": sorted(other), "fingerprint": mark(other)},
    }


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
def suggest(document: Any, sample: Optional[Mapping[str, Mapping[str, Any]]] = None,
            taken: Iterable[str] = ()) -> Dict[str, Any]:
    """A plain starting configuration for a model: one agent holding the roles the access rules name, pursuing
    every goal, with a ``simulated.succeed`` tool for each action, and one sample case along the first case
    template. A person edits it; the engine validates whatever is saved."""
    onto = Ontology.from_dict(dict(document))
    roles = sorted({role for rule in onto.rules if rule.kind in ACCESS_KINDS for role in rule.params["roles"]})
    agent = {"purpose": "Pursues the model's goals within its rules", "responsibilities": [],
             "roles": roles, "goals": sorted(onto.goals), "autonomy": {"mode": "policy"},
             "tools": [{"action": name, "tool": "simulated.succeed"} for name in sorted(onto.actions)]}
    out: Dict[str, Any] = {"agents": {"solution_agent": agent} if onto.actions and onto.goals else {}}
    data = sample_records(onto, sample, taken)
    if data is not None:
        out["sample_data"] = data
    return out


def sample_records(onto: Ontology, sample: Optional[Mapping[str, Mapping[str, Any]]],
                   taken: Iterable[str] = ()) -> Optional[Dict[str, Any]]:
    """One synthetic record per entity of the first case template, linked along the template's paths (a path
    may take several steps: ``orders.lines``), or None when the model has no case template. A run needs records
    to read its case from; a model nobody wrote a template for has none until a person asks for these.
    ``taken``: identifiers already in use (the use case's records): a sample never claims one, because a record
    that exists is never overwritten and the sample would silently not be loaded."""
    template = next(iter(onto.case_templates.values()), None)
    if template is None or sample is None:
        return None
    ids: Dict[str, str] = {}
    used = set(taken)
    for entity in template.entities:
        stem, n = entity.upper()[:8], 1
        while f"{stem}-{n}" in ids.values() or f"{stem}-{n}" in used:
            n += 1
        ids[entity] = f"{stem}-{n}"
    instances, links = [], []
    for entity, steps in template.entities.items():
        if entity not in sample:
            continue
        previous = template.root
        if len(steps) > 1:  # the record the last step starts from: the entity the path reaches one step earlier
            try:
                previous = onto._walk(template.root, steps[:-1], f"case template {template.name!r}")
            except OntologyError:
                continue
            if previous not in ids or previous not in sample:
                continue
        instances.append({"type": entity, "id": ids[entity], **dict(sample[entity])})
        if steps:
            step = steps[-1]
            links.append([ids[entity], step[1:], ids[previous]] if step.startswith("^")
                         else [ids[previous], step, ids[entity]])
    return {"instances": instances, "links": links}


def from_descriptions(document: Any, described: Any) -> Dict[str, Any]:
    """A starting configuration from the agents an architect *described* (name, description, actions). The
    descriptions are untrusted text: only names and actions that exist in the model are kept, each agent holds
    just the roles the model's access rules ask for on its own actions, every tool is the plain simulated one,
    and the result is still validated before anyone can save it. It grants nothing: it is a draft for a person."""
    onto = Ontology.from_dict(dict(document))
    agents: Dict[str, Any] = {}
    for item in described if isinstance(described, list) else []:
        if not isinstance(item, Mapping) or len(agents) >= MAX_AGENTS:
            continue
        name = re.sub(r"[^A-Za-z0-9_]+", "_", str(item.get("name") or "")).strip("_").lower()[:48]
        actions = [a for a in dict.fromkeys(item.get("actions") or []) if isinstance(a, str) and a in onto.actions]
        if not NAME.match(name) or name in agents or not actions or not onto.goals:
            continue
        written = {f for a in actions for f in set(onto.actions[a].writes) | set(_effects(onto.actions[a]))}
        roles = sorted({role for rule in onto.rules for role in rule.params.get("roles", [])
                        if (rule.kind == "action_access" and rule.params["action"] in actions)
                        or (rule.kind == "write_access" and rule.params["field"] in written)})
        agents[name] = {"purpose": str(item.get("description") or "")[:MAX_TEXT], "responsibilities": [],
                        "roles": roles, "goals": sorted(onto.goals), "autonomy": {"mode": "policy"},
                        "tools": [{"action": a, "tool": "simulated.succeed"} for a in actions]}
    return {"agents": agents}


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
