#!/usr/bin/env python3
"""Batch fix remaining critical runtime issues."""
import os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

def read(f):
    with open(f) as fh: return fh.read()

def write(f, c):
    with open(f, 'w') as fh: fh.write(c)
    print(f"  Updated {f}")

# ===================================================================
# 1. Dashboard .env files
# ===================================================================
ui_dir = "vendorvigil_ui"
if not os.path.exists(f"{ui_dir}/.env.development.example"):
    write(f"{ui_dir}/.env.development.example",
        "# Development environment for VendorVigil dashboard\n"
        "# In dev mode, CRA proxy forwards /api requests to the backend\n"
        "REACT_APP_API_URL=\n")
if not os.path.exists(f"{ui_dir}/.env.production.example"):
    write(f"{ui_dir}/.env.production.example",
        "# Production environment for VendorVigil dashboard\n"
        "# Set to the FastAPI backend URL\n"
        "REACT_APP_API_URL=http://localhost:8000\n")

# ===================================================================
# 2. Mention extraction utility
# ===================================================================
util_code = '''
"""
VendorVigil — Band Mention Extraction
Extracts trusted mention handles from Band PlatformMessage metadata.
Band stores mentions in msg.metadata["mentions"], not msg.mentions.
"""
from __future__ import annotations
from typing import Any


def extract_message_mentions(msg: Any) -> list[str]:
    """Extract normalized mention handles from a Band PlatformMessage.

    Reads msg.metadata["mentions"] which is a list of dicts with keys:
      id, username, name, handle

    Returns a list of normalized handle strings (username or handle field).
    Falls back to empty list if no metadata or no mentions.
    """
    metadata = getattr(msg, "metadata", None) or {}
    if isinstance(metadata, dict):
        raw_mentions = metadata.get("mentions", [])
    else:
        # Pydantic object with dict-like access
        raw_mentions = getattr(metadata, "mentions", []) if hasattr(metadata, "mentions") else []

    if not isinstance(raw_mentions, list):
        return []

    handles = []
    for m in raw_mentions:
        if isinstance(m, dict):
            # Try handle, then username, then name, then id
            handle = m.get("handle") or m.get("username") or m.get("name") or ""
            if handle:
                handles.append(handle)
        elif isinstance(m, str):
            handles.append(m)
    return handles
'''

with open("utils/mention_extractor.py", "w") as f:
    f.write(util_code.lstrip())
print("  Created utils/mention_extractor.py")

# ===================================================================
# 3. Fix outbound_guard.py: remove _human_caller_, add caller context
# ===================================================================
og = read("utils/outbound_guard.py")
# Replace _human_caller_ references
og = og.replace('"_human_caller_"', '"__direct_human_reply__"')
og = og.replace("'_human_caller_'", "'__direct_human_reply__'")
# Add caller_id parameter to validate_and_prepare
if "caller_id" not in og:
    og = og.replace(
        "def validate_and_prepare(\n        self,\n        sender_role: str,\n        action_type: ActionType,\n        content: str,\n        interaction_mode: InteractionMode,\n        workflow_id: str | None = None,\n        event_id: str | None = None,\n        llm_mentions: list[str] | None = None,\n    ) -> OutboundResult:",
        "def validate_and_prepare(\n        self,\n        sender_role: str,\n        action_type: ActionType,\n        content: str,\n        interaction_mode: InteractionMode,\n        workflow_id: str | None = None,\n        event_id: str | None = None,\n        llm_mentions: list[str] | None = None,\n        caller_id: str | None = None,\n        caller_handle: str | None = None,\n    ) -> OutboundResult:"
    )
    # In _determine_recipient, replace _human_caller_ with caller_handle
    og = og.replace(
        'return "_human_caller_"',
        'return caller_handle or "__unknown_caller__"'
    )
    og = og.replace(
        "return \"_human_caller_\"",
        "return caller_handle or \"__unknown_caller__\""
    )
    write("utils/outbound_guard.py", og)

# ===================================================================
# 4. Fix adapter.py: mention extraction, action classification, agent ID, observability
# ===================================================================
ad = read("adapter.py")

# Add import for mention extractor
if "from utils.mention_extractor import extract_message_mentions" not in ad:
    ad = ad.replace(
        "from utils.workflow_state import WorkflowStore",
        "from utils.mention_extractor import extract_message_mentions\nfrom utils.workflow_state import WorkflowStore"
    )

