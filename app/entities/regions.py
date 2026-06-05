"""
Endpoints et logique métier pour les régions.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.entities.geometry import parse_geometry

from app.nom_search import (
    NOM_SEARCH_CANDIDATE_LIMIT,
    nom_match_score,
    nom_search_sql_clause,
)
from app.normalize_string import normalize_string

REGION_MINIMAL_PROPERTIES = ["nom", "code_region"]
REGION_DEFAULT_PROPERTIES = ("nom", "code_region")

REGION_API_TO_SQL = {
    "code": "code_region",
    "nom": "nom",
    "codeChefLieu": "code_chef_lieu",
    "nomEnrichi": "nom_enrichi",
    "nomMajuscules": "nom_majuscules",
}
REGION_SQL_TO_API = {v: k for k, v in REGION_API_TO_SQL.items()}


def regions_nom_recherche_available(db: Session) -> bool:
    try:
        db.execute(text("SELECT nom_recherche FROM regions LIMIT 1"))
        return True
    except Exception:
        return False


def resolve_region_field_lists(fields: Optional[str]):
    if fields:
        requested_fields = [f.strip() for f in fields.split(",") if f.strip()]
        for field in requested_fields:
            if field not in REGION_API_TO_SQL:
                raise HTTPException(
                    status_code=400,
                    detail=f"Le champ '{field}' n'est pas reconnu pour les régions.",
                )
    else:
        requested_fields = []

    if not fields:
        return list(REGION_DEFAULT_PROPERTIES), [], False

    list_properties = REGION_MINIMAL_PROPERTIES.copy()
    for field in requested_fields:
        sql_col = REGION_API_TO_SQL[field]
        if sql_col not in list_properties:
            list_properties.append(sql_col)
    return list_properties, requested_fields, True


def build_region_properties(
    row,
    list_properties: List[str],
    requested_fields: List[str],
    fields: Optional[str],
) -> dict:
    properties = {}
    for i, column_name in enumerate(list_properties):
        api_field = REGION_SQL_TO_API.get(column_name)
        if not api_field:
            continue
        properties[api_field] = row[i]

    if fields:
        allowed = {"nom", "code"} | set(requested_fields)
        properties = {k: v for k, v in properties.items() if k in allowed}
    return properties


def region_exists(db: Session, code: str) -> bool:
    row = db.execute(
        text("SELECT 1 FROM regions WHERE code_region = :code LIMIT 1"),
        {"code": code},
    ).fetchone()
    return row is not None


def list_region_entities(
    db: Session,
    *,
    nom: Optional[str] = None,
    fields: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    nom_query = None
    if nom is not None:
        nom_query = normalize_string(nom)
        if not nom_query:
            return []

    list_properties, requested_fields, _ = resolve_region_field_lists(fields)
    has_nom_recherche = regions_nom_recherche_available(db)
    if nom_query is not None:
        if has_nom_recherche and "nom_recherche" not in list_properties:
            list_properties.append("nom_recherche")

    list_properties_sql = ", ".join(list_properties)
    query = f"SELECT {list_properties_sql} FROM regions WHERE 1=1"
    params: dict = {}

    if nom_query is not None and has_nom_recherche:
        query += nom_search_sql_clause(params, nom_query)

    if nom_query is not None:
        if has_nom_recherche:
            query += " LIMIT :candidate_limit"
            params["candidate_limit"] = NOM_SEARCH_CANDIDATE_LIMIT
        else:
            query += " ORDER BY nom"
    else:
        query += " ORDER BY code_region LIMIT :limit OFFSET :offset"
        params["limit"] = limit
        params["offset"] = offset

    results = db.execute(text(query), params).fetchall()

    nom_idx = (
        list_properties.index("nom_recherche")
        if has_nom_recherche and "nom_recherche" in list_properties
        else None
    )
    nom_label_idx = list_properties.index("nom")

    scored_rows: list[tuple[float, tuple]] = []
    for row in results:
        match_score = 0.0
        if nom_query is not None:
            candidate = (
                row[nom_idx]
                if nom_idx is not None
                else normalize_string(row[nom_label_idx] or "")
            )
            match_score = nom_match_score(nom_query, candidate or "")
            if match_score <= 0:
                continue
        scored_rows.append((match_score, row))

    if nom_query is not None:
        code_idx = list_properties.index("code_region")
        scored_rows.sort(key=lambda item: (-item[0], item[1][code_idx]))
        scored_rows = scored_rows[offset : offset + limit]

    regions = []
    for match_score, row in scored_rows:
        props = build_region_properties(row, list_properties, requested_fields, fields)
        if nom_query is not None:
            props["_score"] = match_score
        regions.append(props)
    return regions


def get_region_entity_by_code(
    code: str,
    fields: Optional[str],
    format: Literal["json", "geojson"],
    db: Session,
):
    list_properties, requested_fields, _ = resolve_region_field_lists(fields)
    query_columns = list(list_properties)
    if format == "geojson" and "geometry_geojson" not in query_columns:
        query_columns.append("geometry_geojson")

    list_properties_sql = ", ".join(query_columns)
    result = db.execute(
        text(
            f"SELECT {list_properties_sql} FROM regions WHERE code_region = :code"
        ),
        {"code": code},
    ).fetchone()

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Région avec le code {code} non trouvée",
        )

    if format == "geojson":
        row = result
        geom_raw = None
        if len(query_columns) > len(list_properties):
            geom_raw = row[len(list_properties)]
            row = row[: len(list_properties)]
        properties = build_region_properties(
            row, list_properties, requested_fields, fields
        )
        geometry = parse_geometry(geom_raw) if geom_raw else None
        return {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry,
        }

    return build_region_properties(result, list_properties, requested_fields, fields)


REGION_LIST_PARAMS = {
    "nom": Query(None, description="Recherche par nom (partiel, normalisé)"),
    "fields": Query(None, description="Liste des champs à inclure, séparés par des virgules"),
    "limit": Query(100, ge=1, le=1000, description="Nombre maximum de résultats"),
    "offset": Query(0, ge=0, description="Offset pour la pagination"),
}
