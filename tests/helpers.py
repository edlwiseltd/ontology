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

from autology.ontology import load_document  # noqa: E402

_DOC = load_document(ONTOLOGY_PATH)  # composed from modules


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


MFG = ROOT / "examples" / "manufacturing"
MFG_ONTOLOGY = MFG / "enterprise.json"
if str(MFG) not in sys.path:
    sys.path.insert(0, str(MFG))

import manufacturing_tools  # noqa: E402,F401


def supplier_case(**contract):
    c = {"value": 400_000, "end_date": "2027-12-31", "late_delivery_penalty": True, "revision": 0}
    c.update(contract)
    return {"Supplier": {"name": "Supplier Y", "on_time_rate": 0.81}, "Contract": c}


def order_case(on_time_rate=0.97, alternate=True):
    return {"Supplier": {"name": "Supplier X", "on_time_rate": on_time_rate},
            "ProductionLine": {"code": "LYON-1", "alternate_available": alternate},
            "Order": {"quantity": 10, "amount": 1000, "line": "primary"}}
