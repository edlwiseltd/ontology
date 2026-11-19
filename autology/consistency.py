"""Workflow consistency checks on a model document: potential inconsistencies for a person to decide.

The engine's strict loader says whether a model *loads*. A model that loads can still describe a workflow nobody
intended: a case that reaches its goal while an exception is open, an action that can never start, an obligation
that can never be met. The first stored run of a model proposed by a language model (17 November 2026) showed one:
a turnaround could be completed while its operational conflict was still open.

:func:`findings` reads a document and returns such findings. It is static (no run, no data), it is rule-based (no
model is asked), and **it changes nothing**: each finding says what was noticed, why it may matter and what a
person could do, including "this is intended". It never adds a rule and never blocks a save.

What it reads: an action's ``requires`` and ``effects``, the states of entities, goals' targets, rules, the case
templates and relationships. A condition is read for the ``Entity.status == 'state'`` comparisons it contains and
for the entities it mentions; anything subtler is left to simulation and to people.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Set, Tuple

STATUS = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.status\s*==\s*'([^']+)'")
MENTION = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*")
CHECKS = ("goal_unreachable", "open_exception", "action_cannot_start", "obligation_cannot_be_met", "always_prohibited",
          "outside_effect_ungoverned", "state_never_reached")


def _conditions(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def _mentions(conditions: Iterable[str]) -> Set[str]:
    return {m.group(1) for c in conditions for m in MENTION.finditer(c)}


def findings(document: Any) -> Dict[str, Any]:
    """Potential inconsistencies of the workflow ``document`` describes. Never raises on a malformed document: a
    model the loader refuses simply yields what can still be read (the loader's message is the finding that
    matters then)."""
    out: List[Dict[str, Any]] = []
    if not isinstance(document, Mapping):
        return {"findings": out, "checked": list(CHECKS), "note": NOTE}
    def named(key: str) -> Dict[str, Mapping[str, Any]]:  # a section of named things, whatever the document holds there
        section = document.get(key)
        return {str(n): v for n, v in section.items() if isinstance(v, Mapping)} if isinstance(section, Mapping) else {}

    def listed(key: str) -> List[Mapping[str, Any]]:
        section = document.get(key)
        return [v for v in section if isinstance(v, Mapping)] if isinstance(section, (list, tuple)) else []

    entities, actions, goals = named("entities"), named("actions"), named("goals")
    rules, relationships = listed("rules"), listed("relationships")
    def states_of(entity: Mapping[str, Any]) -> List[str]:
        raw = entity.get("states")
        return [str(s) for s in raw] if isinstance(raw, (list, tuple)) else []

    states = {n: states_of(e) for n, e in entities.items()}

    def first_state(entity: str) -> str:  # the state a new record starts in ("" when the entity has none)
        return (states.get(entity) or [""])[0]

    sets: Dict[Tuple[str, str], List[str]] = {}  # (entity, state) -> the actions that bring a record there
    leaves: Dict[Tuple[str, str], List[str]] = {}  # (entity, state) -> the actions that can start from there
    needs: Dict[str, List[Tuple[str, str]]] = {}
    for name, action in actions.items():
        effects = action.get("effects")
        for entity, effect in (effects.items() if isinstance(effects, Mapping) else ()):
            if isinstance(effect, Mapping) and "status" in effect:
                sets.setdefault((str(entity), str(effect["status"])), []).append(name)
        needs[name] = [(m.group(1), m.group(2)) for c in _conditions(action.get("requires")) for m in STATUS.finditer(c)]
        for pair in needs[name]:
            leaves.setdefault(pair, []).append(name)

    def reachable(entity: str, state: str, without: str = "") -> bool:
        # ``without``: an action that needs the state cannot be the one that brings it about
        return any(a != without for a in sets.get((entity, state)) or []) or first_state(entity) == state

    def add(kind: str, severity: str, finding: str, why: str, could: List[str], **where: Any) -> None:
        out.append({"id": f"{kind}:{':'.join(str(v) for v in where.values())}", "kind": kind, "severity": severity,
                    "finding": finding, "why": why, "a_person_could": could + ["leave it: this is intended"], **where})

    prohibited_always = {r.get("action") for r in rules if r.get("type") == "prohibition" and not r.get("when")}
    cannot_start: Set[str] = set()
    for name, pairs in needs.items():
        by_entity: Dict[str, List[str]] = {}
        for entity, state in pairs:
            by_entity.setdefault(entity, []).append(state)
        for entity, wanted in by_entity.items():
            if entity in states and not any(reachable(entity, s, name) for s in wanted):
                cannot_start.add(name)
                add("action_cannot_start", "medium",
                    f"{name} needs a {entity} in state {', '.join(sorted(set(wanted)))}, which no action brings about",
                    f"a {entity} starts as {states[entity][0] if states[entity] else 'nothing'} and no action sets "
                    f"{' or '.join(sorted(set(wanted)))}: unless records arrive in that state from another system, "
                    f"{name} never starts",
                    [f"add the action that brings a {entity} to that state", f"change what {name} requires"],
                    action=name, entity=entity)
    for action in sorted(a for a in prohibited_always if a in actions):
        add("always_prohibited", "medium", f"{action} is prohibited without any condition",
            "a prohibition with no \"when\" applies always: the action can never be performed",
            ["give the prohibition a condition", "remove the action"], action=action)

    for name, goal in goals.items():
        wanted_by: Dict[str, List[str]] = {}
        for entity, state in STATUS.findall(str(goal.get("target", ""))):
            if entity in states:
                wanted_by.setdefault(entity, []).append(state)
        for entity, wanted in wanted_by.items():
            if not any(reachable(entity, s) for s in wanted):  # a target with several states needs one of them
                add("goal_unreachable", "high",
                    f"no action brings a {entity} to {' or '.join(repr(s) for s in wanted)}, which the goal {name} waits for",
                    "a run that pursues this goal has no path to it and will escalate",
                    [f"add the action that sets {entity}.status to {wanted[0]}", "change the goal's target"],
                    goal=name, entity=entity)
        for entity, state in [(e, s) for e, many in wanted_by.items() for s in many]:
            finishing = sets.get((entity, state), [])
            # what the goal's record owns: the entities its relationships lead to (a turnaround's conflicts, an
            # order's lines). What it belongs to (the record above it) is not an exception of it
            near = sorted({str(r.get("to")) for r in relationships if r.get("from") == entity})
            for other in near:
                first = first_state(other)
                unsettled = [s for s in states.get(other, []) if leaves.get((other, s))]  # states work still leaves
                if other == entity or not first or first not in unsettled:
                    continue
                for finisher in finishing:
                    guards = _mentions(_conditions(actions[finisher].get("requires")))
                    guards |= _mentions(str(r.get("when", "")) for r in rules
                                        if r.get("type") == "prohibition" and r.get("action") == finisher)
                    if other not in guards:
                        add("open_exception", "medium",
                            f"{finisher} can bring a {entity} to {state!r} whatever the state of its {other}",
                            f"nothing {finisher} requires, and no prohibition on it, refers to {other}: the goal {name} "
                            f"can be reached while a {other} is still {' or '.join(unsettled)}",
                            [f"add a precondition on {other} to {finisher}",
                             f"add a prohibition on {finisher} while a {other} is not settled"],
                            action=finisher, entity=other, goal=name)

    for rule in rules:
        if rule.get("type") != "mandatory_step":
            continue
        step = rule.get("step")
        if step in cannot_start or step in prohibited_always:
            add("obligation_cannot_be_met", "high",
                f"the rule {rule.get('id')} requires {step}, which can never be performed",
                f"{step} {'is always prohibited' if step in prohibited_always else 'can never start'}: "
                + (f"{rule['before']} would be blocked for ever" if rule.get("before") else "the obligation is never met"),
                [f"make {step} possible", "change the rule"], rule=str(rule.get("id")), action=str(step))

    governed = {r.get("action") for r in rules if r.get("type") in ("human_review", "prohibition", "action_access")}
    for name, action in sorted(actions.items()):
        if action.get("side_effect") not in (None, "none") and name not in governed:
            add("outside_effect_ungoverned", "low", f"{name} acts outside Autology and no rule names it",
                "no review, prohibition or access rule covers it: whoever may run an agent that has this action can "
                "trigger the effect",
                [f"add an access rule for {name}", f"add a human review for {name} above a limit"], action=name)

    for entity, every in sorted(states.items()):
        never = [s for s in every[1:] if not sets.get((entity, s))]
        if never and len(every) > 1:
            add("state_never_reached", "low", f"no action brings a {entity} to {', '.join(never)}",
                "such a state is reached only if records arrive in it from another system; if not, it is unused",
                ["add the action that leads there", "remove the state"], entity=entity)

    order = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda f: (order[f["severity"]], f["kind"], f["id"]))
    return {"findings": out, "checked": list(CHECKS), "note": NOTE}


NOTE = ("potential inconsistencies found by reading the model, for a person to decide: nothing was changed, nothing is "
        "blocked, and a finding may describe something intended")
