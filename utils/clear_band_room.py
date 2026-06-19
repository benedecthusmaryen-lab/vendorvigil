"""
VendorVigil — Band Room History Cleaner
Clears all messages from a Band Chat Room so you can reuse the same
room ID without old conversations interfering with new test runs.

This solves the problem where:
  - A previous test run failed mid-conversation
  - Old messages are still in the room
  - Agents pick up old context and get confused
  - You waste tokens/rate limit waiting for old conversations to finish

Usage:
    python -m utils.clear_band_room              # Clear all messages
    python -m utils.clear_band_room --dry-run    # Preview what would be deleted
    python -m utils.clear_band_room --before 2h  # Delete messages older than 2 hours

Requires: BAND_ROOM_ID and BAND_KOORDINATOR_VENDOR_KEY in .env
"""

from __future__ import annotations

import os
import sys
import time
import argparse
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

try:
    import httpx
except ImportError:
    print("ERROR: httpx not installed. Run: pip install httpx")
    sys.exit(1)


BAND_API_BASE = "https://api.band.ai/v1"


def get_credentials() -> tuple[str, str]:
    """Get room ID and API key from environment."""
    room_id = os.getenv("BAND_ROOM_ID", "")
    api_key = os.getenv("BAND_KOORDINATOR_VENDOR_KEY", "")

    if not room_id:
        print("ERROR: BAND_ROOM_ID not set in .env")
        sys.exit(1)
    if not api_key:
        print("ERROR: BAND_KOORDINATOR_VENDOR_KEY not set in .env")
        sys.exit(1)

    return room_id, api_key


def list_messages(room_id: str, api_key: str, limit: int = 100) -> list[dict]:
    """Fetch messages from the Band room."""
    url = f"{BAND_API_BASE}/rooms/{room_id}/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, headers=headers, params={"limit": limit})
            if resp.status_code == 200:
                data = resp.json()
                messages = data if isinstance(data, list) else data.get("messages", data.get("data", []))
                return messages
            else:
                print(f"ERROR: Failed to list messages (HTTP {resp.status_code})")
                print(f"  Response: {resp.text[:200]}")
                return []
    except Exception as e:
        print(f"ERROR: Could not connect to Band API: {e}")
        return []


def delete_message(room_id: str, message_id: str, api_key: str) -> bool:
    """Delete a single message from the Band room."""
    url = f"{BAND_API_BASE}/rooms/{room_id}/messages/{message_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.delete(url, headers=headers)
            return resp.status_code in (200, 204)
    except Exception:
        return False


def clear_room(before_hours: float | None = None, dry_run: bool = False) -> dict:
    """Clear messages from the Band room.

    Args:
        before_hours: Only delete messages older than this many hours. None = all.
        dry_run: If True, only preview what would be deleted.

    Returns:
        Summary dict with counts.
    """
    room_id, api_key = get_credentials()

    print(f"Band Room Cleaner {'(DRY-RUN)' if dry_run else ''}")
    print(f"Room ID: {room_id}")
    print()

    # Fetch messages
    messages = list_messages(room_id, api_key, limit=200)
    if not messages:
        print("No messages found in room (or API error).")
        return {"total": 0, "deleted": 0, "kept": 0}

    print(f"Found {len(messages)} messages in room")

    # Filter by age if requested
    if before_hours is not None:
        cutoff = time.time() - (before_hours * 3600)
        to_delete = []
        for msg in messages:
            created = msg.get("created_at", "")
            # Try to parse timestamp
            try:
                if isinstance(created, (int, float)):
                    msg_time = created
                else:
                    msg_time = time.time()  # fallback: treat as old
                if msg_time < cutoff:
                    to_delete.append(msg)
            except Exception:
                to_delete.append(msg)
    else:
        to_delete = messages

    kept = len(messages) - len(to_delete)
    print(f"Messages to delete: {len(to_delete)}")
    print(f"Messages to keep: {kept}")
    print()

    if dry_run:
        for msg in to_delete[:10]:
            sender = msg.get("sender_name", msg.get("sender", "?"))
            content = str(msg.get("content", ""))[:60]
            print(f"  [DRY-RUN] Would delete: {sender}: {content}...")
        if len(to_delete) > 10:
            print(f"  ... and {len(to_delete) - 10} more")
        return {"total": len(messages), "deleted": 0, "kept": kept}

    # Delete messages
    deleted = 0
    failed = 0
    for i, msg in enumerate(to_delete):
        msg_id = msg.get("id", msg.get("message_id", ""))
        if not msg_id:
            failed += 1
            continue

        if delete_message(room_id, str(msg_id), api_key):
            deleted += 1
        else:
            failed += 1

        # Progress indicator
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{len(to_delete)} ({deleted} deleted, {failed} failed)")

        # Small delay to avoid rate limiting
        time.sleep(0.1)

    print(f"\nDone: {deleted} deleted, {failed} failed, {kept} kept")
    return {"total": len(messages), "deleted": deleted, "failed": failed, "kept": kept}


def main():
    parser = argparse.ArgumentParser(description="Clear Band Chat Room history")
    parser.add_argument("--dry-run", action="store_true", help="Preview without deleting")
    parser.add_argument("--before", type=str, help="Delete messages older than this (e.g., '2h', '30m', '1d')")
    args = parser.parse_args()

    before_hours = None
    if args.before:
        unit = args.before[-1].lower()
        try:
            value = float(args.before[:-1])
        except ValueError:
            value = float(args.before)
            unit = "h"

        if unit == "m":
            before_hours = value / 60
        elif unit == "h":
            before_hours = value
        elif unit == "d":
            before_hours = value * 24
        else:
            before_hours = value

    clear_room(before_hours=before_hours, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
