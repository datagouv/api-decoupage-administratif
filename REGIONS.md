# 🗺️ Régions - Données et Géométries

## Vue d'ensemble

Les données des **régions françaises** sont maintenant intégrées dans l'API avec leurs géométries calculées automatiquement en fusionnant les contours des départements.

## 📊 Source des données

**Métadonnées** : [Code Officiel Géographique (COG)](https://www.data.gouv.fr/datasets/code-officiel-geographique-cog/) - Insee  
**Fichier** : https://www.data.gouv.fr/api/1/datasets/r/2486b351-5d85-4e1a-8d12-5df082c75104

**Géométries** : Calculées en fusionnant les géométries des départements (`ST_Union`)

## 🗄️ Structure de la base de données

### Table `regions_metadata`
Métadonnées brutes du COG :
- `reg` : Code région (ex: "11", "84", "01")
- `cheflieu` : Code INSEE du chef-lieu (commune préfecture de région)
- `tncc` : Type de nom (article)
- `ncc` : Nom en majuscules
- `nccenr` : Nom enrichi (avec accents)
- `libelle` : Libellé officiel

### Table `regions_geometries`
Géométries calculées :
- `reg` : Code région (clé primaire)
- `nom` : Nom de la région
- `geometry` : Géométrie MULTIPOLYGON (fusion des départements)

### Vue `regions`
Jointure des deux tables :
```sql
CREATE VIEW regions AS
SELECT 
    m.reg as code_region,
    m.libelle as nom,
    m.nccenr as nom_enrichi,
    m.ncc as nom_majuscules,
    m.tncc as type_nom,
    m.cheflieu as code_chef_lieu,
    g.reg as reg_geo,
    g.geometry_geojson as geometry_geojson,
    g.geometry as geometry
FROM regions_metadata m
LEFT JOIN regions_geometries g ON m.reg = g.reg
```

## 🔄 Processus de création des géométries

1. **Script 3** : union des départements par région via `unary_union()` → `regions.geojson`
2. **Script 4** : simplification → `regions_5m.geojson`
3. **Script 5** : import WKT + GeoJSON pré-calculé dans `regions_geometries`

## 📋 Liste des régions

**Régions métropolitaines** (13) :
- `11` - Île-de-France
- `24` - Centre-Val de Loire
- `27` - Bourgogne-Franche-Comté
- `28` - Normandie
- `32` - Hauts-de-France
- `44` - Grand Est
- `52` - Pays de la Loire
- `53` - Bretagne
- `75` - Nouvelle-Aquitaine
- `76` - Occitanie
- `84` - Auvergne-Rhône-Alpes
- `93` - Provence-Alpes-Côte d'Azur
- `94` - Corse

**Régions d'Outre-Mer** (5) :
- `01` - Guadeloupe
- `02` - Martinique
- `03` - Guyane
- `04` - La Réunion
- `06` - Mayotte

**Total** : 18 régions

## 📡 API Endpoints

### GET `/regions`
Liste toutes les régions

**Exemple** :
```bash
curl http://localhost:8000/regions
```

**Réponse** :
```json
[
  {
    "code_region": "11",
    "nom": "Île-de-France",
    "nom_enrichi": "Île-de-France",
    "nom_majuscules": "ILE DE FRANCE",
    "code_chef_lieu": "75056"
  },
  {
    "code_region": "84",
    "nom": "Auvergne-Rhône-Alpes",
    "nom_enrichi": "Auvergne-Rhône-Alpes",
    "nom_majuscules": "AUVERGNE RHONE ALPES",
    "code_chef_lieu": "69123"
  }
]
```

### GET `/regions/{code}/departements`
Liste les départements de la région.

### GET `/regions/{code}/communes`
Liste les communes de la région.

### GET `/regions/{code}`
Récupère une région avec sa géométrie

**Paramètres** :
- `code` (path) : Code région
- `geometry` (query) : Inclure la géométrie (défaut: true)

**Exemple** :
```bash
curl http://localhost:8000/regions/11
curl "http://localhost:8000/regions/84?geometry=true"
```

**Réponse** :
```json
{
  "type": "Feature",
  "properties": {
    "code_region": "11",
    "nom": "Île-de-France",
    "nom_enrichi": "Île-de-France",
    "nom_majuscules": "ILE DE FRANCE",
    "code_chef_lieu": "75056"
  },
  "geometry": {
    "type": "MultiPolygon",
    "coordinates": [[[...]]]
  }
}
```

## 🚀 Installation et utilisation

```bash
python3 1_download_decoupage_administratif_data.py   # regions.csv
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py              # regions.geojson
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py                    # regions_metadata + regions_geometries + vue
```

### 3. Tester l'API

```bash
# Lancer l'API
uvicorn app.main:app --reload

# Dans un autre terminal
curl http://localhost:8000/regions | jq
curl http://localhost:8000/regions/11 | jq '.properties'
```

## 📊 Statistiques

```bash
# Compter les régions
sqlite3 data/apigeo.db "SELECT COUNT(*) FROM regions"
# Résultat : 18 (13 métropole + 5 DROM)

# Régions avec géométries
sqlite3 data/apigeo.db "
SELECT COUNT(*) 
FROM regions 
WHERE geometry IS NOT NULL
"

# Départements par région
sqlite3 data/apigeo.db "
SELECT 
  r.nom as region,
  COUNT(d.dep) as nb_departements
FROM regions_metadata r
JOIN departements_metadata d ON r.reg = d.reg
GROUP BY r.reg, r.nom
ORDER BY nb_departements DESC
"
```

## 🔍 Cas d'usage

### 1. Trouver les départements d'une région

```bash
curl "http://localhost:8000/departements?region=11"
```

### 2. Trouver les communes d'une région

```sql
SELECT c.*
FROM communes c
WHERE c.code_region = '11'
LIMIT 10
```

### 3. Afficher la géométrie d'une région

```python
import requests
import json

response = requests.get("http://localhost:8000/regions/11")
region = response.json()

# Sauvegarder en GeoJSON
with open("ile_de_france.geojson", "w") as f:
    json.dump(region, f)
```

### 4. Superficie et limitrophes

Utiliser le paramètre API `fields=surface` (calcul Shapely) ou un outil SIG. Les fonctions `ST_Area` / `ST_Touches` ne sont pas exposées en SQL dans la base actuelle.

### 6. Nombre de communes par région

```sql
SELECT 
  r.nom as region,
  COUNT(c.code_insee) as nb_communes
FROM regions r
JOIN communes c ON r.code_region = c.code_region
GROUP BY r.code_region, r.nom
ORDER BY nb_communes DESC
```

## 📈 Hiérarchie territoriale complète

L'API expose maintenant la hiérarchie administrative complète de la France :

```
Région
  └── Département
       └── Commune (ou Arrondissement ou Commune déléguée/associée)
```

**Exemple pour Paris** :
```bash
# Région Île-de-France
curl http://localhost:8000/regions/11

# Département de Paris
curl http://localhost:8000/departements/75

# Commune de Paris (avec arrondissements)
curl "http://localhost:8000/communes?departement=75"
```

## ⚙️ Performance

- **Fusion (script 3)** : quelques secondes
- **Taille géométries** : ~200-500 Ko par région (WKT + GeoJSON pré-calculé)
- **API** : lecture directe de `geometry_geojson`

## 🐛 Dépannage

### Géométries manquantes

Si certaines régions n'ont pas de géométrie :

```sql
-- Vérifier les départements sans code région
SELECT COUNT(*) 
FROM departements_metadata 
WHERE reg IS NULL

-- Vérifier le matching
SELECT DISTINCT reg 
FROM departements_metadata 
ORDER BY reg
```

### Géométries manquantes en base

Vérifier `data/regions_5m.geojson` (scripts 3 et 4).

## 📚 Ressources

- [COG - Code Officiel Géographique](https://www.data.gouv.fr/datasets/code-officiel-geographique-cog/)
- [Régions françaises - Wikipédia](https://fr.wikipedia.org/wiki/R%C3%A9gion_fran%C3%A7aise)
- [Réforme territoriale 2016](https://fr.wikipedia.org/wiki/R%C3%A9forme_territoriale_de_2015)

## 🎯 Workflow complet

```bash
python3 1_download_decoupage_administratif_data.py
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py
uvicorn app.main:app --reload

curl http://localhost:8000/regions
curl http://localhost:8000/regions/11/communes?limit=5
```

## 🌍 Visualisation

Les géométries peuvent être visualisées dans :
- [geojson.io](https://geojson.io)
- QGIS
- Leaflet / OpenLayers
- Mapbox

**Exemple avec curl + geojson.io** :
```bash
curl http://localhost:8000/regions/11 > ile_de_france.geojson
# Ouvrir ile_de_france.geojson dans geojson.io
```

## 🆕 Prochaines étapes

Améliorations possibles :
- Cache des géométries simplifiées pour performance
- Endpoint pour les régions limitrophes
- Calcul automatique des superficies
- Ajout des populations régionales (agrégation)
- Export en différents formats (Shapefile, KML, etc.)
- WebSocket pour streaming de grandes géométries

## 📊 Comparaison des niveaux

| Niveau | Nombre | Taille géo (WKT) | Temps fusion |
|--------|--------|------------------|--------------|
| Communes | ~35 000 | 5-50 Ko | - |
| Départements | 101 | 50-200 Ko | ~30s-2min |
| Régions | 18 | 200-500 Ko | ~10-30s |

## ✅ API Complète

L'API expose maintenant **3 niveaux géographiques** avec leurs géométries :

| Endpoint | Entités | Géométrie source |
|----------|---------|------------------|
| `/communes` | ~35 000 | IGN (shapefiles) |
| `/departements` | 101 | Fusion des communes |
| `/regions` | 18 | Fusion des départements |

🎉 **API Géo France complète !**


