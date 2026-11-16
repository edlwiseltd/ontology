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
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

from . import architect
from .ai import DATA_CLASSES, ModelGateway, ProviderError, WorkspaceAI
from .ai_policy import terms_fingerprint
from .sandbox_ai import MODEL, SandboxArchitect
from .server import ApiError, User
from .store import RecordConflict

if TYPE_CHECKING:
    from .server import AutologyService

APPROVED_PROVIDERS = ("sandbox",)  # extended only by an owner decision (D7, D10)
STATUS = {"not_configured": 409, "not_allowed": 409, "budget_exceeded": 409, "invalid_request": 400,
          "in_progress": 409, "auth": 502,
          "rate_limited": 503, "unavailable": 503, "timeout": 504, "cancelled": 503, "refused": 502, "truncated": 502,
          "tool_request": 502, "invalid_response": 502, "failed": 502}


AI_KEYS = {"provider", "model", "policy", "data_classes", "content"}


def check_setting(spec: Any) -> Tuple[str, ...]:
    """The data classes a use case's ``ai`` setting covers. Raises ``ValueError`` on a setting that is not one.

    ``{"provider": ..., "model": ..., "policy": ..., "data_classes": [...], "content": "synthetic"}``. The sandbox
    test double needs only ``provider``. Any other provider is named with its exact ``model`` and the ``policy``
    terms it was configured under (the fingerprint the workspace's AI page shows): the setting is part of the use
    case's governing configuration, so a release says which model it may ask and under which terms.
    ``content: synthetic`` is the operator's statement that everything this use case sends is invented data."""
    if not isinstance(spec, Mapping) or set(spec) - AI_KEYS or not isinstance(spec.get("provider"), str):
        raise ValueError("ai: {\"provider\": ..., \"model\": ..., \"policy\": ..., \"data_classes\": [...], "
                         "\"content\": \"synthetic\"} (the sandbox needs only the provider)")
    classes = tuple(spec.get("data_classes") or ("synthetic", "model_design"))
    if set(classes) - set(DATA_CLASSES):
        raise ValueError(f"ai.data_classes: taken from {list(DATA_CLASSES)}")
    if spec.get("content") not in (None, "synthetic"):
        raise ValueError("ai.content: \"synthetic\" (everything this use case sends is invented data), or nothing")
    for key in ("model", "policy"):
        if key in spec and not (isinstance(spec[key], str) and 1 <= len(spec[key]) <= 120):
            raise ValueError(f"ai.{key}: text")
    if spec["provider"] in APPROVED_PROVIDERS:
        if spec.get("model") not in (None, MODEL) or "policy" in spec:
            raise ValueError(f"ai: the sandbox is the test double {MODEL!r}; it has no other model and no policy terms")
    elif "model" not in spec or "policy" not in spec:
        raise ValueError(f"ai: the provider {spec['provider']!r} is named with its exact model and the policy terms "
                         "it is configured under: {\"provider\", \"model\", \"policy\"}")
    return classes


