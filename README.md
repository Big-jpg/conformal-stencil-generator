# Flexible Conformal Stencil Generator

A localhost tool for converting 2D SVG vector art into watertight, 3D-printable STL files optimized for flexible materials (TPU, PETG, thin PLA).

## Purpose

This is a **purpose-built fabrication tool** for paint masks and airbrushing stencils, not a generic SVG→STL converter. It enables:

- **Rapid stencil iteration** — Upload SVG, export STL in seconds
- **Repeatable alignment** — Built-in alignment marks for consistent masking
- **Clean airbrush edges** — Optimized geometry for flat or gently curved surfaces
- **Reliable island handling** — Automatic detection and bridging of disconnected stencil regions

## Core Workflow

1. **Upload SVG** — Filled paths, pre-flattened (no live text, no strokes)
2. **Configure parameters** — Plate margin, clearance, sprues, alignment marks
3. **Preview 2D geometry** — Verify silhouette and cutouts
4. **Generate 3D mesh** — Extrude to thickness, merge geometry
5. **Export STL** — Watertight, manifold, ready for slicing

## Installation

### Prerequisites

- Python 3.11+
- pip or uv

### Setup

```bash
git clone https://github.com/Big-jpg/conformal-stencil-generator.git
cd conformal-stencil-generator
pip install -r requirements.txt
```

## Usage

Launch the Streamlit app:

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`.

### Workflow

1. **Upload SVG** — Use the file uploader in the main panel
2. **Configure parameters** — Adjust in the sidebar:
   - **Plate margin** — Space around bounding box (mm)
   - **Plate thickness** — Extrusion height (mm)
   - **Clearance** — Offset around art (mm)
   - **Sprues** — Width and max length for island bridges
   - **Alignment marks** — Type, size, offset
3. **Generate Mask Plate** — Click "Generate Mask Plate" to create 2D geometry
4. **Preview** — 2D geometry preview shows plate and cutouts
5. **Generate STL** — Click "Generate STL" to extrude to 3D
6. **Download** — Click "Download STL" to save the file

## Parameters

### Plate Configuration

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Plate margin | 5–50 mm | 10 mm | Margin around SVG bounding box |
| Plate thickness | 1.0–5.0 mm | 2.0 mm | Extrusion height (printable thickness) |

### Geometry

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Clearance | 0.0–2.0 mm | 0.5 mm | Offset around art for easier removal |

### Sprues (Island Bridges)

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Enable sprues | Boolean | True | Automatically bridge disconnected islands |
| Sprue width | 1.0–5.0 mm | 2.0 mm | Width of connecting bridges |
| Max sprue length | 10–100 mm | 50 mm | Maximum bridge length |
| Max sprue count | 1–20 | 10 | Maximum number of sprues to add |

### Alignment Marks

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Add marks | Boolean | False | Include alignment marks |
| Mark type | Crosshair / Hole | Crosshair | Shape of alignment mark |
| Mark size | 2–20 mm | 5 mm | Diameter or width of mark |
| Offset from edge | 5–30 mm | 10 mm | Distance from plate edge |

## SVG Requirements

**Accepted:**
- Filled paths (closed geometry)
- Pre-flattened shapes (no live text)
- Pre-converted strokes (if needed)
- Multiple disconnected regions

**Not supported (v1):**
- Live text (convert to paths first)
- Strokes (convert to fills)
- Open paths (must be closed)
- Clipping or masking

## Output

### STL Properties

- **Watertight** — No holes or non-manifold edges
- **Single solid** — Plate with holes (negative space)
- **Printable** — Optimized for flexible materials
- **Sliceable** — No mesh repair needed

### Export Format

- **File type** — Binary STL
- **Units** — Millimeters
- **Orientation** — Plate flat (XY plane), extrusion along Z

## Design Constraints

- **Localhost only** — No cloud dependencies
- **Deterministic** — Same input always produces same output
- **Tolerant** — Handles imperfect SVGs gracefully
- **Robust** — Manifold output guaranteed


## Known Limitations (v1)

- **No 3D surface projection** — Stencil is flat plate only
- **No texture baking** — Geometry only
- **No automatic UV unwrapping** — Not applicable to stencils
- **No cloud deployment** — Localhost only
- **SVG complexity** — Very large or deeply nested paths may be slow
- **Sprue algorithm** — Uses nearest-neighbor to exterior; may not be optimal for all cases
- **Alignment marks** — Fixed corner positions only

## Testing

Test assets are in `tests/`:

- `simple_shape.svg` — Basic rectangle with circle cutout
- `islands.svg` — Multiple disconnected regions
- `text_as_path.svg` — Text converted to paths

### Test Results

All test SVGs have been validated:

| Test SVG | Status | Notes |
|----------|--------|-------|
| simple_shape.svg | ✓ Pass | 1 hole, 14KB STL, watertight |
| islands.svg | ✓ Pass | 6 holes → 0 after sprues, watertight |
| text_as_path.svg | ✓ Pass | Complex paths, valid geometry |

## Tech Stack

| Component | Library | Version |
|-----------|---------|---------|
| UI | Streamlit | ≥1.28.0 |
| 2D geometry | Shapely | ≥2.0.0 |
| 3D mesh | Trimesh | ≥3.20.0 |
| SVG parsing | svgpathtools | ≥1.4.1 |
| Plotting | Matplotlib | ≥3.8.0 |
| Numerics | NumPy | ≥1.24.0 |
| Triangulation | mapbox-earcut | ≥1.0.0 |

## Development

### Project Structure

```
conformal-stencil-generator/
├─ app.py                 # Streamlit UI
├─ requirements.txt       # Dependencies
├─ README.md              # This file
├─ src/
│  ├─ svg_parse.py       # SVG loading and parsing
│  ├─ geom2d.py          # 2D geometry operations
│  └─ mesh3d.py          # 3D mesh and STL export
└─ tests/
   ├─ simple_shape.svg
   ├─ islands.svg
   └─ text_as_path.svg
```

