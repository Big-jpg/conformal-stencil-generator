#!/usr/bin/env python3
"""
Validation script for all test SVGs.
Tests the complete pipeline: SVG → 2D → 3D → STL
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from svg_parse import load_svg
from geom2d import create_mask_plate, add_sprues, add_alignment_marks
from mesh3d import extrude_to_mesh, export_stl, validate_mesh, get_mesh_info


def test_svg(svg_path: Path, output_dir: Path, test_name: str):
    """Test a single SVG through the complete pipeline."""
    print(f"\n{'='*60}")
    print(f"Testing: {test_name}")
    print(f"{'='*60}")
    
    try:
        # 1. Load SVG
        geometry, metadata = load_svg(svg_path)
        print(f"✓ SVG loaded: {metadata['num_paths']} paths, {metadata['num_valid_polygons']} polygons")
        print(f"  Dimensions: {metadata['width']:.2f} x {metadata['height']:.2f} mm")
        
        # 2. Create mask plate
        plate = create_mask_plate(geometry, plate_margin=10, clearance=0.5)
        num_holes_before = len(list(plate.interiors))
        print(f"✓ Mask plate created: {num_holes_before} holes")
        
        # 3. Add sprues
        plate_with_sprues = add_sprues(plate, sprue_width=2.0, max_length=50, max_count=10)
        num_holes_after = len(list(plate_with_sprues.interiors))
        print(f"✓ Sprues added: {num_holes_before} holes → {num_holes_after} holes")
        
        # 4. Add alignment marks
        plate_final = add_alignment_marks(
            plate_with_sprues,
            mark_type="circular_hole",
            mark_size=5,
            offset_from_edge=10
        )
        print(f"✓ Alignment marks added")
        
        # 5. Extrude to 3D
        mesh = extrude_to_mesh(plate_final, thickness=2.0)
        print(f"✓ 3D mesh generated")
        
        # 6. Validate mesh
        is_valid, message = validate_mesh(mesh)
        if is_valid:
            print(f"✓ Mesh validation: {message}")
        else:
            print(f"⚠ Mesh validation: {message}")
        
        # 7. Get mesh info
        info = get_mesh_info(mesh)
        print(f"  Vertices: {info['vertices']:,}")
        print(f"  Faces: {info['faces']:,}")
        print(f"  Watertight: {info['watertight']}")
        print(f"  Volume: {info['volume']:.2f} mm³")
        print(f"  Surface area: {info['surface_area']:.2f} mm²")
        
        # 8. Export STL
        output_path = output_dir / f"{test_name}.stl"
        export_stl(mesh, str(output_path))
        file_size = output_path.stat().st_size
        print(f"✓ STL exported: {output_path.name} ({file_size:,} bytes)")
        
        print(f"\n✓✓✓ {test_name} PASSED ✓✓✓")
        return True
        
    except Exception as e:
        print(f"\n❌❌❌ {test_name} FAILED ❌❌❌")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    test_dir = Path(__file__).parent
    output_dir = test_dir / "output"
    output_dir.mkdir(exist_ok=True)
    
    tests = [
        ("simple_shape.svg", "simple_shape"),
        ("islands.svg", "islands"),
        ("text_as_path.svg", "text_as_path"),
    ]
    
    print("="*60)
    print("CONFORMAL STENCIL GENERATOR - TEST SUITE")
    print("="*60)
    
    results = []
    for svg_file, test_name in tests:
        svg_path = test_dir / svg_file
        if svg_path.exists():
            passed = test_svg(svg_path, output_dir, test_name)
            results.append((test_name, passed))
        else:
            print(f"\n⚠ Skipping {test_name}: file not found")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "❌ FAIL"
        print(f"{status:8} {test_name}")
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    print(f"\nTotal: {passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 All tests passed! 🎉")
        return 0
    else:
        print(f"\n⚠ {total_count - passed_count} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
