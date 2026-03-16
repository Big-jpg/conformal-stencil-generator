# src/pipelines/raster_silhouette.py
"""
Raster silhouette pipeline: PNG/JPG → binary mask → Shapely geometry.

Key improvement over the original implementation
-------------------------------------------------
The original mask_to_polygons() used cv2.RETR_EXTERNAL which retrieves only
the outermost contours.  This discards all inner contours (holes within
shapes), so any artwork with enclosed negative space — letters like O, A, B,
logos with rings — lost its interior topology entirely before reaching the
sprue logic.  True floating plate islands were never detected.

The replacement uses cv2.RETR_CCOMP (two-level hierarchy):
  - Level 0: outer contours (artwork fill regions)
  - Level 1: inner contours (holes inside those regions)

Each outer contour becomes a Shapely Polygon exterior ring.  Its direct
children in the hierarchy become interior rings (holes).  This correctly
represents letters with counters, donuts, and any shape with enclosed voids.

The resulting MultiPolygon is topologically correct and feeds cleanly into
add_sprues() which can now detect and bridge true floating islands.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from .base import PipelineResult, RasterPipeline
from stencil_rules import enforce_stencil_rules


# ---------------------------------------------------------------------------
# Mask building
# ---------------------------------------------------------------------------

def _to_grayscale(image_rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)


def build_binary_mask(
    image_rgb: np.ndarray,
    threshold: int = 128,
    invert: bool = False,
    blur_px: int = 1,
    auto_threshold: bool = True,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Build a binary mask where artwork pixels are white (255) and background
    pixels are black (0).

    Args:
        image_rgb:       RGB uint8 image array [H, W, 3].
        threshold:       Manual threshold value (0–255).
        invert:          Swap foreground/background interpretation.
        blur_px:         Gaussian blur radius in pixels (0 = no blur).
        auto_threshold:  Use Otsu's method to determine threshold automatically.

    Returns:
        (mask, metadata_dict)
    """
    gray = _to_grayscale(image_rgb)

    if blur_px and blur_px > 0:
        k = blur_px * 2 + 1
        gray = cv2.GaussianBlur(gray, (k, k), 0)

    thresh_flag = cv2.THRESH_BINARY if invert else cv2.THRESH_BINARY_INV

    if auto_threshold:
        used_threshold, mask = cv2.threshold(
            gray, 0, 255, thresh_flag | cv2.THRESH_OTSU,
        )
        threshold_used = float(used_threshold)
    else:
        _, mask = cv2.threshold(gray, int(threshold), 255, thresh_flag)
        threshold_used = int(threshold)

    meta: Dict[str, Any] = {
        "threshold_used": threshold_used,
        "invert": bool(invert),
        "blur_px": int(blur_px),
    }
    return mask, meta


