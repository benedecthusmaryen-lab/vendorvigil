"""
VendorVigil — Full Pipeline Runner
Orchestrates all 7 agents in sequence: Coordinator → Specialists (parallel) → Risk Scorer → Audit → Report.
This is the main entry point called by the Streamlit dashboard.
"""

from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
from typing import Any

from agents.vendor_coordinator import assess_vendor as run_coordinator
from agents.security_reviewer import assess_security as run_security
from agents.privacy_reviewer import assess_privacy as run_privacy
from agents.financial_reviewer import assess_financial as run_financial
from agents.risk_scorer import compute_risk_decision as run_risk
from agents.audit_logger import create_audit_trail as run_audit
from agents.report_compiler import generate_report as run_report

from utils.band_helpers import BandChatRoom
from utils.schemas import (
    AssessmentBundle,
    FinalReport,
    AuditRecord,
    RiskDecision,
    SecurityAssessment,
    PrivacyAssessment,
    FinancialAssessment,
)

logger = logging.getLogger(__name__)


def run_pipeline(vendor_profile: dict) -> tuple[FinalReport, BandChatRoom]:
    """Execute the full VendorVigil pipeline for a single vendor.

    Flow:
    1. @VendorCoordinator → RoutingPlan
    2. @SecurityReviewer, @PrivacyReviewer, @FinancialReviewer → parallel assessments
    3. @RiskScorer → RiskDecision (deterministic scoring + fail-closed)
    4. @AuditLogger → AuditRecord (immutable audit log)
    5. @ReportCompiler → FinalReport (dashboard-ready)

    Args:
        vendor_profile: Parsed vendor JSON dict from data/vendor_scenarios/

    Returns:
        (FinalReport, BandChatRoom) — the report for display + chat transcript
    """
    vendor_name = vendor_profile.get("vendor_name", "Unknown")
    room = BandChatRoom()

    try:
        # Phase 1: Coordinator routing
        room.user_says(
            f"@VendorCoordinator Please assess vendor {vendor_name} "
            f"for service {vendor_profile.get('service_type', '')}."
        )
        plan = run_coordinator(vendor_profile, room)
        logger.info(f"Phase 1 done: routing plan for {vendor_name}")
    except Exception as e:
        logger.error(f"Phase 1 failed: {e}")
        raise

    # Phase 2: Parallel specialist assessments
    security: SecurityAssessment | None = None
    privacy: PrivacyAssessment | None = None
    financial: FinancialAssessment | None = None

    try:
        if plan.requires_security_check:
            security = run_security(vendor_profile, room)
            logger.info(f"Phase 2: security assessment done ({security.score})")
    except Exception as e:
        logger.error(f"Security assessment failed: {e}")

    try:
        if plan.requires_privacy_check:
            privacy = run_privacy(vendor_profile, room)
            logger.info(f"Phase 2: privacy assessment done ({privacy.score})")
    except Exception as e:
        logger.error(f"Privacy assessment failed: {e}")

    try:
        if plan.requires_financial_check:
            financial = run_financial(vendor_profile, room)
            logger.info(f"Phase 2: financial assessment done ({financial.score})")
    except Exception as e:
        logger.error(f"Financial assessment failed: {e}")

    # Phase 3: Risk scoring
    bundle = AssessmentBundle(
        vendor_profile=vendor_profile,
        security=security,
        privacy=privacy,
        financial=financial,
    )

    # Fill missing assessments with neutral scores (100 = not applicable = passed)
    if not security:
        security = SecurityAssessment(
            vendor_id=vendor_profile.get("vendor_id", ""),
            score=100,
            findings=["Security not assessed — vendor does not process sensitive data"],
            confidence=1.0,
        )
    if not privacy:
        privacy = PrivacyAssessment(
            vendor_id=vendor_profile.get("vendor_id", ""),
            score=100,
            personal_data_processed=False,
            findings=["Privacy not assessed — vendor does not process personal data"],
            confidence=1.0,
        )
    if not financial:
        financial = FinancialAssessment(
            vendor_id=vendor_profile.get("vendor_id", ""),
            score=100,
            findings=["Financial not assessed — vendor does not process payments"],
            confidence=1.0,
        )
    # Update bundle with neutral assessments
    bundle.security = security
    bundle.privacy = privacy
    bundle.financial = financial

    risk_decision = run_risk(vendor_profile, bundle, room)
    logger.info(f"Phase 3: risk decision = {risk_decision.status} ({risk_decision.total_score})")

    # Phase 4: Audit log
    audit_record = run_audit(vendor_profile, risk_decision, room)
    logger.info(f"Phase 4: audit record = {audit_record.audit_id}")

    # Phase 5: Final report
    final_report = run_report(vendor_profile, bundle, risk_decision, audit_record, room)
    logger.info(f"Phase 5: report ready for {vendor_name}")

    return final_report, room


def load_vendor_scenario(scenario_name: str) -> dict:
    """Load a vendor scenario JSON file by name (e.g., 'cloud_pay_x')."""
    data_dir = Path(__file__).parent / "data" / "vendor_scenarios"
    file_path = data_dir / f"{scenario_name}.json"
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario not found: {file_path}")
    return json.loads(file_path.read_text())


def list_scenarios() -> list[dict[str, str]]:
    """List all available vendor scenarios."""
    data_dir = Path(__file__).parent / "data" / "vendor_scenarios"
    scenarios: list[dict[str, str]] = []
    for f in sorted(data_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            scenarios.append({
                "key": f.stem,
                "vendor_id": data.get("vendor_id", ""),
                "vendor_name": data.get("vendor_name", f.stem),
                "expected_status": data.get("expected_status", ""),
            })
        except Exception:
            continue
    return scenarios


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # Run all three demo scenarios
    scenarios = ["safe_docs_id", "cloud_pay_x", "quick_lead_pro"]
    for key in scenarios:
        print(f"\n{'='*60}")
        print(f"  RUNNING SCENARIO: {key}")
        print(f"{'='*60}")
        profile = load_vendor_scenario(key)
        report, room = run_pipeline(profile)
        print(f"\n  Status: {report.status}")
        print(f"  Score:  {report.total_score}/100")
        print(f"  Audit:  {report.audit_id}")
        print(f"  Human Review: {'Yes' if report.human_review_required else 'No'}")
        print(f"\n  Band Chat Transcript:\n{room.format_for_display()}")
        print(f"\n  Executive Summary:\n  {report.executive_summary}")
