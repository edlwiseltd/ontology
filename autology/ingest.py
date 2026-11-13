"""Data ingestion: load records from other systems into the knowledge graph, checked and traced.

A *pipeline* (JSON) names its sources and maps their rows onto ontology objects::

    {"name": "claims_feed", "every": 300,
     "sources": {
       "policies": {"type": "csv", "path": "policies.csv"},
       "claims":   {"type": "sql", "database": "staging.db",
                    "query": "SELECT * FROM claims WHERE updated_at > {watermark} ORDER BY updated_at",
                    "incremental": {"column": "updated_at", "initial": ""}}},
     "mappings": [
       {"source": "policies", "entity": "Policy", "id": "policy_no",
        "attributes": {"holder": "holder_name", "deductible": "deductible", "status": {"value": "active", "on": "create"}}},
       {"source": "claims", "entity": "Claim", "id": {"template": "CL-{claim_no}"},
        "attributes": {"amount": "claim_amount", "status": {"value": "reported", "on": "create"}},
        "links": [{"kind": "against", "target": "policy_no"}],
        "checks": [{"attribute": "amount", "rule": "required"}, {"attribute": "amount", "rule": "min", "value": 0}]}]}

Source types: ``csv``, ``json`` (``items`` is the dotted path to the list), ``jsonl``, ``sql`` (a SQLite file, or
any DB-API driver with ``driver`` and ``dsn_env``), ``http`` (JSON over GET, ``next`` for pagination) and ``push``
(rows sent to ``POST /api/pipelines/{name}/run`` by another tool, such as an Airbyte, dlt or dbt job).

Every row is converted to the ontology's attribute types and checked before anything is written: types, states,
the mapping's ``checks`` (required, min, max, in, pattern), duplicate ids, and that each link's target exists.
Rows that fail are *quarantined* with the reason, not loaded. Accepted rows are written in one transaction with
a lineage entry per changed object (pipeline, source, row key, attributes changed), so the API can say where every
object came from. Incremental sources remember a watermark and read only newer rows next time.

Mapped attributes overwrite what is in the graph. Map lifecycle attributes such as ``status`` with
``"on": "create"`` so a reload does not undo what agents did since.
"""

from __future__ import annotations

import csv
import importlib
import io
import json
import os
import re
import string
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ontology import ID, STATUS, Ontology, OntologyError

SOURCE_TYPES = ("csv", "json", "jsonl", "sql", "http", "push")
CHECKS = ("required", "min", "max", "in", "pattern")
_TRUE, _FALSE = {"true", "yes", "y", "1", "t"}, {"false", "no", "n", "0", "f"}
MAX_PAGES = 1000


class PipelineError(ValueError):
    """A pipeline definition is invalid, or a source cannot be read."""


def _dig(data: Any, path: Optional[str]) -> Any:
    for part in (path.split(".") if path else []):
        data = data.get(part) if isinstance(data, dict) else None
    return data


def _template_fields(template: str) -> List[str]:
    names = []
    for _, name, spec, conv in string.Formatter().parse(template):
        if name is None:
            continue
        if not re.fullmatch(r"[A-Za-z_][\w ]*", name) or spec or conv:
            raise PipelineError(f"template {template!r}: only plain {{column}} fields are allowed")
        names.append(name)
    return names


@dataclass
class ValueSpec:
    """Where one value comes from: a column, a template over columns, or a constant."""

    column: Optional[str] = None
    template: Optional[str] = None
    value: Any = None
    has_value: bool = False
    mapping: Optional[Dict[str, Any]] = None
    default: Any = None
    on: str = "always"  # or "create": only set when the object is first created

    @classmethod
    def parse(cls, spec: Any, where: str) -> "ValueSpec":
        if isinstance(spec, str):
            return cls(column=spec)
        if not isinstance(spec, dict):
            raise PipelineError(f"{where}: give a column name or an object with column, template or value")
        unknown = set(spec) - {"column", "template", "value", "map", "default", "on"}
        if unknown:
            raise PipelineError(f"{where}: unknown keys {sorted(unknown)}")
        if sum(k in spec for k in ("column", "template", "value")) != 1:
            raise PipelineError(f"{where}: give exactly one of column, template or value")
        if spec.get("on", "always") not in ("always", "create"):
            raise PipelineError(f"{where}: on must be 'always' or 'create'")
        if "template" in spec:
            _template_fields(str(spec["template"]))
        if "map" in spec and not isinstance(spec["map"], dict):
            raise PipelineError(f"{where}: map must be an object")
        return cls(column=spec.get("column"), template=spec.get("template"), value=spec.get("value"),
                   has_value="value" in spec, mapping=spec.get("map"), default=spec.get("default"),
                   on=spec.get("on", "always"))

    def read(self, row: Dict[str, Any]) -> Any:
        if self.has_value:
            return self.value
        if self.template is not None:
            values = {}
            for name in _template_fields(self.template):
                if row.get(name) in (None, ""):
                    return None
                values[name] = row[name]
            return self.template.format_map(values)
        raw = row.get(self.column)
        if raw == "":
            raw = None
        if self.mapping is not None and raw is not None:
            raw = self.mapping.get(str(raw), self.mapping.get("*", raw))
        return self.default if raw is None else raw


