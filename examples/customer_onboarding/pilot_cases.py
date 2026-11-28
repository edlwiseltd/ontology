"""Generate a reproducible pilot batch of onboarding cases (simulated environment, methodology 2.3).

    python examples/customer_onboarding/pilot_cases.py      # writes pilot_cases.json

Mix (assumptions - replace with your own case data): industries Retail 40%, Manufacturing 25%,
Technology 15%, Financial Services 20%; 15% non-standard contract terms; 8% of contracts >= 1M;
invoice billing above 250k; 2% sanctioned parties; 10% of FS customers have a PEP owner.
"""

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def generate(n: int = 120, seed: int = 11):
    rng = random.Random(seed)
    cases = []
    for i in range(n):
        industry = rng.choices(["Retail", "Manufacturing", "Technology", "Financial Services"], [40, 25, 15, 20])[0]
        value = rng.choice([1_200_000, 2_500_000]) if rng.random() < 0.08 else rng.choice(
            [24_000, 48_000, 90_000, 180_000, 320_000, 640_000])
        name = "Shady Holdings Ltd" if rng.random() < 0.02 else f"Customer {i:03d}"
        tax_id = f"TX-{i:05d}" + ("-PEP" if industry == "Financial Services" and rng.random() < 0.1 else "")
        cases.append({"case_id": f"ONB-{i:03d}", "case": {
            "Customer": {"name": name, "industry": industry, "tax_id": tax_id},
            "Contact": {"name": f"Signatory {i:03d}", "email": f"signatory{i:03d}@example.com", "title": "CFO"},
            "Contract": {"value": value, "nonstandard_terms": rng.random() < 0.15, "revision": 0},
            "BillingAccount": {"method": "invoice" if value > 250_000 else "card"},
            "Order": {"sku": "PLAN-ENTERPRISE" if value > 250_000 else "PLAN-STARTER"},
        }})
    return cases


if __name__ == "__main__":
    out = HERE / "pilot_cases.json"
    out.write_text(json.dumps(generate(), indent=1) + "\n")
    print(f"wrote {out}")
