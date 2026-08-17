"""Utilitaires géométriques partagés."""

from __future__ import annotations

import json
from typing import Optional, Sequence

from pyproj import Geod
from shapely.geometry import shape

GEOMETRY_RESPONSE_FIELDS = frozenset({"contour", "centre", "bbox", "surface"})

_GEOD = Geod(ellps="WGS84")


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


def centre_geojson_from_shape(geom_shape) -> Optional[dict]:
    if geom_shape is None or geom_shape.is_empty:
        return None
    return {
        "type": "Point",
        "coordinates": [geom_shape.centroid.x, geom_shape.centroid.y],
    }


def bbox_geojson_from_shape(geom_shape) -> Optional[dict]:
    if geom_shape is None or geom_shape.is_empty:
        return None
    minx, miny, maxx, maxy = geom_shape.bounds
    return {
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


def apply_geometry_response_fields(
    properties: dict,
    geom_raw: Optional[str],
    requested_fields: Sequence[str],
) -> None:
    """Renseigne contour, centre, bbox et surface à partir d'une géométrie stockée."""
    if not geom_raw or not any(
        field in requested_fields for field in GEOMETRY_RESPONSE_FIELDS
    ):
        return
    geometry = parse_geometry(geom_raw)
    if not geometry:
        return
    geom_shape = shape(geometry)
    if "contour" in requested_fields:
        properties["contour"] = geometry
    if "centre" in requested_fields:
        properties["centre"] = centre_geojson_from_shape(geom_shape)
    if "bbox" in requested_fields:
        properties["bbox"] = bbox_geojson_from_shape(geom_shape)
    if "surface" in requested_fields:
        properties["surface"] = compute_surface_hectares(geom_shape)


def geometry_shape_from_column(geom_str: Optional[str]):
    """Géométrie Shapely pour tests de distance / appartenance."""
    geometry = parse_geometry(geom_str)
    if not geometry:
        return None
    try:
        return shape(geometry)
    except Exception:
        return None
