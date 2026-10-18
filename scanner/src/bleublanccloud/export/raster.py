"""Rendu d'images PNG en Python pur, pour les visuels générés par le serveur.

- polygones remplis avec anticrénelage (règle d'enroulement non nul, couverture horizontale
  exacte et sous-échantillonnage vertical) ;
- traits (segments épaissis, réunis en un seul remplissage) ;
- texte dessiné à partir des contours de la police Luciole auto-hébergée (fontTools) ;
- encodage PNG avec zlib.

Aucune bibliothèque graphique (Pillow, Cairo) ni navigateur : le serveur reste léger, et
l'image ne dépend d'aucun service externe.
"""

from __future__ import annotations

import math
import struct
import zlib
from collections.abc import Callable, Iterable, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, Literal

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

Couleur = tuple[int, int, int]
Point = tuple[float, float]
Anneau = Sequence[Point]
Motif = Callable[[int, int], float]
"""Opacité (0 à 1) d'un motif au pixel (x, y), ex. des hachures."""

SOUS_LIGNES: Final = 4
"""Lignes d'échantillonnage par pixel (anticrénelage vertical)."""
PAS_COURBES: Final = 8
"""Segments par courbe de Bézier dans les contours des glyphes."""


def couleur_hex(valeur: str) -> Couleur:
    """« #3d6bf2 » → (61, 107, 242)."""
    valeur = valeur.lstrip("#")
    return (int(valeur[0:2], 16), int(valeur[2:4], 16), int(valeur[4:6], 16))


def rectangle_arrondi(x: float, y: float, largeur: float, hauteur: float, rayon: float) -> Anneau:
    """Contour d'un rectangle aux coins arrondis (sens horaire à l'écran)."""
    rayon = max(0.0, min(rayon, largeur / 2, hauteur / 2))
    if rayon == 0:
        return [(x, y), (x + largeur, y), (x + largeur, y + hauteur), (x, y + hauteur)]
    points: list[Point] = []
    coins = (
        (x + largeur - rayon, y + rayon, -math.pi / 2),
        (x + largeur - rayon, y + hauteur - rayon, 0.0),
        (x + rayon, y + hauteur - rayon, math.pi / 2),
        (x + rayon, y + rayon, math.pi),
    )
    for cx, cy, depart in coins:
        for k in range(7):
            angle = depart + k * (math.pi / 2) / 6
            points.append((cx + rayon * math.cos(angle), cy + rayon * math.sin(angle)))
    return points


