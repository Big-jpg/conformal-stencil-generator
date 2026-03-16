# src/variants.py
"""
Multi-variant mask plate generator.

Rather than requiring the user to tune a single set of parameters and
regenerate manually, this module runs a fixed set of named preset strategies
against the source geometry and returns all results simultaneously.

Each variant is self-contained: it carries its own raster pipeline settings
(if the source is raster), mask-plate parameters, and sprue configuration.
The app renders all variants side-by-side so the user can compare and pick.

Variant catalogue
-----------------
For SVG input (geometry already vectorised, no raster re-processing):
  raw            — plate with no sprues, no clearance
  clearance      — 0.5 mm clearance offset, no sprues
  bridged        — clearance + sprues (2 mm wide, 50 mm max)
  bridged_narrow — clearance + narrow sprues (1 mm wide, 30 mm max)
  inverted       — geometry inverted (plate = artwork, holes = background)

For raster input (re-runs the pipeline with different settings):
  raw            — Otsu threshold, no cleanup, no sprues
  cleaned        — Otsu + morph open/close, small-component filter
  inverted       — Otsu inverted (swap fg/bg interpretation)
  culled         — cleaned + aggressive small-feature removal
  bridged        — cleaned + sprues (2 mm, 50 mm max)
  bridged_small  — cleaned + sprues (1 mm, 20 mm max, for fine detail)
  detail         — lower threshold, minimal cleanup, preserves fine marks
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from geom2d import add_alignment_marks, add_sprues, create_mask_plate
from pipelines.raster_silhouette import RasterSilhouettePipeline


@dataclass
class VariantResult:
    name: str
    label: str
    description: str
    plate: Optional[Polygon]
    geometry: Optional[MultiPolygon]   # the artwork geometry used
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared plate-building helper
# ---------------------------------------------------------------------------

def _build_plate(
    geometry: MultiPolygon,
    plate_margin: float,
    clearance: float,
    use_sprues: bool,
    sprue_width: float,
    sprue_max_length: float,
    sprue_max_count: int,
    use_marks: bool = False,
    mark_type: str = "Crosshair",
    mark_size: float = 5.0,
    mark_offset: float = 10.0,
) -> Polygon:
    plate = create_mask_plate(geometry, plate_margin, clearance)
    if use_sprues:
        plate = add_sprues(plate, sprue_width, sprue_max_length, sprue_max_count)
    if use_marks:
        plate = add_alignment_marks(plate, mark_type, mark_size, mark_offset)
    return plate


def _invert_geometry(
    geometry: MultiPolygon,
    plate_margin: float,
) -> MultiPolygon:
    """
    Return the complement of *geometry* within its bounding box + margin.
    This swaps the interpretation of foreground and background.
    """
    from shapely.geometry import box as shapely_box

    minx, miny, maxx, maxy = geometry.bounds
    bbox = shapely_box(
        minx - plate_margin, miny - plate_margin,
        maxx + plate_margin, maxy + plate_margin,
    )
    inverted = bbox.difference(geometry)
    if isinstance(inverted, Polygon):
        return MultiPolygon([inverted])
    if isinstance(inverted, MultiPolygon):
        return inverted
    polys = [g for g in getattr(inverted, "geoms", []) if isinstance(g, Polygon)]
    return MultiPolygon(polys)


# ---------------------------------------------------------------------------
# SVG variant set
# ---------------------------------------------------------------------------

_SVG_VARIANTS = [
    {
        "name": "raw",
        "label": "Raw (no sprues)",
        "description": "Plate with no clearance and no sprues. Shows the artwork cutouts as-is.",
        "clearance": 0.0,
        "use_sprues": False,
    },
    {
        "name": "clearance",
        "label": "Clearance only",
        "description": "0.5 mm outward offset on all cutouts. No sprues.",
        "clearance": 0.5,
        "use_sprues": False,
    },
    {
        "name": "bridged",
        "label": "Bridged (2 mm sprues)",
        "description": "0.5 mm clearance + 2 mm wide sprue channels connecting all holes to the plate edge.",
        "clearance": 0.5,
        "use_sprues": True,
        "sprue_width": 2.0,
        "sprue_max_length": 50.0,
        "sprue_max_count": 30,
    },
    {
        "name": "bridged_narrow",
        "label": "Bridged narrow (1 mm sprues)",
        "description": "0.5 mm clearance + narrow 1 mm sprues. Better for fine detail.",
        "clearance": 0.5,
        "use_sprues": True,
        "sprue_width": 1.0,
        "sprue_max_length": 30.0,
        "sprue_max_count": 30,
    },
    {
        "name": "inverted",
        "label": "Inverted",
        "description": "Foreground/background swapped. The artwork becomes the plate material; the background becomes the cutout.",
        "clearance": 0.0,
        "use_sprues": False,
        "invert_geometry": True,
    },
    {
        "name": "inverted_bridged",
        "label": "Inverted + bridged",
        "description": "Inverted geometry with 2 mm sprues.",
        "clearance": 0.0,
        "use_sprues": True,
        "sprue_width": 2.0,
        "sprue_max_length": 50.0,
        "sprue_max_count": 30,
        "invert_geometry": True,
    },
]


def run_svg_variants(
    geometry: MultiPolygon,
    plate_margin: float = 10.0,
) -> List[VariantResult]:
    results = []
    for spec in _SVG_VARIANTS:
        try:
            geom = geometry
            if spec.get("invert_geometry"):
                geom = _invert_geometry(geometry, plate_margin)
                if geom.is_empty:
                    raise ValueError("Inverted geometry is empty")

            plate = _build_plate(
                geometry=geom,
                plate_margin=plate_margin,
                clearance=spec.get("clearance", 0.0),
                use_sprues=spec.get("use_sprues", False),
                sprue_width=spec.get("sprue_width", 2.0),
                sprue_max_length=spec.get("sprue_max_length", 50.0),
                sprue_max_count=spec.get("sprue_max_count", 20),
            )
            results.append(VariantResult(
                name=spec["name"],
                label=spec["label"],
                description=spec["description"],
                plate=plate,
                geometry=geom,
                metadata={
                    "holes": len(list(plate.interiors)),
                    "area_mm2": plate.area,
                    "clearance": spec.get("clearance", 0.0),
                    "sprues": spec.get("use_sprues", False),
                },
            ))
        except Exception as exc:
            results.append(VariantResult(
                name=spec["name"],
                label=spec["label"],
                description=spec["description"],
                plate=None,
                geometry=None,
                error=traceback.format_exc(),
            ))
    return results


# ---------------------------------------------------------------------------
# Raster variant set
# ---------------------------------------------------------------------------

# Base settings shared across all raster variants
_RASTER_BASE = {
    "blur_px": 1,
    "morph_open_px": 1,
    "morph_close_px": 2,
    "min_component_area_px": 32,
    "min_area_mm2": 0.5,
    "min_feature_mm": 0.2,
    "simplify_tolerance_mm": 0.15,
}

_RASTER_VARIANTS = [
    {
        "name": "raw",
        "label": "Raw (Otsu, no cleanup)",
        "description": "Otsu threshold, no morphological cleanup, no sprues. Maximum detail retention.",
        "pipeline_overrides": {
            "auto_threshold": True,
            "invert": False,
            "blur_px": 0,
            "morph_open_px": 0,
            "morph_close_px": 0,
            "min_component_area_px": 1,
            "min_area_mm2": 0.1,
            "min_feature_mm": 0.0,
            "simplify_tolerance_mm": 0.0,
        },
        "plate": {"clearance": 0.0, "use_sprues": False},
    },
    {
        "name": "cleaned",
        "label": "Cleaned",
        "description": "Otsu threshold with standard morphological cleanup and small-component filtering.",
        "pipeline_overrides": {
            "auto_threshold": True,
            "invert": False,
        },
        "plate": {"clearance": 0.3, "use_sprues": False},
    },
    {
        "name": "inverted",
        "label": "Inverted",
        "description": "Otsu threshold with foreground/background swapped. Use when the artwork is light-on-dark.",
        "pipeline_overrides": {
            "auto_threshold": True,
            "invert": True,
        },
        "plate": {"clearance": 0.3, "use_sprues": False},
    },
    {
        "name": "culled",
        "label": "Culled (large features only)",
        "description": "Cleaned mask with aggressive minimum-feature and minimum-area filters. Removes fine marks and noise.",
        "pipeline_overrides": {
            "auto_threshold": True,
            "invert": False,
            "min_component_area_px": 200,
            "min_area_mm2": 3.0,
            "min_feature_mm": 1.0,
            "simplify_tolerance_mm": 0.3,
        },
        "plate": {"clearance": 0.5, "use_sprues": False},
    },
    {
        "name": "bridged",
        "label": "Bridged (2 mm sprues)",
        "description": "Cleaned mask with 2 mm sprue channels connecting all holes to the plate edge.",
        "pipeline_overrides": {
            "auto_threshold": True,
            "invert": False,
        },
        "plate": {
            "clearance": 0.3,
            "use_sprues": True,
            "sprue_width": 2.0,
            "sprue_max_length": 60.0,
            "sprue_max_count": 50,
        },
    },
    {
        "name": "bridged_small",
        "label": "Bridged narrow (1 mm sprues)",
        "description": "Cleaned mask with narrow 1 mm sprues. Preserves more detail around fine features.",
        "pipeline_overrides": {
            "auto_threshold": True,
            "invert": False,
        },
        "plate": {
            "clearance": 0.2,
            "use_sprues": True,
            "sprue_width": 1.0,
            "sprue_max_length": 30.0,
            "sprue_max_count": 50,
        },
    },
    {
        "name": "detail",
        "label": "Detail (low threshold)",
        "description": "Lower threshold (T=80) with minimal cleanup. Captures fine lines and subtle marks.",
        "pipeline_overrides": {
            "auto_threshold": False,
            "threshold": 80,
            "invert": False,
            "blur_px": 0,
            "morph_open_px": 0,
            "morph_close_px": 1,
            "min_component_area_px": 16,
            "min_area_mm2": 0.1,
            "min_feature_mm": 0.0,
            "simplify_tolerance_mm": 0.05,
        },
        "plate": {"clearance": 0.2, "use_sprues": False},
    },
    {
        "name": "inverted_bridged",
        "label": "Inverted + bridged",
        "description": "Inverted mask with 2 mm sprues. For light-on-dark artwork that also needs bridging.",
        "pipeline_overrides": {
            "auto_threshold": True,
            "invert": True,
        },
        "plate": {
            "clearance": 0.3,
            "use_sprues": True,
            "sprue_width": 2.0,
            "sprue_max_length": 60.0,
            "sprue_max_count": 50,
        },
    },
]


def run_raster_variants(
    normalized_rgb: np.ndarray,
    target_width_mm: float,
    target_height_mm: float,
    plate_margin: float = 10.0,
) -> List[VariantResult]:
    pipeline = RasterSilhouettePipeline()
    results = []

    for spec in _RASTER_VARIANTS:
        try:
            # Merge base settings with variant overrides
            settings: Dict[str, Any] = {
                **_RASTER_BASE,
                "target_width_mm": target_width_mm,
                "target_height_mm": target_height_mm,
                **spec["pipeline_overrides"],
            }

            result = pipeline.run(normalized_rgb, settings)
            geom = result.geometry

            if geom.is_empty:
                raise ValueError("Pipeline produced empty geometry for this variant")

            plate_spec = spec["plate"]
            plate = _build_plate(
                geometry=geom,
                plate_margin=plate_margin,
                clearance=plate_spec.get("clearance", 0.0),
                use_sprues=plate_spec.get("use_sprues", False),
                sprue_width=plate_spec.get("sprue_width", 2.0),
                sprue_max_length=plate_spec.get("sprue_max_length", 50.0),
                sprue_max_count=plate_spec.get("sprue_max_count", 30),
            )

            polys = list(geom.geoms) if not geom.is_empty else []
            total_holes_in_geom = sum(len(list(p.interiors)) for p in polys)

            results.append(VariantResult(
                name=spec["name"],
                label=spec["label"],
                description=spec["description"],
                plate=plate,
                geometry=geom,
                metadata={
                    "polygon_count": len(polys),
                    "geometry_holes": total_holes_in_geom,
                    "plate_holes": len(list(plate.interiors)),
                    "plate_area_mm2": plate.area,
                    "clearance": plate_spec.get("clearance", 0.0),
                    "sprues": plate_spec.get("use_sprues", False),
                    "threshold": settings.get("threshold", "Otsu"),
                    "invert": settings.get("invert", False),
                },
            ))
        except Exception:
            results.append(VariantResult(
                name=spec["name"],
                label=spec["label"],
                description=spec["description"],
                plate=None,
                geometry=None,
                error=traceback.format_exc(),
            ))

    return results
