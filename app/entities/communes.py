"""Logique métier communes (COM) et communes associées/déléguées (COMA/COMD)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, List, Literal, Optional

from fastapi import HTTPException, Query
from shapely.geometry import Point, shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.nom_search import (
    NOM_SEARCH_CANDIDATE_LIMIT,
    nom_match_score,
    nom_search_sql_clause,
)
from app.entities.geometry import (
    commune_zone,
    compute_surface_hectares,
    geometry_shape_from_column,
    parse_geometry,
    resolve_lat_lon_point,
)
from app.entities.aom import load_aom_for_commune
from app.normalize_string import normalize_string
from app.schemas import CommuneResponseSchema

def pick_nearest_commune_row(
    rows: list,
    list_properties: List[str],
    lon: float,
    lat: float,
):
    """Parmi les lignes candidates, retourne celle dont le contour est le plus proche du point."""
    if not rows:
        return None
    geom_col = (
        "geometry_geojson"
        if "geometry_geojson" in list_properties
        else "geometry"
        if "geometry" in list_properties
        else None
    )
    if geom_col is None:
        return rows[0]

    geom_idx = list_properties.index(geom_col)
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
        WHERE geometry IS NOT NULL
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
            WHERE geometry IS NOT NULL
              AND min_lon IS NOT NULL
        """
        fallback_query += config.type_filter_sql(params)
        if nom_recherche is not None:
            fallback_query += " AND nom_recherche LIKE :nom_recherche"
        if code_postal:
            fallback_query += " AND (',' || codes_postaux || ',') LIKE :code_postal_pattern"
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

    dep_names = load_departement_names(db) if "departement" in requested_fields else None
    reg_names = load_region_names(db) if "region" in requested_fields else None
    interco_by_siren = None
    if "intercommunalites" in requested_fields:
        siren_idx = list_properties.index("siren") if "siren" in list_properties else None
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

dict_apigeo = {
    "code": "code_insee",
    "nom": "nom",
    "codeDepartement": "code_departement",
    "codeRegion": "code_region",
    "siren": "siren",
    "codeEpci": "siren_interco",
    "epci": "nom_interco",
    "codesPostaux": "codes_postaux",
    "population": "population",
    "contour": "geometry_geojson",
    "centre": "geometry_geojson",
    "bbox": "geometry_geojson",
    "mairie": "mairie_geojson",
    "chefLieu": "commune_parente",
    "type": "type_commune",
}
dict_apigeo_reverse = {
    "code_insee": "code",
    "nom": "nom",
    "code_departement": "codeDepartement",
    "code_region": "codeRegion",
    "siren": "siren",
    "siren_interco": "codeEpci",
    "nom_interco": "epci",
    "codes_postaux": "codesPostaux",
    "population": "population",
    "geometry_geojson": "contour",
    "mairie_geojson": "mairie",
    "commune_parente": "chefLieu",
}

COMMUNE_MINIMAL_PROPERTIES = ["nom", "code_insee"]
COMMUNE_TYPE_COM = "COM"
COMMUNE_TYPES_ASSOCIEE_DELEGUEE = ("COMA", "COMD")

COMMUNE_TYPE_API_LABEL = {
    "COMD": "commune-deleguee",
    "COMA": "commune-associee",
}

COMMUNE_ASSOCIEE_FORBIDDEN_FIELDS = frozenset(
    {"siren", "population", "codesPostaux", "zone"}
)

COMMUNE_INTERCO_COMPETENCES_FIELD = "competences"
COMMUNE_AOM_FIELD = "aom"


@dataclass(frozen=True)
class CommunesEndpointConfig:
    """Configuration partagée pour /communes et /communes_associees_deleguees."""

    label: str
    default_properties: tuple[str, ...]
    forbidden_fields: frozenset[str]
    type_filter_sql: Callable[[dict], str]
    not_found_code: str
    not_found_point: str
    not_found_search: str
    enrich_from_parent: bool = False
    map_type_label: bool = False


def commune_type_com_sql(params: dict) -> str:
    """Filtre : communes de type COM uniquement."""
    params["type_commune"] = COMMUNE_TYPE_COM
    return " AND type_commune = :type_commune"


def commune_type_coma_comd_sql(params: dict) -> str:
    """Filtre : communes associées (COMA) et déléguées (COMD)."""
    return " AND type_commune IN ('COMA', 'COMD')"