class Image:
    """Image RGB en mémoire."""

    def __init__(self, largeur: int, hauteur: int, fond: Couleur) -> None:
        self.largeur = largeur
        self.hauteur = hauteur
        self.pixels = bytearray(bytes(fond) * (largeur * hauteur))

    # ------------------------------------------------------------------ Remplissage

    def remplir(
        self,
        anneaux: Iterable[Anneau],
        couleur: Couleur,
        opacite: float = 1.0,
        motif: Motif | None = None,
    ) -> None:
        """Remplit un ensemble d'anneaux (trous et îles compris, règle non nulle)."""
        aretes: list[tuple[float, float, float, float, int]] = []
        for anneau in anneaux:
            nombre = len(anneau)
            for i in range(nombre):
                x0, y0 = anneau[i]
                x1, y1 = anneau[(i + 1) % nombre]
                if y0 == y1:
                    continue
                sens = 1 if y1 > y0 else -1
                if y0 > y1:
                    x0, y0, x1, y1 = x1, y1, x0, y0
                aretes.append((y0, y1, x0, (x1 - x0) / (y1 - y0), sens))
        if not aretes:
            return
        haut = max(0, math.floor(min(a[0] for a in aretes)))
        bas = min(self.hauteur, math.ceil(max(a[1] for a in aretes)))
        abscisses = [a[2] for a in aretes] + [a[2] + a[3] * (a[1] - a[0]) for a in aretes]
        gauche = max(0, math.floor(min(abscisses)))
        droite = min(self.largeur, math.ceil(max(abscisses)))
        if gauche >= droite or haut >= bas:
            return
        largeur = droite - gauche
        aretes.sort(key=lambda a: a[0])
        poids = 1.0 / SOUS_LIGNES
        actives: list[tuple[float, float, float, float, int]] = []
        prochaine = 0
        r, v, b = couleur
        pixels = self.pixels
        for ligne in range(haut, bas):
            partiel = [0.0] * (largeur + 1)
            plein = [0.0] * (largeur + 2)
            for sous_ligne in range(SOUS_LIGNES):
                y = ligne + (sous_ligne + 0.5) / SOUS_LIGNES
                while prochaine < len(aretes) and aretes[prochaine][0] <= y:
                    actives.append(aretes[prochaine])
                    prochaine += 1
                actives = [a for a in actives if a[1] > y]
                croisements = sorted((a[2] + (y - a[0]) * a[3], a[4]) for a in actives)
                enroulement = 0
                debut = 0.0
                for x, sens in croisements:
                    precedent = enroulement
                    enroulement += sens
                    if precedent == 0 and enroulement != 0:
                        debut = x
                    elif precedent != 0 and enroulement == 0:
                        _couvrir(partiel, plein, debut - gauche, x - gauche, poids, largeur)
            cumul = 0.0
            indice = (ligne * self.largeur + gauche) * 3
            for colonne in range(largeur):
                cumul += plein[colonne]
                alpha = partiel[colonne] + cumul
                if alpha > 0.002:
                    alpha = min(1.0, alpha) * opacite
                    if motif is not None:
                        alpha *= motif(gauche + colonne, ligne)
                    if alpha >= 0.999:
                        pixels[indice] = r
                        pixels[indice + 1] = v
                        pixels[indice + 2] = b
                    elif alpha > 0.002:
                        pixels[indice] = int(pixels[indice] + (r - pixels[indice]) * alpha + 0.5)
                        pixels[indice + 1] = int(
                            pixels[indice + 1] + (v - pixels[indice + 1]) * alpha + 0.5
                        )
                        pixels[indice + 2] = int(
                            pixels[indice + 2] + (b - pixels[indice + 2]) * alpha + 0.5
                        )
                indice += 3

    def tracer(
        self,
        lignes: Iterable[Sequence[Point]],
        couleur: Couleur,
        epaisseur: float,
        opacite: float = 1.0,
    ) -> None:
        """Trace des lignes brisées : chaque segment devient un rectangle prolongé d'une
        demi-épaisseur (jointures couvertes), le tout rempli en une fois."""
        demi = epaisseur / 2
        quadrilateres: list[Anneau] = []
        for ligne in lignes:
            for (x0, y0), (x1, y1) in pairwise(ligne):
                longueur = math.hypot(x1 - x0, y1 - y0)
                if longueur == 0:
                    continue
                ux, uy = (x1 - x0) / longueur * demi, (y1 - y0) / longueur * demi
                nx, ny = -uy, ux
                quadrilateres.append(
                    [
                        (x0 - ux + nx, y0 - uy + ny),
                        (x1 + ux + nx, y1 + uy + ny),
                        (x1 + ux - nx, y1 + uy - ny),
                        (x0 - ux - nx, y0 - uy - ny),
                    ]
                )
        self.remplir(quadrilateres, couleur, opacite)

    def rectangle(
        self,
        x: float,
        y: float,
        largeur: float,
        hauteur: float,
        couleur: Couleur,
        rayon: float = 0.0,
        opacite: float = 1.0,
    ) -> None:
        self.remplir([rectangle_arrondi(x, y, largeur, hauteur, rayon)], couleur, opacite)

    # ------------------------------------------------------------------ Texte

    def texte(
        self,
        police: Police,
        contenu: str,
        taille: float,
        x: float,
        y: float,
        couleur: Couleur,
        ancre: Literal["gauche", "centre", "droite"] = "gauche",
    ) -> float:
        """Écrit `contenu` avec sa ligne de base en `y` ; renvoie la largeur occupée."""
        largeur = police.largeur(contenu, taille)
        if ancre == "centre":
            x -= largeur / 2
        elif ancre == "droite":
            x -= largeur
        self.remplir(police.contours(contenu, taille, x, y), couleur)
        return largeur

    # ------------------------------------------------------------------ Export

    def png(self) -> bytes:
        """Image encodée en PNG (RGB 8 bits, sans entrelacement)."""
        ligne = self.largeur * 3
        brut = b"".join(
            b"\x00" + bytes(self.pixels[i * ligne : (i + 1) * ligne]) for i in range(self.hauteur)
        )

        def bloc(nature: bytes, donnees: bytes) -> bytes:
            corps = nature + donnees
            return struct.pack(">I", len(donnees)) + corps + struct.pack(">I", zlib.crc32(corps))

        entete = struct.pack(">IIBBBBB", self.largeur, self.hauteur, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + bloc(b"IHDR", entete)
            + bloc(b"IDAT", zlib.compress(brut, 9))
            + bloc(b"IEND", b"")
        )

    def enregistrer(self, chemin: Path) -> None:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(self.png())


