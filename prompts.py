"""
VendorVigil — Agent Prompts & Definitions
=========================================
System prompts are loaded from agent spec markdown files in agents/specs/.
Agent configuration definitions (name, model, provider) live in AGENT_DEFS below.

To modify an agent's behavior: edit the corresponding markdown file.
To modify an agent's model/provider: edit AGENT_DEFS below or change .env.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.schemas import AgentRole

from config import (
    GEMINI_MODEL_MAIN,
    GEMINI_MODEL_SECOND_OPINION,
    MODEL_VENDOR_COORDINATOR,
    MODEL_SECURITY_REVIEWER,
    MODEL_PRIVACY_REVIEWER,
    MODEL_FINANCE_REVIEWER,
    MODEL_RISK_SCORER,
    MODEL_AUDIT_LOGGER,
    MODEL_REPORT_COMPILER,
    PROVIDER_VENDOR_COORDINATOR,
    PROVIDER_SECURITY_REVIEWER,
    PROVIDER_PRIVACY_REVIEWER,
    PROVIDER_FINANCE_REVIEWER,
    PROVIDER_RISK_SCORER,
    PROVIDER_AUDIT_LOGGER,
    PROVIDER_REPORT_COMPILER,
    make_model,
    or_model,
    live_gemini_model,
    make_band_model,
    get_vendor_data_block,
)

# OpenRouter fallback models (different provider = different rate limits)
OR_MODEL_FALLBACK = "meta-llama/llama-3.3-70b-instruct"
OR_MODEL_FALLBACK_FAST = "meta-llama/llama-3.3-70b-instruct"

# ---
# Spec Loader — reads agent role specs from markdown files
# ---

_SPECS_DIR = Path(__file__).resolve().parent / "agents" / "specs"


def load_agent_spec(spec_name: str) -> str:
    """Load an agent spec from agents/specs/{spec_name}.md.

    Args:
        spec_name: Filename without .md extension (e.g. 'security_reviewer').

    Returns:
        The markdown content as a string.
    """
    path = _SPECS_DIR / f"{spec_name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"# {spec_name} spec not found"


def _build_agent_prompt(role_spec_name: str, extra_context: str = "") -> str:
    """Build a full agent prompt from spec file + base protocol + extra context.

    Combines:
    1. Band environment spec (shared)
    2. Communication policy spec (shared)
    3. Role-specific spec
    4. Extra context (e.g., vendor data for coordinator)
    """
    env_spec = load_agent_spec("band_environment")
    comm_spec = load_agent_spec("communication_policy")
    role_spec = load_agent_spec(role_spec_name)
    parts = [env_spec, "\n---\n", comm_spec, "\n---\n", role_spec]
    if extra_context:
        parts.extend(["\n---\n", extra_context])
    return "\n".join(parts)

# Cross-provider fallback models (used when primary provider is exhausted)
# Each agent falls back to a DIFFERENT provider than its primary
FALLBACK_MODELS = {
    "groq": ("deepseek-v4-flash", "openrouter"),       # DigitalOcean → DeepSeek (v4-flash)
    "openrouter": ("deepseek-4-flash", "groq"),         # DeepSeek → DigitalOcean (4-flash)
    "gemini": ("deepseek-4-flash", "groq"),             # fallback
    "aiml": ("deepseek-4-flash", "groq"),               # fallback
}


def _make_primary(model_id: str, provider_name: str):
    """Create primary model using the correct provider."""
    return make_model(model_id, provider_name)


def _make_fallback(provider_name: str):
    """Create fallback model from a DIFFERENT provider."""
    fb_model, fb_provider = FALLBACK_MODELS.get(provider_name, ("gemini-2.5-flash", "gemini"))
    return make_model(fb_model, fb_provider)

# ---
# BAND MULTI-AGENT OPERATING SYSTEM — Global Protocol
# ---

SHARED_RULES = (
    "# BAND MULTI-AGENT EXECUTION ENVIRONMENT\n"
    "\n"
    "You are an AI agent operating inside BAND — a structured multi-agent execution system.\n"
    "\n"
    "## Environment Model\n"
    "- Every message is an EVENT in a shared room.\n"
    "- @mentions may be greetings, questions, or task dispatches.\n"
    "- Sending a message = publishing a result event via band_send_message(content).\n"
    "- Plain text output is NOT delivered. Call band_send_message(content) to communicate.\n"
    "\n"
    "## Identity and Mention Format\n"
    "- Your display name is your identity in the room.\n"
    "- When mentioning other agents, use ONLY simplified names: SecurityReviewer, VendorCoordinator, etc. (the system adds @ automatically).\n"
    "- NEVER include username prefixes (e.g., user/agent-name is FORBIDDEN).\n"
    "\n"
    "## Communication Rules\n"
    "- Use band_send_message(content) to send any message.\n"
    "- Use ONE normal text message as your FINAL output. Never publish reasoning, intermediate steps, or tool errors.\n"
    "- A greeting receives ONE concise reply. No repeated introductions or capability lists.\n"
    "- On error, reply briefly without explaining technical details.\n"
    "- You may reply in the caller's language.\n"
    "- All agents share ONE room. Never create sub-rooms or tasks.\n"
    "\n"
    "## Safety Protocol\n"
    "- If unsure what to do: DO NOT guess, DO NOT delegate randomly, WAIT for coordinator.\n"
    "- If role conflict occurs: always default to your role restriction rules.\n"
    "- If mention is ambiguous: respond only within your domain scope.\n"
    "\n"
    "## Forbidden Tools (never call these)\n"
    "band_send_event, band_lookup_peers, band_add_participant, band_remove_participant,\n"
    "band_create_room, band_create_task, band_create_channel,\n"
    "band_invite, band_transfer, band_assign\n"
    "\n"
    "## Output Format\n"
    "- Your final output is ONLY the message text. No meta-commentary.\n"
    "- Never say 'I will coordinate' or 'let me ask X' — you are NOT a coordinator (unless you are VendorCoordinator).\n"
)

# Notice removed: NO_TOOLS_NOTICE caused APIError with Band SDK tool injection
# The Band SDK injects band_send_message as a tool — models MUST use it.
NO_TOOLS_NOTICE = ""  # Empty — kept for backward compat but no longer active

# ---
# SPECIALIST AGENT PROTOCOL — Base for all non-coordinator agents
# ---

ASSESSOR_BASE = (
    SHARED_RULES + "\n\n"
    "# SPECIALIST AGENT PROTOCOL\n"
    "\n"
    "You are a DOMAIN SPECIALIST agent. You are NOT a coordinator or orchestrator.\n"
    "\n"
    "## Core Behavior\n"
    "- When @mentioned by ANY user or agent: respond within your domain expertise.\n"
    "- When asked to assess/analyze a vendor: produce YOUR domain assessment immediately.\n"
    "- When asked a casual question (greeting, general knowledge): respond naturally within your expertise.\n"
    "- When @mentioned by @VendorCoordinator with a task: execute the task and send results back.\n"
    "\n"
    "## Strict Boundaries\n"
    "- DO NOT coordinate, delegate, or assign tasks to other agents.\n"
    "- DO NOT say 'I will coordinate', 'I will begin', 'let me start', or 'I will dispatch'.\n"
    "- DO NOT produce greetings or readiness statements. Produce your ANALYSIS directly.\n"
    "- DO NOT mention other agents in your message content.\n"
    "- DO NOT call band_send_message more than ONCE. Send your output, then stop.\n"
    "\n"
    "## Output Rules\n"
    "- All output must be structured, domain-specific, and factual.\n"
    "- No coordination language, no delegation language, no meta commentary.\n"
    "- If data is insufficient: state what is MISSING in your assessment, do not ask others.\n"
)

# ---
# COORDINATOR PROTOCOL — State Machine Controller
# ---

COORDINATOR_BASE = (
    SHARED_RULES + "\n\n"
    "# COORDINATOR PROTOCOL — STATE MACHINE CONTROLLER\n"
    "\n"
    "You are the VENDOR COORDINATOR — the state machine controller for vendor assessments.\n"
    "\n"
    "## Core Behavior\n"
    "- When a user greets you: respond naturally and conversationally.\n"
    "- When a user requests a vendor assessment: produce a dispatch message immediately.\n"
    "- The runtime automatically determines WHO receives your message based on workflow state.\n"
    "- Your job: produce the right CONTENT. The system handles mentions.\n"
    "\n"
    "## Identity Rules\n"
    "- NEVER put @mention markers in your message content. The system adds them.\n"
    "- NEVER mention yourself.\n"
    "- NEVER mention the human user.\n"
    "\n"
    "## Sequential Workflow\n"
    "When a vendor assessment is requested, dispatch ONE agent at a time:\n"
    "\n"
    "Step 1: Send vendor data to the Security reviewer. STOP and WAIT.\n"
    "Step 2: After Security reviewer responds, send data to the Privacy reviewer. STOP and WAIT.\n"
    "Step 3: After Privacy reviewer responds, send data to the Financial reviewer. STOP and WAIT.\n"
    "Step 4: After ALL 3 respond, compile findings for the Risk scorer. STOP and WAIT.\n"
    "Step 5: After Risk scorer responds, forward to Audit logger. STOP and WAIT.\n"
    "Step 6: After Audit logger responds, forward to Report compiler. STOP and WAIT.\n"
    "Step 7: After Report compiler responds, inform the user that assessment is COMPLETE.\n"
    "\n"
    "## Workflow Rules\n"
    "- ONE agent per message. Never discuss multiple agents in one message.\n"
    "- Call band_send_message ONCE per step, then STOP. Wait for response.\n"
    "- Do NOT skip steps. Do NOT compute domain analysis yourself.\n"
    "- If a specialist has not responded: WAIT. Do NOT re-send.\n"
)


# ---
# Agent Definitions — 7 agents, each with model + prompt loaded from spec files
# ---
# Prompts are built from agents/specs/*.md files via _build_agent_prompt().
# To change behavior: edit the markdown spec files.
# To change model/provider: edit AGENT_DEFS below or change .env variables.
# ---

AGENT_DEFS: list[dict[str, Any]] = [

    # -- 1. COORDINATOR --
    {
        "name": "VendorCoordinator",
        "id_env": "BAND_VENDOR_COORDINATOR_ID",
        "key_env": "BAND_VENDOR_COORDINATOR_KEY",
        "is_coordinator": True,
        "agent_role": AgentRole.VENDOR_COORDINATOR.value,
        "provider_name": PROVIDER_VENDOR_COORDINATOR,
        "model_id": f"openai:{MODEL_VENDOR_COORDINATOR}",
        "band_model": make_band_model(MODEL_VENDOR_COORDINATOR, PROVIDER_VENDOR_COORDINATOR),
        "llm": _make_primary(MODEL_VENDOR_COORDINATOR, PROVIDER_VENDOR_COORDINATOR),
        "fallback": _make_fallback(PROVIDER_VENDOR_COORDINATOR),
        "prompt": _build_agent_prompt("vendor_coordinator", get_vendor_data_block()),
    },

    # -- 2. SECURITY --
    {
        "name": "SecurityReviewer",
        "id_env": "BAND_SECURITY_REVIEWER_ID",
        "key_env": "BAND_SECURITY_REVIEWER_KEY",
        "agent_role": AgentRole.SECURITY_REVIEWER.value,
        "provider_name": PROVIDER_SECURITY_REVIEWER,
        "model_id": f"openai:{MODEL_SECURITY_REVIEWER}",
        "band_model": make_band_model(MODEL_SECURITY_REVIEWER, PROVIDER_SECURITY_REVIEWER),
        "llm": _make_primary(MODEL_SECURITY_REVIEWER, PROVIDER_SECURITY_REVIEWER),
        "fallback": _make_fallback(PROVIDER_SECURITY_REVIEWER),
        "prompt": _build_agent_prompt("security_reviewer"),
    },

    # -- 3. PRIVACY --
    {
        "name": "PrivacyReviewer",
        "id_env": "BAND_PRIVACY_REVIEWER_ID",
        "key_env": "BAND_PRIVACY_REVIEWER_KEY",
        "agent_role": AgentRole.PRIVACY_REVIEWER.value,
        "provider_name": PROVIDER_PRIVACY_REVIEWER,
        "model_id": f"openai:{MODEL_PRIVACY_REVIEWER}",
        "band_model": make_band_model(MODEL_PRIVACY_REVIEWER, PROVIDER_PRIVACY_REVIEWER),
        "llm": _make_primary(MODEL_PRIVACY_REVIEWER, PROVIDER_PRIVACY_REVIEWER),
        "fallback": _make_fallback(PROVIDER_PRIVACY_REVIEWER),
        "prompt": _build_agent_prompt("privacy_reviewer"),
    },

    # -- 4. FINANCIAL --
    {
        "name": "FinancialReviewer",
        "id_env": "BAND_FINANCIAL_REVIEWER_ID",
        "key_env": "BAND_FINANCIAL_REVIEWER_KEY",
        "agent_role": AgentRole.FINANCIAL_REVIEWER.value,
        "provider_name": PROVIDER_FINANCE_REVIEWER,
        "model_id": f"openai:{MODEL_FINANCE_REVIEWER}",
        "band_model": make_band_model(MODEL_FINANCE_REVIEWER, PROVIDER_FINANCE_REVIEWER),
        "llm": _make_primary(MODEL_FINANCE_REVIEWER, PROVIDER_FINANCE_REVIEWER),
        "fallback": _make_fallback(PROVIDER_FINANCE_REVIEWER),
        "prompt": _build_agent_prompt("financial_reviewer"),
    },

    # -- 5. RISK SCORER --
    {
        "name": "RiskScorer",
        "id_env": "BAND_RISK_SCORER_ID",
        "key_env": "BAND_RISK_SCORER_KEY",
        "agent_role": AgentRole.RISK_SCORER.value,
        "provider_name": PROVIDER_RISK_SCORER,
        "model_id": f"openai:{MODEL_RISK_SCORER}",
        "band_model": make_band_model(MODEL_RISK_SCORER, PROVIDER_RISK_SCORER),
        "llm": _make_primary(MODEL_RISK_SCORER, PROVIDER_RISK_SCORER),
        "fallback": _make_fallback(PROVIDER_RISK_SCORER),
        "prompt": _build_agent_prompt("risk_scorer"),
    },

    # -- 6. AUDIT LOGGER --
    {
        "name": "AuditLogger",
        "id_env": "BAND_AUDIT_LOGGER_ID",
        "key_env": "BAND_AUDIT_LOGGER_KEY",
        "agent_role": AgentRole.AUDIT_LOGGER.value,
        "provider_name": PROVIDER_AUDIT_LOGGER,
        "model_id": f"openai:{MODEL_AUDIT_LOGGER}",
        "band_model": make_band_model(MODEL_AUDIT_LOGGER, PROVIDER_AUDIT_LOGGER),
        "llm": _make_primary(MODEL_AUDIT_LOGGER, PROVIDER_AUDIT_LOGGER),
        "fallback": _make_fallback(PROVIDER_AUDIT_LOGGER),
        "prompt": _build_agent_prompt("audit_logger"),
    },

    # -- 7. REPORT COMPILER --
    {
        "name": "ReportCompiler",
        "id_env": "BAND_REPORT_COMPILER_ID",
        "key_env": "BAND_REPORT_COMPILER_KEY",
        "agent_role": AgentRole.REPORT_COMPILER.value,
        "provider_name": PROVIDER_REPORT_COMPILER,
        "model_id": f"openai:{MODEL_REPORT_COMPILER}",
        "band_model": make_band_model(MODEL_REPORT_COMPILER, PROVIDER_REPORT_COMPILER),
        "llm": _make_primary(MODEL_REPORT_COMPILER, PROVIDER_REPORT_COMPILER),
        "fallback": _make_fallback(PROVIDER_REPORT_COMPILER),
        "prompt": _build_agent_prompt("report_compiler"),
    },
]
