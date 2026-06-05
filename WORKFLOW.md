# 🔄 Workflow — Installation et utilisation

## 📋 Pipeline complet (5 étapes + API)

```bash
python3 1_download_decoupage_administratif_data.py   # ① Données administratives
python3 2_download_geometries_ign.py               # ② Shapefiles IGN
python3 3_convert_shape_into_geojson.py            # ③ GeoJSON + agrégations
python3 4_simplify_geojson.py                      # ④ Simplification
python3 5_load_into_spatialite.py                  # ⑤ Import SQLite
uvicorn app.main:app --reload                      # ⑥ API
```

---

### Étape 1 : `1_download_decoupage_administratif_data.py`

Télécharge et prépare toutes les données tabulaires.

**Produit notamment :**
- `data/communes.csv`, `arrondissements.csv`, `communes-associees-ou-deleguees.csv`
- `data/departements.csv`, `regions.csv`
- `data/siren_insee_mapping.csv`
- `data/intercos.csv`, `interco_members.csv`, `interco_enriched.csv`
- `data/aom.csv`, `aom_commune.csv`, `base-rt-aom.ods`
- `data/mairies.geojson.gz`

**Enrichissements intégrés :**
- SIREN communes (Banatic)
- Intercommunalité principale par commune (Banatic)
- Codes postaux (La Poste + `assets/codes-postaux-missing.json`)
- Liste et membres des intercommunalités (résolution récursive des communes)
- AOM : autorités organisatrices de mobilité + composition communale

> **AOM** : l’URL du fichier ODS change chaque année — constante `AOM_SOURCE_URL` en tête du script 1.

---

### Étape 2 : `2_download_geometries_ign.py`

- Télécharge ADMIN-EXPRESS-COG (IGN)
- Extrait les shapefiles dans `sources/`

---

### Étape 3 : `3_convert_shape_into_geojson.py`

- Convertit les shapefiles → GeoJSON (`communes`, `arrondissements`, communes déléguées/associées)
- **Agrège** les géométries par union des membres :
  - `departements.geojson` (communes)
  - `regions.geojson` (départements)
  - `intercommunalites.geojson` (+ variantes par `nature_juridique`)
  - `aom.geojson` (communes membres via `aom_commune.csv`)

---

### Étape 4 : `4_simplify_geojson.py`

Produit des variantes simplifiées à 5m, 10m, 100m et 1000m :

- `communes_5m.geojson` (utilisé en base pour les communes)
- `departements_5m.geojson`, `regions_5m.geojson`
- `intercommunalites_5m.geojson`
- `aom_5m.geojson`

---

### Étape 5 : `5_load_into_spatialite.py`

Charge tout dans `data/apigeo.db` (SQLite, **sans SpatiaLite**) :

- Métadonnées + géométries communes (table unifiée COM/ARM/COMD/COMA)
- Départements, régions, intercommunalités, **AOM**
- Associations `commune_interco_associations`, compétences `interco_commune`
- Points mairie (`communes_mairies`)
- GeoJSON pré-calculé dans les tables `*_geometries`
- Vues : `communes`, `departements`, `regions`, `interco`, `aom`
- Index (codes, `nom_recherche`, bbox)

```bash
# Migration bbox uniquement (sans rechargement complet)
python3 5_load_into_spatialite.py --migrate-bbox
```

---

### Étape 6 : API

```bash
uvicorn app.main:app --reload
# http://localhost:8000/docs
```

---

## 🚀 Installation from scratch

```bash
git clone <repo>
cd apigeo2
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-api.txt

python3 1_download_decoupage_administratif_data.py
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py
uvicorn app.main:app --reload
```

## 📂 Scripts du dépôt

| Script | Rôle |
|--------|------|
| `1_download_decoupage_administratif_data.py` | COG, Banatic, La Poste, intercos, AOM, mairies |
| `2_download_geometries_ign.py` | Shapefiles IGN |
| `3_convert_shape_into_geojson.py` | Conversion + unions géométriques |
| `4_simplify_geojson.py` | Simplification multi-précision |
| `5_load_into_spatialite.py` | Import SQLite + vues |
| `reset_database.py` | Supprime `apigeo.db` |

