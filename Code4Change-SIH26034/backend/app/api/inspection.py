"""
api/inspection.py – POST /api/inspect endpoint.

Receives an uploaded product image, runs it through the full
processing pipeline, persists the result and returns JSON.

Pipeline:
  upload → validate → save → preprocess → OCR → compliance
         → DB insert → PDF generation → DB update → response
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.config import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, UPLOAD_DIR
from app.database import get_db, row_to_dict
from app.models.inspection import ErrorResponse, InspectionResult
from app.services.compliance_engine import run_compliance_pipeline
from app.services.image_processor import preprocess_image
from app.services.ocr_service import extract_text
from app.services.report_generator import generate_report

router = APIRouter(prefix="/api", tags=["Inspection"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_upload(file: UploadFile, raw_bytes: bytes) -> None:
    """Raise HTTPException if the upload fails basic validation."""
    # File size
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum allowed size is "
                   f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    # Extension check
    suffix = Path(file.filename or "").suffix.lstrip(".").lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '.{suffix}'. "
                   f"Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )


def _safe_filename(original: str) -> str:
    """Return a collision-safe filename that preserves the extension."""
    suffix = Path(original).suffix.lower() or ".jpg"
    return f"{uuid.uuid4().hex}{suffix}"


# ── POST /api/inspect ─────────────────────────────────────────────────────────

@router.post(
    "/inspect",
    response_model=InspectionResult,
    status_code=status.HTTP_201_CREATED,
    summary="Analyse a packaged commodity image for compliance",
    responses={
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Unsupported media type"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def inspect_product(
    file: UploadFile = File(..., description="Product label image (JPEG/PNG/etc.)")
) -> InspectionResult:
    """
    Upload a product image and receive a compliance analysis.

    **Returns**
    - `inspection_id` – unique database record ID
    - `extracted_text` – raw OCR output from the label
    - `detected_declarations` – identified MRP, quantity, manufacturer, etc.
    - `compliance_score` – 0–100 percentage of required fields found
    - `status` – COMPLIANT or NON_COMPLIANT
    - `violations` – list of missing/invalid declarations

    > **Note:** This is an AI-assisted preliminary check only.
    > It is not a legal compliance certificate.
    """

    # 1. Read raw bytes and validate
    raw_bytes = await file.read()
    _validate_upload(file, raw_bytes)

    # 2. Save uploaded file with a safe name
    safe_name = _safe_filename(file.filename or "upload.jpg")
    image_path = UPLOAD_DIR / safe_name
    try:
        image_path.write_bytes(raw_bytes)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded file: {exc}",
        ) from exc

    timestamp = datetime.now(timezone.utc)

    try:
        # 3. Preprocess image (Phase 4 will apply full OpenCV pipeline)
        processed_path = preprocess_image(image_path)

        # 4. OCR (Phase 5 will call Tesseract / EasyOCR)
        ocr_result = extract_text(processed_path)
        extracted_text = ocr_result["text"]
        ocr_error = ocr_result.get("error")  # may be None

        # 5. Compliance pipeline (Phases 6–7)
        compliance = run_compliance_pipeline(extracted_text)

        # 6. Persist to database first — we need the real inspection_id for the PDF
        with get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO inspections
                    (timestamp, image_path, extracted_text,
                     detected_declarations, declaration_status,
                     compliance_score, status, violations, report_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp.isoformat(),
                    str(image_path),
                    extracted_text,
                    json.dumps(compliance["detected_declarations"]),
                    json.dumps(compliance.get("declaration_status", {})),
                    compliance["compliance_score"],
                    compliance["status"],
                    json.dumps(compliance["violations"]),
                    None,   # report_path updated below after PDF generation
                ),
            )
            inspection_id = cursor.lastrowid

        # 7. Generate PDF report now that we have the real inspection_id (Phase 10)
        report_path_obj = generate_report(
            inspection_id=inspection_id,
            inspection_data={
                "timestamp":   timestamp.isoformat(),
                "image_path":  str(image_path),
                "extracted_text": extracted_text,
                **compliance,
            },
        )
        report_path_str = str(report_path_obj) if report_path_obj else None

        # 8. Update the DB row with the report path (only if PDF was generated)
        if report_path_str:
            with get_db() as conn:
                conn.execute(
                    "UPDATE inspections SET report_path = ? WHERE id = ?",
                    (report_path_str, inspection_id),
                )

        # If OCR failed, surface the error inside violations so the UI can show it
        violations = list(compliance["violations"])
        if ocr_error:
            violations.insert(0, f"OCR notice: {ocr_error}")

        return InspectionResult(
            inspection_id=inspection_id,
            timestamp=timestamp,
            extracted_text=extracted_text,
            detected_declarations=compliance["detected_declarations"],
            declaration_status=compliance.get("declaration_status", {}),
            compliance_score=compliance["compliance_score"],
            status=compliance["status"],
            violations=violations,
            image_filename=safe_name,
            report_path=report_path_str,
        )

    except HTTPException:
        raise
    except Exception as exc:
        # Clean up saved file on unexpected failure to avoid orphaned uploads
        if image_path.exists():
            image_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inspection pipeline error: {exc}",
        ) from exc


# ── GET /api/inspection/{id} ──────────────────────────────────────────────────

@router.get(
    "/inspection/{inspection_id}",
    response_model=InspectionResult,
    summary="Retrieve a single inspection by ID",
    responses={404: {"model": ErrorResponse, "description": "Not found"}},
)
async def get_inspection(inspection_id: int) -> InspectionResult:
    """Return the full details of a previously stored inspection."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM inspections WHERE id = ?", (inspection_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspection {inspection_id} not found.",
        )

    data = row_to_dict(row)
    image_filename = Path(data["image_path"]).name if data.get("image_path") else ""

    return InspectionResult(
        inspection_id=data["id"],
        timestamp=data["timestamp"],
        extracted_text=data["extracted_text"],
        detected_declarations=data["detected_declarations"],
        declaration_status=data.get("declaration_status", {}),
        compliance_score=data["compliance_score"],
        status=data["status"],
        violations=data["violations"],
        image_filename=image_filename,
        report_path=data.get("report_path"),
    )


# ── GET /api/report/{id} ──────────────────────────────────────────────────────

@router.get(
    "/report/{inspection_id}",
    summary="Download the PDF report for an inspection",
    responses={
        404: {"model": ErrorResponse, "description": "Report not found"},
    },
)
async def download_report(inspection_id: int):
    """Stream the PDF report file for download."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT report_path FROM inspections WHERE id = ?", (inspection_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inspection {inspection_id} not found.",
        )

    report_path = row["report_path"]
    if not report_path or not Path(report_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PDF report has not been generated for this inspection yet.",
        )

    return FileResponse(
        path=report_path,
        media_type="application/pdf",
        filename=f"compliance_report_{inspection_id}.pdf",
    )
