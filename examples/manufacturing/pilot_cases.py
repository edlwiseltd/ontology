"""Generate a reproducible pilot batch of supplier contracts (simulated environment, methodology 2.3).

    python examples/manufacturing/pilot_cases.py      # writes pilot_cases.json

Mix (assumptions - replace with your own data): 15% lack the LateDeliveryPenalty clause, 20% are
worth >= 1M (CFO review), 2% are with a supplier that is already suspended.
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def generate(n: int = 150, seed: int = 7):
    rng = random.Random(seed)
    cases = []
    for i in range(n):
        value = rng.choice([1_200_000, 2_500_000]) if rng.random() < 0.2 else rng.choice(
            [60_000, 150_000, 300_000, 650_000])
        supplier = {"name": f"Supplier {i:03d}", "on_time_rate": round(rng.uniform(0.8, 0.99), 2)}
        if rng.random() < 0.02:
            supplier["status"] = "suspended"
        cases.append({"case_id": f"PROC-{i:03d}", "case": {
            "Supplier": supplier,
            "Contract": {"value": value, "end_date": "2027-12-31", "revision": 0,
                         "late_delivery_penalty": rng.random() > 0.15},
        }})
    return cases


if __name__ == "__main__":
    out = HERE / "pilot_cases.json"
    out.write_text(json.dumps(generate(), indent=1) + "\n")
    print(f"wrote {out}")
