"""Ontology layer: a formal, machine-readable model of the business.

An ontology describes *what* the business is and *what is allowed* - nouns,
verbs and rules - never *how* a specific process must be walked:

* **entities**      - business objects (Customer, Contract, ...) with typed
                      attributes (optionally tagged ``pii``/``restricted``/
                      ``protected``) and a lifecycle (``status``) state set;
* **relationships** - first-class links (Customer -hasContract-> Contract);
* **actions**       - verbs with preconditions, possible outcomes and effects,
                      the capability a tool must provide, an optional tool
                      allow-list and a failure (self-healing) policy;
* **goals**         - target conditions an agent can be asked to reach;
* **rules**         - immutable governance policies (mandatory steps, human
                      review, data/action/write access, prohibitions);
* **competency questions** - the questions the model must be able to answer,
                      checked statically and against sample data.

Ontologies are **modular**: a document may ``import`` other module files
(``ProcurementOntology`` + ``CustomerOntology`` -> enterprise ontology).
A loaded ontology is validated, deeply frozen and content-fingerprinted;
change means publishing a new version (see :mod:`autology.versioning`).
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .expressions import Expression, ExpressionError, compile_expression

STATUS = "status"
ID = "id"
PARAMS = "Params"  # pseudo-entity for competency-question parameters

RULE_KINDS = frozenset({"mandatory_step", "human_review", "data_access", "write_access", "action_access",
                        "prohibition"})
AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})


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
    sensitivity: Optional[str] = None  # "pii", "restricted", "protected" (bias-relevant), ...
    description: str = ""


@dataclass(frozen=True)
class EntityType:
    name: str
    attributes: Mapping[str, Attribute]
    states: Tuple[str, ...]
    initial_state: str
    description: str = ""
    external_states: Tuple[str, ...] = ()  # states set by outside systems (ETL, sensors), not by actions

    def has_attribute(self, attr: str) -> bool:
        return attr in (STATUS, ID) or attr in self.attributes


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
class FailurePolicy:
    """Self-healing: how an agent reacts when every tool for an action fails.

    ``max_attempts`` rounds are tried (each round tries the primary tool and, if
    ``fallback_tools``, every other eligible tool). ``fallback_after`` keeps the first
    rounds primary-only - retry the cheap tool before paying for the expensive
    fallback. Between rounds the agent waits ``backoff_seconds`` - inline if short,
    otherwise it *defers* the case and can be resumed later. After the last round it
    escalates to ``escalate_to``.
    """

    max_attempts: int = 3
    backoff_seconds: float = 0.0
    fallback_tools: bool = True
    escalate_to: str = "operations"
    fallback_after: int = 0


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
    tools: Tuple[str, ...] = ()  # allow-list of tool names; empty = any tool with the capability
    on_failure: FailurePolicy = FailurePolicy()

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


@dataclass(frozen=True)
class CompetencyQuestion:
    """A question the ontology must be able to answer, e.g. "Which contracts expire in 30 days?".

    ``find`` instances of an entity filtered by ``where``, then ``follow`` relationship
    kinds (prefix ``^`` to walk a relationship backwards), filter the reached instances
    with ``result_where`` and optionally ``aggregate`` them (``{"sum": "Order.amount"}``).
    ``Params.<name>`` in conditions refers to ``params``.
    """

    id: str
    question: str
    find: str
    where: Optional[Expression] = None
    follow: Tuple[str, ...] = ()
    result_where: Optional[Expression] = None
    aggregate: Optional[Tuple[str, Optional[str]]] = None  # (function, "Entity.attr" | None)
    params: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    expect: Any = None  # expected answer against the sample data (ids or a number)


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
        questions: Iterable[CompetencyQuestion] = (),
        modules: Iterable[str] = (),
        settings: Optional[Mapping[str, Any]] = None,
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
        self.questions = tuple(questions)
        self.modules = tuple(modules)
        self.settings = _freeze(dict(settings or {}))
        self.source = _freeze(copy.deepcopy(dict(source)) if source is not None else {"name": name})
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

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    # -- queries --------------------------------------------------------
    def rules_of(self, kind: str) -> Tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.kind == kind)

    def attribute(self, ref: str) -> Optional[Attribute]:
        entity, _, attr = ref.partition(".")
        etype = self.entities.get(entity)
        return etype.attributes.get(attr) if etype else None

    def relationship(self, entity: str, step: str) -> Tuple[Relationship, str]:
        """Resolve a traversal step (``kind`` or ``^kind``) from ``entity``; returns (relationship, next entity)."""
        reverse = step.startswith("^")
        kind = step.lstrip("^")
        for rel in self.relationships:
            if rel.kind == kind and (rel.target if reverse else rel.source) == entity:
                return rel, (rel.source if reverse else rel.target)
        raise OntologyError(f"no relationship {step!r} from {entity!r}")

    def describe(self) -> str:
        """Human/LLM-readable summary of the ontology."""
        lines = [f"Ontology {self.ref}: {self.description}".rstrip(": ")]
        if self.modules:
            lines.append(f"Modules: {', '.join(self.modules)}")
        lines.append("Entities:")
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
    def _check_ref(self, entity: str, attr: str, where: str, allow_params: bool = False) -> None:
        if allow_params and entity == PARAMS:
            return
        etype = self.entities.get(entity)
        if etype is None:
            raise OntologyError(f"{where}: unknown entity {entity!r}")
        if not etype.has_attribute(attr):
            raise OntologyError(f"{where}: entity {entity!r} has no attribute {attr!r}")

    def _check_expr(self, expr: Optional[Expression], where: str, allow_params: bool = False,
                    only: Optional[str] = None) -> None:
        if expr is None:
            return
        for entity, attr in expr.references:
            self._check_ref(entity, attr, where, allow_params)
            if only and entity not in (only, PARAMS):
                raise OntologyError(f"{where}: condition may only reference {only} (or Params), not {entity}")

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
            unknown = set(e.external_states) - set(e.states)
            if unknown:
                raise OntologyError(f"entity {e.name!r}: external states {sorted(unknown)} not in states")
        for r in self.relationships:
            for end in (r.source, r.target):
                if end not in self.entities:
                    raise OntologyError(f"relationship {r.kind!r}: unknown entity {end!r}")
        for a in self.actions.values():
            where = f"action {a.name!r}"
            if not a.outcomes:
                raise OntologyError(f"{where}: must declare at least one outcome")
            if a.on_failure.max_attempts < 1:
                raise OntologyError(f"{where}: on_failure.max_attempts must be >= 1")
            if not 0 <= a.on_failure.fallback_after < a.on_failure.max_attempts:
                raise OntologyError(f"{where}: on_failure.fallback_after must be between 0 and max_attempts - 1")
            for expr in a.requires:
                self._check_expr(expr, where)
            for ref in a.reads + a.writes:
                self._check_field(ref, where)
            for ref in a.writes:
                if ref.endswith("." + STATUS) or ref.endswith("." + ID):
                    raise OntologyError(f"{where}: {ref} may only change through outcomes")
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
                    try:
                        self.actions[p["step"]].outcome(p["outcome"])
                    except KeyError as exc:
                        raise OntologyError(f"{where}: {exc.args[0]}") from None
            elif r.kind in ("human_review", "prohibition", "action_access"):
                if p.get("action") not in self.actions:
                    raise OntologyError(f"{where}: 'action' must name an action")
                if r.kind == "human_review" and not p.get("reviewer"):
                    raise OntologyError(f"{where}: human_review needs a 'reviewer' role")
            if r.kind in ("data_access", "write_access"):
                self._check_field(p.get("field", ""), where)
            if r.kind in ("data_access", "write_access", "action_access") and not p.get("roles"):
                raise OntologyError(f"{where}: {r.kind} needs a non-empty 'roles' list")
        qids = set()
        for q in self.questions:
            where = f"competency question {q.id!r}"
            if q.id in qids:
                raise OntologyError(f"{where}: duplicate id")
            qids.add(q.id)
            if q.find not in self.entities:
                raise OntologyError(f"{where}: unknown entity {q.find!r}")
            self._check_expr(q.where, where, allow_params=True, only=q.find)
            current = q.find
            for step in q.follow:
                _, current = self.relationship(current, step)
            self._check_expr(q.result_where, where, allow_params=True, only=current)
            if q.aggregate:
                fn, target = q.aggregate
                if fn not in AGGREGATES:
                    raise OntologyError(f"{where}: unknown aggregate {fn!r}")
                if fn != "count":
                    if not target or not target.startswith(current + "."):
                        raise OntologyError(f"{where}: {fn} needs a field of {current}")
                    self._check_field(target, where)
        mv = self.settings.get("max_violations")
        if mv is not None and (not isinstance(mv, int) or mv < 1):
            raise OntologyError("settings.max_violations must be a positive integer")

    # -- loading --------------------------------------------------------
    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> "Ontology":
        try:
            return cls._from_dict(doc)
        except ExpressionError as exc:
            raise OntologyError(str(exc)) from None
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            if isinstance(exc, OntologyError):
                raise
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
                                        spec.get("description", ""), tuple(spec.get("external_states", ())))
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
            failure = spec.get("on_failure", {})
            actions[name] = ActionType(
                name=name,
                description=spec.get("description", ""),
                capability=spec.get("capability", name),
                requires=tuple(compile_expression(r) for r in requires),
                outcomes=outcomes,
                reads=tuple(spec.get("reads", ())),
                writes=tuple(spec.get("writes", ())),
                cost=int(spec.get("cost", 1)),
                tools=tuple(spec.get("tools", ())),
                on_failure=FailurePolicy(int(failure.get("max_attempts", 3)),
                                         float(failure.get("backoff_seconds", 0)),
                                         bool(failure.get("fallback_tools", True)),
                                         str(failure.get("escalate_to", "operations")),
                                         int(failure.get("fallback_after", 0))),
            )
        goals = {name: Goal(name, spec.get("description", ""), compile_expression(spec["target"]))
                 for name, spec in doc.get("goals", {}).items()}
        rules: List[Rule] = []
        for spec in doc.get("rules", []):
            params = {k: v for k, v in spec.items() if k not in ("id", "type", "description", "when")}
            when = spec.get("when")
            rules.append(Rule(spec["id"], spec["type"], spec.get("description", ""),
                              compile_expression(when) if when else None, _freeze(params)))
        questions = []
        for spec in doc.get("competency_questions", []):
            agg = spec.get("aggregate")
            aggregate = None
            if agg:
                (fn, target), = agg.items()
                aggregate = (fn, None if fn == "count" else target)
            questions.append(CompetencyQuestion(
                spec["id"], spec.get("question", ""), spec["find"],
                compile_expression(spec["where"]) if spec.get("where") else None,
                tuple(spec.get("follow", ())),
                compile_expression(spec["result_where"]) if spec.get("result_where") else None,
                aggregate, _freeze(spec.get("params", {})), spec.get("expect")))
        source = {k: v for k, v in doc.items() if k != "imports"}
        return cls(doc["name"], str(doc.get("version", "0")), entities, relationships, actions, goals,
                   rules, doc.get("description", ""), source=source, questions=questions,
                   modules=doc.get("modules", ()), settings=doc.get("settings"))

    @classmethod
    def load(cls, path: str | Path) -> "Ontology":
        """Load an ontology file, resolving ``imports`` of module files (relative to the importer)."""
        return cls.from_dict(load_document(path))


# -- modules ------------------------------------------------------------------
_MERGE_MAPS = ("entities", "actions", "goals")
_SINGULAR = {"entities": "entity", "actions": "action", "goals": "goal"}


def _read(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # optional dependency
        except ImportError as exc:  # pragma: no cover
            raise OntologyError("install PyYAML to load YAML ontologies, or use JSON") from exc
        return yaml.safe_load(text)
    return json.loads(text)


def merge_documents(root: Mapping[str, Any], modules: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Compose module documents under ``root``. Duplicate definitions must be identical."""
    merged: Dict[str, Any] = {k: copy.deepcopy(v) for k, v in root.items()
                              if k not in _MERGE_MAPS + ("relationships", "rules", "competency_questions",
                                                         "imports")}
    for key in _MERGE_MAPS:
        merged[key] = {}
    merged["relationships"], merged["rules"], merged["competency_questions"] = [], [], []
    module_refs: List[str] = []
    for doc in list(modules) + [root]:
        if doc is not root:
            module_refs.append(f"{doc.get('name', '?')}@{doc.get('version', '0')}")
        origin = doc.get("name", "?")
        for key in _MERGE_MAPS:
            for name, spec in doc.get(key, {}).items():
                if name in merged[key] and merged[key][name] != spec:
                    raise OntologyError(f"module {origin!r} redefines {_SINGULAR[key]} {name!r} differently")
                merged[key][name] = copy.deepcopy(spec)
        for rel in doc.get("relationships", []):
            if rel not in merged["relationships"]:
                merged["relationships"].append(copy.deepcopy(rel))
        for listkey in ("rules", "competency_questions"):
            existing = {item["id"]: item for item in merged[listkey]}
            for item in doc.get(listkey, []):
                if item["id"] in existing:
                    if existing[item["id"]] != item:
                        raise OntologyError(f"module {origin!r} redefines {listkey[:-1]} {item['id']!r} differently")
                    continue
                merged[listkey].append(copy.deepcopy(item))
                existing[item["id"]] = item
    merged["modules"] = list(dict.fromkeys(module_refs))
    return merged


def load_document(path: str | Path, _stack: Tuple[Path, ...] = ()) -> Dict[str, Any]:
    """Read an ontology document and (recursively) merge its ``imports``."""
    path = Path(path).resolve()
    if path in _stack:
        raise OntologyError(f"circular import: {' -> '.join(p.name for p in _stack + (path,))}")
    doc = _read(path)
    imports = doc.get("imports", [])
    if not imports:
        return doc
    modules: List[Dict[str, Any]] = []
    for rel in imports:
        sub = load_document(path.parent / rel, _stack + (path,))
        # flatten: a sub-module's own modules come first
        for ref in sub.pop("modules", []):
            name, _, version = ref.partition("@")
            modules.append({"name": name, "version": version})
        modules.append(sub)
    return merge_documents(doc, modules)
