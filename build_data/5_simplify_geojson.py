#!/usr/bin/env python3
"""
Script to simplify GeoJSON files at different precision levels
Generates simplified versions at 5m, 10m, 100m, and 1000m precision
Uses Douglas-Peucker algorithm via Shapely
"""

import gzip
import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

# Paths
DATA_DIR = "data"

# Simplification tolerances (in decimal degrees, approximation for WGS84 at ~45°N latitude)
# Conversion: 1 degree ≈ 111km at equator, ~78km at 45°N for longitude
# For safety, using conservative values
SIMPLIFICATION_LEVELS = {
    "5m": 0.000045,  # ~5 meters
    "10m": 0.00009,  # ~10 meters
    "100m": 0.0009,  # ~100 meters
    "1000m": 0.009,  # ~1000 meters
}


def simplify_geojson(input_filename, tolerance, tolerance_label):
    """Simplify a GeoJSON file with given tolerance"""

    input_path = os.path.join(DATA_DIR, input_filename)

    # Generate output filename
    base_name = input_filename.replace(".geojson.gz", "").replace(".geojson", "")
    output_filename = f"{base_name}_{tolerance_label}.geojson.gz"
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
        if input_path.endswith(".gz"):
            input_path = f"/vsigzip/{input_path}"
        gdf = gpd.read_file(input_path)
        print(f"({len(gdf)} features)")

        # Simplify geometries
        print(
            f"  🔄 Simplifying with tolerance {tolerance_label} ({tolerance}°)...",
            end=" ",
        )
        gdf["geometry"] = gdf["geometry"].simplify_coverage(tolerance)

        # Save simplified GeoJSON
        uncompress_name = output_path.replace(".gz", "")
        gdf.to_file(uncompress_name, driver="GeoJSON", encoding="utf-8")
        if input_path.endswith(".gz"):
            with open(uncompress_name, "rb") as orig_file:
                with gzip.open(output_path, "wb") as zipped_file:
                    zipped_file.writelines(orig_file)
            Path(uncompress_name).unlink(missing_ok=True)

        # Get simplified file size
        simplified_size = os.path.getsize(output_path) / (1024 * 1024)
        reduction = (
            ((original_size - simplified_size) / original_size) * 100
            if original_size > 0
            else 0
        )

        print("✓")
        print(f"  💾 Saved: {output_filename}")
        print(
            f"  📊 Size: {original_size:.2f} MB → {simplified_size:.2f} MB (-{reduction:.1f}%)"
        )

        return {
            "output_file": output_filename,
            "original_size": original_size,
            "simplified_size": simplified_size,
            "reduction_percent": reduction,
            "features": len(gdf),
        }

    except Exception as e:
        print("❌")
        print(f"  ❌ Error: {e}")
        return None