COMMUNES_CONFIG = CommunesEndpointConfig(
    label="commune",
    default_properties=(
        "nom",
        "code_insee",
        "code_departement",
        "siren",
        "siren_interco",
        "code_region",
        "codes_postaux",
        "population",
    ),
    forbidden_fields=frozenset(),
    type_filter_sql=commune_type_com_sql,
    not_found_code="Commune avec le code {code} non trouvée",
    not_found_point="Aucune commune trouvée pour ces coordonnées",
    not_found_search="Aucune commune trouvée pour ces critères",
)

COMMUNES_ASSOCIEES_CONFIG = CommunesEndpointConfig(
    label="commune associée ou déléguée",
    default_properties=(
        "nom",
        "code_insee",
        "code_departement",
        "siren_interco",
        "code_region",
        "commune_parente",
        "type_commune",
    ),
    forbidden_fields=COMMUNE_ASSOCIEE_FORBIDDEN_FIELDS,
    type_filter_sql=commune_type_coma_comd_sql,
    not_found_code="Commune associée ou déléguée avec le code {code} non trouvée",
    not_found_point="Aucune commune associée ou déléguée trouvée pour ces coordonnées",
    not_found_search="Aucune commune associée ou déléguée trouvée pour ces critères",
    enrich_from_parent=True,
    map_type_label=True,
)


ASSOCIEE_PARENT_ENRICH_FIELDS = frozenset(
    {"codeDepartement", "codeRegion", "codeEpci"}
)
ASSOCIEE_PARENT_NESTED_FIELDS = frozenset({"departement", "region", "epci"})


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


def resolve_commune_field_lists(
    fields: Optional[str],
    config: CommunesEndpointConfig = COMMUNES_CONFIG,
    *,
    allow_interco_competences: bool = False,
    allow_aom: bool = False,
):
    """Build SQL columns and requested API fields from ?fields=."""
    if fields:
        requested_fields = [f.strip() for f in fields.split(",") if f.strip()]
        for field in requested_fields:
            if field == COMMUNE_INTERCO_COMPETENCES_FIELD:
                if not allow_interco_competences:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Le champ 'competences' n'est disponible que sur "
                            "/epcis/{code}/communes et "
                            "/groupement_collectivites_territoriales/{code}/communes."
                        ),
                    )
                continue
            if field == COMMUNE_AOM_FIELD:
                if not allow_aom:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Le champ 'aom' n'est disponible que sur "
                            "/communes/{code}."
                        ),
                    )
                continue
            if field in config.forbidden_fields:
                raise HTTPException(
                    status_code=400,
                    detail=f"Le champ '{field}' n'est pas autorisé pour cet endpoint.",
                )
        if (
            "intercommunalites" in requested_fields
            and "siren" in config.forbidden_fields
        ):
            raise HTTPException(
                status_code=400,
                detail="Le champ 'intercommunalites' n'est pas disponible pour cet endpoint.",
            )
    else:
        requested_fields = []

    if not fields:
        return list(config.default_properties), [], False

    list_properties = COMMUNE_MINIMAL_PROPERTIES.copy()
    for field in requested_fields:
        if field in dict_apigeo and dict_apigeo[field] not in list_properties:
            list_properties.append(dict_apigeo[field])
    if "departement" in requested_fields and "code_departement" not in list_properties:
        list_properties.append("code_departement")
    if "region" in requested_fields and "code_region" not in list_properties:
        list_properties.append("code_region")
    if "epci" in requested_fields:
        if "siren_interco" not in list_properties:
            list_properties.append("siren_interco")
        if "nom_interco" not in list_properties:
            list_properties.append("nom_interco")
    if (
        "intercommunalites" in requested_fields
        and "siren" not in config.forbidden_fields
        and "siren" not in list_properties
    ):
        list_properties.append("siren")
    if (
        any(
            f in requested_fields
            for f in ("mairie", "surface", "contour", "centre", "bbox")
        )
        and "geometry_geojson" not in list_properties
    ):
        list_properties.append("geometry_geojson")
    if "mairie" in requested_fields and "mairie_geojson" not in list_properties:
        list_properties.append("mairie_geojson")
    if config.enrich_from_parent and needs_associee_parent_enrich(
        requested_fields, fields_explicit=True
    ):
        if "commune_parente" not in list_properties:
            list_properties.append("commune_parente")
    return list_properties, requested_fields, True


def commune_centre_geometry(geom_wkt_or_geojson: Optional[str]):
    """Point GeoJSON du centroïde à partir d'une géométrie stockée en base."""
    raw_geom = parse_geometry(geom_wkt_or_geojson)
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


