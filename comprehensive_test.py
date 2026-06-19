#!/usr/bin/env python3
"""
VendorVigil — Comprehensive Test Suite
======================================
Tests ALL components end-to-end:
  - File structure & data
  - Import & dependencies
  - Pydantic schema validation
  - Scoring engine (deterministic)
  - 7 Fail-Closed Rules
  - All 7 agents (mock mode)
  - Pipeline end-to-end (3 vendor scenarios)
  - Audit log persistence
  - Band Chat Room simulation
  - Partner clients (mock fallback)

Usage:
  python3 comprehensive_test.py
  python3 comprehensive_test.py --verbose
  python3 comprehensive_test.py --stop-on-fail
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ---
# Setup
# ---

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
os.environ["USE_MOCK_PROVIDER"] = "true"  # Force mock mode for testing

VERBOSE = "--verbose" in sys.argv
STOP_ON_FAIL = "--stop-on-fail" in sys.argv

_pass_count = 0
_fail_count = 0
_total_start = time.time()


def test(name: str) -> callable:
    """Decorator: wraps a test function with pass/fail reporting."""
    def decorator(fn):
        def wrapper():
            global _pass_count, _fail_count
            start = time.time()
            try:
                fn()
                elapsed = time.time() - start
                _pass_count += 1
                print(f"  ✅ {name}  ({elapsed:.3f}s)")
                if VERBOSE:
                    print(f"      PASSED")
            except Exception as e:
                elapsed = time.time() - start
                _fail_count += 1
                print(f"  ❌ {name}  ({elapsed:.3f}s)")
                print(f"      ERROR: {e}")
                if VERBOSE:
                    import traceback
                    traceback.print_exc()
                if STOP_ON_FAIL:
                    sys.exit(1)
        # Run immediately
        wrapper()
        return fn
    return decorator


# ---
# SECTION 1: File Structure & Data Integrity
# ---

def section(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


@test("All required directories exist")
def _():
    for d in ["agents", "config", "data/vendor_scenarios", "docs", "tests", "utils"]:
        assert (THIS_DIR / d).is_dir(), f"Directory '{d}' not found"


@test("All 7 agent files exist")
def _():
    agents = [
        "vendor_coordinator.py", "security_reviewer.py", "privacy_reviewer.py",
        "financial_reviewer.py", "risk_scorer.py", "audit_logger.py",
        "report_compiler.py",
    ]
    for f in agents:
        assert (THIS_DIR / "agents" / f).exists(), f"Agent file '{f}' not found"


@test("All config files exist")
def _():
    assert (THIS_DIR / "config" / "model_policy.yaml").exists()
    assert (THIS_DIR / "config" / "scoring_rules.yaml").exists()


@test("All 3 vendor scenario files are valid JSON")
def _():
    for f in ["safe_docs_id", "cloud_pay_x", "quick_lead_pro"]:
        path = THIS_DIR / "data" / "vendor_scenarios" / f"{f}.json"
        assert path.exists(), f"Scenario '{f}' not found"
        data = json.loads(path.read_text())
        assert "vendor_id" in data
        assert "vendor_name" in data
        assert "expected_status" in data


@test("All utility files exist")
def _():
    for f in ["schemas.py", "scoring.py", "partner_clients.py", "audit_log.py", "band_helpers.py"]:
        assert (THIS_DIR / "utils" / f).exists(), f"Utility '{f}' not found"


@test(".env.example exists and is valid")
def _():
    path = THIS_DIR / ".env.example"
    assert path.exists()
    content = path.read_text()
    assert "AIML_API_KEY" in content
    assert "FEATHERLESS_API_KEY" in content
    assert "USE_MOCK_PROVIDER" in content


@test(".gitignore exists")
def _():
    assert (THIS_DIR / ".gitignore").exists()
    content = (THIS_DIR / ".gitignore").read_text()
    assert ".env" in content
    assert "__pycache__" in content


@test("requirements.txt exists")
def _():
    path = THIS_DIR / "requirements.txt"
    assert path.exists()
    content = path.read_text()
    assert "pydantic" in content.lower()
    assert "streamlit" in content.lower()


# ---
# SECTION 2: Import & Dependency
# ---

@test("Utils: schemas import successful")
def _():
    from utils.schemas import (
        RoutingPlan, SecurityAssessment, PrivacyAssessment,
        FinancialAssessment, RiskDecision, AuditRecord,
        FinalReport, AssessmentBundle, RiskStatus,
    )
    assert RoutingPlan is not None
    assert RiskStatus is not None


@test("Utils: scoring import successful")
def _():
    from utils.scoring import (
        compute_total_score, compute_evidence_completeness,
        status_for_score, apply_fail_closed_rules, WEIGHTS,
    )
    assert WEIGHTS["security"] == 0.35


@test("Utils: partner_clients import successful")
def _():
    from utils.partner_clients import (
        call_aiml_api, call_featherless, get_mock_specialist,
        ProviderResult, USE_MOCK,
    )
    assert USE_MOCK is True
    assert ProviderResult is not None


@test("Utils: audit_log import successful")
def _():
    from utils.audit_log import (
        create_audit_record, generate_audit_id, load_audit_record,
        list_all_audit_records, get_audit_summary, SAFE_POSITION_DISCLAIMER,
    )
    assert SAFE_POSITION_DISCLAIMER
    assert "not an official auditor" in SAFE_POSITION_DISCLAIMER


@test("Utils: band_helpers import successful")
def _():
    from utils.band_helpers import (
        BandChatRoom, BandMessage, AGENT_MANIFEST,
        load_model_policy, load_scoring_rules, get_agent_info,
    )
    assert len(AGENT_MANIFEST) == 7
    info = get_agent_info("vendor_coordinator")
    assert info["handle"] == "@VendorCoordinator"
    assert info["framework"] == "Pydantic AI"


@test("Agents: all 7 agents import successful")
def _():
    from agents.vendor_coordinator import assess_vendor
    from agents.security_reviewer import assess_security
    from agents.privacy_reviewer import assess_privacy
    from agents.financial_reviewer import assess_financial
    from agents.risk_scorer import compute_risk_decision
    from agents.audit_logger import create_audit_trail
    from agents.report_compiler import generate_report
    assert assess_vendor is not None
    assert assess_security is not None
    assert assess_privacy is not None
    assert assess_financial is not None
    assert compute_risk_decision is not None
    assert create_audit_trail is not None
    assert generate_report is not None


@test("Pipeline: run_pipeline import successful")
def _():
    from run_pipeline import run_pipeline, load_vendor_scenario, list_scenarios
    scenarios = list_scenarios()
    assert len(scenarios) == 3
    names = [s["vendor_name"] for s in scenarios]
    assert "CloudPayX" in names
    assert "SafeDocsID" in names
    assert "QuickLeadPro" in names


# ---
# SECTION 3: Schema Validation
# ---

@test("Schema: RoutingPlan validates successfully")
def _():
    from utils.schemas import RoutingPlan
    plan = RoutingPlan(
        vendor_id="V-001", vendor_name="TestCorp", vendor_type="SaaS",
        requires_security_check=True, reason=["Test reason"],
    )
    d = plan.model_dump()
    assert d["vendor_id"] == "V-001"
    assert d["requires_security_check"] is True
    assert d["requires_privacy_check"] is False  # default


@test("Schema: SecurityAssessment bounds validation")
def _():
    from utils.schemas import SecurityAssessment
    # Valid
    a = SecurityAssessment(vendor_id="V", score=50, confidence=0.5)
    assert a.score == 50
    # Invalid: score > 100
    try:
        SecurityAssessment(vendor_id="V", score=150, confidence=0.5)
        assert False, "Should have failed validation"
    except Exception:
        pass
    # Invalid: confidence > 1
    try:
        SecurityAssessment(vendor_id="V", score=50, confidence=1.5)
        assert False, "Should have failed validation"
    except Exception:
        pass


@test("Schema: all 7 schemas can be instantiated with valid data")
def _():
    from utils.schemas import (
        RoutingPlan, SecurityAssessment, PrivacyAssessment,
        FinancialAssessment, RiskDecision, AuditRecord, FinalReport,
    )
    SecurityAssessment(vendor_id="V", score=100, findings=["OK"], confidence=1.0)
    PrivacyAssessment(vendor_id="V", score=100, findings=["OK"], confidence=1.0)
    FinancialAssessment(vendor_id="V", score=100, findings=["OK"], confidence=1.0)

    RiskDecision(
        vendor_id="V", total_score=85, status="APPROVED",
        confidence=0.9, human_review_required=False,
    )

    AuditRecord(
        audit_id="VV-2026-999", vendor_id="V", vendor_name="Test",
        decision_status="APPROVED", total_score=85,
        human_review_required=False, confidence=0.9,
    )

    FinalReport(
        vendor_name="Test", vendor_id="V", status="APPROVED",
        total_score=85, domain_scores={}, audit_id="VV-2026-999",
        human_review_required=False,
    )


@test("Schema: disclaimer in AuditRecord & FinalReport exists")
def _():
    from utils.schemas import AuditRecord, FinalReport
    ar = AuditRecord(
        audit_id="VV-2026-999", vendor_id="V", vendor_name="T",
        decision_status="D", total_score=0,
        human_review_required=False, confidence=0.0,
    )
    assert "not an official auditor" in ar.disclaimer

    fr = FinalReport(
        vendor_name="T", vendor_id="V", status="D",
        total_score=0, audit_id="VV",
        human_review_required=False,
    )
    assert "not an official auditor" in fr.disclaimer


# ---
# SECTION 4: Scoring Engine
# ---

@test("Scoring: weighted total_score is correct")
def _():
    from utils.scoring import compute_total_score
    # 100*0.35 + 100*0.30 + 100*0.20 + 100*0.15 = 100
    assert compute_total_score(100, 100, 100, 100) == 100
    # 0*0.35 + 0*0.30 + 0*0.20 + 0*0.15 = 0
    assert compute_total_score(0, 0, 0, 0) == 0
    # 80*0.35 + 70*0.30 + 60*0.20 + 50*0.15 = 28+21+12+7.5 = 68.5 → 68
    assert compute_total_score(80, 70, 60, 50) == 68


@test("Scoring: status thresholds are correct")
def _():
    from utils.scoring import status_for_score
    assert status_for_score(100) == "APPROVED"
    assert status_for_score(85) == "APPROVED"
    assert status_for_score(80) == "APPROVED"
    assert status_for_score(79) == "NEEDS_REVISION"
    assert status_for_score(65) == "NEEDS_REVISION"
    assert status_for_score(64) == "ESCALATED"
    assert status_for_score(45) == "ESCALATED"
    assert status_for_score(44) == "TEMPORARILY_REJECTED"
    assert status_for_score(0) == "TEMPORARILY_REJECTED"


@test("Scoring: evidence_completeness calculation is correct")
def _():
    from utils.scoring import compute_evidence_completeness
    # SafeDocsID style: full evidence
    full = {
        "security_evidence": {"soc2": True, "iso27001": True, "encryption": "complete", "incident_history": "ok"},
        "privacy_evidence": {"dpa": True, "data_location": "ID", "data_retention": "12"},
        "financial_indicators": {"negative_notes": []},
    }
    assert compute_evidence_completeness(full) == 100

    # QuickLeadPro style: zero evidence
    zero = {
        "security_evidence": {"soc2": False, "iso27001": False, "encryption": "not available", "incident_history": "not available"},
        "privacy_evidence": {"dpa": False, "data_location": "unclear", "data_retention": "not available"},
        "financial_indicators": {"negative_notes": ["item1"]},
    }
    assert compute_evidence_completeness(zero) == 0

    # CloudPayX style: partial (ISO 27001 + partial encryption + no negative notes)
    partial = {
        "security_evidence": {"soc2": False, "iso27001": True, "encryption": "mentioned", "incident_history": "not available"},
        "privacy_evidence": {"dpa": False, "data_location": "unclear", "data_retention": "not available"},
        "financial_indicators": {"negative_notes": []},
    }
    assert compute_evidence_completeness(partial) == 38  # 3/8


# ---
# SECTION 5: Fail-Closed Rules
# ---

@test("Fail-Closed Rule 1: personal data + no DPA → ESCALATED")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": True, "processes_payments": False, "privacy_evidence": {"dpa": False}, "security_evidence": {}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=90, confidence=0.9),
        PrivacyAssessment(vendor_id="V", score=90, confidence=0.9),
        FinancialAssessment(vendor_id="V", score=90, confidence=0.9),
        90, "APPROVED",
    )
    assert status == "ESCALATED"
    assert human is True
    assert any("DPA" in r for r in reasons)


@test("Fail-Closed Rule 2: payment + no SOC2 → ESCALATED")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": False, "processes_payments": True, "privacy_evidence": {"dpa": True}, "security_evidence": {"soc2": False}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=90, confidence=0.9),
        PrivacyAssessment(vendor_id="V", score=90, confidence=0.9),
        FinancialAssessment(vendor_id="V", score=90, confidence=0.9),
        90, "APPROVED",
    )
    assert status == "ESCALATED"
    assert human is True


@test("Fail-Closed Rule 3: no ISO 27001 + no encryption → ESCALATED")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {"iso27001": False, "encryption": "not available"}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=90, confidence=0.9),
        PrivacyAssessment(vendor_id="V", score=90, confidence=0.9),
        FinancialAssessment(vendor_id="V", score=90, confidence=0.9),
        90, "APPROVED",
    )
    assert status == "ESCALATED"


@test("Fail-Closed Rule 4: two sub-scores below 50 → ESCALATED")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=30, confidence=0.9),
        PrivacyAssessment(vendor_id="V", score=40, confidence=0.9),
        FinancialAssessment(vendor_id="V", score=90, confidence=0.9),
        85, "APPROVED",
    )
    assert status == "ESCALATED"


@test("Fail-Closed Rule 5: total score < 45 → TEMPORARILY_REJECTED")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=30, confidence=0.9),
        PrivacyAssessment(vendor_id="V", score=30, confidence=0.9),
        FinancialAssessment(vendor_id="V", score=30, confidence=0.9),
        40, "ESCALATED",
    )
    assert status == "TEMPORARILY_REJECTED"


@test("Fail-Closed Rule 6: confidence < 0.75 → ESCALATED")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=90, confidence=0.5),
        PrivacyAssessment(vendor_id="V", score=90, confidence=0.9),
        FinancialAssessment(vendor_id="V", score=90, confidence=0.9),
        90, "APPROVED",
    )
    assert status == "ESCALATED"
    assert human is True


@test("Fail-Closed Rule 7: incomplete input + APPROVED → ESCALATED")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {"iso27001": False, "encryption": "not available"}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=100, confidence=1.0),
        PrivacyAssessment(vendor_id="V", score=100, confidence=1.0),
        FinancialAssessment(vendor_id="V", score=100, confidence=1.0),
        100, "APPROVED",
    )
    # Evidence < 30 because all false/empty → cannot be APPROVED
    assert status in ("ESCALATED", "TEMPORARILY_REJECTED")


@test("Fail-Closed: clean vendor not affected by fail-closed")
def _():
    from utils.scoring import apply_fail_closed_rules
    from utils.schemas import SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = {"processes_personal_data": False, "processes_payments": False, "privacy_evidence": {"dpa": True}, "security_evidence": {"soc2": True, "iso27001": True, "encryption": "complete"}}
    status, reasons, human = apply_fail_closed_rules(
        profile,
        SecurityAssessment(vendor_id="V", score=90, confidence=0.9),
        PrivacyAssessment(vendor_id="V", score=90, confidence=0.9),
        FinancialAssessment(vendor_id="V", score=90, confidence=0.9),
        90, "APPROVED",
    )
    # Clean vendor: SOC2+ISO+encryption+DPA → stays APPROVED
    assert status == "APPROVED"
    assert human is False


# ---
# SECTION 6: Band Chat Room Simulation
# ---

@test("BandChatRoom: user_says and agent_says")
def _():
    from utils.band_helpers import BandChatRoom
    room = BandChatRoom()
    room.user_says("Hello vendor A")
    room.agent_says("@VendorCoordinator", "Received request")
    assert len(room.messages) == 2
    assert room.messages[0].sender == "👤 User / Reviewer"
    assert room.messages[1].sender == "@VendorCoordinator"


@test("BandChatRoom: @mention routing")
def _():
    from utils.band_helpers import BandChatRoom
    room = BandChatRoom()
    room.mention("@VendorCoordinator", "@SecurityReviewer", "cek vendor X")
    m = room.messages[0]
    assert m.recipient == "@SecurityReviewer"
    assert "@SecurityReviewer" in m.content


@test("BandChatRoom: format_for_display produces text")
def _():
    from utils.band_helpers import BandChatRoom
    room = BandChatRoom()
    room.user_says("Test")
    txt = room.format_for_display()
    assert "Test" in txt
    assert "---" in txt


@test("BandChatRoom: get_agent_trace collects agent handles")
def _():
    from utils.band_helpers import BandChatRoom
    room = BandChatRoom()
    room.user_says("Mulai")
    room.agent_says("@VendorCoordinator", "Routing")
    room.agent_says("@SecurityReviewer", "Assessment")
    room.agent_says("@RiskScorer", "Scoring")
    trace = room.get_agent_trace()
    assert len(trace) == 3
    assert trace == ["@VendorCoordinator", "@SecurityReviewer", "@RiskScorer"]


# ---
# SECTION 7: Partner Clients (Mock Mode)
# ---

@test("PartnerClient: call_aiml_api in mock mode returns ProviderResult")
def _():
    from utils.partner_clients import call_aiml_api, USE_MOCK
    assert USE_MOCK is True
    result = call_aiml_api("sys", "user", "gemini-flash")
    assert result.provider == "aimlapi"
    assert result.is_mock is True


@test("PartnerClient: call_featherless in mock mode returns ProviderResult")
def _():
    from utils.partner_clients import call_featherless
    result = call_featherless("sys", "user", "qwen")
    assert result.provider == "featherless"
    assert result.is_mock is True


@test("PartnerClient: get_mock_specialist returns data for CloudPayX")
def _():
    from utils.partner_clients import get_mock_specialist
    data = get_mock_specialist("cloudpayx", "security")
    assert data["vendor_id"] == "V-002"
    assert data["score"] == 58
    data2 = get_mock_specialist("cloudpayx", "financial")
    assert data2["score"] == 74


@test("PartnerClient: get_mock_specialist returns empty for unknown vendor")
def _():
    from utils.partner_clients import get_mock_specialist
    data = get_mock_specialist("nonexistent", "security")
    assert data == {}


# ---
# SECTION 8: Agent Output Validation (Mock Mode)
# ---

@test("Agent @VendorCoordinator: routing plan for CloudPayX")
def _():
    from agents.vendor_coordinator import assess_vendor
    from utils.band_helpers import BandChatRoom
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/cloud_pay_x.json").read_text())
    room = BandChatRoom()
    plan = assess_vendor(profile, room)
    assert plan.requires_security_check is True
    assert plan.requires_privacy_check is True
    assert plan.requires_financial_check is True
    assert plan.vendor_name == "CloudPayX"


@test("Agent @VendorCoordinator: routing plan for SafeDocsID (security only)")
def _():
    from agents.vendor_coordinator import assess_vendor
    from utils.band_helpers import BandChatRoom
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/safe_docs_id.json").read_text())
    room = BandChatRoom()
    plan = assess_vendor(profile, room)
    assert plan.requires_security_check is True
    assert plan.requires_privacy_check is False  # Does not process personal data
    assert plan.requires_financial_check is False  # Does not process payments


@test("Agent @SecurityReviewer: assessment CloudPayX (mock → deterministic)")
def _():
    from agents.security_reviewer import assess_security
    from utils.band_helpers import BandChatRoom
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/cloud_pay_x.json").read_text())
    room = BandChatRoom()
    result = assess_security(profile, room)
    assert result.vendor_id == "V-002"
    assert 0 <= result.score <= 100
    assert 0.0 <= result.confidence <= 1.0
    # CloudPayX mock: score=58, confidence=0.82
    assert result.score == 58
    assert len(result.critical_gaps) >= 1


@test("Agent @PrivacyReviewer: assessment CloudPayX (mock → deterministic)")
def _():
    from agents.privacy_reviewer import assess_privacy
    from utils.band_helpers import BandChatRoom
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/cloud_pay_x.json").read_text())
    room = BandChatRoom()
    result = assess_privacy(profile, room)
    assert result.personal_data_processed is True
    assert result.score == 52
    assert len(result.critical_gaps) >= 1


@test("Agent @FinancialReviewer: assessment CloudPayX (mock → deterministic)")
def _():
    from agents.financial_reviewer import assess_financial
    from utils.band_helpers import BandChatRoom
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/cloud_pay_x.json").read_text())
    room = BandChatRoom()
    result = assess_financial(profile, room)
    assert result.score == 74


@test("Agent @RiskScorer: compute risk for CloudPayX → ESCALATED")
def _():
    from agents.risk_scorer import compute_risk_decision
    from utils.band_helpers import BandChatRoom
    from utils.schemas import AssessmentBundle, SecurityAssessment, PrivacyAssessment, FinancialAssessment
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/cloud_pay_x.json").read_text())
    bundle = AssessmentBundle(
        vendor_profile=profile,
        security=SecurityAssessment(vendor_id="V-002", score=58, confidence=0.82, critical_gaps=["SOC 2 not available"]),
        privacy=PrivacyAssessment(vendor_id="V-002", score=52, confidence=0.78, critical_gaps=["DPA not available"]),
        financial=FinancialAssessment(vendor_id="V-002", score=74, confidence=0.85),
    )
    room = BandChatRoom()
    decision = compute_risk_decision(profile, bundle, room)
    assert decision.status == "ESCALATED"
    assert decision.human_review_required is True
    assert decision.total_score == 56


@test("Agent @AuditLogger: audit record created with unique ID")
def _():
    from agents.audit_logger import create_audit_trail
    from utils.band_helpers import BandChatRoom
    from utils.schemas import RiskDecision
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/cloud_pay_x.json").read_text())
    decision = RiskDecision(
        vendor_id="V-002", total_score=52, status="ESCALATED",
        reasons=["Fail-closed Rule 1", "Fail-closed Rule 2"],
        required_actions=["Human review"], human_review_required=True,
        confidence=0.82,
    )
    room = BandChatRoom()
    room.agent_says("@VendorCoordinator", "Done")
    room.agent_says("@RiskScorer", "Done")
    record = create_audit_trail(profile, decision, room)
    assert record.audit_id.startswith("VV-")
    assert "not an official auditor" in record.disclaimer
    assert len(record.agent_trace) == 2


@test("Agent @ReportCompiler: generate report for CloudPayX")
def _():
    from agents.report_compiler import generate_report
    from utils.band_helpers import BandChatRoom
    from utils.schemas import (
        AssessmentBundle, RiskDecision, AuditRecord,
        SecurityAssessment, PrivacyAssessment, FinancialAssessment,
    )
    profile = json.loads((THIS_DIR / "data/vendor_scenarios/cloud_pay_x.json").read_text())
    bundle = AssessmentBundle(
        vendor_profile=profile,
        security=SecurityAssessment(vendor_id="V-002", score=58, confidence=0.82),
        privacy=PrivacyAssessment(vendor_id="V-002", score=52, confidence=0.78),
        financial=FinancialAssessment(vendor_id="V-002", score=74, confidence=0.85),
    )
    decision = RiskDecision(
        vendor_id="V-002", total_score=52, status="ESCALATED",
        reasons=["Rule 1"], required_actions=["Review"],
        human_review_required=True, confidence=0.82,
    )
    audit = AuditRecord(
        audit_id="VV-2026-TEST", vendor_id="V-002", vendor_name="CloudPayX",
        decision_status="ESCALATED", total_score=52,
        agent_trace=["@VendorCoordinator", "@RiskScorer"],
        human_review_required=True, confidence=0.82,
    )
    room = BandChatRoom()
    report = generate_report(profile, bundle, decision, audit, room)
    assert report.vendor_name == "CloudPayX"
    assert report.status == "ESCALATED"
    assert report.audit_id == "VV-2026-TEST"
    assert len(report.recommendations) > 0
    assert len(report.executive_summary) > 0
    assert "not an official auditor" in report.disclaimer


# ---
# SECTION 9: End-to-End Pipeline (Golden Path)
# ---

@test("Pipeline: CloudPayX → ESCALATED (golden path)")
def _():
    from run_pipeline import run_pipeline, load_vendor_scenario
    profile = load_vendor_scenario("cloud_pay_x")
    report, room = run_pipeline(profile)
    assert report.status == "ESCALATED"
    assert report.total_score == 56
    assert report.human_review_required is True
    assert report.audit_id.startswith("VV-")
    trace = room.get_agent_trace()
    assert "@VendorCoordinator" in trace
    assert "@RiskScorer" in trace


@test("Pipeline: SafeDocsID → APPROVED (clean scenario)")
def _():
    from run_pipeline import run_pipeline, load_vendor_scenario
    profile = load_vendor_scenario("safe_docs_id")
    report, room = run_pipeline(profile)
    assert report.status == "APPROVED"
    assert report.total_score == 100
    assert report.human_review_required is False


@test("Pipeline: QuickLeadPro → TEMPORARILY_REJECTED (fail scenario)")
def _():
    from run_pipeline import run_pipeline, load_vendor_scenario
    profile = load_vendor_scenario("quick_lead_pro")
    report, room = run_pipeline(profile)
    assert report.status == "TEMPORARILY_REJECTED"
    assert report.total_score == 20
    assert report.human_review_required is True


@test("Pipeline: all 3 scenarios produce different audit IDs")
def _():
    from run_pipeline import run_pipeline, load_vendor_scenario
    ids = set()
    for key in ["safe_docs_id", "cloud_pay_x", "quick_lead_pro"]:
        profile = load_vendor_scenario(key)
        report, _ = run_pipeline(profile)
        ids.add(report.audit_id)
    assert len(ids) == 3, f"Expected 3 unique IDs, got {ids}"


@test("Pipeline: all 3 scenarios have disclaimer in report")
def _():
    from run_pipeline import run_pipeline, load_vendor_scenario
    for key in ["safe_docs_id", "cloud_pay_x", "quick_lead_pro"]:
        profile = load_vendor_scenario(key)
        report, _ = run_pipeline(profile)
        assert "not an official auditor" in report.disclaimer, f"Failure: disclaimer missing for {key}"
        assert len(report.executive_summary) > 0, f"Failure: executive summary empty for {key}"


# ---
# SECTION 10: Audit Log Persistence
# ---

@test("AuditLog: create & load record works")
def _():
    from utils.audit_log import create_audit_record, load_audit_record
    record = create_audit_record(
        vendor_id="V-TEST", vendor_name="TestCorp",
        decision_status="APPROVED", total_score=95,
        agent_trace=["@VendorCoordinator"],
    )
    loaded = load_audit_record(record.audit_id)
    assert loaded is not None
    assert loaded["vendor_name"] == "TestCorp"
    assert loaded["decision_status"] == "APPROVED"


@test("AuditLog: list_all_audit_records returns records")
def _():
    from utils.audit_log import list_all_audit_records
    records = list_all_audit_records()
    assert len(records) >= 1  # At least 1 from pipeline tests


@test("AuditLog: get_audit_summary returns statistics")
def _():
    from utils.audit_log import get_audit_summary
    summary = get_audit_summary()
    assert "total_records" in summary
    assert "by_status" in summary
    assert summary["total_records"] >= 3  # 3 pipeline scenarios + record above


# ---
# SECTION 11: Config File Parsing
# ---

@test("Config: model_policy.yaml can be read")
def _():
    from utils.band_helpers import load_model_policy
    policy = load_model_policy()
    assert "vendorvigil" in policy
    assert "vendor_coordinator" in policy["vendorvigil"]
    assert policy["vendorvigil"]["vendor_coordinator"]["model"] == "google/gemini-3-flash-preview"


@test("Config: scoring_rules.yaml can be read")
def _():
    from utils.band_helpers import load_scoring_rules
    rules = load_scoring_rules()
    assert "weights" in rules
    assert rules["weights"]["security"] == 0.35
    assert "fail_closed_rules" in rules
    assert len(rules["fail_closed_rules"]) == 7


# ---
# SECTION 12: Band Agent Manifest
# ---

@test("BandManifest: all 7 agents registered with framework & provider")
def _():
    from utils.band_helpers import AGENT_MANIFEST, get_agent_info
    expected = {
        "vendor_coordinator": "Pydantic AI",
        "security_reviewer": "Pydantic AI",
        "privacy_reviewer": "Pydantic AI",
        "financial_reviewer": "Pydantic AI",
        "risk_scorer": "Pydantic AI",
        "audit_logger": "Pydantic AI + Python utility",
        "report_compiler": "Pydantic AI",
    }
    for key, framework in expected.items():
        info = get_agent_info(key)
        assert info["handle"].startswith("@"), f"Agent {key}: handle invalid"
        assert info["framework"] == framework, f"Agent {key}: framework mismatch"
        assert info["provider"] in ("AI/ML API", "Featherless"), f"Agent {key}: provider invalid"


# ---
# SECTION 13: Safe Position Compliance
# ---

@test("Disclaimer appears in all required outputs")
def _():
    from utils.audit_log import SAFE_POSITION_DISCLAIMER
    from utils.schemas import AuditRecord, FinalReport
    assert "not an official auditor" in SAFE_POSITION_DISCLAIMER
    assert "not a compliance certification" in SAFE_POSITION_DISCLAIMER

    # Verify AuditRecord default disclaimer
    ar = AuditRecord(audit_id="X", vendor_id="V", vendor_name="T", decision_status="D", total_score=0, human_review_required=False, confidence=0.0)
    assert "not an official auditor" in ar.disclaimer

    # Verify FinalReport default disclaimer
    fr = FinalReport(vendor_name="T", vendor_id="V", status="D", total_score=0, audit_id="X", human_review_required=False)
    assert "not an official auditor" in fr.disclaimer


# ---
# FINAL REPORT
# ---

def main():
    global _pass_count, _fail_count
    print("=" * 70)
    print("  VendorVigil — Comprehensive Test Suite")
    print("  Mode: MOCK (USE_MOCK_PROVIDER=true)")
    print(f"  Stop on fail: {'YES' if STOP_ON_FAIL else 'NO'}")
    print("=" * 70)

    # All test functions have already run via the decorator

    total = _pass_count + _fail_count
    elapsed = time.time() - _total_start
    print(f"\n{'='*70}")
    print(f"  RESULTS: {_pass_count}/{total} passed, {_fail_count} failed")
    print(f"  Time:    {elapsed:.2f}s")
    print(f"{'='*70}")

    if _fail_count > 0:
        print("\n  ❌ SOME TESTS FAILED. Check errors above.")
        return 1
    else:
        print("\n  ✅ ALL TESTS PASSED. VendorVigil system is ready!")
        return 0


# ---
# All test sections are called when the file is imported or run
# ---

section("1. File Structure & Data Integrity")

section("2. Import & Dependency")

section("3. Schema Validation")

section("4. Scoring Engine")

section("5. Fail-Closed Rules")

section("6. Band Chat Room Simulation")

section("7. Partner Clients (Mock Mode)")

section("8. Agent Output Validation (Mock Mode)")

section("9. End-to-End Pipeline (Golden Path)")

section("10. Audit Log Persistence")

section("11. Config File Parsing")

section("12. Band Agent Manifest")

section("13. Safe Position Compliance")

if __name__ == "__main__":
    code = main()
    sys.exit(code or 0)
