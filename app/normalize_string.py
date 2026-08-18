"""
Normalisation des noms pour la recherche (aligné api-geo normalizeString).
"""

import re
import unicodedata


def normalize_string(nom: str) -> str:
    if nom is None:
        return ""
    s = str(nom).lower()
    s = re.sub(r" [dl]'", "", s)
    s = re.sub(r"^[dl]'", "", s)
    s = s.replace("-", " ")
    s = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z]", "", s)
