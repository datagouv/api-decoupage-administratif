#!/usr/bin/env python3
"""
Script to load commune data into SQLite database.
Géométries stockées en WKT + GeoJSON pré-calculé (pas d'extension spatiale requise).
"""

import gzip
import json
import os
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping
from sqlalchemy import create_engine, text

sys.path.append(".")
from anciens_codes import compute_anciens_codes_communes

from app.normalize_string import normalize_string

# Database configuration
DB_FILE = "data/apigeo.db"
DATABASE_URL = f"sqlite:///{DB_FILE}"

# Data files
DATA_DIR = "data"

# Precision levels for different entity types
# Communes, arrondissements, COMD/COMA: high precision (5m)
# Intercommunalités, départements, régions: medium precision (10m)

COMMUNES_CSV = os.path.join(DATA_DIR, "communes.csv")
COMMUNES_COM_CSV = os.path.join("assets", "collectivites-outremer.csv")
COMMUNES_GEOJSON = os.path.join(DATA_DIR, "communes_5m.geojson.gz")  # 5m precision
ARRONDISSEMENTS_CSV = os.path.join(DATA_DIR, "arrondissements.csv")
ARRONDISSEMENTS_GEOJSON = os.path.join(
    DATA_DIR, "arrondissements_5m.geojson.gz"
)  # 5m precision
COMMUNES_DELEGUEES_CSV = os.path.join(DATA_DIR, "communes-associees-ou-deleguees.csv")
COMMUNES_DELEGUEES_GEOJSON = os.path.join(
    DATA_DIR, "communes-deleguees-et-associees_5m.geojson.gz"
)  # 5m precision
DEPARTEMENTS_CSV = os.path.join(DATA_DIR, "departements.csv")
DEPARTEMENTS_GEOJSON = os.path.join(
    DATA_DIR, "departements_5m.geojson.gz"
)  # 10m precision
REGIONS_CSV = os.path.join(DATA_DIR, "regions.csv")
REGIONS_GEOJSON = os.path.join(DATA_DIR, "regions_5m.geojson.gz")  # 10m precision
INTERCO_CSV = os.path.join(DATA_DIR, "interco_enriched.csv")
INTERCO_GEOJSON = os.path.join(
    DATA_DIR, "intercommunalites_5m.geojson.gz"
)  # 10m precision
INTERCO_MEMBERS_CSV = os.path.join(
    DATA_DIR, "interco_members.csv"
)  # All commune-interco associations
AOM_CSV = os.path.join(DATA_DIR, "aom.csv")
AOM_COMMUNE_CSV = os.path.join(DATA_DIR, "aom_commune.csv")
AOM_GEOJSON = os.path.join(DATA_DIR, "aom_5m.geojson.gz")
AOM_GEOJSON_FALLBACK = os.path.join(DATA_DIR, "aom.geojson.gz")
SIREN_INSEE_MAPPING_CSV = os.path.join(DATA_DIR, "siren_insee_mapping.csv")
MAIRIES_GEOJSON = os.path.join(DATA_DIR, "mairies.geojson.gz")

chef_lieu_com = {
    "975": "97502",
    "977": "97701",
    "978": "97801",
    "984": "97502",
    "986": "98613",
    "987": "98735",
    "988": "98818",
    "989": "98901",
}


def generate_departements_and_regions_com(path):
    # Lecture du CSV
    rows = pd.read_csv(path, dtype=str)

    # Un enregistrement par code_collectivite
    departements = rows.drop_duplicates(subset=["code_collectivite"]).assign(
        code=lambda df: df["code_collectivite"],
        region=lambda df: df["code_collectivite"],
        chefLieu=lambda df: df["code_collectivite"].map(chef_lieu_com),
        nom=lambda df: df["nom_collectivite"],
        typeLiaison=0,
        zone="com",
    )[
        [
            "code",
            "region",
            "chefLieu",
            "nom",
            "typeLiaison",
            "zone",
        ]
    ]

    departements = departements.rename(
        columns={
            "code": "dep",
            "region": "reg",
            "chefLieu": "cheflieu",
            "typeLiaison": "tncc",
            "nom": "libelle",
        }
    )
    departements["nccenr"] = departements["libelle"]
    departements["ncc"] = (
        departements["libelle"]
        .str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("utf-8")
        .str.upper()
    )

    # Copie des départements puis suppression de la colonne "region"
    regions = departements.copy().drop(columns=["dep"])

    return departements, regions


departements_com, regions_com = generate_departements_and_regions_com(COMMUNES_COM_CSV)


