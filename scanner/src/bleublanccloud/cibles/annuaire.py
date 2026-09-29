"""Import depuis l'API « Annuaire de l'administration et des services publics » (DILA).

Seuls les champs nécessaires sont demandés (nom, type, site web, code commune) : les adresses
électroniques et numéros de téléphone de l'annuaire ne sont JAMAIS téléchargés ni publiés.

Format réel d'un enregistrement (les champs `pivot` et `site_internet` sont des listes JSON
sérialisées en texte) :

    {"nom": "Mairie - Grenoble", "code_insee_commune": "38185",
     "site_internet": "[{\\"libelle\\": \\"\\", \\"valeur\\": \\"https://www.grenoble.fr/\\"}]",
     "pivot": "[{\\"type_service_local\\": \\"mairie\\", \\"code_insee_commune\\": [\\"38185\\"]}]"}

Documentation : https://www.data.gouv.fr/dataservices/api-annuaire-de-ladministration-et-des-services-publics
Syntaxe des requêtes : Opendatasoft Explore v2.1 (ODSQL).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

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
# Repli pour les valeurs JSON tronquées ou mal formées
MOTIF_VALEUR = re.compile(r'"valeur"\s*:\s*"([^"]*)"')
MOTIF_TYPE_PIVOT = re.compile(r'"type_service_local"\s*:\s*"([^"]+)"')
MOTIF_CODE_INSEE = re.compile(r"^(\d{5}|2[AB]\d{3})$")
MOTIF_AUTRE_SCHEMA = re.compile(r"^[a-z][a-z0-9+.-]*:(?!//)(?!\d)", re.IGNORECASE)
MOTIF_NOM_HOTE = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class ServiceAnnuaire(BaseModel):
    nom: str
    pivots: list[str]
    sites: list[str]
    code_insee_commune: str | None = None

    @property
    def site_principal(self) -> str | None:
        """Premier site web valide (les valeurs vides ont déjà été écartées)."""
        return self.sites[0] if self.sites else None


def filtre_pivot(pivot: str) -> str:
    """Clause ODSQL : `pivot` est un texte JSON, une égalité stricte ne trouverait rien."""
    return f'pivot like "{pivot}"'


def decoder_liste_json(valeur: Any) -> list[Any] | None:
    """Décode une liste JSON éventuellement sérialisée en texte (voire deux fois).

    Retourne [] pour une valeur vide, None si le texte est mal formé.
    """
    for _ in range(3):
        if valeur is None:
            return []
        if isinstance(valeur, list):
            return valeur
        if isinstance(valeur, dict):
            return [valeur]
        if not isinstance(valeur, str):
            return None
        texte = valeur.strip()
        if texte in ("", "null", "[]", "{}"):
            return []
        if not texte.startswith(("[", "{", '"')):
            return None
        try:
            valeur = json.loads(texte)
        except json.JSONDecodeError:
            return None
    return None


def normaliser_url_site(texte: Any) -> str | None:
    """Transforme une valeur du champ site web en URL http(s) valide, sinon None."""
    if not isinstance(texte, str):
        return None
    url = texte.strip()
    if not url:
        return None
    if "://" not in url:
        if MOTIF_AUTRE_SCHEMA.match(url):
            return None  # mailto:, tel:… ne sont pas des sites web
        url = f"https://{url.removeprefix('//')}"
    try:
        morceaux = urlsplit(url)
        hote = (morceaux.hostname or "").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError):
        return None
    if (
        morceaux.scheme not in ("http", "https")
        or "@" in morceaux.netloc
        or not MOTIF_NOM_HOTE.match(hote)
    ):
        return None
    return url


def extraire_sites(valeur: Any) -> list[str]:
    """Sites web valides, dans l'ordre, sans doublon (champ `site_internet`)."""
    elements = decoder_liste_json(valeur)
    candidats: list[Any]
    if elements is None:
        texte = valeur if isinstance(valeur, str) else ""
        candidats = MOTIF_VALEUR.findall(texte) or [texte]
    else:
        candidats = [e.get("valeur") if isinstance(e, dict) else e for e in elements]
    sites: list[str] = []
    for candidat in candidats:
        url = normaliser_url_site(candidat)
        if url and url not in sites:
            sites.append(url)
    return sites


def normaliser_code_insee(valeur: Any) -> str | None:
    """Code INSEE sur 5 caractères (« 1001 » → « 01001 », « 2a004 » → « 2A004 »), sinon None."""
    if isinstance(valeur, list):
        valeur = next((v for v in valeur if normaliser_code_insee(v)), None)
    if isinstance(valeur, bool) or valeur is None:
        return None
    texte = str(valeur).strip().upper()
    if texte.isdigit() and len(texte) == 4:
        texte = texte.zfill(5)
    return texte if MOTIF_CODE_INSEE.match(texte) else None


def analyser_pivot(valeur: Any) -> tuple[list[str], list[str]]:
    """Types de service et codes INSEE déclarés dans le champ `pivot`."""
    elements = decoder_liste_json(valeur)
    if elements is None:
        texte = valeur.strip() if isinstance(valeur, str) else ""
        types_repli: list[str] = MOTIF_TYPE_PIVOT.findall(texte)
        if not types_repli and re.fullmatch(r"[a-z_]+", texte):
            types_repli = [texte]
        return types_repli, []
    types: list[str] = []
    codes: list[str] = []
    for element in elements:
        if isinstance(element, dict):
            if element.get("type_service_local"):
                types.append(str(element["type_service_local"]))
            code = normaliser_code_insee(element.get("code_insee_commune"))
            if code:
                codes.append(code)
        elif isinstance(element, str) and element.strip():
            types.append(element.strip())
    return types, codes


def extraire_pivots(valeur: Any) -> list[str]:
    return analyser_pivot(valeur)[0]


def analyser_enregistrement(enregistrement: dict[str, Any]) -> ServiceAnnuaire:
    types, codes_pivot = analyser_pivot(enregistrement.get("pivot"))
    code = normaliser_code_insee(enregistrement.get("code_insee_commune"))
    return ServiceAnnuaire(
        nom=str(enregistrement.get("nom") or "").strip(),
        pivots=types,
        sites=extraire_sites(enregistrement.get("site_internet")),
        code_insee_commune=code or (codes_pivot[0] if codes_pivot else None),
    )


def filtrer_services(enregistrements: Any, pivot: str) -> list[ServiceAnnuaire]:
    """Garde les enregistrements dont le type est confirmé (le filtre `like` est approximatif)."""
    if not isinstance(enregistrements, list):
        journal.warning("Réponse inattendue de l'annuaire (liste attendue) : ignorée.")
        return []
    services: list[ServiceAnnuaire] = []
    ecartes = 0
    for enregistrement in enregistrements:
        if not isinstance(enregistrement, dict):
            ecartes += 1
            continue
        service = analyser_enregistrement(enregistrement)
        if pivot in service.pivots:
            services.append(service)
        else:
            ecartes += 1
    if ecartes:
        journal.info("%d enregistrement(s) « %s » écarté(s) (type non confirmé).", ecartes, pivot)
    return services


async def telecharger_services(client: httpx.AsyncClient, pivot: str) -> list[ServiceAnnuaire]:
    """Tous les services d'un type (ex. toutes les mairies), champs utiles seulement."""
    reponse = await client.get(
        URL_EXPORT, params={"select": CHAMPS, "where": filtre_pivot(pivot)}, timeout=120
    )
    reponse.raise_for_status()
    return filtrer_services(reponse.json(), pivot)


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