# Add band_agent_id parameter to __init__
if "band_agent_id: str = \"\"" not in ad:
    ad = ad.replace(
        "mock_model=None, provider_name: str = \"gemini\", **kwargs):",
        "mock_model=None, provider_name: str = \"gemini\", band_agent_id: str = \"\", **kwargs):"
    )
    ad = ad.replace(
        "self._provider_name = provider_name",
        "self._provider_name = provider_name\n        self._band_agent_id = band_agent_id"
    )

# Fix classification: context-aware action type
old_classify = '''    def _classify_action_type(self) -> ActionType:
        """Determine the action type based on sender role."""
        if self.is_coordinator:
            return ActionType.DISPATCH_AGENT_TASK
        try:
            role = AgentRole(self._agent_role)
        except (ValueError, KeyError):
            return ActionType.REPLY_TO_CALLER
        if role in (AgentRole.RISK_SCORER, AgentRole.AUDIT_LOGGER, AgentRole.REPORT_COMPILER):
            return ActionType.SUBMIT_DOMAIN_RESULT
        return ActionType.REPLY_TO_CALLER'''

new_classify = '''    def _classify_action_type(self, interaction_mode: InteractionMode | None = None,
                              workflow_id: str | None = None) -> ActionType:
        """Determine the action type based on context, not just sender role."""
        if not self.is_coordinator:
            try:
                role = AgentRole(self._agent_role)
            except (ValueError, KeyError):
                return ActionType.REPLY_TO_CALLER
            if role in (AgentRole.RISK_SCORER, AgentRole.AUDIT_LOGGER, AgentRole.REPORT_COMPILER):
                return ActionType.SUBMIT_DOMAIN_RESULT
            return ActionType.REPLY_TO_CALLER

        # Coordinator classification based on interaction mode and workflow state
        if interaction_mode == InteractionMode.CASUAL_CHAT:
            return ActionType.REPLY_TO_CALLER
        if interaction_mode == InteractionMode.CLARIFICATION:
            return ActionType.REQUEST_CLARIFICATION
        if interaction_mode == InteractionMode.DIRECT_DOMAIN_REQUEST:
            return ActionType.REPLY_TO_CALLER

        # Check if terminal or finalizing
        if workflow_id:
            wf = _SHARED_WORKFLOW_STORE.get_workflow(workflow_id)
            if wf:
                from utils.schemas import WorkflowStage
                if wf.current_stage in (WorkflowStage.FINALIZING.value, WorkflowStage.COMPLETED.value):
                    return ActionType.FINAL_NOTIFY_HUMAN

        # Default for coordinated workflow: dispatch next agent
        return ActionType.DISPATCH_AGENT_TASK'''

ad = ad.replace(old_classify, new_classify)

# Fix mention extraction in on_message: use extract_message_mentions
if "mentions_list = getattr(msg, 'mentions', None) or []" in ad:
    ad = ad.replace(
        "mentions_list = getattr(msg, 'mentions', None) or []",
        "mentions_list = extract_message_mentions(msg)"
    )

# Fix _is_self_message to use band_agent_id
if "my_id = getattr(self, '_band_agent_id', None) or os.getenv(\"BAND_AGENT_ID\", \"\")" in ad:
    pass  # Already has it
elif "my_id = getattr(self, '_band_agent_id', None)" not in ad:
    ad = ad.replace(
        "def _is_self_message(self, sender_id: str, sender_name: str) -> bool:",
        "def _is_self_message(self, sender_id: str, sender_name: str) -> bool:\n        # Compare against this agent's own ID\n        my_id = getattr(self, '_band_agent_id', None) or os.getenv(\"BAND_AGENT_ID\", \"\")"
    )

# Add INBOUND/OUTBOUND INFO diagnostics
ad = ad.replace(
    'logger.debug("InboundGuard: %s for %s — %s",',
    'logger.info("INBOUND_IGNORED: %s for %s — %s",'
)
ad = ad.replace(
    'logger.debug("SKIP backlog from %s",',
    'logger.info("INBOUND_SKIP_BACKLOG: from %s",'
)
ad = ad.replace(
    'logger.debug("SELF message from %s — ignoring",',
    'logger.info("INBOUND_SELF_IGNORED: from %s",'
)
ad = ad.replace(
    'logger.debug("SKIP duplicate in room %s (key=%s)",',
    'logger.info("INBOUND_DUPLICATE_SKIP: room %s key=%s",'
)

