"""
VendorVigil — Pydantic AI Schemas
All agent outputs are validated against these schemas.
Architecture: Band = coordination layer, Pydantic AI = agent framework.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---
# 1. RoutingPlan — Output from @VendorCoordinator (Pydantic AI-based)
# ---

class RoutingPlan(BaseModel):
    """Coordinator output: determines which specialist agents to invoke."""
    vendor_id: str = Field(..., description="Unique vendor identifier")
    vendor_name: str = Field(..., description="Vendor display name")
    vendor_type: str = Field(..., description="Service category/type of vendor")
    requires_security_check: bool = Field(
        default=False, description="Whether security assessment is needed"
    )
    requires_privacy_check: bool = Field(
        default=False, description="Whether privacy assessment is needed"
    )
    requires_financial_check: bool = Field(
        default=False, description="Whether financial assessment is needed"
    )
    reason: list[str] = Field(
        default_factory=list,
        description="Rationale for routing decisions",
    )


# ---
# 2. SecurityAssessment — Output from @SecurityReviewer
# ---

class SecurityAssessment(BaseModel):
    """Security specialist agent output."""
    vendor_id: str
    score: int = Field(ge=0, le=100, description="Security score 0-100")
    findings: list[str] = Field(default_factory=list, description="Positive findings")
    missing_evidence: list[str] = Field(
        default_factory=list, description="Evidence gaps found"
    )
    critical_gaps: list[str] = Field(
        default_factory=list,
        description="Critical security gaps requiring attention",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Agent confidence level")


# ---
# 3. PrivacyAssessment — Output from @PrivacyReviewer
# ---

class PrivacyAssessment(BaseModel):
    """Privacy specialist agent output."""
    vendor_id: str
    score: int = Field(ge=0, le=100, description="Privacy score 0-100")
    personal_data_processed: bool = Field(
        default=False, description="Whether vendor processes personal data"
    )
    findings: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    critical_gaps: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


# ---
# 4. FinancialAssessment — Output from @FinancialReviewer
# ---

class FinancialAssessment(BaseModel):
    """Financial specialist agent output."""
    vendor_id: str
    score: int = Field(ge=0, le=100, description="Financial risk score 0-100")
    findings: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(
        default_factory=list, description="Financial risk indicators"
    )
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        default="MEDIUM",
        description="Financial risk level — replaces final recommendation language",
    )
    confidence: float = Field(ge=0.0, le=1.0)


# ---
# 5. RiskDecision — Output from @RiskScorer
# ---

RiskStatus = Literal["APPROVED", "NEEDS_REVISION", "ESCALATED", "TEMPORARILY_REJECTED"]


class RiskDecision(BaseModel):
    """Risk scoring agent output — the final decision before audit."""
    vendor_id: str
    total_score: int = Field(ge=0, le=100)
    status: RiskStatus = Field(..., description="Final risk status")
    reasons: list[str] = Field(
        default_factory=list, description="Why this status was assigned"
    )
    required_actions: list[str] = Field(
        default_factory=list, description="Recommended next steps"
    )
    human_review_required: bool = Field(
        default=False, description="Whether human approval is mandatory"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    security_score: int = Field(default=0, ge=0, le=100)
    privacy_score: int = Field(default=0, ge=0, le=100)
    financial_score: int = Field(default=0, ge=0, le=100)
    evidence_completeness: int = Field(default=0, ge=0, le=100)


# ---
# 6. AuditRecord — Output from @AuditLogger
# ---

class AuditRecord(BaseModel):
    """Audit trail agent output — immutable decision log."""
    audit_id: str = Field(..., description="Unique audit identifier, e.g., VV-2026-001")
    vendor_id: str
    vendor_name: str
    decision_status: str
    total_score: int
    evidence_summary: list[str] = Field(default_factory=list)
    agent_trace: list[str] = Field(
        default_factory=list,
        description="Ordered list of agents involved in this decision",
    )
    human_review_required: bool
    confidence: float
    disclaimer: str = Field(
        default=(
            "VendorVigil is a decision support tool for initial vendor risk triage. "
            "This system is not an official auditor, not a compliance certification, "
            "and not a replacement for human judgment."
        ),
        description="Mandatory safe-position disclaimer",
    )


# ---
# 7. FinalReport — Output from @ReportCompiler
# ---

class FinalReport(BaseModel):
    """Report generator agent output — sent to Streamlit dashboard."""
    vendor_name: str
    vendor_id: str
    status: str
    total_score: int
    domain_scores: dict[str, int] = Field(
        default_factory=dict,
        description="Sub-scores: security, privacy, financial, evidence",
    )
    missing_evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    audit_id: str
    executive_summary: str = Field(
        default="", description="One-paragraph summary for decision maker"
    )
    human_review_required: bool
    agent_trace: list[str] = Field(default_factory=list)
    disclaimer: str = Field(
        default=(
            "VendorVigil is a decision support tool for initial vendor risk triage. "
            "This system is not an official auditor, not a compliance certification, "
            "and not a replacement for human judgment."
        ),
    )


# ---
# Aggregate type for internal pipeline
# ---

# ---
# Runtime Enums — used by workflow state machine and guards
# ---

class AgentRole(str, Enum):
    """Canonical agent roles — single source of truth for all runtime identity."""
    VENDOR_COORDINATOR = "VendorCoordinator"
    SECURITY_REVIEWER = "SecurityReviewer"
    PRIVACY_REVIEWER = "PrivacyReviewer"
    FINANCIAL_REVIEWER = "FinancialReviewer"
    RISK_SCORER = "RiskScorer"
    AUDIT_LOGGER = "AuditLogger"
    REPORT_COMPILER = "ReportCompiler"

    @property
    def short_key(self) -> str:
        """Return the short storage key for this role."""
        return _AGENT_ROLE_TO_SHORT[self]

    @classmethod
    def from_short_key(cls, key: str) -> AgentRole:
        """Resolve a short storage key back to canonical AgentRole."""
        return _SHORT_TO_AGENT_ROLE.get(key, cls.VENDOR_COORDINATOR)


# Canonical short-key mapping — one authoritative place
_AGENT_ROLE_TO_SHORT: dict[AgentRole, str] = {
    AgentRole.VENDOR_COORDINATOR: "coordinator",
    AgentRole.SECURITY_REVIEWER: "security",
    AgentRole.PRIVACY_REVIEWER: "privacy",
    AgentRole.FINANCIAL_REVIEWER: "financial",
    AgentRole.RISK_SCORER: "risk",
    AgentRole.AUDIT_LOGGER: "audit",
    AgentRole.REPORT_COMPILER: "report",
}

_SHORT_TO_AGENT_ROLE: dict[str, AgentRole] = {v: k for k, v in _AGENT_ROLE_TO_SHORT.items()}


class WorkflowStage(str, Enum):
    """Stages in the sequential vendor assessment workflow."""
    CREATED = "CREATED"
    ROUTING = "ROUTING"
    SECURITY_PENDING = "SECURITY_PENDING"
    PRIVACY_PENDING = "PRIVACY_PENDING"
    FINANCIAL_PENDING = "FINANCIAL_PENDING"
    RISK_PENDING = "RISK_PENDING"
    AUDIT_PENDING = "AUDIT_PENDING"
    REPORT_PENDING = "REPORT_PENDING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentLifecycle(str, Enum):
    """Lifecycle states for individual agents within a workflow."""
    IDLE = "IDLE"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    RESULT_SUBMITTED = "RESULT_SUBMITTED"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InteractionMode(str, Enum):
    """Classification of incoming events before LLM processing."""
    CASUAL_CHAT = "CASUAL_CHAT"
    DIRECT_DOMAIN_REQUEST = "DIRECT_DOMAIN_REQUEST"
    COORDINATED_WORKFLOW = "COORDINATED_WORKFLOW"
    CLARIFICATION = "CLARIFICATION"
    FINAL_NOTIFICATION = "FINAL_NOTIFICATION"


class ActionType(str, Enum):
    """Types of outbound actions an agent can take."""
    REPLY_TO_CALLER = "REPLY_TO_CALLER"
    SUBMIT_DOMAIN_RESULT = "SUBMIT_DOMAIN_RESULT"
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
    DISPATCH_AGENT_TASK = "DISPATCH_AGENT_TASK"
    FINAL_NOTIFY_HUMAN = "FINAL_NOTIFY_HUMAN"
    NO_ACTION = "NO_ACTION"


# ---
# New runtime models — used by guards and workflow state
# ---

class AgentAction(BaseModel):
    """Structured action produced by an agent's LLM."""
    action_type: ActionType
    content: str
    structured_payload: dict[str, Any] | None = None


