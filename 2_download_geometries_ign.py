#!/usr/bin/env python3
"""
Script pour télécharger et préparer les sources de données administratives.
"""
import sys
import tempfile
from pathlib import Path
import geopandas as gpd
import requests
import py7zr
import zipfile


# Configuration des sources
SOURCES_PATH = Path(__file__).parent / "sources"

ADMIN_EXPRESS_BASE_URL = "https://data.geopf.fr/telechargement/download/ADMIN-EXPRESS/ADMIN-EXPRESS_4-0__GPKG_WGS84G_FRA_2026-01-19/"
ADMIN_EXPRESS_FILE = "ADMIN-EXPRESS_4-0__GPKG_WGS84G_FRA_2026-01-19.7z"

OSM_COMMUNES_COM_BASE_URL = "https://contours-administratifs.s3.rbx.io.cloud.ovh.net/2022/shp/"
OSM_COMMUNES_COM_FILE = "communes-com-20220101-shp.zip"


def get_source_file_path(file_name: str) -> Path:
    """Retourne le chemin complet d'un fichier source."""
    return SOURCES_PATH / file_name


def download_source_file(url: str, file_name: str) -> None:
    """
    Télécharge un fichier source si celui-ci n'existe pas déjà.
    
    Args:
        url: URL complète du fichier à télécharger
        file_name: Nom du fichier de destination
    """
    file_path = get_source_file_path(file_name)
    
    if file_path.exists():
        print(f"{file_name} already exists. Skip download.")
        return
    
    print(f"Downloading {file_name}…")
    
    try:
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        
        # Téléchargement avec barre de progression
        total_size = int(response.headers.get('content-length', 0))
        
        with open(file_path, 'wb') as f:
            if total_size == 0:
                f.write(response.content)
            else:
                downloaded = 0
                chunk_size = 8192
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = (downloaded * 100) // total_size
                        print(f"\rProgress: {percent}%", end='', flush=True)
                print()  # Nouvelle ligne après la progression
        
        print(f"✓ {file_name} downloaded successfully")
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error downloading {file_name}: {e}")
        if file_path.exists():
            file_path.unlink()
        raise


def decompress_admin_express_files() -> None:
    """
    Décompresse l'archive ADMIN EXPRESS en extrayant uniquement
    les fichiers relatifs aux communes, communes associées/déléguées
    et arrondissements municipaux.
    """
    # Vérifier si les fichiers sont déjà extraits
    if (SOURCES_PATH / "COMMUNE.shp").exists():
        print("ADMIN EXPRESS files already extracted. Skip decompression.")
        return
    
    print("Decompressing ADMIN EXPRESS archive…")
    
    archive_path = get_source_file_path(ADMIN_EXPRESS_FILE)

    # Patterns des fichiers à extraire
    patterns = {
        'commune': {'cleabs': 'ID', 'nom_officiel': 'NOM', 'nom_officiel_en_majuscules': 'NOM_M', 'code_insee': 'INSEE_COM', 'statut': 'STATUT', 'population': 'POPULATION', 'code_insee_du_canton': 'INSEE_CAN', 'code_insee_de_l_arrondissement': 'INSEE_ARR', 'code_insee_du_departement': 'INSEE_DEP', 'code_insee_de_la_region': 'INSEE_REG', 'codes_siren_des_epci': 'SIREN_EPCI'},
        'commune_associee_ou_deleguee': {'cleabs':'ID', 'nom_officiel':'NOM', 'nom_officiel_en_majuscules':'NOM_M', 'code_insee':'INSEE_CAD', 'code_insee_de_la_commune_de_rattach':'INSEE_COM', 'nature':'NATURE', 'population':'POPULATION'},
        'arrondissement_municipal': {'cleabs': 'ID', 'nom_officiel': 'NOM', 'nom_officiel_en_majuscules': 'NOM_M', 'code_insee': 'INSEE_ARM', 'code_insee_de_la_commune_de_rattach': 'INSEE_COM', 'population': 'POPULATION'}
    }
    
    try:
        with py7zr.SevenZipFile(archive_path, mode='r') as archive:
            all_files = archive.getnames()
            
            # Filtrer les fichiers à extraire
            files_to_extract = []
            for file_name in all_files:
                # Vérifier si le nom de fichier (sans le chemin) correspond aux patterns
                base_name = Path(file_name).name
                if '.gpkg' in base_name:
                    files_to_extract.append(file_name)
            
            if len(files_to_extract) > 0:
                print(f"Extracting {len(files_to_extract)} files…")
                # Extraire dans un dossier temporaire
                with tempfile.TemporaryDirectory() as temp_dir:
                    archive.extract(targets=files_to_extract, path=temp_dir)
                    list_layers = gpd.list_layers(Path(temp_dir) / files_to_extract[0])['name']
                    layers_gpkg = list_layers[list_layers.isin(patterns.keys())]
                    for layer in layers_gpkg.to_list():
                        gdf = gpd.read_file(Path(temp_dir) / files_to_extract[0], layer=layer).rename(columns=patterns[layer])
                        file_name_dest = layer.upper() + '.shp'
                        dest_file = SOURCES_PATH / file_name_dest
                        gdf.to_file(dest_file)
                
                print("✓ ADMIN EXPRESS archive decompressed successfully")
            else:
                print("✗ No matching files found in archive")
                
    except py7zr.exceptions.Bad7zFile as e:
        print(f"✗ Error decompressing ADMIN EXPRESS archive: {e}")
        raise
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        raise


