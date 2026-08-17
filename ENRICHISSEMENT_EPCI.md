# 🏛️ Enrichissement avec les EPCI (Établissements Publics de Coopération Intercommunale)

## Vue d'ensemble

Les données sont maintenant enrichies avec les **informations sur les EPCI** (Établissements Publics de Coopération Intercommunale) provenant de la [Banatic](https://www.banatic.interieur.gouv.fr/), disponible sur [data.gouv.fr](https://www.data.gouv.fr/api/1/datasets/r/6e05c448-62cc-4470-aa0f-4f31adea0bc4).

Un **EPCI** est un regroupement de communes qui s'associent pour exercer certaines compétences en commun (déchets, transports, développement économique, etc.).

## 📊 Données enrichies

Le script `1_download_decoupage_administratif_data.py` télécharge notamment **trois sources Banatic/COG** :

1. **COG (Code Officiel Géographique)** - INSEE
   - Codes INSEE, noms, types, etc.

2. **Banatic - Correspondance INSEE/SIREN**
   - Mapping Code INSEE → SIREN de la commune

3. **Banatic - Composition des EPCI**
   - Mapping SIREN commune → SIREN EPCI + Nom EPCI

### Nouvelles colonnes ajoutées

- **`siren_epci`** : SIREN de l'EPCI auquel la commune appartient
- **`nom_epci`** : Nom complet de l'EPCI (ex: "CC Rives de l'Ain - Pays du Cerdon")

## 🔗 Jointures

Le script effectue **deux jointures successives** :

### Étape 1 : COG → SIREN commune
```
COG.COM (Code INSEE) → Banatic_SIREN.Siren
```

### Étape 2 : SIREN commune → EPCI
```
Banatic_SIREN.Siren → Banatic_EPCI.siren_membre
                   → Banatic_EPCI.siren (SIREN EPCI)
                   → Banatic_EPCI.raison_sociale (Nom EPCI)
```

## 📍 Types d'EPCI

Les principaux types d'EPCI :

- **CC** : Communauté de Communes
- **CA** : Communauté d'Agglomération
- **CU** : Communauté Urbaine
- **MET** : Métropole
- **METRO** : Métropole de Lyon

## 📂 Fichiers générés

Tous les fichiers CSV contiennent maintenant les colonnes EPCI :
- `data/communes.csv`
- `data/arrondissements.csv`
- `data/communes-associees-ou-deleguees.csv`

Colonnes ajoutées :
- `Siren` (SIREN de la commune)
- `siren_epci` (SIREN de l'EPCI)
- `nom_epci` (Nom de l'EPCI)

## 🗄️ Base de données

### Table `communes_metadata`
```sql
CREATE TABLE communes_metadata (
  com TEXT PRIMARY KEY,
  libelle TEXT,
  ...,
  siren TEXT,           -- ← SIREN de la commune
  siren_epci TEXT,      -- ← SIREN de l'EPCI
  nom_epci TEXT         -- ← Nom de l'EPCI
);
```

### Vue `communes`
```sql
SELECT
  m.siren as siren,
  m.siren_epci as siren_epci,
  m.nom_epci as nom_epci,
  ...
FROM communes_metadata m
LEFT JOIN communes_geometries g ON m.com = g.code
```

## 📡 API

Tous les endpoints retournent maintenant les infos EPCI :

### GET `/communes/{code}`
```json
{
  "type": "Feature",
  "properties": {
    "code_insee": "01304",
    "nom": "Pont-d'Ain",
    "siren": "210103040",
    "siren_epci": "200029999",
    "nom_epci": "CC Rives de l'Ain - Pays du Cerdon",
    ...
  },
  "geometry": {...}
}
```

### GET `/communes`
```json
[
  {
    "code_insee": "01304",
    "nom": "Pont-d'Ain",
    "siren": "210103040",
    "siren_epci": "200029999",
    "nom_epci": "CC Rives de l'Ain - Pays du Cerdon",
    ...
  }
]
```

## 🔄 Mise à jour

Pour régénérer les données avec les informations EPCI :

```bash
# 1. Télécharger les données enrichies (SIREN + EPCI)
python3 1_download_decoupage_administratif_data.py

# Sortie attendue :
# ============================================================
# DOWNLOADING AND ENRICHING COG DATA
# ============================================================
#
# 📥 Downloading COG data from data.gouv.fr...
# ✓ Total rows loaded: 36,658
#
# 📥 Downloading Banatic SIREN data...
# ✓ 34,966 unique SIREN mappings (INSEE → SIREN)
#
# 📥 Downloading Banatic EPCI data...
# ✓ 34,500 unique EPCI mappings (SIREN commune → SIREN EPCI)
#
# 🔗 Step 1/2: Merging COG data with SIREN numbers...
# ✓ 34,966 / 36,658 entities have SIREN
#
# 🔗 Step 2/2: Merging with EPCI data...
# ✓ 33,800 / 36,658 entities have EPCI

# 2. Recharger dans la base
python3 5_load_into_spatialite.py
```

## 📈 Statistiques

### Couverture

- **~95%** des communes ont un SIREN
- **~92%** des communes avec SIREN ont un EPCI
- Les communes sans EPCI sont généralement :
  - Des arrondissements municipaux
  - Des communes déléguées/associées
  - Des communes nouvelles en transition
  - Paris, Lyon, Marseille (statuts particuliers)

### Répartition

```bash
sqlite3 data/apigeo.db "
SELECT
  type_commune,
  COUNT(*) as total,
  SUM(CASE WHEN siren_epci IS NOT NULL THEN 1 ELSE 0 END) as avec_epci,
  ROUND(100.0 * SUM(CASE WHEN siren_epci IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as pourcentage
FROM communes
GROUP BY type_commune
"
```

## 🔍 Cas d'usage

### 1. Trouver toutes les communes d'un EPCI

```bash
# API
curl "http://localhost:8000/communes?limit=1000" | jq '.[] | select(.siren_epci == "200029999")'

# SQL
sqlite3 data/apigeo.db "
SELECT code_insee, nom, siren
FROM communes
WHERE siren_epci = '200029999'
ORDER BY nom
"
```

### 2. Compter les communes par EPCI

```bash
sqlite3 data/apigeo.db "
SELECT
  nom_epci,
  siren_epci,
  COUNT(*) as nb_communes
FROM communes
WHERE siren_epci IS NOT NULL AND type_commune = 'COM'
GROUP BY siren_epci, nom_epci
ORDER BY nb_communes DESC
LIMIT 10
"
```

### 3. Chercher un EPCI par nom

```bash
# API
curl "http://localhost:8000/communes/search/Pont-d%27Ain" | jq '.[0].nom_epci'

# SQL
sqlite3 data/apigeo.db "
SELECT DISTINCT nom_epci, siren_epci, COUNT(*) as nb_communes
FROM communes
WHERE nom_epci LIKE '%Cerdon%'
GROUP BY nom_epci, siren_epci
"
```

### 4. Communes sans EPCI

```bash
sqlite3 data/apigeo.db "
SELECT code_insee, nom, type_commune, siren
FROM communes
WHERE siren IS NOT NULL AND siren_epci IS NULL
ORDER BY type_commune, nom
LIMIT 20
"
```

## 📚 Ressources

- [Banatic - Base nationale sur l'intercommunalité](https://www.data.gouv.fr/fr/datasets/base-nationale-sur-lintercommunalite/)
- [Composition des EPCI 2025](https://www.data.gouv.fr/api/1/datasets/r/6e05c448-62cc-4470-aa0f-4f31adea0bc4)
- [Carte des EPCI](https://www.banatic.interieur.gouv.fr/V5/recherche-de-groupements/fiche-raison-sociale.php)

## ⚙️ Détails techniques

### Encodage
Le fichier Banatic EPCI utilise :
- Séparateur : `;`
- Encodage : Latin1 ou UTF-8 (détecté automatiquement)

### Dédoublonnage
Si une commune apparaît dans plusieurs EPCI (très rare), on garde le premier.

### NULL vs vide
- `siren_epci = NULL` : La commune n'a pas d'EPCI (ou pas de SIREN)
- `nom_epci = NULL` : Idem

### Performance
- Téléchargement Banatic EPCI : ~5-10 secondes (fichier ~4 MB)
- Jointure pandas : ~1 seconde
- Index créé sur `siren_epci` pour les requêtes rapides

## 📡 Endpoints intercommunalités dédiés

En plus des champs `siren_interco` / `nom_interco` sur les communes, l’API expose :

### EPCI (`/epcis`)

Filtre sur les natures EPCI : CA, CU, CC, MET69, METRO.

```bash
GET /epcis
GET /epcis/{code}
GET /epcis/{code}/communes?fields=competences
```

### Groupements (`/groupement_collectivites_territoriales`)

Tous les types d’intercommunalités Banatic (CC, SIVOM, METRO, etc.).

```bash
GET /groupement_collectivites_territoriales?type=CC
GET /groupement_collectivites_territoriales/{code}
GET /groupement_collectivites_territoriales/{code}/communes?fields=competences
```

Le paramètre `fields=competences` renvoie les compétences exercées par le groupement pour chaque commune (table `interco_commune`). Les libellés lisibles sont dans `competences_mapping.json`.
