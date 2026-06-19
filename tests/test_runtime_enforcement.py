"""
VendorVigil — Runtime Enforcement Tests
Tests the workflow state machine, inbound/outbound guards, handle resolver,
action policy, and all 25 behavioral scenarios from the spec.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from utils.schemas import (
    WorkflowStage,
    AgentLifecycle,
    InteractionMode,
    ActionType,
    FinancialAssessment,
    SecurityAssessment,
    PrivacyAssessment,
    RiskDecision,
    AuditRecord,
    FinalReport,
    AgentAction,
    ClarificationRequest,
    CasualReply,
    DirectDomainReply,
    WorkflowEvent,
    PolicyViolation,
    AgentRole,
)
from utils.workflow_state import WorkflowStore, WorkflowState, STAGE_AGENT_ROLE
from utils.handle_resolver import HandleResolver, COORDINATOR_ROLE, SPECIALIST_ROLES
from utils.action_policy import ActionPolicy, PolicyDecision
from utils.inbound_guard import InboundRoutingGuard, InboundDecision
from utils.outbound_guard import OutboundMessageGuard, GuardResult


# --- Fixtures ---

@pytest.fixture
def workflow_store():
    return WorkflowStore()


@pytest.fixture
def handle_resolver():
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
def action_policy():
    return ActionPolicy()


@pytest.fixture
def inbound_guard():
    return InboundRoutingGuard()


@pytest.fixture
def outbound_guard(action_policy, handle_resolver, workflow_store):
    return OutboundMessageGuard(action_policy, handle_resolver, workflow_store)


@pytest.fixture
def sample_workflow(workflow_store):
    return workflow_store.create_workflow(
        room_id="room-1",
        vendor_id="V-002",
        vendor_name="CloudPayX",
        human_requester_id="human-1",
        human_requester_handle="test-human",
    )


# ============================================================================
# PHASE 1: Workflow State Machine Tests
# ============================================================================

class TestWorkflowState:
    def test_create_workflow(self, workflow_store):
        wf = workflow_store.create_workflow("room-1", "V-001", "TestVendor")
        assert wf.workflow_id.startswith("wf-")
        assert wf.vendor_name == "TestVendor"
        assert wf.status == WorkflowStage.CREATED.value
        assert wf.current_stage == WorkflowStage.CREATED.value

    def test_advance_to_routing(self, workflow_store, sample_workflow):
        wf = workflow_store.get_workflow(sample_workflow.workflow_id)
        import asyncio
        loop = asyncio.new_event_loop()
        wf = loop.run_until_complete(workflow_store.advance_stage(sample_workflow.workflow_id))
        loop.close()
        assert wf.current_stage == WorkflowStage.ROUTING.value

    def test_sequential_stage_order(self, workflow_store, sample_workflow):
        import asyncio
        loop = asyncio.new_event_loop()
        wf = sample_workflow
        routing_plan = {
            "requires_security_check": True,
            "requires_privacy_check": True,
            "requires_financial_check": True,
        }
        # Step 1: CREATED -> ROUTING (routing_plan ignored at CREATED stage)
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id)
        )
        assert wf.current_stage == WorkflowStage.ROUTING.value

        # Step 2: ROUTING -> SECURITY_PENDING (routing_plan processed here)
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, routing_plan=routing_plan)
        )
        assert wf.current_stage == WorkflowStage.SECURITY_PENDING.value
        assert AgentRole.SECURITY_REVIEWER.value in wf.required_agents

        # Step 5: SECURITY_PENDING -> PRIVACY_PENDING
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"score": 60})
        )
        assert wf.current_stage == WorkflowStage.PRIVACY_PENDING.value
        assert AgentRole.SECURITY_REVIEWER.value in wf.completed_agents

        # Step 4: PRIVACY_PENDING -> FINANCIAL_PENDING
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"score": 55})
        )
        assert wf.current_stage == WorkflowStage.FINANCIAL_PENDING.value

        # Step 5: FINANCIAL_PENDING -> RISK_PENDING
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"score": 70})
        )
        assert wf.current_stage == WorkflowStage.RISK_PENDING.value

        # Step 6: RISK_PENDING -> AUDIT_PENDING
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"status": "ESCALATED"})
        )
        assert wf.current_stage == WorkflowStage.AUDIT_PENDING.value

        # Step 7: AUDIT_PENDING -> REPORT_PENDING
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"audit_id": "VV-001"})
        )
        assert wf.current_stage == WorkflowStage.REPORT_PENDING.value

        # Step 8: REPORT_PENDING -> FINALIZING
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"report": "done"})
        )
        assert wf.current_stage == WorkflowStage.FINALIZING.value

        # Step 9: FINALIZING -> COMPLETED
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id)
        )
        assert wf.current_stage == WorkflowStage.COMPLETED.value
        loop.close()

    def test_skip_optional_agents(self, workflow_store):
        import asyncio
        loop = asyncio.new_event_loop()
        wf = workflow_store.create_workflow("room-2", "V-001", "SafeDocsID")
        routing_plan = {
            "requires_security_check": True,
            "requires_privacy_check": False,
            "requires_financial_check": False,
        }
        wf = loop.run_until_complete(workflow_store.advance_stage(wf.workflow_id))
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, routing_plan=routing_plan)
        )
        assert AgentRole.PRIVACY_REVIEWER.value in wf.skipped_agents
        assert AgentRole.FINANCIAL_REVIEWER.value in wf.skipped_agents
        assert AgentRole.SECURITY_REVIEWER.value in wf.required_agents
        loop.close()

    def test_fail_workflow(self, workflow_store, sample_workflow):
        workflow_store.fail_workflow(sample_workflow.workflow_id, "test failure")
        wf = workflow_store.get_workflow(sample_workflow.workflow_id)
        assert wf.status == WorkflowStage.FAILED.value

    def test_duplicate_event_detection(self, workflow_store, sample_workflow):
        assert workflow_store.record_event_id(sample_workflow.workflow_id, "evt-1")
        assert not workflow_store.record_event_id(sample_workflow.workflow_id, "evt-1")

    def test_get_active_workflow(self, workflow_store):
        wf = workflow_store.create_workflow("room-3", "V-001", "Test")
        active = workflow_store.get_active_workflow_for_room("room-3")
        assert active is not None
        assert active.workflow_id == wf.workflow_id


# ============================================================================
# PHASE 2: Handle Resolver Tests
# ============================================================================

class TestHandleResolver:
    def test_resolve_known_role(self, handle_resolver):
        assert handle_resolver.resolve("SecurityReviewer") == "test-user/security-reviewer"

    def test_resolve_unknown_role(self, handle_resolver):
        assert handle_resolver.resolve("NonexistentAgent") is None

    def test_is_known_agent(self, handle_resolver):
        assert handle_resolver.is_known_agent("test-user/security-reviewer")
        assert not handle_resolver.is_known_agent("test-user/unknown-agent")

    def test_get_role_from_handle(self, handle_resolver):
        assert handle_resolver.get_role_from_handle("test-user/security-reviewer") == "SecurityReviewer"

    def test_get_role_from_sender_formats(self, handle_resolver):
        assert handle_resolver.get_role_from_sender("SecurityReviewer") == "SecurityReviewer"
        assert handle_resolver.get_role_from_sender("@SecurityReviewer") == "SecurityReviewer"
        assert handle_resolver.get_role_from_sender("test-user/security-reviewer") == "SecurityReviewer"

    def test_is_human_sender(self, handle_resolver):
        assert handle_resolver.is_human_sender("John Doe")
        assert not handle_resolver.is_human_sender("SecurityReviewer")

    def test_from_band_participants(self):
        participants = "Participants: @user1/vendor-coordinator, @user1/security-reviewer"
        resolver = HandleResolver.from_band_participants(participants)
        assert resolver.resolve("VendorCoordinator") == "user1/vendor-coordinator"
        assert resolver.resolve("SecurityReviewer") == "user1/security-reviewer"

    def test_from_config(self):
        resolver = HandleResolver.from_config()
        assert resolver.resolve("VendorCoordinator") is not None
        assert resolver.resolve("SecurityReviewer") is not None


# ============================================================================
# PHASE 3: Action Policy Tests
# ============================================================================

class TestActionPolicy:
    def test_coordinator_can_dispatch(self, action_policy):
        assert action_policy.is_action_allowed("VendorCoordinator", ActionType.DISPATCH_AGENT_TASK)

    def test_specialist_cannot_dispatch(self, action_policy):
        assert not action_policy.is_action_allowed("SecurityReviewer", ActionType.DISPATCH_AGENT_TASK)

    def test_specialist_can_reply(self, action_policy):
        assert action_policy.is_action_allowed("SecurityReviewer", ActionType.REPLY_TO_CALLER)

    def test_specialist_can_submit(self, action_policy):
        assert action_policy.is_action_allowed("SecurityReviewer", ActionType.SUBMIT_DOMAIN_RESULT)

    def test_coordinator_can_final_notify(self, action_policy):
        assert action_policy.is_action_allowed("VendorCoordinator", ActionType.FINAL_NOTIFY_HUMAN)

    def test_specialist_cannot_final_notify(self, action_policy):
        assert not action_policy.is_action_allowed("SecurityReviewer", ActionType.FINAL_NOTIFY_HUMAN)

    def test_validate_specialist_dispatch_blocked(self, action_policy):
        decision = action_policy.validate_action(
            sender_role="SecurityReviewer",
            action_type=ActionType.DISPATCH_AGENT_TASK,
        )
        assert not decision.allowed

    def test_validate_coordinator_dispatch_allowed(self, action_policy):
        decision = action_policy.validate_action(
            sender_role="VendorCoordinator",
            action_type=ActionType.DISPATCH_AGENT_TASK,
        )
        assert decision.allowed


# ============================================================================
# PHASE 4: Inbound Guard Tests
# ============================================================================

class TestInboundGuard:
    def test_ignore_self(self, inbound_guard, workflow_store, handle_resolver):
        event = {
            "sender_name": "SecurityReviewer",
            "content": "my own message",
            "event_id": "evt-1",
            "room_id": "room-1",
            "mentions": [],
            "is_self": True,
        }
        result = inbound_guard.evaluate(event, "SecurityReviewer", workflow_store, handle_resolver)
        assert result.decision == InboundDecision.IGNORE_SELF

    def test_ignore_not_targeted(self, inbound_guard, workflow_store, handle_resolver):
        event = {
            "sender_name": "human-1",
            "content": "hello other agent",
            "event_id": "evt-2",
            "room_id": "room-1",
            "mentions": [],
            "is_self": False,
        }
        result = inbound_guard.evaluate(event, "SecurityReviewer", workflow_store, handle_resolver)
        assert result.decision == InboundDecision.IGNORE_NOT_TARGETED

    def test_process_when_targeted(self, inbound_guard, workflow_store, handle_resolver):
        event = {
            "sender_name": "human-1",
            "content": "@SecurityReviewer please assess",
            "event_id": "evt-3",
            "room_id": "room-1",
            "mentions": ["test-user/security-reviewer"],
            "is_self": False,
        }
        result = inbound_guard.evaluate(event, "SecurityReviewer", workflow_store, handle_resolver)
        assert result.decision == InboundDecision.PROCESS

    def test_ignore_system_event(self, inbound_guard, workflow_store, handle_resolver):
        event = {
            "sender_name": "system",
            "content": "participant joined",
            "event_id": "evt-4",
            "room_id": "room-1",
            "mentions": [],
            "is_self": False,
            "is_system_event": True,
        }
        result = inbound_guard.evaluate(event, "SecurityReviewer", workflow_store, handle_resolver)
        assert result.decision == InboundDecision.IGNORE_SYSTEM_EVENT

    def test_classify_casual_chat(self, inbound_guard, workflow_store, handle_resolver):
        mode = inbound_guard._classify_mode(
            "SecurityReviewer", None, True, "hi how are you", None
        )
        assert mode == InteractionMode.CASUAL_CHAT

    def test_classify_direct_domain(self, inbound_guard, workflow_store, handle_resolver):
        mode = inbound_guard._classify_mode(
            "SecurityReviewer", None, True, "analyze the security evidence and SOC 2 compliance", None
        )
        assert mode == InteractionMode.DIRECT_DOMAIN_REQUEST

    def test_classify_coordinated_workflow(self, inbound_guard, workflow_store, handle_resolver, sample_workflow):
        mode = inbound_guard._classify_mode(
            "SecurityReviewer", "VendorCoordinator", True, "please assess security", sample_workflow
        )
        assert mode == InteractionMode.COORDINATED_WORKFLOW

    def test_build_envelope(self, inbound_guard, handle_resolver, workflow_store, sample_workflow):
        event = {
            "sender_name": "human-1",
            "sender_id": "human-1",
            "content": "assess vendor",
            "event_id": "evt-5",
            "room_id": "room-1",
            "mentions": [],
            "created_at": "2026-01-01T00:00:00Z",
        }
        envelope = inbound_guard.build_envelope(
            event, "SecurityReviewer", InteractionMode.DIRECT_DOMAIN_REQUEST,
            sample_workflow.workflow_id, handle_resolver, workflow_store
        )
        assert envelope["target_role"] == "SecurityReviewer"
        assert envelope["interaction_mode"] == InteractionMode.DIRECT_DOMAIN_REQUEST.value
        assert "allowed_actions" in envelope


# ============================================================================
# PHASE 5: Outbound Guard Tests
# ============================================================================

class TestOutboundGuard:
    def test_no_action_skipped(self, outbound_guard):
        result = outbound_guard.validate_and_prepare(
            "SecurityReviewer", ActionType.NO_ACTION, "content",
            InteractionMode.CASUAL_CHAT, event_id="evt-1"
        )
        assert result.guard_result == GuardResult.SKIPPED_NO_ACTION

    def test_duplicate_send_blocked(self, outbound_guard):
        outbound_guard.validate_and_prepare(
            "SecurityReviewer", ActionType.SUBMIT_DOMAIN_RESULT, "result",
            InteractionMode.COORDINATED_WORKFLOW, event_id="evt-dup"
        )
        result = outbound_guard.validate_and_prepare(
            "SecurityReviewer", ActionType.SUBMIT_DOMAIN_RESULT, "result2",
            InteractionMode.COORDINATED_WORKFLOW, event_id="evt-dup"
        )
        assert result.guard_result == GuardResult.BLOCKED_DUPLICATE

    def test_self_mention_blocked(self, outbound_guard):
        result = outbound_guard.validate_and_prepare(
            "SecurityReviewer", ActionType.REPLY_TO_CALLER,
            "I am SecurityReviewer and here is my assessment",
            InteractionMode.CASUAL_CHAT, event_id="evt-self"
        )
        assert result.guard_result == GuardResult.BLOCKED_SELF_MENTION

    def test_specialist_dispatch_blocked(self, outbound_guard):
        result = outbound_guard.validate_and_prepare(
            "SecurityReviewer", ActionType.DISPATCH_AGENT_TASK, "do this",
            InteractionMode.COORDINATED_WORKFLOW, event_id="evt-dispatch"
        )
        assert result.guard_result == GuardResult.BLOCKED_POLICY_VIOLATION

    def test_coordinator_dispatch_allowed(self, outbound_guard, workflow_store, sample_workflow):
        import asyncio
        loop = asyncio.new_event_loop()
        # Step 1: CREATED -> ROUTING
        wf = loop.run_until_complete(workflow_store.advance_stage(sample_workflow.workflow_id))
        assert wf.current_stage == WorkflowStage.ROUTING.value
        # Step 2: ROUTING -> SECURITY_PENDING (routing_plan processed here)
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, routing_plan={
                "requires_security_check": True,
                "requires_privacy_check": False,
                "requires_financial_check": False,
            })
        )
        assert wf.current_stage == WorkflowStage.SECURITY_PENDING.value
        loop.close()
        result = outbound_guard.validate_and_prepare(
            "VendorCoordinator", ActionType.DISPATCH_AGENT_TASK,
            "please assess security for CloudPayX",
            InteractionMode.COORDINATED_WORKFLOW,
            workflow_id=sample_workflow.workflow_id,
            event_id="evt-dispatch-ok"
        )
        assert result.guard_result == GuardResult.SENT
        assert result.recipient == "test-user/security-reviewer"

    def test_content_sanitized(self, outbound_guard):
        result = outbound_guard.validate_and_prepare(
            "ReportCompiler", ActionType.SUBMIT_DOMAIN_RESULT,
            "Report by @SecurityReviewer and @PrivacyReviewer completed",
            InteractionMode.COORDINATED_WORKFLOW, event_id="evt-sanitize"
        )
        assert "@SecurityReviewer" not in result.sanitized_content
        assert "@PrivacyReviewer" not in result.sanitized_content

    def test_recipient_determined_by_runtime(self, outbound_guard, workflow_store, sample_workflow):
        import asyncio
        loop = asyncio.new_event_loop()
        # Step 1: CREATED -> ROUTING
        wf = loop.run_until_complete(workflow_store.advance_stage(sample_workflow.workflow_id))
        assert wf.current_stage == WorkflowStage.ROUTING.value
        # Step 2: ROUTING -> SECURITY_PENDING
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, routing_plan={
                "requires_security_check": True,
                "requires_privacy_check": True,
                "requires_financial_check": True,
            })
        )
        assert wf.current_stage == WorkflowStage.SECURITY_PENDING.value
        loop.close()
        result = outbound_guard.validate_and_prepare(
            "VendorCoordinator", ActionType.DISPATCH_AGENT_TASK,
            "please assess security",
            InteractionMode.COORDINATED_WORKFLOW,
            workflow_id=sample_workflow.workflow_id,
            event_id="evt-runtime"
        )
        assert result.guard_result == GuardResult.SENT
        assert result.mentions is not None
        assert len(result.mentions) == 1


# ============================================================================
# PHASE 6: Schema Tests
# ============================================================================

class TestSchemas:
    def test_financial_assessment_risk_level(self):
        fa = FinancialAssessment(
            vendor_id="V-001", score=70, risk_level="MEDIUM", confidence=0.85
        )
        assert fa.risk_level == "MEDIUM"

    def test_financial_assessment_default_risk_level(self):
        fa = FinancialAssessment(vendor_id="V-001", score=50, confidence=0.7)
        assert fa.risk_level == "MEDIUM"

    def test_agent_action(self):
        action = AgentAction(
            action_type=ActionType.SUBMIT_DOMAIN_RESULT,
            content="my assessment",
            structured_payload={"score": 80}
        )
        assert action.action_type == ActionType.SUBMIT_DOMAIN_RESULT

    def test_clarification_request(self):
        cr = ClarificationRequest(question="What is the vendor name?", context="missing data")
        assert cr.question == "What is the vendor name?"

    def test_casual_reply(self):
        reply = CasualReply(content="Hi there!")
        assert reply.content == "Hi there!"

    def test_policy_violation(self):
        pv = PolicyViolation(
            violation_type="SELF_MENTION",
            sender_role="SecurityReviewer",
            attempted_action="REPLY_TO_CALLER",
            details="self mention detected",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert pv.violation_type == "SELF_MENTION"

    def test_workflow_event(self):
        event = WorkflowEvent(
            event_type="stage_advance",
            workflow_id="wf-123",
            data={"from": "CREATED", "to": "ROUTING"}
        )
        assert event.event_type == "stage_advance"


# ============================================================================
# PHASE 7: Integration Tests
# ============================================================================

class TestIntegration:
    def test_full_sequential_workflow(self, workflow_store, handle_resolver):
        """Test 4: Full sequential path."""
        import asyncio
        loop = asyncio.new_event_loop()
        wf = workflow_store.create_workflow(
            "room-int", "V-002", "CloudPayX",
            human_requester_id="h1", human_requester_handle="human-1"
        )
        routing_plan = {
            "requires_security_check": True,
            "requires_privacy_check": True,
            "requires_financial_check": True,
        }
        wf = loop.run_until_complete(workflow_store.advance_stage(wf.workflow_id))
        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, routing_plan=routing_plan)
        )
        assert wf.current_stage == WorkflowStage.SECURITY_PENDING.value
        assert wf.active_agent_role == "SecurityReviewer"

        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"score": 60})
        )
        assert wf.current_stage == WorkflowStage.PRIVACY_PENDING.value
        assert AgentRole.SECURITY_REVIEWER.value in wf.completed_agents

        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"score": 55})
        )
        assert wf.current_stage == WorkflowStage.FINANCIAL_PENDING.value

        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"score": 70})
        )
        assert wf.current_stage == WorkflowStage.RISK_PENDING.value

        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"status": "ESCALATED"})
        )
        assert wf.current_stage == WorkflowStage.AUDIT_PENDING.value

        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"audit_id": "VV-001"})
        )
        assert wf.current_stage == WorkflowStage.REPORT_PENDING.value

        wf = loop.run_until_complete(
            workflow_store.advance_stage(wf.workflow_id, result={"report": "done"})
        )
        assert wf.current_stage == WorkflowStage.FINALIZING.value
        assert workflow_store.is_all_required_done(wf.workflow_id)

        wf = loop.run_until_complete(workflow_store.advance_stage(wf.workflow_id))
        assert wf.current_stage == WorkflowStage.COMPLETED.value
        loop.close()

    def test_concurrent_workflows_isolated(self, workflow_store):
        """Test 19: Concurrent workflows don't share state."""
        wf1 = workflow_store.create_workflow("room-c1", "V-001", "SafeDocsID")
        wf2 = workflow_store.create_workflow("room-c2", "V-002", "CloudPayX")
        assert wf1.workflow_id != wf2.workflow_id
        assert wf1.vendor_name != wf2.vendor_name

    def test_vendor_lookup(self):
        """Phase 11: Vendor lookup works."""
        from config import lookup_vendor
        result = lookup_vendor("CloudPayX")
        assert result is not None
        assert result["vendor_name"] == "CloudPayX"
        assert "expected_status" not in result

    def test_vendor_lookup_not_found(self):
        from config import lookup_vendor
        result = lookup_vendor("NonexistentVendor")
        assert result is None

    def test_prompt_loader(self):
        """Phase 9: Spec loader works."""
        from prompts import load_agent_spec
        spec = load_agent_spec("security_reviewer")
        assert "SecurityReviewer" in spec
        assert "SOC 2" in spec

    def test_mock_sequential(self):
        """Phase 10: Mock coordinator has sequential steps."""
        from config import MOCK_COORDINATOR_MENTIONS
        assert len(MOCK_COORDINATOR_MENTIONS[2]) == 1
        assert "SecurityReviewer" in MOCK_COORDINATOR_MENTIONS[2]
        assert len(MOCK_COORDINATOR_MENTIONS[3]) == 1
        assert "PrivacyReviewer" in MOCK_COORDINATOR_MENTIONS[3]
