#!/usr/bin/env python3
"""
Script to assemble AdminExpress sources with some OSM sources for missing data due to COM not available or mairies "mortes pour la France"
"""


import gzip
import os
import sys
import json
from pathlib import Path

from lxml import etree
import requests
import pandas as pd
import geopandas as gpd
import numpy as np


# Paths
DATA_DIR = "data"
SOURCE_DIR = "sources"
GPKG_NAME = 'admin_express.gpkg'

COMMUNES_NOT_IN_ADMIN_EXPRESS = 'osm-communes-com-without-admin-express.shp'

INFOS_FOR_REGIONS_DEPTS_COM = "assets/collectivites-outremer.csv"

COMMUNES_MORTES = [
    ("55039", "Beaumont-en-Verdunois", 4735299808),
    ("55050", "Bezonvaux", 1300835620),
    ("55139", "Cumières-le-Mort-Homme", 1708015706),
    ("55189", "Fleury-devant-Douaumont", 915457748),
    ("55239", "Haumont-près-Samogneux", 1300745684),
    ("55307", "Louvemont-Côte-du-Poivre", 1300745706),
]

CHEF_LIEUX = {
    "chef_lieu_de_collectivite_territoriale": """
SELECT
    replace(nom_officiel, 'Collectivité de ', '') AS nom,
    'mairie' AS type,
    code_insee_de_la_commune_siege AS code_insee,
    geometrie
FROM chef_lieu_de_collectivite_territoriale
WHERE code_insee_de_la_collectivite_territoriale IN (977,978)
""",
    "chef_lieu_d_arrondissement_municipal": """
SELECT
    nom_officiel AS nom,
    'mairie' AS type,
    code_insee_de_l_arrondissement_municipal AS code_insee,
    geometrie
FROM chef_lieu_d_arrondissement_municipal
ORDER BY code_insee_de_l_arrondissement_municipal
""",
    "chef_lieu_de_commune": """
SELECT
    nom_officiel AS nom,
    'mairie' AS type,
    code_insee_de_la_commune AS code_insee,
    geometrie
FROM chef_lieu_de_commune
"""
}

def add_arm_reg_columns(code):
    dep = code[0:2]
    dept_to_reg_arm = {"13": "93", "75": "11", "69": "84"}
    return dept_to_reg_arm[dep]


def fix_arrondissements_columns():
    arm_path = os.path.join(DATA_DIR, 'arrondissements-columns-to-change.geojson.gz')
    gdf_arm = gdf_communes_admin_express = gpd.read_file('/vsigzip/' + arm_path)
    # gdf_arm.loc[:, ["statut", "superficie_cadastrale"]] = np.nan
    gdf_arm["code_insee_du_departement"] = gdf_arm['code_insee'].str.slice(0, 2)
    gdf_arm["statut"] = 'arrondissement-municipal'
    gdf_arm['code_insee_de_la_region'] = gdf_arm['code_insee_du_departement'].apply(add_arm_reg_columns)
    gdf_arm = gdf_arm[['nom_officiel', 'nom_officiel_en_majuscules',
               'numero_de_l_arrondissement_municipal', 'code_insee',
               'code_insee_de_la_commune_de_rattach', 'code_postal', 'population',
               'geometry', 'code_insee_du_departement', 'statut',
               'code_insee_de_la_region']]
    uncompress_output = os.path.join(DATA_DIR, 'arrondissements.geojson')
    gdf_arm.to_file(uncompress_output, driver='GeoJSON', encoding='utf-8')
    with open(uncompress_output, 'rb') as orig_file:
        with gzip.open(uncompress_output + '.gz', 'wb') as zipped_file:
            zipped_file.writelines(orig_file)
    Path(uncompress_output).unlink(missing_ok=True)