def load_communes_mairies(engine):
    """Load mairie points by commune code from mairies.geojson.gz"""
    print("\nLoading communes mairies points...")

    mairies_file = os.environ.get("MAIRIES_GEOJSON", MAIRIES_GEOJSON)
    if not os.path.exists(mairies_file):
        print(f"  ⚠️  Mairies file not found: {mairies_file}")
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS communes_mairies"))
            conn.execute(
                text("""
                CREATE TABLE communes_mairies (
                    code_insee TEXT PRIMARY KEY,
                    mairie_geojson TEXT
                )
            """)
            )
            conn.commit()
        print("  Empty communes_mairies table created")
        return None

    print(f"  Reading mairies from: {mairies_file}")
    try:
        with gzip.open(mairies_file, "rt", encoding="utf-8") as f:
            geojson_data = json.load(f)
    except Exception as e:
        print(f"  ❌ Error reading mairies file: {e}")
        return None

    features = geojson_data.get("features", [])
    mairies_rows = []
    for feature in features:
        properties = feature.get("properties", {}) or {}
        commune_code = properties.get("commune")
        geometry = feature.get("geometry")
        if commune_code and geometry:
            mairies_rows.append(
                {
                    "code_insee": str(commune_code),
                    "mairie_geojson": json.dumps(geometry, ensure_ascii=False),
                }
            )

    mairies_df = pd.DataFrame(mairies_rows)
    if len(mairies_df) > 0:
        mairies_df = mairies_df.drop_duplicates(subset=["code_insee"], keep="first")
    else:
        mairies_df = pd.DataFrame(columns=["code_insee", "mairie_geojson"])

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS communes_mairies"))
        conn.execute(
            text("""
            CREATE TABLE communes_mairies (
                code_insee TEXT PRIMARY KEY,
                mairie_geojson TEXT
            )
        """)
        )
        conn.commit()

    if len(mairies_df) > 0:
        mairies_df.to_sql("communes_mairies", engine, if_exists="append", index=False)

    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_mairies_code_insee
            ON communes_mairies(code_insee)
        """)
        )
        conn.commit()

    print(f"✓ Loaded {len(mairies_df)} mairies points")
    return mairies_df


def init_sqlite_db():
    """Create an empty SQLite database file."""
    print(f"Initializing SQLite database: {DB_FILE}...")
    os.makedirs(DATA_DIR, exist_ok=True)

    if os.path.exists(DB_FILE):
        print("  Removing existing database...")
        os.remove(DB_FILE)

    try:
        import sqlite3

        sqlite3.connect(DB_FILE).close()
        print("✓ SQLite database created")
    except Exception as e:
        print(f"❌ Error creating database: {e}")
        sys.exit(1)


def create_database_connection():
    """Create database engine"""
    print(f"Connecting to database: {DB_FILE}...")

    try:
        # Create engine with check_same_thread=False for SQLite
        engine = create_engine(
            DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
        )

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✓ Connected to SQLite")

        return engine
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


def drop_existing_views(engine):
    """Drop existing views to avoid dependency issues"""
    print("\nDropping existing views if they exist...")
    try:
        with engine.connect() as conn:
            conn.execute(text("DROP VIEW IF EXISTS communes"))
            conn.execute(text("DROP VIEW IF EXISTS departements"))
            conn.execute(text("DROP VIEW IF EXISTS regions"))
            conn.execute(text("DROP VIEW IF EXISTS interco"))
            conn.execute(text("DROP VIEW IF EXISTS aom"))
            conn.commit()
        print("✓ Existing views dropped")
    except Exception as e:
        print(f"⚠️  Warning while dropping views: {e}")


def load_anciens_codes(engine):
    """Load commune metadata from CSV (including communes, arrondissements, and communes déléguées/associées)"""
    print(
        "\nLoading anciens codes communes from COG CSV communes file and associated mouvement file CSV..."
    )

    match_current_anciens_codes = []
    for k_code, v_anciens_codes in compute_anciens_codes_communes().items():
        for v_ancien_code in v_anciens_codes:
            match_current_anciens_codes.append([v_ancien_code, k_code])
    df_match_current_anciens_codes = pd.DataFrame(
        match_current_anciens_codes, columns=["ancien_code", "code"]
    )

    # Load into database
    table_name = "communes_anciens_codes"
    df_match_current_anciens_codes.to_sql(
        table_name, engine, if_exists="replace", index=False
    )
    print(f"\n✓ All data loaded into table '{table_name}'")
    return load_anciens_codes


def load_commune_data(engine):
    """Load commune metadata from CSV (including communes, arrondissements, and communes déléguées/associées)"""
    print("\nLoading commune metadata from multiple CSV files...")

    dataframes = []

    # Load communes (COM)
    if os.path.exists(COMMUNES_CSV):
        df_com = pd.read_csv(COMMUNES_CSV, encoding="utf-8", dtype=str)
        df_com["zone"] = df_com.DEP.apply(
            lambda x: "drom" if x.startswith("97") else "metro"
        )
        print(f"✓ Loaded {len(df_com)} communes (TYPECOM='COM')")
        dataframes.append(df_com)
    else:
        print(f"⚠️  File not found: {COMMUNES_CSV}")

    # Load communes from collectivités Outre-Mer
    if os.path.exists(COMMUNES_COM_CSV):
        df_communes_com = pd.read_csv(
            COMMUNES_COM_CSV, encoding="utf-8", dtype=str
        )  # , na_filter=False, keep_default_na=False).replace(r'^\s*$', np.nan, regex=True)
        df_communes_com = df_communes_com.rename(
            columns={
                "code_postal": "codes_postaux",
                "nom_commune": "LIBELLE",
                "code_collectivite": "DEP",
                "code_commune": "COM",
            }
        ).drop(columns=["nom_collectivite", "population"])
        df_communes_com["NCCENR"] = df_communes_com["LIBELLE"]
        df_communes_com["NCC"] = df_communes_com["LIBELLE"].str.upper()
        df_communes_com["REG"] = df_communes_com["DEP"]
        df_communes_com["TYPECOM"] = "COM"
        df_communes_com["codes_postaux"] = df_communes_com["codes_postaux"].str.replace(
            "|", ","
        )
        df_communes_com["zone"] = "com"
        print(f"✓ Loaded {len(df_communes_com)} communes (TYPECOM='COM') for Outre-Mer")
        dataframes.append(df_communes_com)
    else:
        print(f"⚠️  File not found: {COMMUNES_COM_CSV}")

    # Load arrondissements (ARM)
    if os.path.exists(ARRONDISSEMENTS_CSV):
        df_arm = pd.read_csv(ARRONDISSEMENTS_CSV, encoding="utf-8", dtype=str)
        df_arm["zone"] = "metro"
        print(f"✓ Loaded {len(df_arm)} arrondissements (TYPECOM='ARM')")
        dataframes.append(df_arm)
    else:
        print(f"⚠️  File not found: {ARRONDISSEMENTS_CSV}")

    # Load communes déléguées/associées (COMD/COMA)
    if os.path.exists(COMMUNES_DELEGUEES_CSV):
        df_comda = pd.read_csv(COMMUNES_DELEGUEES_CSV, encoding="utf-8", dtype=str)
        df_comda["zone"] = "metro"
        print(
            f"✓ Loaded {len(df_comda)} communes déléguées/associées (TYPECOM='COMD'/'COMA')"
        )
        dataframes.append(df_comda)
    else:
        print(f"⚠️  File not found: {COMMUNES_DELEGUEES_CSV}")

    if not dataframes:
        print("❌ No CSV files found!")
        print("Please run 1_download_decoupage_administratif_data.py first")
        sys.exit(1)

    # Concatenate all dataframes
    df = pd.concat(dataframes, ignore_index=True)
    print(f"\n✓ Total entities loaded: {len(df)}")
    print("  Breakdown by TYPECOM:")
    for typecom, count in df["TYPECOM"].value_counts().items():
        print(f"    - {typecom}: {count}")
    print(f"  Columns in CSV: {', '.join(df.columns)}")

    # Rename columns to lowercase for easier SQL queries
    print("  Renaming columns to lowercase...")
    df.columns = df.columns.str.lower()
    print(f"  Columns after rename: {', '.join(df.columns)}")

    print("  Building nom_recherche (normalized names for API search)...")
    df["nom_recherche"] = df["libelle"].apply(
        lambda x: normalize_string(x) if pd.notna(x) else ""
    )
    print(
        f"  ✓ nom_recherche column added ({df['nom_recherche'].ne('').sum()} non-empty values)"
    )
    match_current_anciens_codes = [
        [k, ",".join(sorted(v))] for k, v in compute_anciens_codes_communes().items()
    ]
    df_match_current_anciens_codes = pd.DataFrame(
        match_current_anciens_codes, columns=["code", "anciens_codes"]
    )

    df = df.merge(
        df_match_current_anciens_codes, right_on="code", left_on="com", how="left"
    )
    # Fix as we also completed where communes associees/deleguees instead of only typecom == 'COM'
    df.loc[
        df["typecom"] != "COM",
        "anciens_codes",
    ] = np.nan
    df = df[
        [
            "typecom",
            "com",
            "reg",
            "dep",
            "ctcd",
            "arr",
            "tncc",
            "ncc",
            "nccenr",
            "libelle",
            "can",
            "comparent",
            "siren",
            "siren_interco",
            "nom_interco",
            "codes_postaux",
            "zone",
            "nom_recherche",
            "anciens_codes",
        ]
    ]

    # Load into database
    table_name = "communes_metadata"
    df.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"\n✓ All data loaded into table '{table_name}'")

    return df


def load_commune_geometries(engine):
    """Load commune geometries from GeoJSON (including communes, arrondissements, and communes déléguées/associées)"""
    print("\nLoading commune geometries from multiple GeoJSON files...")

    geodataframes = []

    # Load communes geometries
    if os.path.exists(COMMUNES_GEOJSON):
        commune_geojson = COMMUNES_GEOJSON
        if commune_geojson.endswith(".gz"):
            commune_geojson = f"/vsigzip/{commune_geojson}"
        gdf_com = gpd.read_file(commune_geojson)
        print(f"✓ Loaded {len(gdf_com)} communes with geometries")
        geodataframes.append(gdf_com)
    else:
        print(f"⚠️  File not found: {COMMUNES_GEOJSON}")

    # Load arrondissements geometries
    if os.path.exists(ARRONDISSEMENTS_GEOJSON):
        arrondissements_geojson = ARRONDISSEMENTS_GEOJSON
        if arrondissements_geojson.endswith(".gz"):
            arrondissements_geojson = f"/vsigzip/{arrondissements_geojson}"
        gdf_arm = gpd.read_file(arrondissements_geojson)
        print(f"✓ Loaded {len(gdf_arm)} arrondissements with geometries")
        geodataframes.append(gdf_arm)
    else:
        print(f"⚠️  File not found: {ARRONDISSEMENTS_GEOJSON.replace('/vsigzip/', '')}")

    # Load communes déléguées/associées geometries
    if os.path.exists(COMMUNES_DELEGUEES_GEOJSON):
        communes_deleguees_geojson = COMMUNES_DELEGUEES_GEOJSON
        if communes_deleguees_geojson.endswith(".gz"):
            communes_deleguees_geojson = f"/vsigzip/{communes_deleguees_geojson}"
        gdf_comda = gpd.read_file(communes_deleguees_geojson)
        print(f"✓ Loaded {len(gdf_comda)} communes déléguées/associées with geometries")
        geodataframes.append(gdf_comda)
    else:
        print(
            f"⚠️  File not found: {COMMUNES_DELEGUEES_GEOJSON.replace('/vsigzip/', '')}"
        )

    if not geodataframes:
        print("❌ No GeoJSON files found!")
        print(
            "Please run 2_download_geometries_ign.py, 3_convert_admin_express_into_geojson.py, 4_assemble_communes_and_mairies_from_source.py, 5_simplify_geojson.py and 6_assemble_by_admin_units.py first"
        )
        sys.exit(1)

    # Concatenate all geodataframes
    gdf = pd.concat(geodataframes, ignore_index=True)
    gdf = gdf.fillna(value=np.nan)
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=geodataframes[0].crs)

    print(f"\n✓ Total entities with geometries: {len(gdf)}")
    print(f"  CRS: {gdf.crs}")
    print(f"  Columns: {', '.join(gdf.columns)}")

    # Rename columns to lowercase for easier SQL queries (except geometry)
    print("  Renaming columns to lowercase...")
    gdf.columns = [col.lower() if col != "geometry" else col for col in gdf.columns]
    print(f"  Columns after rename: {', '.join(gdf.columns)}")

    # Create unified 'code' column based on entity type
    print("  Creating unified 'code' column...")
    gdf["code"] = gdf["code_insee"]
    gdf = gdf.drop(columns=["zone"])
    print("  ✓ Unified 'code' column created")
    print(f"    Sample codes: {gdf['code'].head(3).tolist()}")
    print(f"    Codes with values: {gdf['code'].notna().sum()} / {len(gdf)}")

    # Convert to WGS84 if needed
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        print(f"  Converting CRS from {gdf.crs} to EPSG:4326...")
        gdf = gdf.to_crs(epsg=4326)

    table_name = "communes_geometries"
    print(f"\n  Loading {len(gdf)} geometries into database...")

    print("  Computing geometry bounding boxes...")
    bounds = gdf.geometry.bounds
    gdf["min_lon"] = bounds["minx"]
    gdf["min_lat"] = bounds["miny"]
    gdf["max_lon"] = bounds["maxx"]
    gdf["max_lat"] = bounds["maxy"]

    print("  Converting geometries to WKT and GeoJSON...")
    gdf["geometry_geojson"] = gdf["geometry"].apply(
        lambda geom: (
            json.dumps(mapping(geom))
            if geom is not None and not geom.is_empty
            else None
        )
    )
    gdf["geometry"] = gdf["geometry"].apply(lambda geom: geom.wkt if geom else None)

    print("  Loading geometries to database...")
    gdf.to_sql(table_name, engine, if_exists="replace", index=False)
    queries_fix_type = [
        f"""ALTER TABLE {table_name} ADD COLUMN population_fix INTEGER;""",
        f"""UPDATE {table_name} SET population_fix = CAST(population as INTEGER);""",
        f"""ALTER TABLE {table_name} DROP COLUMN population;""",
        f"""ALTER TABLE {table_name} RENAME COLUMN population_fix TO population;""",
    ]
    with engine.connect() as conn:
        for query in queries_fix_type:
            conn.execute(text(query))

    print(f"✓ All geometries loaded into table '{table_name}'")

    return gdf


def ensure_admin_geometry_tables(engine) -> None:
    """Crée les tables de géométries admin si absentes (évite des vues SQL cassées)."""
    specs = (
        ("departements_geometries", "dep"),
        ("regions_geometries", "reg"),
    )
    with engine.connect() as conn:
        for table, code_col in specs:
            exists = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t"),
                {"t": table},
            ).fetchone()
            if exists:
                continue
            print(f"  Creating empty table {table}...")
            conn.execute(
                text(f"""
                    CREATE TABLE {table} (
                        {code_col} TEXT PRIMARY KEY,
                        nom TEXT,
                        geometry TEXT,
                        geometry_geojson TEXT
                    )
                """)
            )
        conn.commit()


def load_geometry_table_from_geojson(
    engine,
    *,
    geojson_path: str,
    table_name: str,
    code_column: str,
    label: str,
) -> bool:
    """Charge WKT + GeoJSON pré-calculé dans une table admin (départements/régions)."""
    ensure_admin_geometry_tables(engine)

    if not os.path.exists(geojson_path):
        print(f"⚠️  File not found: {geojson_path}")
        print("  Run scripts 3 and 4 first to generate and simplify GeoJSON files")
        return False

    print(f"\n  Loading {label} geometries from {geojson_path}...")
    if geojson_path.endswith(".gz"):
        geojson_path = f"/vsigzip/{geojson_path}"
    gdf = gpd.read_file(geojson_path)
    print(f"✓ Loaded {len(gdf)} {label} with geometries")

    gdf.columns = [col.lower() if col != "geometry" else col for col in gdf.columns]
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        print(f"  Converting CRS from {gdf.crs} to EPSG:4326...")
        gdf = gdf.to_crs(epsg=4326)

    with engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        conn.commit()
        conn.execute(
            text(f"""
                CREATE TABLE {table_name} (
                    {code_column} TEXT PRIMARY KEY,
                    nom TEXT,
                    geometry TEXT,
                    geometry_geojson TEXT
                )
            """)
        )
        conn.commit()

        print(f"  Converting {label} geometries to WKT and GeoJSON...")
        for _, row in gdf.iterrows():
            code = row.get(code_column)
            nom = row.get("nom") or row.get("libelle")
            geom = row["geometry"]
            if geom and code:
                try:
                    conn.execute(
                        text(f"""
                            INSERT INTO {table_name} ({code_column}, nom, geometry, geometry_geojson)
                            VALUES (:code, :nom, :geometry, :geojson)
                        """),
                        {
                            "code": code,
                            "nom": nom,
                            "geometry": geom.wkt,
                            "geojson": json.dumps(mapping(geom)),
                        },
                    )
                except Exception as e:
                    print(f"    ⚠️  Error loading {code}: {e}")

        conn.commit()
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        print(f"✓ Loaded {count} {label} geometries from simplified GeoJSON")
    return True


def load_departements(engine):
    """Load departements metadata and geometries from simplified GeoJSON"""
    print("\nLoading departements data...")

    # Load departements metadata
    if not os.path.exists(DEPARTEMENTS_CSV):
        print(f"⚠️  File not found: {DEPARTEMENTS_CSV}")
        print("  Please run script 1 first")
        return None

    print(f"  Loading departements metadata from {DEPARTEMENTS_CSV}...")
    df_dept_admin_express = pd.read_csv(DEPARTEMENTS_CSV, encoding="utf-8", dtype=str)
    df_dept_admin_express["zone"] = df_dept_admin_express.dep.apply(
        lambda x: "drom" if x.startswith("97") else "metro"
    )
    print(f"✓ Loaded {len(df_dept_admin_express)} departements")

    df_dept = pd.concat([df_dept_admin_express, departements_com], ignore_index=True)

    print("  Building nom_recherche (normalized names for API search)...")
    df_dept["nom_recherche"] = df_dept["libelle"].apply(
        lambda x: normalize_string(x) if pd.notna(x) else ""
    )
    print(
        f"  ✓ nom_recherche column added "
        f"({df_dept['nom_recherche'].ne('').sum()} non-empty values)"
    )

    # Load into database
    table_name = "departements_metadata"
    df_dept.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"✓ Metadata loaded into table '{table_name}'")

    load_geometry_table_from_geojson(
        engine,
        geojson_path=DEPARTEMENTS_GEOJSON,
        table_name="departements_geometries",
        code_column="dep",
        label="departements",
    )

    print("✓ Departements data loaded successfully")
    return df_dept


def load_regions(engine):
    """Load regions metadata and geometries from simplified GeoJSON"""
    print("\nLoading regions data...")

    # Load regions metadata
    if not os.path.exists(REGIONS_CSV):
        print(f"⚠️  File not found: {REGIONS_CSV}")
        print("  Please run script 1 first")
        return None

    print(f"  Loading regions metadata from {REGIONS_CSV}...")
    df_reg_admin_express = pd.read_csv(REGIONS_CSV, encoding="utf-8", dtype=str)
    df_reg_admin_express["zone"] = df_reg_admin_express.cheflieu.apply(
        lambda x: "drom" if x.startswith("97") else "metro"
    )
    print(f"✓ Loaded {len(df_reg_admin_express)} regions")

    df_reg = pd.concat([df_reg_admin_express, regions_com], ignore_index=True)

    print("  Building nom_recherche (normalized names for API search)...")
    df_reg["nom_recherche"] = df_reg["libelle"].apply(
        lambda x: normalize_string(x) if pd.notna(x) else ""
    )
    print(
        f"  ✓ nom_recherche column added "
        f"({df_reg['nom_recherche'].ne('').sum()} non-empty values)"
    )

    # Load into database
    table_name = "regions_metadata"
    df_reg.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"✓ Metadata loaded into table '{table_name}'")

    load_geometry_table_from_geojson(
        engine,
        geojson_path=REGIONS_GEOJSON,
        table_name="regions_geometries",
        code_column="reg",
        label="regions",
    )

    print("✓ Regions data loaded successfully")
    return df_reg


def _ensure_interco_geometries_table(conn):
    """Create an empty interco_geometries table if it does not exist."""
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS interco_geometries (
            siren TEXT PRIMARY KEY,
            nom TEXT,
            nb_communes INTEGER,
            geometry TEXT,
            geometry_geojson TEXT
        )
    """)
    )
    conn.commit()


