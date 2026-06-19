"""
VendorVigil — Audit Log Utility
Creates immutable audit records with unique IDs, timestamps,
agent trace, and mandatory safe-position disclaimer.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.schemas import AuditRecord

logger = logging.getLogger(__name__)

# Audit log directory — can be overridden via env var
AUDIT_DIR = Path(os.getenv("VENDORVIGIL_AUDIT_DIR", str(Path(__file__).parent.parent / "logs")))

# In-memory counter for audit IDs (resets on restart)
_counter = 0


def _ensure_audit_dir() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def generate_audit_id() -> str:
    """Generate unique audit ID: VV-YYYY-NNN."""
    global _counter
    _counter += 1
    year = datetime.now(timezone.utc).year
    return f"VV-{year}-{_counter:03d}"


def create_audit_record(
    vendor_id: str,
    vendor_name: str,
    decision_status: str,
    total_score: int,
    evidence_summary: list[str] | None = None,
    agent_trace: list[str] | None = None,
    human_review_required: bool = False,
    confidence: float = 0.0,
) -> AuditRecord:
    """Create an immutable audit record for a vendor assessment."""
    audit_id = generate_audit_id()

    record = AuditRecord(
        audit_id=audit_id,
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        decision_status=decision_status,
        total_score=total_score,
        evidence_summary=evidence_summary or [],
        agent_trace=agent_trace or [],
        human_review_required=human_review_required,
        confidence=confidence,
    )

    _persist_audit_record(record)
    logger.info(f"Audit record created: {audit_id} | {vendor_name} | {decision_status}")
    return record


def _persist_audit_record(record: AuditRecord) -> None:
    """Persist audit record to JSON file."""
    _ensure_audit_dir()
    file_path = AUDIT_DIR / f"{record.audit_id}.json"
    try:
        record_dict = record.model_dump(mode="json")
        record_dict["created_at"] = datetime.now(timezone.utc).isoformat()
        file_path.write_text(json.dumps(record_dict, indent=2, default=str))
    except Exception as e:
        logger.error(f"Failed to persist audit record {record.audit_id}: {e}")


def load_audit_record(audit_id: str) -> dict[str, Any] | None:
    """Load a previously saved audit record by ID."""
    file_path = AUDIT_DIR / f"{audit_id}.json"
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text())


def list_all_audit_records() -> list[dict[str, Any]]:
    """List all audit records sorted by creation time (newest first)."""
    _ensure_audit_dir()
    records: list[dict[str, Any]] = []
    for f in sorted(AUDIT_DIR.glob("VV-*.json"), reverse=True):
        try:
            records.append(json.loads(f.read_text()))
        except Exception:
            continue
    return records


def get_audit_summary() -> dict[str, Any]:
    """Get a dashboard-friendly summary of all audit records."""
    records = list_all_audit_records()
    total = len(records)
    by_status: dict[str, int] = {}
    for r in records:
        status = r.get("decision_status", "UNKNOWN")
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total_records": total,
        "by_status": by_status,
        "records": records,
    }


# ---
# Disclaimer — must appear in README, UI, slides, and video
# ---

SAFE_POSITION_DISCLAIMER = (
    "VendorVigil is a decision support tool for initial vendor risk triage. "
    "This system is not an official auditor, not a compliance certification, "
    "and not a replacement for human judgment."
)
