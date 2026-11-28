"""Customer onboarding with Autology - runnable walkthrough.

    python examples/customer_onboarding/run.py                 # all scenarios
    python examples/customer_onboarding/run.py financial       # one scenario
    python examples/customer_onboarding/run.py financial --llm # let Claude choose steps (needs `anthropic`)
    python examples/customer_onboarding/run.py financial --interactive  # you are the human reviewer
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE)]

from autology import AutoApprover, ConsoleApprover, Ontology, WorkAgent  # noqa: E402
from onboarding_tools import build_registry  # noqa: E402

ONTOLOGY = HERE / "ontology.json"

SCENARIOS = {
    "retail": dict(
        title="Retail customer, standard contract: straight-through processing",
        case={
            "Customer": {"name": "Acme Retail", "industry": "Retail", "tax_id": "GB-1234"},
            "Contract": {"value": 48_000, "nonstandard_terms": False, "revision": 0},
            "BillingAccount": {"method": "card"},
            "Order": {"sku": "PLAN-STARTER"},
        },
    ),
    "financial": dict(
        title="Customer XYZ (Financial Services): EDD, rejected contract -> Legal revision, Finance sign-off",
        case={
            "Customer": {"name": "XYZ Capital", "industry": "Financial Services", "tax_id": "US-9981"},
            "Contract": {"value": 2_500_000, "nonstandard_terms": True, "revision": 0},
            "BillingAccount": {"method": "invoice"},
            "Order": {"sku": "PLAN-ENTERPRISE"},
        },
        flaky_billing=0,
    ),
    "sanctioned": dict(
        title="Sanctioned party: governance blocks the contract and escalates",
        case={
            "Customer": {"name": "Shady Holdings Ltd", "industry": "Retail", "tax_id": "KY-0001"},
            "Contract": {"value": 10_000, "nonstandard_terms": False, "revision": 0},
            "BillingAccount": {"method": "card"},
            "Order": {"sku": "PLAN-STARTER"},
        },
    ),
    "pep": dict(
        title="Financial-services customer flagged by enhanced due diligence",
        case={
            "Customer": {"name": "Delta Bank", "industry": "Financial Services", "tax_id": "DE-7777-PEP"},
            "Contract": {"value": 300_000, "nonstandard_terms": False, "revision": 0},
            "BillingAccount": {"method": "invoice"},
            "Order": {"sku": "PLAN-ENTERPRISE"},
        },
    ),
    "unprivileged": dict(
        title="Agent without KYC role: cannot read tax IDs, so it escalates instead of guessing",
        case={
            "Customer": {"name": "Acme Retail", "industry": "Retail", "tax_id": "GB-1234"},
            "Contract": {"value": 48_000, "nonstandard_terms": False, "revision": 0},
            "BillingAccount": {"method": "card"},
            "Order": {"sku": "PLAN-STARTER"},
        },
        roles=("sales",),
    ),
    "declined": dict(
        title="Finance Director declines a 2.5M contract: the agent stops and hands back",
        case={
            "Customer": {"name": "Big Corp", "industry": "Manufacturing", "tax_id": "FR-4242"},
            "Contract": {"value": 2_500_000, "nonstandard_terms": False, "revision": 0},
            "BillingAccount": {"method": "invoice"},
            "Order": {"sku": "PLAN-ENTERPRISE"},
        },
        approvals={"sign_contract": False},
    ),
    "flaky": dict(
        title="Transient billing outage: tool retry, no human needed",
        case={
            "Customer": {"name": "Acme Retail", "industry": "Retail", "tax_id": "GB-1234"},
            "Contract": {"value": 48_000, "nonstandard_terms": False, "revision": 0},
            "BillingAccount": {"method": "card"},
            "Order": {"sku": "PLAN-STARTER"},
        },
        flaky_billing=1,
    ),
}


def printer(event: str, data: dict) -> None:
    if event == "decision":
        print(f"  [{data['step']:>2}] {data['action']:<24} {data['verdict'].upper():<6} "
              f"({data['proposed_by']}) {' '.join(data['rules'])}")
    elif event == "governance.deny":
        print(f"       ! governance denied {data['action']} proposed by {data['proposed_by']}: "
              f"{'; '.join(data['reasons'])}")
    elif event == "review":
        print(f"       ? human review by {data['reviewer']}: {'APPROVED' if data['approved'] else 'DECLINED'}")
    elif event == "tool.error":
        print(f"       x {data['tool']} attempt {data['attempt']} failed: {data['error']}")
    elif event == "step":
        moves = ", ".join(f"{e}: {a}->{b}" for e, (a, b) in data["transitions"].items())
        print(f"       -> {data['tool']}: {data['outcome']} - {data['message']}"
              + (f"  [{moves}]" if moves else ""))


def run(name: str, ontology: Ontology, llm: bool = False, interactive: bool = False) -> str:
    spec = SCENARIOS[name]
    print(f"\n=== {name}: {spec['title']} ===")
    reasoner = None
    if llm:
        from autology import ClaudeReasoner

        reasoner = ClaudeReasoner()
    approver = ConsoleApprover() if interactive else AutoApprover(spec.get("approvals"), default=True)
    agent = WorkAgent("work-agent", ontology, build_registry(spec.get("flaky_billing", 0)),
                      roles=spec.get("roles", ("sales", "kyc")), reasoner=reasoner, approver=approver,
                      observer=printer)
    result = agent.run("onboard_customer", spec["case"], case_id=name)
    print(f"  => {result.status.upper()}", end="")
    if result.escalation:
        print(f": {result.escalation.reason} (to {result.escalation.to})")
        for detail in result.escalation.details:
            print(f"       - {detail}")
    else:
        print()
    print(f"  audit trail: {len(result.audit)} entries, chain valid = {result.audit.verify()}")
    return result.status


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", nargs="*", help=f"scenario(s) to run (default: all): {', '.join(SCENARIOS)}")
    parser.add_argument("--llm", action="store_true", help="use ClaudeReasoner to choose steps")
    parser.add_argument("--interactive", action="store_true", help="answer human reviews on the console")
    args = parser.parse_args(argv)
    unknown = [s for s in args.scenario if s not in SCENARIOS]
    if unknown:
        parser.error(f"unknown scenario(s) {unknown}; choose from {', '.join(SCENARIOS)}")
    ontology = Ontology.load(ONTOLOGY)
    print(f"Loaded ontology {ontology.name} v{ontology.version} (fingerprint {ontology.fingerprint[:12]})")
    for name in args.scenario or SCENARIOS:
        run(name, ontology, args.llm, args.interactive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
