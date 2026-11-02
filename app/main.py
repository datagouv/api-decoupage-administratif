"""
API Géo 2 - FastAPI main application
API pour accéder aux données des communes françaises
"""

from typing import List, Literal, Optional, Union
from urllib.parse import parse_qs, urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
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
    COMMUNE_LIST_PARAMS,
    COMMUNES_ASSOCIEES_CONFIG,
    COMMUNES_ASSOCIEES_FIELDS_PARAM,
    COMMUNES_CONFIG,
    CommuneAssocieeDelegueeField,
    CommuneField,
    CommuneGeometry,
    Format,
    get_commune_entity_by_code,
    list_commune_entities,
    resolve_code_departement_filter,
)
from app.entities.departements import (
    DEPARTEMENT_LIST_PARAMS,
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
    REGION_LIST_PARAMS,
    get_region_entity_by_code,
    list_region_entities,
    region_exists,
)
from app.schemas import (
    AomGeoJSONResponse,
    AomResponseSchema,
    CommuneAssocieeDelegueeGeoJSONResponseFeature,
    CommuneAssocieeDelegueeGeoJSONResponseFeatureCollection,
    CommuneAssocieeDelegueeResponseSchema,
    CommuneGeoJSONResponseFeature,
    CommuneGeoJSONResponseFeatureCollection,
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

# Create FastAPI app
app = FastAPI(
    title="API Découpage Administratif",
    description="API pour accéder aux structures administratives territoriales françaises",
    version="1.1.0",
)


@app.middleware("http")
async def manage_csv_collection(request: Request, call_next):
    q_params = dict(parse_qs(request.scope["query_string"].decode("utf-8")))
    specials_fields = ["fields", "type"]
    for special_field in specials_fields:
        if special_field in q_params:
            if len(q_params[special_field]) == 0:
                q_params.pop(special_field, None)
            elif len(q_params[special_field]) == 1:
                q_params[special_field] = [
                    i.strip() for i in q_params[special_field][0].split(",")
                ]
            else:
                pass
    request.scope["query_string"] = urlencode(q_params, True).encode("utf-8")
    response = await call_next(request)
    return response


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


@app.get(
    "/communes/{code}",
    response_model=Union[CommuneResponseSchema, CommuneGeoJSONResponseFeature],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "Commune non trouvée"},
        200: {"description": "Commune trouvée"},
    },
    tags=["Communes"],
    summary="Récupérer les informations concernant une commune",
)
async def get_commune_by_code(
    code: str,
    fields: Optional[list[CommuneField]] = Query(
        None,
        description="Champs à inclure, séparés par des virgules (json et geojson)",
    ),
    geometry: Optional[str] = Query(
        "centre",
        description="Géométrie à utiliser pour la sortie géographique",
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
            code,
            fields,
            format,
            geometry,
            db,
            COMMUNES_CONFIG,
            allow_aom=True,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/communes",
    response_model=Union[
        CommuneResponseSchema,
        List[CommuneResponseSchema],
        CommuneGeoJSONResponseFeatureCollection,
    ],
    response_model_exclude_none=True,
    tags=["Communes"],
    summary="Recherche des communes",
)
async def list_communes(
    nom: Optional[str] = COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = COMMUNE_LIST_PARAMS["codeDepartement"],
    codeRegion: Optional[str] = COMMUNE_LIST_PARAMS["codeRegion"],
    fields: Optional[list[CommuneField]] = COMMUNE_LIST_PARAMS["fields"],
    zone: Optional[str] = COMMUNE_LIST_PARAMS["zone"],
    boost: Optional[str] = COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = COMMUNE_LIST_PARAMS["limit"],
    offset: int = COMMUNE_LIST_PARAMS["offset"],
    code: Optional[str] = COMMUNE_LIST_PARAMS["code"],
    siren: Optional[str] = COMMUNE_LIST_PARAMS["siren"],
    codeEpci: Optional[str] = COMMUNE_LIST_PARAMS["codeEpci"],
    codeParent: Optional[str] = COMMUNE_LIST_PARAMS["codeParent"],
    ancienCode: Optional[str] = COMMUNE_LIST_PARAMS["ancienCode"],
    format: Format = COMMUNE_LIST_PARAMS["format"],
    geometry: CommuneGeometry = COMMUNE_LIST_PARAMS["geometry"],
    type: Optional[list[str]] = COMMUNE_LIST_PARAMS["type"],
    db: Session = Depends(get_db),
):
    """
    Lister les communes (type **COM**).

    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        dep_code = resolve_code_departement_filter(codeDepartement)
        content = list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=codeRegion,
            code=code,
            siren=siren,
            code_epci=codeEpci,
            code_parent=codeParent,
            ancien_code=ancienCode,
            zone=zone,
            fields=fields,
            boost=boost,
            limit=limit,
            offset=offset,
            format=format,
            geometry=geometry,
            type=type,
        )
        if format is not None and format == "geojson":
            return {"type": "FeatureCollection", "features": content}
        else:
            return content
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/communes_associees_deleguees/{code}",
    response_model=Union[
        CommuneAssocieeDelegueeResponseSchema,
        CommuneAssocieeDelegueeGeoJSONResponseFeature,
    ],
    response_model_exclude_none=True,
    responses={
        404: {"model": ErrorResponse, "description": "Entité non trouvée"},
        200: {"description": "Entité trouvée"},
    },
    tags=["Communes associées et déléguées"],
    summary="Récupérer les informations concernant une commune associée ou déléguée",
)
async def get_commune_associee_deleguee_by_code(
    code: str,
    fields: Optional[list[CommuneAssocieeDelegueeField]] = Query(
        None,
        description="Champs à inclure (siren, population, codesPostaux, zone interdits)",
    ),
    geometry: Optional[str] = Query(
        "centre",
        description="Géométrie à utiliser pour la sortie géographique",
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
            code,
            fields,
            format,
            geometry,
            db,
            COMMUNES_ASSOCIEES_CONFIG,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/communes_associees_deleguees",
    response_model=Union[
        CommuneAssocieeDelegueeResponseSchema,
        List[CommuneAssocieeDelegueeResponseSchema],
        CommuneAssocieeDelegueeGeoJSONResponseFeatureCollection,
    ],
    response_model_exclude_none=True,
    tags=["Communes associées et déléguées"],
    summary="Recherche des communes associées et/ou déléguées",
)
async def list_communes_associees_deleguees(
    nom: Optional[str] = COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = COMMUNE_LIST_PARAMS["lon"],
    codeDepartement: Optional[str] = COMMUNE_LIST_PARAMS["codeDepartement"],
    codeRegion: Optional[str] = COMMUNE_LIST_PARAMS["codeRegion"],
    fields: Optional[
        list[CommuneAssocieeDelegueeField]
    ] = COMMUNES_ASSOCIEES_FIELDS_PARAM,
    boost: Optional[str] = COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = COMMUNE_LIST_PARAMS["limit"],
    offset: int = COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Lister les communes associées (**COMA**) et déléguées (**COMD**).

    Champs interdits dans `fields` : siren, population, codesPostaux, zone.
    Recherche **nom** : tri par pertinence, champ `_score` (0–1, absolu).
    """
    try:
        dep_code = resolve_code_departement_filter(codeDepartement)
        return list_commune_entities(
            db,
            COMMUNES_ASSOCIEES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_departement=dep_code,
            region=codeRegion,
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
    "/departements",
    response_model=List[DepartementResponseSchema],
    response_model_exclude_none=True,
    tags=["Départements"],
    summary="Recherche des départements",
)
async def list_departements(
    nom: Optional[str] = DEPARTEMENT_LIST_PARAMS["nom"],
    zone: Optional[str] = DEPARTEMENT_LIST_PARAMS["zone"],
    code: Optional[str] = DEPARTEMENT_LIST_PARAMS["code"],
    codeRegion: Optional[str] = DEPARTEMENT_LIST_PARAMS["codeRegion"],
    fields: Optional[list[str]] = DEPARTEMENT_LIST_PARAMS["fields"],
    format: Optional[str] = DEPARTEMENT_LIST_PARAMS["format"],
    geometry: Optional[str] = DEPARTEMENT_LIST_PARAMS["geometry"],
    limit: Optional[int] = DEPARTEMENT_LIST_PARAMS["limit"],
    offset: int = DEPARTEMENT_LIST_PARAMS["offset"],
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
            code=code,
            region=codeRegion,
            fields=fields,
            format=format,
            geometry=geometry,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/departements/{code}/communes",
    response_model=Union[
        CommuneResponseSchema,
        List[CommuneResponseSchema],
        CommuneGeoJSONResponseFeatureCollection,
    ],
    response_model_exclude_none=True,
    tags=["Départements", "Communes"],
    summary="Renvoie les communes d'un département",
)
async def list_departement_communes(
    code: str,
    nom: Optional[str] = COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = COMMUNE_LIST_PARAMS["codePostal"],
    codeRegion: Optional[str] = COMMUNE_LIST_PARAMS["codeRegion"],
    fields: Optional[list[CommuneField]] = COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = COMMUNE_LIST_PARAMS["limit"],
    offset: int = COMMUNE_LIST_PARAMS["offset"],
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
            region=codeRegion,
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
    summary="Récupérer les informations concernant un département",
)
async def get_departement_by_code(
    code: str,
    fields: Optional[list[str]] = Query(
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


@app.get(
    "/regions",
    response_model=List[RegionResponseSchema],
    response_model_exclude_none=True,
    tags=["Régions"],
    summary="Recherche des régions",
)
async def list_regions(
    nom: Optional[str] = REGION_LIST_PARAMS["nom"],
    zone: Optional[str] = REGION_LIST_PARAMS["zone"],
    code: Optional[str] = REGION_LIST_PARAMS["code"],
    fields: Optional[list[str]] = REGION_LIST_PARAMS["fields"],
    format: Optional[str] = REGION_LIST_PARAMS["format"],
    geometry: Optional[str] = REGION_LIST_PARAMS["geometry"],
    limit: int = REGION_LIST_PARAMS["limit"],
    offset: int = REGION_LIST_PARAMS["offset"],
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
            code=code,
            fields=fields,
            format=format,
            geometry=geometry,
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
    tags=["Régions", "Départements"],
    summary="Renvoie les départements d'une région",
)
async def list_region_departements(
    code: str,
    nom: Optional[str] = DEPARTEMENT_LIST_PARAMS["nom"],
    fields: Optional[list[str]] = DEPARTEMENT_LIST_PARAMS["fields"],
    limit: Optional[int] = DEPARTEMENT_LIST_PARAMS["limit"],
    offset: int = DEPARTEMENT_LIST_PARAMS["offset"],
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
    response_model=Union[
        CommuneResponseSchema,
        List[CommuneResponseSchema],
        CommuneGeoJSONResponseFeatureCollection,
    ],
    response_model_exclude_none=True,
    tags=["Régions", "Communes"],
    summary="Renvoie les communes d'une région",
)
async def list_region_communes(
    code: str,
    nom: Optional[str] = COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = COMMUNE_LIST_PARAMS["codeDepartement"],
    fields: Optional[list[CommuneField]] = COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = COMMUNE_LIST_PARAMS["limit"],
    offset: int = COMMUNE_LIST_PARAMS["offset"],
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
        dep_code = resolve_code_departement_filter(codeDepartement)
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
    summary="Récupérer les informations concernant une région",
)
async def get_region_by_code(
    code: str,
    fields: Optional[list[str]] = Query(
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
    summary="Recherche des EPCI",
)
async def list_epcis(
    nom: Optional[str] = EPCI_LIST_PARAMS["nom"],
    code: Optional[str] = EPCI_LIST_PARAMS["code"],
    fields: Optional[list[str]] = EPCI_LIST_PARAMS["fields"],
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
            code=code,
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
    response_model=Union[
        CommuneResponseSchema,
        List[CommuneResponseSchema],
        CommuneGeoJSONResponseFeatureCollection,
    ],
    response_model_exclude_none=True,
    tags=["EPCI", "Communes"],
    summary="Renvoie les communes d'un EPCI",
)
async def list_epci_communes(
    code: str,
    nom: Optional[str] = COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = COMMUNE_LIST_PARAMS["codeDepartement"],
    codeRegion: Optional[str] = COMMUNE_LIST_PARAMS["codeRegion"],
    fields: Optional[list[CommuneField]] = COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = COMMUNE_LIST_PARAMS["limit"],
    offset: int = COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes membres de l'EPCI (type **COM**), mêmes propriétés et filtres que `GET /communes`.
    Champ **competences** (`fields=competences`) : compétences OUI depuis **interco_commune**.
    """
    try:
        commune_codes = get_epci_commune_codes(db, code)
        dep_code = resolve_code_departement_filter(codeDepartement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=codeRegion,
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
    summary="Récupérer les informations concernant un EPCI",
)
async def get_epci_by_code(
    code: str,
    fields: Optional[list[str]] = Query(
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
    fields: Optional[list[str]] = INTERCOMMUNALITE_LIST_PARAMS["fields"],
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
    response_model=Union[
        CommuneResponseSchema,
        List[CommuneResponseSchema],
        CommuneGeoJSONResponseFeatureCollection,
    ],
    response_model_exclude_none=True,
    tags=["Intercommunalités", "Communes"],
)
async def list_groupement_communes(
    code: str,
    nom: Optional[str] = COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = COMMUNE_LIST_PARAMS["codeDepartement"],
    codeRegion: Optional[str] = COMMUNE_LIST_PARAMS["codeRegion"],
    fields: Optional[list[CommuneField]] = COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = COMMUNE_LIST_PARAMS["limit"],
    offset: int = COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes liées au groupement via **interco_commune** (type **COM**),
    mêmes propriétés et filtres que `GET /communes`.
    Champ **competences** (`fields=competences`) : compétences OUI depuis **interco_commune**.
    """
    try:
        commune_codes = get_groupement_commune_codes(db, code)
        dep_code = resolve_code_departement_filter(codeDepartement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=codeRegion,
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
        IntercommunaliteResponseSchema,
        IntercommunaliteGeoJSONResponse,
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
    fields: Optional[list[str]] = Query(
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
    fields: Optional[list[str]] = AOM_LIST_PARAMS["fields"],
    format: Optional[str] = AOM_LIST_PARAMS["format"],
    geometry: Optional[str] = AOM_LIST_PARAMS["geometry"],
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
            format=format,
            geometry=geometry,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur serveur: {str(e)}")


@app.get(
    "/aom/{code}/communes",
    response_model=Union[
        CommuneResponseSchema,
        List[CommuneResponseSchema],
        CommuneGeoJSONResponseFeatureCollection,
    ],
    response_model_exclude_none=True,
    tags=["AOM", "Communes"],
)
async def list_aom_communes(
    code: str,
    nom: Optional[str] = COMMUNE_LIST_PARAMS["nom"],
    lat: Optional[float] = COMMUNE_LIST_PARAMS["lat"],
    lon: Optional[float] = COMMUNE_LIST_PARAMS["lon"],
    codePostal: Optional[str] = COMMUNE_LIST_PARAMS["codePostal"],
    codeDepartement: Optional[str] = COMMUNE_LIST_PARAMS["codeDepartement"],
    codeRegion: Optional[str] = COMMUNE_LIST_PARAMS["codeRegion"],
    fields: Optional[list[CommuneField]] = COMMUNE_LIST_PARAMS["fields"],
    boost: Optional[str] = COMMUNE_LIST_PARAMS["boost"],
    limit: Optional[int] = COMMUNE_LIST_PARAMS["limit"],
    offset: int = COMMUNE_LIST_PARAMS["offset"],
    db: Session = Depends(get_db),
):
    """
    Communes membres de l'AOM (type **COM**), mêmes propriétés et filtres que `GET /communes`.
    """
    try:
        commune_codes = get_aom_commune_codes(db, code)
        dep_code = resolve_code_departement_filter(codeDepartement)
        return list_commune_entities(
            db,
            COMMUNES_CONFIG,
            nom=nom,
            lat=lat,
            lon=lon,
            code_postal=codePostal,
            code_departement=dep_code,
            region=codeRegion,
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
    fields: Optional[list[str]] = Query(
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
