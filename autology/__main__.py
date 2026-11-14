"""Command line: engineer, run, score and govern any Autology deployment - no Python glue required.

    python -m autology validate ONTOLOGY [--data SAMPLE.json]   # validation + lint + competency questions
    python -m autology lint ONTOLOGY
    python -m autology describe ONTOLOGY
    python -m autology ask ONTOLOGY DATA.json QUESTION_ID [--param key=value ...]
    python -m autology plan ONTOLOGY GOAL CASE.json [--roles kyc,sales]
    python -m autology run ONTOLOGY GOAL CASES.json --tools TOOLS.json [--roles r1,r2]
                       [--delegate NAME:ROLE+ROLE:TOOLS.json] [--approver auto|deny|console|POLICY.json]
                       [--reasoner planner|claude|routing|module:factory] [--out RUNS.jsonl]
    python -m autology report ONTOLOGY RUNS.jsonl
    python -m autology score ONTOLOGY [--runs RUNS.jsonl] [--tools TOOLS.json] [--data SAMPLE.json]
                       [--budget 50] [--roi 2.5 | --tco TCO.json] [--tasks-per-month N] [--min-score 80] [--json]
    python -m autology diff OLD NEW                              # semantic diff + required version bump
    python -m autology export ONTOLOGY [--format jsonld|turtle]
    python -m autology roi TCO.json
    python -m autology sdk ONTOLOGY --lang python|typescript [--out FILE]   # typed client library
    python -m autology trace [RUNS.jsonl | --db DB] [--run ID] [--out FILE] [--endpoint URL]   # OpenTelemetry
    python -m autology eval SUITE.json [--reasoner NAME=SPEC ...] [--repeats N] [--json] [--min-pass 0.95]
    python -m autology scenario ONTOLOGY DATA.json SCENARIO.json [--schedule] [--json] [--commit OUT.json]
    python -m autology mcp SERVER.json [--token-env AUTOLOGY_TOKEN]       # MCP server over stdio
    python -m autology ingest SERVER.json PIPELINE [--dry-run] [--rows ROWS.json]   # load data from other systems
    python -m autology reporting SERVER.json [--out reporting.db] [--roles analyst]   # governed tables for BI tools
    python -m autology serve SERVER.json [--host 127.0.0.1] [--port 8800] [--store PATH] [--assistant [MODEL]]
    python -m autology backup SERVER.json OUT.db [--store PATH]          # consistent online backup, verified
    python -m autology console --engine http://127.0.0.1:8800 [--port 8900]   # separate UI to talk to the engine
    python -m autology platform PLATFORM.json [--port 8700]      # isolated workspaces, each with use cases
    python -m autology token                                               # new API token and its hash
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .economics import TCOModel, evaluate, from_metrics
from .export import to_jsonld, to_turtle
from .governance import GovernanceLayer, Principal
from .graph import KnowledgeGraph
from .lint import lint, worst
from .ontology import Ontology, OntologyError
from .planner import Planner
from .state import WorldState
from .versioning import LEVELS, actual_bump, diff, required_bump


def _load(path: str) -> Ontology:
    try:
        return Ontology.load(path)
    except (OntologyError, OSError, json.JSONDecodeError) as exc:
        print(f"invalid ontology {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)


def _cmd_trace(args) -> int:
    from .tracing import export, to_otlp

    if args.db:
        from .store import Store

        store = Store(args.db)
        ids = args.run or [r["run_id"] for r in store.list_runs(limit=10 ** 9)]
        runs = [(rid, store.load_run(rid)) for rid in ids]
    elif args.runs:
        from .persistence import load_runs

        runs = [(None, r) for r in load_runs(args.runs)]
    else:
        print("give a runs file or --db", file=sys.stderr)
        return 2
    payload = to_otlp(runs, args.service_name)
    count = len(payload["resourceSpans"][0]["scopeSpans"][0]["spans"])
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    if args.endpoint:
        status = export(payload, args.endpoint)
        print(f"exported {count} spans from {len(runs)} runs to {args.endpoint} (HTTP {status})", file=sys.stderr)
    if not args.out and not args.endpoint:
        print(json.dumps(payload, indent=1))
    elif args.out:
        print(f"wrote {count} spans from {len(runs)} runs to {args.out}", file=sys.stderr)
    return 0


def _cmd_eval(args) -> int:
    from .evals import load_suite, run_suite

    try:
        suite = load_suite(args.suite)
    except (OntologyError, OSError, ValueError, KeyError) as exc:
        print(f"invalid suite: {exc}", file=sys.stderr)
        return 1
    reasoners = dict(r.split("=", 1) for r in args.reasoner) if args.reasoner else None
    report = run_suite(suite, reasoners, args.repeats)
    print(json.dumps(report.as_dict(), indent=2, default=str) if args.json else report.render(), end="")
    if args.json:
        print()
    if args.min_pass is not None:
        low = {n: m["pass_rate"] for n, m in report.summary().items() if m["pass_rate"] < args.min_pass}
        if low:
            print(f"pass rate below {args.min_pass}: {low}", file=sys.stderr)
            return 5
    return 0


def _cmd_scenario(args, onto: Ontology) -> int:
    from .scenarios import Scenario, render

    spec = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    if isinstance(spec, list):
        spec = {"edits": spec}
    graph = _graph(onto, args.data)
    scenario = Scenario(graph, spec.get("name", Path(args.scenario).stem))
    for edit in spec.get("edits", []):
        result = scenario.apply(edit)
        if result["op"] == "action" and not result["applied"]:
            print(f"note: {result['action']} was denied: {'; '.join(result['reasons'])}", file=sys.stderr)
    report = scenario.compare(spec.get("checks", []), schedule=args.schedule)
    print(json.dumps(report, indent=2, default=str) if args.json else render(report), end="" if not args.json else "\n")
    if args.commit:
        scenario.commit(graph)
        data = {"instances": [{"type": i.type, "id": i.id, **{k: v for k, v in i.attributes.items() if v is not None}}
                              for i in graph.instances()],
                "links": [list(l) for l in graph._links]}
        Path(args.commit).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.commit}", file=sys.stderr)
    return 0


def _graph(onto: Ontology, path: str) -> KnowledgeGraph:
    with open(path, encoding="utf-8") as fh:
        return KnowledgeGraph.from_dict(onto, json.load(fh))


def _value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _roles(text: str):
    return [r for r in text.replace("+", ",").split(",") if r]


def _cases(path: str):
    """A case file holds one case object, a list of cases, or a list of {"case_id", "case"} items."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    items = data if isinstance(data, list) else [data]
    for i, item in enumerate(items, 1):
        if isinstance(item, dict) and "case" in item:
            yield str(item.get("case_id", f"case-{i}")), item["case"]
        else:
            yield f"case-{i}", item


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autology", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate", help="validate, lint and check competency questions")
    v.add_argument("ontology")
    v.add_argument("--data", help="sample knowledge-graph data to answer competency questions")
    for name in ("describe", "lint"):
        sub.add_parser(name).add_argument("ontology")
    ask = sub.add_parser("ask", help="answer a competency question against data")
    ask.add_argument("ontology")
    ask.add_argument("data")
    ask.add_argument("question")
    ask.add_argument("--param", action="append", default=[], help="key=value (JSON values allowed)")
    plan = sub.add_parser("plan", help="show the compliant plan an agent would start from")
    plan.add_argument("ontology")
    plan.add_argument("goal")
    plan.add_argument("case", help="JSON file with initial entity attributes")
    plan.add_argument("--roles", default="", help="comma-separated roles of the acting agent")
    run = sub.add_parser("run", help="run an agent on one or more cases")
    run.add_argument("ontology")
    run.add_argument("goal")
    run.add_argument("cases", help="JSON: a case, a list of cases, or a list of {case_id, case}")
    run.add_argument("--tools", required=True, help="tool registry config (JSON)")
    run.add_argument("--name", default="work-agent")
    run.add_argument("--roles", default="")
    run.add_argument("--delegate", action="append", default=[], help="NAME:ROLE+ROLE:TOOLS.json (repeatable)")
    run.add_argument("--approver", default="deny", help="auto | deny | console | POLICY.json (default: deny)")
    run.add_argument("--reasoner", default="planner", help="planner | claude | routing | module:factory")
    run.add_argument("--out", help="append the runs to this JSONL file")
    run.add_argument("--db", help="also store the runs (and their audit) in this SQLite store")
    rep = sub.add_parser("report", help="compliance report from saved runs")
    rep.add_argument("ontology")
    rep.add_argument("runs", nargs="?", help="saved runs (JSONL)")
    rep.add_argument("--db", help="read the runs from this SQLite store instead")
    sc = sub.add_parser("score", help="readiness scorecard")
    sc.add_argument("ontology")
    sc.add_argument("--runs", help="saved runs (JSONL) as agent evidence")
    sc.add_argument("--db", help="SQLite store whose runs are the agent evidence")
    sc.add_argument("--tools", help="tool registry config, for tool-coverage checks")
    sc.add_argument("--data", help="sample knowledge-graph data to answer competency questions")
    sc.add_argument("--budget", type=float, help="target cost per completed task")
    sc.add_argument("--roi", type=float, help="ROI as a fraction (2.5 = 250%%)")
    sc.add_argument("--tco", help="TCO model JSON; ROI is computed with rates measured from --runs")
    sc.add_argument("--tasks-per-month", type=float)
    sc.add_argument("--min-score", type=float, help="exit 4 if the overall score is below this (CI gate)")
    sc.add_argument("--json", action="store_true", help="print the scorecard as JSON")
    d = sub.add_parser("diff", help="semantic diff and the version bump it requires")
    d.add_argument("old")
    d.add_argument("new")
    e = sub.add_parser("export")
    e.add_argument("ontology")
    e.add_argument("--format", choices=["jsonld", "turtle"], default="jsonld")
    r = sub.add_parser("roi", help="TCO / ROI from a JSON model")
    r.add_argument("model")
    sdk = sub.add_parser("sdk", help="generate a typed client library from the ontology")
    sdk.add_argument("ontology")
    sdk.add_argument("--lang", choices=["python", "typescript"], default="python")
    sdk.add_argument("--out", help="write to this file instead of standard output")
    tr = sub.add_parser("trace", help="export runs as OpenTelemetry traces (OTLP/JSON)")
    tr.add_argument("runs", nargs="?", help="runs file written by `autology run --out`")
    tr.add_argument("--db", help="read runs from this store instead")
    tr.add_argument("--run", action="append", default=[], help="only these run ids (with --db)")
    tr.add_argument("--out", help="write the OTLP/JSON payload to this file")
    tr.add_argument("--endpoint", help="POST to this OTLP/HTTP traces endpoint, e.g. http://localhost:4318/v1/traces")
    tr.add_argument("--service-name", default="autology")
    ev = sub.add_parser("eval", help="evaluate reasoners (models, prompts, routing) against a test suite")
    ev.add_argument("suite")
    ev.add_argument("--reasoner", action="append", default=[], metavar="NAME=SPEC",
                    help="evaluate these instead of the suite's reasoners (planner, claude, routing, module:factory)")
    ev.add_argument("--repeats", type=int, help="runs per case and reasoner (consistency of non-deterministic models)")
    ev.add_argument("--json", action="store_true", help="print the full report as JSON")
    ev.add_argument("--min-pass", type=float, help="exit 5 if any reasoner's pass rate is below this (CI gate)")
    scn = sub.add_parser("scenario", help="what-if: apply edits to a copy of the data and compare outcomes")
    scn.add_argument("ontology")
    scn.add_argument("data")
    scn.add_argument("scenario", help='JSON: {"name", "edits": [...], "checks": [...]} or a list of edits')
    scn.add_argument("--schedule", action="store_true", help="also compare schedule KPIs")
    scn.add_argument("--json", action="store_true", help="print the comparison as JSON")
    scn.add_argument("--commit", metavar="OUT.json", help="write the data with the scenario applied")
    mc = sub.add_parser("mcp", help="serve the governed ontology to MCP clients over stdio")
    mc.add_argument("config")
    mc.add_argument("--token-env", default="AUTOLOGY_TOKEN", help="environment variable holding the API token")
    ig = sub.add_parser("ingest", help="run a data pipeline: load checked records into the knowledge graph")
    ig.add_argument("config")
    ig.add_argument("pipeline")
    ig.add_argument("--dry-run", action="store_true", help="check and report, write nothing but the batch record")
    ig.add_argument("--rows", metavar="ROWS.json", help='rows for push sources: {"source": [{...}, ...]}')
    ig.add_argument("--store", help="store file, overriding the config")
    bk = sub.add_parser("backup", help="copy the live store consistently (safe while serving) and verify the copy")
    bk.add_argument("config")
    bk.add_argument("out")
    bk.add_argument("--store", help="store file, overriding the config")
    bk.add_argument("--audit-scope", help="workspace id, for a use case's store behind the platform router "
                                          "(its chains use that workspace's audit key)")
    rp = sub.add_parser("reporting", help="write the governed reporting database that BI tools read")
    rp.add_argument("config")
    rp.add_argument("--out", help="SQLite file (default: the server config's reporting.target)")
    rp.add_argument("--roles", help="ontology roles of the audience, comma-separated (default: from the config)")
    rp.add_argument("--store", help="store file, overriding the config")
    sv = sub.add_parser("serve", help="run the REST API and web inbox")
    sv.add_argument("config")
    sv.add_argument("--store", help="store file, overriding the config (e.g. a container volume)")
    sv.add_argument("--assistant", nargs="?", const="claude-opus-5-5", metavar="MODEL[:EFFORT]",
                    help="turn on the governed assistant with Claude (default claude-opus-5-5); it signs in with "
                         "ANTHROPIC_API_KEY or an `ant auth login` profile")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8800)
    co = sub.add_parser("console", help="run the Autology Console: a separate conversational UI for an engine")
    co.add_argument("--engine", default="http://127.0.0.1:8800", help="the engine's base URL")
    co.add_argument("--host", default="127.0.0.1")
    co.add_argument("--port", type=int, default=8900)
    pf = sub.add_parser("platform", help="serve isolated workspaces, each with its own use cases, behind one router")
    pf.add_argument("config")
    pf.add_argument("--host", default="127.0.0.1")
    pf.add_argument("--port", type=int, default=8700)
    sub.add_parser("token", help="generate an API token and the hash to put in the server config")
    return parser


