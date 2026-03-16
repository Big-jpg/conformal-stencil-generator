from __future__ import annotations

from typing import Any, Dict, Tuple

import cv2
import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from .base import PipelineResult, RasterPipeline
from stencil_rules import enforce_stencil_rules


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
    Build a binary mask where the artwork is white (255) and background is black (0).
    """
    gray = _to_grayscale(image_rgb)

    if blur_px and blur_px > 0:
        k = blur_px * 2 + 1
        gray = cv2.GaussianBlur(gray, (k, k), 0)

    thresh_flag = cv2.THRESH_BINARY if invert else cv2.THRESH_BINARY_INV

    if auto_threshold:
        used_threshold, mask = cv2.threshold(
            gray,
            0,
            255,
            thresh_flag | cv2.THRESH_OTSU,
        )
        threshold_used = float(used_threshold)
    else:
        _, mask = cv2.threshold(gray, int(threshold), 255, thresh_flag)
        threshold_used = int(threshold)

    meta = {
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

    meta = {
        "components_found": int(max(0, num_labels - 1)),
        "components_kept": int(kept),
        "min_component_area_px": int(min_component_area_px),
        "morph_open_px": int(morph_open_px),
        "morph_close_px": int(morph_close_px),
    }
    return filtered, meta


def _contour_to_polygon(
    contour: np.ndarray,
    target_width_mm: float,
    target_height_mm: float,
    image_width_px: int,
    image_height_px: int,
) -> Polygon | None:
    if contour is None or len(contour) < 3:
        return None

    pts = contour[:, 0, :]
    coords = []
    for x_px, y_px in pts:
        x_mm = (float(x_px) / image_width_px) * target_width_mm
        y_mm = (float(y_px) / image_height_px) * target_height_mm
        coords.append((x_mm, y_mm))

    if len(coords) < 3:
        return None

    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)

    if poly.is_empty or not isinstance(poly, Polygon):
        return None

    return poly


def mask_to_polygons(
    mask: np.ndarray,
    target_width_mm: float,
    target_height_mm: float,
    simplify_tolerance_mm: float = 0.15,
    min_area_mm2: float = 0.5,
    min_feature_mm: float = 0.25,
) -> MultiPolygon:
    h, w = mask.shape[:2]

    contours, hierarchy = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    polys = []
    for contour in contours:
        poly = _contour_to_polygon(
            contour,
            target_width_mm=target_width_mm,
            target_height_mm=target_height_mm,
            image_width_px=w,
            image_height_px=h,
        )
        if poly is not None:
            polys.append(poly)

    if not polys:
        return MultiPolygon()

    geom = unary_union(polys)
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    elif not isinstance(geom, MultiPolygon):
        polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
        geom = MultiPolygon(polys)

    geom = enforce_stencil_rules(
        geom,
        min_area_mm2=min_area_mm2,
        min_feature_mm=min_feature_mm,
        simplify_tolerance_mm=simplify_tolerance_mm,
    )
    return geom


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

        meta = {
            "pipeline": self.name,
            "target_width_mm": float(target_width_mm),
            "target_height_mm": float(target_height_mm),
            **mask_meta,
            **clean_meta,
            "polygon_count": len(list(geometry.geoms)) if not geometry.is_empty else 0,
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
