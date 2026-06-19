"""
VendorVigil — Action Policy
Defines what actions each agent role is allowed to take.
Runtime enforcement layer that prevents unauthorized dispatch, delegation,
and mention patterns.

Usage:
    from utils.action_policy import ActionPolicy, ActionType, InteractionMode
    policy = ActionPolicy()
    decision = policy.validate_action("security", ActionType.DISPATCH_AGENT_TASK, ...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from utils.schemas import (
    ActionType,
    InteractionMode,
    WorkflowStage,
    PolicyViolation,
    AgentRole,
)
from utils.handle_resolver import COORDINATOR_ROLE, SPECIALIST_ROLES

logger = logging.getLogger("vendorvigil.action_policy")

# Role permission matrix
COORDINATOR_ACTIONS: set[ActionType] = {
    ActionType.REPLY_TO_CALLER,
    ActionType.REQUEST_CLARIFICATION,
    ActionType.DISPATCH_AGENT_TASK,
    ActionType.FINAL_NOTIFY_HUMAN,
    ActionType.NO_ACTION,
}

SPECIALIST_ACTIONS: set[ActionType] = {
    ActionType.REPLY_TO_CALLER,
    ActionType.SUBMIT_DOMAIN_RESULT,
    ActionType.REQUEST_CLARIFICATION,
    ActionType.NO_ACTION,
}

# Terminal workflow stages where no new dispatch is allowed
TERMINAL_STAGES: set[str] = {
    WorkflowStage.COMPLETED.value,
    WorkflowStage.FAILED.value,
    WorkflowStage.CANCELLED.value,
}


@dataclass
class PolicyDecision:
    """Result of a policy validation check."""
    allowed: bool
    reason: str = ""
    violation: PolicyViolation | None = None

    @classmethod
    def allow(cls, reason: str = "") -> PolicyDecision:
        return cls(allowed=True, reason=reason)

    @classmethod
    def deny(cls, violation_type: str, sender_role: str, attempted_action: str,
             details: str) -> PolicyDecision:
        now = datetime.now(timezone.utc).isoformat()
        violation = PolicyViolation(
            violation_type=violation_type,
            sender_role=sender_role,
            attempted_action=attempted_action,
            details=details,
            timestamp=now,
        )
        logger.warning("POLICY VIOLATION: %s by %s — %s",
                        violation_type, sender_role, details)
        return cls(allowed=False, reason=details, violation=violation)


class ActionPolicy:
    """Validates whether an agent action is permitted under current policy."""

    def __init__(self, violation_log: list[PolicyViolation] | None = None) -> None:
        self._violation_log = violation_log if violation_log is not None else []

    def get_allowed_actions(self, role: str) -> set[ActionType]:
        """Return allowed action types for a given role."""
        if role == COORDINATOR_ROLE:
            return COORDINATOR_ACTIONS
        if role in SPECIALIST_ROLES:
            return SPECIALIST_ACTIONS
        return set()

    def is_action_allowed(self, role: str, action_type: ActionType) -> bool:
        """Quick check if an action type is permitted for a role."""
        allowed = self.get_allowed_actions(role)
        return action_type in allowed

    def validate_action(
        self,
        sender_role: str,
        action_type: ActionType,
        interaction_mode: InteractionMode | None = None,
        workflow_stage: str | None = None,
        target_role: str | None = None,
        is_workflow_terminal: bool = False,
    ) -> PolicyDecision:
        """Full validation of an action against all policy rules.

        Args:
            sender_role: The logical role of the sending agent.
            action_type: The type of action being attempted.
            interaction_mode: Current interaction mode.
            workflow_stage: Current workflow stage (if in coordinated workflow).
            target_role: The target agent role (for dispatch actions).
            is_workflow_terminal: Whether the workflow is in a terminal state.

        Returns:
            PolicyDecision indicating allowed/denied with reason.
        """
        # Rule 1: Check basic role permission
        if not self.is_action_allowed(sender_role, action_type):
            return PolicyDecision.deny(
                "UNAUTHORIZED_ACTION",
                sender_role,
                action_type.value,
                f"Role {sender_role} is not permitted to perform {action_type.value}",
            )

        # Rule 2: Specialists cannot dispatch
        if (sender_role in SPECIALIST_ROLES
                and action_type == ActionType.DISPATCH_AGENT_TASK):
            return PolicyDecision.deny(
                "SPECIALIST_DISPATCH_BLOCKED",
                sender_role,
                action_type.value,
                f"Specialist {sender_role} cannot dispatch tasks to other agents",
            )

        # Rule 3: Only coordinator can send final notification
        if action_type == ActionType.FINAL_NOTIFY_HUMAN:
            if sender_role != COORDINATOR_ROLE:
                return PolicyDecision.deny(
                    "UNAUTHORIZED_FINAL_NOTIFICATION",
                    sender_role,
                    action_type.value,
                    "Only VendorCoordinator can send final completion notifications",
                )
            if not is_workflow_terminal and workflow_stage not in (
                WorkflowStage.FINALIZING.value,
                WorkflowStage.COMPLETED.value,
            ):
                return PolicyDecision.deny(
                    "PREMATURE_FINAL_NOTIFICATION",
                    sender_role,
                    action_type.value,
                    "Cannot send final notification before workflow reaches FINALIZING stage",
                )

        # Rule 4: Cannot dispatch to completed agents
        # (This is checked by the outbound guard with workflow state)

        # Rule 5: Cannot dispatch in terminal workflows
        if (action_type == ActionType.DISPATCH_AGENT_TASK
                and is_workflow_terminal):
            return PolicyDecision.deny(
                "DISPATCH_IN_TERMINAL_WORKFLOW",
                sender_role,
                action_type.value,
                "Cannot dispatch agents in a terminal workflow state",
            )

        # Rule 6: Coordinator dispatch must target a valid next-stage agent
        if (sender_role == COORDINATOR_ROLE
                and action_type == ActionType.DISPATCH_AGENT_TASK
                and target_role is not None):
            if target_role == COORDINATOR_ROLE:
                return PolicyDecision.deny(
                    "SELF_DISPATCH",
                    sender_role,
                    action_type.value,
                    "Coordinator cannot dispatch a task to itself",
                )

        return PolicyDecision.allow(f"{action_type.value} permitted for {sender_role}")

    def record_violation(self, violation: PolicyViolation) -> None:
        """Record a policy violation for audit purposes."""
        self._violation_log.append(violation)
        logger.warning("Policy violation recorded: %s — %s",
                        violation.violation_type, violation.details)

    def get_violation_log(self) -> list[PolicyViolation]:
        """Return all recorded policy violations."""
        return list(self._violation_log)

    def get_violation_count(self) -> int:
        """Return the number of recorded violations."""
        return len(self._violation_log)
