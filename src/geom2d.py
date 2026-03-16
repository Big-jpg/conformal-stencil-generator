# src/geom2d.py
"""
2D geometry operations module.
Handles mask plate generation, clearance offsets, island detection, and sprues.

Geometry model
--------------
After create_mask_plate() the plate is either:

  Polygon       — a single plate piece with zero or more interior rings
                  (holes = artwork cutouts).

  MultiPolygon  — the plate frame (largest polygon, with interior rings)
                  PLUS one or more floating islands of solid plate material
                  that sit inside a cutout.

Floating islands arise naturally from artwork that has enclosed negative
space — e.g. a whale-shark body (dark) with white spots.  After thresholding,
the body polygon has the spots as interior rings.  When the plate is
differenced by this polygon, Shapely's set algebra gives:

    plate - (body - spots) = (plate - body) + spots

The result is a MultiPolygon: the frame (plate with body hole) plus the spot
polygons as separate solid components.  This is the correct stencil geometry:
the body is a through-hole (paint passes) and the spots are raised solid
islands (paint does NOT pass through spots).

The original code discarded the island components with:
    mask_plate = max(polygons, key=lambda p: p.area)
This silently dropped all floating islands.  The fix is to preserve the full
MultiPolygon throughout the pipeline.

Sprue / bridge design intent
-----------------------------
A stencil "sprue" (also called a bridge or tie) is a narrow channel of
REMOVED material that runs from a closed hole in the plate to the plate's
outer edge.  Cutting this channel:
  - Allows the stencil to be peeled away from the substrate without tearing.
  - Keeps floating plate islands physically connected to the rest of the plate
    via the channel walls.

Sprue anchor point
------------------
The sprue rectangle must start at the NEAREST POINT ON THE HOLE BOUNDARY
(not the centroid).  The centroid is inside the hole; a centroid-anchored
sprue rectangle covers the entire hole and consumes it on difference().

Sprues are applied SEQUENTIALLY — one plate.difference(sprue) per hole —
so that each iteration sees the updated topology.
"""

from __future__ import annotations

from typing import List, Tuple, Union

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

# Type alias used throughout
PlateGeom = Union[Polygon, MultiPolygon]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _as_polygons(geom: PlateGeom) -> List[Polygon]:
    """Return a flat list of Polygon components."""
    if isinstance(geom, Polygon):
        return [geom]
    return list(geom.geoms)


def _largest_polygon(geom: PlateGeom) -> Polygon:
    """Return the largest-area Polygon component."""
    polys = _as_polygons(geom)
    return max(polys, key=lambda p: p.area)


def _rebuild_multipolygon(frame: Polygon, islands: List[Polygon]) -> PlateGeom:
    """
    Reconstruct the plate geometry from an updated frame and unchanged islands.

    If there are no islands, return the frame directly as a Polygon.
    """
    if not islands:
        return frame
    return MultiPolygon([frame] + islands)


def _count_holes(geom: PlateGeom) -> int:
    """Count total interior rings across all polygon components."""
    return sum(len(list(p.interiors)) for p in _as_polygons(geom))


def _total_area(geom: PlateGeom) -> float:
    return geom.area


# ---------------------------------------------------------------------------
# Mask plate creation
# ---------------------------------------------------------------------------