def _cmd_run(args, onto: Ontology) -> int:
    from .adapters import AdapterError, load_approver, load_reasoner, load_tools
    from .agent import WorkAgent
    from .persistence import save_runs

    try:
        tools = load_tools(args.tools)
        delegates = []
        for spec in args.delegate:
            name, roles, tools_path = spec.split(":", 2)
            delegates.append(WorkAgent(name, onto, load_tools(tools_path), roles=_roles(roles)))
        approver = load_approver(args.approver)
        search = (str(Path(args.tools).resolve().parent),)
        reasoner = load_reasoner(args.reasoner, search)
    except (AdapterError, OSError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    agent = WorkAgent(args.name, onto, tools, roles=_roles(args.roles), delegates=delegates, approver=approver,
                      reasoner=reasoner)
    results = []
    for case_id, case in _cases(args.cases):
        try:
            result = agent.run(args.goal, case, case_id)
        except OntologyError as exc:
            print(f"{case_id}: invalid case: {exc}", file=sys.stderr)
            return 2
        results.append(result)
        tail = f" - {result.escalation.reason} (to {result.escalation.to})" if result.escalation else ""
        print(f"{case_id}: {result.status} after {len(result.steps)} steps{tail}")
    if args.out:
        save_runs(results, args.out, append=True)
        print(f"{len(results)} run(s) appended to {args.out}")
    if args.db:
        from .store import Store

        store = Store(args.db)
        for result in results:
            store.save_run(result, agent=args.name)
        print(f"{len(results)} run(s) stored in {args.db}")
    return 0 if all(r.status in ("completed", "deferred") for r in results) else 1


def _cmd_score(args, onto: Ontology) -> int:
    from .adapters import AdapterError, load_tools
    from .persistence import load_runs
    from .reporting import metrics
    from .scoring import score_deployment

    try:
        runs = load_runs(args.runs) if args.runs else []
        if args.db:
            from .store import Store

            runs += Store(args.db).all_runs()
        tools = load_tools(args.tools) if args.tools else None
    except (AdapterError, OSError, ValueError) as exc:
        print(f"cannot load evidence: {exc}", file=sys.stderr)
        return 2
    roi = args.roi
    if args.tco:
        model = TCOModel.load(args.tco)
        if runs:
            model = from_metrics(model, metrics(runs))
        roi = evaluate(model).roi
        if args.tasks_per_month is None:
            args.tasks_per_month = model.tasks_per_month
    card = score_deployment(onto, runs, tools=tools, graph=_graph(onto, args.data) if args.data else None,
                            cost_budget=args.budget, roi=roi, tasks_per_month=args.tasks_per_month)
    print(json.dumps(card.as_dict(), indent=2, default=str) if args.json else card.render())
    if args.min_score is not None and (card.overall or 0) < args.min_score:
        print(f"score {card.overall} is below the minimum {args.min_score}", file=sys.stderr)
        return 4
    return 0


def _cmd_backup(args) -> int:
    from .server import AutologyService
    from .store import StoreError

    service = AutologyService.from_file(args.config, args.store, audit_scope=args.audit_scope)
    try:
        out = service.store.backup(args.out)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"backup {out['path']}: {out['bytes']} bytes, schema {out['schema']}, {out['instances']} objects, "
          f"{out['runs']} runs")
    if out["unverified_runs"]:
        print(f"  audit chains that do not verify: {', '.join(out['unverified_runs'])}", file=sys.stderr)
        return 2
    print("  every audit chain verifies")
    return 0


