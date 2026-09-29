"""Contours des communes pour la carte de situation des fiches.

Source : API Découpage administratif (geo.api.gouv.fr), tracés IGN Admin Express, Licence
Ouverte Etalab 2.0. Un contour est demandé par code INSEE lors de l'import des cibles, puis
simplifié (Douglas-Peucker) et arrondi avant d'être stocké : la carte, dessinée au build du
site avec d3-geo, fait quelques centaines de pixels de large, et un détail de 100 m y est
invisible.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import httpx

from bleublanccloud.cibles.communes import URL_GEO
from bleublanccloud.stockage.base import Base

SOURCE_CONTOURS: Final = "geo.api.gouv.fr / IGN, licence Etalab 2.0"
TOLERANCE_DEGRES: Final = 0.001
"""Écart maximal toléré par la simplification (≈ 80 à 110 m en France métropolitaine)."""
DECIMALES: Final = 4
"""Précision des coordonnées conservées (≈ 10 m)."""
CONCURRENCE: Final = 4
TENTATIVES: Final = 3
MOTIF_CODE_INSEE: Final = re.compile(r"^(\d{5}|2[AB]\d{3})$")

Point = list[float]
Anneau = list[Point]
Polygone = list[Anneau]
MultiPolygone = list[Polygone]


# --------------------------------------------------------------------------- #
# Simplification
# --------------------------------------------------------------------------- #


def _douglas_peucker(points: Sequence[Point], tolerance: float, echelle_x: float) -> list[Point]:
    """Douglas-Peucker itératif sur une polyligne ; les longitudes sont multipliées par
    `echelle_x` (cosinus de la latitude) pour mesurer des écarts comparables."""
    if len(points) < 3:
        return list(points)
    garder = [False] * len(points)
    garder[0] = garder[-1] = True
    pile = [(0, len(points) - 1)]
    while pile:
        debut, fin = pile.pop()
        ax, ay = points[debut][0] * echelle_x, points[debut][1]
        bx, by = points[fin][0] * echelle_x, points[fin][1]
        dx, dy = bx - ax, by - ay
        longueur = math.hypot(dx, dy)
        ecart_max, rang_max = 0.0, -1
        for rang in range(debut + 1, fin):
            px, py = points[rang][0] * echelle_x, points[rang][1]
            if longueur == 0:
                ecart = math.hypot(px - ax, py - ay)
            else:
                ecart = abs(dy * px - dx * py + bx * ay - by * ax) / longueur
            if ecart > ecart_max:
                ecart_max, rang_max = ecart, rang
        if rang_max >= 0 and ecart_max > tolerance:
            garder[rang_max] = True
            pile.extend([(debut, rang_max), (rang_max, fin)])
    return [p for p, garde in zip(points, garder, strict=True) if garde]


def simplifier_anneau(
    anneau: Sequence[Sequence[float]], tolerance: float, decimales: int = DECIMALES
) -> Anneau | None:
    """Anneau fermé simplifié et arrondi, ou None s'il devient trop petit pour être dessiné."""
    arrondis: Anneau = []
    for point in anneau:
        courant = [round(float(point[0]), decimales), round(float(point[1]), decimales)]
        if not arrondis or courant != arrondis[-1]:
            arrondis.append(courant)
    if len(arrondis) > 1 and arrondis[0] == arrondis[-1]:
        arrondis.pop()
    if len(arrondis) < 3:
        return None
    echelle_x = math.cos(math.radians(sum(p[1] for p in arrondis) / len(arrondis)))
    # Anneau coupé au point le plus éloigné du premier : deux polylignes simplifiées
    x0, y0 = arrondis[0]
    rang_loin = max(
        range(len(arrondis)),
        key=lambda i: math.hypot((arrondis[i][0] - x0) * echelle_x, arrondis[i][1] - y0),
    )
    aller = _douglas_peucker(arrondis[: rang_loin + 1], tolerance, echelle_x)
    retour = _douglas_peucker([*arrondis[rang_loin:], arrondis[0]], tolerance, echelle_x)
    simplifie = aller + retour[1:]
    if len(simplifie) < 4:  # 3 sommets distincts + fermeture
        return None
    return simplifie


def en_multipolygone(geometrie: Mapping[str, Any]) -> MultiPolygone | None:
    """Coordonnées d'une géométrie GeoJSON Polygon ou MultiPolygon, en MultiPolygon."""
    coordonnees = geometrie.get("coordinates")
    if not isinstance(coordonnees, list) or not coordonnees:
        return None
    if geometrie.get("type") == "Polygon":
        return [coordonnees]
    if geometrie.get("type") == "MultiPolygon":
        return coordonnees
    return None


