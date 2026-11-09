"""Command line: engineer, inspect and dry-run ontologies.

    python -m autology validate ONTOLOGY [--data SAMPLE.json]   # validation + lint + competency questions
    python -m autology lint ONTOLOGY
    python -m autology describe ONTOLOGY
    python -m autology ask ONTOLOGY DATA.json QUESTION_ID [--param key=value ...]
    python -m autology plan ONTOLOGY GOAL CASE.json [--roles kyc,sales]
    python -m autology diff OLD NEW                              # semantic diff + required version bump
    python -m autology export ONTOLOGY [--format jsonld|turtle]
    python -m autology roi TCO.json
"""

from __future__ import annotations

import argparse
import json
import sys

from .economics import TCOModel, evaluate
from .export import to_jsonld, to_turtle
from .governance import GovernanceLayer, Principal
from .graph import KnowledgeGraph
from .lint import lint, worst
from .ontology import Ontology, OntologyError
from .planner import Planner
from .state import WorldState
from .versioning import actual_bump, diff, required_bump


def _load(path: str) -> Ontology:
    try:
        return Ontology.load(path)
    except (OntologyError, OSError, json.JSONDecodeError) as exc:
        print(f"invalid ontology {path}: {exc}", file=sys.stderr)
        raise SystemExit(1)


def _graph(onto: Ontology, path: str) -> KnowledgeGraph:
    with open(path, encoding="utf-8") as fh:
        return KnowledgeGraph.from_dict(onto, json.load(fh))


def _value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autology", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate")
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
    d = sub.add_parser("diff", help="semantic diff and the version bump it requires")
    d.add_argument("old")
    d.add_argument("new")
    e = sub.add_parser("export")
    e.add_argument("ontology")
    e.add_argument("--format", choices=["jsonld", "turtle"], default="jsonld")
    r = sub.add_parser("roi", help="TCO / ROI from a JSON model")
    r.add_argument("model")
    args = parser.parse_args(argv)

    if args.command == "roi":
        print(evaluate(TCOModel.load(args.model)).render())
        return 0
    if args.command == "diff":
        old, new = _load(args.old), _load(args.new)
        changes = diff(old, new)
        for c in changes:
            print(c)
        needed = required_bump(changes)
        got = actual_bump(old.version, new.version) if old.version != new.version else None
        print(f"\n{old.ref} -> {new.ref}: required bump {needed or 'none'}, actual {got or 'none'}")
        from .versioning import LEVELS

        if needed and (got is None or LEVELS[got] < LEVELS[needed]):
            print("version bump is insufficient", file=sys.stderr)
            return 3
        return 0

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
    # plan
    with open(args.case, encoding="utf-8") as fh:
        case = json.load(fh)
    governance = GovernanceLayer(onto)
    principal = Principal("cli", [r for r in args.roles.split(",") if r])
    state = WorldState.initial(onto, case)
    steps = Planner(onto, governance).plan_with_outcomes(state, onto.goals[args.goal], principal)
    if steps is None:
        print("no compliant plan from this state")
        return 2
    for i, (step, outcome) in enumerate(steps, 1):
        print(f"{i:>2}. {step}  (expects {outcome})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
