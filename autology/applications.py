"""Applications on a released solution: the Engine's side of the Application Builder.

An application manifest (:mod:`autology.appspec`) is generated from **what runs** (the released model and the
approved agents), adjusted by a person in Studio's designer, validated here, and saved as an append-only draft
bound to the exact configuration it was made for. A renderer asks ``GET /api/v1/application`` and receives the
manifest **as this caller may use it**, or a refusal:

* nothing was designed yet: 404;
* the configuration that runs is not the one the manifest was designed for (a new release, a rollback, another
  use case's manifest): 409, with both fingerprints. The Engine does not guess that the old screens still fit;
* the saved manifest no longer validates against the model that runs: 409.

Being given a manifest gives a caller nothing else: every record, run, review and audit entry is still asked from
the Engine's ordinary routes, which apply the model's rules to this caller as they always do.

Design drafts are previews. They are not part of a governed release (see docs/application-builder.md for what
publishing an application with its release would need); nothing here activates anything.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping

from . import appspec

if TYPE_CHECKING:
    from .server import AutologyService

HEADER = "X-Autology-Configuration"


def of(engine: "AutologyService") -> "ApplicationService":
    """The engine's application service (made on first use, kept with the engine)."""
    found = engine.__dict__.get("_applications")
    if found is None:
        found = engine.__dict__["_applications"] = ApplicationService(engine)
    return found


def expect_configuration(engine: "AutologyService", headers: Any) -> None:
    """A request may name the configuration it was written for (``X-Autology-Configuration``). When another one
    runs, the Engine refuses it instead of answering for a solution the caller did not mean: the same idea as
    ``expected_revision`` on a record. A request that names none is served as always."""
    from .server import ApiError

    expected = headers.get(HEADER) if headers is not None else None
    if expected and expected != engine.configuration_fingerprint:
        raise ApiError(409, "this request was written for another configuration of the use case than the one that "
                            "runs now (a release was activated or rolled back): read the application again",
                       {"expected": str(expected)[:64], "running": engine.configuration_fingerprint})


