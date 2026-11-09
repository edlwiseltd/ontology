"""Ontology version control: semantic diffs, semver discipline and a publishing registry.

Agents pin an ontology version. Publishing a new version goes through
:class:`OntologyRegistry`, which classifies every change and refuses a
release whose version bump understates it:

* **major** - something agents or tools may depend on was removed/changed
  (entity, attribute, state, action, outcome, capability, goal, relationship);
* **minor** - additions, and governance changes (rules added/changed/removed -
  behaviour changes even when the schema does not);
* **patch** - descriptions only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .ontology import Ontology

LEVELS = {"patch": 0, "minor": 1, "major": 2}


class VersionError(ValueError):
    pass


@dataclass(frozen=True)
class Change:
    level: str  # patch | minor | major
    kind: str  # e.g. "entity.removed", "rule.added"
    item: str
    detail: str = ""

    def __str__(self) -> str:
        return f"[{self.level}] {self.kind}: {self.item}" + (f" - {self.detail}" if self.detail else "")


def parse_version(version: str) -> Tuple[int, int, int]:
    try:
        parts = [int(p) for p in version.split(".")]
    except ValueError:
        raise VersionError(f"version {version!r} is not semantic (MAJOR.MINOR.PATCH)") from None
    if len(parts) != 3:
        raise VersionError(f"version {version!r} is not semantic (MAJOR.MINOR.PATCH)")
    return parts[0], parts[1], parts[2]


def diff(old: Ontology, new: Ontology) -> List[Change]:
    changes: List[Change] = []

    def keyed(kind: str, a: Dict, b: Dict, removed: str = "major", added: str = "minor"):
        for name in sorted(set(a) - set(b)):
            changes.append(Change(removed, f"{kind}.removed", name))
        for name in sorted(set(b) - set(a)):
            changes.append(Change(added, f"{kind}.added", name))
        return sorted(set(a) & set(b))

    for name in keyed("entity", dict(old.entities), dict(new.entities)):
        o, n = old.entities[name], new.entities[name]
        for attr in keyed("attribute", {f"{name}.{k}": v for k, v in o.attributes.items()},
                          {f"{name}.{k}": v for k, v in n.attributes.items()}):
            oa, na = o.attributes[attr.split(".")[1]], n.attributes[attr.split(".")[1]]
            if oa.type != na.type:
                changes.append(Change("major", "attribute.type_changed", attr, f"{oa.type} -> {na.type}"))
            if oa.sensitivity != na.sensitivity:
                changes.append(Change("minor", "attribute.sensitivity_changed", attr,
                                      f"{oa.sensitivity} -> {na.sensitivity}"))
        keyed("state", {f"{name}:{s}": 1 for s in o.states}, {f"{name}:{s}": 1 for s in n.states})
        if o.initial_state != n.initial_state:
            changes.append(Change("major", "entity.initial_state_changed", name,
                                  f"{o.initial_state} -> {n.initial_state}"))

    rel = lambda onto: {f"{r.source}-{r.kind}->{r.target}": r for r in onto.relationships}  # noqa: E731
    keyed("relationship", rel(old), rel(new))

    for name in keyed("action", dict(old.actions), dict(new.actions)):
        o, n = old.actions[name], new.actions[name]
        keyed("outcome", {f"{name}:{x.name}": 1 for x in o.outcomes}, {f"{name}:{x.name}": 1 for x in n.outcomes})
        if o.capability != n.capability:
            changes.append(Change("major", "action.capability_changed", name, f"{o.capability} -> {n.capability}"))
        if [str(e) for e in o.requires] != [str(e) for e in n.requires]:
            changes.append(Change("minor", "action.preconditions_changed", name))
        if o.outcomes and n.outcomes and o.expected_outcome.name != n.expected_outcome.name:
            changes.append(Change("minor", "action.expected_outcome_changed", name))
        if {x.name: dict(x.effects) for x in o.outcomes} != {x.name: dict(x.effects) for x in n.outcomes}:
            changes.append(Change("minor", "action.effects_changed", name))
        if (o.reads, o.writes, o.tools, o.on_failure, o.cost) != (n.reads, n.writes, n.tools, n.on_failure, n.cost):
            changes.append(Change("minor", "action.contract_changed", name, "reads/writes/tools/failure policy/cost"))
        if o.description != n.description:
            changes.append(Change("patch", "action.description_changed", name))

    for name in keyed("goal", dict(old.goals), dict(new.goals)):
        if str(old.goals[name].target) != str(new.goals[name].target):
            changes.append(Change("major", "goal.target_changed", name))

    orules, nrules = {r.id: r for r in old.rules}, {r.id: r for r in new.rules}
    for rid in keyed("rule", orules, nrules, removed="minor", added="minor"):
        o, n = orules[rid], nrules[rid]
        if (o.kind, str(o.when), dict(o.params)) != (n.kind, str(n.when), dict(n.params)):
            changes.append(Change("minor", "rule.changed", rid))
        elif o.description != n.description:
            changes.append(Change("patch", "rule.description_changed", rid))

    keyed("competency_question", {q.id: q for q in old.questions}, {q.id: q for q in new.questions},
          removed="minor", added="minor")
    if old.description != new.description:
        changes.append(Change("patch", "ontology.description_changed", old.name))
    return changes


def required_bump(changes: List[Change]) -> Optional[str]:
    if not changes:
        return None
    return max((c.level for c in changes), key=LEVELS.__getitem__)


def actual_bump(old: str, new: str) -> Optional[str]:
    o, n = parse_version(old), parse_version(new)
    if n <= o:
        return None
    if n[0] > o[0]:
        return "major"
    if n[1] > o[1]:
        return "minor"
    return "patch"


def check_release(old: Ontology, new: Ontology) -> List[Change]:
    """Raise :class:`VersionError` if ``new.version`` understates the changes since ``old``."""
    changes = diff(old, new)
    needed = required_bump(changes)
    if needed is None:
        if new.version != old.version and actual_bump(old.version, new.version) is None:
            raise VersionError(f"{new.version} is not newer than {old.version}")
        return changes
    got = actual_bump(old.version, new.version)
    if got is None:
        raise VersionError(f"{new.name}: changes require a {needed} release but version did not increase "
                           f"({old.version} -> {new.version})")
    if LEVELS[got] < LEVELS[needed]:
        breaking = "; ".join(str(c) for c in changes if c.level == needed)
        raise VersionError(f"{new.name}: {old.version} -> {new.version} is a {got} release but changes require "
                           f"{needed}: {breaking}")
    return changes


class OntologyRegistry:
    """Published ontology versions. Agents pin ``name@version``; versions can be withdrawn."""

    def __init__(self) -> None:
        self._versions: Dict[str, Dict[str, Ontology]] = {}
        self._withdrawn: Dict[str, set] = {}
        self.changelog: Dict[str, List[Change]] = {}

    def publish(self, ontology: Ontology) -> List[Change]:
        parse_version(ontology.version)
        versions = self._versions.setdefault(ontology.name, {})
        if ontology.version in versions:
            raise VersionError(f"{ontology.ref} is already published")
        changes: List[Change] = []
        latest = self.latest(ontology.name)
        if latest is not None:
            if parse_version(ontology.version) < parse_version(latest.version):
                raise VersionError(f"{ontology.ref} is older than the latest {latest.ref}")
            changes = check_release(latest, ontology)
        versions[ontology.version] = ontology
        self.changelog[ontology.ref] = changes
        return changes

    def withdraw(self, name: str, version: str) -> None:
        self._withdrawn.setdefault(name, set()).add(version)

    def available(self, name: str, version: str) -> bool:
        return version in self._versions.get(name, {}) and version not in self._withdrawn.get(name, set())

    def get(self, name: str, version: Optional[str] = None) -> Ontology:
        if version is None:
            latest = self.latest(name)
            if latest is None:
                raise KeyError(f"no published versions of {name!r}")
            return latest
        if not self.available(name, version):
            raise KeyError(f"{name}@{version} is not available")
        return self._versions[name][version]

    def latest(self, name: str) -> Optional[Ontology]:
        live = [v for v in self._versions.get(name, {}) if v not in self._withdrawn.get(name, set())]
        if not live:
            return None
        return self._versions[name][max(live, key=parse_version)]
