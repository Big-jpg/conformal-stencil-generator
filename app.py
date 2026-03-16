# app.py
from pathlib import Path
import sys
import tempfile

# Add src to path BEFORE importing local src modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

import matplotlib.pyplot as plt
import streamlit as st
from shapely.geometry import MultiPolygon, Polygon

from geom2d import add_alignment_marks, _count_holes, _total_area, PlateGeom
from mesh3d import export_stl, extrude_to_mesh, get_mesh_info, validate_mesh
from pipelines import RasterSilhouettePipeline
from raster_io import load_raster, normalize_canvas
from svg_parse import load_svg
from variants import VariantResult, run_raster_variants, run_svg_variants


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Conformal Stencil Generator",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------
_STATE_KEYS = {
    "geometry": None,
    "metadata": None,
    "normalized_rgb": None,
    "target_width_mm": 120.0,
    "target_height_mm": 120.0,
    "variants": None,          # List[VariantResult] after generation
    "debug_images": {},
    "uploaded_filename": None,
    "input_kind": None,
    "uploaded_file_signature": None,
}
for k, v in _STATE_KEYS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_downstream() -> None:
    st.session_state.variants = None


def _clear_all() -> None:
    for k, v in _STATE_KEYS.items():
        st.session_state[k] = v


def _plot_plate(plate: PlateGeom, title: str = "Mask Plate", figsize: float = 5.0):
    """Render a plate (Polygon or MultiPolygon) as a 2D preview.

    Rendering convention:
    - Gray fill  = solid plate material (the frame and any floating islands)
    - White fill = cutout apertures (interior rings / holes)
    - Red outline = cutout boundary
    """
    fig, ax = plt.subplots(figsize=(figsize, figsize))
    polys = [plate] if isinstance(plate, Polygon) else list(plate.geoms)
    for poly in polys:
        x, y = poly.exterior.xy
        ax.fill(x, y, alpha=0.7, fc="lightgray", ec="black", linewidth=1.5)
        for interior in poly.interiors:
            x, y = interior.xy
            ax.fill(x, y, alpha=1.0, fc="white", ec="#e05050", linewidth=1.0)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_xlabel("X (mm)", fontsize=8)
    ax.set_ylabel("Y (mm)", fontsize=8)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    return fig


def _plot_geometry(geometry: Polygon | MultiPolygon, title: str, figsize: float = 5.0):
    fig, ax = plt.subplots(figsize=(figsize, figsize))
    geoms = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
    for geom in geoms:
        x, y = geom.exterior.xy
        ax.fill(x, y, alpha=0.5, fc="steelblue", ec="black", linewidth=1.5)
        for interior in geom.interiors:
            x, y = interior.xy
            ax.fill(x, y, alpha=1.0, fc="white", ec="#e05050", linewidth=0.8)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.2)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.set_xlabel("X (mm)", fontsize=8)
    ax.set_ylabel("Y (mm)", fontsize=8)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    return fig


def _stl_bytes(plate: PlateGeom, thickness: float) -> tuple[bytes | None, str]:
    """
    Extrude plate to mesh and return (stl_bytes, status_message).
    Always returns bytes if extrusion succeeds, regardless of watertight status.
    """
    try:
        mesh = extrude_to_mesh(plate, thickness)
        is_valid, msg = validate_mesh(mesh)
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp_path = f.name
        export_stl(mesh, tmp_path)
        with open(tmp_path, "rb") as f:
            data = f.read()
        Path(tmp_path).unlink(missing_ok=True)
        info = get_mesh_info(mesh)
        status = (
            f"{'Watertight' if info['watertight'] else 'Non-watertight'} | "
            f"{info['vertices']:,} verts | {info['faces']:,} faces"
        )
        if not is_valid:
            status = f"[issues: {msg}] " + status
        return data, status
    except Exception as exc:
        return None, f"Extrusion failed: {exc}"