def _resolve_interco_geojson_path():
    """Prefer simplified GeoJSON; fall back to full intercommunalites.geojson."""
    if os.path.exists(INTERCO_GEOJSON):
        return INTERCO_GEOJSON
    return None


def _load_interco_geometries_from_geojson(engine, geojson_path):
    """Load intercommunalité geometries from a GeoJSON file into interco_geometries."""
    print(f"\n  Loading intercommunalités geometries from {geojson_path}...")
    if geojson_path.endswith(".gz"):
        geojson_path = f"/vsigzip/{geojson_path}"
    gdf_interco = gpd.read_file(geojson_path)
    print(f"✓ Loaded {len(gdf_interco)} intercommunalités with geometries")

    gdf_interco.columns = [
        col.lower() if col != "geometry" else col for col in gdf_interco.columns
    ]
    if gdf_interco.crs and gdf_interco.crs.to_epsg() != 4326:
        print(f"  Converting CRS from {gdf_interco.crs} to EPSG:4326...")
        gdf_interco = gdf_interco.to_crs(epsg=4326)

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS interco_geometries"))
        conn.commit()
        _ensure_interco_geometries_table(conn)

        print("  Converting geometries to WKT and GeoJSON...")
        loaded = 0
        for _, row in gdf_interco.iterrows():
            siren = row.get("nn_siren") or row.get("siren")
            nom = row.get("nom_du_groupement") or row.get("nom")
            nb_communes = row.get("nb_communes")
            geom = row["geometry"]
            if geom is None or not siren:
                continue
            try:
                conn.execute(
                    text("""
                        INSERT INTO interco_geometries (siren, nom, nb_communes, geometry, geometry_geojson)
                        VALUES (:siren, :nom, :nb_communes, :geometry, :geojson)
                    """),
                    {
                        "siren": siren,
                        "nom": nom,
                        "nb_communes": int(nb_communes)
                        if pd.notna(nb_communes)
                        else None,
                        "geometry": geom.wkt,
                        "geojson": json.dumps(mapping(geom)),
                    },
                )
                loaded += 1
            except Exception as e:
                print(f"    ⚠️  Error loading {siren}: {e}")
        conn.commit()
        print(f"✓ Loaded {loaded} intercommunalité geometries from GeoJSON")
        print("  ✓ GeoJSON pre-computed during loading")


