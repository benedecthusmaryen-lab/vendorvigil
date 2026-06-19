"""
VendorVigil — SQLite Assessment Store
======================================
Atomic, concurrent-safe persistence for assessment data using aiosqlite.
Replaces the JSON file-based live_store.py.

Tables:
  - assessments      : One row per assessment/vendor workflow
  - agent_runs       : Per-agent lifecycle events within an assessment
  - assessment_events: Monotonic event log for SSE streaming
  - audit_records    : Immutable audit records
  - idempotency_keys : Idempotency-Key tracking for safe retry

Usage:
    from utils.assessment_store import AssessmentStore
    store = await AssessmentStore.create()
    await store.create_assessment(vendor_name="CloudPayX")
    events = await store.get_events(assessment_id, after_id=5)
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import aiosqlite

from utils.schemas import AgentRole

logger = logging.getLogger("vendorvigil.assessment_store")

DB_DIR = Path(__file__).resolve().parent.parent / "logs"
DB_PATH = DB_DIR / "vendorvigil.db"

# Shared singleton — both API and adapter use the same store instance
_shared_store_instance: AssessmentStore | None = None
_shared_store_lock = None


async def get_shared_store(db_path: str | Path = DB_PATH) -> AssessmentStore:
    """Get or create the shared AssessmentStore singleton."""
    global _shared_store_instance, _shared_store_lock
    if _shared_store_instance is None:
        if _shared_store_lock is None:
            import asyncio
            _shared_store_lock = asyncio.Lock()
        async with _shared_store_lock:
            if _shared_store_instance is None:
                _shared_store_instance = await AssessmentStore.create(db_path)
    return _shared_store_instance


class AssessmentStore:
    """SQLite-backed assessment store with WAL mode and monotonic event IDs."""

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    @classmethod
    async def create(cls, db_path: str | Path = DB_PATH) -> AssessmentStore:
        """Factory: create and initialize the store."""
        store = cls(db_path)
        await store._connect()
        await store._init_schema()
        return store

    async def _connect(self) -> None:
        """Open connection with WAL mode."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")

    async def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        schema = """
        CREATE TABLE IF NOT EXISTS assessments (
            assessment_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL DEFAULT '',
            vendor_name TEXT NOT NULL,
            vendor_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            current_stage TEXT NOT NULL DEFAULT 'CREATED',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            final_result TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id TEXT NOT NULL REFERENCES assessments(assessment_id),
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            result TEXT,
            started_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS assessment_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id TEXT NOT NULL REFERENCES assessments(assessment_id),
            event_type TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_records (
            audit_id TEXT PRIMARY KEY,
            assessment_id TEXT,
            vendor_name TEXT NOT NULL,
            decision_status TEXT NOT NULL,
            total_score INTEGER NOT NULL DEFAULT 0,
            human_review_required INTEGER NOT NULL DEFAULT 0,
            data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS idempotency_keys (
            idempotency_key TEXT PRIMARY KEY,
            assessment_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_events_assessment
            ON assessment_events(assessment_id, event_id);
        CREATE INDEX IF NOT EXISTS idx_runs_assessment
            ON agent_runs(assessment_id);

        -- Durable event ledger: prevents duplicate processing
        CREATE TABLE IF NOT EXISTS processed_events (
            room_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            target_role TEXT NOT NULL DEFAULT '',
            interaction_mode TEXT NOT NULL DEFAULT '',
            workflow_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            claim_owner TEXT,
            lease_expires_at TEXT,
            claimed_at TEXT NOT NULL,
            completed_at TEXT,
            outbound_message_id TEXT,
            failure_code TEXT,
            PRIMARY KEY (room_id, event_id, target_role)
        );

        -- Transactional outbox for external Band delivery
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            room_id TEXT NOT NULL,
            message_type TEXT NOT NULL DEFAULT 'text',
            content TEXT NOT NULL,
            mentions TEXT NOT NULL DEFAULT '[]',
            workflow_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            sent_at TEXT,
            outbound_message_id TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(status, created_at);
        """
        await self._conn.executescript(schema)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    # --- Assessments ---

    async def create_assessment(
        self,
        vendor_name: str,
        vendor_id: str = "",
    ) -> dict[str, Any]:
        """Create a new assessment with default agent lifecycle entries."""
        assessment_id = str(uuid.uuid4())
        workflow_id = f"wf-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        async with self._transaction():
            await self._conn.execute(
                """INSERT INTO assessments
                   (assessment_id, workflow_id, vendor_name, vendor_id,
                    status, started_at)
                   VALUES (?, ?, ?, ?, 'queued', ?)""",
                (assessment_id, workflow_id, vendor_name, vendor_id, now),
            )
            # Create agent lifecycle entries
            for role in AgentRole:
                await self._conn.execute(
                    """INSERT INTO agent_runs
                       (assessment_id, role, status)
                       VALUES (?, ?, 'waiting')""",
                    (assessment_id, role.value),
                )
            # Emit created event
            await self._emit_event(assessment_id, "assessment.created", {
                "vendor_name": vendor_name,
                "vendor_id": vendor_id,
                "workflow_id": workflow_id,
            })

        return {
            "assessment_id": assessment_id,
            "workflow_id": workflow_id,
            "vendor_name": vendor_name,
            "vendor_id": vendor_id,
            "status": "queued",
            "started_at": now,
        }

    async def get_assessment(self, assessment_id: str) -> dict[str, Any] | None:
        """Get assessment by ID with agent lifecycle."""
        async with self._conn.execute(
            "SELECT * FROM assessments WHERE assessment_id = ?",
            (assessment_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None

        result = dict(row)
        # Attach agent runs
        async with self._conn.execute(
            "SELECT * FROM agent_runs WHERE assessment_id = ? ORDER BY id",
            (assessment_id,),
        ) as cursor:
            agents = {}
            async for ar in cursor:
                agents[ar["role"]] = {
                    "status": ar["status"],
                    "result": json.loads(ar["result"]) if ar["result"] else None,
                    "started_at": ar["started_at"],
                    "completed_at": ar["completed_at"],
                }
        result["agents"] = agents
        if result.get("final_result"):
            try:
                result["final_result"] = json.loads(result["final_result"])
            except (json.JSONDecodeError, TypeError):
                pass
        return result

    async def update_assessment_status(
        self, assessment_id: str, status: str
    ) -> None:
        """Update assessment status."""
        now = datetime.now(timezone.utc).isoformat()
        completed_at = now if status in ("completed", "failed") else None
        await self._conn.execute(
            """UPDATE assessments
               SET status = ?, completed_at = COALESCE(?, completed_at)
               WHERE assessment_id = ?""",
            (status, completed_at, assessment_id),
        )
        await self._conn.commit()

    async def list_assessments(
        self, limit: int = 20, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List assessments, newest first."""
        query = "SELECT * FROM assessments"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        async with self._conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_active_assessment(self) -> dict[str, Any] | None:
        """Get the most recent active (running/queued) assessment."""
        async with self._conn.execute(
            """SELECT * FROM assessments
               WHERE status NOT IN ('completed', 'failed')
               ORDER BY started_at DESC LIMIT 1"""
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return await self.get_assessment(row["assessment_id"])

    async def get_latest_assessment(self) -> dict[str, Any] | None:
        """Get the most recent assessment regardless of status."""
        async with self._conn.execute(
            "SELECT * FROM assessments ORDER BY started_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return await self.get_assessment(row["assessment_id"])

    # --- Agent Runs ---

    async def mark_agent_running(self, assessment_id: str, role: str) -> None:
        """Mark an agent as currently running."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            """UPDATE agent_runs
               SET status = 'running', started_at = ?
               WHERE assessment_id = ? AND role = ?""",
            (now, assessment_id, role),
        )
        await self._conn.commit()
        await self._emit_event(assessment_id, "agent.started", {"role": role})

    async def mark_agent_done(
        self, assessment_id: str, role: str, result: dict[str, Any] | None = None
    ) -> None:
        """Mark an agent as done with optional result."""
        now = datetime.now(timezone.utc).isoformat()
        result_json = json.dumps(result) if result else None
        await self._conn.execute(
            """UPDATE agent_runs
               SET status = 'done', result = ?, completed_at = ?
               WHERE assessment_id = ? AND role = ?""",
            (result_json, now, assessment_id, role),
        )
        await self._conn.commit()
        await self._emit_event(assessment_id, "agent.completed", {
            "role": role,
            "result": result,
        })

    async def mark_agent_skipped(self, assessment_id: str, role: str) -> None:
        """Mark an agent as skipped."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            """UPDATE agent_runs
               SET status = 'skipped', completed_at = ?
               WHERE assessment_id = ? AND role = ?""",
            (now, assessment_id, role),
        )
        await self._conn.commit()

    # --- Events (Monotonic SSE) ---

    async def _emit_event(
        self, assessment_id: str, event_type: str, data: dict[str, Any]
    ) -> int:
        """Emit a monotonic event. Returns event_id."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self._conn.execute(
            """INSERT INTO assessment_events
               (assessment_id, event_type, data, created_at)
               VALUES (?, ?, ?, ?)""",
            (assessment_id, event_type, json.dumps(data), now),
        )
        await self._conn.commit()
        return cursor.lastrowid or 0

    async def get_events(
        self, assessment_id: str, after_id: int = 0
    ) -> list[dict[str, Any]]:
        """Get events after a given event_id (for SSE Last-Event-ID)."""
        async with self._conn.execute(
            """SELECT * FROM assessment_events
               WHERE assessment_id = ? AND event_id > ?
               ORDER BY event_id ASC""",
            (assessment_id, after_id),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_latest_event_id(self, assessment_id: str) -> int:
        """Get the latest event ID for an assessment."""
        async with self._conn.execute(
            "SELECT MAX(event_id) FROM assessment_events WHERE assessment_id = ?",
            (assessment_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] or 0 if row else 0

    # --- Audit Records ---

    async def save_audit_record(
        self,
        audit_id: str,
        assessment_id: str | None,
        vendor_name: str,
        decision_status: str,
        total_score: int,
        human_review_required: bool,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Save an immutable audit record."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            """INSERT OR REPLACE INTO audit_records
               (audit_id, assessment_id, vendor_name, decision_status,
                total_score, human_review_required, data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                audit_id, assessment_id, vendor_name, decision_status,
                total_score, 1 if human_review_required else 0,
                json.dumps(data or {}), now,
            ),
        )
        await self._conn.commit()

    async def list_audit_records(self) -> list[dict[str, Any]]:
        """List all audit records."""
        async with self._conn.execute(
            "SELECT * FROM audit_records ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Idempotency ---

    async def try_acquire_idempotency_key(
        self, key: str
    ) -> str | None:
        """Try to acquire an idempotency key.

        Returns existing assessment_id if key exists, None if new.
        """
        # Check if exists
        async with self._conn.execute(
            "SELECT assessment_id FROM idempotency_keys WHERE idempotency_key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            return row["assessment_id"]
        return None

    async def save_idempotency_key(
        self, key: str, assessment_id: str
    ) -> None:
        """Save a new idempotency key."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "INSERT OR IGNORE INTO idempotency_keys VALUES (?, ?, ?)",
            (key, assessment_id, now),
        )
        await self._conn.commit()

    # --- Durable Event Claim ---

    async def claim_event(
        self, room_id: str, event_id: str, target_role: str,
        interaction_mode: str = "", workflow_id: str | None = None,
        claim_owner: str = "", lease_seconds: int = 300,
    ) -> bool:
        """Try to claim an event. Returns True if newly claimed, False if duplicate."""
        now = datetime.now(timezone.utc).isoformat()
        lease_expires = datetime.now(timezone.utc).isoformat()
        # Proper lease offset
        from datetime import timedelta
        lease_expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat()
        try:
            await self._conn.execute(
                """INSERT OR IGNORE INTO processed_events
                   (room_id, event_id, target_role, interaction_mode, workflow_id,
                    status, claim_owner, lease_expires_at, claimed_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (room_id, event_id, target_role, interaction_mode, workflow_id,
                 claim_owner, lease_expires, now),
            )
            await self._conn.commit()
            # Check if our row was inserted
            async with self._conn.execute(
                "SELECT status FROM processed_events WHERE room_id=? AND event_id=? AND target_role=? AND claim_owner=?",
                (room_id, event_id, target_role, claim_owner),
            ) as cursor:
                row = await cursor.fetchone()
                return row is not None
        except Exception as e:
            logger.warning("claim_event: %s", e)
            return False

    async def complete_event(
        self, room_id: str, event_id: str, target_role: str,
        outbound_message_id: str | None = None,
    ) -> None:
        """Mark a claimed event as completed."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE processed_events SET status='completed', completed_at=?, outbound_message_id=COALESCE(?, outbound_message_id) WHERE room_id=? AND event_id=? AND target_role=?",
            (now, outbound_message_id, room_id, event_id, target_role),
        )
        await self._conn.commit()

    async def mark_event_failed(
        self, room_id: str, event_id: str, target_role: str, failure_code: str,
    ) -> None:
        """Mark a claimed event as failed."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE processed_events SET status='failed', completed_at=?, failure_code=? WHERE room_id=? AND event_id=? AND target_role=?",
            (now, failure_code, room_id, event_id, target_role),
        )
        await self._conn.commit()

    async def is_event_claimed(
        self, room_id: str, event_id: str, target_role: str,
    ) -> bool:
        async with self._conn.execute(
            "SELECT 1 FROM processed_events WHERE room_id=? AND event_id=? AND target_role=? AND status='completed'",
            (room_id, event_id, target_role),
        ) as cursor:
            return await cursor.fetchone() is not None

    # --- Transactional Outbox ---

    async def insert_outbox(
        self, idempotency_key: str, room_id: str, content: str,
        mentions: list[str] | None = None, workflow_id: str | None = None,
        message_type: str = "text",
    ) -> int:
        """Insert an outbox record. Returns row ID."""
        now = datetime.now(timezone.utc).isoformat()
        mentions_json = json.dumps(mentions or [])
        try:
            cursor = await self._conn.execute(
                """INSERT OR IGNORE INTO outbox
                   (idempotency_key, room_id, content, mentions, workflow_id, message_type, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (idempotency_key, room_id, content, mentions_json, workflow_id, message_type, now),
            )
            await self._conn.commit()
            return cursor.lastrowid or 0
        except Exception:
            return 0

    async def get_pending_outbox(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get pending outbox records for delivery."""
        async with self._conn.execute(
            "SELECT * FROM outbox WHERE status='pending' ORDER BY id ASC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["mentions"] = json.loads(d["mentions"])
            except Exception:
                d["mentions"] = []
            result.append(d)
        return result

    async def mark_outbox_sent(
        self, outbox_id: int, outbound_message_id: str,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE outbox SET status='sent', sent_at=?, outbound_message_id=?, attempt_count=attempt_count+1 WHERE id=?",
            (now, outbound_message_id, outbox_id),
        )
        await self._conn.commit()

    async def mark_outbox_failed(self, outbox_id: int, error: str) -> None:
        await self._conn.execute(
            "UPDATE outbox SET attempt_count=attempt_count+1, last_error=? WHERE id=?",
            (error[:500], outbox_id),
        )
        await self._conn.commit()

    # --- Final Notification Idempotency ---

    async def persist_final_notification(
        self, assessment_id: str, delivery_status: str, outbound_message_id: str,
    ) -> None:
        """Persist final notification delivery status for restart idempotency."""
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            """INSERT OR REPLACE INTO processed_events
               (room_id, event_id, target_role, status, completed_at, outbound_message_id)
               VALUES ('final_notify', ?, 'coordinator', ?, ?, ?)""",
            (assessment_id, delivery_status, now, outbound_message_id),
        )
        await self._conn.commit()

    async def was_final_notification_sent(self, assessment_id: str) -> bool:
        """Check if final notification was already sent for this assessment."""
        async with self._conn.execute(
            "SELECT 1 FROM processed_events WHERE room_id='final_notify' AND event_id=? AND status='sent'",
            (assessment_id,),
        ) as cursor:
            return await cursor.fetchone() is not None

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        """Context manager for atomic transactions."""
        try:
            yield
        except Exception:
            await self._conn.rollback()
            raise

    async def get_dashboard_summary(self) -> dict[str, Any]:
        """Get aggregated data for the dashboard."""
        active = await self.get_active_assessment()
        latest = await self.get_latest_assessment()
        async with self._conn.execute(
            "SELECT COUNT(*) FROM assessments"
        ) as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0
        async with self._conn.execute(
            "SELECT decision_status, COUNT(*) as cnt FROM audit_records GROUP BY decision_status"
        ) as cursor:
            by_status = {r["decision_status"]: r["cnt"] async for r in cursor}
        async with self._conn.execute(
            "SELECT COUNT(*) FROM audit_records"
        ) as cursor:
            row = await cursor.fetchone()
            audit_total = row[0] if row else 0

        return {
            "active_assessment": active,
            "latest_assessment": latest,
            "total_assessments": total,
            "audit_records": audit_total,
            "audit_by_status": by_status,
        }
