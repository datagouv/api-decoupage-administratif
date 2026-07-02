#!/usr/bin/env python3
"""
Script to simplify GeoJSON files at different precision levels
Generates simplified versions at 5m, 10m, 100m, and 1000m precision
Uses Douglas-Peucker algorithm via Shapely
"""

import geopandas as gpd
import os
import sys
import json
from pathlib import Path

# Paths
DATA_DIR = "data"

# Simplification tolerances (in decimal degrees, approximation for WGS84 at ~45°N latitude)
# Conversion: 1 degree ≈ 111km at equator, ~78km at 45°N for longitude
# For safety, using conservative values
SIMPLIFICATION_LEVELS = {
    "5m": 0.000045,      # ~5 meters
    "10m": 0.00009,      # ~10 meters
    "100m": 0.0009,      # ~100 meters
    "1000m": 0.009,      # ~1000 meters
}

def is_simplified_geojson(filename: str) -> bool:
    """True si le fichier est déjà une variante simplifiée (_5m, _10m, …)."""
    return any(filename.endswith(f"_{level}.geojson") for level in SIMPLIFICATION_LEVELS)


def get_interco_geojson_files():
    """Fichiers intercommunalités sources (agrégé + par nature juridique)."""
    files = []
    if not os.path.exists(DATA_DIR):
        return files

    main_file = "intercommunalites.geojson"
    if os.path.exists(os.path.join(DATA_DIR, main_file)):
        files.append(main_file)

    for filename in sorted(os.listdir(DATA_DIR)):
        if not filename.endswith(".geojson"):
            continue
        if not filename.startswith("intercommunalites_"):
            continue
        if is_simplified_geojson(filename):
            continue
        if filename not in files:
            files.append(filename)
    return files

# Files to simplify (all GeoJSON files in data directory)
GEOJSON_FILES_TO_SIMPLIFY = [
    "communes.geojson",
    "arrondissements.geojson",
    "communes-deleguees-et-associees.geojson",
    "departements.geojson",
    "regions.geojson",
    "intercommunalites.geojson",
    "aom.geojson",
]

def get_all_geojson_files():
    """Get all GeoJSON files in data directory, including intercommunalites_*.geojson"""
    files = GEOJSON_FILES_TO_SIMPLIFY.copy()

    for filename in get_interco_geojson_files():
        if filename not in files:
            files.append(filename)

    return files

def simplify_geojson(input_filename, tolerance, tolerance_label):
    """Simplify a GeoJSON file with given tolerance"""
    
    input_path = os.path.join(DATA_DIR, input_filename)
    
    # Generate output filename
    base_name = input_filename.replace(".geojson", "")
    output_filename = f"{base_name}_{tolerance_label}.geojson"
    output_path = os.path.join(DATA_DIR, output_filename)
    
    # Check if input file exists
    if not os.path.exists(input_path):
        print(f"  ⚠️  File not found: {input_filename}")
        return None
    
    # Get original file size
    original_size = os.path.getsize(input_path) / (1024 * 1024)
    
    try:
        # Load GeoJSON
        print(f"  📂 Loading {input_filename}...", end=" ")
        gdf = gpd.read_file(input_path)
        print(f"({len(gdf)} features)")
        
        # Simplify geometries
        print(f"  🔄 Simplifying with tolerance {tolerance_label} ({tolerance}°)...", end=" ")
        gdf['geometry'] = gdf['geometry'].simplify(tolerance=tolerance, preserve_topology=True)
        
        # Save simplified GeoJSON
        gdf.to_file(output_path, driver='GeoJSON', encoding='utf-8')
        
        # Get simplified file size
        simplified_size = os.path.getsize(output_path) / (1024 * 1024)
        reduction = ((original_size - simplified_size) / original_size) * 100 if original_size > 0 else 0
        
        print(f"✓")
        print(f"  💾 Saved: {output_filename}")
        print(f"  📊 Size: {original_size:.2f} MB → {simplified_size:.2f} MB (-{reduction:.1f}%)")
        
        return {
            "output_file": output_filename,
            "original_size": original_size,
            "simplified_size": simplified_size,
            "reduction_percent": reduction,
            "features": len(gdf)
        }
        
    except Exception as e:
        print(f"❌")
        print(f"  ❌ Error: {e}")
        return None

