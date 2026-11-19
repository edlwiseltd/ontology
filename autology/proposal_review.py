"""Where each element of an architect proposal stands after people reviewed it, and what that makes.

An architect proposal is a list of elements, each marked as **stated** by the description (``basis: supplied``) or
**inferred** by the architect. People record decisions against a revision: accept, reject, or correct an element
(:meth:`autology.architecting.ArchitectService.decide_proposal`). Decisions and corrections are append-only and
attributed. This module reads that history; it stores nothing, asks no provider and decides nothing.

The rules, the same for every proposal (no name of an element means anything here):

* an **inferred** element is confirmed only by a person's explicit acceptance or correction of *that* element.
  Nothing confirms it by default, in bulk by omission, or because a later revision repeats it;
* a **stated** element needs no confirmation and can be rejected like any other;
* the **last** decision about an element wins; every earlier one stays in its history;
* a decision is about the element **as it was shown**. Carried to a later revision it holds only while the element
  is unchanged there. A changed element is undecided again. A **rejected** element that a later revision proposes
  again is still rejected, and is flagged as proposed again: it is never confirmed by reappearing;
* a **correction** replaces an element's content with what the person wrote. It is the person's, attributed to
  them, and needs no provider. The corrected element is validated like any other;
* an element that is kept but **depends** on one that is not (a relationship of a rejected entity, a rule on an
  unconfirmed action) is reported by name before any validation, so that the reviewer sees *which* decision broke
  what. The verdict on the resulting model is the strict loader's (:class:`autology.ontology.Ontology`), as for
  every model: this module is not a second validator.

:func:`report` is what a reviewer reads; :func:`draft_problems` is what the Engine checks when a draft says it was
saved from a proposal: such a draft may not contain an element of that proposal that was rejected, or inferred and
not confirmed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

from .consistency import findings
from .ontology import Ontology, OntologyError

POLICY = ("an inferred element enters a draft only when a person accepted or corrected it; a rejected element "
          "never does; a decision holds for the element as it was shown")
SECTIONS = {"entity": "entities", "action": "actions", "goal": "goals", "case_template": "case_templates",
            "relationship": "relationships", "rule": "rules"}
_NAME = re.compile(r"\b([A-Za-z_]\w*)\.[A-Za-z_]\w*")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _named(text: Any) -> Set[str]:
    return set(_NAME.findall(text)) if isinstance(text, str) else set()


def dependencies(item: Mapping[str, Any], items: Sequence[Mapping[str, Any]]) -> List[str]:
    """The identifiers of the proposal's own elements that ``item`` refers to (structure only)."""
    entities = {i["name"]: i["id"] for i in items if i["kind"] == "entity"}
    actions = {i["name"]: i["id"] for i in items if i["kind"] == "action"}
    relations: Dict[str, List[str]] = {}
    for i in items:
        if i["kind"] == "relationship":
            relations.setdefault(str(i["value"].get("type")), []).append(i["id"])
    value, kind, names, out = item["value"], item["kind"], set(), set()  # type: ignore[var-annotated]
    if kind == "relationship":
        names |= {str(value.get("from")), str(value.get("to"))}
    elif kind == "action":
        for expression in value.get("requires") or []:
            names |= _named(expression)
        effects = value.get("effects") or {}
        names |= set(effects) if isinstance(effects, Mapping) else {str(e.get("entity")) for e in effects if isinstance(e, Mapping)}
    elif kind == "rule":
        names |= _named(value.get("when")) | _named(value.get("field"))
        names |= {str(value[k]).split(".")[0] for k in ("entity", "field") if value.get(k)}
        out |= {actions[str(value[k])] for k in ("action", "before") if str(value.get(k)) in actions}
    elif kind == "goal":
        names |= _named(value.get("target"))
    elif kind == "case_template":
        names.add(str(value.get("root")))
        members = value.get("entities") or {}
        pairs = members.items() if isinstance(members, Mapping) else [(m.get("entity"), m.get("path")) for m in members if isinstance(m, Mapping)]
        for entity, path in pairs:
            names.add(str(entity))
            for step in str(path or "").split("."):
                out |= set(relations.get(step.lstrip("^"), []))
    out |= {entities[n] for n in names if n in entities}
    return sorted(out - {item["id"]})


