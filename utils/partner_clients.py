"""
VendorVigil — Partner API Clients
Handles AI/ML API, Featherless AI, and fallback to deterministic mock.
Architecture: providers are model gateways, NOT agent frameworks.
"""

from __future__ import annotations

import os
import logging
import json
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ---
# Config
# ---

AIML_BASE_URL = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")
FEATHERLESS_BASE_URL = os.getenv("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")


def _use_mock() -> bool:
    """Lazy-check mock mode from env (supports dotenv)."""
    return os.getenv("USE_MOCK_PROVIDER", "true").lower() == "true"


# Module-level export for backward compatibility
USE_MOCK = _use_mock()


def _get_aiml_client():
    """Lazy-load AI/ML API client."""
    try:
        from openai import OpenAI
        api_key = os.getenv("AIML_API_KEY", "")
        if not api_key:
            logger.warning("AIML_API_KEY not set, using mock fallback")
            return None
        return OpenAI(base_url=AIML_BASE_URL, api_key=api_key)
    except ImportError:
        logger.warning("openai package not installed, using mock fallback")
        return None


def _get_featherless_client():
    """Lazy-load Featherless client."""
    try:
        from openai import OpenAI
        api_key = os.getenv("FEATHERLESS_API_KEY", "")
        if not api_key:
            logger.warning("FEATHERLESS_API_KEY not set, using mock fallback")
            return None
        return OpenAI(base_url=FEATHERLESS_BASE_URL, api_key=api_key)
    except ImportError:
        logger.warning("openai package not installed, using mock fallback")
        return None


# ---
# Call Result
# ---

@dataclass
class ProviderResult:
    """Unified result from any provider call."""
    content: str = ""
    model: str = ""
    provider: str = "mock"
    is_mock: bool = True
    error: str | None = None
    metadata: dict = field(default_factory=dict)


# ---
# Mock Data — Deterministic outputs per agent role
# ---

MOCK_RESPONSES: dict[str, dict[str, Any]] = {
    "koordinator": {
        "cloudpayx": {
            "vendor_id": "V-002",
            "vendor_name": "CloudPayX",
            "vendor_type": "Payment processing and customer transaction storage",
            "requires_security_check": True,
            "requires_privacy_check": True,
            "requires_financial_check": True,
            "reason": [
                "Vendor processes customer personal data",
                "Vendor processes payment transactions",
                "Comprehensive assessment across three domains required",
            ],
        },
    },
    "security": {
        "cloudpayx": {
            "vendor_id": "V-002",
            "score": 58,
            "findings": [
                "ISO 27001 available",
                "Vendor mentions data encryption during transmission",
            ],
            "missing_evidence": [
                "SOC 2 not available",
                "Encryption key rotation evidence not available",
                "Incident history not available",
            ],
            "critical_gaps": [
                "SOC 2 not available for payment vendor — critical gap",
            ],
            "confidence": 0.82,
        },
    },
    "privacy": {
        "cloudpayx": {
            "vendor_id": "V-002",
            "score": 52,
            "personal_data_processed": True,
            "findings": [
                "Vendor identifies categories of data processed",
            ],
            "missing_evidence": [
                "DPA not available",
                "Data storage location unclear",
                "Data retention policy not available",
            ],
            "critical_gaps": [
                "Vendor processes personal data without DPA — critical gap",
            ],
            "confidence": 0.78,
        },
    },
    "financial": {
        "cloudpayx": {
            "vendor_id": "V-002",
            "score": 74,
            "findings": [
                "Vendor is operationally active",
                "Series A funding indicates investor confidence",
            ],
            "risk_notes": [
                "Funding history incomplete",
                "Financial stability report not available",
            ],
            "confidence": 0.85,
        },
    },
}


# ---
# API Call Functions
# ---

def call_aiml_api(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> ProviderResult:
    """Call AI/ML API for frontier reasoning tasks.

    AI/ML API is a provider/gateway, NOT a framework.
    """
    model_name = model or os.getenv("AIML_MODEL_MAIN", "google/gemini-3-flash-preview")

    if _use_mock():
        logger.info(f"[MOCK] AI/ML API call skipped — model={model_name}")
        return ProviderResult(
            content=json.dumps({"info": "mock_response"}),
            model=model_name,
            provider="aimlapi",
        )

    client = _get_aiml_client()
    if client is None:
        logger.warning("AI/ML API client unavailable, using mock fallback")
        return ProviderResult(
            content="[FALLBACK] AI/ML API client not available",
            model=model_name,
            provider="aimlapi",
        )

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content or ""
        return ProviderResult(
            content=content,
            model=model_name,
            provider="aimlapi",
            is_mock=False,
            metadata={
                "usage": {
                    "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                    "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                }
            },
        )
    except Exception as e:
        logger.error(f"AI/ML API call failed: {e}")
        return ProviderResult(
            content=f"[ERROR] AI/ML API call failed: {e}",
            model=model_name,
            provider="aimlapi",
            error=str(e),
        )


def call_featherless(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> ProviderResult:
    """Call Featherless AI for open-source model inference.

    Featherless is a provider/gateway for open-weight models, NOT a framework.
    """
    model_name = model or os.getenv(
        "FEATHERLESS_MODEL_SECOND_OPINION", "Qwen/Qwen3.6-35B-A3B"
    )

    if _use_mock():
        logger.info(f"[MOCK] Featherless call skipped — model={model_name}")
        return ProviderResult(
            content=json.dumps({"info": "mock_response"}),
            model=model_name,
            provider="featherless",
        )

    client = _get_featherless_client()
    if client is None:
        logger.warning("Featherless client unavailable, using mock fallback")
        return ProviderResult(
            content="[FALLBACK] Featherless client not available",
            model=model_name,
            provider="featherless",
        )

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = resp.choices[0].message.content or ""
        return ProviderResult(
            content=content,
            model=model_name,
            provider="featherless",
            is_mock=False,
            metadata={
                "usage": {
                    "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                    "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
                }
            },
        )
    except Exception as e:
        logger.error(f"Featherless call failed: {e}")
        return ProviderResult(
            content=f"[ERROR] Featherless call failed: {e}",
            model=model_name,
            provider="featherless",
            error=str(e),
        )


def get_mock_specialist(vendor_key: str, agent_role: str) -> dict:
    """Return deterministic mock output for a specialist agent."""
    return MOCK_RESPONSES.get(agent_role, {}).get(vendor_key, {})