def coerce(attr_type: str, value: Any) -> Any:
    """Convert a raw source value to the ontology type; raises ValueError when it cannot."""
    if value is None:
        return None
    if attr_type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"{value!r} is not a boolean")
    if attr_type == "integer":
        if isinstance(value, bool):
            raise ValueError(f"{value!r} is not an integer")
        if isinstance(value, int):
            return value
        number = float(str(value).strip())
        if not number.is_integer():
            raise ValueError(f"{value!r} is not a whole number")
        return int(number)
    if attr_type == "number":
        if isinstance(value, bool):
            raise ValueError(f"{value!r} is not a number")
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        number = float(text)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{value!r} is not a finite number")
        return int(number) if re.fullmatch(r"[+-]?\d+", text) else number
    if isinstance(value, (dict, list)):
        raise ValueError(f"{value!r} is not a {attr_type}")
    return value if isinstance(value, str) else str(value)


@dataclass
class Mapping:
    source: str
    entity: str
    id: ValueSpec
    attributes: Dict[str, ValueSpec]
    links: List[Tuple[str, ValueSpec, bool]]  # (kind, target id, reverse: the target links to this object)
    checks: List[Dict[str, Any]]


@dataclass
class Rejected:
    source: str
    row: int
    reason: str
    data: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "row": self.row, "reason": self.reason, "data": self.data}


@dataclass
class Plan:
    """What a load would change; nothing is written until :meth:`Store.apply_ingest`."""

    pipeline: str
    creates: Dict[str, Tuple[str, Dict[str, Any]]] = field(default_factory=dict)  # id -> (type, attributes)
    updates: Dict[str, Tuple[str, Dict[str, Any]]] = field(default_factory=dict)  # id -> (type, changed attributes)
    links: List[Tuple[str, str, str]] = field(default_factory=list)
    lineage: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Rejected] = field(default_factory=list)
    watermarks: Dict[str, str] = field(default_factory=dict)
    read: Dict[str, int] = field(default_factory=dict)
    unchanged: int = 0
    rows: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict, repr=False)
    previous: Dict[str, str] = field(default_factory=dict, repr=False)
    held: Dict[str, str] = field(default_factory=dict)  # source -> first rejected mark the watermark stops at

    @property
    def changed_ids(self) -> List[str]:
        ids = list(self.creates) + [i for i in self.updates if i not in self.creates]
        ids += [s for s, _, _ in self.links if s not in ids]
        return ids

    def summary(self, limit: int = 50) -> Dict[str, Any]:
        return {"pipeline": self.pipeline, "read": dict(self.read), "created": len(self.creates),
                "updated": len(self.updates), "unchanged": self.unchanged, "links_added": len(self.links),
                "rejected": len(self.rejected), "rejects": [r.as_dict() for r in self.rejected[:limit]],
                "watermarks": dict(self.watermarks), "held_at": dict(self.held)}