def simplify_communes_arm_geojson(
    input_filename_communes, input_filename_arm, tolerance, tolerance_label
):
    """Simplify a GeoJSON file with given tolerance"""

    input_path_communes = os.path.join(DATA_DIR, input_filename_communes)
    input_path_arm = os.path.join(DATA_DIR, input_filename_arm)

    # Generate output filename
    base_name_communes = input_filename_communes.replace(".geojson.gz", "").replace(
        ".geojson", ""
    )
    base_name_arm = input_filename_arm.replace(".geojson.gz", "").replace(
        ".geojson", ""
    )

    output_filename_communes = f"{base_name_communes}_{tolerance_label}.geojson.gz"
    output_path_communes = os.path.join(DATA_DIR, output_filename_communes)

    output_filename_arm = f"{base_name_arm}_{tolerance_label}.geojson.gz"
    output_path_arm = os.path.join(DATA_DIR, output_filename_arm)

    # Check if input file communes exists
    if not os.path.exists(input_path_communes):
        print(f"  ⚠️  File not found: {input_path_communes}")
        return None

    # Check if input file arm exists
    if not os.path.exists(input_path_arm):
        print(f"  ⚠️  File not found: {input_path_arm}")
        return None

    # Get original file size
    original_size_communes = os.path.getsize(input_path_communes) / (1024 * 1024)
    original_size_arm = os.path.getsize(input_path_arm) / (1024 * 1024)

    try:
        # Load GeoJSON
        print(f"  📂 Loading {input_filename_communes}...", end=" ")
        if input_path_communes.endswith(".gz"):
            input_path_communes = f"/vsigzip/{input_path_communes}"
        gdf_communes = gpd.read_file(input_path_communes)
        gdf_communes_no_75056_69123_13055 = gdf_communes[
            ~gdf_communes["code_insee"].isin(["75056", "69123", "13055"])
        ]
        print(f"({len(gdf_communes)} features)")

        # Simplify geometries for communes alone
        # print(f"  🔄 Simplifying with tolerance {tolerance_label} ({tolerance}°)...", end=" ")
        # gdf_communes['geometry'] = gdf_communes['geometry'].simplify_coverage(tolerance)
        print(f"  📂 Loading {input_filename_arm}...", end=" ")
        if input_path_arm.endswith(".gz"):
            input_path_arm = f"/vsigzip/{input_path_arm}"
        gdf_arm = gpd.read_file(input_path_arm)
        print(f"({len(gdf_arm)} features)")

        # Merge ARM and communes without 75056, 69123, 13055 geometries
        gdf_arm_for_mix = gdf_arm[
            ["code_insee", "code_insee_de_la_commune_de_rattach", "geometry"]
        ].rename(
            columns={
                "code_insee": "insee",
                "code_insee_de_la_commune_de_rattach": "com",
            }
        )
        gdf_arm_for_mix["category"] = "arm"
        gdf_communes_no_75056_69123_13055_mix = gdf_communes_no_75056_69123_13055[
            ["code_insee", "geometry"]
        ].rename(columns={"code_insee": "insee"})
        gdf_communes_no_75056_69123_13055_mix["com"] = ""
        gdf_communes_no_75056_69123_13055_mix["category"] = "com"
        gdf_communes_arm = pd.concat(
            [gdf_communes_no_75056_69123_13055_mix, gdf_arm_for_mix]
        )
        # Simplify
        gdf_communes_arm["geometry"] = gdf_communes_arm["geometry"].simplify_coverage(
            tolerance
        )
        gdf_arm_simplified = gdf_communes_arm[gdf_communes_arm["category"] == "arm"]
        only_75056_69123_13055_simplified = gdf_arm_simplified.dissolve(
            by="com"
        ).reset_index()
        only_75056_69123_13055_simplified = only_75056_69123_13055_simplified[
            ["com", "geometry"]
        ].rename(columns={"com": "insee"})
        gdf_communes_simplified = pd.concat(
            [
                gdf_communes_arm[gdf_communes_arm["category"] == "com"][
                    ["insee", "geometry"]
                ],
                only_75056_69123_13055_simplified,
            ]
        )
        gdf_communes_updated = pd.merge(
            gdf_communes,
            gdf_communes_simplified,
            left_on="code_insee",
            right_on="insee",
        )
        gdf_communes_updated["geometry"] = gdf_communes_updated["geometry_y"]
        gdf_communes_updated = gdf_communes_updated[
            [
                "code_insee",
                "nom_officiel",
                "nom_officiel_en_majuscules",
                "statut",
                "code_insee_du_departement",
                "code_insee_de_la_region",
                "population",
                "superficie_cadastrale",
                "zone",
                "geometry",
            ]
        ]
        gdf_arm_updated = pd.merge(
            gdf_arm, gdf_arm_simplified, left_on="code_insee", right_on="insee"
        )
        gdf_arm_updated["geometry"] = gdf_arm_updated["geometry_y"]
        gdf_arm_updated = gdf_arm_updated[
            [
                "nom_officiel",
                "nom_officiel_en_majuscules",
                "numero_de_l_arrondissement_municipal",
                "code_insee",
                "code_insee_de_la_commune_de_rattach",
                "code_insee_du_departement",
                "code_insee_de_la_region",
                "code_postal",
                "population",
                "zone",
                "geometry",
            ]
        ]

        # Save simplified GeoJSON
        print(f"  📂 Write file to {output_path_arm}")
        uncompress_name_arm = output_path_arm.replace(".gz", "")
        gdf_arm_updated.to_file(uncompress_name_arm, driver="GeoJSON", encoding="utf-8")
        if input_path_communes.endswith(".gz"):
            with open(uncompress_name_arm, "rb") as orig_file:
                with gzip.open(output_path_arm, "wb") as zipped_file:
                    zipped_file.writelines(orig_file)
            Path(uncompress_name_arm).unlink(missing_ok=True)

        # Save simplified GeoJSON
        print(f"  📂 Write file to {output_path_communes}")
        uncompress_name_communes = output_path_communes.replace(".gz", "")
        gdf_communes_updated.to_file(
            uncompress_name_communes, driver="GeoJSON", encoding="utf-8"
        )
        if input_path_communes.endswith(".gz"):
            with open(uncompress_name_communes, "rb") as orig_file:
                with gzip.open(output_path_communes, "wb") as zipped_file:
                    zipped_file.writelines(orig_file)
            Path(uncompress_name_communes).unlink(missing_ok=True)

        print("  📂 Get files size for communes")
        # Get simplified file size
        simplified_size_communes = os.path.getsize(output_path_communes) / (1024 * 1024)
        reduction_communes = (
            (
                (original_size_communes - simplified_size_communes)
                / original_size_communes
            )
            * 100
            if original_size_communes > 0
            else 0
        )
        print("  📂 Get files size for arm")
        simplified_size_arm = os.path.getsize(output_path_arm) / (1024 * 1024)
        reduction_arm = (
            ((original_size_arm - simplified_size_arm) / original_size_arm) * 100
            if original_size_arm > 0
            else 0
        )

        print("✓")
        print(f"  💾 Saved: {output_filename_arm}")
        print(
            f"  📊 Size: {original_size_arm:.2f} MB → {simplified_size_arm:.2f} MB (-{reduction_arm:.1f}%)"
        )

        print("✓")
        print(f"  💾 Saved: {output_filename_communes}")
        print(
            f"  📊 Size: {original_size_communes:.2f} MB → {simplified_size_communes:.2f} MB (-{reduction_communes:.1f}%)"
        )
        return [
            {
                "output_file": output_filename_arm,
                "original_size": original_size_arm,
                "simplified_size": simplified_size_arm,
                "reduction_percent": reduction_arm,
                "features": len(gdf_arm_updated),
            },
            {
                "output_file": output_filename_communes,
                "original_size": original_size_communes,
                "simplified_size": simplified_size_communes,
                "reduction_percent": reduction_communes,
                "features": len(gdf_communes_updated),
            },
        ]

    except Exception as e:
        print("❌")
        print(f"  ❌ Error: {e}")
        return None


