"""
SVG parsing module.
Converts SVG paths to 2D polygons using svgpathtools and shapely.
"""

from typing import List, Tuple, Union
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
import svgpathtools


def load_svg(filepath: Union[str, Path]) -> Tuple[MultiPolygon, dict]:
    """
    Load SVG file and extract filled paths as polygons.
    
    Args:
        filepath: Path to SVG file
        
    Returns:
        Tuple of (MultiPolygon of extracted shapes, metadata dict)
        
    Raises:
        ValueError: If SVG is invalid or contains no closed paths
        FileNotFoundError: If file does not exist
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"SVG file not found: {filepath}")
    
    # Parse SVG using svgpathtools
    try:
        paths, attributes = svgpathtools.svg2paths(str(filepath))
    except Exception as e:
        raise ValueError(f"Failed to parse SVG: {e}")
    
    if not paths:
        raise ValueError("SVG contains no paths")
    
    # Convert paths to polygons
    polygons = []
    for path in paths:
        try:
            poly = path_to_polygon(path, num_samples=100)
            if poly and poly.is_valid and not poly.is_empty:
                polygons.append(poly)
        except Exception as e:
            # Skip invalid paths but continue processing
            print(f"Warning: Skipping invalid path: {e}")
            continue
    
    if not polygons:
        raise ValueError("No valid closed paths found in SVG")
    
    # Union all polygons into a single MultiPolygon
    unified = unary_union(polygons)
    
    # Ensure result is MultiPolygon
    if isinstance(unified, Polygon):
        unified = MultiPolygon([unified])
    
    # Calculate metadata
    bounds = unified.bounds  # (minx, miny, maxx, maxy)
    metadata = {
        'num_paths': len(paths),
        'num_valid_polygons': len(polygons),
        'bounds': bounds,
        'width': bounds[2] - bounds[0],
        'height': bounds[3] - bounds[1],
        'area': unified.area
    }
    
    return unified, metadata


def path_to_polygon(path: svgpathtools.Path, num_samples: int = 100) -> Polygon:
    """
    Convert SVG path to Shapely polygon by sampling points.
    
    Args:
        path: svgpathtools Path object
        num_samples: Number of points to sample along the path
        
    Returns:
        Shapely Polygon object
        
    Raises:
        ValueError: If path cannot be converted to valid polygon
    """
    if not path:
        raise ValueError("Empty path")
    
    # Sample points along the path
    points = []
    for i in range(num_samples):
        t = i / num_samples
        point = path.point(t)
        # Convert complex number to (x, y) tuple
        points.append((point.real, point.imag))
    
    # Close the path if not already closed
    if points[0] != points[-1]:
        points.append(points[0])
    
    # Create polygon
    if len(points) < 4:  # Need at least 3 unique points + closing point
        raise ValueError("Path has too few points to form a polygon")
    
    poly = Polygon(points)
    
    # Validate
    if not poly.is_valid:
        # Try to fix with buffer(0) trick
        poly = poly.buffer(0)
        if not poly.is_valid:
            raise ValueError("Path resulted in invalid polygon")
    
    return poly


def svg_to_polygons(svg_data: Union[str, Path]) -> List[Polygon]:
    """
    Convert SVG file to list of Shapely polygons (without union).
    
    Args:
        svg_data: SVG file path
        
    Returns:
        List of Polygon objects
        
    Raises:
        ValueError: If SVG is invalid
    """
    svg_data = Path(svg_data)
    
    try:
        paths, _ = svgpathtools.svg2paths(str(svg_data))
    except Exception as e:
        raise ValueError(f"Failed to parse SVG: {e}")
    
    polygons = []
    for path in paths:
        try:
            poly = path_to_polygon(path)
            if poly and poly.is_valid and not poly.is_empty:
                polygons.append(poly)
        except Exception:
            continue
    
    return polygons


def get_svg_bounds(geometry: Union[Polygon, MultiPolygon]) -> Tuple[float, float, float, float]:
    """
    Get bounding box of SVG geometry.
    
    Args:
        geometry: Shapely Polygon or MultiPolygon
        
    Returns:
        Tuple of (minx, miny, maxx, maxy)
    """
    return geometry.bounds
