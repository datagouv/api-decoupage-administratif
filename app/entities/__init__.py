"""Couche métier des entités géographiques."""

from app.entities.communes import (
    COMMUNES_ASSOCIEES_CONFIG,
    COMMUNES_CONFIG,
    COMMUNE_LIST_PARAMS,
    get_commune_entity_by_code,
    list_commune_entities,
    resolve_code_departement_filter,
)
from app.entities.departements import (
    departement_exists,
    get_departement_entity_by_code,
    list_departement_entities,
)
from app.entities.geometry import parse_geometry
from app.entities.regions import (
    get_region_entity_by_code,
    list_region_entities,
    region_exists,
)
from app.entities.epcis import (
    epci_exists,
    get_epci_commune_codes,
    get_epci_entity_by_code,
    list_epci_entities,
)
from app.entities.intercommunalites import (
    get_groupement_commune_codes,
    get_intercommunalite_entity_by_code,
    list_intercommunalite_entities,
)
from app.entities.aom import (
    get_aom_commune_codes,
    get_aom_entity_by_code,
    list_aom_entities,
)
