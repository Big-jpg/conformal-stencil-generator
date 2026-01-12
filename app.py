"""
Flexible Conformal Stencil Generator
A localhost tool for converting 2D SVG vector art into watertight, 3D-printable STL files.
"""

import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MPLPolygon
from shapely.geometry import Polygon, MultiPolygon
import tempfile
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from svg_parse import load_svg
from geom2d import create_mask_plate, add_alignment_marks

# Page configuration
st.set_page_config(
    page_title="Conformal Stencil Generator",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'geometry' not in st.session_state:
    st.session_state.geometry = None
if 'metadata' not in st.session_state:
    st.session_state.metadata = None
if 'mask_plate' not in st.session_state:
    st.session_state.mask_plate = None

# Title and description
st.title("🎨 Flexible Conformal Stencil Generator")
st.markdown("""
Convert 2D SVG vector art into watertight, 3D-printable STL files optimized for flexible materials.

**Workflow:**
1. Upload SVG (filled paths, pre-flattened)
2. Configure stencil parameters
3. Preview 2D geometry
4. Generate 3D mesh
5. Export STL for slicing
""")

st.divider()

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
    
    st.subheader("Alignment Marks")
    use_marks = st.checkbox("Add alignment marks", value=False)
    if use_marks:
        mark_type = st.radio("Mark type", ["Crosshair", "Circular hole"])
        mark_size = st.slider("Mark size (mm)", 2, 20, 5)
        mark_offset = st.slider("Offset from edge (mm)", 5, 30, 10)


def plot_geometry(geometry: MultiPolygon, title: str = "2D Preview"):
    """Plot 2D geometry using matplotlib."""
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # Plot each polygon in the MultiPolygon
    if isinstance(geometry, Polygon):
        geoms = [geometry]
    else:
        geoms = list(geometry.geoms)
    
    for geom in geoms:
        # Exterior
        x, y = geom.exterior.xy
        ax.fill(x, y, alpha=0.5, fc='steelblue', ec='black', linewidth=2)
        
        # Holes
        for interior in geom.interiors:
            x, y = interior.xy
            ax.fill(x, y, alpha=1.0, fc='white', ec='red', linewidth=1)
    
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    
    return fig


def plot_mask_plate(plate: Polygon, title: str = "Mask Plate"):
    """Plot mask plate with holes."""
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # Plot exterior (plate)
    x, y = plate.exterior.xy
    ax.fill(x, y, alpha=0.7, fc='lightgray', ec='black', linewidth=2, label='Plate')
    
    # Plot holes (negative space)
    for interior in plate.interiors:
        x, y = interior.xy
        ax.fill(x, y, alpha=1.0, fc='white', ec='red', linewidth=2, label='Cutout')
    
    ax.set_aspect('equal')
    ax.grid(True, alpha=0.3)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel('X (mm)')
    ax.set_ylabel('Y (mm)')
    
    return fig


# Main content area
col1, col2 = st.columns(2)

with col1:
    st.subheader("📤 Upload SVG")
    uploaded_file = st.file_uploader("Choose an SVG file", type=["svg"])
    
    if uploaded_file is not None:
        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.svg') as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        try:
            # Load and parse SVG
            with st.spinner("Parsing SVG..."):
                geometry, metadata = load_svg(tmp_path)
                st.session_state.geometry = geometry
                st.session_state.metadata = metadata
            
            st.success(f"✓ Loaded: {uploaded_file.name}")
            
            # Display metadata
            st.info(f"""
            **Metadata:**
            - Paths: {metadata['num_paths']}
            - Valid polygons: {metadata['num_valid_polygons']}
            - Width: {metadata['width']:.2f} mm
            - Height: {metadata['height']:.2f} mm
            - Area: {metadata['area']:.2f} mm²
            """)
            
        except Exception as e:
            st.error(f"❌ Error parsing SVG: {e}")
            st.session_state.geometry = None
            st.session_state.metadata = None
        
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)
    else:
        st.warning("No SVG uploaded yet")
    
    # Generate mask plate button
    st.divider()
    
    if st.button("🔄 Generate Mask Plate", disabled=(st.session_state.geometry is None)):
        try:
            with st.spinner("Generating mask plate..."):
                # Create mask plate
                mask_plate = create_mask_plate(
                    st.session_state.geometry,
                    plate_margin,
                    clearance
                )
                
                # Add alignment marks if enabled
                if use_marks:
                    mask_plate = add_alignment_marks(
                        mask_plate,
                        mark_type,
                        mark_size,
                        mark_offset
                    )
                
                st.session_state.mask_plate = mask_plate
            
            st.success("✓ Mask plate generated!")
            
            # Display plate info
            num_holes = len(list(mask_plate.interiors))
            bounds = mask_plate.bounds
            st.info(f"""
            **Plate Info:**
            - Holes/cutouts: {num_holes}
            - Plate width: {bounds[2] - bounds[0]:.2f} mm
            - Plate height: {bounds[3] - bounds[1]:.2f} mm
            - Plate area: {mask_plate.area:.2f} mm²
            """)
            
        except Exception as e:
            st.error(f"❌ Error generating mask plate: {e}")
            st.session_state.mask_plate = None

with col2:
    st.subheader("📊 Preview")
    
    # Show either mask plate or original geometry
    if st.session_state.mask_plate is not None:
        try:
            fig = plot_mask_plate(st.session_state.mask_plate, "Mask Plate (with cutouts)")
            st.pyplot(fig)
            plt.close(fig)
        except Exception as e:
            st.error(f"❌ Error rendering mask plate: {e}")
    elif st.session_state.geometry is not None:
        try:
            fig = plot_geometry(st.session_state.geometry, "SVG Geometry (Unified)")
            st.pyplot(fig)
            plt.close(fig)
        except Exception as e:
            st.error(f"❌ Error rendering preview: {e}")
    else:
        st.info("Upload an SVG to see 2D preview")

st.divider()

st.subheader("📥 Export")
col_export1, col_export2 = st.columns(2)

with col_export1:
    if st.button("🔄 Generate STL", disabled=(st.session_state.mask_plate is None)):
        st.info("STL generation coming in Milestone 5")

with col_export2:
    if st.button("💾 Download STL", disabled=True):
        st.info("STL export coming in Milestone 5")

st.divider()

st.markdown("""
---
**Status:** Milestone 2 — Mask Plate Generation ✓  
**Next:** Milestone 3 — Island Detection + Sprues
""")
