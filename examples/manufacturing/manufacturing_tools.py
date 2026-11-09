"""Simulated plant and back-office systems for the manufacturing example.

Each tool carries a per-call ``cost`` so the agent prefers the cheapest
eligible tool and falls back to pricier ones (e.g. outside counsel) only when
the cheap one fails. Process order and rules live in the ontology, not here.
"""

from __future__ import annotations

from autology import ToolCall, ToolError, ToolRegistry, ToolResult


class Faults:
    """Switches to inject failures into the simulated systems."""

    def __init__(self, mes_down: int = 0, clause_ai_down: bool = False, partial_delivery: bool = False):
        self.mes_down = mes_down  # MES start fails this many times
        self.clause_ai_down = clause_ai_down
        self.partial_delivery = partial_delivery


def procurement_tools(faults: Faults | None = None) -> ToolRegistry:
    faults = faults or Faults()
    tools = ToolRegistry()

    @tools.tool("contract.clause_check", name="ai_clause_checker", cost=0.05)
    def ai_clause_checker(call: ToolCall) -> ToolResult:
        """Automated clause extraction and playbook check."""
        if faults.clause_ai_down:
            raise ToolError("clause model endpoint unavailable")
        if not call.inputs["Contract.late_delivery_penalty"]:
            return ToolResult("missing_penalty", message="no LateDeliveryPenalty clause found")
        return ToolResult("compliant", message="all mandatory clauses present")

    @tools.tool("contract.clause_check", name="outside_counsel_review", cost=400.0)
    def outside_counsel(call: ToolCall) -> ToolResult:
        """External law firm review (slow, expensive fallback)."""
        if not call.inputs["Contract.late_delivery_penalty"]:
            return ToolResult("missing_penalty", message="counsel: LateDeliveryPenalty clause missing")
        return ToolResult("compliant", message="counsel: contract compliant")

    @tools.tool("legal.redline", name="legal_redline_desk", cost=150.0)
    def redline(call: ToolCall) -> ToolResult:
        """In-house Legal adds the standard penalty clause."""
        rev = (call.inputs.get("Contract.revision") or 0) + 1
        return ToolResult(updates={"Contract": {"revision": rev}},
                          message=f"standard LateDeliveryPenalty clause inserted (rev {rev})")

    @tools.tool("esign.send", name="esign_gateway", cost=2.0)
    def esign(call: ToolCall) -> ToolResult:
        """E-signature."""
        return ToolResult(message=f"signed with {call.inputs['Supplier.name']}")

    return tools


def finance_tools() -> ToolRegistry:
    tools = ToolRegistry()

    @tools.tool("finance.payment_terms", name="treasury_terms_engine", cost=1.0)
    def terms(call: ToolCall) -> ToolResult:
        """Treasury policy engine for payment terms."""
        net = 60 if call.inputs["Contract.value"] >= 1_000_000 else 30
        return ToolResult(updates={"Contract": {"payment_terms": f"net {net}"}}, message=f"payment terms net {net}")

    return tools


def production_tools(faults: Faults | None = None) -> ToolRegistry:
    faults = faults or Faults()
    tools = ToolRegistry()
    state = {"mes_failures_left": faults.mes_down}

    @tools.tool("scm.supply_check", name="supplier_portal", cost=0.5)
    def supply(call: ToolCall) -> ToolResult:
        """Supplier portal ASN / delivery forecast."""
        if faults.partial_delivery:
            return ToolResult("partial_delivery", message="supplier can ship 60% of the material on time")
        if call.inputs["Supplier.on_time_rate"] < 0.9:
            return ToolResult("late", message=f"{call.inputs['Supplier.name']} forecasts a 5-day delay")
        return ToolResult("on_time", message="materials confirmed for delivery")

    @tools.tool("mes.reroute", name="mes_scheduler", cost=5.0)
    def reroute(call: ToolCall) -> ToolResult:
        """MES scheduler."""
        return ToolResult(message="order moved to alternate line with buffer stock")

    @tools.tool("mes.start", name="mes", cost=1.0)
    def start(call: ToolCall) -> ToolResult:
        """Manufacturing execution system."""
        if state["mes_failures_left"] > 0:
            state["mes_failures_left"] -= 1
            raise ToolError("MES unavailable (maintenance window)")
        return ToolResult(message=f"{call.inputs['Order.quantity']} units released on {call.inputs['Order.line']} line")

    @tools.tool("mes.complete", name="mes_completion", cost=1.0)
    def complete(call: ToolCall) -> ToolResult:
        """MES production confirmation."""
        return ToolResult(message="output confirmed, order closed")

    return tools


def quality_tools() -> ToolRegistry:
    tools = ToolRegistry()

    @tools.tool("qms.trace", name="qms_genealogy", cost=2.0)
    def trace(call: ToolCall) -> ToolResult:
        """Batch genealogy in the QMS."""
        return ToolResult(message=f"defect traced to raw material from {call.inputs['Supplier.name']}")

    @tools.tool("wms.quarantine", name="wms", cost=1.0)
    def quarantine(call: ToolCall) -> ToolResult:
        """Warehouse quarantine."""
        return ToolResult(message="affected lots blocked in all warehouses")

    @tools.tool("wms.release", name="wms_release", cost=1.0)
    def release(call: ToolCall) -> ToolResult:
        """Warehouse release."""
        return ToolResult(message="lots released: defect rate within tolerance")

    @tools.tool("qms.recall", name="recall_service", cost=50.0)
    def recall(call: ToolCall) -> ToolResult:
        """ProductRecall workflow (regulator + customer notifications)."""
        return ToolResult(message="ProductRecall initiated; customers and regulator notified")

    @tools.tool("scm.supplier_status", name="supplier_master", cost=0.5)
    def suspend(call: ToolCall) -> ToolResult:
        """Supplier master data."""
        return ToolResult(message="supplier suspended pending corrective action")

    return tools
