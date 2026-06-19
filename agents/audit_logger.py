"""
VendorVigil — @AuditLogger (Audit Trail Agent)
Framework: Pydantic AI + Python utility
Provider:  Featherless (provider/gateway for open-source models)
Role:     Create immutable audit record with full agent trace and disclaimer.

This agent ensures every decision creates an immutable, timestamped audit log.
The output is an AuditRecord — validated against Pydantic schema.
"""

from __future__ import annotations

import logging
from typing import Any

from utils.audit_log import create_audit_record, generate_audit_id, AuditRecord
from utils.band_helpers import BandChatRoom
from utils.schemas import RiskDecision

logger = logging.getLogger(__name__)

HANDLE = "@AuditLogger"


def create_audit_trail(
    vendor_profile: dict,
    risk_decision: RiskDecision,
    room: BandChatRoom,
) -> AuditRecord:
    """Create an immutable audit log entry for the vendor assessment.

    Args:
        vendor_profile: Original vendor data
        risk_decision: Final risk decision from @RiskScorer
        room: BandChatRoom for tracing agent involvement

    Returns:
        AuditRecord with unique ID and full trace
    """
    vendor_id = vendor_profile.get("vendor_id", "UNKNOWN")
    vendor_name = vendor_profile.get("vendor_name", "Unnamed Vendor")

    # Build evidence summary
    evidence_summary: list[str] = []
    security = vendor_profile.get("security_evidence", {})
    if security.get("soc2"):
        evidence_summary.append("SOC 2: FULFILLED")
    else:
        evidence_summary.append("SOC 2: NOT FULFILLED")
    if security.get("iso27001"):
        evidence_summary.append("ISO 27001: FULFILLED")
    else:
        evidence_summary.append("ISO 27001: NOT FULFILLED")

    privacy = vendor_profile.get("privacy_evidence", {})
    if privacy.get("dpa"):
        evidence_summary.append("DPA: FULFILLED")
    else:
        evidence_summary.append("DPA: NOT FULFILLED")

    # Extract agent trace from Band Chat
    agent_trace = room.get_agent_trace()

    # Create the audit record
    record = create_audit_record(
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        decision_status=risk_decision.status,
        total_score=risk_decision.total_score,
        evidence_summary=evidence_summary,
        agent_trace=agent_trace,
        human_review_required=risk_decision.human_review_required,
        confidence=risk_decision.confidence,
    )

    room.agent_says(
        HANDLE,
        f"Audit log created — {record.audit_id}.\n"
        f"Agent trace: {' → '.join(agent_trace)}\n"
        f"Disclaimer: {record.disclaimer}",
    )

    return record


def run(
    vendor_profile: dict,
    risk_decision: RiskDecision,
    room: BandChatRoom,
) -> AuditRecord:
    """Public entry point for @AuditLogger."""
    room.agent_says(HANDLE, f"Received risk decision for {vendor_profile.get('vendor_name', 'Unknown')}, recording audit trail...")
    return create_audit_trail(vendor_profile, risk_decision, room)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    import json
    from pathlib import Path

    profile_path = Path(__file__).parent.parent / "data" / "vendor_scenarios" / "cloud_pay_x.json"
    profile = json.loads(profile_path.read_text())

    from utils.schemas import RiskDecision
    decision = RiskDecision(
        vendor_id="V-002",
        total_score=52,
        status="ESCALATED",
        reasons=["FAIL-CLOSED: vendor processes personal data without DPA → minimum ESCALATED"],
        required_actions=["Mandatory human review. Escalate to compliance officer."],
        human_review_required=True,
        confidence=0.82,
        security_score=58,
        privacy_score=52,
        financial_score=74,
        evidence_completeness=38,
    )

    room = BandChatRoom()
    # Simulate trace
    room.agent_says("@VendorCoordinator", "Routing plan created")
    room.agent_says("@SecurityReviewer", "Assessment complete")
    room.agent_says("@PrivacyReviewer", "Assessment complete")
    room.agent_says("@FinancialReviewer", "Assessment complete")
    room.agent_says("@RiskScorer", "Final decision")

    record = create_audit_trail(profile, decision, room)
    print(room.format_for_display())
    print(f"\nAudit Record: {record.model_dump_json(indent=2)}")