def load_interco_batch(db, commune_sirens: List[str]):
    """Load interco associations and competences for many communes."""
    interco_by_siren = {s: [] for s in commune_sirens if s}
    competences_by_siren = {s: {} for s in commune_sirens if s}
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
        interco_by_siren.setdefault(row[0], []).append({
            "siren": row[1],
            "nom": row[2],
            "nature": row[3],
            "categorie": row[4],
            "competences": [],
        })

    try:
        comp_query = text(f"""
            SELECT commune_siren, interco_siren, competence
            FROM interco_commune
            WHERE commune_siren IN ({placeholders})
            ORDER BY commune_siren, interco_siren, competence
        """)
        for row in db.execute(comp_query, params).fetchall():
            competences_by_siren.setdefault(row[0], {}).setdefault(row[1], []).append(row[2])
    except Exception:
        pass

    for siren, intercos in interco_by_siren.items():
        comp_map = competences_by_siren.get(siren, {})
        for interco in intercos:
            interco["competences"] = comp_map.get(interco["siren"], [])

    return interco_by_siren, competences_by_siren


def load_interco_commune_competences(
    db: Session,
    interco_siren: str,
    commune_codes: list[str],
) -> dict[str, list[str]]:
    """Compétences OUI par commune pour un groupement (table interco_commune)."""
    codes = [code for code in commune_codes if code]
    if not codes:
        return {}

    placeholders = ", ".join(f":cc_{i}" for i in range(len(codes)))
    params: dict = {"interco_siren": interco_siren}
    for i, commune_code in enumerate(codes):
        params[f"cc_{i}"] = commune_code

    try:
        rows = db.execute(
            text(f"""
                SELECT commune_code, competence
                FROM interco_commune
                WHERE interco_siren = :interco_siren
                  AND commune_code IN ({placeholders})
                ORDER BY commune_code, competence
            """),
            params,
        ).fetchall()
    except Exception:
        return {}

    competences_by_commune: dict[str, list[str]] = {}
    for commune_code, competence in rows:
        if not commune_code or not competence:
            continue
        competences_by_commune.setdefault(commune_code, []).append(competence)
    return competences_by_commune


