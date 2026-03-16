from __future__ import annotations

from pathlib import Path
from typing import Iterable

from shapely.geometry import MultiPolygon, Polygon


def _iter_polygons(geometry) -> Iterable[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    raise TypeError(f"Unsupported geometry type: {type(geometry)}")


def _ring_to_path_data(coords):
    pts = list(coords)
    if not pts:
        return ""
    first = pts[0]
    commands = [f"M {first[0]:.4f} {first[1]:.4f}"]
    for x, y in pts[1:]:
        commands.append(f"L {x:.4f} {y:.4f}")
    commands.append("Z")
    return " ".join(commands)


def multipolygon_to_svg(
    geometry,
    out_path: str | Path,
    width_mm: float,
    height_mm: float,
    fill: str = "black",
    background: str = "white",
) -> str:
    out_path = str(out_path)

    path_parts = []
    for poly in _iter_polygons(geometry):
        d = _ring_to_path_data(poly.exterior.coords)
        for interior in poly.interiors:
            d += " " + _ring_to_path_data(interior.coords)
        path_parts.append(f'<path d="{d}" fill="{fill}" fill-rule="evenodd"/>')

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
    <svg xmlns="http://www.w3.org/2000/svg"
        width="{width_mm}mm"
        height="{height_mm}mm"
        viewBox="0 0 {width_mm} {height_mm}">
    <rect x="0" y="0" width="{width_mm}" height="{height_mm}" fill="{background}" />
    {' '.join(path_parts)}
    </svg>
"""

    Path(out_path).write_text(svg, encoding="utf-8")
    return out_path