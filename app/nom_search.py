"""
Recherche par nom avec score de pertinence (inspiré api-geo : lunr + boost population).
Le score renvoyé par l'API est absolu entre 0 et 1 (_score ; 1 = égalité exacte).
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional


def nom_match_score(
    query_normalized: str,
    candidate_normalized: str,
    population: Optional[float] = None,
    *,
    boost_population: bool = False,
) -> float:
    """
    Score brut de pertinence (0–1) entre requête et nom_recherche normalisés.
    """
    if not query_normalized or not candidate_normalized:
        return 0.0

    q = query_normalized
    c = candidate_normalized

    if q == c:
        base = 1.0
    elif c.startswith(q):
        base = 0.85 + 0.15 * (len(q) / max(len(c), 1))
    else:
        idx = c.find(q)
        if idx >= 0:
            base = 0.55 if idx == 0 else max(0.2, 0.5 - idx * 0.008)
        else:
            ratio = SequenceMatcher(None, q, c).ratio()
            if ratio < 0.45:
                return 0.0
            base = ratio * 0.35

    if boost_population and population:
        try:
            pop = float(population)
            if pop > 0:
                base = min(1.0, base * (1.0 + pop / 100_000.0))
        except (TypeError, ValueError):
            pass

    return round(min(1.0, max(0.0, base)), 4)


def nom_search_sql_clause(params: dict, nom_recherche: str) -> str:
    """Pré-filtre SQL : sous-chaîne sur nom_recherche (équiv. à = / préfixe / contient)."""
    params["nom_contains"] = f"%{nom_recherche}%"
    return " AND nom_recherche LIKE :nom_contains"


NOM_SEARCH_CANDIDATE_LIMIT = 500