# Add OUTBOUND_BLOCKED diagnostic in _wrap_send_message
ad = ad.replace(
    'logger.warning(\n                    "OUTBOUND BLOCKED by %s for %s (event=%s): %s",',
    'logger.warning(\n                    "OUTBOUND_BLOCKED: %s for %s event=%s reason=%s",'
)

# Fix self-mention check to not block plain text role names
old_sanitize = '''    def _sanitize_content(self, content: str, sender_role: str) -> str:
        """Remove raw @AgentName from body to prevent accidental activation.

        Rules:
        - Remove @RoleName patterns for known agents
        - Remove @username/slug patterns for known agents
        - Preserve email addresses and legal @ symbols
        - Do NOT blindly strip all @ characters
        """
        result = content

        # Remove @RoleName patterns (e.g., @SecurityReviewer)
        for role in ALL_ROLES:
            pattern = re.compile(rf"@{re.escape(role)}\\b", re.IGNORECASE)
            result = pattern.sub(role, result)

        # Remove @username/slug patterns for known agents
        for role, slug in ROLE_TO_SLUG.items():
            pattern = re.compile(
                rf"@[\\w.-]*/{re.escape(slug)}\\b", re.IGNORECASE
            )
            result = pattern.sub(role, result)

        return result

    def _contains_self_mention(self, content: str, sender_role: str) -> bool:
        """Check if content mentions the sender's own role."""
        # Check for role name in content
        pattern = re.compile(rf"\\b{re.escape(sender_role)}\\b", re.IGNORECASE)
        if pattern.search(content):
            return True

        # Check for slug in content
        slug = ROLE_TO_SLUG.get(sender_role, "")
        if slug:
            slug_pattern = re.compile(rf"[\\w.-]*/{re.escape(slug)}\\b", re.IGNORECASE)
            if slug_pattern.search(content):
                return True

        return False'''

new_sanitize = '''    def _sanitize_content(self, content: str, sender_role: str) -> str:
        """Remove raw @AgentName from body to prevent accidental activation.

        Rules:
        - Remove ONLY @RoleName patterns for known agents (transport mentions)
        - Remove @username/slug patterns for known agents
        - Preserve email addresses and legal @ symbols
        - Do NOT remove plain role names (they are valid text)
        - Do NOT strip all @ characters
        """
        result = content

        # Remove @RoleName patterns (e.g., @SecurityReviewer) — only @-prefixed
        for role in ALL_ROLES:
            pattern = re.compile(rf"@{re.escape(role)}\\b", re.IGNORECASE)
            result = pattern.sub(role, result)

        # Remove @username/slug patterns for known agents
        for role, slug in ROLE_TO_SLUG.items():
            pattern = re.compile(
                rf"@[\\w.-]*/{re.escape(slug)}\\b", re.IGNORECASE
            )
            result = pattern.sub(role, result)

        return result

    def _contains_self_mention(self, content: str, sender_role: str) -> bool:
        \"\"\"Check if content contains an explicit @-mention of the sender's own role.

        Only blocks @RoleName or @username/slug syntax — plain text role names
        in natural language context are NOT considered self-mentions.
        \"\"\"
        # Check for @RoleName pattern (explicit mention syntax)
        at_pattern = re.compile(rf"@{re.escape(sender_role)}\\b", re.IGNORECASE)
        if at_pattern.search(content):
            return True

        # Check for @username/slug pattern
        slug = ROLE_TO_SLUG.get(sender_role, "")
        if slug:
            slug_pattern = re.compile(rf"@[\\w.-]*/{re.escape(slug)}\\b", re.IGNORECASE)
            if slug_pattern.search(content):
                return True

        return False'''

ad = ad.replace(old_sanitize, new_sanitize)
write("adapter.py", ad)

# ===================================================================
# 5. Run band agents: pass band_agent_id to adapter
# ===================================================================
rb = read("run_band_agents.py")
if "band_agent_id" not in rb:
    rb = rb.replace(
        "adapter = VendorVigilPydanticAdapter(",
        "adapter = VendorVigilPydanticAdapter(\n        band_agent_id=agent_id,"
    )
    write("run_band_agents.py", rb)

