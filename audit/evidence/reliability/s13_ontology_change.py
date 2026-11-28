"""Scenario 13: business rule / ontology change while a run is paused awaiting review (service restart)."""
from common import *  # noqa
from autology.ontology import Ontology


def setup(name):
    d = workdir(name)
    p = server_config(d)
    svc = service(p)
    u = users(svc)
    o = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
    rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
    svc.decide(u["ivan"], rid, {"approved": True})  # now awaiting the manager's review of pay_claim (40,000)
    rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
    print("  run", o["run_id"], svc.store.load_run(o["run_id"]).status, "pending review", rid)
    svc.store.close()
    return d, o["run_id"], rid


def restart(d, mutate):
    doc = json.loads((EX / "ontology.json").read_text())
    mutate(doc)
    op = d / "ontology_v2.json"
    op.write_text(json.dumps(doc))
    cfg = json.loads((d / "server.json").read_text())
    cfg["ontology"] = str(op)
    (d / "server.json").write_text(json.dumps(cfg))
    svc = service(d / "server.json")
    print("  restarted on", svc.ontology.ref, svc.ontology.fingerprint[:12])
    return svc


def decide(svc, run_id, rid, approved=True):
    u = users(svc)
    try:
        out = svc.decide(u["maria"], rid, {"approved": approved, "comment": "ok"})
        print("  decide ->", out["status"])
    except Exception as exc:
        print("  decide ->", type(exc).__name__, getattr(exc, "status", ""), getattr(exc, "message", exc))
    r = svc.store.load_run(run_id)
    starts = [e.data for e in r.audit if e.event == "run.start"]
    print("  run status:", r.status, "| path:", r.path, "| esc:", r.escalation and r.escalation.reason)
    print("  run.ontology_ref:", r.run.ontology_ref, "| run.start fingerprint:", starts[0]["fingerprint"][:12],
          "| any later fingerprint entry:", [e.event for e in r.audit if "fingerprint" in e.data][1:])
    print("  resume entries:", [e.data for e in r.audit if e.event == "run.resume"][-1:])
    print("  review status:", svc.store.get_review(rid)["status"], "| verify_audit:", svc.store.verify_audit(run_id))
    print("  runs table ontology column:", [x["ontology"] for x in svc.store.list_runs() if x["run_id"] == run_id])
    return r


print("== 13a same version 1.0.0, new prohibition: never pay claims over 30,000 ==")
d, run_id, rid = setup("s13a")
svc = restart(d, lambda doc: doc["rules"].append(
    {"id": "R-CAP", "type": "prohibition", "action": "pay_claim", "when": "Claim.amount > 30000",
     "description": "New policy: claims over 30,000 go to the courts"}))
decide(svc, run_id, rid)
svc.store.close()

print("== 13b same version 1.0.0, review rule removed (R-HIGH-PAYOUT threshold raised to 100,000) ==")
d, run_id, rid = setup("s13b")


def raise_threshold(doc):
    for r in doc["rules"]:
        if r["id"] == "R-HIGH-PAYOUT":
            r["when"] = "Claim.payout >= 100000"


svc = restart(d, raise_threshold)
decide(svc, run_id, rid)
svc.store.close()

print("== 13c version bumped to 1.1.0 (no rule change) ==")
d, run_id, rid = setup("s13c")
svc = restart(d, lambda doc: doc.update(version="1.1.0"))
decide(svc, run_id, rid, approved=True)
decide(svc, run_id, rid, approved=False)
print("  pending reviews:", [(x["review_id"], x["status"]) for x in svc.store.list_reviews()])
u = users(svc)
try:
    svc.resume_run(u["admin"], run_id, force=True)
except Exception as exc:
    print("  admin resume ->", getattr(exc, "status", ""), getattr(exc, "message", exc))
svc.store.close()
