"""
api/history.py – Inspection history endpoints.

GET  /api/history              – paginated, filterable list of past inspections
GET  /api/history/stats        – aggregate counts and average score
DELETE /api/inspection/{id}    – remove a single inspection record
"""

import math
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.database import get_db, row_to_dict
from app.models.inspection import (
    ErrorResponse,
    HistoryResponse,
    HistoryStats,
    InspectionSummary,
)

router = APIRouter(prefix="/api", tags=["History"])


# ── GET /api/history ──────────────────────────────────────────────────────────

@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="List past inspections with optional filter, search, and pagination",
    responses={500: {"model": ErrorResponse, "description": "Database error"}},
)
async def get_history(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Records per page"),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by compliance status: COMPLIANT or NON_COMPLIANT",
    ),
    search: Optional[str] = Query(
        default=None,
        description="Search by image filename (case-insensitive substring match)",
    ),
) -> HistoryResponse:
    """
    Return a paginated list of inspections, newest first.

    **Filtering**
    - `status` – `COMPLIANT` or `NON_COMPLIANT`
    - `search` – substring match against the saved image filename

    **Pagination**
    - `page` (1-based) and `page_size` (max 100)
    - Response includes `total`, `total_pages`, `page`, `page_size`
    """
    offset = (page - 1) * page_size

    # Build WHERE clause dynamically
    conditions: list[str] = []
    params: list = []

    if status_filter and status_filter.upper() in ("COMPLIANT", "NON_COMPLIANT"):
        conditions.append("status = ?")
        params.append(status_filter.upper())

    if search and search.strip():
        conditions.append("image_path LIKE ?")
        params.append(f"%{search.strip()}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        with get_db() as conn:
            # Total matching rows
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM inspections {where}", params
            ).fetchone()
            total: int = total_row["cnt"] if total_row else 0

            # Paginated results
            rows = conn.execute(
                f"""
                SELECT id, timestamp, compliance_score, status, image_path
                FROM inspections
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                params + [page_size, offset],
            ).fetchall()

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {exc}",
        ) from exc

    summaries: list[InspectionSummary] = [
        InspectionSummary(
            inspection_id=dict(row)["id"],
            timestamp=dict(row)["timestamp"],
            compliance_score=dict(row)["compliance_score"],
            status=dict(row)["status"],
            image_filename=Path(dict(row)["image_path"]).name
            if dict(row).get("image_path")
            else "",
        )
        for row in rows
    ]

    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1

    return HistoryResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        inspections=summaries,
    )


# ── GET /api/history/stats ────────────────────────────────────────────────────

@router.get(
    "/history/stats",
    response_model=HistoryStats,
    summary="Aggregate statistics across all inspections",
    responses={500: {"model": ErrorResponse, "description": "Database error"}},
)
async def get_history_stats() -> HistoryStats:
    """
    Return aggregate counts and average compliance score.

    **Response fields**
    - `total`         – total number of inspections stored
    - `compliant`     – how many are COMPLIANT
    - `non_compliant` – how many are NON_COMPLIANT
    - `unknown`       – how many have status UNKNOWN
    - `avg_score`     – mean compliance score across all inspections (0–100)
    """
    try:
        with get_db() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*)                                          AS total,
                    SUM(CASE WHEN status = 'COMPLIANT'     THEN 1 ELSE 0 END) AS compliant,
                    SUM(CASE WHEN status = 'NON_COMPLIANT' THEN 1 ELSE 0 END) AS non_compliant,
                    SUM(CASE WHEN status = 'UNKNOWN'       THEN 1 ELSE 0 END) AS unknown,
                    COALESCE(AVG(compliance_score), 0.0)              AS avg_score
                FROM inspections
                """
            ).fetchone()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {exc}",
        ) from exc

    d = dict(row)
    return HistoryStats(
        total=d["total"] or 0,
        compliant=d["compliant"] or 0,
        non_compliant=d["non_compliant"] or 0,
        unknown=d["unknown"] or 0,
        avg_score=round(d["avg_score"] or 0.0, 2),
    )


# ── DELETE /api/inspection/{id} ───────────────────────────────────────────────

@router.delete(
    "/inspection/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an inspection record",
    responses={
        404: {"model": ErrorResponse, "description": "Inspection not found"},
        500: {"model": ErrorResponse, "description": "Database error"},
    },
)
async def delete_inspection(inspection_id: int) -> None:
    """
    Permanently delete an inspection record and its associated files.

    - Removes the DB row
    - Deletes the uploaded image from `uploads/`
    - Deletes the processed image from `processed/` (if present)
    - Deletes the PDF report from `reports/` (if present)

    Returns **204 No Content** on success.
    """
    # Fetch paths before deleting so we can clean up files
    with get_db() as conn:
        row = conn.execute(
            "SELECT image_path, report_path FROM inspections WHERE id = ?",
            (inspection_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inspection {inspection_id} not found.",
            )

        try:
            conn.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to delete inspection: {exc}",
            ) from exc

    # Best-effort file cleanup — never fail the request if a file is missing
    data = dict(row)

    if data.get("image_path"):
        orig = Path(data["image_path"])
        orig.unlink(missing_ok=True)

        # Delete matching processed image: processed/<stem>_proc.png
        from app.config import PROCESSED_DIR
        proc = PROCESSED_DIR / f"{orig.stem}_proc.png"
        proc.unlink(missing_ok=True)

    if data.get("report_path"):
        Path(data["report_path"]).unlink(missing_ok=True)
