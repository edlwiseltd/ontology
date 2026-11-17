"""Least-privilege operations for applications: a **proposed** policy, tested and **not in force** (owner decision D24).

The rule in force is unchanged: writing a record needs the unrestricted ``admin`` data permission
(:meth:`autology.server.AutologyService.upsert_object`), and the permissions are the eight of
:data:`autology.server.PERMISSIONS`. Nothing in the Engine, the platform or the API calls this module, no grant
names a permission it proposes, and the Application Builder keeps its forms as previews. It exists so that the
owner's decision can be taken on something that runs and is tested.

Twelve operations are kept apart (:data:`OPERATIONS`). Three of them would need a right that does not exist today
(``records.create``, ``records.update``, ``records.archive``); two are never a caller's (``actions.execute``,
``reviews.request``: the Engine does them inside a run); the other seven keep the right they have.

:func:`decide` answers one question, from data only: *may this identity do this operation on this record, in this
use case, now?* It reads, in this order, and stops at the first refusal:

1. the operation is one of the twelve;
2. the operation is a caller's at all;
3. the identity's kind may do it (a service identity decides no review and administers nothing);
4. a grant **in force** names the workspace, the use case and the right (in force: approved by a person who is
   neither its proposer nor its holder);
5. the grant names the entity type, and the properties, and the workflow states it is limited to;
6. the record is visible to the identity (a hidden record does not exist: 404);
7. the model's own rules, which stand **above** every grant: a state is never written, a decision-critical property
   needs its writer rule, a ``write_access`` rule refuses a role it does not name, the requester decides no review
   of their own request.

A form, a manifest and a screen are not among the things it reads: a generated form is never an authorisation.
The unrestricted permission keeps passing where it passes today, and stays bound by the rules of step 7 that bind
it today.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

POLICY = "operations-v1 (proposed, not in force)"
UNRESTRICTED = "admin"

#: The twelve operations. ``today``: what lets it through now. ``right``: what would, under the proposal.
#: ``new``: the right does not exist today. ``caller``: whether any caller can be granted it at all.
OPERATIONS: Dict[str, Dict[str, Any]] = {
    "records.read": {"label": "Read records", "today": "read", "right": "read", "new": False, "caller": True,
                     "scope": "rows and fields the model's rules allow",
                     "enforced": "server.AutologyService.visible, server.AutologyService.object_view"},
    "records.create": {"label": "Create records", "today": "admin", "right": "records.create", "new": True, "caller": True,
                       "scope": "named entity types of one use case, named properties, the initial state only",
                       "enforced": "server.AutologyService.upsert_object"},
    "records.update": {"label": "Update permitted fields", "today": "admin", "right": "records.update", "new": True, "caller": True,
                       "scope": "named properties of named entity types, in the workflow states the grant names",
                       "enforced": "server.AutologyService.upsert_object"},
    "records.archive": {"label": "Delete or archive records", "today": "not available: no route deletes a record",
                        "right": "records.archive", "new": True, "caller": True,
                        "scope": "archive only, named entity types, never a record with open work; nothing is deleted",
                        "enforced": "server.AutologyService.upsert_object"},
    "actions.request": {"label": "Request an action", "today": "run", "right": "run", "new": False, "caller": True,
                        "scope": "ask for a run on a visible record; the Engine plans and checks every rule",
                        "enforced": "server.AutologyService.start_run"},
    "actions.execute": {"label": "Execute an authorized action", "today": "the Engine, inside a run", "right": None,
                        "new": False, "caller": False, "scope": "no caller executes; a run does, after every rule",
                        "enforced": "runs.RunService"},
    "reviews.request": {"label": "Request review", "today": "the Engine, when a run reaches a review rule", "right": None,
                        "new": False, "caller": False, "scope": "no caller asks for a review or names a reviewer",
                        "enforced": "runs.RunService"},
    "reviews.decide": {"label": "Decide a review", "today": "review", "right": "review", "new": False, "caller": True,
                       "scope": "a person holding the reviewer role; never the requester, never a service identity",
                       "enforced": "server.AutologyService.require_person"},
    "data.administer": {"label": "Administer domain data", "today": "admin", "right": "admin", "new": False, "caller": True,
                        "scope": "unrestricted, acknowledged by two people; exceptional, never routine",
                        "enforced": "server.AutologyService.upsert_object"},
    "ontology.modify": {"label": "Modify ontology", "today": "configure", "right": "configure", "new": False, "caller": True,
                        "scope": "drafts only; a second person publishes",
                        "enforced": "server.AutologyService.require"},
    "releases.manage": {"label": "Manage releases", "today": "workspace administrator and a release approver",
                        "right": "office:administrator", "new": False, "caller": True,
                        "scope": "propose and activate; another person approves",
                        "enforced": "platform.Platform.may_approve_releases"},
    "permissions.administer": {"label": "Administer permissions", "today": "workspace administrator",
                               "right": "office:administrator", "new": False, "caller": True,
                               "scope": "propose a grant for someone else; a second person approves",
                               "enforced": "platform.Platform"},
}
NEW_RIGHTS = sorted(o["right"] for o in OPERATIONS.values() if o["new"])
PERSONS_ONLY = ("reviews.decide", "ontology.modify", "releases.manage", "permissions.administer", "data.administer")
RECORD_WRITES = ("records.create", "records.update", "records.archive")


def in_force(grant: Dict[str, Any]) -> bool:
    """A grant counts once a person other than its proposer and other than its holder approved it."""
    approver = grant.get("approved_by")
    return bool(approver and approver != grant.get("proposed_by") and approver != grant.get("member")
                and grant.get("approver_kind", "person") == "person")


def _answer(allowed: bool, status: int, check: str, reason: str, operation: str) -> Dict[str, Any]:
    spec = OPERATIONS.get(operation, {})
    return {"allowed": allowed, "status": status, "check": check, "reason": reason, "operation": operation,
            "would_be_enforced_in": spec.get("enforced"), "policy": POLICY, "in_force": False}


def decide(request: Dict[str, Any], grants: List[Dict[str, Any]], model: Dict[str, Any]) -> Dict[str, Any]:
    """Whether ``request`` would be allowed under the proposal. Pure: it reads its arguments and nothing else."""
    operation = str(request.get("operation"))

    def no(status: int, check: str, reason: str) -> Dict[str, Any]:
        return _answer(False, status, check, reason, operation)

    spec = OPERATIONS.get(operation)
    if spec is None:
        return no(400, "operation", f"{operation} is not one of the {len(OPERATIONS)} operations")
    if not spec["caller"]:
        return no(403, "caller", f"{spec['label'].lower()}: {spec['scope']}")
    who = request.get("identity") or {}
    name, kind, roles = who.get("name"), who.get("kind"), set(who.get("roles") or [])
    if kind not in ("person", "service") or not name:
        return no(401, "identity", "no authenticated identity")
    if kind == "service" and operation in PERSONS_ONLY:
        return no(403, "identity", f"a service identity does not {spec['label'].lower()}")
    workspace, use_case = request.get("workspace"), request.get("use_case")
    mine = [g for g in grants if g.get("member") == name and g.get("workspace") == workspace and in_force(g)]
    if spec["right"] == "office:administrator":  # an office of the workspace, never a data permission
        if "administrator" not in (who.get("office") or []):
            return no(403, "grant", "needs the workspace administrator's office")
        if request.get("target") == name or request.get("approves_own"):
            return no(403, "separation", "nobody proposes for themselves or approves what they proposed")
        return _answer(True, 200, "office", "an administrator proposes; a second person approves", operation)
    held = [g for g in mine if g.get("use_case") == use_case]
    unrestricted = any(g.get("permission") == UNRESTRICTED and g.get("unrestricted") is True for g in held)
    grant: Optional[Dict[str, Any]] = next((g for g in held if g.get("permission") == spec["right"]), None)
    if operation == "data.administer":
        if not unrestricted:
            return no(403, "grant", "needs the unrestricted permission, acknowledged by two people")
        return _answer(True, 200, "grant", "unrestricted, as today", operation)
    if grant is None and not (unrestricted and operation in RECORD_WRITES[:2]):
        return no(403, "grant", f"no grant in force gives {spec['right']} on {workspace}/{use_case}")

    entity = request.get("entity")
    record = request.get("record") or {}
    if operation.startswith("records.") or operation == "actions.request":
        shape = (model.get("entities") or {}).get(str(entity))
        if shape is None:
            return no(400, "entity", f"the model has no entity type {entity}")
        scoped = grant is not None and "entities" in grant  # read and run are not scoped by entity type today
        if scoped and entity not in grant["entities"]:  # type: ignore[index]
            return no(403, "entity", f"the grant does not name {entity}")
        exists = operation != "records.create"
        if exists and not record.get("visible", False):
            return no(404, "visibility", "no such record")  # hidden and absent are the same answer
        if operation in RECORD_WRITES:
            refusal = _write(operation, request, grant, shape, roles, record)
            if refusal:
                return no(refusal[0], refusal[1], refusal[2])
        if operation == "actions.request" and record.get("open_run"):
            return no(409, "workflow", "work is already open on this record")
    if operation == "reviews.decide":
        review = request.get("review") or {}
        if review.get("requested_by") == name:
            return no(403, "separation", "nobody decides the review of their own request")
        if not set(review.get("reviewer_roles") or []) & set(who.get("reviewer_roles") or []):
            return no(403, "role", "the review rule names a reviewer role this person does not hold")
    return _answer(True, 200, "grant" if grant is not None else "unrestricted",
                   f"{spec['right']} in force" if grant is not None else "unrestricted, as today", operation)


def _write(operation: str, request: Dict[str, Any], grant: Optional[Dict[str, Any]], shape: Dict[str, Any],
           roles: set, record: Dict[str, Any]) -> Optional[tuple]:
    """Why a write is refused, or None. The model's rules bind every writer, the unrestricted one included."""
    entity, properties = str(request.get("entity")), list(request.get("properties") or [])
    if operation == "records.archive":
        if properties or request.get("links"):
            return 403, "properties", "archiving changes nothing but the archive mark"
        if not shape.get("archivable"):
            return 403, "workflow", f"the model declares no archive for {entity}; nothing is ever deleted"
        if record.get("open_run"):
            return 409, "workflow", "work is open on this record"
        return None
    if "status" in properties or request.get("sets_state"):
        return 403, "state", "a state is changed by an action in a run, never written"
    for prop in properties:
        if prop not in (shape.get("properties") or []):
            return 400, "properties", f"{entity} has no property {prop}"
        writers = (shape.get("write_access") or {}).get(prop)
        if prop in (shape.get("decision_critical") or []) and not writers:
            return 403, "rule", f"{entity}.{prop} is decision-critical and no rule names who may write it"
        if writers is not None and not roles & set(writers):
            return 403, "rule", f"a write rule on {entity}.{prop} names roles this identity does not hold"
    if grant is None:  # the unrestricted permission: nothing narrower to check
        return None
    allowed = set((grant.get("properties") or {}).get(entity) or [])
    extra = [p for p in properties if p not in allowed]
    if extra:
        return 403, "properties", f"the grant does not name {entity}.{extra[0]}"
    if request.get("links") and not set(request["links"]) <= set(grant.get("links") or []):
        return 403, "properties", "the grant names no such relationship"
    if operation == "records.update":
        states = grant.get("states")
        if states is not None and record.get("state") not in states:
            return 409, "workflow", f"the grant does not allow changes in the state {record.get('state')}"
    return None


__all__ = ["POLICY", "OPERATIONS", "NEW_RIGHTS", "decide", "in_force"]
