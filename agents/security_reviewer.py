"""
VendorVigil — @SecurityReviewer (Security Specialist Agent)
Framework: Pydantic AI (agent framework)
Provider:  AI/ML API (provider/gateway for frontier models)
Role:     Assess vendor security posture, controls, and compliance evidence.

This agent uses Pydantic AI for structured schema output.
The output is a SecurityAssessment — validated against Pydantic schema.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from utils.band_helpers import BandChatRoom
from utils.partner_clients import (
    call_aiml_api,
    get_mock_specialist,
    ProviderResult,
    USE_MOCK,
)
from utils.schemas import SecurityAssessment

logger = logging.getLogger(__name__)

HANDLE = "@SecurityReviewer"

SYSTEM_PROMPT = """You are @SecurityReviewer, a security assessment specialist agent.
Review vendor security evidence: SOC 2, ISO 27001, encryption, incident history.
Use security framework reasoning, then provide:
- score 0-100
- findings (positive findings)
- missing_evidence (evidence gaps)
- critical_gaps (critical gaps)
- confidence (0.0 - 1.0)

Output must be JSON conforming to the SecurityAssessment schema."""


def assess_security_with_llm(vendor_profile: dict) -> ProviderResult:
    """Call AI/ML API frontier model for security assessment reasoning."""
    evidence = vendor_profile.get("security_evidence", {})
    user_prompt = f"""Vendor Data:
- Name: {vendor_profile.get('vendor_name')}
- Service: {vendor_profile.get('service_type')}
- Processes Payments: {vendor_profile.get('processes_payments')}

Security Evidence:
- SOC 2: {evidence.get('soc2')}
- ISO 27001: {evidence.get('iso27001')}
- Encryption: {evidence.get('encryption')}
- Incident History: {evidence.get('incident_history')}

Provide assessment in JSON:
{{"vendor_id": "...", "score": 0-100, "findings": [...], "missing_evidence": [...], "critical_gaps": [...], "confidence": 0.0-1.0}}"""

    return call_aiml_api(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=os.getenv("AIML_MODEL_COMPLIANCE", "Qwen/Qwen3.6-27B"),
        temperature=0.2,
        max_tokens=1024,
    )


def assess_security(vendor_profile: dict, room: BandChatRoom) -> SecurityAssessment:
    """Run security assessment using deterministic scoring + LLM reasoning."""
    vendor_id = vendor_profile.get("vendor_id", "UNKNOWN")
    vendor_name = vendor_profile.get("vendor_name", "Unnamed Vendor")

    # Try mock first
    if USE_MOCK:
        mock = get_mock_specialist(vendor_name.lower().replace(" ", "").replace("-", ""), "security")
        if mock:
            assessment = SecurityAssessment(**mock)
            room.agent_says(
                HANDLE,
                f"Security assessment complete for {vendor_name}. "
                f"Score: {assessment.score}/100. Confidence: {assessment.confidence:.0%}. "
                f"Critical gaps: {len(assessment.critical_gaps)}.",
            )
            logger.info(f"Security assessment (mock): {vendor_name} score={assessment.score}")
            return assessment

    # Real LLM path (skip in mock mode)
    result = assess_security_with_llm(vendor_profile) if not USE_MOCK else ProviderResult(content='[MOCK]', provider='mock')
    if USE_MOCK or result.error or not result.content:
        # Fallback to basic deterministic
        evidence = vendor_profile.get("security_evidence", {})
        score = 0
        findings: list[str] = []
        if evidence.get("soc2"):
            score += 30
            findings.append("SOC 2 available")
        else:
            findings.append("SOC 2 not available")
        if evidence.get("iso27001"):
            score += 25
            findings.append("ISO 27001 available")
        else:
            findings.append("ISO 27001 not available")
        if evidence.get("encryption") not in ("", "not available"):
            score += 25
            findings.append(f"Encryption: {evidence.get('encryption')}")
        else:
            findings.append("Encryption not available")
        if evidence.get("incident_history") not in ("", "not available"):
            score += 20
            findings.append(f"Incident history: {evidence.get('incident_history')}")
        else:
            findings.append("Incident history not available")

        missing_evidence = [
            k for k, v in evidence.items() if not v or v in ("", "not available")
        ]
        critical_gaps = [
            k for k, v in evidence.items()
            if (not v or v in ("", "not available")) and k in ("soc2", "iso27001")
        ]
        assessment = SecurityAssessment(
            vendor_id=vendor_id,
            score=score,
            findings=findings,
            missing_evidence=missing_evidence,
            critical_gaps=critical_gaps,
            confidence=0.85,
        )
    else:
        try:
            # LLMs often wrap JSON in markdown code blocks — strip them
            raw = result.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3].strip()
                # Remove optional language tag like ```json
                if raw.startswith("json\n"):
                    raw = raw[5:].strip()
            data = json.loads(raw)
            assessment = SecurityAssessment(**data)
        except Exception as e:
            logger.warning(f"LLM JSON parse failed, falling back: {e}")
            assessment = SecurityAssessment(
                vendor_id=vendor_id,
                score=50,
                findings=[],
                missing_evidence=["LLM parse error"],
                critical_gaps=[],
                confidence=0.3,
            )

    room.agent_says(
        HANDLE,
        f"Security assessment complete for {vendor_name}. "
        f"Score: {assessment.score}/100. "
        f"Critical gaps: {len(assessment.critical_gaps)}.",
    )

    return assessment


def run(vendor_profile: dict, room: BandChatRoom) -> SecurityAssessment:
    """Public entry point for @SecurityReviewer."""
    room.agent_says(HANDLE, f"Starting security assessment for {vendor_profile.get('vendor_name', 'Unknown')}...")
    return assess_security(vendor_profile, room)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from pathlib import Path
    profile_path = Path(__file__).parent.parent / "data" / "vendor_scenarios" / "cloud_pay_x.json"
    profile = json.loads(profile_path.read_text())

    room = BandChatRoom()
    result = assess_security(profile, room)
    print(room.format_for_display())
    print(f"\nSecurity Assessment: {result.model_dump_json(indent=2)}")
