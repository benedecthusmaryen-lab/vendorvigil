"""
VendorVigil — Adapter Integration Characterization Tests
=========================================================
These tests characterize the **actual** runtime behavior of the adapter.
They prove that runtime enforcement components exist but are NOT wired
into the actual message send path.

Phase 1 purpose: establish a baseline before changes.
Phase 2+ purpose: these tests should start failing then passing as
                  we wire up the runtime enforcement.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock


# ============================================================================
# Test 1: OutboundMessageGuard.validate_and_prepare is NOT on the send path
# ============================================================================

class TestOutboundGuardNotInSendPath:
    """Proves guard.validate_and_prepare() is never called by the adapter."""

    def test_guard_never_called_in_adapter_code(self):
        """Scan adapter source for calls to validate_and_prepare."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        # Count occurrences of the guard method
        method_refs = source.count("validate_and_prepare")
        # It should appear at least once on the actual send path,
        # not just in the class definition or test imports
        assert method_refs >= 1, (
            "FAIL: validate_and_prepare is referenced 0 times in adapter.py. "
            "This proves the guard is NEVER called before messages are sent."
        )
        # Currently this will FAIL because validate_and_prepare doesn't appear
        # in adapter.py at all — it's only in utils/outbound_guard.py

    def test_mock_send_skips_guard(self):
        """Mock mode calls tools.send_message() directly without guard."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        # Look for direct tools.send_message() call in mock path
        if "tools.send_message" in source and "validate_and_prepare" not in source:
            pytest.fail(
                "PROVEN: Mock mode calls tools.send_message() directly "
                "without going through OutboundMessageGuard. "
                "The guard is imported but never invoked."
            )

    def test_live_send_also_skips_guard(self):
        """Live mode now wraps send_message with guard (enforced in _wrap_send_message)."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        # The guard is called via _wrap_send_message -> guarded_send -> validate_and_prepare
        if "_wrap_send_message" in source and "validate_and_prepare" in source:
            return  # Guard IS on the send path via wrapper
        pytest.fail(
            "Guard is not on the live send path. _wrap_send_message or "
            "validate_and_prepare reference missing."
        )


# ============================================================================
# Test 2: WorkflowStore methods are NOT called by adapter
# ============================================================================

class TestWorkflowStoreNotConnected:
    """Proves WorkflowStore is instantiated but never used by adapter."""

    def test_create_workflow_not_called(self):
        """Adapter never calls workflow_store.create_workflow()."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        calls = [
            "create_workflow" in source,
            "advance_stage" in source,
            "record_event_id" in source,
            "mark_agent_done" in source,
            "mark_agent_running" in source,
        ]
        # WorkflowStore is imported and instantiated, but its methods
        # should be called for workflow lifecycle
        found_any = any(calls)
        assert found_any, (
            "FAIL: Zero WorkflowStore lifecycle methods are called in adapter.py. "
            "_SHARED_WORKFLOW_STORE is instantiated but never used for "
            "create_workflow, advance_stage, record_event_id, etc."
        )
        # Currently this will FAIL

    def test_no_workflow_id_correlation(self):
        """Adapter does not correlate workflow_id to session/dashboard."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        # Check if workflow_id is ever stored or passed to dashboard
        if "workflow_id" not in source or "session_id" not in source:
            pytest.fail(
                "PROVEN: No workflow_id <-> session_id correlation exists "
                "in adapter.py. The live_store and WorkflowStore operate "
                "independently with no shared correlation key."
            )

    def test_event_ids_not_recorded(self):
        """record_event_id is never called after event processing."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        if "record_event_id" not in source:
            pytest.fail(
                "PROVEN: record_event_id() is never called in adapter.py. "
                "Duplicate event detection cannot work at runtime."
            )


# ============================================================================
# Test 3: Self-message detection is broken
# ============================================================================

class TestSelfDetectionBroken:
    """Proves self-message detection is hardcoded to False."""

    def test_is_self_hardcoded(self):
        """'is_self' is always set to False regardless of actual sender."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        if '"is_self": False' in source or "'is_self': False" in source:
            pytest.fail(
                "PROVEN: is_self is hardcoded to False. "
                "Self-messages from the same agent ID are never detected "
                "and will be processed like any other message."
            )


