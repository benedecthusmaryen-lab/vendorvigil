"""
VendorVigil — Live Results Store
A file-based bridge between running Band agents and the Streamlit dashboard.
Agents write results here as they complete; the dashboard polls this store.

Directory structure:
    logs/live/
    ├── session_<timestamp>.json   # active session (current assessment run)
    └── completed/
        └── <vendor_id>_<timestamp>.json  # finished assessments
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.schemas import AgentRole

logger = logging.getLogger(__name__)

# Default directories
_BASE_DIR = Path(__file__).parent.parent / "logs"
LIVE_DIR = _BASE_DIR / "live"
COMPLETED_DIR = LIVE_DIR / "completed"

# Map of canonical AgentRole values to short keys
_AGENT_ROLE_TO_SHORT: dict[str, str] = {
    role.value: role.short_key
    for role in AgentRole
}


def _ensure_dirs() -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)


# ---
# Session Management
# ---

def create_session(vendor_name: str, vendor_id: str = "") -> dict[str, Any]:
    """Create a new assessment session and persist it.

    A session tracks the progress of a single vendor assessment through
    all 7 agents.
    """
    _ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    session_id = f"session_{ts}"

    session = {
        "session_id": session_id,
        "vendor_name": vendor_name,
        "vendor_id": vendor_id,
        "status": "running",           # running | completed | failed
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "agents": {
            role.value: {"status": "waiting", "result": None, "started_at": None, "completed_at": None}
            for role in AgentRole
        },
        "chat_messages": [],  # list of {sender, content, timestamp}
        "final_result": None, # compiled final result when complete
    }

    _save_session(session)
    logger.info("Live session created: %s for vendor %s", session_id, vendor_name)
    return session


def _session_path(session_id: str) -> Path:
    return LIVE_DIR / f"{session_id}.json"


def _save_session(session: dict[str, Any]) -> None:
    _ensure_dirs()
    path = _session_path(session["session_id"])
    path.write_text(json.dumps(session, indent=2, default=str))


def load_session(session_id: str) -> dict[str, Any] | None:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def get_active_session() -> dict[str, Any] | None:
    """Return the most recent session that is still running."""
    _ensure_dirs()
    sessions = sorted(LIVE_DIR.glob("session_*.json"), reverse=True)
    for path in sessions:
        try:
            s = json.loads(path.read_text())
            if s.get("status") == "running":
                return s
        except Exception:
            continue
    return None


def get_latest_session() -> dict[str, Any] | None:
    """Return the most recent session regardless of status."""
    _ensure_dirs()
    sessions = sorted(LIVE_DIR.glob("session_*.json"), reverse=True)
    for path in sessions:
        try:
            return json.loads(path.read_text())
        except Exception:
            continue
    return None


# ---
# Agent Status Updates
# ---

def mark_agent_running(session_id: str, role: str) -> None:
    """Mark an agent as currently running."""
    session = load_session(session_id)
    if not session:
        return
    if role in session["agents"]:
        session["agents"][role]["status"] = "running"
        session["agents"][role]["started_at"] = datetime.now(timezone.utc).isoformat()
        _save_session(session)
        logger.debug("Agent %s marked as running in session %s", role, session_id)


def mark_agent_done(session_id: str, role: str, result: dict[str, Any]) -> None:
    """Mark an agent as done and store its parsed result.

    Supports 'done' and 'skipped' statuses for completion check.
    """
    session = load_session(session_id)
    if not session:
        return
    if role in session["agents"]:
        session["agents"][role]["status"] = "done"
        session["agents"][role]["result"] = result
        session["agents"][role]["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Check if all agents are done or skipped -> mark session complete
        all_done = all(
            a["status"] in ("done", "skipped")
            for a in session["agents"].values()
        )
        if all_done:
            session["status"] = "completed"
            session["completed_at"] = datetime.now(timezone.utc).isoformat()
            _archive_session(session)

        _save_session(session)
        logger.info("Agent %s completed in session %s", role, session_id)


def mark_agent_skipped(session_id: str, role: str) -> None:
    """Mark an agent as skipped (not required by routing plan)."""
    session = load_session(session_id)
    if not session:
        return
    if role in session["agents"]:
        session["agents"][role]["status"] = "skipped"
        _save_session(session)
        logger.info("Agent %s skipped in session %s", role, session_id)


def add_chat_message(session_id: str, sender: str, content: str) -> None:
    """Append a chat message to the session transcript."""
    session = load_session(session_id)
    if not session:
        return
    session["chat_messages"].append({
        "sender": sender,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_session(session)


def set_final_result(session_id: str, result: dict[str, Any]) -> None:
    """Store the compiled final result for the session."""
    session = load_session(session_id)
    if not session:
        return
    session["final_result"] = result
    _save_session(session)


# ---
# Archiving completed sessions
# ---

def _archive_session(session: dict[str, Any]) -> None:
    """Save a copy of a completed session to the completed/ directory."""
    _ensure_dirs()
    vendor = session.get("vendor_id", session.get("vendor_name", "unknown"))
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = COMPLETED_DIR / f"{vendor}_{ts}.json"
    try:
        path.write_text(json.dumps(session, indent=2, default=str))
        logger.info("Session archived: %s", path.name)
    except Exception as e:
        logger.warning("Failed to archive session: %s", e)


def list_completed_sessions() -> list[dict[str, Any]]:
    """Return all completed sessions, newest first."""
    _ensure_dirs()
    results = []
    for path in sorted(COMPLETED_DIR.glob("*.json"), reverse=True):
        try:
            results.append(json.loads(path.read_text()))
        except Exception:
            continue
    return results


# ---
# Dashboard-friendly summary
# ---

def get_dashboard_summary() -> dict[str, Any]:
    """Get a complete summary for the dashboard: active + completed sessions."""
    active = get_active_session()
    latest = get_latest_session()
    completed = list_completed_sessions()

    # Also include audit log records
    from utils.audit_log import get_audit_summary
    audit = get_audit_summary()

    return {
        "active_session": active,
        "latest_session": latest,
        "completed_sessions": completed,
        "audit_summary": audit,
        "total_completed": len(completed),
    }
