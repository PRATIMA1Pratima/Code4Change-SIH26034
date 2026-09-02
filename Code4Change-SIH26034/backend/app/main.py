"""
main.py – FastAPI application entry point.

Creates the app, configures CORS, registers routers, and initialises
the database on startup.  This is the file uvicorn loads.
"""

import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS, DEBUG, PROCESSED_DIR, REPORT_DIR, UPLOAD_DIR
from app.database import get_db, row_to_dict
from app.api.inspection import router as inspection_router
from app.api.history import router as history_router
from app.database import init_db

# Track startup time for the /api/status endpoint
_startup_time: datetime = datetime.now(timezone.utc)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise resources on startup, clean up on shutdown."""
    global _startup_time
    _startup_time = datetime.now(timezone.utc)
    print("[Startup] Initialising database …")
    init_db()
    print("[Startup] Code4Change backend is ready.")
    yield
    print("[Shutdown] Goodbye.")


# ── Application factory ───────────────────────────────────────────────────────

app = FastAPI(
    title="Code4Change – AI-Assisted Packaged Commodity Compliance System",
    description=(
        "Backend API for SIH 2026 Problem Statement SIH26034.\n\n"
        "> **Disclaimer:** All results are AI-assisted preliminary checks "
        "and do not constitute a legal compliance certificate."
    ),
    version="1.0.0",
    debug=DEBUG,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── CORS ──────────────────────────────────────────────────────────────────────
# In DEBUG mode allow every origin so the frontend can be opened directly from
# the filesystem (file://) or any localhost port without configuration friction.
# In production set DEBUG=false and list explicit origins in CORS_ORIGINS.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEBUG else CORS_ORIGINS,
    allow_credentials=False if DEBUG else True,   # credentials + wildcard is invalid
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(inspection_router)
app.include_router(history_router)


# ── Static file mounts (uploads / reports for direct URL access) ──────────────
# These are internal-only convenience mounts for development.
# In production, serve these through a reverse proxy (nginx) instead.

app.mount("/uploads",   StaticFiles(directory=str(UPLOAD_DIR)),    name="uploads")
app.mount("/reports",   StaticFiles(directory=str(REPORT_DIR)),    name="reports")
app.mount("/processed", StaticFiles(directory=str(PROCESSED_DIR)), name="processed")


# ── System endpoints ──────────────────────────────────────────────────────────

@app.get("/health", tags=["System"], summary="API health check")
async def health_check():
    """Minimal liveness probe — returns quickly so the frontend banner works."""
    return {"status": "ok", "service": "Code4Change Backend"}


@app.get("/api/status", tags=["System"], summary="Detailed server status")
async def api_status():
    """
    Returns server metadata consumed by the frontend connection banner.

    Fields:
    - status        : always "ok" when reachable
    - version       : API version string
    - debug         : whether the server is in debug/dev mode
    - python_version: Python interpreter version
    - started_at    : ISO-8601 UTC startup timestamp
    - uptime_seconds: seconds since last startup
    """
    now = datetime.now(timezone.utc)
    uptime = (now - _startup_time).total_seconds()
    return {
        "status":         "ok",
        "version":        "1.0.0",
        "debug":          DEBUG,
        "python_version": sys.version.split()[0],
        "started_at":     _startup_time.isoformat(),
        "uptime_seconds": round(uptime, 1),
    }


@app.get("/", tags=["System"], summary="API root")
async def root():
    return {
        "message": "Code4Change API is running.",
        "docs":    "/docs",
        "health":  "/health",
        "status":  "/api/status",
    }


# ── Debug endpoints (only active when DEBUG=true) ─────────────────────────────

@app.get(
    "/api/debug/preprocess/{inspection_id}",
    tags=["Debug"],
    summary="View preprocessing result for a stored inspection",
)
async def debug_preprocess(inspection_id: int):
    """
    Re-run (or retrieve) the preprocessing output for an existing inspection.

    Returns:
    - ``config``           – current preprocessing tuning parameters
    - ``original_url``     – URL to the original uploaded image
    - ``processed_url``    – URL to the preprocessed PNG (if it exists)
    - ``processed_exists`` – whether the processed file is on disk

    Useful during development to visually compare the original vs.
    preprocessed image and tune the OpenCV parameters.

    Only available when ``DEBUG=true``.
    """
    if not DEBUG:
        raise HTTPException(status_code=403, detail="Debug endpoints are disabled in production.")

    # Look up the inspection record
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, image_path FROM inspections WHERE id = ?",
            (inspection_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Inspection {inspection_id} not found.")

    data       = row_to_dict(row)
    image_path = Path(data["image_path"])

    # Derive the expected processed path
    stem           = image_path.stem
    processed_path = PROCESSED_DIR / f"{stem}_proc.png"

    # If the processed file doesn't exist yet, re-run preprocessing now
    reprocessed = False
    if not processed_path.exists() and image_path.exists():
        try:
            from app.services.image_processor import preprocess_image
            processed_path = preprocess_image(image_path)
            reprocessed    = True
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Preprocessing failed: {exc}"
            ) from exc

    from app.services.image_processor import get_preprocessing_info
    from app.services.ocr_service import get_ocr_info
    from app.services.compliance_engine import get_compliance_rules

    return {
        "inspection_id":    inspection_id,
        "config":           get_preprocessing_info(),
        "ocr":              get_ocr_info(),
        "compliance_rules": get_compliance_rules(),
        "original_file":    image_path.name,
        "original_url":     f"/uploads/{image_path.name}" if image_path.exists() else None,
        "processed_file":   processed_path.name,
        "processed_url":    f"/processed/{processed_path.name}" if processed_path.exists() else None,
        "processed_exists": processed_path.exists(),
        "reprocessed_now":  reprocessed,
    }
