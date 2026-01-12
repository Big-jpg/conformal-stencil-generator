# Conformal Stencil Generator - Project Summary

## Overview

A localhost Streamlit application for converting 2D SVG vector art into watertight, 3D-printable STL files optimized for flexible stencil materials (TPU, PETG, thin PLA).

## Repository

**GitHub:** https://github.com/Big-jpg/conformal-stencil-generator

## Milestones Completed

### Milestone 0: Repo + App Boot ✓
- Repository structure initialized
- Streamlit skeleton with placeholder UI
- Dependencies configured
- App launches successfully

### Milestone 1: SVG Import & 2D Preview ✓
- SVG loading and path extraction
- Path-to-polygon conversion (100 samples per path)
- Shape union into MultiPolygon
- 2D preview with matplotlib

### Milestone 2: Mask Plate Generation ✓
- Bounding box computation
- Outer rectangle with configurable margin
- Clearance buffer around geometry
- Boolean subtraction for negative space
- Alignment marks (crosshair/circular hole)

### Milestone 3: Island Detection + Sprues ✓
- Disconnected void region detection
- Nearest-neighbor sprue connection
- Rectangular sprue generation
- Max length and count constraints

### Milestone 4: Alignment Marks ✓
- Implemented in Milestone 2
- Crosshair and circular hole options
- Symmetric corner placement

### Milestone 5: 3D Extrusion + STL Export ✓
- 2D polygon to 3D mesh conversion
- Configurable thickness extrusion
- Mesh validation (watertight, manifold)
- Binary STL export
- Mesh repair functionality

### Milestone 6: Test Assets + README ✓
- Comprehensive documentation
- Test validation script
- Troubleshooting guide
- Known limitations documented

## Test Results

All test SVGs validated successfully:

| Test | Paths | Holes | After Sprues | STL Size | Watertight |
|------|-------|-------|--------------|----------|------------|
| simple_shape | 2 | 1 | 0 | 37 KB | ✓ |
| islands | 6 | 6 | 0 | 200 KB | ✓ |
| text_as_path | 3 | 3 | 0 | 140 KB | ✓ |

**Total: 3/3 tests passed ✓**

## Technical Stack

- **UI:** Streamlit 1.28+
- **2D Geometry:** Shapely 2.0+
- **3D Mesh:** Trimesh 3.20+
- **SVG Parsing:** svgpathtools 1.4+
- **Plotting:** Matplotlib 3.8+
- **Numerics:** NumPy 1.24+
- **Triangulation:** mapbox-earcut 1.0+

## Key Features

1. **Robust SVG parsing** — Handles filled paths, multiple shapes, holes
2. **Clearance offset** — Configurable buffer for easier stencil removal
3. **Island bridging** — Automatic sprue generation for disconnected regions
4. **Alignment marks** — Optional crosshair or circular hole marks
5. **Watertight output** — All STLs are manifold and sliceable without repair
6. **Parameter control** — Full control over margin, thickness, clearance, sprues

## Usage

```bash
git clone https://github.com/Big-jpg/conformal-stencil-generator.git
cd conformal-stencil-generator
pip install -r requirements.txt
streamlit run app.py
```

## Workflow

1. Upload SVG (filled paths, pre-flattened)
2. Configure parameters (margin, thickness, clearance, sprues, marks)
3. Generate mask plate (2D preview)
4. Generate STL (3D extrusion)
5. Download STL for slicing

## Known Limitations (v1)

- Flat plate only (no 3D surface projection)
- Localhost only (no cloud deployment)
- Nearest-neighbor sprue algorithm (may not be optimal for all cases)
- Fixed corner positions for alignment marks

## Commit History

- **635c7cd** Milestone 6: Test Assets + README
- **7308f78** Milestone 5: 3D Extrusion + STL Export
- **04f6ab4** Milestone 3: Island Detection + Sprues
- **eebdbcf** Milestone 2: Mask Plate Generation
- **98c84e8** Milestone 1: SVG Import & 2D Preview
- **16a1974** Milestone 0: Repo + App Boot

## Status

**All milestones complete ✓**  
**Version:** 1.0.0  
**Ready for production use**

## License

MIT
