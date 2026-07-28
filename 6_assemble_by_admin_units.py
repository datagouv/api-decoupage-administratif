import json
import os
import sys
import gzip

import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union
from shapely.geometry import mapping

# Paths
DATA_DIR = "data"

SIMPLIFICATION_LEVELS_TITLES = [
    "5m",
    "10m",
    "100m",
    "1000m",
]

def generate_departements_geojson(communes_file_name, tolerance_label):
    """Generate GeoJSON for départements by merging commune geometries"""
    print("\n" + "="*60)
    print(f"GENERATING DÉPARTEMENTS GEOJSON FOR TOLERANCE LABEL {tolerance_label}")
    print("="*60)
    
    communes_path = os.path.join(DATA_DIR, communes_file_name)
    departements_csv = os.path.join(DATA_DIR, "departements.csv")
    output_path = os.path.join(DATA_DIR, f"departements_{tolerance_label}.geojson.gz")
    
    if not os.path.exists(communes_path):
        print(f"⚠️  {communes_path} not found. Run this script without --aggregate first.")
        return False
    
    if not os.path.exists(departements_csv):
        print(f"⚠️  {departements_csv} not found. Run 1_download_decoupage_administratif_data.py first.")
        return False
    
    print(f"\n📂 Loading communes GeoJSON...")
    if communes_path.endswith(communes_path):
        communes_path = f"/vsigzip/{communes_path}"
    gdf_communes = gpd.read_file(communes_path)
    print(f"✓ Loaded {len(gdf_communes)} communes")
    
    print(f"\n📂 Loading départements metadata...")
    df_dep = pd.read_csv(departements_csv, dtype=str)
    print(f"✓ Loaded {len(df_dep)} départements")
    
    print(f"\n🔄 Merging commune geometries by département...")
    
    # Group communes by département and merge geometries
    departements_features = []
    processed = 0
    
    for idx, dep_row in df_dep.iterrows():
        dep_code = dep_row['dep']
        
        # Get all communes for this département
        communes_dep = gdf_communes[gdf_communes['code_insee_du_departement'] == dep_code]
        
        if len(communes_dep) == 0:
            print(f"  ⚠️  No communes found for département {dep_code}")
            continue
        
        # Merge all geometries
        merged_geom = unary_union(communes_dep.geometry.values)
        
        # Create feature
        feature = {
            "type": "Feature",
            "properties": dep_row.to_dict(),
            "geometry": mapping(merged_geom)
        }
        departements_features.append(feature)
        
        processed += 1
        if processed % 10 == 0:
            print(f"  {processed}/{len(df_dep)} départements processed...", end='\r')
    
    print(f"\n✓ {processed} départements processed")
    
    # Create FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": departements_features
    }
    
    # Save to file
    print(f"\n💾 Saving to {output_path}...")
    with gzip.open(output_path, 'wt', encoding='UTF-8') as f:
        json.dump(geojson, f, ensure_ascii=False)
    
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✓ GeoJSON saved ({file_size:.2f} MB)")
    print(f"✓ {len(departements_features)} départements")
    
    return True

def generate_regions_geojson(communes_file_name, tolerance_label):
    """Generate GeoJSON for régions by merging commune geometries"""
    print("\n" + "="*60)
    print(f"GENERATING RÉGIONS GEOJSON FOR TOLERANCE LABEL {tolerance_label}")
    print("="*60)
    
    communes_path = os.path.join(DATA_DIR, communes_file_name)
    regions_csv = os.path.join(DATA_DIR, "regions.csv")
    output_path = os.path.join(DATA_DIR, f"regions_{tolerance_label}.geojson.gz")
    
    if not os.path.exists(communes_path):
        print(f"⚠️  {communes_path} not found. Run this script without --aggregate first.")
        return False
    
    if not os.path.exists(regions_csv):
        print(f"⚠️  {regions_csv} not found. Run 1_download_decoupage_administratif_data.py first.")
        return False
    
    print(f"\n📂 Loading communes GeoJSON...")
    if communes_path.endswith('.gz'):
        communes_path = f"/vsigzip/{communes_path}"
    gdf_communes = gpd.read_file(communes_path)
    print(f"✓ Loaded {len(gdf_communes)} communes")
    
    print(f"\n📂 Loading régions metadata...")
    df_reg = pd.read_csv(regions_csv, dtype=str)
    print(f"✓ Loaded {len(df_reg)} régions")
    
    print(f"\n🔄 Merging commune geometries by région...")
    
    # Group communes by région and merge geometries
    regions_features = []
    processed = 0
    
    for idx, reg_row in df_reg.iterrows():
        reg_code = reg_row['reg']
        
        # Get all communes for this région
        communes_reg = gdf_communes[gdf_communes['code_insee_de_la_region'] == reg_code]
        
        if len(communes_reg) == 0:
            print(f"  ⚠️  No communes found for région {reg_code}")
            continue
        
        # Merge all geometries
        merged_geom = unary_union(communes_reg.geometry.values)
        
        # Create feature
        feature = {
            "type": "Feature",
            "properties": reg_row.to_dict(),
            "geometry": mapping(merged_geom)
        }
        regions_features.append(feature)
        
        processed += 1
        if processed % 5 == 0:
            print(f"  {processed}/{len(df_reg)} régions processed...", end='\r')
    
    print(f"\n✓ {processed} régions processed")
    
    # Create FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": regions_features
    }
    
    # Save to file
    print(f"\n💾 Saving to {output_path}...")

    with gzip.open(output_path, 'wt', encoding='UTF-8') as f:
        json.dump(geojson, f, ensure_ascii=False)
    
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✓ GeoJSON saved ({file_size:.2f} MB)")
    print(f"✓ {len(regions_features)} régions")
    
    return True

