"""Orchestration d'un scan : sondes passives → attribution → détection → constats."""

from __future__ import annotations

import asyncio
import ipaddress
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx

from bleublanccloud.analyse.attribution import (
    Attributeur,
    constat_hebergement,
    constats_dns_informatifs,
    constats_serveurs,
)
from bleublanccloud.analyse.detection import Detecteur, ElementsObserves
from bleublanccloud.configuration import DOSSIER_TELECHARGEMENTS, Parametres
from bleublanccloud.modeles import Constat, InformationsComplementaires, ResultatScan
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.sondes.dns import (
    ChaineResolution,
    DonneesDns,
    ErreurDns,
    ResolveurDns,
    ResolveurDnsPython,
    sonder_dns,
)
from bleublanccloud.sondes.http import ClientWebPoli, DonneesHttp, UrlExclue, sonder_http
from bleublanccloud.sondes.ip import FICHIER_PLAGES, InfoIp, PlagesCloud, ResolveurAsn
from bleublanccloud.sondes.rdap import DonneesRdap, charger_amorcage, sonder_rdap
from bleublanccloud.sondes.tls import DonneesTls, sonder_tls

MOTIF_NOM_HOTE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


StatutResolution = Literal["ip_litterale", "echec_dns", "sans_adresse", "asn_introuvable"]


class CibleInvalide(ValueError):
    """Entrée qui n'est ni un nom de domaine ni une URL valide."""


@dataclass(frozen=True)
class Cible:
    domaine: str
    url_site: str


def normaliser_cible(entree: str) -> Cible:
    """Accepte « ville.fr », « www.ville.fr » ou « https://www.ville.fr/accueil »."""
    texte = entree.strip()
    if not texte:
        raise CibleInvalide("entrée vide")
    url = texte if "://" in texte else f"https://{texte}"
    morceaux = urlsplit(url)
    if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
        raise CibleInvalide(f"URL invalide : {entree}")
    try:
        hote = morceaux.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as erreur:
        raise CibleInvalide(f"nom de domaine invalide : {entree}") from erreur
    if not MOTIF_NOM_HOTE.match(hote):
        raise CibleInvalide(f"nom de domaine invalide : {entree}")
    domaine = hote.removeprefix("www.")
    chemin = morceaux.path or "/"
    return Cible(domaine=domaine, url_site=f"{morceaux.scheme}://{hote}{chemin}")


FonctionTls = Callable[[str], Awaitable[DonneesTls]]


@dataclass
class ContexteScan:
    """Dépendances d'un scan (injectées pour pouvoir tester sans réseau)."""

    parametres: Parametres
    referentiels: Referentiels
    resolveur_dns: ResolveurDns
    resolveur_asn: ResolveurAsn
    attributeur: Attributeur
    detecteur: Detecteur
    client_web: ClientWebPoli | None = None
    client_rdap: ClientWebPoli | None = None
    serveurs_rdap: dict[str, str] = field(default_factory=dict)
    sonde_tls: FonctionTls | None = None

    @classmethod
    def construire(
        cls,
        parametres: Parametres,
        referentiels: Referentiels,
        resolveur_dns: ResolveurDns,
        resolveur_asn: ResolveurAsn,
        client_web: ClientWebPoli | None = None,
        client_rdap: ClientWebPoli | None = None,
        serveurs_rdap: dict[str, str] | None = None,
        sonde_tls: FonctionTls | None = None,
    ) -> ContexteScan:
        attributeur = Attributeur(referentiels.fournisseurs, referentiels.transitaires.values())
        return cls(
            parametres=parametres,
            referentiels=referentiels,
            resolveur_dns=resolveur_dns,
            resolveur_asn=resolveur_asn,
            attributeur=attributeur,
            detecteur=Detecteur(referentiels.regles, attributeur),
            client_web=client_web,
            client_rdap=client_rdap,
            serveurs_rdap=serveurs_rdap or {},
            sonde_tls=sonde_tls,
        )