def simplify_all_geojson():
    """Simplify all GeoJSON files at all tolerance levels"""
    
    print("="*70)
    print("GEOJSON SIMPLIFICATION")
    print("="*70)
    
    # Get all GeoJSON files
    geojson_files = get_all_geojson_files()
    
    print(f"\n📋 Found {len(geojson_files)} GeoJSON files to simplify")
    print(f"🎯 Simplification levels: {', '.join(SIMPLIFICATION_LEVELS.keys())}")
    
    # Statistics
    total_files = len(geojson_files)
    total_levels = len(SIMPLIFICATION_LEVELS)
    total_operations = total_files * total_levels
    completed = 0
    failed = 0
    skipped = 0
    
    results_summary = []
    
    # Process each file
    for idx, filename in enumerate(geojson_files, 1):
        print(f"\n{'='*70}")
        print(f"[{idx}/{total_files}] Processing: {filename}")
        print(f"{'='*70}")
        
        file_results = {
            "filename": filename,
            "levels": {}
        }
        
        # Apply each simplification level
        for level_name, tolerance in SIMPLIFICATION_LEVELS.items():
            result = simplify_geojson(filename, tolerance, level_name)
            
            if result:
                file_results["levels"][level_name] = result
                completed += 1
            elif result is None and not os.path.exists(os.path.join(DATA_DIR, filename)):
                skipped += 1
            else:
                failed += 1
        
        results_summary.append(file_results)
    
    # Final summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    print(f"\n📊 Operations:")
    print(f"  ✓ Completed: {completed}/{total_operations}")
    if skipped > 0:
        print(f"  ⚠️  Skipped: {skipped}/{total_operations}")
    if failed > 0:
        print(f"  ❌ Failed: {failed}/{total_operations}")
    
    print(f"\n📁 Generated files by simplification level:")
    for level_name in SIMPLIFICATION_LEVELS.keys():
        count = sum(1 for r in results_summary if level_name in r["levels"])
        print(f"  {level_name:>6}: {count} files")
    
    # Show average size reduction
    print(f"\n📉 Average size reduction by level:")
    for level_name in SIMPLIFICATION_LEVELS.keys():
        reductions = [
            r["levels"][level_name]["reduction_percent"]
            for r in results_summary
            if level_name in r["levels"]
        ]
        if reductions:
            avg_reduction = sum(reductions) / len(reductions)
            print(f"  {level_name:>6}: {avg_reduction:.1f}%")
    
    print(f"\n🎉 Simplification completed!")
    print(f"\n💡 Usage examples:")
    print(f"  - Use *_5m.geojson for high-detail zoom levels")
    print(f"  - Use *_10m.geojson for medium-detail zoom levels")
    print(f"  - Use *_100m.geojson for low-detail zoom levels")
    print(f"  - Use *_1000m.geojson for overview/country-wide views")
    
    return completed > 0

def simplify_interco_geojson(levels=None):
    """Simplify intercommunalités GeoJSON files (aggregated + par nature juridique)."""
    print("=" * 70)
    print("INTERCOMMUNALITÉS GEOJSON SIMPLIFICATION")
    print("=" * 70)

    geojson_files = get_interco_geojson_files()
    if not geojson_files:
        print(f"\n❌ No intercommunalités GeoJSON found in {DATA_DIR}/")
        print("   Run: python3 3_convert_shape_into_geojson.py --aggregate-only")
        return False

    if levels:
        invalid_levels = [level for level in levels if level not in SIMPLIFICATION_LEVELS]
        if invalid_levels:
            print(f"❌ Invalid simplification levels: {', '.join(invalid_levels)}")
            print(f"   Valid levels: {', '.join(SIMPLIFICATION_LEVELS.keys())}")
            return False
        levels_to_use = {
            level: SIMPLIFICATION_LEVELS[level] for level in levels
        }
    else:
        levels_to_use = SIMPLIFICATION_LEVELS

    print(f"\n📋 {len(geojson_files)} fichier(s) intercommunalités à simplifier")
    for filename in geojson_files:
        filepath = os.path.join(DATA_DIR, filename)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  • {filename} ({size_mb:.1f} MB)")
    print(f"🎯 Niveaux : {', '.join(levels_to_use.keys())}")

    completed = 0
    failed = 0
    for idx, filename in enumerate(geojson_files, 1):
        print(f"\n{'=' * 70}")
        print(f"[{idx}/{len(geojson_files)}] {filename}")
        print(f"{'=' * 70}")
        for level_name, tolerance in levels_to_use.items():
            result = simplify_geojson(filename, tolerance, level_name)
            if result:
                completed += 1
            else:
                failed += 1

    print("\n" + "=" * 70)
    print(f"✓ {completed} simplification(s) réussie(s)")
    if failed:
        print(f"❌ {failed} simplification(s) en échec")
    print("=" * 70)
    return completed > 0 and failed == 0

