"""
services/ocr_service.py – Tesseract OCR integration.

Public API
----------
extract_text(image_path)  →  result dict (never raises)

Return schema
-------------
{
    "success"    : bool,
    "text"       : str,        # cleaned extracted text; "" on failure
    "engine"     : str,        # "tesseract" | "stub"
    "word_count" : int,        # number of words found
    "low_quality": bool,       # True when word_count < OCR_MIN_WORDS
    "error"      : str | None  # human-readable message on any failure
}

Design principles
-----------------
- Engine-agnostic contract: only this file needs to change to swap
  Tesseract for EasyOCR or a cloud OCR API.
- Never raises: all exceptions are caught and surfaced in "error".
- Graceful degradation: if Tesseract is not installed the rest of the
  pipeline still runs with an empty text result and a clear message.
- Post-processing is applied to the raw Tesseract output to strip
  noise characters and normalise whitespace before any downstream
  regex matching.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Post-processing helpers ───────────────────────────────────────────────────

# Characters Tesseract commonly hallucinates on noisy label scans.
# We keep: letters, digits, common punctuation found on product labels.
_KEEP_CHARS_RE = re.compile(
    r"[^\w\s"           # word chars + whitespace
    r"\.\,\:\;\-\/"     # sentence punctuation
    r"\(\)\[\]"         # brackets
    r"\+\=\@\#\%\&\*"  # misc label symbols
    r"₹\$\£\€"          # currency symbols
    r"\u0900-\u097F"    # Devanagari block (Hindi, for future use)
    r"]",
    re.UNICODE,
)

def _clean_text(raw: str) -> str:
    """Post-process raw Tesseract output into clean, usable text.

    Steps:
    1. Unicode normalisation (NFC) – fixes composed/decomposed character
       mismatches that confuse regex matching later.
    2. Strip control characters – Tesseract sometimes emits form-feeds (\x0c).
    3. Remove lone noise characters – single non-alphanumeric tokens on their
       own line (e.g. "|", "~", "°") that add no information.
    4. Normalise whitespace – collapse multiple spaces/tabs to one space;
       collapse 3+ consecutive blank lines to 2.
    5. Strip leading/trailing whitespace from each line and from the whole text.
    """
    if not raw:
        return ""

    # 1. NFC normalisation
    text = unicodedata.normalize("NFC", raw)

    # 2. Strip control characters except \n and \t
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", text)

    # 3. Remove lone noise tokens on their own line
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Keep the line if it has at least one alphanumeric character
        if re.search(r"[A-Za-z0-9\u0900-\u097F]", stripped):
            cleaned_lines.append(stripped)
        elif stripped == "":
            cleaned_lines.append("")   # preserve blank line for paragraph breaks

    text = "\n".join(cleaned_lines)

    # 4. Collapse multiple spaces/tabs to single space
    text = re.sub(r"[ \t]+", " ", text)

    # 5. Collapse 3+ consecutive blank lines → 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _count_words(text: str) -> int:
    """Count the number of whitespace-separated word tokens."""
    return len(text.split()) if text.strip() else 0


def _find_original(processed_path: Path) -> Path | None:
    """Given a processed image path, try to locate the original upload.

    The processed path looks like:  processed/<uuid>_proc.png
    The original upload looks like: uploads/<uuid>.jpg  (or .png etc.)

    Returns the original Path if found, otherwise None.
    """
    try:
        from app.config import UPLOAD_DIR
        # Strip the '_proc' suffix to recover the original stem
        stem = processed_path.stem          # e.g. "abc123_proc"
        if stem.endswith("_proc"):
            orig_stem = stem[:-5]           # e.g. "abc123"
        else:
            return None                     # not a processed file path

        for ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"):
            candidate = UPLOAD_DIR / f"{orig_stem}{ext}"
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return None


# ── Main OCR function ─────────────────────────────────────────────────────────

def extract_text(image_path: Path) -> dict:
    """Run Tesseract OCR on *image_path* and return a structured result.

    The function never raises.  All failure modes are captured and
    returned in the ``error`` field so the compliance pipeline can
    continue with whatever text (possibly empty) was extracted.

    Args:
        image_path: Path to the preprocessed image (PNG recommended).

    Returns:
        dict with keys: success, text, engine, word_count, low_quality, error.
    """
    # Lazy imports so the module loads even if pytesseract is not installed
    try:
        import pytesseract
    except ImportError:
        return {
            "success":     False,
            "text":        "",
            "engine":      "tesseract",
            "word_count":  0,
            "low_quality": True,
            "error": (
                "pytesseract is not installed. "
                "Run: pip install pytesseract==0.3.13"
            ),
        }

    # Import config here (not at module top) to allow unit testing without
    # a full app context.
    from app.config import OCR_LANG, OCR_MIN_WORDS, OCR_OEM, OCR_PSM, TESSERACT_CMD

    # Point pytesseract at the correct binary
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

    # Build the Tesseract config string
    # --oem  : OCR Engine Mode  (3 = LSTM, recommended)
    # --psm  : Page Segmentation Mode
    # -c tessedit_char_blacklist : suppress characters that never appear on
    #   product labels and cause false positives (backtick, pipe, caret, etc.)
    tesseract_config = (
        f"--oem {OCR_OEM} "
        f"--psm {OCR_PSM} "
        r"-c tessedit_char_blacklist=`|^{}\<>"
    )

    logger.info("[ocr] running Tesseract on %s  lang=%s psm=%d", image_path.name, OCR_LANG, OCR_PSM)

    def _run_tesseract(path: Path) -> tuple[bool, str, str | None]:
        """Run Tesseract on *path*. Returns (success, raw_text, error_msg)."""
        try:
            raw: str = pytesseract.image_to_string(
                str(path),
                lang=OCR_LANG,
                config=tesseract_config,
            )
            return True, raw, None
        except pytesseract.pytesseract.TesseractNotFoundError:
            msg = (
                f"Tesseract OCR binary not found. Expected at: '{TESSERACT_CMD}'. "
                "Install Tesseract and make sure it is on your PATH, or set "
                "the TESSERACT_CMD environment variable to the full path. "
                "Windows installer: https://github.com/UB-Mannheim/tesseract/wiki"
            )
            logger.error("[ocr] %s", msg)
            return False, "", msg
        except pytesseract.pytesseract.TesseractError as exc:
            msg = f"Tesseract returned an error: {exc}"
            logger.error("[ocr] %s", msg)
            return False, "", msg
        except FileNotFoundError:
            msg = f"Image file not found for OCR: {path}"
            logger.error("[ocr] %s", msg)
            return False, "", msg
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected OCR error: {type(exc).__name__}: {exc}"
            logger.exception("[ocr] unexpected error on %s", path)
            return False, "", msg

    # ── Try preprocessed image first ──────────────────────────────────
    success, raw_text, error = _run_tesseract(image_path)

    if not success:
        return {
            "success": False, "text": "", "engine": "tesseract",
            "word_count": 0, "low_quality": True, "error": error,
        }

    clean_proc  = _clean_text(raw_text)
    words_proc  = _count_words(clean_proc)

    # ── Try original upload as fallback if preprocessed gives few words ──
    # Adaptive thresholding can destroy fine strokes on synthetic or
    # high-contrast images; the original colour image may OCR better.
    best_text  = clean_proc
    best_words = words_proc
    used_image = image_path.name

    original_path = _find_original(image_path)
    if original_path and words_proc < 10:
        logger.info(
            "[ocr] preprocessed gave only %d words; trying original %s",
            words_proc, original_path.name
        )
        ok2, raw2, _ = _run_tesseract(original_path)
        if ok2:
            clean_orig  = _clean_text(raw2)
            words_orig  = _count_words(clean_orig)
            if words_orig > words_proc:
                best_text  = clean_orig
                best_words = words_orig
                used_image = original_path.name
                logger.info("[ocr] using original image (%d words vs %d)", words_orig, words_proc)

    low_q = best_words < OCR_MIN_WORDS

    if low_q:
        logger.warning(
            "[ocr] low word count (%d words) from %s — label may be unclear",
            best_words, used_image
        )
    else:
        logger.info("[ocr] extracted %d words from %s", best_words, used_image)

    return {
        "success":     True,
        "text":        best_text,
        "engine":      "tesseract",
        "word_count":  best_words,
        "low_quality": low_q,
        "error":       None,
    }


# ── Utility: get OCR engine info ──────────────────────────────────────────────

def get_ocr_info() -> dict:
    """Return current OCR configuration and Tesseract version string.

    Used by the debug endpoint; never raises.
    """
    try:
        import pytesseract
        from app.config import OCR_LANG, OCR_MIN_WORDS, OCR_OEM, OCR_PSM, TESSERACT_CMD
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        version = pytesseract.get_tesseract_version()
        available = True
    except Exception as exc:
        version   = f"unavailable ({exc})"
        available = False
        OCR_LANG  = "unknown"  # type: ignore[assignment]
        OCR_PSM   = -1         # type: ignore[assignment]
        OCR_OEM   = -1         # type: ignore[assignment]
        OCR_MIN_WORDS = -1     # type: ignore[assignment]
        TESSERACT_CMD = "unknown"  # type: ignore[assignment]

    return {
        "engine":       "tesseract",
        "available":    available,
        "version":      str(version),
        "cmd":          TESSERACT_CMD,
        "lang":         OCR_LANG,
        "psm":          OCR_PSM,
        "oem":          OCR_OEM,
        "min_words":    OCR_MIN_WORDS,
    }
