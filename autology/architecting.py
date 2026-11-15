"""The AI Architect of one engine: proposals through the versioned API, with their history (ARC-0 service).

``POST /api/v1/architect/proposals`` has two generators. ``blueprint`` (the default, unchanged) matches approved
templates and stores nothing. ``model`` goes through the engine's AI gateway (:mod:`autology.ai`) and the proposal
contract (:mod:`autology.architect`): the answer is checked against the contract, every item is validated by the
engine's strict loader, and the result is **stored as a revision** with who asked, the brief, the answers given to
clarification questions, the provider and model, the assumptions, the rejected items and the validation result.
Answering questions or asking again creates the next revision of the same proposal; nothing is ever overwritten.
A person's review (which items were accepted or rejected) is recorded against a revision.

What this service cannot do, by construction: change the active model, save a draft, grant anything, publish or
activate a release, call a tool. Accepted items reach a draft only through ``POST /api/v1/model/draft`` by a person
with ``configure``; a draft becomes active only through a release approved by another person.

**Providers.** An engine has an AI gateway only if its configuration says so (``"ai": {"provider": "sandbox"}``).
Until the owner approves a provider and the data it may receive (decisions D7, D10), ``sandbox`` - a deterministic
test double that contacts nothing (:mod:`autology.sandbox_ai`) - is the only value accepted: any other is refused
when the engine starts. Every permission is asked of the engine this service belongs to.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional

from . import architect
from .ai import DATA_CLASSES, ModelGateway, ProviderError, WorkspaceAI
from .sandbox_ai import MODEL, SandboxArchitect
from .server import ApiError, User
from .store import RecordConflict

if TYPE_CHECKING:
    from .server import AutologyService

APPROVED_PROVIDERS = ("sandbox",)  # extended only by an owner decision (D7, D10)
STATUS = {"not_configured": 409, "not_allowed": 409, "invalid_request": 400, "in_progress": 409, "auth": 502,
          "rate_limited": 503, "unavailable": 503, "timeout": 504, "cancelled": 503, "refused": 502, "truncated": 502,
          "tool_request": 502, "invalid_response": 502, "failed": 502}


def build_gateway(spec: Any, workspace: str) -> Optional[ModelGateway]:
    """The engine's AI gateway from its ``ai`` configuration, or None when there is none."""
    if spec is None:
        return None
    if not isinstance(spec, Mapping) or set(spec) - {"provider", "data_classes"} or "provider" not in spec:
        raise ValueError("ai: {\"provider\": ..., \"data_classes\": [...]} (data_classes is optional)")
    if spec["provider"] not in APPROVED_PROVIDERS:
        raise ValueError(f"ai.provider {spec['provider']!r} is not approved: only {list(APPROVED_PROVIDERS)} may be "
                         "configured until the owner approves a provider and its data (decisions D7, D10)")
    classes = tuple(spec.get("data_classes") or ("synthetic", "model_design"))
    if set(classes) - set(DATA_CLASSES):
        raise ValueError(f"ai.data_classes: taken from {list(DATA_CLASSES)}")
    return ModelGateway({"sandbox": SandboxArchitect()}, {workspace: WorkspaceAI("sandbox", MODEL, classes)})


