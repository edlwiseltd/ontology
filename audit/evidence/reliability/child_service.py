"""A service process used by s09/s10 (crash / restart). argv: mode workdir [args...]. Prints JSON lines."""
import sys

from common import *  # noqa

mode, d = sys.argv[1], Path(sys.argv[2])
cfg_path = d / "server.json"
svc = service(cfg_path)
u = users(svc)


def emit(**kw):
    print(json.dumps(kw, default=str), flush=True)


def crash_before_save():
    def boom(*a, **k):
        emit(event="crash", where="save_run")
        os._exit(137)
    svc.store.save_run = boom


if mode == "start":  # start a run on a claim, args: root [crash_before_save]
    if len(sys.argv) > 4 and sys.argv[4] == "crash_before_save":
        crash_before_save()
    out = svc.start_run(u["hana"], {"case_template": "claim_case", "root": sys.argv[3]})
    emit(event="started", out=out)
elif mode == "decide":  # args: run_id approver approved
    run_id, who = sys.argv[3], sys.argv[4]
    rid = [x for x in svc.store.list_reviews() if x["run_id"] == run_id][0]["review_id"]
    out = svc.decide(u[who], rid, {"approved": sys.argv[5] == "1", "comment": "ok"})
    emit(event="decided", out=out)
elif mode == "tick":  # resume deferred runs as if the retry window had passed
    for cfg in svc.agents.values():
        cfg.agent.clock = lambda: time.time() + 10_000
    if len(sys.argv) > 3 and sys.argv[3] == "crash_before_save":
        crash_before_save()
    emit(event="tick", out=svc.tick())
elif mode == "inspect":
    runs = svc.store.list_runs(limit=1000)
    emit(event="inspect",
         runs=[{"run_id": r["run_id"], "case": r["case_id"], "status": r["status"], "agent": r["agent"],
                "verified": svc.store.verify_audit(r["run_id"]),
                "events": [e.event for e in svc.store.audit_log(r["run_id"])]} for r in runs],
         reviews=[(x["review_id"], x["run_id"], x["action"], x["status"]) for x in svc.store.list_reviews(None)],
         graph={i: svc.graph.get(i).attributes for i in ("CL-1", "PAY-1", "CL-2", "PAY-2")},
         automation_state=[dict(r) for r in svc.store._query("SELECT * FROM automation_state")],
         firings=[(f["automation"], f["instance"], f["status"], f["run_id"]) for f in svc.store.list_firings()],
         notifications=[(n["kind"], n["message"]) for n in svc.store.list_notifications()])
elif mode == "upsert_reported":  # admin re-reports a claim (simulates an update that re-arms automations)
    out = svc.upsert_object(u["admin"], {"type": "Claim", "id": sys.argv[3],
                                         "attributes": json.loads(sys.argv[4])})
    emit(event="upsert", out=out)
elif mode == "tick_plain":
    emit(event="tick", out=svc.tick())
