"""Application manifests: what a business application built on a released solution shows, as declarative data.

    released model + approved configuration  ->  generate()  ->  manifest  ->  validate()  ->  a renderer

A manifest names **views** (a list of records, a record, its relationships, a form, the workflow, the reviews that
wait, the audit trail, a dashboard) and binds each of them to things the model really has: an entity, an attribute,
a relationship, a case template, an action, a rule. It is bound to one exact configuration of one use case.

What a manifest is not, by construction:

* **It grants nothing.** No permission, role, grant or visibility is read from a manifest. The roles it lists say
  whom the application is meant for; the Engine decides what each caller sees and may do, on every request,
  exactly as it does without any application (see :func:`tailor`: the Engine removes what a caller can never
  see, and never adds).
* **It executes nothing.** The schema is closed and versioned. A manifest holds no expression, no script, no
  markup, no address of anything outside Autology; a renderer maps each view type to a component it already has.
  Text is text: a label with markup in it is refused, not cleaned.
* **It decides nothing.** Which action is allowed, which needs a person, which is prohibited are the model's
  rules, evaluated by the Engine when the action is asked for. A manifest only names the rules, so that a screen
  can explain them.

:func:`generate` is deterministic: the same model and configuration give the same manifest, byte for byte. It
reads **structure only** (entities, attribute order and types, relationships, states, case templates, rules,
agents); no entity or attribute name means anything to it. Every choice it makes carries its ``basis``:

``ontology``       read from the released model
``configuration``  read from the approved configuration (agents)
``default``        a presentation default nobody confirmed (how many columns, in which order)
``confirmed``      a person changed or confirmed it in the designer
``unresolved``     something the generator could not decide: a person must
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .schema import errors as schema_errors

MANIFEST_VERSION = 1
ENGINE_API = "1"
VIEW_TYPES = ("DashboardView", "EntityListView", "EntityDetailView", "RelationshipView", "RecordFormView",
              "WorkflowView", "ApprovalInboxView", "AuditTimelineView")
BASES = ("ontology", "configuration", "default", "confirmed", "unresolved")
# what a view needs the Engine to let the caller do; a caller without it gets the view marked unavailable
REQUIRES = {"DashboardView": "read", "EntityListView": "read", "EntityDetailView": "read", "RelationshipView": "read",
            "RecordFormView": "read", "WorkflowView": "read", "ApprovalInboxView": "review", "AuditTimelineView": "audit"}
# said plainly in every application: what it cannot do, and why. A closed list: a manifest cannot invent a feature
UNAVAILABLE = {
    "records.create": "creating or changing a record needs the unrestricted data-administration permission; a narrow "
                      "permission for applications is not approved (owner decision D24). Forms are previews",
    "records.server_search": "the Engine lists records by type, a page at a time: it has no search, filter or sort "
                             "of its own, so filtering applies to the records loaded",
    "events.push": "there is no event feed: screens are refreshed on request (owner decision D34)",
    "production": "production execution is disabled: this application runs on synthetic records with simulated tools",
    "geography": "no map, distance or location computation exists",
    "analytics": "no forecasting, optimisation, pattern detection or graph analysis exists: relationships shown are "
                 "recorded links only",
    "multi_agent": "a run has one agent (owner decision D32)",
}
INPUTS = {"string": "text", "number": "number", "boolean": "checkbox", "date": "date", "datetime": "datetime"}
ACCENTS = ("blue", "teal", "green", "amber", "violet", "slate")
MAX_COLUMNS, MAX_VIEWS, MAX_TEXT = 6, 80, 160
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")
UNSAFE = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|javascript:|vbscript:|data:\w+/|://|(?:^|\s)//|\{\{|\$\{", re.I)

S: Dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT}
BASIS: Dict[str, Any] = {"type": "string", "enum": list(BASES)}


def _obj(properties: Dict[str, Any], optional: Sequence[str] = ()) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "additionalProperties": False,
            "required": [k for k in properties if k not in optional]}


def _arr(item: Dict[str, Any], most: int = 60) -> Dict[str, Any]:
    return {"type": "array", "items": item, "maxItems": most}


FIELD = _obj({"field": S, "label": S, "basis": BASIS})
RELATED = _obj({"relationship": S, "direction": {"type": "string", "enum": ["out", "in"]}, "entity": S, "label": S,
                "basis": BASIS})
VIEW = _obj({
    "id": S, "type": {"type": "string", "enum": list(VIEW_TYPES)}, "title": S, "basis": BASIS,
    "entity": S,                                           # every view about records of one type
    "columns": _arr(FIELD, 12), "title_field": S,          # EntityListView
    "page_size": {"type": "integer", "minimum": 5, "maximum": 100},
    "fields": _arr(_obj({"field": S, "label": S, "basis": BASIS, "input": {"type": "string", "enum": sorted(set(INPUTS.values()) | {"select"})},
                         "options": _arr(S, 40)}, optional=("input", "options"))),  # detail and form
    "related": _arr(RELATED),                              # EntityDetailView, RelationshipView
    "case_template": S, "agent": S, "states": _arr(S, 40),  # WorkflowView
    "actions": _arr(_obj({"action": S, "label": S, "rules": _arr(S, 20), "basis": BASIS})),
    "rules": _arr(S, 40),                                  # ApprovalInboxView: the review rules it explains
    "tiles": _arr(_obj({"entity": S, "label": S, "basis": BASIS}), 12),  # DashboardView: records by state
}, optional=("entity", "columns", "title_field", "page_size", "fields", "related", "case_template", "agent", "states",
             "actions", "rules", "tiles"))
SCHEMA: Dict[str, Any] = _obj({
    "manifest_version": {"type": "integer", "enum": [MANIFEST_VERSION]},
    "id": S, "title": S, "description": {"type": "string", "maxLength": 500},
    # the exact solution this application was designed for. The Engine compares it with what runs
    "binding": _obj({"model": S, "model_fingerprint": S, "configuration": S, "engine_api": {"type": "string", "enum": [ENGINE_API]},
                     "workspace": S, "use_case": S}, optional=("workspace", "use_case")),
    "roles": _arr(S, 40),          # whom the application is meant for: information, never a permission
    "navigation": _arr(_obj({"view": S, "label": S, "basis": BASIS}), 40),
    "views": _arr(VIEW, MAX_VIEWS),
    "unavailable": _arr(_obj({"feature": {"type": "string", "enum": sorted(UNAVAILABLE)}, "reason": {"type": "string", "maxLength": 400}}), 20),
    "presentation": _obj({"accent": {"type": "string", "enum": list(ACCENTS)},
                          "density": {"type": "string", "enum": ["comfortable", "compact"]}}),
}, optional=("description",))
# which properties each view type may carry (the schema above is their union)
ALLOWED = {
    "DashboardView": {"tiles"}, "EntityListView": {"entity", "columns", "title_field", "page_size"},
    "EntityDetailView": {"entity", "fields", "related"}, "RelationshipView": {"entity", "related"},
    "RecordFormView": {"entity", "fields"}, "WorkflowView": {"entity", "case_template", "agent", "states", "actions"},
    "ApprovalInboxView": {"rules"}, "AuditTimelineView": set(),
}
NEEDED = {"DashboardView": {"tiles"}, "EntityListView": {"entity", "columns"}, "EntityDetailView": {"entity", "fields"},
          "RelationshipView": {"entity", "related"}, "RecordFormView": {"entity", "fields"},
          "WorkflowView": {"entity", "case_template", "actions"}, "ApprovalInboxView": {"rules"},
          "AuditTimelineView": set()}


def words(name: str) -> str:
    """A name of the model as people read it: ``unit_price`` and ``PurchaseOrder`` become words. It splits on
    underscores, hyphens and capitals; it knows no vocabulary."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(name).replace("_", " ").replace("-", " ")).strip()
    return (spaced[:1].upper() + spaced[1:].lower()) if spaced else str(name)


