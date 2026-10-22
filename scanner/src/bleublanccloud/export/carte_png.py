"""Image PNG (1080 × 1080) de la carte de France par département : note moyenne, part des
notes provisoires, aux couleurs du site (thème sombre). Format carré prêt à partager.

Contours : fond des cartes de situation du site (`site/src/donnees-carte/situation.topo.json`,
IGN Admin Express COG via france-geojson, Licence Ouverte Etalab 2.0). Projection conique
conforme comme la carte de l'accueil (parallèles 44° et 49°, méridien central 3° E),
outre-mer en encadrés (Mercator). Police Luciole auto-hébergée (CC-BY 4.0).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from bleublanccloud.configuration import RACINE_PROJET
from bleublanccloud.export.raster import Anneau, Couleur, Image, Point, Police, couleur_hex
from bleublanccloud.modeles import Note

COTE: Final = 1080
CHEMIN_TOPOLOGIE: Final = RACINE_PROJET / "site" / "src" / "donnees-carte" / "situation.topo.json"
DOSSIER_POLICES: Final = RACINE_PROJET / "site" / "public" / "polices"
OUTRE_MER: Final = ("971", "972", "973", "974", "976")
SEUIL_HACHURES: Final = 50.0
"""Département hachuré quand au moins cette part (en %) de ses notes est provisoire."""

# Couleurs du thème sombre du site (site/src/styles/theme.css)
FOND: Final = couleur_hex("#0a0f24")
SURFACE: Final = couleur_hex("#121937")
TEXTE: Final = couleur_hex("#f2f4ff")
TEXTE_SECONDAIRE: Final = couleur_hex("#b0b8dc")
VIDE: Final = couleur_hex("#1b2350")
COULEURS_NOTES: Final[dict[Note, Couleur]] = {
    "A": couleur_hex("#3d6bf2"),
    "B": couleur_hex("#7fa0f5"),
    "C": couleur_hex("#ffcc00"),
    "D": couleur_hex("#f08a24"),
    "E": couleur_hex("#ed2939"),
}
TEXTE_SUR_NOTE: Final[dict[Note, Couleur]] = {
    "A": couleur_hex("#ffffff"),
    "B": couleur_hex("#0e1330"),
    "C": couleur_hex("#0e1330"),
    "D": couleur_hex("#0e1330"),
    "E": couleur_hex("#ffffff"),
}
BLEU_FRANCE: Final = couleur_hex("#002395")
ROUGE_FRANCE: Final = couleur_hex("#ed2939")


@dataclass(frozen=True)
class DonneeDepartement:
    """Valeurs affichées pour un département."""

    note_moyenne: Note | None
    part_provisoire: float


@dataclass(frozen=True)
class Departement:
    code: str
    nom: str
    polygones: list[list[list[Point]]]
    """Polygones (anneau extérieur puis trous), en degrés (longitude, latitude)."""


# --------------------------------------------------------------------------- #
# Topologie et projections
# --------------------------------------------------------------------------- #


def lire_departements(chemin: Path = CHEMIN_TOPOLOGIE) -> list[Departement]:
    """Départements d'une topologie TopoJSON quantifiée (arcs en deltas)."""
    topo: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs: list[list[Point]] = []
    for arc in topo["arcs"]:
        x = y = 0
        points: list[Point] = []
        for dx, dy in arc:
            x += dx
            y += dy
            points.append((x * sx + tx, y * sy + ty))
        arcs.append(points)

    def anneau(indices: Sequence[int]) -> list[Point]:
        points: list[Point] = []
        for indice in indices:
            arc = arcs[indice] if indice >= 0 else arcs[~indice][::-1]
            points.extend(arc[1:] if points else arc)
        return points

    departements: list[Departement] = []
    for geometrie in topo["objects"]["departements"]["geometries"]:
        polygones = [geometrie["arcs"]] if geometrie["type"] == "Polygon" else geometrie["arcs"]
        departements.append(
            Departement(
                code=geometrie["properties"]["code"],
                nom=geometrie["properties"]["nom"],
                polygones=[[anneau(a) for a in polygone] for polygone in polygones],
            )
        )
    return departements