def standing(revisions: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]],
             corrections: Sequence[Mapping[str, Any]], revision: int) -> List[Dict[str, Any]]:
    """One entry per element of ``revision``: where it stands, by whose decision, and its whole history."""
    by_revision = {r["revision"]: {i["id"]: i for i in r["result"].get("items") or []} for r in revisions}
    events: List[Dict[str, Any]] = []
    for d in decisions:
        for verdict in ("accepted", "rejected"):
            events += [{"at": d["at"], "revision": d["revision"], "by": d["decided_by"], "decision": verdict,
                        "item": item, "note": d.get("note") or ""} for item in d.get(verdict) or []]
    events += [{"at": c["at"], "revision": c["revision"], "by": c["corrected_by"], "decision": "corrected",
                "item": c["item"], "note": c.get("note") or "", "value": c["value"]} for c in corrections]
    events.sort(key=lambda e: (e["at"], e["decision"] != "corrected"))  # stable: recorded order within one moment
    out = []
    for item in (by_revision.get(revision) or {}).values():
        history = [e for e in events if e["item"] == item["id"] and e["revision"] <= revision]
        last = history[-1] if history else None
        entry: Dict[str, Any] = {
            "id": item["id"], "kind": item["kind"], "name": item["name"], "basis": item.get("basis"),
            "origin": item.get("origin"), "needs_confirmation": item.get("basis") != "supplied",
            "decision": None, "by": None, "at": None, "decided_on_revision": None, "flags": [],
            "history": [{k: e[k] for k in ("decision", "by", "at", "revision", "note")} for e in history]}
        value = item["value"]
        if last is not None:
            shown = (by_revision.get(last["revision"]) or {}).get(item["id"])
            same = shown is not None and digest(shown["value"]) == digest(item["value"])
            if last["decision"] == "rejected":
                entry.update(decision="rejected")
                if last["revision"] != revision:
                    entry["flags"].append("proposed again after it was rejected" if same else
                                          "proposed again, changed, after it was rejected")
            elif same or last["revision"] == revision:
                entry.update(decision=last["decision"])
                if last["decision"] == "corrected":
                    value = last["value"]
                if last["revision"] != revision:
                    entry["flags"].append(f"decision carried from revision {last['revision']}: the element is unchanged")
            else:
                entry["flags"].append(f"changed since it was {last['decision']} in revision {last['revision']}: undecided again")
            if entry["decision"]:
                entry.update(by=last["by"], at=last["at"], decided_on_revision=last["revision"])
        entry["kept"] = entry["decision"] in ("accepted", "corrected") or (
            entry["decision"] is None and not entry["needs_confirmation"])
        entry["value"], entry["value_digest"] = value, digest(value)
        out.append(entry)
    for entry in out:
        entry["depends_on"] = dependencies(entry, out)
    return out


