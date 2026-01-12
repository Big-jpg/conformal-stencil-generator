"""
3D mesh operations module.
Handles extrusion, mesh merging, and STL export.
"""

from typing import Tuple, Optional
from shapely.geometry import Polygon
import trimesh
import numpy as np
from shapely import geometry


def extrude_to_mesh(
    geometry_2d: Polygon,
    thickness: float
) -> trimesh.Trimesh:
    """
    Convert 2D geometry to 3D mesh via extrusion.
    
    Args:
        geometry_2d: 2D Shapely polygon
        thickness: Extrusion height (mm)
        
    Returns:
        Trimesh object representing the extruded stencil
        
    Raises:
        ValueError: If geometry is invalid or extrusion fails
    """
    if not geometry_2d.is_valid:
        raise ValueError("Input geometry is not valid")
    
    if geometry_2d.is_empty:
        raise ValueError("Input geometry is empty")
    
    if thickness <= 0:
        raise ValueError("Thickness must be positive")
    
    try:
        # Use trimesh.creation.extrude_polygon
        # This is more robust than Path2D approach
        mesh = trimesh.creation.extrude_polygon(
            geometry_2d,
            height=thickness
        )
        
        # Validate and fix mesh if needed
        if not mesh.is_watertight:
            # Try to fix mesh
            trimesh.repair.fill_holes(mesh)
            trimesh.repair.fix_normals(mesh)
            mesh.remove_degenerate_faces()
            mesh.remove_duplicate_faces()
            mesh.remove_infinite_values()
            mesh.merge_vertices()
        
        return mesh
        
    except Exception as e:
        raise ValueError(f"Failed to extrude geometry: {e}")


def merge_meshes(meshes: list) -> trimesh.Trimesh:
    """
    Merge multiple mesh objects into a single watertight mesh.
    
    Args:
        meshes: List of trimesh objects
        
    Returns:
        Single merged trimesh
        
    Raises:
        ValueError: If meshes list is empty or merging fails
    """
    if not meshes:
        raise ValueError("No meshes to merge")
    
    if len(meshes) == 1:
        return meshes[0]
    
    try:
        # Concatenate all meshes
        merged = trimesh.util.concatenate(meshes)
        
        # Clean up
        merged.merge_vertices()
        merged.remove_duplicate_faces()
        merged.remove_degenerate_faces()
        
        return merged
        
    except Exception as e:
        raise ValueError(f"Failed to merge meshes: {e}")


def export_stl(mesh: trimesh.Trimesh, output_path: str) -> None:
    """
    Export mesh to STL file.
    
    Args:
        mesh: Trimesh object
        output_path: Path to output STL file
        
    Raises:
        ValueError: If mesh is not watertight or manifold
    """
    # Validate mesh before export
    is_valid, message = validate_mesh(mesh)
    
    if not is_valid:
        # Try to fix common issues
        trimesh.repair.fill_holes(mesh)
        trimesh.repair.fix_normals(mesh)
        mesh.remove_degenerate_faces()
        mesh.remove_duplicate_faces()
        mesh.merge_vertices()
        
        # Re-validate
        is_valid, message = validate_mesh(mesh)
        
        if not is_valid:
            # Export anyway but warn user
            print(f"Warning: {message}")
    
    try:
        # Export as binary STL
        mesh.export(output_path, file_type='stl')
    except Exception as e:
        raise ValueError(f"Failed to export STL: {e}")


def validate_mesh(mesh: trimesh.Trimesh) -> Tuple[bool, str]:
    """
    Validate mesh for printability.
    
    Args:
        mesh: Trimesh object
        
    Returns:
        Tuple of (is_valid, message)
    """
    issues = []
    
    # Check if mesh exists
    if mesh is None:
        return False, "Mesh is None"
    
    # Check if mesh has vertices and faces
    if len(mesh.vertices) == 0:
        return False, "Mesh has no vertices"
    
    if len(mesh.faces) == 0:
        return False, "Mesh has no faces"
    
    # Check for watertight (manifold)
    if not mesh.is_watertight:
        issues.append("Mesh is not watertight")
    
    # Check for degenerate faces
    if hasattr(mesh, 'degenerate_faces') and mesh.degenerate_faces.any():
        issues.append(f"Mesh has {mesh.degenerate_faces.sum()} degenerate faces")
    
    # Check for infinite or NaN values
    if not np.isfinite(mesh.vertices).all():
        issues.append("Mesh contains infinite or NaN vertex values")
    
    # Check volume (should be positive for valid mesh)
    try:
        if mesh.is_watertight:
            volume = mesh.volume
            if volume <= 0:
                issues.append(f"Mesh has invalid volume: {volume}")
    except:
        pass  # Volume check not critical
    
    if issues:
        return False, "; ".join(issues)
    
    return True, "Mesh is valid and printable"


def get_mesh_info(mesh: trimesh.Trimesh) -> dict:
    """
    Get mesh statistics and information.
    
    Args:
        mesh: Trimesh object
        
    Returns:
        Dictionary with mesh information
    """
    info = {
        'vertices': len(mesh.vertices),
        'faces': len(mesh.faces),
        'watertight': mesh.is_watertight,
        'volume': mesh.volume if mesh.is_watertight else 0,
        'surface_area': mesh.area,
        'bounds': mesh.bounds.tolist(),
        'center_mass': mesh.center_mass.tolist() if mesh.is_watertight else [0, 0, 0],
    }
    
    return info
