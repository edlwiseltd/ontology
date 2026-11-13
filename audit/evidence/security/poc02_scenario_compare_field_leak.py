"""PoC 2: competency questions over a data_access-hidden field: /questions refuses (403), but a scenario
comparison answers every question without the field check, so any 'read'+'run' user gets the value."""
import json, tempfile
from pathlib import Path
from harness import *  # noqa

onto = json.loads((EX / "ontology.json").read_text())
onto["competency_questions"] += [
    {"id": "CQ-X1", "question": "Total credit limit of all customers", "find": "Customer",
     "aggregate": {"sum": "Customer.credit_limit"}},
    {"id": "CQ-X2", "question": "Customers with a credit limit above 200k", "find": "Customer",
     "where": "Customer.credit_limit > 200000"},
]
p = Path(tempfile.mkdtemp()) / "ontology.json"
p.write_text(json.dumps(onto))
svc = service(ontology=str(p))
olivia = user(svc, "olivia")  # read+run, roles ops (no finance: Customer.credit_limit is hidden by R-FIN-001)
print("get_object C-1 credit_limit:", svc.get_object(olivia, "C-1")["attributes"]["credit_limit"])
print("answer CQ-X1:", call(svc.answer, olivia, "CQ-X1", {}))
print("answer CQ-X2:", call(svc.answer, olivia, "CQ-X2", {}))
# attack: an empty scenario, then compare
sc = svc.create_scenario(olivia, {"name": "probe", "edits": []})
rep = svc.compare_scenario(olivia, sc["scenario_id"], {"checks": []})
for q in rep["questions"]:
    if q["id"].startswith("CQ-X"):
        print("compare", q["id"], "baseline=", q["baseline"])
# binary search the exact credit limit of C-1 via set-edits on another visible field? not needed: the
# scenario 'set' op even lets olivia rewrite the hidden field and watch the aggregate move:
sc2 = svc.create_scenario(olivia, {"name": "probe2", "edits": [
    {"op": "set", "id": "C-1", "attributes": {"credit_limit": 0}}]})
rep2 = svc.compare_scenario(olivia, sc2["scenario_id"], {"checks": []})
q = next(q for q in rep2["questions"] if q["id"] == "CQ-X1")
print("C-1.credit_limit = baseline - scenario =", q["baseline"] - q["scenario"])
