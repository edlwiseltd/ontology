"""Scenario 10e: an automation firing whose run paid but whose save failed is retried -> second payment?"""
from common import *  # noqa

d = workdir("s10e")
rec = Recorder(lambda n, b: (200, {"message": "paid", "output": {"txn": f"TX-{n}"}}, 0, False))
tp = tools_json(d / "tools.json", {"payments": {"name": "payments", "capability": "payments.pay", "type": "http",
                                                "url": rec.url, "timeout": 5, "cost": 1}})
cfgp = server_config(d, tp, automations=True)
cfg = json.loads(cfgp.read_text())
cfg["pipelines"] = {}
cfgp.write_text(json.dumps(cfg))
svc = service(cfgp)
u = users(svc)
real = svc.store.save_run
fail = {"n": 1}


def flaky(*a, **k):
    if fail["n"]:
        fail["n"] -= 1
        raise RuntimeError("database is locked")
    return real(*a, **k)


svc.store.save_run = flaky
attrs = dict(svc.graph.get("CL-1").attributes)
out = svc.upsert_object(u["admin"], {"type": "Claim", "id": "CL-1", "attributes": attrs})  # fires settle_new_claims
print("  firing 1:", [(f["status"], f["detail"][:80]) for f in out.get("triggered", [])], "| payment calls:", len(rec.calls))
print("  runs stored:", [(r["case_id"], r["status"]) for r in svc.store.list_runs()])
print("  automation_state:", svc.store.automation_state("settle_new_claims", "CL-1"))
svc.automator.clock = lambda: time.time() + 400  # the retry window (300 s) has passed
t = svc.tick()
print("  tick firings:", [(f["instance"], f["trigger"], f["status"]) for f in t["firings"]], "| payment calls:", len(rec.calls))
print("  runs stored:", [(r["case_id"], r["status"]) for r in svc.store.list_runs()])
print("  CL-1 status:", svc.graph.get("CL-1").attributes["status"])
rec.stop()

print("== 10f deferred run: save fails after resume paid; next tick ==")
doc = json.loads((EX / "ontology.json").read_text())
doc["actions"]["pay_claim"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": 600}
d = workdir("s10f")
(d / "ontology.json").write_text(json.dumps(doc))
rec = Recorder(lambda n, b: (503, {}, 0, False) if n == 1 else (200, {"message": "paid"}, 0, False))
tp = tools_json(d / "tools.json", {"payments": {"name": "payments", "capability": "payments.pay", "type": "http",
                                                "url": rec.url, "timeout": 5, "cost": 1}})
svc = service(server_config(d, tp, d / "ontology.json", extra={"pipelines": {}}))
u = users(svc)
o = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})
print("  first:", o["status"], "| calls:", len(rec.calls))
svc.agents["claims"].agent.clock = lambda: time.time() + 10_000
real = svc.store.save_run
fail = {"n": 1}
svc.store.save_run = flaky
try:
    svc.tick()
except Exception as exc:
    print("  tick 1 raised:", type(exc).__name__, exc)
print("  calls:", len(rec.calls), "| stored status:", svc.store.load_run(o["run_id"]).status)
print("  tick 2:", svc.tick()["resumed"], "| calls:", len(rec.calls))
rec.stop()
