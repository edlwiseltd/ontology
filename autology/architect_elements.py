"""Element-level reading of an architect's answer: a **proposed** policy, validated and **not in force** (GAP-082).

The rule in force is unchanged: an answer that does not match the contract is refused whole
(:meth:`autology.ai.ModelGateway._answer`). Nothing in the gateway, the architect service or the API calls this
module. It exists so that the owner's decision D30 f can be taken on something that runs and is tested, and so
that a refused answer kept by an evaluation (``--save``) can be read against it at no cost.

What :func:`triage` does with an answer (a JSON object, already parsed):

1. **Strict envelope.** The answer must be an object whose top-level properties are the contract's and whose
   sections have the contract's types. A property the contract does not name at the top level, a property named
   like a permission, a grant, a release, a setting, a tool, an endpoint or a credential **anywhere**, or any defect
   outside the six model sections refuses the whole answer, exactly as today.
2. **Element findings.** Inside the six model sections (entities, relationships, actions, rules, goals, case
   templates) each element is checked against the contract on its own. An element with any defect is **rejected
   whole, by name, with its reasons**. Nothing is repaired, no property is removed to make it pass, no default is
   filled in.
3. **Dependency integrity.** An element that refers to a rejected one (a relationship of a rejected entity, a rule
   on a rejected action, a case template that follows a rejected relationship...) is rejected with it, to a fixed
   point. If a rejected element cannot be named, what
   depends on it cannot be known, and the whole answer is refused.
4. **A limit.** When more than a quarter of the elements are rejected the answer is not treated as usable.
5. **No activation.** The result is marked partial. It is a reading for a person, who must see every rejection
   before accepting anything; this module applies nothing and stores nothing.
6. **Audit.** The result carries a digest of the answer as received, every rejection with its place and reasons,
   the classes of violation and the decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .ai import SENSITIVE_WORDS, violation_classes
from .architect import SCHEMA, SECTIONS
from .schema import errors as schema_errors

POLICY = "element-level-v1 (proposed, not in force)"
MAX_REJECTED_SHARE = 0.25
MODEL_SECTIONS = tuple(section for _, section in SECTIONS)
IDENT = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")


def _sensitive(value: Any, path: str = "$") -> List[str]:
    """Every property, at any depth, named like something the contract must never carry."""
    found: List[str] = []
    if isinstance(value, Mapping):
        for key, sub in value.items():
            if any(word in str(key).lower() for word in SENSITIVE_WORDS):
                found.append(f"{path}: property {str(key)!r} is named like a permission, a release, a setting, a tool "
                             "or a credential")
            found += _sensitive(sub, f"{path}.{key}")
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            found += _sensitive(sub, f"{path}[{i}]")
    return found


def _name(section: str, element: Any) -> Optional[str]:
    """The name other elements would use to refer to this one, if it can be read."""
    if not isinstance(element, Mapping):
        return None
    if section == "relationships":
        parts = [str(element.get(k) or "") for k in ("from", "type", "to")]
        return "-".join(parts) if all(parts) and all(isinstance(element.get(k), str) for k in ("from", "type", "to")) \
            else None
    name = element.get("id" if section == "rules" else "name")
    return name if isinstance(name, str) and name else None


def _refers(section: str, element: Mapping[str, Any]) -> Dict[str, Set[str]]:
    """What an element refers to, by kind of thing: entities, actions, and the relationships a case template
    follows."""
    def words(*values: Any) -> Set[str]:
        return {w for v in values for text in (v if isinstance(v, list) else [v]) if isinstance(text, str)
                for w in IDENT.findall(text)}

    entities: Set[str] = set()
    actions: Set[str] = set()
    paths: Set[str] = set()
    if section == "relationships":
        entities = words(element.get("from"), element.get("to"))
    elif section == "actions":
        entities = words(element.get("requires")) | {str(e.get("entity")) for e in element.get("effects") or []
                                                     if isinstance(e, Mapping)}
    elif section == "rules":
        entities = words(element.get("when"), element.get("entity"), element.get("field"))
        actions = words(element.get("action"), element.get("step"), element.get("before"))
    elif section == "goals":
        entities = words(element.get("target"))
    elif section == "case_templates":
        entities = words(element.get("root")) | {str(e.get("entity")) for e in element.get("entities") or []
                                                 if isinstance(e, Mapping)}
        paths = words([e.get("path") for e in element.get("entities") or [] if isinstance(e, Mapping)]) - {"self"}
    return {"entities": entities, "actions": actions, "relationships": paths}


def triage(data: Any, schema: Mapping[str, Any] = SCHEMA, max_rejected_share: float = MAX_REJECTED_SHARE
           ) -> Dict[str, Any]:
    """Read ``data`` as described in the module docstring. Returns a dictionary with ``decision``
    (``accept``, ``accept_with_rejections`` or ``refuse_whole``), ``kept`` (the answer with its clean elements only,
    or ``None``), ``rejected``, ``envelope`` (the reasons for a whole refusal) and ``audit``. It never raises on a
    malformed answer and never changes ``data``."""
    received = json.dumps(data, sort_keys=True, default=str)
    audit: Dict[str, Any] = {"policy": POLICY, "received_sha256": hashlib.sha256(received.encode()).hexdigest(),
                             "elements": 0, "rejected": 0, "classes": {}}

    def refuse(reasons: List[str], rejected: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        audit["decision"] = "refuse_whole"
        return {"decision": "refuse_whole", "partial": False, "kept": None, "envelope": reasons,
                "rejected": rejected or [], "audit": audit}

    if not isinstance(data, Mapping):
        return refuse(["the answer is not a JSON object"])
    properties = schema["properties"]
    envelope = [f"$: unexpected section {key!r}" for key in data if key not in properties]
    envelope += [f"$: missing section {key!r}" for key in schema.get("required", []) if key not in data]
    envelope += _sensitive(data)
    for key, value in data.items():
        if key in MODEL_SECTIONS:
            if not isinstance(value, list):
                envelope.append(f"$.{key}: expected a list")
        elif key in properties:  # everything that is not a model section is part of the envelope: checked whole
            envelope += schema_errors(value, dict(properties[key]), None, f"$.{key}")
    if envelope:
        audit["classes"] = violation_classes([e for e in envelope if ": unexpected " in e]) or {"envelope": len(envelope)}
        return refuse(envelope)

    rejected: List[Dict[str, Any]] = []
    clean: Dict[str, List[Tuple[int, Mapping[str, Any]]]] = {}
    gone: Dict[str, Set[str]] = {"entities": set(), "actions": set(), "relationships": set()}
    for section in MODEL_SECTIONS:
        clean[section] = []
        for index, element in enumerate(data.get(section) or []):
            audit["elements"] += 1
            problems = schema_errors(element, dict(properties[section]["items"]), None, f"$.{section}[{index}]")
            if not problems:
                clean[section].append((index, element))
                continue
            name = _name(section, element)
            rejected.append({"section": section, "index": index, "name": name, "reason": "does not match the contract",
                             "problems": problems, "classes": violation_classes(problems)})
            if name is None and section in ("entities", "actions"):
                return refuse([f"$.{section}[{index}]: a rejected element cannot be named, so what depends on it "
                               "cannot be known"], rejected)
            if section == "relationships" and isinstance(element, Mapping) and isinstance(element.get("type"), str):
                gone[section].add(element["type"])  # a case template follows a relationship by its type
            elif section in gone and name is not None:
                gone[section].add(name)

    changed = True
    while changed:  # what refers to something rejected goes with it, until nothing more does
        changed = False
        for section in MODEL_SECTIONS:
            for index, element in list(clean[section]):
                refers = _refers(section, element)
                lost = sorted(set().union(*(refers[kind] & gone[kind] for kind in gone)))
                if not lost:
                    continue
                clean[section].remove((index, element))
                name = _name(section, element)
                rejected.append({"section": section, "index": index, "name": name,
                                 "reason": f"refers to rejected {', '.join(lost)}", "problems": [],
                                 "classes": {"depends_on_rejected": 1}})
                if section == "relationships":
                    gone[section].add(str(element.get("type")))
                elif section in gone and name is not None:
                    gone[section].add(name)
                changed = True

    for item in rejected:
        for kind, count in item["classes"].items():
            audit["classes"][kind] = audit["classes"].get(kind, 0) + count
    audit["rejected"] = len(rejected)
    rejected.sort(key=lambda r: (MODEL_SECTIONS.index(r["section"]), r["index"]))
    if audit["elements"] and len(rejected) / audit["elements"] > max_rejected_share:
        return refuse([f"{len(rejected)} of {audit['elements']} elements were rejected: more than "
                       f"{int(max_rejected_share * 100)} % of the answer cannot be used"], rejected)
    kept = {key: value for key, value in data.items() if key not in MODEL_SECTIONS}
    for section in MODEL_SECTIONS:
        if section in data:
            kept[section] = [element for _, element in clean[section]]
    decision = "accept_with_rejections" if rejected else "accept"
    audit["decision"] = decision
    return {"decision": decision, "partial": bool(rejected), "kept": kept, "envelope": [], "rejected": rejected,
            "audit": audit,
            # what a caller must do before anything of a partial answer is used; this module enforces none of it
            "requires": ["show every rejection with its reasons", "a person acknowledges the rejections",
                         "the engine validates what is kept, as it validates any proposal",
                         "nothing is applied, published or released by accepting a partial answer"] if rejected else []}