def simplifier_contour(
    geometrie: Mapping[str, Any],
    tolerance: float = TOLERANCE_DEGRES,
    decimales: int = DECIMALES,
) -> MultiPolygone | None:
    """Contour simplifié (MultiPolygon). Les îlots et trous devenus invisibles sont retirés ;
    si tout disparaît (très petite commune), la tolérance est réduite."""
    polygones = en_multipolygone(geometrie)
    if polygones is None:
        return None
    for essai in (tolerance, tolerance / 4, 0.0):
        resultat: MultiPolygone = []
        for polygone in polygones:
            if not polygone:
                continue
            exterieur = simplifier_anneau(polygone[0], essai, decimales)
            if exterieur is None:
                continue
            trous = [simplifier_anneau(trou, essai, decimales) for trou in polygone[1:]]
            resultat.append([exterieur, *(t for t in trous if t is not None)])
        if resultat:
            return resultat
    return None


def geometrie_depuis_geojson(donnees: Any) -> Mapping[str, Any] | None:
    """Géométrie d'une réponse GeoJSON (Feature, FeatureCollection ou géométrie seule)."""
    if not isinstance(donnees, Mapping):
        return None
    if donnees.get("type") == "FeatureCollection":
        entites = donnees.get("features") or []
        return geometrie_depuis_geojson(entites[0]) if entites else None
    if donnees.get("type") == "Feature":
        geometrie = donnees.get("geometry")
        return geometrie if isinstance(geometrie, Mapping) else None
    if donnees.get("type") in ("Polygon", "MultiPolygon"):
        return donnees
    return None


# --------------------------------------------------------------------------- #
# Téléchargement
# --------------------------------------------------------------------------- #


class ContourIntrouvable(LookupError):
    """La commune n'existe pas (ou plus) dans geo.api.gouv.fr, ou n'a pas de contour."""


async def telecharger_contour(
    client: httpx.AsyncClient,
    code: str,
    attendre: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Mapping[str, Any]:
    """Contour brut d'une commune, demandé par son code INSEE (2 nouvelles tentatives en cas
    d'erreur réseau ou de réponse 429/5xx)."""
    if not MOTIF_CODE_INSEE.match(code):
        raise ValueError(f"code INSEE invalide : {code!r}")
    parametres = {"fields": "code", "format": "geojson", "geometry": "contour"}
    for tentative in range(1, TENTATIVES + 1):
        try:
            reponse = await client.get(f"{URL_GEO}/communes/{code}", params=parametres)
            if reponse.status_code == 404:
                raise ContourIntrouvable(code)
            reponse.raise_for_status()
            geometrie = geometrie_depuis_geojson(reponse.json())
            if geometrie is None:
                raise ContourIntrouvable(code)
            return geometrie
        except (httpx.TransportError, httpx.HTTPStatusError) as erreur:
            relancer = isinstance(erreur, httpx.TransportError) or (
                erreur.response.status_code == 429 or erreur.response.status_code >= 500
            )
            if not relancer or tentative == TENTATIVES:
                raise
            await attendre(2.0 * tentative)
    raise AssertionError("inaccessible")  # pragma: no cover


@dataclass
class BilanContours:
    """Résultat d'une mise à jour des contours."""

    telecharges: int = 0
    deja_presents: int = 0
    introuvables: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)


async def mettre_a_jour_contours(
    base: Base,
    client: httpx.AsyncClient,
    codes: Iterable[str],
    maintenant: datetime,
    forcer: bool = False,
    concurrence: int = CONCURRENCE,
    attendre: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> BilanContours:
    """Télécharge et simplifie le contour des communes qui n'en ont pas encore (toutes avec
    `forcer`). Les contours changent rarement : seuls les manquants sont demandés."""
    bilan = BilanContours()
    uniques = sorted({c for c in codes if MOTIF_CODE_INSEE.match(c)})
    presents = base.codes_communes_avec_contour()
    a_faire = uniques if forcer else [c for c in uniques if c not in presents]
    bilan.deja_presents = len(uniques) - len(a_faire)
    limite = asyncio.Semaphore(concurrence)

    async def traiter(code: str) -> None:
        async with limite:
            try:
                brut = await telecharger_contour(client, code, attendre)
            except ContourIntrouvable:
                bilan.introuvables.append(code)
                return
            except (httpx.HTTPError, ValueError) as erreur:
                # ValueError : réponse qui n'est pas du JSON valide
                bilan.erreurs.append(f"{code} : {type(erreur).__name__}")
                return
        contour = simplifier_contour(brut)
        if contour is None:
            bilan.introuvables.append(code)
            return
        base.enregistrer_contour(code, contour, SOURCE_CONTOURS, maintenant)
        bilan.telecharges += 1

    await asyncio.gather(*(traiter(code) for code in a_faire))
    bilan.introuvables.sort()
    bilan.erreurs.sort()
    return bilan
