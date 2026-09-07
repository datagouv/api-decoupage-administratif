"""
API Géo 2 - FastAPI main application
API pour accéder aux données des communes françaises
"""

import json
from typing import Any, List, Literal, Optional, Union

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pyproj import Geod
from shapely.geometry import Point, shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.entities.aom import (
    AOM_LIST_PARAMS,
    get_aom_commune_codes,
    get_aom_entity_by_code,
    list_aom_entities,
)
from app.entities.communes import (
    ASSOCIEE_PARENT_ENRICH_FIELDS,
    ASSOCIEE_PARENT_NESTED_FIELDS,
    COMMUNES_ASSOCIEES_CONFIG,
    COMMUNES_CONFIG,
    CommunesEndpointConfig,
    build_commune_properties,
    list_commune_entities,
    resolve_commune_field_lists,
)
from app.entities.departements import (
    departement_exists,
    get_departement_entity_by_code,
    list_departement_entities,
)
from app.entities.epcis import (
    EPCI_LIST_PARAMS,
    get_epci_commune_codes,
    get_epci_entity_by_code,
    list_epci_entities,
)
from app.entities.intercommunalites import (
    INTERCOMMUNALITE_LIST_PARAMS,
    get_groupement_commune_codes,
    get_intercommunalite_entity_by_code,
    list_intercommunalite_entities,
)
from app.entities.regions import (
    get_region_entity_by_code,
    list_region_entities,
    region_exists,
)
from app.schemas import (
    AomGeoJSONResponse,
    AomResponseSchema,
    CommuneGeoJSONResponse,
    CommuneResponseSchema,
    DepartementGeoJSONResponse,
    DepartementResponseSchema,
    EpciGeoJSONResponse,
    EpciResponseSchema,
    ErrorResponse,
    IntercommunaliteGeoJSONResponse,
    IntercommunaliteResponseSchema,
    RegionGeoJSONResponse,
    RegionResponseSchema,
)

_GEOD = Geod(ellps="WGS84")


# Helper function to parse geometry
def parse_geometry(geom_str):
    """
    Parse geometry from GeoJSON string.
    Returns a GeoJSON geometry dict or None.
    """
    if not geom_str:
        return None

    try:
        return json.loads(geom_str)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def compute_surface_hectares(geom_shape) -> Optional[float]:
    """Surface en hectares (aligné api-geo: aire géodésique / 10000)."""
    if geom_shape is None or geom_shape.is_empty:
        return None
    area_m2, _ = _GEOD.geometry_area_perimeter(geom_shape)
    return round(abs(area_m2) / 10000, 2)


def commune_zone(code_insee: str) -> str:
    """Zone administrative : drom (97/98) ou metro."""
    if code_insee.startswith("97") or code_insee.startswith("98"):
        return "drom"
    return "metro"


def resolve_lat_lon_point(
    lat: Optional[float],
    lon: Optional[float],
) -> Optional[tuple[float, float]]:
    """
    Retourne (lon, lat) si les deux coordonnées sont valides.
    Si un seul paramètre est renseigné, retourne None (filtre ignoré).
    """
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat_f <= 90 and -180 <= lon_f <= 180):
        return None
    return lon_f, lat_f


def geometry_shape_from_column(geom_str: Optional[str]):
    """Géométrie Shapely pour tests de distance / appartenance."""
    geometry = parse_geometry(geom_str)
    if not geometry:
        return None
    try:
        return shape(geometry)
    except Exception:
        return None


def pick_nearest_commune_row(
    rows: list,
    list_properties: List[str],
    lon: float,
    lat: float,
):
    """Parmi les lignes candidates, retourne celle dont le contour est le plus proche du point."""
    if not rows:
        return None
    if "geometry_geojson" not in list_properties:
        return rows[0]

    geom_idx = list_properties.index("geometry_geojson")
    pt = Point(lon, lat)
    best_row = None
    best_dist = float("inf")
    best_area = float("inf")

    for row in rows:
        geom_shape = geometry_shape_from_column(row[geom_idx])
        if geom_shape is None or geom_shape.is_empty:
            continue
        if geom_shape.covers(pt):
            dist = 0.0
        else:
            dist = geom_shape.distance(pt)
        area = geom_shape.area
        if dist < best_dist or (dist == best_dist and area < best_area):
            best_dist = dist
            best_area = area
            best_row = row

    return best_row


