# src/mesh3d.py
"""
3D mesh operations module.
Handles extrusion, mesh merging, and STL export.

Extrusion strategy
------------------
trimesh.creation.extrude_polygon uses mapbox-earcut to triangulate the top
and bottom cap faces.  earcut is fast but unreliable for polygons with many
holes (>~4): it leaves open boundary loops, producing a non-watertight mesh
(Euler number < 0).

The robust path is:
  1. Extrude the exterior ring as a solid watertight prism.
  2. For each interior ring (hole), extrude it as a solid prism and
     boolean-subtract it from the result using manifold3d.

manifold3d guarantees watertight output for valid boolean operands.
For polygons with 0–3 holes the earcut path is used as a fast fallback
(it is reliable for small hole counts and avoids the boolean overhead).
"""

from __future__ import annotations

from typing import Tuple, Union

import numpy as np
import trimesh
from shapely.geometry import MultiPolygon, Polygon

# Threshold: use boolean subtraction path when hole count exceeds this value.
# earcut is reliable up to ~3 holes in practice.
_EARCUT_HOLE_LIMIT = 3


def _extrude_solid(poly: Polygon, height: float) -> trimesh.Trimesh:
    """Extrude a simple (no-hole) polygon to a watertight solid."""
    simple = Polygon(poly.exterior)
    mesh = trimesh.creation.extrude_polygon(simple, height=height)
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh)
        trimesh.repair.fix_normals(mesh)
        mesh.remove_infinite_values()
        mesh.merge_vertices()
    return mesh


def extrude_to_mesh(
    geometry_2d: Union[Polygon, MultiPolygon],
    thickness: float,
) -> trimesh.Trimesh:
    """
    Convert a 2D Shapely Polygon (possibly with interior holes) to a 3D mesh
    by extrusion.

    Uses manifold3d boolean subtraction for polygons with many holes to
    guarantee a watertight result.  Falls back to earcut for simple cases.

    For MultiPolygon input (plate frame + floating solid islands), each
    component is extruded separately and the meshes are concatenated.

    Args:
        geometry_2d: 2D Shapely Polygon or MultiPolygon.
        thickness:   Extrusion height in mm.

    Returns:
        trimesh.Trimesh — watertight where possible.

    Raises:
        ValueError: If geometry is invalid/empty or extrusion fails.
    """
    if geometry_2d is None:
        raise ValueError("Input geometry is None")

    if thickness <= 0:
        raise ValueError("Thickness must be positive")

    # MultiPolygon: extrude each component separately and concatenate.
    # Components are geometrically disjoint (separate solid islands + frame),
    # so they must NOT be merged with merge_vertices — that would weld shared
    # boundary vertices between adjacent solids and create non-manifold edges.
    # Use a minimum area threshold to discard degenerate slivers from sprues.
    _MIN_COMPONENT_AREA = 0.5  # mm²
    if isinstance(geometry_2d, MultiPolygon):
        meshes = []
        for poly in geometry_2d.geoms:
            if poly.is_empty or poly.area < _MIN_COMPONENT_AREA:
                continue
            meshes.append(_extrude_single_polygon(poly, thickness))
        if not meshes:
            raise ValueError("MultiPolygon has no valid components")
        if len(meshes) == 1:
            return meshes[0]
        # Concatenate without merging — each component is an independent solid.
        # trimesh.Scene.dump() or STL export handles multi-body meshes correctly.
        combined = trimesh.util.concatenate(meshes)
        combined.remove_unreferenced_vertices()
        return combined

    return _extrude_single_polygon(geometry_2d, thickness)