def simplify_single_file(filename, levels=None):
    """Simplify a single GeoJSON file"""
    
    print("="*70)
    print(f"SIMPLIFYING: {filename}")
    print("="*70)
    
    # Determine which levels to use
    if levels:
        # Validate levels
        invalid_levels = [l for l in levels if l not in SIMPLIFICATION_LEVELS]
        if invalid_levels:
            print(f"❌ Invalid simplification levels: {', '.join(invalid_levels)}")
            print(f"   Valid levels: {', '.join(SIMPLIFICATION_LEVELS.keys())}")
            return False
        
        levels_to_use = {k: v for k, v in SIMPLIFICATION_LEVELS.items() if k in levels}
    else:
        levels_to_use = SIMPLIFICATION_LEVELS
    
    print(f"📋 Simplification levels: {', '.join(levels_to_use.keys())}\n")
    
    completed = 0
    failed = 0
    
    for level_name, tolerance in levels_to_use.items():
        result = simplify_geojson(filename, tolerance, level_name)
        if result:
            completed += 1
        else:
            failed += 1
        print()
    
    print("="*70)
    if completed > 0:
        print(f"✓ {completed} simplification(s) completed successfully")
    if failed > 0:
        print(f"❌ {failed} simplification(s) failed")
    
    return completed > 0

def list_geojson_files():
    """List all available GeoJSON files in data directory"""
    
    print("="*70)
    print(f"Available GeoJSON files in {DATA_DIR}/")
    print("="*70)
    
    if not os.path.exists(DATA_DIR):
        print(f"❌ Directory {DATA_DIR} not found!")
        return
    
    geojson_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith('.geojson')])
    
    if not geojson_files:
        print("  No GeoJSON files found")
        return
    
    # Separate original files from simplified files
    original_files = [
        f for f in geojson_files if not is_simplified_geojson(f)
    ]
    simplified_files = [f for f in geojson_files if is_simplified_geojson(f)]
    
    print(f"\n📄 Original files ({len(original_files)}):")
    for filename in original_files:
        filepath = os.path.join(DATA_DIR, filename)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        
        # Check which simplified versions exist
        base_name = filename.replace(".geojson", "")
        existing_levels = []
        for level in SIMPLIFICATION_LEVELS.keys():
            simplified_path = os.path.join(DATA_DIR, f"{base_name}_{level}.geojson")
            if os.path.exists(simplified_path):
                existing_levels.append(level)
        
        status = f"[{', '.join(existing_levels)}]" if existing_levels else "[no simplified versions]"
        print(f"  • {filename:50} {size_mb:8.2f} MB  {status}")
    
    if simplified_files:
        print(f"\n📊 Simplified files ({len(simplified_files)}):")
        for filename in simplified_files:
            filepath = os.path.join(DATA_DIR, filename)
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            print(f"  • {filename:50} {size_mb:8.2f} MB")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Simplify GeoJSON files at different precision levels',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Simplify all GeoJSON files
  %(prog)s --list                             # List available files
  %(prog)s --interco                          # Simplify intercommunalités only
  %(prog)s --interco --levels 5m 10m          # Interco, 5m and 10m only
  %(prog)s --file communes.geojson            # Simplify only communes
  %(prog)s --file communes.geojson --levels 5m 10m  # Only 5m and 10m levels
        """
    )
    
    parser.add_argument('--list', action='store_true', 
                       help='List available GeoJSON files')
    parser.add_argument('--interco', action='store_true',
                       help='Simplify intercommunalités GeoJSON only (aggregated + par nature)')
    parser.add_argument('--file', type=str, 
                       help='Simplify only this specific file')
    parser.add_argument('--levels', nargs='+', choices=list(SIMPLIFICATION_LEVELS.keys()),
                       help='Simplification levels to apply (default: all)')
    
    args = parser.parse_args()
    
    try:
        if args.list:
            list_geojson_files()
            sys.exit(0)

        if args.interco:
            success = simplify_interco_geojson(args.levels)
            sys.exit(0 if success else 1)
        
        if args.file:
            # Simplify a single file
            success = simplify_single_file(args.file, args.levels)
            sys.exit(0 if success else 1)
        else:
            # Simplify all files (but only with specified levels if given)
            if args.levels:
                print(f"⚠️  --levels option is only used with --file")
                print(f"   Simplifying all files with all levels...\n")
            
            success = simplify_all_geojson()
            sys.exit(0 if success else 1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

