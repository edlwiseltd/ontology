"""Reporting database: a flat, governed copy of the graph and of the decision history, for BI tools.

    python -m autology reporting server.json --out reporting.db

Metabase, Superset, Grafana, Power BI and the like read plain tables, not an ontology or an API. This module writes
them: one table per entity (``obj_claim``: id, status and one typed column per attribute), ``links``, and the
history of work: ``runs``, ``steps``, ``reviews``, ``outcomes``, ``automation_firings`` and ``ingest_batches``.

**What the dashboards may show is decided here, not in the BI tool.** The export is made *for an audience*: a set
of ontology roles (``"roles"``). Row and field access rules apply to those roles exactly as they would to an API
user; checkpoint-gated fields and fields of the excluded sensitivities (default ``pii`` and ``confidential``) are
left out unless listed in ``include_fields``; a run whose case holds a record the audience may not see is left
out with its steps, reviews and outcomes. Free text (step messages, explanations, review comments, outcome
notes) is never exported. The ``_export`` table records when, for whom, and what was left out.

The target is a SQLite file (written to a temporary file and swapped in, so readers never see half an export)
or any DB-API database (``{"driver": "psycopg", "dsn_env": "REPORTING_DSN"}``), refreshed in one transaction.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

DEFAULT_EXCLUDED = ("pii", "confidential")
_SQL_TYPES = {"sqlite": {"number": "REAL", "integer": "INTEGER", "boolean": "INTEGER", "text": "TEXT"},
              "other": {"number": "DOUBLE PRECISION", "integer": "BIGINT", "boolean": "BOOLEAN", "text": "TEXT"}}


def table_name(entity: str) -> str:
    return "obj_" + re.sub(r"(?<!^)(?=[A-Z])", "_", entity).lower()


def _q(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"not a safe SQL identifier: {name!r}")
    return f'"{name}"'


class Table:
    def __init__(self, name: str, columns: Sequence[Tuple[str, str]]):
        self.name, self.columns, self.rows = name, list(columns), []  # columns: (name, number|integer|boolean|text)

    def add(self, *values: Any) -> None:
        self.rows.append(tuple(values))


def _kind(attr_type: str) -> str:
    return attr_type if attr_type in ("number", "integer", "boolean") else "text"


def _hours(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    except ValueError:
        return None
    return round(delta.total_seconds() / 3600, 4)


def build_tables(service: Any, roles: Iterable[str] = (), exclude_sensitivities: Iterable[str] = DEFAULT_EXCLUDED,
                 include_fields: Iterable[str] = ()) -> Tuple[List[Table], Dict[str, Any]]:
    """The reporting tables as ``roles`` may see them, and a description of what was left out."""
    from .server import User

    onto, store = service.ontology, service.store
    audience = User("reporting", "", frozenset({"read"}), frozenset(roles))
    excluded_sens, included = set(exclude_sensitivities), set(include_fields)
    gated = service.views.gated
    for ref in included:
        onto._check_field(ref, "reporting include_fields")
    left_out: Dict[str, str] = {}
    tables: List[Table] = []
    updated = {r["id"]: r["updated_at"] for r in store._query("SELECT id, updated_at FROM instances")}

    with service.graph_lock:
        instances = list(service.graph.instances())
        links = list(service.graph._links)
    visible = {i.id: i for i in instances if service.visible(i, audience)}
    for entity, etype in onto.entities.items():
        columns = []
        for attr, spec in etype.attributes.items():
            ref = f"{entity}.{attr}"
            if attr == "status":
                continue
            if ref not in included:
                if ref in gated:
                    left_out[ref] = "checkpoint"
                    continue
                if spec.sensitivity in excluded_sens:
                    left_out[ref] = f"sensitivity {spec.sensitivity}"
                    continue
            columns.append((attr, _kind(spec.type)))
        table = Table(table_name(entity), [("id", "text"), ("status", "text")] + columns + [("updated_at", "text")])
        for inst in (i for i in visible.values() if i.type == entity):
            values = []
            for attr, _ in columns:
                if service.field_hidden(inst, attr, audience):  # a data_access rule, for this record
                    left_out.setdefault(f"{entity}.{attr}", "data_access (some records)")
                    values.append(None)
                else:
                    values.append(inst.attributes.get(attr))
            table.add(inst.id, inst.attributes.get("status"), *values, updated.get(inst.id))
        tables.append(table)

    link_table = Table("links", [("source", "text"), ("kind", "text"), ("target", "text"),
                                 ("source_type", "text"), ("target_type", "text")])
    for source, kind, target in links:
        if source in visible and target in visible:
            link_table.add(source, kind, target, visible[source].type, visible[target].type)
    tables.append(link_table)

    runs = Table("runs", [("run_id", "text"), ("agent", "text"), ("goal", "text"), ("case_id", "text"),
                          ("status", "text"), ("started_by", "text"), ("created_at", "text"), ("updated_at", "text"),
                          ("steps", "integer"), ("human_touches", "integer"), ("tool_cost", "number"),
                          ("llm_usd", "number"), ("hours_open", "number"), ("ontology", "text")])
    steps = Table("steps", [("run_id", "text"), ("step", "integer"), ("action", "text"), ("verdict", "text"),
                            ("outcome", "text"), ("executed_by", "text"), ("reviewer", "text")])
    outcomes = Table("outcomes", [("run_id", "text"), ("action", "text"), ("label", "text"), ("good", "boolean"),
                                  ("recorded_by", "text"), ("recorded_at", "text")])
    shown_runs = set()
    hidden_runs = 0
    for row in store.list_runs(limit=10 ** 9):
        result = store.load_run(row["run_id"])
        if service.views.hides_rows(audience, result.state):
            hidden_runs += 1
            continue
        shown_runs.add(row["run_id"])
        runs.add(row["run_id"], row["agent"], row["goal"], row["case_id"], row["status"], row["started_by"],
                 row["created_at"], row["updated_at"], len(result.steps), result.human_touches,
                 float(result.costs.get("tools", 0) or 0), float(result.costs.get("llm_usd", 0) or 0),
                 _hours(row["created_at"], row["updated_at"]), row["ontology"])
        for s in result.steps:
            steps.add(row["run_id"], s.index, s.action, s.verdict, s.outcome, s.executed_by, s.reviewer)
        for e in result.audit.events("outcome"):
            outcomes.add(row["run_id"], e.data.get("action"), e.data.get("label"), bool(e.data.get("good")),
                         e.data.get("recorded_by"), e.timestamp)

    reviews = Table("reviews", [("review_id", "text"), ("run_id", "text"), ("action", "text"), ("reviewers", "text"),
                                ("status", "text"), ("approved", "boolean"), ("created_at", "text"),
                                ("decided_at", "text"), ("decided_by", "text"), ("hours_to_decide", "number")])
    for r in store.list_reviews(None, limit=10 ** 9):
        if r["run_id"] not in shown_runs:
            continue
        decision = r.get("decision") or {}
        reviews.add(r["review_id"], r["run_id"], r["action"], ",".join(r["reviewers"]), r["status"],
                    decision.get("approved") if decision else None, r["created_at"], r.get("decided_at"),
                    r.get("decided_by"), _hours(r["created_at"], r.get("decided_at")))

    firings = Table("automation_firings", [("automation", "text"), ("instance", "text"), ("trigger", "text"),
                                           ("fired_at", "text"), ("status", "text"), ("run_id", "text")])
    for f in store.list_firings(limit=10 ** 9):
        if f["instance"] in visible and (not f["run_id"] or f["run_id"] in shown_runs):
            firings.add(f["automation"], f["instance"], f["trigger"], f["fired_at"], f["status"], f["run_id"])

    batches = Table("ingest_batches", [("batch_id", "text"), ("pipeline", "text"), ("started_at", "text"),
                                       ("status", "text"), ("triggered_by", "text"), ("created", "integer"),
                                       ("updated", "integer"), ("unchanged", "integer"), ("rejected", "integer")])
    for b in store.ingest_batches(limit=10 ** 9):
        s = b["summary"]
        batches.add(b["batch_id"], b["pipeline"], b["started_at"], b["status"], b["triggered_by"],
                    s.get("created"), s.get("updated"), s.get("unchanged"), s.get("rejected"))
    tables += [runs, steps, reviews, outcomes, firings, batches]
    meta = {"exported_at": datetime.now(timezone.utc).isoformat(), "ontology": onto.ref,
            "roles": sorted(roles), "left_out_fields": left_out, "hidden_records": len(instances) - len(visible),
            "hidden_runs": hidden_runs, "rows": {t.name: len(t.rows) for t in tables}}
    return tables, meta


def _write(conn: Any, tables: List[Table], meta: Dict[str, Any], dialect: str, placeholder: str) -> None:
    types = _SQL_TYPES[dialect]
    cur = conn.cursor()
    export = Table("_export", [("key", "text"), ("value", "text")])
    for key, value in meta.items():
        export.add(key, value if isinstance(value, str) else json.dumps(value))
    for table in tables + [export]:
        cur.execute(f"DROP TABLE IF EXISTS {_q(table.name)}")
        cols = ", ".join(f"{_q(c)} {types[k]}" for c, k in table.columns)
        cur.execute(f"CREATE TABLE {_q(table.name)} ({cols})")
        if table.rows:
            marks = ", ".join([placeholder] * len(table.columns))
            rows = table.rows
            if dialect == "sqlite":  # SQLite has no boolean type
                rows = [tuple(int(v) if isinstance(v, bool) else v for v in r) for r in rows]
            cur.executemany(f"INSERT INTO {_q(table.name)} VALUES ({marks})", rows)


def export_reporting(service: Any, target: Union[str, Dict[str, Any]], roles: Iterable[str] = (),
                     exclude_sensitivities: Iterable[str] = DEFAULT_EXCLUDED,
                     include_fields: Iterable[str] = ()) -> Dict[str, Any]:
    """Write the reporting tables to ``target`` (a SQLite path or ``{"driver", "dsn_env"}``)."""
    tables, meta = build_tables(service, roles, exclude_sensitivities, include_fields)
    if isinstance(target, dict):
        module = importlib.import_module(target["driver"])
        dsn = os.environ.get(target["dsn_env"])
        if not dsn:
            raise ValueError(f"environment variable {target['dsn_env']} is not set")
        placeholder = {"qmark": "?", "format": "%s", "pyformat": "%s", "numeric": "?", "named": "?"}[module.paramstyle]
        conn = module.connect(dsn)
        try:
            _write(conn, tables, meta, "sqlite" if target["driver"] == "sqlite3" else "other", placeholder)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        meta["target"] = f"{target['driver']} ({target['dsn_env']})"
        return meta
    path = Path(target).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".reporting-", suffix=".db", dir=str(path.parent))
    os.close(fd)
    try:
        conn = sqlite3.connect(tmp)
        try:
            _write(conn, tables, meta, "sqlite", "?")
            conn.commit()
        finally:
            conn.close()
        # keep the permissions readers rely on: the old file's, or the usual ones for a new file (the temporary
        # file is owner-only, which would lock out a BI tool running as another user)
        if path.exists():
            mode = path.stat().st_mode & 0o777
        else:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        os.replace(tmp, path)  # readers see the old export or the new one, never half of one
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    meta["target"] = str(path)
    return meta


# -- Prometheus metrics ---------------------------------------------------------------------------------------------
def _esc(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def metrics_text(service: Any) -> str:
    """Operational metrics in the Prometheus text format (counts only: no record values, ids or names)."""
    from . import __version__

    store, out = service.store, []

    def metric(name: str, kind: str, help_text: str, samples: Iterable[Tuple[Dict[str, Any], Any]]) -> None:
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} {kind}")
        for labels, value in samples:
            label = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
            out.append(f"{name}{{{label}}} {value}" if label else f"{name} {value}")

    q = store._query
    metric("autology_info", "gauge", "Deployment information", [({
        "ontology": service.ontology.ref, "version": __version__,
        "simulation": str(service.simulation).lower()}, 1)])
    metric("autology_objects", "gauge", "Objects in the knowledge graph by entity",
           [({"entity": r["type"]}, r["c"]) for r in q("SELECT type, COUNT(*) c FROM instances GROUP BY type "
                                                        "ORDER BY type")])
    metric("autology_runs", "gauge", "Runs by agent and status",
           [({"agent": r["agent"] or "", "status": r["status"]}, r["c"])
            for r in q("SELECT agent, status, COUNT(*) c FROM runs GROUP BY agent, status ORDER BY agent, status")])
    pending: Dict[str, int] = {}
    oldest: Dict[str, float] = {}
    now = datetime.now(timezone.utc)
    for r in q("SELECT reviewers, created_at FROM reviews WHERE status='pending'"):
        age = (now - datetime.fromisoformat(r["created_at"])).total_seconds()
        for role in json.loads(r["reviewers"]):
            pending[role] = pending.get(role, 0) + 1
            oldest[role] = max(oldest.get(role, 0.0), age)
    metric("autology_reviews_pending", "gauge", "Reviews waiting for a decision, by reviewer role",
           [({"reviewer": k}, v) for k, v in sorted(pending.items())])
    metric("autology_review_oldest_pending_seconds", "gauge", "Age of the oldest pending review, by reviewer role",
           [({"reviewer": k}, round(v, 3)) for k, v in sorted(oldest.items())])
    metric("autology_reviews_decided_total", "counter", "Decided reviews by outcome",
           [({"status": r["status"]}, r["c"]) for r in q("SELECT status, COUNT(*) c FROM reviews WHERE "
                                                         "status != 'pending' GROUP BY status ORDER BY status")])
    metric("autology_automation_firings_total", "counter", "Automation firings by automation and result",
           [({"automation": r["automation"], "status": r["status"]}, r["c"])
            for r in q("SELECT automation, status, COUNT(*) c FROM automation_firings GROUP BY automation, status "
                       "ORDER BY automation, status")])
    metric("autology_ingest_batches_total", "counter", "Data loads by pipeline and result",
           [({"pipeline": r["pipeline"], "status": r["status"]}, r["c"])
            for r in q("SELECT pipeline, status, COUNT(*) c FROM ingest_batches GROUP BY pipeline, status "
                       "ORDER BY pipeline, status")])
    metric("autology_ingest_rejected_rows_total", "counter", "Rows quarantined by pipeline",
           [({"pipeline": r["pipeline"]}, r["c"]) for r in q(
               "SELECT b.pipeline, COUNT(*) c FROM ingest_rejects r JOIN ingest_batches b USING (batch_id) "
               "WHERE b.status = 'loaded' GROUP BY b.pipeline ORDER BY b.pipeline")])
    last = {}
    for r in q("SELECT pipeline, MAX(started_at) t FROM ingest_batches WHERE status='loaded' GROUP BY pipeline"):
        last[r["pipeline"]] = datetime.fromisoformat(r["t"]).timestamp()
    metric("autology_ingest_last_success_timestamp_seconds", "gauge", "When each pipeline last loaded",
           [({"pipeline": k}, round(v, 3)) for k, v in sorted(last.items())])
    metric("autology_agents_suspended", "gauge", "Agents currently suspended",
           [({}, q("SELECT COUNT(DISTINCT agent) c FROM suspensions WHERE reinstated_at IS NULL")[0]["c"])])
    metric("autology_api_requests_total", "counter", "API requests by status class",
           [({"status": f"{r['s']}xx"}, r["c"]) for r in q(
               "SELECT status / 100 s, COUNT(*) c FROM access_log GROUP BY status / 100 ORDER BY s")])
    metric("autology_audit_unverified_runs", "gauge", "Runs whose audit chain does not verify (should be 0)",
           [({}, service.unverified_runs())])
    status = service.scheduler_status
    metric("autology_scheduler_errors", "gauge", "1 if the last scheduler pass failed",
           [({}, 1 if status.get("last_error") else 0)])
    return "\n".join(out) + "\n"