def build_commune_properties(
    result,
    list_properties: List[str],
    requested_fields: List[str],
    db: Session,
    fields: Optional[str],
    *,
    dep_names: Optional[dict] = None,
    reg_names: Optional[dict] = None,
    interco_by_siren: Optional[dict] = None,
    competences_by_siren: Optional[dict] = None,
    interco_competences_by_commune: Optional[dict[str, list[str]]] = None,
    config: CommunesEndpointConfig = COMMUNES_CONFIG,
):
    """Build API commune object from a DB row (same rules as GET /communes/{code})."""
    properties = {}
    for i, column_name in enumerate(list_properties):
        if column_name not in dict_apigeo_reverse:
            continue
        api_field = dict_apigeo_reverse[column_name]
        value = result[i]
        if api_field == "codesPostaux":
            value = value.split(",") if value else []
        if api_field == "contour":
            parsed_geometry = parse_geometry(value)
            value = parsed_geometry if "contour" in requested_fields else None
        if api_field == "mairie":
            value = parse_geometry(value)
        properties[api_field] = value

    code_insee = properties.get("code")

    parent_code = None
    if "commune_parente" in list_properties:
        parent_code = result[list_properties.index("commune_parente")]

    if config.enrich_from_parent:
        enrich_commune_from_parent(
            properties,
            db,
            parent_code=parent_code,
            requested_fields=requested_fields,
            fields_explicit=bool(fields),
        )

    if "departement" in requested_fields:
        dep_code = properties.get("codeDepartement")
        if dep_code:
            if dep_names is not None:
                dep_nom = dep_names.get(dep_code)
            else:
                dep_row = db.execute(
                    text("SELECT libelle FROM departements_metadata WHERE dep = :dep LIMIT 1"),
                    {"dep": dep_code},
                ).fetchone()
                dep_nom = dep_row[0] if dep_row else None
            properties["departement"] = {"code": dep_code, "nom": dep_nom}

    if "region" in requested_fields:
        reg_code = properties.get("codeRegion")
        if reg_code:
            if reg_names is not None:
                reg_nom = reg_names.get(reg_code)
            else:
                reg_row = db.execute(
                    text("SELECT libelle FROM regions_metadata WHERE reg = :reg LIMIT 1"),
                    {"reg": reg_code},
                ).fetchone()
                reg_nom = reg_row[0] if reg_row else None
            properties["region"] = {"code": reg_code, "nom": reg_nom}

    if "epci" in requested_fields:
        epci_code = properties.get("codeEpci")
        epci_nom = properties.get("epci")
        if epci_code or epci_nom:
            properties["epci"] = {"code": epci_code, "nom": epci_nom}

    if COMMUNE_AOM_FIELD in requested_fields:
        aom = load_aom_for_commune(
            db,
            code_insee or "",
            properties.get("siren"),
        )
        if aom:
            properties[COMMUNE_AOM_FIELD] = aom

    if fields:
        if "departement" in requested_fields and "codeDepartement" not in requested_fields:
            properties.pop("codeDepartement", None)
        if "region" in requested_fields and "codeRegion" not in requested_fields:
            properties.pop("codeRegion", None)
        if "epci" in requested_fields and "codeEpci" not in requested_fields:
            properties.pop("codeEpci", None)

    if "zone" in requested_fields and code_insee:
        properties["zone"] = commune_zone(code_insee)

    if "geometry_geojson" in list_properties and (
        "centre" in requested_fields
        or "bbox" in requested_fields
        or "mairie" in requested_fields
        or "surface" in requested_fields
    ):
        geometry = parse_geometry(result[list_properties.index("geometry_geojson")])
        if geometry:
            geom_shape = shape(geometry)
            centre_point = {
                "type": "Point",
                "coordinates": [geom_shape.centroid.x, geom_shape.centroid.y],
            }
            if "centre" in requested_fields:
                properties["centre"] = centre_point
            if "bbox" in requested_fields:
                minx, miny, maxx, maxy = geom_shape.bounds
                properties["bbox"] = {
                    "type": "Polygon",
                    "coordinates": [[
                        [minx, miny],
                        [maxx, miny],
                        [maxx, maxy],
                        [minx, maxy],
                        [minx, miny],
                    ]],
                }
            if "mairie" in requested_fields:
                mairie = None
                if "mairie_geojson" in list_properties:
                    mairie = parse_geometry(result[list_properties.index("mairie_geojson")])
                properties["mairie"] = mairie or centre_point
            if "surface" in requested_fields:
                properties["surface"] = compute_surface_hectares(geom_shape)

    if "intercommunalites" in requested_fields:
        commune_siren = properties.get("siren")
        intercommunalites = []
        if commune_siren:
            if interco_by_siren is not None:
                intercommunalites = interco_by_siren.get(commune_siren, [])
            else:
                assoc_results = db.execute(
                    text("""
                        SELECT interco_siren, interco_nom, interco_nature, membre_categorie
                        FROM commune_interco_associations
                        WHERE commune_siren = :siren
                        ORDER BY interco_nature, interco_nom
                    """),
                    {"siren": commune_siren},
                ).fetchall()
                competences_map = {}
                try:
                    for comp_row in db.execute(
                        text("""
                            SELECT interco_siren, competence
                            FROM interco_commune
                            WHERE commune_siren = :siren
                            ORDER BY interco_siren, competence
                        """),
                        {"siren": commune_siren},
                    ).fetchall():
                        competences_map.setdefault(comp_row[0], []).append(comp_row[1])
                except Exception:
                    pass
                for assoc in assoc_results:
                    intercommunalites.append({
                        "siren": assoc[0],
                        "nom": assoc[1],
                        "nature": assoc[2],
                        "categorie": assoc[3],
                        "competences": competences_map.get(assoc[0], []),
                    })
        properties["intercommunalites"] = intercommunalites

    if COMMUNE_INTERCO_COMPETENCES_FIELD in requested_fields:
        commune_code = properties.get("code")
        if interco_competences_by_commune is not None and commune_code:
            properties[COMMUNE_INTERCO_COMPETENCES_FIELD] = (
                interco_competences_by_commune.get(commune_code, [])
            )
        else:
            properties[COMMUNE_INTERCO_COMPETENCES_FIELD] = []

    if config.map_type_label and "type_commune" in list_properties:
        if not fields or "type" in requested_fields:
            raw_type = result[list_properties.index("type_commune")]
            if raw_type:
                properties["type"] = COMMUNE_TYPE_API_LABEL.get(raw_type, raw_type)

    if fields:
        allowed = {"nom", "code"} | set(requested_fields)
        properties = {k: v for k, v in properties.items() if k in allowed}

    return properties


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


