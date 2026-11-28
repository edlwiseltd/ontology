"""Runs of one engine (ARC-0: taken out of ``AutologyService``).

The life of a run: starting it for a person or an automation, storing its result and audit chain, listing and
reading runs, resuming, recovering after a crash, writing results back to the records all or nothing, traces and
recorded outcomes. This service decides nothing by itself: permissions, checkpoints, visibility, the stage gate
and the agents' governance are asked of the engine it belongs to, which remains the only authority.
"""

from __future__ import annotations

import copy
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .agent import ReviewDecision
from .graph import build_case, snapshot
from .ontology import OntologyError
from .server import FINAL_STATUSES, AgentConfig, ApiError, User, log

if TYPE_CHECKING:
    from .server import AutologyService


class RunService:
    def __init__(self, engine: "AutologyService"):
        self.engine = engine
        self._cancelling = threading.RLock()

    def _summary(self, result, run_id: str, user: User, receipt: bool = False) -> Dict[str, Any]:
        """The run as this user may see it (see :mod:`autology.views`). A run over records the user may not
        see is 404 for them; the person who just started or resumed it gets a bare receipt instead."""
        e = self.engine
        view = e.views.run_view(user, result, run_id)
        if view is None:
            if receipt:
                return {"run_id": run_id, "case_id": result.case_id, "status": result.status, "hidden": True,
                        "detail": "this run involves records you may not see"}
            raise ApiError(404, f"no run {run_id!r}")
        status = e.write_back_status(run_id)
        if status is not None:  # a run is not "written back" until its write set committed
            view = {**view, "write_back": {"state": status["state"], "conflicts": len(status["conflicts"])}}
        return view

    def _store_result(self, result, agent_name: str, run_id: Optional[str] = None,
                      sources: Optional[Tuple[str, str, Dict[str, Any], bool]] = None,
                      started_by: Optional[str] = None) -> Tuple[str, List[str]]:
        """Save a run, open its review (and notify reviewers), write results back to the graph.

        Returns ``(run_id, changed instance ids)``. Callers pass the changed ids to :meth:`_changed`
        once they have released the agent's lock, so automations never wait on a running agent.
        """
        e = self.engine
        run_id = e.store.save_run(result, run_id, agent_name, started_by)
        cfg = e.agents.get(agent_name)
        if cfg is not None and cfg.agent.principal.name in cfg.agent.governance.suspended:
            e.store.suspend(agent_name, cfg.agent.governance.suspended[cfg.agent.principal.name], run_id)
        if sources:
            e.store.link_run_sources(run_id, *sources)
        if result.status == "awaiting_review" and result.run and result.run.pending_review:
            from .agent import ReviewRequest

            req = ReviewRequest(**{k: v for k, v in result.run.pending_review.items()
                                   if k in ReviewRequest.__dataclass_fields__})
            review_id = e.store.create_review(run_id, req)
            e._notify("review", req.reviewers, f"Review needed: {req.action} in run {run_id} ({', '.join(req.rule_ids) or 'policy'})",
                         {"review_id": review_id, "run_id": run_id, "action": req.action})
        linked = e.store.run_sources(run_id)
        changed = e._write_back(run_id, result, linked) if linked and linked["write_back"] else []
        if e.tracing and result.status in FINAL_STATUSES:
            e._export_trace(run_id, result)
        return run_id, changed

    def _export_trace(self, run_id: str, result) -> None:
        e = self.engine
        from .tracing import export, resolve_headers, to_otlp

        payload = to_otlp([(run_id, result)], e.tracing.get("service_name", "autology"), e.ontology.ref)

        def send():
            try:
                export(payload, e.tracing["endpoint"], resolve_headers(e.tracing.get("headers")))
            except Exception:  # best effort: the audit log in the store stays the record of truth
                log.warning("trace export of run %s to %s failed", run_id,
                            urlparse(e.tracing["endpoint"]).netloc, exc_info=True)

        t = threading.Thread(target=send, daemon=True)
        t.start()
        e.deliveries.append(t)

    def run_trace(self, user: User, run_id: str) -> Dict[str, Any]:
        e = self.engine
        from .tracing import to_otlp

        e.require(user, "audit")
        try:
            result = e.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        return to_otlp([(run_id, result)], "autology", e.ontology.ref)

    def _write_back(self, run_id: str, result, linked: Dict[str, Any]) -> List[str]:
        """Write the run's results back to its records, all or nothing (audit GAP-009).

        The whole write set of this save is planned first without changing anything. If any field the run
        changed has also moved on the live record, nothing is written: the conflicts are kept on the run, in the
        append-only write-back log and in a notification, for a person to resolve. Otherwise every changed record
        is written in one store transaction that first checks each stored record is the one the server holds;
        the in-memory graph changes only after that transaction commits. A failure leaves every record as it was
        and the write-back pending: recovery completes it (it is idempotent). This covers local records only:
        effects in other systems go through the external-effects journal and reconciliation, never this."""
        e = self.engine
        from .graph import plan_write_back, run_values
        from .store import WriteSetConflict

        base = linked["base"] or {}
        version = e.store.run_version(run_id)
        known = linked["conflicts"]
        with e.graph_lock:
            writes, conflicts = plan_write_back(e.graph, result.state, linked["sources"], base)
            if not conflicts:
                plan = [(iid, e.graph.get(iid).type, dict(e.graph.get(iid).attributes),
                         {**e.graph.get(iid).attributes, **fields}, e.revisions.get(iid))
                        for iid, fields in writes.items()]
                # the base advances to what the records will hold, so the run's own writes are never conflicts later
                new_base = copy.deepcopy(base)
                for iid, seen in new_base.items():
                    if iid not in e.graph._instances:
                        continue
                    after = {**e.graph.get(iid).attributes, **writes.get(iid, {})}
                    for attr, value in (run_values(result.state, linked["sources"], iid) or {}).items():
                        if attr in after and after[attr] == value:
                            seen[attr] = value
                try:
                    e.store.commit_write_set(run_id, plan, new_base, known, version)
                except WriteSetConflict as exc:
                    conflicts = exc.conflicts
                except Exception:  # nothing was written; recovery completes it later
                    e.log_error(f"writing back run {run_id} (nothing was written; it will be retried)")
                    return []
                else:
                    for iid, fields in writes.items():
                        e.graph._instances[iid].attributes.update(fields)
                    e.revisions.update(e.store.instance_revisions(writes))
                    return list(writes)
        new = [c for c in conflicts if c not in known]
        e.store.record_write_back_conflict(run_id, conflicts, known + new, version)
        if new:  # nothing was written: a person decides which values are right
            fields = ", ".join(f"{c['id']}.{c['attribute']}" if c["attribute"] else c["id"] for c in new)
            e._notify("conflict", [], f"Run {run_id} wrote nothing back: {fields} changed while the run was in "
                                         f"progress; resolve the conflict, then retry the write-back",
                         {"run_id": run_id})
        return []

    def complete_write_backs(self) -> List[Dict[str, Any]]:
        """Finish write-backs interrupted by a crash or a failure (they are idempotent)."""
        e = self.engine
        done = []
        for run_id in e.store.pending_write_backs():
            linked = e.store.run_sources(run_id)
            try:
                changed = e._write_back(run_id, e.store.load_run(run_id), linked)
            except Exception:
                e.log_error(f"completing the write-back of run {run_id}")
                continue
            state = (e.store.run_sources(run_id) or {}).get("wb_state")
            done.append({"run_id": run_id, "write_back": state, "changed": changed})
            e._changed(changed)
        return done

    def retry_write_back(self, user: User, run_id: str) -> Dict[str, Any]:
        """After a person resolved a write-back conflict: try the run's write set again (all or nothing)."""
        e = self.engine
        e.require(user, "reconcile")
        linked = e.store.run_sources(run_id)
        if not linked or not linked["write_back"]:
            raise ApiError(404, f"no write-back for run {run_id!r}")
        try:
            result = e.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        if not e.views.can_see_run(user, result) and "admin" not in user.permissions:
            raise ApiError(404, f"no run {run_id!r}")
        changed = e._write_back(run_id, result, linked)
        e._changed(changed)
        return e.write_back_status(run_id)

    def write_back_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        e = self.engine
        linked = e.store.run_sources(run_id)
        if not linked or not linked["write_back"]:
            return None
        pending = linked.get("wb_version") != e.store.run_version(run_id)
        return {"state": "pending" if pending else linked.get("wb_state") or "pending",
                "conflicts": linked["conflicts"]}

    def run_roles(self, cfg: AgentConfig, user: Optional[User] = None, identity: Optional[str] = None) -> List[str]:
        """The roles a run may use (D4): the agent's, narrowed to what the requester may do (their own roles
        plus what an administrator granted them for this agent) or to the service identity's roles."""
        e = self.engine
        own = cfg.agent.principal.roles
        if identity is not None:
            return sorted(own & e.service_identities[identity]["roles"])
        if user is None or "admin" in user.permissions:
            return sorted(own)
        return sorted(own & (user.roles | user.grants(cfg.name)))

    def _case_hides_records(self, sources: Dict[str, Any], user: User) -> bool:
        """Does a case built from the graph include a record the user may not see (audit GAP-013)?"""
        e = self.engine
        ids = [i for src in sources.values() for i in (src if isinstance(src, list) else [src])]
        return any(i in e.graph._instances and not e.visible(e.graph._instances[i], user) for i in ids)

    def start_run(self, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "run")
        e._require_runs()
        name = body.get("agent") or (next(iter(e.agents)) if len(e.agents) == 1 else None)
        if name not in e.agents:
            raise ApiError(400, f"unknown agent {name!r}; available: {sorted(e.agents)}")
        cfg = e.agents[name]
        goal = body.get("goal") or (cfg.goals[0] if len(cfg.goals) == 1 else None)
        if goal not in cfg.goals:
            raise ApiError(400, f"agent {name} may pursue {cfg.goals}, not {goal!r}")
        e.checkpoint(user, "start_run", f"{name}/{goal}/{body.get('root') or body.get('case_id') or 'case'}",
                        body.get("justification"), goal=goal)
        sources = None
        if body.get("case_template"):  # build the case from the knowledge graph
            root = str(body.get("root") or "")
            with e.graph_lock:
                inst = e.graph._instances.get(root)
                if inst is None or not e.visible(inst, user):
                    raise ApiError(404, f"no object {root!r}")
                try:
                    case, found = build_case(e.graph, body["case_template"], root)
                except OntologyError as exc:
                    raise ApiError(400, str(exc)) from None
                if e._case_hides_records(found, user):  # the agent must not reach what the requester can't
                    raise ApiError(403, f"the case for {root} includes records you may not see; ask someone who "
                                        "may see all of them to start this run")
                base = snapshot(e.graph, found)  # what the case read: write-back compares against it
            sources = (body["case_template"], root, found, body.get("write_back", True) is not False, base)
        else:
            if "admin" not in user.permissions and not e.simulation:
                # the facts that trigger reviews and rules must come from the system of record, not the requester
                raise ApiError(403, "start runs from a case_template and a root object; free-form case data is "
                                    "accepted only from admins or on a server configured for simulation")
            case = body.get("case")
            if not isinstance(case, dict):
                raise ApiError(400, "case must be an object (or give case_template and root)")
        hold = e._exclusive(sources[1], user.name) if sources else None
        if hold is not None:
            hold.__enter__()
        try:
            with cfg.lock:
                try:
                    result = cfg.agent.run(goal, case, str(body.get("case_id") or (sources[1] if sources else "case")),
                                           started_by=user.name, root=sources[1] if sources else None,
                                           roles=e.run_roles(cfg, user), acting_as=user.name)
                except OntologyError as exc:
                    raise ApiError(400, f"invalid case: {exc}") from None
                run_id, changed = e._store_result(result, name, sources=sources, started_by=user.name)
        finally:
            if hold is not None:
                hold.__exit__(None, None, None)
        e._changed(changed)
        return e._summary(result, run_id, user, receipt=True)

    def list_runs(self, user: User, status: Optional[str], limit: int, offset: int) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "read")
        if "admin" in user.permissions:
            return {"items": e.store.list_runs(status, limit, offset)}
        rows = [r for r in e.store.list_runs(status, limit=10 ** 9)
                if e.views.can_see_run(user, e.store.load_run(r["run_id"]))]
        return {"items": rows[offset:offset + limit]}

    def _visible_runs(self, user: User) -> List[Any]:
        e = self.engine
        runs = e.store.all_runs()
        return runs if "admin" in user.permissions else [r for r in runs if e.views.can_see_run(user, r)]

    def get_run(self, user: User, run_id: str) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "read")
        try:
            result = e.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        return e._summary(result, run_id, user)

    def run_audit(self, user: User, run_id: str) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "audit")
        log = e.store.audit_log(run_id)
        if not len(log):
            raise ApiError(404, f"no run {run_id!r}")
        return {"run_id": run_id, "verified": e.store.verify_audit(run_id), "entries": log.to_list()}

    def _agent_for(self, run_id: str) -> AgentConfig:
        e = self.engine
        rows = [r for r in e.store.list_runs(limit=10 ** 9) if r["run_id"] == run_id]
        if not rows:
            raise ApiError(404, f"no run {run_id!r}")
        name = rows[0]["agent"]
        if name not in e.agents:
            raise ApiError(409, f"run {run_id} belongs to agent {name!r}, which is not configured")
        return e.agents[name]

    def resume_run(self, user: User, run_id: str, force: bool = False,
                   justification: Optional[str] = None) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "run")
        cfg = e._agent_for(run_id)
        e._require_runs()
        if "admin" not in user.permissions and not e.views.can_see_run(user, e.store.load_run(run_id)):
            raise ApiError(404, f"no run {run_id!r}")  # resuming would act on records the caller may not see
        e.checkpoint(user, "resume_run", run_id, justification)
        with cfg.lock:
            result = e.store.load_run(run_id)
            if result.status not in ("deferred", "paused"):
                raise ApiError(409, f"run {run_id} is {result.status}; only deferred or paused runs resume here")
            try:
                result = cfg.agent.resume(result, force=force)
            except (ValueError, OntologyError) as exc:
                raise ApiError(409, str(exc)) from None
            _, changed = e._store_result(result, cfg.name, run_id)
        e._changed(changed)
        return e._summary(result, run_id, user, receipt=True)

    def cancel_run(self, user: User, run_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Stop a run that is waiting for a review, a retry or a resume. Stopping is always allowed to someone who
        may run and may see the run, whatever the stage; a run that is acting, or whose external call is unresolved,
        is not cut. What the run did stays done; the cancellation and its reason join the audit chain, and the
        review it was waiting for is closed.

        It does not depend on today's configuration: a run whose agent was since removed or renamed is cancelled
        the same way and keeps its own record of the agent and configuration it started on. Asking again for a
        run that is already cancelled answers with that run and records nothing more (idempotent)."""
        from .agent import CANCELLABLE, cancel_stored

        e = self.engine
        e.require(user, "run")
        reason = str((body or {}).get("reason") or "").strip()
        if not 1 <= len(reason) <= 500:
            raise ApiError(400, "give a reason (1 to 500 characters)")
        agent = str(next((r["agent"] for r in e.store.list_runs(limit=10 ** 9) if r["run_id"] == run_id), "") or "")
        try:
            stored = e.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        if "admin" not in user.permissions and not e.views.can_see_run(user, stored):
            raise ApiError(404, f"no run {run_id!r}")
        cfg = e.agents.get(agent)
        # one cancellation at a time per engine, and never while the run's agent (if it still exists) acts on it
        with self._cancelling, (cfg.lock if cfg is not None else self._cancelling):
            stored = e.store.load_run(run_id)
            if stored.status == "cancelled":
                return e._summary(stored, run_id, user, receipt=True)
            if stored.status not in CANCELLABLE:
                raise ApiError(409, f"run {run_id} is {stored.status}: only a run that is waiting "
                                    f"({', '.join(CANCELLABLE)}) can be cancelled")
            result = cfg.agent.cancel(stored, user.name, reason) if cfg is not None else \
                cancel_stored(stored, user.name, reason)
            _, changed = e._store_result(result, agent, run_id)
            e.store.close_reviews(run_id, user.name, reason)
        e._changed(changed)
        return e._summary(result, run_id, user, receipt=True)

    def recover(self) -> List[Dict[str, Any]]:
        """Continue runs left behind by a crash or a failed save (at start-up and on every tick).

        * A run still ``awaiting_review`` whose review was decided resumes with that decision.
        * A run waiting on an external call that a person has since reconciled continues.
        Calls the run already made are replayed from the journal, never made again.
        """
        e = self.engine
        recovered = []
        if e._runs_refused():  # nothing continues while the stage forbids runs; it continues once allowed
            return recovered
        for done in e.complete_write_backs():  # write-backs interrupted by a crash or a failure (GAP-009)
            recovered.append({"run_id": done["run_id"], "write_back": done["write_back"]})
        decided = {}
        for r in e.store.list_reviews(None):
            if r["status"] in ("approved", "declined"):
                decided[r["run_id"]] = r  # the latest decision per run (reviews are listed oldest first)
        pending = {r["run_id"] for r in e.store.list_reviews("pending")}
        for row in e.store.list_runs("awaiting_review", limit=10 ** 9):
            review = decided.get(row["run_id"])
            cfg = e.agents.get(row["agent"])
            if review is None or row["run_id"] in pending or cfg is None:
                continue
            with cfg.lock:
                stored = e.store.load_run(row["run_id"])
                if stored.status != "awaiting_review":
                    continue
                decision = ReviewDecision(review["status"] == "approved", review.get("decided_by") or "?",
                                          (review.get("decision") or {}).get("comment", "")
                                          if isinstance(review.get("decision"), dict) else "")
                try:
                    changed = e._continue_after_review(cfg, row["run_id"], stored, decision, "recovery")
                except ApiError:
                    continue
            recovered.append({"run_id": row["run_id"], "status": e.store.load_run(row["run_id"]).status})
            e._changed(changed)
        for status in ("uncertain", "pending_confirmation"):
            for row in e.store.list_runs(status, limit=10 ** 9):
                cfg = e.agents.get(row["agent"])
                if cfg is None:
                    continue
                with cfg.lock:
                    stored = e.store.load_run(row["run_id"])
                    key = (stored.run.pending_external or {}).get("key") if stored.run else None
                    call = e.store.get_call(key) if key else None
                    if stored.status != status or not call or call["state"] not in ("resolved_done",
                                                                                     "resolved_not_done"):
                        continue
                    try:
                        result = cfg.agent.resume(stored)
                        _, changed = e._store_result(result, cfg.name, row["run_id"])
                    except Exception:
                        e.log_error(f"continuing run {row['run_id']} after reconciliation")
                        continue
                recovered.append({"run_id": row["run_id"], "status": result.status})
                e._changed(changed)
        return recovered

    def _visible_run(self, user: User, run_id: str):
        e = self.engine
        try:
            result = e.store.load_run(run_id)
        except KeyError:
            raise ApiError(404, f"no run {run_id!r}") from None
        if not e.views.can_see_run(user, result):
            raise ApiError(404, f"no run {run_id!r}")
        return result

    def record_outcome(self, user: User, run_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Record what happened after a run or one of its decisions, in the run's tamper-evident audit chain."""
        e = self.engine
        e.require(user, "review")
        result = e._visible_run(user, run_id)
        label, good, action = body.get("label"), body.get("good"), body.get("action")
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise ApiError(400, "label must be a non-empty string of at most 200 characters")
        if not isinstance(good, bool):
            raise ApiError(400, "good must be true or false")
        if action is not None and action not in {s.action for s in result.steps if s.outcome}:
            raise ApiError(400, f"{action!r} is not an executed step of run {run_id}")
        rows = e.store.list_runs(limit=10 ** 9)
        agent = next((r["agent"] for r in rows if r["run_id"] == run_id), None)
        lock = e.agents[agent].lock if agent in e.agents else threading.Lock()
        with lock:
            result = e.store.load_run(run_id)
            result.audit.record("outcome", action=action, label=label.strip(), good=good,
                                note=str(body.get("note") or "")[:2000], recorded_by=user.name)
            e.store.save_run(result, run_id)
        return {"run_id": run_id, "outcomes": e.views.outcomes(user, result)}

    def list_outcomes(self, user: User, run_id: str) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "read")
        return {"items": e.views.outcomes(user, e._visible_run(user, run_id))}

    def outcomes_summary(self, user: User) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "read")
        from .reporting import outcome_analysis

        return outcome_analysis(e._visible_runs(user), e.ontology)
