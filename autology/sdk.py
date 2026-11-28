"""Generate typed client libraries for an Autology deployment, from its ontology.

    python -m autology sdk ONTOLOGY --lang python --out autology_client.py
    python -m autology sdk ONTOLOGY --lang typescript --out autologyClient.ts
    GET /api/sdk/python | /api/sdk/typescript          # from a running server

The generated client is one dependency-free file. It types everything the ontology defines:

* one type per entity, with its attributes and its states as a union of literals;
* the case shape agents accept (multi-record entities as lists);
* action, goal, competency-question, entity and state names as literal unions;
* typed helpers per entity (``list_order`` / ``listOrder``), per competency question
  (``ask_cq_01`` / ``askCq01``) and per goal (``run_fulfil_contract`` / ``runFulfilContract``),
  plus every REST endpoint.

Values hidden from the caller by a data-access rule arrive as the string ``"***redacted***"``,
which the attribute types include. The client carries the ontology fingerprint it was generated
from; ``check_compatibility()`` compares it with the server's and reports drift.
"""

from __future__ import annotations

import json
import keyword
import re
from typing import Dict, List

from .governance import REDACTED
from .ontology import Ontology

PY_TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool", "date": "str",
            "datetime": "str"}
TS_TYPES = {"string": "string", "number": "number", "integer": "number", "boolean": "boolean", "date": "string",
            "datetime": "string"}


def _snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).strip("_").lower()
    s = s if s and not s[0].isdigit() else f"n_{s}"
    return s + "_" if keyword.iskeyword(s) else s


def _camel(name: str) -> str:
    parts = _snake(name).rstrip("_").split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _pascal(name: str) -> str:
    return "".join(p.title() for p in _snake(name).rstrip("_").split("_"))


def _lit(values) -> str:
    return ", ".join(json.dumps(v) for v in values)


def _py_generic(lines: List[str]) -> set:
    return {m.group(1) for line in lines for m in [re.match(r"    def (\w+)\(", line)] if m}


def _free(name: str, taken: set, suffix: str) -> str:
    """A method name that does not clash with a built-in endpoint method."""
    while name in taken:
        name += suffix
    taken.add(name)
    return name


def _ident_ok(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name)


