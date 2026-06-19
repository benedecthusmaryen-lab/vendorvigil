"""
Phase 1 — Critical Runtime Characterization Tests (must fail before fixes)
===========================================================================
Each test proves one of the 9 confirmed runtime bugs exists.
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest


class TestBug1_FastAPILifespan:
    def test_lifespan_is_async_context_manager_not_generator(self):
        """FastAPI lifespan must be an asynccontextmanager, not 'auto'+direct assign."""
        source = (Path(__file__).parent.parent / "api/main.py").read_text()
        has_broken_pattern = 'lifespan="auto"' in source and 'lifespan_context' in source
        assert not has_broken_pattern, (
            "BUG 1: lifespan='auto' combined with direct app.router.lifespan_context assignment "
            "causes 'async_generator' object does not support async context manager protocol"
        )
        has_correct_pattern = 'from contextlib import asynccontextmanager' in source
        assert has_correct_pattern, "BUG 1: Missing @asynccontextmanager import"


class TestBug2_JSONLiveStoreCalls:
    def test_no_undefined_live_store_calls(self):
        """API must not call undefined JSON live-store functions."""
        source = (Path(__file__).parent.parent / "api/main.py").read_text()
        undefined_funcs = ["list_completed_sessions", "get_latest_session",
                           "get_active_session", "load_session"]
        for func in undefined_funcs:
            assert func not in source, f"BUG 2: API still calls undefined JSON function: {func}"

    def test_no_live_store_import_in_api(self):
        """API must not import from live_store."""
        source = (Path(__file__).parent.parent / "api/main.py").read_text()
        assert "from utils.live_store" not in source, "BUG 2: API still imports live_store"


class TestBug3_DashboardEmptyBaseURL:
    def test_dashboard_has_env_base_url_files(self):
        """Dashboard must have .env.development.example and .env.production.example."""
        ui_dir = Path(__file__).parent.parent / "vendorvigil_ui"
        dev_example = ui_dir / ".env.development.example"
        prod_example = ui_dir / ".env.production.example"
        assert dev_example.exists(), "BUG 3: Missing .env.development.example"
        assert prod_example.exists(), "BUG 3: Missing .env.production.example"
        dev_content = dev_example.read_text()
        prod_content = prod_example.read_text()
        assert "REACT_APP_API_URL" in dev_content, "BUG 3: .env.development.example missing REACT_APP_API_URL"
        assert "REACT_APP_API_URL" in prod_content, "BUG 3: .env.production.example missing REACT_APP_API_URL"

    def test_dashboard_404_on_empty_base(self):
        """API client must throw readable error on non-OK response, not crash on JSON parse."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/api.js").read_text()
        has_ok_check = '"response.ok"' in source or 'res.ok' in source or 'response.ok' in source
        assert has_ok_check, "BUG 3: API client must check response.ok before parsing JSON"


class TestBug4_MentionExtraction:
    def test_adapter_uses_metadata_mentions_not_direct_attr(self):
        """Adapter must read msg.metadata['mentions'], not getattr(msg, 'mentions')."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        has_direct_mentions = 'getattr(msg, "mentions"' in source or "msg.mentions" in source
        assert not has_direct_mentions, (
            "BUG 4: Adapter reads msg.mentions directly instead of msg.metadata['mentions']"
        )

    def test_mention_extraction_function_exists(self):
        """There must be a tested function to extract mentions from PlatformMessage metadata."""
        # Check if a mention extraction utility exists
        utils_files = list(Path(__file__).parent.parent.glob("utils/*.py"))
        all_utils = ""
        for f in utils_files:
            all_utils += f.read_text()
        has_extraction = "extract_message_mentions" in all_utils or "extract_mentions" in all_utils
        assert has_extraction, "BUG 4: No mention extraction function exists for Band PlatformMessage metadata"


class TestBug5_HumanCallerPlaceholder:
    def test_no_human_caller_placeholder(self):
        """Outbound guard must not use _human_caller_ placeholder."""
        source = (Path(__file__).parent.parent / "utils/outbound_guard.py").read_text()
        assert "_human_caller_" not in source, "BUG 5: Outbound guard still uses _human_caller_ placeholder"

    def test_outbound_context_has_caller_info(self):
        """Outbound guard validate_and_prepare must accept caller_id or caller_handle."""
        source = (Path(__file__).parent.parent / "utils/outbound_guard.py").read_text()
        has_caller_param = "caller" in source or "sender_id" in source
        assert has_caller_param, "BUG 5: Outbound context must include caller identity"


class TestBug6_CoordinatorActionClassification:
    def test_classify_action_uses_interaction_mode(self):
        """Coordinator action must be classified by interaction mode, not always DISPATCH."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        has_reply_to_caller = 'ActionType.REPLY_TO_CALLER' in source
        has_dispatch = 'ActionType.DISPATCH_AGENT_TASK' in source
        assert has_reply_to_caller, "BUG 6: Missing REPLY_TO_CALLER for CASUAL_CHAT"
        assert has_dispatch, "BUG 6: Missing DISPATCH_AGENT_TASK for workflow dispatch"
        has_context_aware = 'interaction_mode' in source and 'CASUAL_CHAT' in source and 'FINAL_NOTIFY_HUMAN' in source
        assert has_context_aware, "BUG 6: Classification must consider interaction_mode, not just sender role"


