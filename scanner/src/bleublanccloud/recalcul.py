"""Recalcul des scores sans rescanner (« bbcloud scores recalculer »).

Chaque scan noté est relu depuis la base, ses constats sont réattribués avec les référentiels
courants (voir `analyse.reattribution`), puis son score est recalculé selon la méthodologie
en vigueur. Aucune requête réseau n'est émise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bleublanccloud.analyse.attribution import Attributeur
from bleublanccloud.analyse.couverture import CouvertureObservatoire, mesurer_couverture
from bleublanccloud.analyse.reattribution import reattribuer_constats
from bleublanccloud.analyse.score import ScoreImpossible, calculer_score
from bleublanccloud.export.site_statique import score_a_jour
from bleublanccloud.modeles import Note, Score
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import fournisseurs_secnumcloud
from bleublanccloud.stockage.base import Base, ScanEnregistre


@dataclass(frozen=True)
class Changement:
    """Évolution du score d'un scan après recalcul."""

    scan_id: int
    organisation_id: int | None
    domaine: str
    ancien_score: int
    ancienne_note: Note
    ancien_provisoire: bool
    nouveau_score: int
    nouvelle_note: Note
    nouveau_provisoire: bool
    constats_modifies: int


@dataclass
class BilanRecalcul:
    """Résumé d'un recalcul (ou de sa simulation avec `appliquer=False`)."""

    appliquer: bool
    scans_examines: int = 0
    scans_modifies: int = 0
    constats_modifies: int = 0
    scores_impossibles: int = 0
    rapports_obsoletes: int = 0
    changements: list[Changement] = field(default_factory=list)
    couverture_avant: CouvertureObservatoire = field(default_factory=CouvertureObservatoire)
    couverture_apres: CouvertureObservatoire = field(default_factory=CouvertureObservatoire)

    @property
    def notes_modifiees(self) -> list[Changement]:
        return [
            c
            for c in self.changements
            if (c.ancienne_note, c.ancien_provisoire) != (c.nouvelle_note, c.nouveau_provisoire)
        ]


def _scans_observatoire(base: Base, referentiels: Referentiels) -> list[ScanEnregistre]:
    """Dernier scan noté de chaque organisation de l'observatoire, hors domaines retirés
    (le périmètre des statistiques publiées)."""
    return [
        scan
        for scan in base.scans_notes(observatoire=True)
        if not referentiels.est_retire(scan.resultat.domaine)
    ]


def recalculer_scores(
    base: Base, referentiels: Referentiels, appliquer: bool = True, tous: bool = False
) -> BilanRecalcul:
    """Réattribue les constats et recalcule le score du dernier scan noté de chaque
    organisation (de tout l'historique si `tous`). Avec `appliquer=False`, rien n'est écrit.
    """
    attributeur = Attributeur(referentiels.fournisseurs, referentiels.transitaires.values())
    bilan = BilanRecalcul(appliquer=appliquer)
    derniers = {s.id for s in _scans_observatoire(base, referentiels)}
    avant: list[Score] = []
    apres: list[Score] = []
    for scan in base.scans_notes(tous=tous):
        bilan.scans_examines += 1
        ancien = score_a_jour(scan)
        anciens_constats = scan.resultat.constats
        constats = reattribuer_constats(anciens_constats, attributeur, referentiels.regles)
        try:
            score = calculer_score(constats, scan.resultat.sondes_reussies)
        except ScoreImpossible:
            bilan.scores_impossibles += 1
            continue
        if scan.id in derniers:
            avant.append(ancien)
            apres.append(score)
        modifies = sum(a != b for a, b in zip(anciens_constats, constats, strict=True))
        score_modifie = (score.score_global, score.note, score.provisoire) != (
            ancien.score_global,
            ancien.note,
            ancien.provisoire,
        )
        stocke_a_jour = scan.score == score
        if not modifies and stocke_a_jour:
            continue
        bilan.scans_modifies += 1
        bilan.constats_modifies += modifies
        if modifies or score_modifie:
            bilan.changements.append(
                Changement(
                    scan_id=scan.id,
                    organisation_id=scan.organisation_id,
                    domaine=scan.resultat.domaine,
                    ancien_score=ancien.score_global,
                    ancienne_note=ancien.note,
                    ancien_provisoire=ancien.provisoire,
                    nouveau_score=score.score_global,
                    nouvelle_note=score.note,
                    nouveau_provisoire=score.provisoire,
                    constats_modifies=modifies,
                )
            )
            if base.rapport_du_scan(scan.id) is not None:
                bilan.rapports_obsoletes += 1
        if appliquer:
            informations = scan.resultat.informations.model_copy(
                update={
                    "fournisseurs_secnumcloud": fournisseurs_secnumcloud(constats, referentiels)
                }
            )
            base.mettre_a_jour_scan(
                scan.id, constats, informations, score, revise=bool(modifies or score_modifie)
            )
    bilan.couverture_avant = mesurer_couverture(avant)
    bilan.couverture_apres = mesurer_couverture(apres)
    return bilan


def couverture_observatoire(base: Base, referentiels: Referentiels) -> CouvertureObservatoire:
    """Couverture actuelle : dernier scan noté de chaque organisation de l'observatoire, avec
    le score tel qu'il est publié (recalculé si la méthodologie a changé depuis)."""
    scans = _scans_observatoire(base, referentiels)
    return mesurer_couverture(score_a_jour(scan) for scan in scans)


__all__ = [
    "BilanRecalcul",
    "Changement",
    "couverture_observatoire",
    "recalculer_scores",
]
