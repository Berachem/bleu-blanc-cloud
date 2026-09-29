"""Sélection des alternatives européennes pertinentes pour une organisation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from bleublanccloud.modeles import Alternative, CategorieScore, Constat, Score

ALTERNATIVES_PAR_BESOIN: Final = 3


def _types_concernes(
    score_categorie_justifs: Sequence[int], constats: Sequence[Constat]
) -> set[str]:
    types: set[str] = set()
    for index in score_categorie_justifs:
        constat = constats[index]
        type_service = constat.preuve.get("type_service")
        if isinstance(type_service, str):
            types.add(type_service)
        if constat.categorie == "hebergement" and constat.cle == "cdn":
            types.add("cdn")
    return types


def choisir_alternatives(
    score: Score,
    constats: Sequence[Constat],
    alternatives: Mapping[str, Alternative],
    par_besoin: int = ALTERNATIVES_PAR_BESOIN,
) -> list[Alternative]:
    """Alternatives des catégories où l'organisation perd des points.

    - hébergement, messagerie, DNS : les premières alternatives de la catégorie
      (le CDN est proposé en priorité si l'hébergeur est masqué par un CDN) ;
    - SaaS, services tiers, mesure d'audience : alternatives du même type de service.
    L'ordre du référentiel (organisé par pertinence) est conservé.
    """
    choisies: dict[str, Alternative] = {}
    for detail in score.detail:
        if detail.score is None or detail.score >= 100:
            continue
        categorie: CategorieScore = detail.categorie
        candidates = [a for a in alternatives.values() if a.categorie == categorie]
        types = _types_concernes([j.constat_index for j in detail.justifications], constats)
        if categorie in ("hebergement", "messagerie", "dns"):
            prioritaires = [a for a in candidates if types & set(a.types_service)]
            autres = [
                a for a in candidates if a not in prioritaires and "cdn" not in a.types_service
            ]
            for alternative in (prioritaires + autres)[:par_besoin]:
                choisies.setdefault(alternative.id, alternative)
            continue
        for type_service in sorted(types):
            correspondantes = [a for a in candidates if type_service in a.types_service]
            for alternative in correspondantes[:par_besoin]:
                choisies.setdefault(alternative.id, alternative)
    return list(choisies.values())
