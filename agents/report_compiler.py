"""
VendorVigil — @ReportCompiler (Report Generator Agent)
Framework: Pydantic AI (agent framework)
Provider:  AI/ML API (provider/gateway for frontier models)
Role:     Synthesize all assessments, audit record, and risk decision into a
          human-readable FinalReport for the Streamlit dashboard.

This is the final agent in the pipeline. Output goes directly to the UI.
The output is a FinalReport — validated against Pydantic schema.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from utils.band_helpers import BandChatRoom
from utils.partner_clients import (
    call_aiml_api,
    ProviderResult,
    USE_MOCK,
)
from utils.schemas import (
    AssessmentBundle,
    AuditRecord,
    FinalReport,
    RiskDecision,
)

logger = logging.getLogger(__name__)

HANDLE = "@ReportCompiler"

SYSTEM_PROMPT = """You are @ReportCompiler, the final report generation agent for VendorVigil.
You synthesize all agent findings and write a report for the decision maker.
Your tasks:
1. Summarize assessment results from all domains
2. Write a clear and actionable executive_summary
3. Create concrete recommendations for next steps
4. Include disclaimer: VendorVigil is a decision support tool, not an official auditor.

Output format JSON with keys:
- vendor_name, vendor_id, status, total_score
- domain_scores (dict: security, privacy, financial, evidence)
- missing_evidence (array)
- recommendations (array)
- audit_id
- executive_summary (string, 2-3 sentences)
- human_review_required (bool)
- agent_trace (array)
"""


def generate_report_with_llm(
    vendor_profile: dict,
    risk_decision: RiskDecision,
    audit_record: AuditRecord,
    bundle: AssessmentBundle,
) -> ProviderResult:
    """Call AI/ML API for executive summary and recommendations."""
    context = {
        "vendor_name": vendor_profile.get("vendor_name"),
        "vendor_id": vendor_profile.get("vendor_id"),
        "status": risk_decision.status,
        "total_score": risk_decision.total_score,
        "domain_scores": {
            "security": risk_decision.security_score,
            "privacy": risk_decision.privacy_score,
            "financial": risk_decision.financial_score,
            "evidence": risk_decision.evidence_completeness,
        },
        "missing_evidence": [],
        "human_review_required": risk_decision.human_review_required,
        "reasons": risk_decision.reasons,
    }

    if bundle.security:
        for gap in bundle.security.missing_evidence:
            if gap not in context["missing_evidence"]:
                context["missing_evidence"].append(gap)
    if bundle.privacy:
        for gap in bundle.privacy.missing_evidence:
            if gap not in context["missing_evidence"]:
                context["missing_evidence"].append(gap)

    user_prompt = json.dumps(context, indent=2)
    return call_aiml_api(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model="Qwen/Qwen3.6-35B-A3B",
        temperature=0.3,
        max_tokens=1024,
    )


def generate_report(
    vendor_profile: dict,
    bundle: AssessmentBundle,
    risk_decision: RiskDecision,
    audit_record: AuditRecord,
    room: BandChatRoom,
) -> FinalReport:
    """Synthesize the final report for the dashboard."""
    vendor_id = vendor_profile.get("vendor_id", "UNKNOWN")
    vendor_name = vendor_profile.get("vendor_name", "Unnamed Vendor")

    # Collect all missing evidence
    missing_evidence: list[str] = []
    if bundle.security:
        missing_evidence.extend(bundle.security.missing_evidence)
    if bundle.privacy:
        missing_evidence.extend(bundle.privacy.missing_evidence)

    # Build recommendations from required actions
    recommendations = list(risk_decision.required_actions)

    # Add specific recommendations based on gaps
    if bundle.security:
        for gap in bundle.security.critical_gaps:
            recommendations.append(f"Security: {gap}")
    if bundle.privacy:
        for gap in bundle.privacy.critical_gaps:
            recommendations.append(f"Privacy: {gap}")

    if risk_decision.human_review_required:
        recommendations.append("Schedule human review immediately before contract.")

    # Try LLM for executive summary
    executive_summary = ""
    if not USE_MOCK:
        result = generate_report_with_llm(
            vendor_profile, risk_decision, audit_record, bundle
        )
        if result.content:
            try:
                data = json.loads(result.content)
                executive_summary = data.get("executive_summary", "")
                # Merge LLM recommendations
                llm_recs = data.get("recommendations", [])
                recommendations = llm_recs + recommendations
            except Exception:
                pass

    if not executive_summary:
        # Deterministic fallback executive summary
        status_msg = {
            "APPROVED": f"{vendor_name} meets minimum criteria and can proceed to contract stage with normal notes.",
            "NEEDS_REVISION": f"{vendor_name} has not met all criteria. Complete missing evidence before approval.",
            "ESCALATED": f"Decision for {vendor_name} requires human review due to fail-closed rules. Do not proceed without compliance officer approval.",
            "TEMPORARILY_REJECTED": f"{vendor_name} is not yet eligible to proceed to contract stage. Notify vendor of results and requirements.",
        }
        executive_summary = status_msg.get(
            risk_decision.status,
            f"Total score {risk_decision.total_score}/100, status {risk_decision.status}.",
        )

    # Agent trace from audit record
    agent_trace = list(audit_record.agent_trace)

    report = FinalReport(
        vendor_name=vendor_name,
        vendor_id=vendor_id,
        status=risk_decision.status,
        total_score=risk_decision.total_score,
        domain_scores={
            "security": risk_decision.security_score,
            "privacy": risk_decision.privacy_score,
            "financial": risk_decision.financial_score,
            "evidence": risk_decision.evidence_completeness,
        },
        missing_evidence=list(set(missing_evidence)),
        recommendations=recommendations,
        audit_id=audit_record.audit_id,
        executive_summary=executive_summary,
        human_review_required=risk_decision.human_review_required,
        agent_trace=agent_trace,
    )

    room.agent_says(
        HANDLE,
        f"Final report for {vendor_name} complete.\n"
        f"Summary: {executive_summary[:120]}...",
    )

    return report


def run(
    vendor_profile: dict,
    bundle: AssessmentBundle,
    risk_decision: RiskDecision,
    audit_record: AuditRecord,
    room: BandChatRoom,
) -> FinalReport:
    """Public entry point for @ReportCompiler."""
    room.agent_says(HANDLE, f"Compiling final report for {vendor_profile.get('vendor_name', 'Unknown')}...")
    return generate_report(vendor_profile, bundle, risk_decision, audit_record, room)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    import json
    from pathlib import Path

    profile_path = Path(__file__).parent.parent / "data" / "vendor_scenarios" / "cloud_pay_x.json"
    profile = json.loads(profile_path.read_text())

    from utils.schemas import (
        RiskDecision, AuditRecord, AssessmentBundle,
        SecurityAssessment, PrivacyAssessment, FinancialAssessment,
    )

    bundle = AssessmentBundle(
        vendor_profile=profile,
        security=SecurityAssessment(vendor_id="V-002", score=58, confidence=0.82),
        privacy=PrivacyAssessment(vendor_id="V-002", score=52, confidence=0.78),
        financial=FinancialAssessment(vendor_id="V-002", score=74, confidence=0.85),
    )

    decision = RiskDecision(
        vendor_id="V-002", total_score=52, status="ESCALATED",
        reasons=["FAIL-CLOSED: personal data without DPA"],
        required_actions=["Mandatory human review"], human_review_required=True,
        confidence=0.82,
    )

    record = AuditRecord(
        audit_id="VV-2026-001", vendor_id="V-002", vendor_name="CloudPayX",
        decision_status="ESCALATED", total_score=52,
        agent_trace=["@VendorCoordinator", "@SecurityReviewer", "@PrivacyReviewer", "@FinancialReviewer", "@RiskScorer"],
        human_review_required=True, confidence=0.82,
    )

    room = BandChatRoom()
    report = generate_report(profile, bundle, decision, record, room)
    print(room.format_for_display())
    print(f"\nFinal Report: {report.model_dump_json(indent=2)}")
