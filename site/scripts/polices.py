"""Génère le sous-ensemble WOFF2 de la police Luciole (latin + ponctuation française).

Usage (depuis scanner/, qui fournit fonttools et brotli) :
    uv run python ../site/scripts/polices.py /chemin/vers/Luciole-Regular.ttf /chemin/vers/Luciole-Bold.ttf

Luciole © Laurent Bourcellier & Jonathan Perez, licence CC-BY 4.0
(https://creativecommons.org/licenses/by/4.0/legalcode.fr).
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset

DOSSIER_SORTIE = Path(__file__).resolve().parents[1] / "public" / "polices"
PLAGES_UNICODE = (
    "U+0020-007E,U+00A0-00FF,U+0152-0153,U+0178,U+2009,U+2013-2014,U+2018-201E,"
    "U+2022,U+2026,U+202F,U+20AC,U+2192,U+2212"
)


def generer(source: Path) -> Path:
    sortie = DOSSIER_SORTIE / f"{source.stem}.woff2"
    subset.main(
        [
            str(source),
            f"--unicodes={PLAGES_UNICODE}",
            "--flavor=woff2",
            "--layout-features=kern,liga,calt,locl",
            "--name-IDs=0,1,2,3,4,5,6,13,14",
            "--no-hinting",
            f"--output-file={sortie}",
        ]
    )
    return sortie


if __name__ == "__main__":
    DOSSIER_SORTIE.mkdir(parents=True, exist_ok=True)
    for argument in sys.argv[1:]:
        chemin = generer(Path(argument))
        print(f"{chemin.name} : {chemin.stat().st_size // 1024} Ko")
