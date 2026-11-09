"""Export to open standards (JSON-LD and OWL/Turtle) to avoid vendor lock-in.

Entities become ``owl:Class``, attributes ``owl:DatatypeProperty``,
relationships ``owl:ObjectProperty`` and lifecycle states named individuals.
Actions, rules and goals - which OWL does not model natively - are emitted in
an ``autology:`` vocabulary so nothing is lost and the file round-trips into
graph databases and ontology tooling (Protégé, Neptune, GraphDB, ...).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .ontology import Ontology

AUTOLOGY_NS = "https://autology.dev/ns#"
XSD = {"string": "xsd:string", "number": "xsd:decimal", "integer": "xsd:integer", "boolean": "xsd:boolean",
       "date": "xsd:date", "datetime": "xsd:dateTime"}


def _base(onto: Ontology) -> str:
    return f"https://autology.dev/ontology/{onto.name}/{onto.version}#"


def to_jsonld(onto: Ontology) -> Dict[str, Any]:
    base = _base(onto)
    graph: List[Dict[str, Any]] = [{
        "@id": base.rstrip("#"), "@type": "owl:Ontology", "rdfs:label": onto.name,
        "owl:versionInfo": onto.version, "rdfs:comment": onto.description,
        "autology:fingerprint": onto.fingerprint, "autology:module": list(onto.modules),
    }]
    for e in onto.entities.values():
        graph.append({"@id": f":{e.name}", "@type": "owl:Class", "rdfs:label": e.name,
                      "rdfs:comment": e.description,
                      "autology:initialState": {"@id": f":{e.name}.{e.initial_state}"}})
        graph.append({"@id": f":{e.name}.status", "@type": "owl:ObjectProperty", "rdfs:domain": {"@id": f":{e.name}"},
                      "rdfs:range": {"@id": f":{e.name}State"}})
        graph.append({"@id": f":{e.name}State", "@type": "owl:Class",
                      "owl:oneOf": {"@list": [{"@id": f":{e.name}.{s}"} for s in e.states]}})
        for s in e.states:
            graph.append({"@id": f":{e.name}.{s}", "@type": ["owl:NamedIndividual", f":{e.name}State"],
                          "rdfs:label": s})
        for a in e.attributes.values():
            node = {"@id": f":{e.name}.{a.name}", "@type": "owl:DatatypeProperty",
                    "rdfs:domain": {"@id": f":{e.name}"}, "rdfs:range": {"@id": XSD.get(a.type, "xsd:string")}}
            if a.sensitivity:
                node["autology:sensitivity"] = a.sensitivity
            graph.append(node)
    for r in onto.relationships:
        graph.append({"@id": f":{r.kind}", "@type": "owl:ObjectProperty", "rdfs:domain": {"@id": f":{r.source}"},
                      "rdfs:range": {"@id": f":{r.target}"}, "autology:cardinality": r.cardinality})
    for a in onto.actions.values():
        graph.append({
            "@id": f":action/{a.name}", "@type": "autology:Action", "rdfs:label": a.name, "rdfs:comment": a.description,
            "autology:capability": a.capability, "autology:requires": [str(x) for x in a.requires],
            "autology:reads": list(a.reads), "autology:writes": list(a.writes), "autology:allowedTool": list(a.tools),
            "autology:outcome": [{"rdfs:label": o.name, "autology:effects": json.dumps(_plain(o.effects))}
                                 for o in a.outcomes],
        })
    for g in onto.goals.values():
        graph.append({"@id": f":goal/{g.name}", "@type": "autology:Goal", "rdfs:comment": g.description,
                      "autology:target": str(g.target)})
    for r in onto.rules:
        graph.append({"@id": f":rule/{r.id}", "@type": "autology:Rule", "autology:kind": r.kind,
                      "rdfs:comment": r.description, "autology:when": str(r.when) if r.when else None,
                      "autology:params": json.dumps(_plain(r.params))})
    for q in onto.questions:
        graph.append({"@id": f":question/{q.id}", "@type": "autology:CompetencyQuestion", "rdfs:label": q.question})
    return {
        "@context": {"@base": base, "": base, "owl": "http://www.w3.org/2002/07/owl#",
                     "rdfs": "http://www.w3.org/2000/01/rdf-schema#", "xsd": "http://www.w3.org/2001/XMLSchema#",
                     "autology": AUTOLOGY_NS},
        "@graph": graph,
    }


def _plain(value: Any) -> Any:
    if hasattr(value, "items"):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _lit(text: Any) -> str:
    return json.dumps("" if text is None else str(text))


def to_turtle(onto: Ontology) -> str:
    """OWL 2 in Turtle syntax (schema only: classes, properties, states; actions/rules as annotations)."""
    base = _base(onto)
    lines = [f"@prefix : <{base}> .", "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
             "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
             "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .", f"@prefix autology: <{AUTOLOGY_NS}> .", "",
             f"<{base.rstrip('#')}> a owl:Ontology ; rdfs:label {_lit(onto.name)} ; "
             f"owl:versionInfo {_lit(onto.version)} ; autology:fingerprint {_lit(onto.fingerprint)} .", ""]
    for e in onto.entities.values():
        lines.append(f":{e.name} a owl:Class ; rdfs:label {_lit(e.name)} ; rdfs:comment {_lit(e.description)} .")
        states = " ".join(f":{e.name}_{s}" for s in e.states)
        lines.append(f":{e.name}State a owl:Class ; owl:oneOf ( {states} ) .")
        for s in e.states:
            lines.append(f":{e.name}_{s} a owl:NamedIndividual , :{e.name}State ; rdfs:label {_lit(s)} .")
        lines.append(f":{e.name}_status a owl:ObjectProperty , owl:FunctionalProperty ; rdfs:domain :{e.name} ; "
                     f"rdfs:range :{e.name}State .")
        for a in e.attributes.values():
            extra = f" ; autology:sensitivity {_lit(a.sensitivity)}" if a.sensitivity else ""
            lines.append(f":{e.name}_{a.name} a owl:DatatypeProperty ; rdfs:domain :{e.name} ; "
                         f"rdfs:range {XSD.get(a.type, 'xsd:string')}{extra} .")
        lines.append("")
    for r in onto.relationships:
        lines.append(f":{r.kind} a owl:ObjectProperty ; rdfs:domain :{r.source} ; rdfs:range :{r.target} ; "
                     f"autology:cardinality {_lit(r.cardinality)} .")
    lines.append("")
    for a in onto.actions.values():
        lines.append(f":action_{a.name} a autology:Action ; rdfs:label {_lit(a.name)} ; "
                     f"rdfs:comment {_lit(a.description)} ; autology:capability {_lit(a.capability)} .")
    for r in onto.rules:
        lines.append(f":rule_{r.id.replace('-', '_')} a autology:Rule ; autology:kind {_lit(r.kind)} ; "
                     f"rdfs:comment {_lit(r.description)} .")
    return "\n".join(lines) + "\n"
