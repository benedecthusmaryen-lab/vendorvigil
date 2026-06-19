"""
VendorVigil — FastAPI Backend v1
==================================
REST API + SSE streaming for React frontend.
SQLite-backed via AssessmentStore. Read-only for presentation dashboard.
Lifespan uses proper @asynccontextmanager.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from config import VENDOR_SCENARIOS, USE_MOCK_PROVIDER
from utils.assessment_store import AssessmentStore, get_shared_store
from utils.cleanup_service import CleanupService
from adapter import post_to_band_room

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("vendorvigil.api")

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
_cleanup_service = CleanupService()
_assessment_store: AssessmentStore | None = None
_cleanup_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _assessment_store, _cleanup_task
    logger.info("VendorVigil API starting...")
    _assessment_store = await get_shared_store()
    logger.info("SQLite AssessmentStore initialized (shared)")

    cleanup_enabled = os.getenv("CLEANUP_ENABLED", "false").lower() == "true"
    if cleanup_enabled and os.getenv("CLEANUP_ON_STARTUP", "false").lower() == "true":
        try:
            report = _cleanup_service.run(dry_run=False)
            logger.info("Startup cleanup: %s", report.summary())
        except Exception as e:
            logger.warning("Cleanup: %s", e)

    if cleanup_enabled:
        interval = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "60"))

        async def periodic_cleanup():
            while True:
                await asyncio.sleep(interval * 60)
                try:
                    _cleanup_service.run(dry_run=False)
                except Exception:
                    pass

        _cleanup_task = asyncio.create_task(periodic_cleanup())

    yield

    logger.info("Shutting down...")
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    if _assessment_store:
        await _assessment_store.close()


async def get_store() -> AssessmentStore:
    global _assessment_store
    if _assessment_store is None:
        _assessment_store = await get_shared_store()
    return _assessment_store


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="VendorVigil API v1", version="1.0.0", lifespan=lifespan)

_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
_ALLOW_CREDENTIALS = os.getenv("CORS_ALLOW_CREDENTIALS", "false").lower() == "true"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class AssessRequest(BaseModel):
    vendor_name: str = Field(..., description="Vendor name or key")
    vendor_id: str = Field(default="", description="Optional vendor ID")


class AssessResponse(BaseModel):
    assessment_id: str
    workflow_id: str
    vendor: dict[str, str]
    status: str
    status_url: str
    events_url: str
    created_at: str


class ErrorResponse(BaseModel):
    error: dict[str, Any]

    @classmethod
    def create(cls, code: str, message: str, details: dict | None = None, request_id: str = "") -> dict:
        return {"error": {"code": code, "message": message, "details": details or {}, "request_id": request_id}}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _lookup_vendor(name: str) -> tuple[str, dict | None]:
    name_lower = name.lower().strip()
    if name_lower in VENDOR_SCENARIOS:
        return name_lower, VENDOR_SCENARIOS[name_lower]
    for key, data in VENDOR_SCENARIOS.items():
        vn = str(data.get("vendor_name", "")).lower()
        if name_lower == vn or name_lower in vn:
            return key, data
    for key, data in VENDOR_SCENARIOS.items():
        vn = str(data.get("vendor_name", "")).lower()
        if vn in name_lower:
            return key, data
    return name, None


def _public_vendor_data(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "expected_status"}


def _public_assessment(session: dict) -> dict:
    agents = session.get("agents", {})
    agent_statuses = {}
    for role, info in agents.items():
        agent_statuses[role] = {"status": info.get("status", "waiting"), "result": None}
    return {
        "assessment_id": session.get("assessment_id"),
        "workflow_id": session.get("workflow_id", ""),
        "vendor_name": session.get("vendor_name"),
        "vendor_id": session.get("vendor_id"),
        "status": session.get("status"),
        "current_stage": session.get("current_stage", ""),
        "started_at": session.get("started_at"),
        "completed_at": session.get("completed_at"),
        "agent_statuses": agent_statuses,
        "final_result": session.get("final_result"),
        "chat_messages": session.get("chat_messages", []),
    }


def _sse_event(event_type: str, data: dict, event_id: int) -> str:
    lines = []
    if event_type:
        lines.append(f"event: {event_type}")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"data: {json.dumps(data, default=str)}")
    lines.append("")
    return "\n".join(lines)


# ===========================================================================
# HEALTH
# ===========================================================================
@app.get("/api/v1/health/live")
async def health_live():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/health/ready")
async def health_ready():
    issues = []
    if not VENDOR_SCENARIOS:
        issues.append("No vendor data loaded")
    if not USE_MOCK_PROVIDER and not os.getenv("BAND_ROOM_ID", ""):
        issues.append("Band room not configured")
    return {"status": "ok" if not issues else "degraded", "mock_mode": USE_MOCK_PROVIDER,
            "vendors_available": len(VENDOR_SCENARIOS), "issues": issues}


# ===========================================================================
# VENDORS
# ===========================================================================
@app.get("/api/v1/vendors")
async def list_vendors():
    vendors = []
    for key, data in VENDOR_SCENARIOS.items():
        vendors.append(_public_vendor_data({
            "key": key, "vendor_name": data.get("vendor_name", key),
            "vendor_id": data.get("vendor_id", ""), "service_type": data.get("service_type", ""),
            "headquarters": data.get("headquarters", ""), "founded_year": data.get("founded_year", ""),
            "employees": data.get("employees", ""),
        }))
    return {"vendors": vendors}


@app.get("/api/v1/vendors/{vendor_key}")
async def get_vendor(vendor_key: str):
    key, data = _lookup_vendor(vendor_key)
    if data is None:
        raise HTTPException(status_code=404, detail=ErrorResponse.create("VENDOR_NOT_FOUND", f"Vendor '{vendor_key}' not found"))
    return _public_vendor_data(data)


# ===========================================================================
# ASSESSMENTS
# ===========================================================================
@app.post("/api/v1/internal/assessments", status_code=202)
async def trigger_assessment(req: AssessRequest, request: Request):
    """Protected internal endpoint for triggering assessments. Not for dashboard."""
    store = await get_store()
    idempotency_key = request.headers.get("Idempotency-Key", "")
    if idempotency_key:
        existing_id = await store.try_acquire_idempotency_key(idempotency_key)
        if existing_id:
            existing = await store.get_assessment(existing_id)
            if existing:
                return AssessResponse(assessment_id=existing_id, workflow_id=f"wf-{existing_id}",
                    vendor={"vendor_id": existing.get("vendor_id", ""), "vendor_name": existing.get("vendor_name", "")},
                    status=existing.get("status", "running"),
                    status_url=f"/api/v1/assessments/{existing_id}",
                    events_url=f"/api/v1/assessments/{existing_id}/events", created_at=existing.get("started_at", ""))

    vendor_key, vendor_data = _lookup_vendor(req.vendor_name)
    if vendor_data is None:
        raise HTTPException(status_code=404, detail=ErrorResponse.create("VENDOR_NOT_FOUND",
            f"Vendor '{req.vendor_name}' not found. Available: {list(VENDOR_SCENARIOS.keys())}"))
    vname = vendor_data.get("vendor_name", vendor_key)
    vid = req.vendor_id or vendor_data.get("vendor_id", "")
    asmt = await store.create_assessment(vname, vid)
    if idempotency_key:
        await store.save_idempotency_key(idempotency_key, asmt["assessment_id"])
    asyncio.create_task(post_to_band_room(f"@VendorCoordinator assess vendor {vname}"))
    return AssessResponse(assessment_id=asmt["assessment_id"], workflow_id=asmt["workflow_id"],
        vendor={"vendor_id": vid, "vendor_name": vname}, status="queued",
        status_url=f"/api/v1/assessments/{asmt['assessment_id']}",
        events_url=f"/api/v1/assessments/{asmt['assessment_id']}/events", created_at=asmt.get("started_at", ""))


@app.get("/api/v1/assessments")
async def list_assessments(limit: int = Query(default=20, ge=1, le=100),
                           status: str | None = None, vendor: str | None = None):
    store = await get_store()
    all_asmt = await store.list_assessments(limit=limit, status=status)
    items = []
    for a in all_asmt:
        if vendor and vendor.lower() not in a.get("vendor_name", "").lower():
            continue
        items.append({"assessment_id": a.get("assessment_id"), "vendor_name": a.get("vendor_name"),
                       "vendor_id": a.get("vendor_id"), "status": a.get("status"),
                       "started_at": a.get("started_at"), "completed_at": a.get("completed_at")})
    return {"assessments": items, "total": len(items)}


@app.get("/api/v1/assessments/latest")
async def get_latest_assessment():
    store = await get_store()
    a = await store.get_latest_assessment()
    return {"assessment": _public_assessment(a) if a else None}


@app.get("/api/v1/assessments/active")
async def get_active_assessment():
    store = await get_store()
    a = await store.get_active_assessment()
    return {"assessment": _public_assessment(a) if a else None}


@app.get("/api/v1/assessments/{assessment_id}")
async def get_assessment(assessment_id: str):
    store = await get_store()
    a = await store.get_assessment(assessment_id)
    if not a:
        raise HTTPException(status_code=404, detail=ErrorResponse.create("ASSESSMENT_NOT_FOUND", f"Assessment '{assessment_id}' not found"))
    return _public_assessment(a)


# ===========================================================================
# SSE (SQLite-backed)
# ===========================================================================
@app.get("/api/v1/assessments/{assessment_id}/events")
async def stream_assessment_events(assessment_id: str, request: Request):
    last_event_id_str = request.headers.get("Last-Event-ID", "0")
    try:
        last_event_id = int(last_event_id_str)
    except (ValueError, TypeError):
        last_event_id = 0

    async def event_generator():
        nonlocal last_event_id
        store = await get_store()
        last_hb = 0.0

        while True:
            if await request.is_disconnected():
                logger.info("SSE disconnected: %s", assessment_id)
                break

            events = await store.get_events(assessment_id, after_id=last_event_id)
            for ev in events:
                eid = ev["event_id"]
                etype = ev["event_type"]
                data = json.loads(ev["data"]) if isinstance(ev["data"], str) else ev["data"]
                yield _sse_event(etype, data, eid)
                last_event_id = eid

            # Check terminal state
            assessment = await store.get_assessment(assessment_id)
            if assessment and assessment.get("status") in ("completed", "failed"):
                remaining = await store.get_events(assessment_id, after_id=last_event_id)
                for ev in remaining:
                    eid = ev["event_id"]
                    etype = ev["event_type"]
                    data = json.loads(ev["data"]) if isinstance(ev["data"], str) else ev["data"]
                    yield _sse_event(etype, data, eid)
                    last_event_id = eid
                break

            now = __import__("time").time()
            if now - last_hb >= 15:
                yield _sse_event("heartbeat", {"timestamp": datetime.now(timezone.utc).isoformat()}, last_event_id)
                last_hb = now

            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


# ===========================================================================
# DASHBOARD
# ===========================================================================
@app.get("/api/v1/dashboard/summary")
async def dashboard_summary():
    store = await get_store()
    summary = await store.get_dashboard_summary()
    summary["vendor_count"] = len(VENDOR_SCENARIOS)
    summary["mock_mode"] = USE_MOCK_PROVIDER
    return summary


# ===========================================================================
# LEGACY ROUTES (redirect to v1)
# ===========================================================================
@app.get("/api/health")
async def legacy_health():
    return await health_live()


@app.get("/api/vendors")
async def legacy_vendors():
    return await list_vendors()


@app.post("/api/assess")
async def legacy_assess(req: AssessRequest, request: Request):
    return await trigger_assessment(req, request)


# ===========================================================================
# ERROR HANDLERS
# ===========================================================================
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code,
        content=ErrorResponse.create(code=f"HTTP_{exc.status_code}", message=str(exc.detail)))


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc)
    return JSONResponse(status_code=500, content=ErrorResponse.create(code="INTERNAL_ERROR", message="An internal error occurred"))


# Mount React dashboard build as static files (SPA) — MUST be after all route definitions
_BUILD_DIR = Path(__file__).resolve().parent.parent / "vendorvigil_ui" / "build"
if _BUILD_DIR.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_BUILD_DIR), html=True), name="dashboard")
    logger.info("Dashboard static files mounted from %s", _BUILD_DIR)
else:
    logger.warning("Dashboard build not found at %s — run 'npm run build' in vendorvigil_ui/", _BUILD_DIR)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