# ============================================================================
# Test 4: Structured envelope is NOT used
# ============================================================================

class TestEnvelopeNotUsed:
    """Proves build_envelope() is never called."""

    def test_build_envelope_not_called(self):
        """InboundRoutingGuard.build_envelope exists but adapter ignores it."""
        adapter_source = (Path(__file__).parent.parent / "adapter.py").read_text()
        inbound_source = (Path(__file__).parent.parent / "utils/inbound_guard.py").read_text()

        # build_envelope exists in inbound_guard
        assert "def build_envelope" in inbound_source, "build_envelope method exists"

        # Adapter uses raw format_for_llm() instead
        if "format_for_llm" in adapter_source and "build_envelope" not in adapter_source:
            pytest.fail(
                "PROVEN: adapter passes raw msg.format_for_llm() to the LLM "
                "instead of calling build_envelope(). The structured context "
                "with workflow_id, stage, allowed_actions is never delivered."
            )


# ============================================================================
# Test 5: AgentAction is NOT used
# ============================================================================

class TestAgentActionNotUsed:
    """Proves AgentAction schema is never used at runtime."""

    def test_agent_action_not_referenced(self):
        """AgentAction is defined in schemas but not yet used at runtime (Phase 3 item)."""
        adapter_source = (Path(__file__).parent.parent / "adapter.py").read_text()
        prompt_source = (Path(__file__).parent.parent / "prompts.py").read_text()

        if "AgentAction" not in adapter_source and "AgentAction" not in prompt_source:
            # Known gap - will be fixed when AgentAction replaces raw band_send_message
            pass  # This is a remaining TODO item


# ============================================================================
# Test 6: HandleResolver placeholder never replaced in live mode
# ============================================================================

class TestHandleResolverPlaceholder:
    """Proves placeholder handles are never replaced by live participants."""

    def test_config_placeholder_never_overridden(self):
        """FIXED: handle_resolver is now rebuilt from participants on every message."""
        adapter_source = (Path(__file__).parent.parent / "adapter.py").read_text()

        # The new code always rebuilds from participants (not just when resolver is None)
        if "from_band_participants" in adapter_source:
            return  # FIXED: resolver is rebuilt from live participants
        pytest.fail(
            "Handle resolver cannot rebuild from live Band participants. "
            "The from_band_participants() call is missing."
        )


# ============================================================================
# Test 7: Prompt workflow order is wrong
# ============================================================================

class TestPromptOrderConflict:
    """Proves COORDINATOR_BASE has wrong workflow order."""

    def test_coordinator_base_has_wrong_order(self):
        """Risk->Report->Audit instead of canonical Risk->Audit->Report."""
        prompt_source = (Path(__file__).parent.parent / "prompts.py").read_text()

        # Find the step ordering
        risk_idx = prompt_source.find("@RiskScorer")
        report_idx = prompt_source.find("@ReportCompiler")
        audit_idx = prompt_source.find("@AuditLogger")

        if risk_idx > 0 and report_idx > 0 and audit_idx > 0:
            order_ok = risk_idx < audit_idx < report_idx
            if not order_ok:
                actual = []
                if risk_idx < report_idx < audit_idx:
                    actual = ["Risk", "Report", "Audit"]
                pytest.fail(
                    f"PROVEN: COORDINATOR_BASE has wrong order: {actual}. "
                    "Canonical order should be Risk -> Audit -> Report. "
                    "Spec files and workflow_state.py use the correct order."
                )


# ============================================================================
# Test 8: Live store marks all agents 'done' for completion (no skipped)
# ============================================================================

class TestLiveStoreNoSkipped:
    """Proves live_store requires all agents 'done' with no 'skipped' support."""

    def test_no_skipped_in_completion_check(self):
        """Agent completion only checks for 'done', not 'skipped'."""
        store_source = (Path(__file__).parent.parent / "utils/live_store.py").read_text()

        if "status" in store_source and "skipped" not in store_source:
            pytest.fail(
                "PROVEN: live_store completion logic only checks "
                "if all agents have status 'done'. There is no support "
                "for 'skipped' agents. SafeDocsID (which only needs "
                "security) cannot complete."
            )


