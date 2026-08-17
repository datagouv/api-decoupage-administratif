"""
Endpoints et logique métier pour les intercommunalités (table interco).
"""

from __future__ import annotations

import json
from typing import List, Literal, Optional, Sequence

from fastapi import HTTPException, Query
from shapely.geometry import shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.entities.geometry import compute_surface_hectares, parse_geometry
from app.nom_search import (
    NOM_SEARCH_CANDIDATE_LIMIT,
    nom_match_score,
    nom_search_sql_clause,
)
from app.normalize_string import normalize_string

INTERCO_MINIMAL_PROPERTIES = ["nom", "siren"]
INTERCO_DEFAULT_PROPERTIES = ("nom", "siren")
EPCI_DEFAULT_PROPERTIES = ("nom", "siren", "population")

INTERCO_API_TO_SQL = {
    "code": "siren",
    "nom": "nom",
    "type": "nature",
    "financement": "financement",
    "population": "population",
    "membres_siren": "membres_siren",
    "contour": "geometry_geojson",
    "centre": "geometry_geojson",
    "bbox": "geometry_geojson",
    "surface": "geometry_geojson",
}
INTERCO_SQL_TO_API = {v: k for k, v in INTERCO_API_TO_SQL.items()}
INTERCO_COMPUTED_FIELDS = frozenset({"codesDepartements", "codesRegions"})


def parse_json_string_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if item and str(item).strip()]


def parse_communes_code(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(code).strip() for code in parsed if code and str(code).strip()]


def load_commune_admin_codes_map(
    db: Session, commune_codes: set[str]
) -> dict[str, tuple[Optional[str], Optional[str]]]:
    if not commune_codes:
        return {}

    admin_map: dict[str, tuple[Optional[str], Optional[str]]] = {}
    codes_list = list(commune_codes)
    chunk_size = 400

    for offset in range(0, len(codes_list), chunk_size):
        chunk = codes_list[offset : offset + chunk_size]
        placeholders = ", ".join(f":c{i}" for i in range(len(chunk)))
        params = {f"c{i}": code for i, code in enumerate(chunk)}
        rows = db.execute(
            text(
                f"""
                SELECT code_insee, code_departement, code_region
                FROM communes
                WHERE type_commune = 'COM'
                  AND code_insee IN ({placeholders})
                """
            ),
            params,
        ).fetchall()
        for code_insee, code_departement, code_region in rows:
            admin_map[code_insee] = (code_departement, code_region)

    return admin_map


def admin_codes_from_communes(
    commune_codes: list[str],
    admin_map: dict[str, tuple[Optional[str], Optional[str]]],
) -> tuple[list[str], list[str]]:
    departements: set[str] = set()
    regions: set[str] = set()
    for code in commune_codes:
        dep, reg = admin_map.get(code, (None, None))
        if dep:
            departements.add(dep)
        if reg:
            regions.add(reg)
    return sorted(departements), sorted(regions)


def resolve_interco_field_lists(
    fields: Optional[str],
    *,
    entity_label: str = "intercommunalité",
    default_properties: Sequence[str] = INTERCO_DEFAULT_PROPERTIES,
):
    if fields:
        requested_fields = [f.strip() for f in fields.split(",") if f.strip()]
        for field in requested_fields:
            if field not in INTERCO_API_TO_SQL and field not in INTERCO_COMPUTED_FIELDS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Le champ '{field}' n'est pas reconnu pour les {entity_label}s.",
                )
    else:
        requested_fields = []

    if not fields:
        return list(default_properties), [], False

    list_properties = INTERCO_MINIMAL_PROPERTIES.copy()
    for field in requested_fields:
        if field in INTERCO_COMPUTED_FIELDS:
            continue
        sql_col = INTERCO_API_TO_SQL[field]
        if sql_col not in list_properties:
            list_properties.append(sql_col)
    if any(
        field in requested_fields for field in ("contour", "centre", "bbox", "surface")
    ) and "geometry_geojson" not in list_properties:
        list_properties.append("geometry_geojson")
    return list_properties, requested_fields, True


