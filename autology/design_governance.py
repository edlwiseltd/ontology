"""Governed application designs: a **proposed** lifecycle, tested and **not in force** (owner decision D34, GAP-101).

In force, unchanged: a design is a draft kept by the Engine, validated on every read, bound to one configuration and
part of no release (:mod:`autology.applications`). Nobody approves it. Nothing in the Engine, the platform or the API
calls this module; it stores nothing and activates nothing. It exists so that the owner's decision can be taken on
something that runs and is tested with invented fixtures.

The lifecycle it models::

    draft -> validated -> in_review -> approved -> bound -> simulation -> active
                 ^            |                      (bound, simulation, active) -> suspended -> back
                 +-- rejected-+                      any state -> revoked (final);  active -> superseded (final)

Four things are the owner's to choose and have **no default here**: :func:`policy` refuses a missing choice.

* ``approval``: ``with_release`` (the design is a named part of a release and is approved with it, by the release's
  approver) or ``separate`` (the design is approved on its own, then bound to an approved release);
* ``reviewer``: who may approve under ``separate``: the ``release_approver`` or a distinct ``design_reviewer``;
* ``versioning``: whether a changed design needs a ``new_release`` or only a new ``design_revision`` under the same one;
* ``suspension``: whether ``one_administrator`` or ``two_people`` may suspend.

What does not depend on a choice, and is refused whatever the policy:

* a step out of order; an approval by the author, by a service identity or of a design that changed since it was
  submitted; a binding to a release that is not approved, that its proposer approved, or that is for another model
  or configuration;
* an activation in production (production execution is disabled), and an activation of a release that is not the
  active one;
* a resumption or a revocation by one person; anything after a revocation.

The module adds **no publication authority**: under either option the release it binds to was proposed, approved by
a second person and activated by the platform's existing release governance. A design grants no permission at any
step: ``effective_permissions.granted_by_this_design`` is empty by construction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

POLICY = "governed-design-v1 (proposed, not in force)"
STATES = ("draft", "validated", "in_review", "approved", "bound", "simulation", "active", "suspended", "superseded", "revoked")
OPTIONS: Dict[str, tuple] = {"approval": ("with_release", "separate"), "reviewer": ("release_approver", "design_reviewer"),
                             "versioning": ("new_release", "design_revision"), "suspension": ("one_administrator", "two_people")}
FINAL = ("revoked", "superseded")
SERVED = ("simulation", "active")
ROLLBACK = ("restoring a release restores the design bound to it; a design of another release is never shown on it; "
            "with none, or with one that is suspended or revoked, the application is not shown")


class Refused(Exception):
    """A step the lifecycle does not allow. Nothing was changed."""


def policy(**choices: str) -> Dict[str, str]:
    """The owner's four choices. Every one must be given: there is no default to fall back on."""
    for name, allowed in OPTIONS.items():
        if choices.get(name) not in allowed:
            raise Refused(f"{name} must be chosen by the owner: one of {', '.join(allowed)}")
    if set(choices) - set(OPTIONS):
        raise Refused(f"unknown choice: {sorted(set(choices) - set(OPTIONS))[0]}")
    return dict(choices)


