"""Simulated enterprise systems for the customer-onboarding example.

Per-call costs are illustrative (provider fees, internal effort) and feed the cost metrics.

In production these handlers would call real APIs (KYC provider, CLM,
e-signature, billing, ERP, CRM). Note that none of them encodes the process
order or the rules - that lives in ``ontology.json``.
"""

from __future__ import annotations

from autology import ToolCall, ToolError, ToolRegistry, ToolResult

SANCTIONS_LIST = {"Shady Holdings Ltd"}


def build_registry(flaky_billing: int = 0) -> ToolRegistry:
    """Build the tool registry. ``flaky_billing`` makes billing fail N times first (to show retries)."""
    tools = ToolRegistry()
    billing_failures = {"left": flaky_billing}

    def _screen(call: ToolCall, risk: str) -> ToolResult:
        if not call.inputs.get("Customer.tax_id"):
            raise ToolError("tax id missing")
        hit = call.inputs["Customer.name"] in SANCTIONS_LIST
        return ToolResult(updates={"Customer": {"risk_level": risk, "sanctions_hit": hit}},
                          message="sanctions HIT" if hit else "identity verified, no sanctions hit")

    @tools.tool("kyc.verify", name="standard_kyc", cost=1.5)
    def standard_kyc(call: ToolCall) -> ToolResult:
        """Standard KYC provider."""
        return _screen(call, "low")

    @tools.tool("kyc.verify", name="regulated_kyc", when="Customer.industry == 'Financial Services'", cost=4.0)
    def regulated_kyc(call: ToolCall) -> ToolResult:
        """KYC provider certified for regulated financial-services entities."""
        return _screen(call, "medium")

    @tools.tool("kyc.enhanced_due_diligence", name="edd_provider", cost=25.0)
    def edd(call: ToolCall) -> ToolResult:
        """Beneficial-ownership and PEP screening."""
        if str(call.inputs["Customer.tax_id"]).endswith("-PEP"):
            return ToolResult("flagged", message="politically exposed person among beneficial owners")
        return ToolResult("cleared", message="beneficial owners verified")

    @tools.tool("kyc.enhanced_due_diligence", name="edd_lite", when="Contract.value < 500000", cost=8.0)
    def edd_lite(call: ToolCall) -> ToolResult:
        """Database-only PEP / beneficial-owner screening for smaller contracts."""
        if str(call.inputs["Customer.tax_id"]).endswith("-PEP"):
            return ToolResult("flagged", message="PEP match in screening database")
        return ToolResult("cleared", message="no PEP or adverse-media match")

    @tools.tool("kyc.signatory", name="signatory_register", cost=1.0)
    def signatory(call: ToolCall) -> ToolResult:
        """Company-register lookup of authorised signatories."""
        who = call.inputs.get("Contact.name") or "the nominated contact"
        return ToolResult(message=f"{who} is an authorised signatory of {call.inputs['Customer.name']}")

    @tools.tool("contract.submit", name="clm_portal", cost=0.2)
    def submit(call: ToolCall) -> ToolResult:
        """Contract lifecycle management portal."""
        return ToolResult(message="contract uploaded to CLM")

    @tools.tool("contract.validate", name="contract_validator", cost=0.5)
    def validate(call: ToolCall) -> ToolResult:
        """Automated playbook check of contract clauses."""
        if call.inputs["Contract.nonstandard_terms"]:
            return ToolResult("rejected", message="non-standard liability clause violates playbook")
        return ToolResult("approved", message="all clauses within playbook")

    @tools.tool("contract.revise", name="ai_redline_drafter", when="Contract.value < 1000000", cost=6.0)
    def ai_redline(call: ToolCall) -> ToolResult:
        """Generative drafting: proposes the standard-clause redline; Legal still approves it (R-LEGAL-002)."""
        revision = (call.inputs.get("Contract.revision") or 0) + 1
        return ToolResult(updates={"Contract": {"nonstandard_terms": False, "revision": revision}},
                          message=f"AI-drafted redline to standard liability wording (rev {revision}), approved by Legal")

    @tools.tool("contract.revise", name="legal_desk", cost=120.0)
    def revise(call: ToolCall) -> ToolResult:
        """Legal team redlines the contract."""
        revision = (call.inputs.get("Contract.revision") or 0) + 1
        return ToolResult(updates={"Contract": {"nonstandard_terms": False, "revision": revision}},
                          message=f"liability clause replaced with standard wording (rev {revision})")

    @tools.tool("esign.send", name="esign_gateway", cost=2.0)
    def esign(call: ToolCall) -> ToolResult:
        """E-signature service."""
        return ToolResult(message=f"signed by {call.inputs['Customer.name']}")

    @tools.tool("billing.setup", name="card_billing", cost=0.3)
    def card_billing(call: ToolCall) -> ToolResult:
        """Card-based subscription billing."""
        if billing_failures["left"] > 0:
            billing_failures["left"] -= 1
            raise ToolError("billing API timeout")
        return ToolResult(message="card billing account created")

    @tools.tool("billing.setup", name="invoice_billing", when="BillingAccount.method == 'invoice'", cost=0.3)
    def invoice_billing(call: ToolCall) -> ToolResult:
        """Net-30 invoicing for enterprise accounts."""
        return ToolResult(message="invoice billing account created (net 30)")

    @tools.tool("erp.order", name="erp", cost=0.1)
    def order(call: ToolCall) -> ToolResult:
        """ERP order entry."""
        return ToolResult(message=f"order placed for {call.inputs['Order.sku']}")

    @tools.tool("crm.activate", name="crm", cost=0.1)
    def activate(call: ToolCall) -> ToolResult:
        """CRM account activation."""
        return ToolResult(message="customer account active")

    return tools