# ---------------------------------------------------------------------------
# Sidebar — shared plate parameters only
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Parameters")

    st.subheader("Plate")
    plate_margin = st.slider("Plate margin (mm)", 5, 50, 10)
    plate_thickness = st.slider("Plate thickness (mm)", 1.0, 5.0, 2.0, step=0.5)

    st.subheader("Alignment Marks")
    use_marks = st.checkbox("Add alignment marks to all variants", value=False)
    if use_marks:
        mark_type = st.radio("Mark type", ["Crosshair", "Circular hole"])
        mark_size = st.slider("Mark size (mm)", 2, 20, 5)
        mark_offset = st.slider("Offset from edge (mm)", 5, 30, 10)
    else:
        mark_type, mark_size, mark_offset = "Crosshair", 5, 10

    st.subheader("Raster Input")
    target_width_mm = st.number_input(
        "Target artwork width (mm)", min_value=10.0, max_value=500.0, value=120.0, step=5.0,
    )
    lock_aspect = st.checkbox("Preserve aspect ratio", value=True)
    raster_target_height_mm = None
    if not lock_aspect:
        raster_target_height_mm = st.number_input(
            "Target artwork height (mm)", min_value=10.0, max_value=500.0, value=120.0, step=5.0,
        )
    fit_mode = st.selectbox("Canvas fit mode", options=["contain", "cover"], index=0)

    st.divider()
    st.caption(
        "Variant-specific settings (threshold, invert, blur, morphology, sprues) "
        "are controlled by the preset strategies — no manual tuning required."
    )


# ---------------------------------------------------------------------------
# Title
# ---------------------------------------------------------------------------
st.title("Conformal Stencil Generator")
st.markdown(
    "Upload artwork → Generate all variant mask plates simultaneously → "
    "Compare previews → Download the STL that works best."
)
st.divider()


