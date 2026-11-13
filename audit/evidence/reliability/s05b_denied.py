"""Scenario 5 follow-up: 'planned step denied' on contradictory data; repeated bad cases -> agent suspension?"""
from common import *  # noqa
from autology import AutoApprover, DeferredApprover, Ontology, ReviewDecision, WorkAgent
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph, build_case

onto = Ontology.load(EX / "ontology.json")
graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
case, _ = build_case(graph, "claim_case", "CL-1")
case["Claim"].update(status="approved", approved_amount=None)
ag = WorkAgent("claims", onto, load_tools(EX / "tools.json"), roles=["fraud_analytics", "finance", "claims_handler"],
               approver=DeferredApprover())
for i in range(4):
    r = ag.run("settle_claim", case, f"bad-{i}")
    denies = [e.data for e in r.audit if e.event == "governance.deny"]
    print(f"  run {i}: {r.status} esc={r.escalation and (r.escalation.reason, r.escalation.to, r.escalation.details)}")
    print(f"     denies: {[(x['action'], x['reasons'], x.get('suspended')) for x in denies]}")
print("  agent suspended:", ag.governance.suspended)
ok = WorkAgent  # a good claim on the same (now possibly suspended) agent
case2, _ = build_case(graph, "claim_case", "CL-1")
r = ag.run("settle_claim", case2, "good")
print("  good claim afterwards on same agent:", r.status, r.escalation and r.escalation.reason)

print("== missing policy: approve then manager approves payment of None ==")
case3, _ = build_case(graph, "claim_case", "CL-1")
del case3["Policy"]
ag2 = WorkAgent("claims", onto, load_tools(EX / "tools.json"), roles=["fraud_analytics", "finance", "claims_handler"],
                approver=DeferredApprover())
r = ag2.run("settle_claim", case3, "nopolicy")
print("  ", r.status, r.escalation.reason, r.escalation.details)
r2 = ag2.resume(r, decision=ReviewDecision(True, "maria", "ok"))
print("   after approval:", r2.status, r2.path, r2.state.entities["Payment"], r2.state.entities["Claim"]["approved_amount"])
