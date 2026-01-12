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

with col2:
    st.subheader("📊 Preview")
    
    if st.session_state.geometry is not None:
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
    if st.button("🔄 Generate STL", disabled=(st.session_state.geometry is None)):
        st.info("STL generation coming in Milestone 5")

with col_export2:
    if st.button("💾 Download STL", disabled=True):
        st.info("STL export coming in Milestone 5")

st.divider()

st.markdown("""
---
**Status:** Milestone 1 — SVG Import & 2D Preview ✓  
**Next:** Milestone 2 — Mask Plate Generation
""")
