"""Scenario 11: concurrent modification of the same business record."""
from common import *  # noqa

slow = {"delay": 1.0}


def setup(name, extra_pipeline=False):
    d = workdir(name)
    rec = Recorder(lambda n, b: (200, {"message": "paid", "output": {"txn": f"TX-{n}"}}, slow["delay"], False))
    tp = tools_json(d / "tools.json", {"payments": {"name": "payments", "capability": "payments.pay", "type": "http",
                                                    "url": rec.url, "timeout": 10, "cost": 1}})
    extra = None
    if extra_pipeline:
        pipe = {"name": "claim_updates", "sources": {"claims": {"type": "push"}},
                "mappings": [{"source": "claims", "entity": "Claim", "id": "id",
                              "attributes": {"amount": "amount", "status": "status"}}]}
        (d / "claim_updates.json").write_text(json.dumps(pipe))
        extra = {"pipelines": {"claim_updates": str(d / "claim_updates.json")}}
    cfgp = server_config(d, tp, extra=extra)
    return d, rec, service(cfgp)


print("== 11a two runs on the same claim started concurrently ==")
d, rec, svc = setup("s11a")
u = users(svc)
outs = []


def go():
    outs.append(svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"}))


ts = [threading.Thread(target=go) for _ in range(2)]
for t in ts:
    t.start()
    time.sleep(0.2)
for t in ts:
    t.join()
print("  statuses:", [o["status"] for o in outs])
print("  external payment calls:", len(rec.calls))
for o in outs:
    src = svc.store.run_sources(o["run_id"])
    print("  run", o["run_id"], "path", svc.store.load_run(o["run_id"]).path, "conflicts:", src["conflicts"])
print("  graph CL-1:", svc.graph.get("CL-1").attributes["status"], "PAY-1:", svc.graph.get("PAY-1").attributes)
print("  conflict notifications:", [n["message"] for n in svc.store.list_notifications() if n["kind"] == "conflict"])

print("== 11b admin changes the claim while its run awaits review; reviewer approves ==")
slow["delay"] = 0
d, rec, svc = setup("s11b")
u = users(svc)
o = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
print("  run", o["status"])
cur = dict(svc.graph.get("CL-2").attributes)
cur.update(status="rejected", amount=1000)  # the claim was withdrawn / rejected by another channel meanwhile
svc.upsert_object(u["admin"], {"type": "Claim", "id": "CL-2", "attributes": cur})
print("  live CL-2 now:", {k: svc.graph.get("CL-2").attributes[k] for k in ("status", "amount")})
rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]
print("  reviewer sees amount:", rid["request"]["view"]["Claim"]["amount"], "status:", rid["request"]["view"]["Claim"]["status"])
out = svc.decide(u["ivan"], rid["review_id"], {"approved": True})
print("  after SIU approve:", out["status"])
for x in svc.store.list_reviews():
    if x["run_id"] == o["run_id"]:
        out = svc.decide(u["maria"], x["review_id"], {"approved": True})
        print("  after manager approve:", out["status"])
r = svc.store.load_run(o["run_id"])
print("  path:", r.path, "| payment calls:", len(rec.calls),
      "| amount sent to bank (context):", rec.calls[-1]["body"]["context"]["Claim"]["amount"] if rec.calls else None)
print("  live CL-2:", {k: svc.graph.get("CL-2").attributes[k] for k in ("status", "amount", "approved_amount")})
print("  live PAY-2:", svc.graph.get("PAY-2").attributes)
print("  write-back conflicts:", svc.store.run_sources(o["run_id"])["conflicts"])
print("  conflict notifications:", [n["message"] for n in svc.store.list_notifications() if n["kind"] == "conflict"])

print("== 11c ingestion updates the claim amount while the run awaits review ==")
d, rec, svc = setup("s11c", extra_pipeline=True)
u = users(svc)
o = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
ing = svc.ingest("claim_updates", "etl", pushed={"claims": [{"id": "CL-2", "amount": "5000", "status": "assessed"}]})
print("  ingest:", {k: ing.get(k) for k in ("created", "updated", "rejected")})
print("  live CL-2 after ingest:", {k: svc.graph.get("CL-2").attributes[k] for k in ("status", "amount")})
rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
out = svc.decide(u["ivan"], rid, {"approved": True})
print("  after SIU approve:", out["status"])
for x in svc.store.list_reviews():
    if x["run_id"] == o["run_id"]:
        out = svc.decide(u["maria"], x["review_id"], {"approved": True})
        print("  after manager approve:", out["status"])
print("  payment calls:", len(rec.calls), "| live CL-2:",
      {k: svc.graph.get("CL-2").attributes[k] for k in ("status", "amount", "approved_amount")},
      "| PAY-2:", svc.graph.get("PAY-2").attributes)
print("  conflicts:", svc.store.run_sources(o["run_id"])["conflicts"])
