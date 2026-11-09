"""World state: the live facts of one business case (e.g. onboarding customer XYZ).

A case binds one instance of each entity type (the Customer, *their*
Contract, *their* Order...). The state also remembers the latest outcome of
each step, which the governance layer uses to enforce mandatory steps.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, Mapping, Optional, Tuple

from .ontology import STATUS, Ontology, OntologyError


class WorldState:
    def __init__(self, entities: Dict[str, Dict[str, Any]], steps: Optional[Dict[str, str]] = None):
        self.entities = entities
        self.steps: Dict[str, str] = dict(steps or {})  # action name -> latest outcome

    @classmethod
    def initial(cls, ontology: Ontology, case: Mapping[str, Mapping[str, Any]]) -> "WorldState":
        entities: Dict[str, Dict[str, Any]] = {}
        for name, etype in ontology.entities.items():
            given = dict(case.get(name, {}))
            unknown = [k for k in given if not etype.has_attribute(k)]
            if unknown:
                raise OntologyError(f"case data for {name!r} has unknown attributes {unknown}")
            values = {attr: None for attr in etype.attributes}
            values.update(given)
            values.setdefault(STATUS, etype.initial_state)
            if values[STATUS] is None:
                values[STATUS] = etype.initial_state
            entities[name] = values
        extra = set(case) - set(ontology.entities)
        if extra:
            raise OntologyError(f"case data references unknown entities {sorted(extra)}")
        return cls(entities)

    def get(self, entity: str, attr: str) -> Any:
        return self.entities.get(entity, {}).get(attr)

    def field(self, ref: str) -> Any:
        entity, _, attr = ref.partition(".")
        return self.get(entity, attr)

    def set(self, entity: str, attr: str, value: Any) -> None:
        self.entities[entity][attr] = value

    def copy(self) -> "WorldState":
        return WorldState(copy.deepcopy(self.entities), self.steps)

    def key(self) -> Tuple:
        """Hashable snapshot used by the planner for search."""
        return (json.dumps(self.entities, sort_keys=True, default=str),
                tuple(sorted(self.steps.items())))

    def snapshot(self) -> Dict[str, Any]:
        return {"entities": copy.deepcopy(self.entities), "steps": dict(self.steps)}

    def __repr__(self) -> str:
        statuses = ", ".join(f"{e}={v.get(STATUS)}" for e, v in self.entities.items())
        return f"WorldState({statuses})"
