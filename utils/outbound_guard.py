"""
VendorVigil — Outbound Message Guard
Validates all outbound messages before sending to Band.
Determines recipient at runtime — LLM never chooses who to mention.

Usage:
    from utils.outbound_guard import OutboundMessageGuard, GuardResult
    guard = OutboundMessageGuard(action_policy, handle_resolver)
    result = guard.validate_and_send(...)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from utils.schemas import (
    ActionType,
    InteractionMode,
    WorkflowStage,
    AgentLifecycle,
    PolicyViolation,
    AgentRole,
)
from utils.action_policy import ActionPolicy, PolicyDecision
from utils.handle_resolver import HandleResolver, COORDINATOR_ROLE, SPECIALIST_ROLES, ALL_ROLES, ROLE_TO_SLUG
from utils.workflow_state import WorkflowStore, STAGE_AGENT_ROLE

# Maps short stage role names to full logical role names for HandleResolver
_STAGE_ROLE_TO_LOGICAL: dict[str, str] = {
    AgentRole.SECURITY_REVIEWER.short_key: AgentRole.SECURITY_REVIEWER.value,
    AgentRole.PRIVACY_REVIEWER.short_key: AgentRole.PRIVACY_REVIEWER.value,
    AgentRole.FINANCIAL_REVIEWER.short_key: AgentRole.FINANCIAL_REVIEWER.value,
    AgentRole.RISK_SCORER.short_key: AgentRole.RISK_SCORER.value,
    AgentRole.AUDIT_LOGGER.short_key: AgentRole.AUDIT_LOGGER.value,
    AgentRole.REPORT_COMPILER.short_key: AgentRole.REPORT_COMPILER.value,
}

logger = logging.getLogger("vendorvigil.outbound_guard")


class GuardResult(str, Enum):
    """Result of outbound message validation."""
    SENT = "SENT"
    BLOCKED_SELF_MENTION = "BLOCKED_SELF_MENTION"
    BLOCKED_MULTI_MENTION = "BLOCKED_MULTI_MENTION"
    BLOCKED_UNAUTHORIZED_DISPATCH = "BLOCKED_UNAUTHORIZED_DISPATCH"
    BLOCKED_PREMATURE_FINAL = "BLOCKED_PREMATURE_FINAL"
    BLOCKED_DUPLICATE = "BLOCKED_DUPLICATE"
    BLOCKED_COMPLETED_AGENT = "BLOCKED_COMPLETED_AGENT"
    BLOCKED_POLICY_VIOLATION = "BLOCKED_POLICY_VIOLATION"
    BLOCKED_MALFORMED = "BLOCKED_MALFORMED"
    SKIPPED_NO_ACTION = "SKIPPED_NO_ACTION"


@dataclass
class OutboundResult:
    """Full result of an outbound message validation attempt."""
    guard_result: GuardResult
    recipient: str | None = None
    sanitized_content: str = ""
    mentions: list[str] | None = None
    policy_violation: PolicyViolation | None = None
    reason: str = ""


class OutboundMessageGuard:
    """Validates and sends outbound messages with runtime recipient determination."""

    def __init__(
        self,
        action_policy: ActionPolicy,
        handle_resolver: HandleResolver,
        workflow_store: WorkflowStore,
        violation_log: list[PolicyViolation] | None = None,
    ) -> None:
        self._policy = action_policy
        self._resolver = handle_resolver
        self._store = workflow_store
        self._violation_log = violation_log if violation_log is not None else []
        self._send_count_by_event: dict[str, int] = {}

    def validate_and_prepare(
        self,
        sender_role: str,
        action_type: ActionType,
        content: str,
        interaction_mode: InteractionMode,
        workflow_id: str | None = None,
        event_id: str | None = None,
        llm_mentions: list[str] | None = None,
        caller_id: str | None = None,
        caller_handle: str | None = None,
    ) -> OutboundResult:
        """Validate an outbound message and determine recipient.

        The LLM's `mentions` argument is IGNORED. Recipient is always
        determined by runtime policy.

        Args:
            sender_role: The sending agent's logical role.
            action_type: The type of action being taken.
            content: The message content.
            interaction_mode: Current interaction mode.
            workflow_id: Active workflow ID if applicable.
            event_id: The incoming event ID this is a response to.
            llm_mentions: The mentions the LLM tried to use (IGNORED).

        Returns:
            OutboundResult with validated content, recipient, and mentions.
        """
        # Get workflow state if available
        workflow = None
        if workflow_id:
            workflow = self._store.get_workflow(workflow_id)

        # Rule 1: Check for NO_ACTION
        if action_type == ActionType.NO_ACTION:
            return OutboundResult(
                guard_result=GuardResult.SKIPPED_NO_ACTION,
                reason="Agent chose NO_ACTION",
            )

        # Rule 2: Check for duplicate send (max 1 per incoming event)
        if event_id:
            count = self._send_count_by_event.get(event_id, 0)
            if count >= 1:
                violation = PolicyViolation(
                    violation_type="DUPLICATE_SEND",
                    sender_role=sender_role,
                    attempted_action=action_type.value,
                    details=f"Attempted send #{count + 1} for event {event_id}",
                    timestamp="",
                )
                self._record_violation(violation)
                return OutboundResult(
                    guard_result=GuardResult.BLOCKED_DUPLICATE,
                    policy_violation=violation,
                    reason="Maximum 1 outbound action per incoming event",
                )

        # Rule 3: Policy validation
        is_terminal = False
        if workflow:
            is_terminal = workflow.status in {
                WorkflowStage.COMPLETED.value,
                WorkflowStage.FAILED.value,
                WorkflowStage.CANCELLED.value,
            }

        policy_decision = self._policy.validate_action(
            sender_role=sender_role,
            action_type=action_type,
            interaction_mode=interaction_mode,
            workflow_stage=workflow.current_stage if workflow else None,
            is_workflow_terminal=is_terminal,
        )
        if not policy_decision.allowed:
            self._record_violation(policy_decision.violation)
            return OutboundResult(
                guard_result=GuardResult.BLOCKED_POLICY_VIOLATION,
                policy_violation=policy_decision.violation,
                reason=policy_decision.reason,
            )

        # Rule 4: Check self-mention
        sanitized = self._sanitize_content(content, sender_role)
        if self._contains_self_mention(sanitized, sender_role):
            violation = PolicyViolation(
                violation_type="SELF_MENTION",
                sender_role=sender_role,
                attempted_action=action_type.value,
                details=f"Content contains self-mention for {sender_role}",
                timestamp="",
            )
            self._record_violation(violation)
            return OutboundResult(
                guard_result=GuardResult.BLOCKED_SELF_MENTION,
                sanitized_content=sanitized,
                policy_violation=violation,
                reason="Message contains self-mention",
            )

        # Rule 5: Determine recipient at runtime
        recipient = self._determine_recipient(
            sender_role, action_type, workflow, interaction_mode
        )

        if recipient is None:
            return OutboundResult(
                guard_result=GuardResult.BLOCKED_MALFORMED,
                sanitized_content=sanitized,
                reason="Could not determine recipient",
            )

        # Resolve __direct_human_reply__ placeholder to actual handle
        if recipient == "__direct_human_reply__":
            if caller_handle:
                recipient = self._resolver.resolve_human(caller_handle)
                logger.info("Resolved direct human reply -> %s", recipient)
            else:
                logger.warning("__direct_human_reply__ but no caller_handle provided")

        # Rule 6: Check if recipient agent is already completed
        if workflow and recipient != workflow.human_requester_handle:
            target_role = self._resolver.get_role_from_handle(recipient)
            if target_role and target_role in workflow.completed_agents:
                violation = PolicyViolation(
                    violation_type="COMPLETED_AGENT_REACTIVATION",
                    sender_role=sender_role,
                    attempted_action=action_type.value,
                    details=f"Attempted to send to completed agent {target_role}",
                    timestamp="",
                )
                self._record_violation(violation)
                return OutboundResult(
                    guard_result=GuardResult.BLOCKED_COMPLETED_AGENT,
                    sanitized_content=sanitized,
                    policy_violation=violation,
                    reason=f"Agent {target_role} is already completed",
                )

        # Rule 7: Check for multi-mention in dispatch
        if action_type == ActionType.DISPATCH_AGENT_TASK:
            target_role = self._resolver.get_role_from_handle(recipient)
            if target_role and workflow:
                expected_short = STAGE_AGENT_ROLE.get(WorkflowStage(workflow.current_stage))
                expected_logical = _STAGE_ROLE_TO_LOGICAL.get(expected_short, "") if expected_short else ""
                if expected_logical and target_role != expected_logical:
                    violation = PolicyViolation(
                        violation_type="WRONG_STAGE_DISPATCH",
                        sender_role=sender_role,
                        attempted_action=action_type.value,
                        details=(
                            f"Dispatched {target_role} but stage "
                            f"{workflow.current_stage} expects {expected_logical}"
                        ),
                        timestamp="",
                    )
                    self._record_violation(violation)
                    return OutboundResult(
                        guard_result=GuardResult.BLOCKED_POLICY_VIOLATION,
                        sanitized_content=sanitized,
                        policy_violation=violation,
                        reason=f"Wrong stage dispatch: expected {expected_logical}, got {target_role}",
                    )

        # Build mentions list for Band SDK (requires @ prefix per SDK examples)
        mentions = [f"@{recipient}"] if recipient else []

        # Record the send
        if event_id:
            self._send_count_by_event[event_id] = (
                self._send_count_by_event.get(event_id, 0) + 1
            )

        return OutboundResult(
            guard_result=GuardResult.SENT,
            recipient=recipient,
            sanitized_content=sanitized,
            mentions=mentions,
            reason="Message validated and ready to send",
        )

    def _determine_recipient(
        self,
        sender_role: str,
        action_type: ActionType,
        workflow,
        interaction_mode: InteractionMode,
    ) -> str | None:
        """Determine the recipient at runtime based on policy.

        The LLM NEVER chooses the recipient. This method uses workflow
        state and action type to determine who should receive the message.
        """
        # Coordinator dispatching a task -> next specialist in workflow
        if (sender_role == COORDINATOR_ROLE
                and action_type == ActionType.DISPATCH_AGENT_TASK
                and workflow):
            stage = workflow.current_stage
            target_role = STAGE_AGENT_ROLE.get(WorkflowStage(stage))
            if target_role:
                # Convert short role name to logical role name for HandleResolver
                logical_role = _STAGE_ROLE_TO_LOGICAL.get(target_role, target_role)
                return self._resolver.resolve(logical_role)

        # Coordinator sending final notification -> human requester
        if (sender_role == COORDINATOR_ROLE
                and action_type == ActionType.FINAL_NOTIFY_HUMAN
                and workflow):
            return self._resolver.resolve_human(workflow.human_requester_handle)

        # Coordinator replying to caller (casual or clarification) -> human
        if (sender_role == COORDINATOR_ROLE
                and action_type in (ActionType.REPLY_TO_CALLER,
                                     ActionType.REQUEST_CLARIFICATION)
                and workflow):
            return self._resolver.resolve_human(workflow.human_requester_handle)

        # Coordinator casual chat (no workflow) -> human who messaged
        if (sender_role == COORDINATOR_ROLE
                and action_type == ActionType.REPLY_TO_CALLER
                and not workflow):
            # Without workflow, we don't know the human handle.
            # Return a generic placeholder; adapter must fill from event.
            return "__direct_human_reply__"

        # Specialist submitting domain result -> coordinator
        if (sender_role in SPECIALIST_ROLES
                and action_type == ActionType.SUBMIT_DOMAIN_RESULT):
            return self._resolver.resolve(COORDINATOR_ROLE)

        # Specialist replying to caller (direct chat) -> human
        if (sender_role in SPECIALIST_ROLES
                and action_type in (ActionType.REPLY_TO_CALLER,
                                     ActionType.REQUEST_CLARIFICATION)):
            if workflow:
                # In workflow context, specialist talks to coordinator
                if interaction_mode == InteractionMode.COORDINATED_WORKFLOW:
                    return self._resolver.resolve(COORDINATOR_ROLE)
                # Direct chat -> human
                return self._resolver.resolve_human(
                    workflow.human_requester_handle
                )
            # No workflow -> direct chat with human
            return "__direct_human_reply__"

        # Default: coordinator (safe fallback)
        return self._resolver.resolve(COORDINATOR_ROLE)

    def _sanitize_content(self, content: str, sender_role: str) -> str:
        """Strip ALL @mention patterns from content to prevent accidental activation.

        The runtime determines recipients — content must never contain @ tags.
        Preserves email addresses (user@domain.com has no space before @).
        """
        result = content

        # Remove @RoleName patterns (e.g., @SecurityReviewer)
        for role in ALL_ROLES:
            pattern = re.compile(rf"@{re.escape(role)}", re.IGNORECASE)
            result = pattern.sub(role, result)

        # Remove @username/slug patterns for known agents
        for role, slug in ROLE_TO_SLUG.items():
            pattern = re.compile(rf"@[\w.-]*/{re.escape(slug)}", re.IGNORECASE)
            result = pattern.sub(role, result)

        # Remove ANY @word pattern that isn't an email (no dot after @)
        # Catches: @username, @display_name, @any-handle
        result = re.sub(r'@(\w[\w.-]*)', r'\1', result)

        return result

    def _contains_self_mention(self, content: str, sender_role: str) -> bool:
        """Check if content contains explicit @mention of own role.

        Blocks only: @RoleName, @username/slug.
        Allows: plain role name in normal text (e.g. 'SecurityReviewer completed').
        """
        # Block explicit @RoleName
        at_pattern = re.compile(rf"@{re.escape(sender_role)}\b", re.IGNORECASE)
        if at_pattern.search(content):
            return True

        # Block @username/slug
        slug = ROLE_TO_SLUG.get(sender_role, "")
        if slug:
            slug_pattern = re.compile(rf"@[\w.-]*/{re.escape(slug)}\b", re.IGNORECASE)
            if slug_pattern.search(content):
                return True

        return False

    def _record_violation(self, violation: PolicyViolation | None) -> None:
        """Record a policy violation."""
        if violation:
            self._violation_log.append(violation)
            self._policy.record_violation(violation)

    def get_violation_log(self) -> list[PolicyViolation]:
        """Return all recorded violations."""
        return list(self._violation_log)

    def reset_send_count(self, event_id: str) -> None:
        """Reset the send count for a given event ID."""
        self._send_count_by_event.pop(event_id, None)
