"""PoC 1: a user with run+review fires an automation by hand and approves the review of the run it started.
Also: run_now(instance) ignores the automation's `when` condition."""
from harness import *  # noqa

RITA = {"name": "rita", "token_env": "AUTOLOGY_TOKEN_RITA", "permissions": ["read", "run", "review"],
        "roles": ["ops", "eu_ops"], "reviewer_roles": ["logistics_manager"]}
svc = service([RITA])
add_big_order(svc)  # K-2 (no status -> draft?) covers O-4 amount 85000 -> needs logistics_manager review
rita = user(svc, "rita")
print("K-2 status:", svc.graph.get("K-2").attributes.get("status"))
print("automation when:", svc.automations["fulfil_signed_contracts"].when)

# 1) control: rita starts the run herself -> self-review refused
st, run = call(svc.start_run, rita, {"case_template": "contract_case", "root": "K-2", "write_back": False})
print("direct start:", st, run.get("status"), run.get("pending_review"))
rv = [r for r in svc.store.list_reviews("pending") if r["run_id"] == run["run_id"]][0]
print("direct self-decide:", call(svc.decide, rita, rv["review_id"], {"approved": True}))

# 2) attack: rita fires the automation by hand on K-2 (condition Contract.status=='signed' does NOT hold)
st, out = call(svc.run_automation, rita, "fulfil_signed_contracts", {"instance": "K-2"})
print("run_automation:", st, out)
run_id = out["firings"][0]["run_id"]
print("run started_by:", svc.store.run_starter(run_id))
rv = [r for r in svc.store.list_reviews("pending") if r["run_id"] == run_id][0]
st, res = call(svc.decide, rita, rv["review_id"], {"approved": True, "comment": "lgtm"})
print("self-decide via automation:", st, res.get("status"))
print("steps:", [(s["action"], s["outcome"], s["reviewer"]) for s in res["steps"]])
print("access log of rita:", [(e["target"], e["status"]) for e in svc.store.access_log("rita")])
