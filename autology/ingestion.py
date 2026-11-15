"""Data ingestion of one engine (ARC-0: taken out of ``AutologyService``; GAP-037 for the write rules).

Running a pipeline (from the API, the schedule or the command line), listing pipelines and loads, and a record's
lineage. Permissions, the graph, the store and the write rules are the engine's: this service asks it, it holds no
authority of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Optional

from .server import ApiError, User, log

if TYPE_CHECKING:
    from .server import AutologyService


class IngestionService:
    def __init__(self, engine: "AutologyService"):
        self.engine = engine

    def ingest(self, name: str, triggered_by: str, dry_run: bool = False,
               pushed: Optional[Dict[str, Any]] = None, roles: Optional[FrozenSet[str]] = None,
               unrestricted: bool = False) -> Dict[str, Any]:
        """Run one pipeline: read its sources, check every row, write the accepted ones, fire automations.

        Fields protected by a ``write_access`` rule are written only with the right roles (GAP-037): ``roles``,
        the caller's, for rows the caller pushed; the pipeline's own declared roles for the sources the operator
        configured (and for pushed rows when no caller is known, e.g. the command line). ``unrestricted`` is a
        caller holding the engine's ``admin`` permission. This is the one entry for every way a pipeline runs:
        the API, the schedule, the command line."""
        e = self.engine
        from .ingest import PipelineError, apply_to_graph
        from .integrity import write_refusal

        pipe = e.pipelines.get(name)
        if pipe is None:
            raise ApiError(404, f"no pipeline {name!r}")
        with e.ingest_lock:
            try:
                plan = pipe.read(e.store.ingest_watermarks(name), pushed)
            except PipelineError as exc:
                batch = e.store.record_ingest_failure(name, triggered_by, str(exc))
                log.warning("pipeline %s failed: %s", name, exc)
                raise ApiError(502 if not pushed else 400, str(exc), {"batch_id": batch}) from None
            with e.graph_lock:
                from .store import ABSENT, RecordConflict

                def guard(entity, existing, changing, was_pushed):
                    if unrestricted and was_pushed:
                        return None
                    writer = roles if was_pushed and roles is not None else pipe.roles
                    return write_refusal(e.ontology, entity, existing, changing, writer)

                plan = pipe.plan(e.graph, plan, guard)
                critical = {iid: sorted(a for a in attrs if f"{etype}.{a}" in e.decision_fields)
                            for iid, (etype, attrs) in plan.updates.items()}
                critical = {iid: attrs for iid, attrs in critical.items() if attrs}
                try:  # over the revisions this process holds: a stale or tampered record refuses the load
                    batch = e.store.apply_ingest(plan, triggered_by, dry_run, expected={
                        iid: e.revisions.get(iid, ABSENT) for iid in plan.updates})
                except RecordConflict as exc:
                    e._record_conflict(exc)
                    raise ApiError(409, f"{exc}; nothing was loaded, run the pipeline again",
                                   {"record": exc.iid, "tampered": exc.tampered}) from None
                if not dry_run:
                    apply_to_graph(e.graph, plan)
                    e.revisions.update(e.store.instance_revisions(list(plan.creates) + list(plan.updates)))
        out = {"batch_id": batch, "dry_run": dry_run, **plan.summary(),
               # facts that rules, preconditions, goals or automations read, changed on existing records: names only
               "decision_fields_changed": [{"id": iid, "attributes": attrs} for iid, attrs in sorted(critical.items())]}
        if not dry_run:
            if critical:
                try:
                    e.store.log_access(triggered_by, "ingest.decision_fields",
                                          f"{name} batch {batch}: {len(critical)} records", 200)
                except Exception:  # the load is done; its report still says what changed
                    e.log_error("recording decision-field changes")
                out["decisions_to_revalidate"] = e._evidence_changed(critical, f"pipeline {name} ({triggered_by})")
            fired = e._changed(plan.changed_ids)
            if fired:
                out["triggered"] = [f.as_dict() for f in fired]
        return out

    def _due_pipelines(self) -> List[Dict[str, Any]]:
        e = self.engine
        from datetime import datetime, timezone

        loads = []
        for name, pipe in e.pipelines.items():
            if not pipe.every or all(s["type"] == "push" for s in pipe.sources.values()):
                continue
            last = e.store.ingest_batches(name, limit=1)
            if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last[0]["started_at"])
                         ).total_seconds() < pipe.every:
                continue
            try:
                out = e.ingest(name, "schedule")
                loads.append({k: out[k] for k in ("batch_id", "created", "updated", "rejected")})
            except ApiError as exc:
                loads.append({"pipeline": name, "error": exc.message})
        return loads

    def list_pipelines(self, user: User) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "ingest")
        items = []
        for name, pipe in e.pipelines.items():
            last = e.store.ingest_batches(name, limit=1)
            written = sorted({f"{m.entity}.{a}" for m in pipe.mappings for a in m.attributes})
            guarded = {r.params["field"] for r in e.ontology.rules_of("write_access")}
            items.append({"name": name, "every": pipe.every, "roles": sorted(pipe.roles),
                          # decision-critical fields this pipeline writes, and those no write_access rule protects:
                          # for those, whoever may run the pipeline may change what decisions rest on
                          "decision_fields": [f for f in written if f in e.decision_fields],
                          "unprotected_decision_fields": [f for f in written if f in e.decision_fields
                                                          and f not in guarded],
                          "sources": {s: src["type"] for s, src in pipe.sources.items()},
                          "entities": sorted({m.entity for m in pipe.mappings}),
                          "watermarks": e.store.ingest_watermarks(name),
                          "last_batch": last[0] if last else None})
        return {"items": items}

    def run_pipeline(self, user: User, name: str, body: Dict[str, Any]) -> Dict[str, Any]:
        e = self.engine
        e.require(user, "ingest")
        rows = body.get("rows")
        if rows is not None and (not isinstance(rows, dict) or
                                 not all(isinstance(v, list) for v in rows.values())):
            raise ApiError(400, "rows must map each push source to a list of records")
        return e.ingest(name, user.name, bool(body.get("dry_run")), rows, roles=user.roles,
                           unrestricted="admin" in user.permissions)

    def ingest_batch(self, user: User, batch_id: str) -> Dict[str, Any]:
        """A load and its quarantined rows. The rows hold raw source data, so only ingesters see them."""
        e = self.engine
        e.require(user, "ingest")
        rows = [b for b in e.store.ingest_batches(limit=10 ** 6) if b["batch_id"] == batch_id]
        if not rows:
            raise ApiError(404, f"no batch {batch_id!r}")
        return {**rows[0], "rejects": e.store.ingest_rejects(batch_id)}

    def object_lineage(self, user: User, iid: str) -> Dict[str, Any]:
        """Where an object came from: every load that created or changed it (attribute names, not values)."""
        e = self.engine
        e.require(user, "read")
        with e.graph_lock:
            inst = e.graph._instances.get(iid)
            if inst is None or not e.visible(inst, user):
                raise ApiError(404, f"no object {iid!r}")
        return {"id": iid, "type": inst.type, "loads": e.store.lineage(iid)}
