"""Scenario 8e: a python tool that executed and then raised a non-ToolError (the only 'may have acted' path)."""
from common import *  # noqa
from autology import DeferredApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph, build_case
from autology.reporting import classify

onto = Ontology.load(EX / "ontology.json")
graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
case, _ = build_case(graph, "claim_case", "CL-1")
tools = load_tools(EX / "tools.json")
ledger = []


def pay(call):
    ledger.append(call.attempt)
    raise TimeoutError("read timed out after the bank accepted the transfer")


tools.register("py_bank", "payments.pay", pay, priority=99)
ag = WorkAgent("claims", onto, tools, roles=["fraud_analytics", "finance", "claims_handler"], approver=DeferredApprover())
r = ag.run("settle_claim", case, "CL-1")
print("  status:", r.status, "| to:", r.escalation.to, "| reason:", r.escalation.reason)
print("  bank calls:", len(ledger), "| Payment state:", r.state.entities["Payment"], "| Claim:", r.state.entities["Claim"]["status"])
print("  classify:", classify(r))
try:
    ag.resume(r, force=True)
except Exception as exc:
    print("  resume:", type(exc).__name__, exc)
r2 = ag.run("settle_claim", {"Claim": dict(r.state.entities["Claim"]), "Policy": case["Policy"], "Payment": dict(r.state.entities["Payment"])}, "CL-1")
print("  operator restarts from the recorded state ->", r2.status, "| bank calls:", len(ledger))
