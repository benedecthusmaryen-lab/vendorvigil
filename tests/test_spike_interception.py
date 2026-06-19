"""
Phase 0.5 — Band SDK Interception Spike
=========================================
Proof-of-concept that wrapping `tools.send_message` BEFORE agent execution
intercepts the LLM's `band_send_message` call and can block unauthorized sends.

This test uses FakeAgentTools (from Band SDK) to simulate the tools object
that the adapter receives. It does NOT need a real Band connection.

Acceptance criteria (behavioral):
  - Without guard: tools.send_message is called
  - With guard blocking: tools.send_message is NOT called (assert_no_messages_sent)
  - With guard allowing: tools.send_message IS called with determined mentions
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from band.testing.fake_tools import FakeAgentTools

from utils.schemas import ActionType, InteractionMode
from utils.handle_resolver import HandleResolver
from utils.action_policy import ActionPolicy
from utils.workflow_state import WorkflowStore
from utils.outbound_guard import OutboundMessageGuard, GuardResult


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def fake_tools():
    """FakeAgentTools that tracks all send_message calls."""
    return FakeAgentTools()


@pytest.fixture
def handle_resolver():
    """HandleResolver with test handles."""
    return HandleResolver({
        "VendorCoordinator": "test-user/vendor-coordinator",
        "SecurityReviewer": "test-user/security-reviewer",
        "PrivacyReviewer": "test-user/privacy-reviewer",
        "FinancialReviewer": "test-user/financial-reviewer",
        "RiskScorer": "test-user/risk-scorer",
        "AuditLogger": "test-user/audit-logger",
        "ReportCompiler": "test-user/report-compiler",
    })


@pytest.fixture
def workflow_store():
    return WorkflowStore()


@pytest.fixture
def action_policy():
    return ActionPolicy()


@pytest.fixture
def outbound_guard(action_policy, handle_resolver, workflow_store):
    return OutboundMessageGuard(action_policy, handle_resolver, workflow_store)


# ============================================================================
# Proof 1: Without guard, send_message IS called (baseline)
# ============================================================================

class TestBaselineSendWithoutGuard:
    """Prove that unwrapped send_message passes LLM mentions directly."""

    async def test_send_message_passes_llm_mentions(self, fake_tools):
        """Without guard, tools.send_message records whatever mentions are passed."""
        await fake_tools.send_message(
            "Security assessment done",
            mentions=["@SecurityReviewer", "@PrivacyReviewer"],
        )
        # Verify message was sent with LLM-chosen mentions
        assert len(fake_tools.messages_sent) == 1
        msg = fake_tools.messages_sent[0]
        assert "@SecurityReviewer" in msg["mentions"]
        assert "@PrivacyReviewer" in msg["mentions"]
        print("PASS: Baseline - send_message records mentions directly")


# ============================================================================
# Proof 2: Wrapping send_message with guard blocks unauthorized sends
# ============================================================================

class TestGuardBlocksUnauthorizedSend:
    """Prove that wrapping tools.send_message with guard blocks unauthorized mentions."""

    async def test_guard_blocks_unauthorized_mentions(self, fake_tools, outbound_guard):
        """Specialist peer mention is blocked by guard-wrapped send_message."""
        original_send = fake_tools.send_message

        # This simulates what the adapter does in _wrap_send_message
        async def guarded_send(content: str, mentions: list[str] | None = None, **kwargs):
            result = outbound_guard.validate_and_prepare(
                sender_role="SecurityReviewer",
                action_type=ActionType.DISPATCH_AGENT_TASK,
                content=content,
                interaction_mode=InteractionMode.COORDINATED_WORKFLOW,
                workflow_id=None,
                event_id="test-evt-1",
                llm_mentions=mentions or [],
            )
            if result.guard_result != GuardResult.SENT:
                # BLOCKED — do NOT call original send
                return None
            # Only call original send with guard-determined mentions
            safe_mentions = result.mentions or mentions or []
            return await original_send(content=content, mentions=safe_mentions)

        # Wrap send_message
        fake_tools.send_message = guarded_send

        # SecurityReviewer tries to dispatch PrivacyReviewer (unauthorized)
        result = await fake_tools.send_message(
            "Hey PrivacyReviewer do this task",
            mentions=["@PrivacyReviewer"],
        )

        # Behavioral assertion: no message reached the transport
        assert result is None, "Guard should return None (blocked)"
        fake_tools.assert_no_messages_sent()
        print("PASS: Guard blocks unauthorized peer dispatch - no messages sent")

    async def test_guard_allows_authorized_dispatch(self, fake_tools, outbound_guard, workflow_store):
        """Coordinator dispatch to next-stage specialist IS allowed."""
        original_send = fake_tools.send_message

        # Create a workflow at SECURITY_PENDING stage
        wf = workflow_store.create_workflow(
            "room-test", "V-002", "CloudPayX",
            human_requester_id="human-1", human_requester_handle="test-human",
        )
        # Advance to ROUTING, then SECURITY_PENDING
        wf = await workflow_store.advance_stage(wf.workflow_id)
        wf = await workflow_store.advance_stage(wf.workflow_id, routing_plan={
            "requires_security_check": True,
            "requires_privacy_check": True,
            "requires_financial_check": True,
        })
        assert wf.current_stage == "SECURITY_PENDING"

        # Guard wrapper
        async def guarded_send(content: str, mentions: list[str] | None = None, **kwargs):
            result = outbound_guard.validate_and_prepare(
                sender_role="VendorCoordinator",
                action_type=ActionType.DISPATCH_AGENT_TASK,
                content=content,
                interaction_mode=InteractionMode.COORDINATED_WORKFLOW,
                workflow_id=wf.workflow_id,
                event_id="test-evt-2",
                llm_mentions=mentions or [],
            )
            if result.guard_result != GuardResult.SENT:
                return None
            safe_mentions = result.mentions or mentions or []
            return await original_send(content=content, mentions=safe_mentions)

        fake_tools.send_message = guarded_send

        # Coordinator dispatches SecurityReviewer (authorized)
        result = await fake_tools.send_message(
            "Please assess CloudPayX security",
            mentions=["@SecurityReviewer"],
        )

        # Behavioral assertion: message WAS sent (with guard-determined mentions)
        assert result is not None, "Guard should allow authorized dispatch"
        assert len(fake_tools.messages_sent) == 1
        print(f"PASS: Guard allows authorized dispatch - message sent: {fake_tools.messages_sent[0]}")

    async def test_guard_ignores_llm_mentions(self, fake_tools, outbound_guard, workflow_store):
        """Guard-determined recipient replaces LLM's arbitrary mentions."""
        original_send = fake_tools.send_message

        wf = workflow_store.create_workflow(
            "room-test2", "V-002", "CloudPayX",
            human_requester_id="human-1", human_requester_handle="test-human",
        )
        wf = await workflow_store.advance_stage(wf.workflow_id)
        wf = await workflow_store.advance_stage(wf.workflow_id, routing_plan={
            "requires_security_check": True,
            "requires_privacy_check": True,
            "requires_financial_check": True,
        })

        async def guarded_send(content: str, mentions: list[str] | None = None, **kwargs):
            result = outbound_guard.validate_and_prepare(
                sender_role="VendorCoordinator",
                action_type=ActionType.DISPATCH_AGENT_TASK,
                content=content,
                interaction_mode=InteractionMode.COORDINATED_WORKFLOW,
                workflow_id=wf.workflow_id,
                event_id="test-evt-3",
                llm_mentions=mentions or [],
            )
            if result.guard_result != GuardResult.SENT:
                return None
            safe_mentions = result.mentions or mentions or []
            return await original_send(content=result.sanitized_content, mentions=safe_mentions)

        fake_tools.send_message = guarded_send

        # LLM tries to send to PrivacyReviewer BUT workflow expects SecurityReviewer
        result = await fake_tools.send_message(
            "Please assess CloudPayX security",
            mentions=["@PrivacyReviewer"],  # LLM chose WRONG recipient
        )

        # Guard REPLACES wrong LLM mentions with correct runtime-determined recipient
        assert result is not None, "Guard should not block, it replaces mentions"
        assert len(fake_tools.messages_sent) == 1
        sent = fake_tools.messages_sent[0]
        # Mentions should be the guard-determined SecurityReviewer, NOT PrivacyReviewer
        assert "test-user/security-reviewer" in sent["mentions"], (
            f"Expected guard to replace LLM's @PrivacyReviewer with SecurityReviewer. "
            f"Got mentions: {sent['mentions']}"
        )
        # Verify the wrong mention was NOT used
        assert "privacy-reviewer" not in str(sent["mentions"]).lower(), (
            f"LLM's wrong mention @PrivacyReviewer should have been replaced. "
            f"Got: {sent['mentions']}"
        )
        print(f"PASS: Guard replaced LLM mentions with runtime-determined recipient: {sent['mentions']}")