def generate_interco_geojson(communes_file_name, tolerance_label):
    """Generate GeoJSON for intercommunalités by merging commune geometries"""
    print("\n" + "="*60)
    print(f"GENERATING INTERCOMMUNALITÉS GEOJSON FOR TOLERANCE LABEL {tolerance_label}")
    print("="*60)
    
    communes_path = os.path.join(DATA_DIR, communes_file_name)
    interco_csv = os.path.join(DATA_DIR, "interco_enriched.csv")
    output_path = os.path.join(DATA_DIR, f"intercommunalites_{tolerance_label}.geojson.gz")
    
    if not os.path.exists(communes_path):
        print(f"⚠️  {communes_path} not found. Run this script without --aggregate first.")
        return False
    
    if not os.path.exists(interco_csv):
        print(f"⚠️  {interco_csv} not found. Run 1_download_decoupage_administratif_data.py first.")
        return False
    
    print(f"\n📂 Loading communes GeoJSON...")
    if communes_path.endswith('.gz'):
        communes_path = f"/vsigzip/{communes_path}"
    gdf_communes = gpd.read_file(communes_path)
    print(f"✓ Loaded {len(gdf_communes)} communes")
    
    print(f"\n📂 Loading intercommunalités metadata...")
    df_interco = pd.read_csv(interco_csv, dtype=str)
    print(f"✓ Loaded {len(df_interco)} intercommunalités")
    
    # Create a mapping of code INSEE -> geometry
    print(f"\n🔄 Creating commune code → geometry mapping...")
    commune_geoms = {}
    for idx, row in gdf_communes.iterrows():
        code = row.get('code_insee')
        if code:
            commune_geoms[code] = row.geometry
    
    print(f"✓ {len(commune_geoms)} communes indexed")
    
    print(f"\n🔄 Merging commune geometries by intercommunalité...")
    
    # Process each intercommunalité
    interco_features = []
    processed = 0
    skipped = 0
    
    for idx, interco_row in df_interco.iterrows():
        communes_code_json = interco_row.get('communes_code')
        
        if pd.isna(communes_code_json) or not communes_code_json:
            skipped += 1
            continue
        
        try:
            # Parse the JSON list of commune codes
            communes_codes = json.loads(communes_code_json)
            
            if not communes_codes:
                skipped += 1
                continue
            
            # Collect geometries
            geometries = []
            for code in communes_codes:
                if code in commune_geoms:
                    geometries.append(commune_geoms[code])
            
            if not geometries:
                skipped += 1
                continue
            
            # Merge geometries
            merged_geom = unary_union(geometries)
            
            # Create properties (exclude communes_code, communes_siren from output)
            properties = interco_row.drop(['communes_code', 'communes_siren', 'membres_siren']).to_dict()
            
            # Create feature
            feature = {
                "type": "Feature",
                "properties": properties,
                "geometry": mapping(merged_geom)
            }
            interco_features.append(feature)
            
            processed += 1
            if processed % 100 == 0:
                print(f"  {processed}/{len(df_interco)-skipped} intercommunalités processed...", end='\r')
        
        except Exception as e:
            print(f"\n  ⚠️  Error processing intercommunalité {interco_row.get('nn_siren', 'unknown')}: {e}")
            skipped += 1
            continue
    
    print(f"\n✓ {processed} intercommunalités processed, {skipped} skipped")
    
    # Create FeatureCollection
    geojson = {
        "type": "FeatureCollection",
        "features": interco_features
    }
    
    # Save to file
    print(f"\n💾 Saving to {output_path}...")
    with gzip.open(output_path, 'wt', encoding='UTF-8') as f:
        json.dump(geojson, f, ensure_ascii=False)
    
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✓ GeoJSON saved ({file_size:.2f} MB)")
    print(f"✓ {len(interco_features)} intercommunalités")
    
    # Generate separate GeoJSON by nature_juridique
    print(f"\n🔄 Generating GeoJSON by nature juridique...")
    generate_interco_by_nature(df_interco, commune_geoms, tolerance_label)
    
    return True


