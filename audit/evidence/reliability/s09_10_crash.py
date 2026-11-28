"""Scenarios 9, 10, 14: process crash between an external call and persistence; restart and recovery."""
import signal
import subprocess

from common import *  # noqa

HERE = Path(__file__).resolve().parent
CHILD = [sys.executable, str(HERE / "child_service.py")]
ENV = dict(os.environ, PYTHONPATH=str(ROOT), AUTOLOGY_AUDIT_KEY="k")
current = {"proc": None, "kill_on_call": False}


def behaviour(n, body):
    if current["kill_on_call"] and current["proc"] is not None:
        # the bank has executed the transfer (call recorded); the Autology process dies before the reply
        current["proc"].send_signal(signal.SIGKILL)
        return 200, {"message": "paid", "output": {"txn": f"TX-{n}"}}, 0.2, False
    return 200, {"message": "paid", "output": {"txn": f"TX-{n}"}}, 0, False


def child(*args, kill_on_call=False):
    current["kill_on_call"] = kill_on_call
    p = subprocess.Popen(CHILD + [str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=ENV,
                         cwd=str(ROOT), text=True)
    current["proc"] = p
    out, err = p.communicate(timeout=60)
    current["proc"] = None
    lines = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return p.returncode, lines, err.strip().splitlines()[-1:] if err.strip() else []


def setup(name, ontology_doc=None, automations=False):
    d = workdir(name)
    rec = Recorder(behaviour)
    tp = tools_json(d / "tools.json", {"payments": {"name": "payments", "capability": "payments.pay", "type": "http",
                                                    "url": rec.url, "timeout": 5, "cost": 1}})
    op = None
    if ontology_doc:
        op = d / "ontology.json"
        op.write_text(json.dumps(ontology_doc))
    server_config(d, tp, op, automations=automations)
    return d, rec


def inspect(d, label):
    rc, lines, err = child("inspect", d)
    info = lines[-1] if lines else {"error": err}
    print(f"  [{label}] runs:", json.dumps(info.get("runs"), default=str))
    print(f"  [{label}] reviews:", info.get("reviews"))
    print(f"  [{label}] graph CL-1/PAY-1:", info.get("graph", {}).get("CL-1", {}).get("status"),
          info.get("graph", {}).get("PAY-1"))
    print(f"  [{label}] graph CL-2/PAY-2:", info.get("graph", {}).get("CL-2", {}).get("status"),
          info.get("graph", {}).get("PAY-2"))
    if info.get("automation_state"):
        print(f"  [{label}] automation_state:", info["automation_state"])
        print(f"  [{label}] firings:", info["firings"])
    return info


print("== 9a SIGKILL while the payment call is in flight (bank executed it), run started by a user ==")
d, rec = setup("s09a")
rc, lines, err = child("start", d, "CL-1", kill_on_call=True)
print("  child exit code:", rc, "| external calls:", len(rec.calls))
inspect(d, "after restart")
rc, lines, err = child("start", d, "CL-1")
print("  user retries the claim after restart ->", lines[-1]["out"]["status"] if lines else err,
      "| external calls now:", len(rec.calls), [c["body"]["attempt"] for c in rec.calls])
rec.stop()

print("== 9b crash right AFTER the http tool succeeded but BEFORE save_run ==")
d, rec = setup("s09b")
rc, lines, err = child("start", d, "CL-1", "crash_before_save")
print("  child exit code:", rc, "| child said:", lines, "| external calls:", len(rec.calls))
inspect(d, "after restart")
rc, lines, err = child("start", d, "CL-1")
print("  retry ->", lines[-1]["out"]["status"] if lines else err, "| external calls now:", len(rec.calls))
rec.stop()

print("== 10a review approved, crash while the (resumed) payment is in flight; restart; decide again ==")
d, rec = setup("s10a")
rc, lines, err = child("start", d, "CL-2")
run_id = lines[-1]["out"]["run_id"]
print("  started", run_id, lines[-1]["out"]["status"])
rc, lines, err = child("decide", d, run_id, "ivan", 1)
print("  SIU approve ->", lines[-1]["out"]["status"])
rc, lines, err = child("decide", d, run_id, "maria", 1, kill_on_call=True)
print("  manager approve, killed during payment: exit", rc, "| external calls:", len(rec.calls))
info = inspect(d, "after restart")
rc, lines, err = child("decide", d, run_id, "maria", 1)
print("  manager decides again after restart ->", lines[-1]["out"]["status"] if lines else err,
      "| external calls now:", len(rec.calls))
inspect(d, "final")
rec.stop()

print("== 10b review approved, save fails after the payment (in-process: StoreError path re-opens review) ==")
d, rec = setup("s10b")
svc = service(d / "server.json")
u = users(svc)
o = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
svc.decide(u["ivan"], rid, {"approved": True})
rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
real = svc.store.save_run
fail = {"n": 1}


def flaky(*a, **k):
    if fail["n"]:
        fail["n"] -= 1
        raise RuntimeError("database is locked")
    return real(*a, **k)


svc.store.save_run = flaky
try:
    svc.decide(u["maria"], rid, {"approved": True})
except Exception as exc:
    print("  first decide:", type(exc).__name__, getattr(exc, "status", ""), getattr(exc, "message", exc))
print("  external calls:", len(rec.calls), "| review status:", svc.store.get_review(rid)["status"],
      "| run status:", svc.store.load_run(o["run_id"]).status)
out = svc.decide(u["maria"], rid, {"approved": True})
print("  second decide ->", out["status"], "| external calls now:", len(rec.calls))
rec.stop()

print("== 10c deferred run resumed by the scheduler; crash in flight; restart; tick again ==")
doc = json.loads((EX / "ontology.json").read_text())
doc["actions"]["pay_claim"]["on_failure"] = {"max_attempts": 3, "backoff_seconds": 600}
d, rec = setup("s10c", doc)
rec.behaviour = lambda n, b: (503, {}, 0, False) if n == 1 else behaviour(n, b)
rc, lines, err = child("start", d, "CL-1")
run_id = lines[-1]["out"]["run_id"]
print("  first run:", lines[-1]["out"]["status"], "| calls:", len(rec.calls))
rc, lines, err = child("tick", d, kill_on_call=True)
print("  tick killed during payment: exit", rc, "| calls:", len(rec.calls))
inspect(d, "after restart")
rc, lines, err = child("tick", d)
print("  tick after restart ->", lines[-1]["out"]["resumed"] if lines else err, "| calls now:", len(rec.calls))
inspect(d, "final")
rec.stop()

print("== 10d automation-fired run killed during payment; restart; does the automation re-fire? ==")
d, rec = setup("s10d", automations=True)
rc, lines, err = child("upsert_reported", d, "CL-1",
                       json.dumps({"amount": 3200, "damage_type": "rear bumper", "reported_days_after": 2,
                                   "status": "reported"}), kill_on_call=True)
print("  admin upsert (fires automation) killed: exit", rc, "| calls:", len(rec.calls))
inspect(d, "after restart")
rc, lines, err = child("tick_plain", d)
print("  tick after restart ->", lines[-1]["out"] if lines else err, "| calls now:", len(rec.calls))
inspect(d, "final")
rec.stop()
