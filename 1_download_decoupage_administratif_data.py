#!/usr/bin/env python3
"""
Télécharge et prépare les données de découpage administratif et assimilées.

Sources :
- COG (communes, arrondissements, communes déléguées/associées, départements, régions)
- Banatic (SIREN, intercommunalités, membres)
- La Poste (codes postaux)
- AOM (Autorités Organisatrices de Mobilité, fichier ODS annuel data.gouv.fr)
- Mairies GeoJSON (contours administratifs)

Produit dans data/ :
- communes.csv, arrondissements.csv, communes-associees-ou-deleguees.csv
- departements.csv, regions.csv
- intercos.csv, interco_members.csv, interco_enriched.csv
- aom.csv, aom_commune.csv, base-rt-aom.ods
- mairies.geojson.gz, siren_insee_mapping.csv
"""

from __future__ import annotations

import json
import os
import re
from io import BytesIO, StringIO

import pandas as pd
import requests

# URLs
COG_URL = "https://www.data.gouv.fr/api/1/datasets/r/91a95bee-c7c8-45f9-a8aa-f14cc4697545"
BANATIC_SIREN_URL = "https://www.data.gouv.fr/api/1/datasets/r/5d3cfdd0-00de-43fe-a5db-dffeacec6fc7"
BANATIC_INTERCO_URL = "https://www.data.gouv.fr/api/1/datasets/r/6e05c448-62cc-4470-aa0f-4f31adea0bc4"
LAPOSTE_URL = "https://datanova.laposte.fr/data-fair/api/v1/datasets/laposte-hexasmal/data-files/019HexaSmal.csv"
INTERCO_LIST_URL = "https://www.data.gouv.fr/api/1/datasets/r/25571b3e-a5ce-4567-bfb4-650504644d7b"
INTERCO_MEMBERS_URL = "https://www.banatic.interieur.gouv.fr/consultation/api/export/pregenere/telecharger/France"
MAIRIES_GEOJSON_URL = "https://contours-administratifs.s3.rbx.io.cloud.ovh.net/2026/geojson/mairies.geojson.gz"

# Directories
DATA_DIR = "data"
ASSETS_DIR = "assets"
MISSING_CODES_FILE = os.path.join(ASSETS_DIR, "codes-postaux-missing.json")

# INTERCO files
INTERCO_FILE = os.path.join(DATA_DIR, "intercos.csv")
INTERCO_MEMBERS_XLSX = os.path.join(DATA_DIR, "intercos_membres.xlsx")
INTERCO_MEMBERS_FILE = os.path.join(DATA_DIR, "interco_members.csv")

# AOM files (URL à mettre à jour chaque année lors de la publication RT)
AOM_SOURCE_URL = (
    "https://static.data.gouv.fr/resources/"
    "liste-et-composition-des-autorites-organisatrices-de-la-mobilite-aom/"
    "20260423-072522/base-rt-2025-v11.ods"
)
AOM_SOURCE_FILE = os.path.join(DATA_DIR, "base-rt-aom.ods")
AOM_FILE = os.path.join(DATA_DIR, "aom.csv")
AOM_COMMUNE_FILE = os.path.join(DATA_DIR, "aom_commune.csv")

