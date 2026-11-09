"""Generate the plant knowledge graph (seeded, reproducible): python examples/scheduling/make_data.py

40 work orders / ~100 operations for 12 structural parts, 12 machines, 6 molds, 10 operators,
2 material lots, an engineering change (ECN-7 on 4 parts) and a quality return (QR-1).
Events: ECN-7, ECN-8, QR-1, QR-2 and a breakdown alert for every machine (ALERT-01 .. ALERT-12).
Standing conditions: mold M-06 is in maintenance, operator OP_07 is absent, EQ_12 calibration expires
mid-horizon, mold M-04 is near end of life.
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPS = {"cut": ["EQ_01", "EQ_02", "EQ_03", "EQ_04"], "mill": ["EQ_05", "EQ_06", "EQ_07", "EQ_08"],
       "form": ["EQ_09", "EQ_10"], "heat": ["EQ_11"], "inspect": ["EQ_12"]}
SKILL = {"cut": "cnc", "mill": "cnc", "form": "press", "heat": "heat", "inspect": "cmm"}
PARTS = [("PT-01", "wing rib", ["cut", "mill", "inspect"]), ("PT-02", "spar fitting", ["cut", "mill", "heat"]),
         ("PT-03", "bracket", ["cut", "form"]), ("PT-04", "frame clip", ["form", "heat", "inspect"]),
         ("PT-05", "stringer", ["cut", "mill"]), ("PT-06", "bulkhead web", ["cut", "form", "inspect"]),
         ("PT-07", "hinge", ["mill", "heat", "inspect"]), ("PT-08", "doubler", ["cut", "form"]),
         ("PT-09", "cleat", ["cut", "mill"]), ("PT-10", "skin panel", ["form", "inspect"]),
         ("PT-11", "lug", ["cut", "mill", "heat"]), ("PT-12", "longeron", ["cut", "mill"])]
MOLD_OF = {"PT-03": "M-01", "PT-04": "M-02", "PT-06": "M-03", "PT-08": "M-04", "PT-10": "M-05"}


def generate(seed: int = 3):
    rng = random.Random(seed)
    inst, links = [], []
    for kind, machines in OPS.items():
        for m in machines:
            inst.append({"type": "Machine", "id": m, "kind": kind, "calibration_due_h": 999,
                         "status": "available"})
    inst[-1]["calibration_due_h"] = 60  # EQ_12 (CMM): calibration expires mid-horizon
    for i in range(1, 7):
        inst.append({"type": "Mold", "id": f"M-0{i}", "shots_left": 30 if i == 4 else 5000,
                     "status": "maintenance" if i == 6 else "available"})
    ops = [("OP_01", "cnc"), ("OP_02", "cnc"), ("OP_03", "cnc"), ("OP_04", "cnc"), ("OP_05", "press"),
           ("OP_06", "press"), ("OP_07", "heat"), ("OP_08", "heat"), ("OP_09", "cmm"), ("OP_10", "cmm")]
    for oid, skill in ops:
        inst.append({"type": "Operator", "id": oid, "skill": skill, "employee_id": f"E{1000 + int(oid[3:])}",
                     "cert_expires_h": 9999,
                     "status": "absent" if oid == "OP_07" else "on_shift"})
    inst += [{"type": "Material", "id": "MAT-AL7075", "grade": "Al 7075-T6", "on_hand_kg": 900},
             {"type": "Material", "id": "MAT-TI64", "grade": "Ti-6Al-4V", "on_hand_kg": 400}]
    for pid, name, _ in PARTS:
        inst.append({"type": "Part", "id": pid, "name": name, "revision": "C", "family": "structure",
                     "status": "released"})
    for k in range(1, 9):
        inst.append({"type": "Order", "id": f"SO-{k}", "customer": f"Airframer {k % 3 + 1}", "due_h": 140})
    for n in range(1, 41):
        pid, _, routing = PARTS[(n - 1) % len(PARTS)]
        wid = f"WO-{n:02d}"
        qty = rng.choice([10, 20, 25, 40])
        release = rng.choice([0, 0, 4, 8, 12, 16])
        kind = "subassembly" if n in (3, 8, 15, 20, 27) else "production"
        inst.append({"type": "WorkOrder", "id": wid, "quantity": qty, "release_h": release,
                     "due_h": release + rng.choice([48, 60, 72, 96]), "kind": kind})
        links += [[wid, "produces", pid], [wid, "fulfils", f"SO-{(n - 1) % 8 + 1}"]]
        for s, op in enumerate(routing, 1):
            tid = f"{wid}/{s * 10}"
            hours = max(1, round(rng.uniform(1.5, 4.0) * (qty / 20) ** 0.5 + (2 if op == "heat" else 0)))
            material = "MAT-TI64" if pid in ("PT-02", "PT-07", "PT-11") else "MAT-AL7075"
            proc = {"type": "Process", "id": tid, "seq": s * 10, "op": op, "hours": hours, "quantity": qty,
                    "material_kg": round(qty * (1.6 if material == "MAT-TI64" else 0.9), 1) if s == 1 else 0}
            inst.append(proc)
            links.append([wid, "hasProcess", tid])
            for m in OPS[op]:
                links.append([tid, "requiresMachine", m])
            if op == "form":
                links.append([tid, "requiresMold", MOLD_OF.get(pid, "M-06")])
            for oid, skill in ops:
                if skill == SKILL[op]:
                    links.append([tid, "operatedBy", oid])
            if s == 1:
                links.append([tid, "consumes", material])
    for sub, parent in ((3, 1), (8, 6), (15, 13), (20, 18), (27, 25)):
        links.append([f"WO-{sub:02d}", "feeds", f"WO-{parent:02d}"])
    inst += [{"type": "ECN", "id": "ECN-7", "title": "Rev D: thicker flange, extra deburr", "duration_factor": 1.25,
              "effective_at": 6},
             {"type": "ECN", "id": "ECN-8", "title": "Rev E: tighter hole tolerance", "duration_factor": 1.1,
              "effective_at": 0},
             {"type": "QualityReturn", "id": "QR-1", "defect": "heat-treat hardness out of tolerance", "from_seq": 20},
             {"type": "QualityReturn", "id": "QR-2", "defect": "edge cracks after forming", "from_seq": 10}]
    for kind, machines in OPS.items():
        for m in machines:
            inst.append({"type": "MachineAlert", "id": f"ALERT-{m[3:]}", "code": "BREAKDOWN", "message": f"{m} {kind} fault"})
            links.append([f"ALERT-{m[3:]}", "affects", m])
    links += [["ECN-7", "changes", p] for p in ("PT-02", "PT-05", "PT-07", "PT-11")]
    links.append(["QR-1", "returnOf", "WO-04"])
    links += [["ECN-8", "changes", p] for p in ("PT-09", "PT-12")]
    links.append(["QR-2", "returnOf", "WO-10"])
    return {"instances": inst, "links": links}


if __name__ == "__main__":
    out = HERE / "data.json"
    out.write_text(json.dumps(generate(), indent=1) + "\n")
    print(f"wrote {out}")
