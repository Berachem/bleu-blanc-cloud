"""Mise à jour des référentiels téléchargés (commande `bbcloud referentiels maj`).

- plages IP publiées par les grands clouds → `telechargements/plages_cloud.json` ;
- base IP → ASN (IPinfo Lite, jeton gratuit) → `telechargements/asn.mmdb` ;
- amorçage RDAP de l'IANA → `telechargements/rdap_dns.json` ;
- liste ANSSI des offres qualifiées SecNumCloud → comparaison avec fournisseurs.yaml
  (rapport uniquement : le référentiel n'est jamais modifié automatiquement).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from bleublanccloud.modeles import Fournisseur
from bleublanccloud.sondes.ip import FICHIER_PLAGES, PlageCloud

journal = logging.getLogger(__name__)

URL_AWS = "https://ip-ranges.amazonaws.com/ip-ranges.json"
URL_GOOGLE_CLOUD = "https://www.gstatic.com/ipranges/cloud.json"
URL_GOOGLE = "https://www.gstatic.com/ipranges/goog.json"
URL_CLOUDFLARE_V4 = "https://www.cloudflare.com/ips-v4"
URL_CLOUDFLARE_V6 = "https://www.cloudflare.com/ips-v6"
URL_ORACLE = "https://docs.oracle.com/en-us/iaas/tools/public_ip_ranges.json"
URL_AZURE_PAGE = "https://www.microsoft.com/en-us/download/details.aspx?id=56519"
URL_FASTLY = "https://api.fastly.com/public-ip-list"
URL_GITHUB = "https://api.github.com/meta"
URL_IPINFO_LITE = "https://ipinfo.io/data/ipinfo_lite.mmdb"
URL_BOOTSTRAP_RDAP = "https://data.iana.org/rdap/dns.json"
# Page de l'ANSSI listant les offres qualifiées SecNumCloud (URL à vérifier si elle change).
URL_SECNUMCLOUD = "https://cyber.gouv.fr/offres-de-cloud-qualifiees"

MOTIF_AZURE = re.compile(
    r"https://download\.microsoft\.com/download/[^\"']+/ServiceTags_Public_\d+\.json"
)


# --------------------------------------------------------------------------- #
# Analyse des formats publiés par chaque fournisseur (fonctions pures, testées)
# --------------------------------------------------------------------------- #


def analyser_aws(donnees: dict[str, Any]) -> list[PlageCloud]:
    plages = [
        PlageCloud(prefixe=p["ip_prefix"], fournisseur_id="aws", service=p.get("service"))
        for p in donnees.get("prefixes", [])
    ]
    plages += [
        PlageCloud(prefixe=p["ipv6_prefix"], fournisseur_id="aws", service=p.get("service"))
        for p in donnees.get("ipv6_prefixes", [])
    ]
    return plages


def analyser_google(donnees: dict[str, Any], service: str) -> list[PlageCloud]:
    plages: list[PlageCloud] = []
    for p in donnees.get("prefixes", []):
        prefixe = p.get("ipv4Prefix") or p.get("ipv6Prefix")
        if prefixe:
            plages.append(PlageCloud(prefixe=prefixe, fournisseur_id="google", service=service))
    return plages


def analyser_liste_texte(texte: str, fournisseur_id: str) -> list[PlageCloud]:
    return [
        PlageCloud(prefixe=ligne.strip(), fournisseur_id=fournisseur_id)
        for ligne in texte.splitlines()
        if ligne.strip() and not ligne.startswith("#")
    ]


def analyser_oracle(donnees: dict[str, Any]) -> list[PlageCloud]:
    return [
        PlageCloud(prefixe=c["cidr"], fournisseur_id="oracle", service=region.get("region"))
        for region in donnees.get("regions", [])
        for c in region.get("cidrs", [])
    ]


def analyser_azure(donnees: dict[str, Any]) -> list[PlageCloud]:
    """« AzureCloud » regroupe toutes les plages publiques ; on garde aussi les étiquettes
    Front Door (CDN) pour distinguer ce rôle."""
    plages: list[PlageCloud] = []
    for valeur in donnees.get("values", []):
        nom = valeur.get("name", "")
        if nom != "AzureCloud" and not nom.startswith("AzureFrontDoor"):
            continue
        for prefixe in valeur.get("properties", {}).get("addressPrefixes", []):
            plages.append(PlageCloud(prefixe=prefixe, fournisseur_id="microsoft", service=nom))
    return plages


def analyser_fastly(donnees: dict[str, Any]) -> list[PlageCloud]:
    return [
        PlageCloud(prefixe=p, fournisseur_id="fastly")
        for p in donnees.get("addresses", []) + donnees.get("ipv6_addresses", [])
    ]


def analyser_github(donnees: dict[str, Any]) -> list[PlageCloud]:
    return [
        PlageCloud(prefixe=p, fournisseur_id="github", service="pages")
        for p in donnees.get("pages", [])
    ]


def extraire_url_azure(page_html: str) -> str | None:
    correspondance = MOTIF_AZURE.search(page_html)
    return correspondance.group(0) if correspondance else None


# --------------------------------------------------------------------------- #
# Téléchargements
# --------------------------------------------------------------------------- #


@dataclass
class RapportMiseAJour:
    plages_par_source: dict[str, int] = field(default_factory=dict)
    erreurs: list[str] = field(default_factory=list)
    base_asn: str | None = None
    bootstrap_rdap: bool = False
    secnumcloud: list[str] = field(default_factory=list)


async def _json(client: httpx.AsyncClient, url: str) -> Any:
    reponse = await client.get(url)
    reponse.raise_for_status()
    return reponse.json()


async def _texte(client: httpx.AsyncClient, url: str) -> str:
    reponse = await client.get(url)
    reponse.raise_for_status()
    return reponse.text


async def telecharger_plages_cloud(
    client: httpx.AsyncClient, dossier: Path, rapport: RapportMiseAJour
) -> Path:
    """Télécharge toutes les plages publiées et les enregistre dans un fichier normalisé."""
    plages: list[PlageCloud] = []

    async def azure() -> list[PlageCloud]:
        url = extraire_url_azure(await _texte(client, URL_AZURE_PAGE))
        if url is None:
            raise ValueError("lien ServiceTags_Public introuvable sur la page Microsoft")
        return analyser_azure(await _json(client, url))

    async def aws() -> list[PlageCloud]:
        return analyser_aws(await _json(client, URL_AWS))

    async def google_cloud() -> list[PlageCloud]:
        return analyser_google(await _json(client, URL_GOOGLE_CLOUD), "Google Cloud")

    async def google() -> list[PlageCloud]:
        return analyser_google(await _json(client, URL_GOOGLE), "Google")

    async def cloudflare() -> list[PlageCloud]:
        return analyser_liste_texte(
            await _texte(client, URL_CLOUDFLARE_V4), "cloudflare"
        ) + analyser_liste_texte(await _texte(client, URL_CLOUDFLARE_V6), "cloudflare")

    async def oracle() -> list[PlageCloud]:
        return analyser_oracle(await _json(client, URL_ORACLE))

    async def fastly() -> list[PlageCloud]:
        return analyser_fastly(await _json(client, URL_FASTLY))

    async def github() -> list[PlageCloud]:
        return analyser_github(await _json(client, URL_GITHUB))

    sources: dict[str, Callable[[], Any]] = {
        "aws": aws,
        "google_cloud": google_cloud,
        "google": google,
        "cloudflare": cloudflare,
        "oracle": oracle,
        "azure": azure,
        "fastly": fastly,
        "github_pages": github,
    }
    for nom, fonction in sources.items():
        try:
            resultat: list[PlageCloud] = await fonction()
        except (httpx.HTTPError, ValueError, KeyError) as erreur:
            rapport.erreurs.append(f"plages {nom} : {erreur}")
            continue
        rapport.plages_par_source[nom] = len(resultat)
        plages.extend(resultat)

    chemin = dossier / FICHIER_PLAGES
    ancien: dict[str, Any] = {}
    if chemin.exists():
        ancien = json.loads(chemin.read_text(encoding="utf-8"))
    # En cas d'échec partiel, on conserve les plages précédentes des sources en erreur.
    sources_ok = set(rapport.plages_par_source)
    correspondance_sources = {
        "aws": "aws",
        "google_cloud": "google",
        "google": "google",
        "cloudflare": "cloudflare",
        "oracle": "oracle",
        "azure": "microsoft",
        "fastly": "fastly",
        "github_pages": "github",
    }
    fournisseurs_ok = {correspondance_sources[s] for s in sources_ok}
    for plage in ancien.get("plages", []):
        if plage.get("fournisseur_id") not in fournisseurs_ok:
            plages.append(PlageCloud.model_validate(plage))

    dossier.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(
            {
                "genere_le": datetime.now(UTC).isoformat(),
                "sources": sorted(sources_ok),
                "plages": [p.model_dump() for p in plages],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return chemin


async def telecharger_base_asn(
    client: httpx.AsyncClient, jeton: str | None, destination: Path, rapport: RapportMiseAJour
) -> None:
    """Télécharge la base IPinfo Lite (.mmdb). Sans jeton, le scanner utilisera RIPEstat."""
    if not jeton:
        rapport.erreurs.append(
            "IPINFO_TOKEN absent : base ASN locale non téléchargée (repli sur RIPEstat)."
        )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporaire = destination.with_suffix(".tmp")
    try:
        async with client.stream("GET", URL_IPINFO_LITE, params={"token": jeton}) as reponse:
            reponse.raise_for_status()
            with temporaire.open("wb") as fichier:
                async for morceau in reponse.aiter_bytes():
                    fichier.write(morceau)
    except httpx.HTTPError as erreur:
        rapport.erreurs.append(f"base ASN : {erreur}")
        temporaire.unlink(missing_ok=True)
        return
    temporaire.replace(destination)
    rapport.base_asn = str(destination)


async def telecharger_bootstrap_rdap(
    client: httpx.AsyncClient, dossier: Path, rapport: RapportMiseAJour
) -> None:
    try:
        donnees = await _json(client, URL_BOOTSTRAP_RDAP)
    except (httpx.HTTPError, ValueError) as erreur:
        rapport.erreurs.append(f"amorçage RDAP : {erreur}")
        return
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "rdap_dns.json").write_text(json.dumps(donnees), encoding="utf-8")
    rapport.bootstrap_rdap = True


def comparer_secnumcloud(texte_page: str, fournisseurs: list[Fournisseur]) -> list[str]:
    """Compare la page ANSSI avec le champ `propose_offre_secnumcloud` du référentiel.

    Retourne des remarques à vérifier manuellement (aucune modification automatique).
    """
    texte = texte_page.lower()
    remarques: list[str] = []
    for fournisseur in fournisseurs:
        nom_court = fournisseur.nom.split(" (")[0].lower()
        present = nom_court in texte or fournisseur.id.replace("-", " ") in texte
        if present and not fournisseur.propose_offre_secnumcloud:
            remarques.append(
                f"{fournisseur.nom} apparaît sur la page ANSSI mais n'est pas marqué "
                "propose_offre_secnumcloud : à vérifier."
            )
        if fournisseur.propose_offre_secnumcloud and not present:
            remarques.append(
                f"{fournisseur.nom} est marqué propose_offre_secnumcloud mais n'apparaît pas "
                "sur la page ANSSI : à vérifier."
            )
    return remarques


async def verifier_secnumcloud(
    client: httpx.AsyncClient, fournisseurs: list[Fournisseur], rapport: RapportMiseAJour
) -> None:
    try:
        texte = await _texte(client, URL_SECNUMCLOUD)
    except httpx.HTTPError as erreur:
        rapport.erreurs.append(f"liste SecNumCloud : {erreur}")
        return
    rapport.secnumcloud = comparer_secnumcloud(texte, fournisseurs)
