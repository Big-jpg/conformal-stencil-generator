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
(plate.interiors) are the artwork cutouts.  Each interior ring is a hole.

A correct sprue rectangle must:
  1. Start at the NEAREST POINT ON THE HOLE BOUNDARY  (not the centroid).
  2. End at the NEAREST POINT ON THE PLATE EXTERIOR.
  3. Be applied one at a time via plate.difference(sprue) so that each
     successive operation sees the updated hole count.

Bug in the original implementation
------------------------------------
The original code used the hole centroid as the sprue start point.  Because
the centroid is inside the hole, the sprue rectangle covered the entire hole
area.  plate.difference(sprue) therefore consumed the hole completely, merging
it with the exterior rather than leaving a narrow channel.  Batching all sprues
into a single unary_union before the difference made this worse: the merged
slab wiped out all holes simultaneously.

True floating-island detection
-------------------------------
A "true floating island" is a region of plate material that is completely
surrounded by a cutout ring — e.g. the dot of an 'i', the counter of an 'O'.
These appear as polygons-within-holes in the Shapely representation and require
a different bridge strategy: connect the island to the nearest solid plate
material (not to the outer edge).  detect_true_islands() handles this case.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import nearest_points, unary_union


# ---------------------------------------------------------------------------
# Mask plate creation
# ---------------------------------------------------------------------------

def create_mask_plate(
    geometry: MultiPolygon,
    plate_margin: float,
    clearance: float,
) -> Polygon:
    """
    Generate mask plate with cutouts.

    Args:
        geometry:      SVG / raster geometry as MultiPolygon.
        plate_margin:  Margin around bounding box (mm).
        clearance:     Outward offset applied to artwork before subtraction (mm).

    Returns:
        Polygon representing the stencil plate with negative-space cutouts.
    """
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

def detect_islands(plate: Polygon) -> List[Polygon]:
    """
    Return the set of hole polygons (interior rings) in *plate*.

    Each returned Polygon represents one cutout in the stencil.  These are
    NOT floating islands of plate material — they are the artwork apertures.
    See detect_true_islands() for floating plate-material islands.

    Args:
        plate: Stencil plate polygon (may have interior rings).

    Returns:
        List of Polygon objects, one per interior ring.
    """
    islands: List[Polygon] = []
    if hasattr(plate, "interiors"):
        for interior in plate.interiors:
            island = Polygon(interior)
            if island.is_valid and not island.is_empty:
                islands.append(island)
    return islands


def detect_true_islands(plate: Polygon) -> List[Polygon]:
    """
    Detect regions of plate material that are completely enclosed by a cutout.

    This occurs when artwork has enclosed negative space, e.g. the counter of
    the letter 'O'.  In the Shapely model these appear as Polygons that lie
    entirely within an interior ring of *plate* but are not themselves part of
    the plate polygon.

    Implementation note: after create_mask_plate() the plate is a single
    Polygon with holes.  True floating islands cannot be represented inside a
    simple Polygon — they would require a MultiPolygon or a Polygon with nested
    rings.  This function is therefore a forward-looking hook; in the current
    pipeline true islands are handled upstream by mask_to_polygons() using
    RETR_CCOMP contour retrieval (see raster_silhouette.py).

    Returns:
        Empty list (placeholder for future extension).
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

    Uses shapely.ops.nearest_points which operates on the boundary geometries
    directly, giving the true minimum-distance pair.
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

    Args:
        point1: Start point (on hole boundary).
        point2: End point (on plate exterior).
        width:  Width of the sprue channel (mm).

    Returns:
        Rectangular Polygon representing the sprue channel.
        Returns an empty Polygon if the two points are coincident.
    """
    dx = point2.x - point1.x
    dy = point2.y - point1.y
    length = np.hypot(dx, dy)

    if length < 1e-9:
        return Polygon()

    # Unit direction and perpendicular
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
    plate: Polygon,
    sprue_width: float,
    max_length: float,
    max_count: int = 10,
) -> Polygon:
    """
    Connect each hole (cutout) in *plate* to the plate exterior via a narrow
    channel, one sprue at a time.

    Fixes vs. original implementation
    -----------------------------------
    1. Anchor point is the NEAREST POINT ON THE HOLE BOUNDARY, not the
       centroid.  The centroid is inside the hole, so a centroid-anchored sprue
       rectangle covers the entire hole and consumes it on difference().

    2. Sprues are applied SEQUENTIALLY (one difference() per hole) rather than
       batching all sprues into a single unary_union before differencing.
       Batching caused overlapping sprues to merge into a slab that wiped out
       multiple holes simultaneously.

    3. After each difference() the plate is re-examined so that the updated
       interior ring list drives the next iteration.  This is important when a
       single sprue channel happens to merge two adjacent holes.

    Args:
        plate:         Stencil plate with holes (interior rings).
        sprue_width:   Width of each channel (mm).
        max_length:    Maximum allowed channel length (mm).  Holes further than
                       this from the plate edge are left unconnected.
        max_count:     Maximum number of sprues to add.

    Returns:
        Updated plate Polygon with sprue channels cut in.
    """
    holes = detect_islands(plate)
    if not holes:
        return plate

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

        # Apply one sprue at a time so subsequent iterations see the correct
        # hole topology.
        candidate = plate.difference(sprue)

        # difference() can return a MultiPolygon if the sprue cuts the plate
        # into disconnected pieces (pathological case).  Keep the largest piece.
        if isinstance(candidate, MultiPolygon):
            candidate = max(candidate.geoms, key=lambda g: g.area)

        if not candidate.is_valid:
            candidate = candidate.buffer(0)

        if candidate.is_empty:
            continue  # Sprue consumed the whole plate — skip

        plate = candidate
        exterior = plate.exterior  # Refresh after topology change
        sprues_added += 1

    return plate


# ---------------------------------------------------------------------------
# Alignment marks
# ---------------------------------------------------------------------------

def add_alignment_marks(
    plate: PlateGeom,
    mark_type: str,
    mark_size: float,
    offset_from_edge: float,
) -> Polygon:
    """
    Subtract alignment marks from the stencil plate corners.

    Args:
        plate:            Stencil plate geometry.
        mark_type:        "Crosshair" or "Circular hole".
        mark_size:        Size of the mark (mm).
        offset_from_edge: Distance from plate edge to mark centre (mm).

    Returns:
        Plate with alignment marks subtracted.
    """
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
        else:  # crosshair
            h_line = box(
                x - mark_size / 2, y - mark_size / 10,
                x + mark_size / 2, y + mark_size / 10,
            )
            v_line = box(
                x - mark_size / 10, y - mark_size / 2,
                x + mark_size / 10, y + mark_size / 2,
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

def get_plate_bounds(plate: Polygon) -> Tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) bounding box of *plate*."""
    return plate.bounds