Projection = Callable[[float, float], Point]


def conique_conforme(
    parallele1: float = 44, parallele2: float = 49, meridien: float = 3
) -> Projection:
    """Projection conique conforme (formules de d3-geo), y vers le bas, échelle unitaire."""
    p1, p2 = math.radians(parallele1), math.radians(parallele2)

    def tangente(phi: float) -> float:
        return math.tan((math.pi / 2 + phi) / 2)

    n = math.log(math.cos(p1) / math.cos(p2)) / math.log(tangente(p2) / tangente(p1))
    f = math.cos(p1) * tangente(p1) ** n / n

    def projeter(longitude: float, latitude: float) -> Point:
        lam = math.radians(longitude - meridien)
        rayon = f / tangente(math.radians(latitude)) ** n
        return (rayon * math.sin(n * lam), -(f - rayon * math.cos(n * lam)))

    return projeter


def mercator(longitude: float, latitude: float) -> Point:
    return (math.radians(longitude), -math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2)))


def cadrer(
    projection: Projection,
    departements: Sequence[Departement],
    x: float,
    y: float,
    largeur: float,
    hauteur: float,
) -> Projection:
    """Projection ajustée pour que les départements tiennent, centrés, dans le cadre."""
    points = [projection(*p) for d in departements for polygone in d.polygones for p in polygone[0]]
    x0, x1 = min(p[0] for p in points), max(p[0] for p in points)
    y0, y1 = min(p[1] for p in points), max(p[1] for p in points)
    echelle = min(largeur / (x1 - x0), hauteur / (y1 - y0))
    dx = x + (largeur - echelle * (x1 - x0)) / 2 - echelle * x0
    dy = y + (hauteur - echelle * (y1 - y0)) / 2 - echelle * y0

    def projeter(longitude: float, latitude: float) -> Point:
        px, py = projection(longitude, latitude)
        return (dx + echelle * px, dy + echelle * py)

    return projeter


def projeter_departement(departement: Departement, projection: Projection) -> list[Anneau]:
    return [
        [projection(*p) for p in anneau]
        for polygone in departement.polygones
        for anneau in polygone
    ]


def hachures(x: int, y: int) -> float:
    """Hachures diagonales (traits de 3 px tous les 10 px, bords adoucis)."""
    return max(0.0, min(1.0, 2.0 - abs((x + y) % 10 - 4.5)))


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def date_en_francais(valeur: datetime | None) -> str:
    mois = (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    )
    if valeur is None:
        return "—"
    return f"{valeur.day} {mois[valeur.month - 1]} {valeur.year}"


def _pourcentage(valeur: float) -> str:
    return f"{valeur:.0f} %" if valeur >= 10 or valeur == 0 else f"{valeur:.1f} %".replace(".", ",")


