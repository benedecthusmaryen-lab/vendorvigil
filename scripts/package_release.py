#!/usr/bin/env python3
"""
VendorVigil — Release Package Script
=====================================
Creates a clean release archive from an allowlist.
Excludes .env, .venv, logs, cache, and generated artifacts.
Optionally runs tests and secret scanning before packaging.

Usage:
    python scripts/package_release.py              # Create archive
    python scripts/package_release.py --dry-run     # List files only
    python scripts/package_release.py --run-tests   # Run tests before packaging
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = [
    # Core
    "adapter.py",
    "config.py",
    "prompts.py",
    "run_band_agents.py",
    "run_pipeline.py",
    "requirements.txt",
    # Agents
    "agents/__init__.py",
    "agents/koordinator_vendor.py",
    "agents/pemeriksa_keamanan.py",
    "agents/pemeriksa_privasi.py",
    "agents/pemeriksa_finansial.py",
    "agents/penilai_risiko.py",
    "agents/pencatat_audit.py",
    "agents/penyusun_laporan.py",
    "agents/specs/band_environment.md",
    "agents/specs/communication_policy.md",
    "agents/specs/vendor_coordinator.md",
    "agents/specs/security_reviewer.md",
    "agents/specs/privacy_reviewer.md",
    "agents/specs/financial_reviewer.md",
    "agents/specs/risk_scorer.md",
    "agents/specs/audit_logger.md",
    "agents/specs/report_compiler.md",
    # API
    "api/__init__.py",
    "api/main.py",
    # Config
    "config/model_policy.yaml",
    "config/scoring_rules.yaml",
    # Data
    "data/vendor_scenarios/cloud_pay_x.json",
    "data/vendor_scenarios/safe_docs_id.json",
    "data/vendor_scenarios/quick_lead_pro.json",
    # Utils
    "utils/__init__.py",
    "utils/schemas.py",
    "utils/scoring.py",
    "utils/audit_log.py",
    "utils/handle_resolver.py",
    "utils/action_policy.py",
    "utils/inbound_guard.py",
    "utils/outbound_guard.py",
    "utils/workflow_state.py",
    "utils/live_store.py",
    "utils/result_collector.py",
    "utils/cleanup.py",
    "utils/cleanup_service.py",
    "utils/band_helpers.py",
    "utils/partner_clients.py",
    "utils/provider_preflight.py",
    # Tests
    "tests/test_core.py",
    "tests/test_runtime_enforcement.py",
    "comprehensive_test.py",
    # Docs
    "README.md",
    "docs/architecture.md",
    "docs/demo_script.md",
    "docs/submission_draft.md",
    # Root
    ".env.example",
    ".gitignore",
]

EXCLUDE_PATTERNS = [
    ".env",
    ".venv",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "logs",
    "*.log",
    "*.lock",
    ".coverage",
    "htmlcov",
    ".hypothesis",
    ".tox",
]

KNOWN_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(secret|token|password|credential)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),  # OpenAI-style keys
    re.compile(r"BAND_[A-Z_]+_(KEY|ID|SECRET)\s*=\s*.+"),
]


def run_tests() -> bool:
    """Run the pytest suite before packaging."""
    print("Running tests before packaging...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-x", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("TESTS FAILED:")
        print(result.stdout)
        print(result.stderr)
        return False
    print("Tests passed!")
    return True


def scan_file_for_secrets(filepath: Path) -> list[str]:
    """Scan a file for potential secrets."""
    findings = []
    try:
        content = filepath.read_text(errors="ignore")
        for i, line in enumerate(content.splitlines(), 1):
            for pattern in KNOWN_SECRET_PATTERNS:
                if pattern.search(line) and "example" not in line.lower():
                    findings.append(f"  {filepath.relative_to(ROOT)}:{i}: potential secret detected")
                    break
    except Exception:
        pass
    return findings


def main():
    parser = argparse.ArgumentParser(description="VendorVigil Release Packager")
    parser.add_argument("--dry-run", action="store_true", help="List files without creating archive")
    parser.add_argument("--run-tests", action="store_true", help="Run tests before packaging")
    parser.add_argument("--output", type=str, default="", help="Output archive path")
    args = parser.parse_args()

    if args.run_tests and not run_tests():
        print("ERROR: Tests failed. Aborting packaging.")
        return 1

    # Build file list
    included: list[Path] = []
    for rel_path in ALLOWLIST:
        full_path = ROOT / rel_path
        if full_path.exists():
            included.append(full_path)
        else:
            print(f"WARNING: File not found: {rel_path}")

    # Check for excluded files
    for pattern in [".env", ".venv"]:
        for found in ROOT.rglob(pattern):
            if found.is_file() or found.is_dir():
                print(f"ERROR: {pattern} found in project: {found.relative_to(ROOT)}")
                print("Refusing to package! Remove or .gitignore the file first.")
                return 1

    # Secret scanning
    print("Scanning for potential secrets...")
    secret_findings: list[str] = []
    for f in included:
        secret_findings.extend(scan_file_for_secrets(f))

    if secret_findings:
        print("WARNING: Potential secrets detected in source files:")
        for finding in secret_findings:
            print(finding)
        print("Review and rotate credentials if they were previously in an archive.")

    # Dry run
    if args.dry_run:
        print(f"\nWould include {len(included)} files:")
        for f in sorted(included):
            size = f.stat().st_size if f.is_file() else 0
            print(f"  {f.relative_to(ROOT)} ({size} bytes)")
        return 0

    # Create archive
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = args.output or str(ROOT / f"vendorvigil_release_{timestamp}.tar.gz")
    archive_path = Path(archive_name)

    print(f"Creating archive: {archive_path.name}")
    with tarfile.open(str(archive_path), "w:gz") as tar:
        for f in included:
            tar.add(str(f), arcname=str(f.relative_to(ROOT)))

    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(f"Archive created: {archive_path.name} ({size_mb:.2f} MB)")
    print(f"Files included: {len(included)}")

    if secret_findings:
        print(f"\nWARNING: {len(secret_findings)} potential secrets detected in archive.")
        print("Review and rotate any real credentials.")

    print("\nTo exclude docs and tests for a smaller release, edit ALLOWLIST in this script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
