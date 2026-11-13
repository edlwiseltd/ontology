from tests.test_platform import service
svc = service(automations={}, chat=None)
u = {x.name: x for x in svc.users}
olivia = u["olivia"]
print("olivia roles:", sorted(olivia.roles))
o3 = svc.graph.get("O-3"); print("O-3 region:", o3.attributes.get("region"), "visible to olivia:", svc.visible(o3, olivia))
out = svc.start_run(olivia, {"case_template": "contract_case", "root": "K-1"})
print("run status:", out["status"], "keys:", sorted(out)[:8])
res = svc.store.load_run(out["run_id"])
print("steps on O-3:", [(s.action, s.outcome) for s in res.steps if "O-3" in s.action])