def load_interco(engine):
    """Load intercommunalité metadata and geometries from simplified GeoJSON"""
    print("\nLoading intercommunalités data...")

    # Load intercommunalité metadata
    if not os.path.exists(INTERCO_CSV):
        print(f"⚠️  File not found: {INTERCO_CSV}")
        print("  Please run script 1 first")
        return None

    print(f"  Loading intercommunalités metadata from {INTERCO_CSV}...")
    df_interco = pd.read_csv(INTERCO_CSV, encoding="utf-8", dtype=str)
    print(f"✓ Loaded {len(df_interco)} intercommunalités")

    print("  Building nom_recherche (normalized names for API search)...")
    df_interco["nom_recherche"] = df_interco["nom_du_groupement"].apply(
        lambda x: normalize_string(x) if pd.notna(x) else ""
    )
    print(
        f"  ✓ nom_recherche column added "
        f"({df_interco['nom_recherche'].ne('').sum()} non-empty values)"
    )

    # Load into database
    table_name = "interco_metadata"
    df_interco.to_sql(table_name, engine, if_exists="replace", index=False)
    print(f"✓ Metadata loaded into table '{table_name}'")

    geojson_path = _resolve_interco_geojson_path()
    if geojson_path is None:
        print(f"⚠️  File not found: {INTERCO_GEOJSON}")
        print(
            "  Please run scripts 3, 4 and 5 first to generate and simplify GeoJSON files"
        )
        with engine.connect() as conn:
            _ensure_interco_geometries_table(conn)
        print("✓ Empty interco_geometries table created (metadata-only mode)")
        return df_interco

    _load_interco_geometries_from_geojson(engine, geojson_path)
    print("✓ Intercommunalités data loaded successfully")
    return df_interco


def _ensure_aom_geometries_table(conn):
    """Create an empty aom_geometries table if it does not exist."""
    conn.execute(
        text("""
        CREATE TABLE IF NOT EXISTS aom_geometries (
            siren TEXT PRIMARY KEY,
            nom TEXT,
            nb_communes INTEGER,
            geometry TEXT,
            geometry_geojson TEXT
        )
    """)
    )
    conn.commit()


def _resolve_aom_geojson_path():
    """Prefer simplified GeoJSON; fall back to full aom.geojson."""
    if os.path.exists(AOM_GEOJSON):
        return AOM_GEOJSON
    if os.path.exists(AOM_GEOJSON_FALLBACK):
        print(f"  ⚠️  {AOM_GEOJSON} not found, using {AOM_GEOJSON_FALLBACK}")
        return AOM_GEOJSON_FALLBACK
    return None


def _load_aom_geometries_from_geojson(engine, geojson_path):
    """Load AOM geometries from a GeoJSON file into aom_geometries."""
    print(f"\n  Loading AOM geometries from {geojson_path}...")
    if geojson_path.endswith(".gz"):
        geojson_path = f"/vsigzip/{geojson_path}"
    gdf_aom = gpd.read_file(geojson_path)
    print(f"✓ Loaded {len(gdf_aom)} AOM with geometries")

    gdf_aom.columns = [
        col.lower() if col != "geometry" else col for col in gdf_aom.columns
    ]
    if gdf_aom.crs and gdf_aom.crs.to_epsg() != 4326:
        print(f"  Converting CRS from {gdf_aom.crs} to EPSG:4326...")
        gdf_aom = gdf_aom.to_crs(epsg=4326)

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS aom_geometries"))
        conn.commit()
        _ensure_aom_geometries_table(conn)

        print("  Converting geometries to WKT and GeoJSON...")
        loaded = 0
        for _, row in gdf_aom.iterrows():
            siren = row.get("siren")
            nom = row.get("nom")
            nb_communes = row.get("nb_communes")
            geom = row["geometry"]
            if geom is None or not siren:
                continue
            try:
                conn.execute(
                    text("""
                        INSERT INTO aom_geometries (siren, nom, nb_communes, geometry, geometry_geojson)
                        VALUES (:siren, :nom, :nb_communes, :geometry, :geojson)
                    """),
                    {
                        "siren": siren,
                        "nom": nom,
                        "nb_communes": int(nb_communes)
                        if pd.notna(nb_communes)
                        else None,
                        "geometry": geom.wkt,
                        "geojson": json.dumps(mapping(geom)),
                    },
                )
                loaded += 1
            except Exception as e:
                print(f"    ⚠️  Error loading AOM {siren}: {e}")
        conn.commit()
        print(f"✓ Loaded {loaded} AOM geometries from GeoJSON")


