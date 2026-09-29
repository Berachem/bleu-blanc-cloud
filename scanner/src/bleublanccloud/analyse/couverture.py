"""Couverture de l'observatoire : part du poids des catégories encore non évaluée.

Pour chaque organisation, le poids applicable est la somme des poids des catégories hors
« sans objet » (ex. aucun MX). La part inconnue globale est la somme des poids exclus pour
fournisseur inconnu, rapportée à la somme des poids applicables de toutes les organisations :
c'est la moyenne des parts inconnues individuelles, pondérée par leur poids applicable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from bleublanccloud.analyse.score import POIDS
from bleublanccloud.modeles import CategorieScore, Score


@dataclass
class CompteCategorie:
    """Nombre d'organisations par état d'une catégorie."""

    evaluee: int = 0
    inconnu: int = 0
    indisponible: int = 0
    sans_objet: int = 0

    @property
    def applicable(self) -> int:
        return self.evaluee + self.inconnu + self.indisponible


@dataclass
class CouvertureObservatoire:
    """Agrégat de couverture sur un ensemble de scores (un par organisation)."""

    nombre_organisations: int = 0
    nombre_provisoires: int = 0
    poids_applicable: float = 0.0
    poids_inconnu: float = 0.0
    poids_indisponible: float = 0.0
    par_categorie: dict[CategorieScore, CompteCategorie] = field(
        default_factory=lambda: {c: CompteCategorie() for c in POIDS}
    )

    def _part(self, poids: float) -> float:
        return round(100 * poids / self.poids_applicable, 1) if self.poids_applicable else 0.0

    @property
    def part_inconnue(self) -> float:
        """Part (en %) du poids applicable exclue faute de fournisseur identifié."""
        return self._part(self.poids_inconnu)

    @property
    def part_indisponible(self) -> float:
        """Part (en %) du poids applicable exclue faute de données (site ou DNS injoignable)."""
        return self._part(self.poids_indisponible)

    @property
    def part_evaluee(self) -> float:
        return round(100 - self.part_inconnue - self.part_indisponible, 1)


def mesurer_couverture(scores: Iterable[Score]) -> CouvertureObservatoire:
    """Couverture agrégée d'un ensemble de scores (le dernier de chaque organisation)."""
    couverture = CouvertureObservatoire()
    for score in scores:
        couverture.nombre_organisations += 1
        couverture.nombre_provisoires += int(score.provisoire)
        for categorie in score.detail:
            compte = couverture.par_categorie[categorie.categorie]
            if categorie.evaluable:
                compte.evaluee += 1
            elif categorie.exclusion == "sans_objet":
                compte.sans_objet += 1
                continue
            elif categorie.exclusion == "indisponible":
                compte.indisponible += 1
                couverture.poids_indisponible += categorie.poids
            else:
                # « inconnu », ou score antérieur à la v1.2 sans motif d'exclusion
                compte.inconnu += 1
                couverture.poids_inconnu += categorie.poids
            couverture.poids_applicable += categorie.poids
    return couverture
