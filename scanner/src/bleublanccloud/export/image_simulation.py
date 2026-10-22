"""Images de partage (Open Graph, 1200 × 630) des préréglages du simulateur « Et si… ? ».

Rendues par le serveur avec le moteur PNG en Python pur (`export/raster.py`), à partir des
résultats du moteur de simulation : aucun navigateur, aucune ressource externe. Le chiffre
affiché est recalculé à chaque publication.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from bleublanccloud.export.carte_png import (
    BLEU_FRANCE,
    DOSSIER_POLICES,
    FOND,
    ROUGE_FRANCE,
    SURFACE,
    TEXTE,
    TEXTE_SECONDAIRE,
    date_en_francais,
)
from bleublanccloud.export.raster import Image, Police, couleur_hex

LARGEUR: Final = 1200
HAUTEUR: Final = 630
ACCENT: Final = couleur_hex("#ff7a86")


def nombre(valeur: int) -> str:
    """1162 → « 1 162 » (espace fine insécable)."""
    return f"{valeur:,}".replace(",", " ")


def compter(valeur: int, singulier: str, pluriel: str) -> str:
    """« 1 site hors ligne », « 2 sites hors ligne »."""
    return f"{nombre(valeur)} {singulier if valeur <= 1 else pluriel}"


def couper(police: Police, texte: str, taille: float, largeur: float) -> list[str]:
    """Découpe un texte en lignes qui tiennent dans `largeur`."""
    lignes: list[str] = []
    courante = ""
    for mot in texte.split():
        essai = f"{courante} {mot}".strip()
        if courante and police.largeur(essai, taille) > largeur:
            lignes.append(courante)
            courante = mot
        else:
            courante = essai
    if courante:
        lignes.append(courante)
    return lignes


def dessiner_partage(
    prereglage: Mapping[str, Any],
    resultat: Mapping[str, Any],
    date_donnees: datetime | None,
    domaine_site: str,
    dossier_polices: Path = DOSSIER_POLICES,
) -> Image:
    """Image 1200 × 630 : titre du préréglage et chiffre héros (collectivités touchées)."""
    gras = Police(dossier_polices / "Luciole-Bold.woff2")
    normal = Police(dossier_polices / "Luciole-Regular.woff2")
    image = Image(LARGEUR, HAUTEUR, FOND)
    tiers = LARGEUR / 3
    image.rectangle(0, 0, tiers, 10, BLEU_FRANCE)
    image.rectangle(tiers, 0, tiers, 10, couleur_hex("#ffffff"))
    image.rectangle(2 * tiers, 0, LARGEUR - 2 * tiers, 10, ROUGE_FRANCE)

    image.texte(gras, "BLEU BLANC CLOUD · SIMULATEUR « ET SI… ? »", 20, 64, 70, TEXTE_SECONDAIRE)
    y = 132.0
    for ligne in couper(gras, str(prereglage["titre"]), 46, LARGEUR - 128)[:2]:
        image.texte(gras, ligne, 46, 64, y, TEXTE)
        y += 56

    # Chiffre héros dans un encadré
    touchees, total = int(resultat["touchees"]), int(resultat["total"])
    image.rectangle(64, 268, LARGEUR - 128, 236, SURFACE, rayon=22)
    largeur_chiffre = image.texte(gras, nombre(touchees), 112, 100, 398, ACCENT)
    image.texte(
        gras,
        f"collectivité{'s' if touchees > 1 else ''} touchée{'s' if touchees > 1 else ''} "
        f"sur {nombre(total)}",
        30,
        100 + largeur_chiffre + 28,
        356,
        TEXTE,
    )
    details = " · ".join(
        (
            compter(int(resultat["sites_hors_ligne"]), "site hors ligne", "sites hors ligne"),
            compter(
                int(resultat["messageries_coupees"]), "messagerie coupée", "messageries coupées"
            ),
            compter(int(resultat["sites_degrades"]), "site dégradé", "sites dégradés"),
        )
    )
    image.texte(normal, details, 24, 100 + largeur_chiffre + 28, 398, TEXTE_SECONDAIRE)
    image.texte(
        normal,
        "Simulation, pas une prédiction : ne tient pas compte des plans de secours.",
        22,
        100,
        470,
        TEXTE_SECONDAIRE,
    )

    image.texte(
        normal,
        f"Dépendances détectées le {date_en_francais(date_donnees)} · {domaine_site}/simulateur",
        22,
        64,
        574,
        TEXTE_SECONDAIRE,
    )
    return image
