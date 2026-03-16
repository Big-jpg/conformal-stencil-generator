from __future__ import annotations

from typing import Iterable, List

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


def _iter_polygons(geometry) -> Iterable[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    raise TypeError(f"Unsupported geometry type: {type(geometry)}")


def prune_small_regions(geometry, min_area_mm2: float):
    polys = [p for p in _iter_polygons(geometry) if p.area >= min_area_mm2]
    if not polys:
        return MultiPolygon()
    return MultiPolygon(polys)


def simplify_geometry(geometry, tolerance_mm: float):
    polys: List[Polygon] = []
    for poly in _iter_polygons(geometry):
        simp = poly.simplify(tolerance_mm, preserve_topology=True)
        if simp.is_empty:
            continue
        if isinstance(simp, Polygon):
            polys.append(simp)
        elif isinstance(simp, MultiPolygon):
            polys.extend(list(simp.geoms))
    if not polys:
        return MultiPolygon()
    return MultiPolygon(polys)


def remove_thin_slivers(geometry, min_feature_mm: float):
    """
    Soft cleanup using morphological open/close in geometry space.
    This is conservative and not perfect, but good enough for Milestone 8.
    """
    if geometry.is_empty or min_feature_mm <= 0:
        return geometry

    radius = min_feature_mm / 2.0
    opened = geometry.buffer(radius).buffer(-radius)
    if opened.is_empty:
        return geometry
    return opened


def enforce_stencil_rules(
    geometry,
    min_area_mm2: float,
    min_feature_mm: float,
    simplify_tolerance_mm: float,
):
    if geometry.is_empty:
        return MultiPolygon()

    cleaned = prune_small_regions(geometry, min_area_mm2=min_area_mm2)
    if cleaned.is_empty:
        return MultiPolygon()

    if simplify_tolerance_mm > 0:
        cleaned = simplify_geometry(cleaned, tolerance_mm=simplify_tolerance_mm)

    if min_feature_mm > 0:
        cleaned = remove_thin_slivers(cleaned, min_feature_mm=min_feature_mm)

    # Merge overlaps after cleanup.
    merged = unary_union(cleaned)
    if merged.is_empty:
        return MultiPolygon()

    if isinstance(merged, Polygon):
        return MultiPolygon([merged])
    if isinstance(merged, MultiPolygon):
        return merged

    polys = [g for g in getattr(merged, "geoms", []) if isinstance(g, Polygon)]
    return MultiPolygon(polys)