# ---------------------------------------------------------------------------
# Upload section
# ---------------------------------------------------------------------------
st.subheader("Upload Artwork")
uploaded_file = st.file_uploader(
    "SVG, PNG, JPG, JPEG, or WEBP",
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
            _reset_downstream()

            if suffix == ".svg":
                with st.spinner("Parsing SVG..."):
                    geometry, metadata = load_svg(tmp_path)

                st.session_state.geometry = geometry
                st.session_state.metadata = metadata
                st.session_state.normalized_rgb = None
                st.session_state.debug_images = {}
                st.session_state.input_kind = "svg"
                st.session_state.uploaded_filename = uploaded_file.name
                st.session_state.uploaded_file_signature = file_signature
                st.success(f"Loaded SVG: {uploaded_file.name}")

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
                        t_h = target_width_mm * (normalized_rgb.shape[0] / normalized_rgb.shape[1])
                    else:
                        t_h = raster_target_height_mm or target_width_mm

                    st.session_state.geometry = None
                    st.session_state.normalized_rgb = normalized_rgb
                    st.session_state.target_width_mm = target_width_mm
                    st.session_state.target_height_mm = t_h
                    st.session_state.metadata = {**raster_meta, **norm_meta}
                    st.session_state.debug_images = {
                        "input_rgb": image_rgb,
                        "normalized_rgb": normalized_rgb,
                    }
                    st.session_state.input_kind = "raster"
                    st.session_state.uploaded_filename = uploaded_file.name
                    st.session_state.uploaded_file_signature = file_signature
                    st.success(f"Loaded raster: {uploaded_file.name}")

        except Exception as exc:
            import traceback as _tb
            st.error(f"Error processing file: {exc}")
            st.code(_tb.format_exc())
            _clear_all()
        finally:
            tmp_path.unlink(missing_ok=True)
    else:
        st.info(f"Using cached artwork: {uploaded_file.name}")

    # Metadata summary
    if st.session_state.input_kind == "svg" and st.session_state.metadata:
        m = st.session_state.metadata
        st.caption(
            f"SVG — {m.get('num_paths','?')} paths, {m.get('num_valid_polygons','?')} polygons, "
            f"{m.get('width',0):.1f} × {m.get('height',0):.1f} mm"
        )
    elif st.session_state.input_kind == "raster" and st.session_state.metadata:
        m = st.session_state.metadata
        dbg = st.session_state.debug_images
        if dbg:
            dcols = st.columns(min(len(dbg), 3))
            for i, (k, img) in enumerate(list(dbg.items())[:3]):
                dcols[i].image(img, caption=k.replace("_", " ").title(), use_container_width=True, clamp=True)
        st.caption(
            f"Raster — {m.get('original_width_px','?')}×{m.get('original_height_px','?')} px → "
            f"{st.session_state.target_width_mm:.0f}×{st.session_state.target_height_mm:.0f} mm"
        )

else:
    if st.session_state.uploaded_file_signature is not None:
        _clear_all()
    st.info("Upload artwork to begin.")

st.divider()


# ---------------------------------------------------------------------------
# Generate all variants
# ---------------------------------------------------------------------------
can_generate = (
    st.session_state.input_kind == "svg" and st.session_state.geometry is not None
) or (
    st.session_state.input_kind == "raster" and st.session_state.normalized_rgb is not None
)

if st.button("Generate All Variant Mask Plates", disabled=not can_generate, type="primary"):
    with st.spinner("Running all variants..."):
        try:
            if st.session_state.input_kind == "svg":
                variants = run_svg_variants(
                    st.session_state.geometry,
                    plate_margin=plate_margin,
                )
            else:
                variants = run_raster_variants(
                    normalized_rgb=st.session_state.normalized_rgb,
                    target_width_mm=st.session_state.target_width_mm,
                    target_height_mm=st.session_state.target_height_mm,
                    plate_margin=plate_margin,
                )

            # Apply alignment marks if requested
            if use_marks:
                for v in variants:
                    if v.plate is not None:
                        try:
                            v.plate = add_alignment_marks(
                                v.plate, mark_type, mark_size, mark_offset
                            )
                        except Exception:
                            pass  # marks are cosmetic; don't fail the variant

            st.session_state.variants = variants
            ok = sum(1 for v in variants if v.plate is not None)
            st.success(f"Generated {ok}/{len(variants)} variants successfully.")
        except Exception as exc:
            import traceback as _tb
            st.error(f"Variant generation failed: {exc}")
            st.code(_tb.format_exc())


# ---------------------------------------------------------------------------
# Variant grid display
# ---------------------------------------------------------------------------
if st.session_state.variants:
    variants: list[VariantResult] = st.session_state.variants
    st.subheader("Variant Mask Plates")
    st.caption(
        "Each tile shows the 2D mask plate preview. "
        "Red outlines = cutouts/apertures. Gray = plate material. "
        "Download the STL directly from any tile."
    )

    # Lay out in rows of 3
    COLS_PER_ROW = 3
    rows = [variants[i:i + COLS_PER_ROW] for i in range(0, len(variants), COLS_PER_ROW)]

    for row in rows:
        cols = st.columns(COLS_PER_ROW)
        for col, variant in zip(cols, row):
            with col:
                st.markdown(f"**{variant.label}**")
                st.caption(variant.description)

                if variant.error:
                    st.error("Failed")
                    with st.expander("Error details"):
                        st.code(variant.error)
                    continue

                # 2D preview
                try:
                    fig = _plot_plate(variant.plate, title="", figsize=4.0)
                    st.pyplot(fig, use_container_width=True)
                    plt.close(fig)
                except Exception as exc:
                    st.warning(f"Preview error: {exc}")

                # Stats
                m = variant.metadata
                holes = m.get("plate_holes", m.get("holes", "?"))
                area = m.get("plate_area_mm2", m.get("area_mm2", 0))
                sprues_on = m.get("sprues", False)
                st.caption(
                    f"Holes: {holes} | Area: {area:.0f} mm² | "
                    f"{'Sprues: on' if sprues_on else 'Sprues: off'}"
                )

                # STL export — always available, no watertight gate
                stl_data, stl_status = _stl_bytes(variant.plate, plate_thickness)
                if stl_data is not None:
                    fname = f"stencil_{variant.name}.stl"
                    st.download_button(
                        label="Download STL",
                        data=stl_data,
                        file_name=fname,
                        mime="application/octet-stream",
                        key=f"dl_{variant.name}",
                    )
                    st.caption(stl_status)
                else:
                    st.error(stl_status)

    st.divider()

    # Geometry preview for raster variants (shows what the pipeline extracted)
    if st.session_state.input_kind == "raster":
        with st.expander("Geometry previews (what the pipeline extracted per variant)"):
            geom_rows = [variants[i:i + COLS_PER_ROW] for i in range(0, len(variants), COLS_PER_ROW)]
            for row in geom_rows:
                gcols = st.columns(COLS_PER_ROW)
                for gcol, variant in zip(gcols, row):
                    with gcol:
                        if variant.geometry is not None and not variant.geometry.is_empty:
                            try:
                                fig = _plot_geometry(
                                    variant.geometry,
                                    title=variant.label,
                                    figsize=3.5,
                                )
                                st.pyplot(fig, use_container_width=True)
                                plt.close(fig)
                            except Exception as exc:
                                st.caption(f"Preview error: {exc}")
                        else:
                            st.caption(f"{variant.label}: no geometry")

st.divider()
st.caption("Conformal Stencil Generator — multi-variant edition")