def _couvrir(
    partiel: list[float], plein: list[float], xa: float, xb: float, poids: float, largeur: int
) -> None:
    """Ajoute la couverture de l'intervalle [xa, xb[ d'une sous-ligne : fractions aux
    extrémités, tableau de différences pour les pixels entièrement couverts."""
    xa = max(0.0, xa)
    xb = min(float(largeur), xb)
    if xb <= xa:
        return
    ia, ib = int(xa), int(xb)
    if ia == ib:
        partiel[ia] += (xb - xa) * poids
        return
    partiel[ia] += (ia + 1 - xa) * poids
    plein[ia + 1] += poids
    plein[ib] -= poids
    if ib < largeur:
        partiel[ib] += (xb - ib) * poids


class Police:
    """Police TrueType ou WOFF2 (lue par fontTools) : avance des caractères et contours."""

    def __init__(self, chemin: Path) -> None:
        police = TTFont(str(chemin))
        self._glyphes: Any = police.getGlyphSet()
        self._cmap: dict[int, str] = police.getBestCmap()
        self._avances: dict[str, tuple[int, int]] = police["hmtx"].metrics
        self._unites: int = police["head"].unitsPerEm

    def _glyphe(self, caractere: str) -> str | None:
        nom = self._cmap.get(ord(caractere))
        if nom is None and caractere in "   ":
            nom = self._cmap.get(ord(" "))
        return nom

    def largeur(self, contenu: str, taille: float) -> float:
        echelle = taille / self._unites
        total = 0
        for caractere in contenu:
            nom = self._glyphe(caractere)
            if nom is not None:
                total += self._avances[nom][0]
        return total * echelle

    def contours(self, contenu: str, taille: float, x: float, y: float) -> list[Anneau]:
        echelle = taille / self._unites
        anneaux: list[Anneau] = []
        for caractere in contenu:
            nom = self._glyphe(caractere)
            if nom is None:
                continue
            stylo = _StyloAnneaux(self._glyphes, x, y, echelle)
            self._glyphes[nom].draw(stylo)
            anneaux.extend(stylo.anneaux)
            x += self._avances[nom][0] * echelle
        return anneaux


class _StyloAnneaux(BasePen):  # type: ignore[misc]
    """Convertit les contours d'un glyphe en anneaux de points (courbes aplaties), dans le
    repère de l'image (y vers le bas)."""

    def __init__(self, glyphes: Any, x: float, y: float, echelle: float) -> None:
        super().__init__(glyphes)
        self._x, self._y, self._echelle = x, y, echelle
        self.anneaux: list[list[Point]] = []
        self._courant: list[Point] = []
        self._position: Point = (0.0, 0.0)

    def _vers_image(self, point: Point) -> Point:
        return (self._x + point[0] * self._echelle, self._y - point[1] * self._echelle)

    def _moveTo(self, point: Point) -> None:
        self._fermer()
        self._position = point
        self._courant = [self._vers_image(point)]

    def _lineTo(self, point: Point) -> None:
        self._position = point
        self._courant.append(self._vers_image(point))

    def _qCurveToOne(self, controle: Point, arrivee: Point) -> None:
        (x0, y0), (x1, y1), (x2, y2) = self._position, controle, arrivee
        for k in range(1, PAS_COURBES + 1):
            t = k / PAS_COURBES
            u = 1 - t
            self._courant.append(
                self._vers_image(
                    (
                        u * u * x0 + 2 * u * t * x1 + t * t * x2,
                        u * u * y0 + 2 * u * t * y1 + t * t * y2,
                    )
                )
            )
        self._position = arrivee

    def _curveToOne(self, controle1: Point, controle2: Point, arrivee: Point) -> None:
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = self._position, controle1, controle2, arrivee
        for k in range(1, PAS_COURBES + 1):
            t = k / PAS_COURBES
            u = 1 - t
            a, b, c, d = u**3, 3 * u * u * t, 3 * u * t * t, t**3
            self._courant.append(
                self._vers_image(
                    (a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3)
                )
            )
        self._position = arrivee

    def _closePath(self) -> None:
        self._fermer()

    def _endPath(self) -> None:
        self._fermer()

    def _fermer(self) -> None:
        if len(self._courant) >= 3:
            self.anneaux.append(self._courant)
        self._courant = []