def simplify_all_geojson():
    """Simplify all GeoJSON files at all tolerance levels"""

    print("=" * 70)
    print("GEOJSON SIMPLIFICATION")
    print("=" * 70)

    # Get all GeoJSON files

    print("\n📋 Will simplify 3 GeoJSON files")
    print(f"🎯 Simplification levels: {', '.join(SIMPLIFICATION_LEVELS.keys())}")

    # Statistics
    total_files = 3
    total_levels = len(SIMPLIFICATION_LEVELS)
    total_operations = total_files * total_levels
    completed = 0
    failed = 0
    skipped = 0

    results_summary = []

    # Process each file
    filename = "communes-deleguees-et-associees.geojson.gz"
    print(f"\n{'=' * 70}")
    print(f"Processing: {filename}")
    print(f"{'=' * 70}")

    file_results = {"filename": filename, "levels": {}}

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

    # Apply each simplification level
    file_results_arm = {"filename": "arrondissements.geojson.gz", "levels": {}}
    file_results_communes = {"filename": "communes.geojson.gz", "levels": {}}
    for level_name, tolerance in SIMPLIFICATION_LEVELS.items():
        results = simplify_communes_arm_geojson(
            "communes.geojson.gz", "arrondissements.geojson.gz", tolerance, level_name
        )
        if results:
            file_results_arm["levels"][level_name] = results[0]
            file_results_communes["levels"][level_name] = results[1]
            completed += 2
        elif (
            results is None
            and not os.path.exists(os.path.join(DATA_DIR, "communes.geojson.gz"))
            and not os.path.exists(os.path.join(DATA_DIR, "arrondissements.geojson.gz"))
        ):
            skipped += 2
        else:
            failed += 2

    results_summary.append(file_results_arm)
    results_summary.append(file_results_communes)

    # Final summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print("\n📊 Operations:")
    print(f"  ✓ Completed: {completed}/{total_operations}")
    if skipped > 0:
        print(f"  ⚠️  Skipped: {skipped}/{total_operations}")
    if failed > 0:
        print(f"  ❌ Failed: {failed}/{total_operations}")

    print("\n📁 Generated files by simplification level:")
    for level_name in SIMPLIFICATION_LEVELS.keys():
        count = sum(1 for r in results_summary if level_name in r["levels"])
        print(f"  {level_name:>6}: {count} files")

    # Show average size reduction
    print("\n📉 Average size reduction by level:")
    for level_name in SIMPLIFICATION_LEVELS.keys():
        reductions = [
            r["levels"][level_name]["reduction_percent"]
            for r in results_summary
            if level_name in r["levels"]
        ]
        if reductions:
            avg_reduction = sum(reductions) / len(reductions)
            print(f"  {level_name:>6}: {avg_reduction:.1f}%")

    print("\n🎉 Simplification completed!")
    print("\n💡 Usage examples:")
    print("  - Use *_5m.geojson for high-detail zoom levels")
    print("  - Use *_10m.geojson for medium-detail zoom levels")
    print("  - Use *_100m.geojson for low-detail zoom levels")
    print("  - Use *_1000m.geojson for overview/country-wide views")

    return completed > 0


