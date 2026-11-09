import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "customer_onboarding"
ONTOLOGY_PATH = EXAMPLE / "ontology.json"

for p in (str(ROOT), str(EXAMPLE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from onboarding_tools import build_registry  # noqa: E402,F401

_DOC = json.loads(ONTOLOGY_PATH.read_text())


def load_doc():
    return copy.deepcopy(_DOC)


def retail_case(**overrides):
    case = {
        "Customer": {"name": "Acme Retail", "industry": "Retail", "tax_id": "GB-1234"},
        "Contract": {"value": 48_000, "nonstandard_terms": False, "revision": 0},
        "BillingAccount": {"method": "card"},
        "Order": {"sku": "PLAN-STARTER"},
    }
    for entity, attrs in overrides.items():
        case[entity].update(attrs)
    return case


def financial_case():
    return retail_case(
        Customer={"name": "XYZ Capital", "industry": "Financial Services", "tax_id": "US-9981"},
        Contract={"value": 2_500_000, "nonstandard_terms": True},
        BillingAccount={"method": "invoice"},
        Order={"sku": "PLAN-ENTERPRISE"},
    )