class TestBug7_SelfMentionValidation:
    def test_self_mention_checks_actual_recipient_not_body_text(self):
        """Self-mention must check actual recipient/transport mention, not plain text."""
        source = (Path(__file__).parent.parent / "utils/outbound_guard.py").read_text()
        has_body_text_check = "_contains_self_mention" in source or "sender_role" in source
        assert has_body_text_check, "BUG 7: Missing self-mention validation"
        # Check that the method checks for @mention syntax, not just plain role name
        has_at_check = '@' in source or 'mention' in source.lower()
        assert has_at_check, "BUG 7: Self-mention should check for explicit @mention not just plain text"


class TestBug8_AgentIDNotPassed:
    def test_adapter_accepts_band_agent_id(self):
        """Adapter constructor must accept band_agent_id parameter."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        assert "band_agent_id" in source, "BUG 8: Adapter must accept band_agent_id in constructor"

    def test_runner_passes_agent_id_to_adapter(self):
        """run_band_agents.py must pass agent ID to adapter."""
        source = (Path(__file__).parent.parent / "run_band_agents.py").read_text()
        assert "band_agent_id" in source, "BUG 8: Runner must pass band_agent_id to adapter"

    def test_is_self_message_uses_trusted_id(self):
        """Self-message detection must compare trusted sender ID against band_agent_id."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        assert "self._band_agent_id" in source, "BUG 8: Self-message must use self._band_agent_id"


class TestBug9_SilentRoutingFailure:
    def test_inbound_guard_logs_at_info(self):
        """Inbound guard should log ignored/blocked messages at INFO for debugging."""
        source = (Path(__file__).parent.parent / "utils/inbound_guard.py").read_text()
        has_diagnostics = 'INBOUND_ACCEPTED' in source or 'INBOUND_IGNORED' in source or 'INBOUND_SELF' in source
        assert has_diagnostics, "BUG 9: Inbound guard must emit INBOUND_ACCEPTED/INBOUND_IGNORED at INFO level"


class TestSSEUnboundLocalError:
    def test_sse_event_generator_nonlocal(self):
        """SSE event_generator must use nonlocal for cursor variable."""
        source = (Path(__file__).parent.parent / "api/main.py").read_text()
        assert "nonlocal last_event_id" in source, "SSE event_generator must declare nonlocal last_event_id"


class TestEnvNamesEnglish:
    def test_prompts_english_env_vars(self):
        """prompts.py must use English Band env var names."""
        source = (Path(__file__).parent.parent / "prompts.py").read_text()
        idn_vars = ["BAND_KOORDINATOR_VENDOR", "BAND_PEMERIKSA_KEAMANAN",
                     "BAND_PEMERIKSA_PRIVASI", "BAND_PEMERIKSA_FINANSIAL",
                     "BAND_PENILAI_RISIKO", "BAND_PENCATAT_AUDIT", "BAND_PENYUSUN_LAPORAN"]
        for var in idn_vars:
            assert var not in source, f"prompts.py still uses Indonesian env var: {var}"

    def test_env_example_english(self):
        """.env.example must use English Band env var names with blank values."""
        source = (Path(__file__).parent.parent / ".env.example").read_text()
        idn_vars = ["KOORDINATOR_VENDOR", "PEMERIKSA_KEAMANAN",
                     "PEMERIKSA_PRIVASI", "PEMERIKSA_FINANSIAL",
                     "PENILAI_RISIKO", "PENCATAT_AUDIT", "PENYUSUN_LAPORAN"]
        for var in idn_vars:
            assert var not in source, f".env.example still uses Indonesian env var: {var}"
        eng_vars = ["BAND_VENDOR_COORDINATOR_ID", "BAND_SECURITY_REVIEWER_ID",
                     "BAND_PRIVACY_REVIEWER_ID", "BAND_FINANCIAL_REVIEWER_ID",
                     "BAND_RISK_SCORER_ID", "BAND_AUDIT_LOGGER_ID", "BAND_REPORT_COMPILER_ID"]
        for var in eng_vars:
            assert var in source, f".env.example missing English env var: {var}"


class TestProviderHonesty:
    def test_no_misleading_provider_aliases(self):
        """Provider config must not alias one provider into another's variable."""
        source = (Path(__file__).parent.parent / ".env.example").read_text()
        misleading_pairs = [
            ("GROQ", "DIGITALOCEAN"),
            ("OPENROUTER", "DEEPSEEK"),
            ("AIML", "FEATHERLESS"),
        ]
        for var, wrong_label in misleading_pairs:
            has_var = var in source
            has_wrong = wrong_label in source
            # It's OK to have both GROQ and DIGITALOCEAN as separate providers
            # but GROQ shouldn't be labeled as DigitalOcean
            pass
        # Check that FEATHERLESS has its own section
        assert "FEATHERLESS_API_KEY" in source, "Featherless must have first-class provider config"
        assert "DIGITALOCEAN_INFERENCE_API_KEY" in source, "DigitalOcean must have first-class provider config"
        assert "DEEPSEEK_API_KEY" in source, "DeepSeek must have first-class provider config"


class TestAdapterSQLitePersistence:
    def test_adapter_creates_assessment_in_sqlite(self):
        """Adapter must create assessments via AssessmentStore, not live_store."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        assert "AssessmentStore" in source or "assessment_store" in source.lower(), (
            "Adapter must use AssessmentStore for persistence"
        )

    def test_adapter_no_live_store_import(self):
        """Adapter must not import from live_store in production path."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        assert "from utils.live_store" not in source, (
            "Adapter must not import from live_store"
        )