def resolve(base: Mapping[str, Any], elements: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """``base`` with the kept elements added. An element the base already holds, identically, is not added twice."""
    out = copy.deepcopy(dict(base))
    for e in elements:
        if not e["kept"]:
            continue
        section = SECTIONS[e["kind"]]
        if e["kind"] in ("relationship", "rule"):
            if e["value"] not in out.setdefault(section, []):
                out[section].append(copy.deepcopy(e["value"]))
        else:
            out.setdefault(section, {})[e["name"]] = copy.deepcopy(e["value"])
    return out


def _present(document: Mapping[str, Any], element: Mapping[str, Any], value: Any) -> bool:
    section = document.get(SECTIONS[element["kind"]])
    if element["kind"] in ("relationship", "rule"):
        return isinstance(section, list) and value in section
    return isinstance(section, Mapping) and section.get(element["name"]) == value


def report(base: Mapping[str, Any], revisions: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]],
           corrections: Sequence[Mapping[str, Any]], revision: int) -> Dict[str, Any]:
    """The review of one revision: every element's standing, what is unresolved, what a decision broke, and what
    the strict loader says about the model the kept elements make."""
    elements = standing(revisions, decisions, corrections, revision)
    kept = {e["id"] for e in elements if e["kept"]}
    by_id = {e["id"]: e for e in elements}
    broken = []
    for e in elements:
        missing = [d for d in e["depends_on"] if d not in kept and not _present(base, by_id[d], by_id[d]["value"])]
        if e["kept"] and missing:
            broken.append({"element": e["id"], "needs": missing, "because": {
                d: "rejected" if by_id[d]["decision"] == "rejected" else "inferred and not confirmed" for d in missing}})
    document = resolve(base, elements)
    problems: List[str] = []
    try:
        Ontology.from_dict(dict(document))
    except OntologyError as exc:
        problems.append(str(exc)[:400])
    # what loads can still describe a workflow nobody intended: the existing checks, for the reviewer to decide
    noticed = [] if problems else [{"kind": f["kind"], "severity": f["severity"], "finding": f["finding"]}
                                   for f in findings(document)["findings"]]
    unresolved = [e["id"] for e in elements if e["needs_confirmation"] and e["decision"] is None]
    inferred = [e for e in elements if e["needs_confirmation"]]

    def count(test: Any) -> int:
        return sum(1 for e in elements if test(e))

    why = ([f"{len(broken)} kept element(s) depend on an element that is not kept"] if broken else []) + (
        ["the strict loader refuses the model: " + problems[0]] if problems else [])
    return {
        "revision": revision, "policy": POLICY, "elements": elements,
        "counts": {"elements": len(elements), "stated": len(elements) - len(inferred), "inferred": len(inferred),
                   "confirmed": count(lambda e: e["needs_confirmation"] and e["decision"] in ("accepted", "corrected")),
                   "corrected": count(lambda e: e["decision"] == "corrected"),
                   "rejected": count(lambda e: e["decision"] == "rejected"), "unresolved": len(unresolved),
                   "proposed_again_after_rejection": count(lambda e: any("after it was rejected" in f for f in e["flags"])),
                   "kept": len(kept), "dependency_failures": len(broken)},
        "unresolved": unresolved, "dependency_failures": broken, "document": document,
        "validation": {"valid": not problems, "problems": problems,
                       "by": "the engine's strict loader, on the current model plus the kept elements"},
        "consistency": noticed, "ready_for_draft": not problems and not broken, "why_not": why,
        "decided_by": sorted({h["by"] for e in elements for h in e["history"]})}


def draft_problems(document: Mapping[str, Any], elements: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Elements of the proposal that ``document`` contains although nobody confirmed them, or someone rejected them."""
    out = []
    for e in elements:
        if e["kept"] or not _present(document, e, e["value"]):
            continue
        out.append({"element": e["id"], "why": "it was rejected" + (f" by {e['by']}" if e.get("by") else "")
                    if e["decision"] == "rejected" else "it is inferred and nobody confirmed it"})
    return out


def traceability(revision_row: Mapping[str, Any], review: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One line per element: what it rests on, what the Engine found, what a person decided."""
    items = {i["id"]: i for i in revision_row["result"].get("items") or []}
    lines = []
    for e in review["elements"]:
        item = items[e["id"]]
        lines.append({"element": e["id"], "basis": e["basis"], "origin": e["origin"],
                      "cites": [x.get("ref") for x in item.get("evidence") or []], "rationale": item.get("rationale"),
                      "engine": item.get("validation"), "decision": e["decision"] or ("none needed" if e["kept"] else "none"),
                      "decided_by": e["by"], "in_the_model": e["kept"], "flags": e["flags"]})
    for r in revision_row["result"].get("rejected") or []:
        lines.append({"element": f"{r['kind']}:{r['name']}", "basis": None, "origin": None, "cites": [], "rationale": None,
                      "engine": f"refused: {r['problem']}", "decision": "not offered for review", "decided_by": None,
                      "in_the_model": False, "flags": []})
    return lines


__all__ = ["POLICY", "dependencies", "standing", "resolve", "report", "draft_problems", "traceability", "digest"]
