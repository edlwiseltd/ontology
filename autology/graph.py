"""Knowledge graph: ontology-typed instances and links, queried by competency questions.

The planner and agents work on one *case* at a time; the knowledge graph holds
the wider enterprise picture (all contracts, suppliers, production lines...) so
the ontology can answer questions such as "Which contracts expire within 30
days?" or "Which suppliers does ProductionLine #1 depend on?". It is an
in-memory reference store; production deployments would back the same
interface with a graph database (Neo4j, Neptune) synced by ETL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .expressions import Expression, compile_expression
from .ontology import ID, PARAMS, STATUS, CompetencyQuestion, Ontology, OntologyError


@dataclass
class Instance:
    type: str
    id: str
    attributes: Dict[str, Any]

    def get(self, attr: str) -> Any:
        if attr == ID:
            return self.id
        return self.attributes.get(attr)


@dataclass
class QueryResult:
    instances: List[Instance]
    value: Any = None  # aggregate value, if requested

    @property
    def ids(self) -> List[str]:
        return [i.id for i in self.instances]

    @property
    def answer(self) -> Any:
        return self.value if self.value is not None else self.ids


class KnowledgeGraph:
    def __init__(self, ontology: Ontology):
        self.ontology = ontology
        self._instances: Dict[str, Instance] = {}
        self._links: List[Tuple[str, str, str]] = []  # (source id, kind, target id)

    # -- building -------------------------------------------------------
    def add(self, entity_type: str, id: str, **attributes: Any) -> Instance:
        etype = self.ontology.entities.get(entity_type)
        if etype is None:
            raise OntologyError(f"unknown entity type {entity_type!r}")
        unknown = [k for k in attributes if not etype.has_attribute(k) or k == ID]
        if unknown:
            raise OntologyError(f"{entity_type} {id!r}: unknown attributes {unknown}")
        status = attributes.get(STATUS, etype.initial_state)
        if status not in etype.states:
            raise OntologyError(f"{entity_type} {id!r}: {status!r} is not a valid state")
        if id in self._instances:
            raise OntologyError(f"duplicate instance id {id!r}")
        values = {a: None for a in etype.attributes}
        values.update(attributes)
        values[STATUS] = status
        inst = Instance(entity_type, id, values)
        self._instances[id] = inst
        return inst

    def link(self, source: str, kind: str, target: str) -> None:
        src, tgt = self._instances[source], self._instances[target]
        if not any(r.kind == kind and r.source == src.type and r.target == tgt.type
                   for r in self.ontology.relationships):
            raise OntologyError(f"ontology has no relationship {src.type} -{kind}-> {tgt.type}")
        self._links.append((source, kind, target))

    @classmethod
    def from_dict(cls, ontology: Ontology, data: Mapping[str, Any]) -> "KnowledgeGraph":
        graph = cls(ontology)
        for spec in data.get("instances", []):
            spec = dict(spec)
            graph.add(spec.pop("type"), spec.pop("id"), **spec)
        for source, kind, target in data.get("links", []):
            graph.link(source, kind, target)
        return graph

    # -- querying -------------------------------------------------------
    def instances(self, entity_type: Optional[str] = None) -> List[Instance]:
        return [i for i in self._instances.values() if entity_type is None or i.type == entity_type]

    def get(self, id: str) -> Instance:
        return self._instances[id]

    def neighbours(self, inst: Instance, step: str) -> List[Instance]:
        reverse = step.startswith("^")
        kind = step.lstrip("^")
        if reverse:
            return [self._instances[s] for s, k, t in self._links if k == kind and t == inst.id]
        return [self._instances[t] for s, k, t in self._links if k == kind and s == inst.id]

    @staticmethod
    def _matches(expr: Optional[Expression], inst: Instance, params: Mapping[str, Any]) -> bool:
        if expr is None:
            return True

        def resolve(entity: str, attr: str) -> Any:
            if entity == PARAMS:
                return params.get(attr)
            return inst.get(attr) if entity == inst.type else None

        return expr.evaluate(resolve)

    def query(self, find: str, where: Optional[str | Expression] = None, follow: Sequence[str] = (),
              result_where: Optional[str | Expression] = None, aggregate: Optional[Tuple[str, Optional[str]]] = None,
              params: Optional[Mapping[str, Any]] = None) -> QueryResult:
        params = dict(params or {})
        where = compile_expression(where) if isinstance(where, str) else where
        result_where = compile_expression(result_where) if isinstance(result_where, str) else result_where
        current = [i for i in self.instances(find) if self._matches(where, i, params)]
        for step in follow:
            self.ontology.relationship(current[0].type if current else find, step)  # validates step
            seen: Dict[str, Instance] = {}
            for inst in current:
                for n in self.neighbours(inst, step):
                    seen.setdefault(n.id, n)
            current = list(seen.values())
        current = [i for i in current if self._matches(result_where, i, params)]
        value = None
        if aggregate:
            fn, target = aggregate
            if fn == "count":
                value = len(current)
            else:
                attr = target.partition(".")[2]
                nums = [i.get(attr) for i in current if isinstance(i.get(attr), (int, float))]
                if fn == "sum":
                    value = sum(nums)
                elif nums:
                    value = {"avg": sum(nums) / len(nums), "min": min(nums), "max": max(nums)}[fn]
        return QueryResult(sorted(current, key=lambda i: i.id), value)

    def ask(self, question: CompetencyQuestion | str, **params: Any) -> QueryResult:
        if isinstance(question, str):
            question = next((q for q in self.ontology.questions if q.id == question), None) or \
                _raise(OntologyError(f"unknown competency question {question!r}"))
        merged = dict(question.params)
        merged.update(params)
        return self.query(question.find, question.where, question.follow, question.result_where,
                          question.aggregate, merged)

    def check_competency(self) -> List[Tuple[CompetencyQuestion, Any, Optional[bool]]]:
        """Answer every competency question; third element is True/False when ``expect`` is set."""
        report = []
        for q in self.ontology.questions:
            answer = self.ask(q).answer
            ok = None
            if q.expect is not None:
                expected = sorted(q.expect) if isinstance(q.expect, (list, tuple)) else q.expect
                ok = answer == expected
            report.append((q, answer, ok))
        return report


def build_case(graph: "KnowledgeGraph", template: str, root_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Assemble an agent case from the graph with a case template.

    Returns ``(case, sources)`` - ``sources`` maps each entity to the instance id(s) it came from, so a
    completed run can write its results back to exactly those instances.
    """
    onto = graph.ontology
    tpl = onto.case_templates.get(template)
    if tpl is None:
        raise OntologyError(f"unknown case template {template!r}")
    try:
        root = graph.get(root_id)
    except KeyError:
        raise OntologyError(f"no instance {root_id!r}") from None
    if root.type != tpl.root:
        raise OntologyError(f"template {template!r} starts at a {tpl.root}, not a {root.type}")
    case: Dict[str, Any] = {}
    sources: Dict[str, Any] = {}
    for entity, steps in tpl.entities.items():
        reached = [root]
        for step in steps:
            seen: Dict[str, Instance] = {}
            for inst in reached:
                for n in graph.neighbours(inst, step):
                    seen.setdefault(n.id, n)
            reached = sorted(seen.values(), key=lambda i: i.id)
        if onto.entities[entity].multiple:
            case[entity] = [{"id": i.id, **i.attributes} for i in reached]
            sources[entity] = [i.id for i in reached]
        elif reached:
            case[entity] = dict(reached[0].attributes)
            sources[entity] = reached[0].id
    return case, sources


def write_back(graph: "KnowledgeGraph", state: Any, sources: Mapping[str, Any]) -> List[str]:
    """Copy a world state's values onto the graph instances a case was built from (see :func:`build_case`).

    Only attributes the instance already has are written. Returns the ids of instances that changed.
    """
    changed = []
    for entity, src in sources.items():
        if isinstance(src, list):
            pairs = [(iid, state.collections.get(entity, {}).get(iid)) for iid in src]
        else:
            pairs = [(src, state.entities.get(entity))]
        for iid, values in pairs:
            inst = graph._instances.get(iid)
            if not values or inst is None:
                continue
            new = {k: v for k, v in values.items() if k in inst.attributes and inst.attributes[k] != v}
            if new:
                inst.attributes.update(new)
                changed.append(iid)
    return changed


def fork(graph: "KnowledgeGraph") -> "KnowledgeGraph":
    """An independent copy of ``graph``: changes to the copy never touch the original."""
    copy = KnowledgeGraph(graph.ontology)
    copy._instances = {i.id: Instance(i.type, i.id, dict(i.attributes)) for i in graph._instances.values()}
    copy._links = list(graph._links)
    return copy


def _raise(exc: Exception):
    raise exc