def digest(manifest: Any) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# -- generating -----------------------------------------------------------------------------------------------
def generate(ontology: Any, agents: Mapping[str, Mapping[str, Any]], binding: Mapping[str, str],
             app_id: Optional[str] = None) -> Dict[str, Any]:
    """A draft manifest for the released model ``ontology`` (an :class:`autology.ontology.Ontology`) and the agents
    of its approved configuration (``{name: {"goals": [...], "roles": [...]}}``). Deterministic; see the module
    docstring for what it reads and what it never does."""
    entities = list(ontology.entities.values())
    roots = [t.root for t in ontology.case_templates.values()]
    degree = {e.name: sum(1 for r in ontology.relationships if e.name in (r.source, r.target)) for e in entities}
    declared = {e.name: i for i, e in enumerate(entities)}
    # work items first (what a run starts from), then what is most connected, then the order of the model
    ordered = sorted(entities, key=lambda e: (e.name not in roots, -degree[e.name], declared[e.name]))
    views: List[Dict[str, Any]] = []
    navigation: List[Dict[str, Any]] = []

    def attributes(entity: Any) -> List[Tuple[str, str]]:
        return [(a.name, a.type) for a in entity.attributes.values() if a.name != "status"]

    def add(view: Dict[str, Any], in_navigation: bool = True) -> None:
        views.append(view)
        if in_navigation:
            navigation.append({"view": view["id"], "label": view["title"], "basis": "default"})

    if roots:
        add({"id": "overview", "type": "DashboardView", "title": "Overview", "basis": "default",
             "tiles": [{"entity": name, "label": words(name), "basis": "ontology"} for name in dict.fromkeys(roots)]})
    for template in ontology.case_templates.values():
        root = ontology.entities[template.root]
        touching = [a for a in ontology.actions.values() if any(template.root in o.effects for o in a.outcomes)
                    or any(template.root in str(x) for x in a.requires)]
        agent = next((name for name in sorted(agents) if any(g in ontology.goals for g in agents[name].get("goals", []))), None)
        view: Dict[str, Any] = {
            "id": f"work-{template.name}", "type": "WorkflowView", "title": f"{words(template.root)}: work",
            "basis": "ontology", "entity": template.root, "case_template": template.name, "states": list(root.states),
            "actions": [{"action": a.name, "label": words(a.name), "basis": "ontology",
                         "rules": [r.id for r in ontology.rules
                                   if r.params.get("action") == a.name or r.params.get("before") == a.name]}
                        for a in touching]}
        if agent is not None:
            view["agent"] = agent
        else:
            view["basis"] = "unresolved"  # the model has work to do and no approved agent to do it
        add(view)
    for entity in ordered:
        attrs = attributes(entity)
        shown = attrs[:MAX_COLUMNS - 1]
        title = next((name for name, kind in attrs if kind == "string"), None)
        slug = entity.name.lower()
        listing: Dict[str, Any] = {
            "id": f"list-{slug}", "type": "EntityListView", "title": words(entity.name), "basis": "ontology",
            "entity": entity.name, "page_size": 25,
            "columns": [{"field": "status", "label": "Status", "basis": "ontology"}]
            + [{"field": name, "label": words(name), "basis": "default"} for name, _ in shown]}
        if title:
            listing["title_field"] = title
        add(listing)
        related = []
        for r in ontology.relationships:
            if r.source == entity.name:
                related.append({"relationship": r.kind, "direction": "out", "entity": r.target,
                                "label": f"{words(r.kind)}: {words(r.target)}", "basis": "ontology"})
            if r.target == entity.name:
                related.append({"relationship": r.kind, "direction": "in", "entity": r.source,
                                "label": f"{words(r.source)} ({words(r.kind).lower()})", "basis": "ontology"})
        add({"id": f"detail-{slug}", "type": "EntityDetailView", "title": words(entity.name), "basis": "ontology",
             "entity": entity.name, "related": related,
             "fields": [{"field": "status", "label": "Status", "basis": "ontology"}]
             + [{"field": name, "label": words(name), "basis": "ontology"} for name, _ in attrs]}, in_navigation=False)
        if related:
            add({"id": f"links-{slug}", "type": "RelationshipView", "title": f"{words(entity.name)}: relationships",
                 "basis": "ontology", "entity": entity.name, "related": related}, in_navigation=False)
        add({"id": f"form-{slug}", "type": "RecordFormView", "title": f"New {words(entity.name).lower()}",
             "basis": "default", "entity": entity.name,
             "fields": [{"field": "status", "label": "Status", "basis": "ontology", "input": "select",
                         "options": list(entity.states)}]
             + [{"field": name, "label": words(name), "basis": "ontology", "input": INPUTS.get(kind, "text")}
                for name, kind in attrs]}, in_navigation=False)
    reviews = [r.id for r in ontology.rules if r.kind == "human_review"]
    if reviews:
        add({"id": "reviews", "type": "ApprovalInboxView", "title": "Decisions waiting for a person", "basis": "ontology",
             "rules": reviews})
    add({"id": "audit", "type": "AuditTimelineView", "title": "Audit trail", "basis": "default"})
    roles: Set[str] = set()
    for rule in ontology.rules:
        roles |= {str(x) for x in rule.params.get("roles") or []}
        if rule.params.get("reviewer"):
            roles.add(str(rule.params["reviewer"]))
    for agent_spec in agents.values():
        roles |= {str(x) for x in agent_spec.get("roles", [])}
    name = str(binding["model"]).split("@")[0]
    return {
        "manifest_version": MANIFEST_VERSION, "id": app_id or f"{name}-app"[:64], "title": words(name),
        # the model's own description, when it is plain text; never cleaned into something its author did not write
        "description": "" if UNSAFE.search(str(getattr(ontology, "description", "") or "")) else str(getattr(ontology, "description", "") or "")[:500],
        "binding": {k: str(v) for k, v in binding.items()},
        "roles": sorted(roles), "navigation": navigation, "views": views,
        "unavailable": [{"feature": feature, "reason": reason} for feature, reason in sorted(UNAVAILABLE.items())],
        "presentation": {"accent": ACCENTS[int(digest(name), 16) % len(ACCENTS)], "density": "comfortable"}}