def locate_commune_at_point(
    db: Session,
    lon: float,
    lat: float,
    fields: Optional[str],
    config: "CommunesEndpointConfig",
    *,
    nom_recherche: Optional[str] = None,
    code_postal: Optional[str] = None,
    code_departement: Optional[str] = None,
    region: Optional[str] = None,
) -> CommuneResponseSchema:
    """Commune la plus proche du point (contour si possible, sinon distance au polygone)."""
    list_properties, requested_fields, _ = resolve_commune_field_lists(fields, config)
    if "geometry_geojson" not in list_properties:
        list_properties.append("geometry_geojson")

    list_properties_sql = ", ".join(list_properties)
    query = f"""
        SELECT {list_properties_sql}
        FROM communes
        WHERE geometry_geojson IS NOT NULL
    """
    params: dict = {}
    query += config.type_filter_sql(params)

    if nom_recherche is not None:
        query += " AND nom_recherche LIKE :nom_recherche"
        params["nom_recherche"] = f"%{nom_recherche}%"
    if code_postal:
        query += " AND (',' || codes_postaux || ',') LIKE :code_postal_pattern"
        params["code_postal_pattern"] = f"%,{code_postal.strip()},%"
    use_parent = config.enrich_from_parent
    if code_departement:
        query += commune_code_departement_sql(
            params, code_departement, enrich_from_parent=use_parent
        )
    if region:
        query += commune_code_region_sql(params, region, enrich_from_parent=use_parent)

    # Pré-filtre SQL rapide (bbox), puis choix du plus proche en géométrie
    query += """
        AND min_lon IS NOT NULL
        AND min_lon <= :lon AND max_lon >= :lon
        AND min_lat <= :lat AND max_lat >= :lat
    """
    params["lon"] = lon
    params["lat"] = lat

    rows = db.execute(text(query), params).fetchall()

    if not rows:
        # Point hors bbox (frontière, bbox manquante) : candidats par centre de bbox
        fallback_query = f"""
            SELECT {list_properties_sql}
            FROM communes
            WHERE geometry_geojson IS NOT NULL
              AND min_lon IS NOT NULL
        """
        fallback_query += config.type_filter_sql(params)
        if nom_recherche is not None:
            fallback_query += " AND nom_recherche LIKE :nom_recherche"
        if code_postal:
            fallback_query += (
                " AND (',' || codes_postaux || ',') LIKE :code_postal_pattern"
            )
        if code_departement:
            fallback_query += commune_code_departement_sql(
                params, code_departement, enrich_from_parent=use_parent
            )
        if region:
            fallback_query += commune_code_region_sql(
                params, region, enrich_from_parent=use_parent
            )
        fallback_query += """
            ORDER BY
              ((min_lon + max_lon) / 2.0 - :lon) * ((min_lon + max_lon) / 2.0 - :lon)
            + ((min_lat + max_lat) / 2.0 - :lat) * ((min_lat + max_lat) / 2.0 - :lat)
            LIMIT 30
        """
        rows = db.execute(text(fallback_query), params).fetchall()

    nearest = pick_nearest_commune_row(rows, list_properties, lon, lat)
    if nearest is None:
        raise HTTPException(status_code=404, detail=config.not_found_point)

    dep_names = (
        load_departement_names(db) if "departement" in requested_fields else None
    )
    reg_names = load_region_names(db) if "region" in requested_fields else None
    interco_by_siren = None
    if "intercommunalites" in requested_fields:
        siren_idx = (
            list_properties.index("siren") if "siren" in list_properties else None
        )
        siren = nearest[siren_idx] if siren_idx is not None else None
        if siren:
            interco_by_siren, _ = load_interco_batch(db, [siren])

    return build_commune_properties(
        nearest,
        list_properties,
        requested_fields,
        db,
        fields,
        dep_names=dep_names,
        reg_names=reg_names,
        interco_by_siren=interco_by_siren,
        config=config,
    )


# Create FastAPI app
app = FastAPI(
    title="API Découpage Administratif",
    description="API pour accéder aux structures administratives territoriales françaises",
    version="1.0.0",
)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information"""
    return {
        "name": "API Découpage Administratif",
        "version": "1.0.0",
        "description": "API pour accéder aux structures administratives territoriales françaises",
        "endpoints": {
            "commune_par_code": "/communes/{code}",
            "commune_associee_deleguee_par_code": "/communes_associees_deleguees/{code}",
            "communes_par_departement": "/communes?codeDepartement={dep}",
            "departement_par_code": "/departements/{code}",
            "departement_communes": "/departements/{code}/communes",
            "departements_recherche": "/departements?nom={nom}",
            "region_par_code": "/regions/{code}",
            "region_departements": "/regions/{code}/departements",
            "region_communes": "/regions/{code}/communes",
            "regions_recherche": "/regions?nom={nom}",
            "epci_par_code": "/epcis/{code}",
            "epci_communes": "/epcis/{code}/communes",
            "epcis": "/epcis",
            "groupement_collectivites_territoriales_par_code": "/groupement_collectivites_territoriales/{code}",
            "groupement_collectivites_territoriales_communes": "/groupement_collectivites_territoriales/{code}/communes",
            "groupements_collectivites_territoriales": "/groupement_collectivites_territoriales",
            "aom_par_code": "/aom/{code}",
            "aom_communes": "/aom/{code}/communes",
            "aom": "/aom",
            "communes_associees_deleguees": "/communes_associees_deleguees",
            "communes_par_region": "/communes?region={reg}",
            "recherche": "/communes?nom={nom}",
            "health": "/health",
        },
    }


@app.get("/health", tags=["Health"])
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint"""
    try:
        # Test database connection
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
            },
        )