# -- Python ---------------------------------------------------------------------------
def generate_python(ontology: Ontology) -> str:
    o = ontology
    out: List[str] = [
        f'"""Typed client for the Autology deployment of {o.ref}. Generated - do not edit.',
        "",
        "Regenerate with: python -m autology sdk ONTOLOGY --lang python",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import json",
        "import urllib.error",
        "import urllib.parse",
        "import urllib.request",
        "from typing import Any, Dict, List, Literal, Optional, TypedDict, Union, cast",
        "",
        f"ONTOLOGY_REF = {json.dumps(o.ref)}",
        f"ONTOLOGY_FINGERPRINT = {json.dumps(o.fingerprint)}",
        "",
        f"Redacted = Literal[{json.dumps(REDACTED)}]",
        f"EntityName = Literal[{_lit(o.entities)}]",
        f"ObjectTypeName = Literal[{_lit(list(o.entities) + list(o.interfaces))}]",
        f"ActionName = Literal[{_lit(o.actions) or json.dumps('')}]",
        f"GoalName = Literal[{_lit(o.goals) or json.dumps('')}]",
        f"QuestionId = Literal[{_lit(q.id for q in o.questions) or json.dumps('')}]",
        "",
    ]
    for e in o.entities.values():
        p = _pascal(e.name)
        out.append(f"{p}State = Literal[{_lit(e.states)}]")
    out.append("")
    for e in o.entities.values():
        p = _pascal(e.name)
        fields = [("status", f"{p}State")] + [
            (a.name, f"Union[{PY_TYPES.get(a.type, 'Any')}, Redacted, None]" if a.type in PY_TYPES else "Any")
            for a in e.attributes.values() if a.name != "status"]
        inputs = [("status", f"{p}State")] + [(a.name, f"Optional[{PY_TYPES.get(a.type, 'Any')}]")
                                              for a in e.attributes.values() if a.name != "status"]
        if e.multiple:
            inputs = [("id", "str")] + inputs
        out += _py_typed_dict(f"{p}Attributes", fields, e.description or f"Attributes of {e.name}")
        out += _py_typed_dict(f"{p}Input", inputs, f"{e.name} as given in a case")
        out += [f"class {p}Object(TypedDict):", f'    """A {e.name} object as the API returns it."""',
                "    id: str", f"    type: Literal[{json.dumps(e.name)}]", f"    attributes: {p}Attributes", "", ""]
    for i in o.interfaces.values():
        p = _pascal(i.name)
        fields = [("status", "str")] + [(a.name, f"Union[{PY_TYPES.get(a.type, 'Any')}, Redacted, None]"
                                         if a.type in PY_TYPES else "Any") for a in i.attributes.values()]
        out += _py_typed_dict(f"{p}Attributes", fields, i.description or f"Attributes shared by {i.name} types")
        members = [f"{_pascal(e)}Object" for e in o.implementers(i.name)]
        out += [f"{p}Object = Union[{', '.join(members)}]" if len(members) > 1 else
                f"{p}Object = {members[0] if members else 'Dict[str, Any]'}", ""]
    case_fields = [(e.name, f"List[{_pascal(e.name)}Input]" if e.multiple else f"{_pascal(e.name)}Input")
                   for e in o.entities.values()]
    out += _py_typed_dict("Case", case_fields, "Case data an agent run starts from")
    out += [
        "class AutologyApiError(Exception):",
        "    def __init__(self, status: int, message: str):",
        '        super().__init__(f"{status}: {message}")',
        "        self.status = status",
        "        self.message = message",
        "",
        "",
        "class AutologyClient:",
        f'    """REST client for {o.ref}. Uses only the Python standard library."""',
        "",
        "    def __init__(self, base_url: str, token: str, timeout: float = 30.0):",
        '        self.base_url = base_url.rstrip("/")',
        "        self.token = token",
        "        self.timeout = timeout",
        "",
        "    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,",
        "                 query: Optional[Dict[str, Any]] = None) -> Any:",
        '        url = self.base_url + "/api/" + path',
        "        params = {k: v for k, v in (query or {}).items() if v is not None}",
        "        if params:",
        '            url += "?" + urllib.parse.urlencode(params)',
        "        data = json.dumps(body).encode() if body is not None else None",
        '        req = urllib.request.Request(url, data=data, method=method, headers={',
        '            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})',
        "        try:",
        "            with urllib.request.urlopen(req, timeout=self.timeout) as resp:",
        "                payload = resp.read()",
        '                if "json" in resp.headers.get("Content-Type", ""):',
        "                    return json.loads(payload)",
        "                return payload.decode()",
        "        except urllib.error.HTTPError as exc:",
        "            try:",
        '                message = json.loads(exc.read()).get("error", exc.reason)',
        "            except ValueError:",
        "                message = str(exc.reason)",
        "            raise AutologyApiError(exc.code, message) from None",
        "",
        "    @staticmethod",
        "    def _q(value: str) -> str:",
        '        return urllib.parse.quote(value, safe="")',
        "",
        "    # -- generic endpoints --------------------------------------------------",
        "    def me(self) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "me"))',
        "",
        "    def ontology(self) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "ontology"))',
        "",
        "    def check_compatibility(self) -> Optional[str]:",
        '        """None if the server runs the ontology this client was generated from, else a description."""',
        "        info = self.ontology()",
        '        if info.get("fingerprint") == ONTOLOGY_FINGERPRINT:',
        "            return None",
        '        return f"client generated for {ONTOLOGY_REF}, server runs {info.get(\'ref\')} (fingerprint differs)"',
        "",
        "    def list_objects(self, type: Optional[ObjectTypeName] = None, limit: int = 100, offset: int = 0,",
        "                     justification: Optional[str] = None) -> Dict[str, Any]:",
        '        """Objects you may see. Fields behind a checkpoint read "***justification required***"',
        '        unless you give a justification, which is recorded."""',
        '        return cast(Dict[str, Any], self._request("GET", "objects", query={',
        '            "type": type, "limit": limit, "offset": offset, "justification": justification}))',
        "",
        "    def get_object(self, object_id: str, justification: Optional[str] = None) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "objects/" + self._q(object_id),',
        '                                                  query={"justification": justification}))',
        "",
        "    def upsert_object(self, type: EntityName, object_id: str, attributes: Dict[str, Any],",
        "                      links: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:",
        '        body = {"type": type, "id": object_id, "attributes": attributes, "links": links or []}',
        '        return cast(Dict[str, Any], self._request("POST", "objects", body))',
        "",
        "    def ask(self, question: QuestionId, **params: Any) -> Any:",
        '        return self._request("POST", "questions/" + self._q(question), {"params": params})["answer"]',
        "",
        "    def start_run(self, goal: GoalName, case: Optional[Case] = None, *, agent: Optional[str] = None,",
        "                  case_id: Optional[str] = None, case_template: Optional[str] = None,",
        "                  root: Optional[str] = None, write_back: bool = True,",
        "                  justification: Optional[str] = None) -> Dict[str, Any]:",
        '        body: Dict[str, Any] = {"goal": goal, "agent": agent, "case_id": case_id, "justification": justification}',
        "        if case_template:",
        '            body.update(case_template=case_template, root=root, write_back=write_back)',
        "        else:",
        '            body["case"] = case or {}',
        '        return cast(Dict[str, Any], self._request("POST", "runs", body))',
        "",
        "    def list_runs(self, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:",
        '        return cast(List[Dict[str, Any]], self._request("GET", "runs", query={"status": status, "limit": limit,',
        '                                                                            "offset": offset})["items"])',
        "",
        "    def get_run(self, run_id: str) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "runs/" + self._q(run_id)))',
        "",
        "    def run_audit(self, run_id: str) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "runs/" + self._q(run_id) + "/audit"))',
        "",
        "    def resume_run(self, run_id: str, force: bool = False) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("POST", "runs/" + self._q(run_id) + "/resume", {"force": force}))',
        "",
        "    def list_reviews(self, status: str = \"pending\") -> List[Dict[str, Any]]:",
        '        return cast(List[Dict[str, Any]], self._request("GET", "reviews", query={"status": status})["items"])',
        "",
        "    def get_review(self, review_id: str) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "reviews/" + self._q(review_id)))',
        "",
        "    def decide(self, review_id: str, approved: bool, comment: str = \"\") -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("POST", "reviews/" + self._q(review_id) + "/decision",',
        '                                                  {"approved": approved, "comment": comment}))',
        "",
        "    def report(self) -> str:",
        '        return cast(str, self._request("GET", "report"))',
        "",
        "    def score(self) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "score"))',
        "",
        "    def automations(self) -> List[Dict[str, Any]]:",
        '        return cast(List[Dict[str, Any]], self._request("GET", "automations")["items"])',
        "",
        "    def run_automation(self, name: str, instance: Optional[str] = None) -> List[Dict[str, Any]]:",
        '        body = {"instance": instance} if instance else {}',
        '        return cast(List[Dict[str, Any]], self._request("POST", "automations/" + self._q(name) + "/run",',
        '                                                        body)["firings"])',
        "",
        "    def notifications(self, since: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:",
        '        return cast(List[Dict[str, Any]], self._request("GET", "notifications",',
        '                                                        query={"since": since, "limit": limit})["items"])',
        "",
        "    def create_scenario(self, name: str, edits: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("POST", "scenarios", {"name": name, "edits": edits or []}))',
        "",
        "    def scenario(self, scenario_id: str) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("GET", "scenarios/" + self._q(scenario_id)))',
        "",
        "    def scenario_edits(self, scenario_id: str, edits: List[Dict[str, Any]]) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("POST", "scenarios/" + self._q(scenario_id) + "/edits",',
        '                                                  {"edits": edits}))',
        "",
        "    def compare_scenario(self, scenario_id: str, checks: Optional[List[Dict[str, Any]]] = None,",
        "                         schedule: bool = False) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("POST", "scenarios/" + self._q(scenario_id) + "/compare",',
        '                                                  {"checks": checks or [], "schedule": schedule}))',
        "",
        "    def commit_scenario(self, scenario_id: str) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("POST", "scenarios/" + self._q(scenario_id) + "/commit", {}))',
        "",
        "    def discard_scenario(self, scenario_id: str) -> Dict[str, Any]:",
        '        return cast(Dict[str, Any], self._request("POST", "scenarios/" + self._q(scenario_id) + "/discard", {}))',
        "",
        "    # -- typed helpers from the ontology ---------------------------------------",
    ]
    taken = _py_generic(out)
    for e in o.entities.values():
        p, s = _pascal(e.name), _snake(e.name).rstrip("_")
        list_name = _free(f"list_{s}", taken, "_objects")
        get_name = _free(f"get_{s}", taken, "_object")
        out += [
            f"    def {list_name}(self, limit: int = 100, offset: int = 0) -> List[{p}Object]:",
            f'        """{e.name} objects you may see{" (" + e.description + ")" if e.description else ""}."""',
            f'        return cast(List[{p}Object], self.list_objects({json.dumps(e.name)}, limit, offset)["items"])',
            "",
            f"    def {get_name}(self, object_id: str) -> {p}Object:",
            "        obj = self.get_object(object_id)",
            f'        if obj.get("type") != {json.dumps(e.name)}:',
            f'            raise AutologyApiError(404, f"{{object_id}} is a {{obj.get(\'type\')}}, not a {e.name}")',
            f"        return cast({p}Object, obj)",
            "",
        ]
    for i in o.interfaces.values():
        p, s_ = _pascal(i.name), _snake(i.name).rstrip("_")
        out += [f"    def {_free('list_' + s_, taken, '_objects')}(self, limit: int = 100, offset: int = 0) -> List[{p}Object]:",
                f'        """Objects of every type implementing {i.name}."""',
                f'        return cast(List[{p}Object], self.list_objects({json.dumps(i.name)}, limit, offset)["items"])', ""]
    for q in o.questions:
        out += [f"    def {_free('ask_' + _snake(q.id), taken, '_')}(self, **params: Any) -> Any:",
                f"        {json.dumps(q.question)}",
                f"        return self.ask({json.dumps(q.id)}, **params)", ""]
    for g in o.goals.values():
        out += [f"    def {_free('run_' + _snake(g.name).rstrip('_'), taken, '_goal')}(self, case: Optional[Case] = None,"
                " *, root: Optional[str] = None,",
                "                 case_template: Optional[str] = None, agent: Optional[str] = None,",
                "                 case_id: Optional[str] = None, justification: Optional[str] = None) -> Dict[str, Any]:",
                f'        """{g.description or g.name}. Give case_template and root (case data is admin-only)."""',
                f"        return self.start_run({json.dumps(g.name)}, case, agent=agent, case_id=case_id,",
                "                              case_template=case_template, root=root, justification=justification)", ""]
    return "\n".join(out).rstrip() + "\n"


