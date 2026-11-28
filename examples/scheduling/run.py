"""Ontology + dual-agent scheduling, narrated: the 6-step replanning cycle.

    python examples/scheduling/run.py                    # ECN-7 (engineering change)
    python examples/scheduling/run.py ALERT-11           # furnace breakdown (no alternative machine)
    python examples/scheduling/run.py QR-1 --solver cp-sat   # rework order, exact solver (pip install ortools)

1 event -> 2 ImpactAgent inference -> 3 risks -> 4 ScheduleAgent optimisation -> 5 ontology
validation -> 6 publish to MES (JSON + HTML Gantt in examples/scheduling/out/), all as a governed
WorkAgent run: the rules in modules/replanning.json decide what needs a planner's approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from autology import AutoApprover, ConsoleApprover, Ontology, WorkAgent  # noqa: E402
from autology.graph import KnowledgeGraph  # noqa: E402
from autology.impact import ImpactAgent  # noqa: E402
from autology.scheduling import Assignment, Problem, Schedule, gantt_text, scheduling_tools  # noqa: E402

REWORK = {"event": "QualityReturn", "source": "returnOf", "link": "reworks", "from_seq": "from_seq"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("event", nargs="?", default="ECN-7")
    ap.add_argument("--solver", default="auto", choices=["auto", "builtin", "cp-sat"])
    ap.add_argument("--time-limit", type=float, default=10.0)
    ap.add_argument("--interactive", action="store_true", help="answer the planner review yourself")
    args = ap.parse_args(argv)

    onto = Ontology.load(HERE / "ontology.json")
    data = json.loads((HERE / "data.json").read_text())
    graph = KnowledgeGraph.from_dict(onto, data)
    print(f"{onto.ref}: {len(graph.instances('WorkOrder'))} work orders, {len(graph.instances('Process'))} operations, "
          f"{len(graph.instances('Machine'))} machines, {len(graph.instances('Mold'))} molds, "
          f"{len(graph.instances('Operator'))} operators")

    print(f"\n[1] EVENT {args.event}: {graph.get(args.event).attributes}")
    preview = ImpactAgent(onto, graph).analyze(args.event)
    print(f"\n[2] IMPACTAGENT  {preview.summary(onto)}")
    for etype in ("WorkOrder", "Process"):
        some = preview.affected.get(etype, [])[:2]
        for iid in some:
            print(f"      {iid:<10} because {preview.explain(iid)}")
    print(f"\n[3] RISKS ({len(preview.risks)})")
    for r in sorted(preview.risks, key=lambda r: r.severity != "critical")[:5]:
        print(f"      {r.severity.upper():8} {r.message}")

    out = HERE / "out"
    tools = scheduling_tools(str(HERE / "ontology.json"), str(HERE / "data.json"), solver=args.solver,
                             time_limit=args.time_limit, out_dir=str(out), rework=REWORK)
    approver = ConsoleApprover() if args.interactive else AutoApprover(
        {"publish_to_mes": lambda req: req.view["Replan"]["jobs_on_hold"] == 0}, reviewer="production-planner")

    def observe(event, data):
        if event == "step":
            label = {"optimize_schedule": "[4] SCHEDULEAGENT", "validate_schedule": "[5] VALIDATION  ",
                     "publish_to_mes": "[6] MES PUBLISH  "}.get(data["action"])
            if label:
                print(f"\n{label} {data['message']}")
        elif event == "review":
            print(f"      planner review ({', '.join(data['rules'])}): {'APPROVED' if data['approved'] else 'DECLINED'}")

    agent = WorkAgent("scheduler-agent", onto, tools, roles=["scheduler"], approver=approver, observer=observe)
    result = agent.run("replan_after_event", {"Replan": {"event_id": args.event}}, args.event)
    replan = result.state.entities["Replan"]
    print(f"\n=> {result.status.upper()}" + (f": {result.escalation.reason}" if result.escalation else ""))
    print(f"   makespan {replan['makespan']}h (baseline {replan['baseline_makespan']}h, change {replan['delay']:+}h), "
          f"{replan['jobs_delayed']} orders finish later, {replan['jobs_on_hold']} on hold, "
          f"{replan['warnings']} validation warnings ({replan['critical_warnings']} critical)")
    path = out / f"schedule-{args.event}.json"
    if path.exists():
        saved = json.loads(path.read_text())
        for w in saved["warnings"][:6]:
            print(f"   - {w['severity']:8} {w['check']}: {w['message']}")
        print(f"   Gantt: {out / ('schedule-' + args.event + '.html')}")
        sch = saved["schedule"]
        schedule = Schedule(sch["status"], sch["makespan"], {a["task"]: Assignment(**a) for a in sch["assignments"]},
                            sch["solver"])
        print("\n" + gantt_text(schedule, Problem({}, {}), width=64))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