def decompress_osm_communes_com_files() -> None:
    """
    Décompresse l'archive OSM communes-com et renomme les fichiers
    en osm-communes-com.
    """
    # Vérifier si les fichiers sont déjà extraits
    if (SOURCES_PATH / "osm-communes-com.shp").exists():
        print("OSM communes-com files already extracted. Skip decompression.")
        return
    
    print("Decompressing OSM communes-com archive…")
    
    archive_path = get_source_file_path(OSM_COMMUNES_COM_FILE)
    
    try:
        with zipfile.ZipFile(archive_path, 'r') as zip_file:
            # Lister tous les fichiers qui commencent par 'communes-com'
            files_to_extract = [
                name for name in zip_file.namelist()
                if name.startswith('communes-com')
            ]
            
            if not files_to_extract:
                print("✗ No communes-com files found in archive")
                return
            
            print(f"Extracting and renaming {len(files_to_extract)} files…")
            
            for file_name in files_to_extract:
                # Extraire le fichier
                file_data = zip_file.read(file_name)
                
                # Construire le nouveau nom avec l'extension du fichier original
                extension = Path(file_name).suffix
                new_file_name = f"osm-communes-com{extension}"
                new_file_path = SOURCES_PATH / new_file_name
                
                # Écrire le fichier avec le nouveau nom
                with open(new_file_path, 'wb') as f:
                    f.write(file_data)
            
            print("✓ OSM communes-com archive decompressed successfully")
            
    except zipfile.BadZipFile as e:
        print(f"✗ Error decompressing OSM communes-com archive: {e}")
        raise
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        raise


def main() -> int:
    """
    Point d'entrée principal du script.
    
    Returns:
        Code de sortie (0 si succès, 1 si erreur)
    """
    try:
        # Créer le répertoire sources s'il n'existe pas
        SOURCES_PATH.mkdir(parents=True, exist_ok=True)
        print(f"Using sources directory: {SOURCES_PATH}")
        
        # Télécharger et décompresser ADMIN EXPRESS
        download_source_file(
            ADMIN_EXPRESS_BASE_URL + ADMIN_EXPRESS_FILE,
            ADMIN_EXPRESS_FILE
        )
        decompress_admin_express_files()
        
        # Télécharger et décompresser OSM communes-com
        download_source_file(
            OSM_COMMUNES_COM_BASE_URL + OSM_COMMUNES_COM_FILE,
            OSM_COMMUNES_COM_FILE
        )
        decompress_osm_communes_com_files()
        
        print("\n✓ All sources prepared successfully!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