def simplify_single_file(filename, levels=None):
    """Simplify a single GeoJSON file"""

    print("=" * 70)
    print(f"SIMPLIFYING: {filename}")
    print("=" * 70)

    # Determine which levels to use
    if levels:
        # Validate levels
        invalid_levels = [
            level for level in levels if level not in SIMPLIFICATION_LEVELS
        ]
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

    print("=" * 70)
    if completed > 0:
        print(f"✓ {completed} simplification(s) completed successfully")
    if failed > 0:
        print(f"❌ {failed} simplification(s) failed")

    return completed > 0


def list_geojson_files():
    """List all available GeoJSON files in data directory"""

    print("=" * 70)
    print(f"Available GeoJSON files in {DATA_DIR}/")
    print("=" * 70)

    if not os.path.exists(DATA_DIR):
        print(f"❌ Directory {DATA_DIR} not found!")
        return

    geojson_files = sorted([f for f in os.listdir(DATA_DIR) if f.endswith(".geojson")])

    if not geojson_files:
        print("  No GeoJSON files found")
        return

    # Separate original files from simplified files
    original_files = [
        f
        for f in geojson_files
        if not any(
            f.endswith(f"_{level}.geojson") for level in SIMPLIFICATION_LEVELS.keys()
        )
    ]
    simplified_files = [
        f
        for f in geojson_files
        if any(
            f.endswith(f"_{level}.geojson") for level in SIMPLIFICATION_LEVELS.keys()
        )
    ]

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

        status = (
            f"[{', '.join(existing_levels)}]"
            if existing_levels
            else "[no simplified versions]"
        )
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
        description="Simplify GeoJSON files at different precision levels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Simplify all GeoJSON files
  %(prog)s --list                             # List available files
  %(prog)s --file communes.geojson            # Simplify only communes
  %(prog)s --file communes.geojson --levels 5m 10m  # Only 5m and 10m levels
        """,
    )

    parser.add_argument(
        "--list", action="store_true", help="List available GeoJSON files"
    )
    parser.add_argument("--file", type=str, help="Simplify only this specific file")
    parser.add_argument(
        "--levels",
        nargs="+",
        choices=list(SIMPLIFICATION_LEVELS.keys()),
        help="Simplification levels to apply (default: all)",
    )

    args = parser.parse_args()

    try:
        if args.list:
            list_geojson_files()
            sys.exit(0)

        if args.file:
            # Simplify a single file
            success = simplify_single_file(args.file, args.levels)
            sys.exit(0 if success else 1)
        else:
            # Simplify all files (but only with specified levels if given)
            if args.levels:
                print("⚠️  --levels option is only used with --file")
                print("   Simplifying all files with all levels...\n")

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
