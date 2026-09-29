"""Calcul du score (0 à 100) et de la note (A à E) — méthodologie version 1.0.

Voir docs/methodologie.md. Toute modification de ce fichier qui change un résultat doit
s'accompagner d'une nouvelle version de la méthodologie.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Final

from bleublanccloud.analyse.attribution import pire_niveau
from bleublanccloud.modeles import (
    CategorieScore,
    Constat,
    Justification,
    Niveau,
    Note,
    Score,
    ScoreCategorie,
)

VERSION_METHODO: Final = "1.0"

POIDS: Final[dict[CategorieScore, float]] = {
    "hebergement": 25,
    "messagerie": 25,
    "dns": 10,
    "suites_saas": 15,
    "services_tiers": 15,
    "mesure_audience": 10,
}
LIBELLES: Final[dict[CategorieScore, str]] = {
    "hebergement": "Hébergement du site",
    "messagerie": "Messagerie",
    "dns": "DNS",
    "suites_saas": "Suites collaboratives et SaaS",
    "services_tiers": "Services tiers chargés par le site",
    "mesure_audience": "Mesure d'audience et cookies",
}
POINTS_NIVEAUX: Final[dict[Niveau, float]] = {"A": 100, "B": 70, "C": 40, "D": 0}
PENALITE_SUITES_SAAS: Final = 25.0
PENALITE_SERVICES_TIERS: Final = 20.0
SEUILS_NOTES: Final[tuple[tuple[float, Note], ...]] = ((85, "A"), (70, "B"), (50, "C"), (30, "D"))

# Sondes dont dépend chaque catégorie : sans données, la catégorie n'est pas évaluable.
SONDES_REQUISES: Final[dict[CategorieScore, str]] = {
    "hebergement": "dns",
    "messagerie": "dns",
    "dns": "dns",
    "suites_saas": "dns",
    "services_tiers": "http",
    "mesure_audience": "http",
}


class ScoreImpossible(ValueError):
    """Aucune catégorie n'est évaluable (domaine injoignable, scan en erreur…)."""


@dataclass
class _Evaluation:
    score: float | None
    explication: str
    justifications: list[Justification] = field(default_factory=list)


def note_depuis_score(score: float) -> Note:
    """A ≥ 85 · B ≥ 70 · C ≥ 50 · D ≥ 30 · E < 30."""
    for seuil, note in SEUILS_NOTES:
        if score >= seuil:
            return note
    return "E"


def arrondir(valeur: float) -> int:
    """Arrondi commercial (0,5 → supérieur), indépendant de l'arrondi bancaire de Python."""
    return int(valeur + 0.5)


def _indexes(constats: Sequence[Constat], categorie: CategorieScore) -> list[int]:
    return [i for i, c in enumerate(constats) if c.categorie == categorie]


def _evaluer_par_niveau(
    constats: Sequence[Constat], indexes: list[int], sujet: str, absence: str
) -> _Evaluation:
    """Hébergement, messagerie, DNS : niveau du fournisseur (le moins bon si plusieurs)."""
    if not indexes:
        return _Evaluation(None, absence)
    connus = [i for i in indexes if constats[i].niveau != "inconnu"]
    inconnus = len(indexes) - len(connus)
    if not connus:
        return _Evaluation(
            None,
            f"{sujet} : fournisseur non identifié, catégorie exclue du calcul (poids redistribué).",
        )
    niveau = pire_niveau(constats[i].niveau for i in connus)
    score = POINTS_NIVEAUX[niveau]
    explication = f"{sujet} : niveau {niveau} ({score:.0f}/100)."
    if len(connus) > 1:
        explication += " Le moins bon niveau parmi les serveurs est retenu."
    if inconnus:
        explication += f" {inconnus} serveur(s) non identifié(s) non pris en compte."
    justifications: list[Justification] = []
    if score < 100:
        responsables = [i for i in connus if constats[i].niveau == niveau]
        part = (100 - score) / len(responsables)
        justifications = [
            Justification(
                constat_index=i,
                points_retires=round(part, 2),
                raison=f"{constats[i].valeur} : fournisseur de niveau {niveau}.",
            )
            for i in responsables
        ]
    return _Evaluation(score, explication, justifications)


def _services(constats: Sequence[Constat], indexes: list[int]) -> dict[str, list[int]]:
    """Regroupe les constats par service (règle de détection ou fournisseur générique)."""
    services: dict[str, list[int]] = {}
    for i in indexes:
        cle = str(constats[i].preuve.get("regle") or constats[i].valeur)
        services.setdefault(cle, []).append(i)
    return services