def list_commune_entities(
    db: Session,
    config: CommunesEndpointConfig,
    *,
    nom: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    code_postal: Optional[str] = None,
    code_departement: Optional[str] = None,
    region: Optional[str] = None,
    commune_codes: Optional[list[str]] = None,
    interco_code: Optional[str] = None,
    fields: Optional[str] = None,
    boost: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
):
    nom_recherche = None
    if nom is not None:
        nom_recherche = normalize_string(nom)
        if not nom_recherche:
            point_early = resolve_lat_lon_point(lat, lon)
            if point_early:
                raise HTTPException(status_code=404, detail=config.not_found_search)
            return []

    point = resolve_lat_lon_point(lat, lon)
    if point:
        lon_f, lat_f = point
        return locate_commune_at_point(
            db,
            lon_f,
            lat_f,
            fields,
            config,
            nom_recherche=nom_recherche,
            code_postal=code_postal,
            code_departement=code_departement,
            region=region,
        )

    boost_population = boost == "population"
    if boost and boost != "population":
        raise HTTPException(
            status_code=400,
            detail="Valeur de boost non supportée. Utilisez boost=population.",
        )

    list_properties, requested_fields, _ = resolve_commune_field_lists(
        fields,
        config,
        allow_interco_competences=interco_code is not None,
    )
    if nom_recherche is not None:
        for col in ("nom_recherche", "population"):
            if col not in list_properties:
                list_properties.append(col)
    list_properties_sql = ", ".join(list_properties)

    query = f"""
        SELECT {list_properties_sql}
        FROM communes
        WHERE 1=1
    """
    params: dict = {}
    query += config.type_filter_sql(params)

    if nom_recherche is not None:
        query += nom_search_sql_clause(params, nom_recherche)

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

    if commune_codes is not None:
        if not commune_codes:
            return []
        placeholders = ", ".join(f":cc_{i}" for i in range(len(commune_codes)))
        query += f" AND code_insee IN ({placeholders})"
        for i, commune_code in enumerate(commune_codes):
            params[f"cc_{i}"] = commune_code

    if nom_recherche is not None:
        query += " LIMIT :candidate_limit"
        params["candidate_limit"] = NOM_SEARCH_CANDIDATE_LIMIT
    else:
        query += " ORDER BY nom"
        if offset:
            query += " OFFSET :offset"
            params["offset"] = offset
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = limit

    results = db.execute(text(query), params).fetchall()

    dep_names = load_departement_names(db) if "departement" in requested_fields else None
    reg_names = load_region_names(db) if "region" in requested_fields else None
    interco_by_siren = None
    if "intercommunalites" in requested_fields:
        siren_idx = list_properties.index("siren") if "siren" in list_properties else None
        sirens = []
        if siren_idx is not None:
            sirens = [row[siren_idx] for row in results if row[siren_idx]]
        interco_by_siren, _ = load_interco_batch(db, sirens)

    nom_idx = (
        list_properties.index("nom_recherche")
        if "nom_recherche" in list_properties
        else None
    )
    pop_idx = (
        list_properties.index("population")
        if "population" in list_properties
        else None
    )

    scored_rows: list[tuple[float, tuple]] = []
    for row in results:
        match_score = 0.0
        if nom_recherche is not None and nom_idx is not None:
            pop = row[pop_idx] if pop_idx is not None else None
            match_score = nom_match_score(
                nom_recherche,
                row[nom_idx] or "",
                pop,
                boost_population=boost_population,
            )
            if match_score <= 0:
                continue
        scored_rows.append((match_score, row))

    if nom_recherche is not None:
        scored_rows.sort(key=lambda item: (-item[0], item[1][list_properties.index("nom")]))
        if limit is not None:
            scored_rows = scored_rows[offset : offset + limit]
        elif offset:
            scored_rows = scored_rows[offset:]

    interco_competences_by_commune = None
    if (
        COMMUNE_INTERCO_COMPETENCES_FIELD in requested_fields
        and interco_code
    ):
        code_idx = list_properties.index("code_insee")
        result_codes = [row[code_idx] for _, row in scored_rows if row[code_idx]]
        interco_competences_by_commune = load_interco_commune_competences(
            db, interco_code, result_codes
        )

    communes = []
    for match_score, row in scored_rows:
        props = build_commune_properties(
            row,
            list_properties,
            requested_fields,
            db,
            fields,
            dep_names=dep_names,
            reg_names=reg_names,
            interco_by_siren=interco_by_siren,
            interco_competences_by_commune=interco_competences_by_commune,
            config=config,
        )
        if nom_recherche is not None:
            props["_score"] = match_score  # sérialisé via alias _score (schéma Pydantic)
        communes.append(props)

    return communes


COMMUNE_LIST_PARAMS = {
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
    "region": Query(None, description="Filtrer par code région"),
    "fields": Query(None, description="Liste des champs à inclure, séparés par des virgules"),
    "boost": Query(
        None,
        description="Avec nom : boost=population pour favoriser les communes les plus peuplées (api-geo)",
    ),
    "limit": Query(None, ge=1, le=1000, description="Nombre maximum de résultats (optionnel)"),
    "offset": Query(0, ge=0, description="Offset pour la pagination"),
}
