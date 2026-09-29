"""Import depuis l'API « Annuaire de l'administration et des services publics » (DILA).

Seuls les champs nécessaires sont demandés (nom, type, site web, code commune) : les adresses
électroniques et numéros de téléphone de l'annuaire ne sont JAMAIS téléchargés ni publiés.

Documentation : https://www.data.gouv.fr/dataservices/api-annuaire-de-ladministration-et-des-services-publics
Syntaxe des requêtes : Opendatasoft Explore v2.1 (ODSQL).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel

journal = logging.getLogger(__name__)

# Domaine « .gouv.fr » en service depuis le 1er octobre 2025 (l'ancien domaine a été arrêté).
URL_EXPORT = (
    "https://api-lannuaire.service-public.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "api-lannuaire-administration/exports/json"
)
CHAMPS = "nom,pivot,site_internet,code_insee_commune"

# Codes « pivot » des types de services (référentiel de l'annuaire)
PIVOT_MAIRIE = "mairie"
PIVOT_CONSEIL_DEPARTEMENTAL = "cg"
PIVOT_CONSEIL_REGIONAL = "cr"

MOTS_SECONDAIRES = re.compile(
    r"annexe|d[ée]l[ée]gu[ée]e|arrondissement|mobile|secteur|antenne|point|relais", re.IGNORECASE
)


class ServiceAnnuaire(BaseModel):
    nom: str
    pivots: list[str]
    sites: list[str]
    code_insee_commune: str | None = None

    @property
    def site_principal(self) -> str | None:
        return self.sites[0] if self.sites else None


def _decoder_json(valeur: Any) -> Any:
    if isinstance(valeur, str):
        texte = valeur.strip()
        if texte.startswith(("[", "{")):
            try:
                return json.loads(texte)
            except json.JSONDecodeError:
                return valeur
    return valeur


def extraire_sites(valeur: Any) -> list[str]:
    """Le champ site_internet est une liste JSON de {libelle, valeur} (parfois une chaîne)."""
    valeur = _decoder_json(valeur)
    if valeur is None:
        return []
    if isinstance(valeur, str):
        valeur = [valeur]
    if isinstance(valeur, dict):
        valeur = [valeur]
    sites: list[str] = []
    for element in valeur:
        url = element.get("valeur") if isinstance(element, dict) else element
        if isinstance(url, str) and url.strip():
            url = url.strip()
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            sites.append(url)
    return sites


def extraire_pivots(valeur: Any) -> list[str]:
    """Le champ pivot est une liste JSON de {type_service_local, code_insee_commune}."""
    valeur = _decoder_json(valeur)
    if valeur is None:
        return []
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, dict):
        valeur = [valeur]
    pivots: list[str] = []
    for element in valeur:
        if isinstance(element, dict) and element.get("type_service_local"):
            pivots.append(str(element["type_service_local"]))
        elif isinstance(element, str):
            pivots.append(element)
    return pivots


def analyser_enregistrement(enregistrement: dict[str, Any]) -> ServiceAnnuaire:
    code = enregistrement.get("code_insee_commune")
    return ServiceAnnuaire(
        nom=str(enregistrement.get("nom") or "").strip(),
        pivots=extraire_pivots(enregistrement.get("pivot")),
        sites=extraire_sites(enregistrement.get("site_internet")),
        code_insee_commune=str(code) if code else None,
    )


async def telecharger_services(client: httpx.AsyncClient, pivot: str) -> list[ServiceAnnuaire]:
    """Tous les services d'un type (ex. toutes les mairies), champs utiles seulement."""
    reponse = await client.get(
        URL_EXPORT, params={"select": CHAMPS, "where": f'pivot="{pivot}"'}, timeout=120
    )
    reponse.raise_for_status()
    services = [analyser_enregistrement(e) for e in reponse.json()]
    return [s for s in services if not s.pivots or pivot in s.pivots]


def choisir_service_principal(candidats: list[ServiceAnnuaire]) -> ServiceAnnuaire | None:
    """Parmi plusieurs services d'une même commune, garde la mairie principale avec site web."""
    if not candidats:
        return None

    def rang(service: ServiceAnnuaire) -> tuple[int, int, int]:
        return (
            0 if service.site_principal else 1,
            1 if MOTS_SECONDAIRES.search(service.nom) else 0,
            len(service.nom),
        )

    return sorted(candidats, key=rang)[0]