def generate_aom_geojson(communes_file_name, tolerance_label):
    """Generate GeoJSON for AOM by merging commune geometries of their members."""
    print("\n" + "=" * 60)
    print(f"GENERATING AOM GEOJSON FOR TOLERANCE LABEL {tolerance_label}")
    print("=" * 60)

    communes_path = os.path.join(DATA_DIR, communes_file_name)
    aom_csv = os.path.join(DATA_DIR, "aom.csv")
    aom_commune_csv = os.path.join(DATA_DIR, "aom_commune.csv")
    mapping_csv = os.path.join(DATA_DIR, "siren_insee_mapping.csv")
    output_path = os.path.join(DATA_DIR, f"aom_{tolerance_label}.geojson.gz")

    required = {
        communes_path: "communes.geojson (run shapefile conversion first)",
        aom_csv: "aom.csv (run 1_download_decoupage_administratif_data.py first)",
        aom_commune_csv: "aom_commune.csv",
        mapping_csv: "siren_insee_mapping.csv",
    }
    for path, label in required.items():
        if not os.path.exists(path):
            print(f"⚠️  {path} not found ({label})")
            return False

    print(f"\n📂 Loading communes GeoJSON...")
    if communes_path.endswith('.gz'):
        communes_path = f"/vsigzip/{communes_path}"
    gdf_communes = gpd.read_file(communes_path)
    print(f"✓ Loaded {len(gdf_communes)} communes")

    print(f"\n📂 Loading AOM metadata...")
    df_aom = pd.read_csv(aom_csv, dtype=str)
    df_members = pd.read_csv(aom_commune_csv, dtype=str)
    df_mapping = pd.read_csv(mapping_csv, dtype=str)
    print(f"✓ {len(df_aom)} AOM, {len(df_members)} liaisons commune → AOM")

    siren_to_insee = dict(zip(df_mapping["Siren"], df_mapping["COM"]))

    print(f"\n🔄 Creating commune code → geometry mapping...")
    commune_geoms = {}
    for _, row in gdf_communes.iterrows():
        code = row.get("code_insee")
        if code:
            commune_geoms[code] = row.geometry
    print(f"✓ {len(commune_geoms)} communes indexed")

    aom_names = dict(zip(df_aom["siren"], df_aom["nom"]))
    members_by_aom = df_members.groupby("siren_aom")["siren_commune"].apply(list).to_dict()

    print(f"\n🔄 Merging commune geometries by AOM...")
    aom_features = []
    processed = 0
    skipped = 0

    for siren_aom, commune_sirens in members_by_aom.items():
        if not siren_aom or pd.isna(siren_aom):
            skipped += 1
            continue

        commune_codes = []
        geometries = []
        for commune_siren in commune_sirens:
            if not commune_siren or pd.isna(commune_siren):
                continue
            code_insee = siren_to_insee.get(commune_siren)
            if not code_insee:
                continue
            commune_codes.append(code_insee)
            if code_insee in commune_geoms:
                geometries.append(commune_geoms[code_insee])

        commune_codes = sorted(set(commune_codes))
        if not geometries:
            skipped += 1
            continue

        try:
            merged_geom = unary_union(geometries)
            properties = {
                "siren": siren_aom,
                "nom": aom_names.get(siren_aom),
                "nb_communes": len(commune_codes),
                "communes_code": json.dumps(commune_codes, ensure_ascii=False),
            }
            aom_features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": mapping(merged_geom),
                }
            )
            processed += 1
            if processed % 50 == 0:
                print(f"  {processed} AOM processed...", end="\r")
        except Exception as e:
            print(f"\n  ⚠️  Error processing AOM {siren_aom}: {e}")
            skipped += 1

    print(f"\n✓ {processed} AOM processed, {skipped} skipped")

    geojson = {"type": "FeatureCollection", "features": aom_features}
    print(f"\n💾 Saving to {output_path}...")
    with gzip.open(output_path, 'wt', encoding='UTF-8') as f:
        json.dump(geojson, f, ensure_ascii=False)

    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"✓ GeoJSON saved ({file_size:.2f} MB)")
    print(f"✓ {len(aom_features)} AOM")
    return True


