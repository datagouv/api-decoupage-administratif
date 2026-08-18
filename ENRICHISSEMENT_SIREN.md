# 🏢 Enrichissement avec les SIREN (Banatic)

## Vue d'ensemble

Les données ont été enrichies avec les **numéros SIREN** provenant de la [Banatic](https://www.banatic.interieur.gouv.fr/) (Base nationale sur l'intercommunalité), disponible sur [data.gouv.fr](https://www.data.gouv.fr/api/1/datasets/r/5d3cfdd0-00de-43fe-a5db-dffeacec6fc7).

Le **SIREN** (Système d'Identification du Répertoire des Entreprises) est un identifiant unique à 9 chiffres attribué aux communes et EPCI.

## 📊 Données enrichies

Le script `1_download_decoupage_administratif_data.py` télécharge **deux sources** :

1. **COG (Code Officiel Géographique)** - INSEE
   - Codes INSEE, noms, types, etc.

2. **Banatic - Correspondance INSEE/SIREN**
   - Mapping Code INSEE → SIREN

### Fichiers générés

Tous les fichiers CSV contiennent maintenant une colonne `Siren` :
- `data/communes.csv` - Communes (TYPECOM=COM)
- `data/arrondissements.csv` - Arrondissements municipaux (TYPECOM=ARM)
- `data/communes-associees-ou-deleguees.csv` - Communes déléguées/associées (TYPECOM=COMD/COMA)

## 🔗 Jointure

Le matching est fait sur :
- **Banatic** : `Code INSEE de la commune`
- **COG** : `COM`

Jointure de type `LEFT JOIN` pour garder toutes les communes, même celles sans SIREN.

## 📍 Disponibilité

⚠️ **Important** : Toutes les communes n'ont pas forcément un SIREN :
- Les **communes** (COM) ont généralement un SIREN
- Les **arrondissements municipaux** (ARM) peuvent ne pas en avoir
- Les **communes déléguées/associées** (COMD/COMA) utilisent souvent le SIREN de la commune parente

## 🗄️ Base de données

La colonne `siren` est maintenant présente dans :

### Table `communes_metadata`
```sql
CREATE TABLE communes_metadata (
  com TEXT PRIMARY KEY,
  typecom TEXT,
  reg TEXT,
  dep TEXT,
  libelle TEXT,
  ...,
  siren TEXT  -- ← Nouvelle colonne
);
```

### Vue `communes`
La vue joignant métadonnées et géométries inclut maintenant :
```sql
SELECT
  m.siren as siren,
  ...
FROM communes_metadata m
LEFT JOIN communes_geometries g ON m.com = g.code
```

## 📡 API

Tous les endpoints retournent maintenant le SIREN :

### GET `/communes/{code}`
```json
{
  "type": "Feature",
  "properties": {
    "code_insee": "75056",
    "nom": "Paris",
    "type_commune": "COM",
    "siren": "217500016",
    ...
  },
  "geometry": {...}
}
```

### GET `/communes`
```json
[
  {
    "code_insee": "75056",
    "nom": "Paris",
    "siren": "217500016",
    ...
  }
]
```

### GET `/communes/search/{nom}`
Même format que `/communes`

## 🔄 Mise à jour

Pour régénérer les données avec SIREN :

```bash
# 1. Télécharger les données enrichies
python3 1_download_decoupage_administratif_data.py

# 2. Recharger dans la base (après étapes 2→4 si les géométries changent)
python3 5_load_into_spatialite.py
```

## 📈 Statistiques

Lors du téléchargement, le script affiche :
```
🔗 Merging COG data with SIREN numbers...
✓ Merge complete
  34,966 / 36,658 entities have SIREN
  1,692 entities without SIREN
```

## 🔍 Utilisation

### Filtrer par SIREN
```bash
# Via SQL direct
sqlite3 data/apigeo.db "SELECT * FROM communes WHERE siren = '217500016'"

# Via l'API
curl "http://localhost:8000/communes/75056" | jq '.properties.siren'
```

### Statistiques
```bash
# Compter les communes avec SIREN
sqlite3 data/apigeo.db "SELECT COUNT(*) FROM communes WHERE siren IS NOT NULL"

# Compter par type
sqlite3 data/apigeo.db "
SELECT
  type_commune,
  COUNT(*) as total,
  SUM(CASE WHEN siren IS NOT NULL THEN 1 ELSE 0 END) as avec_siren
FROM communes
GROUP BY type_commune
"
```

## 📚 Ressources

- [Banatic sur data.gouv.fr](https://www.data.gouv.fr/fr/datasets/base-nationale-sur-lintercommunalite/)
- [Documentation SIREN/SIRET](https://www.insee.fr/fr/information/2015441)
- [API Entreprise - Recherche par SIREN](https://api.gouv.fr/les-api/api-entreprise)

## ⚙️ Détails techniques

### Encodage
Le fichier Banatic utilise un séparateur `;` et peut être encodé en :
- UTF-8
- Latin1 (ISO-8859-1)
- CP1252 (Windows)

Le script essaie automatiquement plusieurs encodages.

### Dédoublonnage
Si plusieurs SIREN existent pour un même code INSEE (cas rare), on garde le premier.

### Performance
- Téléchargement Banatic : ~2-5 secondes
- Jointure pandas : ~500ms pour 36 000 lignes
- Pas d'impact sur les performances de l'API
