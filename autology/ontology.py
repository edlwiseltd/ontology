"""Ontology layer: a formal, machine-readable model of the business.

An ontology describes *what* the business is and *what is allowed*, never
*how* a specific process must be walked. It contains:

* **entities**      - business objects (Customer, Contract, ...) with typed
                      attributes and a lifecycle (``status``) state set;
* **relationships** - how entities relate (Customer -has-> Contract);
* **actions**       - units of work with preconditions, possible outcomes and
                      their effects, plus the capability a tool must provide;
* **goals**         - target conditions an agent can be asked to reach;
* **rules**         - immutable governance policies (mandatory steps,
                      human review, data access, prohibitions).

Agents plan over this model at run time, so changing the business means
changing the ontology - not rewiring workflows. A loaded ontology is deeply
frozen and fingerprinted; the governance layer refuses to operate if the
fingerprint changes underneath it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .expressions import Expression, ExpressionError, compile_expression

STATUS = "status"

RULE_KINDS = frozenset({"mandatory_step", "human_review", "data_access", "prohibition"})


class OntologyError(ValueError):
    """Raised when an ontology document is malformed or internally inconsistent."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class Attribute:
    name: str
    type: str = "string"
    sensitivity: Optional[str] = None  # e.g. "pii", "confidential"
    description: str = ""


@dataclass(frozen=True)
class EntityType:
    name: str
    attributes: Mapping[str, Attribute]
    states: Tuple[str, ...]
    initial_state: str
    description: str = ""

    def has_attribute(self, attr: str) -> bool:
        return attr == STATUS or attr in self.attributes


@dataclass(frozen=True)
class Relationship:
    source: str
    target: str
    kind: str
    cardinality: str = "1..*"


@dataclass(frozen=True)
class Outcome:
    name: str
    effects: Mapping[str, Mapping[str, Any]]  # entity -> attribute -> value
    description: str = ""


@dataclass(frozen=True)
class ActionType:
    name: str
    description: str
    capability: str
    requires: Tuple[Expression, ...]
    outcomes: Tuple[Outcome, ...]  # the first outcome is the expected (planning) outcome
    reads: Tuple[str, ...] = ()  # "Entity.attribute" fields passed to tools
    writes: Tuple[str, ...] = ()  # non-status fields a tool may update
    cost: int = 1

    @property
    def expected_outcome(self) -> Outcome:
        return self.outcomes[0]

    def outcome(self, name: str) -> Outcome:
        for outcome in self.outcomes:
            if outcome.name == name:
                return outcome
        raise KeyError(f"action {self.name!r} has no outcome {name!r}")


@dataclass(frozen=True)
class Goal:
    name: str
    description: str
    target: Expression


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    description: str
    when: Optional[Expression] = None
    params: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def applies(self, resolve) -> bool:
        return self.when is None or self.when.evaluate(resolve)


