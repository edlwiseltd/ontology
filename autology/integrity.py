"""Decision integrity (SEC-A: audit gaps GAP-035, GAP-037, GAP-045).

Autology turns business information into decisions and governed actions. Some of that information is not trusted:
free text in records, imported rows, replies of tools, documents, and whatever a language model writes after
reading them. This module holds the rules that keep such content from governing anything. None of them relies on
a model behaving well: the tests replace the model with one that obeys every instruction it finds in the data.

**What a model may decide (GAP-045).** A model reasoner only ever names one of the actions the ontology allows
right now, and governance evaluates that action again. That still left a choice *among* valid actions that text
in the data could steer. So a model's choice that differs from the deterministic plan is honoured only where an
authorised policy says a model may choose:

* the action is under a ``human_review`` rule in the current state (a person with the reviewer role decides), or
* the agent's configuration lists it in ``model_may_choose`` (an explicit grant of discretion, part of the
  governing configuration and therefore of the release that a second person approves).

Anything else is replaced by the plan's step and recorded (``reasoner.deviation_refused``). An agent can also be
set to ``"model_discretion": "plan"`` (the model only explains) or ``"open"`` (the previous behaviour: any valid
action; explicit, and reported by :func:`model_findings`). Data is passed to the model inside a marked block that
its content cannot close, and a reply with anything beyond the two expected fields is refused; both are hygiene,
not the control.

**Who may change the facts decisions rest on (GAP-037).** ``write_access`` rules already say which roles may
modify a field. They now bind ingestion too: a pipeline writes a protected field only if the writer holds one of
the rule's roles - the caller's roles for rows the caller supplies (push), the pipeline's declared ``roles`` for
sources the operator configured. A row that would create or change a protected field without that authority is
rejected like any other bad row; the rest of the load goes on. Changes to *decision-critical* fields (those that
rules, preconditions, goals or automations read) are listed in the load's report, and people who have a decision
pending on such a record are told. The pending approval itself is never used on changed facts: the run re-reads
its records when it resumes and asks again (ACT-6).

**What a notification may say (GAP-035).** A notification's text is rendered for its reader: a field the reader
may not see is replaced by ``[restricted]``, and a notification about a record or a run the reader may not see is
not listed. What leaves the platform (webhooks) and what is stored as text is the version every addressed role may
read.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

MODEL_SOURCES = ("llm", "llm-cache")  # Proposal.source values that mean "a model chose this"
DISCRETION = ("governed", "open", "plan")
DATA_OPEN, DATA_CLOSE = "<<<UNTRUSTED_DATA", "UNTRUSTED_DATA>>>"
RESTRICTED = "[restricted]"
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
PRIVATE_REF = "_render"  # the part of a notification's reference that is never returned or sent out


def data_block(value: Any) -> str:
    """Untrusted values as JSON inside a marked block. ``<`` and ``>`` are escaped inside the JSON, so nothing in
    the data can close the block or open another one."""
    text = json.dumps(value, indent=2, default=str, sort_keys=True)
    text = text.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"{DATA_OPEN}\n{text}\n{DATA_CLOSE}"


# -- what a model may choose ------------------------------------------------------------------------------
def may_deviate(action: str, verdict: str, discretion: str, may_choose: Iterable[str]) -> Tuple[bool, str]:
    """Whether a model's choice of ``action`` instead of the plan's step is honoured, and why not if not.
    ``verdict`` is governance's verdict on that action in the current state ("allow" or "review")."""
    base = action.partition("@")[0]
    if discretion == "open":
        return True, ""
    if discretion == "plan":
        return False, "this agent's policy is to follow the plan (model_discretion: plan)"
    if verdict == "review":
        return True, ""
    if base in set(may_choose) or action in set(may_choose):
        return True, ""
    return False, ("no policy lets a model choose it: it is neither under human review in this state nor listed in "
                   "the agent's model_may_choose")


def model_findings(ontology: Any, agent: str, discretion: str, may_choose: Iterable[str]) -> List[str]:
    """What an operator should know about the discretion a model has on this agent (shown in the agents list
    and logged at start): consequential actions a model may choose with no person in the loop."""
    listed = set(may_choose)
    reviewed = {r.params["action"] for r in ontology.rules_of("human_review")}
    consequential = {a.name for a in ontology.actions.values() if a.side_effect != "none"}
    out = []
    unknown = sorted(listed - set(ontology.actions))
    if unknown:
        out.append(f"agent {agent}: model_may_choose names unknown actions {unknown}")
    if discretion == "open":
        uncovered = sorted(consequential - reviewed)
        if uncovered:
            out.append(f"agent {agent}: model_discretion is open; a model may choose {uncovered} with no human "
                       "review rule on them")
    else:
        uncovered = sorted((listed & consequential) - reviewed)
        if uncovered:
            out.append(f"agent {agent}: model_may_choose lets a model choose {uncovered}, which act outside "
                       "Autology and have no human review rule")
    return out


