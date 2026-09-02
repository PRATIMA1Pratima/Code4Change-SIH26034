"""
config.py – Application-wide configuration.

All tuneable values live here. Override any of them by setting
the corresponding environment variable before starting the server.
"""

import os
from pathlib import Path

# ── Base paths ────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent   # backend/
UPLOAD_DIR: Path = BASE_DIR / "uploads"
REPORT_DIR: Path = BASE_DIR / "reports"
DB_DIR: Path = BASE_DIR.parent / "database"

# Ensure required directories exist at import time
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{DB_DIR / 'inspections.db'}"
)

# ── Processed images ─────────────────────────────────────────────────────────
# Preprocessed images are saved here — originals in uploads/ are never touched.
PROCESSED_DIR: Path = BASE_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# ── Upload constraints ────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS: set[str] = {"jpg", "jpeg", "png", "webp", "bmp", "tiff"}
MAX_UPLOAD_BYTES: int = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024  # default 10 MB

# ── Image preprocessing ───────────────────────────────────────────────────────
# Target long-edge pixel size.  Images larger than this are downscaled;
# smaller images are upscaled to ensure OCR has enough resolution.
PREPROCESS_TARGET_LONG_EDGE: int = int(os.getenv("PREPROCESS_TARGET_LONG_EDGE", "2000"))

# Gaussian blur kernel size (must be odd).  Reduces sensor noise before
# thresholding.  Set to 0 to skip blurring entirely.
PREPROCESS_BLUR_KSIZE: int = int(os.getenv("PREPROCESS_BLUR_KSIZE", "3"))

# CLAHE (Contrast Limited Adaptive Histogram Equalisation) clip limit.
# Higher = more contrast boost.  0.0 disables CLAHE.
PREPROCESS_CLAHE_CLIP: float = float(os.getenv("PREPROCESS_CLAHE_CLIP", "2.0"))

# Adaptive threshold block size (must be odd, >= 3).
# Controls the neighbourhood used for local binarisation.
PREPROCESS_THRESH_BLOCK: int = int(os.getenv("PREPROCESS_THRESH_BLOCK", "31"))

# Adaptive threshold C constant subtracted from the mean.
PREPROCESS_THRESH_C: int = int(os.getenv("PREPROCESS_THRESH_C", "10"))

# Unsharp-mask sharpening strength (0.0 = off, 1.0 = subtle, 2.0 = strong).
# Sharpening is applied BEFORE thresholding to help edge definition.
PREPROCESS_SHARPEN_STRENGTH: float = float(os.getenv("PREPROCESS_SHARPEN_STRENGTH", "1.0"))

# ── OCR ───────────────────────────────────────────────────────────────────────
# Path to the Tesseract executable.
# "tesseract" works when Tesseract is on the system PATH (the default on this
# machine).  Set TESSERACT_CMD to an absolute path if it is not on PATH, e.g.:
#   set TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")

# Tesseract Page Segmentation Mode (PSM).
# PSM 6  – Assume a single uniform block of text.  Good for clean labels.
# PSM 11 – Sparse text: find as much text as possible.  Better for cluttered
#           labels with text at various positions and orientations.
# PSM 3  – Fully automatic page segmentation (Tesseract default).
# See: tesseract --help-psm for all options.
OCR_PSM: int = int(os.getenv("OCR_PSM", "6"))

# Tesseract OCR Engine Mode (OEM).
# 3 = Default (LSTM neural net).  0 = legacy engine.  Use 3 unless you have
# a specific reason to fall back to the old engine.
OCR_OEM: int = int(os.getenv("OCR_OEM", "3"))

# Language(s) to pass to Tesseract.  "eng" is always available.
# For Hindi text add "+hin" after installing the hin.traineddata pack.
OCR_LANG: str = os.getenv("OCR_LANG", "eng")

# Words per line threshold below which we consider OCR output "low quality".
# Used to add a warning notice to the violations list, not to discard output.
OCR_MIN_WORDS: int = int(os.getenv("OCR_MIN_WORDS", "3"))

# ── Server ────────────────────────────────────────────────────────────────────
APP_HOST: str = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

# ── CORS ──────────────────────────────────────────────────────────────────────
# Origins allowed to call the API.  In development the frontend is served from
# the filesystem (file://) or a simple HTTP server on localhost.
CORS_ORIGINS: list[str] = [
    "http://localhost",
    "http://localhost:5500",   # VS Code Live Server default
    "http://127.0.0.1:5500",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "null",                    # file:// origin reported by some browsers
]

# ── Compliance ────────────────────────────────────────────────────────────────
# Minimum score (0–100) for a product to be considered COMPLIANT.
COMPLIANCE_THRESHOLD: int = int(os.getenv("COMPLIANCE_THRESHOLD", "100"))
