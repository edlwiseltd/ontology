"""Reviews of one engine (ARC-0: taken out of ``AutologyService``).

Human review of a paused run: listing and reading reviews, deciding one (a person, never a service identity and
never the run's own requester), checking that the facts the decision rests on have not moved, and continuing the
run. Who may review, see or decide is asked of the engine it belongs to, which remains the only authority; an
action that policy lets an agent take without a review never reaches this service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .agent import ReviewDecision
from .server import AgentConfig, ApiError, User
from .store import StoreError

if TYPE_CHECKING:
    from .server import AutologyService


class ReviewService:
    def __init__(self, engine: "AutologyService"):
        self.engine = engine

    def list_reviews(self, user: User, status: Optional[str]) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "review" if status in (None, "pending") else "read")
        views = (e.views.review_view(user, r) for r in e.store.list_reviews(status))
        return {"items": [v for v in views if v is not None]}

    def get_review(self, user: User, review_id: str) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "read")
        try:
            review = e.store.get_review(review_id)
        except KeyError:
            raise ApiError(404, f"no review {review_id!r}") from None
        view = e.views.review_view(user, review)
        if view is None:  # readable by admins, the review's reviewers and the run's starter only
            raise ApiError(404, f"no review {review_id!r}")
        return view

    def decide(self, user: User, review_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "review")
        e.require_person(user, "record a human approval")
        if not isinstance(body.get("approved"), bool):
            raise ApiError(400, "approved must be true or false")
        review = e.get_review(user, review_id)
        if "admin" not in user.permissions and not user.reviewer_roles & set(review["reviewers"]):
            raise ApiError(403, f"{user.name} may not decide reviews for {review['reviewers']}")
        if e.store.run_starter(review["run_id"]) == user.name:
            rules = [r for r in e.ontology.rules if r.id in (review["request"].get("rule_ids") or [])]
            if not rules or not all(r.params.get("allow_self_review") for r in rules):
                raise ApiError(403, "you started this run: another reviewer must decide its review "
                                    "(a rule can allow this with \"allow_self_review\": true)")
        linked = e.store.run_sources(review["run_id"])
        if body["approved"] and linked and e.one_active_run_per_record:
            others = e._active_runs(linked["root"], exclude=review["run_id"])
            if others:  # duplicates from before this rule existed: approving could repeat the same action
                raise ApiError(409, f"{linked['root']} has {len(others)} other open run(s) "
                                    f"({', '.join(r['run_id'] for r in others)}). Decline the duplicates first, so "
                                    "the same action cannot happen twice; declining is always allowed",
                               {"root": linked["root"], "other_runs": [r["run_id"] for r in others]})
        cfg = e._agent_for(review["run_id"])
        e._require_runs()  # deciding continues the run: not while the stage forbids runs
        e.checkpoint(user, "decide", review_id, body.get("justification") or body.get("comment"),
                        action=str(review["action"]).partition("@")[0], approved=body["approved"])
        comment = str(body.get("comment", ""))
        with cfg.lock:
            if e.store.get_review(review_id)["status"] != "pending":
                raise ApiError(409, f"review {review_id} was already decided")
            stored = e.store.load_run(review["run_id"])
            if stored.status != "awaiting_review" or stored.run is None:
                raise ApiError(409, f"the run cannot continue: it is {stored.status}")
            if not getattr(stored, "integrity_problem", None) and stored.run.ontology_ref != cfg.agent.ontology.ref:
                raise ApiError(409, f"the run cannot continue: it was started on {stored.run.ontology_ref}; the "
                                    f"agent now uses {cfg.agent.ontology.ref}")
            started_on = getattr(stored.run, "configuration", "")
            if started_on and started_on != e.configuration_fingerprint:  # approvals bind the configuration (F-04)
                raise ApiError(409, f"the run cannot continue: it was started on configuration {started_on[:12]}; the "
                                    f"use case now runs {e.configuration_fingerprint[:12]}. The decision is not "
                                    "recorded; start a new run on the current configuration")
            # Order matters (audit GAP-004): the decision is recorded before the run can act, and never undone.
            # If the run then fails or cannot be saved, it is recovered from the journal: calls already made are
            # replayed, never repeated, and the review is not opened again.
            try:
                e.store.decide_review(review_id, body["approved"], user.name, comment)
            except StoreError as exc:
                raise ApiError(409, str(exc)) from None
            changed = e._continue_after_review(cfg, review["run_id"], stored,
                                                  ReviewDecision(body["approved"], user.name, comment),
                                                  f"review {review_id}")
            result = e.store.load_run(review["run_id"])
        e._changed(changed)
        return e._summary(result, review["run_id"], user, receipt=True)

    def _live_changes(self, run_id: str, stored) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """What changed on the run's live records since it last read or wrote them (ACT-6): ``(refresh,
        conflicts)``. A field only changed outside is refreshed; one the run changed too is a conflict."""
        e = self.engine
        linked = e.store.run_sources(run_id)
        if not linked or not linked.get("base") or stored.run is None:
            return [], []
        state, base = stored.run.state, linked["base"]
        refresh, conflicts = [], []
        with e.graph_lock:
            for entity, src in linked["sources"].items():
                for iid in (src if isinstance(src, list) else [src]):
                    inst = e.graph._instances.get(iid)
                    seen = base.get(iid)
                    if inst is None or seen is None:
                        continue
                    mine = (state.collections.get(entity, {}).get(iid) if isinstance(src, list)
                            else state.entities.get(entity)) or {}
                    for attr, live in inst.attributes.items():
                        if attr not in seen or live == seen.get(attr) or live == mine.get(attr):
                            continue
                        change = {"entity": entity, "instance": iid if isinstance(src, list) else None,
                                  "id": iid, "attr": attr, "base": seen.get(attr), "live": live,
                                  "run": mine.get(attr)}
                        (refresh if mine.get(attr) == seen.get(attr) else conflicts).append(change)
        return refresh, conflicts

    def _continue_after_review(self, cfg: AgentConfig, run_id: str, stored, decision, what: str) -> List[str]:
        """Resume a run with a recorded review decision and save it (the caller holds the agent's lock).
        The run first re-reads its live records: a fact the reviewer saw that has changed means a new review."""
        e = self.engine
        refresh, conflicts = e._live_changes(run_id, stored)
        try:
            result = cfg.agent.resume(stored, decision=decision, refresh=refresh, conflicts=conflicts)
        except Exception as exc:
            e.log_error(f"resuming run {run_id} after {what}")
            raise ApiError(500, f"the decision is recorded but the run could not continue ({type(exc).__name__}); "
                                "it will be recovered automatically, and no external call is repeated") from None
        try:
            _, changed = e._store_result(result, cfg.name, run_id)
        except Exception as exc:
            e.log_error(f"saving run {run_id} after {what}")
            raise ApiError(500, f"the decision is recorded but the run could not be saved ({type(exc).__name__}); "
                                "it will be recovered automatically, and no external call is repeated") from None
        return changed
