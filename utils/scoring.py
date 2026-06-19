"""
VendorVigil — Deterministic Scoring Engine
All numeric scores are computed here using pure Python rules.
LLMs are used only for reasoning, extraction, explanation, and report writing.

Weights:
  - Security   35%
  - Privacy    30%
  - Financial  20%
  - Evidence   15%
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.schemas import (
        SecurityAssessment,
        PrivacyAssessment,
        FinancialAssessment,
        RiskDecision,
        RiskStatus,
    )


WEIGHTS = {
    "security": 0.35,
    "privacy": 0.30,
    "financial": 0.20,
    "evidence": 0.15,
}

STATUS_THRESHOLDS: list[tuple[int, int, str]] = [
    (80, 100, "APPROVED"),
    (65, 79, "NEEDS_REVISION"),
    (45, 64, "ESCALATED"),
    (0, 44, "TEMPORARILY_REJECTED"),
]


def compute_total_score(
    security: int,
    privacy: int,
    financial: int,
    evidence_completeness: int,
) -> int:
    """Compute weighted total score."""
    raw = (
        security * WEIGHTS["security"]
        + privacy * WEIGHTS["privacy"]
        + financial * WEIGHTS["financial"]
        + evidence_completeness * WEIGHTS["evidence"]
    )
    return max(0, min(100, round(raw)))


def compute_evidence_completeness(vendor_profile: dict) -> int:
    """Compute evidence completeness from vendor profile (deterministic).

    Checks for each mandatory evidence item 0 or 1, scales to 0-100.
    """
    checks: list[bool] = []

    sec_evidence = vendor_profile.get("security_evidence", {})
    checks.append(sec_evidence.get("soc2", False))
    checks.append(sec_evidence.get("iso27001", False))
    checks.append(sec_evidence.get("encryption", "") not in ("", "not available"))
    checks.append(sec_evidence.get("incident_history", "") not in ("", "not available"))

    priv_evidence = vendor_profile.get("privacy_evidence", {})
    checks.append(priv_evidence.get("dpa", False))
    checks.append(priv_evidence.get("data_location", "") not in ("", "unclear"))
    checks.append(priv_evidence.get("data_retention", "") not in ("", "not available"))

    fin_indicators = vendor_profile.get("financial_indicators", {})
    notes = fin_indicators.get("negative_notes", [])
    checks.append(len(notes) == 0)

    passed = sum(1 for c in checks if c)
    return round((passed / len(checks)) * 100)


def status_for_score(score: int) -> str:
    """Map numeric score to status label."""
    for lo, hi, status in STATUS_THRESHOLDS:
        if lo <= score <= hi:
            return status
    return "TEMPORARILY_REJECTED"


# =============================================================================
# FAIL-CLOSED RULES — Applied AFTER numeric scoring
# =============================================================================

def apply_fail_closed_rules(
    vendor_profile: dict,
    security: SecurityAssessment,
    privacy: PrivacyAssessment,
    financial: FinancialAssessment,
    raw_score: int,
    raw_status: str,
) -> tuple[str, list[str], bool]:
    """Apply fail-closed override rules.

    Returns: (final_status, reasons, human_review_required)
    """
    reasons: list[str] = []
    human_review_required = False
    final_status = raw_status

    # Rule 1: Personal data + no DPA → minimum ESCALATED
    if (
        vendor_profile.get("processes_personal_data")
        and not vendor_profile.get("privacy_evidence", {}).get("dpa")
    ):
        if raw_status in ("APPROVED", "NEEDS_REVISION"):
            final_status = "ESCALATED"
        reasons.append(
            "FAIL-CLOSED: vendor processes personal data without DPA "
            "→ minimum ESCALATED"
        )
        human_review_required = True

    # Rule 2: Payment processing + no SOC 2 → minimum ESCALATED
    if (
        vendor_profile.get("processes_payments")
        and not vendor_profile.get("security_evidence", {}).get("soc2")
    ):
        if raw_status in ("APPROVED", "NEEDS_REVISION"):
            final_status = "ESCALATED"
        reasons.append(
            "FAIL-CLOSED: vendor processes payments without SOC 2 "
            "→ minimum ESCALATED"
        )
        human_review_required = True

    # Rule 3: No ISO 27001 AND encryption missing → minimum ESCALATED
    sec_evidence = vendor_profile.get("security_evidence", {})
    if not sec_evidence.get("iso27001") and sec_evidence.get("encryption") in (
        "",
        "not available",
    ):
        if raw_status in ("APPROVED", "NEEDS_REVISION"):
            final_status = "ESCALATED"
        reasons.append(
            "FAIL-CLOSED: ISO 27001 not available and encryption not available "
            "→ minimum ESCALATED"
        )
        human_review_required = True

    # Rule 4: Two domain sub-scores below 50 → minimum ESCALATED
    low_domains = sum(
        score < 50 for score in [security.score, privacy.score, financial.score]
    )
    if low_domains >= 2:
        if raw_status in ("APPROVED", "NEEDS_REVISION"):
            final_status = "ESCALATED"
        reasons.append(
            f"FAIL-CLOSED: {low_domains} domain sub-scores below 50 "
            "→ minimum ESCALATED"
        )
        human_review_required = True

    # Rule 5: Total score below 45 → TEMPORARILY_REJECTED
    if raw_score < 45:
        final_status = "TEMPORARILY_REJECTED"
        reasons.append(
            "FAIL-CLOSED: total score below 45 → TEMPORARILY_REJECTED"
        )

    # Rule 6: Low confidence → ESCALATED
    min_confidence = min(
        security.confidence, privacy.confidence, financial.confidence
    )
    if min_confidence < 0.75:
        if final_status in ("APPROVED", "NEEDS_REVISION"):
            final_status = "ESCALATED"
        reasons.append(
            f"FAIL-CLOSED: lowest agent confidence {min_confidence:.2f} "
            "→ minimum ESCALATED"
        )
        human_review_required = True

    # Rule 7: Incomplete input → never APPROVED
    evidence = compute_evidence_completeness(vendor_profile)
    if evidence < 30 and final_status == "APPROVED":
        final_status = "ESCALATED"
        reasons.append(
            "FAIL-CLOSED: incomplete input data, cannot be APPROVED"
        )
        human_review_required = True

    return final_status, reasons, human_review_required