class Pipeline:
    def __init__(self, spec: Dict[str, Any], ontology: Ontology, base_dir: Path = Path(".")):
        if not isinstance(spec, dict):
            raise PipelineError("a pipeline must be a JSON object")
        self.name = str(spec.get("name") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.name):
            raise PipelineError("a pipeline needs a name of letters, digits, '_', '.' or '-'")
        self.ontology, self.base_dir = ontology, Path(base_dir)
        self.every = spec.get("every")
        if self.every is not None and (not isinstance(self.every, (int, float)) or self.every < 1):
            raise PipelineError(f"{self.name}: every must be a number of seconds >= 1")
        self.sources: Dict[str, Dict[str, Any]] = dict(spec.get("sources") or {})
        if not self.sources:
            raise PipelineError(f"{self.name}: no sources")
        for sname, src in self.sources.items():
            if not isinstance(src, dict) or src.get("type") not in SOURCE_TYPES:
                raise PipelineError(f"{self.name}.{sname}: type must be one of {list(SOURCE_TYPES)}")
            if src["type"] in ("csv", "json", "jsonl") and not src.get("path"):
                raise PipelineError(f"{self.name}.{sname}: path is required")
            if src["type"] == "sql":
                if not src.get("query") or not (src.get("database") or src.get("driver")):
                    raise PipelineError(f"{self.name}.{sname}: sql sources need a query and a database or driver")
                if src.get("driver") and not src.get("dsn_env"):
                    raise PipelineError(f"{self.name}.{sname}: give dsn_env, the environment variable holding "
                                        "the connection string (never the secret itself)")
            if src["type"] == "http" and not str(src.get("url", "")).startswith(("http://", "https://")):
                raise PipelineError(f"{self.name}.{sname}: url must be http or https")
            inc = src.get("incremental")
            if inc is not None and (not isinstance(inc, dict) or not inc.get("column")):
                raise PipelineError(f"{self.name}.{sname}: incremental needs a column")
        self.mappings = [self._mapping(i, m) for i, m in enumerate(spec.get("mappings") or [])]
        if not self.mappings:
            raise PipelineError(f"{self.name}: no mappings")

    @classmethod
    def load(cls, path: str, ontology: Ontology) -> "Pipeline":
        p = Path(path).resolve()
        try:
            spec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PipelineError(f"cannot read pipeline {path}: {exc}") from None
        return cls(spec, ontology, p.parent)

    def _mapping(self, index: int, m: Dict[str, Any]) -> Mapping:
        where = f"{self.name}.mappings[{index}]"
        if m.get("source") not in self.sources:
            raise PipelineError(f"{where}: unknown source {m.get('source')!r}")
        entity = self.ontology.canonical(m.get("entity"))
        etype = self.ontology.entities.get(entity)
        if etype is None:
            raise PipelineError(f"{where}: unknown entity {m.get('entity')!r}")
        if "id" not in m:
            raise PipelineError(f"{where}: id is required")
        attrs = {}
        for name, spec in (m.get("attributes") or {}).items():
            if name == ID or not etype.has_attribute(name):
                raise PipelineError(f"{where}: {entity} has no attribute {name!r}")
            attrs[name] = ValueSpec.parse(spec, f"{where}.attributes.{name}")
        links = []
        for j, link in enumerate(m.get("links") or []):
            kind, reverse = str(link.get("kind", "")), bool(link.get("reverse", False))
            rels = [r for r in self.ontology.relationships if r.kind == kind and
                    (r.target if reverse else r.source) == entity]
            if not rels:
                raise PipelineError(f"{where}.links[{j}]: {entity} has no {'incoming' if reverse else ''} "
                                    f"relationship {kind!r}")
            links.append((kind, ValueSpec.parse(link.get("target"), f"{where}.links[{j}].target"), reverse))
        checks = []
        for j, check in enumerate(m.get("checks") or []):
            if check.get("rule") not in CHECKS:
                raise PipelineError(f"{where}.checks[{j}]: rule must be one of {list(CHECKS)}")
            if check.get("attribute") not in attrs:
                raise PipelineError(f"{where}.checks[{j}]: attribute must be one this mapping sets")
            if check["rule"] in ("min", "max", "in", "pattern") and "value" not in check:
                raise PipelineError(f"{where}.checks[{j}]: {check['rule']} needs a value")
            if check["rule"] == "pattern":
                re.compile(str(check["value"]))
            checks.append(dict(check))
        return Mapping(m["source"], entity, ValueSpec.parse(m["id"], f"{where}.id"), attrs, links, checks)

    # -- extract ------------------------------------------------------------------
    def _path(self, src: Dict[str, Any]) -> Path:
        return (self.base_dir / src["path"]).resolve()

    def extract(self, source: str, watermark: Optional[str] = None,
                pushed: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Rows of one source, as dictionaries, newer than ``watermark`` for incremental sources."""
        src = self.sources[source]
        kind = src["type"]
        try:
            if kind == "push":
                rows = list(pushed or [])
            elif kind == "csv":
                text = self._path(src).read_text(encoding=src.get("encoding", "utf-8-sig"))
                rows = list(csv.DictReader(io.StringIO(text), delimiter=src.get("delimiter", ",")))
            elif kind == "jsonl":
                lines = self._path(src).read_text(encoding="utf-8").splitlines()
                rows = [json.loads(line) for line in lines if line.strip()]
            elif kind == "json":
                rows = _dig(json.loads(self._path(src).read_text(encoding="utf-8")), src.get("items"))
            elif kind == "sql":
                rows = self._sql(src, watermark)
            else:
                rows = self._http(src)
        except (OSError, ValueError) as exc:
            raise PipelineError(f"{self.name}.{source}: cannot read: {exc}") from None
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise PipelineError(f"{self.name}.{source}: expected a list of records")
        inc = src.get("incremental")
        if inc and watermark not in (None, "") and kind != "sql":  # SQL filters in the query itself
            rows = [r for r in rows if _after(r.get(inc["column"]), watermark)]
        return rows

    def _sql(self, src: Dict[str, Any], watermark: Optional[str]) -> List[Dict[str, Any]]:
        inc = src.get("incremental") or {}
        mark = watermark if watermark not in (None, "") else inc.get("initial", "")
        if src.get("driver"):
            module = importlib.import_module(src["driver"])
            dsn = os.environ.get(src["dsn_env"])
            if not dsn:
                raise PipelineError(f"{self.name}: environment variable {src['dsn_env']} is not set")
            conn, style = module.connect(dsn), getattr(module, "paramstyle", "qmark")
        else:
            import sqlite3

            path = (self.base_dir / src["database"]).resolve()
            if not path.exists():
                raise PipelineError(f"{self.name}: database {path} does not exist")
            conn, style = sqlite3.connect(f"file:{path}?mode=ro", uri=True), "qmark"
        placeholder = {"qmark": "?", "named": ":watermark", "numeric": ":1", "format": "%s",
                       "pyformat": "%(watermark)s"}[style]
        query = str(src["query"])
        uses = "{watermark}" in query
        query = query.replace("{watermark}", placeholder)
        params: Any = ()
        if uses:
            params = {"watermark": mark} if style in ("named", "pyformat") else (mark,)
        try:
            cur = conn.cursor()
            cur.execute(query, params) if uses else cur.execute(query)
            names = [d[0] for d in cur.description or []]
            return [dict(zip(names, row)) for row in cur.fetchall()]
        except Exception as exc:  # DB-API errors have no common base class
            raise PipelineError(f"{self.name}: query failed: {type(exc).__name__}: {exc}") from None
        finally:
            conn.close()

    def _http(self, src: Dict[str, Any]) -> List[Dict[str, Any]]:
        headers = {"Accept": "application/json"}
        for name, value in (src.get("headers") or {}).items():
            if isinstance(value, dict) and "env" in value:  # secrets come from the environment
                secret = os.environ.get(value["env"])
                if not secret:
                    raise PipelineError(f"{self.name}: environment variable {value['env']} is not set")
                value = value.get("prefix", "") + secret
            headers[name] = str(value)
        url, rows = src["url"], []
        for _ in range(MAX_PAGES):
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=float(src.get("timeout", 30))) as resp:
                payload = json.loads(resp.read())
            page = _dig(payload, src.get("items"))
            if not isinstance(page, list):
                raise PipelineError(f"{self.name}: {url} returned no list at {src.get('items')!r}")
            rows.extend(page)
            url = _dig(payload, src.get("next")) if src.get("next") else None
            if not url:
                return rows
            if not str(url).startswith(("http://", "https://")):
                raise PipelineError(f"{self.name}: next page {url!r} is not an http(s) URL")
        raise PipelineError(f"{self.name}: more than {MAX_PAGES} pages")

    # -- transform ----------------------------------------------------------------
    def read(self, watermarks: Dict[str, str], pushed: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> Plan:
        """Read the sources (no graph needed, so no lock is held while waiting on other systems)."""
        plan = Plan(self.name)
        rows_by_source = plan.rows
        pushed = pushed or {}
        unknown = set(pushed) - {n for n, s in self.sources.items() if s["type"] == "push"}
        if unknown:
            raise PipelineError(f"{self.name}: {sorted(unknown)} are not push sources")
        for sname, src in self.sources.items():
            if src["type"] == "push" and sname not in pushed:
                continue  # nothing pushed for this source in this call
            if src["type"] != "push" and pushed:
                continue  # a push call loads only what was pushed
            rows = self.extract(sname, watermarks.get(sname), pushed.get(sname))
            rows_by_source[sname] = rows
            plan.read[sname] = len(rows)
        plan.previous = dict(watermarks)
        return plan

    def _advance_watermarks(self, plan: Plan) -> None:
        """Move each incremental source's watermark to its newest row, but not past a rejected row
        (so the row is read again once its cause, such as a missing policy, is fixed) unless the source
        sets ``skip_rejected``."""
        for sname, rows in plan.rows.items():
            inc = self.sources[sname].get("incremental")
            if not inc:
                continue
            col = inc["column"]
            marks = [str(r[col]) for r in rows if r.get(col) not in (None, "")]
            if not inc.get("skip_rejected"):
                held = [str(r.data.get(col)) for r in plan.rejected if r.source == sname
                        and r.data.get(col) not in (None, "")]
                if held:
                    first = min(held, key=_sort_key)
                    marks = [m for m in marks if _after(first, m)]
                    plan.held[sname] = first
            newest = max(marks, key=_sort_key) if marks else None
            if newest is not None and (plan.previous.get(sname) in (None, "") or
                                       _after(newest, plan.previous[sname])):
                plan.watermarks[sname] = newest

    def plan(self, graph: Any, read: Plan) -> Plan:
        """Work out the changes the rows read would make, rejecting rows that fail a check."""
        from .graph import KnowledgeGraph

        plan, rows_by_source = read, read.rows

        candidates: List[Dict[str, Any]] = []  # accepted rows: id, entity, attributes, links, source, row
        seen: Dict[str, str] = {}
        for m in self.mappings:
            etype = self.ontology.entities[m.entity]
            for number, row in enumerate(rows_by_source.get(m.source, []), start=1):
                reject = lambda reason: plan.rejected.append(  # noqa: E731
                    Rejected(m.source, number, f"{m.entity}: {reason}", _clean(row)))
                iid = m.id.read(row)
                if iid in (None, ""):
                    reject("no id")
                    continue
                iid = str(iid)
                existing = graph._instances.get(iid)
                if existing is not None and existing.type != m.entity:
                    reject(f"id {iid!r} already belongs to a {existing.type}")
                    continue
                if iid in seen:
                    reject(f"duplicate id {iid!r} (first seen in {seen[iid]})")
                    continue
                values, error = {}, None
                for attr, spec in m.attributes.items():
                    if spec.on == "create" and existing is not None:
                        continue
                    try:
                        values[attr] = coerce(etype.attributes[attr].type if attr != STATUS else "string",
                                              spec.read(row))
                    except (ValueError, TypeError) as exc:
                        error = f"{attr}: {exc}"
                        break
                if error is None:
                    error = self._check(m, values, etype, existing)
                if error is None:  # the object as it would be stored must satisfy the ontology
                    try:
                        merged = {**(existing.attributes if existing else {}), **values}
                        KnowledgeGraph(self.ontology).add(m.entity, iid, **merged)
                    except OntologyError as exc:
                        error = str(exc)
                if error:
                    reject(error)
                    continue
                links = []
                for kind, spec, reverse in m.links:
                    target = spec.read(row)
                    if target not in (None, ""):
                        links.append((kind, str(target), reverse))
                seen[iid] = f"{m.source} row {number}"
                candidates.append({"id": iid, "entity": m.entity, "values": values, "links": links,
                                   "source": m.source, "row": number, "data": row, "existing": existing})

        # links must point at objects that exist, or are loaded in this batch; drop rows until that holds
        while True:
            ids = set(graph._instances) | {c["id"] for c in candidates}
            bad = []
            for c in candidates:
                for kind, target, reverse in c["links"]:
                    problem = self._link_problem(graph, candidates, c, kind, target, reverse, ids)
                    if problem:
                        bad.append((c, problem))
                        break
            if not bad:
                break
            for c, problem in bad:
                plan.rejected.append(Rejected(c["source"], c["row"], f"{c['entity']}: {problem}", _clean(c["data"])))
                candidates.remove(c)

        existing_links = set(graph._links)
        for c in candidates:
            iid, existing = c["id"], c["existing"]
            if existing is None:
                plan.creates[iid] = (c["entity"], c["values"])
                changed = sorted(c["values"])
            else:
                diff = {a: v for a, v in c["values"].items() if existing.attributes.get(a) != v}
                if diff:
                    plan.updates[iid] = (c["entity"], diff)
                changed = sorted(diff)
            new_links = []
            for kind, target, reverse in c["links"]:
                link = (target, kind, iid) if reverse else (iid, kind, target)
                if link not in existing_links:
                    existing_links.add(link)
                    plan.links.append(link)
                    new_links.append(f"{'^' if reverse else ''}{kind}:{target}")
            if not changed and not new_links:
                plan.unchanged += 1
                continue
            plan.lineage.append({"instance_id": iid, "entity": c["entity"], "source": c["source"],
                                 "row": c["row"], "action": "created" if existing is None else "updated",
                                 "attributes": changed, "links": new_links})
        self._advance_watermarks(plan)
        return plan

    def _check(self, m: Mapping, values: Dict[str, Any], etype: Any, existing: Any) -> Optional[str]:
        status = values.get(STATUS)
        if status is not None and status not in etype.states:
            return f"{status!r} is not a state of {m.entity}"
        for check in m.checks:
            attr, rule, value = check["attribute"], check["rule"], values.get(check["attribute"])
            if attr not in values:  # an on-create attribute of an existing object: not part of this load
                continue
            label = check.get("message") or f"{attr} fails {rule}"
            if rule == "required":
                if value is None:
                    return f"{attr} is required"
                continue
            if value is None:
                continue
            try:
                ok = {"min": lambda: value >= check["value"], "max": lambda: value <= check["value"],
                      "in": lambda: value in check["value"],
                      "pattern": lambda: re.fullmatch(str(check["value"]), str(value)) is not None}[rule]()
            except TypeError:
                ok = False
            if not ok:
                return f"{label} ({value!r})"
        return None

    def _link_problem(self, graph: Any, candidates: List[Dict[str, Any]], c: Dict[str, Any], kind: str,
                      target: str, reverse: bool, ids: set) -> Optional[str]:
        if target not in ids:
            return f"link {kind} to unknown object {target!r}"
        other = next((x["entity"] for x in candidates if x["id"] == target), None) or graph._instances[target].type
        src, tgt = (other, c["entity"]) if reverse else (c["entity"], other)
        if not any(r.kind == kind and r.source == src and r.target == tgt for r in self.ontology.relationships):
            return f"no relationship {src} -{kind}-> {tgt} (target {target!r} is a {other})"
        return None


def _clean(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): (v if isinstance(v, (str, int, float, bool)) or v is None else str(v)) for k, v in row.items()}


def _sort_key(value: Any) -> Tuple[int, Any]:
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _after(value: Any, mark: Any) -> bool:
    if value in (None, ""):
        return False
    a, b = _sort_key(value), _sort_key(mark)
    return a > b if a[0] == b[0] else str(value) > str(mark)


def load_pipelines(spec: Dict[str, str], ontology: Ontology, base_dir: Path) -> Dict[str, Pipeline]:
    pipelines: Dict[str, Pipeline] = {}
    for name, path in (spec or {}).items():
        pipe = Pipeline.load(str((Path(base_dir) / path).resolve()), ontology)
        if pipe.name != name:
            raise PipelineError(f"pipeline {path} is named {pipe.name!r}, configured as {name!r}")
        pipelines[name] = pipe
    return pipelines


def apply_to_graph(graph: Any, plan: Plan) -> None:
    """Make the in-memory graph match a plan the store has just committed."""
    from .graph import Instance, KnowledgeGraph

    for iid, (etype, values) in plan.creates.items():
        graph._instances[iid] = KnowledgeGraph(graph.ontology).add(etype, iid, **values)
    for iid, (etype, diff) in plan.updates.items():
        inst = graph._instances[iid]
        graph._instances[iid] = Instance(etype, iid, {**inst.attributes, **diff})
    for link in plan.links:
        graph._links.append(link)
