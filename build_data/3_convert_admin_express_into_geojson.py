#!/usr/bin/env python3
"""
Script to convert AdminExpress GPKG to GeoJSON format
Converts multiple GPKG layers from sources/ to GeoJSON files in data/
"""

import gzip
import os
import sys
from pathlib import Path

import geopandas as gpd

# Paths
SOURCES_DIR = "sources"
DATA_DIR = "data"

GPKG_NAME = "admin_express.gpkg"

GPKG_LAYERS_TO_CONVERT = {
    "commune": "communes-admin-express.geojson.gz",
    "arrondissement_municipal": "arrondissements-columns-to-change.geojson.gz",
    "commune_associee_ou_deleguee": "communes-deleguees-et-associees.geojson.gz",
    "collectivite_territoriale": "collectivite_territoriale.geojson.gz",
}


def convert_gpkg_to_geojson(gpkg_path, layer_name, output_name):
    """Convert a single GPKG layer to GeoJSON format"""

    input_path = os.path.join(SOURCES_DIR, gpkg_path)
    output_path = os.path.join(DATA_DIR, output_name)

    print(f"\n{'=' * 60}")
    print(f"Converting {layer_name}")
    print(f"{'=' * 60}")

    # Check if GPKG exists
    if not os.path.exists(input_path):
        print(f"⚠️  Shapefile not found at {input_path}")
        print("   Skipping...")
        return False

    try:
        # Read shapefile with geopandas
        print("📂 Loading GPKG...")
        gdf = gpd.read_file(input_path, layer=layer_name)

        print(f"✓ Loaded {len(gdf)} features")
        print(f"  CRS: {gdf.crs}")
        print(f"  Columns: {', '.join(gdf.columns)}")
        print(f"  Geometry types: {', '.join(gdf.geometry.type.unique())}")

        # Create output directory if it doesn't exist
        os.makedirs(DATA_DIR, exist_ok=True)

        # Convert to GeoJSON and save
        print("🔄 Converting to GeoJSON...")
        # gdf.to_file(output_path, driver='GeoJSON', encoding='utf-8')
        uncompress_name = output_path.replace(".gz", "")
        gdf.to_file(uncompress_name, driver="GeoJSON", encoding="utf-8")
        if output_path.endswith(".gz"):
            with open(uncompress_name, "rb") as orig_file:
                with gzip.open(output_path, "wb") as zipped_file:
                    zipped_file.writelines(orig_file)
            Path(uncompress_name).unlink(missing_ok=True)

        # Get file size for reporting
        file_size = os.path.getsize(output_path)
        file_size_mb = file_size / (1024 * 1024)

        print(f"✓ GeoJSON saved to {output_path}")
        print(f"✓ File size: {file_size_mb:.2f} MB")
        print(f"✓ {len(gdf)} features converted successfully")

        # Display sample of the data
        if len(gdf) > 0:
            first_feature = gdf.iloc[0]
            print("\n📋 Sample attributes:")
            for key, value in dict(first_feature.drop("geometry")).items():
                print(f"  - {key}: {value}")

        return True

    except Exception as e:
        print(f"❌ Error during conversion: {e}")
        return False


def convert_all_shapefiles():
    """Convert all configured shapefiles"""
    print("=" * 60)
    print("GPKG TO GEOJSON CONVERSION")
    print("=" * 60)
    print(f"\n{len(GPKG_LAYERS_TO_CONVERT.keys())} layers to convert:")
    for shapefile, output in GPKG_LAYERS_TO_CONVERT.items():
        print(f"  • {shapefile} → {output}")

    success_count = 0
    failed_count = 0
    skipped_count = 0

    for layer_name, output_name in GPKG_LAYERS_TO_CONVERT.items():
        result = convert_gpkg_to_geojson(GPKG_NAME, layer_name, output_name)
        if result:
            success_count += 1
        elif result is False and os.path.exists(os.path.join(SOURCES_DIR, layer_name)):
            failed_count += 1
        else:
            skipped_count += 1

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"✓ Successfully converted: {success_count}")
    if skipped_count > 0:
        print(f"⚠️  Skipped (file not found): {skipped_count}")
    if failed_count > 0:
        print(f"❌ Failed: {failed_count}")
    print("=" * 60)

    if success_count > 0:
        print("\n🎉 Conversion completed!")
        print("\nGenerated files in 'data/' directory:")
        for shapefile_name, output_name in GPKG_LAYERS_TO_CONVERT.items():
            output_path = os.path.join(DATA_DIR, output_name)
            if os.path.exists(output_path):
                print(f"  ✓ {output_name}")

    return success_count > 0


def list_available_shapefiles():
    """List all available shapefiles in the sources directory"""
    print(f"\n{'=' * 60}")
    print(f"Available shapefiles in {SOURCES_DIR}/")
    print("=" * 60)

    if not os.path.exists(SOURCES_DIR):
        print(f"❌ Directory {SOURCES_DIR} not found!")
        return

    shapefiles = sorted([f for f in os.listdir(SOURCES_DIR) if f.endswith(".shp")])

    if not shapefiles:
        print("  No shapefiles found")
    else:
        for shapefile in shapefiles:
            shapefile_path = os.path.join(SOURCES_DIR, shapefile)
            try:
                gdf = gpd.read_file(shapefile_path)
                in_config = "✓" if shapefile in GPKG_LAYERS_TO_CONVERT else " "
                print(f"  [{in_config}] {shapefile} ({len(gdf)} features)")
            except Exception as e:
                print(f"  [ ] {shapefile} (error: {e})")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert shapefiles to GeoJSON")
    parser.add_argument("--list", action="store_true", help="List available shapefiles")
    parser.add_argument("--single", type=str, help="Convert a single shapefile")
    args = parser.parse_args()

    if args.list:
        list_available_shapefiles()
        sys.exit(0)

    if args.single:
        # Convert a single shapefile
        if args.single in GPKG_LAYERS_TO_CONVERT:
            output_name = GPKG_LAYERS_TO_CONVERT[args.single]
            success = convert_gpkg_to_geojson(GPKG_NAME, args.single, output_name)
            sys.exit(0 if success else 1)
        else:
            print(f"❌ Shapefile '{args.single}' not in configuration")
            print("\nAvailable shapefiles to convert:")
            for layer in GPKG_LAYERS_TO_CONVERT.keys():
                print(f"  - {layer}")
            sys.exit(1)

    # Default: convert all shapefiles, then generate aggregated GeoJSON
    try:
        success = convert_all_shapefiles()
        if not success:
            print("\n⚠️  Shapefile conversion had issues")

        # Final summary
        print("\n" + "=" * 60)
        print("FINAL SUMMARY")
        print("=" * 60)

        print("\n📄 Shapefiles converted to GeoJSON:")
        for output_name in GPKG_LAYERS_TO_CONVERT.values():
            output_path = os.path.join(DATA_DIR, output_name)
            if os.path.exists(output_path):
                print(f"  ✓ {output_name}")

        print("\n🎉 All done!")
        sys.exit(0)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
