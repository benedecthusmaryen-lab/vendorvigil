"""
VendorVigil — Inbound Routing Guard
Determines whether an agent should process an incoming event.
Silence-by-default: agents only act when explicitly targeted.

Usage:
    from utils.inbound_guard import InboundRoutingGuard, InboundDecision
    guard = InboundRoutingGuard()
    decision = guard.should_process(event, agent_role, workflow_store, handle_resolver)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from utils.schemas import (
    InteractionMode,
    WorkflowStage,
    AgentLifecycle,
    AgentRole,
)
from utils.handle_resolver import HandleResolver, COORDINATOR_ROLE, SPECIALIST_ROLES, ALL_ROLES
from utils.workflow_state import WorkflowStore, STAGE_AGENT_ROLE

logger = logging.getLogger("vendorvigil.inbound_guard")


class InboundDecision(str, Enum):
    """Decision on whether to process an incoming event."""
    PROCESS = "PROCESS"
    IGNORE_SELF = "IGNORE_SELF"
    IGNORE_NOT_TARGETED = "IGNORE_NOT_TARGETED"
    IGNORE_DUPLICATE = "IGNORE_DUPLICATE"
    IGNORE_STALE = "IGNORE_STALE"
    IGNORE_WRONG_WORKFLOW = "IGNORE_WRONG_WORKFLOW"
    IGNORE_COMPLETED = "IGNORE_COMPLETED"
    IGNORE_OUT_OF_ORDER = "IGNORE_OUT_OF_ORDER"
    IGNORE_SYSTEM_EVENT = "IGNORE_SYSTEM_EVENT"


@dataclass
class InboundResult:
    """Result of inbound routing evaluation."""
    decision: InboundDecision
    interaction_mode: InteractionMode | None = None
    workflow_id: str | None = None
    reason: str = ""


class InboundRoutingGuard:
    """Determines whether an agent should process an incoming Band event."""

    def evaluate(
        self,
        event: dict[str, Any],
        agent_role: str,
        workflow_store: WorkflowStore,
        handle_resolver: HandleResolver,
    ) -> InboundResult:
        """Evaluate whether this agent should process the event.

        Args:
            event: Dict with keys: sender_name, sender_id, content,
                   event_id, room_id, mentions (list), created_at,
                   is_self (bool).
            agent_role: This agent's logical role.
            workflow_store: The workflow state store.
            handle_resolver: The handle resolver for this room.

        Returns:
            InboundResult with decision and metadata.
        """
        sender_name = event.get("sender_name", "")
        sender_role = handle_resolver.get_role_from_sender(sender_name)
        content = event.get("content", "")
        event_id = event.get("event_id", "")
        room_id = event.get("room_id", "")
        mentions = event.get("mentions", [])
        is_self = event.get("is_self", False)

        # Rule 1: Ignore own messages
        if is_self or sender_role == agent_role:
            return InboundResult(
                decision=InboundDecision.IGNORE_SELF,
                reason="Ignoring self-authored event",
            )

        # Rule 2: Ignore system/participant updates
        if event.get("is_system_event", False):
            return InboundResult(
                decision=InboundDecision.IGNORE_SYSTEM_EVENT,
                reason="Ignoring system event",
            )

        # Rule 3: Check duplicate event ID
        active_wf = workflow_store.get_active_workflow_for_room(room_id)
        if active_wf and event_id:
            if workflow_store.is_event_processed(active_wf.workflow_id, event_id):
                return InboundResult(
                    decision=InboundDecision.IGNORE_DUPLICATE,
                    workflow_id=active_wf.workflow_id,
                    reason=f"Event {event_id} already processed",
                )

        # Rule 3b: Multi-agent broadcast policy
        # Human sender with 2+ mentions: only coordinator processes
        human_mentioned = [m for m in mentions if handle_resolver.is_human_sender(sender_name) is False]
        is_human = handle_resolver.is_human_sender(sender_name)
        if is_human and len(mentions) >= 2:
            if agent_role != COORDINATOR_ROLE:
                return InboundResult(
                    decision=InboundDecision.IGNORE_NOT_TARGETED,
                    reason="Multi-agent broadcast: only coordinator responds",
                )

        # Rule 4: Check if this agent is targeted by the message
        is_targeted = self._is_agent_targeted(agent_role, mentions, content, handle_resolver)

        # Rule 5: Check workflow state for coordinated workflow events
        if active_wf:
            wf_result = self._check_workflow_context(
                agent_role, sender_role, active_wf, is_targeted
            )
            if wf_result:
                return wf_result

        # Classify interaction mode
        mode = self._classify_mode(
            agent_role, sender_role, is_targeted, content, active_wf
        )

        # If not targeted and not in workflow context, ignore
        if not is_targeted and mode != InteractionMode.COORDINATED_WORKFLOW:
            return InboundResult(
                decision=InboundDecision.IGNORE_NOT_TARGETED,
                interaction_mode=mode,
                reason=f"Agent {agent_role} not targeted by message",
            )

        logger.info("INBOUND_ACCEPTED: agent=%s mode=%s wf=%s", agent_role, mode.value if mode else "?", active_wf.workflow_id if active_wf else None)
        return InboundResult(
            decision=InboundDecision.PROCESS,
            interaction_mode=mode,
            workflow_id=active_wf.workflow_id if active_wf else None,
            reason="Event accepted for processing",
        )

    def _is_agent_targeted(
        self,
        agent_role: str,
        mentions: list[str],
        content: str,
        handle_resolver: HandleResolver,
    ) -> bool:
        """Check if the agent is explicitly targeted by the message.

        Strategy:
        1. Check metadata.mentions list (via Band SDK Mention objects)
        2. Check for @RoleName or @handle patterns in content
        3. Check for any known agent slug in content (fallback when
           Band web UI doesn't populate metadata.mentions)
        """
        # ---- Strategy 1: Check metadata mentions list ----
        normalized_mentions = [m.lstrip("@") for m in mentions if m]
        agent_handle = handle_resolver.resolve(agent_role)
        if agent_handle:
            normalized_handle = agent_handle.lstrip("@")
            if normalized_handle in normalized_mentions:
                return True
            for nm in normalized_mentions:
                slug_part = normalized_handle.split("/")[-1] if "/" in normalized_handle else normalized_handle
                if slug_part and slug_part in nm:
                    return True

        # ---- Strategy 2: Check @RoleName pattern in content ----
        role_pattern = re.compile(rf"@{re.escape(agent_role)}\b", re.IGNORECASE)
        if role_pattern.search(content):
            return True

        # ---- Strategy 3: Check full handle pattern in content ----
        from utils.handle_resolver import ROLE_TO_SLUG
        slug = ROLE_TO_SLUG.get(agent_role, "")
        if slug:
            # Match @username/slug anywhere in content
            slug_pattern = re.compile(rf"@?[\w.-]*/{re.escape(slug)}\b", re.IGNORECASE)
            if slug_pattern.search(content):
                return True
            # Match standalone slug (without username prefix)
            standalone_pattern = re.compile(rf"\b{re.escape(slug)}\b", re.IGNORECASE)
            if standalone_pattern.search(content):
                return True

        return False

    def _check_workflow_context(
        self,
        agent_role: str,
        sender_role: str | None,
        workflow,
        is_targeted: bool,
    ) -> InboundResult | None:
        """Check workflow-related conditions that might require ignoring."""
        wf_stage = workflow.current_stage

        # If workflow is terminal, ignore workflow-related events
        if wf_stage in {
            WorkflowStage.COMPLETED.value,
            WorkflowStage.FAILED.value,
            WorkflowStage.CANCELLED.value,
        }:
            if not is_targeted:
                return InboundResult(
                    decision=InboundDecision.IGNORE_COMPLETED,
                    workflow_id=workflow.workflow_id,
                    reason=f"Workflow {workflow.workflow_id} is terminal ({wf_stage})",
                )
            return None  # Allow direct chat even if workflow is terminal

        # Check if this agent is already completed in the workflow
        if agent_role in workflow.completed_agents:
            if not is_targeted:
                return InboundResult(
                    decision=InboundDecision.IGNORE_COMPLETED,
                    workflow_id=workflow.workflow_id,
                    reason=f"Agent {agent_role} already completed in workflow",
                )

        # Check out-of-order results: specialist sending result when it's not their turn
        expected_role = STAGE_AGENT_ROLE.get(WorkflowStage(wf_stage))
        if (sender_role in SPECIALIST_ROLES
                and sender_role != expected_role
                and agent_role == COORDINATOR_ROLE
                and not is_targeted):
            return InboundResult(
                decision=InboundDecision.IGNORE_OUT_OF_ORDER,
                workflow_id=workflow.workflow_id,
                reason=(
                    f"Result from {sender_role} rejected: "
                    f"current stage expects {expected_role}"
                ),
            )

        return None

    def _classify_mode(
        self,
        agent_role: str,
        sender_role: str | None,
        is_targeted: bool,
        content: str,
        active_workflow,
    ) -> InteractionMode:
        """Classify the interaction mode based on message context."""

        # If there's an active workflow and this message is part of it
        if active_workflow and active_workflow.current_stage not in {
            WorkflowStage.COMPLETED.value,
            WorkflowStage.FAILED.value,
            WorkflowStage.CANCELLED.value,
        }:
            # Coordinator receiving specialist results
            if agent_role == COORDINATOR_ROLE and sender_role in SPECIALIST_ROLES:
                return InteractionMode.COORDINATED_WORKFLOW

            # Specialist receiving task from coordinator
            if agent_role in SPECIALIST_ROLES and sender_role == COORDINATOR_ROLE:
                return InteractionMode.COORDINATED_WORKFLOW

            # Coordinator receiving clarification from human
            if (agent_role == COORDINATOR_ROLE
                    and sender_role is None
                    and active_workflow.pending_clarification):
                return InteractionMode.CLARIFICATION

        # Check if content looks like a vendor assessment request
        if agent_role == COORDINATOR_ROLE and is_targeted:
            assessment_keywords = [
                "assess", "evaluate", "review", "analyze",
                "penilaian", "analisis", "tinjau", "periksa",
                "analisa", "lakukan", "kerjakan", "proses",
                "audit", "cek", "check", "test",
            ]
            content_lower = content.lower()
            if any(kw in content_lower for kw in assessment_keywords):
                return InteractionMode.COORDINATED_WORKFLOW
            # Also check vendor names
            try:
                from config import VENDOR_SCENARIOS
                for vkey in VENDOR_SCENARIOS:
                    if vkey in content_lower:
                        return InteractionMode.COORDINATED_WORKFLOW
            except Exception:
                pass

        # Check if content looks like a direct domain request
        if agent_role in SPECIALIST_ROLES and is_targeted:
            # Map full logical role names to short domain keyword keys
            role_to_keyword = {
                "SecurityReviewer": "security",
                "PrivacyReviewer": "privacy",
                "FinancialReviewer": "financial",
                "RiskScorer": "risk",
                "AuditLogger": "audit",
                "ReportCompiler": "report",
            }
            domain_keywords = {
                "security": ["security", "soc", "iso", "encryption", "keamanan"],
                "privacy": ["privacy", "dpa", "gdpr", "data", "privasi"],
                "financial": ["financial", "funding", "revenue", "financial", "finansial"],
                "risk": ["risk", "score", "risk", "risiko"],
                "audit": ["audit", "record", "log", "audit"],
                "report": ["report", "summary", "laporan"],
            }
            content_lower = content.lower()
            keyword_key = role_to_keyword.get(agent_role, "")
            keywords = domain_keywords.get(keyword_key, [])
            if any(kw in content_lower for kw in keywords):
                return InteractionMode.DIRECT_DOMAIN_REQUEST

        # Default: casual chat
        return InteractionMode.CASUAL_CHAT

    def build_envelope(
        self,
        event: dict[str, Any],
        agent_role: str,
        mode: InteractionMode,
        workflow_id: str | None,
        handle_resolver: HandleResolver,
        workflow_store: WorkflowStore,
    ) -> dict[str, Any]:
        """Build a structured context envelope for the LLM.

        Instead of passing raw '[Sender]: content' strings, provide
        structured metadata so the agent understands its context.
        """
        sender_role = handle_resolver.get_role_from_sender(
            event.get("sender_name", "")
        )

        workflow = None
        if workflow_id:
            workflow = workflow_store.get_workflow(workflow_id)

        envelope = {
            "event_id": event.get("event_id", ""),
            "room_id": event.get("room_id", ""),
            "interaction_mode": mode.value,
            "sender_id": event.get("sender_id", ""),
            "sender_type": "agent" if sender_role else "human",
            "sender_role": sender_role or "human",
            "sender_handle": event.get("sender_name", ""),
            "target_role": agent_role,
            "message_content": event.get("content", ""),
            "created_at": event.get("created_at", ""),
        }

        # Add workflow context if available
        if workflow:
            envelope["workflow_id"] = workflow.workflow_id
            envelope["vendor_id"] = workflow.vendor_id
            envelope["vendor_name"] = workflow.vendor_name
            envelope["stage"] = workflow.current_stage
            envelope["human_requester_handle"] = workflow.human_requester_handle

            # Determine allowed actions for this agent in this context
            from utils.action_policy import ActionPolicy, ActionType
            policy = ActionPolicy()
            allowed = policy.get_allowed_actions(agent_role)
            envelope["allowed_actions"] = [a.value for a in allowed]
        else:
            from utils.action_policy import ActionPolicy, ActionType
            policy = ActionPolicy()
            allowed = policy.get_allowed_actions(agent_role)
            envelope["allowed_actions"] = [a.value for a in allowed]

        return envelope