def _extrude_single_polygon(
    geometry_2d: Polygon,
    thickness: float,
) -> trimesh.Trimesh:
    """Extrude a single Shapely Polygon (may have interior rings)."""
    if not geometry_2d.is_valid:
        geometry_2d = geometry_2d.buffer(0)
        if not geometry_2d.is_valid:
            raise ValueError("Input geometry is not valid")

    if geometry_2d.is_empty:
        raise ValueError("Input geometry is empty")

    holes = list(geometry_2d.interiors)
    n_holes = len(holes)

    try:
        if n_holes <= _EARCUT_HOLE_LIMIT:
            # Fast path: earcut handles small hole counts reliably
            mesh = trimesh.creation.extrude_polygon(geometry_2d, height=thickness)
            if not mesh.is_watertight:
                trimesh.repair.fill_holes(mesh)
                trimesh.repair.fix_normals(mesh)
                mesh.remove_infinite_values()
                mesh.merge_vertices()
            return mesh

        # Robust path: extrude exterior solid, then subtract each hole
        result = _extrude_solid(geometry_2d, thickness)

        for interior in holes:
            hole_poly = Polygon(interior)
            if hole_poly.area < 1e-6:
                continue  # skip degenerate rings
            hole_mesh = _extrude_solid(hole_poly, thickness)
            try:
                result = result.difference(hole_mesh, engine="manifold")
            except Exception:
                # manifold failed for this hole; try trimesh boolean
                try:
                    result = trimesh.boolean.difference([result, hole_mesh], engine="blender")
                except Exception:
                    pass  # leave hole uncut rather than crash

        if not result.is_watertight:
            trimesh.repair.fill_holes(result)
            trimesh.repair.fix_normals(result)
            result.remove_infinite_values()
            result.merge_vertices()

        return result

    except Exception as exc:
        raise ValueError(f"Failed to extrude geometry: {exc}") from exc


def merge_meshes(meshes: list) -> trimesh.Trimesh:
    """
    Merge multiple mesh objects into a single mesh.

    Args:
        meshes: List of trimesh objects.

    Returns:
        Single merged trimesh.

    Raises:
        ValueError: If meshes list is empty or merging fails.
    """
    if not meshes:
        raise ValueError("No meshes to merge")

    if len(meshes) == 1:
        return meshes[0]

    try:
        merged = trimesh.util.concatenate(meshes)
        merged.merge_vertices()
        merged.remove_unreferenced_vertices()
        return merged
    except Exception as exc:
        raise ValueError(f"Failed to merge meshes: {exc}") from exc


def export_stl(mesh: trimesh.Trimesh, output_path: str) -> None:
    """
    Export mesh to STL file.

    Exports regardless of watertight status — validation is the caller's
    responsibility.  Issues a warning to stdout if the mesh has problems.

    Args:
        mesh:        trimesh object.
        output_path: Destination path for binary STL.

    Raises:
        ValueError: If export fails.
    """
    is_valid, message = validate_mesh(mesh)
    if not is_valid:
        # Attempt light repair before export
        trimesh.repair.fill_holes(mesh)
        trimesh.repair.fix_normals(mesh)
        mesh.remove_infinite_values()
        mesh.merge_vertices()
        is_valid, message = validate_mesh(mesh)
        if not is_valid:
            print(f"Warning: exporting non-ideal mesh — {message}")

    try:
        mesh.export(output_path, file_type="stl")
    except Exception as exc:
        raise ValueError(f"Failed to export STL: {exc}") from exc


def validate_mesh(mesh: trimesh.Trimesh) -> Tuple[bool, str]:
    """
    Validate mesh for printability.

    Args:
        mesh: trimesh object.

    Returns:
        (is_valid, message) tuple.
    """
    if mesh is None:
        return False, "Mesh is None"
    if len(mesh.vertices) == 0:
        return False, "Mesh has no vertices"
    if len(mesh.faces) == 0:
        return False, "Mesh has no faces"

    issues = []

    if not mesh.is_watertight:
        issues.append("Mesh is not watertight")

    if hasattr(mesh, "degenerate_faces") and np.any(mesh.degenerate_faces):
        n = int(np.sum(mesh.degenerate_faces))
        issues.append(f"{n} degenerate faces")

    if not np.isfinite(mesh.vertices).all():
        issues.append("Mesh contains infinite or NaN vertex values")

    try:
        if mesh.is_watertight and mesh.volume <= 0:
            issues.append(f"Invalid volume: {mesh.volume:.3f}")
    except Exception:
        pass

    if issues:
        return False, "; ".join(issues)
    return True, "Mesh is valid and printable"


def get_mesh_info(mesh: trimesh.Trimesh) -> dict:
    """
    Return mesh statistics.

    Args:
        mesh: trimesh object.

    Returns:
        Dictionary with vertices, faces, watertight, volume, surface_area,
        bounds, center_mass.
    """
    return {
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "watertight": mesh.is_watertight,
        "volume": mesh.volume if mesh.is_watertight else 0.0,
        "surface_area": mesh.area,
        "bounds": mesh.bounds.tolist(),
        "center_mass": mesh.center_mass.tolist() if mesh.is_watertight else [0.0, 0.0, 0.0],
    }
