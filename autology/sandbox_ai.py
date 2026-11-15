"""The sandbox architect: a deterministic test double behind the AI gateway (not a language model).

Until the owner approves a model provider and the data it may receive (decisions D7, D10), this is the only
"provider" an engine can be configured with for the AI Architect. It lets the whole path be built, exercised and
demonstrated - Studio, the versioned API, the gateway (workspace configuration, data classes, deadline, schema
validation, accounting, logging), the proposal contract and the engine's validation - without sending anything
anywhere and without pretending that a model reasoned.

What it does: it reads the request the gateway hands it (the brief, an outline of the current model, the answers
given so far), picks the approved template (:mod:`autology.modeling` blueprints) whose vocabulary the brief uses,
fills the template's parameters from the answers, and returns a proposal in the form of
:data:`autology.architect.SCHEMA`. Parameters still on their default become clarification questions and stated
assumptions, with a lower confidence on the items that depend on them. A brief that matches no template gets
questions, not guesses.

Its answer is treated exactly like a model's: untrusted, schema-checked by the gateway, validated by the engine,
provisional until a person accepts it. Reports carry ``"ai": false`` and name the generator ``sandbox``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from .ai import Capabilities, ProviderCall, ProviderError, ProviderReply
from .integrity import DATA_CLOSE, DATA_OPEN
from .modeling import fill, match, parameters

MODEL = "sandbox-templates-1"


def _matching(brief: str) -> Optional[Dict[str, Any]]:
    return match(brief)[0]


def _request_data(prompt: str) -> Dict[str, Any]:
    """The data block of a gateway request (the JSON between the markers)."""
    start, end = prompt.find(DATA_OPEN), prompt.rfind(DATA_CLOSE)
    if start < 0 or end < start:
        raise ProviderError("invalid_request", "the sandbox architect answers architect requests only")
    try:
        data = json.loads(prompt[start + len(DATA_OPEN):end])
    except ValueError:
        raise ProviderError("invalid_request", "the request's data block is not JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("brief"), str):
        raise ProviderError("invalid_request", "the sandbox architect answers architect requests only")
    return data


def answer(data: Mapping[str, Any]) -> Dict[str, Any]:
    """The proposal for one architect request (see the module docstring)."""
    empty: Dict[str, Any] = {key: [] for key in ("entities", "relationships", "actions", "rules", "goals", "questions",
                                                 "assumptions", "unknowns", "roles", "agents", "integrations")}
    template = _matching(data["brief"])
    if template is None:
        empty["questions"] = [{"id": "process", "why": "No approved template matches this description yet",
                               "question": "Which process should come first? Say who asks for what, who decides, "
                                           "and what is delivered."}]
        empty["unknowns"] = ["The business process to model"]
        return empty
    given = {str(a.get("id")): a.get("answer") for a in data.get("answers") or [] if isinstance(a, dict)}
    values, still_open = parameters(template, given)
    specs = {p["id"]: p for p in template.get("parameters") or []}
    have = data.get("current_model") or {}
    known = {"entity": set(have.get("entities") or {}), "action": set(have.get("actions") or []),
             "rule": set(have.get("rules") or []), "goal": set(have.get("goals") or []),
             "relationship": set(have.get("relationships") or [])}
    out = dict(empty)
    out.update({key: [] for key in empty})
    for item in template["items"]:
        value, kind = fill(item["value"], values), item["kind"]
        name = item.get("name") or value.get("id") or f"{value['from']} -{value['type']}-> {value['to']}"
        if name in known[kind]:
            continue  # the current model has it already: a proposal only adds
        guessed = [p for p in item.get("uses") or [] if p in still_open]
        evidence = {"rationale": item["rationale"] + (f" (assuming {', '.join(guessed)})" if guessed else ""),
                    "sources": ["brief"], "confidence": 0.5 if guessed else 0.8}
        if kind == "entity":
            out["entities"].append({"name": name, "description": value.get("description", ""),
                                    "states": list(value.get("states") or []),
                                    "attributes": [{"name": a, "type": t if isinstance(t, str) else t.get("type", "string")}
                                                   for a, t in (value.get("attributes") or {}).items()], **evidence})
        elif kind == "relationship":
            out["relationships"].append({"from": value["from"], "to": value["to"], "type": value["type"],
                                         "cardinality": value.get("cardinality", "1..*"), **evidence})
        elif kind == "action":
            effects = [{"entity": entity, "attribute": attribute, "value": str(new)}
                       for entity, changes in (value.get("effects") or {}).items() for attribute, new in changes.items()]
            out["actions"].append({"name": name, "description": value.get("description", ""),
                                   "capability": value.get("capability", name),
                                   "requires": list(value.get("requires") or []), "effects": effects,
                                   "side_effect": value.get("side_effect", "non_idempotent"), **evidence})
        elif kind == "rule":
            out["rules"].append({**{k: v for k, v in value.items()}, **evidence})
        elif kind == "goal":
            out["goals"].append({"name": name, "description": value.get("description", ""), "target": value["target"],
                                 **evidence})
    out["questions"] = [{"id": p, "question": specs[p]["question"], "why": specs[p]["why"]} for p in still_open]
    out["assumptions"] = [{"statement": text, "sources": ["brief"], "confidence": 0.6}
                          for text in template.get("assumptions") or []]
    out["assumptions"] += [{"statement": f"{specs[p]['question']} Assumed: {values[p]!r}", "sources": [],
                            "confidence": 0.4} for p in still_open if values[p] not in ("", None)]
    out["unknowns"] = list(template.get("unknowns") or []) + [specs[p]["question"] for p in still_open
                                                              if values[p] in ("", None)]
    for section in ("roles", "agents", "integrations"):
        out[section] = fill(template.get(section) or [], values)
    return out


class SandboxArchitect:
    """The gateway provider for the sandbox architect. It contacts nothing and holds no credential."""

    name = "sandbox"

    def capabilities(self) -> Capabilities:
        return Capabilities(self.name, "in-process deterministic templates (no network)", "native", False, False, False,
                            "this is a test double: it is not a language model and proves nothing about one",
                            language_model=False)

    def invoke(self, call: ProviderCall) -> ProviderReply:
        if call.cancel.is_set():
            raise ProviderError("cancelled", "cancelled before the request was read", uncertain=False)
        return ProviderReply(json.dumps(answer(_request_data(call.prompt))), "complete", {}, MODEL)

