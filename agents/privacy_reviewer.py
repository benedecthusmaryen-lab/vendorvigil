"""
VendorVigil — @PrivacyReviewer (Privacy Specialist Agent)
Framework: Pydantic AI (agent framework)
Provider:  AI/ML API (provider/gateway for frontier models)
Role:     Assess vendor privacy posture, data handling, and compliance.

This agent uses Pydantic AI for structured schema output.
The output is a PrivacyAssessment — validated against Pydantic schema.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from utils.band_helpers import BandChatRoom
from utils.partner_clients import (
    call_aiml_api,
    get_mock_specialist,
    ProviderResult,
    USE_MOCK,
)
from utils.schemas import PrivacyAssessment

logger = logging.getLogger(__name__)

HANDLE = "@PrivacyReviewer"

SYSTEM_PROMPT = """You are @PrivacyReviewer, a privacy assessment specialist agent.
Review: whether vendor processes personal data, whether DPA is available, data retention policy, and data location.
Use privacy reasoning, then provide:
- score 0-100
- personal_data_processed (true/false)
- findings (findings)
- missing_evidence (evidence gaps)
- critical_gaps (critical gaps)
- confidence (0.0 - 1.0)

Output must be JSON conforming to the PrivacyAssessment schema."""


def assess_privacy_with_llm(vendor_profile: dict) -> ProviderResult:
    """Call AI/ML API frontier model for privacy assessment reasoning."""
    evidence = vendor_profile.get("privacy_evidence", {})
    user_prompt = f"""Vendor Data:
- Name: {vendor_profile.get('vendor_name')}
- Service: {vendor_profile.get('service_type')}
- Processes Personal Data: {vendor_profile.get('processes_personal_data')}
- Data Types: {vendor_profile.get('data_types')}

Privacy Evidence:
- DPA: {evidence.get('dpa')}
- Data Location: {evidence.get('data_location')}
- Data Retention: {evidence.get('data_retention')}

Provide assessment in JSON:
{{"vendor_id": "...", "score": 0-100, "personal_data_processed": true/false, "findings": [...], "missing_evidence": [...], "critical_gaps": [...], "confidence": 0.0-1.0}}"""

    return call_aiml_api(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model="Qwen/Qwen3.6-27B",
        temperature=0.2,
        max_tokens=1024,
    )


def assess_privacy(vendor_profile: dict, room: BandChatRoom) -> PrivacyAssessment:
    """Run privacy assessment using deterministic scoring + LLM reasoning."""
    vendor_id = vendor_profile.get("vendor_id", "UNKNOWN")
    vendor_name = vendor_profile.get("vendor_name", "Unnamed Vendor")
    processes_personal = vendor_profile.get("processes_personal_data", False)

    if USE_MOCK:
        mock = get_mock_specialist(vendor_name.lower().replace(" ", "").replace("-", ""), "privacy")
        if mock:
            assessment = PrivacyAssessment(**mock)
            room.agent_says(
                HANDLE,
                f"Privacy assessment complete for {vendor_name}. "
                f"Score: {assessment.score}/100. Personal data: {'Yes' if assessment.personal_data_processed else 'No'}.",
            )
            logger.info(f"Privacy assessment (mock): {vendor_name} score={assessment.score}")
            return assessment

    # Real LLM path (skip in mock mode)
    result = assess_privacy_with_llm(vendor_profile) if not USE_MOCK else ProviderResult(content='[MOCK]', provider='mock')
    if USE_MOCK or result.error or not result.content:
        evidence = vendor_profile.get("privacy_evidence", {})
        score = 0
        findings: list[str] = []
        if evidence.get("dpa"):
            score += 40
            findings.append("DPA available")
        else:
            findings.append("DPA not available")
        if evidence.get("data_location") not in ("", "unclear"):
            score += 30
            findings.append(f"Data location: {evidence.get('data_location')}")
        else:
            findings.append("Data location unclear")
        if evidence.get("data_retention") not in ("", "not available"):
            score += 30
            findings.append(f"Data retention: {evidence.get('data_retention')}")
        else:
            findings.append("Data retention not available")

        missing = [
            k for k, v in evidence.items() if not v or v in ("", "unclear", "not available")
        ]
        critical = ["DPA not available"] if (not evidence.get("dpa") and processes_personal) else []
        assessment = PrivacyAssessment(
            vendor_id=vendor_id,
            score=score,
            personal_data_processed=processes_personal,
            findings=findings,
            missing_evidence=missing,
            critical_gaps=critical,
            confidence=0.85,
        )
        assessment.critical_gaps = [g for g in assessment.critical_gaps if g]
    else:
        try:
            data = json.loads(result.content)
            assessment = PrivacyAssessment(**data)
        except Exception:
            assessment = PrivacyAssessment(
                vendor_id=vendor_id,
                score=50,
                personal_data_processed=processes_personal,
                findings=[],
                missing_evidence=["LLM parse error"],
                critical_gaps=[],
                confidence=0.3,
            )

    room.agent_says(
        HANDLE,
        f"Privacy assessment complete for {vendor_name}. Score: {assessment.score}/100.",
    )

    return assessment


def run(vendor_profile: dict, room: BandChatRoom) -> PrivacyAssessment:
    """Public entry point for @PrivacyReviewer."""
    room.agent_says(HANDLE, f"Starting privacy assessment for {vendor_profile.get('vendor_name', 'Unknown')}...")
    return assess_privacy(vendor_profile, room)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from pathlib import Path
    profile_path = Path(__file__).parent.parent / "data" / "vendor_scenarios" / "cloud_pay_x.json"
    profile = json.loads(profile_path.read_text())

    room = BandChatRoom()
    result = assess_privacy(profile, room)
    print(room.format_for_display())
    print(f"\nPrivacy Assessment: {result.model_dump_json(indent=2)}")