def _py_typed_dict(name: str, fields, doc: str) -> List[str]:
    if all(_ident_ok(f) for f, _ in fields):
        lines = [f"class {name}(TypedDict, total=False):", f"    {json.dumps(doc)}"]
        lines += [f"    {f}: {t}" for f, t in fields]
        return lines + ["", ""]
    body = ", ".join(f"{json.dumps(f)}: {t}" for f, t in fields)
    return [f"{name} = TypedDict({json.dumps(name)}, {{{body}}}, total=False)", ""]


# -- TypeScript ---------------------------------------------------------------------------
def generate_typescript(ontology: Ontology) -> str:
    o = ontology
    union = lambda vals: " | ".join(json.dumps(v) for v in vals) or "never"  # noqa: E731
    out: List[str] = [
        f"// Typed client for the Autology deployment of {o.ref}. Generated - do not edit.",
        "// Regenerate with: python -m autology sdk ONTOLOGY --lang typescript",
        "",
        f"export const ONTOLOGY_REF = {json.dumps(o.ref)};",
        f"export const ONTOLOGY_FINGERPRINT = {json.dumps(o.fingerprint)};",
        "",
        f"export type Redacted = {json.dumps(REDACTED)};",
        f"export type EntityName = {union(o.entities)};",
        f"export type ObjectTypeName = {union(list(o.entities) + list(o.interfaces))};",
        f"export type ActionName = {union(o.actions)};",
        f"export type GoalName = {union(o.goals)};",
        f"export type QuestionId = {union(q.id for q in o.questions)};",
        "export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };",
        "export type JsonObject = { [key: string]: Json };",
        "",
    ]
    for e in o.entities.values():
        p = _pascal(e.name)
        out.append(f"export type {p}State = {union(e.states)};")
        out.append(f"/** {e.description or 'Attributes of ' + e.name} */")
        out.append(f"export interface {p}Attributes {{")
        out.append(f"  status?: {p}State;")
        for a in e.attributes.values():
            if a.name != "status":
                t = TS_TYPES.get(a.type, "Json")
                out.append(f"  {json.dumps(a.name)}?: {t} | Redacted | null;")
        out.append("}")
        out.append(f"export interface {p}Input {{")
        if e.multiple:
            out.append("  id?: string;")
        out.append(f"  status?: {p}State;")
        for a in e.attributes.values():
            if a.name != "status":
                out.append(f"  {json.dumps(a.name)}?: {TS_TYPES.get(a.type, 'Json')} | null;")
        out.append("}")
        out.append(f"export interface {p}Object {{ id: string; type: {json.dumps(e.name)}; attributes: {p}Attributes;"
                   f" links?: JsonObject[] }}")
        out.append("")
    for i in o.interfaces.values():
        p = _pascal(i.name)
        out.append(f"/** {i.description or 'Attributes shared by ' + i.name + ' types'} */")
        out.append(f"export interface {p}Attributes {{")
        out.append("  status?: string;")
        for a in i.attributes.values():
            out.append(f"  {json.dumps(a.name)}?: {TS_TYPES.get(a.type, 'Json')} | Redacted | null;")
        out.append("}")
        members = [f"{_pascal(e)}Object" for e in o.implementers(i.name)] or ["JsonObject"]
        out.append(f"export type {p}Object = {' | '.join(members)};")
        out.append("")
    out.append("export interface Case {")
    for e in o.entities.values():
        p = _pascal(e.name)
        out.append(f"  {json.dumps(e.name)}?: {p}Input{'[]' if e.multiple else ''};")
    out += [
        "}",
        "",
        "export class AutologyApiError extends Error {",
        "  readonly status: number;",
        "  constructor(status: number, message: string) {",
        "    super(`${status}: ${message}`);",
        "    this.status = status;",
        "  }",
        "}",
        "",
        "type Query = Record<string, string | number | boolean | undefined | null>;",
        "",
        f"/** REST client for {o.ref}. Works wherever fetch is available (browsers, Node 18+, Deno, Bun). */",
        "export class AutologyClient {",
        "  private readonly baseUrl: string;",
        "  private readonly token: string;",
        "  constructor(baseUrl: string, token: string) {",
        '    this.baseUrl = baseUrl.replace(/\\/+$/, "");',
        "    this.token = token;",
        "  }",
        "",
        "  private async request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {",
        "    const params = new URLSearchParams();",
        "    for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null) params.set(k, String(v));",
        '    const qs = params.toString() ? `?${params}` : "";',
        "    const res = await fetch(`${this.baseUrl}/api/${path}${qs}`, {",
        "      method,",
        '      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json" },',
        "      body: body === undefined ? undefined : JSON.stringify(body),",
        "    });",
        '    const isJson = (res.headers.get("Content-Type") ?? "").includes("json");',
        "    const payload: unknown = isJson ? await res.json() : await res.text();",
        "    if (!res.ok) {",
        "      const msg = isJson && payload && typeof payload === \"object\" && \"error\" in payload",
        "        ? String((payload as { error: unknown }).error) : res.statusText;",
        "      throw new AutologyApiError(res.status, msg);",
        "    }",
        "    return payload as T;",
        "  }",
        "",
        "  private static q(v: string): string { return encodeURIComponent(v); }",
        "",
        "  // -- generic endpoints",
        '  me(): Promise<JsonObject> { return this.request("GET", "me"); }',
        '  ontology(): Promise<JsonObject> { return this.request("GET", "ontology"); }',
        "  async checkCompatibility(): Promise<string | null> {",
        "    const info = await this.ontology();",
        "    return info.fingerprint === ONTOLOGY_FINGERPRINT ? null",
        "      : `client generated for ${ONTOLOGY_REF}, server runs ${String(info.ref)} (fingerprint differs)`;",
        "  }",
        "  /** Fields behind a checkpoint read \"***justification required***\" unless a justification is given. */",
        "  listObjects(type?: ObjectTypeName, limit = 100, offset = 0, justification?: string):",
        "    Promise<{ total: number; items: JsonObject[] }> {",
        '    return this.request("GET", "objects", undefined, { type, limit, offset, justification });',
        "  }",
        "  getObject(id: string, justification?: string): Promise<JsonObject> {",
        "    return this.request(\"GET\", `objects/${AutologyClient.q(id)}`, undefined, { justification });",
        "  }",
        "  upsertObject(type: EntityName, id: string, attributes: JsonObject, links: JsonObject[] = []): Promise<JsonObject> {",
        '    return this.request("POST", "objects", { type, id, attributes, links });',
        "  }",
        "  async ask(question: QuestionId, params: JsonObject = {}): Promise<Json> {",
        "    const r = await this.request<{ answer: Json }>(\"POST\", `questions/${AutologyClient.q(question)}`, { params });",
        "    return r.answer;",
        "  }",
        "  startRun(goal: GoalName, opts: { case?: Case; agent?: string; caseId?: string; caseTemplate?: string;",
        "    root?: string; writeBack?: boolean; justification?: string } = {}): Promise<JsonObject> {",
        "    const body: JsonObject = { goal, agent: opts.agent ?? null, case_id: opts.caseId ?? null,",
        "      justification: opts.justification ?? null };",
        "    if (opts.caseTemplate) Object.assign(body, { case_template: opts.caseTemplate, root: opts.root ?? null,",
        "      write_back: opts.writeBack ?? true });",
        "    else body.case = (opts.case ?? {}) as unknown as JsonObject;",
        '    return this.request("POST", "runs", body);',
        "  }",
        "  async listRuns(status?: string, limit = 100, offset = 0): Promise<JsonObject[]> {",
        '    return (await this.request<{ items: JsonObject[] }>("GET", "runs", undefined, { status, limit, offset })).items;',
        "  }",
        "  getRun(id: string): Promise<JsonObject> { return this.request(\"GET\", `runs/${AutologyClient.q(id)}`); }",
        "  runAudit(id: string): Promise<JsonObject> { return this.request(\"GET\", `runs/${AutologyClient.q(id)}/audit`); }",
        "  resumeRun(id: string, force = false): Promise<JsonObject> {",
        "    return this.request(\"POST\", `runs/${AutologyClient.q(id)}/resume`, { force });",
        "  }",
        '  async listReviews(status = "pending"): Promise<JsonObject[]> {',
        '    return (await this.request<{ items: JsonObject[] }>("GET", "reviews", undefined, { status })).items;',
        "  }",
        "  getReview(id: string): Promise<JsonObject> { return this.request(\"GET\", `reviews/${AutologyClient.q(id)}`); }",
        '  decide(id: string, approved: boolean, comment = ""): Promise<JsonObject> {',
        "    return this.request(\"POST\", `reviews/${AutologyClient.q(id)}/decision`, { approved, comment });",
        "  }",
        '  report(): Promise<string> { return this.request("GET", "report"); }',
        '  score(): Promise<JsonObject> { return this.request("GET", "score"); }',
        "  async automations(): Promise<JsonObject[]> {",
        '    return (await this.request<{ items: JsonObject[] }>("GET", "automations")).items;',
        "  }",
        "  async runAutomation(name: string, instance?: string): Promise<JsonObject[]> {",
        "    const r = await this.request<{ firings: JsonObject[] }>(\"POST\", `automations/${AutologyClient.q(name)}/run`,",
        "      instance ? { instance } : {});",
        "    return r.firings;",
        "  }",
        "  async notifications(since?: string, limit = 100): Promise<JsonObject[]> {",
        '    return (await this.request<{ items: JsonObject[] }>("GET", "notifications", undefined, { since, limit })).items;',
        "  }",
        "  createScenario(name: string, edits: JsonObject[] = []): Promise<JsonObject> {",
        '    return this.request("POST", "scenarios", { name, edits });',
        "  }",
        "  scenario(id: string): Promise<JsonObject> { return this.request(\"GET\", `scenarios/${AutologyClient.q(id)}`); }",
        "  scenarioEdits(id: string, edits: JsonObject[]): Promise<JsonObject> {",
        "    return this.request(\"POST\", `scenarios/${AutologyClient.q(id)}/edits`, { edits });",
        "  }",
        "  compareScenario(id: string, checks: JsonObject[] = [], schedule = false): Promise<JsonObject> {",
        "    return this.request(\"POST\", `scenarios/${AutologyClient.q(id)}/compare`, { checks, schedule });",
        "  }",
        "  commitScenario(id: string): Promise<JsonObject> {",
        "    return this.request(\"POST\", `scenarios/${AutologyClient.q(id)}/commit`, {});",
        "  }",
        "  discardScenario(id: string): Promise<JsonObject> {",
        "    return this.request(\"POST\", `scenarios/${AutologyClient.q(id)}/discard`, {});",
        "  }",
        "",
        "  // -- typed helpers from the ontology",
    ]
    taken = {m.group(1) for line in out for m in [re.match(r"  (?:async )?(\w+)\(", line)] if m}
    for e in o.entities.values():
        p = _pascal(e.name)
        list_name, get_name = _free(f"list{p}", taken, "Objects"), _free(f"get{p}", taken, "Object")
        out += [
            f"  /** {e.name} objects you may see{' (' + e.description + ')' if e.description else ''}. */",
            f"  async {list_name}(limit = 100, offset = 0): Promise<{p}Object[]> {{",
            f"    return (await this.listObjects({json.dumps(e.name)}, limit, offset)).items as unknown as {p}Object[];",
            "  }",
            f"  async {get_name}(id: string): Promise<{p}Object> {{",
            "    const obj = await this.getObject(id);",
            f"    if (obj.type !== {json.dumps(e.name)}) throw new AutologyApiError(404, `${{id}} is not a {e.name}`);",
            f"    return obj as unknown as {p}Object;",
            "  }",
        ]
    for i in o.interfaces.values():
        p = _pascal(i.name)
        out += [f"  /** Objects of every type implementing {i.name}. */",
                f"  async {_free('list' + p, taken, 'Objects')}(limit = 100, offset = 0): Promise<{p}Object[]> {{",
                f"    return (await this.listObjects({json.dumps(i.name)}, limit, offset)).items as unknown as {p}Object[];",
                "  }"]
    for q in o.questions:
        out += [f"  /** {q.question} */",
                f"  {_free('ask' + _pascal(q.id), taken, 'Q')}(params: JsonObject = {{}}): Promise<Json> "
                f"{{ return this.ask({json.dumps(q.id)}, params); }}"]
    for g in o.goals.values():
        out += [f"  /** {g.description or g.name} */",
                f"  {_free('run' + _pascal(g.name), taken, 'Goal')}(c?: Case | null, opts: {{ agent?: string; caseId?: string;"
                " caseTemplate?: string; root?: string; justification?: string } = {}): Promise<JsonObject> {",
                f"    return this.startRun({json.dumps(g.name)}, c ? {{ ...opts, case: c }} : opts);",
                "  }"]
    out.append("}")
    return "\n".join(out) + "\n"


GENERATORS = {"python": generate_python, "typescript": generate_typescript}


def generate(ontology: Ontology, lang: str) -> str:
    if lang not in GENERATORS:
        raise ValueError(f"unknown language {lang!r}; choose from {sorted(GENERATORS)}")
    return GENERATORS[lang](ontology)


def names(ontology: Ontology) -> Dict[str, List[str]]:
    """The typed helper methods each generator emits (useful for docs and checks)."""
    py = re.findall(r"^    def (\w+)\(", generate_python(ontology), re.M)
    ts = re.findall(r"^  (?:async )?(\w+)\(", generate_typescript(ontology), re.M)
    return {"python": py[py.index("list_objects"):], "typescript": ts[ts.index("listObjects"):]}
