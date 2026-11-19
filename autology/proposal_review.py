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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

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
        # how many decisions and corrections this review rests on: a reviewer who decided over an older count is told
        "version": len(decisions) + len(corrections),
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


MODES = ("architect_proposal", "manual_authoring", "derived_revision", "imported_configuration", "legacy_unknown")
ESTABLISHED = "the engine, from the authenticated save and the stored proposal history; nothing a client says about origin is taken as proof"


def _key(kind: str, name: Any, value: Mapping[str, Any]) -> str:
    """What makes two elements the same element, whatever their content."""
    if kind == "relationship":
        return f"relationship:{value.get('from')}-{value.get('type')}-{value.get('to')}"
    return f"{kind}:{value.get('id') if kind == 'rule' else name}"


def _elements(document: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for kind, section in SECTIONS.items():
        held = document.get(section)
        if isinstance(held, Mapping):
            out.update({_key(kind, name, value if isinstance(value, Mapping) else {}): value for name, value in held.items()})
        elif isinstance(held, list):
            out.update({_key(kind, None, value): value for value in held if isinstance(value, Mapping)})
    return out


def classify(document: Mapping[str, Any], parent: Mapping[str, Any], proposals: Sequence[Mapping[str, Any]], author: str,
             declared: Optional[Mapping[str, Any]] = None, parent_record: Optional[Mapping[str, Any]] = None,
             parent_revision: int = 0, legacy_parent: bool = False) -> Dict[str, Any]:
    """Where the model of a draft comes from, **established by the Engine**, and whether it may be saved.

    ``parent`` is the model the draft changes (the draft before it, else what runs); ``proposals`` are all the
    stored proposals of the use case, each ``{"id", "revisions", "decisions", "corrections"}``. Every element the
    draft adds or changes is compared, by identity and by content, with the elements of those proposals:

    * content identical to an element a person **confirmed** (stated and not rejected, accepted, or corrected to
      exactly this) is the proposal's, confirmed: recorded with the proposal, the revision and who decided;
    * content identical to an element that was **rejected**, or inferred and **never confirmed**, or to the
      original of an element a person **corrected**, refuses the draft. Naming no origin changes nothing: the
      Engine does not ask where the element is said to come from;
    * the same element with **other content** than what was reviewed: refused when the draft names that proposal
      (an edited element needs a recorded correction); otherwise it is the author's own content, recorded as such
      and flagged, because it cannot be proven to come from anywhere;
    * anything else is the authenticated author's own.

    ``declared`` (the proposal a client names) is checked against what was found and proves nothing by itself.
    """
    before, after = _elements(parent), _elements(document)
    index: Dict[str, List[Dict[str, Any]]] = {}
    for proposal in proposals:
        for row in sorted(proposal["revisions"], key=lambda r: r["revision"]):
            for e in standing(proposal["revisions"], proposal["decisions"], proposal["corrections"], row["revision"]):
                raw = next(i["value"] for i in row["result"]["items"] if i["id"] == e["id"])
                index.setdefault(_key(e["kind"], e["name"], raw), []).append(
                    {"proposal": proposal["id"], "revision": row["revision"], "id": e["id"], "kept": e["kept"],
                     "decision": e["decision"], "by": e["by"], "value": e["value"], "raw": raw,
                     "needs_confirmation": e["needs_confirmation"]})
    confirmed, manual, flags, refused = [], [], [], []
    named = (declared or {}).get("proposal")
    for key, value in after.items():
        if key in before and before[key] == value:
            continue
        candidates = index.get(key) or []
        latest: Dict[str, Dict[str, Any]] = {}
        for c in candidates:  # per proposal, the latest revision in which this exact content was shown or written
            if value in (c["value"], c["raw"]):
                latest[c["proposal"]] = c
        good = [c for c in latest.values() if c["kept"] and c["value"] == value]
        if good:
            best = next((c for c in good if c["proposal"] == named), good[0])
            # whether it may be taken is judged on the latest revision that shows it (a later rejection counts);
            # the revision recorded is the one named, when that revision showed this same content
            shown = any(c["proposal"] == named and c["revision"] == (declared or {}).get("revision") and value in (c["value"], c["raw"])
                        for c in candidates)
            confirmed.append({"element": key, "proposal": best["proposal"],
                              "revision": (declared or {}).get("revision") if shown and best["proposal"] == named else best["revision"],
                              "decision": best["decision"] or "stated, not rejected", "by": best["by"]})
        elif latest:
            c = next((x for x in latest.values() if x["proposal"] == named), next(iter(latest.values())))
            why = ("it was rejected" + (f" by {c['by']}" if c["by"] else "") if c["decision"] == "rejected" else
                   f"its content was corrected by {c['by']}, and the draft takes the content from before the correction"
                   if c["decision"] == "corrected" else "it is inferred and nobody confirmed it")
            refused.append({"element": key, "proposal": c["proposal"], "revision": c["revision"], "why": why})
        elif any(c["proposal"] == named for c in candidates):
            refused.append({"element": key, "proposal": named, "revision": (declared or {}).get("revision"),
                            "why": "its content differs from the element as it was reviewed: an edited element needs "
                                   "a recorded correction"})
        else:
            manual.append(key)
            if candidates:
                last = candidates[-1]
                flags.append({"element": key, "note": f"same element as one of proposal {last['proposal']} "
                              f"({'kept' if last['kept'] else 'not confirmed' if last['decision'] is None else last['decision']} "
                              "there), with other content: recorded as the author's own, which cannot be verified"})
    if named and not refused and not any(c["proposal"] == named for c in confirmed):
        refused.append({"element": None, "proposal": named, "revision": (declared or {}).get("revision"),
                        "why": "nothing this draft adds or changes comes from the proposal it names"
                               + (f"; its elements are those of proposal {confirmed[0]['proposal']}" if confirmed else "")})
    removed = sorted(k for k in before if k not in after)
    sources = sorted({(c["proposal"], c["revision"]) for c in confirmed})
    carried = [dict(p) for p in (parent_record or {}).get("proposals") or []]
    linked = carried + [{"proposal": p, "revision": r} for p, r in sources if {"proposal": p, "revision": r} not in carried]
    mode = "architect_proposal" if confirmed else "manual_authoring" if manual or removed else "derived_revision"
    record = {
        "mode": mode, "established_by": ESTABLISHED, "author": author,
        "parent": {"revision": parent_revision, "mode": "active_model" if not parent_revision else
                   (parent_record or {}).get("mode", "legacy_unknown")},
        # the proposals this draft's model rests on, this revision's and every one before it: a link is never dropped
        "proposals": linked, "declared_origin": dict(declared) if declared else None,
        "elements": {"unchanged": sum(1 for k, v in after.items() if before.get(k) == v), "from_a_proposal_confirmed": len(confirmed),
                     "authored_by_hand": len(manual), "removed": len(removed)},
        "confirmed": confirmed[:200], "authored": manual[:200], "flags": flags[:100],
        "reestablished_from_legacy": legacy_parent,
        "includes_unknown": bool((parent_record or {}).get("includes_unknown")) and not legacy_parent,
        "cannot_prove": "that hand-authored content was not copied from outside Autology"}
    return {"refused": refused, "record": record,
            "origin": {"proposal": sources[-1][0], "revision": sources[-1][1]} if sources else None}


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


__all__ = ["POLICY", "MODES", "dependencies", "standing", "resolve", "report", "draft_problems", "classify", "traceability",
           "digest"]
