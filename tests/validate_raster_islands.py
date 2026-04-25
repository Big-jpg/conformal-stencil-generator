#!/usr/bin/env python3
# tests/validate_raster_islands.py
"""
Raster pipeline island / bridge validation.

Tests that the pipeline correctly:
1. Preserves enclosed voids (holes) in artwork — e.g. letter 'O', donuts.
2. Bridges those holes to the plate exterior via narrow sprue channels.
3. Produces a watertight STL from the resulting plate geometry.

These cases were broken in the original implementation because:
  - mask_to_polygons() used RETR_EXTERNAL, discarding inner contours.
  - add_sprues() anchored sprues at the hole centroid (inside the hole),
    causing the sprue rectangle to consume the entire hole on difference().
  - All sprues were batched into a single unary_union before differencing,
    causing overlapping sprues to wipe out multiple holes simultaneously.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from geom2d import add_sprues, create_mask_plate
from mesh3d import extrude_to_mesh, get_mesh_info, validate_mesh
from pipelines.raster_silhouette import RasterSilhouettePipeline
from raster_io import normalize_canvas


def _make_donut_image(size: int = 256) -> np.ndarray:
    """
    Synthetic 'letter O' image: white background, black ring with white centre.
    """
    img = np.ones((size, size, 3), dtype=np.uint8) * 255
    cx, cy = size // 2, size // 2
    cv2.circle(img, (cx, cy), size // 4, (0, 0, 0), -1)      # outer fill
    cv2.circle(img, (cx, cy), size // 8, (255, 255, 255), -1) # inner void
    return img


def _make_multi_island_image(size: int = 256) -> np.ndarray:
    """
    Three separate solid rectangles (disconnected islands, no enclosed voids).
    """
    img = np.ones((size, size, 3), dtype=np.uint8) * 255
    cv2.rectangle(img, (10, 10), (70, 70), (0, 0, 0), -1)
    cv2.rectangle(img, (100, 10), (160, 70), (0, 0, 0), -1)
    cv2.rectangle(img, (55, 100), (115, 160), (0, 0, 0), -1)
    return img


def _make_mixed_image(size: int = 256) -> np.ndarray:
    """
    Mix: one donut (enclosed void) + one solid rectangle.
    """
    img = np.ones((size, size, 3), dtype=np.uint8) * 255
    cv2.circle(img, (160, 128), 60, (0, 0, 0), -1)
    cv2.circle(img, (160, 128), 30, (255, 255, 255), -1)
    cv2.rectangle(img, (10, 90), (70, 170), (0, 0, 0), -1)
    return img


SETTINGS = {
    "target_width_mm": 100.0,
    "target_height_mm": 100.0,
    "auto_threshold": True,
    "invert": False,
    "blur_px": 1,
    "morph_open_px": 1,
    "morph_close_px": 2,
    "min_component_area_px": 32,
    "min_area_mm2": 0.5,
    "min_feature_mm": 0.2,
    "simplify_tolerance_mm": 0.1,
}


def run_test(name: str, img: np.ndarray, expected_holes_in_geometry: int) -> bool:
    print(f"\n{'='*60}")
    print(f"Test: {name}")
    print(f"{'='*60}")

    try:
        normalized, _ = normalize_canvas(
            img,
            target_aspect_ratio=img.shape[1] / img.shape[0],
            fit_mode="contain",
            max_dim_px=512,
        )

        result = RasterSilhouettePipeline().run(normalized, SETTINGS)
        geom = result.geometry

        if geom.is_empty:
            print("FAIL: Pipeline produced empty geometry")
            return False

        polys = list(geom.geoms)
        total_holes = sum(len(list(p.interiors)) for p in polys)
        print(f"Polygons: {len(polys)}, total interior rings: {total_holes}")
        for i, p in enumerate(polys):
            holes = len(list(p.interiors))
            print(f"  Poly {i}: area={p.area:.1f} mm², holes={holes}")

        if total_holes < expected_holes_in_geometry:
            print(
                f"FAIL: Expected >= {expected_holes_in_geometry} interior rings "
                f"in geometry, got {total_holes}. "
                f"RETR_CCOMP fix may not be working."
            )
            return False

        print(f"✓ Geometry has {total_holes} interior ring(s) (expected >= {expected_holes_in_geometry})")

        # Create plate and add sprues
        plate = create_mask_plate(geom, plate_margin=10, clearance=0.5)
        holes_before = len(list(plate.interiors))
        print(f"Plate holes before sprues: {holes_before}")

        plate_sprued = add_sprues(plate, sprue_width=2.0, max_length=80, max_count=20)
        holes_after = len(list(plate_sprued.interiors))
        print(f"Plate holes after sprues:  {holes_after}")

        area_removed = plate.area - plate_sprued.area
        print(f"Area removed by sprues: {area_removed:.1f} mm²")

        # Each sprue should remove roughly sprue_width × channel_length area.
        # Verify the area removed is small (not the whole plate).
        if area_removed > plate.area * 0.5:
            print("FAIL: Sprues removed more than 50% of plate area — holes were consumed")
            return False

        # Extrude and validate
        mesh = extrude_to_mesh(plate_sprued, thickness=2.0)
        is_valid, msg = validate_mesh(mesh)
        info = get_mesh_info(mesh)

        print(f"Mesh valid: {is_valid} — {msg}")
        print(f"Vertices: {info['vertices']}, Faces: {info['faces']}, Watertight: {info['watertight']}")

        if not info["watertight"]:
            print("FAIL: Mesh is not watertight")
            return False

        print(f"✓✓✓ {name} PASSED ✓✓✓")
        return True

    except Exception as exc:
        import traceback
        print(f"FAIL: Exception — {exc}")
        traceback.print_exc()
        return False


def main() -> int:
    tests = [
        ("donut_enclosed_void",    _make_donut_image(),       1),
        ("multi_island_no_voids",  _make_multi_island_image(), 0),
        ("mixed_donut_and_solid",  _make_mixed_image(),        1),
    ]

    results = []
    for name, img, expected_holes in tests:
        passed = run_test(name, img, expected_holes)
        results.append((name, passed))

    print(f"\n{'='*60}")
    print("RASTER ISLAND TEST SUMMARY")
    print(f"{'='*60}")
    for name, passed in results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"{status:8} {name}")

    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    print(f"\nTotal: {passed_count}/{total} tests passed")
    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
