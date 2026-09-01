import json
from collections import defaultdict

import pandas as pd
from download_urls import COG_URL, MOUVEMENTS_URL


def compute_anciens_codes_communes():
    # Load datasets
    communes = pd.read_csv(COG_URL, dtype=str)
    mouvements = pd.read_csv(MOUVEMENTS_URL, dtype=str)

    # Current communes (COM and ARM)
    communes_actuelles = set(
        communes.loc[
            communes["TYPECOM"].isin(["COM", "ARM"]),
            "COM",
        ]
    )

    # Build successor mapping by iterating in reverse order
    successor_mapping = {}

    mouvements_filtered = mouvements[
        (mouvements["TYPECOM_AV"] == "COM")
        & (mouvements["TYPECOM_AP"] == "COM")
        & (mouvements["COM_AV"] != mouvements["COM_AP"])
    ]

    for _, row in mouvements_filtered.iloc[::-1].iterrows():
        com_av = row["COM_AV"]
        com_ap = row["COM_AP"]

        if com_av in communes_actuelles:
            continue

        successor_mapping[com_av] = com_ap

    def get_successor(code):
        if code in communes_actuelles:
            return code

        successor = successor_mapping.get(code)
        if successor is None:
            raise ValueError(f"Successeur inconnu pour le code {code}")

        return get_successor(successor)

    # Resolve all mappings to the final current commune
    for code in list(successor_mapping):
        successor_mapping[code] = get_successor(code)

    # Equivalent of lodash invertBy()
    anciens_codes = defaultdict(list)
    for ancien, actuel in successor_mapping.items():
        anciens_codes[actuel].append(ancien)

    return dict(anciens_codes)


if __name__ == "__main__":
    anciens_codes = compute_anciens_codes_communes()
    # Example
    print(f"{len(anciens_codes)} current communes have former commune codes.")
    print(json.dumps(anciens_codes))
