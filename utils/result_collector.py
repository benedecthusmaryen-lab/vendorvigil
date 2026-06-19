"""
VendorVigil — Agent Output Parser
Parses markdown-formatted agent messages from the Band chat room
into structured Pydantic objects for the dashboard.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---
# Agent name → role mapping
# ---

AGENT_ROLES: dict[str, str] = {
    "SecurityReviewer": "security",
    "PrivacyReviewer": "privacy",
    "FinancialReviewer": "financial",
    "RiskScorer": "risk",
    "ReportCompiler": "report",
    "AuditLogger": "audit",
    "VendorCoordinator": "coordinator",
}


def detect_agent_role(sender_name: str) -> str | None:
    """Detect which agent sent a message based on sender name."""
    for key, role in AGENT_ROLES.items():
        if key.lower() in sender_name.lower():
            return role
    return None


# ---
# Generic helpers
# ---

def _extract_score(text: str) -> int | None:
    """Extract a score like 'Score: 72/100' or 'Total Score: 65/100'."""
    m = re.search(r"(?:Score|Total\s+Score)[:\s]*(\d+)\s*/\s*100", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _extract_confidence(text: str) -> float | None:
    """Extract confidence like 'Confidence: 0.85'."""
    m = re.search(r"Confidence[:\s]*([\d.]+)", text, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _extract_vendor_name(text: str) -> str:
    """Extract vendor name from headers like '## Security Assessment: CloudPayX'."""
    m = re.search(r"##\s*[^:]+:\s*(.+)", text)
    if m:
        return m.group(1).strip().rstrip("*").strip()
    return "Unknown Vendor"


def _extract_status(text: str) -> str:
    """Extract status like 'Status: APPROVED' or 'Status: ESCALATED'."""
    m = re.search(r"\*\*Status[:\s]*\*\*\s*[:\s]*(APPROVED|NEEDS_REVISION|ESCALATED|TEMPORARILY_REJECTED)", text, re.I)
    if m:
        return m.group(1).upper()
    # Also try without bold markers
    m = re.search(r"Status[:\s]+(APPROVED|NEEDS_REVISION|ESCALATED|TEMPORARILY_REJECTED)", text, re.I)
    if m:
        return m.group(1).upper()
    return "UNKNOWN"


def _extract_human_review(text: str) -> bool:
    """Extract 'Human Review: YES' or 'Human Review: NO'."""
    m = re.search(r"Human\s+Review[:\s]*(YES|NO)", text, re.I)
    if m:
        return m.group(1).upper() == "YES"
    return False


def _extract_table_rows(text: str) -> list[tuple[str, str]]:
    """Extract markdown table rows as (col1, col2) tuples."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and "---" not in line and line.count("|") >= 3:
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) >= 2 and cols[0].lower() not in ("evidence", "criterion", "category"):
                # Skip header row by checking common header keywords
                if not any(kw in cols[0].lower() for kw in ("evidence", "criterion", "category", "---")):
                    rows.append((cols[0], cols[1]))
    return rows


def _extract_bullets(text: str, section_header: str) -> list[str]:
    """Extract bullet points under a given section header."""
    pattern = re.compile(
        rf"\*\*{re.escape(section_header)}[:\s]*\*\*[:\s]*\n((?:\s*[-*•]\s*.+\n?)+)",
        re.I,
    )
    m = pattern.search(text)
    if not m:
        # Try without bold
        pattern2 = re.compile(
            rf"{re.escape(section_header)}[:\s]*\n((?:\s*[-*•]\s*.+\n?)+)",
            re.I,
        )
        m = pattern2.search(text)
    if m:
        block = m.group(1)
        return [
            line.strip().lstrip("-*• ").strip()
            for line in block.strip().splitlines()
            if line.strip().startswith(("-", "*", "•"))
        ]
    return []


def _extract_numbered_list(text: str, section_header: str) -> list[str]:
    """Extract numbered list items under a section header."""
    pattern = re.compile(
        rf"##?\s*{re.escape(section_header)}[:\s]*\n((?:\s*\d+\.\s*.+\n?)+)",
        re.I,
    )
    m = pattern.search(text)
    if m:
        block = m.group(1)
        return [
            re.sub(r"^\d+\.\s*", "", line.strip())
            for line in block.strip().splitlines()
            if re.match(r"\s*\d+\.", line)
        ]
    return []


