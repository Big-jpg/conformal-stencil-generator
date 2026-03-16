from pathlib import Path
import sys
import tempfile

# Add src to path BEFORE importing local src modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

import matplotlib.pyplot as plt
import streamlit as st
from shapely.geometry import MultiPolygon, Polygon

from geom2d import add_alignment_marks, add_sprues, create_mask_plate
from mesh3d import export_stl, extrude_to_mesh, get_mesh_info, validate_mesh
from pipelines import RasterSilhouettePipeline
from raster_io import load_raster, normalize_canvas
from svg_parse import load_svg


# Page configuration
st.set_page_config(
    page_title="Conformal Stencil Generator",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Initialize session state
if "geometry" not in st.session_state:
    st.session_state.geometry = None
if "metadata" not in st.session_state:
    st.session_state.metadata = None
if "mask_plate" not in st.session_state:
    st.session_state.mask_plate = None
if "mesh" not in st.session_state:
    st.session_state.mesh = None
if "stl_path" not in st.session_state:
    st.session_state.stl_path = None
if "debug_images" not in st.session_state:
    st.session_state.debug_images = {}
if "uploaded_filename" not in st.session_state:
    st.session_state.uploaded_filename = None
if "input_kind" not in st.session_state:
    st.session_state.input_kind = None
if "uploaded_file_signature" not in st.session_state:
    st.session_state.uploaded_file_signature = None


# Title and description
st.title("🎨 Flexible Conformal Stencil Generator")
st.markdown(
    """
Convert 2D SVG vector art or high-contrast raster art into watertight,
3D-printable STL files optimized for flexible materials.

**Workflow:**
1. Upload SVG, PNG, JPG, JPEG, or WEBP
2. Configure stencil parameters
3. Preview 2D geometry
4. Generate 3D mesh
5. Export STL for slicing
"""
)
st.divider()


def reset_downstream_state() -> None:
    """Reset derived artifacts when source geometry changes."""
    st.session_state.mask_plate = None
    st.session_state.mesh = None
    st.session_state.stl_path = None


def clear_all_loaded_state() -> None:
    """Clear all loaded input and downstream state."""
    st.session_state.geometry = None
    st.session_state.metadata = None
    st.session_state.mask_plate = None
    st.session_state.mesh = None
    st.session_state.stl_path = None
    st.session_state.debug_images = {}
    st.session_state.uploaded_filename = None
    st.session_state.input_kind = None
    st.session_state.uploaded_file_signature = None


def plot_geometry(
    geometry: Polygon | MultiPolygon,
    title: str = "2D Preview",
):
    """Plot 2D geometry using matplotlib."""
    fig, ax = plt.subplots(figsize=(10, 10))

    if isinstance(geometry, Polygon):
        geoms = [geometry]
    else:
        geoms = list(geometry.geoms)

    for geom in geoms:
        x, y = geom.exterior.xy
        ax.fill(x, y, alpha=0.5, fc="steelblue", ec="black", linewidth=2)

        for interior in geom.interiors:
            x, y = interior.xy
            ax.fill(x, y, alpha=1.0, fc="white", ec="red", linewidth=1)

    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    return fig


def plot_mask_plate(plate: Polygon, title: str = "Mask Plate"):
    """Plot mask plate with holes."""
    fig, ax = plt.subplots(figsize=(10, 10))

    x, y = plate.exterior.xy
    ax.fill(
        x,
        y,
        alpha=0.7,
        fc="lightgray",
        ec="black",
        linewidth=2,
        label="Plate",
    )

    for interior in plate.interiors:
        x, y = interior.xy
        ax.fill(
            x,
            y,
            alpha=1.0,
            fc="white",
            ec="red",
            linewidth=2,
            label="Cutout",
        )

    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    return fig


# Sidebar for parameters
with st.sidebar:
    st.header("⚙️ Parameters")
    st.info("Configure stencil generation parameters here.")

    st.subheader("Plate Configuration")
    plate_margin = st.slider("Plate margin (mm)", 5, 50, 10)
    plate_thickness = st.slider("Plate thickness (mm)", 1.0, 5.0, 2.0, step=0.5)

    st.subheader("Geometry")
    clearance = st.slider("Clearance offset (mm)", 0.0, 2.0, 0.5, step=0.1)

    st.subheader("Sprues (Island Bridges)")
    use_sprues = st.checkbox("Enable sprues for disconnected islands", value=True)
    if use_sprues:
        sprue_width = st.slider("Sprue width (mm)", 1.0, 5.0, 2.0, step=0.5)
        sprue_max_length = st.slider("Max sprue length (mm)", 10, 100, 50)
        sprue_max_count = st.slider("Max sprue count", 1, 20, 10)
    else:
        sprue_width = 2.0
        sprue_max_length = 50
        sprue_max_count = 10

    st.subheader("Alignment Marks")
    use_marks = st.checkbox("Add alignment marks", value=False)
    if use_marks:
        mark_type = st.radio("Mark type", ["Crosshair", "Circular hole"])
        mark_size = st.slider("Mark size (mm)", 2, 20, 5)
        mark_offset = st.slider("Offset from edge (mm)", 5, 30, 10)
    else:
        mark_type = "Crosshair"
        mark_size = 5
        mark_offset = 10

    st.subheader("Raster Pipeline")
    target_width_mm = st.number_input(
        "Target artwork width (mm)",
        min_value=10.0,
        max_value=500.0,
        value=120.0,
        step=5.0,
    )

    lock_aspect = st.checkbox("Preserve aspect ratio", value=True)

    raster_target_height_mm = None
    if not lock_aspect:
        raster_target_height_mm = st.number_input(
            "Target artwork height (mm)",
            min_value=10.0,
            max_value=500.0,
            value=120.0,
            step=5.0,
        )

    fit_mode = st.selectbox(
        "Canvas fit mode",
        options=["contain", "cover"],
        index=0,
    )

    auto_threshold = st.checkbox("Auto threshold (Otsu)", value=True)
    threshold = st.slider(
        "Manual threshold",
        min_value=0,
        max_value=255,
        value=128,
        step=1,
        disabled=auto_threshold,
    )

    invert = st.checkbox("Invert mask", value=False)
    blur_px = st.slider("Blur (px)", 0, 5, 1, 1)
    morph_open_px = st.slider("Morph open (px)", 0, 5, 1, 1)
    morph_close_px = st.slider("Morph close (px)", 0, 5, 2, 1)

    min_component_area_px = st.number_input(
        "Minimum component area (px)",
        min_value=1,
        max_value=10000,
        value=32,
        step=1,
    )

    min_area_mm2 = st.number_input(
        "Minimum output region area (mm^2)",
        min_value=0.0,
        max_value=1000.0,
        value=0.75,
        step=0.05,
    )

    min_feature_mm = st.number_input(
        "Minimum feature size (mm)",
        min_value=0.0,
        max_value=10.0,
        value=0.25,
        step=0.05,
    )

    simplify_tolerance_mm = st.number_input(
        "Simplify tolerance (mm)",
        min_value=0.0,
        max_value=5.0,
        value=0.15,
        step=0.05,
    )


# Main content area
col1, col2 = st.columns(2)

with col1:
    st.subheader("📤 Upload Artwork")
    uploaded_file = st.file_uploader(
        "Choose an artwork file",
        type=["svg", "png", "jpg", "jpeg", "webp"],
    )

    if uploaded_file is not None:
        suffix = Path(uploaded_file.name).suffix.lower()
        file_signature = f"{uploaded_file.name}:{uploaded_file.size}"
        needs_reprocess = file_signature != st.session_state.uploaded_file_signature

        if needs_reprocess:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                tmp_file.write(uploaded_file.getbuffer())
                tmp_path = Path(tmp_file.name)

            try:
                reset_downstream_state()

                if suffix == ".svg":
                    with st.spinner("Parsing SVG..."):
                        geometry, metadata = load_svg(tmp_path)

                    st.session_state.geometry = geometry
                    st.session_state.metadata = metadata
                    st.session_state.debug_images = {}
                    st.session_state.input_kind = "svg"
                    st.session_state.uploaded_filename = uploaded_file.name
                    st.session_state.uploaded_file_signature = file_signature

                    st.success(f"✓ Loaded SVG: {uploaded_file.name}")

                else:
                    with st.spinner("Processing raster image..."):
                        image_rgb, raster_meta = load_raster(tmp_path)
                        source_h, source_w = image_rgb.shape[:2]
                        target_aspect_ratio = source_w / source_h if source_h else 1.0

                        normalized_rgb, norm_meta = normalize_canvas(
                            image_rgb=image_rgb,
                            target_aspect_ratio=target_aspect_ratio,
                            fit_mode=fit_mode,
                            max_dim_px=1024,
                            background=255,
                        )

                        if lock_aspect:
                            target_height_mm = target_width_mm * (
                                normalized_rgb.shape[0] / normalized_rgb.shape[1]
                            )
                        else:
                            target_height_mm = raster_target_height_mm

                        pipeline_settings = {
                            "target_width_mm": target_width_mm,
                            "target_height_mm": target_height_mm,
                            "auto_threshold": auto_threshold,
                            "threshold": threshold,
                            "invert": invert,
                            "blur_px": blur_px,
                            "morph_open_px": morph_open_px,
                            "morph_close_px": morph_close_px,
                            "min_component_area_px": min_component_area_px,
                            "min_area_mm2": min_area_mm2,
                            "min_feature_mm": min_feature_mm,
                            "simplify_tolerance_mm": simplify_tolerance_mm,
                        }

                        pipeline = RasterSilhouettePipeline()
                        result = pipeline.run(normalized_rgb, pipeline_settings)

                    st.session_state.geometry = result.geometry
                    st.session_state.metadata = {
                        **raster_meta,
                        **norm_meta,
                        **result.metadata,
                    }
                    st.session_state.debug_images = result.debug_images
                    st.session_state.input_kind = "raster"
                    st.session_state.uploaded_filename = uploaded_file.name
                    st.session_state.uploaded_file_signature = file_signature

                    st.success(f"✓ Loaded raster image: {uploaded_file.name}")

                    if (
                        st.session_state.geometry is None
                        or st.session_state.geometry.is_empty
                    ):
                        st.warning(
                            "The current settings produced empty geometry. "
                            "Adjust threshold, invert, or cleanup settings."
                        )

            except Exception as e:
                st.error(f"❌ Error processing uploaded file: {e}")
                clear_all_loaded_state()

                import traceback

                st.code(traceback.format_exc())

            finally:
                tmp_path.unlink(missing_ok=True)

        else:
            st.info(f"Using cached artwork: {uploaded_file.name}")

        if st.session_state.input_kind == "svg" and st.session_state.metadata:
            metadata = st.session_state.metadata
            st.info(
                f"""
**Metadata:**
- Paths: {metadata.get('num_paths', 'N/A')}
- Valid polygons: {metadata.get('num_valid_polygons', 'N/A')}
- Width: {metadata.get('width', 0.0):.2f} mm
- Height: {metadata.get('height', 0.0):.2f} mm
- Area: {metadata.get('area', 0.0):.2f} mm²
"""
            )

        elif st.session_state.input_kind == "raster" and st.session_state.metadata:
            metadata = st.session_state.metadata
            st.info(
                f"""
**Raster Metadata:**
- Original size: {metadata.get('original_width_px', 0)} x {metadata.get('original_height_px', 0)} px
- Canvas size: {metadata.get('canvas_width_px', 0)} x {metadata.get('canvas_height_px', 0)} px
- Target width: {metadata.get('target_width_mm', 0.0):.2f} mm
- Target height: {metadata.get('target_height_mm', 0.0):.2f} mm
- Threshold: {metadata.get('threshold_used', 'N/A')}
- Components kept: {metadata.get('components_kept', 0)}
- Polygon count: {metadata.get('polygon_count', 0)}
"""
            )

    else:
        if st.session_state.uploaded_file_signature is not None:
            clear_all_loaded_state()

        st.warning("No artwork uploaded yet")

    st.divider()

    if st.button(
        "🔄 Generate Mask Plate",
        disabled=(st.session_state.geometry is None),
    ):
        try:
            with st.spinner("Generating mask plate..."):
                mask_plate = create_mask_plate(
                    st.session_state.geometry,
                    plate_margin,
                    clearance,
                )

                if use_sprues:
                    mask_plate = add_sprues(
                        mask_plate,
                        sprue_width,
                        sprue_max_length,
                        sprue_max_count,
                    )

                if use_marks:
                    mask_plate = add_alignment_marks(
                        mask_plate,
                        mark_type,
                        mark_size,
                        mark_offset,
                    )

                st.session_state.mask_plate = mask_plate

            st.success("✓ Mask plate generated!")

            num_holes = len(list(mask_plate.interiors))
            bounds = mask_plate.bounds

            st.info(
                f"""
**Plate Info:**
- Holes/cutouts: {num_holes}
- Plate width: {bounds[2] - bounds[0]:.2f} mm
- Plate height: {bounds[3] - bounds[1]:.2f} mm
- Plate area: {mask_plate.area:.2f} mm²
"""
            )

        except Exception as e:
            st.error(f"❌ Error generating mask plate: {e}")

            import traceback

            st.code(traceback.format_exc())
            st.session_state.mask_plate = None


with col2:
    st.subheader("📊 Preview")

    if st.session_state.get("debug_images"):
        st.markdown("**Raster Debug Views**")
        dbg = st.session_state.debug_images
        preview_cols = st.columns(3)

        if "input_rgb" in dbg:
            preview_cols[0].image(
                dbg["input_rgb"],
                caption="Normalized Input",
                width="stretch",
            )

        if "binary_mask" in dbg:
            preview_cols[1].image(
                dbg["binary_mask"],
                caption="Binary Mask",
                width="stretch",
                clamp=True,
            )

        if "cleaned_mask" in dbg:
            preview_cols[2].image(
                dbg["cleaned_mask"],
                caption="Cleaned Mask",
                width="stretch",
                clamp=True,
            )

        st.divider()

    if st.session_state.mask_plate is not None:
        try:
            fig = plot_mask_plate(
                st.session_state.mask_plate,
                "Mask Plate (with cutouts)",
            )
            st.pyplot(fig)
            plt.close(fig)
        except Exception as e:
            st.error(f"❌ Error rendering mask plate: {e}")

    elif st.session_state.geometry is not None:
        try:
            source_label = "Artwork Geometry"

            if st.session_state.input_kind == "svg":
                source_label = "SVG Geometry (Unified)"
            elif st.session_state.input_kind == "raster":
                source_label = "Raster Geometry (Vectorized)"

            fig = plot_geometry(st.session_state.geometry, source_label)
            st.pyplot(fig)
            plt.close(fig)
        except Exception as e:
            st.error(f"❌ Error rendering preview: {e}")

    else:
        st.info("Upload artwork to see a 2D preview")

    st.divider()
    st.subheader("📥 Export")

    col_export1, col_export2 = st.columns(2)

    with col_export1:
        if st.button(
            "🔄 Generate STL",
            disabled=(st.session_state.mask_plate is None),
        ):
            if st.session_state.mask_plate is None:
                st.error(
                    "No mask plate is currently available. "
                    "Generate the mask plate first."
                )
            else:
                try:
                    with st.spinner("Generating 3D mesh..."):
                        mesh = extrude_to_mesh(
                            st.session_state.mask_plate,
                            plate_thickness,
                        )
                        st.session_state.mesh = mesh

                        is_valid, message = validate_mesh(mesh)

                        if is_valid:
                            st.success(f"✓ 3D mesh generated! {message}")

                            mesh_info = get_mesh_info(mesh)
                            st.info(
                                f"""
**Mesh Info:**
- Vertices: {mesh_info['vertices']:,}
- Faces: {mesh_info['faces']:,}
- Watertight: {'Yes' if mesh_info['watertight'] else 'No'}
- Volume: {mesh_info['volume']:.2f} mm³ (if watertight)
- Surface area: {mesh_info['surface_area']:.2f} mm²
"""
                            )

                            stl_path = (
                                Path(tempfile.gettempdir()) / "stencil_output.stl"
                            )
                            export_stl(mesh, str(stl_path))
                            st.session_state.stl_path = str(stl_path)

                        else:
                            st.warning(f"⚠️ Mesh generated but has issues: {message}")
                            st.session_state.mesh = mesh

                except Exception as e:
                    st.error(f"❌ Error generating STL: {e}")

                    import traceback

                    st.code(traceback.format_exc())
                    st.session_state.mesh = None

    with col_export2:
        if st.session_state.stl_path and Path(st.session_state.stl_path).exists():
            with open(st.session_state.stl_path, "rb") as f:
                stl_data = f.read()

            st.download_button(
                label="💾 Download STL",
                data=stl_data,
                file_name="conformal_stencil.stl",
                mime="application/octet-stream",
            )
        else:
            st.button("💾 Download STL", disabled=True)

    st.divider()
    st.markdown(
        """
---
**Status:** Milestone 8 — Raster Silhouette Pipeline + STL Export  
**Next:** Test corpus + tuning + additional segmentation strategies
"""
    )
