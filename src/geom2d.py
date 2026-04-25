# src/geom2d.py
"""
2D geometry operations module.
Handles mask plate generation, clearance offsets, island detection, and sprues.

Sprue / bridge design intent
-----------------------------
A stencil "sprue" (also called a bridge or tie) is a narrow channel of REMOVED
material that runs from a closed hole in the plate to the plate's outer edge.
Cutting this channel:
  - Allows the stencil to be peeled away from the substrate without tearing.
  - Keeps floating plate islands (e.g. the counter of a letter 'O') physically
    connected to the rest of the plate via the channel walls.

Geometry model
--------------
After create_mask_plate() the plate is a Shapely Polygon whose interior rings
(plate.interiors) are the artwork cutouts. Each interior ring is a hole.

A correct sprue rectangle must:
  1. Start at the NEAREST POINT ON THE HOLE BOUNDARY (not the centroid).
  2. End at the NEAREST POINT ON THE PLATE EXTERIOR.
  3. Be applied one at a time via plate.difference(sprue) so that each
     successive operation sees the updated hole count.

Bug in the original implementation
------------------------------------
The original code used the hole centroid as the sprue start point. Because the
centroid is inside the hole, the sprue rectangle covered the entire hole area.
plate.difference(sprue) therefore consumed the hole completely, merging it with
the exterior rather than leaving a narrow channel. Batching all sprues into a
single unary_union before the difference made this worse: the merged slab wiped
out all holes simultaneously.

True floating-island detection
-------------------------------
A "true floating island" is a region of plate material that is completely
surrounded by a cutout ring — e.g. the dot of an 'i', the counter of an 'O'.
These appear as polygons-within-holes in the Shapely representation and require
a different bridge strategy: connect the island to the nearest solid plate
material (not to the outer edge). detect_true_islands() handles this case.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple, Union

import numpy as np
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

GeometryLike = Union[Polygon, MultiPolygon]


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------

class PlateGeom:
    """
    Lightweight wrapper for plate geometry plus metadata.

    This class exists as a compatibility layer for app iterations that want to
    carry geometry and derived metadata together. It deliberately delegates
    unknown attributes to the wrapped Shapely geometry, so code that asks for
    `.bounds`, `.area`, `.interiors`, `.is_valid`, etc. still behaves as
    expected.
    """

    def __init__(
        self,
        geometry: Optional[GeometryLike] = None,
        plate: Optional[GeometryLike] = None,
        source_geometry: Optional[GeometryLike] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        resolved = geometry if geometry is not None else plate
        if resolved is None:
            raise ValueError("PlateGeom requires either geometry= or plate=")

        self.geometry = resolved
        self.source_geometry = source_geometry
        self.metadata: dict[str, Any] = dict(metadata or {})

        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def plate(self) -> GeometryLike:
        return self.geometry

    @property
    def geom(self) -> GeometryLike:
        return self.geometry

    @property
    def hole_count(self) -> int:
        return _count_holes(self.geometry)

    @property
    def total_area(self) -> float:
        return _total_area(self.geometry)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.geometry, name)

    def __repr__(self) -> str:
        return (
            "PlateGeom("
            f"type={self.geometry.geom_type!r}, "
            f"holes={self.hole_count}, "
            f"area={self.total_area:.3f}"
            ")"
        )


def _as_geometry(value: Any) -> GeometryLike:
    """Return the wrapped Shapely geometry for Polygon/MultiPolygon/PlateGeom."""
    if isinstance(value, (Polygon, MultiPolygon)):
        return value

    if isinstance(value, PlateGeom):
        return value.geometry

    if hasattr(value, "geometry"):
        candidate = getattr(value, "geometry")
        if isinstance(candidate, (Polygon, MultiPolygon)):
            return candidate

    if hasattr(value, "plate"):
        candidate = getattr(value, "plate")
        if isinstance(candidate, (Polygon, MultiPolygon)):
            return candidate

    raise TypeError(f"Unsupported geometry type: {type(value)}")


def _iter_polygons(value: Any) -> List[Polygon]:
    """Return all Polygon members from a Polygon, MultiPolygon, or PlateGeom."""
    geom = _as_geometry(value)
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [poly for poly in geom.geoms if isinstance(poly, Polygon)]
    return []


def _count_holes(value: Any) -> int:
    """Count all interior rings across Polygon/MultiPolygon/PlateGeom input."""
    return sum(len(poly.interiors) for poly in _iter_polygons(value))


def _total_area(value: Any) -> float:
    """Return total area for Polygon/MultiPolygon/PlateGeom input."""
    geom = _as_geometry(value)
    return float(geom.area)


# ---------------------------------------------------------------------------
# Mask plate creation
# ---------------------------------------------------------------------------

def create_mask_plate(
    geometry: GeometryLike,
    plate_margin: float,
    clearance: float,
) -> Polygon:
    """
    Generate mask plate with cutouts.

    Args:
        geometry:      SVG / raster geometry as Polygon or MultiPolygon.
        plate_margin:  Margin around bounding box (mm).
        clearance:     Outward offset applied to artwork before subtraction (mm).

    Returns:
        Polygon representing the stencil plate with negative-space cutouts.
    """
    geometry = _as_geometry(geometry)
    minx, miny, maxx, maxy = geometry.bounds

    plate = box(
        minx - plate_margin,
        miny - plate_margin,
        maxx + plate_margin,
        maxy + plate_margin,
    )

    if clearance > 0:
        buffered_geometry = geometry.buffer(clearance)
    else:
        buffered_geometry = geometry

    mask_plate = plate.difference(buffered_geometry)

    if isinstance(mask_plate, MultiPolygon):
        polygons = list(mask_plate.geoms)
        mask_plate = max(polygons, key=lambda p: p.area)

    if not mask_plate.is_valid:
        mask_plate = mask_plate.buffer(0)

    return mask_plate


# ---------------------------------------------------------------------------
# Island detection
# ---------------------------------------------------------------------------

def detect_islands(plate: GeometryLike) -> List[Polygon]:
    """
    Return the set of hole polygons (interior rings) in *plate*.

    Each returned Polygon represents one cutout in the stencil. These are NOT
    floating islands of plate material — they are the artwork apertures.
    See detect_true_islands() for floating plate-material islands.
    """
    islands: List[Polygon] = []
    plate = _as_geometry(plate)

    for poly in _iter_polygons(plate):
        for interior in poly.interiors:
            island = Polygon(interior)
            if island.is_valid and not island.is_empty:
                islands.append(island)

    return islands


def detect_true_islands(plate: GeometryLike) -> List[Polygon]:
    """
    Detect regions of plate material that are completely enclosed by a cutout.

    Current placeholder. True islands are usually handled upstream by preserving
    contour hierarchy before mask plate generation.
    """
    return []


# ---------------------------------------------------------------------------
# Sprue / bridge generation
# ---------------------------------------------------------------------------

def _nearest_boundary_points(
    hole: Polygon,
    plate_exterior,
) -> Tuple[Point, Point]:
    """
    Return (point_on_hole_boundary, point_on_plate_exterior) that are mutually
    closest.
    """
    p_hole, p_ext = nearest_points(hole.exterior, plate_exterior)
    return p_hole, p_ext


def create_sprue_rectangle(
    point1: Point,
    point2: Point,
    width: float,
) -> Polygon:
    """
    Create a rectangular sprue between two points.
    """
    dx = point2.x - point1.x
    dy = point2.y - point1.y
    length = np.hypot(dx, dy)

    if length < 1e-9:
        return Polygon()

    ux, uy = dx / length, dy / length
    px, py = -uy, ux

    hw = width / 2.0
    corners = [
        (point1.x + px * hw, point1.y + py * hw),
        (point1.x - px * hw, point1.y - py * hw),
        (point2.x - px * hw, point2.y - py * hw),
        (point2.x + px * hw, point2.y + py * hw),
    ]
    return Polygon(corners)


def add_sprues(
    plate: GeometryLike,
    sprue_width: float,
    max_length: float,
    max_count: int = 10,
) -> Polygon:
    """
    Connect each hole (cutout) in *plate* to the plate exterior via a narrow
    channel, one sprue at a time.
    """
    plate = _as_geometry(plate)
    holes = detect_islands(plate)
    if not holes:
        return plate

    if isinstance(plate, MultiPolygon):
        plate = max(plate.geoms, key=lambda g: g.area)

    exterior = plate.exterior
    sprues_added = 0

    for hole in holes:
        if sprues_added >= max_count:
            break

        p_hole, p_ext = _nearest_boundary_points(hole, exterior)
        distance = p_hole.distance(p_ext)

        if distance > max_length:
            continue

        sprue = create_sprue_rectangle(p_hole, p_ext, sprue_width)
        if sprue.is_empty or not sprue.is_valid:
            continue

        candidate = plate.difference(sprue)

        if isinstance(candidate, MultiPolygon):
            candidate = max(candidate.geoms, key=lambda g: g.area)

        if not candidate.is_valid:
            candidate = candidate.buffer(0)

        if candidate.is_empty:
            continue

        plate = candidate
        exterior = plate.exterior
        sprues_added += 1

    return plate


# ---------------------------------------------------------------------------
# Alignment marks
# ---------------------------------------------------------------------------

def add_alignment_marks(
    plate: GeometryLike,
    mark_type: str,
    mark_size: float,
    offset_from_edge: float,
) -> Polygon:
    """
    Subtract alignment marks from the stencil plate corners.
    """
    plate = _as_geometry(plate)
    if isinstance(plate, MultiPolygon):
        plate = max(plate.geoms, key=lambda g: g.area)

    minx, miny, maxx, maxy = plate.bounds

    positions = [
        (minx + offset_from_edge, miny + offset_from_edge),
        (maxx - offset_from_edge, miny + offset_from_edge),
        (minx + offset_from_edge, maxy - offset_from_edge),
        (maxx - offset_from_edge, maxy - offset_from_edge),
    ]

    marks = []
    for x, y in positions:
        mt = mark_type.lower().replace(" ", "_")
        if mt in ("circular_hole", "circular hole"):
            mark = Point(x, y).buffer(mark_size / 2)
        else:
            h_line = box(
                x - mark_size / 2,
                y - mark_size / 10,
                x + mark_size / 2,
                y + mark_size / 10,
            )
            v_line = box(
                x - mark_size / 10,
                y - mark_size / 2,
                x + mark_size / 10,
                y + mark_size / 2,
            )
            mark = unary_union([h_line, v_line])
        marks.append(mark)

    marks_union = unary_union(marks)
    result = plate.difference(marks_union)

    if isinstance(result, MultiPolygon):
        result = max(result.geoms, key=lambda g: g.area)

    return result


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_plate_bounds(plate: GeometryLike) -> Tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) bounding box of *plate*."""
    return _as_geometry(plate).bounds