### Scripts retirés (fonctionnalités absorbées)

- ~~`1_download_cog_communes.py`~~ / ~~`1_download_aom.py`~~ → `1_download_decoupage_administratif_data.py`
- ~~`5_download_codes_postaux.py`~~ → script 1
- ~~`5_download_interco.py`~~ → script 1
- ~~`6_download_departements.py`~~ → script 1
- ~~`7_download_regions.py`~~ → script 1
- ~~`8_optimize_geojson.py`~~ → script 5 (GeoJSON pré-calculé à l’import)

## 🔄 Mise à jour des données

```bash
python3 reset_database.py
python3 1_download_decoupage_administratif_data.py
python3 2_download_geometries_ign.py
python3 3_convert_shape_into_geojson.py
python3 4_simplify_geojson.py
python3 5_load_into_spatialite.py
```

Pour l’AOM seulement (nouveau millésime RT) : mettre à jour `AOM_SOURCE_URL` puis relancer le script 1 et les étapes 3→5.

## 📊 Temps d'exécution estimés

| Étape | Temps | Description |
|-------|-------|-------------|
| 1 | 3–10 min | COG + Banatic + intercos + AOM |
| 2 | 5–10 min | Archive IGN (~700 Mo) |
| 3 | 2–5 min | Conversion + unions (intercos, AOM…) |
| 4 | 5–15 min | Simplification de tous les GeoJSON |
| 5 | 5–20 min | Import SQLite |
| **Total** | **~20–60 min** | Selon machine et cache |

## 🎯 Endpoints API

### Communes
- `GET /communes`, `GET /communes/{code}`
- `GET /communes_associees_deleguees`, `GET /communes_associees_deleguees/{code}`

### Départements / Régions
- `GET /departements`, `GET /departements/{code}`, `GET /departements/{code}/communes`
- `GET /regions`, `GET /regions/{code}`, `GET /regions/{code}/departements`, `GET /regions/{code}/communes`

### EPCI (`/epcis`)
- Filtre nature : CA, CU, CC, MET69, METRO
- `GET /epcis/{code}/communes` — `?fields=competences` (table `interco_commune`)

### Groupements (`/groupement_collectivites_territoriales`)
- Tous types d’intercommunalités (CC, SIVOM, etc.) — `?type=`
- `GET /groupement_collectivites_territoriales/{code}/communes` — `?fields=competences`

### Divers
- `GET /stats`, `GET /health`

Paramètre `fields` courant : `centre`, `contour`, `bbox`, `surface`, `population`, `membres_siren`, etc.

## 📈 Performance API

- GeoJSON pré-calculé à l’import (pas de conversion WKT à la volée)
- Géométries simplifiées (5m communes, 5m/10m agrégats)
- Index SQL sur les clés de filtrage

Temps de réponse typiques : 10–200 ms selon l’entité et les champs demandés.

## 📚 Documentation

- [README.md](README.md)
- [PERFORMANCE.md](PERFORMANCE.md)
- [ENRICHISSEMENT_SIREN.md](ENRICHISSEMENT_SIREN.md)
- [ENRICHISSEMENT_EPCI.md](ENRICHISSEMENT_EPCI.md)
- [DEPARTEMENTS.md](DEPARTEMENTS.md)
- [REGIONS.md](REGIONS.md)
- `competences_mapping.json` — libellés des compétences interco

## 🆘 Dépannage

1. **Base corrompue** : `python3 reset_database.py` puis pipeline complet
2. **Géométries manquantes** : vérifier scripts 2–4 et présence des `*_5m.geojson`
3. **AOM vide** : vérifier `data/aom.csv` et `AOM_SOURCE_URL` (millésime annuel)
4. **Import errors** : `pip install -r requirements.txt` (inclut `odfpy` pour l’AOM)
