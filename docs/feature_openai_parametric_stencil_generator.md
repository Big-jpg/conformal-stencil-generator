# OpenAI Parametric Stencil Generator Feature Brief

## Purpose

This branch isolates the next iteration of the conformal stencil generator: a reliable SVG -> mask plate -> STL path that can later accept either user-authored SVGs, OpenAI-generated SVGs, or procedural/parametric primitives.

The design goal is deliberately staged:

1. Keep the current deterministic local SVG/raster -> STL fabrication pipeline working.
2. Add a clean internal contract for generated SVG templates.
3. Add a front-end request schema that can describe desired stencil properties.
4. Add an OpenAI generation adapter that returns constrained SVG, not arbitrary application code.
5. Add procedural primitive generators for OpenSCAD-like parametric stencil templates.

## Working mental model

```text
Frontend request params
  -> StencilTemplateRequest
  -> SVG generation path
       a) user uploaded SVG
       b) OpenAI-generated constrained SVG
       c) procedural primitive SVG/Shapely geometry
  -> SVG/geometry validator
  -> mask plate generator
  -> sprues/alignment/fabrication rules
  -> STL export
```

The key architectural decision is that OpenAI should generate bounded vector geometry, not mesh geometry. Mesh generation remains deterministic and local via Shapely and Trimesh.

## Why SVG first

SVG is the right interchange layer because it is:

- human inspectable
- easy to validate before fabrication
- easy to preview in Streamlit
- compatible with external vector tooling
- safer than executing generated Python/OpenSCAD directly
- already supported by the current app pipeline

The generated SVG should be a constrained subset:

- closed filled paths only
- no scripts
- no external references
- no live text
- no strokes unless converted to fills
- explicit width/height/viewBox
- physical units mapped to millimetres

## Proposed request schema

```json
{
  "template_kind": "dot_gradient | curve_shield | organic_scroll | texture_field | custom_svg",
  "canvas": {
    "width_mm": 120,
    "height_mm": 80
  },
  "material_profile": "PLA_thin | PETG_film | TPU_95A",
  "fabrication": {
    "plate_margin_mm": 10,
    "plate_thickness_mm": 0.6,
    "clearance_mm": 0.3,
    "min_feature_mm": 0.8,
    "min_wall_mm": 1.0
  },
  "style": {
    "motif": "art nouveau curves",
    "density": 0.45,
    "edge_behavior": "hard | soft | feather",
    "seed": 42
  },
  "prompt": "Generate an organic set of airbrush stencil curves suitable for portrait shadow transitions."
}
```

## OpenAI generation contract

The OpenAI adapter should return JSON, not free-form prose:

```json
{
  "name": "portrait_shadow_scrolls_v1",
  "units": "mm",
  "width_mm": 120,
  "height_mm": 80,
  "svg": "<svg ...>...</svg>",
  "notes": ["closed paths only", "minimum feature target 1.0 mm"]
}
```

The app should then validate the SVG before it enters the existing `load_svg()` path.

## Validation rules before STL

Generated SVG must pass:

- XML parse success
- no `<script>`, `<foreignObject>`, external links, or embedded raster images
- all geometry reducible to closed filled paths
- bounded viewBox and physical dimensions
- geometry not empty
- minimum feature/wall checks where practical
- STL mesh validation after extrusion

## Parametric primitive roadmap

These should be implemented as deterministic local generators, not LLM-generated code:

- dot gradient texture plate
- randomized stipple field with seed
- crescent/leaf mask
- taper ribbon/curve shield
- scroll/spiral primitive
- test calibration card for nozzle/paint/material tuning
- registration holes and handling tabs

OpenAI can select and parameterize primitives, but the geometry functions should remain local, typed, and testable.

## Branch acceptance target

Initial acceptance for this branch:

- A clean feature branch exists for iteration.
- Existing SVG/raster -> STL path remains intact.
- Documentation captures the intended OpenAI + parametric architecture.
- Next implementation step is to add typed request/config models and a procedural primitive generator module.
