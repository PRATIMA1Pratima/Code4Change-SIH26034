"""
services/report_generator.py – PDF inspection report generation (Phase 10).

Generates a professional compliance report using fpdf2.

Report layout
─────────────
Page 1
  • Header band   – Code4Change branding + SIH badge
  • Meta section  – Inspection ID, timestamp, image filename
  • Image panel   – thumbnail of the uploaded product image
  • Score/Status  – large score number, COMPLIANT / NON_COMPLIANT badge
  • Declarations  – table: Declaration | Detected Value | Status
  • Violations    – bulleted list with severity prefix
  • OCR text      – raw extracted text (truncated to 800 chars)
  • Disclaimer    – AI-assisted, not a legal certificate

All sections degrade gracefully if data is missing or the image is
unavailable (e.g. it was deleted after the inspection).
"""

from __future__ import annotations

import logging
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Colour palette (R, G, B) ──────────────────────────────────────────────────
CLR_PRIMARY        = (26,  86, 219)   # #1a56db – brand blue
CLR_COMPLIANT      = (14, 127,  74)   # #0e7f4a – green
CLR_NONCOMPLIANT   = (185, 28,  28)   # #b91c1c – red
CLR_WARNING        = (180, 83,   9)   # #b45309 – amber
CLR_HEADING_BG     = (248, 250, 252)  # light grey row header
CLR_ROW_ALT        = (250, 251, 252)  # alternating row tint
CLR_BORDER         = (209, 217, 224)  # #d1d9e0
CLR_TEXT           = ( 26,  32,  44)  # #1a202c
CLR_MUTED          = (107, 114, 128)  # #6b7280
CLR_WHITE          = (255, 255, 255)

