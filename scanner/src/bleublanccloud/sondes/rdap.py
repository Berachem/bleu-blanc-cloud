"""Sonde RDAP : bureau d'enregistrement du domaine (information affichée, non notée en v1)."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

journal = logging.getLogger(__name__)

# Repli minimal si l'amorçage IANA n'a pas été téléchargé (bbcloud referentiels maj).
SERVEURS_RDAP_PAR_DEFAUT = {
    "fr": "https://rdap.nic.fr/",
    "com": "https://rdap.verisign.com/com/v1/",
    "net": "https://rdap.verisign.com/net/v1/",
}


class DonneesRdap(BaseModel):
    domaine: str
    serveur_rdap: str | None = None
    bureau_enregistrement: str | None = None
    erreur: str | None = None


def charger_amorcage(chemin: Path) -> dict[str, str]:
    """Lit l'amorçage IANA (dns.json) : extension → URL du serveur RDAP."""
    serveurs = dict(SERVEURS_RDAP_PAR_DEFAUT)
    if not chemin.exists():
        return serveurs
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    for extensions, urls in donnees.get("services", []):
        url = next((u for u in urls if u.startswith("https://")), urls[0] if urls else None)
        if url is None:
            continue
        for extension in extensions:
            serveurs[extension.lower()] = url if url.endswith("/") else url + "/"
    return serveurs


def _nom_vcard(entite: dict[str, Any]) -> str | None:
    vcard = entite.get("vcardArray")
    if isinstance(vcard, list) and len(vcard) == 2:
        for propriete in vcard[1]:
            if isinstance(propriete, list) and len(propriete) >= 4 and propriete[0] == "fn":
                return str(propriete[3]) or None
    return None


def extraire_bureau(reponse: dict[str, Any]) -> str | None:
    """Cherche récursivement l'entité de rôle « registrar »."""
    for entite in reponse.get("entities", []) or []:
        if "registrar" in (entite.get("roles") or []):
            return _nom_vcard(entite) or entite.get("handle")
        imbrique = extraire_bureau(entite)
        if imbrique:
            return imbrique
    return None


ObtenirJson = Callable[[str], Awaitable[httpx.Response]]


async def sonder_rdap(domaine: str, obtenir: ObtenirJson, serveurs: dict[str, str]) -> DonneesRdap:
    """Interroge le serveur RDAP du registre (une seule requête par domaine)."""
    donnees = DonneesRdap(domaine=domaine)
    extension = domaine.rsplit(".", 1)[-1].lower()
    serveur = serveurs.get(extension)
    if serveur is None:
        donnees.erreur = f"aucun serveur RDAP connu pour .{extension}"
        return donnees
    donnees.serveur_rdap = serveur
    try:
        reponse = await obtenir(f"{serveur}domain/{domaine}")
        reponse.raise_for_status()
        donnees.bureau_enregistrement = extraire_bureau(reponse.json())
    except (httpx.HTTPError, ValueError) as erreur:
        donnees.erreur = f"RDAP : {type(erreur).__name__}"
    return donnees