def generate_interco_by_nature(df_interco, commune_geoms, tolerance_label):
    """Generate separate GeoJSON files for each nature_juridique"""
    
    # Get unique nature_juridique values
    natures = df_interco['nature_juridique'].dropna().unique()
    print(f"\n  Found {len(natures)} different nature juridique:")
    
    for nature in natures:
        # Clean nature for filename (remove special characters)
        nature_clean = nature.replace('/', '_').replace(' ', '_').replace("'", '').lower()
        output_path = os.path.join(DATA_DIR, f"intercommunalites_{nature_clean}_{tolerance_label}.geojson.gz")
        
        print(f"\n  Processing: {nature} for tolerance {tolerance_label}")
        
        # Filter intercommunalités for this nature
        df_filtered = df_interco[df_interco['nature_juridique'] == nature]
        print(f"    {len(df_filtered)} intercommunalités")
        
        # Process each intercommunalité
        features = []
        processed = 0
        skipped = 0
        
        for idx, interco_row in df_filtered.iterrows():
            communes_code_json = interco_row.get('communes_code')
            
            if pd.isna(communes_code_json) or not communes_code_json:
                skipped += 1
                continue
            
            try:
                communes_codes = json.loads(communes_code_json)
                
                if not communes_codes:
                    skipped += 1
                    continue
                
                # Collect geometries
                geometries = []
                for code in communes_codes:
                    if code in commune_geoms:
                        geometries.append(commune_geoms[code])
                
                if not geometries:
                    skipped += 1
                    continue
                
                # Merge geometries
                merged_geom = unary_union(geometries)
                
                # Create properties
                properties = interco_row.drop(['communes_code', 'communes_siren', 'membres_siren']).to_dict()
                
                # Create feature
                feature = {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": mapping(merged_geom)
                }
                features.append(feature)
                processed += 1
            
            except Exception as e:
                skipped += 1
                continue
        
        # Create FeatureCollection
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        # Save to file
        with gzip.open(output_path, 'wt', encoding='UTF-8') as f:
            json.dump(geojson, f, ensure_ascii=False)
        
        file_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"    ✓ Saved {len(features)} features ({file_size:.2f} MB)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate aggregated GeoJSON (departements, regions, intercommunalites)')
    args = parser.parse_args()
    
        
    # Default: convert all shapefiles, then generate aggregated GeoJSON
    try:
        # Generate aggregated GeoJSON
        print("\n" + "="*60)
        print("GENERATING AGGREGATED GEOJSON")
        print("="*60)
        
        success_dep = all([generate_departements_geojson(f"communes_{tolerance_label}.geojson.gz", tolerance_label) for tolerance_label in SIMPLIFICATION_LEVELS_TITLES])
        success_reg = all([generate_regions_geojson(f"communes_{tolerance_label}.geojson.gz", tolerance_label) for tolerance_label in SIMPLIFICATION_LEVELS_TITLES])
        success_interco = all([generate_interco_geojson(f"communes_{tolerance_label}.geojson.gz", tolerance_label) for tolerance_label in SIMPLIFICATION_LEVELS_TITLES])
        success_aom = all([generate_aom_geojson(f"communes_{tolerance_label}.geojson.gz", tolerance_label) for tolerance_label in SIMPLIFICATION_LEVELS_TITLES])
        
        # Final summary
        print("\n" + "="*60)
        print("FINAL SUMMARY")
        print("="*60)
        
        print("\n📦 Aggregated GeoJSON generated:")
        if success_dep:
            for tolerance_label in SIMPLIFICATION_LEVELS_TITLES:
                print(f"  ✓ departements_{tolerance_label}.geojson.gz")
        if success_reg:
            for tolerance_label in SIMPLIFICATION_LEVELS_TITLES:
                print(f"  ✓ regions_{tolerance_label}.geojson.gz")
        if success_interco:
            for tolerance_label in SIMPLIFICATION_LEVELS_TITLES:
                print(f"  ✓ intercommunalites_{tolerance_label}.geojson.gz")
            print(f"  ✓ intercommunalites_*.geojson.gz (by nature juridique) for levels {', '.join(SIMPLIFICATION_LEVELS_TITLES)}")
        if success_aom:
            for tolerance_label in SIMPLIFICATION_LEVELS_TITLES:
                print(f"  ✓ aom_{tolerance_label}.geojson.gz")

        print("\n🎉 All done!")
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
