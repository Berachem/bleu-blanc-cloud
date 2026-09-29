"""Planification et exécution de la génération des rapports IA pour les derniers scans."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from bleublanccloud.analyse.alternatives import choisir_alternatives
from bleublanccloud.ia.client_mistral import (
    DemandeRapport,
    GenerateurRapports,
    empreinte_constats,
)
from bleublanccloud.ia.invites import VERSION_INVITE
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base, RapportEnregistre


@dataclass(frozen=True)
class TacheRapport:
    scan_id: int
    nom: str
    empreinte: str
    demande: DemandeRapport


@dataclass
class PlanRapports:
    a_generer: list[TacheRapport] = field(default_factory=list)
    depuis_cache: list[tuple[int, str, RapportEnregistre]] = field(default_factory=list)
    deja_a_jour: int = 0


@dataclass
class BilanRapports:
    generes: int = 0
    depuis_cache: int = 0
    en_erreur: list[str] = field(default_factory=list)
    appels: int = 0
    jetons_entree: int = 0
    jetons_sortie: int = 0


def planifier(base: Base, referentiels: Referentiels, modele: str) -> PlanRapports:
    """Répartit les derniers scans notés entre : déjà à jour, cache réutilisable, à générer."""
    plan = PlanRapports()
    for enregistree in base.organisations():
        scan = base.dernier_scan(enregistree.id)
        if scan is None or scan.score is None:
            continue
        if referentiels.est_retire(scan.resultat.domaine):
            continue
        existant = base.rapport_du_scan(scan.id)
        if existant and existant.modele == modele and existant.version_invite == VERSION_INVITE:
            plan.deja_a_jour += 1
            continue
        empreinte = empreinte_constats(scan.resultat.constats, VERSION_INVITE, modele)
        cache = base.rapport_en_cache(empreinte, modele, VERSION_INVITE)
        if cache is not None:
            plan.depuis_cache.append((scan.id, empreinte, cache))
            continue
        organisation = enregistree.organisation
        plan.a_generer.append(
            TacheRapport(
                scan_id=scan.id,
                nom=organisation.nom,
                empreinte=empreinte,
                demande=DemandeRapport(
                    nom_organisation=organisation.nom,
                    type_organisation=organisation.type,
                    score=scan.score,
                    constats=scan.resultat.constats,
                    alternatives=choisir_alternatives(
                        scan.score, scan.resultat.constats, referentiels.alternatives
                    ),
                ),
            )
        )
    return plan


def appliquer_cache(base: Base, plan: PlanRapports, modele: str) -> int:
    """Rattache aux nouveaux scans les rapports déjà générés pour des constats identiques."""
    for scan_id, empreinte, rapport in plan.depuis_cache:
        base.enregistrer_rapport(scan_id, empreinte, modele, VERSION_INVITE, rapport.contenu)
    return len(plan.depuis_cache)


async def generer_rapports(
    base: Base,
    taches: list[TacheRapport],
    generateur: GenerateurRapports,
    progression: Callable[[TacheRapport], None] | None = None,
) -> BilanRapports:
    """Génère les rapports un par un (respect des limites de débit de l'API)."""
    bilan = BilanRapports()
    for tache in taches:
        resultat = await generateur.generer(tache.demande)
        bilan.appels += resultat.appels
        bilan.jetons_entree += resultat.jetons_entree
        bilan.jetons_sortie += resultat.jetons_sortie
        base.enregistrer_rapport(
            tache.scan_id,
            tache.empreinte,
            generateur.modele,
            VERSION_INVITE,
            resultat.rapport,
            erreur=resultat.erreur,
            jetons=(resultat.jetons_entree, resultat.jetons_sortie),
        )
        if resultat.rapport is not None:
            bilan.generes += 1
        else:
            bilan.en_erreur.append(f"{tache.nom} : {resultat.erreur}")
        if progression is not None:
            progression(tache)
    return bilan