def _evaluer_par_penalite(
    constats: Sequence[Constat], indexes: list[int], penalite: float, nature: str
) -> _Evaluation:
    """Suites SaaS et services tiers : 100 − pénalité par service de niveau D (minimum 0)."""
    services = _services(constats, indexes)
    services_d = [membres[0] for membres in services.values() if constats[membres[0]].niveau == "D"]
    score = max(0.0, 100 - penalite * len(services_d))
    if not services_d:
        explication = (
            f"Aucun {nature} soumis au Cloud Act détecté."
            if not services
            else f"{len(services)} {nature}(s) détecté(s), aucun de niveau D."
        )
        return _Evaluation(100.0, explication)
    justifications = []
    points_restants = 100.0
    for i in services_d:
        retire = min(penalite, points_restants)
        points_restants -= retire
        justifications.append(
            Justification(
                constat_index=i,
                points_retires=retire,
                raison=f"{constats[i].valeur} : service de niveau D (−{penalite:.0f}).",
            )
        )
    explication = (
        f"{len(services_d)} {nature}(s) de niveau D détecté(s) : "
        f"100 − {penalite:.0f} × {len(services_d)} = {score:.0f}/100."
    )
    return _Evaluation(score, explication, justifications)


def _evaluer_mesure_audience(constats: Sequence[Constat], indexes: list[int]) -> _Evaluation:
    """100 si aucune solution ou solution de niveau A ; niveau le moins bon sinon."""
    connus = [i for i in indexes if constats[i].niveau != "inconnu"]
    if not connus:
        return _Evaluation(100.0, "Aucune solution de mesure d'audience tierce détectée.")
    niveau = pire_niveau(constats[i].niveau for i in connus)
    score = POINTS_NIVEAUX[niveau]
    noms = ", ".join(sorted({constats[i].valeur for i in connus}))
    explication = f"Solution(s) détectée(s) : {noms}. Niveau retenu : {niveau} ({score:.0f}/100)."
    justifications: list[Justification] = []
    if score < 100:
        responsables = [i for i in connus if constats[i].niveau == niveau]
        part = (100 - score) / len(responsables)
        justifications = [
            Justification(
                constat_index=i,
                points_retires=round(part, 2),
                raison=f"{constats[i].valeur} : solution de niveau {niveau}.",
            )
            for i in responsables
        ]
    return _Evaluation(score, explication, justifications)


def _evaluer(
    categorie: CategorieScore, constats: Sequence[Constat], sondes_reussies: Collection[str]
) -> _Evaluation:
    if SONDES_REQUISES[categorie] not in sondes_reussies:
        sonde = "le site web" if SONDES_REQUISES[categorie] == "http" else "le DNS"
        return _Evaluation(None, f"Données indisponibles ({sonde} n'a pas pu être analysé).")
    indexes = _indexes(constats, categorie)
    if categorie == "hebergement":
        return _evaluer_par_niveau(
            constats, indexes, "Hébergement du site", "Adresse IP du site introuvable."
        )
    if categorie == "messagerie":
        return _evaluer_par_niveau(
            constats,
            indexes,
            "Messagerie",
            "Aucun serveur de messagerie (MX) déclaré : catégorie non applicable.",
        )
    if categorie == "dns":
        return _evaluer_par_niveau(
            constats, indexes, "Serveurs DNS", "Aucun serveur DNS (NS) trouvé."
        )
    if categorie == "suites_saas":
        return _evaluer_par_penalite(constats, indexes, PENALITE_SUITES_SAAS, "service SaaS")
    if categorie == "services_tiers":
        return _evaluer_par_penalite(constats, indexes, PENALITE_SERVICES_TIERS, "service tiers")
    return _evaluer_mesure_audience(constats, indexes)


def calculer_score(
    constats: Sequence[Constat], sondes_reussies: Collection[str] = ("dns", "http")
) -> Score:
    """Calcule le score global (moyenne pondérée des catégories évaluables) et la note.

    Une catégorie non évaluable (fournisseur inconnu, données indisponibles, absence de
    messagerie) est exclue : son poids est redistribué proportionnellement.
    """
    evaluations = {c: _evaluer(c, constats, sondes_reussies) for c in POIDS}
    poids_evaluables = sum(POIDS[c] for c, e in evaluations.items() if e.score is not None)
    if poids_evaluables == 0:
        raise ScoreImpossible("aucune catégorie évaluable")

    total = 0.0
    detail: list[ScoreCategorie] = []
    for categorie, evaluation in evaluations.items():
        evaluable = evaluation.score is not None
        poids_effectif = POIDS[categorie] / poids_evaluables * 100 if evaluable else 0.0
        points_perdus = 0.0
        if evaluation.score is not None:
            total += evaluation.score * poids_effectif / 100
            points_perdus = (100 - evaluation.score) * poids_effectif / 100
        detail.append(
            ScoreCategorie(
                categorie=categorie,
                libelle=LIBELLES[categorie],
                poids=POIDS[categorie],
                poids_effectif=round(poids_effectif, 2),
                score=evaluation.score,
                evaluable=evaluable,
                points_perdus_global=round(points_perdus, 2),
                explication=evaluation.explication,
                justifications=evaluation.justifications,
            )
        )
    score_global = min(100, max(0, arrondir(total)))
    return Score(
        score_global=score_global,
        note=note_depuis_score(score_global),
        version_methodo=VERSION_METHODO,
        detail=detail,
        categories_non_evaluables=[c for c, e in evaluations.items() if e.score is None],
    )


__all__ = [
    "LIBELLES",
    "POIDS",
    "VERSION_METHODO",
    "ScoreImpossible",
    "calculer_score",
    "note_depuis_score",
]
