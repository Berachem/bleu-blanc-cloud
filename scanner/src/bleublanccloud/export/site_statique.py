"""Export des fichiers JSON statiques consommés par le site (contrat de données, section 11).

- meta.json : date de campagne, version méthodologie, nombre d'organisations ;
- index.json : liste légère ;
- organisations/{slug}.json : détail complet ;
- departements.json : agrégats par département ;
- alternatives.json : référentiel des alternatives (page /alternatives).

Aucune donnée personnelle n'est exportée (ni e-mail, ni téléphone, ni nom de personne).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from bleublanccloud.analyse.alternatives import choisir_alternatives
from bleublanccloud.analyse.attribution import niveau_juridiction
from bleublanccloud.analyse.score import (
    VERSION_METHODO,
    ScoreImpossible,
    calculer_score,
    note_depuis_score,
)
from bleublanccloud.modeles import (
    Alternative,
    AlternativeExport,
    DepartementExport,
    EntreeIndex,
    FournisseurExport,
    MetaExport,
    Organisation,
    OrganisationExport,
    RapportIAExport,
    Score,
)
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import normaliser_cible
from bleublanccloud.stockage.base import Base, RapportEnregistre, ScanEnregistre


@dataclass
class RapportExport:
    nombre_organisations: int = 0
    ignorees: list[str] = field(default_factory=list)
    fichiers_supprimes: int = 0


def exporter_alternative(alternative: Alternative) -> AlternativeExport:
    return AlternativeExport(
        id=alternative.id,
        nom=alternative.nom,
        pays=alternative.pays,
        url=str(alternative.url),
        categorie=alternative.categorie,
        types_service=alternative.types_service,
        description_courte=alternative.description_courte,
        a_verifier=alternative.a_verifier,
    )


def fournisseurs_cites(
    ids: Iterable[str | None], referentiels: Referentiels
) -> dict[str, FournisseurExport]:
    resultat: dict[str, FournisseurExport] = {}
    for fournisseur_id in sorted({i for i in ids if i}):
        fournisseur = referentiels.fournisseurs.get(fournisseur_id)
        if fournisseur is None:
            continue
        resultat[fournisseur_id] = FournisseurExport(
            id=fournisseur.id,
            nom=fournisseur.nom,
            pays_siege=fournisseur.pays_siege,
            maison_mere=fournisseur.maison_mere,
            pays_maison_mere=fournisseur.pays_maison_mere,
            soumis_cloud_act=fournisseur.soumis_cloud_act,
            autre_loi_extraterritoriale=fournisseur.autre_loi_extraterritoriale,
            propose_offre_secnumcloud=fournisseur.propose_offre_secnumcloud,
            niveau=niveau_juridiction(fournisseur),
            a_verifier=fournisseur.a_verifier,
        )
    return resultat


def score_a_jour(scan: ScanEnregistre) -> Score:
    """Score du scan, recalculé à partir des constats enregistrés si la méthodologie a changé
    depuis (ex. indicateur de couverture de la v1.2 absent d'un score v1.0)."""
    assert scan.score is not None
    if scan.score.version_methodo == VERSION_METHODO:
        return scan.score
    try:
        return calculer_score(scan.resultat.constats, scan.resultat.sondes_reussies)
    except ScoreImpossible:
        return scan.score


def construire_organisation(
    organisation: Organisation,
    scan: ScanEnregistre,
    referentiels: Referentiels,
    rapport: RapportEnregistre | None,
    noms_departements: dict[str, str],
    noms_regions: dict[str, str],
) -> OrganisationExport:
    score = score_a_jour(scan)
    resultat = scan.resultat
    alternatives = choisir_alternatives(score, resultat.constats, referentiels.alternatives)
    return OrganisationExport(
        slug=organisation.slug,
        nom=organisation.nom,
        type=organisation.type,
        departement=organisation.departement,
        departement_nom=noms_departements.get(organisation.departement or ""),
        region=organisation.region,
        region_nom=noms_regions.get(organisation.region or ""),
        population=organisation.population,
        site_web=organisation.site_web,
        domaine=resultat.domaine,
        date_scan=resultat.debut,
        statut_scan=resultat.statut,
        score=score,
        constats=resultat.constats,
        informations=resultat.informations,
        fournisseurs=fournisseurs_cites(
            (c.fournisseur_id for c in resultat.constats), referentiels
        ),
        rapport_ia=(
            RapportIAExport(
                contenu=rapport.contenu,
                modele=rapport.modele,
                version_invite=rapport.version_invite,
                genere_le=rapport.cree_le,
            )
            if rapport
            else None
        ),
        alternatives=[exporter_alternative(a) for a in alternatives],
    )


def entree_index(organisation: OrganisationExport) -> EntreeIndex:
    return EntreeIndex(
        slug=organisation.slug,
        nom=organisation.nom,
        type=organisation.type,
        departement=organisation.departement,
        departement_nom=organisation.departement_nom,
        region=organisation.region,
        population=organisation.population,
        domaine=organisation.domaine,
        score=organisation.score.score_global,
        note=organisation.score.note,
        note_provisoire=organisation.score.provisoire,
        date_scan=organisation.date_scan,
    )


def agreger_departements(
    entrees: Sequence[EntreeIndex], noms: dict[str, tuple[str, str | None]]
) -> list[DepartementExport]:
    par_departement: dict[str, list[EntreeIndex]] = {}
    for entree in entrees:
        # Les analyses sur demande restent hors des statistiques de l'observatoire
        if entree.departement and entree.type != "sur_demande":
            par_departement.setdefault(entree.departement, []).append(entree)
    resultat: list[DepartementExport] = []
    for code in sorted(set(par_departement) | set(noms)):
        membres = par_departement.get(code, [])
        nom, region = noms.get(code, (membres[0].departement_nom if membres else code, None))
        moyenne = sum(e.score for e in membres) / len(membres) if membres else None
        repartition = {note: 0 for note in "ABCDE"}
        for membre in membres:
            repartition[membre.note] += 1
        resultat.append(
            DepartementExport(
                code=code,
                nom=nom or code,
                region=region or (membres[0].region if membres else None),
                nombre_organisations=len(membres),
                score_moyen=round(moyenne, 1) if moyenne is not None else None,
                note_moyenne=note_depuis_score(moyenne) if moyenne is not None else None,
                repartition_notes=repartition,
            )
        )
    return resultat


def _ecrire(chemin: Path, donnees: BaseModel | list[dict[str, Any]]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(donnees, BaseModel):
        texte = donnees.model_dump_json()
    else:
        texte = json.dumps(donnees, ensure_ascii=False, separators=(",", ":"))
    chemin.write_text(texte, encoding="utf-8")


def ecrire_export(
    dossier: Path,
    organisations: Sequence[OrganisationExport],
    departements_noms: dict[str, tuple[str, str | None]],
    referentiels: Referentiels,
    date_campagne: datetime | None = None,
    donnees_demonstration: bool = False,
) -> RapportExport:
    """Écrit l'ensemble des fichiers du contrat de données."""
    rapport = RapportExport(nombre_organisations=len(organisations))
    dossier_orgs = dossier / "organisations"
    dossier_orgs.mkdir(parents=True, exist_ok=True)
    slugs = {o.slug for o in organisations}
    for ancien in dossier_orgs.glob("*.json"):
        if ancien.stem not in slugs:
            ancien.unlink()
            rapport.fichiers_supprimes += 1

    for organisation in organisations:
        _ecrire(dossier_orgs / f"{organisation.slug}.json", organisation)
    entrees = sorted((entree_index(o) for o in organisations), key=lambda e: e.nom)
    _ecrire(dossier / "index.json", [e.model_dump(mode="json") for e in entrees])
    departements = agreger_departements(entrees, departements_noms)
    _ecrire(dossier / "departements.json", [d.model_dump(mode="json") for d in departements])
    _ecrire(
        dossier / "alternatives.json",
        [
            exporter_alternative(a).model_dump(mode="json")
            for a in referentiels.alternatives.values()
        ],
    )
    observatoire = [o for o in organisations if o.type != "sur_demande"]
    # La date de campagne ne dépend que de l'observatoire (les demandes arrivent chaque jour)
    dates = [o.date_scan for o in observatoire] or [o.date_scan for o in organisations]
    _ecrire(
        dossier / "meta.json",
        MetaExport(
            date_campagne=date_campagne or (max(dates) if dates else datetime.now(UTC)),
            date_export=datetime.now(UTC),
            version_methodo=VERSION_METHODO,
            nombre_organisations=len(observatoire),
            nombre_sur_demande=len(organisations) - len(observatoire),
            donnees_demonstration=donnees_demonstration,
        ),
    )
    return rapport


def exporter(base: Base, referentiels: Referentiels, dossier: Path) -> RapportExport:
    """Exporte le dernier scan noté de chaque organisation."""
    departements = base.territoires("departement")
    regions = base.territoires("region")
    noms_departements = {code: nom for code, (nom, _) in departements.items()}
    noms_regions = {code: nom for code, (nom, _) in regions.items()}
    organisations: list[OrganisationExport] = []
    ignorees: list[str] = []
    for enregistree in base.organisations():
        scan = base.dernier_scan(enregistree.id)
        if scan is None or scan.score is None:
            continue
        domaine = scan.resultat.domaine
        if referentiels.est_retire(domaine):
            ignorees.append(f"{enregistree.organisation.slug} (retrait demandé)")
            continue
        rapport = base.rapport_du_scan(scan.id)
        organisations.append(
            construire_organisation(
                enregistree.organisation,
                scan,
                referentiels,
                rapport,
                noms_departements,
                noms_regions,
            )
        )
    rapport_export = ecrire_export(dossier, organisations, departements, referentiels)
    rapport_export.ignorees = ignorees
    return rapport_export


def domaine_organisation(organisation: Organisation) -> str | None:
    """Domaine à analyser pour une organisation (à partir de son site web)."""
    if not organisation.site_web:
        return None
    try:
        return normaliser_cible(organisation.site_web).domaine
    except ValueError:
        return None