class ClarificationRequest(BaseModel):
    """Agent requesting more information from caller or coordinator."""
    question: str
    context: str = ""


class CasualReply(BaseModel):
    """Natural language reply for casual chat mode."""
    content: str


class DirectDomainReply(BaseModel):
    """Reply for direct domain request mode."""
    content: str
    domain: str


class WorkflowEvent(BaseModel):
    """Internal event within the workflow system."""
    event_type: str
    workflow_id: str
    data: dict[str, Any] = Field(default_factory=dict)


class PolicyViolation(BaseModel):
    """Record of a policy violation blocked by the outbound guard."""
    violation_type: str
    sender_role: str
    attempted_action: str
    details: str
    timestamp: str


class AssessmentBundle(BaseModel):
    """Internal container: all specialist assessments before risk scoring."""
    vendor_profile: dict
    security: SecurityAssessment | None = None
    privacy: PrivacyAssessment | None = None
    financial: FinancialAssessment | None = None


# --- AgentAction — unified structured output contract ---

ROLE_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "SecurityReviewer": SecurityAssessment,
    "PrivacyReviewer": PrivacyAssessment,
    "FinancialReviewer": FinancialAssessment,
    "RiskScorer": RiskDecision,
    "AuditLogger": AuditRecord,
    "ReportCompiler": FinalReport,
}


