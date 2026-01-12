"""
2D geometry operations module.
Handles mask plate generation, clearance offsets, island detection, and sprues.
"""

from typing import List, Tuple, Optional
from shapely.geometry import Polygon, MultiPolygon, box, Point, LineString
from shapely.ops import unary_union
import numpy as np


def create_mask_plate(
    geometry: MultiPolygon,
    plate_margin: float,
    clearance: float
) -> Polygon:
    """
    Generate mask plate with cutouts.
    
    Args:
        geometry: SVG geometry as MultiPolygon
        plate_margin: Margin around bounding box (mm)
        clearance: Offset around art (mm)
        
    Returns:
        Polygon representing the stencil plate with negative space
    """
    # Get bounding box of input geometry
    minx, miny, maxx, maxy = geometry.bounds
    
    # Create outer plate rectangle with margin
    plate = box(
        minx - plate_margin,
        miny - plate_margin,
        maxx + plate_margin,
        maxy + plate_margin
    )
    
    # Apply clearance buffer to geometry
    if clearance > 0:
        # Positive buffer expands the geometry
        buffered_geometry = geometry.buffer(clearance)
    else:
        buffered_geometry = geometry
    
    # Subtract buffered geometry from plate to create negative space
    mask_plate = plate.difference(buffered_geometry)
    
    # Ensure result is a valid Polygon
    if isinstance(mask_plate, MultiPolygon):
        # If result is MultiPolygon, take the largest polygon (the plate)
        # This can happen if clearance creates disconnected regions
        polygons = list(mask_plate.geoms)
        mask_plate = max(polygons, key=lambda p: p.area)
    
    if not mask_plate.is_valid:
        mask_plate = mask_plate.buffer(0)  # Fix invalid geometry
    
    return mask_plate


def detect_islands(geometry: Polygon) -> List[Polygon]:
    """
    Identify disconnected void regions (holes) in the stencil.
    
    Args:
        geometry: Stencil geometry (plate with holes)
        
    Returns:
        List of disconnected island polygons (the holes)
    """
    islands = []
    
    # Extract all interior rings (holes) from the polygon
    if hasattr(geometry, 'interiors'):
        for interior in geometry.interiors:
            # Convert interior ring to polygon
            island = Polygon(interior)
            if island.is_valid and not island.is_empty:
                islands.append(island)
    
    return islands


def add_sprues(
    plate: Polygon,
    sprue_width: float,
    max_length: float,
    max_count: int = 10
) -> Polygon:
    """
    Connect disconnected islands (holes) using rectangular sprues.
    
    Uses nearest-neighbor strategy to connect holes to plate exterior.
    
    Args:
        plate: Stencil plate geometry with holes
        sprue_width: Width of connecting sprues (mm)
        max_length: Maximum sprue length (mm)
        max_count: Maximum number of sprues to add
        
    Returns:
        Plate geometry with sprues added (holes connected to exterior)
    """
    # Detect islands (holes)
    islands = detect_islands(plate)
    
    if not islands:
        return plate  # No islands to connect
    
    # Get exterior boundary of plate
    exterior = plate.exterior
    
    # Generate sprues for each island
    sprues = []
    for i, island in enumerate(islands[:max_count]):
        # Find nearest point on exterior to island centroid
        island_center = island.centroid
        
        # Find closest point on exterior to island center
        nearest_point = exterior.interpolate(exterior.project(island_center))
        
        # Calculate distance
        distance = island_center.distance(nearest_point)
        
        # Only add sprue if within max_length
        if distance <= max_length:
            # Create rectangular sprue connecting island to exterior
            sprue = create_sprue_rectangle(
                island_center,
                Point(nearest_point.x, nearest_point.y),
                sprue_width
            )
            sprues.append(sprue)
    
    # Union sprues with plate (subtract sprues from plate to create channels)
    if sprues:
        sprue_union = unary_union(sprues)
        plate = plate.difference(sprue_union)
    
    return plate


def create_sprue_rectangle(
    point1: Point,
    point2: Point,
    width: float
) -> Polygon:
    """
    Create a rectangular sprue between two points.
    
    Args:
        point1: Start point
        point2: End point
        width: Width of the sprue
        
    Returns:
        Rectangular polygon representing the sprue
    """
    # Calculate direction vector
    dx = point2.x - point1.x
    dy = point2.y - point1.y
    length = np.sqrt(dx**2 + dy**2)
    
    if length == 0:
        # Points are the same, return empty polygon
        return Polygon()
    
    # Normalize direction
    dx /= length
    dy /= length
    
    # Perpendicular vector (rotated 90 degrees)
    perp_x = -dy
    perp_y = dx
    
    # Calculate half-width offset
    hw = width / 2
    
    # Calculate rectangle corners
    corners = [
        (point1.x + perp_x * hw, point1.y + perp_y * hw),
        (point1.x - perp_x * hw, point1.y - perp_y * hw),
        (point2.x - perp_x * hw, point2.y - perp_y * hw),
        (point2.x + perp_x * hw, point2.y + perp_y * hw),
    ]
    
    return Polygon(corners)


def add_alignment_marks(
    plate: Polygon,
    mark_type: str,
    mark_size: float,
    offset_from_edge: float
) -> Polygon:
    """
    Add alignment marks to the stencil plate.
    
    Args:
        plate: Stencil plate geometry
        mark_type: "crosshair" or "circular_hole"
        mark_size: Size of the mark (mm)
        offset_from_edge: Distance from plate edge (mm)
        
    Returns:
        Plate with alignment marks subtracted
    """
    # Get plate bounds
    minx, miny, maxx, maxy = plate.bounds
    
    # Calculate mark positions (corners with offset)
    positions = [
        (minx + offset_from_edge, miny + offset_from_edge),  # Bottom-left
        (maxx - offset_from_edge, miny + offset_from_edge),  # Bottom-right
        (minx + offset_from_edge, maxy - offset_from_edge),  # Top-left
        (maxx - offset_from_edge, maxy - offset_from_edge),  # Top-right
    ]
    
    marks = []
    
    for x, y in positions:
        if mark_type.lower() == "circular_hole" or mark_type.lower() == "circular hole":
            # Create circular hole
            mark = Point(x, y).buffer(mark_size / 2)
        else:  # crosshair
            # Create crosshair as two intersecting rectangles
            h_line = box(x - mark_size/2, y - mark_size/10, x + mark_size/2, y + mark_size/10)
            v_line = box(x - mark_size/10, y - mark_size/2, x + mark_size/10, y + mark_size/2)
            mark = unary_union([h_line, v_line])
        
        marks.append(mark)
    
    # Subtract marks from plate
    marks_union = unary_union(marks)
    plate = plate.difference(marks_union)
    
    return plate


def get_plate_bounds(plate: Polygon) -> Tuple[float, float, float, float]:
    """
    Get bounding box of plate.
    
    Args:
        plate: Plate geometry
        
    Returns:
        Tuple of (minx, miny, maxx, maxy)
    """
    return plate.bounds