def clean_binary_mask(
    mask: np.ndarray,
    morph_open_px: int = 1,
    morph_close_px: int = 1,
    min_component_area_px: int = 32,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Apply morphological cleanup and remove small connected components.

    Args:
        mask:                  Binary mask (uint8, values 0/255).
        morph_open_px:         Morphological opening radius (removes speckles).
        morph_close_px:        Morphological closing radius (fills small gaps).
        min_component_area_px: Minimum foreground component area in pixels.

    Returns:
        (cleaned_mask, metadata_dict)
    """
    cleaned = mask.copy()

    if morph_open_px > 0:
        k = morph_open_px * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)

    if morph_close_px > 0:
        k = morph_close_px * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        cleaned, connectivity=8
    )
    filtered = np.zeros_like(cleaned)
    kept = 0
    for idx in range(1, num_labels):
        area = stats[idx, cv2.CC_STAT_AREA]
        if area >= min_component_area_px:
            filtered[labels == idx] = 255
            kept += 1

    meta: Dict[str, Any] = {
        "components_found": int(max(0, num_labels - 1)),
        "components_kept": int(kept),
        "min_component_area_px": int(min_component_area_px),
        "morph_open_px": int(morph_open_px),
        "morph_close_px": int(morph_close_px),
    }
    return filtered, meta


# ---------------------------------------------------------------------------
# Contour → Polygon conversion
# ---------------------------------------------------------------------------

def _px_to_mm(
    pts: np.ndarray,
    target_width_mm: float,
    target_height_mm: float,
    image_width_px: int,
    image_height_px: int,
) -> List[Tuple[float, float]]:
    """Convert pixel coordinates to millimetre coordinates."""
    coords = []
    for x_px, y_px in pts:
        x_mm = (float(x_px) / image_width_px) * target_width_mm
        y_mm = (float(y_px) / image_height_px) * target_height_mm
        coords.append((x_mm, y_mm))
    return coords


def _contour_to_ring(
    contour: np.ndarray,
    target_width_mm: float,
    target_height_mm: float,
    image_width_px: int,
    image_height_px: int,
) -> Optional[List[Tuple[float, float]]]:
    """
    Convert an OpenCV contour array to a list of (x_mm, y_mm) coordinate
    pairs suitable for use as a Shapely ring.  Returns None if the contour
    has fewer than 3 points.
    """
    if contour is None or len(contour) < 3:
        return None
    pts = contour[:, 0, :]
    return _px_to_mm(
        pts,
        target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
        image_width_px=image_width_px,
        image_height_px=image_height_px,
    )


def mask_to_polygons(
    mask: np.ndarray,
    target_width_mm: float,
    target_height_mm: float,
    simplify_tolerance_mm: float = 0.15,
    min_area_mm2: float = 0.5,
    min_feature_mm: float = 0.25,
) -> MultiPolygon:
    """
    Convert a binary mask to a MultiPolygon in millimetre space.

    Uses RETR_CCOMP to capture a two-level contour hierarchy:
      - Level-0 contours → exterior rings of Shapely Polygons.
      - Level-1 contours (children of a level-0 contour) → interior rings
        (holes) of the corresponding Polygon.

    This correctly handles artwork with enclosed voids (letter counters, rings,
    etc.) that the original RETR_EXTERNAL approach silently discarded.

    Args:
        mask:                  Cleaned binary mask (uint8, 0/255).
        target_width_mm:       Physical width of the canvas (mm).
        target_height_mm:      Physical height of the canvas (mm).
        simplify_tolerance_mm: Douglas-Peucker tolerance for polygon
                               simplification (mm).
        min_area_mm2:          Minimum polygon area to retain (mm²).
        min_feature_mm:        Minimum feature size for sliver removal (mm).

    Returns:
        MultiPolygon in millimetre coordinates.
    """
    h, w = mask.shape[:2]

    # RETR_CCOMP: two-level hierarchy — outer contours at level 0,
    # holes at level 1.  hierarchy shape: [1, N, 4] where each entry is
    # [next, prev, first_child, parent].
    contours, hierarchy = cv2.findContours(
        mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours or hierarchy is None:
        return MultiPolygon()

    hierarchy = hierarchy[0]  # Unwrap the extra dimension → shape [N, 4]

    polys: List[Polygon] = []

    for idx, contour in enumerate(contours):
        parent_idx = hierarchy[idx][3]

        # Only process top-level (outer) contours.
        # Holes (parent_idx >= 0) are collected when processing their parent.
        if parent_idx >= 0:
            continue

        exterior_ring = _contour_to_ring(
            contour,
            target_width_mm=target_width_mm,
            target_height_mm=target_height_mm,
            image_width_px=w,
            image_height_px=h,
        )
        if exterior_ring is None or len(exterior_ring) < 3:
            continue

        # Collect all direct children (holes) of this outer contour.
        interior_rings: List[List[Tuple[float, float]]] = []
        child_idx = hierarchy[idx][2]  # first_child
        while child_idx >= 0:
            hole_ring = _contour_to_ring(
                contours[child_idx],
                target_width_mm=target_width_mm,
                target_height_mm=target_height_mm,
                image_width_px=w,
                image_height_px=h,
            )
            if hole_ring is not None and len(hole_ring) >= 3:
                interior_rings.append(hole_ring)
            # Move to next sibling
            child_idx = hierarchy[child_idx][0]

        try:
            poly = Polygon(exterior_ring, interior_rings)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue
            # buffer(0) can return a MultiPolygon when fixing self-intersections
            if isinstance(poly, MultiPolygon):
                polys.extend(
                    g for g in poly.geoms
                    if isinstance(g, Polygon) and not g.is_empty
                )
            elif isinstance(poly, Polygon):
                polys.append(poly)
        except Exception:
            continue

    if not polys:
        return MultiPolygon()

    geom = unary_union(polys)
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    elif not isinstance(geom, MultiPolygon):
        extracted = [
            g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)
        ]
        geom = MultiPolygon(extracted)

    geom = enforce_stencil_rules(
        geom,
        min_area_mm2=min_area_mm2,
        min_feature_mm=min_feature_mm,
        simplify_tolerance_mm=simplify_tolerance_mm,
    )
    return geom


# ---------------------------------------------------------------------------
# Pipeline class
# ---------------------------------------------------------------------------

class RasterSilhouettePipeline(RasterPipeline):
    name = "raster_silhouette"

    def run(self, image_rgb: np.ndarray, settings: Dict[str, Any]) -> PipelineResult:
        target_width_mm = float(settings.get("target_width_mm", 120.0))
        target_height_mm = settings.get("target_height_mm")
        if target_height_mm is None:
            h, w = image_rgb.shape[:2]
            target_height_mm = target_width_mm * (h / w)

        mask, mask_meta = build_binary_mask(
            image_rgb=image_rgb,
            threshold=int(settings.get("threshold", 128)),
            invert=bool(settings.get("invert", False)),
            blur_px=int(settings.get("blur_px", 1)),
            auto_threshold=bool(settings.get("auto_threshold", True)),
        )

        cleaned_mask, clean_meta = clean_binary_mask(
            mask=mask,
            morph_open_px=int(settings.get("morph_open_px", 1)),
            morph_close_px=int(settings.get("morph_close_px", 2)),
            min_component_area_px=int(settings.get("min_component_area_px", 32)),
        )

        geometry = mask_to_polygons(
            mask=cleaned_mask,
            target_width_mm=float(target_width_mm),
            target_height_mm=float(target_height_mm),
            simplify_tolerance_mm=float(settings.get("simplify_tolerance_mm", 0.15)),
            min_area_mm2=float(settings.get("min_area_mm2", 0.75)),
            min_feature_mm=float(settings.get("min_feature_mm", 0.25)),
        )

        meta: Dict[str, Any] = {
            "pipeline": self.name,
            "target_width_mm": float(target_width_mm),
            "target_height_mm": float(target_height_mm),
            **mask_meta,
            **clean_meta,
            "polygon_count": (
                len(list(geometry.geoms)) if not geometry.is_empty else 0
            ),
        }

        debug_images = {
            "input_rgb": image_rgb,
            "binary_mask": mask,
            "cleaned_mask": cleaned_mask,
        }

        return PipelineResult(
            geometry=geometry,
            metadata=meta,
            debug_images=debug_images,
            svg_path=None,
        )