# Declaration display labels (mirrors compliance_engine.py)
DECLARATION_LABELS: dict[str, str] = {
    "mrp":               "MRP (Maximum Retail Price)",
    "net_quantity":      "Net Quantity",
    "manufacturer":      "Manufacturer / Packer Name",
    "address":           "Manufacturer / Packer Address",
    "manufacturing_date": "Manufacturing / Packing Date",
    "consumer_care":     "Consumer Care Information",
    "product_name":      "Product Name",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_str(value: Any, max_len: int = 200) -> str:
    """Return a length-capped, Latin-1-safe string for fpdf2 core fonts."""
    if value is None:
        return "-"
    s = str(value).strip()
    s = s[:max_len] + ("..." if len(s) > max_len else "")
    return _to_latin1(s)


# Latin-1 substitution map for common non-Latin-1 characters
_LATIN1_MAP = str.maketrans({
    "\u2014": "--",   # em dash
    "\u2013": "-",    # en dash
    "\u2018": "'",    # left single quote
    "\u2019": "'",    # right single quote
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",    # non-breaking space
    "\u2022": "*",    # bullet
    "\u2014": "--",   # em dash (duplicate key harmless)
    "\u20b9": "Rs.",  # Indian Rupee sign
    "\u2714": "OK",   # check mark
    "\u2718": "X",    # ballot X
    "\u26a0": "(!)",  # warning sign
})


def _to_latin1(text: str) -> str:
    """Replace non-Latin-1 characters with ASCII equivalents.

    Applies a known substitution map first, then falls back to replacing
    any remaining non-encodable character with '?'.
    """
    text = text.translate(_LATIN1_MAP)
    # Encode to Latin-1, replacing any remaining unmapped characters
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _format_timestamp(iso: str) -> str:
    """Convert ISO timestamp to a readable local-looking string."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y  %H:%M UTC")
    except Exception:
        return _to_latin1(iso)


def _strip_violation_prefix(msg: str) -> tuple[str, str]:
    """
    Split '[MISSING]  MRP – detail' into ('[MISSING]', 'MRP – detail').
    Returns ('', msg) if no known prefix is found.
    """
    for prefix in ("[MISSING]", "[INVALID]", "[WARNING]"):
        if msg.startswith(prefix):
            rest = msg[len(prefix):].lstrip()
            return prefix, rest
    return "", msg


# ── PDF builder ───────────────────────────────────────────────────────────────

def generate_report(inspection_id: int, inspection_data: dict) -> Path | None:
    """Generate a PDF compliance report and return its absolute path.

    Args:
        inspection_id: Real database ID (never 0 from Phase 10 onwards).
        inspection_data: Dict produced by the inspection pipeline containing:
            timestamp, image_path, extracted_text, detected_declarations,
            declaration_status, compliance_score, status, violations.

    Returns:
        Absolute Path to the saved PDF, or None if generation fails.
    """
    try:
        from fpdf import FPDF
        from app.config import REPORT_DIR
    except ImportError as exc:
        logger.error("[report] fpdf2 not installed: %s", exc)
        return None

    # ── Validate inspection_id ───────────────────────────────────────────────
    if not inspection_id or inspection_id == 0:
        logger.warning("[report] called with inspection_id=0 — skipping")
        return None

    out_path = REPORT_DIR / f"report_{inspection_id}.pdf"

    # Skip regeneration if file already exists (idempotent)
    if out_path.exists():
        return out_path

    try:
        pdf = _build_pdf(inspection_id, inspection_data)
        pdf.output(str(out_path))
        logger.info("[report] generated %s", out_path.name)
        return out_path
    except Exception as exc:
        logger.exception("[report] PDF generation failed: %s", exc)
        return None


def _build_pdf(inspection_id: int, data: dict):
    """Construct and return the FPDF object (not yet saved to disk)."""
    from fpdf import FPDF

    # ── Unpack data ──────────────────────────────────────────────────────────
    timestamp_str  = data.get("timestamp", "")
    image_path_str = data.get("image_path", "")
    extracted_text = data.get("extracted_text", "")
    declarations   = data.get("detected_declarations") or {}
    decl_status    = data.get("declaration_status") or {}
    score          = float(data.get("compliance_score", 0.0))
    status         = str(data.get("status", "UNKNOWN")).upper()
    violations     = data.get("violations") or []

    is_compliant   = status == "COMPLIANT"
    status_colour  = CLR_COMPLIANT if is_compliant else CLR_NONCOMPLIANT

    # ── Page setup ───────────────────────────────────────────────────────────
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    page_w  = pdf.w
    margin  = 15
    content_w = page_w - 2 * margin

    # ── 1. Header band ───────────────────────────────────────────────────────
    pdf.set_fill_color(*CLR_PRIMARY)
    pdf.rect(0, 0, page_w, 26, style="F")

    pdf.set_xy(margin, 5)
    pdf.set_text_color(*CLR_WHITE)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(content_w * 0.7, 8, "Code4Change", ln=False)

    # SIH badge (right-aligned)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_xy(page_w - margin - 50, 7)
    pdf.set_fill_color(255, 255, 255)
    pdf.set_text_color(*CLR_PRIMARY)
    pdf.cell(50, 6, "SIH 2026  |  SIH26034", border=1, align="C", fill=True)

    pdf.set_xy(margin, 14)
    pdf.set_text_color(*CLR_WHITE)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(content_w, 6, "AI-Assisted Packaged Commodity Compliance System", ln=True)

    pdf.ln(6)  # gap below header

    # ── 2. Report title ──────────────────────────────────────────────────────
    pdf.set_text_color(*CLR_TEXT)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(content_w, 8, "Compliance Inspection Report", ln=True, align="C")
    pdf.ln(2)
    pdf.set_draw_color(*CLR_BORDER)
    pdf.line(margin, pdf.get_y(), page_w - margin, pdf.get_y())
    pdf.ln(4)

    # ── 3. Meta section ──────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*CLR_MUTED)
    pdf.cell(content_w / 3, 6, _to_latin1(f"Inspection ID: #{inspection_id}"))
    pdf.cell(content_w / 3, 6, _to_latin1(f"Date/Time: {_format_timestamp(timestamp_str)}"))
    pdf.cell(content_w / 3, 6,
             _to_latin1(f"Image: {Path(image_path_str).name[:40] if image_path_str else '-'}"),
             ln=True)
    pdf.ln(4)

    # ── 4. Score + status panel ──────────────────────────────────────────────
    panel_h  = 22
    panel_y  = pdf.get_y()
    half_w   = content_w / 2

    # Score box
    pdf.set_fill_color(*CLR_HEADING_BG)
    pdf.set_draw_color(*CLR_BORDER)
    pdf.rect(margin, panel_y, half_w - 2, panel_h, style="FD")
    pdf.set_xy(margin, panel_y + 2)
    pdf.set_text_color(*status_colour)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(half_w - 2, 10, f"{round(score)}%", align="C", ln=False)
    pdf.set_xy(margin, panel_y + 13)
    pdf.set_text_color(*CLR_MUTED)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(half_w - 2, 6, "COMPLIANCE SCORE", align="C", ln=False)

    # Status box
    pdf.set_fill_color(*status_colour)
    pdf.rect(margin + half_w + 2, panel_y, half_w - 2, panel_h, style="F")
    pdf.set_xy(margin + half_w + 2, panel_y + 2)
    pdf.set_text_color(*CLR_WHITE)
    pdf.set_font("Helvetica", "B", 14)
    status_label = "[COMPLIANT]" if is_compliant else "[NON-COMPLIANT]"
    pdf.cell(half_w - 2, 10, status_label, align="C", ln=False)
    pdf.set_xy(margin + half_w + 2, panel_y + 13)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(half_w - 2, 6, "COMPLIANCE STATUS", align="C", ln=True)

    pdf.ln(6)

    # ── 5. Product image thumbnail ───────────────────────────────────────────
    if image_path_str:
        img_path = Path(image_path_str)
        if img_path.exists():
            try:
                thumb_w = 60
                img_x   = page_w / 2 - thumb_w / 2
                img_y   = pdf.get_y()
                pdf.image(str(img_path), x=img_x, y=img_y, w=thumb_w)
                pdf.set_y(img_y + thumb_w * 0.6 + 3)  # approx height
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(*CLR_MUTED)
                pdf.cell(content_w, 4, f"Product image: {img_path.name}", align="C", ln=True)
                pdf.ln(4)
            except Exception as exc:
                logger.warning("[report] could not embed image: %s", exc)

    # ── 6. Declarations table ─────────────────────────────────────────────────
    _section_heading(pdf, margin, content_w, "Detected Declarations")
    pdf.ln(2)

    # Table header
    col_w = [content_w * 0.40, content_w * 0.40, content_w * 0.20]
    _table_header(pdf, margin, col_w, ["Declaration", "Detected Value", "Status"])

    # Rows — iterate in canonical order then add any extras
    all_keys = list(DECLARATION_LABELS.keys())
    for key in all_keys:
        label = DECLARATION_LABELS[key]
        ds    = decl_status.get(key, {})
        value = ds.get("value") if ds else declarations.get(key)
        found = ds.get("found", value is not None and str(value).strip() != "")
        valid = ds.get("valid", found)

        if found and valid:
            status_text  = "Valid"
            status_clr   = CLR_COMPLIANT
        elif found and not valid:
            status_text  = "Invalid"
            status_clr   = CLR_WARNING
        else:
            status_text  = "Missing"
            status_clr   = CLR_NONCOMPLIANT

        value_display = _safe_str(value, 60) if found else "—"

        _table_row(pdf, margin, col_w,
                   [label, value_display, status_text],
                   status_colour=status_clr, status_col=2)

    pdf.ln(5)

    # ── 7. Violations ────────────────────────────────────────────────────────
    _section_heading(pdf, margin, content_w, "Violations & Notices")
    pdf.ln(2)

    if not violations:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*CLR_COMPLIANT)
        pdf.set_x(margin)
        pdf.cell(content_w, 6, "OK  All required declarations detected and valid.", ln=True)
    else:
        for msg in violations:
            prefix, rest = _strip_violation_prefix(msg)
            if prefix == "[MISSING]":
                bullet_clr = CLR_NONCOMPLIANT; bullet = "[!]"
            elif prefix == "[INVALID]":
                bullet_clr = CLR_WARNING;      bullet = "[?]"
            elif prefix == "[WARNING]":
                bullet_clr = CLR_WARNING;      bullet = "[W]"
            else:
                bullet_clr = CLR_MUTED;        bullet = "  -"

            pdf.set_x(margin)
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(*bullet_clr)
            pdf.cell(8, 5, bullet, ln=False)

            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*CLR_TEXT)
            # Wrap long violation text — sanitise for Latin-1
            wrapped = textwrap.fill(_to_latin1(rest), width=90)
            for i, line in enumerate(wrapped.splitlines()):
                if i == 0:
                    pdf.cell(content_w - 8, 5, line, ln=True)
                else:
                    pdf.set_x(margin + 8)
                    pdf.cell(content_w - 8, 5, line, ln=True)

    pdf.ln(5)

    # ── 8. OCR extracted text ─────────────────────────────────────────────────
    if extracted_text and extracted_text.strip():
        _section_heading(pdf, margin, content_w, "OCR Extracted Text")
        pdf.ln(2)
        pdf.set_fill_color(*CLR_HEADING_BG)
        pdf.set_draw_color(*CLR_BORDER)
        ocr_preview = extracted_text[:800] + ("..." if len(extracted_text) > 800 else "")
        pdf.set_font("Courier", "", 7)
        pdf.set_text_color(*CLR_TEXT)
        pdf.set_x(margin)
        # Multi-line cell — sanitise for Latin-1
        pdf.multi_cell(content_w, 4, _to_latin1(ocr_preview), border=1, fill=True)
        pdf.ln(5)

    # ── 9. Disclaimer ─────────────────────────────────────────────────────────
    # Draw disclaimer even if we've moved to a second page
    pdf.set_fill_color(*CLR_HEADING_BG)
    pdf.set_draw_color(*CLR_BORDER)
    pdf.set_x(margin)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*CLR_MUTED)
    disclaimer = _to_latin1(
        "DISCLAIMER: This report is an AI-assisted preliminary compliance check only. "
        "It does NOT constitute a legal compliance certificate under the Legal Metrology Act, "
        "FSSAI regulations, BIS standards, or any other applicable legislation. "
        "All findings must be verified by a qualified compliance officer before any "
        "regulatory action is taken. Code4Change - Smart India Hackathon 2026 (SIH26034)."
    )
    pdf.multi_cell(content_w, 4, disclaimer, border=1, fill=True, align="J")
    pdf.ln(4)

    # ── 10. Footer on every page ──────────────────────────────────────────────
    # fpdf2 footer via set_footer_function equivalent — use page_break handler
    for page_no in range(1, pdf.page + 1):
        pdf.page = page_no
        pdf.set_y(-12)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*CLR_MUTED)
        footer = _to_latin1(
            f"Code4Change  |  Inspection #{inspection_id}  |  "
            f"Generated {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}  |  "
            f"Page {page_no}"
        )
        pdf.cell(0, 5, footer, align="C")

    return pdf


# ── Layout helpers ────────────────────────────────────────────────────────────

def _section_heading(pdf, margin: float, content_w: float, title: str) -> None:
    """Render a left-bordered section heading."""
    pdf.set_fill_color(*CLR_PRIMARY)
    pdf.rect(margin, pdf.get_y(), 3, 7, style="F")
    pdf.set_x(margin + 5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*CLR_TEXT)
    pdf.cell(content_w - 5, 7, title, ln=True)


def _table_header(pdf, margin: float, col_widths: list[float],
                  headers: list[str]) -> None:
    """Render a styled table header row."""
    pdf.set_fill_color(*CLR_PRIMARY)
    pdf.set_text_color(*CLR_WHITE)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_x(margin)
    for i, (text, w) in enumerate(zip(headers, col_widths)):
        pdf.cell(w, 6, text, border=0, fill=True, align="L")
    pdf.ln()


def _table_row(pdf, margin: float, col_widths: list[float],
               cells: list[str], *, status_colour: tuple,
               status_col: int = -1) -> None:
    """Render a single table data row with alternating fill."""
    # Use light alternating background
    row_y = pdf.get_y()
    pdf.set_fill_color(*CLR_ROW_ALT)
    pdf.rect(margin, row_y, sum(col_widths), 6, style="F")
    pdf.set_draw_color(*CLR_BORDER)

    pdf.set_x(margin)
    for i, (text, w) in enumerate(zip(cells, col_widths)):
        if i == status_col:
            pdf.set_text_color(*status_colour)
            pdf.set_font("Helvetica", "B", 8)
        else:
            pdf.set_text_color(*CLR_TEXT)
            pdf.set_font("Helvetica", "", 8)
        pdf.cell(w, 6, _safe_str(text, 60), border=0, align="L")
    pdf.ln()