# -- validating -----------------------------------------------------------------------------------------------
def _strings(value: Any, path: str = "$") -> Iterable[Tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, sub in value.items():
            yield from _strings(sub, f"{path}.{key}")
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            yield from _strings(sub, f"{path}[{i}]")


def validate(manifest: Any, ontology: Any, agents: Mapping[str, Any], running: Mapping[str, str]) -> List[Dict[str, str]]:
    """Every reason ``manifest`` cannot be used with the model ``ontology`` that runs as ``running`` (the same
    keys as a manifest's ``binding``). An empty list: it can. Nothing is repaired."""
    problems = [{"path": p.split(": ")[0], "message": p.split(": ", 1)[1] if ": " in p else p}
                for p in schema_errors(manifest, SCHEMA)]
    if problems or not isinstance(manifest, Mapping):
        return problems  # nothing else is read from a manifest that is not one

    def bad(path: str, message: str) -> None:
        problems.append({"path": path, "message": message})

    for path, text in _strings(manifest):
        if UNSAFE.search(text):
            bad(path, "text only: markup, addresses, scripts and expressions are not allowed in a manifest")
    if not NAME.match(manifest["id"]):
        bad("$.id", "an identifier: a letter, then letters, digits, _ or -")
    binding = manifest["binding"]
    for key in ("model", "model_fingerprint", "configuration", "workspace", "use_case"):
        if key in running and binding.get(key) != running[key]:
            bad(f"$.binding.{key}", "this application was designed for another " + {
                "model": "model", "model_fingerprint": "version of the model", "configuration": "configuration (release)",
                "workspace": "workspace", "use_case": "use case"}[key] + f": {running[key]!r} runs here")
    known_roles: Set[str] = set()
    for rule in ontology.rules:
        known_roles |= {str(x) for x in rule.params.get("roles") or []} | ({str(rule.params["reviewer"])} if rule.params.get("reviewer") else set())
    for spec in agents.values():
        known_roles |= {str(x) for x in spec.get("roles", [])}
    for i, role in enumerate(manifest["roles"]):
        if role not in known_roles:
            bad(f"$.roles[{i}]", f"{role!r} is not a role of this model; a manifest never creates or grants one")
    rules = {r.id: r for r in ontology.rules}
    seen: Set[str] = set()
    for i, view in enumerate(manifest["views"]):
        where, kind = f"$.views[{i}]", view["type"]
        if not NAME.match(view["id"]) or view["id"] in seen:
            bad(f"{where}.id", "view identifiers are unique names")
        seen.add(view["id"])
        extra = (set(view) - {"id", "type", "title", "basis"}) - ALLOWED[kind]
        missing = NEEDED[kind] - set(view)
        if extra or missing:
            bad(where, f"a {kind} " + "; ".join(x for x in (f"has no {sorted(extra)}" if extra else "",
                                                               f"needs {sorted(missing)}" if missing else "") if x))
            continue
        entity: Any = ontology.entities.get(view.get("entity", "")) if "entity" in view else None
        if "entity" in view and entity is None:
            bad(f"{where}.entity", f"the model has no entity {view['entity']!r}")
            continue

        def field(path: str, owner: Any, name: str) -> None:
            if name != "status" and name not in owner.attributes:
                bad(path, f"{owner.name} has no attribute {name!r}")

        for key in ("columns", "fields"):
            for j, column in enumerate(view.get(key, [])):
                field(f"{where}.{key}[{j}].field", entity, column["field"])
                if column.get("input") == "select" and column["field"] == "status" and set(column.get("options", [])) - set(entity.states):
                    bad(f"{where}.{key}[{j}].options", f"not states of {entity.name}")
        if "title_field" in view:
            field(f"{where}.title_field", entity, view["title_field"])
        for j, link in enumerate(view.get("related", [])):
            source, target = (entity.name, link["entity"]) if link["direction"] == "out" else (link["entity"], entity.name)
            if not any((r.source, r.target, r.kind) == (source, target, link["relationship"]) for r in ontology.relationships):
                bad(f"{where}.related[{j}]", f"the model has no relationship {source} -{link['relationship']}-> {target}")
        if kind == "WorkflowView":
            template = ontology.case_templates.get(view["case_template"])
            if template is None or template.root != entity.name:
                bad(f"{where}.case_template", f"no case template {view['case_template']!r} starts from {entity.name}")
            if "agent" in view and view["agent"] not in agents:
                bad(f"{where}.agent", f"no agent {view['agent']!r} is part of what runs")
            if set(view.get("states", [])) - set(entity.states):
                bad(f"{where}.states", f"not states of {entity.name}")
            for j, action in enumerate(view["actions"]):
                if action["action"] not in ontology.actions:
                    bad(f"{where}.actions[{j}].action", f"the model has no action {action['action']!r}")
                for rule_id in action["rules"]:
                    if rule_id not in rules:
                        bad(f"{where}.actions[{j}].rules", f"the model has no rule {rule_id!r}")
        for j, rule_id in enumerate(view.get("rules", [])):
            if rule_id not in rules or rules[rule_id].kind != "human_review":
                bad(f"{where}.rules[{j}]", f"{rule_id!r} is not a review rule of the model")
        for j, tile in enumerate(view.get("tiles", [])):
            if tile["entity"] not in ontology.entities:
                bad(f"{where}.tiles[{j}].entity", f"the model has no entity {tile['entity']!r}")
    for i, item in enumerate(manifest["navigation"]):
        if item["view"] not in seen:
            bad(f"$.navigation[{i}].view", f"no view {item['view']!r}")
    features = [u["feature"] for u in manifest["unavailable"]]
    for feature in sorted(set(UNAVAILABLE) - set(features)):
        bad("$.unavailable", f"an application says what it cannot do: {feature!r} is missing")
    return problems


# -- what one caller gets ---------------------------------------------------------------------------------------
def tailor(manifest: Mapping[str, Any], ontology: Any, roles: Set[str], permissions: Set[str]) -> Dict[str, Any]:
    """``manifest`` as the Engine hands it to one caller: views of records the caller can never see are removed,
    fields the caller can never read are removed, and views that need a permission the caller does not hold are
    marked. It only removes. Conditional rules are not decided here: the Engine applies them to every record it
    returns, whatever the manifest says."""
    unrestricted = "admin" in permissions
    hidden_entities = set() if unrestricted else {
        r.params["entity"] for r in ontology.rules_of("row_access") if r.when is None and not roles & set(r.params["roles"])}
    hidden_fields = set() if unrestricted else {
        r.params["field"] for r in ontology.rules_of("data_access") if r.when is None and not roles & set(r.params["roles"])}
    views = []
    for view in manifest["views"]:
        if view.get("entity") in hidden_entities:
            continue
        view = dict(view)
        entity = view.get("entity")
        for key in ("columns", "fields"):
            if key in view:
                view[key] = [c for c in view[key] if f"{entity}.{c['field']}" not in hidden_fields]
        if view.get("title_field") and f"{entity}.{view['title_field']}" in hidden_fields:
            view.pop("title_field")
        if "related" in view:
            view["related"] = [x for x in view["related"] if x["entity"] not in hidden_entities]
        if "tiles" in view:
            view["tiles"] = [t for t in view["tiles"] if t["entity"] not in hidden_entities]
        needed = REQUIRES[view["type"]]
        view["available"] = needed in permissions or unrestricted
        if not view["available"]:
            view["unavailable_because"] = f"you do not hold the {needed!r} permission on this use case"
        views.append(view)
    kept = {v["id"] for v in views}
    return {**manifest, "views": views, "navigation": [n for n in manifest["navigation"] if n["view"] in kept]}


# -- D24: the operations an application needs, kept apart (a proposal; nothing here is enforced or active) ---------
# "today" is what the Engine requires now. "proposed" names a right that does not exist: "records.create" and
# "records.update" would be grants scoped to named entity types and attributes of one use case. They are not the
# "operate" permission of the D24 specification, which covers operational routes (scheduler pass, reporting refresh)
# and no record write.
PROPOSED_OPERATIONS: Dict[str, Dict[str, Any]] = {
    "create_case": {"today": "admin", "proposed": "records.create", "scope": "named entity types of one use case"},
    "read_case": {"today": "read", "proposed": "read", "scope": "rows and fields the model's rules allow"},
    "update_allowed_fields": {"today": "admin", "proposed": "records.update", "scope": "named attributes; never a decision-critical one without its writer rule"},
    "perform_workflow_action": {"today": "run", "proposed": "run", "scope": "ask for a run; the Engine plans and checks every rule"},
    "request_approval": {"today": "run", "proposed": "run", "scope": "a run that reaches a review rule waits; nobody asks for approval directly"},
    "review_or_approve": {"today": "review", "proposed": "review", "scope": "a person holding the reviewer role; never the requester, never a service identity"},
    "administer_ontology": {"today": "configure", "proposed": "configure", "scope": "drafts only; a release needs a second person"},
    "administer_security": {"today": "workspace administrator", "proposed": "workspace administrator", "scope": "members and grants, each approved by a second person"},
    "manage_releases": {"today": "workspace administrator + release approver", "proposed": "workspace administrator + release approver", "scope": "propose, approve (another person), activate"},
}

__all__ = ["MANIFEST_VERSION", "SCHEMA", "VIEW_TYPES", "BASES", "UNAVAILABLE", "PROPOSED_OPERATIONS", "words", "digest",
           "generate", "validate", "tailor"]