def download_communes_siren():
    """Download Banatic dataset data with mapping between siren and cog commune"""
    
    mapping_file = os.path.join(DATA_DIR, "siren_insee_mapping.csv")
    if os.path.exists(mapping_file):
        print(f"\n✓ SIREN mapping file already exists, loading : {mapping_file}")
        banatic_df = pd.read_csv(mapping_file, encoding='utf-8', dtype=str)
        print(f"✓ Loaded {len(banatic_df)} SIREN mappings from cache")
        return banatic_df

    print(f"\n📥 Downloading Banatic SIREN data...")
    
    response = requests.get(BANATIC_SIREN_URL)
    response.raise_for_status()

    print("✓ Download complete. Loading Banatic data...")
    
    encodings = ['utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    banatic_df = None
    
    for encoding in encodings:
        try:
            banatic_df = pd.read_csv(
                BytesIO(response.content), 
                encoding=encoding, 
                dtype=str,
                sep=';'  # Banatic uses semicolon separator
            )
            print(f"✓ Successfully loaded with encoding: {encoding}")
            break
        except Exception as e:
            continue
    
    if banatic_df is None:
        print("❌ Could not load Banatic file with any encoding")
        return None
    
    print(f"✓ Banatic data loaded: {len(banatic_df)} rows")
    print(f"  Columns: {', '.join(banatic_df.columns)}")
    
    banatic_df.columns = banatic_df.columns.str.strip()
    banatic_df = banatic_df.rename(columns={'Code INSEE de la commune': 'COM'})
    
    if 'Siren' in banatic_df.columns:
        banatic_df = banatic_df[['COM', 'Siren']].copy()
        banatic_df = banatic_df.drop_duplicates(subset=['COM'], keep='first')
        print(f"✓ {len(banatic_df)} unique SIREN mappings")
        print(f" Saving SIREN mapping to {mapping_file}... (we will reuse it in other scripts)")
        banatic_df.to_csv(mapping_file, index=False, encoding='utf-8')
        print(f"✓ Mapping saved")
        return banatic_df
    else:
        print(" 'Siren' column not found in Banatic data")
        return None

def download_banatic_interco():
    """Download Banatic dataset intercommunalité data"""
    print(f"\n  Downloading Banatic intercommunalité data...")
    
    response = requests.get(BANATIC_INTERCO_URL)
    response.raise_for_status()
    
    print("✓ Download complete. Loading Banatic intercommunalité data...")
    
    encodings = ['utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    interco_df = None
    
    for encoding in encodings:
        try:
            interco_df = pd.read_csv(
                BytesIO(response.content), 
                encoding=encoding, 
                dtype=str,
                sep=';'
            )
            print(f"✓ Successfully loaded with encoding: {encoding}")
            break
        except Exception as e:
            continue
    
    if interco_df is None:
        print("  Could not load Banatic intercommunalité file with any encoding")
        return None
    
    print(f"✓ Banatic intercommunalité data loaded: {len(interco_df)} rows")
    print(f"  Columns: {', '.join(interco_df.columns)}")
    
    interco_df.columns = interco_df.columns.str.strip()
    
    required_cols = ['siren_membre', 'siren', 'raison_sociale']
    missing_cols = [col for col in required_cols if col not in interco_df.columns]
    
    if missing_cols:
        print(f"   Missing columns: {', '.join(missing_cols)}")
        return None
    
    interco_df = interco_df[required_cols].copy()
    interco_df = interco_df.rename(columns={
        'siren_membre': 'Siren',  # SIREN de la commune (pour le matching)
        'siren': 'siren_interco',    # SIREN de l'intercommunalité
        'raison_sociale': 'nom_interco'  # Nom de l'intercommunalité
    })
    
    interco_df = interco_df.drop_duplicates(subset=['Siren'], keep='first')
    
    interco_df = interco_df[interco_df['Siren'].notna()].copy()
    
    print(f"✓ {len(interco_df)} unique intercommunalité mappings")
    
    return interco_df

def download_codes_postaux():
    """Download and process postal codes from La Poste"""
    print(f"\n📥 Downloading postal codes from La Poste...")
    
    try:
        response = requests.get(LAPOSTE_URL, timeout=30)
        response.raise_for_status()
        print("✓ Download complete. Loading postal codes...")
    except Exception as e:
        print(f"❌ Error downloading postal codes: {e}")
        return None
    
    try:
        # La Poste uses semicolon as separator
        df = pd.read_csv(StringIO(response.text), sep=';', dtype=str)
        print(f"✓ Loaded {len(df)} rows")
        
        # Rename columns to expected format
        column_mapping = {
            'Code_commune_INSEE': 'codeCommune',
            'Nom_commune': 'nomCommune',
            'Code_postal': 'codePostal',
            'Libelle_d_acheminement': 'libelleAcheminement'
        }
        
        # Try to find and rename columns
        for old_col in df.columns:
            for expected, new_col in column_mapping.items():
                if expected.lower() in old_col.lower():
                    df = df.rename(columns={old_col: new_col})
                    break
        
        # If columns still don't match, try by position
        if 'codeCommune' not in df.columns and len(df.columns) >= 4:
            df.columns = ['codeCommune', 'nomCommune', 'codePostal', 'libelleAcheminement'] + list(df.columns[4:])
        
        # Keep only relevant columns
        required_columns = ['codeCommune', 'codePostal']
        df = df[required_columns].copy()
        
        # Remove rows with missing data
        df = df.dropna(subset=['codeCommune', 'codePostal'])
        
        print(f"✓ Processed {len(df)} postal code entries")
        
        # Load and merge with missing postal codes
        if os.path.exists(MISSING_CODES_FILE):
            print(f"  Loading missing postal codes...")
            try:
                with open(MISSING_CODES_FILE, 'r', encoding='utf-8') as f:
                    missing_codes = json.load(f)
                
                # Convert to DataFrame
                missing_df = pd.DataFrame(missing_codes)[['codeCommune', 'codePostal']]
                
                # Combine and deduplicate
                df = pd.concat([df, missing_df], ignore_index=True)
                df = df.drop_duplicates(subset=['codeCommune', 'codePostal'])
                
                print(f"  ✓ Added {len(missing_df)} missing codes, total: {len(df)}")
            except Exception as e:
                print(f"  ⚠️  Warning: Could not load missing codes: {e}")
        
        # Group by commune to create list of postal codes
        print(f"  Grouping postal codes by commune...")
        commune_codes = df.groupby('codeCommune')['codePostal'].apply(
            lambda x: ','.join(sorted(set(x)))
        ).reset_index()
        commune_codes.columns = ['COM', 'codes_postaux']
        
        print(f"✓ {len(commune_codes)} communes with postal codes")
        return commune_codes
        
    except Exception as e:
        print(f"❌ Error processing postal codes: {e}")
        import traceback
        traceback.print_exc()
        return None

def download_and_filter_communes():
    """Download COG data, enrich with SIREN, filter and save to CSV"""
    
    print("="*60)
    print("DOWNLOADING AND ENRICHING COG DATA")
    print("="*60)
    
    # Create data directory if it doesn't exist
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Download COG data
    print(f"\n📥 Downloading COG data from data.gouv.fr...")
    response = requests.get(COG_URL)
    response.raise_for_status()
    
    print("✓ Download complete. Loading COG data into pandas...")
    df = pd.read_csv(BytesIO(response.content), encoding='utf-8', dtype=str)
    
    print(f"✓ Total rows loaded: {len(df)}")
    print(f"  Columns: {', '.join(df.columns)}")
    
    banatic_df = download_communes_siren()
    
    if banatic_df is not None:
        print(f"\n  Step 1/2: Merging COG data with SIREN numbers...")
        df = df.merge(banatic_df, on='COM', how='left')
        print(f"✓ Merge complete")
        print(f"  {df['Siren'].notna().sum()} / {len(df)} entities have SIREN")
        print(f"  {df['Siren'].isna().sum()} entities without SIREN")
    else:
        print("\n  Skipping SIREN enrichment (Banatic data not available)")
        df['Siren'] = None
    
    interco_df = download_banatic_interco()
    
    if interco_df is not None and 'Siren' in df.columns:
        print(f"\n🔗 Step 2/3: Merging with intercommunalité data...")
        df = df.merge(interco_df, on='Siren', how='left')
        print(f"✓ Merge complete")
        print(f"  {df['siren_interco'].notna().sum()} / {len(df)} entities have intercommunalité")
        print(f"  {df['siren_interco'].isna().sum()} entities without intercommunalité")
    else:
        print("\n  Skipping intercommunalité enrichment (intercommunalité data not available or no SIREN)")
        df['siren_interco'] = None
        df['nom_interco'] = None
    
    codes_postaux_df = download_codes_postaux()
    
    if codes_postaux_df is not None:
        print(f"\n🔗 Step 3/3: Merging with postal codes...")
        df = df.merge(codes_postaux_df, on='COM', how='left')
        print(f"✓ Merge complete")
        print(f"  {df['codes_postaux'].notna().sum()} / {len(df)} entities have postal codes")
        print(f"  {df['codes_postaux'].isna().sum()} entities without postal codes")
    else:
        print("\n⚠️  Skipping postal codes enrichment (postal codes data not available)")
        df['codes_postaux'] = None
    
    print(f"\n📊 Filtering and saving data...")
    communes_df = df[df['TYPECOM'] == 'COM'].copy()
    communes_file = os.path.join(DATA_DIR, "communes.csv")
    print(f"\n  ✓ Communes (TYPECOM='COM'): {len(communes_df)}")
    if 'Siren' in communes_df.columns:
        print(f"    - With SIREN: {communes_df['Siren'].notna().sum()}")
    if 'siren_interco' in communes_df.columns:
        print(f"    - With intercommunalité: {communes_df['siren_interco'].notna().sum()}")
    if 'codes_postaux' in communes_df.columns:
        print(f"    - With postal codes: {communes_df['codes_postaux'].notna().sum()}")
    communes_df.to_csv(communes_file, index=False, encoding='utf-8')
    print(f"    - Saved to: {communes_file}")
    
    # Filter and save arrondissements (ARM)
    arm_df = df[df['TYPECOM'] == 'ARM'].copy()
    arm_file = os.path.join(DATA_DIR, "arrondissements.csv")
    print(f"\n  ✓ Arrondissements municipaux (TYPECOM='ARM'): {len(arm_df)}")
    if 'Siren' in arm_df.columns:
        print(f"    - With SIREN: {arm_df['Siren'].notna().sum()}")
    if 'siren_interco' in arm_df.columns:
            print(f"    - With intercommunalité: {arm_df['siren_interco'].notna().sum()}")
    if 'codes_postaux' in arm_df.columns:
        print(f"    - With postal codes: {arm_df['codes_postaux'].notna().sum()}")
    arm_df.to_csv(arm_file, index=False, encoding='utf-8')
    print(f"    - Saved to: {arm_file}")
    
    # Filter and save communes déléguées/associées (COMD/COMA)
    comda_df = df[(df['TYPECOM'] == 'COMD') | (df['TYPECOM'] == 'COMA')].copy()
    comda_file = os.path.join(DATA_DIR, "communes-associees-ou-deleguees.csv")
    print(f"\n  ✓ Communes déléguées/associées (TYPECOM='COMD'/'COMA'): {len(comda_df)}")
    if 'Siren' in comda_df.columns:
        print(f"    - With SIREN: {comda_df['Siren'].notna().sum()}")
    if 'siren_interco' in comda_df.columns:
        print(f"    - With intercommunalité: {comda_df['siren_interco'].notna().sum()}")
    if 'codes_postaux' in comda_df.columns:
        print(f"    - With postal codes: {comda_df['codes_postaux'].notna().sum()}")
    comda_df.to_csv(comda_file, index=False, encoding='utf-8')
    print(f"    - Saved to: {comda_file}")
    
    print("\n" + "="*60)
    print("✅ ALL DATA DOWNLOADED AND ENRICHED SUCCESSFULLY!")
    print("="*60)
    
    # Summary
    total = len(communes_df) + len(arm_df) + len(comda_df)
    print(f"\nSummary:")
    print(f"  Total entities: {total}")
    print(f"  - Communes (COM): {len(communes_df)}")
    print(f"  - Arrondissements (ARM): {len(arm_df)}")
    print(f"  - Communes déléguées/associées: {len(comda_df)}")
    if banatic_df is not None:
        print(f"\n  Enrichment:")
        print(f"  - Entities with SIREN: {df['Siren'].notna().sum()} / {len(df)}")
    if interco_df is not None:
        print(f"  - Entities with intercommunalité: {df['siren_interco'].notna().sum()} / {len(df)}")
    if codes_postaux_df is not None:
        print(f"  - Entities with postal codes: {df['codes_postaux'].notna().sum()} / {len(df)}")

def download_departements():
    """Download departements data from COG"""
    
    print("\n" + "="*80)
    print("DOWNLOADING DEPARTEMENTS DATA FROM COG")
    print("="*80)
    
    DEPARTEMENTS_URL = "https://www.data.gouv.fr/api/1/datasets/r/54a8263d-6e2d-48d5-b214-aa17cc13f7a0"
    OUTPUT_FILE = os.path.join(DATA_DIR, "departements.csv")
    
    print(f"\n📥 Downloading departements from COG...")
    try:
        response = requests.get(DEPARTEMENTS_URL, timeout=30)
        response.raise_for_status()
        print("✓ Download complete")
    except Exception as e:
        print(f"❌ Error downloading file: {e}")
        return None
    
    print("\n🔧 Parsing departements data...")
    try:
        df = pd.read_csv(BytesIO(response.content), encoding='utf-8', dtype=str)
        print(f"✓ Loaded {len(df)} departements")
    except Exception as e:
        print(f"❌ Error parsing CSV: {e}")
        return None
    
    # Rename columns to lowercase
    df.columns = df.columns.str.lower()
    
    # Save to CSV
    print(f"\n💾 Saving to {OUTPUT_FILE}...")
    df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8')
    print(f"✓ Saved {len(df)} departements")
    
    print(f"\n✅ DEPARTEMENTS DATA DOWNLOADED SUCCESSFULLY!")
    return df

def download_regions():
    """Download regions data from COG"""
    
    print("\n" + "="*80)
    print("DOWNLOADING REGIONS DATA FROM COG")
    print("="*80)
    
    REGIONS_URL = "https://www.data.gouv.fr/api/1/datasets/r/2486b351-5d85-4e1a-8d12-5df082c75104"
    OUTPUT_FILE = os.path.join(DATA_DIR, "regions.csv")
    
    print(f"\n📥 Downloading regions from COG...")
    try:
        response = requests.get(REGIONS_URL, timeout=30)
        response.raise_for_status()
        print("✓ Download complete")
    except Exception as e:
        print(f"❌ Error downloading file: {e}")
        return None
    
    print("\n🔧 Parsing regions data...")
    try:
        df = pd.read_csv(BytesIO(response.content), encoding='utf-8', dtype=str)
        print(f"✓ Loaded {len(df)} regions")
    except Exception as e:
        print(f"❌ Error parsing CSV: {e}")
        return None
    
    # Rename columns to lowercase
    df.columns = df.columns.str.lower()
    
    # Save to CSV
    print(f"\n💾 Saving to {OUTPUT_FILE}...")
    df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8')
    print(f"✓ Saved {len(df)} regions")
    
    print(f"\n✅ REGIONS DATA DOWNLOADED SUCCESSFULLY!")
    return df

def download_interco_list():
    """Download intercommunalité list from Banatic (or load from cache)"""
    
    print("\n" + "="*80)
    print("LOADING INTERCOMMUNALITÉ LIST FROM BANATIC")
    print("="*80)
    
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Check if file already exists
    if os.path.exists(INTERCO_FILE):
        print(f"\n✓ File already exists: {INTERCO_FILE}")
        print(f"  Loading from cache (no download needed)...")
        try:
            df = pd.read_csv(INTERCO_FILE, encoding='utf-8', dtype=str)
            print(f"✓ Loaded {len(df)} intercommunalité from cache")
            return df
        except Exception as e:
            print(f"⚠️  Error reading cached file: {e}")
            print(f"  Will download fresh data...")
    
    print(f"\n📥 Downloading intercommunalité list from Banatic...")
    try:
        response = requests.get(INTERCO_LIST_URL, timeout=60)
        response.raise_for_status()
        print("✓ Download complete")
    except Exception as e:
        print(f"❌ Error downloading file: {e}")
        return None
    
    print("\n🔧 Parsing intercommunalité data...")
    
    # Try different encodings (Banatic files are often in latin1/cp1252)
    encodings = ['utf-8', 'latin1', 'cp1252', 'iso-8859-1']
    df = None
    
    for encoding in encodings:
        try:
            df = pd.read_csv(
                BytesIO(response.content), 
                encoding=encoding, 
                dtype=str,
                sep=';',
                low_memory=False
            )
            print(f"✓ Successfully loaded with encoding: {encoding}")
            break
        except Exception as e:
            continue
    
    if df is None:
        print("❌ Could not load intercommunalité file with any encoding")
        return None
    
    print(f"✓ Loaded {len(df)} intercommunalité")
    print(f"  Columns: {', '.join(df.columns)}")
    
    # Rename columns to lowercase and clean
    df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_').str.replace('°', 'n').str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode("utf-8")
    
    # Save to CSV
    print(f"\n💾 Saving to {INTERCO_FILE}...")
    df.to_csv(INTERCO_FILE, index=False, encoding='utf-8')
    print(f"✓ Saved {len(df)} intercommunalité")
    
    print(f"\n✅ INTERCOMMUNALITÉ LIST DOWNLOADED SUCCESSFULLY!")
    
    # Show some examples
    print(f"\nExamples of intercommunalité:")
    for i in range(min(5, len(df))):
        row = df.iloc[i]
        siren = row.get('nn_siren', 'N/A')
        nom = row.get('nom_du_groupement', 'N/A')
        nature = row.get('nature_juridique', 'N/A')
        print(f"  {siren} - {nom} ({nature})")
    
    return df

def download_interco_members():
    """Download intercommunalité members list from Banatic (Excel file, or load from cache)"""
    
    print("\n" + "="*80)
    print("LOADING INTERCOMMUNALITÉ MEMBERS FROM BANATIC")
    print("="*80)
    
    # Check if CSV version exists (faster to load)
    if os.path.exists(INTERCO_MEMBERS_FILE):
        print(f"\n✓ CSV file already exists: {INTERCO_MEMBERS_FILE}")
        print(f"  Loading from cache (no download needed)...")
        try:
            df = pd.read_csv(INTERCO_MEMBERS_FILE, encoding='utf-8', dtype=str)
            print(f"✓ Loaded {len(df)} membership records from cache")
            return df
        except Exception as e:
            print(f"⚠️  Error reading cached file: {e}")
            print(f"  Will download fresh data...")
    
    # Check if Excel file already exists
    if not os.path.exists(INTERCO_MEMBERS_XLSX):
        print(f"\n📥 Downloading intercommunalité members (Excel file, may take a while)...")
        try:
            response = requests.get(INTERCO_MEMBERS_URL, timeout=120)
            response.raise_for_status()
            print("✓ Download complete")
            
            # Save the Excel file
            print(f"\n💾 Saving Excel file to {INTERCO_MEMBERS_XLSX}...")
            with open(INTERCO_MEMBERS_XLSX, 'wb') as f:
                f.write(response.content)
            print(f"✓ Excel file saved")
        except Exception as e:
            print(f"❌ Error downloading file: {e}")
            return None
    
    print(f"\n🔧 Parsing Excel file (this may take a few moments)...")
    try:
        df = pd.read_excel(INTERCO_MEMBERS_XLSX, dtype=str)
        print(f"✓ Loaded {len(df)} membership records")
        
        # Rename columns to lowercase and clean
        df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_').str.replace('°', 'n').str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode("utf-8")
        
        # Save to CSV for faster future access
        print(f"  Saving CSV version for faster access...")
        df.to_csv(INTERCO_MEMBERS_FILE, index=False, encoding='utf-8')
        
        return df
    except Exception as e:
        print(f"⚠️  Error reading Excel file: {e}")
        return None

def resolve_communes_for_interco(interco_siren, members_df, interco_df, depth=0, max_depth=5, visited=None):
    """
    Recursively resolve all communes for an intercommunalité
    Handles cases where members are themselves intercommunalité
    """
    if visited is None:
        visited = set()
    
    if depth > max_depth:
        return set()
    
    if interco_siren in visited:
        return set()
    
    visited.add(interco_siren)
    
    # Find all members of this intercommunalité
    siren_col = 'nn_siren'
    membre_col = 'siren_membre'
    
    if membre_col is None:
        return set()
    
    members = members_df[members_df[siren_col] == interco_siren]
    
    if len(members) == 0:
        return set()
    
    communes = set()
    
    for _, member_row in members.iterrows():
        member_siren = member_row[membre_col]
        
        if pd.isna(member_siren):
            continue
        
        # Check if this member is itself an intercommunalité
        interco_siren_col = 'nn_siren'
        is_interco = member_siren in interco_df[interco_siren_col].values
        
        if is_interco:
            # Recursively resolve this intercommunalité
            sub_communes = resolve_communes_for_interco(
                member_siren, members_df, interco_df, depth + 1, max_depth, visited
            )
            communes.update(sub_communes)
        else:
            # This is a commune
            communes.add(member_siren)
    
    return communes

def enrich_interco_with_communes(interco_df, members_df):
    """Enrich intercommunalité data with list of member communes"""
    
    print("\n" + "="*80)
    print("RESOLVING COMMUNES FOR EACH INTERCOMMUNALITÉ")
    print("="*80)
    print("\nThis may take a few moments as we resolve recursive memberships...")
    
    # Load SIREN → INSEE mapping
    mapping_file = os.path.join(DATA_DIR, "siren_insee_mapping.csv")
    siren_to_insee = {}
    
    if os.path.exists(mapping_file):
        print(f"\n📥 Loading SIREN → INSEE mapping from {mapping_file}...")
        try:
            mapping_df = pd.read_csv(mapping_file, encoding='utf-8', dtype=str)
            # Create dictionary: SIREN → Code INSEE
            siren_to_insee = dict(zip(mapping_df['Siren'], mapping_df['COM']))
            print(f"✓ Loaded {len(siren_to_insee)} SIREN → INSEE mappings")
        except Exception as e:
            print(f"⚠️  Could not load mapping: {e}")
            print(f"  communes_code will not be populated")
    else:
        print(f"⚠️  SIREN mapping file not found: {mapping_file}")
        print(f"  communes_code will not be populated")
    
    interco_siren_col = 'nn_siren'
    
    # Add columns for members
    interco_df['membres_siren'] = None
    interco_df['communes_siren'] = None
    interco_df['communes_code'] = None
    interco_df['nb_membres'] = 0
    interco_df['nb_communes'] = 0
    
    total = len(interco_df)
    processed = 0
    
    for idx, row in interco_df.iterrows():
        interco_siren = row[interco_siren_col]
        
        # Get direct members
        siren_col = 'nn_siren'
        membre_col = 'siren_membre'
        
        direct_members = members_df[members_df[siren_col] == interco_siren]
        membres_list = direct_members[membre_col].dropna().tolist() if len(direct_members) > 0 else []
        
        # Resolve all communes recursively
        communes = resolve_communes_for_interco(interco_siren, members_df, interco_df)
        communes_list = sorted(list(communes))
        
        # Convert SIREN to Code INSEE
        communes_code_list = []
        for siren in communes_list:
            code_insee = siren_to_insee.get(siren)
            if code_insee:
                communes_code_list.append(code_insee)
        communes_code_list = sorted(communes_code_list)
        
        # Store as JSON strings
        interco_df.at[idx, 'membres_siren'] = json.dumps(membres_list) if membres_list else None
        interco_df.at[idx, 'communes_siren'] = json.dumps(communes_list) if communes_list else None
        interco_df.at[idx, 'communes_code'] = json.dumps(communes_code_list) if communes_code_list else None
        interco_df.at[idx, 'nb_membres'] = len(membres_list)
        interco_df.at[idx, 'nb_communes'] = len(communes_list)
        
        processed += 1
        if processed % 100 == 0:
            print(f"  {processed}/{total} intercommunalités processed...", end='\r')
    
    print(f"\n✓ {total} intercommunalités processed")
    
    # Statistics
    print(f"\nStatistics:")
    print(f"  Total intercommunalités: {len(interco_df)}")
    print(f"  intercommunalités with communes SIREN: {len(interco_df[interco_df['nb_communes'] > 0])}")
    interco_with_codes = len(interco_df[interco_df['communes_code'].notna()])
    print(f"  intercommunalités with communes INSEE codes: {interco_with_codes}")
    print(f"  Average communes per intercommunalité: {interco_df['nb_communes'].astype(int).mean():.1f}")
    print(f"  Max communes in an intercommunalité: {interco_df['nb_communes'].astype(int).max()}")
    
    if interco_with_codes < len(interco_df[interco_df['nb_communes'] > 0]):
        print(f"\n⚠️  {len(interco_df[interco_df['nb_communes'] > 0]) - interco_with_codes} intercommunalités have communes but no INSEE codes")
        print(f"  This may be due to missing SIREN → INSEE mapping")
    
    # Save enriched data
    output_file = os.path.join(DATA_DIR, "interco_enriched.csv")
    print(f"\n💾 Saving enriched data to {output_file}...")
    interco_df.to_csv(output_file, index=False, encoding='utf-8')
    print(f"✓ Saved enriched intercommunalités data")
    
    return interco_df


def normalize_siren(value) -> str | None:
    """Normalise un SIREN (9 chiffres, sans décimales Excel)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if len(digits) > 9:
        return None
    return digits.zfill(9)


def _normalize_col_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def find_aom_sheet(sheet_names: list[str]) -> str:
    for name in sheet_names:
        if name.endswith("_AOM") or re.search(r"_\d{4}_AOM$", name):
            return name
    raise ValueError(f"Onglet AOM introuvable dans {sheet_names}")


def find_composition_sheet(sheet_names: list[str]) -> str:
    for name in sheet_names:
        if "composition_communale" in name.lower():
            return name
    raise ValueError(f"Onglet composition communale introuvable dans {sheet_names}")


def find_aom_siren_column(columns: list[str]) -> str:
    for col in columns:
        norm = _normalize_col_name(col)
        if norm in {"nsirenaom", "sirenaom"}:
            return col
        if "siren" in norm and "aom" in norm and "groupement" not in norm:
            return col
    raise ValueError(f"Colonne SIREN AOM introuvable dans {columns}")


def find_aom_nom_column(columns: list[str]) -> str:
    for col in columns:
        lower = col.lower()
        if "nom de l" in lower and "aom" in lower:
            if "president" in lower or "commune principale" in lower:
                continue
            return col
    raise ValueError(f"Colonne nom AOM introuvable dans {columns}")


def find_composition_aom_nom_column(columns: list[str]) -> str:
    for col in columns:
        lower = col.lower()
        if "nom de l" in lower and "aom" in lower:
            if "groupement" in lower or "membre" in lower:
                continue
            return col
    raise ValueError(f"Colonne nom AOM (composition) introuvable dans {columns}")


def find_commune_siren_column(columns: list[str]) -> str:
    for col in columns:
        norm = _normalize_col_name(col)
        if norm in {"sirenmembre", "sirencommune"}:
            return col
        if norm == "sirenmembre":
            return col
    for col in columns:
        norm = _normalize_col_name(col)
        if "siren" in norm and "membre" in norm:
            return col
    raise ValueError(f"Colonne SIREN membre introuvable dans {columns}")


def download_aom_source(force: bool = False) -> str:
    """Télécharge le fichier ODS source (ou réutilise le cache local)."""
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(AOM_SOURCE_FILE) and not force:
        size_mb = os.path.getsize(AOM_SOURCE_FILE) / (1024 * 1024)
        print(f"✓ Fichier AOM déjà présent : {AOM_SOURCE_FILE} ({size_mb:.2f} MB)")
        return AOM_SOURCE_FILE

    print(f"📥 Téléchargement AOM depuis data.gouv.fr...")
    print(f"   {AOM_SOURCE_URL}")
    response = requests.get(AOM_SOURCE_URL, timeout=180)
    response.raise_for_status()

    with open(AOM_SOURCE_FILE, "wb") as handle:
        handle.write(response.content)

    size_mb = os.path.getsize(AOM_SOURCE_FILE) / (1024 * 1024)
    print(f"✓ Fichier source enregistré : {AOM_SOURCE_FILE} ({size_mb:.2f} MB)")
    return AOM_SOURCE_FILE


def prepare_aom_tables(source_path: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extrait les tables aom et aom_commune depuis le fichier ODS."""
    source_path = source_path or AOM_SOURCE_FILE
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Fichier source introuvable : {source_path}")

    print(f"\n📄 Lecture du fichier ODS : {source_path}")
    workbook = pd.ExcelFile(source_path, engine="odf")
    aom_sheet = find_aom_sheet(workbook.sheet_names)
    composition_sheet = find_composition_sheet(workbook.sheet_names)
    print(f"  Onglet AOM : {aom_sheet}")
    print(f"  Onglet composition : {composition_sheet}")

    raw_aom = pd.read_excel(source_path, sheet_name=aom_sheet, engine="odf", dtype=str)
    raw_composition = pd.read_excel(
        source_path, sheet_name=composition_sheet, engine="odf", dtype=str
    )

    aom_siren_col = find_aom_siren_column(list(raw_aom.columns))
    aom_nom_col = find_aom_nom_column(list(raw_aom.columns))
    commune_siren_col = find_commune_siren_column(list(raw_composition.columns))
    composition_aom_col = find_aom_siren_column(list(raw_composition.columns))
    composition_nom_col = find_composition_aom_nom_column(list(raw_composition.columns))

    print(f"  Colonnes AOM : {aom_siren_col!r}, {aom_nom_col!r}")
    print(
        "  Colonnes composition : "
        f"{commune_siren_col!r}, {composition_aom_col!r}, {composition_nom_col!r}"
    )

    aom_from_sheet = pd.DataFrame(
        {
            "siren": raw_aom[aom_siren_col].map(normalize_siren),
            "nom": raw_aom[aom_nom_col].astype(str).str.strip(),
        }
    )
    aom_from_sheet = aom_from_sheet[aom_from_sheet["siren"].notna()]
    aom_from_sheet = aom_from_sheet[
        aom_from_sheet["nom"].notna() & (aom_from_sheet["nom"].str.lower() != "nan")
    ]
    before = len(aom_from_sheet)
    aom_from_sheet = aom_from_sheet.drop_duplicates(subset=["siren"], keep="first")
    if len(aom_from_sheet) < before:
        print(f"  ⚠️  {before - len(aom_from_sheet)} doublons SIREN AOM ignorés (onglet AOM)")

    composition_for_names = raw_composition.assign(
        siren=raw_composition[composition_aom_col].map(normalize_siren),
        nom=raw_composition[composition_nom_col].astype(str).str.strip(),
    )
    composition_for_names = composition_for_names[composition_for_names["siren"].notna()]
    composition_for_names = composition_for_names[
        composition_for_names["nom"].notna()
        & (composition_for_names["nom"].str.lower() != "nan")
    ]
    composition_names = (
        composition_for_names.groupby("siren")["nom"]
        .agg(lambda values: values.mode().iloc[0])
        .reset_index()
    )

    aom_df = aom_from_sheet.merge(
        composition_names,
        on="siren",
        how="left",
        suffixes=("_sheet", "_composition"),
    )
    aom_df["nom"] = aom_df["nom_composition"].fillna(aom_df["nom_sheet"])
    aom_df = aom_df[["siren", "nom"]]
    if len(composition_names):
        print(
            f"  ✓ {len(composition_names)} noms AOM canoniques "
            "issus de la composition communale"
        )

    composition_df = pd.DataFrame(
        {
            "siren_commune": raw_composition[commune_siren_col].map(normalize_siren),
            "siren_aom": raw_composition[composition_aom_col].map(normalize_siren),
        }
    )
    composition_df = composition_df[
        composition_df["siren_commune"].notna() & composition_df["siren_aom"].notna()
    ]
    before = len(composition_df)
    composition_df = composition_df.drop_duplicates(subset=["siren_commune", "siren_aom"])
    if len(composition_df) < before:
        print(f"  ⚠️  {before - len(composition_df)} doublons commune/AOM ignorés")

    print(f"✓ {len(aom_df)} AOM")
    print(f"✓ {len(composition_df)} liaisons commune → AOM")
    return aom_df, composition_df


def save_aom_tables(
    aom_df: pd.DataFrame,
    composition_df: pd.DataFrame,
) -> tuple[str, str]:
    """Enregistre les CSV plats dans data/."""
    os.makedirs(DATA_DIR, exist_ok=True)
    aom_df.to_csv(AOM_FILE, index=False, encoding="utf-8")
    composition_df.to_csv(AOM_COMMUNE_FILE, index=False, encoding="utf-8")
    print(f"\n💾 {AOM_FILE} ({len(aom_df)} lignes)")
    print(f"💾 {AOM_COMMUNE_FILE} ({len(composition_df)} lignes)")
    return AOM_FILE, AOM_COMMUNE_FILE


def download_and_prepare_aom(force_download: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Télécharge la source et produit les fichiers plats AOM."""
    print("=" * 80)
    print("PRÉPARATION DES DONNÉES AOM")
    print("=" * 80)
    source_path = download_aom_source(force=force_download)
    aom_df, composition_df = prepare_aom_tables(source_path)
    save_aom_tables(aom_df, composition_df)
    return aom_df, composition_df


def download_decoupage_administratif_data(force_aom_download: bool = False):
    """Exécute l'ensemble des téléchargements et préparations."""
    download_and_filter_communes()
    download_departements()
    download_regions()

    interco_df = download_interco_list()
    members_df = download_interco_members()
    enrich_interco_with_communes(interco_df, members_df)

    download_and_prepare_aom(force_download=force_aom_download)


if __name__ == "__main__":
    download_decoupage_administratif_data()

    print("\n" + "=" * 80)
    print("✅ ALL DOWNLOADS COMPLETE!")
    print("=" * 80)
    print("\nData downloaded:")
    print("  ✓ Communes, arrondissements, communes déléguées (SIREN, intercommunalités, codes postaux)")
    print("  ✓ Départements et régions")
    print("  ✓ Intercommunalités (avec communes résolues)")
    print("  ✓ AOM (aom.csv, aom_commune.csv)")
    print("\nNext steps:")
    print("  1. python3 2_download_geometries_ign.py")
    print("  2. python3 3_convert_admin_express_into_geojson.py")
    print("  3. python3 4_assemble_communes_and_mairies_from_source.py")
    print("  4. python3 5_simplify_geojson.py")
    print("  5. python3 6_assemble_by_admin_units.py")
    print("  6. python3 7_load_into_spatialite.py")
