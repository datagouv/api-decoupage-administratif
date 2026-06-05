# API Découpage Administratif (reboot) 🗺️

API REST pour accéder aux données géographiques et administratives des communes françaises et entités associées.

Basé sur le **COG INSEE**, les géométries **IGN Admin Express**, **Banatic**, **La Poste** et le référentiel **AOM** (data.gouv.fr).

**Architecture** : SQLite pur (`data/apigeo.db`) — géométries en WKT + GeoJSON pré-calculé, filtres spatiaux via Shapely au runtime (pas d’extension SpatiaLite requise).

## 🚀 Démarrage rapide

### Prérequis

- Python 3.11+
- Dépendances : `pip install -r requirements.txt` (+ `requirements-api.txt` pour l’API)

### Installation complète

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Télécharger les données administratives (COG, Banatic, AOM, intercos…)
python3 1_download_decoupage_administratif_data.py

# 3. Télécharger les géométries IGN
python3 2_download_geometries_ign.py

# 4. Convertir en GeoJSON + agrégations (départements, régions, intercos, AOM)
python3 3_convert_shape_into_geojson.py

# 5. Simplifier les GeoJSON (5m, 10m, 100m, 1000m)
python3 4_simplify_geojson.py

# 6. Charger dans SQLite
python3 5_load_into_spatialite.py

# 7. Lancer l'API
uvicorn app.main:app --reload
```

L'API est accessible sur **http://localhost:8000**

## 📦 Avec Docker

```bash
# Préparer les données (une fois, en local)
python3 1_download_decoupage_administratif_data.py
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py

# Lancer l'API
docker-compose up
```

## 📖 Documentation

- **Swagger UI** : http://localhost:8000/docs
- **ReDoc** : http://localhost:8000/redoc
- **Workflow détaillé** : [WORKFLOW.md](WORKFLOW.md)

## 🔍 Endpoints principaux

### Communes

```bash
GET /communes
GET /communes/{code}
GET /communes_associees_deleguees
GET /communes_associees_deleguees/{code}
```

Filtres : `nom`, `codePostal`, `codeDepartement`, `departement`, `region`, `lat`/`lon`, `fields`, `limit`, `offset`.

### Départements et régions

```bash
GET /departements
GET /departements/{code}
GET /departements/{code}/communes
GET /regions
GET /regions/{code}
GET /regions/{code}/departements
GET /regions/{code}/communes
```

### EPCI et groupements

```bash
GET /epcis                          # CA, CU, CC, MET69, METRO
GET /epcis/{code}
GET /epcis/{code}/communes          # ?fields=competences
GET /groupement_collectivites_territoriales
GET /groupement_collectivites_territoriales/{code}
GET /groupement_collectivites_territoriales/{code}/communes  # ?fields=competences
```

### Statistiques

```bash
GET /stats
GET /health
```

## 🗂️ Structure du projet

```
apigeo2/
├── app/
│   ├── main.py                   # Routes FastAPI
│   ├── database.py               # Connexion SQLite
│   ├── schemas.py                # Schémas Pydantic
│   ├── entities/                 # Logique métier par entité
│   │   ├── communes.py
│   │   ├── departements.py
│   │   ├── regions.py
│   │   ├── intercommunalites.py
│   │   └── epcis.py
│   └── ...
├── data/
│   ├── *.csv                     # Métadonnées COG, intercos, AOM…
│   ├── *.geojson                 # Géométries brutes
│   ├── *_5m.geojson              # Géométries simplifiées (utilisées en base)
│   └── apigeo.db                 # Base SQLite
├── sources/                      # Shapefiles IGN
├── 1_download_decoupage_administratif_data.py
├── 2_download_geometries_ign.py
├── 3_convert_shape_into_geojson.py
├── 4_simplify_geojson.py
├── 5_load_into_spatialite.py
├── competences_mapping.json      # Libellés compétences interco
├── reset_database.py
├── docker-compose.yml
└── requirements.txt
```

## 💾 Base de données SQLite

### Principes

- Fichier unique `data/apigeo.db`, portable et sans serveur
- Géométries stockées en **WKT** (`geometry`) et **GeoJSON** (`geometry_geojson`) pré-calculés à l’import
- Vues SQL pour joindre métadonnées et géométries (`communes`, `departements`, `regions`, `interco`, `aom`)
- Index sur codes, `nom_recherche`, bbox des communes

### Tables principales

| Domaine | Métadonnées | Géométries | Liaisons |
|---------|-------------|------------|----------|
| Communes | `communes_metadata` | `communes_geometries` | — |
| Départements | `departements_metadata` | `departements_geometries` | — |
| Régions | `regions_metadata` | `regions_geometries` | — |
| Intercos | `interco_metadata` | `interco_geometries` | `commune_interco_associations`, `interco_commune` |
| AOM | `aom_metadata` | `aom_geometries` | `aom_commune` |

## 🔧 Scripts utilitaires

```bash
# Supprimer la base et recharger
python3 reset_database.py
python3 5_load_into_spatialite.py

# Migration bbox seule (base existante)
python3 5_load_into_spatialite.py --migrate-bbox
```

### Accès direct à la base

```bash
sqlite3 data/apigeo.db
SELECT COUNT(*) FROM communes;
SELECT siren, nom FROM aom LIMIT 5;
```

## 📊 Sources de données

- **COG INSEE** : [data.gouv.fr](https://www.data.gouv.fr/datasets/code-officiel-geographique-cog/)
- **IGN Admin Express** : [geoservices.ign.fr](https://geoservices.ign.fr/adminexpress)
- **Banatic** : SIREN, intercommunalités, membres
- **La Poste** : codes postaux
- **AOM** : [liste et composition des AOM](https://www.data.gouv.fr/fr/datasets/liste-et-composition-des-autorites-organisatrices-de-la-mobilite-aom/) (fichier ODS annuel — URL à mettre à jour dans le script 1)

Licence Ouverte / Open Licence 2.0.

## 🐛 Dépannage

### Base absente ou incomplète

```bash
ls -lh data/apigeo.db
python3 5_load_into_spatialite.py
```

### Réinitialisation complète

```bash
python3 reset_database.py
python3 1_download_decoupage_administratif_data.py
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py
```

### Géométries manquantes

Vérifier que les scripts 2, 3 et 4 ont bien produit les fichiers `*_5m.geojson` dans `data/`.

## 📚 Documentation complémentaire

- [WORKFLOW.md](WORKFLOW.md) — pipeline pas à pas
- [PERFORMANCE.md](PERFORMANCE.md) — GeoJSON pré-calculé, simplification
- [ENRICHISSEMENT_SIREN.md](ENRICHISSEMENT_SIREN.md)
- [ENRICHISSEMENT_EPCI.md](ENRICHISSEMENT_EPCI.md)
- [DEPARTEMENTS.md](DEPARTEMENTS.md)
- [REGIONS.md](REGIONS.md)

## 📄 Licence

Projet et données sources : Licence Ouverte / Open Licence 2.0.
