"""Command line: inspect and dry-run ontologies.

    python -m autology validate ONTOLOGY.json
    python -m autology describe ONTOLOGY.json
    python -m autology plan ONTOLOGY.json GOAL CASE.json [--roles kyc,sales]
"""

from __future__ import annotations

import argparse
import json
import sys

from .governance import GovernanceLayer, Principal
from .ontology import Ontology, OntologyError
from .planner import Planner
from .state import WorldState


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autology", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "describe"):
        sub.add_parser(name).add_argument("ontology")
    plan = sub.add_parser("plan", help="show the compliant plan an agent would start from")
    plan.add_argument("ontology")
    plan.add_argument("goal")
    plan.add_argument("case", help="JSON file with initial entity attributes")
    plan.add_argument("--roles", default="", help="comma-separated roles of the acting agent")
    args = parser.parse_args(argv)

    try:
        ontology = Ontology.load(args.ontology)
    except (OntologyError, OSError, json.JSONDecodeError) as exc:
        print(f"invalid ontology: {exc}", file=sys.stderr)
        return 1

    if args.command == "validate":
        print(f"ok: {ontology.name} v{ontology.version} - {len(ontology.entities)} entities, "
              f"{len(ontology.actions)} actions, {len(ontology.rules)} rules, fingerprint {ontology.fingerprint}")
    elif args.command == "describe":
        print(ontology.describe())
    else:
        with open(args.case, encoding="utf-8") as fh:
            case = json.load(fh)
        governance = GovernanceLayer(ontology)
        principal = Principal("cli", [r for r in args.roles.split(",") if r])
        state = WorldState.initial(ontology, case)
        steps = Planner(ontology, governance).plan(state, ontology.goals[args.goal], principal)
        if steps is None:
            print("no compliant plan from this state")
            return 2
        for i, step in enumerate(steps, 1):
            print(f"{i:>2}. {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