# ============================================================================
# Proof 3: Mock-mode guard equivalence
# ============================================================================

class TestMockModeAlsoUsesGuard:
    """Prove the mock path also goes through the same guard."""

    async def test_mock_path_uses_same_guard(self, fake_tools, outbound_guard):
        """Mock mode should also call guard before tools.send_message."""
        original_send = fake_tools.send_message

        async def guarded_send(content: str, mentions: list[str] | None = None, **kwargs):
            result = outbound_guard.validate_and_prepare(
                sender_role="SecurityReviewer",
                action_type=ActionType.SUBMIT_DOMAIN_RESULT,
                content=content,
                interaction_mode=InteractionMode.COORDINATED_WORKFLOW,
                workflow_id="wf-mock",
                event_id="mock-evt-1",
                llm_mentions=mentions or [],
            )
            if result.guard_result != GuardResult.SENT:
                return None
            return await original_send(content=result.sanitized_content, mentions=result.mentions or [])

        fake_tools.send_message = guarded_send

        # SecurityReviewer submits result to VendorCoordinator (authorized)
        result = await fake_tools.send_message(
            "Security assessment complete for CloudPayX",
            mentions=["@VendorCoordinator"],
        )

        assert result is not None, "Authorized submission should pass"
        assert len(fake_tools.messages_sent) == 1
        print("PASS: Mock path uses same guard - authorized submission passes")

    async def test_mock_path_blocked_by_guard(self, fake_tools, outbound_guard):
        """Mock mode also blocks unauthorized sends via guard."""
        original_send = fake_tools.send_message

        async def guarded_send(content: str, mentions: list[str] | None = None, **kwargs):
            result = outbound_guard.validate_and_prepare(
                sender_role="SecurityReviewer",
                action_type=ActionType.DISPATCH_AGENT_TASK,
                content=content,
                interaction_mode=InteractionMode.COORDINATED_WORKFLOW,
                workflow_id="wf-mock",
                event_id="mock-evt-2",
                llm_mentions=mentions or [],
            )
            if result.guard_result != GuardResult.SENT:
                return None
            return await original_send(content=content, mentions=result.mentions or [])

        fake_tools.send_message = guarded_send

        # SecurityReviewer tries to dispatch PrivacyReviewer (unauthorized)
        result = await fake_tools.send_message(
            "PrivacyReviewer please assess privacy",
            mentions=["@PrivacyReviewer"],
        )

        assert result is None, "Blocked dispatch should return None"
        fake_tools.assert_no_messages_sent()
        print("PASS: Mock path blocked by guard - unauthorized dispatch prevented")


# ============================================================================
# Run if called directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