def load_aom(engine):
    """Load AOM metadata, liaisons commune-AOM et géométries."""
    print("\nLoading AOM data...")

    if not os.path.exists(AOM_CSV):
        print(f"⚠️  File not found: {AOM_CSV}")
        print("  Please run 1_download_decoupage_administratif_data.py first")
        return None

    if not os.path.exists(AOM_COMMUNE_CSV):
        print(f"⚠️  File not found: {AOM_COMMUNE_CSV}")
        return None

    print(f"  Loading AOM metadata from {AOM_CSV}...")
    df_aom = pd.read_csv(AOM_CSV, encoding="utf-8", dtype=str)
    print(f"✓ Loaded {len(df_aom)} AOM")

    print("  Building nom_recherche (normalized names for API search)...")
    df_aom["nom_recherche"] = df_aom["nom"].apply(
        lambda x: normalize_string(x) if pd.notna(x) else ""
    )

    print(f"  Loading commune → AOM links from {AOM_COMMUNE_CSV}...")
    df_aom_commune = pd.read_csv(AOM_COMMUNE_CSV, encoding="utf-8", dtype=str)
    print(f"✓ Loaded {len(df_aom_commune)} links")

    siren_to_insee = {}
    if os.path.exists(SIREN_INSEE_MAPPING_CSV):
        mapping_df = pd.read_csv(SIREN_INSEE_MAPPING_CSV, encoding="utf-8", dtype=str)
        siren_to_insee = dict(zip(mapping_df["Siren"], mapping_df["COM"]))
        df_aom_commune["commune_code"] = df_aom_commune["siren_commune"].map(
            siren_to_insee
        )
        mapped = df_aom_commune["commune_code"].notna().sum()
        print(f"  ✓ {mapped}/{len(df_aom_commune)} liaisons avec code INSEE")
    else:
        df_aom_commune["commune_code"] = None
        print(f"  ⚠️  {SIREN_INSEE_MAPPING_CSV} not found, commune_code will be empty")

    communes_by_aom = (
        df_aom_commune.dropna(subset=["siren_aom"])
        .groupby("siren_aom")["commune_code"]
        .apply(
            lambda codes: json.dumps(sorted({c for c in codes if pd.notna(c) and c}))
        )
        .reset_index(name="communes_code")
        .rename(columns={"siren_aom": "siren"})
    )
    nb_communes = (
        df_aom_commune.dropna(subset=["siren_aom"])
        .groupby("siren_aom")["siren_commune"]
        .nunique()
        .reset_index()
        .rename(columns={"siren_aom": "siren", "siren_commune": "nb_communes"})
    )
    df_aom = df_aom.merge(nb_communes, on="siren", how="left")
    df_aom = df_aom.merge(communes_by_aom, on="siren", how="left")
    df_aom["nb_communes"] = df_aom["nb_communes"].fillna(0).astype(int)

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS aom_commune"))
        conn.commit()

    df_aom_commune[["siren_commune", "siren_aom", "commune_code"]].to_sql(
        "aom_commune", engine, if_exists="replace", index=False
    )
    print("✓ Liaisons loaded into table 'aom_commune'")

    df_aom.to_sql("aom_metadata", engine, if_exists="replace", index=False)
    print("✓ Metadata loaded into table 'aom_metadata'")

    geojson_path = _resolve_aom_geojson_path()
    if geojson_path is None:
        print(f"⚠️  File not found: {AOM_GEOJSON}")
        print("  Please run scripts 3 and 4 first to generate and simplify aom.geojson")
        with engine.connect() as conn:
            _ensure_aom_geometries_table(conn)
        print("✓ Empty aom_geometries table created (metadata-only mode)")
        return df_aom

    _load_aom_geometries_from_geojson(engine, geojson_path)
    print("✓ AOM data loaded successfully")
    return df_aom