def _cmd_reporting(args) -> int:
    from .server import AutologyService

    service = AutologyService.from_file(args.config, args.store)
    if args.out:
        service.reporting["target"] = str(Path(args.out).resolve())
    if args.roles is not None:
        service.reporting["roles"] = [r for r in args.roles.split(",") if r]
    if not service.reporting.get("target"):
        print("error: give --out or set reporting.target in the server config", file=sys.stderr)
        return 1
    meta = service.refresh_reporting()
    print(f"wrote {meta['target']} for roles {meta['roles'] or '(none)'}: "
          + ", ".join(f"{t} {n}" for t, n in meta["rows"].items()))
    for ref, why in sorted(meta["left_out_fields"].items()):
        print(f"  left out {ref}: {why}")
    if meta["hidden_records"] or meta["hidden_runs"]:
        print(f"  hidden from this audience: {meta['hidden_records']} records, {meta['hidden_runs']} runs")
    return 0


def _cmd_ingest(args) -> int:
    from .server import ApiError, AutologyService

    service = AutologyService.from_file(args.config, args.store)
    pushed = json.loads(Path(args.rows).read_text(encoding="utf-8")) if args.rows else None
    try:
        out = service.ingest(args.pipeline, "cli", args.dry_run, pushed)
    except ApiError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    mode = " (dry run: nothing written)" if out["dry_run"] else ""
    print(f"batch {out['batch_id']}{mode}: read {out['read']}, created {out['created']}, updated {out['updated']}, "
          f"unchanged {out['unchanged']}, links added {out['links_added']}, rejected {out['rejected']}")
    for rej in out["rejects"]:
        print(f"  rejected {rej['source']} row {rej['row']}: {rej['reason']}")
    for fired in out.get("triggered", []):
        print(f"  automation {fired.get('automation')} on {fired.get('instance')}: {fired.get('status')}")
    return 2 if out["rejected"] else 0


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "roi":
        print(evaluate(TCOModel.load(args.model)).render())
        return 0
    if args.command == "token":
        from .server import new_token

        token, digest = new_token()
        print(f"token (give to the user; shown once): {token}")
        print(f"token_sha256 (put in server config):  {digest}")
        return 0
    if args.command == "platform":  # pragma: no cover - blocking
        from .platform import serve as serve_platform

        serve_platform(args.config, args.host, args.port)
        return 0
    if args.command == "console":  # pragma: no cover - blocking
        from .console import serve as serve_console

        serve_console(args.engine, args.host, args.port)
        return 0
    if args.command == "serve":  # pragma: no cover - blocking
        from .server import serve

        serve(args.config, args.host, args.port, args.store, args.assistant)
        return 0
    if args.command == "diff":
        old, new = _load(args.old), _load(args.new)
        changes = diff(old, new)
        for c in changes:
            print(c)
        needed = required_bump(changes)
        got = actual_bump(old.version, new.version) if old.version != new.version else None
        print(f"\n{old.ref} -> {new.ref}: required bump {needed or 'none'}, actual {got or 'none'}")
        if needed and (got is None or LEVELS[got] < LEVELS[needed]):
            print("version bump is insufficient", file=sys.stderr)
            return 3
        return 0

    if args.command == "eval":
        return _cmd_eval(args)
    if args.command == "mcp":
        from .mcp import run

        return run(args.config, args.token_env)
    if args.command == "trace":
        return _cmd_trace(args)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "reporting":
        return _cmd_reporting(args)
    if args.command == "backup":
        return _cmd_backup(args)

    onto = _load(args.ontology)
    if args.command == "validate":
        print(f"ok: {onto.ref} - {len(onto.entities)} entities, {len(onto.actions)} actions, {len(onto.rules)} rules, "
              f"{len(onto.questions)} competency questions; modules: {', '.join(onto.modules) or '-'}; "
              f"fingerprint {onto.fingerprint}")
        findings = lint(onto)
        for f in findings:
            print(f"  {f}")
        status = 0 if worst(findings) != "error" else 1
        if args.data:
            for q, answer, ok in _graph(onto, args.data).check_competency():
                mark = {True: "OK", False: "MISMATCH", None: ""}[ok]
                print(f"  {q.id}: {q.question} -> {answer} {mark}")
                if ok is False:
                    status = 1
        return status
    if args.command == "lint":
        findings = lint(onto)
        for f in findings or ["clean"]:
            print(f)
        return 1 if worst(findings) == "error" else 0
    if args.command == "describe":
        print(onto.describe())
        return 0
    if args.command == "export":
        print(json.dumps(to_jsonld(onto), indent=2) if args.format == "jsonld" else to_turtle(onto))
        return 0
    if args.command == "ask":
        params = dict(p.split("=", 1) for p in args.param)
        result = _graph(onto, args.data).ask(args.question, **{k: _value(v) for k, v in params.items()})
        print(json.dumps(result.answer))
        return 0
    if args.command == "run":
        return _cmd_run(args, onto)
    if args.command == "scenario":
        return _cmd_scenario(args, onto)
    if args.command == "sdk":
        from .sdk import generate

        code = generate(onto, args.lang)
        if args.out:
            Path(args.out).write_text(code, encoding="utf-8")
            print(f"wrote {args.out} ({args.lang} client for {onto.ref})", file=sys.stderr)
        else:
            print(code, end="")
        return 0
    if args.command == "score":
        return _cmd_score(args, onto)
    if args.command == "report":
        from .persistence import load_runs
        from .reporting import compliance_report

        if not args.runs and not args.db:
            print("give a runs file or --db", file=sys.stderr)
            return 2
        runs = load_runs(args.runs) if args.runs else []
        if args.db:
            from .store import Store

            runs += Store(args.db).all_runs()
        print(compliance_report(runs, onto))
        return 0
    # plan
    with open(args.case, encoding="utf-8") as fh:
        case = json.load(fh)
    governance = GovernanceLayer(onto)
    principal = Principal("cli", _roles(args.roles))
    state = WorldState.initial(onto, case)
    from .planner import SearchBudgetExceeded

    try:
        steps = Planner(onto, governance).plan_with_outcomes(state, onto.goals[args.goal], principal)
    except SearchBudgetExceeded as exc:
        print(f"no plan found within the search budget: {exc}")
        return 2
    if steps is None:
        print("no compliant plan from this state")
        return 2
    for i, (step, outcome) in enumerate(steps, 1):
        print(f"{i:>2}. {step}  (expects {outcome})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