def create_mask_plate(
    geometry: MultiPolygon,
    plate_margin: float,
    clearance: float,
) -> PlateGeom:
    """
    Generate mask plate with cutouts.

    The result may be a Polygon or a MultiPolygon.  A MultiPolygon is
    returned when the artwork contains enclosed negative space (interior
    rings), which produce floating islands of solid plate material inside
    the cutout region.  All components are preserved — callers must handle
    both types.

    Args:
        geometry:      SVG / raster geometry as MultiPolygon.
        plate_margin:  Margin around bounding box (mm).
        clearance:     Outward offset applied to artwork before subtraction (mm).

    Returns:
        Polygon or MultiPolygon representing the stencil plate.
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

    # Do NOT drop MultiPolygon components here — they are floating islands.
    # Only clean up degenerate / invalid geometry.
    if not mask_plate.is_valid:
        mask_plate = mask_plate.buffer(0)

    # Remove any degenerate zero-area components that can arise from
    # numerical noise (but keep all components with meaningful area).
    if isinstance(mask_plate, MultiPolygon):
        clean = [p for p in mask_plate.geoms if p.area > 1e-6 and p.is_valid]
        if len(clean) == 0:
            # Degenerate — fall back to the bounding box
            return plate
        if len(clean) == 1:
            mask_plate = clean[0]
        else:
            mask_plate = MultiPolygon(clean)

    return mask_plate


# ---------------------------------------------------------------------------
# Island detection
# ---------------------------------------------------------------------------

def detect_islands(plate: PlateGeom) -> List[Polygon]:
    """
    Return the set of hole polygons (interior rings) in the plate FRAME.

    Each returned Polygon represents one cutout aperture in the stencil.
    This function operates on the largest polygon component (the frame) and
    returns its interior rings.

    Note: floating solid islands (separate Polygon components of a
    MultiPolygon plate) are NOT returned here — they are plate material,
    not cutouts.

    Args:
        plate: Stencil plate (Polygon or MultiPolygon).

    Returns:
        List of Polygon objects, one per interior ring of the frame.
    """
    frame = _largest_polygon(plate)
    islands: List[Polygon] = []
    for interior in frame.interiors:
        island = Polygon(interior)
        if island.is_valid and not island.is_empty:
            islands.append(island)
    return islands


def detect_true_islands(plate: PlateGeom) -> List[Polygon]:
    """
    Return floating solid islands — Polygon components of a MultiPolygon
    plate that are NOT the frame (largest component).

    These are regions of solid plate material enclosed within a cutout,
    e.g. the white spots of a whale shark inside the body cutout.

    Args:
        plate: Stencil plate (Polygon or MultiPolygon).

    Returns:
        List of island Polygons (empty if plate is a simple Polygon).
    """
    polys = _as_polygons(plate)
    if len(polys) <= 1:
        return []
    frame = max(polys, key=lambda p: p.area)
    return [p for p in polys if p is not frame]


# ---------------------------------------------------------------------------
# Sprue / bridge generation
# ---------------------------------------------------------------------------

def _nearest_boundary_points(
    hole: Polygon,
    plate_exterior,
) -> Tuple[Point, Point]:
    """
    Return (point_on_hole_boundary, point_on_plate_exterior) that are
    mutually closest.
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
        Rectangular Polygon.  Empty Polygon if points are coincident.
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
    plate: PlateGeom,
    sprue_width: float,
    max_length: float,
    max_count: int = 10,
) -> PlateGeom:
    """
    Connect each hole (cutout) in the plate FRAME to the plate exterior via
    a narrow channel, one sprue at a time.

    Floating solid islands (separate MultiPolygon components) are NOT
    modified — they are plate material, not holes.

    Args:
        plate:         Stencil plate (Polygon or MultiPolygon).
        sprue_width:   Width of each channel (mm).
        max_length:    Maximum allowed channel length (mm).
        max_count:     Maximum number of sprues to add.

    Returns:
        Updated plate with sprue channels cut in.
    """
    # Separate frame from floating islands
    polys = _as_polygons(plate)
    frame = max(polys, key=lambda p: p.area)
    solid_islands = [p for p in polys if p is not frame]

    holes = detect_islands(frame)
    if not holes:
        return plate

    exterior = frame.exterior
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

        candidate = frame.difference(sprue)

        if isinstance(candidate, MultiPolygon):
            # Sprue split the frame — keep the largest piece as the new frame
            # and collect any new solid islands
            candidate_polys = sorted(candidate.geoms, key=lambda g: g.area, reverse=True)
            frame = candidate_polys[0]
            # Any smaller pieces are new solid islands (rare but possible)
            solid_islands.extend(candidate_polys[1:])
        else:
            frame = candidate

        if not frame.is_valid:
            frame = frame.buffer(0)

        if frame.is_empty:
            break

        exterior = frame.exterior
        sprues_added += 1

    return _rebuild_multipolygon(frame, solid_islands)


# ---------------------------------------------------------------------------
# Alignment marks
# ---------------------------------------------------------------------------

def add_alignment_marks(
    plate: PlateGeom,
    mark_type: str,
    mark_size: float,
    offset_from_edge: float,
) -> PlateGeom:
    """
    Subtract alignment marks from the stencil plate corners.

    Operates on the FRAME (largest polygon component).  Floating solid
    islands are preserved unchanged.

    Args:
        plate:            Stencil plate geometry.
        mark_type:        "Crosshair" or "Circular hole".
        mark_size:        Size of the mark (mm).
        offset_from_edge: Distance from plate edge to mark centre (mm).

    Returns:
        Plate with alignment marks subtracted.
    """
    polys = _as_polygons(plate)
    frame = max(polys, key=lambda p: p.area)
    solid_islands = [p for p in polys if p is not frame]

    minx, miny, maxx, maxy = frame.bounds

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
    result = frame.difference(marks_union)

    if isinstance(result, MultiPolygon):
        # Marks split the frame — keep largest piece
        result = max(result.geoms, key=lambda g: g.area)

    return _rebuild_multipolygon(result, solid_islands)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_plate_bounds(plate: PlateGeom) -> Tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) bounding box of *plate*."""
    return plate.bounds
