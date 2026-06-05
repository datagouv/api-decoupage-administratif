# 🗺️ Départements - Données et Géométries

## Vue d'ensemble

Les données des **départements français** sont maintenant intégrées dans l'API avec leurs géométries calculées automatiquement en fusionnant les contours des communes.

## 📊 Source des données

**Métadonnées** : [Code Officiel Géographique (COG)](https://www.data.gouv.fr/datasets/code-officiel-geographique-cog/) - Insee  
**Fichier** : https://www.data.gouv.fr/api/1/datasets/r/54a8263d-6e2d-48d5-b214-aa17cc13f7a0

**Géométries** : Calculées en fusionnant les géométries des communes (`ST_Union`)

## 🗄️ Structure de la base de données

### Table `departements_metadata`
Métadonnées brutes du COG :
- `dep` : Code département (ex: "75", "2A", "974")
- `reg` : Code région
- `cheflieu` : Code INSEE du chef-lieu
- `tncc` : Type de nom (article)
- `ncc` : Nom en majuscules
- `nccenr` : Nom enrichi (avec accents)
- `libelle` : Libellé officiel

### Table `departements_geometries`
Géométries calculées :
- `dep` : Code département (clé primaire)
- `nom` : Nom du département
- `geometry` : Géométrie MULTIPOLYGON (fusion des communes)

### Vue `departements`
Jointure des deux tables :
```sql
CREATE VIEW departements AS
SELECT 
    m.dep as code_departement,
    m.libelle as nom,
    m.nccenr as nom_enrichi,
    m.ncc as nom_majuscules,
    m.tncc as type_nom,
    m.reg as code_region,
    m.cheflieu as code_chef_lieu,
    g.dep as dep_geo,
    g.geometry_geojson as geometry_geojson,
    g.geometry as geometry
FROM departements_metadata m
LEFT JOIN departements_geometries g ON m.dep = g.dep
```

## 🔄 Processus de création des géométries

1. **Script 3** (`3_convert_shape_into_geojson.py`) : union des communes par département via `unary_union()` (Shapely) → `departements.geojson`
2. **Script 4** (`4_simplify_geojson.py`) : simplification → `departements_5m.geojson`
3. **Script 5** (`5_load_into_spatialite.py`) : import WKT + GeoJSON pré-calculé dans `departements_geometries`

```python
# Extrait de generate_departements_geojson() — script 3
from shapely.ops import unary_union
merged_geom = unary_union(geometries)  # communes du même département
```

## 📡 API Endpoints

### GET `/departements`
Liste tous les départements

**Paramètres** :
- `region` (query, optionnel) : Filtrer par code région

**Exemple** :
```bash
curl http://localhost:8000/departements
curl http://localhost:8000/departements?region=11
```

**Réponse** :
```json
[
  {
    "code_departement": "75",
    "nom": "Paris",
    "nom_enrichi": "Paris",
    "nom_majuscules": "PARIS",
    "code_region": "11",
    "code_chef_lieu": "75056"
  }
]
```

### GET `/departements/{code}/communes`
Liste les communes du département (mêmes filtres que `GET /communes`).

### GET `/departements/{code}`
Récupère un département avec sa géométrie

**Paramètres** :
- `code` (path) : Code département
- `geometry` (query) : Inclure la géométrie (défaut: true)

**Exemple** :
```bash
curl http://localhost:8000/departements/75
curl "http://localhost:8000/departements/2A?geometry=true"
```

**Réponse** :
```json
{
  "type": "Feature",
  "properties": {
    "code_departement": "75",
    "nom": "Paris",
    "nom_enrichi": "Paris",
    "nom_majuscules": "PARIS",
    "code_region": "11",
    "code_chef_lieu": "75056"
  },
  "geometry": {
    "type": "MultiPolygon",
    "coordinates": [[[...]]]
  }
}
```

## 🚀 Installation et utilisation

Les métadonnées départements sont téléchargées par le script 1 ; les géométries sont agrégées au script 3.

```bash
python3 1_download_decoupage_administratif_data.py   # departements.csv
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py              # departements.geojson
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py
```

Le script 5 crée :
- `departements_metadata`, `departements_geometries`
- la vue `departements`
- les index SQL

### 3. Tester l'API

```bash
# Lancer l'API
uvicorn app.main:app --reload

# Dans un autre terminal
curl http://localhost:8000/departements | jq '.[0]'
curl http://localhost:8000/departements/75 | jq '.properties'
```

## 📊 Statistiques

```bash
# Compter les départements
sqlite3 data/apigeo.db "SELECT COUNT(*) FROM departements"
# Résultat : 101 (96 métropole + 5 DROM)

# Départements avec géométries
sqlite3 data/apigeo.db "
SELECT COUNT(*) 
FROM departements 
WHERE geometry IS NOT NULL
"

# Départements par région
sqlite3 data/apigeo.db "
SELECT 
  code_region,
  COUNT(*) as nb_departements
FROM departements
GROUP BY code_region
ORDER BY nb_departements DESC
"
```

## 🔍 Cas d'usage

### 1. Trouver les communes d'un département

```bash
curl "http://localhost:8000/communes?departement=75&limit=100"
```

### 2. Afficher la géométrie d'un département

```python
import requests
import json

response = requests.get("http://localhost:8000/departements/75")
dept = response.json()

# Sauvegarder en GeoJSON
with open("paris_dept.geojson", "w") as f:
    json.dump(dept, f)
```

### 3. Calculer la superficie d'un département

```sql
SELECT 
  code_departement,
  nom,
  ST_Area(geometry, 1) / 1000000 as superficie_km2
FROM departements
WHERE code_departement = '75'
```

### 4. Départements limitrophes

> Les fonctions spatiales SQL (`ST_Touches`, etc.) ne sont pas disponibles dans la base SQLite actuelle. Utiliser Shapely côté application ou un outil SIG (QGIS) pour ce type d’analyse.

## ⚙️ Performance

- **Fusion (script 3)** : quelques secondes à ~1 minute
- **Taille géométries** : ~50-200 Ko par département (WKT + GeoJSON pré-calculé)
- **API** : lecture directe de `geometry_geojson` (pas de conversion à la volée)

## 🐛 Dépannage

### Géométries manquantes

Si certains départements n'ont pas de géométrie :

```sql
-- Vérifier les communes sans code département
SELECT COUNT(*) 
FROM communes_geometries 
WHERE insee_dep IS NULL

-- Vérifier le matching
SELECT DISTINCT insee_dep 
FROM communes_geometries 
ORDER BY insee_dep
```

### Géométries manquantes en base

Vérifier la présence de `data/departements_5m.geojson` (scripts 3 et 4).

## 📚 Ressources

- [COG - Code Officiel Géographique](https://www.data.gouv.fr/datasets/code-officiel-geographique-cog/)
- [Shapely - unary_union](https://shapely.readthedocs.io/en/stable/manual.html#shapely.ops.unary_union)
- [WORKFLOW.md](WORKFLOW.md)

## 🎯 Workflow complet

```bash
python3 1_download_decoupage_administratif_data.py
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py
uvicorn app.main:app --reload

curl http://localhost:8000/departements
curl http://localhost:8000/departements/75
curl "http://localhost:8000/departements/75/communes?limit=5"
```