COMMUNE_MINIMAL_PROPERTIES = ["nom", "code_insee"]
COMMUNE_TYPE_COM = "COM"


def needs_associee_parent_enrich(
    requested_fields: List[str],
    fields_explicit: bool,
) -> bool:
    """True si l'enrichissement parent est nécessaire (codes ou objets imbriqués)."""
    if not fields_explicit:
        return True
    requested = set(requested_fields)
    return bool(
        ASSOCIEE_PARENT_ENRICH_FIELDS.intersection(requested)
        or ASSOCIEE_PARENT_NESTED_FIELDS.intersection(requested)
    )


def associee_parent_enrich_targets(
    requested_fields: List[str],
    fields_explicit: bool,
) -> set[str]:
    """Champs code à remplir depuis la commune parente COM."""
    if not fields_explicit:
        return set(ASSOCIEE_PARENT_ENRICH_FIELDS)
    requested = set(requested_fields)
    targets: set[str] = set()
    if "codeDepartement" in requested or "departement" in requested:
        targets.add("codeDepartement")
    if "codeRegion" in requested or "region" in requested:
        targets.add("codeRegion")
    if "codeEpci" in requested or "epci" in requested:
        targets.add("codeEpci")
    return targets


def enrich_commune_from_parent(
    properties: dict,
    db: Session,
    *,
    parent_code: Optional[str] = None,
    requested_fields: Optional[List[str]] = None,
    fields_explicit: bool = False,
) -> None:
    """
    COMD/COMA : département, région et EPCI absents sur la ligne enfant
    → reprise depuis la commune parente (type COM).
    Ne remplit que les champs demandés si ?fields= est précisé.
    """
    parent_code = parent_code or properties.get("chefLieu")
    if not parent_code or parent_code == properties.get("code"):
        return

    parent = db.execute(
        text("""
            SELECT code_departement, code_region, siren_interco, nom_interco
            FROM communes
            WHERE code_insee = :code AND type_commune = :type_commune
            LIMIT 1
        """),
        {"code": parent_code, "type_commune": COMMUNE_TYPE_COM},
    ).fetchone()
    if not parent:
        return

    targets = associee_parent_enrich_targets(requested_fields or [], fields_explicit)
    if "codeDepartement" in targets and not properties.get("codeDepartement"):
        properties["codeDepartement"] = parent[0]
    if "codeRegion" in targets and not properties.get("codeRegion"):
        properties["codeRegion"] = parent[1]
    if "codeEpci" in targets and not properties.get("codeEpci"):
        properties["codeEpci"] = parent[2]
    if "codeEpci" in targets and not properties.get("epci") and parent[3]:
        properties["epci"] = parent[3]


def resolve_code_departement_filter(
    code_departement: Optional[str],
    departement: Optional[str] = None,
) -> Optional[str]:
    """Code département à partir de codeDepartement ou departement (alias)."""
    value = (code_departement or departement or "").strip()
    return value or None


def commune_code_departement_sql(
    params: dict,
    code_departement: str,
    *,
    enrich_from_parent: bool = False,
) -> str:
    """Filtre département ; COMA/COMD : via commune_parente → COM (IN, pas EXISTS corrélé)."""
    params["code_departement"] = code_departement
    if not enrich_from_parent:
        return " AND code_departement = :code_departement"
    params["type_commune_parent"] = COMMUNE_TYPE_COM
    # COMA/COMD : dep vide sur l'enfant ; IN évite un EXISTS lent sur la vue communes
    return """
        AND commune_parente IN (
            SELECT code_insee FROM communes
            WHERE type_commune = :type_commune_parent
              AND code_departement = :code_departement
        )
    """


def commune_code_region_sql(
    params: dict,
    code_region: str,
    *,
    enrich_from_parent: bool = False,
) -> str:
    """Filtre région ; COMA/COMD : via commune_parente → COM (IN, pas EXISTS corrélé)."""
    params["region"] = code_region
    if not enrich_from_parent:
        return " AND code_region = :region"
    params.setdefault("type_commune_parent", COMMUNE_TYPE_COM)
    return """
        AND commune_parente IN (
            SELECT code_insee FROM communes
            WHERE type_commune = :type_commune_parent
              AND code_region = :region
        )
    """


def commune_centre_geometry(geom_geojson: Optional[str]):
    """Point GeoJSON du centroïde à partir d'une géométrie stockée en base."""
    raw_geom = parse_geometry(geom_geojson)
    if not raw_geom:
        return None
    geom_shape = shape(raw_geom)
    return {
        "type": "Point",
        "coordinates": [geom_shape.centroid.x, geom_shape.centroid.y],
    }


