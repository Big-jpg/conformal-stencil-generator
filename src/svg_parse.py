"""
SVG parsing module.
Converts SVG paths to 2D polygons using svgpathtools and shapely.
"""

from typing import List, Tuple
from shapely.geometry import Polygon, MultiPolygon
import svgpathtools


def load_svg(filepath: str) -> MultiPolygon:
    """
    Load SVG file and extract filled paths as polygons.
    
    Args:
        filepath: Path to SVG file
        
    Returns:
        MultiPolygon of extracted shapes
        
    Raises:
        ValueError: If SVG is invalid or contains no closed paths
    """
    # TODO: Implement SVG parsing
    raise NotImplementedError("Milestone 1: SVG Import & 2D Preview")


def svg_to_polygons(svg_data: str) -> List[Polygon]:
    """
    Convert SVG path data to list of Shapely polygons.
    
    Args:
        svg_data: SVG XML string or file path
        
    Returns:
        List of Polygon objects
    """
    # TODO: Implement path-to-polygon conversion
    raise NotImplementedError("Milestone 1: SVG Import & 2D Preview")
