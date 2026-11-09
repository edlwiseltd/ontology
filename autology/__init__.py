"""Autology: Ontology x Agent - ontology-driven workflow automation.

Business knowledge (entities, actions, rules) lives in an immutable ontology;
agents plan and execute against it at run time, and a governance layer makes
sure they never skip mandatory steps or break enterprise rules.
"""

from .agent import (AutoApprover, ConsoleApprover, Escalation, ReviewDecision, ReviewRequest, RunResult,
                    StepRecord, WorkAgent)
from .audit import AuditLog
from .expressions import Expression, ExpressionError, compile_expression
from .governance import Decision, GovernanceLayer, IntegrityError, Principal, Verdict
from .ontology import ActionType, Goal, Ontology, OntologyError, Rule
from .planner import Planner
from .reasoners import ClaudeReasoner, DecisionContext, PlanFollowingReasoner, Proposal
from .state import WorldState
from .tools import Tool, ToolCall, ToolError, ToolRegistry, ToolResult

__version__ = "0.1.0"

__all__ = [
    "ActionType", "AuditLog", "AutoApprover", "ClaudeReasoner", "ConsoleApprover", "Decision",
    "DecisionContext", "Escalation", "Expression", "ExpressionError", "GovernanceLayer", "Goal",
    "IntegrityError", "Ontology", "OntologyError", "PlanFollowingReasoner", "Planner", "Principal",
    "Proposal", "ReviewDecision", "ReviewRequest", "Rule", "RunResult", "StepRecord", "Tool", "ToolCall",
    "ToolError", "ToolRegistry", "ToolResult", "Verdict", "WorkAgent", "WorldState", "compile_expression",
]
