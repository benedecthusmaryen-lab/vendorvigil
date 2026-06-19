"""
VendorVigil — Band Agent Runner
================================
Launches all 7 Remote Agents connected to Band Chat Room via WebSocket.
All configuration, prompts, and adapter logic are in separate modules:
  - config.py   → env vars, providers, model factories
  - prompts.py  → system prompts, agent definitions (AGENT_DEFS)
  - adapter.py  → VendorVigilPydanticAdapter, session management

To switch AI models:  edit .env variables (GEMINI_MODEL_*, FEATHERLESS_*)
To mock (no API):     set USE_MOCK_PROVIDER=true in .env
To change providers:  swap gemini_model() → fl_model() / aiml_model() in prompts.py

Usage:
    python run_band_agents.py
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import signal
import sys
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
load_dotenv(override=True)

# ---
# Logging with rotation
# ---

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"band_agents_{datetime.now():%Y%m%d_%H%M%S}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.TimedRotatingFileHandler(
            LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("vendorvigil.band")
logger.info("Log file: %s", LOG_FILE)

for noisy in ["httpx", "httpcore", "phoenix_channels_python_client",
              "band.client.streaming", "band.platform", "band.runtime.execution",
              "websockets", "langchain_core", "langgraph", "pydantic_ai",
              "openai", "httpcore.http11"]:
    logging.getLogger(noisy).setLevel(logging.WARNING)

# ---
# Imports from modular files
# ---

from config import ROOM_ID, USE_MOCK_PROVIDER, STARTUP_STAGGER, MAX_AGENT_COUNT, MockModel
from prompts import AGENT_DEFS
from adapter import VendorVigilPydanticAdapter

from band import Agent

# ---
# Validate
# ---

if not ROOM_ID:
    logger.error("BAND_ROOM_ID not set in .env!")
    sys.exit(1)


# ---
# Agent Launcher
# ---

async def create_and_start_agent(defn: dict[str, Any], retry_count: int = 0) -> Agent:
    """Create a single agent and connect it to Band, with retry for session conflicts."""
    agent_id = os.getenv(defn["id_env"], "")
    agent_key = os.getenv(defn["key_env"], "")

    if not agent_id or not agent_key:
        raise ValueError(f"Missing {defn['id_env']} or {defn['key_env']}")

    adapter = VendorVigilPydanticAdapter(
        band_agent_id=agent_id,
        model=defn["band_model"],        # Real model object for Band SDK
        custom_section=defn["prompt"],
        is_coordinator=defn.get("is_coordinator", False),
        fallback_model=defn.get("fallback"),
        agent_role=defn.get("agent_role", ""),
        agent_name_label=defn["name"],
        mock_model=defn["llm"] if isinstance(defn["llm"], MockModel) else None,
        provider_name=defn.get("provider_name", "gemini"),
    )

    agent = Agent.create(adapter=adapter, agent_id=agent_id, api_key=agent_key)
    model_label = defn["model_id"].replace("openai:", "")
    mock_tag = " [MOCK]" if isinstance(defn["llm"], MockModel) else ""
    logger.info("[%s] Created (%s)%s — starting...", defn["name"], model_label, mock_tag)

    try:
        await agent.start()
        logger.info("[%s] ONLINE in room %s", defn["name"], ROOM_ID)
        return agent
    except Exception as e:
        err_str = str(e).lower()
        if "session.already_connected" in err_str and retry_count < 3:
            wait = 15 * (retry_count + 1)
            logger.warning("[%s] Session conflict — waiting %ds before retry (%d/3)...",
                          defn["name"], wait, retry_count + 1)
            await asyncio.sleep(wait)
            return await create_and_start_agent(defn, retry_count + 1)
        raise


# ---
# Main
# ---

async def main():
    """Launch all agents."""
    logger.info("=" * 70)
    logger.info("VendorVigil — Band Agent Launcher")
    logger.info("  Mode: %s", "MOCK" if USE_MOCK_PROVIDER else "LIVE")
    logger.info("  Room: %s", ROOM_ID)
    logger.info("=" * 70)

    agents: list[Agent] = []
    selected = AGENT_DEFS if MAX_AGENT_COUNT <= 0 else AGENT_DEFS[:MAX_AGENT_COUNT]
    if MAX_AGENT_COUNT > 0:
        logger.info("Starting %d of %d agents per MAX_AGENT_COUNT", len(selected), len(AGENT_DEFS))

    for defn in selected:
        try:
            agent = await create_and_start_agent(defn)
            agents.append(agent)
            if STARTUP_STAGGER > 0:
                await asyncio.sleep(STARTUP_STAGGER)
        except Exception as e:
            logger.error("FAILED to start %s: %s", defn["name"], e)

    logger.info("\n" + "=" * 70)
    logger.info("ALL %d/%d AGENTS RUNNING", len(agents), len(AGENT_DEFS))
    logger.info("Band Chat: https://app.band.ai/chats/%s", ROOM_ID)
    logger.info("Try: @VendorCoordinator assess vendor CloudPayX")
    logger.info("Ctrl+C to stop")
    logger.info("=" * 70 + "\n")

    # Wait for interrupt
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("\nShutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        for agent in agents:
            try:
                await agent.stop()
            except Exception:
                pass
        logger.info("All agents stopped.")


if __name__ == "__main__":
    asyncio.run(main())
