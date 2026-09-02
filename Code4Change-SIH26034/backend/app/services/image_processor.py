"""
services/image_processor.py – OpenCV image preprocessing pipeline.

Converts a raw product photo into a high-contrast, noise-reduced
greyscale image that maximises OCR accuracy.

Pipeline (in order)
-------------------
1. Read           – load via OpenCV (handles JPEG/PNG/BMP/TIFF/WEBP)
2. Rotate         – auto-correct EXIF/JPEG orientation so text is upright
3. Resize         – scale to a standard long-edge resolution (default 2000 px)
                    • upscales small images  (phone photos with low res)
                    • downscales huge images (avoids slow OCR with no gain)
4. Grayscale      – convert BGR → single-channel grey
5. Denoise        – mild Gaussian blur to suppress sensor/compression noise
6. Sharpen        – unsharp-mask to enhance character edges before binarisation
7. CLAHE          – Contrast Limited Adaptive Histogram Equalisation:
                    recovers text on unevenly lit or faded labels
8. Threshold      – adaptive Gaussian thresholding → clean black-on-white
                    binarised image; handles local lighting variation
9. Save           – write to PROCESSED_DIR/<stem>_proc.png (lossless PNG)

The original upload in UPLOAD_DIR is NEVER modified.

All tuning parameters are read from config.py and can be overridden
via environment variables without touching code.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from app.config import (
    PREPROCESS_BLUR_KSIZE,
    PREPROCESS_CLAHE_CLIP,
    PREPROCESS_SHARPEN_STRENGTH,
    PREPROCESS_TARGET_LONG_EDGE,
    PREPROCESS_THRESH_BLOCK,
    PREPROCESS_THRESH_C,
    PROCESSED_DIR,
)

logger = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_image(image_path: Path) -> np.ndarray:
    """Read an image file into a BGR numpy array.

    Raises:
        FileNotFoundError: path does not exist.
        RuntimeError: OpenCV could not decode the file.
    """
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # cv2.imread does not handle Unicode paths on Windows reliably;
    # use np.fromfile + imdecode instead.
    raw  = np.fromfile(str(image_path), dtype=np.uint8)
    img  = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(
            f"OpenCV could not decode '{image_path.name}'. "
            "File may be corrupt or an unsupported format."
        )
    return img


def _fix_orientation(img: np.ndarray, image_path: Path) -> np.ndarray:
    """Rotate the image to correct EXIF/JPEG orientation if needed.

    Many phone cameras embed an orientation tag instead of rotating
    the pixels.  OpenCV ignores this tag, so we read it via the
    Pillow library (already in requirements) and apply the rotation
    manually.  If Pillow is unavailable or the tag is absent, the
    original image is returned unchanged.
    """
    try:
        from PIL import Image as PilImage
        from PIL.ExifTags import TAGS

        with PilImage.open(str(image_path)) as pil_img:
            exif_data = pil_img._getexif()  # returns None for non-JPEG
            if not exif_data:
                return img

            orientation_key = next(
                (k for k, v in TAGS.items() if v == "Orientation"), None
            )
            if orientation_key is None:
                return img

            orientation = exif_data.get(orientation_key, 1)

        # Apply the required rotation / flip
        if orientation == 3:
            img = cv2.rotate(img, cv2.ROTATE_180)
        elif orientation == 6:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif orientation == 8:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        # orientations 2,4,5,7 involve flips; uncommon on product photos
    except Exception:
        pass  # orientation fix is best-effort; never fail the pipeline

    return img


def _resize_to_target(img: np.ndarray, target_long_edge: int) -> np.ndarray:
    """Scale *img* so its longest dimension equals *target_long_edge*.

    Uses INTER_CUBIC for upscaling (sharpens details) and
    INTER_AREA for downscaling (avoids aliasing / moiré).
    """
    h, w = img.shape[:2]
    long_edge = max(h, w)

    if long_edge == target_long_edge:
        return img

    scale  = target_long_edge / long_edge
    new_w  = max(1, round(w * scale))
    new_h  = max(1, round(h * scale))
    interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA

    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def _to_grayscale(img: np.ndarray) -> np.ndarray:
    """Convert BGR to single-channel grayscale."""
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _denoise(gray: np.ndarray, ksize: int) -> np.ndarray:
    """Apply a Gaussian blur to reduce sensor and compression noise.

    *ksize* must be an odd positive integer.  A ksize of 0 or 1 is a no-op.
    Using ksize=3 is enough to knock out JPEG artefacts without blurring text.
    """
    if ksize < 3:
        return gray
    k = ksize if ksize % 2 == 1 else ksize + 1  # ensure odd
    return cv2.GaussianBlur(gray, (k, k), 0)


def _sharpen(gray: np.ndarray, strength: float) -> np.ndarray:
    """Unsharp-mask sharpening: enhances character edges.

    Works by subtracting a blurred version from the original.
    *strength* controls how much of the edge detail is added back:
      0.0 = identity  |  1.0 = subtle  |  2.0 = aggressive

    Applied before thresholding so binarisation sees cleaner edges.
    """
    if strength <= 0.0:
        return gray

    # Use a 5×5 Gaussian as the 'blur' component
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    # unsharp = original + strength × (original – blurred)
    sharpened = cv2.addWeighted(gray, 1.0 + strength, blurred, -strength, 0)
    return sharpened


def _apply_clahe(gray: np.ndarray, clip_limit: float) -> np.ndarray:
    """Contrast Limited Adaptive Histogram Equalisation.

    Recovers text on labels with uneven lighting, shadows, or fading.
    *clip_limit* = 0.0 disables CLAHE (returns gray unchanged).
    Tile grid 8×8 balances local contrast with global appearance.
    """
    if clip_limit <= 0.0:
        return gray

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _threshold(gray: np.ndarray, block_size: int, c: int) -> np.ndarray:
    """Adaptive Gaussian thresholding → binary black-on-white image.

    Unlike global thresholding, adaptive thresholding computes a
    local threshold for each pixel's neighbourhood, so it handles:
      - uneven illumination across the label
      - curved surfaces (bottles, cans)
      - varying background colours

    *block_size* must be odd and >= 3.
    *c* is subtracted from the computed mean; higher = more aggressive.

    The result is inverted (THRESH_BINARY_INV) so text is black on
    a white background, which Tesseract handles best.
    """
    b = block_size if block_size % 2 == 1 else block_size + 1
    b = max(b, 3)
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        b, c
    )


def _save_processed(img: np.ndarray, stem: str) -> Path:
    """Write *img* to PROCESSED_DIR as a lossless PNG.

    Returns the absolute path of the saved file.

    Raises:
        RuntimeError: if cv2.imencode or the file write fails.
    """
    out_path = PROCESSED_DIR / f"{stem}_proc.png"
    ok, buf  = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("cv2.imencode failed — could not encode processed image.")
    out_path.write_bytes(buf.tobytes())
    return out_path


# ── Public API ────────────────────────────────────────────────────────────────

def preprocess_image(image_path: Path) -> Path:
    """Run the full preprocessing pipeline on *image_path*.

    The original file is never modified.  A new PNG is written to
    ``PROCESSED_DIR/<stem>_proc.png`` and its path is returned.

    Args:
        image_path: Absolute path to the uploaded image.

    Returns:
        Path to the preprocessed PNG ready for OCR.

    Raises:
        FileNotFoundError: *image_path* does not exist.
        RuntimeError: Any step of the pipeline fails.
    """
    logger.info("[preprocess] starting pipeline for %s", image_path.name)

    # ── Step 1: Read ──────────────────────────────────────────────
    img = _read_image(image_path)
    h0, w0 = img.shape[:2]
    logger.debug("[preprocess] loaded  %dx%d px", w0, h0)

    # ── Step 2: Fix EXIF orientation ──────────────────────────────
    img = _fix_orientation(img, image_path)

    # ── Step 3: Resize ────────────────────────────────────────────
    img = _resize_to_target(img, PREPROCESS_TARGET_LONG_EDGE)
    h1, w1 = img.shape[:2]
    logger.debug("[preprocess] resized %dx%d px", w1, h1)

    # ── Step 4: Grayscale ─────────────────────────────────────────
    gray = _to_grayscale(img)

    # ── Step 5: Denoise ───────────────────────────────────────────
    gray = _denoise(gray, PREPROCESS_BLUR_KSIZE)

    # ── Step 6: Sharpen ───────────────────────────────────────────
    gray = _sharpen(gray, PREPROCESS_SHARPEN_STRENGTH)

    # ── Step 7: CLAHE ─────────────────────────────────────────────
    gray = _apply_clahe(gray, PREPROCESS_CLAHE_CLIP)

    # ── Step 8: Threshold ─────────────────────────────────────────
    binary = _threshold(gray, PREPROCESS_THRESH_BLOCK, PREPROCESS_THRESH_C)

    # ── Step 9: Save ──────────────────────────────────────────────
    stem     = image_path.stem
    out_path = _save_processed(binary, stem)
    logger.info("[preprocess] saved   %s", out_path.name)

    return out_path


def get_preprocessing_info() -> dict:
    """Return the current preprocessing configuration as a dict.

    Used by the debug endpoint to surface tuning parameters in the API.
    """
    return {
        "target_long_edge":  PREPROCESS_TARGET_LONG_EDGE,
        "blur_ksize":        PREPROCESS_BLUR_KSIZE,
        "clahe_clip":        PREPROCESS_CLAHE_CLIP,
        "sharpen_strength":  PREPROCESS_SHARPEN_STRENGTH,
        "thresh_block":      PREPROCESS_THRESH_BLOCK,
        "thresh_c":          PREPROCESS_THRESH_C,
        "processed_dir":     str(PROCESSED_DIR),
    }