class Ontology:
    """An immutable, validated business ontology."""

    def __init__(
        self,
        name: str,
        version: str,
        entities: Mapping[str, EntityType],
        relationships: Iterable[Relationship],
        actions: Mapping[str, ActionType],
        goals: Mapping[str, Goal],
        rules: Iterable[Rule],
        description: str = "",
        source: Optional[Mapping[str, Any]] = None,
    ):
        object.__setattr__(self, "_frozen", False)
        self.name = name
        self.version = version
        self.description = description
        self.entities = MappingProxyType(dict(entities))
        self.relationships = tuple(relationships)
        self.actions = MappingProxyType(dict(actions))
        self.goals = MappingProxyType(dict(goals))
        self.rules = tuple(rules)
        canonical = json.dumps(source if source is not None else {"name": name, "version": version},
                               sort_keys=True, separators=(",", ":"), default=str)
        self.fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        self._validate()
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, key: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("ontologies are immutable; publish a new version instead")
        object.__setattr__(self, key, value)

    def __delattr__(self, key: str) -> None:
        raise AttributeError("ontologies are immutable; publish a new version instead")

    # -- queries --------------------------------------------------------
    def rules_of(self, kind: str) -> Tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.kind == kind)

    def attribute(self, ref: str) -> Optional[Attribute]:
        entity, _, attr = ref.partition(".")
        etype = self.entities.get(entity)
        return etype.attributes.get(attr) if etype else None

    def describe(self) -> str:
        """Human/LLM-readable summary of the ontology."""
        lines = [f"Ontology {self.name} v{self.version}: {self.description}".rstrip(": "), "Entities:"]
        for e in self.entities.values():
            attrs = ", ".join(e.attributes) or "-"
            lines.append(f"  - {e.name} [states: {', '.join(e.states)}] attributes: {attrs}")
        if self.relationships:
            lines.append("Relationships:")
            for r in self.relationships:
                lines.append(f"  - {r.source} -{r.kind}-> {r.target} ({r.cardinality})")
        lines.append("Actions:")
        for a in self.actions.values():
            outs = "/".join(o.name for o in a.outcomes)
            lines.append(f"  - {a.name}: {a.description} (outcomes: {outs})")
        lines.append("Rules:")
        for r in self.rules:
            lines.append(f"  - [{r.id}] {r.kind}: {r.description}")
        return "\n".join(lines)

    # -- validation -----------------------------------------------------
    def _check_ref(self, entity: str, attr: str, where: str) -> None:
        etype = self.entities.get(entity)
        if etype is None:
            raise OntologyError(f"{where}: unknown entity {entity!r}")
        if not etype.has_attribute(attr):
            raise OntologyError(f"{where}: entity {entity!r} has no attribute {attr!r}")

    def _check_expr(self, expr: Optional[Expression], where: str) -> None:
        if expr is None:
            return
        for entity, attr in expr.references:
            self._check_ref(entity, attr, where)

    def _check_field(self, ref: str, where: str) -> None:
        entity, dot, attr = ref.partition(".")
        if not dot:
            raise OntologyError(f"{where}: field {ref!r} must be Entity.attribute")
        self._check_ref(entity, attr, where)

    def _validate(self) -> None:
        for e in self.entities.values():
            if not e.states:
                raise OntologyError(f"entity {e.name!r} must declare at least one state")
            if e.initial_state not in e.states:
                raise OntologyError(f"entity {e.name!r}: initial state {e.initial_state!r} not in states")
        for r in self.relationships:
            for end in (r.source, r.target):
                if end not in self.entities:
                    raise OntologyError(f"relationship {r.kind!r}: unknown entity {end!r}")
        for a in self.actions.values():
            where = f"action {a.name!r}"
            if not a.outcomes:
                raise OntologyError(f"{where}: must declare at least one outcome")
            for expr in a.requires:
                self._check_expr(expr, where)
            for ref in a.reads + a.writes:
                self._check_field(ref, where)
            for ref in a.writes:
                if ref.endswith("." + STATUS):
                    raise OntologyError(f"{where}: lifecycle status may only change through outcomes")
            for o in a.outcomes:
                for entity, changes in o.effects.items():
                    for attr, value in changes.items():
                        self._check_ref(entity, attr, f"{where} outcome {o.name!r}")
                        if attr == STATUS and value not in self.entities[entity].states:
                            raise OntologyError(
                                f"{where} outcome {o.name!r}: {value!r} is not a state of {entity!r}")
        for g in self.goals.values():
            self._check_expr(g.target, f"goal {g.name!r}")
        seen = set()
        for r in self.rules:
            where = f"rule {r.id!r}"
            if r.id in seen:
                raise OntologyError(f"{where}: duplicate rule id")
            seen.add(r.id)
            if r.kind not in RULE_KINDS:
                raise OntologyError(f"{where}: unknown kind {r.kind!r} (expected one of {sorted(RULE_KINDS)})")
            self._check_expr(r.when, where)
            p = r.params
            if r.kind == "mandatory_step":
                for key in ("step", "before"):
                    if p.get(key) not in self.actions:
                        raise OntologyError(f"{where}: {key!r} must name an action")
                for name in p.get("reset_by", ()):
                    if name not in self.actions:
                        raise OntologyError(f"{where}: reset_by names unknown action {name!r}")
                if "outcome" in p:
                    self.actions[p["step"]].outcome(p["outcome"])
            elif r.kind in ("human_review", "prohibition"):
                if p.get("action") not in self.actions:
                    raise OntologyError(f"{where}: 'action' must name an action")
                if r.kind == "human_review" and not p.get("reviewer"):
                    raise OntologyError(f"{where}: human_review needs a 'reviewer' role")
            elif r.kind == "data_access":
                self._check_field(p.get("field", ""), where)
                if not p.get("roles"):
                    raise OntologyError(f"{where}: data_access needs a non-empty 'roles' list")

    # -- loading --------------------------------------------------------
    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> "Ontology":
        try:
            return cls._from_dict(doc)
        except ExpressionError as exc:
            raise OntologyError(str(exc)) from None
        except (KeyError, TypeError, AttributeError) as exc:
            raise OntologyError(f"malformed ontology document: {exc!r}") from None

    @classmethod
    def _from_dict(cls, doc: Mapping[str, Any]) -> "Ontology":
        entities: Dict[str, EntityType] = {}
        for name, spec in doc.get("entities", {}).items():
            attrs = {}
            for aname, aspec in spec.get("attributes", {}).items():
                if isinstance(aspec, str):
                    aspec = {"type": aspec}
                attrs[aname] = Attribute(aname, aspec.get("type", "string"), aspec.get("sensitivity"),
                                         aspec.get("description", ""))
            states = tuple(spec.get("states", ()))
            entities[name] = EntityType(name, MappingProxyType(attrs), states,
                                        spec.get("initial", states[0] if states else ""),
                                        spec.get("description", ""))
        relationships = [Relationship(r["from"], r["to"], r["type"], r.get("cardinality", "1..*"))
                         for r in doc.get("relationships", [])]
        actions: Dict[str, ActionType] = {}
        for name, spec in doc.get("actions", {}).items():
            outcomes_spec = spec.get("outcomes")
            if outcomes_spec is None:  # shorthand: a single "done" outcome
                outcomes_spec = {"done": {"effects": spec.get("effects", {})}}
            outcomes = tuple(
                Outcome(oname, _freeze(ospec.get("effects", {})), ospec.get("description", ""))
                for oname, ospec in outcomes_spec.items())
            requires = spec.get("requires", [])
            if isinstance(requires, str):
                requires = [requires]
            actions[name] = ActionType(
                name=name,
                description=spec.get("description", ""),
                capability=spec.get("capability", name),
                requires=tuple(compile_expression(r) for r in requires),
                outcomes=outcomes,
                reads=tuple(spec.get("reads", ())),
                writes=tuple(spec.get("writes", ())),
                cost=int(spec.get("cost", 1)),
            )
        goals = {name: Goal(name, spec.get("description", ""), compile_expression(spec["target"]))
                 for name, spec in doc.get("goals", {}).items()}
        rules: List[Rule] = []
        for spec in doc.get("rules", []):
            params = {k: v for k, v in spec.items() if k not in ("id", "type", "description", "when")}
            when = spec.get("when")
            rules.append(Rule(spec["id"], spec["type"], spec.get("description", ""),
                              compile_expression(when) if when else None, _freeze(params)))
        return cls(doc["name"], str(doc.get("version", "0")), entities, relationships, actions, goals,
                   rules, doc.get("description", ""), source=doc)

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            try:
                import yaml  # optional dependency
            except ImportError as exc:  # pragma: no cover
                raise OntologyError("install PyYAML to load YAML ontologies, or use JSON") from exc
            return cls.from_dict(yaml.safe_load(text))
        return cls.from_dict(json.loads(text))
