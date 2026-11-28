"""Scenarios 1-3: automated run, approved review, declined review (auto_insurance, via AutologyService)."""
from common import *  # noqa

d = workdir("s01")
svc = service(server_config(d))
u = users(svc)

print("== S1 fully automated CL-1 ==")
out = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})
show("status", out["status"])
r = svc.store.load_run(out["run_id"])
show("path", r.path)
show("graph CL-1", svc.graph.get("CL-1").attributes)
show("graph PAY-1", svc.graph.get("PAY-1").attributes)
show("verify_audit", svc.store.verify_audit(out["run_id"]))
print("  audit events:", [e.event for e in r.audit])

print("== S2 review approved CL-2 ==")
out2 = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
show("status", out2["status"])
show("pending_review", out2.get("pending_review"))
rev = svc.store.list_reviews()
show("pending reviews", [(x["review_id"], x["action"], x["reviewers"]) for x in rev])
rid = [x for x in rev if x["run_id"] == out2["run_id"]][0]["review_id"]
done = svc.decide(u["ivan"], rid, {"approved": True, "comment": "looked at photos"})
show("after approve", done["status"])
r2 = svc.store.load_run(out2["run_id"])
show("path", r2.path)
show("escalation", r2.escalation)
show("graph CL-2", svc.graph.get("CL-2").attributes)
show("graph PAY-2", svc.graph.get("PAY-2").attributes)
show("verify_audit", svc.store.verify_audit(out2["run_id"]))
pend = svc.store.list_reviews()
show("pending reviews now", [(x["review_id"], x["action"], x["reviewers"]) for x in pend])
# CL-2 payout = 48000-1000 capped 40000 = 40000 >= 20000 -> claims_manager review of pay_claim
for x in pend:
    if x["run_id"] == out2["run_id"]:
        done2 = svc.decide(u["maria"], x["review_id"], {"approved": True, "comment": "ok"})
        show("after 2nd approve", done2["status"])
        r2 = svc.store.load_run(out2["run_id"])
        show("path", r2.path)
        show("graph CL-2", svc.graph.get("CL-2").attributes)
        show("graph PAY-2", svc.graph.get("PAY-2").attributes)

print("== S3 review declined (CL-3 fraud -> reject_claim needs SIU) ==")
out3 = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-3"})
show("status", out3["status"])
r3 = svc.store.load_run(out3["run_id"])
show("pending action", r3.run.pending_review["action"])
rid3 = [x for x in svc.store.list_reviews() if x["run_id"] == out3["run_id"]][0]["review_id"]
dec = svc.decide(u["ivan"], rid3, {"approved": False, "comment": "need more evidence"})
show("after decline", dec["status"])
r3 = svc.store.load_run(out3["run_id"])
show("escalation", r3.escalation)
show("graph CL-3", svc.graph.get("CL-3").attributes)
print("  audit tail:", [e.event for e in r3.audit][-5:])
try:
    svc.resume_run(u["admin"], out3["run_id"], force=True)
except Exception as exc:
    show("resume blocked run", f"{type(exc).__name__}: {getattr(exc, 'status', '')} {getattr(exc, 'message', exc)}")
show("open reviews for CL-3 run", [x for x in svc.store.list_reviews() if x["run_id"] == out3["run_id"]])
# a fresh run on the same claim after a decline
out3b = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-3"})
show("new run on CL-3 after decline", (out3b["status"], svc.store.load_run(out3b["run_id"]).path))

print("== S3b decline on CL-2-like approve: does the agent replan to reject? ==")
d2 = workdir("s03b")
svc2 = service(server_config(d2))
u2 = users(svc2)
o = svc2.start_run(u2["hana"], {"case_template": "claim_case", "root": "CL-2"})
rid = [x for x in svc2.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
dd = svc2.decide(u2["ivan"], rid, {"approved": False, "comment": "suspicious"})
rr = svc2.store.load_run(o["run_id"])
show("status after decline of approve_claim", dd["status"])
show("escalation", rr.escalation)
show("graph CL-2 status", svc2.graph.get("CL-2").attributes["status"])
show("pending reviews", svc2.store.list_reviews())
