"""Scenarios 7 and 8: http payments tool unavailable / erroring / timing out after executing."""
from common import *  # noqa
from autology import DeferredApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph, build_case

onto = Ontology.load(EX / "ontology.json")
graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
case, _ = build_case(graph, "claim_case", "CL-1")
show("pay_claim on_failure policy", onto.actions["pay_claim"].on_failure)


def agent_with(url, timeout=1.0, onto_=onto):
    d = workdir("s07")
    p = tools_json(d / "tools.json", {"payments": {"name": "payments", "capability": "payments.pay", "type": "http",
                                                   "url": url, "timeout": timeout, "cost": 1}})
    return WorkAgent("claims", onto_, load_tools(p), roles=["fraud_analytics", "finance", "claims_handler"],
                     approver=DeferredApprover())


def run(label, behaviour, timeout=1.0, wait_after=0.0):
    rec = Recorder(behaviour)
    t0 = time.time()
    res = agent_with(rec.url, timeout).run("settle_claim", case, "CL-1")
    took = time.time() - t0
    time.sleep(wait_after)
    print(f"== {label} ==")
    show("run status", res.status)
    show("escalation", res.escalation and (res.escalation.reason, res.escalation.to))
    show("path", res.path)
    show("Claim.status / Payment", (res.state.entities["Claim"]["status"], res.state.entities["Payment"]))
    show("external calls received", len(rec.calls))
    show("attempt fields seen by server", [c["body"].get("attempt") for c in rec.calls])
    show("tool events", [(e.event, e.data.get("attempt"), e.data.get("error")) for e in res.audit
                         if e.event.startswith("tool.")])
    show("elapsed s", round(took, 2))
    rec.stop()
    return res, rec


# 7a connection refused
port = free_port()
res = agent_with(f"http://127.0.0.1:{port}/pay").run("settle_claim", case, "CL-1")
print("== 7a connection refused ==")
show("run status", res.status)
show("escalation", res.escalation and (res.escalation.reason, res.escalation.to))
show("tool events", [(e.event, e.data.get("attempt"), e.data.get("error")) for e in res.audit if e.event.startswith("tool.")])

run("7b HTTP 500 always", lambda n, b: (500, {"error": "boom"}, 0, False))
run("7c HTTP 503 then 200", lambda n, b: ((503, {}, 0, False) if n == 1 else (200, {"message": "paid"}, 0, False)))
run("7d HTTP 200 with empty JSON body {}", lambda n, b: (200, {}, 0, False))
run("7e HTTP 202 Accepted (queued, not executed)", lambda n, b: (202, {"message": "queued for processing"}, 0, False))
run("7f HTTP 200 non-JSON body", lambda n, b: (200, "OK", 0, False))
run("7g HTTP 200 outcome not in ontology", lambda n, b: (200, {"outcome": "failed", "message": "insufficient funds"}, 0, False))
run("7h HTTP 200 with 'status: failed' inside output (no outcome key)",
    lambda n, b: (200, {"output": {"status": "FAILED", "error": "account closed"}}, 0, False))
run("7i HTTP 200 body 'null'", lambda n, b: (200, "null", 0, False))

# 8: the bank executes the transfer and then replies after the client timeout
res, rec = run("8a timeout AFTER execution (server sleeps 2s, tool timeout 1s)",
               lambda n, b: (200, {"message": "paid", "output": {"txn": f"TX-{n}"}}, 2.0, False), timeout=1.0,
               wait_after=2.5)
print("  payload keys sent to external system:", sorted(rec.calls[0]["body"].keys()))
print("  headers sent:", sorted(rec.calls[0]["headers"].keys()))
print("  context keys:", sorted(rec.calls[0]["body"]["context"].keys()), "inputs:", rec.calls[0]["body"]["inputs"])
print("  any idempotency/run/case id in payload:", any(k in json.dumps(rec.calls[0]["body"]).lower()
                                                     for k in ("idempot", "run_id", "case_id", "request_id", "cl-1")))
print("  bodies identical except attempt:",
      all({k: v for k, v in c["body"].items() if k != "attempt"} == {k: v for k, v in rec.calls[0]["body"].items() if k != "attempt"} for c in rec.calls))

run("8b connection dropped after server executed (no reply)", lambda n, b: (200, {}, 0, True))

# 8c: with max_attempts = 1 (no retry), what is reported?
doc = json.loads((EX / "ontology.json").read_text())
doc["actions"]["pay_claim"]["on_failure"] = {"max_attempts": 1}
p = workdir("s08c") / "ontology.json"
p.write_text(json.dumps(doc))
onto1 = Ontology.load(p)
rec = Recorder(lambda n, b: (200, {"message": "paid"}, 2.0, False))
res = agent_with(rec.url, 1.0, onto1).run("settle_claim", case, "CL-1")
time.sleep(2.2)
print("== 8c timeout after execution, max_attempts=1 ==")
show("run status", res.status)
show("escalation", res.escalation and (res.escalation.reason, res.escalation.to))
show("external calls", len(rec.calls))
show("Payment state in run", res.state.entities["Payment"])
show("step message", [(s.action, s.outcome, s.message) for s in res.steps])
rec.stop()

# 8d: large backoff -> deferred, then resume: repeats the call
doc["actions"]["pay_claim"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": 600}
p2 = workdir("s08d") / "ontology.json"
p2.write_text(json.dumps(doc))
onto2 = Ontology.load(p2)
rec = Recorder(lambda n, b: (200, {"message": "paid"}, 2.0, False) if n == 1 else (200, {"message": "paid"}, 0, False))
ag = agent_with(rec.url, 1.0, onto2)
res = ag.run("settle_claim", case, "CL-1")
print("== 8d timeout after execution, backoff 600s -> deferred, then resume(force) ==")
show("first status", (res.status, res.escalation and res.escalation.reason, res.resume_at is not None))
time.sleep(2.2)
res2 = ag.resume(res, force=True)
show("after resume", (res2.status, res2.path))
show("external calls (duplicates?)", len(rec.calls))
rec.stop()
