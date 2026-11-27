"""Universités publiques : jeu de données « Principaux établissements d'enseignement
supérieur » du ministère de l'Enseignement supérieur (Licence Ouverte 2.0), voir ADR-0006.

Les noms de champs de la plateforme open data du ministère sont lus avec tolérance
(plusieurs noms possibles, comparés sans accents ni casse) : l'aperçu de la commande
`bbcloud cibles universites` permet de vérifier la liste avant tout enregistrement.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

from bleublanccloud.cibles.importation import slugifier
from bleublanccloud.modeles import Organisation

JEU_DE_DONNEES = "fr-esr-principaux-etablissements-enseignement-superieur"
URL_EXPORT = (
    "https://data.enseignementsup-recherche.gouv.fr/api/explore/v2.1/catalog/datasets/"
    f"{JEU_DE_DONNEES}/exports/json"
)
SOURCE = f"data.enseignementsup-recherche.gouv.fr:{JEU_DE_DONNEES}"

CHAMPS: dict[str, tuple[str, ...]] = {
    "nom": ("uo_lib", "uo_lib_officiel", "libelle", "nom", "etablissement"),
    "type": ("type_d_etablissement", "type_etablissement", "type"),
    "secteur": ("secteur_d_etablissement", "secteur_etablissement", "secteur"),
    "url": ("url", "site_web", "site_internet"),
    "departement": ("dep_id", "code_departement", "departement_code", "dep_code"),
}


def _cle(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sans_accents.lower()).strip("_")


def champ(enregistrement: Mapping[str, Any], nom: str) -> str:
    """Valeur du premier champ présent parmi les noms possibles, ou chaîne vide."""
    cles = {_cle(cle): valeur for cle, valeur in enregistrement.items()}
    for candidat in CHAMPS[nom]:
        valeur = cles.get(candidat)
        if isinstance(valeur, list):  # champs multivalués de la plateforme
            valeur = valeur[0] if valeur else None
        if valeur not in (None, ""):
            return str(valeur).strip()
    return ""


def code_departement(valeur: str) -> str | None:
    """« D075 » ou « 075 » → « 75 » ; « D02A » → « 2A » ; « 971 » reste « 971 »."""
    code = valeur.strip().upper().removeprefix("D")
    if not code:
        return None
    if len(code) == 3 and code.startswith("0"):
        code = code[1:]
    return code


def site_web(url: str) -> str | None:
    url = url.strip()
    if not url:
        return None
    return url if re.match(r"^https?://", url, re.I) else f"https://{url}"


def est_universite_publique(enregistrement: Mapping[str, Any]) -> bool:
    type_etablissement = _cle(champ(enregistrement, "type"))
    secteur = _cle(champ(enregistrement, "secteur"))
    return type_etablissement.startswith("universite") and "public" in secteur


def construire_universites(enregistrements: Iterable[Mapping[str, Any]]) -> list[Organisation]:
    """Une organisation par université publique (doublons de slug écartés)."""
    organisations: dict[str, Organisation] = {}
    for enregistrement in enregistrements:
        nom = champ(enregistrement, "nom")
        if not nom or not est_universite_publique(enregistrement):
            continue
        slug = slugifier(nom)
        if not slug.startswith("universite"):
            slug = f"universite-{slug}"
        organisations.setdefault(
            slug,
            Organisation(
                slug=slug,
                nom=nom,
                type="universite",
                departement=code_departement(champ(enregistrement, "departement")),
                site_web=site_web(champ(enregistrement, "url")),
                source=SOURCE,
            ),
        )
    return sorted(organisations.values(), key=lambda o: o.slug)


async def telecharger_universites(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    reponse = await client.get(URL_EXPORT)
    reponse.raise_for_status()
    donnees = reponse.json()
    if not isinstance(donnees, list):
        raise httpx.DecodingError("export inattendu : une liste d'établissements était attendue")
    return donnees
