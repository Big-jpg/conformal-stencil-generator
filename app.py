"""
Flexible Conformal Stencil Generator
A localhost tool for converting 2D SVG vector art into watertight, 3D-printable STL files.
"""

import streamlit as st

# Page configuration
st.set_page_config(
    page_title="Conformal Stencil Generator",
    page_icon="🎨",
    layout="wide",
    initial_sidebar_state="expanded"
)

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

# Main content area
col1, col2 = st.columns(2)

with col1:
    st.subheader("📤 Upload SVG")
    uploaded_file = st.file_uploader("Choose an SVG file", type=["svg"])
    
    if uploaded_file is not None:
        st.success(f"✓ Loaded: {uploaded_file.name}")
        st.info("SVG parsing and 2D preview coming in Milestone 1")
    else:
        st.warning("No SVG uploaded yet")

with col2:
    st.subheader("📊 Preview")
    st.info("2D geometry preview will appear here")

st.divider()

st.subheader("📥 Export")
col_export1, col_export2 = st.columns(2)

with col_export1:
    if st.button("🔄 Generate STL", disabled=True):
        st.info("STL generation coming in Milestone 5")

with col_export2:
    if st.button("💾 Download STL", disabled=True):
        st.info("STL export coming in Milestone 5")

st.divider()

st.markdown("""
---
**Status:** Milestone 0 — App Boot ✓  
**Next:** Milestone 1 — SVG Import & 2D Preview
""")
