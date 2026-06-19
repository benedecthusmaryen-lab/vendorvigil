"""
VendorVigil — Workflow State Machine
Manages sequential vendor assessment workflows with persisted state.
Replaces implicit chat-based coordination with explicit state transitions.

Usage:
    from utils.workflow_state import WorkflowStore, WorkflowStage
    store = WorkflowStore()
    wf = store.create_workflow(room_id, vendor_id, vendor_name, human_id, human_handle)
    store.advance_stage(wf.workflow_id, routing_plan_result)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.schemas import (
    WorkflowStage,
    AgentLifecycle,
    InteractionMode,
    AgentRole,
)

logger = logging.getLogger("vendorvigil.workflow")

# Workflow persistence directory
_STATE_DIR = Path(__file__).resolve().parent.parent / "logs" / "workflows"

# Sequential stage order
STAGE_ORDER: list[WorkflowStage] = [
    WorkflowStage.CREATED,
    WorkflowStage.ROUTING,
    WorkflowStage.SECURITY_PENDING,
    WorkflowStage.PRIVACY_PENDING,
    WorkflowStage.FINANCIAL_PENDING,
    WorkflowStage.RISK_PENDING,
    WorkflowStage.AUDIT_PENDING,
    WorkflowStage.REPORT_PENDING,
    WorkflowStage.FINALIZING,
    WorkflowStage.COMPLETED,
]

# Maps each stage to the agent role responsible for it (using canonical AgentRole)
STAGE_AGENT_ROLE: dict[WorkflowStage, str] = {
    WorkflowStage.SECURITY_PENDING: AgentRole.SECURITY_REVIEWER.value,
    WorkflowStage.PRIVACY_PENDING: AgentRole.PRIVACY_REVIEWER.value,
    WorkflowStage.FINANCIAL_PENDING: AgentRole.FINANCIAL_REVIEWER.value,
    WorkflowStage.RISK_PENDING: AgentRole.RISK_SCORER.value,
    WorkflowStage.AUDIT_PENDING: AgentRole.AUDIT_LOGGER.value,
    WorkflowStage.REPORT_PENDING: AgentRole.REPORT_COMPILER.value,
}

# Terminal stages where no further processing occurs
TERMINAL_STAGES = {
    WorkflowStage.COMPLETED,
    WorkflowStage.FAILED,
    WorkflowStage.CANCELLED,
}

# Maximum turns before a workflow is considered stuck
MAX_TURNS_PER_WORKFLOW = 30
MAX_RETRIES_PER_STAGE = 2
STAGE_TIMEOUT_SECONDS = 120


@dataclass
class WorkflowState:
    """Persisted state for a single vendor assessment workflow."""

    workflow_id: str
    room_id: str
    vendor_id: str
    vendor_name: str
    human_requester_id: str = ""
    human_requester_handle: str = ""
    interaction_mode: str = InteractionMode.COORDINATED_WORKFLOW.value
    status: str = WorkflowStage.CREATED.value
    current_stage: str = WorkflowStage.CREATED.value
    active_agent_role: str | None = None
    required_agents: list[str] = field(default_factory=list)
    completed_agents: list[str] = field(default_factory=list)
    skipped_agents: list[str] = field(default_factory=list)
    failed_agents: list[str] = field(default_factory=list)
    agent_lifecycle: dict[str, str] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)
    pending_clarification: dict[str, Any] | None = None
    turn_count: int = 0
    retry_count_by_stage: dict[str, int] = field(default_factory=dict)
    processed_event_ids: list[str] = field(default_factory=list)
    last_outbound_action: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON persistence."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowState:
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class WorkflowStore:
    """Thread-safe in-memory store for workflow states with JSON persistence."""

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowState] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        _STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _get_lock(self, workflow_id: str) -> asyncio.Lock:
        if workflow_id not in self._locks:
            self._locks[workflow_id] = asyncio.Lock()
        return self._locks[workflow_id]

    def create_workflow(
        self,
        room_id: str,
        vendor_id: str,
        vendor_name: str,
        human_requester_id: str = "",
        human_requester_handle: str = "",
    ) -> WorkflowState:
        """Create a new workflow in CREATED stage."""
        workflow_id = f"wf-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()

        state = WorkflowState(
            workflow_id=workflow_id,
            room_id=room_id,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            human_requester_id=human_requester_id,
            human_requester_handle=human_requester_handle,
            created_at=now,
            updated_at=now,
        )

        self._workflows[workflow_id] = state
        self._persist(state)
        logger.info("Workflow created: %s for vendor %s in room %s",
                     workflow_id, vendor_name, room_id)
        return state

    async def initialize_workflow(
        self, workflow_id: str,
        routing_plan: dict[str, bool] | None = None,
    ) -> tuple[str, str, str]:
        """Atomically initialize workflow: CREATED -> ROUTING -> first PENDING.

        Returns (active_agent_role, current_stage, workflow_id).
        Does NOT force SecurityReviewer if routing plan skips it.
        After init, active_agent_role is set for immediate coordinator dispatch.
        """
        if routing_plan is None:
            routing_plan = {"requires_security_check": True, "requires_privacy_check": True, "requires_financial_check": True}

        state = self._workflows.get(workflow_id)
        if not state:
            raise ValueError(f"Workflow {workflow_id} not found")

        # Stage 1: CREATED -> ROUTING
        state.current_stage = WorkflowStage.ROUTING.value
        state.status = WorkflowStage.ROUTING.value

        # Process routing plan
        state.required_agents = []
        for check_key, role in [
            ("requires_security_check", AgentRole.SECURITY_REVIEWER),
            ("requires_privacy_check", AgentRole.PRIVACY_REVIEWER),
            ("requires_financial_check", AgentRole.FINANCIAL_REVIEWER),
        ]:
            if routing_plan.get(check_key, True):
                state.required_agents.append(role.value)
            else:
                state.skipped_agents.append(role.value)
                state.agent_lifecycle[role.value] = AgentLifecycle.SKIPPED.value

        state.required_agents.extend([
            AgentRole.RISK_SCORER.value,
            AgentRole.AUDIT_LOGGER.value,
            AgentRole.REPORT_COMPILER.value,
        ])
        state.results["routing_plan"] = routing_plan

        # Stage 2: ROUTING -> first PENDING stage
        next_stage = self._compute_next_stage(state)
        state.current_stage = next_stage.value
        state.status = next_stage.value
        state.active_agent_role = STAGE_AGENT_ROLE.get(next_stage)
        if state.active_agent_role:
            state.agent_lifecycle[state.active_agent_role] = AgentLifecycle.ASSIGNED.value

        state.turn_count += 1
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)
        logger.info("Workflow %s initialized: stage=%s active=%s",
                     workflow_id, state.current_stage, state.active_agent_role)
        return (state.active_agent_role or "", state.current_stage, workflow_id)

    def get_workflow(self, workflow_id: str) -> WorkflowState | None:
        """Get workflow by ID."""
        return self._workflows.get(workflow_id)

    def get_active_workflow_for_room(self, room_id: str) -> WorkflowState | None:
        """Get the most recent non-terminal workflow for a room."""
        candidates = [
            wf for wf in self._workflows.values()
            if wf.room_id == room_id
            and wf.status not in {s.value for s in TERMINAL_STAGES}
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda w: w.created_at, reverse=True)
        return candidates[0]

    def get_active_workflows(self) -> list[WorkflowState]:
        """Get all non-terminal workflows."""
        return [
            wf for wf in self._workflows.values()
            if wf.status not in {s.value for s in TERMINAL_STAGES}
        ]

    async def advance_stage(
        self,
        workflow_id: str,
        result: dict[str, Any] | None = None,
        routing_plan: dict[str, Any] | None = None,
    ) -> WorkflowState:
        """Advance workflow to the next stage. Thread-safe with async lock.

        Args:
            workflow_id: The workflow to advance.
            result: The validated result from the current stage's agent.
            routing_plan: RoutingPlan dict (only for ROUTING stage).
        """
        lock = self._get_lock(workflow_id)
        async with lock:
            state = self._workflows.get(workflow_id)
            if not state:
                raise ValueError(f"Workflow {workflow_id} not found")

            current = WorkflowStage(state.current_stage)
            if current in TERMINAL_STAGES:
                logger.warning("Attempted to advance terminal workflow %s", workflow_id)
                return state

            # Store result if provided
            if result and state.active_agent_role:
                state.results[state.active_agent_role] = result
                state.completed_agents.append(state.active_agent_role)
                state.agent_lifecycle[state.active_agent_role] = AgentLifecycle.DONE.value

            # If we just completed ROUTING, determine required agents
            if current == WorkflowStage.ROUTING and routing_plan:
                state.required_agents = []
                if routing_plan.get("requires_security_check"):
                    state.required_agents.append(AgentRole.SECURITY_REVIEWER.value)
                else:
                    state.skipped_agents.append(AgentRole.SECURITY_REVIEWER.value)
                    state.agent_lifecycle[AgentRole.SECURITY_REVIEWER.value] = AgentLifecycle.SKIPPED.value

                if routing_plan.get("requires_privacy_check"):
                    state.required_agents.append(AgentRole.PRIVACY_REVIEWER.value)
                else:
                    state.skipped_agents.append(AgentRole.PRIVACY_REVIEWER.value)
                    state.agent_lifecycle[AgentRole.PRIVACY_REVIEWER.value] = AgentLifecycle.SKIPPED.value

                if routing_plan.get("requires_financial_check"):
                    state.required_agents.append(AgentRole.FINANCIAL_REVIEWER.value)
                else:
                    state.skipped_agents.append(AgentRole.FINANCIAL_REVIEWER.value)
                    state.agent_lifecycle[AgentRole.FINANCIAL_REVIEWER.value] = AgentLifecycle.SKIPPED.value

                # Risk, Audit, Report are always required
                state.required_agents.extend([
                    AgentRole.RISK_SCORER.value,
                    AgentRole.AUDIT_LOGGER.value,
                    AgentRole.REPORT_COMPILER.value,
                ])
                state.results["routing_plan"] = routing_plan

            # Determine next stage
            next_stage = self._compute_next_stage(state)
            state.current_stage = next_stage.value
            state.status = next_stage.value

            # Set active agent for the new stage
            state.active_agent_role = STAGE_AGENT_ROLE.get(next_stage)
            if state.active_agent_role:
                state.agent_lifecycle[state.active_agent_role] = AgentLifecycle.ASSIGNED.value

            state.turn_count += 1
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self._persist(state)

            logger.info("Workflow %s advanced to %s (turn %d)",
                        workflow_id, next_stage.value, state.turn_count)
            return state

    def _compute_next_stage(self, state: WorkflowState) -> WorkflowStage:
        """Compute the next stage based on current state and completed agents."""
        current = WorkflowStage(state.current_stage)

        # Stage transition map
        transitions: dict[WorkflowStage, WorkflowStage] = {
            WorkflowStage.CREATED: WorkflowStage.ROUTING,
            WorkflowStage.ROUTING: WorkflowStage.SECURITY_PENDING,
            WorkflowStage.SECURITY_PENDING: WorkflowStage.PRIVACY_PENDING,
            WorkflowStage.PRIVACY_PENDING: WorkflowStage.FINANCIAL_PENDING,
            WorkflowStage.FINANCIAL_PENDING: WorkflowStage.RISK_PENDING,
            WorkflowStage.RISK_PENDING: WorkflowStage.AUDIT_PENDING,
            WorkflowStage.AUDIT_PENDING: WorkflowStage.REPORT_PENDING,
            WorkflowStage.REPORT_PENDING: WorkflowStage.FINALIZING,
            WorkflowStage.FINALIZING: WorkflowStage.COMPLETED,
        }

        next_stage = transitions.get(current)
        if next_stage is None:
            return WorkflowStage.COMPLETED

        # Skip stages where the agent was skipped
        while next_stage in transitions:
            agent_role = STAGE_AGENT_ROLE.get(next_stage)
            if agent_role and agent_role in state.skipped_agents:
                next_stage = transitions[next_stage]
            else:
                break

        return next_stage

    def mark_agent_running(self, workflow_id: str, role: str) -> None:
        """Mark an agent as actively running within a workflow."""
        state = self._workflows.get(workflow_id)
        if state:
            state.agent_lifecycle[role] = AgentLifecycle.RUNNING.value
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self._persist(state)

    def mark_agent_done(self, workflow_id: str, role: str, result: dict[str, Any] | None = None) -> None:
        """Mark an agent as done and store its result."""
        state = self._workflows.get(workflow_id)
        if not state:
            return
        state.agent_lifecycle[role] = AgentLifecycle.DONE.value
        if role not in state.completed_agents:
            state.completed_agents.append(role)
        if result:
            state.results[role] = result
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)

    def mark_agent_skipped(self, workflow_id: str, role: str) -> None:
        """Mark an agent as skipped (not required by routing plan)."""
        state = self._workflows.get(workflow_id)
        if not state:
            return
        state.agent_lifecycle[role] = AgentLifecycle.SKIPPED.value
        if role not in state.skipped_agents:
            state.skipped_agents.append(role)
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)

    def mark_agent_failed(self, workflow_id: str, role: str) -> None:
        """Mark an agent as failed."""
        state = self._workflows.get(workflow_id)
        if not state:
            return
        state.agent_lifecycle[role] = AgentLifecycle.FAILED.value
        if role not in state.failed_agents:
            state.failed_agents.append(role)
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)

    def fail_workflow(self, workflow_id: str, reason: str = "") -> None:
        """Mark a workflow as failed."""
        state = self._workflows.get(workflow_id)
        if not state:
            return
        state.status = WorkflowStage.FAILED.value
        state.current_stage = WorkflowStage.FAILED.value
        if reason:
            state.results["_failure_reason"] = reason
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)
        logger.warning("Workflow %s FAILED: %s", workflow_id, reason)

    def record_event_id(self, workflow_id: str, event_id: str) -> bool:
        """Record a processed event ID. Returns False if already seen (duplicate)."""
        state = self._workflows.get(workflow_id)
        if not state:
            return True
        if event_id in state.processed_event_ids:
            return False
        state.processed_event_ids.append(event_id)
        return True

    def is_event_processed(self, workflow_id: str, event_id: str) -> bool:
        """Check if an event has already been processed."""
        state = self._workflows.get(workflow_id)
        if not state:
            return False
        return event_id in state.processed_event_ids

    def increment_stage_retry(self, workflow_id: str) -> int:
        """Increment retry count for the current stage. Returns new count."""
        state = self._workflows.get(workflow_id)
        if not state:
            return 0
        stage = state.current_stage
        count = state.retry_count_by_stage.get(stage, 0) + 1
        state.retry_count_by_stage[stage] = count
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)
        return count

    def is_workflow_complete(self, workflow_id: str) -> bool:
        """Check if a workflow has reached a terminal state."""
        state = self._workflows.get(workflow_id)
        if not state:
            return True
        return state.status in {s.value for s in TERMINAL_STAGES}

    def is_all_required_done(self, workflow_id: str) -> bool:
        """Check if all required agents have completed."""
        state = self._workflows.get(workflow_id)
        if not state:
            return True
        return all(
            agent in state.completed_agents or agent in state.skipped_agents
            for agent in state.required_agents
        )

    def set_clarification(self, workflow_id: str, question: str, from_role: str) -> None:
        """Set a pending clarification request."""
        state = self._workflows.get(workflow_id)
        if not state:
            return
        state.pending_clarification = {
            "question": question,
            "from_role": from_role,
        }
        state.status = WorkflowStage.WAITING_FOR_HUMAN.value
        state.current_stage = WorkflowStage.WAITING_FOR_HUMAN.value
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)

    def resolve_clarification(self, workflow_id: str, answer: str) -> None:
        """Resolve a pending clarification and resume workflow."""
        state = self._workflows.get(workflow_id)
        if not state:
            return
        state.results["_clarification_answer"] = answer
        state.pending_clarification = None
        # Restore to the stage before clarification was needed
        state.status = state.results.get("_pre_clarification_stage", WorkflowStage.ROUTING.value)
        state.current_stage = state.status
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(state)

    def _persist(self, state: WorkflowState) -> None:
        """Persist workflow state to JSON file."""
        try:
            path = _STATE_DIR / f"{state.workflow_id}.json"
            path.write_text(json.dumps(state.to_dict(), indent=2, default=str))
        except Exception as e:
            logger.error("Failed to persist workflow %s: %s", state.workflow_id, e)

    def load_from_disk(self) -> None:
        """Load all persisted workflows from disk."""
        for path in _STATE_DIR.glob("wf-*.json"):
            try:
                data = json.loads(path.read_text())
                state = WorkflowState.from_dict(data)
                self._workflows[state.workflow_id] = state
                logger.info("Loaded workflow %s from disk (stage: %s)",
                            state.workflow_id, state.current_stage)
            except Exception as e:
                logger.warning("Failed to load workflow from %s: %s", path.name, e)

    def get_all_workflows(self) -> list[WorkflowState]:
        """Return all workflows (including terminal)."""
        return list(self._workflows.values())
