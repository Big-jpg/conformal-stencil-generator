from __future__ import annotations

from pathlib import Path
from typing import Dict, Literal, Optional, Tuple

import numpy as np
from PIL import Image

FitMode = Literal["contain", "cover"]


def _flatten_alpha_to_white(img: Image.Image) -> Image.Image:
    """
    Convert RGBA/LA/P images to RGB by compositing against white.
    """
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
        return img.convert("RGB")

    if img.mode == "P":
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
        return img.convert("RGB")

    return img.convert("RGB")


def load_raster(filepath: str | Path) -> Tuple[np.ndarray, Dict]:
    """
    Load PNG/JPG/JPEG/WEBP into RGB uint8 ndarray [H, W, 3].
    """
    path = Path(filepath)
    img = Image.open(path)
    img = _flatten_alpha_to_white(img)

    image_rgb = np.array(img, dtype=np.uint8)
    h, w = image_rgb.shape[:2]

    metadata = {
        "source_path": str(path),
        "source_name": path.name,
        "source_ext": path.suffix.lower(),
        "original_width_px": int(w),
        "original_height_px": int(h),
        "mode": "RGB",
    }
    return image_rgb, metadata


def normalize_canvas(
    image_rgb: np.ndarray,
    target_aspect_ratio: Optional[float] = None,
    fit_mode: FitMode = "contain",
    max_dim_px: int = 1024,
    background: int = 255,
) -> Tuple[np.ndarray, Dict]:
    """
    Resize and pad/crop to a deterministic working canvas.

    - contain: preserve entire image, pad with background
    - cover: fill the target aspect, crop excess
    """
    if image_rgb.ndim != 3 or image_rgb.shape[2] != 3:
        raise ValueError("Expected RGB image of shape [H, W, 3].")

    src_h, src_w = image_rgb.shape[:2]

    if target_aspect_ratio is None:
        target_aspect_ratio = src_w / src_h if src_h else 1.0

    # Determine output canvas size bounded by max_dim_px.
    if target_aspect_ratio >= 1.0:
        out_w = max_dim_px
        out_h = max(1, int(round(out_w / target_aspect_ratio)))
    else:
        out_h = max_dim_px
        out_w = max(1, int(round(out_h * target_aspect_ratio)))

    src_img = Image.fromarray(image_rgb, mode="RGB")

    src_ratio = src_w / src_h if src_h else 1.0
    dst_ratio = target_aspect_ratio

    if fit_mode == "contain":
        if src_ratio >= dst_ratio:
            new_w = out_w
            new_h = max(1, int(round(new_w / src_ratio)))
        else:
            new_h = out_h
            new_w = max(1, int(round(new_h * src_ratio)))

        resized = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (out_w, out_h), (background, background, background))
        paste_x = (out_w - new_w) // 2
        paste_y = (out_h - new_h) // 2
        canvas.paste(resized, (paste_x, paste_y))

        meta = {
            "fit_mode": fit_mode,
            "canvas_width_px": int(out_w),
            "canvas_height_px": int(out_h),
            "resized_width_px": int(new_w),
            "resized_height_px": int(new_h),
            "paste_x": int(paste_x),
            "paste_y": int(paste_y),
            "target_aspect_ratio": float(target_aspect_ratio),
        }
        return np.array(canvas, dtype=np.uint8), meta

    if fit_mode == "cover":
        if src_ratio >= dst_ratio:
            new_h = out_h
            new_w = max(1, int(round(new_h * src_ratio)))
        else:
            new_w = out_w
            new_h = max(1, int(round(new_w / src_ratio)))

        resized = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        left = max(0, (new_w - out_w) // 2)
        top = max(0, (new_h - out_h) // 2)
        cropped = resized.crop((left, top, left + out_w, top + out_h))

        meta = {
            "fit_mode": fit_mode,
            "canvas_width_px": int(out_w),
            "canvas_height_px": int(out_h),
            "resized_width_px": int(new_w),
            "resized_height_px": int(new_h),
            "crop_left": int(left),
            "crop_top": int(top),
            "target_aspect_ratio": float(target_aspect_ratio),
        }
        return np.array(cropped, dtype=np.uint8), meta

    raise ValueError(f"Unsupported fit_mode: {fit_mode}")


def raster_to_physical_scale(
    image_rgb: np.ndarray,
    target_width_mm: float,
    target_height_mm: float | None = None,
    preserve_aspect: bool = True,
) -> Dict:
    """
    Return physical mapping metadata for downstream geometry conversion.
    """
    h, w = image_rgb.shape[:2]
    if w <= 0 or h <= 0:
        raise ValueError("Invalid image dimensions.")

    if target_height_mm is None:
        target_height_mm = target_width_mm * (h / w)

    if preserve_aspect:
        source_ratio = w / h
        requested_ratio = target_width_mm / target_height_mm
        if abs(source_ratio - requested_ratio) > 1e-6:
            # Preserve image aspect by adjusting height from width.
            target_height_mm = target_width_mm * (h / w)

    return {
        "image_width_px": int(w),
        "image_height_px": int(h),
        "target_width_mm": float(target_width_mm),
        "target_height_mm": float(target_height_mm),
        "px_to_mm_x": float(target_width_mm / w),
        "px_to_mm_y": float(target_height_mm / h),
    }