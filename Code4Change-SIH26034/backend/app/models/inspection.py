"""
models/inspection.py – Pydantic schemas for the Inspection domain.

These are the data-transfer objects (DTOs) used by the API layer.
They are NOT database models; the database layer uses raw sqlite3.

Separating the two keeps the door open for swapping SQLite for any
other database without touching the API contracts.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    UNKNOWN = "UNKNOWN"


# ── Response schemas ──────────────────────────────────────────────────────────

class InspectionResult(BaseModel):
    """Full result returned by POST /api/inspect."""

    inspection_id: int = Field(..., description="Auto-assigned database ID")
    timestamp: datetime = Field(..., description="UTC time of inspection")

    # OCR output
    extracted_text: str = Field(
        default="",
        description="Raw text extracted from the product label"
    )

    # Declaration detection
    detected_declarations: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Key = declaration name (e.g. 'mrp'), "
            "Value = extracted value or null if not found"
        )
    )

    # Per-field compliance status (Phase 7)
    # Key = declaration key, Value = {found, valid, severity, value, message}
    declaration_status: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-field compliance detail: found (bool), valid (bool), "
            "severity (ERROR|WARNING), value (str|null), message (str|null)"
        )
    )

    # Compliance
    compliance_score: float = Field(
        ...,
        ge=0.0, le=100.0,
        description="Percentage of required declarations found (0–100)"
    )
    status: ComplianceStatus = Field(
        ..., description="COMPLIANT / NON_COMPLIANT / UNKNOWN"
    )
    violations: list[str] = Field(
        default_factory=list,
        description="List of missing or invalid declaration descriptions"
    )

    # File paths (relative, not exposed as absolute filesystem paths)
    image_filename: str = Field(
        default="",
        description="Saved filename of the uploaded image"
    )
    report_path: str | None = Field(
        default=None,
        description="Relative path to the generated PDF report, if available"
    )

    class Config:
        use_enum_values = True


class InspectionSummary(BaseModel):
    """Lightweight record used in the history list."""

    inspection_id: int
    timestamp: datetime
    compliance_score: float
    status: ComplianceStatus
    image_filename: str

    class Config:
        use_enum_values = True


class HistoryResponse(BaseModel):
    """Response body for GET /api/history — includes pagination metadata."""

    total: int = Field(..., description="Total number of matching inspections")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Records per page")
    total_pages: int = Field(..., description="Total number of pages")
    inspections: list[InspectionSummary]


class HistoryStats(BaseModel):
    """Response body for GET /api/history/stats."""

    total: int
    compliant: int
    non_compliant: int
    unknown: int
    avg_score: float = Field(..., description="Average compliance score across all inspections")


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    detail: str
    code: str = "ERROR"
