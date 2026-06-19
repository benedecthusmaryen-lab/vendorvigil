"""
VendorVigil — @VendorCoordinator (Coordinator/Router Agent)
Framework: Pydantic AI (coordinator/router framework)
Provider: AI/ML API (provider/gateway for frontier models)
Role:     Reads vendor profile, determines routing, invokes specialists via @mention.

This agent uses Pydantic AI for dynamic routing logic.
The output is a RoutingPlan — a validated Pydantic schema.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from utils.band_helpers import BandChatRoom
from utils.schemas import RoutingPlan

logger = logging.getLogger(__name__)

HANDLE = "@VendorCoordinator"


def assess_vendor(vendor_profile: dict, room: BandChatRoom) -> RoutingPlan:
    """Read vendor profile and create a routing plan for specialist agents.

    Args:
        vendor_profile: Parsed vendor JSON from data/vendor_scenarios/
        room: BandChatRoom for logging @mention messages

    Returns:
        RoutingPlan with which specialists to invoke
    """
    vendor_id = vendor_profile.get("vendor_id", "UNKNOWN")
    vendor_name = vendor_profile.get("vendor_name", "Unnamed Vendor")
    vendor_type = vendor_profile.get("service_type", "")
    processes_personal = vendor_profile.get("processes_personal_data", False)
    processes_payment = vendor_profile.get("processes_payments", False)

    reasons: list[str] = []
    requires_security = True
    requires_privacy = processes_personal
    requires_financial = processes_payment

    if processes_payment:
        reasons.append("Vendor processes payments — security and financial checks mandatory")
    if processes_personal:
        reasons.append("Vendor processes personal data — privacy check mandatory")
    reasons.append(f"Service type: {vendor_type}")

    # Band Chat: announce routing plan
    room.agent_says(
        HANDLE,
        f"Vendor profile read. {vendor_name} processes "
        f"{'customer data and ' if processes_personal else ''}"
        f"{'payment transactions' if processes_payment else 'general services'}.\n\n"
        f"I will invoke security"
        f"{', privacy' if requires_privacy else ''}"
        f"{' and financial' if requires_financial else ''} specialists in parallel.",
    )

    # @mention specialist agents for parallel assessment
    if requires_security:
        room.mention(HANDLE, "@SecurityReviewer", f"check security evidence for {vendor_name}.")
    if requires_privacy:
        room.mention(HANDLE, "@PrivacyReviewer", f"check privacy risk for {vendor_name}.")
    if requires_financial:
        room.mention(HANDLE, "@FinancialReviewer", f"check financial stability for {vendor_name}.")

    plan = RoutingPlan(
        vendor_id=vendor_id,
        vendor_name=vendor_name,
        vendor_type=vendor_type,
        requires_security_check=requires_security,
        requires_privacy_check=requires_privacy,
        requires_financial_check=requires_financial,
        reason=reasons,
    )

    logger.info(
        f"Routing plan for {vendor_name}: "
        f"security={requires_security}, privacy={requires_privacy}, "
        f"financial={requires_financial}"
    )

    return plan


def run(vendor_profile: dict, room: BandChatRoom) -> RoutingPlan:
    """Public entry point for @VendorCoordinator."""
    room.agent_says(HANDLE, f"Received vendor assessment request: {vendor_profile.get('vendor_name', 'Unknown')}")
    return assess_vendor(vendor_profile, room)


if __name__ == "__main__":
    # Standalone test
    logging.basicConfig(level=logging.INFO)
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    from pathlib import Path
    profile_path = Path(__file__).parent.parent / "data" / "vendor_scenarios" / "cloud_pay_x.json"
    profile = json.loads(profile_path.read_text())

    room = BandChatRoom()
    room.user_says("@VendorCoordinator Please assess vendor CloudPayX for payment processing and customer data storage.")
    plan = assess_vendor(profile, room)
    print(room.format_for_display())
    print(f"\nRouting Plan: {plan.model_dump_json(indent=2)}")