def load_commune_interco_associations(engine):
    """Load all commune-intercommunalité associations from interco_members.csv

    Handles transitive associations: when an interco has another interco as member,
    all communes of the member interco are also associated with the parent interco.

    Example: Evolis 23 has CC Grand Guéret as member, which contains commune Peyrabout.
    Result: Peyrabout is associated with both CC Grand Guéret AND Evolis 23.
    """
    print("\nLoading commune-intercommunalité associations...")

    # Check if file exists
    if not os.path.exists(INTERCO_MEMBERS_CSV):
        print(f"⚠️  File not found: {INTERCO_MEMBERS_CSV}")
        print("  Associations table will not be created")
        return None

    print(f"  Loading associations from {INTERCO_MEMBERS_CSV}...")

    # Load the members CSV
    try:
        df_members = pd.read_csv(
            INTERCO_MEMBERS_CSV, encoding="utf-8", dtype=str, low_memory=False
        )
        print(f"✓ Loaded {len(df_members)} association records")
    except Exception as e:
        print(f"❌ Error loading file: {e}")
        return None

    # Extract relevant columns
    # siren_membre is the SIREN of the commune/member
    # nn_siren is the SIREN of the intercommunalité
    if "siren_membre" not in df_members.columns or "nn_siren" not in df_members.columns:
        print(f"⚠️  Required columns not found in {INTERCO_MEMBERS_CSV}")
        return None

    # Create a clean dataframe with commune SIREN -> interco SIREN associations
    associations = df_members[
        [
            "siren_membre",
            "nn_siren",
            "nom_du_groupement",
            "nature_juridique",
            "categorie_des_membres_du_groupement",
        ]
    ].copy()
    associations = associations.rename(
        columns={
            "siren_membre": "commune_siren",
            "nn_siren": "interco_siren",
            "nom_du_groupement": "interco_nom",
            "nature_juridique": "interco_nature",
            "categorie_des_membres_du_groupement": "membre_categorie",
        }
    )

    # Remove rows with missing essential data
    associations = associations.dropna(subset=["commune_siren", "interco_siren"])

    print(f"  {len(associations)} associations before deduplication")

    # Separate direct commune associations from interco-to-interco associations
    commune_associations = associations[
        associations["membre_categorie"] == "commune"
    ].copy()
    interco_to_interco = associations[
        associations["membre_categorie"] == "groupement"
    ].copy()

    print(f"  {len(commune_associations)} direct commune associations")
    print(f"  {len(interco_to_interco)} interco-to-interco associations")

    # Create transitive associations: for each interco that has another interco as member,
    # find all communes of that member interco and create associations
    transitive_associations = []

    if len(interco_to_interco) > 0:
        print("\n  Creating transitive associations...")

        for idx, row in interco_to_interco.iterrows():
            parent_interco_siren = row["interco_siren"]  # e.g., Evolis 23
            parent_interco_nom = row["interco_nom"]
            parent_interco_nature = row["interco_nature"]
            member_interco_siren = row[
                "commune_siren"
            ]  # e.g., CC Grand Guéret (it's actually an interco)

            # Find all communes that are members of this member interco
            member_communes = commune_associations[
                commune_associations["interco_siren"] == member_interco_siren
            ]

            if len(member_communes) > 0:
                # Create associations between these communes and the parent interco
                for _, commune_row in member_communes.iterrows():
                    transitive_associations.append(
                        {
                            "commune_siren": commune_row[
                                "commune_siren"
                            ],  # e.g., Peyrabout
                            "interco_siren": parent_interco_siren,  # e.g., Evolis 23
                            "interco_nom": parent_interco_nom,
                            "interco_nature": parent_interco_nature,
                            "membre_categorie": "commune (transitif)",
                        }
                    )

        if transitive_associations:
            df_transitive = pd.DataFrame(transitive_associations)
            print(f"  ✓ Created {len(df_transitive)} transitive associations")

            # Combine direct and transitive associations
            associations = pd.concat(
                [commune_associations, df_transitive], ignore_index=True
            )
        else:
            print("  ⚠️  No transitive associations could be created")
            associations = commune_associations
    else:
        associations = commune_associations

    # Remove duplicates: keep the first occurrence of each (commune_siren, interco_siren) pair
    print(f"\n  {len(associations)} total associations before final deduplication")
    associations = associations.drop_duplicates(
        subset=["commune_siren", "interco_siren"], keep="first"
    )

    print(f"  {len(associations)} unique associations after deduplication")

    # Create table in database
    print("\n  Creating commune_interco_associations table...")
    with engine.connect() as conn:
        # Drop table if exists
        conn.execute(text("DROP TABLE IF EXISTS commune_interco_associations"))
        conn.commit()

        # Create table
        conn.execute(
            text("""
            CREATE TABLE commune_interco_associations (
                commune_siren TEXT,
                interco_siren TEXT,
                interco_nom TEXT,
                interco_nature TEXT,
                membre_categorie TEXT,
                PRIMARY KEY (commune_siren, interco_siren)
            )
        """)
        )
        conn.commit()
        print("    ✓ Table created")

    # Load data into table
    print("  Loading associations into database...")
    associations.to_sql(
        "commune_interco_associations", engine, if_exists="append", index=False
    )

    # Create indexes
    print("  Creating indexes...")
    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_commune_interco_assoc_commune
            ON commune_interco_associations(commune_siren)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_commune_interco_assoc_interco
            ON commune_interco_associations(interco_siren)
        """)
        )
        conn.commit()

    print(f"✓ {len(associations)} commune-intercommunalité associations loaded")

    # -------------------------------------------------------------------------
    # Build interco_commune competency join table
    # One row = one competence marked "OUI" for a (interco, commune) pair
    # -------------------------------------------------------------------------
    print("\n  Creating interco_commune competency join table...")

    competence_start_col = "nombre_de_competences_exercees"
    competence_end_col = "adhesion_siren"

    if (
        competence_start_col in df_members.columns
        and competence_end_col in df_members.columns
    ):
        start_idx = df_members.columns.get_loc(competence_start_col) + 1
        end_idx = df_members.columns.get_loc(competence_end_col)
        competence_columns = list(df_members.columns[start_idx:end_idx])
    else:
        competence_columns = []

    if not competence_columns:
        print("  ⚠️  Competence columns not found in interco_members.csv")
        print("  interco_commune table will be created empty")
        interco_competences = pd.DataFrame(
            columns=["interco_siren", "commune_siren", "commune_code", "competence"]
        )
    else:
        print(f"  Detected {len(competence_columns)} competence columns")

        # Build a competence source that includes:
        # 1) direct commune members
        # 2) transitive propagation when a member is an interco/groupement
        competence_rows = []

        competence_input = df_members[
            [
                "nn_siren",
                "siren_membre",
                "categorie_des_membres_du_groupement",
            ]
            + competence_columns
        ].copy()

        # 1) Direct communes
        direct_comp_rows = competence_input[
            competence_input["categorie_des_membres_du_groupement"] == "commune"
        ]
        for _, row in direct_comp_rows.iterrows():
            row_dict = {
                "interco_siren": row["nn_siren"],
                "commune_siren": row["siren_membre"],
            }
            for col in competence_columns:
                row_dict[col] = row[col]
            competence_rows.append(row_dict)

        # 2) Groupement members: propagate competencies to all communes of member interco
        groupement_comp_rows = competence_input[
            competence_input["categorie_des_membres_du_groupement"] == "groupement"
        ]
        if len(groupement_comp_rows) > 0:
            for _, row in groupement_comp_rows.iterrows():
                parent_interco_siren = row["nn_siren"]
                member_interco_siren = row["siren_membre"]
                member_communes = associations[
                    associations["interco_siren"] == member_interco_siren
                ]

                if len(member_communes) == 0:
                    continue

                for _, commune_row in member_communes.iterrows():
                    row_dict = {
                        "interco_siren": parent_interco_siren,
                        "commune_siren": commune_row["commune_siren"],
                    }
                    for col in competence_columns:
                        row_dict[col] = row[col]
                    competence_rows.append(row_dict)

        competence_source = pd.DataFrame(competence_rows)
        competence_source = competence_source.dropna(
            subset=["interco_siren", "commune_siren"]
        )

        # Attach commune code (INSEE) when available
        with engine.connect() as conn:
            commune_mapping_rows = conn.execute(
                text("""
                SELECT DISTINCT
                    siren AS commune_siren,
                    com AS commune_code
                FROM communes_metadata
                WHERE siren IS NOT NULL AND com IS NOT NULL
            """)
            ).fetchall()

        commune_mapping = pd.DataFrame(
            commune_mapping_rows, columns=["commune_siren", "commune_code"]
        )
        if len(commune_mapping) > 0:
            commune_mapping = commune_mapping.drop_duplicates(
                subset=["commune_siren"], keep="first"
            )
            competence_source = competence_source.merge(
                commune_mapping, on="commune_siren", how="left"
            )
        else:
            competence_source["commune_code"] = None

        if len(competence_source) == 0:
            interco_competences = pd.DataFrame(
                columns=["interco_siren", "commune_siren", "commune_code", "competence"]
            )
        else:
            # Pivot competencies to long format and keep only "OUI"
            interco_competences = competence_source.melt(
                id_vars=["interco_siren", "commune_siren", "commune_code"],
                value_vars=competence_columns,
                var_name="competence",
                value_name="value",
            )
            interco_competences["value"] = (
                interco_competences["value"]
                .fillna("")
                .astype(str)
                .str.strip()
                .str.upper()
            )
            interco_competences = interco_competences[
                interco_competences["value"] == "OUI"
            ].copy()
            interco_competences = interco_competences.drop(columns=["value"])
            interco_competences = interco_competences.drop_duplicates(
                subset=["interco_siren", "commune_siren", "competence"],
                keep="first",
            )

    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS interco_commune"))
        conn.commit()

        conn.execute(
            text("""
            CREATE TABLE interco_commune (
                interco_siren TEXT,
                commune_siren TEXT,
                commune_code TEXT,
                competence TEXT,
                PRIMARY KEY (interco_siren, commune_siren, competence)
            )
        """)
        )
        conn.commit()
        print("    ✓ interco_commune table created")

    if len(interco_competences) > 0:
        print(
            f"  Loading {len(interco_competences)} interco_commune competence rows..."
        )
        interco_competences.to_sql(
            "interco_commune", engine, if_exists="append", index=False
        )
    else:
        print("  ⚠️  No 'OUI' competence rows found to load")

    with engine.connect() as conn:
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_interco_commune_interco
            ON interco_commune(interco_siren)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_interco_commune_commune_siren
            ON interco_commune(commune_siren)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_interco_commune_commune_code
            ON interco_commune(commune_code)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_interco_commune_competence
            ON interco_commune(competence)
        """)
        )
        conn.commit()

    print(f"✓ {len(interco_competences)} rows loaded into interco_commune")

    # Display some statistics
    unique_communes = associations["commune_siren"].nunique()
    unique_intercos = associations["interco_siren"].nunique()
    avg_intercos_per_commune = (
        len(associations) / unique_communes if unique_communes > 0 else 0
    )

    print("  Statistics:")
    print(f"    - Unique communes: {unique_communes}")
    print(f"    - Unique intercommunalités: {unique_intercos}")
    print(f"    - Avg associations per commune: {avg_intercos_per_commune:.1f}")

    # Show distribution of association counts
    assoc_counts = associations.groupby("commune_siren").size()
    print(f"    - Communes with 1 interco: {(assoc_counts == 1).sum()}")
    print(
        f"    - Communes with 2-5 intercos: {((assoc_counts >= 2) & (assoc_counts <= 5)).sum()}"
    )
    print(f"    - Communes with 6+ intercos: {(assoc_counts >= 6).sum()}")

    return associations


def ensure_communes_bbox(engine) -> bool:
    """
    Ajoute et remplit min_lon/min_lat/max_lon/max_lat sur communes_geometries
    si la base a été créée avant cette fonctionnalité. Retourne True si des bbox
    ont été calculées ou étaient déjà présentes.
    """
    print("\nEnsuring commune bounding boxes...")
    with engine.connect() as conn:
        cols = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(communes_geometries)")
            ).fetchall()
        }
        if "communes_geometries" not in {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='communes_geometries'"
                )
            ).fetchall()
        }:
            print("  ⚠️  Table communes_geometries absente, rien à faire")
            return False

        if "min_lon" not in cols:
            print("  Adding bbox columns to communes_geometries...")
            for col in ("min_lon", "min_lat", "max_lon", "max_lat"):
                conn.execute(
                    text(f"ALTER TABLE communes_geometries ADD COLUMN {col} REAL")
                )
            conn.commit()

        pending = conn.execute(
            text("""
                SELECT COUNT(*) FROM communes_geometries
                WHERE geometry IS NOT NULL
                  AND (min_lon IS NULL OR min_lat IS NULL OR max_lon IS NULL OR max_lat IS NULL)
            """)
        ).scalar()
        if not pending:
            print("  ✓ Bbox columns already populated")
            return True

        print(f"  Computing bbox for {pending:,} geometries...")
        rows = conn.execute(
            text(
                "SELECT code, geometry FROM communes_geometries WHERE geometry IS NOT NULL"
            )
        ).fetchall()

    updates = []
    for code, geom_str in rows:
        if not geom_str:
            continue
        try:
            geom = shapely_wkt.loads(geom_str)
            if geom.is_empty:
                continue
            minx, miny, maxx, maxy = geom.bounds
            updates.append(
                {
                    "code": code,
                    "min_lon": minx,
                    "min_lat": miny,
                    "max_lon": maxx,
                    "max_lat": maxy,
                }
            )
        except Exception:
            continue

    if not updates:
        print("  ⚠️  No geometry could be parsed for bbox")
        return False

    with engine.connect() as conn:
        conn.execute(
            text("""
                UPDATE communes_geometries
                SET min_lon = :min_lon, min_lat = :min_lat, max_lon = :max_lon, max_lat = :max_lat
                WHERE code = :code
            """),
            updates,
        )
        conn.commit()

    print(f"  ✓ Bbox computed for {len(updates):,} communes")
    return True