class ApplicationService:
    def __init__(self, engine: "AutologyService"):
        self.engine = engine

    # -- what runs ---------------------------------------------------------------------------------------
    def running(self) -> Dict[str, str]:
        e = self.engine
        scope = getattr(e, "scope", None) or {}
        return {"model": e.ontology.ref, "model_fingerprint": e.ontology.fingerprint,
                "configuration": e.configuration_fingerprint, "engine_api": appspec.ENGINE_API,
                **{k: str(scope[k]) for k in ("workspace", "use_case") if scope.get(k)}}

    def _agents(self) -> Dict[str, Dict[str, Any]]:
        return {name: {"goals": list(cfg.goals), "roles": sorted(cfg.agent.principal.roles)}
                for name, cfg in self.engine.agents.items()}

    def _check(self, manifest: Any) -> Dict[str, Any]:
        problems = appspec.validate(manifest, self.engine.ontology, self._agents(), self.running())
        return {"valid": not problems, "problems": problems[:100], "by": "the engine, against the model and "
                "configuration that run", "manifest_version": appspec.MANIFEST_VERSION,
                "digest": appspec.digest(manifest) if not problems else None}

    def _stage(self) -> Dict[str, Any]:
        policy = self.engine.execution_policy()
        return {"stage": policy["stage"] if policy else None, "runs_refused": self.engine._runs_refused() or None,
                "production": False}

    # -- designing (Studio) ------------------------------------------------------------------------------
    def generate(self, user: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
        """A draft manifest generated from what runs. Nothing is saved."""
        from .server import ApiError

        e = self.engine
        e.require_any(user, "read", "configure")
        if not e.ontology.entities:
            raise ApiError(409, "nothing is released yet: an application is generated from the model that runs, "
                                "never from a draft")
        app_id = body.get("id")
        if app_id is not None and not (isinstance(app_id, str) and appspec.NAME.match(app_id)):
            raise ApiError(400, "id: a letter, then letters, digits, _ or -")
        manifest = appspec.generate(e.ontology, self._agents(), self.running(), app_id)
        return {"manifest": manifest, "validation": self._check(manifest), "saved": False, "generator": {
            "kind": "deterministic", "ai": False, "reads": "the released model's structure and the approved agents",
            "note": "no language model was asked; no name or word of the model is interpreted"}}

    def validate(self, user: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
        self.engine.require_any(user, "read", "configure")
        return {"validation": self._check(body.get("manifest")), "running": self.running()}

    def draft(self, user: Any) -> Dict[str, Any]:
        e = self.engine
        e.require_any(user, "read", "configure")
        row = e.store.application_draft()
        history = e.store.application_draft_history()
        if row is None:
            return {"revision": 0, "manifest": None, "validation": None, "history": history, "running": self.running()}
        return {"revision": row["revision"], "author": row["author"], "at": row["at"], "note": row["note"],
                "manifest": row["manifest"], "validation": self._check(row["manifest"]), "history": history,
                "running": self.running()}

    def save(self, user: Any, body: Mapping[str, Any]) -> Dict[str, Any]:
        """Save a design draft over the revision the designer read. An invalid manifest is never stored."""
        from .server import ApiError
        from .store import RecordConflict

        e = self.engine
        e.require(user, "configure")
        e.require_person(user, "save an application design")
        manifest, expected = body.get("manifest"), body.get("expected_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ApiError(400, "expected_revision: the revision you read (0: no design saved yet)")
        check = self._check(manifest)
        if not check["valid"]:
            raise ApiError(400, "the application design does not validate against what runs: nothing was saved",
                           {"problems": check["problems"][:20]})
        try:
            revision = e.store.save_application_draft(dict(manifest or {}), user.name, str(body.get("note") or ""), expected,
                                                      e.configuration_fingerprint)
        except RecordConflict as exc:
            raise ApiError(409, str(exc), {"revision": exc.revision}) from None
        return {**self.draft(user), "revision": revision, "saved": True}

    # -- using (a renderer) ---------------------------------------------------------------------------------
    def application(self, user: Any) -> Dict[str, Any]:
        """The application as this caller may use it: see the module docstring for the refusals."""
        from .server import ApiError

        e = self.engine
        e.require(user, "read")
        row = e.store.application_draft()
        if row is None:
            raise ApiError(404, "no application has been designed for this use case")
        running = self.running()
        if row["configuration"] != running["configuration"]:
            raise ApiError(409, "this application was designed for another configuration of the use case than the "
                                "one that runs now (a release was activated or rolled back). It is not shown until "
                                "a designer has checked it against what runs",
                           {"designed_for": row["configuration"], "running": running["configuration"]})
        check = self._check(row["manifest"])
        if not check["valid"]:
            raise ApiError(409, "the saved application design no longer validates against what runs",
                           {"problems": check["problems"][:20]})
        roles = set(user.principal.roles) | set(user.reviewer_roles)
        manifest = appspec.tailor(row["manifest"], e.ontology, roles, set(user.permissions))
        can = set(user.permissions)
        person = user.kind == "person"
        return {
            "manifest": manifest, "revision": row["revision"], "digest": check["digest"], "running": running,
            "status": "design preview: not part of a governed release", **self._stage(),
            # what the Engine will let this caller do; a screen shows it, the Engine enforces it on each request
            "you": {"name": user.name, "kind": user.kind, "permissions": sorted(can),
                    "may": {"read_records": "read" in can or "admin" in can,
                            "start_runs": "run" in can and not e._runs_refused(),
                            "decide_reviews": "review" in can and person, "read_audit": "audit" in can,
                            # no narrow permission exists (D24): only an unrestricted grant writes records
                            "write_records": "admin" in can}}}