def interco_filter_sql(
    params: dict,
    *,
    natures: Optional[Sequence[str]] = None,
    type_filter: Optional[str] = None,
) -> str:
    clause = ""
    if natures:
        quoted = ", ".join(f"'{nature}'" for nature in natures)
        clause += f" AND nature IN ({quoted})"
    if type_filter is not None:
        clause += " AND nature = :type_filter"
        params["type_filter"] = type_filter
    return clause


def build_interco_properties(
    row,
    list_properties: List[str],
    requested_fields: List[str],
    fields: Optional[str],
    *,
    commune_codes: Optional[list[str]] = None,
    admin_map: Optional[dict[str, tuple[Optional[str], Optional[str]]]] = None,
    default_admin_codes: bool = False,
) -> dict:
    properties: dict = {}
    communes_code_idx = (
        list_properties.index("communes_code")
        if "communes_code" in list_properties
        else None
    )

    for i, column_name in enumerate(list_properties):
        if column_name in ("communes_code", "nom_recherche"):
            continue
        api_field = INTERCO_SQL_TO_API.get(column_name)
        if not api_field:
            continue
        value = row[i]
        if api_field == "membres_siren":
            value = parse_json_string_list(value)
        properties[api_field] = value

    if commune_codes is None and communes_code_idx is not None:
        commune_codes = parse_communes_code(row[communes_code_idx])

    include_admin_codes = (
        default_admin_codes and not fields
    ) or any(
        field in requested_fields
        for field in ("codesDepartements", "codesRegions")
    )
    if include_admin_codes and commune_codes is not None:
        if admin_map is None:
            admin_map = {}
        codes_deps, codes_regs = admin_codes_from_communes(commune_codes, admin_map)
        properties["codesDepartements"] = codes_deps
        properties["codesRegions"] = codes_regs

    geom_raw = None
    if "geometry_geojson" in list_properties:
        geom_raw = row[list_properties.index("geometry_geojson")]

    if geom_raw and any(
        field in requested_fields for field in ("contour", "centre", "bbox", "surface")
    ):
        geometry = parse_geometry(geom_raw)
        if geometry:
            geom_shape = shape(geometry)
            if "contour" in requested_fields:
                properties["contour"] = geometry
            if "centre" in requested_fields:
                properties["centre"] = {
                    "type": "Point",
                    "coordinates": [geom_shape.centroid.x, geom_shape.centroid.y],
                }
            if "bbox" in requested_fields:
                minx, miny, maxx, maxy = geom_shape.bounds
                properties["bbox"] = {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [minx, miny],
                            [maxx, miny],
                            [maxx, maxy],
                            [minx, maxy],
                            [minx, miny],
                        ]
                    ],
                }
            if "surface" in requested_fields:
                properties["surface"] = compute_surface_hectares(geom_shape)

    if fields:
        allowed = {"nom", "code"} | set(requested_fields)
        properties = {k: v for k, v in properties.items() if k in allowed}
    return properties


def interco_nom_recherche_available(db: Session) -> bool:
    try:
        db.execute(text("SELECT nom_recherche FROM interco LIMIT 1"))
        return True
    except Exception:
        return False


def interco_exists(
    db: Session,
    code: str,
    *,
    natures: Optional[Sequence[str]] = None,
) -> bool:
    params: dict = {"code": code}
    row = db.execute(
        text(
            "SELECT 1 FROM interco WHERE siren = :code"
            + interco_filter_sql(params, natures=natures)
            + " LIMIT 1"
        ),
        params,
    ).fetchone()
    return row is not None


def _needs_admin_codes(
    fields: Optional[str],
    requested_fields: List[str],
    *,
    default_admin_codes: bool,
) -> bool:
    return (default_admin_codes and not fields) or any(
        field in requested_fields
        for field in ("codesDepartements", "codesRegions")
    )