def create_indexes(engine):
    """Create indexes for optimal query performance"""
    print("\nCreating indexes...")

    with engine.connect() as conn:
        # Index on commune code (metadata table)
        print("  Creating index on communes_metadata.com...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_com
            ON communes_metadata(com)
        """)
        )

        print(
            "  Creating index on communes_metadata.typecom and communes_metadata.libelle..."
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_typecom_libelle
            ON communes_metadata(typecom, libelle)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_zone
            ON communes_metadata(zone)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX idx_communes_anciens_codes_code
            ON communes_anciens_codes(ancien_code)
        """)
        )
        # Index on unified code (geometry table)
        print("  Creating index on communes_geometries.code...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_geometries_code
            ON communes_geometries(code)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_geometries_bbox
            ON communes_geometries(min_lon, max_lon, min_lat, max_lat)
        """)
        )
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_geometries_code_insee_nature
            ON communes_geometries(code_insee, nature)
        """)
        )

        # Index on department code
        print("  Creating index on communes_metadata.dep...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_dep
            ON communes_metadata(dep)
        """)
        )

        # Index on region code
        print("  Creating index on communes_metadata.reg...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_reg
            ON communes_metadata(reg)
        """)
        )

        # Index on type_commune
        print("  Creating index on communes_metadata.typecom...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_typecom
            ON communes_metadata(typecom)
        """)
        )

        print("  Creating index on communes_metadata.nom_recherche...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_nom_recherche
            ON communes_metadata(nom_recherche)
        """)
        )

        print("  Creating index on communes_metadata.libelle...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_communes_metadata_libelle
            ON communes_metadata(libelle)
        """)
        )

        print("  Creating index on interco_metadata.nom_recherche...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_interco_metadata_nom_recherche
            ON interco_metadata(nom_recherche)
        """)
        )

        print("  Creating index on aom_metadata.siren...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_aom_metadata_siren
            ON aom_metadata(siren)
        """)
        )
        print("  Creating index on aom_metadata.nom_recherche...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_aom_metadata_nom_recherche
            ON aom_metadata(nom_recherche)
        """)
        )
        print("  Creating index on aom_commune.siren_aom...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_aom_commune_siren_aom
            ON aom_commune(siren_aom)
        """)
        )
        print("  Creating index on aom_commune.siren_commune...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_aom_commune_siren_commune
            ON aom_commune(siren_commune)
        """)
        )
        print("  Creating index on aom_commune.commune_code...")
        conn.execute(
            text("""
            CREATE INDEX IF NOT EXISTS idx_aom_commune_commune_code
            ON aom_commune(commune_code)
        """)
        )

        conn.commit()

    print("✓ All indexes created successfully")


def create_view(engine):
    """Create a view joining metadata and geometries"""
    print("\nCreating communes view...")

    with engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS communes"))

        view_sql = """
            CREATE VIEW communes AS
            SELECT
                m.com as code_insee,
                m.libelle as nom,
                m.nom_recherche as nom_recherche,
                m.typecom as type_commune,
                m.reg as code_region,
                m.dep as code_departement,
                m.arr as code_arrondissement,
                m.ctcd as code_collectivite,
                m.can as code_canton,
                m.ncc as nom_majuscules,
                m.nccenr as nom_enrichi,
                m.tncc as type_nom,
                m.comparent as commune_parente,
                m.siren as siren,
                m.siren_interco as siren_interco,
                m.nom_interco as nom_interco,
                m.codes_postaux as codes_postaux,
                m.anciens_codes as anciens_codes,
                m.zone as zone,
                g.code as code_geo,
                -- g.insee_com as insee_com_geo,
                -- g.insee_arm as insee_arm_geo,
                -- g.insee_cad as insee_cad_geo,
                code_insee_de_la_commune_de_rattach,
                g.nom_officiel as nom_geo,
                g.nom_officiel_en_majuscules as nom_majuscules_geo,
                -- g.insee_can as code_canton_geo,
                -- g.insee_arr as code_arrondissement_geo,
                g.code_insee_du_departement as code_departement_geo,
                g.code_insee_de_la_region as code_region_geo,
                g.statut as statut,
                g.population as population,
                g.min_lon as min_lon,
                g.min_lat as min_lat,
                g.max_lon as max_lon,
                g.max_lat as max_lat,
                NULL as superficie,
                ma.mairie_geojson as mairie_geojson,
                g.geometry_geojson as geometry_geojson,
                g.geometry as geometry
            FROM communes_metadata m
            LEFT JOIN communes_geometries g ON m.com = g.code_insee
              AND (
                (m.typecom IN ('COM', 'ARM') AND g.code_insee = m.com AND g.nature IS NULL)
                OR (m.typecom IN ('COMD', 'COMA') AND g.code_insee = m.com AND g.nature IN ('COMD', 'COMA'))
              )
            LEFT JOIN communes_mairies ma ON (m.com = ma.code_insee AND m.typecom = 'COM')
        """

        conn.execute(text(view_sql))
        conn.commit()

    print("✓ View 'communes' created successfully")


def create_departements_view(engine):
    """Create a view joining departements metadata and geometries"""
    print("\nCreating departements view...")
    ensure_admin_geometry_tables(engine)

    with engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS departements"))

        # Use pre-computed GeoJSON for better performance
        view_sql = """
            CREATE VIEW departements AS
            SELECT
                m.dep as code_departement,
                m.libelle as nom,
                m.nom_recherche as nom_recherche,
                m.nccenr as nom_enrichi,
                m.ncc as nom_majuscules,
                m.tncc as type_nom,
                m.reg as code_region,
                m.cheflieu as code_chef_lieu,
                m.zone as zone,
                g.dep as dep_geo,
                g.geometry_geojson as geometry_geojson,
                g.geometry as geometry
            FROM departements_metadata m
            LEFT JOIN departements_geometries g ON m.dep = g.dep
        """

        conn.execute(text(view_sql))
        conn.commit()

    print("✓ View 'departements' created successfully (using pre-computed GeoJSON)")


def create_regions_view(engine):
    """Create a view joining regions metadata and geometries"""
    print("\nCreating regions view...")
    ensure_admin_geometry_tables(engine)

    with engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS regions"))

        # Use pre-computed GeoJSON for better performance
        view_sql = """
            CREATE VIEW regions AS
            SELECT
                m.reg as code_region,
                m.libelle as nom,
                m.nom_recherche as nom_recherche,
                m.nccenr as nom_enrichi,
                m.ncc as nom_majuscules,
                m.tncc as type_nom,
                m.cheflieu as code_chef_lieu,
                m.zone as zone,
                g.reg as reg_geo,
                g.geometry_geojson as geometry_geojson,
                g.geometry as geometry
            FROM regions_metadata m
            LEFT JOIN regions_geometries g ON m.reg = g.reg
        """

        conn.execute(text(view_sql))
        conn.commit()

    print("✓ View 'regions' created successfully (using pre-computed GeoJSON)")


