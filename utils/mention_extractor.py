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
        elif hasattr(m, 'handle') or hasattr(m, 'username'):
            # Pydantic Mention object
            handle = getattr(m, 'handle', None) or getattr(m, 'username', None) or getattr(m, 'name', None) or getattr(m, 'id', '')
            if handle:
                handles.append(handle)
    return handles