def list_interco_entities(
    db: Session,
    *,
    nom: Optional[str] = None,
    code: Optional[str] = None,
    natures: Optional[Sequence[str]] = None,
    type_filter: Optional[str] = None,
    fields: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    entity_label: str = "intercommunalité",
    default_properties: Sequence[str] = INTERCO_DEFAULT_PROPERTIES,
    default_admin_codes: bool = False,
) -> list[dict]:
    nom_query = None
    if nom is not None:
        nom_query = normalize_string(nom)
        if not nom_query and code is None:
            return []

    list_properties, requested_fields, _ = resolve_interco_field_lists(
        fields,
        entity_label=entity_label,
        default_properties=default_properties,
    )
    has_nom_recherche = interco_nom_recherche_available(db)
    if nom_query is not None:
        if has_nom_recherche and "nom_recherche" not in list_properties:
            list_properties.append("nom_recherche")

    need_admin_codes = _needs_admin_codes(
        fields, requested_fields, default_admin_codes=default_admin_codes
    )
    query_columns = list(list_properties)
    if need_admin_codes and "communes_code" not in query_columns:
        query_columns.append("communes_code")

    params: dict = {}
    list_properties_sql = ", ".join(query_columns)
    query = (
        f"SELECT {list_properties_sql} FROM interco WHERE 1=1"
        + interco_filter_sql(params, natures=natures, type_filter=type_filter)
    )

    if code is not None:
        query += " AND siren = :siren"
        params["siren"] = code

    if nom_query is not None and has_nom_recherche:
        query += nom_search_sql_clause(params, nom_query)
    elif nom_query is not None:
        params["nom_like"] = f"%{nom.strip()}%"
        query += " AND nom LIKE :nom_like"

    if nom_query is not None:
        if has_nom_recherche:
            query += " LIMIT :candidate_limit"
            params["candidate_limit"] = NOM_SEARCH_CANDIDATE_LIMIT
        else:
            query += " ORDER BY nom"
    else:
        query += " ORDER BY nom"
        if offset:
            query += " OFFSET :offset"
            params["offset"] = offset
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = limit

    results = db.execute(text(query), params).fetchall()

    nom_idx = (
        list_properties.index("nom_recherche")
        if has_nom_recherche and "nom_recherche" in list_properties
        else None
    )
    nom_label_idx = list_properties.index("nom")
    code_idx = list_properties.index("siren")

    parsed_codes_per_row: list[Optional[list[str]]] = []
    admin_map = None
    if need_admin_codes:
        all_commune_codes: set[str] = set()
        communes_code_idx = query_columns.index("communes_code")
        for row in results:
            commune_codes = parse_communes_code(row[communes_code_idx])
            parsed_codes_per_row.append(commune_codes)
            all_commune_codes.update(commune_codes)
        admin_map = load_commune_admin_codes_map(db, all_commune_codes)
    else:
        parsed_codes_per_row = [None] * len(results)

    scored_rows: list[tuple[float, tuple, Optional[list[str]]]] = []
    for row, commune_codes in zip(results, parsed_codes_per_row):
        row_props = row[: len(list_properties)]
        match_score = 0.0
        if nom_query is not None:
            candidate = (
                row_props[nom_idx]
                if nom_idx is not None
                else normalize_string(row_props[nom_label_idx] or "")
            )
            match_score = nom_match_score(nom_query, candidate or "")
            if match_score <= 0:
                continue
        scored_rows.append((match_score, row_props, commune_codes))

    if nom_query is not None:
        scored_rows.sort(key=lambda item: (-item[0], item[1][code_idx]))
        if limit is not None:
            scored_rows = scored_rows[offset : offset + limit]
        elif offset:
            scored_rows = scored_rows[offset:]

    entities = []
    for match_score, row, commune_codes in scored_rows:
        props = build_interco_properties(
            row,
            list_properties,
            requested_fields,
            fields,
            commune_codes=commune_codes,
            admin_map=admin_map,
            default_admin_codes=default_admin_codes,
        )
        if nom_query is not None:
            props["_score"] = match_score
        entities.append(props)
    return entities


