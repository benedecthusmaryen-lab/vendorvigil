"""
VendorVigil — Cleanup Service
==============================
Structured cleanup with configurable retention, dry-run support,
path traversal protection, and lifecycle integration.

Usage:
    from utils.cleanup_service import CleanupService, CleanupSettings
    service = CleanupService(settings)
    report = service.run(dry_run=True)
    print(report.summary())
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("vendorvigil.cleanup_service")

# ---
# Settings
# ---

@dataclass
class CleanupSettings:
    """Configuration for cleanup operations."""
    project_root: Path = Path(__file__).resolve().parent.parent

    # Retention by age (days)
    app_log_retention_days: int = 7
    workflow_retention_days: int = 2
    session_retention_days: int = 7
    audit_retention_days: int = 30
    completed_session_retention_days: int = 30

    # Retention by count
    max_app_log_files: int = 10
    max_audit_files: int = 10
    max_completed_sessions: int = 20

    # Whether to skip active/open files
    skip_active_files: bool = True

    # Approved project directories (prevent path traversal)
    approved_subdirs: tuple[str, ...] = (
        "logs",
        "logs/workflows",
        "logs/live",
        "logs/live/completed",
    )


class CleanupCategory(str, Enum):
    """Categories of cleanup targets."""
    APP_LOG = "app_log"
    WORKFLOW = "workflow"
    SESSION = "session"
    COMPLETED_SESSION = "completed_session"
    AUDIT = "audit"
    PYTHON_CACHE = "python_cache"
    TEST_CACHE = "test_cache"
    COVERAGE = "coverage"
    BUILD = "build"


@dataclass
class CleanupCandidate:
    """A file or directory that may be cleaned."""
    path: Path
    category: CleanupCategory
    size_bytes: int = 0
    age_days: float = 0.0
    is_active: bool = False
    reason: str = ""


@dataclass
class CleanupReport:
    """Detailed result of a cleanup operation."""
    matched: int = 0
    would_delete: int = 0
    deleted: int = 0
    failed: int = 0
    kept: int = 0
    skipped_active: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        mode = " (DRY-RUN)" if self.dry_run else ""
        return (
            f"Cleanup{mode}: matched={self.matched}, "
            f"would_delete={self.would_delete}, deleted={self.deleted}, "
            f"failed={self.failed}, kept={self.kept}, "
            f"skipped_active={self.skipped_active}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "would_delete": self.would_delete,
            "deleted": self.deleted,
            "failed": self.failed,
            "kept": self.kept,
            "skipped_active": self.skipped_active,
            "errors": self.errors,
            "dry_run": self.dry_run,
        }


class CleanupService:
    """Structured cleanup with configurable retention policies."""

    def __init__(self, settings: CleanupSettings | None = None) -> None:
        self._settings = settings or CleanupSettings()
        self._root = self._settings.project_root.resolve()

    def _safe_path(self, path: Path) -> Path | None:
        """Resolve a path and ensure it is inside an approved project directory.

        Protects against symlink/path traversal attacks.
        Returns None if the path is unsafe.
        """
        try:
            resolved = path.resolve()
        except (OSError, RuntimeError):
            return None

        # Must be inside project root
        try:
            resolved.relative_to(self._root)
        except ValueError:
            return None

        # Must be in an approved subdirectory (or be a cache dir)
        for sub in self._settings.approved_subdirs:
            approved = (self._root / sub).resolve()
            if str(resolved).startswith(str(approved)):
                return resolved

        # Allow cache/build directories at any level
        cache_names = {"__pycache__", ".pytest_cache", ".mypy_cache",
                        ".ruff_cache", ".coverage", "htmlcov", ".hypothesis",
                        ".tox", "build", "dist"}
        if resolved.name in cache_names or resolved.suffix in (".pyc", ".pyo"):
            return resolved

        return None

    def _is_active_file(self, path: Path) -> bool:
        """Check if a file is likely active/open."""
        if not self._settings.skip_active_files:
            return False
        try:
            # Check if file was modified in the last hour
            age = time.time() - path.stat().st_mtime
            return age < 3600  # 1 hour
        except OSError:
            return True  # Assume active if can't check

    def _find_candidates(
        self,
        directory: str,
        pattern: str,
        category: CleanupCategory,
        retention_days: int | None = None,
        max_files: int | None = None,
        skip_active: bool = True,
    ) -> list[CleanupCandidate]:
        """Find files matching criteria within an approved directory."""
        target = self._root / directory
        if not target.exists():
            return []

        candidates: list[CleanupCandidate] = []
        for f in sorted(target.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
            safe = self._safe_path(f)
            if safe is None:
                continue

            age_days = 0.0
            try:
                age_seconds = time.time() - f.stat().st_mtime
                age_days = age_seconds / 86400.0
            except OSError:
                continue

            is_active = self._is_active_file(f) if skip_active else False

            candidates.append(CleanupCandidate(
                path=f,
                category=category,
                size_bytes=f.stat().st_size if f.is_file() else 0,
                age_days=age_days,
                is_active=is_active,
            ))

        return candidates

    def _select_for_removal(
        self,
        candidates: list[CleanupCandidate],
        retention_days: int | None = None,
        max_files: int | None = None,
    ) -> tuple[list[CleanupCandidate], list[CleanupCandidate]]:
        """Split candidates into keep and remove lists.

        Rules:
        1. Active files are always kept (if skip_active is True).
        2. Files newer than retention_days are kept.
        3. If max_files is set, the oldest beyond max_files are removed.
        """
        keep: list[CleanupCandidate] = []
        remove: list[CleanupCandidate] = []

        now = datetime.now(timezone.utc)

        for i, c in enumerate(candidates):
            # Rule 1: Active files are always kept
            if c.is_active:
                keep.append(c)
                continue

            # Rule 2: Age-based retention
            if retention_days is not None and c.age_days < retention_days:
                keep.append(c)
                continue

            # Rule 3: Count-based retention (newest files)
            if max_files is not None and i < max_files:
                keep.append(c)
                continue

            remove.append(c)

        return keep, remove

    def _delete_candidate(self, candidate: CleanupCandidate) -> bool:
        """Delete a single candidate (file or directory)."""
        try:
            path = candidate.path
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=False)
            else:
                path.unlink()
            return True
        except Exception as e:
            logger.error("Failed to delete %s: %s", candidate.path, e)
            return False

    def run(
        self,
        dry_run: bool = False,
        categories: list[CleanupCategory] | None = None,
    ) -> CleanupReport:
        """Run cleanup for specified categories (or all if none specified).

        Args:
            dry_run: If True, only report what would be deleted.
            categories: Subset of categories to clean. None = all.

        Returns:
            CleanupReport with detailed results.
        """
        report = CleanupReport(dry_run=dry_run)
        all_categories = list(CleanupCategory)

        for cat in (categories or all_categories):
            handler = self._get_handler(cat)
            if handler:
                try:
                    handler(report)
                except Exception as e:
                    report.errors.append(f"{cat.value}: {e}")
                    report.failed += 1

        return report

    def _get_handler(self, category: CleanupCategory):
        """Return the handler method for a category."""
        handlers = {
            CleanupCategory.APP_LOG: self._clean_app_logs,
            CleanupCategory.WORKFLOW: self._clean_workflows,
            CleanupCategory.SESSION: self._clean_sessions,
            CleanupCategory.COMPLETED_SESSION: self._clean_completed_sessions,
            CleanupCategory.AUDIT: self._clean_audit,
            CleanupCategory.PYTHON_CACHE: self._clean_python_cache,
            CleanupCategory.TEST_CACHE: self._clean_test_caches,
            CleanupCategory.COVERAGE: self._clean_coverage,
            CleanupCategory.BUILD: self._clean_build,
        }
        return handlers.get(category)

    def _clean_app_logs(self, report: CleanupReport) -> None:
        """Clean application log files (band_agents_*.log)."""
        candidates = self._find_candidates(
            "logs", "band_agents_*.log",
            CleanupCategory.APP_LOG,
            retention_days=self._settings.app_log_retention_days,
            max_files=self._settings.max_app_log_files,
        )
        keep, remove = self._select_for_removal(
            candidates,
            retention_days=self._settings.app_log_retention_days,
            max_files=self._settings.max_app_log_files,
        )
        report.matched += len(candidates)
        report.kept += len(keep)
        report.skipped_active += sum(1 for c in keep if c.is_active)
        report.would_delete += len(remove)

        if not dry_run_guard(report):
            for c in remove:
                if self._delete_candidate(c):
                    report.deleted += 1
                else:
                    report.failed += 1

    def _clean_workflows(self, report: CleanupReport) -> None:
        """Clean terminal workflow state files, retaining active ones."""
        candidates = self._find_candidates(
            "logs/workflows", "wf-*.json",
            CleanupCategory.WORKFLOW,
            retention_days=self._settings.workflow_retention_days,
        )
        # For workflows, we only remove non-active (terminal) files by age
        keep, remove = self._select_for_removal(
            candidates,
            retention_days=self._settings.workflow_retention_days,
            max_files=None,  # No count limit, use age only
        )
        report.matched += len(candidates)
        report.kept += len(keep)
        report.skipped_active += sum(1 for c in keep if c.is_active)
        report.would_delete += len(remove)

        if not dry_run_guard(report):
            for c in remove:
                if self._delete_candidate(c):
                    report.deleted += 1
                else:
                    report.failed += 1

    def _clean_sessions(self, report: CleanupReport) -> None:
        """Clean active session files (retention by age)."""
        candidates = self._find_candidates(
            "logs/live", "session_*.json",
            CleanupCategory.SESSION,
            retention_days=self._settings.session_retention_days,
        )
        keep, remove = self._select_for_removal(
            candidates,
            retention_days=self._settings.session_retention_days,
            max_files=None,
        )
        report.matched += len(candidates)
        report.kept += len(keep)
        report.skipped_active += sum(1 for c in keep if c.is_active)
        report.would_delete += len(remove)

        if not dry_run_guard(report):
            for c in remove:
                if self._delete_candidate(c):
                    report.deleted += 1
                else:
                    report.failed += 1

    def _clean_completed_sessions(self, report: CleanupReport) -> None:
        """Clean archived completed sessions."""
        candidates = self._find_candidates(
            "logs/live/completed", "*.json",
            CleanupCategory.COMPLETED_SESSION,
            retention_days=self._settings.completed_session_retention_days,
            max_files=self._settings.max_completed_sessions,
        )
        keep, remove = self._select_for_removal(
            candidates,
            retention_days=self._settings.completed_session_retention_days,
            max_files=self._settings.max_completed_sessions,
        )
        report.matched += len(candidates)
        report.kept += len(keep)
        report.would_delete += len(remove)

        if not dry_run_guard(report):
            for c in remove:
                if self._delete_candidate(c):
                    report.deleted += 1
                else:
                    report.failed += 1

    def _clean_audit(self, report: CleanupReport) -> None:
        """Clean audit record files (separate retention from app logs)."""
        candidates = self._find_candidates(
            "logs", "VV-*.json",
            CleanupCategory.AUDIT,
            retention_days=self._settings.audit_retention_days,
            max_files=self._settings.max_audit_files,
        )
        keep, remove = self._select_for_removal(
            candidates,
            retention_days=self._settings.audit_retention_days,
            max_files=self._settings.max_audit_files,
        )
        report.matched += len(candidates)
        report.kept += len(keep)
        report.would_delete += len(remove)

        if not dry_run_guard(report):
            for c in remove:
                if self._delete_candidate(c):
                    report.deleted += 1
                else:
                    report.failed += 1

    def _clean_python_cache(self, report: CleanupReport) -> None:
        """Clean __pycache__ directories and .pyc/.pyo files."""
        count = 0
        for pycache in self._root.rglob("__pycache__"):
            if ".venv" in str(pycache):
                continue
            safe = self._safe_path(pycache)
            if safe is None:
                continue
            report.matched += 1
            report.would_delete += 1
            count += 1
            if not dry_run_guard(report):
                try:
                    shutil.rmtree(safe, ignore_errors=True)
                    report.deleted += 1
                except Exception:
                    report.failed += 1

    def _clean_test_caches(self, report: CleanupReport) -> None:
        """Clean .pytest_cache, .mypy_cache, .ruff_cache, .hypothesis."""
        cache_dirs = [".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"]
        for name in cache_dirs:
            target = self._root / name
            if target.exists():
                safe = self._safe_path(target)
                if safe is None:
                    continue
                report.matched += 1
                report.would_delete += 1
                if not dry_run_guard(report):
                    try:
                        shutil.rmtree(safe, ignore_errors=True)
                        report.deleted += 1
                    except Exception:
                        report.failed += 1

    def _clean_coverage(self, report: CleanupReport) -> None:
        """Clean .coverage and htmlcov/."""
        targets = [self._root / ".coverage", self._root / "htmlcov"]
        for target in targets:
            if target.exists():
                safe = self._safe_path(target)
                if safe is None:
                    continue
                report.matched += 1
                report.would_delete += 1
                if not dry_run_guard(report):
                    try:
                        if target.is_dir():
                            shutil.rmtree(safe, ignore_errors=True)
                        else:
                            target.unlink()
                        report.deleted += 1
                    except Exception:
                        report.failed += 1

    def _clean_build(self, report: CleanupReport) -> None:
        """Clean build/, dist/, *.egg-info/."""
        for pattern in ["build", "dist", "*.egg-info"]:
            for item in self._root.glob(pattern):
                safe = self._safe_path(item)
                if safe is None:
                    continue
                report.matched += 1
                report.would_delete += 1
                if not dry_run_guard(report):
                    try:
                        if item.is_dir():
                            shutil.rmtree(safe, ignore_errors=True)
                        else:
                            item.unlink()
                        report.deleted += 1
                    except Exception:
                        report.failed += 1


def dry_run_guard(report: CleanupReport) -> bool:
    """Return True if this is a dry run (skip actual deletion)."""
    return report.dry_run
