#!/usr/bin/env python3
"""
Script pour télécharger et préparer les sources de données administratives.
"""
import sys
import shutil
import tempfile
from pathlib import Path
import requests
import py7zr
import zipfile
from typing import Optional


# Configuration des sources
SOURCES_PATH = Path(__file__).parent / "sources"

ADMIN_EXPRESS_BASE_URL = "https://data.geopf.fr/telechargement/download/ADMIN-EXPRESS-COG/ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2025-04-02/"
ADMIN_EXPRESS_FILE = "ADMIN-EXPRESS-COG_3-2__SHP_WGS84G_FRA_2025-04-02.7z"

OSM_COMMUNES_COM_BASE_URL = "http://etalab-datasets.geo.data.gouv.fr/contours-administratifs/2022/shp/"
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
    patterns = [
        'COMMUNE.',
        'COMMUNE_ASSOCIEE_OU_DELEGUEE.',
        'ARRONDISSEMENT_MUNICIPAL.'
    ]
    
    try:
        with py7zr.SevenZipFile(archive_path, mode='r') as archive:
            all_files = archive.getnames()
            
            # Filtrer les fichiers à extraire
            files_to_extract = []
            for file_name in all_files:
                # Vérifier si le nom de fichier (sans le chemin) correspond aux patterns
                base_name = Path(file_name).name
                if any(pattern in base_name for pattern in patterns):
                    files_to_extract.append(file_name)
            
            if files_to_extract:
                print(f"Extracting {len(files_to_extract)} files…")
                # Extraire dans un dossier temporaire
                with tempfile.TemporaryDirectory() as temp_dir:
                    archive.extract(targets=files_to_extract, path=temp_dir)
                    
                    # Déplacer les fichiers extraits vers SOURCES_PATH en "aplatissant" la structure
                    temp_path = Path(temp_dir)
                    for extracted_file in files_to_extract:
                        source_file = temp_path / extracted_file
                        if source_file.exists():
                            # Prendre uniquement le nom du fichier, pas le chemin complet
                            dest_file = SOURCES_PATH / source_file.name
                            # Copier le fichier
                            shutil.copy2(source_file, dest_file)
                            print(f"  → {source_file.name}")
                
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

