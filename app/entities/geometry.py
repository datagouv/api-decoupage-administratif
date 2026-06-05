"""Utilitaires géométriques partagés."""

from __future__ import annotations

import json
from typing import Optional

from pyproj import Geod
from shapely import wkt
from shapely.geometry import mapping, shape

_GEOD = Geod(ellps="WGS84")

# Helper function to parse geometry
def parse_geometry(geom_str):
    """
    Parse geometry from either GeoJSON or WKT format
    Returns a GeoJSON geometry dict or None
    """
    if not geom_str:
        return None
    
    # Try to parse as JSON first (GeoJSON)
    try:
        return json.loads(geom_str)
    except (json.JSONDecodeError, ValueError):
        pass
    
    # Try to parse as WKT
    try:
        geom = wkt.loads(geom_str)
        return mapping(geom)
    except Exception:
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
    if not geom_str:
        return None
    try:
        if isinstance(geom_str, str) and geom_str.strip().startswith("{"):
            return shape(json.loads(geom_str))
        return wkt.loads(geom_str)
    except Exception:
        return None