async def _info_ip_principale(
    resolution: ChaineResolution | None, contexte: ContexteScan
) -> InfoIp | None:
    if resolution is None or resolution.ip_principale is None:
        return None
    return await contexte.resolveur_asn.informer(resolution.ip_principale)


NOMBRE_MAX_IP_SERVEUR = 4


@dataclass(frozen=True)
class SituationServeur:
    """Résultat de la localisation d'un serveur MX ou NS."""

    info: InfoIp | None
    resolution: StatutResolution | None = None
    diagnostic: str | None = None


def _est_ip(texte: str) -> bool:
    try:
        ipaddress.ip_address(texte)
    except ValueError:
        return False
    return True


async def _premiere_info_utile(ips: list[str], contexte: ContexteScan) -> InfoIp | None:
    """Première IP dont l'ASN (ou la plage cloud) est connu ; à défaut, la première IP."""
    premiere: InfoIp | None = None
    for ip in ips[:NOMBRE_MAX_IP_SERVEUR]:
        info = await contexte.resolveur_asn.informer(ip)
        if info.asn is not None or info.plage_cloud is not None:
            return info
        premiere = premiere or info
    return premiere


async def situer_serveur(hote: str, contexte: ContexteScan) -> SituationServeur:
    """Résout un serveur MX/NS en adresses IP puis en ASN, avec diagnostic en cas d'échec.

    - un enregistrement contenant directement une adresse IP est accepté tel quel ;
    - une requête DNS en échec (délai dépassé) est relancée une fois ;
    - toutes les adresses (IPv4 puis IPv6) sont essayées jusqu'à obtenir un ASN.
    """
    if contexte.referentiels.est_retire(hote):
        return SituationServeur(None)
    if _est_ip(hote):
        info_ip = await contexte.resolveur_asn.informer(hote)
        return SituationServeur(
            info_ip, "ip_litterale", "L'enregistrement désigne une adresse IP et non un nom d'hôte."
        )
    resolution: ChaineResolution | None = None
    derniere_erreur: ErreurDns | None = None
    for _ in range(2):
        try:
            resolution = await contexte.resolveur_dns.resoudre(hote)
            break
        except ErreurDns as erreur:
            derniere_erreur = erreur
    if resolution is None:
        return SituationServeur(
            None, "echec_dns", f"Échec de la résolution DNS : {derniere_erreur}"
        )
    ips = resolution.ipv4 + resolution.ipv6
    if not ips:
        return SituationServeur(
            None,
            "sans_adresse",
            "Le nom ne résout vers aucune adresse IPv4 ni IPv6 : serveur injoignable.",
        )
    info = await _premiere_info_utile(ips, contexte)
    if info is not None and info.asn is None and info.plage_cloud is None:
        return SituationServeur(info, "asn_introuvable", "Opérateur de l'adresse IP introuvable.")
    return SituationServeur(info)


async def _situer_serveurs(hotes: list[str], contexte: ContexteScan) -> dict[str, SituationServeur]:
    """Situe les serveurs MX/NS qui ne sont pas attribuables par leur nom."""
    a_resoudre = list(dict.fromkeys(h for h in hotes if contexte.attributeur.par_nom(h) is None))
    situations = await asyncio.gather(*(situer_serveur(h, contexte) for h in a_resoudre))
    return dict(zip(a_resoudre, situations, strict=True))


def constats_mx_injoignables(
    hotes_mx: list[str], situations: dict[str, SituationServeur]
) -> list[Constat]:
    """Constat informatif pour chaque MX qui ne résout vers aucune adresse."""
    return [
        Constat(
            sonde="dns",
            categorie="informatif",
            cle="mx_sans_adresse",
            valeur=f"Le serveur de messagerie {hote} ne résout vers aucune adresse IP",
            preuve={"hote": hote, "resolution": "sans_adresse"},
        )
        for hote in hotes_mx
        if hote in situations and situations[hote].resolution == "sans_adresse"
    ]


