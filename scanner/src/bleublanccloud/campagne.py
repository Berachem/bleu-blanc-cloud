"""Campagne : scan de toutes les organisations connues, calcul et enregistrement des scores."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from bleublanccloud.analyse.score import VERSION_METHODO, ScoreImpossible, calculer_score
from bleublanccloud.modeles import ResultatScan, Score
from bleublanccloud.scan import CibleInvalide, ContexteScan, normaliser_cible, scanner_domaine
from bleublanccloud.stockage.base import Base, OrganisationEnregistree

journal = logging.getLogger(__name__)

SCANS_SIMULTANES_MAX = 10


@dataclass(frozen=True)
class CibleCampagne:
    organisation: OrganisationEnregistree
    domaine: str
    url: str


@dataclass
class RapportCampagne:
    prevues: int = 0
    scannees: int = 0
    notees: int = 0
    erreurs: list[str] = field(default_factory=list)
    ignorees: list[str] = field(default_factory=list)
    notes: dict[str, int] = field(default_factory=dict)


def preparer_cibles(
    organisations: Sequence[OrganisationEnregistree],
    est_retire: Callable[[str], bool],
    limite: int | None = None,
) -> tuple[list[CibleCampagne], list[str]]:
    """Organisations à scanner (site web valide, domaine non retiré), sans aucun appel réseau."""
    cibles: list[CibleCampagne] = []
    ignorees: list[str] = []
    for enregistree in organisations:
        organisation = enregistree.organisation
        if organisation.type == "sur_demande":
            continue  # analysée uniquement à la demande, hors observatoire
        if not organisation.site_web:
            ignorees.append(f"{organisation.nom} : aucun site web connu")
            continue
        try:
            cible = normaliser_cible(organisation.site_web)
        except CibleInvalide:
            ignorees.append(f"{organisation.nom} : site web invalide ({organisation.site_web})")
            continue
        if est_retire(cible.domaine):
            ignorees.append(f"{organisation.nom} : retrait demandé")
            continue
        cibles.append(CibleCampagne(enregistree, cible.domaine, cible.url_site))
        if limite is not None and len(cibles) >= limite:
            break
    return cibles, ignorees


async def lancer_campagne(
    base: Base,
    contexte: ContexteScan,
    cibles: Sequence[CibleCampagne],
    scans_simultanes: int = SCANS_SIMULTANES_MAX,
    progression: Callable[[CibleCampagne, ResultatScan], None] | None = None,
) -> RapportCampagne:
    """Scanne les cibles (un même domaine n'est scanné qu'une fois) et enregistre les scores."""
    rapport = RapportCampagne(prevues=len(cibles))
    semaphore = asyncio.Semaphore(scans_simultanes)
    resultats_par_domaine: dict[str, asyncio.Task[ResultatScan]] = {}

    async def scanner(url: str) -> ResultatScan:
        async with semaphore:
            return await scanner_domaine(url, contexte)

    async def traiter(cible: CibleCampagne) -> None:
        if cible.domaine not in resultats_par_domaine:
            resultats_par_domaine[cible.domaine] = asyncio.create_task(scanner(cible.url))
        try:
            resultat = await resultats_par_domaine[cible.domaine]
        except Exception as erreur:  # une organisation en échec ne bloque pas les autres
            journal.exception("Échec du scan de %s", cible.domaine)
            rapport.erreurs.append(f"{cible.organisation.organisation.nom} : {erreur}")
            return
        score: Score | None
        try:
            score = calculer_score(resultat.constats, resultat.sondes_reussies)
        except ScoreImpossible:
            score = None
            rapport.erreurs.append(f"{cible.organisation.organisation.nom} : score impossible")
        base.enregistrer_scan(cible.organisation.id, resultat, score, VERSION_METHODO)
        rapport.scannees += 1
        if score is not None:
            rapport.notees += 1
            rapport.notes[score.note] = rapport.notes.get(score.note, 0) + 1
        if progression is not None:
            progression(cible, resultat)

    await asyncio.gather(*(traiter(cible) for cible in cibles))
    return rapport