def list_intercommunalite_entities(
    db: Session,
    *,
    nom: Optional[str] = None,
    type_filter: Optional[str] = None,
    fields: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    return list_interco_entities(
        db,
        nom=nom,
        type_filter=type_filter,
        fields=fields,
        limit=limit,
        offset=offset,
    )


def get_interco_entity_by_code(
    code: str,
    fields: Optional[str],
    format: Literal["json", "geojson"],
    db: Session,
    *,
    natures: Optional[Sequence[str]] = None,
    not_found_detail: str,
    entity_label: str = "intercommunalité",
    default_properties: Sequence[str] = INTERCO_DEFAULT_PROPERTIES,
    default_admin_codes: bool = False,
):
    list_properties, requested_fields, _ = resolve_interco_field_lists(
        fields,
        entity_label=entity_label,
        default_properties=default_properties,
    )
    need_admin_codes = _needs_admin_codes(
        fields, requested_fields, default_admin_codes=default_admin_codes
    )
    query_columns = list(list_properties)
    if need_admin_codes and "communes_code" not in query_columns:
        query_columns.append("communes_code")
    if format == "geojson" and "geometry_geojson" not in query_columns:
        query_columns.append("geometry_geojson")

    params: dict = {"code": code}
    list_properties_sql = ", ".join(query_columns)
    result = db.execute(
        text(
            f"SELECT {list_properties_sql} FROM interco WHERE siren = :code"
            + interco_filter_sql(params, natures=natures)
            + " LIMIT 1"
        ),
        params,
    ).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail=not_found_detail)

    row_by_column = {col: result[i] for i, col in enumerate(query_columns)}
    commune_codes = None
    admin_map = None
    if need_admin_codes:
        commune_codes = parse_communes_code(row_by_column.get("communes_code"))
        admin_map = load_commune_admin_codes_map(db, set(commune_codes))
    row = tuple(row_by_column[col] for col in list_properties)
    geom_raw = row_by_column.get("geometry_geojson")

    properties = build_interco_properties(
        row,
        list_properties,
        requested_fields,
        fields,
        commune_codes=commune_codes,
        admin_map=admin_map,
        default_admin_codes=default_admin_codes,
    )

    if format == "geojson":
        geometry = parse_geometry(geom_raw) if geom_raw else None
        return {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry,
        }

    return properties


def get_groupement_commune_codes(db: Session, code: str) -> list[str]:
    """Communes liées au groupement via la table interco_commune (compétences OUI)."""
    if not interco_exists(db, code):
        raise HTTPException(
            status_code=404,
            detail=f"Groupement de collectivités territoriales avec le code {code} non trouvé",
        )

    try:
        rows = db.execute(
            text("""
                SELECT DISTINCT commune_code
                FROM interco_commune
                WHERE interco_siren = :code
                  AND commune_code IS NOT NULL
                  AND TRIM(commune_code) != ''
                ORDER BY commune_code
            """),
            {"code": code},
        ).fetchall()
    except Exception:
        rows = []

    return [row[0] for row in rows]


def get_intercommunalite_entity_by_code(
    code: str,
    fields: Optional[str],
    format: Literal["json", "geojson"],
    db: Session,
):
    return get_interco_entity_by_code(
        code,
        fields,
        format,
        db,
        not_found_detail=f"Intercommunalité avec le code {code} non trouvée",
    )


INTERCOMMUNALITE_LIST_PARAMS = {
    "nom": Query(None, description="Recherche par nom (partiel, normalisé)"),
    "code": Query(None, description="Recherche par code SIREN"),
    "type": Query(
        None,
        description="Filtrer par nature juridique (CC, CA, CU, METRO, SIVOM, etc.)",
    ),
    "fields": Query(
        None,
        description="Champs à inclure (centre, contour, bbox, surface, population, type, financement, membres_siren, codesDepartements, codesRegions)",
    ),
    "limit": Query(None, ge=1, le=1000, description="Nombre maximum de résultats (optionnel)"),
    "offset": Query(0, ge=0, description="Offset pour la pagination"),
}