def choisir_nom_hote_site(donnees: DonneesDns, url_site: str) -> str:
    """Nom d'hôte du site : celui de l'URL de départ s'il résout, sinon le domaine, sinon www."""
    hote_url = (urlsplit(url_site).hostname or donnees.domaine).lower()
    for candidat in (hote_url, donnees.domaine, f"www.{donnees.domaine}"):
        if candidat in donnees.resolutions and donnees.resolutions[candidat].ip_principale:
            return candidat
    return hote_url


def fournisseurs_secnumcloud(constats: list[Constat], referentiels: Referentiels) -> list[str]:
    ids = {c.fournisseur_id for c in constats if c.fournisseur_id}
    return sorted(
        referentiels.fournisseurs[i].nom
        for i in ids
        if i in referentiels.fournisseurs and referentiels.fournisseurs[i].propose_offre_secnumcloud
    )


async def _sonder_rdap(domaine: str, contexte: ContexteScan) -> DonneesRdap | None:
    client = contexte.client_rdap
    if client is None:
        return None

    async def obtenir(url: str) -> httpx.Response:
        try:
            reponse, _ = await client.obtenir(url)
        except UrlExclue as erreur:
            raise httpx.RequestError(str(erreur)) from erreur
        return reponse

    return await sonder_rdap(domaine, obtenir, contexte.serveurs_rdap)


async def _sonder_http(cible: Cible, contexte: ContexteScan) -> DonneesHttp | None:
    if contexte.client_web is None:
        return None
    return await sonder_http(cible.url_site, cible.domaine, contexte.client_web)


async def scanner_domaine(entree: str, contexte: ContexteScan) -> ResultatScan:
    """Scan passif complet d'un domaine."""
    debut = datetime.now(UTC)
    cible = normaliser_cible(entree)

    # La liste de retraits est vérifiée AVANT toute requête réseau.
    if contexte.referentiels.est_retire(cible.domaine):
        return ResultatScan(
            domaine=cible.domaine,
            debut=debut,
            fin=datetime.now(UTC),
            statut="exclu",
            erreurs=["Domaine exclu à la demande de l'organisation (retraits.yaml)."],
        )

    donnees_dns = await sonder_dns(cible.domaine, contexte.resolveur_dns)
    erreurs = list(donnees_dns.erreurs)
    constats: list[Constat] = []
    informations = InformationsComplementaires()

    donnees_http, donnees_rdap = await asyncio.gather(
        _sonder_http(cible, contexte),
        _sonder_rdap(donnees_dns.zone or cible.domaine, contexte),
    )
    if donnees_http is not None:
        erreurs += [f"HTTP : {e}" for e in donnees_http.erreurs]
        if donnees_http.certificat_invalide:
            erreurs.append("HTTP : certificat TLS non valide")
    if donnees_rdap is not None:
        informations.bureau_enregistrement = donnees_rdap.bureau_enregistrement

    # Hébergement du site : hôte final après redirections, sinon meilleur candidat DNS
    if donnees_http is not None and donnees_http.hote_final:
        nom_hote_site = donnees_http.hote_final.lower()
    else:
        nom_hote_site = choisir_nom_hote_site(donnees_dns, cible.url_site)
    resolution_site = donnees_dns.resolutions.get(nom_hote_site)
    if resolution_site is None and not contexte.referentiels.est_retire(nom_hote_site):
        try:
            resolution_site = await contexte.resolveur_dns.resoudre(nom_hote_site)
        except ErreurDns as erreur:
            erreurs.append(str(erreur))
    info_site = await _info_ip_principale(resolution_site, contexte)
    en_tetes = donnees_http.en_tetes if donnees_http else {}
    constat_site = None
    if resolution_site is not None:
        constat_site = constat_hebergement(
            resolution_site, info_site, en_tetes, contexte.attributeur
        )
        if constat_site is not None:
            constats.append(constat_site)

    # Messagerie (MX) et DNS (NS)
    hotes_mx = [mx.hote for mx in donnees_dns.mx]
    situations = await _situer_serveurs(hotes_mx + donnees_dns.ns, contexte)
    infos_serveurs = {hote: s.info for hote, s in situations.items()}
    diagnostics = {
        hote: {"resolution": s.resolution, "diagnostic": s.diagnostic}
        for hote, s in situations.items()
        if s.resolution is not None and s.diagnostic is not None
    }
    constats += constats_serveurs(
        "mx",
        [(mx.hote, mx.priorite) for mx in donnees_dns.mx],
        infos_serveurs,
        contexte.attributeur,
        diagnostics,
    )
    constats += constats_serveurs(
        "ns",
        [(ns, None) for ns in donnees_dns.ns],
        infos_serveurs,
        contexte.attributeur,
        diagnostics,
    )
    constats += constats_mx_injoignables(hotes_mx, situations)
    constats += constats_dns_informatifs(donnees_dns)

    # Services tiers, suites SaaS, mesure d'audience
    elements = ElementsObserves.depuis_sondes(donnees_dns, donnees_http)
    detection = contexte.detecteur.detecter(elements)
    constats += detection.constats
    exclus = (
        {constat_site.fournisseur_id} if constat_site and constat_site.fournisseur_id else set()
    )
    generiques, inconnus = contexte.detecteur.ressources_non_couvertes(
        elements, detection.elements_expliques, exclus
    )
    constats += generiques
    informations.domaines_tiers_inconnus = inconnus

    # Autorité de certification (informatif)
    if (
        contexte.sonde_tls is not None
        and donnees_http is not None
        and donnees_http.url_finale
        and donnees_http.url_finale.startswith("https://")
        and not contexte.referentiels.est_retire(nom_hote_site)
    ):
        donnees_tls = await contexte.sonde_tls(nom_hote_site)
        informations.autorite_certification = donnees_tls.autorite
        if donnees_tls.erreur:
            erreurs.append(f"TLS : {donnees_tls.erreur}")

    informations.fournisseurs_secnumcloud = fournisseurs_secnumcloud(
        constats, contexte.referentiels
    )
    aucune_donnee = not donnees_dns.resolutions and not donnees_dns.ns and not donnees_dns.mx
    statut = "erreur" if aucune_donnee else ("partiel" if erreurs else "termine")
    sondes_reussies: list[Literal["dns", "http"]] = [] if aucune_donnee else ["dns"]
    if donnees_http is not None and donnees_http.html_pages:
        sondes_reussies.append("http")
    return ResultatScan(
        domaine=cible.domaine,
        debut=debut,
        fin=datetime.now(UTC),
        statut=statut,
        sondes_reussies=sondes_reussies,
        constats=constats,
        informations=informations,
        erreurs=erreurs,
    )


