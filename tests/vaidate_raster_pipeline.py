from __future__ import annotations

from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from raster_io import load_raster, normalize_canvas
from pipelines import RasterSilhouettePipeline
from geom2d import create_mask_plate
from mesh3d import extrude_to_mesh, validate_mesh, get_mesh_info


def validate_raster_image(image_path: Path):
    image_rgb, meta = load_raster(image_path)
    normalized_rgb, norm_meta = normalize_canvas(
        image_rgb,
        target_aspect_ratio=image_rgb.shape[1] / image_rgb.shape[0],
        fit_mode="contain",
        max_dim_px=1024,
        background=255,
    )

    settings = {
        "target_width_mm": 120.0,
        "auto_threshold": True,
        "invert": False,
        "blur_px": 1,
        "morph_open_px": 1,
        "morph_close_px": 2,
        "min_component_area_px": 32,
        "min_area_mm2": 0.75,
        "min_feature_mm": 0.25,
        "simplify_tolerance_mm": 0.15,
    }

    result = RasterSilhouettePipeline().run(normalized_rgb, settings)

    if result.geometry.is_empty:
        raise RuntimeError("Pipeline produced empty geometry.")

    plate = create_mask_plate(result.geometry, plate_margin=10.0, clearance=0.5)
    mesh = extrude_to_mesh(plate, thickness=2.0)

    is_valid, issues = validate_mesh(mesh)
    info = get_mesh_info(mesh)

    print(f"\nImage: {image_path.name}")
    print(f"Geometry polygons: {len(list(result.geometry.geoms))}")
    print(f"Mesh valid: {is_valid}")
    print(f"Issues: {issues}")
    print(f"Mesh info: {info}")


if __name__ == "__main__":
    raster_dir = Path(__file__).resolve().parent / "raster"
    if not raster_dir.exists():
        print("No tests/raster directory found.")
        raise SystemExit(0)

    for image_path in sorted(raster_dir.glob("*")):
        if image_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            validate_raster_image(image_path)