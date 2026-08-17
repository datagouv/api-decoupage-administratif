"""
Endpoints et logique métier pour les EPCI (intercommunalités à fiscalité propre).
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.entities.intercommunalites import (
    EPCI_DEFAULT_PROPERTIES,
    INTERCOMMUNALITE_LIST_PARAMS,
    get_interco_entity_by_code,
    interco_exists as _interco_exists,
    interco_filter_sql,
    list_interco_entities,
    parse_communes_code,
)

EPCI_NATURES = ("CA", "CU", "CC", "MET69", "METRO")


def epci_nature_filter_sql() -> str:
    return interco_filter_sql({}, natures=EPCI_NATURES)


def epci_exists(db: Session, code: str) -> bool:
    return _interco_exists(db, code, natures=EPCI_NATURES)


def get_epci_commune_codes(db: Session, code: str) -> list[str]:
    params: dict = {"code": code}
    row = db.execute(
        text(
            "SELECT communes_code FROM interco WHERE siren = :code"
            + interco_filter_sql(params, natures=EPCI_NATURES)
            + " LIMIT 1"
        ),
        params,
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"EPCI avec le code {code} non trouvé",
        )
    return parse_communes_code(row[0])


def list_epci_entities(
    db: Session,
    *,
    nom: Optional[str] = None,
    code: Optional[str] = None,
    fields: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list[dict]:
    return list_interco_entities(
        db,
        nom=nom,
        code=code,
        natures=EPCI_NATURES,
        fields=fields,
        limit=limit,
        offset=offset,
        entity_label="EPCI",
        default_properties=EPCI_DEFAULT_PROPERTIES,
        default_admin_codes=True,
    )


def get_epci_entity_by_code(
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
        natures=EPCI_NATURES,
        not_found_detail=f"EPCI avec le code {code} non trouvé",
        entity_label="EPCI",
        default_properties=EPCI_DEFAULT_PROPERTIES,
        default_admin_codes=True,
    )


EPCI_LIST_PARAMS = {
    "nom": INTERCOMMUNALITE_LIST_PARAMS["nom"],
    "code": INTERCOMMUNALITE_LIST_PARAMS["code"],
    "fields": INTERCOMMUNALITE_LIST_PARAMS["fields"],
    "limit": INTERCOMMUNALITE_LIST_PARAMS["limit"],
    "offset": INTERCOMMUNALITE_LIST_PARAMS["offset"],
}
