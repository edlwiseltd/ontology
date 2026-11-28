"""Scenario 11d: two reviewers decide the same review concurrently; blocked run notification."""
from common import *  # noqa
d = workdir("s11d")
svc = service(server_config(d))
u = users(svc)
o = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
res = []
def go(approved):
    try:
        res.append(("ok", approved, svc.decide(u["ivan"] if approved else u["admin"], rid, {"approved": approved})["status"]))
    except Exception as exc:
        res.append(("err", approved, getattr(exc, "status", ""), getattr(exc, "message", str(exc))))
ts = [threading.Thread(target=go, args=(a,)) for a in (True, False)]
[t.start() for t in ts]; [t.join() for t in ts]
print("  results:", res)
r = svc.store.load_run(o["run_id"])
print("  run:", r.status, "| review.decision entries:", len([e for e in r.audit if e.event == "review.decision"]),
      "| review row:", svc.store.get_review(rid)["status"])
print("  notifications for claims_manager:", [n["message"] for n in svc.store.list_notifications(roles=["claims_manager"])])
o3 = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-3"})
rid3 = [x for x in svc.store.list_reviews() if x["run_id"] == o3["run_id"]][0]["review_id"]
svc.decide(u["ivan"], rid3, {"approved": False})
print("  notifications after a decline (all):", [(n["kind"], n["roles"], n["message"][:70]) for n in svc.store.list_notifications()][:3])
print("  conflict notification visibility for a reviewer: list_notifications(maria):",
      [n["kind"] for n in svc.list_notifications(u["maria"], None, 100)["items"]])