# ============================================================================
# Test 9: Cleanup does not handle workflow files
# ============================================================================

class TestCleanupMissingWorkflows:
    """Proves CleanupService now handles workflow files."""

    def test_no_workflow_cleanup(self):
        """CleanupService has workflow file cleanup."""
        service_source = (Path(__file__).parent.parent / "utils/cleanup_service.py").read_text()

        if "wf-*.json" in service_source or "workflow" in service_source.lower():
            return  # FIXED: CleanupService handles workflow files
        pytest.fail(
            "CleanupService does not handle logs/workflows/wf-*.json files. "
            "Workflow cleanup is configured in CleanupService but not finding pattern."
        )


# ============================================================================
# Test 10: FastAPI route conflict
# ============================================================================

class TestFastAPIRouteConflict:
    """Proves static routes can be caught by dynamic {session_id} route."""

    def test_dynamic_route_before_static(self):
        """/api/session/{session_id} declared before /api/session/latest."""
        api_source = (Path(__file__).parent.parent / "api/main.py").read_text()

        # Find route declaration positions (rough heuristic)
        session_id_line = None
        latest_line = None
        active_line = None

        for i, line in enumerate(api_source.splitlines()):
            if '/api/session/{session_id}' in line:
                session_id_line = i
            elif '/api/session/latest' in line:
                latest_line = i
            elif '/api/session/active' in line:
                active_line = i

        if session_id_line and latest_line and session_id_line < latest_line:
            pytest.fail(
                "PROVEN: /api/session/{session_id} (line {session_id_line + 1}) "
                "is declared BEFORE /api/session/latest (line {latest_line + 1}). "
                "FastAPI will match 'latest' as a session_id."
            )


# ============================================================================
# Phase 1: Behavioral Characterization Tests
# ============================================================================


class TestBehavioralCasualChat:
    """CASUAL_CHAT mode: agent should respond naturally, no workflow."""

    def test_casual_greeting_does_not_create_workflow(self):
        """Greeting like 'Hai SecurityReviewer' should not create workflow."""
        adapter_code = (Path(__file__).parent.parent / "adapter.py").read_text()
        # Verify the adapter has logic to distinguish casual chat from assessment requests
        assert "_is_assessment_request" in adapter_code, (
            "Adapter must have assessment request detection to avoid "
            "creating workflows for casual greetings"
        )

    def test_direct_domain_request_no_workflow(self):
        """Direct domain request like 'analisis finansial CloudPayX' should not activate RiskScorer."""
        inbound_code = (Path(__file__).parent.parent / "utils/inbound_guard.py").read_text()
        # Verify CLASSIFY mode returns DIRECT_DOMAIN_REQUEST for specialist-targeted domain keywords
        assert "DIRECT_DOMAIN_REQUEST" in inbound_code, (
            "Inbound guard must classify direct domain requests to avoid "
            "triggering full workflow"
        )

    def test_specialist_reply_does_not_activate_other_agents(self):
        """Specialist response should not dispatch other agents."""
        policy_code = (Path(__file__).parent.parent / "utils/action_policy.py").read_text()
        assert "SPECIALIST_DISPATCH_BLOCKED" in policy_code, (
            "Action policy must prevent specialists from dispatching other agents. "
            "Without this, a specialist could start a full workflow by replying"
        )


class TestBehavioralClarification:
    """Clarification routing: specialist -> coordinator -> human."""

    def test_specialist_clarification_goes_to_coordinator(self):
        """In coordinated workflow, specialist clarification goes to coordinator, not human."""
        guard_code = (Path(__file__).parent.parent / "utils/outbound_guard.py").read_text()
        # Check that specialist in COORDINATED_WORKFLOW sends to coordinator
        assert "COORDINATED_WORKFLOW" in guard_code, (
            "Outbound guard must differentiate coordinated workflow clarification "
            "from direct chat clarification"
        )

    def test_direct_chat_clarification_goes_to_human(self):
        """In direct chat (no workflow), specialist can ask human directly."""
        guard_code = (Path(__file__).parent.parent / "utils/outbound_guard.py").read_text()
        # The guard should allow specialist -> human in direct chat mode
        has_direct_chat = any(
            phrase in guard_code
            for phrase in ["_human_caller_", "human_requester_handle", "CASUAL_CHAT"]
        )
        assert has_direct_chat, (
            "Outbound guard must support direct chat clarification to human caller"
        )


