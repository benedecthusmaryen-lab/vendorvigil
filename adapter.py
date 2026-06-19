"""
VendorVigil — Band Adapter
===========================
Custom PydanticAIAdapter with runtime enforcement:
  1. Inbound routing guard — silence-by-default, only process targeted events
  2. Outbound message guard — runtime recipient determination, policy validation
  3. Workflow state machine — sequential enforcement, stage tracking
  4. Handle resolver — logical role to transport handle mapping
  5. Action policy — role-based permission enforcement
  6. Fallback model — if primary hits 429/token limit, switch to fallback
  7. Live store hook — saves parsed results to dashboard store
  8. Mock support — skips real API calls when MockModel is active

RUNTIME ENFORCEMENT (after Phase 3 fixes):
- Exact LLM tool inventory: {band_send_message}
- No band_send_event, no execution emission
- DeliveryState per-turn tracking, max one outbound send per event
- SQLite durable event ledger for idempotency
- Structured AgentAction validation for workflow advancement
- TurnContext immutable per-event context
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic_ai import Agent, RunContext
from band.core.protocols import AgentToolsProtocol
from band.runtime.tools import get_tool_description

from band.adapters.pydantic_ai import PydanticAIAdapter
from band.core.simple_adapter import SimpleAdapter

from config import (
    MODEL_SEMAPHORE,
    MOCK_COORDINATOR_MENTIONS,
    MOCK_MENTIONS,
    MockModel,
    RESPONSE_DELAY_SEC,
    MAX_RETRIES,
    RETRY_BACKOFF_SEC,
    ROOM_ID,
    extract_vendor_key,
    get_semaphore,
)
from prompts import ASSESSOR_BASE, COORDINATOR_BASE
from utils.result_collector import parse_agent_message
from utils.mention_extractor import extract_message_mentions
from utils.workflow_state import WorkflowStore
from utils.handle_resolver import HandleResolver, SPECIALIST_ROLES
from utils.action_policy import ActionPolicy
from utils.inbound_guard import InboundRoutingGuard, InboundDecision
from utils.outbound_guard import (
    OutboundMessageGuard,
    GuardResult,
    OutboundResult,
)
from utils.schemas import (
    InteractionMode,
    ActionType,
    AgentRole,
)
from utils.assessment_store import get_shared_store

logger = logging.getLogger("vendorvigil.adapter")

# ---
# Shared runtime components (shared across all adapter instances)
# ---

_SHARED_WORKFLOW_STORE = WorkflowStore()
_SHARED_ACTION_POLICY = ActionPolicy()
_SHARED_INBOUND_GUARD = InboundRoutingGuard()

# Mapping: workflow_id -> assessment_id (bridges WorkflowStore and AssessmentStore)
_WORKFLOW_TO_ASSESSMENT: dict[str, str] = {}


# --- Delivery tracking types ---

class DeliveryState(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    FINAL_FAILURE = "FINAL_FAILURE"
    UNKNOWN = "UNKNOWN"


@dataclass
class DeliveryResult:
    state: DeliveryState = DeliveryState.NOT_ATTEMPTED
    final_text: str | None = None
    attempts: int = 0
    outbound_message_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class TurnContext:
    interaction_mode: InteractionMode
    workflow_id: str | None
    assessment_id: str | None
    event_id: str
    room_id: str
    caller_handle: str
    caller_id: str
    active_role: str | None = None
    sender_role: str | None = None
    target_role: str | None = None
    vendor_id: str | None = None
    task_id: str | None = None


def _is_normal_text_message(msg) -> bool:
    msg_type = getattr(msg, 'message_type', None) or getattr(msg, 'type', None) or ''
    if hasattr(msg_type, 'value'):
        msg_type = msg_type.value
    msg_type = str(msg_type).lower()
    if msg_type not in ('', 'text', 'message'):
        return False
    content = getattr(msg, 'content', '')
    if not content or not isinstance(content, str):
        return False
    return True


async def post_to_band_room(message: str) -> bool:
    """Post a message to the Band room via REST API to trigger agents."""
    import httpx
    agent_key = os.getenv("BAND_VENDOR_COORDINATOR_KEY", "") or os.getenv("BAND_KOORDINATOR_VENDOR_KEY", "")
    if not agent_key or not ROOM_ID:
        logger.error("Cannot post to Band room: missing credentials or room ID")
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.band.ai/v1/rooms/{ROOM_ID}/messages",
                headers={"Authorization": f"Bearer {agent_key}", "Content-Type": "application/json"},
                json={"content": message},
                timeout=15.0,
            )
            if resp.status_code in (200, 201):
                logger.info("Posted to Band room: %s", message[:80])
                return True
            logger.warning("Band post failed: %s %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logger.warning("Failed to post to Band room: %s", e)
        return False


# ---
# Adapter Class
# ---

class VendorVigilPydanticAdapter(PydanticAIAdapter):
    """Custom adapter with fallback, dedup, guard enforcement, and live hooks."""

    def __init__(self, *args, is_coordinator: bool = False, fallback_model=None,
                 agent_role: str = "", agent_name_label: str = "",
                 mock_model=None, provider_name: str = "gemini", band_agent_id: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.is_coordinator = is_coordinator
        self._fallback_model = fallback_model
        self._start_time: datetime | None = None
        self._using_fallback = False
        self._seen_message_hashes: set[str] = set()
        self._agent_role = agent_role  # canonical AgentRole value
        try:
            self._agent_role_short = AgentRole(agent_role).short_key
        except (ValueError, KeyError):
            self._agent_role_short = ""
        self._agent_name_label = agent_name_label
        self._mock_model = mock_model
        self._provider_name = provider_name
        self._band_agent_id = band_agent_id
        self._semaphore = get_semaphore(provider_name)
        # Loop guard
        self._mock_max_responses: int = 13 if is_coordinator else 1
        self._mock_response_count: int = 0
        # Runtime enforcement components (initialized in on_started)
        self._handle_resolver: HandleResolver | None = None
        self._outbound_guard: OutboundMessageGuard | None = None
        # Track live participant metadata
        self._participants_msg: str | None = None

    # ── Lifecycle ──

    async def on_started(self, agent_name: str, agent_description: str) -> None:
        await SimpleAdapter.on_started(self, agent_name, agent_description)

        base = COORDINATOR_BASE if self.is_coordinator else ASSESSOR_BASE
        clean_prompt = (
            f"You are {agent_name}, a VendorVigil specialist agent.\n\n"
            + base + "\n\n"
            + (self.custom_section or "")
        )
        self.system_prompt = clean_prompt
        self._system_prompt = clean_prompt
        self._agent = self._create_agent()
        self._start_time = datetime.now(timezone.utc)

        # Initialize handle resolver from participants if available,
        # otherwise fall back to config (placeholder) handles.
        # Actual participant data from on_message will replace this.
        self._handle_resolver = HandleResolver.from_config()
        self._outbound_guard = OutboundMessageGuard(
            action_policy=_SHARED_ACTION_POLICY,
            handle_resolver=self._handle_resolver,
            workflow_store=_SHARED_WORKFLOW_STORE,
        )

        fb_name = "none"
        if self._fallback_model:
            fb_name = getattr(self._fallback_model, 'model_name', None) or getattr(self._fallback_model, 'model', '?')
        mock_tag = " [MOCK]" if self._mock_model else ""
        logger.info("Adapter started: %s%s (provider: %s, fallback: %s, role: %s)",
                     agent_name, mock_tag, self._provider_name, fb_name, self._agent_role)

    # ── Override _create_agent for mock mode ──

    def _create_agent(self):
        """Create Pydantic AI Agent with EXACT tool inventory: {"band_send_message"}.

        Full override preserves all parent settings (model, deps_type,
        output_type) but registers ONLY band_send_message(content).
        No band_send_event, no peer/participant/room tools.
        """
        model = self._mock_model if self._mock_model is not None else self.model
        system = self.system_prompt or ""

        agent = Agent(
            model,
            system_prompt=system,
            deps_type=AgentToolsProtocol,
            output_type=str,
        )

        async def band_send_message(
            ctx: RunContext[AgentToolsProtocol],
            content: str,
        ) -> str:
            try:
                return await ctx.deps.send_message(content, [])
            except Exception:
                return "not_sent"

        band_send_message.__doc__ = get_tool_description("band_send_message")
        agent.tool(band_send_message)

        # Register custom tools (if any)
        for custom_tool in (self._custom_tools if hasattr(self, '_custom_tools') else []):
            agent.tool(custom_tool)

        return agent

    # ── Fallback ──

    def _switch_to_fallback(self):
        if self._fallback_model and not self._using_fallback:
            self._using_fallback = True
            old_name = getattr(self.model, 'model_name', None) or getattr(self.model, 'model', '?')
            self.model = self._fallback_model
            self._agent = self._create_agent()
            new_name = getattr(self._fallback_model, 'model_name', None) or getattr(self._fallback_model, 'model', '?')
            logger.warning("FALLBACK activated: %s → %s", old_name, new_name)

    @staticmethod
    def _is_retryable_error(error) -> bool:
        err_str = str(error).lower()
        if any(kw in err_str for kw in [
            '404', 'not_found', 'not found', 'decommissioned', 'invalid_request',
            'failed to call a function', 'adjust your prompt', 'failed_generation',
            'apierror',
        ]):
            return False
        return any(kw in err_str for kw in [
            '429', 'concurrency', 'rate limit', 'rate_limit',
            'token limit', 'context_length', 'max_tokens',
            '503', 'service_unavailable',
            'ratelimiterror',
        ])

    # ── Core execution ──

    async def _process_stream_events(self, user_message, tools, room_id):
        """Run agent stream — capture band_send_message content.

        No execution event emission. No band_send_event calls.
        Captures AgentRunResultEvent for plain text fallback.
        """
        from pydantic_ai import FunctionToolCallEvent, AgentRunResultEvent

        captured_content: str | None = None
        final_text: str | None = None

        async for event in self._agent.run_stream_events(
            user_message, deps=tools, message_history=self._message_history[room_id],
        ):
            if isinstance(event, FunctionToolCallEvent):
                if event.part.tool_name == "band_send_message" and isinstance(event.part.args, dict):
                    captured_content = event.part.args.get("content", "")
            elif isinstance(event, AgentRunResultEvent):
                raw = getattr(event, 'data', None)
                if raw is not None:
                    output = getattr(raw, 'output', None) or getattr(raw, 'data', None)
                    if output and isinstance(output, str) and output.strip():
                        final_text = str(output).strip()

        return captured_content, final_text

    def _wrap_send_message(self, tools, ctx: TurnContext):
        """Wrap tools.send_message to enforce OutboundMessageGuard."""
        original_send = getattr(tools, "send_message", None)
        if original_send is None:
            return None

        delivery = DeliveryResult()

        async def guarded_send(content: str, mentions: list[str] | None = None, **kwargs):
            nonlocal delivery
            delivery.attempts += 1

            if not self._outbound_guard:
                delivery.state = DeliveryState.SUCCEEDED
                delivery.final_text = content
                return await original_send(content=content, mentions=mentions or [], **kwargs)

            action_type = self._classify_action_type(ctx)

            result: OutboundResult = self._outbound_guard.validate_and_prepare(
                sender_role=self._agent_role,
                action_type=action_type,
                content=content,
                interaction_mode=ctx.interaction_mode,
                workflow_id=ctx.workflow_id,
                event_id=ctx.event_id,
                llm_mentions=mentions or [],
                caller_handle=ctx.caller_handle,
                caller_id=ctx.caller_id,
            )
            delivery.final_text = result.sanitized_content or content

            if result.guard_result != GuardResult.SENT:
                logger.info("OUTBOUND_BLOCKED: r=%s role=%s ev=%s",
                            result.guard_result.value, self._agent_role, ctx.event_id[:12])
                delivery.state = DeliveryState.POLICY_BLOCKED
                return None

            delivery.state = DeliveryState.SUCCEEDED
            safe_mentions = result.mentions or []
            safe_content = result.sanitized_content or content

            logger.info("OUTBOUND_SENT: r=%s rec=%s ev=%s",
                        action_type.value, result.recipient, ctx.event_id[:12])
            try:
                rv = await original_send(content=safe_content, mentions=safe_mentions, **kwargs)
                if hasattr(rv, 'get'):
                    delivery.outbound_message_id = rv.get('id') or rv.get('message_id')
            except Exception as e:
                delivery.state = DeliveryState.RETRYABLE_FAILURE
                delivery.error_code = type(e).__name__
                raise
            return rv

        guarded_send._delivery = delivery
        return guarded_send

    def _classify_action_type(self, ctx: TurnContext = None,
                              interaction_mode: InteractionMode | None = None,
                              workflow_id: str | None = None) -> ActionType:
        """Context-aware action classification matrix.

        Specialist: CASUAL/DIRECT -> REPLY_TO_CALLER, COORDINATED -> SUBMIT_DOMAIN_RESULT
        Coordinator: CASUAL -> REPLY_TO_CALLER, CLARIFICATION -> REQUEST_CLARIFICATION,
                     COORDINATED + pending -> DISPATCH, FINALIZING -> FINAL_NOTIFY.
        Terminal workflow -> NO_ACTION for all roles.
        """
        if ctx is not None:
            interaction_mode = ctx.interaction_mode
            workflow_id = ctx.workflow_id

        # Terminal workflow check
        if workflow_id:
            from utils.schemas import WorkflowStage
            wf = _SHARED_WORKFLOW_STORE.get_workflow(workflow_id)
            if wf and wf.current_stage in (WorkflowStage.COMPLETED.value, WorkflowStage.FAILED.value, WorkflowStage.CANCELLED.value):
                return ActionType.NO_ACTION

        if not self.is_coordinator:
            if interaction_mode in (InteractionMode.CASUAL_CHAT, InteractionMode.DIRECT_DOMAIN_REQUEST):
                return ActionType.REPLY_TO_CALLER
            if interaction_mode == InteractionMode.COORDINATED_WORKFLOW:
                return ActionType.SUBMIT_DOMAIN_RESULT
            return ActionType.REPLY_TO_CALLER

        # Coordinator
        if interaction_mode == InteractionMode.CASUAL_CHAT:
            return ActionType.REPLY_TO_CALLER
        if interaction_mode == InteractionMode.DIRECT_DOMAIN_REQUEST:
            return ActionType.REPLY_TO_CALLER
        if interaction_mode == InteractionMode.CLARIFICATION:
            return ActionType.REQUEST_CLARIFICATION
        if workflow_id:
            wf = _SHARED_WORKFLOW_STORE.get_workflow(workflow_id)
            if wf:
                from utils.schemas import WorkflowStage
                if wf.current_stage in (WorkflowStage.FINALIZING.value, WorkflowStage.COMPLETED.value):
                    return ActionType.FINAL_NOTIFY_HUMAN
                if wf.active_agent_role and interaction_mode == InteractionMode.COORDINATED_WORKFLOW:
                    return ActionType.DISPATCH_AGENT_TASK
        return ActionType.DISPATCH_AGENT_TASK

    async def _run_agent_stream(self, user_message, tools, room_id,
                                 ctx: TurnContext):
        """Run agent with DeliveryState tracking, max one outbound send."""
        captured_content: str | None = None
        final_text: str | None = None

        # Wrap send_message with guard + delivery tracking
        original_send = getattr(tools, "send_message", None)
        guarded_send = self._wrap_send_message(tools, ctx)
        delivery: DeliveryResult = guarded_send._delivery if guarded_send else DeliveryResult()

        if guarded_send is not None:
            tools.send_message = guarded_send

        # Mark agent running in AssessmentStore (if applicable)
        if ctx.assessment_id and self._agent_role:
            try:
                store = await get_shared_store()
                await store.mark_agent_running(ctx.assessment_id, self._agent_role)
            except Exception as e:
                logger.debug("AssessmentStore mark: %s", e)

        # Mock mode
        if self._mock_model is not None:
            if self._mock_response_count >= self._mock_max_responses:
                self._mock_response_count += 1  # skip
                if original_send is not None:
                    tools.send_message = original_send
                return
            self._mock_response_count += 1
            captured_content = await self._mock_model(agent_role=self._agent_role, step=self._mock_response_count)
            if guarded_send and captured_content:
                await guarded_send(content=captured_content)
            captured_content = captured_content or f"Mock {self._agent_role}"
        else:
            # Real execution
            await self._semaphore.acquire()
            try:
                if RESPONSE_DELAY_SEC > 0:
                    await asyncio.sleep(RESPONSE_DELAY_SEC)

                last_error = None
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        captured_content, final_text = await self._process_stream_events(user_message, tools, room_id)
                        # If send already succeeded, stop retrying
                        if delivery.state == DeliveryState.SUCCEEDED:
                            break
                        # If no content captured but model produced text, send it once
                        if not captured_content and final_text and delivery.state == DeliveryState.NOT_ATTEMPTED:
                            if final_text.upper() != "NO_ACTION" and final_text.strip():
                                if guarded_send:
                                    await guarded_send(content=final_text)
                                captured_content = final_text
                        break
                    except Exception as e:
                        last_error = e
                        if delivery.state == DeliveryState.SUCCEEDED:
                            break  # don't retry after successful send
                        if self._is_retryable_error(e):
                            if attempt < MAX_RETRIES:
                                wait_time = RETRY_BACKOFF_SEC * (2 ** attempt)
                                logger.warning("[%s] Retry %d/%d — %.0fs", self._agent_role, attempt + 1, MAX_RETRIES, wait_time)
                                await asyncio.sleep(wait_time)
                                continue
                            if self._fallback_model and not self._using_fallback:
                                logger.warning("[%s] Fallback activated", self._agent_role)
                                self._switch_to_fallback()
                                self._message_history[room_id] = []
                                try:
                                    captured_content, final_text = await self._process_stream_events(user_message, tools, room_id)
                                    break
                                except Exception as fb_err:
                                    last_error = fb_err
                        if captured_content is None:
                            raise last_error
            finally:
                try:
                    self._semaphore.release()
                except Exception:
                    pass
                if original_send is not None:
                    tools.send_message = original_send

        # Save agent output to AssessmentStore
        await self._save_agent_output(ctx.assessment_id, captured_content)
        return captured_content

    async def _save_agent_output(self, session_id: str | None, content: str | None):
        """Persist agent output to AssessmentStore (SQLite)."""
        if not content or not session_id:
            return

        sender_label = self._agent_name_label or self._agent_role or "unknown"
        role = self._agent_role or ""

        if role:
            try:
                parsed = parse_agent_message(sender_label, content)
                store = await get_shared_store()
                if parsed:
                    # Save parsed result to AssessmentStore
                    await store.mark_agent_done(session_id, role, parsed)
                    logger.info("Agent result saved to AssessmentStore: %s/%s",
                                session_id[:8], role)
                else:
                    # Save raw content even if not parseable
                    await store.mark_agent_done(session_id, role, {"raw": content[:200]})
                    logger.info("Agent raw result saved (unparseable): %s/%s",
                                session_id[:8], role)
            except Exception as e:
                logger.warning("Failed to save agent output to AssessmentStore: %s", e)

    # ── Inbound message handling ──

    async def on_message(self, msg, tools, history, participants_msg, contacts_msg,
                         *, is_session_bootstrap, room_id):
        """Process incoming messages: filter -> claim -> guard -> LLM."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        if self._agent is None:
            self._agent = self._create_agent()

        # ---- Step 1: Non-text filter ----
        if not _is_normal_text_message(msg):
            msg_type = getattr(msg, 'message_type', None) or getattr(msg, 'type', '') or ''
            if hasattr(msg_type, 'value'):
                msg_type = msg_type.value
            logger.info("INBOUND_SKIP_NONTEXT: type=%s", msg_type)
            return

        # ---- Step 2: Self-authored filter (normalize IDs) ----
        sender_id = str(getattr(msg, 'sender_id', '') or '').strip()
        sender_name = str(getattr(msg, 'sender_name', '') or '').strip()
        my_id = str(getattr(self, '_band_agent_id', '') or '').strip()
        if sender_id and my_id and sender_id == my_id:
            logger.info("INBOUND_SELF_TEXT: from %s", sender_name)
            return

        # ---- Step 3: Participant metadata refresh ----
        if participants_msg:
            self._participants_msg = participants_msg
            new_resolver = HandleResolver.from_band_participants(participants_msg)
            if new_resolver.get_all_handles():
                self._handle_resolver = new_resolver
                self._outbound_guard = OutboundMessageGuard(
                    action_policy=_SHARED_ACTION_POLICY,
                    handle_resolver=self._handle_resolver,
                    workflow_store=_SHARED_WORKFLOW_STORE,
                )
                logger.info("Handles: %d", len(new_resolver.get_all_handles()))

        # ---- Step 4: Backlog filter ----
        if self._start_time is not None:
            msg_time = getattr(msg, 'created_at', None)
            if msg_time is not None:
                if msg_time.tzinfo is None:
                    msg_time = msg_time.replace(tzinfo=timezone.utc)
                if msg_time < self._start_time:
                    logger.info("INBOUND_SKIP_BACKLOG")
                    return

        # ---- Step 5: Extract mentions + fallback ----
        mentions_list = extract_message_mentions(msg)
        raw_content = getattr(msg, 'content', str(msg))
        if not mentions_list and raw_content:
            from utils.handle_resolver import ALL_ROLES, ROLE_TO_SLUG
            content_lower = raw_content.lower()
            for role in ALL_ROLES:
                if f"@{role.lower()}" in content_lower:
                    mentions_list.append(role)
                slug = ROLE_TO_SLUG.get(role, "")
                if slug and f"/{slug.lower()}" in content_lower:
                    mentions_list.append(role)
            mentions_list = list(set(mentions_list))

        msg_id = getattr(msg, 'id', None) or getattr(msg, 'message_id', None)
        event_key = f"id:{msg_id}" if msg_id else str(hash(raw_content))

        logger.info("Mentions=%s content=%.50s", mentions_list, raw_content[:50])

        # ---- Step 6: Inbound guard (target filtering before claim) ----
        if self._handle_resolver and _SHARED_INBOUND_GUARD:
            event_for_guard = {
                "sender_name": sender_name,
                "sender_id": sender_id,
                "content": raw_content,
                "event_id": event_key,
                "room_id": room_id,
                "mentions": mentions_list if isinstance(mentions_list, list) else [],
                "is_self": False,
                "created_at": str(getattr(msg, 'created_at', '')),
            }
            inbound_result = _SHARED_INBOUND_GUARD.evaluate(
                event=event_for_guard,
                agent_role=self._agent_role,
                workflow_store=_SHARED_WORKFLOW_STORE,
                handle_resolver=self._handle_resolver,
            )
            if inbound_result.decision != InboundDecision.PROCESS:
                logger.info("INBOUND_IGNORED: r=%s role=%s reason=%s",
                            inbound_result.decision.value, self._agent_role, inbound_result.reason)
                return

        # ---- Step 7: Determine workflow context ----
        interaction_mode = inbound_result.interaction_mode if inbound_result.decision == InboundDecision.PROCESS else InteractionMode.CASUAL_CHAT
        active_wf = _SHARED_WORKFLOW_STORE.get_active_workflow_for_room(room_id)

        if (self.is_coordinator and active_wf is None
                and self._is_assessment_request(raw_content)):
            vendor_key = extract_vendor_key(raw_content)
            from config import lookup_vendor
            vendor_data = lookup_vendor(vendor_key)
            vendor_name = vendor_data.get("vendor_name", vendor_key) if vendor_data else vendor_key
            vendor_id = vendor_data.get("vendor_id", "") if vendor_data else ""
            active_wf = _SHARED_WORKFLOW_STORE.create_workflow(
                room_id=room_id, vendor_id=vendor_id, vendor_name=vendor_name,
                human_requester_id=sender_id, human_requester_handle=sender_name,
            )
            logger.info("Workflow created: %s vendor=%s", active_wf.workflow_id, vendor_name)
            try:
                store = await get_shared_store()
                asmt = await store.create_assessment(vendor_name, vendor_id)
                _WORKFLOW_TO_ASSESSMENT[active_wf.workflow_id] = asmt["assessment_id"]
                await store.update_assessment_status(asmt["assessment_id"], "running")
                logger.info("Assessment: %s", asmt["assessment_id"])
            except Exception as e:
                logger.warning("Assessment create failed: %s", e)
            # Atomic initialization: CREATED -> ROUTING -> first PENDING
            try:
                active_role, stage, _ = await _SHARED_WORKFLOW_STORE.initialize_workflow(
                    active_wf.workflow_id,
                    routing_plan={"requires_security_check": True, "requires_privacy_check": True, "requires_financial_check": True},
                )
                logger.info("Workflow initialized: role=%s stage=%s", active_role, stage)
            except Exception as e:
                logger.warning("Workflow init failed: %s", e)

        workflow_id = active_wf.workflow_id if active_wf else None
        assessment_id = _WORKFLOW_TO_ASSESSMENT.get(workflow_id) if workflow_id else None

        # ---- Step 8b: Coordinator pre-processing — advance stage BEFORE LLM ----
        if (self.is_coordinator and workflow_id
                and interaction_mode == InteractionMode.COORDINATED_WORKFLOW):
            sender_role = self._handle_resolver.get_role_from_sender(sender_name) if self._handle_resolver else None
            if sender_role and sender_role in SPECIALIST_ROLES and raw_content:
                from utils.schemas import validate_specialist_result
                validation = validate_specialist_result(sender_role, raw_content)
                if validation.is_domain_result:
                    await _SHARED_WORKFLOW_STORE.advance_stage(
                        workflow_id, result={"content": raw_content, "payload": validation.result_payload},
                    )
                    active_wf = _SHARED_WORKFLOW_STORE.get_workflow(workflow_id)
                    logger.info("Stage advanced by coordinator: %s → %s", sender_role, active_wf.current_stage if active_wf else '?')
                    if assessment_id:
                        try:
                            store = await get_shared_store()
                            await store.mark_agent_done(assessment_id, sender_role, validation.result_payload or {"raw": raw_content[:200]})
                        except Exception as e:
                            logger.warning("Persist: %s", e)

        # ---- Step 9: Build ctx with updated stage ----
        ctx = TurnContext(
            interaction_mode=interaction_mode,
            workflow_id=workflow_id,
            assessment_id=assessment_id,
            event_id=event_key,
            room_id=room_id,
            caller_handle=sender_name,
            caller_id=sender_id,
            active_role=getattr(active_wf, 'active_agent_role', None) if active_wf else None,
            target_role=self._agent_role,
            vendor_id=getattr(active_wf, 'vendor_id', None) if active_wf else None,
            task_id=getattr(active_wf, 'workflow_id', None) if active_wf else None,
        )

        # ---- Step 10: Format LLM input ----
        envelope = _SHARED_INBOUND_GUARD.build_envelope(
            event={
                "sender_name": sender_name, "sender_id": sender_id,
                "content": raw_content, "event_id": event_key,
                "room_id": room_id,
                "mentions": mentions_list if isinstance(mentions_list, list) else [],
                "is_self": False,
                "created_at": str(getattr(msg, 'created_at', '')),
            },
            agent_role=self._agent_role, mode=interaction_mode,
            workflow_id=workflow_id, handle_resolver=self._handle_resolver,
            workflow_store=_SHARED_WORKFLOW_STORE,
        )
        if inbound_result.interaction_mode:
            envelope["interaction_mode"] = inbound_result.interaction_mode.value
        user_message = self._format_llm_input(envelope)

        # ---- Step 10: Execute ----
        self._message_history[room_id] = []
        if participants_msg:
            self._message_history[room_id].append(
                ModelRequest(parts=[UserPromptPart(content=f"[System]: {participants_msg}")])
            )

        try:
            captured_content = await self._run_agent_stream(user_message, tools, room_id, ctx)
        except Exception as e:
            logger.error("Agent failed room=%s: %s", room_id[:8], type(e).__name__)

    def _is_self_message(self, sender_id: str, sender_name: str) -> bool:
        """Determine if a message was sent by this agent itself.

        Uses trusted sender identity (ID and handle) rather than hardcoded False.
        """
        if not sender_id and not sender_name:
            return False

        # Compare against this agent's own ID if available
        my_id = getattr(self, '_band_agent_id', None) or os.getenv("BAND_AGENT_ID", "")
        if my_id and sender_id == my_id:
            return True

        # Compare sender name against our own handle or name label
        if self._agent_name_label and sender_name:
            if sender_name == self._agent_name_label:
                return True
            if sender_name.rstrip().lstrip("@") == self._agent_name_label.rstrip().lstrip("@"):
                return True

        # Check if sender's handle matches our resolver entry for our own role
        if self._handle_resolver and self._agent_role:
            our_handle = self._handle_resolver.resolve(self._agent_role)
            if our_handle and (sender_name == our_handle or sender_id == our_handle):
                return True

        return False

    def _is_assessment_request(self, message: str) -> bool:
        """Check if a message looks like a vendor assessment request."""
        keywords = [
            "assess", "evaluate", "review", "analyze",
            "penilaian", "analisis", "tinjau", "periksa",
            "analisa", "lakukan", "kerjakan", "proses",
            "audit", "cek", "check", "test",
        ]
        msg_lower = message.lower()
        # Also check for vendor names as implicit assessment trigger
        from config import VENDOR_SCENARIOS
        for vkey in VENDOR_SCENARIOS:
            if vkey in msg_lower:
                return True
        return any(kw in msg_lower for kw in keywords)

    def _format_llm_input(self, envelope: dict[str, Any]) -> str:
        """Format the structured envelope + message content for the LLM.

        Includes trusted context: event_id, sender_role, interaction_mode,
        workflow_id, vendor info, allowed actions.
        """
        parts = []
        parts.append("=== EVENT CONTEXT ===")
        parts.append(f"Event ID: {envelope.get('event_id', 'N/A')}")
        parts.append(f"Room ID: {envelope.get('room_id', 'N/A')}")
        parts.append(f"Interaction Mode: {envelope.get('interaction_mode', 'CASUAL_CHAT')}")
        parts.append(f"Sender Role: {envelope.get('sender_role', 'human')}")
        parts.append(f"Target Agent: {envelope.get('target_role', 'N/A')}")

        if envelope.get("workflow_id"):
            parts.append(f"Workflow ID: {envelope['workflow_id']}")
            parts.append(f"Vendor: {envelope.get('vendor_name', 'N/A')}")
            parts.append(f"Current Stage: {envelope.get('stage', 'N/A')}")

        if envelope.get("allowed_actions"):
            parts.append(f"Allowed Actions: {', '.join(envelope['allowed_actions'])}")

        parts.append("")
        parts.append("=== MESSAGE ===")
        parts.append(envelope.get("message_content", ""))

        return "\n".join(parts)

