"""Scenario 14: audit chain verification after interruption and restart; key change; tampering while paused."""
import subprocess

from common import *  # noqa

d = workdir("s14")
p = server_config(d)
svc = service(p)
u = users(svc)
o1 = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-1"})
o2 = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
print("  runs:", o1["status"], o2["status"], "| verify:", svc.store.verify_audit(o1["run_id"]), svc.store.verify_audit(o2["run_id"]))
heads = svc.store.audit_heads()
svc.store.close()

code = f"""
import sys, json; sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})
from common import *
svc = service({str(p)!r}); u = users(svc)
print("verify after restart (key=%s):" % os.environ["AUTOLOGY_AUDIT_KEY"], [svc.store.verify_audit(r) for r in ({o1['run_id']!r}, {o2['run_id']!r})])
print("unverified_runs metric:", svc.unverified_runs())
rid = [x for x in svc.store.list_reviews() if x["run_id"] == {o2['run_id']!r}][0]["review_id"]
try:
    out = svc.decide(u["ivan"], rid, {{"approved": True}})
    r = svc.store.load_run({o2['run_id']!r})
    print("decide ->", out["status"], "| esc:", r.escalation and (r.escalation.reason, r.escalation.to))
except Exception as exc:
    print("decide ->", type(exc).__name__, getattr(exc, "status", ""), getattr(exc, "message", exc))
"""
import shutil
shutil.copy(d / "claims.db", d / "claims_copy.db")
c2 = json.loads(p.read_text()); c2["store"] = str(d / "claims_copy.db")
p2 = d / "server_copy.json"; p2.write_text(json.dumps(c2))
for key, cfgfile in (("other-key", p2), ("k", p)):
    env = dict(os.environ, PYTHONPATH=str(ROOT), AUTOLOGY_AUDIT_KEY=key)
    out = subprocess.run([sys.executable, "-c", code.replace(repr(str(p)), repr(str(cfgfile)))], env=env,
                         capture_output=True, text=True, cwd=str(ROOT))
    print(f"  [restart with key {key!r}]", out.stdout.strip().replace("\n", "\n     "), out.stderr.strip()[-300:])

print("== tampering with the stored run record while paused ==")


def tamper(label, edit):
    d = workdir("s14b")
    svc = service(server_config(d))
    u = users(svc)
    o = svc.start_run(u["hana"], {"case_template": "claim_case", "root": "CL-2"})
    row = svc.store._query("SELECT record FROM runs WHERE run_id=?", (o["run_id"],))[0]
    rec = json.loads(row["record"])
    edit(rec)
    svc.store._db.execute("UPDATE runs SET record=? WHERE run_id=?", (json.dumps(rec), o["run_id"]))
    rid = [x for x in svc.store.list_reviews() if x["run_id"] == o["run_id"]][0]["review_id"]
    try:
        out = svc.decide(u["ivan"], rid, {"approved": True})
        r = svc.store.load_run(o["run_id"])
        print(f"  {label}: decide ->", out["status"], "|", r.escalation and (r.escalation.reason, r.escalation.to),
              "| verify:", svc.store.verify_audit(o["run_id"]))
        for x in svc.store.list_reviews():
            if x["run_id"] == o["run_id"]:
                out = svc.decide(u["ivan"], x["review_id"], {"approved": True})
                r = svc.store.load_run(o["run_id"])
                print(f"     second review ({x['action']}) by ivan ->", out["status"], r.path,
                      "| reviewers on steps:", [(s.action, s.reviewer) for s in r.steps if s.reviewer])
    except Exception as exc:
        print(f"  {label}: decide ->", type(exc).__name__, getattr(exc, "status", ""), getattr(exc, "message", exc))


tamper("edit parked state (Claim.amount)", lambda rec: rec["state"]["entities"]["Claim"].update(amount=4000))
tamper("edit run.ontology_ref", lambda rec: rec["run"].update(ontology_ref="auto-insurance-claims@0.9"))
tamper("edit run.failures/attempts", lambda rec: rec["run"].update(failures={"pay_claim": 99}, attempts={}))
tamper("edit pending_review.action -> pay_claim", lambda rec: rec["run"]["pending_review"].update(action="pay_claim"))
