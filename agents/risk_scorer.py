"""
VendorVigil — @RiskScorer (Risk Scoring Agent)
Framework: Pydantic AI (agent framework)
Provider:  Featherless (provider/gateway for open-source models)
Role:     Compute final risk score, apply fail-closed rules, produce RiskDecision.

This agent COMBINES deterministic Python scoring with LLM reasoning.
Scoring is ALWAYS deterministic — LLMs only provide reasoning/explanation.
The output is a RiskDecision — validated against Pydantic schema.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from utils.band_helpers import BandChatRoom
from utils.partner_clients import (
    call_featherless,
    ProviderResult,
    USE_MOCK,
)
from utils.schemas import (
    AssessmentBundle,
    RiskDecision,
    SecurityAssessment,
    PrivacyAssessment,
    FinancialAssessment,
)
from utils.scoring import (
    compute_total_score,
    compute_evidence_completeness,
    status_for_score,
    apply_fail_closed_rules,
)

logger = logging.getLogger(__name__)

HANDLE = "@RiskScorer"


def compute_risk_decision(
    vendor_profile: dict,
    bundle: AssessmentBundle,
    room: BandChatRoom,
) -> RiskDecision:
    """Compute final risk decision: score + fail-closed rules + LLM reasoning."""
    vendor_id = vendor_profile.get("vendor_id", "UNKNOWN")
    vendor_name = vendor_profile.get("vendor_name", "Unnamed Vendor")

    # 1. Compute evidence completeness (deterministic)
    evidence = compute_evidence_completeness(vendor_profile)

    # 2. Extract sub-scores from specialist assessments
    security_score = bundle.security.score if bundle.security else 0
    privacy_score = bundle.privacy.score if bundle.privacy else 0
    financial_score = bundle.financial.score if bundle.financial else 0

    # 3. Compute weighted total score (deterministic)
    total_score = compute_total_score(
        security=security_score,
        privacy=privacy_score,
        financial=financial_score,
        evidence_completeness=evidence,
    )

    # 4. Get raw status
    raw_status = status_for_score(total_score)

    # 5. Apply fail-closed rules (deterministic)
    final_status, fail_reasons, human_review = apply_fail_closed_rules(
        vendor_profile=vendor_profile,
        security=bundle.security or SecurityAssessment(vendor_id=vendor_id, score=0, confidence=0.0),
        privacy=bundle.privacy or PrivacyAssessment(vendor_id=vendor_id, score=0, confidence=0.0),
        financial=bundle.financial or FinancialAssessment(vendor_id=vendor_id, score=0, confidence=0.0),
        raw_score=total_score,
        raw_status=raw_status,
    )

    required_actions: list[str] = []
    if final_status == "APPROVED":
        required_actions.append("Vendor can proceed to contract stage with normal notes.")
    elif final_status == "NEEDS_REVISION":
        required_actions.append("Request vendor to complete missing evidence before approval.")
    elif final_status == "ESCALATED":
        required_actions.append("Mandatory human review. Escalate to compliance officer.")
    elif final_status == "TEMPORARILY_REJECTED":
        required_actions.append("Vendor not yet eligible. Notify vendor of the results.")

    # Compute confidence from specialists
    confidences = []
    if bundle.security:
        confidences.append(bundle.security.confidence)
    if bundle.privacy:
        confidences.append(bundle.privacy.confidence)
    if bundle.financial:
        confidences.append(bundle.financial.confidence)
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    decision = RiskDecision(
        vendor_id=vendor_id,
        total_score=total_score,
        status=final_status,
        reasons=fail_reasons,
        required_actions=required_actions,
        human_review_required=human_review,
        confidence=avg_confidence,
        security_score=security_score,
        privacy_score=privacy_score,
        financial_score=financial_score,
        evidence_completeness=evidence,
    )

    # Band Chat: announce decision
    status_emoji = {
        "APPROVED": "✅",
        "NEEDS_REVISION": "⚠️",
        "ESCALATED": "🔴",
        "TEMPORARILY_REJECTED": "🚫",
    }
    room.agent_says(
        HANDLE,
        f"Final risk decision for {vendor_name}: "
        f"{status_emoji.get(final_status, '')} {final_status}. "
        f"Total score: {total_score}/100.\n"
        f"Sub-scores: Security {security_score}, Privacy {privacy_score}, "
        f"Financial {financial_score}, Evidence {evidence}.\n"
        f"Human review: {'Required' if human_review else 'Not required'}.",
    )

    return decision


def run(
    vendor_profile: dict,
    bundle: AssessmentBundle,
    room: BandChatRoom,
) -> RiskDecision:
    """Public entry point for @RiskScorer."""
    room.agent_says(HANDLE, f"Received assessment bundle for {vendor_profile.get('vendor_name', 'Unknown')}, computing score...")
    return compute_risk_decision(vendor_profile, bundle, room)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from pathlib import Path
    profile_path = Path(__file__).parent.parent / "data" / "vendor_scenarios" / "cloud_pay_x.json"
    profile = json.loads(profile_path.read_text())

    # Simulate specialist outputs
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    bundle = AssessmentBundle(
        vendor_profile=profile,
        security=SecurityAssessment(vendor_id="V-002", score=58, confidence=0.82, critical_gaps=["SOC 2 not available"]),
        privacy=PrivacyAssessment(vendor_id="V-002", score=52, confidence=0.78, critical_gaps=["DPA not available"]),
        financial=FinancialAssessment(vendor_id="V-002", score=74, confidence=0.85),
    )

    room = BandChatRoom()
    decision = compute_risk_decision(profile, bundle, room)
    print(room.format_for_display())
    print(f"\nRisk Decision: {decision.model_dump_json(indent=2)}")
