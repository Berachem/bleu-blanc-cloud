"""Import des cibles : communes (≥ population minimale), départements et régions."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Collection
from dataclasses import dataclass, field

import httpx

from bleublanccloud.cibles.annuaire import (
    PIVOT_CONSEIL_DEPARTEMENTAL,
    PIVOT_CONSEIL_REGIONAL,
    PIVOT_MAIRIE,
    ServiceAnnuaire,
    choisir_service_principal,
    telecharger_services,
)
from bleublanccloud.cibles.communes import (
    CommuneGeo,
    TerritoireGeo,
    filtrer_par_population,
    telecharger_communes,
    telecharger_departements,
    telecharger_regions,
)
from bleublanccloud.modeles import Organisation
from bleublanccloud.stockage.base import Base

SOURCE = "annuaire-administration+geo.api.gouv.fr"


def slugifier(texte: str) -> str:
    """« Saint-Étienne-du-Rouvray » → « saint-etienne-du-rouvray »."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")


@dataclass
class DonneesImport:
    communes: list[CommuneGeo]
    departements: list[TerritoireGeo]
    regions: list[TerritoireGeo]
    mairies: list[ServiceAnnuaire]
    conseils_departementaux: list[ServiceAnnuaire]
    conseils_regionaux: list[ServiceAnnuaire]


@dataclass
class BilanMairies:
    """Rapprochement des mairies de l'annuaire avec les communes de geo.api.gouv.fr."""

    trouvees: int = 0
    """Mairies trouvées dans l'annuaire (type « mairie » confirmé)."""
    sans_code_insee: int = 0
    """Mairies sans code INSEE exploitable (impossibles à rapprocher)."""
    communes_retenues: int = 0
    """Communes au-dessus du seuil de population."""
    rapprochees: int = 0
    """Communes retenues pour lesquelles une mairie a été trouvée (même code INSEE)."""
    avec_site_web: int = 0
    """Communes retenues dont la mairie a un site web valide."""


def rapprocher_mairies(
    communes: list[CommuneGeo], mairies: list[ServiceAnnuaire]
) -> dict[str, ServiceAnnuaire]:
    """Mairie principale de chaque commune, rapprochée par code INSEE."""
    par_code: dict[str, list[ServiceAnnuaire]] = {}
    for mairie in mairies:
        if mairie.code_insee_commune:
            par_code.setdefault(mairie.code_insee_commune, []).append(mairie)
    resultat: dict[str, ServiceAnnuaire] = {}
    for commune in communes:
        service = choisir_service_principal(par_code.get(commune.code, []))
        if service is not None:
            resultat[commune.code] = service
    return resultat


def bilan_mairies(donnees: DonneesImport, population_min: int) -> BilanMairies:
    retenues = filtrer_par_population(donnees.communes, population_min)
    rapprochement = rapprocher_mairies(retenues, donnees.mairies)
    return BilanMairies(
        trouvees=len(donnees.mairies),
        sans_code_insee=sum(1 for m in donnees.mairies if not m.code_insee_commune),
        communes_retenues=len(retenues),
        rapprochees=len(rapprochement),
        avec_site_web=sum(1 for s in rapprochement.values() if s.site_principal),
    )


@dataclass
class RapportImport:
    organisations: int = 0
    avec_site: int = 0
    sans_site: list[str] = field(default_factory=list)


async def telecharger_donnees(client: httpx.AsyncClient, types: Collection[str]) -> DonneesImport:
    communes = await telecharger_communes(client)
    departements = await telecharger_departements(client)
    regions = await telecharger_regions(client)
    return DonneesImport(
        communes=communes,
        departements=departements,
        regions=regions,
        mairies=await telecharger_services(client, PIVOT_MAIRIE) if "commune" in types else [],
        conseils_departementaux=(
            await telecharger_services(client, PIVOT_CONSEIL_DEPARTEMENTAL)
            if "departement" in types
            else []
        ),
        conseils_regionaux=(
            await telecharger_services(client, PIVOT_CONSEIL_REGIONAL) if "region" in types else []
        ),
    )


def construire_organisations(
    donnees: DonneesImport, population_min: int, types: Collection[str]
) -> list[Organisation]:
    """Croise geo.api.gouv.fr (population, rattachements) et l'annuaire (sites web)."""
    communes_par_code = {c.code: c for c in donnees.communes}
    organisations: list[Organisation] = []

    if "commune" in types:
        retenues = filtrer_par_population(donnees.communes, population_min)
        mairies = rapprocher_mairies(retenues, donnees.mairies)
        for commune in retenues:
            service = mairies.get(commune.code)
            organisations.append(
                Organisation(
                    slug=f"{slugifier(commune.nom)}-{commune.code.lower()}",
                    nom=commune.nom,
                    type="commune",
                    code_commune=commune.code,
                    departement=commune.code_departement,
                    region=commune.code_region,
                    population=commune.population,
                    site_web=service.site_principal if service else None,
                    source=SOURCE,
                )
            )

    def conseils(
        services: list[ServiceAnnuaire], territoire: Callable[[CommuneGeo], str | None]
    ) -> dict[str, ServiceAnnuaire]:
        """Rattache chaque conseil au territoire (département ou région) de sa commune siège."""
        resultat: dict[str, list[ServiceAnnuaire]] = {}
        for service in services:
            commune = communes_par_code.get(service.code_insee_commune or "")
            cle = territoire(commune) if commune else None
            if cle:
                resultat.setdefault(cle, []).append(service)
        choisis = {cle: choisir_service_principal(liste) for cle, liste in resultat.items()}
        return {cle: service for cle, service in choisis.items() if service is not None}

    if "departement" in types:
        par_departement = conseils(donnees.conseils_departementaux, lambda c: c.code_departement)
        for departement in donnees.departements:
            service = par_departement.get(departement.code)
            organisations.append(
                Organisation(
                    slug=f"departement-{slugifier(departement.nom)}",
                    nom=service.nom
                    if service and service.nom
                    else f"Département {departement.nom}",
                    type="departement",
                    departement=departement.code,
                    region=departement.code_region,
                    site_web=service.site_principal if service else None,
                    source=SOURCE,
                )
            )

    if "region" in types:
        par_region = conseils(donnees.conseils_regionaux, lambda c: c.code_region)
        for region in donnees.regions:
            service = par_region.get(region.code)
            siege = communes_par_code.get(service.code_insee_commune or "") if service else None
            organisations.append(
                Organisation(
                    slug=f"region-{slugifier(region.nom)}",
                    nom=service.nom if service and service.nom else f"Région {region.nom}",
                    type="region",
                    departement=siege.code_departement if siege else None,
                    region=region.code,
                    site_web=service.site_principal if service else None,
                    source=SOURCE,
                )
            )
    return organisations


def enregistrer_import(
    base: Base, donnees: DonneesImport, organisations: list[Organisation]
) -> RapportImport:
    for region in donnees.regions:
        base.enregistrer_territoire("region", region.code, region.nom)
    for departement in donnees.departements:
        base.enregistrer_territoire(
            "departement", departement.code, departement.nom, departement.code_region
        )
    rapport = RapportImport()
    for organisation in organisations:
        base.enregistrer_organisation(organisation)
        rapport.organisations += 1
        if organisation.site_web:
            rapport.avec_site += 1
        else:
            rapport.sans_site.append(organisation.nom)
    return rapport
