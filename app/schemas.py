"""
Pydantic schemas for API request/response validation
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class CommuneResponseSchema(BaseModel):
    """Schema for commune endpoint"""
    nom: str = Field(..., description="Nom de la commune")
    code: str = Field(..., description="Code INSEE de la commune")
    score: Optional[float] = Field(
        None,
        validation_alias="_score",
        serialization_alias="_score",
        description="Pertinence de la recherche par nom (0–1 ; 1 = correspondance exacte du nom normalisé)",
    )
    chefLieu: Optional[str] = Field(
        None, description="Code INSEE de la commune chef-lieu (COMD/COMA)"
    )
    type: Optional[str] = Field(
        None,
        description="Type d'entité : commune-deleguee (COMD) ou commune-associee (COMA)",
    )
    codeDepartement: Optional[str] = Field(None, description="Code département")
    departement: Optional[Dict[str, Any]] = Field(None, description="Département {code, nom}")
    siren: Optional[str] = Field(None, description="SIREN de la commune")
    codeEpci: Optional[str] = Field(None, description="Code de l'EPCI parente")
    epci: Optional[Dict[str, Any]] = Field(None, description="EPCI {code, nom}")
    aom: Optional[Dict[str, Any]] = Field(
        None, description="AOM associée à la commune {code, nom}"
    )
    codeRegion: Optional[str] = Field(None, description="Code région")
    region: Optional[Dict[str, Any]] = Field(None, description="Région {code, nom}")
    codesPostaux: Optional[List[str]] = Field(None, description="Liste des codes postaux de la commune (La Poste)")
    population: Optional[float] = Field(None, description="Population")
    surface: Optional[float] = Field(None, description="Surface de la commune en hectares")
    zone: Optional[str] = Field(None, description="Zone : metro, drom ou com")
    contour: Optional[Dict[str, Any]] = Field(None, description="Contour GeoJSON de la commune")
    centre: Optional[Dict[str, Any]] = Field(None, description="Centre GeoJSON (Point) de la commune")
    bbox: Optional[Dict[str, Any]] = Field(None, description="Bounding box GeoJSON (Polygon)")
    mairie: Optional[Dict[str, Any]] = Field(None, description="Point GeoJSON proxy de la mairie")
    intercommunalites: Optional[List[Dict[str, Any]]] = Field(None, description="Intercommunalités associées à la commune")
    competences: Optional[List[str]] = Field(
        None,
        description="Compétences exercées par l'EPCI/groupement pour cette commune (interco_commune)",
    )


class DepartementResponseSchema(BaseModel):
    """Schema for departement endpoints"""
    nom: str = Field(..., description="Nom du département")
    code: str = Field(..., description="Code département (ex: 75, 2A)")
    codeRegion: Optional[str] = Field(None, description="Code région")
    score: Optional[float] = Field(
        None,
        validation_alias="_score",
        serialization_alias="_score",
        description="Pertinence de la recherche par nom (0–1 ; 1 = correspondance exacte)",
    )
    codeChefLieu: Optional[str] = Field(None, description="Code INSEE de la commune chef-lieu")
    nomEnrichi: Optional[str] = Field(None, description="Nom enrichi")
    nomMajuscules: Optional[str] = Field(None, description="Nom en majuscules")
    surface: Optional[float] = Field(None, description="Surface en hectares")
    contour: Optional[Dict[str, Any]] = Field(None, description="Contour GeoJSON")
    centre: Optional[Dict[str, Any]] = Field(None, description="Centre GeoJSON (Point)")
    bbox: Optional[Dict[str, Any]] = Field(None, description="Bounding box GeoJSON (Polygon)")


class RegionResponseSchema(BaseModel):
    """Schema for region endpoints"""
    nom: str = Field(..., description="Nom de la région")
    code: str = Field(..., description="Code région")
    score: Optional[float] = Field(
        None,
        validation_alias="_score",
        serialization_alias="_score",
        description="Pertinence de la recherche par nom (0–1 ; 1 = correspondance exacte)",
    )
    codeChefLieu: Optional[str] = Field(None, description="Code INSEE de la commune chef-lieu")
    nomEnrichi: Optional[str] = Field(None, description="Nom enrichi")
    nomMajuscules: Optional[str] = Field(None, description="Nom en majuscules")
    surface: Optional[float] = Field(None, description="Surface en hectares")
    contour: Optional[Dict[str, Any]] = Field(None, description="Contour GeoJSON")
    centre: Optional[Dict[str, Any]] = Field(None, description="Centre GeoJSON (Point)")
    bbox: Optional[Dict[str, Any]] = Field(None, description="Bounding box GeoJSON (Polygon)")


class EpciResponseSchema(BaseModel):
    """Schema for EPCI endpoints"""
    nom: str = Field(..., description="Nom de l'EPCI")
    code: str = Field(..., description="Code SIREN de l'EPCI")
    score: Optional[float] = Field(
        None,
        validation_alias="_score",
        serialization_alias="_score",
        description="Pertinence de la recherche par nom (0–1 ; 1 = correspondance exacte)",
    )
    codesDepartements: Optional[List[str]] = Field(
        None, description="Codes départements des communes membres"
    )
    codesRegions: Optional[List[str]] = Field(
        None, description="Codes régions des communes membres"
    )
    population: Optional[float] = Field(None, description="Population")
    type: Optional[str] = Field(None, description="Nature juridique (CA, CU, CC, METRO, MET69)")
    financement: Optional[str] = Field(None, description="Mode de financement")
    membres_siren: Optional[List[str]] = Field(
        None, description="SIREN des membres (communes et groupements)"
    )
    surface: Optional[float] = Field(None, description="Surface en hectares")
    contour: Optional[Dict[str, Any]] = Field(None, description="Contour GeoJSON")
    centre: Optional[Dict[str, Any]] = Field(None, description="Centre GeoJSON (Point)")
    bbox: Optional[Dict[str, Any]] = Field(None, description="Bounding box GeoJSON (Polygon)")


class IntercommunaliteResponseSchema(EpciResponseSchema):
    """Schema for intercommunalité endpoints (mêmes champs que EPCI)."""


class IntercommunaliteGeoJSONResponse(BaseModel):
    """Schema for intercommunalité GeoJSON response"""
    type: str = "Feature"
    properties: Dict[str, Any] = Field(..., description="Propriétés de l'intercommunalité")
    geometry: Optional[Dict[str, Any]] = Field(None, description="Géométrie au format GeoJSON")


class EpciGeoJSONResponse(BaseModel):
    """Schema for EPCI GeoJSON response"""
    type: str = "Feature"
    properties: Dict[str, Any] = Field(..., description="Propriétés de l'EPCI")
    geometry: Optional[Dict[str, Any]] = Field(None, description="Géométrie au format GeoJSON")


class AomResponseSchema(BaseModel):
    """Schema for AOM endpoints"""
    nom: str = Field(..., description="Nom de l'AOM")
    code: str = Field(..., description="Code SIREN de l'AOM")
    score: Optional[float] = Field(
        None,
        validation_alias="_score",
        serialization_alias="_score",
        description="Pertinence de la recherche par nom (0–1 ; 1 = correspondance exacte)",
    )
    nbCommunes: Optional[int] = Field(None, description="Nombre de communes membres")
    codesDepartements: Optional[List[str]] = Field(
        None, description="Codes départements des communes membres"
    )
    codesRegions: Optional[List[str]] = Field(
        None, description="Codes régions des communes membres"
    )
    surface: Optional[float] = Field(None, description="Surface en hectares")
    contour: Optional[Dict[str, Any]] = Field(None, description="Contour GeoJSON")
    centre: Optional[Dict[str, Any]] = Field(None, description="Centre GeoJSON (Point)")
    bbox: Optional[Dict[str, Any]] = Field(None, description="Bounding box GeoJSON (Polygon)")


class AomGeoJSONResponse(BaseModel):
    """Schema for AOM GeoJSON response"""
    type: str = "Feature"
    properties: Dict[str, Any] = Field(..., description="Propriétés de l'AOM")
    geometry: Optional[Dict[str, Any]] = Field(None, description="Géométrie au format GeoJSON")


class RegionGeoJSONResponse(BaseModel):
    """Schema for region GeoJSON response"""
    type: str = "Feature"
    properties: Dict[str, Any] = Field(..., description="Propriétés de la région")
    geometry: Optional[Dict[str, Any]] = Field(None, description="Géométrie au format GeoJSON")


class DepartementGeoJSONResponse(BaseModel):
    """Schema for departement GeoJSON response"""
    type: str = "Feature"
    properties: Dict[str, Any] = Field(..., description="Propriétés du département")
    geometry: Optional[Dict[str, Any]] = Field(None, description="Géométrie au format GeoJSON")


class CommuneGeoJSONResponse(BaseModel):
    """Schema for GeoJSON response"""
    type: str = "Feature"
    properties: Dict[str, Any] = Field(..., description="Propriétés de la commune")
    geometry: Optional[Dict[str, Any]] = Field(None, description="Géométrie au format GeoJSON")


class ErrorResponse(BaseModel):
    """Schema for error responses"""
    detail: str = Field(..., description="Message d'erreur")

