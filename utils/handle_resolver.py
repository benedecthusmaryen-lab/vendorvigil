"""
VendorVigil — Handle Resolver
Maps logical agent role names to exact Band transport handles.
LLM never constructs or guesses handles; runtime resolves them.

Usage:
    from utils.handle_resolver import HandleResolver
    resolver = HandleResolver.from_band_participants(participants_msg)
    handle = resolver.resolve("SecurityReviewer")
"""

from __future__ import annotations

import logging
import re
from typing import Any

from utils.schemas import AgentRole

logger = logging.getLogger("vendorvigil.handle_resolver")

# Maps AgentRole values to agent slug patterns found in Band handles.
# Band handles are formatted as: username/agent-slug
# The slug (after /) is what we match against.
ROLE_TO_SLUG: dict[str, str] = {
    AgentRole.VENDOR_COORDINATOR.value: "vendor-coordinator",
    AgentRole.SECURITY_REVIEWER.value: "security-reviewer",
    AgentRole.PRIVACY_REVIEWER.value: "privacy-reviewer",
    AgentRole.FINANCIAL_REVIEWER.value: "financial-reviewer",
    AgentRole.RISK_SCORER.value: "risk-scorer",
    AgentRole.AUDIT_LOGGER.value: "audit-logger",
    AgentRole.REPORT_COMPILER.value: "report-compiler",
}

# Reverse mapping: slug -> logical role
SLUG_TO_ROLE: dict[str, str] = {v: k for k, v in ROLE_TO_SLUG.items()}

# All known logical roles
ALL_ROLES: set[str] = set(ROLE_TO_SLUG.keys())

# Roles that are specialists (non-coordinator)
SPECIALIST_ROLES: set[str] = ALL_ROLES - {AgentRole.VENDOR_COORDINATOR.value}

# Coordinator role constant
COORDINATOR_ROLE: str = AgentRole.VENDOR_COORDINATOR.value


class HandleResolver:
    """Resolves logical agent roles to Band transport handles."""

    def __init__(self, participant_registry: dict[str, str]) -> None:
        """Initialize with a mapping of logical_role -> exact_band_handle.

        Args:
            participant_registry: Maps logical role names to full Band handles.
                e.g. {"SecurityReviewer": "benedecthusmaryen/security-reviewer"}
        """
        self._registry: dict[str, str] = dict(participant_registry)
        self._reverse: dict[str, str] = {v: k for k, v in self._registry.items()}

    @classmethod
    def from_band_participants(cls, participants_msg: str | None) -> HandleResolver:
        """Parse Band participant list to build registry.

        Band provides participant info as a formatted string with lines like:
            @username/agent-slug (Display Name)
        or structured data. This parser handles both formats.

        Args:
            participants_msg: Raw participant metadata from Band SDK.
        """
        registry: dict[str, str] = {}

        if not participants_msg:
            logger.warning("No participants message provided; using empty registry")
            return cls(registry)

        # Try to extract handle patterns from the participants text
        # Pattern: @username/slug or username/slug
        handle_pattern = re.compile(
            r"@?([\w.-]+)/([\w-]+)"
        )

        for match in handle_pattern.finditer(participants_msg):
            full_handle = f"{match.group(1)}/{match.group(2)}"
            slug = match.group(2)

            # Map slug to logical role
            role = SLUG_TO_ROLE.get(slug)
            if role and role not in registry:
                registry[role] = full_handle
                logger.info("Registered handle: %s -> %s", role, full_handle)

        # Log any unmapped roles
        for role in ALL_ROLES:
            if role not in registry:
                logger.warning("No Band handle found for role: %s", role)

        return cls(registry)

    @classmethod
    def from_config(cls) -> HandleResolver:
        """Create resolver from environment/config (for testing without Band).

        Uses placeholder handles that can be overridden.
        """
        registry = {
            role: f"test-user/{slug}"
            for role, slug in ROLE_TO_SLUG.items()
        }
        return cls(registry)

    def resolve(self, logical_role: str) -> str | None:
        """Get exact transport handle for a logical role.

        Args:
            logical_role: The logical role name (e.g. "SecurityReviewer").

        Returns:
            The exact Band handle string, or None if not registered.
        """
        return self._registry.get(logical_role)

    def resolve_or_warn(self, logical_role: str) -> str | None:
        """Get handle with logging if not found."""
        handle = self.resolve(logical_role)
        if handle is None:
            logger.warning("Cannot resolve handle for role: %s", logical_role)
        return handle

    def resolve_human(self, human_requester_handle: str) -> str:
        """Get transport handle for human requester.

        For humans, the handle is typically the display name or user ID
        passed through from the workflow state.
        """
        return human_requester_handle

    def is_known_agent(self, handle: str) -> bool:
        """Check if a handle belongs to a known agent.

        Args:
            handle: A Band transport handle (e.g. "user/security-reviewer").
        """
        return handle in self._reverse

    def get_role_from_handle(self, handle: str) -> str | None:
        """Reverse lookup: transport handle to logical role.

        Args:
            handle: A Band transport handle.

        Returns:
            The logical role name, or None if not a known agent handle.
        """
        return self._reverse.get(handle)

    def get_role_from_sender(self, sender_name: str) -> str | None:
        """Determine the logical role from a sender display name.

        Handles:
        - "vendor-coordinator" / "vendor_coordinator" (slug with hyphen or underscore)
        - "user/vendor-coordinator" (full handle)
        - "VendorCoordinator" (logical name)
        - "@VendorCoordinator" (with @ prefix)
        """
        if not sender_name:
            return None

        # Strip @ prefix
        name = sender_name.lstrip("@").strip()

        # Check logical role name (exact match)
        if name in ALL_ROLES:
            return name

        # Check if full handle (username/slug)
        if "/" in name:
            slug = name.split("/", 1)[1]
            role = SLUG_TO_ROLE.get(slug)
            if role:
                return role

        # Check slug (hyphen version)
        role = SLUG_TO_ROLE.get(name)
        if role:
            return role

        # Check slug with underscore→hyphen conversion (Band uses display names
        # like "security_reviewer" but our slugs use "security-reviewer")
        name_hyphen = name.replace("_", "-")
        role = SLUG_TO_ROLE.get(name_hyphen)
        if role:
            return role

        # Check case-insensitive logical name match
        for role in ALL_ROLES:
            if name.lower() == role.lower():
                return role

        return None

    def is_human_sender(self, sender_name: str) -> bool:
        """Check if a sender is a human (not a known agent)."""
        return self.get_role_from_sender(sender_name) is None

    def get_all_handles(self) -> dict[str, str]:
        """Return the full registry (logical_role -> handle)."""
        return dict(self._registry)

    def get_agent_handles(self) -> list[str]:
        """Return all registered agent handles."""
        return list(self._registry.values())
