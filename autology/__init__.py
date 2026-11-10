"""Autology: Ontology x Agent - ontology-driven workflow automation.

Business knowledge (entities, actions, rules) lives in an immutable ontology;
agents plan and execute against it at run time, and a governance layer makes
sure they never skip mandatory steps or break enterprise rules.
"""

from .agent import (AutoApprover, ConsoleApprover, DeferredApprover, Escalation, ReviewDecision, ReviewRequest, RunResult,
                    StepRecord, WorkAgent)
from .audit import AuditLog
from .expressions import Expression, ExpressionError, compile_expression
from .governance import Decision, GovernanceLayer, IntegrityError, Principal, Verdict
from .ontology import ActionType, Goal, Ontology, OntologyError, Rule
from .planner import Planner
from .economics import ROIReport, TCOModel
from .graph import KnowledgeGraph
from .lint import Finding, lint
from .reasoners import (AnthropicChatModel, ChatModel, ClaudeReasoner, DecisionContext, FunctionChatModel, LLMReasoner,
                        LLMResponse, PlanFollowingReasoner, Proposal, RoutingReasoner)
from .reporting import compliance_report, metrics, ontology_gaps
from .scoring import Scorecard, score_deployment, score_ontology
from .state import WorldState
from .tools import Tool, ToolCall, ToolError, ToolRegistry, ToolResult
from .versioning import OntologyRegistry, VersionError

__version__ = "0.3.0"

__all__ = [
    "ActionType", "AuditLog", "AutoApprover", "ClaudeReasoner", "ConsoleApprover", "Decision",
    "DecisionContext", "Escalation", "Expression", "ExpressionError", "GovernanceLayer", "Goal",
    "IntegrityError", "Ontology", "OntologyError", "PlanFollowingReasoner", "Planner", "Principal",
    "Proposal", "ReviewDecision", "ReviewRequest", "Rule", "RunResult", "StepRecord", "Tool", "ToolCall",
    "ToolError", "ToolRegistry", "ToolResult", "Verdict", "WorkAgent", "WorldState", "compile_expression",
    "Finding", "KnowledgeGraph", "OntologyRegistry", "ROIReport", "RoutingReasoner", "TCOModel", "VersionError",
    "compliance_report", "lint", "metrics", "ontology_gaps", "Scorecard", "score_deployment", "score_ontology",
    "DeferredApprover", "AnthropicChatModel", "ChatModel", "FunctionChatModel", "LLMReasoner", "LLMResponse",
]
