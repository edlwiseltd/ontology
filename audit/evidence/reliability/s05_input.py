"""Scenario 5: missing / wrong-typed / contradictory input data, and tool output of the wrong type."""
from common import *  # noqa
from autology import DeferredApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph, build_case

onto = Ontology.load(EX / "ontology.json")


def agent(tools=None):
    return WorkAgent("claims", onto, tools or load_tools(EX / "tools.json"),
                     roles=["fraud_analytics", "finance", "claims_handler"], approver=DeferredApprover())


def base():
    graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
    case, _ = build_case(graph, "claim_case", "CL-1")
    return case


def attempt(label, case):
    try:
        r = agent().run("settle_claim", case, "X")
        print(f"  {label}: status={r.status} path={r.path} esc={r.escalation and r.escalation.reason!r}")
        print(f"      Claim={r.state.entities['Claim']} Payment={r.state.entities['Payment']}")
        return r
    except Exception as exc:
        print(f"  {label}: raised {type(exc).__name__}: {exc}")


print("== 5 agent level ==")
c = base(); c["Unknown"] = {}; attempt("unknown entity", c)
c = base(); c["Claim"]["colour"] = "red"; attempt("unknown attribute", c)
c = base(); c["Claim"]["amount"] = "3200"; attempt("amount as string", c)
c = base(); c["Claim"]["status"] = "lost"; attempt("invalid state", c)
c = base(); c["Claim"].pop("amount"); c["Claim"]["amount"] = None; attempt("missing amount (None)", c)
c = base(); del c["Policy"]; attempt("no Policy in case at all", c)
c = base(); c["Policy"] = {"deductible": None, "coverage_limit": None}; attempt("Policy with unknown terms", c)
c = base(); c["Claim"]["status"] = "paid"; attempt("contradictory: Claim paid, Payment pending", c)
c = base(); c["Claim"].update(status="approved", approved_amount=None); attempt("contradictory: approved, no amount", c)
c = base(); c["Policy"]["status"] = "lapsed"; c["Claim"].update(status="approved", approved_amount=2700)
attempt("contradictory: lapsed policy but claim already approved", c)
c = base(); c["Claim"]["amount"] = -5000; attempt("negative amount", c)
c = base(); c["Claim"]["amount"] = float("nan"); attempt("NaN amount", c)

print("== 5 service level: graph claim with no policy link ==")
d = workdir("s05")
svc = service(server_config(d))
u = users(svc)
svc.upsert_object(u["admin"], {"type": "Claim", "id": "CL-9", "attributes": {"amount": 9000, "damage_type": "x",
                                                                           "reported_days_after": 1,
                                                                           "status": "reported"}})
try:
    out = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-9"})
    r = svc.store.load_run(out["run_id"])
    print("  CL-9 without Policy/Payment links:", out["status"], r.path, r.escalation and r.escalation.reason)
    print("    case Policy as the agent saw it:", r.state.entities["Policy"])
    print("    case Payment:", r.state.entities["Payment"])
    print("    graph CL-9:", svc.graph.get("CL-9").attributes)
except Exception as exc:
    print("  CL-9 raised", type(exc).__name__, exc)
for body in ({"type": "Claim", "id": "CL-10", "attributes": {"amount": "lots"}},
             {"type": "Claim", "id": "CL-11", "attributes": {"status": "whatever"}}):
    try:
        svc.upsert_object(u["admin"], body)
        print("  upsert accepted", body)
    except Exception as exc:
        print("  upsert rejected:", getattr(exc, "status", ""), getattr(exc, "message", exc))

print("== 5 tool output of the wrong type for a declared write ==")
d = workdir("s05b")
tp = tools_json(d / "tools.json", {"fraud_engine": {"name": "fraud_engine", "capability": "fraud.score", "type": "table",
                                                    "rows": [{"outcome": "clear",
                                                              "updates": {"Claim": {"fraud_score": "very low"}}}]}})
svc = service(server_config(d, tp))
u = users(svc)
out = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})
print("  run:", out["status"], "| graph CL-1.fraud_score =", repr(svc.graph.get("CL-1").attributes["fraud_score"]))
del svc
try:
    svc2 = service(d / "server.json")
    print("  restart OK; CL-1.fraud_score =", repr(svc2.graph.get("CL-1").attributes["fraud_score"]))
except Exception as exc:
    print("  RESTART FAILED:", type(exc).__name__, exc)

print("== 5 ingestion with bad rows (pipeline) ==")
d = workdir("s05c")
svc = service(server_config(d))
u = users(svc)
out = svc.ingest("claims_feed", "audit")
print("  ingest:", {k: out[k] for k in ("created", "updated", "rejected")})
for rj in svc.store.ingest_rejects(out["batch_id"]):
    print("   reject:", rj["source"], rj["row"], rj["reason"])
