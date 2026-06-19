"""
VendorVigil — Auto-Cleanup Utility
===================================
Delegates to CleanupService for all operations.
Supports dry-run, category-specific cleanup, and lifecycle integration.

Usage:
    python -m utils.cleanup                    # Clean everything
    python -m utils.cleanup --dry-run          # Preview what would be deleted
    python -m utils.cleanup --category=app_log # Clean only app logs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.cleanup_service import CleanupService, CleanupCategory


def main():
    parser = argparse.ArgumentParser(description="VendorVigil Cleanup Utility")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be deleted")
    parser.add_argument("--category", type=str, default="",
                        help="Category to clean (default: all)")
    args = parser.parse_args()

    service = CleanupService()
    categories = None
    if args.category:
        try:
            categories = [CleanupCategory(args.category)]
        except ValueError:
            print(f"Unknown category: {args.category}")
            print(f"Available: {[c.value for c in CleanupCategory]}")
            return 1

    report = service.run(dry_run=args.dry_run, categories=categories)

    print(f"VendorVigil Cleanup {'(DRY-RUN)' if args.dry_run else ''}")
    print(f"Project root: {ROOT}")
    print()
    print(report.summary())
    if report.errors:
        print("\nErrors:")
        for err in report.errors:
            print(f"  {err}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
