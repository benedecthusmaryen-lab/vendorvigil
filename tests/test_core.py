"""
Tests for VendorVigil utilities.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure vendorvigil is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.schemas import (
    RoutingPlan,
    SecurityAssessment,
    PrivacyAssessment,
    FinancialAssessment,
    RiskDecision,
    AuditRecord,
    FinalReport,
    AssessmentBundle,
)

from utils.scoring import (
    compute_total_score,
    compute_evidence_completeness,
    status_for_score,
    apply_fail_closed_rules,
    WEIGHTS,
)

# ---
# Schema Tests
# ---

class TestSchemas:
    def test_routing_plan(self):
        plan = RoutingPlan(
            vendor_id="V-001",
            vendor_name="SafeDocsID",
            vendor_type="Document storage",
            requires_security_check=True,
            requires_privacy_check=False,
            requires_financial_check=False,
            reason=["Reason 1"],
        )
        assert plan.vendor_id == "V-001"
        assert plan.requires_security_check is True
        assert plan.requires_privacy_check is False

    def test_security_assessment(self):
        a = SecurityAssessment(
            vendor_id="V-002",
            score=58,
            findings=["ISO 27001 OK"],
            missing_evidence=["SOC 2 missing"],
            critical_gaps=["SOC 2 not available"],
            confidence=0.82,
        )
        assert 0 <= a.score <= 100
        assert 0.0 <= a.confidence <= 1.0

    def test_security_assessment_bounds(self):
        try:
            SecurityAssessment(vendor_id="X", score=150)
            assert False, "Should have raised validation error"
        except Exception:
            pass

    def test_risk_decision(self):
        rd = RiskDecision(
            vendor_id="V-002",
            total_score=52,
            status="ESCALATED",
            reasons=["Rule violated"],
            required_actions=["Human review"],
            human_review_required=True,
            confidence=0.82,
        )
        assert rd.status == "ESCALATED"
        assert rd.human_review_required is True

    def test_audit_record(self):
        ar = AuditRecord(
            audit_id="VV-2026-001",
            vendor_id="V-002",
            vendor_name="CloudPayX",
            decision_status="ESCALATED",
            total_score=52,
            agent_trace=["@VendorCoordinator", "@RiskScorer"],
            human_review_required=True,
            confidence=0.82,
        )
        assert ar.audit_id == "VV-2026-001"
        assert "not an official auditor" in ar.disclaimer

    def test_final_report(self):
        fr = FinalReport(
            vendor_name="CloudPayX",
            vendor_id="V-002",
            status="ESCALATED",
            total_score=52,
            domain_scores={"security": 58, "privacy": 52, "financial": 74, "evidence": 38},
            audit_id="VV-2026-001",
            human_review_required=True,
        )
        assert "not an official auditor" in fr.disclaimer

    def test_assessment_bundle(self):
        bundle = AssessmentBundle(
            vendor_profile={"vendor_id": "V-001"},
            security=None,
            privacy=None,
            financial=None,
        )
        assert bundle.security is None
        assert bundle.vendor_profile["vendor_id"] == "V-001"


# ---
# Scoring Tests
# ---

class TestScoring:
    def test_perfect_score(self):
        score = compute_total_score(100, 100, 100, 100)
        assert score == 100

    def test_zero_score(self):
        score = compute_total_score(0, 0, 0, 0)
        assert score == 0

    def test_weighted_score(self):
        # security 35%, privacy 30%, financial 20%, evidence 15%
        score = compute_total_score(80, 70, 60, 50)
        expected = round(80 * 0.35 + 70 * 0.30 + 60 * 0.20 + 50 * 0.15)
        assert score == expected
        assert score == 68  # 28 + 21 + 12 + 7.5 = 68.5 → 68

    def test_status_thresholds(self):
        assert status_for_score(85) == "APPROVED"
        assert status_for_score(70) == "NEEDS_REVISION"
        assert status_for_score(55) == "ESCALATED"
        assert status_for_score(30) == "TEMPORARILY_REJECTED"

    def test_status_boundaries(self):
        assert status_for_score(80) == "APPROVED"
        assert status_for_score(79) == "NEEDS_REVISION"
        assert status_for_score(65) == "NEEDS_REVISION"
        assert status_for_score(64) == "ESCALATED"
        assert status_for_score(45) == "ESCALATED"
        assert status_for_score(44) == "TEMPORARILY_REJECTED"

    def test_evidence_completeness_full(self):
        profile = {
            "security_evidence": {
                "soc2": True,
                "iso27001": True,
                "encryption": "complete",
                "incident_history": "no incidents",
            },
            "privacy_evidence": {
                "dpa": True,
                "data_location": "Indonesia",
                "data_retention": "12 months",
            },
            "financial_indicators": {
                "negative_notes": [],
            },
        }
        assert compute_evidence_completeness(profile) == 100

    def test_evidence_completeness_empty(self):
        profile = {
            "security_evidence": {
                "soc2": False,
                "iso27001": False,
                "encryption": "not available",
                "incident_history": "not available",
            },
            "privacy_evidence": {
                "dpa": False,
                "data_location": "unclear",
                "data_retention": "not available",
            },
            "financial_indicators": {
                "negative_notes": ["item1"],
            },
        }
        assert compute_evidence_completeness(profile) == 0


# ---
# Fail-Closed Rules Tests
# ---

class TestFailClosedRules:
    def test_rule_1_personal_data_no_dpa(self):
        """Personal data + no DPA → ESCALATED"""
        profile = {"processes_personal_data": True, "processes_payments": False, "privacy_evidence": {"dpa": False}, "security_evidence": {}}
        sec = SecurityAssessment(vendor_id="V", score=90, confidence=0.9)
        priv = PrivacyAssessment(vendor_id="V", score=90, confidence=0.9)
        fin = FinancialAssessment(vendor_id="V", score=90, confidence=0.9)
        status, reasons, human = apply_fail_closed_rules(profile, sec, priv, fin, 85, "APPROVED")
        assert status == "ESCALATED"
        assert human is True
        assert any("DPA" in r for r in reasons)

    def test_rule_2_payment_no_soc2(self):
        """Payment processing + no SOC 2 → ESCALATED"""
        profile = {"processes_personal_data": False, "processes_payments": True, "privacy_evidence": {"dpa": True}, "security_evidence": {"soc2": False}}
        sec = SecurityAssessment(vendor_id="V", score=90, confidence=0.9)
        priv = PrivacyAssessment(vendor_id="V", score=90, confidence=0.9)
        fin = FinancialAssessment(vendor_id="V", score=90, confidence=0.9)
        status, reasons, human = apply_fail_closed_rules(profile, sec, priv, fin, 85, "APPROVED")
        assert status == "ESCALATED"
        assert human is True

    def test_rule_5_low_total_score(self):
        """Total score < 45 → TEMPORARILY_REJECTED"""
        profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {}}
        sec = SecurityAssessment(vendor_id="V", score=30, confidence=0.9)
        priv = PrivacyAssessment(vendor_id="V", score=30, confidence=0.9)
        fin = FinancialAssessment(vendor_id="V", score=30, confidence=0.9)
        status, reasons, human = apply_fail_closed_rules(profile, sec, priv, fin, 40, "TEMPORARILY_REJECTED")
        assert status == "TEMPORARILY_REJECTED"

    def test_no_flags_passes(self):
        """Clean vendor should keep original status."""
        profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {"soc2": True, "iso27001": True, "encryption": "complete"}}
        sec = SecurityAssessment(vendor_id="V", score=90, confidence=0.9)
        priv = PrivacyAssessment(vendor_id="V", score=90, confidence=0.9)
        fin = FinancialAssessment(vendor_id="V", score=90, confidence=0.9)
        status, reasons, human = apply_fail_closed_rules(profile, sec, priv, fin, 90, "APPROVED")
        assert status == "APPROVED"
        assert human is False


# ---
# Golden Path Demo Test
# ---

class TestGoldenPath:
    def test_cloudpayx_expected_escalated(self):
        """Golden path: CloudPayX processes personal data + payment, no SOC2, no DPA → ESCALATED"""
        data_dir = Path(__file__).parent.parent / "data" / "vendor_scenarios"
        profile = json.loads((data_dir / "cloud_pay_x.json").read_text())

        assert profile["vendor_id"] == "V-002"
        assert profile["vendor_name"] == "CloudPayX"
        assert profile["expected_status"] == "ESCALATED"

        evidence = compute_evidence_completeness(profile)
        assert evidence == 38  # ISO 27001 + encryption (partial) + no negative notes (3/8)

    def test_safedocsid_expected_approved(self):
        data_dir = Path(__file__).parent.parent / "data" / "vendor_scenarios"
        profile = json.loads((data_dir / "safe_docs_id.json").read_text())

        assert profile["expected_status"] == "APPROVED"
        evidence = compute_evidence_completeness(profile)
        assert evidence == 100

    def test_quickleadpro_expected_rejected(self):
        data_dir = Path(__file__).parent.parent / "data" / "vendor_scenarios"
        profile = json.loads((data_dir / "quick_lead_pro.json").read_text())

        assert profile["expected_status"] == "TEMPORARILY_REJECTED"
        evidence = compute_evidence_completeness(profile)
        assert evidence == 0