def digest(manifest: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def artifact(manifest: Dict[str, Any], revision: int, author: str, at: str, needs: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The record of one design: everything a reviewer and an auditor need, and no permission."""
    binding = manifest["binding"]
    return {
        "manifest_id": manifest["id"], "version": {"design_revision": revision, "digest": digest(manifest)},
        "workspace": binding.get("workspace"), "use_case": binding.get("use_case"),
        "ontology_fingerprint": binding["model_fingerprint"], "configuration_fingerprint": binding["configuration"],
        "author": author, "reviewers": [], "approval": {"status": "none", "by": None, "at": None, "of_digest": None},
        "release": None,
        "effective_permissions": {"granted_by_this_design": [], "needed_to_use": dict(needs or {})},
        "compatible_runtime": {"manifest_version": manifest["manifest_version"], "engine_api": binding["engine_api"]},
        "audit": [{"event": "created", "by": author, "at": at, "from": None, "to": "draft"}],
        "rollback": ROLLBACK, "state": "draft", "policy": POLICY, "in_force": False}


def _person(actor: Dict[str, Any], what: str) -> str:
    if actor.get("kind") != "person" or not actor.get("name"):
        raise Refused(f"only a person may {what}")
    return str(actor["name"])


def _release(design: Dict[str, Any], release: Optional[Dict[str, Any]], rules: Dict[str, str]) -> Dict[str, Any]:
    """The release a design is approved with or bound to: one the existing release governance approved."""
    if not release or not release.get("approved_by"):
        raise Refused("the release is not approved")
    if release["approved_by"] == release.get("proposed_by"):
        raise Refused("the release was approved by its proposer")
    if (release.get("configuration") != design["configuration_fingerprint"]
            or release.get("model_fingerprint") != design["ontology_fingerprint"]):
        raise Refused("the release is for another model or configuration than the design")
    if rules["approval"] == "with_release" and (release.get("parts") or {}).get("application") != design["version"]["digest"]:
        raise Refused("the release does not contain this design")
    return {"number": release["number"], "fingerprint": release["fingerprint"], "approved_by": release["approved_by"]}


def advance(design: Dict[str, Any], event: str, actor: Dict[str, Any], rules: Dict[str, str], at: str,
            context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The design after ``event``, as a new record. Raises :class:`Refused`, and changes nothing, when it may not happen."""
    policy(**rules)
    ctx, state = context or {}, design["state"]
    new = json.loads(json.dumps(design))
    note: Dict[str, Any] = {}

    def needs(*states: str) -> None:
        if state not in states:
            raise Refused(f"{event} is not possible from {state}")

    if state in FINAL:
        raise Refused(f"the design is {state}: nothing follows")
    if event == "change":  # an approval is of one digest: a changed design starts again
        needs("draft", "validated", "in_review", "approved")
        _person(actor, "change a design")
        new["version"] = {"design_revision": design["version"]["design_revision"] + 1, "digest": ctx["digest"]}
        new["approval"] = {"status": "none", "by": None, "at": None, "of_digest": None}
        new["release"], target = None, "draft"
    elif event == "validate":  # the Engine's check of this digest against what runs; nobody asserts it
        needs("draft")
        check = ctx.get("check") or {}
        if actor.get("kind") != "engine" or not check.get("valid") or check.get("digest") != design["version"]["digest"]:
            raise Refused("only the Engine's own check of this exact design validates it")
        target = "validated"
    elif event == "submit":
        needs("validated")
        if _person(actor, "submit a design") != design["author"]:
            raise Refused("a design is submitted by its author")
        target = "in_review"
    elif event in ("approve", "reject"):
        needs("in_review")
        name = _person(actor, f"{event} a design")
        if name == design["author"]:
            raise Refused("nobody decides on their own design")
        new["reviewers"] = sorted(set(design["reviewers"]) | {name})
        if event == "reject":
            target, note = "draft", {"reason": ctx.get("reason")}
        else:
            if rules["approval"] == "with_release":  # one authority: the release's approver approved the design in it
                if _release(design, ctx.get("release"), rules)["approved_by"] != name:
                    raise Refused("under this policy a design is approved by the approver of the release that contains it")
            elif rules["reviewer"] not in (actor.get("offices") or []):
                raise Refused(f"needs the office of {rules['reviewer'].replace('_', ' ')}")
            new["approval"] = {"status": "approved", "by": name, "at": at, "of_digest": design["version"]["digest"]}
            target = "approved"
    elif event == "bind":
        needs("approved")
        if design["approval"]["of_digest"] != design["version"]["digest"]:
            raise Refused("the approval is of another version of the design")
        new["release"], target = _release(design, ctx.get("release"), rules), "bound"
    elif event in ("simulate", "activate"):
        needs("bound" if event == "simulate" else "simulation")
        if not ctx.get("release_active") or ctx.get("active_release") != (design["release"] or {}).get("number"):
            raise Refused("the release the design is bound to is not the active one")
        stage = ctx.get("stage")
        if stage == "production":
            raise Refused("production execution is disabled")
        if stage not in (("simulation",) if event == "simulate" else ("simulation", "pilot")):
            raise Refused(f"not possible in the stage {stage}")
        target = "simulation" if event == "simulate" else "active"
    elif event == "suspend":
        needs("bound", "simulation", "active")
        name = _person(actor, "suspend a design")
        if "administrator" not in (actor.get("offices") or []):
            raise Refused("needs the workspace administrator's office")
        if rules["suspension"] == "two_people" and ctx.get("second") in (None, name):
            raise Refused("a second person must confirm a suspension")
        target, note = "suspended", {"was": state, "reason": ctx.get("reason")}
    elif event in ("resume", "revoke"):  # the direction that widens, and the one that cannot be undone: two people
        if event == "resume":
            needs("suspended")
        name = _person(actor, f"{event} a design")
        second = ctx.get("second") or {}
        if second.get("kind") != "person" or second.get("name") in (None, name):
            raise Refused(f"a second person must confirm: nobody may {event} a design alone")
        target = "revoked" if event == "revoke" else next(e["was"] for e in reversed(design["audit"]) if e["event"] == "suspend")
        note = {"second": second["name"], "reason": ctx.get("reason")}
    elif event == "supersede":
        needs("active")
        target, note = "superseded", {"by_release": ctx.get("release")}
    else:
        raise Refused(f"unknown step: {event}")
    new["state"] = target
    new["audit"].append({"event": event, "by": actor.get("name") or actor.get("kind"), "at": at, "from": state, "to": target, **note})
    return new


def served(designs: List[Dict[str, Any]], active_release: Optional[int]) -> Optional[Dict[str, Any]]:
    """The one design shown for the release that runs (after an activation or a rollback), or None: nothing is shown."""
    mine = [d for d in designs if (d.get("release") or {}).get("number") == active_release and d["state"] in SERVED]
    return max(mine, key=lambda d: d["version"]["design_revision"]) if mine and active_release is not None else None


def needs_new_release(rules: Dict[str, str]) -> bool:
    """Whether a changed design can only reach users through a new release (it always can under ``with_release``)."""
    policy(**rules)
    return rules["approval"] == "with_release" or rules["versioning"] == "new_release"


def migrate(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Existing design drafts (store schema 20) as lifecycle records: every one a draft, none approved, none lost."""
    out = []
    for row in sorted(rows, key=lambda r: r["revision"]):
        record = artifact(row["manifest"], row["revision"], row["author"], row["at"])
        record["audit"][0]["event"] = "migrated"
        record["audit"][0]["note"] = row.get("note")
        out.append(record)
    return out


__all__ = ["POLICY", "STATES", "OPTIONS", "Refused", "policy", "artifact", "advance", "served", "needs_new_release", "migrate", "digest"]
