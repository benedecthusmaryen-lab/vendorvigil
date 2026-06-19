"""
VendorVigil — Band Configuration Helpers
Loads agent credentials and provides Band SDK connectivity.
Band is the COORDINATION LAYER, NOT an agent framework.

For hackathon demo: agents run as standalone Python scripts.
Each agent file connects to Band as a Remote Agent.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---
# Agent manifest — maps agent handles to env vars
# ---

AGENT_MANIFEST: dict[str, dict[str, str]] = {
    "vendor_coordinator": {
        "id_env": "BAND_KOORDINATOR_VENDOR_ID",
        "key_env": "BAND_KOORDINATOR_VENDOR_KEY",
        "handle": "@VendorCoordinator",
        "framework": "Pydantic AI",
        "provider": "AI/ML API",
    },
    "security_reviewer": {
        "id_env": "BAND_PEMERIKSA_KEAMANAN_ID",
        "key_env": "BAND_PEMERIKSA_KEAMANAN_KEY",
        "handle": "@SecurityReviewer",
        "framework": "Pydantic AI",
        "provider": "AI/ML API",
    },
    "privacy_reviewer": {
        "id_env": "BAND_PEMERIKSA_PRIVASI_ID",
        "key_env": "BAND_PEMERIKSA_PRIVASI_KEY",
        "handle": "@PrivacyReviewer",
        "framework": "Pydantic AI",
        "provider": "AI/ML API",
    },
    "financial_reviewer": {
        "id_env": "BAND_PEMERIKSA_FINANSIAL_ID",
        "key_env": "BAND_PEMERIKSA_FINANSIAL_KEY",
        "handle": "@FinancialReviewer",
        "framework": "Pydantic AI",
        "provider": "Featherless",
    },
    "risk_scorer": {
        "id_env": "BAND_PENILAI_RISIKO_ID",
        "key_env": "BAND_PENILAI_RISIKO_KEY",
        "handle": "@RiskScorer",
        "framework": "Pydantic AI",
        "provider": "Featherless",
    },
    "audit_logger": {
        "id_env": "BAND_PENCATAT_AUDIT_ID",
        "key_env": "BAND_PENCATAT_AUDIT_KEY",
        "handle": "@AuditLogger",
        "framework": "Pydantic AI + Python utility",
        "provider": "AI/ML API",
    },
    "report_compiler": {
        "id_env": "BAND_PENYUSUN_LAPORAN_ID",
        "key_env": "BAND_PENYUSUN_LAPORAN_KEY",
        "handle": "@ReportCompiler",
        "framework": "Pydantic AI",
        "provider": "AI/ML API",
    },
}


# ---
# Band Room simulation for demo (when Band API is not connected)
# ---

@dataclass
class BandMessage:
    """A single message in the Band Chat Room."""
    sender: str  # e.g., "@VendorCoordinator" or "User"
    recipient: str | None  # None = broadcast, or "@Agent"
    content: str
    timestamp: str = ""


@dataclass
class BandChatRoom:
    """Simulates Band Chat Room for offline/demo mode.

    This is a DEMO simulation — in production, use the real Band SDK.
    """

    room_id: str = "vendorvigil-demo-room"
    messages: list[BandMessage] = field(default_factory=list)

    def user_says(self, content: str) -> BandMessage:
        msg = BandMessage(sender="👤 User / Reviewer", recipient=None, content=content)
        self.messages.append(msg)
        return msg

    def agent_says(
        self, sender_handle: str, content: str, recipient: str | None = None
    ) -> BandMessage:
        msg = BandMessage(sender=sender_handle, recipient=recipient, content=content)
        self.messages.append(msg)
        return msg

    def mention(
        self, sender_handle: str, recipient_handle: str, content: str
    ) -> BandMessage:
        msg = BandMessage(
            sender=sender_handle,
            recipient=recipient_handle,
            content=f"{recipient_handle} {content}",
        )
        self.messages.append(msg)
        return msg

    def format_for_display(self) -> str:
        """Format all messages as a Band Chat transcript."""
        lines: list[str] = []
        for m in self.messages:
            recipient = f" → {m.recipient}" if m.recipient else ""
            lines.append(f"{m.sender}{recipient}")
            lines.append(f"  {m.content}")
            lines.append("---")
        return "\n".join(lines)

    def get_agent_trace(self) -> list[str]:
        """Extract ordered agent handles for audit trail."""
        seen = []
        for m in self.messages:
            sender = m.sender.replace("👤 User / Reviewer", "").strip()
            if sender and sender.startswith("@") and sender not in seen:
                seen.append(sender)
        return seen


def load_model_policy() -> dict[str, Any]:
    """Load model policy YAML config."""
    config_path = Path(__file__).parent.parent / "config" / "model_policy.yaml"
    if not config_path.exists():
        logger.warning("model_policy.yaml not found, using defaults")
        return {}
    return yaml.safe_load(config_path.read_text())


def load_scoring_rules() -> dict[str, Any]:
    """Load scoring rules YAML config."""
    config_path = Path(__file__).parent.parent / "config" / "scoring_rules.yaml"
    if not config_path.exists():
        logger.warning("scoring_rules.yaml not found, using defaults")
        return {}
    return yaml.safe_load(config_path.read_text())


def get_agent_info(agent_key: str) -> dict[str, str]:
    """Get agent metadata from manifest."""
    return AGENT_MANIFEST.get(agent_key, {})