def create_interco_view(engine):
    """Create a view joining intercommunalité metadata and geometries"""
    print("\nCreating intercommunalités view...")

    with engine.connect() as conn:
        conn.execute(text("DROP VIEW IF EXISTS interco"))

        # Use pre-computed GeoJSON for better performance
        view_sql = """
            CREATE VIEW interco AS
            SELECT
                m.nn_siren as siren,
                m.nom_du_groupement as nom,
                m.nom_recherche as nom_recherche,
                m.nature_juridique as nature,
                m.mode_de_financement as financement,
                m.date_de_creation as date_creation,
                m.population_totale as population,
                m.nombre_de_membres as nb_membres_declares,
                m.nombre_de_competences_exercees as nb_competences,
                m.membres_siren as membres_siren,
                m.communes_siren as communes_siren,
                m.communes_code as communes_code,
                m.nb_communes as nb_communes,
                g.siren as siren_geo,
                g.geometry_geojson as geometry_geojson,
                g.geometry as geometry
            FROM interco_metadata m
            LEFT JOIN interco_geometries g ON m.nn_siren = g.siren
        """

        conn.execute(text(view_sql))
        conn.commit()

    print("✓ View 'interco' created successfully (using pre-computed GeoJSON)")


def create_aom_view(engine):
    """Create a view joining AOM metadata and geometries."""
    print("\nCreating AOM view...")

    with engine.connect() as conn:
        _ensure_aom_geometries_table(conn)
        conn.execute(text("DROP VIEW IF EXISTS aom"))
        view_sql = """
            CREATE VIEW aom AS
            SELECT
                m.siren as siren,
                m.nom as nom,
                m.nom_recherche as nom_recherche,
                m.nb_communes as nb_communes,
                m.communes_code as communes_code,
                g.siren as siren_geo,
                g.geometry_geojson as geometry_geojson,
                g.geometry as geometry
            FROM aom_metadata m
            LEFT JOIN aom_geometries g ON m.siren = g.siren
        """
        conn.execute(text(view_sql))
        conn.commit()

    print("✓ View 'aom' created successfully (using pre-computed GeoJSON)")


def print_statistics(engine):
    """Print database statistics"""
    print("\n" + "=" * 60)
    print("DATABASE STATISTICS")
    print("=" * 60)

    with engine.connect() as conn:
        # Count total entities
        result = conn.execute(text("SELECT COUNT(*) FROM communes_metadata"))
        metadata_count = result.scalar()

        result = conn.execute(text("SELECT COUNT(*) FROM communes_geometries"))
        geometry_count = result.scalar()

        result = conn.execute(
            text("SELECT COUNT(*) FROM communes WHERE geometry IS NOT NULL")
        )
        complete_count = result.scalar()

        print(f"Total entities in metadata table:  {metadata_count:,}")
        print(f"Total entities in geometry table:  {geometry_count:,}")
        print(f"Total entities with full data:     {complete_count:,}")

        # Breakdown by TYPECOM
        print("\nBreakdown by type (TYPECOM):")
        result = conn.execute(
            text("""
            SELECT type_commune, COUNT(*) as count
            FROM communes
            GROUP BY type_commune
            ORDER BY count DESC
        """)
        )
        for row in result:
            type_label = {
                "COM": "Communes",
                "ARM": "Arrondissements municipaux",
                "COMD": "Communes déléguées",
                "COMA": "Communes associées",
            }.get(row[0], row[0])
            print(f"  {type_label:30s}: {row[1]:,}")

        try:
            result = conn.execute(text("SELECT COUNT(*) FROM aom_metadata"))
            aom_meta = result.scalar()
            result = conn.execute(
                text("SELECT COUNT(*) FROM aom WHERE geometry IS NOT NULL")
            )
            aom_geom = result.scalar()
            print("\nAOM:")
            print(f"  Metadata:                        {aom_meta:,}")
            print(f"  With geometry:                   {aom_geom:,}")
        except Exception:
            pass

        # Sample query
        result = conn.execute(
            text("""
            SELECT code_insee, nom, type_commune, code_departement, population
            FROM communes
            WHERE geometry IS NOT NULL
            ORDER BY CAST(population AS REAL) DESC
            LIMIT 5
        """)
        )

        print("\nTop 5 entities by population:")
        for row in result:
            pop = f"{float(row[4]):,.0f}" if row[4] else "N/A"
            type_label = {
                "COM": "COM",
                "ARM": "ARM",
                "COMD": "COMD",
                "COMA": "COMA",
            }.get(row[2], row[2])
            print(f"  {row[0]} - {row[1]} [{type_label}] ({row[3]}) - {pop} hab.")

    print("=" * 60)
    print(f"\n📁 Database file: {DB_FILE}")
    if os.path.exists(DB_FILE):
        file_size = os.path.getsize(DB_FILE) / (1024 * 1024)
        print(f"📊 File size: {file_size:.2f} MB")


def main():
    """Main execution function"""
    print("=" * 60)
    print("LOADING COMMUNE DATA INTO SQLITE")
    print("=" * 60)

    init_sqlite_db()

    # Create database connection
    engine = create_database_connection()

    # Drop existing views to avoid dependency issues
    drop_existing_views(engine)

    # Load data (communes, arrondissements, and communes déléguées/associées merged into one table)
    load_commune_data(engine)
    load_commune_geometries(engine)

    # Load anciensCodes in specific table
    load_anciens_codes(engine)

    # Load departements and create their geometries from communes
    load_departements(engine)

    # Load regions and create their geometries from departements
    load_regions(engine)

    # Load intercommunalités and create their geometries from communes
    load_interco(engine)

    # Load all commune-intercommunalité associations
    load_commune_interco_associations(engine)

    # Load AOM (metadata, liaisons commune-AOM, géométries)
    load_aom(engine)

    # Load mairie points (from mairies.geojson.gz)
    load_communes_mairies(engine)

    ensure_communes_bbox(engine)

    # Create indexes
    create_indexes(engine)

    # Create views
    create_view(engine)
    create_departements_view(engine)
    create_regions_view(engine)
    create_interco_view(engine)
    create_aom_view(engine)

    # Print statistics
    print_statistics(engine)

    print("\n✓ All data loaded successfully!")
    print(
        "  (GeoJSON for departements, regions, intercommunalités and AOM has been pre-computed for optimal performance)"
    )
    print("\nYou can now start the API with:")
    print("  uvicorn app.main:app --reload")
    print("  or")
    print("  docker-compose up api")


def migrate_bbox_only():
    """Met à jour une base existante (bbox + vue communes) sans recharger toutes les données."""
    print("=" * 60)
    print("MIGRATE COMMUNE BBOX (existing database)")
    print("=" * 60)
    engine = create_database_connection()
    if not ensure_communes_bbox(engine):
        sys.exit(1)
    create_view(engine)
    with engine.connect() as conn:
        conn.execute(
            text("""
                CREATE INDEX IF NOT EXISTS idx_communes_geometries_bbox
                ON communes_geometries(min_lon, max_lon, min_lat, max_lat)
            """)
        )
        conn.commit()
    print("\n✓ Migration bbox terminée. Redémarrez l'API si elle tourne déjà.")


def migrate_admin_geometries():
    """Répare ou recharge les géométries départements/régions sur une base existante."""
    print("=" * 60)
    print("MIGRATE ADMIN GEOMETRIES (départements + régions)")
    print("=" * 60)
    engine = create_database_connection()
    ensure_admin_geometry_tables(engine)

    dept_ok = load_geometry_table_from_geojson(
        engine,
        geojson_path=DEPARTEMENTS_GEOJSON,
        table_name="departements_geometries",
        code_column="dep",
        label="departements",
    )
    reg_ok = load_geometry_table_from_geojson(
        engine,
        geojson_path=REGIONS_GEOJSON,
        table_name="regions_geometries",
        code_column="reg",
        label="regions",
    )

    create_departements_view(engine)
    create_regions_view(engine)

    if not dept_ok and not reg_ok:
        print(
            "\n⚠️  Tables vides créées : l'API répond à nouveau, "
            "mais sans géométries tant que les GeoJSON ne sont pas générés."
        )
        print("  python3 3_convert_shape_into_geojson.py --aggregate-only")
        print("  python3 4_simplify_geojson.py")
        print("  python3 5_load_into_spatialite.py --migrate-admin-geometries")
    else:
        print("\n✓ Migration admin geometries terminée.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--migrate-bbox":
        migrate_bbox_only()
    elif len(sys.argv) > 1 and sys.argv[1] == "--migrate-admin-geometries":
        migrate_admin_geometries()
    else:
        main()
