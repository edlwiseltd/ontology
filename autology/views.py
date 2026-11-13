"""What one API user may see of a run, a review, a field or an answer: one policy for every endpoint.

Every endpoint and assistant tool that returns runs or reviews goes through :class:`ViewPolicy`:

* **Runs.** A run whose case holds a record the user may not see (``row_access``) is hidden from them
  entirely, as if it did not exist. Otherwise the state is shown through the user's own field access
  (``data_access``); values behind a ``read_field`` checkpoint read ``"***justification required***"``.
  Step explanations, tool messages and escalation details carry the agent's facts, so restricted facts
  are scrubbed from them, and the message of a step whose action reads or writes a restricted field is
  withheld.
* **Reviews.** Readable only by admins, holders of one of the review's reviewer roles, and the person
  who started the run, each through their own field access. Nobody else learns the review exists.
* **Admins** see every record and field, but checkpoint-gated fields still need a justification.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, Iterable, Optional, Set

from .governance import REDACTED

JUSTIFY = "***justification required***"


class ViewPolicy:
    def __init__(self, service: Any):
        self.svc = service

    # -- fields -------------------------------------------------------------------
    @property
    def gated(self) -> Set[str]:
        return {r.params["field"] for r in self.svc.ontology.rules_of("checkpoint") if r.params["on"] == "read_field"}

    @staticmethod
    def is_admin(user: Any) -> bool:
        return "admin" in user.permissions

    def restricted_refs(self, user: Any, state: Any) -> Set[str]:
        """References whose values must not appear in free text: hidden by access rules, or checkpoint-gated."""
        return self.hidden_refs(user, state) | self.gated

    def hidden_refs(self, user: Any, state: Any) -> Set[str]:
        """``Entity.attr`` references the user may not read on at least one record of ``state``."""
        refs: Set[str] = set()
        if self.is_admin(user):
            return refs
        gov, principal = self.svc.access, user.principal
        for entity, values in state.entities.items():
            refs |= {f"{entity}.{a}" for a in values if not gov.can_read(f"{entity}.{a}", state, principal)}
        for entity, bucket in state.collections.items():
            for iid, values in bucket.items():
                refs |= {f"{entity}.{a}" for a in values
                         if not gov.can_read(f"{entity}.{a}", state, principal, {entity: iid})}
        return refs

    def hides_rows(self, user: Any, state: Any) -> bool:
        if self.is_admin(user):
            return False
        gov, principal = self.svc.access, user.principal
        if any(not gov.row_visible(e, state, principal)[0] for e in state.entities):
            return True
        return any(not gov.row_visible(e, state, principal, iid)[0]
                   for e, bucket in state.collections.items() for iid in bucket)

    def state_view(self, user: Any, state: Any) -> Dict[str, Any]:
        if self.is_admin(user):
            view = copy.deepcopy({**state.entities, **state.collections})
        else:
            view = self.svc.access.redacted_view(state, user.principal)
        gated = self.gated
        for entity, block in view.items():
            records = block.values() if entity in state.collections else [block]
            for values in records:
                for attr in values:
                    if f"{entity}.{attr}" in gated and values[attr] not in (REDACTED, None):
                        values[attr] = JUSTIFY
        return view

    @staticmethod
    def scrub(text: Any, refs: Iterable[str]) -> Any:
        """Replace ``Entity.attr=value`` facts for restricted references inside free text."""
        if not isinstance(text, str):
            return text
        for ref in refs:
            text = re.sub(rf"{re.escape(ref)}\s*=\s*('[^']*'|\"[^\"]*\"|[^,;)\s]+)", f"{ref}={REDACTED}", text)
        return text

    def _touches(self, action_name: str, refs: Set[str]) -> bool:
        action = self.svc.ontology.actions.get(action_name.partition("@")[0])
        return bool(action and refs & (set(action.reads) | set(action.writes)))

    # -- runs ---------------------------------------------------------------------
    def can_see_run(self, user: Any, result: Any) -> bool:
        return not self.hides_rows(user, result.state)

    def run_view(self, user: Any, result: Any, run_id: str) -> Optional[Dict[str, Any]]:
        """The run as ``user`` may see it, or ``None`` if it must stay hidden from them."""
        if not self.can_see_run(user, result):
            return None
        refs = self.restricted_refs(user, result.state)
        esc = result.escalation
        out = {"run_id": run_id, "case_id": result.case_id, "goal": result.goal, "status": result.status,
               "steps": [{"index": s.index, "action": s.action, "verdict": s.verdict, "outcome": s.outcome,
                          "executed_by": s.executed_by, "reviewer": s.reviewer,
                          "message": REDACTED if self._touches(s.action, refs) else self.scrub(s.message, refs),
                          "explanation": self.scrub(s.explanation, refs)} for s in result.steps],
               "escalation": {"reason": self.scrub(esc.reason, refs), "to": esc.to, "action": esc.action,
                              "details": [self.scrub(d, refs) for d in esc.details]} if esc else None,
               "costs": result.costs, "audit_verified": self.svc.store.verify_audit(run_id),
               "state": self.state_view(user, result.state)}
        out["outcomes"] = self.outcomes(user, result)
        linked = self.svc.store.run_sources(run_id)
        out["write_back_conflicts"] = [
            {**c, **({k: REDACTED for k in ("base", "live", "run")} if f"{c['type']}.{c['attribute']}" in refs else {})}
            for c in (linked["conflicts"] if linked else [])]
        pending = [r for r in self.svc.store.list_reviews("pending") if r["run_id"] == run_id]
        out["pending_review"] = pending[0]["review_id"] if pending and self.review_view(user, pending[0]) else None
        return out

    def outcomes(self, user: Any, result: Any) -> list:
        """What people recorded as happening after the run's decisions (notes scrubbed of restricted facts)."""
        refs = self.restricted_refs(user, result.state)
        return [{"at": e.timestamp, "action": e.data.get("action"), "label": e.data.get("label"),
                 "good": e.data.get("good"), "note": self.scrub(e.data.get("note"), refs),
                 "recorded_by": e.data.get("recorded_by")} for e in result.audit.events("outcome")]

    # -- reviews ------------------------------------------------------------------
    def review_view(self, user: Any, review: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The review as ``user`` may see it, or ``None`` if they may not know it exists."""
        admin = self.is_admin(user)
        if not admin and not (user.reviewer_roles & set(review["reviewers"])
                              or self.svc.store.run_starter(review["run_id"]) == user.name):
            return None
        try:
            run = self.svc.store.load_run(review["run_id"])
        except KeyError:
            return None if not admin else review
        if self.hides_rows(user, run.state):
            return None
        hidden, gated = self.hidden_refs(user, run.state), self.gated
        refs = hidden | gated
        out = dict(review)
        request = dict(review["request"])
        request["view"] = self.state_view(user, run.state)
        request["facts"] = {k: (REDACTED if k in hidden else JUSTIFY if k in gated else v)
                            for k, v in (request.get("facts") or {}).items()}
        for key in ("explanation", "description"):
            request[key] = self.scrub(request.get(key), refs)
        request["reasons"] = [self.scrub(r, refs) for r in request.get("reasons") or []]
        out["request"] = request
        return out
