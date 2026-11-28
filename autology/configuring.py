"""A use case's executable configuration through the versioned API (ARC-0 service): agents, simulated tools,
sample records, as drafts.

``GET /api/v1/solution/draft`` and ``POST /api/v1/solution/draft`` read and save the configuration part of the
draft (the same revisions as the model draft: the two are published and released together). ``POST
/api/v1/solution/validate`` checks a configuration without saving it; ``POST /api/v1/solution/suggest`` returns a
starting point; ``GET /api/v1/tools/catalog`` lists the approved tools and those that are not available.

Everything here is a draft. A saved configuration changes nothing that runs: it becomes active only when another
person publishes the draft and a release of it is approved and activated (:mod:`autology.platform`). The engine
validates each configuration against the draft's model (:mod:`autology.solution`); Studio decides nothing. A use
case whose agents an operator configured in files is not editable here: Studio manages a configuration only where
no operator did, so it can never silently replace one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from . import proposal_review
from . import solution as solutions
from .server import ApiError, User
from .store import RecordConflict

if TYPE_CHECKING:
    from .server import AutologyService


class ConfigurationService:
    def __init__(self, engine: "AutologyService", config: Mapping[str, Any]):
        self.engine = engine
        # what runs: the solution a release put in place (Studio-managed), or agents an operator wrote in files
        self.active: Optional[Dict[str, Any]] = dict(config["solution"]) if config.get("solution") else None
        self.managed = "studio" if self.active is not None else ("files" if config.get("agents") else "none")

    # -- reading ----------------------------------------------------------------------------------------
    def _draft(self) -> Dict[str, Any]:
        e = self.engine
        row = e.store.draft()
        return {"revision": row["revision"] if row else 0, "author": row["author"] if row else None,
                "at": row["at"] if row else None, "note": row["note"] if row else "",
                "document": row["document"] if row else e._active_document(),
                "solution": row["solution"] if row else None, "saved": bool(row)}

    def _view(self, draft: Mapping[str, Any], candidate: Any) -> Dict[str, Any]:
        e = self.engine
        problems, compiled = solutions.check(candidate, draft["document"]) if candidate is not None else ([], None)
        state = "none" if candidate is None else "invalid" if problems else "validated"
        return {"revision": draft["revision"], "author": draft["author"], "at": draft["at"], "note": draft["note"],
                "solution": candidate, "state": state,
                "validation": {"valid": not problems, "problems": problems,
                               "by": "the engine, against the draft's model"},
                "permissions": solutions.effective_permissions(candidate, draft["document"]) if candidate else {},
                "simulated_tools": sorted(t["name"] for a in (compiled or {}).get("agents", {}).values()
                                          for t in a["tools"]["tools"]),
                "active": {"managed": self.managed, "agents": sorted(e.agents), "solution": self.active,
                           "configuration": e.configuration_fingerprint,
                           "editable": self.managed != "files",
                           "note": {"studio": "this configuration came from a release of a Studio draft",
                                    "files": "the agents of this use case were configured by an operator in files: "
                                             "they are not editable here",
                                    "none": "no agent is configured: nothing can run yet"}[self.managed]},
                "changes": solutions.changes(self.active, candidate),
                "catalog": solutions.catalog()}

    def solution_draft(self, user: User) -> Dict[str, Any]:
        e = self.engine
        e.require_any(user, "read", "configure")
        draft = self._draft()
        return self._view(draft, draft["solution"] if draft["saved"] else self.active)

    def tool_catalog(self, user: User) -> Dict[str, Any]:
        self.engine.require_any(user, "read", "configure")
        return {"items": solutions.catalog(),
                "note": "every available tool is simulated: it is compiled to a decision table and reaches no "
                        "other system"}

    # -- synthetic sample records -------------------------------------------------------------------------
    def sample_status(self) -> Dict[str, Any]:
        """The sample records of the configuration that runs, and which of them were loaded. A configuration
        never loads its samples by itself: a person asks (the platform checks who, and that an approved release
        is what runs)."""
        e = self.engine
        wanted = [str(i.get("id")) for i in ((self.active or {}).get("sample_data") or {}).get("instances") or []]
        marked = e.store.sample_records()
        with e.graph_lock:
            present = set(e.graph._instances)
        return {"available": len(wanted), "loaded": sorted(i for i in wanted if i in marked),
                "already_present": sorted(i for i in wanted if i in present and i not in marked),
                "records_marked_as_samples": len(marked),
                "note": "synthetic records for rehearsal; loaded only on request, never by a release"}

    def load_samples(self, by: str) -> Dict[str, Any]:
        """Load the running configuration's sample records that are not there yet. A record that exists is never
        overwritten; each loaded record is marked as a sample with who loaded it and for which configuration."""
        from .graph import KnowledgeGraph
        from .integrity import record_refusal
        from .ontology import OntologyError
        from .store import ABSENT

        e = self.engine
        data = (self.active or {}).get("sample_data") or {}
        if not data.get("instances"):
            raise ApiError(409, "the configuration that runs has no sample records")
        try:
            candidate = KnowledgeGraph.from_dict(e.ontology, {"instances": [dict(i) for i in data["instances"]],
                                                              "links": [tuple(link) for link in data.get("links") or []]})
        except (OntologyError, KeyError, TypeError, ValueError) as exc:
            raise ApiError(409, f"the sample records do not fit the model that runs: {exc}") from None
        loaded: List[str] = []
        skipped: List[str] = []
        links = 0
        with e.graph_lock:
            for inst in candidate.instances():
                if inst.id in e.graph._instances:
                    skipped.append(inst.id)
                    continue
                refused = record_refusal(e.ontology, e.graph, inst.type, inst.id, inst.attributes, ())
                if refused:  # a decision-critical fact has a named writer: a sample loader is not one
                    raise ApiError(403, f"{refused}; no sample record was loaded after {len(loaded)}")
                e.revisions[inst.id] = e.store.upsert_instance(inst.type, inst.id, inst.attributes, ABSENT)
                e.graph._instances[inst.id] = inst
                loaded.append(inst.id)
            fresh = set(loaded)
            for source, kind, target in candidate._links:
                if (source in fresh or target in fresh) and source in e.graph._instances and target in e.graph._instances:
                    e.graph.link(source, kind, target)
                    e.store.add_link(source, kind, target)
                    links += 1
            e.store.mark_samples(loaded, by, e.configuration_fingerprint)
        e._changed(loaded)
        return {"loaded": loaded, "skipped": skipped, "links": links, "configuration": e.configuration_fingerprint}

    # -- checking and saving ----------------------------------------------------------------------------
    def validate_solution(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        e = self.engine
        e.require_any(user, "read", "configure")
        draft = self._draft()
        if isinstance(body.get("document"), dict):
            draft = {**draft, "document": body["document"]}
        return self._view(draft, body.get("solution"))

    def suggest_solution(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        """A starting configuration for the draft's model: the approved template's, when the model came from a
        stored proposal whose template has one; a plain one otherwise. Nothing is saved."""
        from .modeling import fill, match, parameters
        from .ontology import OntologyError
        from .simulation import sample_case

        e = self.engine
        e.require(user, "configure")
        draft = self._draft()
        document = body["document"] if isinstance(body.get("document"), dict) else draft["document"]
        try:
            from .ontology import Ontology

            onto = Ontology.from_dict(dict(document))
        except OntologyError as exc:
            raise ApiError(400, f"the model does not validate: {exc}") from None
        suggested, source = None, "generic"
        if body.get("proposal"):
            rows = e.store.architect_revisions(str(body["proposal"]))
            if not rows:
                raise ApiError(404, f"no proposal {body['proposal']!r}")
            template, _ = match(rows[-1]["brief"], e.architect.folders)
            if template and template.get("solution"):
                values, _ = parameters(template, {a["id"]: a["answer"] for a in rows[-1]["answers"]})
                candidate = fill(template["solution"], values)
                if not solutions.check(candidate, document)[0]:  # only if it fits the model as it is now
                    suggested, source = candidate, f"template {template['id']}"
            if suggested is None:  # no template: the agents the architect described, as a draft for a person
                candidate = solutions.from_descriptions(document, (rows[-1]["result"].get("suggestions") or {})
                                                        .get("agents") or [])
                if candidate["agents"] and not solutions.check(candidate, document)[0]:
                    suggested, source = candidate, "architect descriptions"
        with e.graph_lock:
            taken = set(e.graph._instances)  # a sample never claims the identifier of a record that exists
        if suggested is None:
            suggested = solutions.suggest(document, sample_case(onto, document), taken)
        elif not suggested.get("sample_data"):
            # agents a person or the architect described come without records: one synthetic case along the
            # model's case template, so that what was configured can be rehearsed (kept only if it fits)
            records = solutions.sample_records(onto, sample_case(onto, document), taken)
            if records and not solutions.check({**suggested, "sample_data": records}, document)[0]:
                suggested = {**suggested, "sample_data": records}
        return {**self._view({**draft, "document": document}, suggested), "source": source, "saved": False}

    def save_solution_draft(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "configure")
        if self.managed == "files":
            raise ApiError(409, "the agents of this use case were configured by an operator in files; Studio "
                                "manages a configuration only where no operator did")
        candidate, expected = body.get("solution"), body.get("expected_revision")
        if candidate is not None and not isinstance(candidate, dict):
            raise ApiError(400, "solution: a configuration object, or null to withdraw the draft configuration")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ApiError(400, "expected_revision is required: the draft revision you read (0 if none)")
        draft = self._draft()
        if candidate is not None:
            problems, _ = solutions.check(candidate, draft["document"])
            if problems:  # an invalid configuration is never stored: there is nothing to publish from it
                raise ApiError(400, "the configuration is not valid: " + "; ".join(p["message"] for p in problems[:3]),
                               {"problems": problems})
        # a configuration saved before any draft of the model: the first draft holds the model that runs, unchanged,
        # and its provenance says exactly that (it is derived from the active model, and nobody authored anything)
        first = None if draft["saved"] else draft["document"]
        runs = None if first is None else proposal_review.classify(first, first, [], user.name)["record"]
        try:
            e.store.save_draft(first, user.name, str(body.get("note") or "configuration saved from Studio")[:500],
                               expected, solution=candidate, provenance=runs)
        except RecordConflict as exc:
            raise ApiError(409, f"{exc}; reload the draft and apply your changes again",
                           {"revision": exc.revision}) from None
        return self.solution_draft(user)
