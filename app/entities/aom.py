"""
Endpoints et logique métier pour les AOM (Autorités Organisatrices de Mobilité).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import HTTPException, Query
from shapely.geometry import shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.entities.geometry import compute_surface_hectares, parse_geometry
from app.entities.intercommunalites import (
    admin_codes_from_communes,
    load_commune_admin_codes_map,
    parse_communes_code,
)
from app.nom_search import (
    NOM_SEARCH_CANDIDATE_LIMIT,
    nom_match_score,
    nom_search_sql_clause,
)
from app.normalize_string import normalize_string

AOM_MINIMAL_PROPERTIES = ["nom", "siren"]
AOM_DEFAULT_PROPERTIES = (
    "nom",
    "code",
    "nbCommunes",
    "codesDepartements",
    "codesRegions",
)

AOM_API_TO_SQL = {
    "code": "siren",
    "nom": "nom",
    "nbCommunes": "nb_communes",
    "contour": "geometry_geojson",
    "centre": "geometry_geojson",
    "bbox": "geometry_geojson",
    "surface": "geometry_geojson",
}
AOM_SQL_TO_API = {v: k for k, v in AOM_API_TO_SQL.items()}
AOM_COMPUTED_FIELDS = frozenset({"codesDepartements", "codesRegions"})


def resolve_aom_field_lists(fields: Optional[str]):
    if fields:
        requested_fields = [f.strip() for f in fields.split(",") if f.strip()]
        for field in requested_fields:
            if field not in AOM_API_TO_SQL and field not in AOM_COMPUTED_FIELDS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Le champ '{field}' n'est pas reconnu pour les AOM.",
                )
    else:
        requested_fields = []

    if not fields:
        return ["nom", "siren", "nb_communes"], [], False

    list_properties = AOM_MINIMAL_PROPERTIES.copy()
    for field in requested_fields:
        if field in AOM_COMPUTED_FIELDS:
            continue
        sql_col = AOM_API_TO_SQL[field]
        if sql_col not in list_properties:
            list_properties.append(sql_col)
    if (
        any(
            field in requested_fields
            for field in ("contour", "centre", "bbox", "surface")
        )
        and "geometry_geojson" not in list_properties
    ):
        list_properties.append("geometry_geojson")
    return list_properties, requested_fields, True


def aom_nom_recherche_available(db: Session) -> bool:
    try:
        db.execute(text("SELECT nom_recherche FROM aom LIMIT 1"))
        return True
    except Exception:
        return False


def aom_exists(db: Session, code: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM aom WHERE siren = :code LIMIT 1"),
        {"code": code},
    ).fetchone()
    return row is not None


def load_aom_for_commune(
    db: Session,
    commune_code: str,
    commune_siren: Optional[str] = None,
) -> Optional[dict]:
    """AOM associée à une commune : {code, nom} ou None."""
    if not commune_code and not commune_siren:
        return None

    try:
        if commune_code:
            row = db.execute(
                text("""
                    SELECT ac.siren_aom, a.nom
                    FROM aom_commune ac
                    LEFT JOIN aom a ON a.siren = ac.siren_aom
                    WHERE ac.commune_code = :code
                    ORDER BY ac.siren_aom
                    LIMIT 1
                """),
                {"code": commune_code},
            ).fetchone()
            if row and row[0]:
                return {"code": row[0], "nom": row[1]}

        if commune_siren:
            row = db.execute(
                text("""
                    SELECT ac.siren_aom, a.nom
                    FROM aom_commune ac
                    LEFT JOIN aom a ON a.siren = ac.siren_aom
                    WHERE ac.siren_commune = :siren
                    ORDER BY ac.siren_aom
                    LIMIT 1
                """),
                {"siren": commune_siren},
            ).fetchone()
            if row and row[0]:
                return {"code": row[0], "nom": row[1]}
    except Exception:
        return None

    return None


def _needs_admin_codes(fields: Optional[str], requested_fields: List[str]) -> bool:
    return (not fields) or any(
        field in requested_fields for field in ("codesDepartements", "codesRegions")
    )


def build_aom_properties(
    row,
    list_properties: List[str],
    requested_fields: List[str],
    fields: Optional[str],
    *,
    commune_codes: Optional[list[str]] = None,
    admin_map: Optional[dict[str, tuple[Optional[str], Optional[str]]]] = None,
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
        api_field = AOM_SQL_TO_API.get(column_name)
        if not api_field:
            continue
        value = row[i]
        if api_field == "nbCommunes" and value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                pass
        properties[api_field] = value

    if commune_codes is None and communes_code_idx is not None:
        commune_codes = parse_communes_code(row[communes_code_idx])

    include_admin_codes = _needs_admin_codes(fields, requested_fields)
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
    elif not requested_fields:
        allowed = set(AOM_DEFAULT_PROPERTIES)
        properties = {k: v for k, v in properties.items() if k in allowed}
    return properties


def list_aom_entities(
    db: Session,
    *,
    nom: Optional[str] = None,
    fields: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    nom_query = None
    if nom is not None:
        nom_query = normalize_string(nom)
        if not nom_query:
            return []

    list_properties, requested_fields, explicit_fields = resolve_aom_field_lists(fields)
    has_nom_recherche = aom_nom_recherche_available(db)
    if nom_query is not None:
        if has_nom_recherche and "nom_recherche" not in list_properties:
            list_properties.append("nom_recherche")

    need_admin_codes = _needs_admin_codes(fields, requested_fields)
    query_columns = list(list_properties)
    if need_admin_codes and "communes_code" not in query_columns:
        query_columns.append("communes_code")
    if explicit_fields and "nb_communes" not in query_columns:
        if "nbCommunes" in requested_fields or not fields:
            query_columns.append("nb_communes")

    params: dict = {}
    query = f"SELECT {', '.join(query_columns)} FROM aom WHERE 1=1"

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
        props = build_aom_properties(
            row,
            list_properties,
            requested_fields,
            fields,
            commune_codes=commune_codes,
            admin_map=admin_map,
        )
        if nom_query is not None:
            props["_score"] = match_score
        entities.append(props)
    return entities


def get_aom_entity_by_code(
    code: str,
    fields: Optional[str],
    format: Literal["json", "geojson"],
    db: Session,
):
    list_properties, requested_fields, _ = resolve_aom_field_lists(fields)
    need_admin_codes = _needs_admin_codes(fields, requested_fields)
    query_columns = list(list_properties)
    if need_admin_codes and "communes_code" not in query_columns:
        query_columns.append("communes_code")
    if format == "geojson" and "geometry_geojson" not in query_columns:
        query_columns.append("geometry_geojson")

    result = db.execute(
        text(f"SELECT {', '.join(query_columns)} FROM aom WHERE siren = :code LIMIT 1"),
        {"code": code},
    ).fetchone()

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"AOM avec le code {code} non trouvée",
        )

    row_by_column = {col: result[i] for i, col in enumerate(query_columns)}
    commune_codes = None
    admin_map = None
    if need_admin_codes:
        commune_codes = parse_communes_code(row_by_column.get("communes_code"))
        admin_map = load_commune_admin_codes_map(db, set(commune_codes))
    row = tuple(row_by_column[col] for col in list_properties)
    geom_raw = row_by_column.get("geometry_geojson")

    properties = build_aom_properties(
        row,
        list_properties,
        requested_fields,
        fields,
        commune_codes=commune_codes,
        admin_map=admin_map,
    )

    if format == "geojson":
        geometry = parse_geometry(geom_raw) if geom_raw else None
        return {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry,
        }

    return properties


def get_aom_commune_codes(db: Session, code: str) -> list[str]:
    if not aom_exists(db, code):
        raise HTTPException(
            status_code=404,
            detail=f"AOM avec le code {code} non trouvée",
        )

    try:
        rows = db.execute(
            text("""
                SELECT DISTINCT commune_code
                FROM aom_commune
                WHERE siren_aom = :code
                  AND commune_code IS NOT NULL
                  AND TRIM(commune_code) != ''
                ORDER BY commune_code
            """),
            {"code": code},
        ).fetchall()
    except Exception:
        rows = []

    if rows:
        return [row[0] for row in rows]

    row = db.execute(
        text("SELECT communes_code FROM aom WHERE siren = :code LIMIT 1"),
        {"code": code},
    ).fetchone()
    return parse_communes_code(row[0] if row else None)


AOM_LIST_PARAMS = {
    "nom": Query(None, description="Recherche par nom (partiel, normalisé)"),
    "fields": Query(
        None,
        description="Champs à inclure (centre, contour, bbox, surface, nbCommunes, codesDepartements, codesRegions)",
    ),
    "limit": Query(
        None, ge=1, le=1000, description="Nombre maximum de résultats (optionnel)"
    ),
    "offset": Query(0, ge=0, description="Offset pour la pagination"),
}