class AgentActionResult(BaseModel):
    """Structured result from an agent after schema validation."""
    message: str = Field(..., description="Free-text agent message")
    result_payload: dict[str, Any] | None = Field(
        default=None, description="Role-specific structured payload"
    )
    role: str = Field(default="", description="Agent role name")
    is_domain_result: bool = Field(
        default=False, description="True if result passes role-specific schema"
    )


def validate_specialist_result(role: str, content: str) -> AgentActionResult:
    """Validate agent output against role-specific schema.

    Casual/direct/NO_ACTION/greetings never count as domain results.
    Only coordinated workflow outputs that match role schema qualify.
    """
    result = AgentActionResult(message=content, role=role, is_domain_result=False)

    # Greetings/readiness/NO_ACTION never count as domain results
    lower = content.lower().strip()
    greeting_patterns = [
        "hello", "halo", "hi ", "hey ", "greetings", "welcome",
        "how can i help", "how can i assist", "how may i help",
        "ready", "i am ready", "i'm ready", "siap",
        "no_action", "no action",
    ]
    if any(lower.startswith(p) for p in greeting_patterns):
        return result
    if len(content) < 50:  # Too short to be a structured assessment
        return result
    if lower == "no_action":
        return result

    schema_cls = ROLE_SCHEMA_MAP.get(role)
    if schema_cls is None:
        return result

    # Try to parse/validate against the role schema
    try:
        from utils.result_collector import parse_agent_message
        parsed = parse_agent_message(role, content)
        if parsed and isinstance(parsed, dict):
            # Check minimum required fields: score or total_score
            has_score = parsed.get("score") is not None or parsed.get("total_score") is not None
            has_vendor = parsed.get("vendor_name") or parsed.get("vendor_id")
            if has_score or has_vendor:
                result.result_payload = parsed
                result.is_domain_result = True
    except Exception:
        pass

    return result
