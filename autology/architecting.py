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
On its own an engine accepts only ``sandbox``, a deterministic test double that contacts nothing
(:mod:`autology.sandbox_ai`). Under a platform a use case may name a real provider with its exact model and policy
terms; it is served only while the workspace's approved policy, the owner's authorisation (decisions D7, D10), the
key and the budget all allow it (:func:`build_gateway`). Every permission is asked of the engine this service
belongs to.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import architect, proposal_review
from .ai import DATA_CLASSES, ModelGateway, ProviderError, WorkspaceAI
from .ai_policy import terms_fingerprint
from .modeling import library
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


def build_gateway(spec: Any, workspace: str, grant: Optional[Mapping[str, Any]] = None,
                  folders: Sequence[Any] = ()) -> Tuple[Optional[ModelGateway], str]:
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
        return ModelGateway({"sandbox": SandboxArchitect(folders)}, {workspace: config}, budget=budget), ""
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
        # the blueprint folders this use case's configuration names: domain templates are configuration, not engine
        self.folders = library(config.get("blueprints"), getattr(engine, "base_dir", "."))
        self.gateway, self.unavailable = build_gateway(self.wanted, self.workspace, config.get("ai_grant"), self.folders)

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
            return propose(brief, base, self.folders)
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
            details: Dict[str, Any] = {"kind": exc.kind, "retryable": exc.retryable}
            if exc.violation_classes:  # why an answer outside the contract was refused, never the answer itself
                details["violations"] = dict(exc.violation_classes)
            raise ApiError(STATUS[exc.kind], f"the architect gave no usable proposal ({exc.kind}): {exc}",
                           details) from None
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
                "open_questions": len(result["questions"]),
                # who generated this revision: a test double is never called a model, and a model is named exactly
                "generator": result.get("generator"), "ai": bool(result.get("ai")),
                "provider": result.get("provider"), "model": result.get("model"),
                "cost_usd": result.get("cost_usd"), "feedback": result.get("feedback") or ""}

    def list_proposals(self, user: User) -> Dict[str, Any]:
        e = self.engine
        e.require_any(user, "read", "configure")
        threads: Dict[str, List[Dict[str, Any]]] = {}
        for row in e.store.architect_revisions():
            threads.setdefault(row["id"], []).append(row)
        items = [{"id": pid, "brief": rows[-1]["brief"][:200], "revisions": len(rows),
                  "decisions": len(e.store.architect_decisions(pid)),
                  # what was already paid for this design session, and where it led: nobody has to ask again
                  "spent_usd": round(sum(float(r["result"].get("cost_usd") or 0) for r in rows), 6),
                  "drafts": [d["draft_revision"] for d in e.store.drafts_from(pid)],
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
        self.gateway, self.unavailable = build_gateway(self.wanted, self.workspace, grant, self.folders)

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
                "decisions": e.store.architect_decisions(pid),
                "corrections": e.store.architect_corrections(pid),
                # where every element stands after people's decisions, and what the kept elements make
                "review": self.review(pid, rows, row["revision"]),
                # what an element's references point to, so that "why was this proposed" can be read: the brief,
                # each answer with the question it answered. Only what this revision was given
                "source_index": self._source_index(rows, row),
                # the drafts saved from this proposal (the engine recorded the link when each was saved)
                "drafts": e.store.drafts_from(pid)}

    @staticmethod
    def _source_index(rows: List[Dict[str, Any]], row: Mapping[str, Any]) -> Dict[str, Dict[str, str]]:
        asked: Dict[str, str] = {}
        for earlier in rows:
            if earlier["revision"] < row["revision"]:
                asked.update({q["id"]: q["question"] for q in earlier["result"].get("questions") or []})
        index: Dict[str, Dict[str, str]] = {"brief": {"kind": "brief", "text": row["brief"][:500]}}
        for answer in row["answers"]:
            index[f"answer:{answer['id']}"] = {"kind": "answer", "question": asked.get(answer["id"], ""),
                                              "text": str(answer["answer"])[:500]}
        return index

    def review(self, pid: str, rows: List[Dict[str, Any]], revision: int) -> Dict[str, Any]:
        """The review of one revision (:mod:`autology.proposal_review`), against the model being designed: the
        draft if there is one, else what runs."""
        e = self.engine
        draft = e.store.draft()
        base = draft["document"] if draft else e._active_document()
        out = proposal_review.report(base, rows, e.store.architect_decisions(pid), e.store.architect_corrections(pid),
                                     revision)
        out.pop("document")  # the model the kept elements make is validated here; a caller reads the model where it lives
        return out

    def draft_origin(self, origin: Any) -> Optional[Dict[str, Any]]:
        """The architect proposal a draft says its model was saved from, checked: the revision must exist in this
        use case. Recorded with the draft, so that a draft and what is released from it can be traced back; a
        draft that names none has no recorded origin, and none is guessed."""
        if origin is None:
            return None
        if not (isinstance(origin, dict) and isinstance(origin.get("proposal"), str)
                and isinstance(origin.get("revision"), int) and not isinstance(origin.get("revision"), bool)
                and not set(origin) - {"proposal", "revision"}):
            raise ApiError(400, 'origin: {"proposal": id, "revision": number} of a stored architect proposal')
        if not any(r["revision"] == origin["revision"] for r in self.engine.store.architect_revisions(origin["proposal"])):
            raise ApiError(400, f"origin: there is no revision {origin['revision']} of a proposal "
                                f"{origin['proposal']!r} in this use case")
        return {"proposal": origin["proposal"], "revision": origin["revision"]}

    @staticmethod
    def draft_provenance(row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        """A draft's recorded origin and the provenance the engine established for it. A draft from before the
        engine established any is reported as unknown; with no draft there is nothing to report."""
        return {"origin": (row or {}).get("origin"), "provenance": None if row is None else row.get("provenance") or {
            "mode": "legacy_unknown", "includes_unknown": True,
            "note": "this draft predates the engine's classification: where its elements come from was never established"}}

    def save_draft(self, document: Dict[str, Any], author: str, note: str, expected: int, origin: Any) -> int:
        """Save a draft revision of the model. Where its elements come from is established here, by the engine,
        from the stored proposals and their reviews (:func:`autology.proposal_review.classify`): a draft may not
        take an element of any proposal that was rejected, or inferred and never confirmed, **whether or not it
        names a proposal**. What a client says about origin is checked and proves nothing."""
        checked = self.draft_origin(origin)
        store = self.engine.store
        row = store.draft()
        # a draft of unknown provenance is not built upon: everything it holds beyond what runs is classified again
        legacy = row is not None and row.get("provenance") is None
        parent = self.engine._active_document() if row is None or legacy else row["document"]
        proposals = [{"id": pid, "revisions": self._revisions(pid), "decisions": store.architect_decisions(pid),
                      "corrections": store.architect_corrections(pid)} for pid in store.architect_proposal_ids()]
        found = proposal_review.classify(document, parent, proposals, author, checked, (row or {}).get("provenance"),
                                         row["revision"] if row else 0, legacy)
        if found["refused"]:
            first = found["refused"][0]
            raise ApiError(409, f"the draft cannot be saved: {len(found['refused'])} element(s) of a stored proposal are "
                                f"not confirmed for it (first: {first['element'] or 'the origin it names'}, proposal "
                                f"{first['proposal']}: {first['why']}). Record the review of these elements first; "
                                "nothing was saved", {"unconfirmed": found["refused"][:50]})
        # the origin recorded is the one the engine found (a named revision that is stale is not taken on trust)
        # "origin" stays what it was: the proposal this revision's model was saved from, as the engine found it
        # (none for a model changed by hand). What the model rests on over all its revisions is in the provenance
        # record, which the engine carries forward and no request can shorten
        return store.save_draft(document, author, note, expected, origin=found["origin"] or checked,
                                provenance=found["record"])

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
        corrected = self._corrections(body.get("corrected"))
        # two reviewers at once: a decision made over a review that has moved on is not recorded; the reviewer is
        # shown the review as it is now and decides again
        seen, now = body.get("expected_version"), len(e.store.architect_decisions(pid)) + len(e.store.architect_corrections(pid))
        if seen is not None and (isinstance(seen, bool) or not isinstance(seen, int) or seen != now):
            raise ApiError(409, f"this proposal was reviewed meanwhile (the review is at version {now}, you decided over "
                                f"{seen!r}); nothing was recorded. Read the review again and decide",
                           {"version": now, "review": self.review(pid, rows, row["revision"])})
        known = {i["id"] for i in row["result"]["items"]}
        unknown = sorted((set(accepted) | set(rejected) | set(corrected)) - known)
        if unknown or set(accepted) & set(rejected) or set(corrected) & set(rejected) or not (accepted or rejected or corrected):
            raise ApiError(400, "accepted, rejected and corrected: ids of this revision's provisional items, none both "
                                "rejected and accepted or corrected" + (f" (unknown: {unknown[:5]})" if unknown else ""))
        # a correction is the acceptance of the element as the person wrote it: it is not also listed as accepted
        accepted = [i for i in accepted if i not in corrected]
        e.store.add_architect_decision(pid, row["revision"], user.name, accepted, rejected, str(body.get("note") or ""),
                                       corrected)
        return self.get_proposal(user, pid, row["revision"])

    @staticmethod
    def _corrections(value: Any) -> Dict[str, Any]:
        """``[{"id": element, "value": {...}}]``: the content a person gives an element instead of the proposed one."""
        if value is None:
            return {}
        if not (isinstance(value, list) and len(value) <= 100 and all(
                isinstance(c, dict) and set(c) == {"id", "value"} and isinstance(c["id"], str)
                and isinstance(c["value"], dict) and len(json.dumps(c["value"], default=str)) <= 20_000 for c in value)):
            raise ApiError(400, 'corrected: a list of {"id": element id, "value": the element\'s content as an object}')
        return {c["id"]: c["value"] for c in value}

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