def build_commune_geojson_feature(
    result,
    list_properties: List[str],
    requested_fields: List[str],
    db: Session,
    fields: Optional[str],
    geom_for_centre: Optional[str] = None,
    config: CommunesEndpointConfig = COMMUNES_CONFIG,
):
    """
    Feature GeoJSON : properties selon ?fields= (comme format=json),
    geometry = centre (Point), calculé même si centre n'est pas dans fields.
    """
    properties = build_commune_properties(
        result,
        list_properties,
        requested_fields,
        db,
        fields,
        config=config,
    )
    geometry = properties.get("centre")
    if geometry is None:
        if geom_for_centre is None and "geometry_geojson" in list_properties:
            geom_for_centre = result[list_properties.index("geometry_geojson")]
        geometry = commune_centre_geometry(geom_for_centre)
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": geometry,
    }


def load_departement_names(db) -> dict:
    rows = db.execute(text("SELECT dep, libelle FROM departements_metadata")).fetchall()
    return {row[0]: row[1] for row in rows}


def load_region_names(db) -> dict:
    rows = db.execute(text("SELECT reg, libelle FROM regions_metadata")).fetchall()
    return {row[0]: row[1] for row in rows}


def load_interco_batch(
    db, commune_sirens: List[str]
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, dict[str, list[str]]],
]:
    """Load interco associations and competences for many communes."""
    interco_by_siren: dict[str, list[dict[str, Any]]] = {
        s: [] for s in commune_sirens if s
    }
    competences_by_siren: dict[str, dict[str, list[str]]] = {
        s: {} for s in commune_sirens if s
    }
    sirens = [s for s in commune_sirens if s]
    if not sirens:
        return interco_by_siren, competences_by_siren

    placeholders = ", ".join(f":s{i}" for i in range(len(sirens)))
    params = {f"s{i}": s for i, s in enumerate(sirens)}

    assoc_query = text(f"""
        SELECT commune_siren, interco_siren, interco_nom, interco_nature, membre_categorie
        FROM commune_interco_associations
        WHERE commune_siren IN ({placeholders})
        ORDER BY commune_siren, interco_nature, interco_nom
    """)
    for row in db.execute(assoc_query, params).fetchall():
        interco_by_siren.setdefault(row[0], []).append(
            {
                "siren": row[1],
                "nom": row[2],
                "nature": row[3],
                "categorie": row[4],
                "competences": [],
            }
        )

    try:
        comp_query = text(f"""
            SELECT commune_siren, interco_siren, competence
            FROM interco_commune
            WHERE commune_siren IN ({placeholders})
            ORDER BY commune_siren, interco_siren, competence
        """)
        for row in db.execute(comp_query, params).fetchall():
            competences_by_siren.setdefault(row[0], {}).setdefault(row[1], []).append(
                row[2]
            )
    except Exception:
        pass

    for siren, intercos in interco_by_siren.items():
        comp_map = competences_by_siren.get(siren, {})
        for interco in intercos:
            interco["competences"] = comp_map.get(interco["siren"], [])

    return interco_by_siren, competences_by_siren


def get_commune_entity_by_code(
    code: str,
    fields: Optional[str],
    format: Literal["json", "geojson"],
    db: Session,
    config: CommunesEndpointConfig,
    *,
    allow_aom: bool = False,
):
    list_properties, requested_fields, _ = resolve_commune_field_lists(
        fields, config, allow_aom=allow_aom
    )
    query_columns = list(list_properties)
    if format == "geojson" and "geometry_geojson" not in query_columns:
        query_columns.append("geometry_geojson")
    list_properties_sql = ", ".join(query_columns)

    params: dict = {"code": code}
    sql = (
        f"SELECT {list_properties_sql} FROM communes "
        f"WHERE code_insee = :code{config.type_filter_sql(params)}"
    )
    result = db.execute(text(sql), params).fetchone()

    if not result:
        raise HTTPException(
            status_code=404,
            detail=config.not_found_code.format(code=code),
        )

    if format == "geojson":
        row = result
        geom_for_centre = None
        if len(query_columns) > len(list_properties):
            geom_for_centre = row[len(list_properties)]
            row = row[: len(list_properties)]
        return build_commune_geojson_feature(
            row,
            list_properties,
            requested_fields,
            db,
            fields,
            geom_for_centre=geom_for_centre,
            config=config,
        )

    return build_commune_properties(
        result, list_properties, requested_fields, db, fields, config=config
    )


_COMMUNE_LIST_PARAMS = {
    "nom": Query(None, description="Recherche par nom (partiel, normalisé)"),
    "lat": Query(
        None,
        description="Latitude (WGS84) : avec lon, renvoie la commune la plus proche (objet unique)",
    ),
    "lon": Query(
        None,
        description="Longitude (WGS84) : avec lat, renvoie la commune la plus proche (objet unique)",
    ),
    "codePostal": Query(None, description="Filtrer par code postal"),
    "codeDepartement": Query(
        None, description="Filtrer par code département (ex: 75, 2A, 972)"
    ),
    "departement": Query(
        None,
        description="Alias de codeDepartement (déprécié)",
        deprecated=True,
    ),
    "zone": Query(None, description="Filtrer par zone e.g metro, drom, com"),
    "region": Query(None, description="Filtrer par code région"),
    "fields": Query(
        None, description="Liste des champs à inclure, séparés par des virgules"
    ),
    "boost": Query(
        None,
        description="Avec nom : boost=population pour favoriser les communes les plus peuplées (api-geo)",
    ),
    "limit": Query(
        None, ge=1, le=1000, description="Nombre maximum de résultats (optionnel)"
    ),
    "offset": Query(0, ge=0, description="Offset pour la pagination"),
}