def build_gateway(spec: Any, workspace: str, grant: Optional[Mapping[str, Any]] = None
                  ) -> Tuple[Optional[ModelGateway], str]:
    """``(gateway, why not)``: the engine's AI gateway from its ``ai`` configuration, or None with the reason.

    The sandbox test double needs nothing else. Any other provider is reachable only with a ``grant`` from the
    platform: the workspace's approved policy, covered by the owner's authorisation, with an adapter and a budget
    (:mod:`autology.ai_policy`), **and only when the use case names that policy's provider, exact model and
    terms**. A policy that moved to another model, or whose terms changed, serves this use case nothing until a
    new release of the use case names it. An engine on its own can never configure one: it has no grant to show."""
    if spec is None:
        return None, "this use case's configuration names no AI provider"
    if grant is None and isinstance(spec, Mapping) and isinstance(spec.get("provider"), str) \
            and spec["provider"] not in APPROVED_PROVIDERS:
        raise ValueError(f"ai.provider {spec['provider']!r} is not approved: only {list(APPROVED_PROVIDERS)} may be "
                         "configured until the owner approves a provider and its data (decisions D7, D10)")
    classes = check_setting(spec)
    policy = (grant or {}).get("policy")
    if spec["provider"] in APPROVED_PROVIDERS:
        config = WorkspaceAI("sandbox", MODEL, classes)
        budget = None
        if policy is not None and policy["provider"] == "sandbox":  # a workspace may bound even the test double
            config = WorkspaceAI("sandbox", MODEL, tuple(c for c in classes if c in policy["data_classes"]) or classes,
                                 policy["limits"]["max_attempts"], policy["limits"]["timeout_seconds"],
                                 policy["limits"]["max_output_tokens"])
            budget = grant.get("budget") if grant else None
        return ModelGateway({"sandbox": SandboxArchitect()}, {workspace: config}, budget=budget), ""
    if policy is None or policy["provider"] != spec["provider"] or grant is None or grant.get("adapter") is None:
        return None, str((grant or {}).get("refused") or f"the workspace has no approved, authorised policy for "
                                                        f"{spec['provider']}")
    if policy["model"] != spec["model"]:
        return None, (f"this use case is configured for the model {spec['model']}; the workspace's approved policy "
                      f"names {policy['model']}. A model changes only through a new release of the use case")
    if terms_fingerprint(policy) != spec["policy"]:
        return None, (f"this use case is configured under the policy terms {spec['policy']}; the workspace's "
                      f"approved policy now has the terms {terms_fingerprint(policy)} (what may be sent, or for "
                      "what, changed). The use case is served again once a new release names them")
    allowed = tuple(c for c in classes if c in policy["data_classes"])
    if not allowed:
        return None, "the workspace's AI policy allows none of the data classes this use case would send"
    config = WorkspaceAI(policy["provider"], policy["model"], allowed, policy["limits"]["max_attempts"],
                         policy["limits"]["timeout_seconds"], policy["limits"]["max_output_tokens"])
    return ModelGateway({policy["provider"]: grant["adapter"]}, {workspace: config}, budget=grant["budget"]), ""


class ArchitectService:
    def __init__(self, engine: "AutologyService", config: Mapping[str, Any]):
        self.engine = engine
        self.workspace = "engine"  # one gateway per engine: nothing is shared between use cases
        self.wanted = config.get("ai")  # what the use case's (governing) configuration asks for
        # what a brief typed into this use case is: a model design, unless the operator declared the use case
        # synthetic (an evaluation or demonstration that holds only invented data)
        self.content = "synthetic" if isinstance(self.wanted, Mapping) and self.wanted.get("content") == "synthetic" \
            else "model_design"
        self.gateway, self.unavailable = build_gateway(self.wanted, self.workspace, config.get("ai_grant"))

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
            raise ApiError(409, f"no AI provider is available to this use case: {self.unavailable} (a real "
                                "provider needs the owner's decisions D7 and D10 and an approved workspace policy); "
                                "the blueprint generator is available", {"kind": "not_configured"})
        answers = self._answers(previous, body.get("answers"))
        feedback = body.get("feedback", "")
        if not isinstance(feedback, str) or len(feedback) > 2000:
            raise ApiError(400, "feedback: what to change in the proposal, up to 2000 characters")
        try:
            limits = self.gateway.describe(self.workspace)
            result = architect.propose(self.gateway, self.workspace, brief, base, answers=answers, feedback=feedback,
                                       data_classes=(self.content,), deadline_seconds=limits["max_deadline_seconds"],
                                       max_output_tokens=limits["max_output_tokens"])
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
            wanted = self.wanted.get("provider") if isinstance(self.wanted, Mapping) else None
            return {"configured": False, "generators": ["blueprint"], "wanted": wanted,
                    "wanted_model": self.wanted.get("model") if isinstance(self.wanted, Mapping) else None,
                    "content": self.content,
                    # "none": nothing is asked for; "not_authorised": a provider is named but may not be reached
                    "state": "not_authorised" if wanted else "none", "reason": self.unavailable}
        described = self.gateway.describe(self.workspace)
        caps = described["capabilities"]
        return {"configured": True, "generators": ["blueprint", "model"], "provider": caps["provider"],
                "model": described["model"], "data_classes": described["data_classes"],
                "language_model": caps["language_model"], "verified_against": caps["verified_against"],
                # a test double is never called a model; a real provider is named with its model
                "state": "authorised" if caps["language_model"] else "sandbox", "reason": "",
                "bounded": self.gateway.budget is not None, "content": self.content,
                "policy_terms": self.wanted.get("policy") if isinstance(self.wanted, Mapping) else None}

    def attach(self, grant: Optional[Mapping[str, Any]]) -> None:
        """Take the workspace's AI policy as it is now (the platform calls this when a policy is approved,
        disabled or expires). The use case's own setting does not change: only whether it may be served."""
        self.gateway, self.unavailable = build_gateway(self.wanted, self.workspace, grant)

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
