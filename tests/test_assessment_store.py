"""Tests for SQLite AssessmentStore."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from utils.assessment_store import AssessmentStore


@pytest.fixture
async def store(tmp_path):
    db_path = tmp_path / "test.db"
    s = await AssessmentStore.create(db_path)
    yield s
    await s.close()


class TestAssessmentStore:
    async def test_create_assessment(self, store: AssessmentStore):
        a = await store.create_assessment("CloudPayX", "V-002")
        assert a["assessment_id"] is not None
        assert a["vendor_name"] == "CloudPayX"
        assert a["status"] == "queued"
        assert a["workflow_id"].startswith("wf-")

    async def test_get_assessment(self, store: AssessmentStore):
        a = await store.create_assessment("CloudPayX")
        loaded = await store.get_assessment(a["assessment_id"])
        assert loaded is not None
        assert loaded["vendor_name"] == "CloudPayX"
        assert "agents" in loaded
        assert len(loaded["agents"]) == 7  # All AgentRole entries

    async def test_agent_lifecycle(self, store: AssessmentStore):
        a = await store.create_assessment("CloudPayX")
        await store.mark_agent_running(a["assessment_id"], "SecurityReviewer")
        await store.mark_agent_done(a["assessment_id"], "SecurityReviewer", {"score": 85})

        loaded = await store.get_assessment(a["assessment_id"])
        sec = loaded["agents"]["SecurityReviewer"]
        assert sec["status"] == "done"
        assert sec["result"]["score"] == 85

    async def test_monotonic_events(self, store: AssessmentStore):
        a = await store.create_assessment("CloudPayX")
        events = await store.get_events(a["assessment_id"])
        assert len(events) >= 1  # assessment.created
        assert events[0]["event_type"] == "assessment.created"

        # Event IDs should be monotonic
        ids = [e["event_id"] for e in events]
        assert ids == sorted(ids)

    async def test_events_after_id(self, store: AssessmentStore):
        a = await store.create_assessment("CloudPayX")
        await store.mark_agent_running(a["assessment_id"], "SecurityReviewer")
        await store.mark_agent_done(a["assessment_id"], "SecurityReviewer")

        # Get only events after ID 0 (should get all)
        all_events = await store.get_events(a["assessment_id"], after_id=0)
        assert len(all_events) >= 3

        # Get only events after first one
        later_events = await store.get_events(a["assessment_id"], after_id=1)
        assert len(later_events) < len(all_events)

    async def test_idempotency(self, store: AssessmentStore):
        a = await store.create_assessment("SafeDocsID")
        key = "test-idem-key"

        # Key doesn't exist yet
        existing = await store.try_acquire_idempotency_key(key)
        assert existing is None

        # Save key
        await store.save_idempotency_key(key, a["assessment_id"])

        # Now key exists
        existing = await store.try_acquire_idempotency_key(key)
        assert existing == a["assessment_id"]

    async def test_audit_record(self, store: AssessmentStore):
        await store.save_audit_record(
            audit_id="VV-2026-001",
            assessment_id="test-asmt",
            vendor_name="CloudPayX",
            decision_status="ESCALATED",
            total_score=52,
            human_review_required=True,
        )

        records = await store.list_audit_records()
        assert len(records) == 1
        assert records[0]["audit_id"] == "VV-2026-001"

    async def test_list_assessments(self, store: AssessmentStore):
        await store.create_assessment("CloudPayX")
        await store.create_assessment("SafeDocsID")

        assessments = await store.list_assessments()
        assert len(assessments) == 2

    async def test_active_latest(self, store: AssessmentStore):
        a1 = await store.create_assessment("CloudPayX")
        a2 = await store.create_assessment("SafeDocsID")

        active = await store.get_active_assessment()
        assert active is not None
        assert active["assessment_id"] == a2["assessment_id"]

        latest = await store.get_latest_assessment()
        assert latest is not None
        assert latest["assessment_id"] == a2["assessment_id"]