def merge_communes():
    infos_for_regions_depts_com = pd.read_csv(INFOS_FOR_REGIONS_DEPTS_COM, dtype='string')
    print(f"\n{'='*60}")
    print(f"Load and reformat columns for Admin Express communes")
    print(f"{'='*60}")
    communes_admin_express = os.path.join(DATA_DIR, 'communes-admin-express.geojson.gz')
    communes_not_from_admin_express = os.path.join(SOURCE_DIR, COMMUNES_NOT_IN_ADMIN_EXPRESS)
    collectivites_territoriales_admin_express = os.path.join(DATA_DIR, 'collectivite_territoriale.geojson.gz')
    gdf_communes_admin_express = gpd.read_file('/vsigzip/' + communes_admin_express)
    gdf_communes_admin_express.loc[gdf_communes_admin_express['code_insee_du_departement'] == 'NR', 'code_insee_du_departement'] = '975'
    gdf_communes_admin_express.loc[gdf_communes_admin_express['code_insee_de_la_region'] == 'NR', 'code_insee_de_la_region'] = '975'
    gdf_communes_admin_express = gdf_communes_admin_express[['code_insee', 'nom_officiel', 'nom_officiel_en_majuscules', 'statut', 'code_insee_du_departement', 'code_insee_de_la_region', 'population', 'superficie_cadastrale', 'geometry']]

    print(f"\n{'='*60}")
    print(f"Load and reformat columns for communes from collectivités\nterritoriales in Admin Express")
    print(f"{'='*60}")
    gdf_collectivites_territoriales_admin_express = gpd.read_file('/vsigzip/' + collectivites_territoriales_admin_express)
    gdf_collectivites_territoriales_admin_express_977_978 = gdf_collectivites_territoriales_admin_express[gdf_collectivites_territoriales_admin_express['code_insee'].isin(['977', '978'])]
    gdf_collectivites_territoriales_admin_express_977_978.loc[:, ["code_insee_du_departement", "code_insee_de_la_region", "statut", "population", "superficie_cadastrale"]] = np.nan
    gdf_collectivites_territoriales_admin_express_977_978.loc[gdf_collectivites_territoriales_admin_express_977_978['code_insee'] == '977', 'code_insee'] = '97701'
    gdf_collectivites_territoriales_admin_express_977_978.loc[gdf_collectivites_territoriales_admin_express_977_978['code_insee'] == '978', 'code_insee'] = '97801'
    gdf_collectivites_territoriales_admin_express_977_978 = pd.merge(gdf_collectivites_territoriales_admin_express_977_978, infos_for_regions_depts_com, left_on='code_insee', right_on='code_commune')
    gdf_collectivites_territoriales_admin_express_977_978['code_insee_du_departement'] = gdf_collectivites_territoriales_admin_express_977_978['code_collectivite']
    gdf_collectivites_territoriales_admin_express_977_978['code_insee_de_la_region'] = gdf_collectivites_territoriales_admin_express_977_978['code_collectivite']
    gdf_collectivites_territoriales_admin_express_977_978 = gdf_collectivites_territoriales_admin_express_977_978.rename(columns={"population_y": "population"})
    gdf_collectivites_territoriales_admin_express_977_978['nom_officiel'] = gdf_collectivites_territoriales_admin_express_977_978['nom_officiel'].str.replace('Collectivité de ', '')
    gdf_collectivites_territoriales_admin_express_977_978['nom_officiel_en_majuscules'] = gdf_collectivites_territoriales_admin_express_977_978['nom_officiel_en_majuscules'].str.replace('COLLECTIVITE DE ', '')
    gdf_collectivites_territoriales_admin_express_977_978 = gdf_collectivites_territoriales_admin_express_977_978[['code_insee', 'nom_officiel', 'nom_officiel_en_majuscules', 'statut', 'code_insee_du_departement', 'code_insee_de_la_region', 'population', 'superficie_cadastrale', 'geometry']]

    print(f"\n{'='*60}")
    print(f"Load and reformat columns for communes COM not in\nAdmin Express")
    print(f"{'='*60}")
    gdf_communes_not_from_admin_express = gpd.read_file(communes_not_from_admin_express)
    gdf_communes_not_from_admin_express = gdf_communes_not_from_admin_express.rename(columns={"nom": "nom_officiel"})
    gdf_communes_not_from_admin_express = pd.merge(gdf_communes_not_from_admin_express, infos_for_regions_depts_com, left_on='code_insee', right_on='code_commune')
    gdf_communes_not_from_admin_express.loc[:, ["nom_officiel_en_majuscules", "statut", "code_insee_du_departement", "code_insee_de_la_region", "superficie_cadastrale"]] = np.nan
    gdf_communes_not_from_admin_express['code_insee_du_departement'] = gdf_communes_not_from_admin_express['code_collectivite']
    gdf_communes_not_from_admin_express['code_insee_de_la_region'] = gdf_communes_not_from_admin_express['code_collectivite']
    gdf_communes_not_from_admin_express['nom_officiel_en_majuscules'] = gdf_communes_not_from_admin_express['nom_officiel'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode("utf-8").str.upper()
    gdf_communes_not_from_admin_express = gdf_communes_not_from_admin_express[['code_insee', 'nom_officiel', 'nom_officiel_en_majuscules', 'statut', 'code_insee_du_departement', 'code_insee_de_la_region', 'population', 'superficie_cadastrale', 'geometry']]

    print(f"\n{'='*60}")
    print(f"Concat all communes sources and write to a compressed\ngeojson file")
    print(f"{'='*60}")
    gdf = pd.concat([gdf_communes_admin_express, gdf_communes_not_from_admin_express, gdf_collectivites_territoriales_admin_express_977_978])
    uncompress_output = os.path.join(DATA_DIR, 'communes.geojson')
    gdf.to_file(uncompress_output, driver='GeoJSON', encoding='utf-8')
    with open(uncompress_output, 'rb') as orig_file:
        with gzip.open(uncompress_output + '.gz', 'wb') as zipped_file:
            zipped_file.writelines(orig_file)
    Path(uncompress_output).unlink(missing_ok=True)

def query_openstreetmap_node(node_osm_id):
    r = requests.get(f"https://www.openstreetmap.org/api/0.6/node/{node_osm_id}")
    r.raise_for_status()
    return r.text

def build_communes_mortes():
    features = []

    for insee, nom, osm_id in COMMUNES_MORTES:
        cache = Path(SOURCE_DIR) / f"communes_mortes_{insee}_pour_la_france.geojson"
        if cache.exists():
            feature = json.loads(cache.read_text())
        else:
            
            root = etree.fromstring(query_openstreetmap_node(osm_id).encode())
            node = root.find('node')
            lon, lat = float(node.attrib['lon']), float(node.attrib['lat'])

            feature = {
                "type": "Feature",
                "properties": {
                    "code_insee": insee,
                    "nom": nom,
                    "type": "memorial",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
            }

            cache.write_text(json.dumps(feature))

        features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }

def process_mairies():
    gpkg = Path(SOURCE_DIR) / GPKG_NAME
    features = []

    concatenated = pd.concat([gpd.read_file(f"{gpkg}", sql=sql, engine="pyogrio") for sql in CHEF_LIEUX.values()])
    query_osm = """SELECT nom, 'centre' AS type, code_insee
    FROM "osm-communes-com-without-admin-express"
    """

    gdf_osm = gpd.read_file(f"{SOURCE_DIR}/{COMMUNES_NOT_IN_ADMIN_EXPRESS}", sql=query_osm, engine="pyogrio")
    gdf_osm.geometry = gdf_osm.geometry.representative_point()

    cache = Path(SOURCE_DIR) / "communes_mortes_pour_la_france.osm"
    if cache.exists():
        memorials = json.loads(cache.read_text())
    else:
        memorials = build_communes_mortes()
        cache.write_text(json.dumps(memorials))
    
    gdf_mortes_pour_la_france = gpd.read_file(cache)

    result = {
        "type": "FeatureCollection",
        "features": [],
    }

    for f in features:
        result["features"].append(
            {
                "type": "Feature",
                "properties": {
                    "commune": f["properties"]["code_insee"],
                    "nom": f["properties"]["nom"],
                    "type": f["properties"]["type"],
                },
                "geometry": f["geometry"],
            }
        )
    all_mairies = pd.concat([concatenated, gdf_osm, gdf_mortes_pour_la_france]).rename(columns={"code_insee": "commune"}).sort_values(by=["commune"])
    mairies_output_path = os.path.join(DATA_DIR, "mairies.geojson")
    all_mairies.to_file(mairies_output_path, driver='GeoJSON', encoding='utf-8')
    with open(mairies_output_path, 'rb') as orig_file:
        with gzip.open(mairies_output_path + '.gz', 'wb') as zipped_file:
            zipped_file.writelines(orig_file)
    Path(mairies_output_path).unlink(missing_ok=True)
    # print(all_mairies)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Merge communes sources and create mairies layer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Merge communes sources and create mairies assembled data
        """
    )
    
    args = parser.parse_args()
    
    try:
        success_communes = merge_communes()
        success_mairies = process_mairies()
        success_arm = fix_arrondissements_columns()
        sys.exit(0 if (success_communes and success_mairies and success_arm) else 1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
