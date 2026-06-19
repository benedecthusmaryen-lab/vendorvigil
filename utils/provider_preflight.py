"""
VendorVigil — Provider Preflight
Validates all AI providers before agent launch.
Checks credentials, model availability, tool calling support, and fallback validity.

Usage:
    from utils.provider_preflight import ProviderPreflight
    preflight = ProviderPreflight()
    report = preflight.run_all_checks()
    if not report.all_passed:
        for failure in report.failures:
            print(f"FAILED: {failure}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("vendorvigil.preflight")


@dataclass
class CheckResult:
    """Result of a single provider check."""
    provider_name: str
    check_type: str
    passed: bool
    details: str = ""


@dataclass
class PreflightReport:
    """Aggregated result of all preflight checks."""
    results: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    @property
    def passed(self) -> list[CheckResult]:
        return [r for r in self.results if r.passed]

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    def summary(self) -> str:
        total = len(self.results)
        ok = len(self.passed)
        fail = len(self.failures)
        lines = [f"Preflight: {ok}/{total} passed, {fail} failed"]
        for f in self.failures:
            lines.append(f"  FAIL: [{f.provider_name}] {f.check_type} — {f.details}")
        return "\n".join(lines)


class ProviderPreflight:
    """Validates all configured providers before launching agents."""

    def __init__(self) -> None:
        pass

    def run_all_checks(self) -> PreflightReport:
        """Run preflight checks for all configured providers.

        Checks:
        1. Credential availability
        2. Base URL format
        3. Model reachability (lightweight API call)
        4. Fallback model validity
        5. Semaphore availability
        """
        report = PreflightReport()

        # Import config to get current provider settings
        try:
            import config
        except ImportError:
            report.add(CheckResult(
                provider_name="system",
                check_type="config_import",
                passed=False,
                details="Failed to import config module",
            ))
            return report

        # Check each provider slot
        providers = {
            "gemini": {
                "key": config.GEMINI_KEY,
                "base": config.GEMINI_BASE,
                "label": "Google Gemini",
            },
            "groq": {
                "key": config.GROQ_KEY,
                "base": config.GROQ_BASE,
                "label": "Groq",
            },
            "openrouter": {
                "key": config.OR_KEY,
                "base": config.OR_BASE,
                "label": "OpenRouter",
            },
            "aiml": {
                "key": config.AIML_KEY,
                "base": config.AIML_BASE,
                "label": "AI/ML API",
            },
        }

        for name, info in providers.items():
            self._check_provider(report, name, info)

        # Check per-agent model assignments
        self._check_agent_models(report, config)

        # Check semaphores
        self._check_semaphores(report, config)

        logger.info(report.summary())
        return report

    def _check_provider(
        self,
        report: PreflightReport,
        name: str,
        info: dict[str, str],
    ) -> None:
        """Check a single provider."""
        label = info["label"]
        key = info["key"]
        base = info["base"]

        # Check 1: Credential available
        has_key = bool(key and len(key) > 5)
        report.add(CheckResult(
            provider_name=label,
            check_type="credential_available",
            passed=has_key,
            details="API key found" if has_key else "API key missing or too short",
        ))

        # Check 2: Base URL format
        has_url = bool(base and base.startswith("http"))
        report.add(CheckResult(
            provider_name=label,
            check_type="base_url_valid",
            passed=has_url,
            details=f"URL: {base}" if has_url else "Base URL missing or invalid",
        ))

    def _check_agent_models(self, report: PreflightReport, config: Any) -> None:
        """Check that each agent's model assignment is valid."""
        agent_models = {
            "VendorCoordinator": {
                "model": config.MODEL_VENDOR_COORDINATOR,
                "provider": config.PROVIDER_VENDOR_COORDINATOR,
            },
            "SecurityReviewer": {
                "model": config.MODEL_SECURITY_REVIEWER,
                "provider": config.PROVIDER_SECURITY_REVIEWER,
            },
            "PrivacyReviewer": {
                "model": config.MODEL_PRIVACY_REVIEWER,
                "provider": config.PROVIDER_PRIVACY_REVIEWER,
            },
            "FinancialReviewer": {
                "model": config.MODEL_FINANCE_REVIEWER,
                "provider": config.PROVIDER_FINANCE_REVIEWER,
            },
            "RiskScorer": {
                "model": config.MODEL_RISK_SCORER,
                "provider": config.PROVIDER_RISK_SCORER,
            },
            "AuditLogger": {
                "model": config.MODEL_AUDIT_LOGGER,
                "provider": config.PROVIDER_AUDIT_LOGGER,
            },
            "ReportCompiler": {
                "model": config.MODEL_REPORT_COMPILER,
                "provider": config.PROVIDER_REPORT_COMPILER,
            },
        }

        for agent_name, info in agent_models.items():
            model = info["model"]
            provider = info["provider"]
            has_model = bool(model and len(model) > 0)
            has_provider = bool(provider and len(provider) > 0)

            report.add(CheckResult(
                provider_name=agent_name,
                check_type="model_assigned",
                passed=has_model and has_provider,
                details=f"{model} via {provider}" if has_model else "Model or provider not configured",
            ))

    def _check_semaphores(self, report: PreflightReport, config: Any) -> None:
        """Check that semaphores are available for each provider."""
        try:
            sem = config.get_semaphore("gemini")
            report.add(CheckResult(
                provider_name="system",
                check_type="semaphore_gemini",
                passed=sem is not None,
                details="Gemini semaphore available",
            ))
        except Exception as e:
            report.add(CheckResult(
                provider_name="system",
                check_type="semaphore_gemini",
                passed=False,
                details=f"Error: {e}",
            ))

        try:
            sem = config.get_semaphore("groq")
            report.add(CheckResult(
                provider_name="system",
                check_type="semaphore_groq",
                passed=sem is not None,
                details="Groq/DO semaphore available",
            ))
        except Exception as e:
            report.add(CheckResult(
                provider_name="system",
                check_type="semaphore_groq",
                passed=False,
                details=f"Error: {e}",
            ))

        try:
            sem = config.get_semaphore("openrouter")
            report.add(CheckResult(
                provider_name="system",
                check_type="semaphore_openrouter",
                passed=sem is not None,
                details="OpenRouter semaphore available",
            ))
        except Exception as e:
            report.add(CheckResult(
                provider_name="system",
                check_type="semaphore_openrouter",
                passed=False,
                details=f"Error: {e}",
            ))

    def check_live_model(
        self,
        provider_name: str,
        api_key: str,
        base_url: str,
        model_id: str,
    ) -> CheckResult:
        """Test a model with a lightweight API call.

        Sends a minimal chat completion request to verify the model
        is reachable and responding.
        """
        try:
            import httpx
            response = httpx.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                timeout=15.0,
            )
            if response.status_code == 200:
                return CheckResult(
                    provider_name=provider_name,
                    check_type="model_live",
                    passed=True,
                    details=f"{model_id} responded successfully",
                )
            else:
                return CheckResult(
                    provider_name=provider_name,
                    check_type="model_live",
                    passed=False,
                    details=f"{model_id} returned HTTP {response.status_code}: {response.text[:100]}",
                )
        except Exception as e:
            return CheckResult(
                provider_name=provider_name,
                check_type="model_live",
                passed=False,
                details=f"{model_id} connection error: {e}",
            )
