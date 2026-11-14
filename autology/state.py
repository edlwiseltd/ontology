"""World state: the live facts of one business case (e.g. onboarding customer XYZ).

Single-instance entities (the Customer, the Contract...) live in
``entities[type]``. Entities the ontology marks ``multiple`` (several orders
under one contract, several lines on an order) live in
``collections[type][instance_id]``. Expressions are evaluated through a
:class:`Resolver`, optionally *bound* to one instance per multi-instance type
(the instance an action is working on); quantifiers such as
``all_of(Order.status == 'placed')`` iterate over the instances.

The state also remembers the latest outcome of each step - keyed by action,
or ``action@instance`` for per-instance actions - which the governance layer
uses to enforce mandatory steps.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .ontology import ID, STATUS, Ontology, OntologyError, check_types


def ground_name(action: str, target: Optional[str]) -> str:
    return f"{action}@{target}" if target else action


def parse_ground(name: str) -> Tuple[str, Optional[str]]:
    action, sep, target = name.partition("@")
    return action, (target if sep else None)


class Resolver:
    """Callable ``(entity, attr) -> value`` with a binding of multi-instance entities to instances."""

    __slots__ = ("state", "binding")

    def __init__(self, state: "WorldState", binding: Optional[Mapping[str, str]] = None):
        self.state = state
        self.binding = dict(binding or {})

    def __call__(self, entity: str, attr: str) -> Any:
        if entity in self.state.collections:
            iid = self.binding.get(entity)
            if iid is None:
                return None
            if attr == ID:
                return iid
            return self.state.collections[entity].get(iid, {}).get(attr)
        return self.state.entities.get(entity, {}).get(attr)

    def each(self, entity: str) -> Optional[List["Resolver"]]:
        """Resolvers for every instance of a multi-instance entity (None for single-instance entities)."""
        if entity not in self.state.collections:
            return None
        return [Resolver(self.state, {**self.binding, entity: iid}) for iid in sorted(self.state.collections[entity])]


class WorldState:
    def __init__(self, entities: Dict[str, Dict[str, Any]], steps: Optional[Dict[str, str]] = None,
                 collections: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None):
        self.entities = entities
        self.collections: Dict[str, Dict[str, Dict[str, Any]]] = collections if collections is not None else {}
        self.steps: Dict[str, str] = dict(steps or {})  # action (or action@instance) -> latest outcome

    @staticmethod
    def _values(etype, given: Mapping[str, Any], where: str) -> Dict[str, Any]:
        unknown = [k for k in given if not etype.has_attribute(k)]
        if unknown:
            raise OntologyError(f"case data for {where} has unknown attributes {unknown}")
        check_types(etype, given, f"case data for {where}")
        values = {attr: None for attr in etype.attributes}
        values.update(given)
        if values.get(STATUS) is None:
            values[STATUS] = etype.initial_state
        if values[STATUS] not in etype.states:
            raise OntologyError(f"case data for {where}: {values[STATUS]!r} is not a state of {etype.name}")
        return values

    @classmethod
    def initial(cls, ontology: Ontology, case: Mapping[str, Any]) -> "WorldState":
        case = ontology.canonical_case(case)  # any team's name for an entity
        extra = set(case) - set(ontology.entities)
        if extra:
            raise OntologyError(f"case data references unknown entities {sorted(extra)}")
        entities: Dict[str, Dict[str, Any]] = {}
        collections: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for name, etype in ontology.entities.items():
            given = case.get(name)
            if etype.multiple:
                items = given or []
                if isinstance(items, Mapping):
                    raise OntologyError(f"case data for {name} must be a list of instances (it is marked multiple)")
                bucket: Dict[str, Dict[str, Any]] = {}
                for i, item in enumerate(items, 1):
                    item = dict(item)
                    iid = str(item.pop(ID, None) or f"{name}-{i}")
                    if iid in bucket:
                        raise OntologyError(f"case data for {name}: duplicate id {iid!r}")
                    bucket[iid] = cls._values(etype, item, f"{name} {iid!r}")
                collections[name] = bucket
            else:
                if given is not None and not isinstance(given, Mapping):
                    raise OntologyError(f"case data for {name} must be an object")
                if given is None and etype.when_absent != "initial":
                    # no such record in the case: nothing about it may be assumed (audit GAP-017)
                    entities[name] = {attr: None for attr in etype.attributes}
                    entities[name][STATUS] = None
                else:
                    entities[name] = cls._values(etype, dict(given or {}), repr(name))
        return cls(entities, collections=collections)

    # -- access ---------------------------------------------------------
    def resolver(self, binding: Optional[Mapping[str, str]] = None) -> Resolver:
        return Resolver(self, binding)

    def get(self, entity: str, attr: str, instance: Optional[str] = None) -> Any:
        if entity in self.collections:
            return self.collections[entity].get(instance, {}).get(attr) if instance else None
        return self.entities.get(entity, {}).get(attr)

    def field(self, ref: str, binding: Optional[Mapping[str, str]] = None) -> Any:
        entity, _, attr = ref.partition(".")
        return self.resolver(binding)(entity, attr)

    def set(self, entity: str, attr: str, value: Any, instance: Optional[str] = None) -> None:
        if entity in self.collections:
            if instance is None:
                raise OntologyError(f"{entity} is multi-instance: say which instance to change")
            self.collections[entity][instance][attr] = value
        else:
            self.entities[entity][attr] = value

    def instances(self, entity: str) -> List[str]:
        return sorted(self.collections.get(entity, {}))

    def copy(self) -> "WorldState":
        """Two-level copy: attribute values are replaced, never mutated in place, by planning and actions."""
        return WorldState({e: dict(v) for e, v in self.entities.items()}, self.steps,
                          {e: {i: dict(a) for i, a in b.items()} for e, b in self.collections.items()})

    def key(self) -> Tuple:
        """Hashable snapshot used by the planner for search."""
        return (json.dumps([self.entities, self.collections], sort_keys=True, default=str),
                tuple(sorted(self.steps.items())))

    def snapshot(self) -> Dict[str, Any]:
        snap = {"entities": copy.deepcopy(self.entities), "steps": dict(self.steps)}
        if self.collections:
            snap["collections"] = copy.deepcopy(self.collections)
        return snap

    def __repr__(self) -> str:
        statuses = [f"{e}={v.get(STATUS)}" for e, v in self.entities.items()]
        statuses += [f"{e}[{len(v)}]" for e, v in self.collections.items()]
        return f"WorldState({', '.join(statuses)})"


class GroundAction:
    """An action bound to the instance it works on (``ship_order@O-2``), or a plain action.

    Behaves like its :class:`~autology.ontology.ActionType` (``description``, ``outcomes``,
    ``reads``...) but has a ground ``name`` and a ``binding`` for evaluating its conditions.
    """

    __slots__ = ("action", "target")

    def __init__(self, action, target: Optional[str] = None):
        self.action = action
        self.target = target

    @property
    def name(self) -> str:
        return ground_name(self.action.name, self.target)

    @property
    def binding(self) -> Dict[str, str]:
        return {self.action.for_each: self.target} if self.target and self.action.for_each else {}

    def __getattr__(self, item: str):
        return getattr(self.action, item)

    def __eq__(self, other) -> bool:
        return isinstance(other, GroundAction) and (self.action.name, self.target) == (other.action.name, other.target)

    def __hash__(self) -> int:
        return hash((self.action.name, self.target))

    def __repr__(self) -> str:
        return f"GroundAction({self.name})"


def ground(ontology: Ontology, action, state: Optional[WorldState] = None,
           target: Optional[str] = None) -> GroundAction:
    """Resolve an action name (``x`` or ``x@instance``), ActionType or GroundAction into a GroundAction."""
    if isinstance(action, GroundAction):
        return action
    if isinstance(action, str):
        name, parsed = parse_ground(action)
        target = target or parsed
        if name not in ontology.actions:
            raise KeyError(name)
        action = ontology.actions[name]
    return GroundAction(action, target)
