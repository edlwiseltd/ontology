"""Ontology quality checks beyond hard validation.

Validation (in :mod:`autology.ontology`) rejects ontologies that are *wrong*.
Linting flags ontologies that are *risky*: security-by-design gaps, possible
bias, dead states, actions no tool can perform, and goals no agent can reach.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .ontology import STATUS, Ontology


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.code}: {self.message}"


def lint(ontology: Ontology, tools=None) -> List[Finding]:
    """Return findings; pass a :class:`~autology.tools.ToolRegistry` to also check tool coverage."""
    out: List[Finding] = []
    o = ontology

    # security by design ---------------------------------------------------
    read_guarded = {r.params["field"] for r in o.rules_of("data_access")}
    write_guarded = {r.params["field"] for r in o.rules_of("write_access")}
    for e in o.entities.values():
        for a in e.attributes.values():
            ref = f"{e.name}.{a.name}"
            if a.sensitivity in ("pii", "confidential") and ref not in read_guarded:
                out.append(Finding("warning", "SEC001", f"{ref} is {a.sensitivity} but no data_access rule guards it"))
            if a.sensitivity == "restricted" and ref not in write_guarded:
                writers = [x.name for x in o.actions.values() if ref in x.writes]
                if writers:
                    out.append(Finding("warning", "SEC002", f"{ref} is restricted but writable by {writers} "
                                                            "without a write_access rule"))

    # bias -----------------------------------------------------------------
    protected = {f"{e.name}.{a.name}" for e in o.entities.values() for a in e.attributes.values()
                 if a.sensitivity == "protected"}
    conditions = [(f"rule {r.id}", r.when) for r in o.rules] + \
                 [(f"action {a.name}", ex) for a in o.actions.values() for ex in a.requires]
    for where, expr in conditions:
        if expr is None:
            continue
        hits = sorted(f"{e}.{at}" for e, at in expr.references if f"{e}.{at}" in protected)
        if hits:
            out.append(Finding("warning", "BIAS001", f"{where} decides on protected attribute(s) {hits}: "
                                                     "review for disparate impact"))
    # numeric cut-offs only matter for bias when they decide about a party (an entity holding personal data)
    parties = {e.name for e in o.entities.values()
               if any(a.sensitivity in ("pii", "protected") for a in e.attributes.values())}
    for r in o.rules:
        if r.when is not None and r.kind in ("prohibition", "action_access", "human_review"):
            numeric = [f"{e}.{at}" for e, at in r.when.references
                       if e in parties and (attr := o.attribute(f"{e}.{at}")) and attr.type in ("number", "integer")]
            if numeric and r.kind == "prohibition":
                out.append(Finding("info", "BIAS002", f"rule {r.id} excludes cases by numeric threshold on "
                                                      f"{numeric}; confirm it does not disadvantage a segment"))

    # structure ------------------------------------------------------------
    produced = {(ent, ch[STATUS]) for a in o.actions.values() for out_ in a.outcomes
                for ent, ch in out_.effects.items() if STATUS in ch}
    for e in o.entities.values():
        for s in e.states:
            if s != e.initial_state and s not in e.external_states and (e.name, s) not in produced:
                out.append(Finding("info", "STR001", f"state {e.name}:{s} is never produced by any action "
                                                     "(declare it in external_states if another system sets it)"))
    related = {r.source for r in o.relationships} | {r.target for r in o.relationships}
    for e in o.entities:
        if o.relationships and e not in related:
            out.append(Finding("info", "STR002", f"entity {e} has no relationships"))
    for g in o.goals.values():
        targets = {(ent, attr) for ent, attr in g.target.references}
        reachable = any((ent, attr) in {(ex_ent, ex_attr) for a in o.actions.values() for oc in a.outcomes
                                         for ex_ent, ch in oc.effects.items() for ex_attr in ch}
                        for ent, attr in targets)
        if not reachable:
            out.append(Finding("warning", "STR003", f"goal {g.name}: no action changes {sorted(targets)}"))
    if not o.questions:
        out.append(Finding("info", "CQ001", "no competency questions declared"))

    # tools ------------------------------------------------------------------
    if tools is not None:
        names = {t.name for t in tools}
        caps = set(tools.capabilities())
        for a in o.actions.values():
            if a.capability not in caps:
                out.append(Finding("error", "TOOL001", f"no tool provides {a.capability} for action {a.name}"))
            for t in a.tools:
                if t not in names:
                    out.append(Finding("warning", "TOOL002", f"action {a.name} allows unknown tool {t!r}"))
    # semantic fragmentation: two entity types that look like one concept under two names
    names = sorted(o.entities)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ea, eb = set(o.entities[a].attributes), set(o.entities[b].attributes)
            shared = ea & eb
            if len(shared) >= 3 and len(shared) / len(ea | eb) >= 0.8:
                out.append(Finding("warning", "DUP001", f"{a} and {b} share {len(shared)} of {len(ea | eb)} attributes "
                                   f"({', '.join(sorted(shared)[:5])}): if they are one concept, merge them and list "
                                   "the other name under 'aliases'"))
    return out


def worst(findings: List[Finding]) -> Optional[str]:
    order = {"info": 0, "warning": 1, "error": 2}
    return max((f.level for f in findings), key=order.__getitem__, default=None)