# ===================================================================
# 6. Inbound guard: add INFO diagnostics
# ===================================================================
ig = read("utils/inbound_guard.py")
# Replace DEBUG logs with INFO for routing decisions
ig = ig.replace(
    'logger.debug("InboundGuard: %s for %s — %s",',
    'logger.info("INBOUND_ACCEPTED: %s for %s — %s",'
)
# Before the first evaluate return that's PROCESS, add an info log
old_evaluate_return = '''        return InboundResult(
            decision=InboundDecision.PROCESS,
            interaction_mode=mode,
            workflow_id=active_wf.workflow_id if active_wf else None,
            reason="Event accepted for processing",
        )'''

new_evaluate_return = '''        logger.info("INBOUND_ACCEPTED: agent=%s mode=%s wf=%s", agent_role, mode.value if mode else "?", active_wf.workflow_id if active_wf else None)
        return InboundResult(
            decision=InboundDecision.PROCESS,
            interaction_mode=mode,
            workflow_id=active_wf.workflow_id if active_wf else None,
            reason="Event accepted for processing",
        )'''

ig = ig.replace(old_evaluate_return, new_evaluate_return)
write("utils/inbound_guard.py", ig)

# ===================================================================
# 7. Fix .env.example - English vars, blank secrets, honest providers
# ===================================================================
env = read(".env.example")
# Replace Indonesian vars
env = env.replace("BAND_KOORDINATOR_VENDOR_ID", "BAND_VENDOR_COORDINATOR_ID")
env = env.replace("BAND_KOORDINATOR_VENDOR_KEY", "BAND_VENDOR_COORDINATOR_KEY")
env = env.replace("BAND_PEMERIKSA_KEAMANAN_ID", "BAND_SECURITY_REVIEWER_ID")
env = env.replace("BAND_PEMERIKSA_KEAMANAN_KEY", "BAND_SECURITY_REVIEWER_KEY")
env = env.replace("BAND_PEMERIKSA_PRIVASI_ID", "BAND_PRIVACY_REVIEWER_ID")
env = env.replace("BAND_PEMERIKSA_PRIVASI_KEY", "BAND_PRIVACY_REVIEWER_KEY")
env = env.replace("BAND_PEMERIKSA_FINANSIAL_ID", "BAND_FINANCIAL_REVIEWER_ID")
env = env.replace("BAND_PEMERIKSA_FINANSIAL_KEY", "BAND_FINANCIAL_REVIEWER_KEY")
env = env.replace("BAND_PENILAI_RISIKO_ID", "BAND_RISK_SCORER_ID")
env = env.replace("BAND_PENILAI_RISIKO_KEY", "BAND_RISK_SCORER_KEY")
env = env.replace("BAND_PENCATAT_AUDIT_ID", "BAND_AUDIT_LOGGER_ID")
env = env.replace("BAND_PENCATAT_AUDIT_KEY", "BAND_AUDIT_LOGGER_KEY")
env = env.replace("BAND_PENYUSUN_LAPORAN_ID", "BAND_REPORT_COMPILER_ID")
env = env.replace("BAND_PENYUSUN_LAPORAN_KEY", "BAND_REPORT_COMPILER_KEY")

# Add separated provider sections
provider_section = """

# ===========================================================================
# HONEST PROVIDER CONFIGURATION
# Each provider has its own KEY and BASE_URL. No aliasing.
# ===========================================================================

# AI/ML API (primary partner)
AIML_API_KEY=
AIML_BASE_URL=https://api.aimlapi.com/v1

# Featherless AI (primary partner)
FEATHERLESS_API_KEY=
FEATHERLESS_BASE_URL=

# Gemini (Google)
GEMINI_API_KEY=
GEMINI_BASE_URL=

# Groq
GROQ_API_KEY=
GROQ_BASE_URL=https://api.groq.com/openai/v1

# OpenRouter
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# DeepSeek (standalone provider)
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=

# DigitalOcean Inference (standalone provider)
DIGITALOCEAN_INFERENCE_API_KEY=
DIGITALOCEAN_INFERENCE_BASE_URL=
"""

if "HONEST PROVIDER CONFIGURATION" not in env:
    env += provider_section

write(".env.example", env)

print("\\nAll fixes applied!")