# -- the facts decisions rest on ----------------------------------------------------------------------------
def decision_fields(ontology: Any, automations: Optional[Mapping[str, Any]] = None) -> Dict[str, List[str]]:
    """``"Entity.attribute"`` -> what reads it to decide: rules, action preconditions, goals, automations."""
    found: Dict[str, List[str]] = {}

    def note(expr: Any, what: str) -> None:
        for entity, attr in getattr(expr, "references", ()) or ():
            found.setdefault(f"{entity}.{attr}", []).append(what)

    for rule in ontology.rules:
        if rule.when is not None:
            note(rule.when, f"rule {rule.id}")
    for action in ontology.actions.values():
        for expr in action.requires:
            note(expr, f"action {action.name}")
    for goal in ontology.goals.values():
        note(goal.target, f"goal {goal.name}")
    for auto in (automations or {}).values():
        note(getattr(auto, "when", None), f"automation {auto.name}")
    return {ref: sorted(set(users)) for ref, users in sorted(found.items())}


def critical_refusal(ontology: Any, ref: str, roles: Iterable[str]) -> Optional[str]:
    """Why a writer holding ``roles`` may not change the decision-critical field ``ref``, or None (always None for
    a field that is not classified). Fail closed: the writer must hold the roles of a ``write_access`` rule on the
    field, whatever that rule's condition; while no rule names a writer, nobody changes it."""
    if ref not in ontology.critical_fields:
        return None
    named = [r for r in ontology.rules_of("write_access") if r.params["field"] == ref]
    if not named:
        return (f"{ref} is decision-critical and no write_access rule names who may change it: it cannot be "
                "changed until one does")
    if not any(set(roles) & set(r.params["roles"]) for r in named):
        allowed = sorted({role for r in named for role in r.params["roles"]})
        return f"{ref} is decision-critical ({', '.join(r.id for r in named)}): changing it needs one of the roles {allowed}"
    return None


def changed_attributes(existing: Optional[Mapping[str, Any]], attributes: Mapping[str, Any]) -> Dict[str, Any]:
    """The attributes a write would create or change on a record (all of them for a new record)."""
    if existing is None:
        return {a: v for a, v in attributes.items() if v is not None}
    return {a: v for a, v in attributes.items() if existing.get(a) != v}


def write_refusal(ontology: Any, entity: str, existing: Optional[Mapping[str, Any]], changing: Mapping[str, Any],
                  roles: Iterable[str], unrestricted: bool = False) -> Optional[str]:
    """Why a writer holding ``roles`` may not create or change ``changing`` on a record of ``entity``, or None.
    A ``write_access`` rule's condition is evaluated on the record as it is now (as it would be created, for a
    new one); a condition that cannot be evaluated protects the field. ``unrestricted`` is a writer holding the
    engine's ``admin`` permission: ordinary write rules do not bind it (as that permission is defined), the
    rules on decision-critical fields do."""
    held = set(roles)
    record = dict(existing) if existing is not None else dict(changing)

    def resolve(e: str, a: str) -> Any:
        return record.get(a) if e == entity else None

    for attr in sorted(changing):
        refused = critical_refusal(ontology, f"{entity}.{attr}", held)
        if refused:
            return refused
    for rule in ontology.rules_of("write_access"):
        owner, _, attr = rule.params["field"].partition(".")
        if owner != entity or attr not in changing or held & set(rule.params["roles"]):
            continue
        if unrestricted and rule.params["field"] not in ontology.critical_fields:
            continue
        try:  # a condition that cannot be evaluated (a fact is missing) protects the field
            known = True if rule.when is None else rule.when.evaluate_known(resolve)
        except Exception:
            known = None
        if known is None or known:
            return (f"{rule.params['field']} is write-protected ({rule.id}): changing it needs one of the roles "
                    f"{sorted(rule.params['roles'])}")
    return None


def record_refusal(ontology: Any, graph: Any, entity: str, iid: str, attributes: Mapping[str, Any],
                   roles: Iterable[str]) -> Optional[str]:
    """Why a holder of the engine's unrestricted permission, with ``roles``, may not write this record directly
    (the record API, a scenario commit), or None. Ordinary write rules do not bind that permission; the rules on
    decision-critical fields do, for the attributes the write would create or change."""
    current = graph._instances.get(iid)
    existing = dict(current.attributes) if current is not None else None
    return write_refusal(ontology, entity, existing, changed_attributes(existing, attributes), roles,
                         unrestricted=True)


# -- notifications ----------------------------------------------------------------------------------------
def placeholders(template: str) -> List[str]:
    return PLACEHOLDER.findall(template)


def render(template: str, values: Mapping[str, Any], hidden: Callable[[str], bool], id_key: str = "id") -> str:
    """The template with each ``{attribute}`` replaced by its value, or by ``[restricted]`` when ``hidden`` says
    the reader may not see that attribute. ``{id}`` is the record's identifier."""
    def sub(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name != id_key and hidden(name):
            return RESTRICTED
        return str(values.get(name))

    return PLACEHOLDER.sub(sub, template)


def public_note(note: Mapping[str, Any]) -> Dict[str, Any]:
    """A notification without its private rendering data: what is returned to readers and sent to webhooks."""
    return {**note, "ref": {k: v for k, v in dict(note.get("ref") or {}).items() if k != PRIVATE_REF}}
