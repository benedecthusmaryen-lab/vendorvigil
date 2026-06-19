"""
VendorVigil — @FinancialReviewer (Financial Specialist Agent)
Framework: Pydantic AI (agent framework)
Provider:  Featherless (provider/gateway for open-source models)
Role:     Assess vendor financial stability, operational risk, and indicators.

This agent uses Pydantic AI + Featherless (open-source models).
The output is a FinancialAssessment — validated against Pydantic schema.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from utils.band_helpers import BandChatRoom
from utils.partner_clients import (
    call_featherless,
    get_mock_specialist,
    ProviderResult,
    USE_MOCK,
)
from utils.schemas import FinancialAssessment

logger = logging.getLogger(__name__)

HANDLE = "@FinancialReviewer"

SYSTEM_PROMPT = """You are @FinancialReviewer, a financial risk assessment specialist agent.
Review indicators: founding year, funding, operational status, and negative notes.
Use financial reasoning, then provide:
- score 0-100
- findings (findings)
- risk_notes (risk indicators)
- confidence (0.0 - 1.0)

Output must be JSON conforming to the FinancialAssessment schema."""


def assess_financial_with_llm(vendor_profile: dict) -> ProviderResult:
    """Call Featherless for open-source financial analysis."""
    indicators = vendor_profile.get("financial_indicators", {})
    user_prompt = f"""Vendor Data:
- Name: {vendor_profile.get('vendor_name')}
- Service: {vendor_profile.get('service_type')}

Financial Indicators:
- Founded Year: {indicators.get('founded_year')}
- Funding: {indicators.get('funding')}
- Operational Status: {indicators.get('operational_status')}
- Negative Notes: {indicators.get('negative_notes')}

Provide assessment in JSON:
{{"vendor_id": "...", "score": 0-100, "findings": [...], "risk_notes": [...], "confidence": 0.0-1.0}}"""

    return call_featherless(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model="Qwen/Qwen3.6-27B",
        temperature=0.2,
        max_tokens=1024,
    )


def assess_financial(vendor_profile: dict, room: BandChatRoom) -> FinancialAssessment:
    """Run financial assessment using deterministic scoring + LLM reasoning."""
    vendor_id = vendor_profile.get("vendor_id", "UNKNOWN")
    vendor_name = vendor_profile.get("vendor_name", "Unnamed Vendor")

    if USE_MOCK:
        mock = get_mock_specialist(vendor_name.lower().replace(" ", "").replace("-", ""), "financial")
        if mock:
            assessment = FinancialAssessment(**mock)
            room.agent_says(
                HANDLE,
                f"Financial assessment complete for {vendor_name}. "
                f"Score: {assessment.score}/100. Risk indicators: {len(assessment.risk_notes)}.",
            )
            return assessment

    # Real LLM path (skip in mock mode)
    result = assess_financial_with_llm(vendor_profile) if not USE_MOCK else ProviderResult(content='[MOCK]', provider='mock')
    if USE_MOCK or result.error or not result.content:
        indicators = vendor_profile.get("financial_indicators", {})
        negative_notes = indicators.get("negative_notes", [])
        score = 100 - min(len(negative_notes) * 25, 100)
        assessment = FinancialAssessment(
            vendor_id=vendor_id,
            score=score,
            findings=[indicators.get("funding", ""), indicators.get("operational_status", "")],
            risk_notes=negative_notes,
            confidence=0.85,
        )
    else:
        try:
            data = json.loads(result.content)
            assessment = FinancialAssessment(**data)
        except Exception:
            assessment = FinancialAssessment(
                vendor_id=vendor_id,
                score=50,
                findings=[],
                risk_notes=["LLM parse error"],
                confidence=0.3,
            )

    room.agent_says(
        HANDLE,
        f"Financial assessment complete for {vendor_name}. Score: {assessment.score}/100.",
    )

    return assessment


def run(vendor_profile: dict, room: BandChatRoom) -> FinancialAssessment:
    """Public entry point for @FinancialReviewer."""
    room.agent_says(HANDLE, f"Starting financial assessment for {vendor_profile.get('vendor_name', 'Unknown')}...")
    return assess_financial(vendor_profile, room)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from pathlib import Path
    profile_path = Path(__file__).parent.parent / "data" / "vendor_scenarios" / "cloud_pay_x.json"
    profile = json.loads(profile_path.read_text())

    room = BandChatRoom()
    result = assess_financial(profile, room)
    print(room.format_for_display())
    print(f"\nFinancial Assessment: {result.model_dump_json(indent=2)}")