def dessiner_carte(
    donnees: Mapping[str, DonneeDepartement],
    nombre_organisations: int,
    part_provisoire: float,
    dernier_scan: datetime | None,
    domaine_site: str,
    chemin_topologie: Path = CHEMIN_TOPOLOGIE,
    dossier_polices: Path = DOSSIER_POLICES,
) -> Image:
    """Carte 1080 × 1080 de la note moyenne par département."""
    gras = Police(dossier_polices / "Luciole-Bold.woff2")
    normal = Police(dossier_polices / "Luciole-Regular.woff2")
    image = Image(COTE, COTE, FOND)

    # Bandeau tricolore et titres
    tiers = COTE / 3
    image.rectangle(0, 0, tiers, 10, BLEU_FRANCE)
    image.rectangle(tiers, 0, tiers, 10, couleur_hex("#ffffff"))
    image.rectangle(2 * tiers, 0, COTE - 2 * tiers, 10, ROUGE_FRANCE)
    image.texte(gras, "BLEU BLANC CLOUD · OBSERVATOIRE", 19, 56, 62, TEXTE_SECONDAIRE)
    image.texte(gras, "Note moyenne par département", 46, 56, 116, TEXTE)
    image.texte(
        normal,
        f"{nombre_organisations:,} organisation{'s' if nombre_organisations > 1 else ''}".replace(
            ",", "\u202f"
        )
        + f" · dernier scan le {date_en_francais(dernier_scan)} · "
        f"{_pourcentage(part_provisoire)} de notes provisoires",
        21,
        56,
        154,
        TEXTE_SECONDAIRE,
    )

    departements = lire_departements(chemin_topologie)
    metropole = [d for d in departements if d.code not in OUTRE_MER]
    projection = cadrer(conique_conforme(), metropole, 236, 186, 800, 760)

    def dessiner(departement: Departement, projeter: Projection) -> None:
        anneaux = projeter_departement(departement, projeter)
        donnee = donnees.get(departement.code)
        note = donnee.note_moyenne if donnee else None
        image.remplir(anneaux, COULEURS_NOTES[note] if note else VIDE)
        if donnee and note and donnee.part_provisoire >= SEUIL_HACHURES:
            image.remplir(anneaux, FOND, opacite=0.45, motif=hachures)

    for departement in metropole:
        dessiner(departement, projection)
    # Limites : chaque contour tracé dans la couleur du fond
    image.tracer(
        ([*anneau, anneau[0]] for d in metropole for anneau in projeter_departement(d, projection)),
        FOND,
        1.3,
    )

    # Outre-mer : encadrés à gauche
    noms = {
        "971": "Guadeloupe",
        "972": "Martinique",
        "973": "Guyane",
        "974": "La Réunion",
        "976": "Mayotte",
    }
    for rang, code in enumerate(OUTRE_MER):
        entite = next((d for d in departements if d.code == code), None)
        if entite is None:
            continue
        x, y, largeur, hauteur = 44.0, 196.0 + rang * 148, 160.0, 134.0
        image.rectangle(x, y, largeur, hauteur, SURFACE, rayon=10)
        cadre = cadrer(mercator, [entite], x + 18, y + 12, largeur - 36, hauteur - 46)
        dessiner(entite, cadre)
        image.texte(
            normal, noms[code], 16, x + largeur / 2, y + hauteur - 12, TEXTE_SECONDAIRE, "centre"
        )

    # Légende
    y_legende = 978
    x = 56.0
    x += image.texte(gras, "Note moyenne", 19, x, y_legende + 26, TEXTE) + 18
    for note, couleur in COULEURS_NOTES.items():
        image.rectangle(x, y_legende, 38, 38, couleur, rayon=8)
        image.texte(gras, note, 22, x + 19, y_legende + 27, TEXTE_SUR_NOTE[note], "centre")
        x += 46
    x += 16
    image.rectangle(x, y_legende + 7, 24, 24, VIDE, rayon=5)
    x += 32 + image.texte(normal, "Aucune donnée", 18, x + 32, y_legende + 26, TEXTE_SECONDAIRE)
    x += 22
    image.rectangle(x, y_legende + 7, 24, 24, COULEURS_NOTES["B"], rayon=5)
    image.remplir(
        [
            [
                (x, y_legende + 7),
                (x + 24, y_legende + 7),
                (x + 24, y_legende + 31),
                (x, y_legende + 31),
            ]
        ],
        FOND,
        opacite=0.45,
        motif=hachures,
    )
    image.texte(
        normal,
        "Majorité de notes provisoires",
        18,
        x + 32,
        y_legende + 26,
        TEXTE_SECONDAIRE,
    )

    # Pied
    image.texte(
        normal,
        f"{domaine_site} · Score indicatif : empreinte externe et publique · "
        "Contours IGN Admin Express (Licence Ouverte)",
        15,
        56,
        1056,
        TEXTE_SECONDAIRE,
    )
    return image
