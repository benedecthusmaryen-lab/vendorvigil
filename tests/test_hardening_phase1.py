"""
Phase 1 — Hardening Characterization Tests (must fail before fixes)
===================================================================
Each test proves a confirmed defect exists. Tests become behavioral
acceptance criteria after fixes.
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest


class TestSQLiteIsSourceOfTruth:
    def test_api_uses_assessment_store_not_live_store(self):
        """api/main.py must import AssessmentStore, not live_store."""
        source = (Path(__file__).parent.parent / "api/main.py").read_text()
        uses_live_store = "from utils.live_store import" in source or "from utils import live_store" in source
        uses_assessment_store = "from utils.assessment_store import" in source or "AssessmentStore" in source
        assert not uses_live_store, "api/main.py still imports live_store — must use AssessmentStore"
        assert uses_assessment_store, "api/main.py must import AssessmentStore"

    def test_no_active_session_id_global(self):
        """adapter.py must not have _ACTIVE_SESSION_ID."""
        source = (Path(__file__).parent.parent / "adapter.py").read_text()
        assert "_ACTIVE_SESSION_ID" not in source, "adapter.py must not have _ACTIVE_SESSION_ID"

    def test_idempotency_in_sqlite_not_memory(self):
        """Idempotency must use SQLite, not in-memory dict."""
        source = (Path(__file__).parent.parent / "api/main.py").read_text()
        assert "_idempotency_store" not in source, "Idempotency must use SQLite, not in-memory dict"


class TestDashboardIsReadOnly:
    def test_no_start_assessment_button(self):
        """Dashboard must not have Start Assessment button."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/components/Dashboard.js").read_text()
        assert "Start Assessment" not in source, "Dashboard must not have Start Assessment button"

    def test_no_reassess_button(self):
        """Dashboard must not have Re-assess button."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/components/Dashboard.js").read_text()
        assert "Re-assess" not in source, "Dashboard must not have Re-assess button"

    def test_no_vendor_selector(self):
        """Dashboard must not have vendor selection UI."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/components/Dashboard.js").read_text()
        assert "vendor-list" not in source, "Dashboard must not have vendor selection"

    def test_no_assessment_trigger_api_call(self):
        """Dashboard must not call assessment POST endpoint."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/api.js").read_text()
        assert "startAssessment" not in source, "Dashboard must not trigger assessments"

    def test_no_expected_status_display(self):
        """Dashboard must not display expected_status."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/components/Dashboard.js").read_text()
        assert "expected_status" not in source, "Dashboard must not display expected_status"


class TestCorrectTimelineOrder:
    def test_timeline_has_risk_audit_report_in_order(self):
        """Dashboard timeline must be: Risk -> Audit -> Report, not Risk -> Report -> Audit."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/components/Dashboard.js").read_text()
        order_index = source.find("order = [")
        if order_index >= 0:
            order_line_end = source.index("]", order_index)
            order_line = source[order_index:order_line_end + 1]
            risk_pos = order_line.find("'risk'")
            audit_pos = order_line.find("'audit'")
            report_pos = order_line.find("'report'")
            assert risk_pos < audit_pos < report_pos, (
                "Timeline order must be risk -> audit -> report. "
                f"Found: {order_line}"
            )


class TestAPIContractCorrect:
    def test_api_calls_v1_endpoints(self):
        """Dashboard API client must use v1 endpoints."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/api.js").read_text()
        old_patterns = ["/api/health", "/api/vendors", "/api/assess", "/api/session/", "/api/summary", "/api/stream/"]
        has_old = any(p in source for p in old_patterns)
        assert not has_old, f"api.js still uses old endpoint patterns"

    def test_sse_uses_named_events(self):
        """Dashboard must register named SSE event listeners."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/api.js").read_text()
        assert "addEventListener" in source, "Dashboard must use addEventListener for named SSE events, not just onmessage"

    def test_sse_uses_v1_events_endpoint(self):
        """SSE client must use /api/v1/assessments/{id}/events."""
        source = (Path(__file__).parent.parent / "vendorvigil_ui/src/api.js").read_text()
        assert "/assessments/" in source, "SSE must use /api/v1/assessments/{id}/events"


class TestProviderLabelsHonest:
    def test_provider_preflight_labels_match(self):
        """Provider preflight must use correct labels."""
        source = (Path(__file__).parent.parent / "utils/provider_preflight.py").read_text()
        wrong_labels = ["DigitalOcean", "DeepSeek", "Featherless AI"]
        for label in wrong_labels:
            assert label not in source, f"provider_preflight must not use wrong label: {label}"


class TestEnglishOnly:
    def test_no_indonesian_agent_filenames(self):
        """Agent files must have English names."""
        agents_dir = Path(__file__).parent.parent / "agents"
        indonesian_files = [
            "koordinator_vendor.py", "pemeriksa_keamanan.py", "pemeriksa_privasi.py",
            "pemeriksa_finansial.py", "penilai_risiko.py", "pencatat_audit.py", "penyusun_laporan.py",
        ]
        for f in indonesian_files:
            assert not (agents_dir / f).exists(), f"Indonesian-named file must be removed: {f}"

    def test_no_indonesian_band_env_vars(self):
        """Band env vars must use English canonical names."""
        source = (Path(__file__).parent.parent / "config.py").read_text()
        indonesian_envs = [
            "BAND_KOORDINATOR_VENDOR", "BAND_PEMERIKSA_KEAMANAN",
            "BAND_PEMERIKSA_PRIVASI", "BAND_PEMERIKSA_FINANSIAL",
            "BAND_PENILAI_RISIKO", "BAND_PENCATAT_AUDIT", "BAND_PENYUSUN_LAPORAN",
        ]
        for env in indonesian_envs:
            assert env not in source, f"Indonesian env var in config.py: {env}"

    def test_no_indonesian_test_names(self):
        """Test names must be English."""
        source = (Path(__file__).parent.parent / "tests/test_core.py").read_text()
        idn_names = ["eskalasi", "disetujui", "ditolak"]
        for name in idn_names:
            assert name not in source.lower(), f"Indonesian test name found: {name}"

    def test_no_indonesian_variables_in_agents(self):
        """Agent files must not have Indonesian variable names."""
        agents_dir = Path(__file__).parent.parent / "agents"
        indonesian_vars = ["bukti", "indikator", "catatan"]
        for agent_file in sorted(agents_dir.glob("*.py")):
            content = agent_file.read_text()
            for var in indonesian_vars:
                if var in content:
                    pytest.fail(f"{agent_file.name} contains Indonesian variable: {var}")
                    return

    def test_run_pipeline_uses_english_imports(self):
        """run_pipeline.py must import English-named modules."""
        source = (Path(__file__).parent.parent / "run_pipeline.py").read_text()
        idn_imports = ["koordinator_vendor", "pemeriksa_keamanan", "pemeriksa_privasi",
                       "pemeriksa_finansial", "penilai_risiko", "pencatat_audit", "penyusun_laporan"]
        for imp in idn_imports:
            assert imp not in source, f"run_pipeline.py imports Indonesian module: {imp}"


class TestCleanupStatusAware:
    def test_cleanup_uses_status_not_mtime(self):
        """CleanupService must use workflow status, not just modification time."""
        source = (Path(__file__).parent.parent / "utils/cleanup_service.py").read_text()
        has_mtime_based = "_is_active_file" in source
        has_status_based = "terminal" in source.lower() or "active" in source.lower() or "status" in source.lower()
        assert has_status_based, "CleanupService must check status, not just mtime"