@asynccontextmanager
async def contexte_reseau(
    parametres: Parametres, referentiels: Referentiels, avec_http: bool = True
) -> AsyncIterator[ContexteScan]:
    """Construit un contexte de scan réel (DNS, base ASN, HTTP poli, RDAP, TLS)."""
    client_api = httpx.AsyncClient(
        headers={"User-Agent": parametres.user_agent},
        timeout=parametres.delai_expiration_s,
        follow_redirects=True,
    )
    plages = PlagesCloud.depuis_fichier(DOSSIER_TELECHARGEMENTS / FICHIER_PLAGES)
    resolveur_asn = ResolveurAsn(plages, parametres.base_asn, client_http=client_api)
    client_web = ClientWebPoli(parametres, referentiels) if avec_http else None
    client_rdap = ClientWebPoli(parametres, referentiels) if avec_http else None

    async def sonde_tls(hote: str) -> DonneesTls:
        return await sonder_tls(hote, delai_s=parametres.delai_expiration_s)

    try:
        yield ContexteScan.construire(
            parametres,
            referentiels,
            ResolveurDnsPython(delai_s=parametres.delai_expiration_s),
            resolveur_asn,
            client_web=client_web,
            client_rdap=client_rdap,
            serveurs_rdap=charger_amorcage(DOSSIER_TELECHARGEMENTS / "rdap_dns.json"),
            sonde_tls=sonde_tls if avec_http else None,
        )
    finally:
        resolveur_asn.fermer()
        await client_api.aclose()
        for client in (client_web, client_rdap):
            if client is not None:
                await client.fermer()