# ---
# Per-agent parsers
# ---

def parse_security_assessment(content: str) -> dict[str, Any]:
    """Parse @SecurityReviewer markdown output."""
    score = _extract_score(content) or 0
    confidence = _extract_confidence(content) or 0.0
    vendor = _extract_vendor_name(content)
    rows = _extract_table_rows(content)

    evidence: dict[str, str] = {}
    for col1, col2 in rows:
        evidence[col1] = col2

    findings = _extract_bullets(content, "Key Findings")
    critical_gaps = _extract_bullets(content, "Critical Gaps")
    missing = [k for k, v in evidence.items() if "missing" in v.lower()]

    return {
        "role": "security",
        "vendor_name": vendor,
        "score": score,
        "confidence": confidence,
        "evidence_table": evidence,
        "findings": findings,
        "critical_gaps": critical_gaps,
        "missing_evidence": missing,
        "raw_markdown": content,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_privacy_assessment(content: str) -> dict[str, Any]:
    """Parse @PrivacyReviewer markdown output."""
    score = _extract_score(content) or 0
    confidence = _extract_confidence(content) or 0.0
    vendor = _extract_vendor_name(content)
    rows = _extract_table_rows(content)

    evidence: dict[str, str] = {}
    for col1, col2 in rows:
        evidence[col1] = col2

    findings = _extract_bullets(content, "Key Findings")
    critical_gaps = _extract_bullets(content, "Critical Gaps")
    missing = [k for k, v in evidence.items() if "missing" in v.lower() or "unknown" in v.lower()]

    # Check personal data processed
    personal_data = False
    m = re.search(r"Personal\s+Data\s+Processed[:\s]*(YES|NO)", content, re.I)
    if m:
        personal_data = m.group(1).upper() == "YES"

    return {
        "role": "privacy",
        "vendor_name": vendor,
        "score": score,
        "confidence": confidence,
        "evidence_table": evidence,
        "findings": findings,
        "critical_gaps": critical_gaps,
        "missing_evidence": missing,
        "personal_data_processed": personal_data,
        "raw_markdown": content,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_financial_assessment(content: str) -> dict[str, Any]:
    """Parse @FinancialReviewer markdown output."""
    score = _extract_score(content) or 0
    confidence = _extract_confidence(content) or 0.0
    vendor = _extract_vendor_name(content)
    rows = _extract_table_rows(content)

    criteria: dict[str, str] = {}
    for col1, col2 in rows:
        criteria[col1] = col2

    risk_notes = _extract_bullets(content, "Risk Notes")
    findings = _extract_bullets(content, "Key Findings")

    # Extract recommendation
    recommendation = "UNKNOWN"
    m = re.search(r"\*\*Recommendation[:\s]*\*\*\s*[:\s]*(APPROVED|CONDITIONAL|REJECTED)", content, re.I)
    if m:
        recommendation = m.group(1).upper()

    return {
        "role": "financial",
        "vendor_name": vendor,
        "score": score,
        "confidence": confidence,
        "criteria_table": criteria,
        "findings": findings,
        "risk_notes": risk_notes,
        "recommendation": recommendation,
        "raw_markdown": content,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_risk_decision(content: str) -> dict[str, Any]:
    """Parse @RiskScorer markdown output."""
    total_score = _extract_score(content) or 0
    status = _extract_status(content)
    human_review = _extract_human_review(content)
    vendor = _extract_vendor_name(content)
    rows = _extract_table_rows(content)

    domain_scores: dict[str, int] = {}
    for col1, col2 in rows:
        m = re.search(r"(\d+)", col2)
        if m:
            key = col1.lower().strip()
            if "security" in key:
                domain_scores["security"] = int(m.group(1))
            elif "privacy" in key:
                domain_scores["privacy"] = int(m.group(1))
            elif "financial" in key:
                domain_scores["financial"] = int(m.group(1))
            elif "evidence" in key:
                domain_scores["evidence"] = int(m.group(1))

    reasoning = _extract_bullets(content, "Reasoning")
    if not reasoning:
        # Try extracting from "**Reasoning:** ..." single line
        m = re.search(r"\*\*Reasoning[:\s]*\*\*\s*[:\s]*(.+?)(?:\n|$)", content)
        if m:
            reasoning = [m.group(1).strip()]

    return {
        "role": "risk",
        "vendor_name": vendor,
        "total_score": total_score,
        "status": status,
        "domain_scores": domain_scores,
        "human_review_required": human_review,
        "reasoning": reasoning,
        "raw_markdown": content,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_report(content: str) -> dict[str, Any]:
    """Parse @ReportCompiler markdown output."""
    total_score = _extract_score(content) or 0
    status = _extract_status(content)
    vendor = _extract_vendor_name(content)
    rows = _extract_table_rows(content)

    domain_scores: dict[str, int] = {}
    for col1, col2 in rows:
        m = re.search(r"(\d+)", col2)
        if m:
            key = col1.lower().strip()
            if "security" in key:
                domain_scores["security"] = int(m.group(1))
            elif "privacy" in key:
                domain_scores["privacy"] = int(m.group(1))
            elif "financial" in key:
                domain_scores["financial"] = int(m.group(1))
            elif "evidence" in key:
                domain_scores["evidence"] = int(m.group(1))

    gaps = _extract_bullets(content, "Key Gaps & Findings")
    if not gaps:
        gaps = _extract_bullets(content, "Key Gaps")
    actions = _extract_numbered_list(content, "Recommended Actions")
    if not actions:
        actions = _extract_bullets(content, "Recommended Actions")

    # Executive summary
    exec_summary = ""
    m = re.search(r"##\s*Executive\s+Summary\s*\n(.+?)(?=\n##|\n\*\*|$)", content, re.S)
    if m:
        exec_summary = m.group(1).strip()

    # Date
    date_str = ""
    m = re.search(r"\*\*Date[:\s]*\*\*\s*[:\s]*(.+?)(?:\n|$)", content)
    if m:
        date_str = m.group(1).strip()

    return {
        "role": "report",
        "vendor_name": vendor,
        "total_score": total_score,
        "status": status,
        "domain_scores": domain_scores,
        "gaps": gaps,
        "recommended_actions": actions,
        "executive_summary": exec_summary,
        "report_date": date_str,
        "raw_markdown": content,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_audit_record(content: str) -> dict[str, Any]:
    """Parse @AuditLogger markdown output."""
    vendor = _extract_vendor_name(content)
    status = _extract_status(content)
    total_score = _extract_score(content) or 0

    # Extract audit ID
    audit_id = ""
    m = re.search(r"\*\*ID[:\s]*\*\*\s*[:\s]*(VV-\d+-\d+)", content)
    if m:
        audit_id = m.group(1)

    # Extract date
    date_str = ""
    m = re.search(r"\*\*Date[:\s]*\*\*\s*[:\s]*(.+?)(?:\n|$)", content)
    if m:
        date_str = m.group(1).strip()

    return {
        "role": "audit",
        "vendor_name": vendor,
        "audit_id": audit_id,
        "status": status,
        "total_score": total_score,
        "record_date": date_str,
        "raw_markdown": content,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---
# Universal parser — routes to the correct parser based on agent role
# ---

_PARSERS = {
    "security": parse_security_assessment,
    "privacy": parse_privacy_assessment,
    "financial": parse_financial_assessment,
    "risk": parse_risk_decision,
    "report": parse_report,
    "audit": parse_audit_record,
}


def parse_agent_message(sender_name: str, content: str) -> dict[str, Any] | None:
    """Parse any agent message and return structured data.

    Returns None if the sender is not a recognized agent or if the
    message does not contain parseable assessment output.
    """
    role = detect_agent_role(sender_name)
    if role is None or role == "coordinator":
        return None

    parser = _PARSERS.get(role)
    if parser is None:
        return None

    try:
        result = parser(content)
        result["agent_name"] = sender_name
        return result
    except Exception as e:
        logger.warning("Failed to parse message from %s: %s", sender_name, e)
        return None