@app.get(
    "/communes/{code}",
    response_model=Union[CommuneResponseSchema, CommuneGeoJSONResponse],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "Commune non trouvée"},
        200: {"description": "Commune trouvée"},
    },
    tags=["Communes"],
)
async def get_commune_by_code(
    code: str,
    fields: Optional[str] = Query(
        None,
        description="Champs à inclure, séparés par des virgules (json et geojson)",
    ),
    format: Literal["json", "geojson"] = Query(
        "json",
        description="json : objet API ; geojson : Feature (properties + geometry = centre)",
    ),
    db: Session = Depends(get_db),
):
    """
    Récupérer une commune par son code INSEE (type **COM** uniquement).

    Champ **aom** (`fields=aom`) : AOM associée `{code, nom}` (uniquement sur cet endpoint).
    """
    try:
        return get_commune_entity_by_code(
            code, fields, format, db, COMMUNES_CONFIG, allow_aom=True
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/communes",
    response_model=Union[CommuneResponseSchema, List[CommuneResponseSchema]],
    response_model_exclude_none=True,
    tags=["Communes"],
)
async def list_communes(
    nom: Optional[str] = _COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = _COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = _COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = _COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = _COMMUNE_LIST_PARAMS["codeDepartement"],
    departement: Optional[str] = _COMMUNE_LIST_PARAMS["departement"],
    region: Optional[str] = _COMMUNE_LIST_PARAMS["region"],
    fields: Optional[str] = _COMMUNE_LIST_PARAMS["fields"],
    zone: Optional[str] = _COMMUNE_LIST_PARAMS["zone"],
    boost: Optional[str] = _COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = _COMMUNE_LIST_PARAMS["limit"],
    offset: int = _COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister les communes (type **COM**).

    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        dep_code = resolve_code_departement_filter(codeDepartement, departement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=region,
            zone=zone,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/communes_associees_deleguees/{code}",
    response_model=Union[CommuneResponseSchema, CommuneGeoJSONResponse],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "Entité non trouvée"},
        200: {"description": "Entité trouvée"},
    },
    tags=["Communes associées et déléguées"],
)
async def get_commune_associee_deleguee_by_code(
    code: str,
    fields: Optional[str] = Query(
        None,
        description="Champs à inclure (siren, population, codesPostaux, zone interdits)",
    ),
    format: Literal["json", "geojson"] = Query(
        "json",
        description="json : objet API ; geojson : Feature (properties + geometry = centre)",
    ),
    db: Session = Depends(get_db),
):
    """
    Récupérer une commune associée (**COMA**) ou déléguée (**COMD**) par code INSEE.
    """
    try:
        return get_commune_entity_by_code(
            code, fields, format, db, COMMUNES_ASSOCIEES_CONFIG
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/communes_associees_deleguees",
    response_model=Union[CommuneResponseSchema, List[CommuneResponseSchema]],
    response_model_exclude_none=True,
    tags=["Communes associées et déléguées"],
)
async def list_communes_associees_deleguees(
    nom: Optional[str] = _COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = _COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = _COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = _COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = _COMMUNE_LIST_PARAMS["codeDepartement"],
    departement: Optional[str] = _COMMUNE_LIST_PARAMS["departement"],
    region: Optional[str] = _COMMUNE_LIST_PARAMS["region"],
    fields: Optional[str] = _COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = _COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = _COMMUNE_LIST_PARAMS["limit"],
    offset: int = _COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister les communes associées (**COMA**) et déléguées (**COMD**).

    Champs interdits dans `fields` : siren, population, codesPostaux, zone.
    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        dep_code = resolve_code_departement_filter(codeDepartement, departement)
        return list_commune_entities(
            db,
            COMMUNES_ASSOCIEES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=region,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


_DEPARTEMENT_LIST_PARAMS = {
    "nom": Query(None, description="Recherche par nom (partiel, normalisé)"),
    "zone": Query(None, description="Filtrage par zone (metro, drom, com)"),
    "region": Query(None, description="Filtrer par code région"),
    "fields": Query(
        None, description="Liste des champs à inclure, séparés par des virgules"
    ),
    "limit": Query(
        None, ge=1, le=1000, description="Nombre maximum de résultats (optionnel)"
    ),
    "offset": Query(0, ge=0, description="Offset pour la pagination"),
}


@app.get(
    "/departements",
    response_model=List[DepartementResponseSchema],
    response_model_exclude_none=True,
    tags=["Départements"],
)
async def list_departements(
    nom: Optional[str] = _DEPARTEMENT_LIST_PARAMS["nom"],
    zone: Optional[str] = _DEPARTEMENT_LIST_PARAMS["zone"],
    region: Optional[str] = _DEPARTEMENT_LIST_PARAMS["region"],
    fields: Optional[str] = _DEPARTEMENT_LIST_PARAMS["fields"],
    limit: Optional[int] = _DEPARTEMENT_LIST_PARAMS["limit"],
    offset: int = _DEPARTEMENT_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister les départements.

    Par défaut : **nom**, **code**, **codeRegion**.
    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        return list_departement_entities(
            db,
            nom=nom,
            zone=zone,
            region=region,
            fields=fields,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/departements/{code}/communes",
    response_model=Union[CommuneResponseSchema, List[CommuneResponseSchema]],
    response_model_exclude_none=True,
    tags=["Départements"],
)
async def list_departement_communes(
    code: str,
    nom: Optional[str] = _COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = _COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = _COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = _COMMUNE_LIST_PARAMS["codePostal"],
    region: Optional[str] = _COMMUNE_LIST_PARAMS["region"],
    fields: Optional[str] = _COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = _COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = _COMMUNE_LIST_PARAMS["limit"],
    offset: int = _COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes du département (type **COM**), mêmes propriétés et filtres que `GET /communes`.
    """
    try:
        if not departement_exists(db, code):
            raise HTTPException(
                status_code=404,
                detail=f"Département avec le code {code} non trouvé",
            )
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=code,
            region=region,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/departements/{code}",
    response_model=Union[DepartementResponseSchema, DepartementGeoJSONResponse],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "Département non trouvé"},
        200: {"description": "Département trouvé"},
    },
    tags=["Départements"],
)
async def get_departement_by_code(
    code: str,
    fields: Optional[str] = Query(
        None,
        description="Champs à inclure, séparés par des virgules (json et geojson)",
    ),
    format: Literal["json", "geojson"] = Query(
        "json",
        description="json : objet API ; geojson : Feature (properties + geometry)",
    ),
    db: Session = Depends(get_db),
):
    """
    Récupérer un département par son code (ex: **75**, **2A**).

    Par défaut : **nom**, **code**, **codeRegion**.
    """
    try:
        return get_departement_entity_by_code(code, fields, format, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


_REGION_LIST_PARAMS = {
    "nom": Query(None, description="Recherche par nom (partiel, normalisé)"),
    "zone": Query(None, description="Filtrer par zone e.g metro, drom, com"),
    "fields": Query(
        None, description="Liste des champs à inclure, séparés par des virgules"
    ),
    "limit": Query(100, ge=1, le=1000, description="Nombre maximum de résultats"),
    "offset": Query(0, ge=0, description="Offset pour la pagination"),
}


@app.get(
    "/regions",
    response_model=List[RegionResponseSchema],
    response_model_exclude_none=True,
    tags=["Régions"],
)
async def list_regions(
    nom: Optional[str] = _REGION_LIST_PARAMS["nom"],
    zone: Optional[str] = _REGION_LIST_PARAMS["zone"],
    fields: Optional[str] = _REGION_LIST_PARAMS["fields"],
    limit: int = _REGION_LIST_PARAMS["limit"],
    offset: int = _REGION_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister les régions.

    Par défaut : **nom**, **code**.
    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        return list_region_entities(
            db,
            nom=nom,
            zone=zone,
            fields=fields,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/regions/{code}/departements",
    response_model=List[DepartementResponseSchema],
    response_model_exclude_none=True,
    tags=["Régions"],
)
async def list_region_departements(
    code: str,
    nom: Optional[str] = _DEPARTEMENT_LIST_PARAMS["nom"],
    fields: Optional[str] = _DEPARTEMENT_LIST_PARAMS["fields"],
    limit: Optional[int] = _DEPARTEMENT_LIST_PARAMS["limit"],
    offset: int = _DEPARTEMENT_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Départements de la région. Par défaut : **nom**, **code**, **codeRegion**.
    """
    try:
        if not region_exists(db, code):
            raise HTTPException(
                status_code=404,
                detail=f"Région avec le code {code} non trouvée",
            )
        return list_departement_entities(
            db,
            nom=nom,
            region=code,
            fields=fields,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/regions/{code}/communes",
    response_model=Union[CommuneResponseSchema, List[CommuneResponseSchema]],
    response_model_exclude_none=True,
    tags=["Régions"],
)
async def list_region_communes(
    code: str,
    nom: Optional[str] = _COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = _COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = _COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = _COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = _COMMUNE_LIST_PARAMS["codeDepartement"],
    departement: Optional[str] = _COMMUNE_LIST_PARAMS["departement"],
    fields: Optional[str] = _COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = _COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = _COMMUNE_LIST_PARAMS["limit"],
    offset: int = _COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes de la région (type **COM**), mêmes propriétés et filtres que `GET /communes`.
    """
    try:
        if not region_exists(db, code):
            raise HTTPException(
                status_code=404,
                detail=f"Région avec le code {code} non trouvée",
            )
        dep_code = resolve_code_departement_filter(codeDepartement, departement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=code,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/regions/{code}",
    response_model=Union[RegionResponseSchema, RegionGeoJSONResponse],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "Région non trouvée"},
        200: {"description": "Région trouvée"},
    },
    tags=["Régions"],
)
async def get_region_by_code(
    code: str,
    fields: Optional[str] = Query(
        None,
        description="Champs à inclure, séparés par des virgules (json et geojson)",
    ),
    format: Literal["json", "geojson"] = Query(
        "json",
        description="json : objet API ; geojson : Feature (properties + geometry)",
    ),
    db: Session = Depends(get_db),
):
    """
    Récupérer une région par son code (ex: **11**, **84**).

    Par défaut : **nom**, **code**.
    """
    try:
        return get_region_entity_by_code(code, fields, format, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/epcis",
    response_model=List[EpciResponseSchema],
    response_model_exclude_none=True,
    tags=["EPCI"],
)
async def list_epcis(
    nom: Optional[str] = EPCI_LIST_PARAMS["nom"],
    fields: Optional[str] = EPCI_LIST_PARAMS["fields"],
    limit: Optional[int] = EPCI_LIST_PARAMS["limit"],
    offset: int = EPCI_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister les EPCI (CA, CU, CC, METRO, MET69).

    Par défaut : **nom**, **code**, **codesDepartements**, **codesRegions**, **population**.
    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        return list_epci_entities(
            db,
            nom=nom,
            fields=fields,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/epcis/{code}/communes",
    response_model=Union[CommuneResponseSchema, List[CommuneResponseSchema]],
    response_model_exclude_none=True,
    tags=["EPCI"],
)
async def list_epci_communes(
    code: str,
    nom: Optional[str] = _COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = _COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = _COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = _COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = _COMMUNE_LIST_PARAMS["codeDepartement"],
    departement: Optional[str] = _COMMUNE_LIST_PARAMS["departement"],
    region: Optional[str] = _COMMUNE_LIST_PARAMS["region"],
    fields: Optional[str] = _COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = _COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = _COMMUNE_LIST_PARAMS["limit"],
    offset: int = _COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes membres de l'EPCI (type **COM**), mêmes propriétés et filtres que `GET /communes`.
    Champ **competences** (`fields=competences`) : compétences OUI depuis **interco_commune**.
    """
    try:
        commune_codes = get_epci_commune_codes(db, code)
        dep_code = resolve_code_departement_filter(codeDepartement, departement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=region,
            commune_codes=commune_codes,
            interco_code=code,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/epcis/{code}",
    response_model=Union[EpciResponseSchema, EpciGeoJSONResponse],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "EPCI non trouvé"},
        200: {"description": "EPCI trouvé"},
    },
    tags=["EPCI"],
)
async def get_epci_by_code(
    code: str,
    fields: Optional[str] = Query(
        None,
        description="Champs à inclure, séparés par des virgules (json et geojson)",
    ),
    format: Literal["json", "geojson"] = Query(
        "json",
        description="json : objet API ; geojson : Feature (properties + geometry)",
    ),
    db: Session = Depends(get_db),
):
    """
    Récupérer un EPCI par son code SIREN.

    Par défaut : **nom**, **code**, **codesDepartements**, **codesRegions**, **population**.
    """
    try:
        return get_epci_entity_by_code(code, fields, format, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/groupement_collectivites_territoriales",
    response_model=List[IntercommunaliteResponseSchema],
    response_model_exclude_none=True,
    tags=["Intercommunalités"],
)
async def list_intercommunalites(
    nom: Optional[str] = INTERCOMMUNALITE_LIST_PARAMS["nom"],
    type: Optional[str] = INTERCOMMUNALITE_LIST_PARAMS["type"],
    fields: Optional[str] = INTERCOMMUNALITE_LIST_PARAMS["fields"],
    limit: Optional[int] = INTERCOMMUNALITE_LIST_PARAMS["limit"],
    offset: int = INTERCOMMUNALITE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister toutes les intercommunalités (sans filtre EPCI).

    Par défaut : **nom**, **code**.
    Filtre **type** : nature juridique (CC, CA, CU, METRO, SIVOM, etc.).
    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        return list_intercommunalite_entities(
            db,
            nom=nom,
            type_filter=type,
            fields=fields,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/groupement_collectivites_territoriales/{code}/communes",
    response_model=Union[CommuneResponseSchema, List[CommuneResponseSchema]],
    response_model_exclude_none=True,
    tags=["Intercommunalités"],
)
async def list_groupement_communes(
    code: str,
    nom: Optional[str] = _COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = _COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = _COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = _COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = _COMMUNE_LIST_PARAMS["codeDepartement"],
    departement: Optional[str] = _COMMUNE_LIST_PARAMS["departement"],
    region: Optional[str] = _COMMUNE_LIST_PARAMS["region"],
    fields: Optional[str] = _COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = _COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = _COMMUNE_LIST_PARAMS["limit"],
    offset: int = _COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes liées au groupement via **interco_commune** (type **COM**),
    mêmes propriétés et filtres que `GET /communes`.
    Champ **competences** (`fields=competences`) : compétences OUI depuis **interco_commune**.
    """
    try:
        commune_codes = get_groupement_commune_codes(db, code)
        dep_code = resolve_code_departement_filter(codeDepartement, departement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=region,
            commune_codes=commune_codes,
            interco_code=code,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/groupement_collectivites_territoriales/{code}",
    response_model=Union[
        IntercommunaliteResponseSchema, IntercommunaliteGeoJSONResponse
    ],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "Intercommunalité non trouvée"},
        200: {"description": "Intercommunalité trouvée"},
    },
    tags=["Intercommunalités"],
)
async def get_intercommunalite_by_code(
    code: str,
    fields: Optional[str] = Query(
        None,
        description="Champs à inclure, séparés par des virgules (json et geojson)",
    ),
    format: Literal["json", "geojson"] = Query(
        "json",
        description="json : objet API ; geojson : Feature (properties + geometry)",
    ),
    db: Session = Depends(get_db),
):
    """
    Récupérer une intercommunalité par son code SIREN.

    Par défaut : **nom**, **code**.
    """
    try:
        return get_intercommunalite_entity_by_code(code, fields, format, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/aom",
    response_model=List[AomResponseSchema],
    response_model_exclude_none=True,
    tags=["AOM"],
)
async def list_aom(
    nom: Optional[str] = AOM_LIST_PARAMS["nom"],
    fields: Optional[str] = AOM_LIST_PARAMS["fields"],
    limit: Optional[int] = AOM_LIST_PARAMS["limit"],
    offset: int = AOM_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister les AOM (Autorités Organisatrices de Mobilité).

    Par défaut : **nom**, **code**, **nbCommunes**, **codesDepartements**, **codesRegions**.
    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        return list_aom_entities(
            db,
            nom=nom,
            fields=fields,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/aom/{code}/communes",
    response_model=Union[CommuneResponseSchema, List[CommuneResponseSchema]],
    response_model_exclude_none=True,
    tags=["AOM"],
)
async def list_aom_communes(
    code: str,
    nom: Optional[str] = _COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = _COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = _COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = _COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = _COMMUNE_LIST_PARAMS["codeDepartement"],
    departement: Optional[str] = _COMMUNE_LIST_PARAMS["departement"],
    region: Optional[str] = _COMMUNE_LIST_PARAMS["region"],
    fields: Optional[str] = _COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = _COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = _COMMUNE_LIST_PARAMS["limit"],
    offset: int = _COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes membres de l'AOM (type **COM**), mêmes propriétés et filtres que `GET /communes`.
    """
    try:
        commune_codes = get_aom_commune_codes(db, code)
        dep_code = resolve_code_departement_filter(codeDepartement, departement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=region,
            commune_codes=commune_codes,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/aom/{code}",
    response_model=Union[AomResponseSchema, AomGeoJSONResponse],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "AOM non trouvée"},
        200: {"description": "AOM trouvée"},
    },
    tags=["AOM"],
)
async def get_aom_by_code(
    code: str,
    fields: Optional[str] = Query(
        None,
        description="Champs à inclure, séparés par des virgules (json et geojson)",
    ),
    format: Literal["json", "geojson"] = Query(
        "json",
        description="json : objet API ; geojson : Feature (properties + geometry)",
    ),
    db: Session = Depends(get_db),
):
    """
    Récupérer une AOM par son code SIREN.

    Par défaut : **nom**, **code**, **nbCommunes**, **codesDepartements**, **codesRegions**.
    """
    try:
        return get_aom_entity_by_code(code, fields, format, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get("/stats", tags=["Statistics"])
async def get_statistics(db: Session = Depends(get_db)):
    """
    Obtenir des statistiques sur les données
    """
    try:
        stats_query = text("""
            SELECT
                COUNT(*) as total_entities,
                COUNT(DISTINCT code_departement) as total_departements,
                COUNT(DISTINCT code_region) as total_regions,
                COUNT(CASE WHEN geometry_geojson IS NOT NULL THEN 1 END) as entities_avec_geometrie,
                SUM(population) as population_totale,
                SUM(superficie) as superficie_totale
            FROM communes
        """)

        result = db.execute(stats_query).fetchone()

        # Count by type
        type_query = text("""
            SELECT type_commune, COUNT(*) as count
            FROM communes
            GROUP BY type_commune
            ORDER BY count DESC
        """)
        type_results = db.execute(type_query).fetchall()

        types_breakdown = {row[0]: row[1] for row in type_results}

        return {
            "total_entities": result[0],
            "total_departements": result[1],
            "total_regions": result[2],
            "entities_avec_geometrie": result[3],
            "population_totale": int(result[4]) if result[4] else None,
            "superficie_totale_km2": float(result[5]) if result[5] else None,
            "breakdown_by_type": types_breakdown,
            "type_labels": {
                "COM": "Communes",
                "ARM": "Arrondissements municipaux",
                "COMD": "Communes déléguées",
                "COMA": "Communes associées",
            },
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
