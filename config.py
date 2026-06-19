"""
VendorVigil — Configuration & Model Providers
=============================================
All environment variables, provider initialization, and model factory
functions live here. To switch AI providers or models, just edit the
.env file or change the defaults below.

Usage:
    from config import make_model, USE_MOCK_PROVIDER, ROOM_ID
    model = make_model("gemini-2.5-flash", provider="gemini")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from utils.schemas import AgentRole

load_dotenv(override=True)

logger = logging.getLogger("vendorvigil.config")

# ---
# Band Configuration
# ---

ROOM_ID: str = os.getenv("BAND_ROOM_ID", "")

# ---
# Provider Keys & URLs — change these in .env to switch providers
# ---

# AI/ML API
AIML_KEY: str = os.getenv("AIML_API_KEY", "")
AIML_BASE: str = os.getenv("AIML_BASE_URL", "https://api.aimlapi.com/v1")

# OpenRouter (unified API — hundreds of models, OpenAI-compatible)
OR_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OR_BASE: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Groq (fast, generous free tier — 30 RPM)
GROQ_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_BASE: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Gemini (Google)
GEMINI_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE: str = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/v1",
)

# Per-agent Gemini model overrides (read from .env)
# Legacy shared vars (kept for backward compat)
GEMINI_MODEL_MAIN: str = os.getenv("GEMINI_MODEL_MAIN", "gemini-2.5-flash")
GEMINI_MODEL_REASONING: str = os.getenv("GEMINI_MODEL_REASONING", GEMINI_MODEL_MAIN)
GEMINI_MODEL_COMPLIANCE: str = os.getenv("GEMINI_MODEL_COMPLIANCE", GEMINI_MODEL_MAIN)
GEMINI_MODEL_FINANCIAL: str = os.getenv("GEMINI_MODEL_FINANCIAL", GEMINI_MODEL_MAIN)
GEMINI_MODEL_AUDIT: str = os.getenv("GEMINI_MODEL_AUDIT", GEMINI_MODEL_MAIN)
GEMINI_MODEL_SECOND_OPINION: str = os.getenv("GEMINI_MODEL_SECOND_OPINION", GEMINI_MODEL_MAIN)

# Per-agent model allocation (new — overrides shared vars above)
MODEL_VENDOR_COORDINATOR: str = os.getenv("MODEL_VENDOR_COORDINATOR", "gemini-2.5-flash")
MODEL_SECURITY_REVIEWER: str = os.getenv("MODEL_SECURITY_REVIEWER", "gemini-2.5-pro")
MODEL_PRIVACY_REVIEWER: str = os.getenv("MODEL_PRIVACY_REVIEWER", "gemini-2.5-pro")
MODEL_FINANCE_REVIEWER: str = os.getenv("MODEL_FINANCE_REVIEWER", "gemini-2.5-flash")
MODEL_RISK_SCORER: str = os.getenv("MODEL_RISK_SCORER", "gemini-2.5-flash")
MODEL_AUDIT_LOGGER: str = os.getenv("MODEL_AUDIT_LOGGER", "gemini-3.1-flash-lite")
MODEL_REPORT_COMPILER: str = os.getenv("MODEL_REPORT_COMPILER", "gemini-3.1-flash-lite")

# Per-agent PROVIDER allocation (gemini, groq, openrouter)
PROVIDER_VENDOR_COORDINATOR: str = os.getenv("PROVIDER_VENDOR_COORDINATOR", "gemini")
PROVIDER_SECURITY_REVIEWER: str = os.getenv("PROVIDER_SECURITY_REVIEWER", "gemini")
PROVIDER_PRIVACY_REVIEWER: str = os.getenv("PROVIDER_PRIVACY_REVIEWER", "gemini")
PROVIDER_FINANCE_REVIEWER: str = os.getenv("PROVIDER_FINANCE_REVIEWER", "gemini")
PROVIDER_RISK_SCORER: str = os.getenv("PROVIDER_RISK_SCORER", "groq")
PROVIDER_AUDIT_LOGGER: str = os.getenv("PROVIDER_AUDIT_LOGGER", "groq")
PROVIDER_REPORT_COMPILER: str = os.getenv("PROVIDER_REPORT_COMPILER", "gemini")

# Mock mode — set USE_MOCK_PROVIDER=true in .env for deterministic testing
USE_MOCK_PROVIDER: bool = os.getenv("USE_MOCK_PROVIDER", "false").lower() == "true"

# Concurrency limit — PER PROVIDER semaphores (each provider has its own rate limit)
GEMINI_CONCURRENCY: int = int(os.getenv("GEMINI_CONCURRENCY_LIMIT", "2"))
GROQ_CONCURRENCY: int = int(os.getenv("GROQ_CONCURRENCY_LIMIT", "4"))
OR_CONCURRENCY: int = int(os.getenv("OPENROUTER_CONCURRENCY_LIMIT", "4"))

GEMINI_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(GEMINI_CONCURRENCY)
GROQ_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(GROQ_CONCURRENCY)
OR_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(OR_CONCURRENCY)

# Legacy compat — default semaphore (Gemini)
MODEL_SEMAPHORE = GEMINI_SEMAPHORE

# Delay between API calls (seconds) — spreads requests to avoid rate limits
RESPONSE_DELAY_SEC: float = float(os.getenv("RESPONSE_DELAY_SEC", "4"))

# Max retries on 429 rate limit errors
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))

# Retry backoff base (seconds) — doubles each retry
RETRY_BACKOFF_SEC: float = float(os.getenv("RETRY_BACKOFF_SEC", "10"))

# Startup stagger between agents (seconds)
STARTUP_STAGGER: float = float(os.getenv("GEMINI_STARTUP_STAGGER_SEC", os.getenv("STARTUP_STAGGER_SEC", "2")))

# Max agents to start (0 = all)
MAX_AGENT_COUNT: int = int(os.getenv("MAX_AGENT_COUNT", "0"))


# ---
# Provider Initialization
# ---

def _init_provider(api_key: str, base_url: str, label: str):
    """Initialize an OpenAI-compatible provider. Returns None on failure."""
    if not api_key:
        logger.info("%s not configured — disabled.", label)
        return None
    try:
        from pydantic_ai.providers.openai import OpenAIProvider
        provider = OpenAIProvider(api_key=api_key, base_url=base_url)
        logger.info("%s provider enabled.", label)
        return provider
    except Exception as e:
        logger.warning("Failed to initialize %s: %s", label, e)
        return None


aiml_provider = _init_provider(AIML_KEY, AIML_BASE, "AI/ML API")
or_provider = _init_provider(OR_KEY, OR_BASE, "OpenRouter")
gemini_provider = _init_provider(GEMINI_KEY, GEMINI_BASE, "Gemini")
groq_provider = _init_provider(GROQ_KEY, GROQ_BASE, "Groq")


# ---
# Model Factories — call make_model() to create a model for any agent
# ---

def _make_openai_model(model_id: str, provider) -> "OpenAIChatModel":
    """Create a Pydantic AI OpenAIChatModel with the given provider."""
    from pydantic_ai.models.openai import OpenAIChatModel
    if provider is None:
        return OpenAIChatModel(model_id)
    return OpenAIChatModel(model_id, provider=provider)


def aiml_model(model_id: str):
    """Model pointed at AI/ML API. Falls back to OpenRouter."""
    return _make_openai_model(model_id, aiml_provider or or_provider)


def or_model(model_id: str):
    """Model pointed at OpenRouter (unified API, hundreds of models).
    Returns MockModel when USE_MOCK_PROVIDER=true."""
    if USE_MOCK_PROVIDER:
        return MockModel(model_id)
    provider = or_provider or gemini_provider or groq_provider
    return _make_openai_model(model_id, provider)


def groq_model(model_id: str):
    """Model pointed at Groq (fast, 30 RPM free tier).
    Returns MockModel when USE_MOCK_PROVIDER=true."""
    if USE_MOCK_PROVIDER:
        return MockModel(model_id)
    provider = groq_provider or gemini_provider or or_provider
    return _make_openai_model(model_id, provider)


def gemini_model(model_id: str):
    """Model pointed at Gemini. Falls back to OpenRouter → AIML.
    Returns MockModel when USE_MOCK_PROVIDER=true."""
    if USE_MOCK_PROVIDER:
        return MockModel(model_id)
    provider = gemini_provider or or_provider or aiml_provider
    return _make_openai_model(model_id, provider)


def live_gemini_model(model_id: str):
    """Always returns a real model for Band adapter WebSocket connection.
    Prefers Gemini, falls back to Groq → OpenRouter.
    Never returns MockModel."""
    provider = gemini_provider or groq_provider or or_provider or aiml_provider
    return _make_openai_model(model_id, provider)


def make_band_model(model_id: str, provider_name: str):
    """Create the model object passed to Band SDK (band_model).
    Uses the CORRECT provider for each agent — fixes the routing bug where
    Groq model IDs were being sent to Gemini API causing 404 errors.
    Never returns MockModel."""
    provider_map = {
        "gemini": gemini_provider,
        "groq": groq_provider,
        "openrouter": or_provider,
        "aiml": aiml_provider,
    }
    provider = provider_map.get(provider_name, gemini_provider)
    # Fallback chain if preferred provider is unavailable
    if provider is None:
        for fallback in [gemini_provider, groq_provider, or_provider, aiml_provider]:
            if fallback is not None:
                provider = fallback
                break
    return _make_openai_model(model_id, provider)


def make_model(model_id: str, provider: str = "gemini"):
    """Universal factory — create a model by provider name.

    Args:
        model_id: Model identifier (e.g. "gemini-2.5-flash", "Qwen/Qwen3.6-27B")
        provider: One of "gemini", "groq", "openrouter", "aiml", "mock"
    """
    factories = {
        "gemini": gemini_model,
        "groq": groq_model,
        "openrouter": or_model,
        "aiml": aiml_model,
        "mock": lambda mid: MockModel(mid),
    }
    factory = factories.get(provider, gemini_model)
    return factory(model_id)


def get_semaphore(provider_name: str) -> asyncio.Semaphore:
    """Return the correct semaphore for a provider (rate-limit isolation)."""
    semaphores = {
        "gemini": GEMINI_SEMAPHORE,
        "groq": GROQ_SEMAPHORE,
        "openrouter": OR_SEMAPHORE,
    }
    return semaphores.get(provider_name, GEMINI_SEMAPHORE)


# ---
# MockModel — deterministic responses without API calls
# Sequential workflow: one agent per step, matching live protocol
# ---

class MockModel:
    """Returns deterministic responses for testing without API calls.

    Coordinator mock follows the sequential 13-step workflow:
    each step dispatches exactly ONE agent.
    """

    def __init__(self, model_name: str = "mock"):
        self.model_name = model_name
        self.model = model_name

    async def __call__(self, *args, **kwargs):
        agent_role = kwargs.get("agent_role", "unknown")
        step = kwargs.get("step", 1)
        # Map canonical AgentRole values to short keys for lookup
        try:
            role_key = AgentRole(agent_role).short_key
        except (ValueError, KeyError):
            role_key = agent_role
        if role_key == "coordinator":
            return _COORDINATOR_STEPS.get(step, _COORDINATOR_STEPS.get(13, ""))
        return _MOCK_RESPONSES.get(role_key, f"Mock response for {agent_role}")


# Mock specialist responses — no raw @AgentName in body
_MOCK_RESPONSES: dict[str, str] = {
    "security": (
        "## Security Assessment: CloudPayX\n"
        "**Score: 60/100**  |  **Confidence: 0.80**\n\n"
        "| Evidence | Status |\n|---|---|\n"
        "| SOC 2 | MISSING |\n"
        "| ISO 27001 | FOUND |\n"
        "| Encryption at-rest | FOUND |\n"
        "| Encryption in-transit | FOUND |\n"
        "| Incident Response | MISSING |\n"
        "| Access Controls | FOUND |\n\n"
        "**Key Findings:**\n"
        "- ISO 27001 certified\n"
        "- SOC 2 missing\n"
        "- No incident response plan\n"
        "**Critical Gaps:**\n"
        "- SOC 2 required for payment processing"
    ),
    "privacy": (
        "## Privacy Assessment: CloudPayX\n"
        "**Score: 55/100**  |  **Confidence: 0.75**\n\n"
        "| Evidence | Status |\n|---|---|\n"
        "| DPA | MISSING |\n"
        "| Data Location | KNOWN |\n"
        "| Sub-processors | UNKNOWN |\n"
        "| Retention Policy | FOUND |\n"
        "| Cross-border Safeguards | MISSING |\n\n"
        "**Personal Data Processed:** YES\n"
        "**Key Findings:**\n"
        "- DPA not signed\n"
        "- Data location known (US)\n"
        "**Critical Gaps:**\n"
        "- DPA mandatory for personal data"
    ),
    "financial": (
        "## Financial Assessment: CloudPayX\n"
        "**Score: 70/100**  |  **Confidence: 0.85**\n\n"
        "| Criterion | Assessment |\n|---|---|\n"
        "| Years Operating | 4 years |\n"
        "| Funding Stage | Series A |\n"
        "| Revenue Signal | Moderate |\n"
        "| Runway Estimate | 18 months |\n"
        "| Credit Risk | Medium |\n\n"
        "**Financial Risk Level:** MEDIUM\n"
        "**Risk Notes:**\n"
        "- Pre-profit startup\n"
        "- Series A funded"
    ),
    "risk": (
        "## Final Risk Decision: CloudPayX\n"
        "**Status:** NEEDS_REVISION\n"
        "**Total Score:** 60/100\n\n"
        "| Category | Score |\n|---|---|\n"
        "| Security | 60/100 |\n"
        "| Privacy | 55/100 |\n"
        "| Financial | 70/100 |\n"
        "| Evidence | 55/100 |\n\n"
        "**Human Review:** YES\n"
        "**Reasoning:** Missing SOC 2 and DPA require human review before approval.\n"
        "DISCLAIMER: VendorVigil is a decision support tool."
    ),
    "report": (
        "# VendorVigil Report: CloudPayX\n"
        "**Date:** 2026-06-17\n\n"
        "## Executive Summary\n"
        "CloudPayX shows moderate risk due to missing SOC 2 and DPA. "
        "Financial stability is acceptable at Series A stage.\n\n"
        "## Risk Status: NEEDS_REVISION\n"
        "**Total Score:** 60/100\n\n"
        "## Score Breakdown\n"
        "| Category | Score |\n|---|---|\n"
        "| Security | 60/100 |\n"
        "| Privacy | 55/100 |\n"
        "| Financial | 70/100 |\n"
        "| Evidence | 55/100 |\n\n"
        "## Key Gaps & Findings\n"
        "- SOC 2 certification missing\n"
        "- DPA not signed despite processing personal data\n"
        "- No incident response plan\n\n"
        "## Recommended Actions\n"
        "1. Require SOC 2 Type II before production access\n"
        "2. Execute DPA immediately\n"
        "3. Request incident response documentation\n\n"
        "DISCLAIMER: VendorVigil is a decision support tool."
    ),
    "audit": (
        "## Audit Record\n"
        "**ID:** VV-2026-MOCK | **Vendor:** CloudPayX (V-002)\n"
        "**Status:** NEEDS_REVISION | **Score:** 60/100\n"
        "**Reviewers:** SecurityReviewer, PrivacyReviewer, FinancialReviewer, RiskScorer, ReportCompiler\n"
        "**Date:** 2026-06-17\n"
        "DISCLAIMER: VendorVigil is a decision support tool."
    ),
}

# Sequential coordinator mock — 13 steps, one dispatch per step
_COORDINATOR_STEPS: dict[int, str] = {
    1:  "Starting vendor assessment for CloudPayX. Creating routing plan.",
    2:  "Routing plan created. Dispatching SecurityReviewer for security assessment.",
    3:  "Security assessment received (60/100). Dispatching PrivacyReviewer for privacy assessment.",
    4:  "Privacy assessment received (55/100). Dispatching FinancialReviewer for financial assessment.",
    5:  "Financial assessment received (70/100). All specialists complete. Dispatching RiskScorer.",
    6:  "Risk decision received: NEEDS_REVISION (60/100). Dispatching AuditLogger.",
    7:  "Audit record created (VV-2026-MOCK). Dispatching ReportCompiler.",
    8:  "Final report compiled. Assessment complete for CloudPayX. Status: NEEDS_REVISION.",
    9:  "Assessment workflow finished. Notifying requester.",
    10: "CloudPayX assessment complete. NEEDS_REVISION (60/100). Human review required.",
    11: "Workflow step 11: wrapping up.",
    12: "Workflow step 12: finalizing.",
    13: "Workflow step 13: done.",
}

# Mock mentions — sequential, one per step, using logical role names.
# Actual transport handles are resolved by HandleResolver at runtime.
MOCK_MENTIONS: dict[str, list[str]] = {
    AgentRole.VENDOR_COORDINATOR.value: [AgentRole.SECURITY_REVIEWER.value],
    AgentRole.SECURITY_REVIEWER.value:  [AgentRole.VENDOR_COORDINATOR.value],
    AgentRole.PRIVACY_REVIEWER.value:   [AgentRole.VENDOR_COORDINATOR.value],
    AgentRole.FINANCIAL_REVIEWER.value: [AgentRole.VENDOR_COORDINATOR.value],
    AgentRole.RISK_SCORER.value:      [AgentRole.VENDOR_COORDINATOR.value],
    AgentRole.REPORT_COMPILER.value:    [AgentRole.VENDOR_COORDINATOR.value],
    AgentRole.AUDIT_LOGGER.value:     [AgentRole.VENDOR_COORDINATOR.value],
}

# Sequential coordinator mentions — one agent per step
MOCK_COORDINATOR_MENTIONS: dict[int, list[str]] = {
    1:  [],
    2:  ["SecurityReviewer"],
    3:  ["PrivacyReviewer"],
    4:  ["FinancialReviewer"],
    5:  ["RiskScorer"],
    6:  ["AuditLogger"],
    7:  ["ReportCompiler"],
    8:  [],
    9:  [],
    10: [],
    11: [],
    12: [],
    13: [],
}


# ---
# Vendor Data Loading
# ---

_VENDOR_DATA_DIR = Path(__file__).parent / "data" / "vendor_scenarios"
VENDOR_SCENARIOS: dict[str, dict] = {}

for _f in _VENDOR_DATA_DIR.glob("*.json"):
    try:
        _d = json.loads(_f.read_text())
        _key = _d.get("vendor_name", _f.stem).lower()
        VENDOR_SCENARIOS[_key] = _d
    except Exception:
        pass


def get_vendor_data_block() -> str:
    """Build a text block with all vendor scenarios for the coordinator prompt.

    Strips expected_status from output (only used in tests, never in live prompts).
    """
    if not VENDOR_SCENARIOS:
        return "No vendor data available."
    lines = ["VENDOR DATABASE (include relevant data when delegating to specialists):\n"]
    for name, data in VENDOR_SCENARIOS.items():
        lines.append(f"--- {data.get('vendor_name', name)} (ID: {data.get('vendor_id', 'N/A')}) ---")
        lines.append(f"Service: {data.get('service_type', 'N/A')}")
        lines.append(f"HQ: {data.get('headquarters', 'N/A')} | Founded: {data.get('founded_year', 'N/A')} | Employees: {data.get('employees', 'N/A')}")
        lines.append(f"Processes personal data: {data.get('processes_personal_data', 'N/A')} | Processes payments: {data.get('processes_payments', 'N/A')}")
        lines.append(f"Data types: {', '.join(data.get('data_types', []))}")
        se = data.get('security_evidence', {})
        lines.append(f"Security: SOC2={se.get('soc2','?')}, ISO27001={se.get('iso27001','?')}, Encryption={se.get('encryption','?')}, Incident={se.get('incident_history','?')}")
        pe = data.get('privacy_evidence', {})
        lines.append(f"Privacy: DPA={pe.get('dpa','?')}, Location={pe.get('data_location','?')}, Retention={pe.get('data_retention','?')}")
        fi = data.get('financial_indicators', {})
        lines.append(f"Financial: Founded={fi.get('founded_year','?')}, Funding={fi.get('funding','?')}, Status={fi.get('operational_status','?')}")
        neg = fi.get('negative_notes', [])
        if neg:
            lines.append(f"Concerns: {'; '.join(neg)}")
        lines.append("")
    return "\n".join(lines)


def lookup_vendor(name: str) -> dict | None:
    """Look up a vendor by name (case-insensitive).

    Returns the vendor data dict if found, or None if not found.
    Does NOT auto-fallback to a default vendor.
    Strips expected_status from the returned data (only used in tests).
    """
    name_lower = name.lower().strip()
    data = VENDOR_SCENARIOS.get(name_lower)
    if data is None:
        # Try partial match
        for key, vendor_data in VENDOR_SCENARIOS.items():
            vendor_name = str(vendor_data.get("vendor_name", "")).lower()
            if name_lower in vendor_name or vendor_name in name_lower:
                data = vendor_data
                break
    if data is not None:
        # Return a copy without expected_status
        result = {k: v for k, v in data.items() if k != "expected_status"}
        return result
    return None


def extract_vendor_key(message: str) -> str:
    """Extract vendor key from a message string."""
    msg_lower = message.lower()
    for key, data in VENDOR_SCENARIOS.items():
        vendor_name = str(data.get("vendor_name", "")).lower()
        if vendor_name and vendor_name in msg_lower:
            return key
        if key in msg_lower:
            return key
    return next(iter(VENDOR_SCENARIOS), "cloudpayx")