class ArchitectService:
    def __init__(self, engine: "AutologyService", config: Mapping[str, Any]):
        self.engine = engine
        self.workspace = "engine"  # one gateway per engine: nothing is shared between use cases
        self.gateway = build_gateway(config.get("ai"), self.workspace)

    # -- asking -----------------------------------------------------------------------------------------
    def architect_proposals(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        from .modeling import propose

        e = self.engine
        e.require(user, "configure")
        generator = body.get("generator", "blueprint")
        if generator not in ("blueprint", "model"):
            raise ApiError(400, "generator: blueprint or model")
        previous = self._latest(str(body["revises"])) if body.get("revises") else None
        brief = body.get("brief") if body.get("brief") is not None else (previous or {}).get("brief")
        if not isinstance(brief, str) or not 1 <= len(brief.strip()) <= 4000:
            raise ApiError(400, "brief: 1 to 4000 characters describing the business")
        base = body.get("document")
        if not isinstance(base, dict):
            row = e.store.draft()
            base = row["document"] if row else e._active_document()
        if generator == "blueprint":
            return propose(brief, base)
        if self.gateway is None:
            raise ApiError(409, "no AI provider is configured for this use case (owner decisions D7 and D10); the "
                                "blueprint generator is available")
        answers = self._answers(previous, body.get("answers"))
        try:
            result = architect.propose(self.gateway, self.workspace, brief, base, answers=answers)
        except architect.ArchitectError as exc:
            raise ApiError(400, str(exc)) from None
        except ProviderError as exc:
            raise ApiError(STATUS[exc.kind], f"the architect gave no usable proposal ({exc.kind}): {exc}",
                           {"kind": exc.kind, "retryable": exc.retryable}) from None
        pid = previous["id"] if previous else f"P-{uuid.uuid4().hex[:10]}"
        try:
            e.store.add_architect_revision(pid, user.name, brief, answers, result, previous["revision"] if previous else 0)
        except RecordConflict as exc:
            raise ApiError(409, f"{exc}; read the proposal again", {"revision": exc.revision}) from None
        return self.get_proposal(user, pid)

    @staticmethod
    def _answers(previous: Optional[Mapping[str, Any]], given: Any) -> List[Dict[str, Any]]:
        """Earlier answers with the new ones over them (by question id)."""
        if given is not None and not (isinstance(given, list) and all(
                isinstance(a, dict) and isinstance(a.get("id"), str) and isinstance(a.get("answer"), (str, int, float))
                and not isinstance(a.get("answer"), bool) for a in given)):
            raise ApiError(400, "answers: a list of {\"id\": question id, \"answer\": text or number}")
        merged = {a["id"]: a["answer"] for a in (previous or {}).get("answers", [])}
        merged.update({a["id"][:64]: a["answer"] for a in given or []})
        if len(merged) > 40:
            raise ApiError(400, "answers: at most 40")
        return [{"id": k, "answer": str(v)[:500]} for k, v in merged.items()]

    # -- reading ----------------------------------------------------------------------------------------
    def _revisions(self, pid: str) -> List[Dict[str, Any]]:
        rows = self.engine.store.architect_revisions(pid)
        if not rows:
            raise ApiError(404, f"no proposal {pid!r}")
        return rows

    def _latest(self, pid: str) -> Dict[str, Any]:
        return self._revisions(pid)[-1]

    @staticmethod
    def _counts(row: Mapping[str, Any]) -> Dict[str, Any]:
        result = row["result"]
        return {"revision": row["revision"], "at": row["at"], "created_by": row["created_by"],
                "answers": row["answers"], "items": len(result["items"]), "rejected": len(result["rejected"]),
                "open_questions": len(result["questions"])}

    def list_proposals(self, user: User) -> Dict[str, Any]:
        e = self.engine
        e.require_any(user, "read", "configure")
        threads: Dict[str, List[Dict[str, Any]]] = {}
        for row in e.store.architect_revisions():
            threads.setdefault(row["id"], []).append(row)
        items = [{"id": pid, "brief": rows[-1]["brief"][:200], "revisions": len(rows),
                  "generator": rows[-1]["result"]["generator"], "ai": rows[-1]["result"]["ai"],
                  "provider": rows[-1]["result"]["provider"], "decisions": len(e.store.architect_decisions(pid)),
                  **self._counts(rows[-1])} for pid, rows in threads.items()]
        return {"items": sorted(items, key=lambda i: i["at"], reverse=True), "architect": self.status()}

    def status(self) -> Dict[str, Any]:
        """Whether this engine has an architect provider, and what kind (never a credential)."""
        if self.gateway is None:
            return {"configured": False, "generators": ["blueprint"]}
        caps = self.gateway.describe(self.workspace)["capabilities"]
        return {"configured": True, "generators": ["blueprint", "model"], "provider": caps["provider"],
                "language_model": caps["language_model"], "verified_against": caps["verified_against"]}

    def get_proposal(self, user: User, pid: str, revision: Optional[int] = None) -> Dict[str, Any]:
        e = self.engine
        e.require_any(user, "read", "configure")
        rows = self._revisions(pid)
        row = rows[-1] if revision is None else next((r for r in rows if r["revision"] == revision), None)
        if row is None:
            raise ApiError(404, f"proposal {pid} has no revision {revision}")
        return {"id": pid, "revision": row["revision"], "latest_revision": rows[-1]["revision"],
                "created_by": row["created_by"], "at": row["at"], "brief": row["brief"], **row["result"],
                "answers": row["answers"], "history": [self._counts(r) for r in rows],
                "decisions": e.store.architect_decisions(pid)}

    # -- a person's review --------------------------------------------------------------------------------
    def decide_proposal(self, user: User, pid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Record which items of a revision a person accepted or rejected. It changes no model: accepted items
        reach a draft only when that person saves one."""
        e = self.engine
        e.require(user, "configure")
        e.require_person(user, "review a proposal")
        rows = self._revisions(pid)
        revision = body.get("revision", rows[-1]["revision"])
        row = next((r for r in rows if r["revision"] == revision), None)
        if row is None:
            raise ApiError(404, f"proposal {pid} has no revision {revision!r}")
        accepted, rejected = self._ids(body.get("accepted"), "accepted"), self._ids(body.get("rejected"), "rejected")
        known = {i["id"] for i in row["result"]["items"]}
        unknown = sorted((set(accepted) | set(rejected)) - known)
        if unknown or set(accepted) & set(rejected) or not (accepted or rejected):
            raise ApiError(400, "accepted and rejected: distinct ids of this revision's provisional items"
                           + (f" (unknown: {unknown[:5]})" if unknown else ""))
        e.store.add_architect_decision(pid, row["revision"], user.name, accepted, rejected, str(body.get("note") or ""))
        return self.get_proposal(user, pid, row["revision"])

    # -- trying a model before it is published ---------------------------------------------------------------
    def simulate_draft(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        """A dry run of a model document (the one given, else the draft, else the active model) with stub tools:
        see :mod:`autology.simulation`. Nothing is stored and nothing outside the engine is called."""
        from .simulation import SimulationError, simulate

        e = self.engine
        e.require(user, "configure")
        document = body.get("document")
        if not isinstance(document, dict):
            row = e.store.draft()
            document = row["document"] if row else e._active_document()
        approvals = body.get("approvals") or []
        if not isinstance(approvals, list) or len(approvals) > 20:
            raise ApiError(400, "approvals: a list of at most 20 simulated decisions")
        roles = body.get("roles")
        if roles is not None and not (isinstance(roles, list) and all(isinstance(r, str) for r in roles)):
            raise ApiError(400, "roles: a list of role names")
        try:
            out = simulate(document, body.get("case"), body.get("goal"), roles, approvals)
        except SimulationError as exc:
            raise ApiError(400, str(exc)) from None
        return {**out, "requested_by": user.name}

    @staticmethod
    def _ids(value: Any, name: str) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value) or len(value) > 500:
            raise ApiError(400, f"{name}: a list of item ids")
        return list(dict.fromkeys(value))