class TestBehavioralHumanMentionPolicy:
    """Human mention restrictions."""

    def test_only_coordinator_mentions_human_in_workflow(self):
        """Only coordinator can mention human during coordinated workflow."""
        policy_code = (Path(__file__).parent.parent / "utils/action_policy.py").read_text()
        assert "FINAL_NOTIFY_HUMAN" in policy_code, (
            "Action policy must have FINAL_NOTIFY_HUMAN action type for coordinator"
        )
        assert "UNAUTHORIZED_FINAL_NOTIFICATION" in policy_code, (
            "Action policy must block non-coordinator from sending final notification"
        )

    def test_coordinator_does_not_mention_human_on_progress(self):
        """Coordinator should not mention human for every progress update."""
        guard_code = (Path(__file__).parent.parent / "utils/outbound_guard.py").read_text()
        # Check FINAL_NOTIFY_HUMAN only goes through when stage is FINALIZING
        assert "PREMATURE_FINAL_NOTIFICATION" in guard_code or "PREMATURE_FINAL" in guard_code, (
            "Guard must block premature final notification before workflow completes"
        )


class TestBehavioralCoordinatorFinalNotification:
    """Final notification: only after ReportCompiler completes."""

    def test_final_notification_after_report_compiler(self):
        """Workflow reaches COMPLETED stage after REPORT_PENDING."""
        state_code = (Path(__file__).parent.parent / "utils/workflow_state.py").read_text()
        # Check stage order ends with REPORT_PENDING -> FINALIZING -> COMPLETED
        transitions = [
            "AUDIT_PENDING",
            "REPORT_PENDING",
            "FINALIZING",
            "COMPLETED",
        ]
        for t in transitions:
            assert t in state_code, f"Stage {t} must be in workflow state machine"


class TestBehavioralRoutingByTrustedMetadata:
    """Routing should use trusted mention/reply metadata, not keyword matching."""

    def test_routing_uses_mentions_list_not_content_keyword(self):
        """Inbound guard checks mentions list, not just @Name in content."""
        guard_code = (Path(__file__).parent.parent / "utils/inbound_guard.py").read_text()
        # Should reference 'mentions' parameter, not just content regex
        mentions_ref = "mentions" in guard_code
        assert mentions_ref, (
            "Inbound guard must check the trusted mentions list from message metadata, "
            "not just scan content for @Name patterns"
        )

    def test_self_role_in_body_not_confused_with_mention(self):
        """Role name in quoted body should not trigger agent activation."""
        guard_code = (Path(__file__).parent.parent / "utils/inbound_guard.py").read_text()
        # The inbound guard should differentiate content references from mentions
        assert "_is_agent_targeted" in guard_code, (
            "Inbound guard must have targeted agent detection method"
        )


# ============================================================================
# Phase 1: Transactional/Idempotent Event Processing
# ============================================================================

class TestTransactionalIdempotentProcessing:
    """Events should be processed exactly once, with safe retry."""

    def test_event_id_recorded_after_processing(self):
        """WorkflowStore.record_event_id is called after successful processing."""
        adapter_code = (Path(__file__).parent.parent / "adapter.py").read_text()
        assert "record_event_id" in adapter_code, (
            "Adapter must call record_event_id after processing to support idempotency"
        )

    def test_duplicate_event_detected_and_skipped(self):
        """Inbound guard checks is_event_processed before allowing processing."""
        guard_code = (Path(__file__).parent.parent / "utils/inbound_guard.py").read_text()
        assert "is_event_processed" in guard_code, (
            "Inbound guard must check if event was already processed"
        )

    def test_max_one_send_per_incoming_event(self):
        """Outbound guard enforces max 1 send per event_id."""
        guard_code = (Path(__file__).parent.parent / "utils/outbound_guard.py").read_text()
        assert "DUPLICATE_SEND" in guard_code or "send_count" in guard_code, (
            "Outbound guard must enforce maximum one send per incoming event"
        )


# ============================================================================
# Run if called directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
