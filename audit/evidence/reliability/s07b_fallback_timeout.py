"""Scenario 7/8 follow-ups: fallback tool after an ambiguous timeout; timeout is per socket read, not a deadline;
tool output validation against declared writes."""
import socket

from common import *  # noqa
from autology import DeferredApprover, Ontology, WorkAgent
from autology.adapters import load_tools
from autology.graph import KnowledgeGraph, build_case

onto = Ontology.load(EX / "ontology.json")
graph = KnowledgeGraph.from_dict(onto, json.loads((EX / "data.json").read_text()))
case, _ = build_case(graph, "claim_case", "CL-1")


def agent(tool_specs, onto_=onto):
    d = workdir("s07b")
    p = tools_json(d / "tools.json", tool_specs)
    return WorkAgent("claims", onto_, load_tools(p), roles=["fraud_analytics", "finance", "claims_handler"],
                     approver=DeferredApprover())


print("== fallback payment provider after the primary timed out (primary had executed) ==")
bank_a = Recorder(lambda n, b: (200, {"message": "paid by A"}, 2.0, False))
bank_b = Recorder(lambda n, b: (200, {"message": "paid by B"}, 0, False))
ag = agent({"payments": {"name": "bank_a", "capability": "payments.pay", "type": "http", "url": bank_a.url,
                         "timeout": 1, "priority": 2},
            "bank_b": {"name": "bank_b", "capability": "payments.pay", "type": "http", "url": bank_b.url,
                       "timeout": 1, "priority": 1}})
r = ag.run("settle_claim", case, "CL-1")
time.sleep(2.2)
print("  status:", r.status, "| path:", r.path, "| step tool:", [(s.action, s.tool, s.message) for s in r.steps][-1])
print("  bank A calls:", len(bank_a.calls), "| bank B calls:", len(bank_b.calls))
print("  tool events:", [(e.event, e.data.get("tool"), e.data.get("attempt")) for e in r.audit if e.event.startswith("tool.") and e.data.get("action") == "pay_claim"])

print("== fallback_after=1: primary retried once before the fallback ==")
doc = json.loads((EX / "ontology.json").read_text())
doc["actions"]["pay_claim"]["on_failure"] = {"max_attempts": 3, "fallback_after": 1}
op = workdir("s07c") / "ontology.json"
op.write_text(json.dumps(doc))
bank_a.calls.clear(); bank_b.calls.clear()
ag = agent({"payments": {"name": "bank_a", "capability": "payments.pay", "type": "http", "url": bank_a.url,
                         "timeout": 1, "priority": 2},
            "bank_b": {"name": "bank_b", "capability": "payments.pay", "type": "http", "url": bank_b.url,
                       "timeout": 1, "priority": 1}}, Ontology.load(op))
r = ag.run("settle_claim", case, "CL-1")
time.sleep(2.2)
print("  status:", r.status, "| bank A calls:", len(bank_a.calls), "| bank B calls:", len(bank_b.calls))
bank_a.stop(); bank_b.stop()

print("== timeout is per socket operation: a server trickling its reply ==")
srv = socket.socket()
srv.bind(("127.0.0.1", 0)); srv.listen(5)
port = srv.getsockname()[1]


def trickle():
    conn, _ = srv.accept()
    conn.recv(65536)
    body = b'{"message": "paid"}' + b" " * 12
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(body))
    for ch in body:
        conn.sendall(bytes([ch]))
        time.sleep(0.25)
    conn.close()


threading.Thread(target=trickle, daemon=True).start()
from autology.adapters import http_tool
from autology.tools import ToolCall
h = http_tool(f"http://127.0.0.1:{port}/pay", timeout=1.0)
t0 = time.time()
try:
    res = h(ToolCall("pay_claim", "payments.pay", {}, {}, 1))
    print("  result:", res.message, "| configured timeout 1.0 s, elapsed", round(time.time() - t0, 2), "s")
except Exception as exc:
    print("  raised", exc, round(time.time() - t0, 2))

print("== tool output validation ==")
for label, updates in (("undeclared field", {"Payment": {"amount": 999999}}),
                       ("status via updates", {"Claim": {"status": "paid"}}),
                       ("declared field, wrong type", {"Payment": {"reference": 12345}}),
                       ("declared field, nested object", {"Payment": {"reference": {"$set": "x"}}})):
    rec = Recorder(lambda n, b, u=updates: (200, {"updates": u, "message": "ok"}, 0, False))
    r = agent({"payments": {"name": "payments", "capability": "payments.pay", "type": "http", "url": rec.url}}).run(
        "settle_claim", case, "CL-1")
    print(f"  {label}: {r.status} | {r.escalation and r.escalation.reason} | Payment={r.state.entities['Payment']}")
    rec.stop()
