"""Sonde DNS : A, AAAA, CNAME (chaîne complète), NS, MX, TXT, CAA, DMARC.

La sonde ne fait que collecter. L'attribution des enregistrements à des fournisseurs est
réalisée dans `analyse/attribution.py` et la détection des services dans `analyse/detection.py`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Protocol

import dns.asyncresolver
import dns.exception
import dns.name
import dns.rdatatype
import dns.resolver
from pydantic import BaseModel, Field

journal = logging.getLogger(__name__)


class ErreurDns(Exception):
    """Échec d'une requête DNS (délai dépassé, serveurs injoignables…)."""


class ChaineResolution(BaseModel):
    """Résolution d'un nom : chaîne CNAME puis adresses IP finales."""

    nom: str
    cnames: list[str] = Field(default_factory=list)
    ipv4: list[str] = Field(default_factory=list)
    ipv6: list[str] = Field(default_factory=list)

    @property
    def ip_principale(self) -> str | None:
        """Première adresse IPv4, à défaut première IPv6."""
        if self.ipv4:
            return self.ipv4[0]
        if self.ipv6:
            return self.ipv6[0]
        return None


class EnregistrementMx(BaseModel):
    priorite: int
    hote: str


class DonneesDns(BaseModel):
    """Données brutes collectées par la sonde DNS."""

    domaine: str
    zone: str | None = None
    resolutions: dict[str, ChaineResolution] = Field(default_factory=dict)
    ns: list[str] = Field(default_factory=list)
    mx: list[EnregistrementMx] = Field(default_factory=list)
    mx_nul: bool = False
    txt: list[str] = Field(default_factory=list)
    caa: list[str] = Field(default_factory=list)
    dmarc: str | None = None
    erreurs: list[str] = Field(default_factory=list)

    @property
    def spf(self) -> str | None:
        """Enregistrement SPF du domaine (premier TXT commençant par v=spf1)."""
        for valeur in self.txt:
            if valeur.lower().startswith("v=spf1"):
                return valeur
        return None


def normaliser_nom(nom: str) -> str:
    """Minuscules, sans point final."""
    return nom.strip().lower().rstrip(".")


class ResolveurDns(Protocol):
    """Interface d'un résolveur DNS (réel ou factice pour les tests)."""

    async def interroger(self, nom: str, type_enregistrement: str) -> list[str]:
        """Retourne les valeurs normalisées d'un type d'enregistrement ([] si absent)."""
        ...

    async def resoudre(self, nom: str) -> ChaineResolution:
        """Résout un nom en suivant la chaîne CNAME jusqu'aux adresses IP."""
        ...

    async def zone_de(self, nom: str) -> str | None:
        """Retourne la zone DNS (domaine enregistrable ou délégué) qui contient le nom."""
        ...


class ResolveurDnsPython:
    """Résolveur asynchrone reposant sur dnspython."""

    def __init__(self, delai_s: float = 10.0, serveurs: list[str] | None = None) -> None:
        self._resolveur = dns.asyncresolver.Resolver()
        self._resolveur.lifetime = delai_s
        self._resolveur.timeout = min(delai_s, 4.0)
        if serveurs:
            self._resolveur.nameservers = serveurs

    async def _resolve(self, nom: str, type_enregistrement: str) -> dns.resolver.Answer | None:
        try:
            return await self._resolveur.resolve(nom, type_enregistrement, raise_on_no_answer=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return None
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as erreur:
            raise ErreurDns(f"{type_enregistrement} {nom} : {erreur}") from erreur

    async def interroger(self, nom: str, type_enregistrement: str) -> list[str]:
        reponse = await self._resolve(nom, type_enregistrement)
        if reponse is None or reponse.rrset is None:
            return []
        valeurs: list[str] = []
        for donnee in reponse.rrset:
            if donnee.rdtype == dns.rdatatype.TXT:
                valeurs.append(b"".join(donnee.strings).decode("utf-8", errors="replace"))
            elif donnee.rdtype == dns.rdatatype.MX:
                valeurs.append(f"{donnee.preference} {normaliser_nom(donnee.exchange.to_text())}")
            elif donnee.rdtype in (dns.rdatatype.NS, dns.rdatatype.CNAME):
                valeurs.append(normaliser_nom(donnee.target.to_text()))
            else:
                valeurs.append(donnee.to_text())
        return valeurs

    async def resoudre(self, nom: str) -> ChaineResolution:
        """A puis AAAA : l'échec d'un seul des deux types n'empêche pas d'utiliser l'autre."""
        chaine = ChaineResolution(nom=normaliser_nom(nom))
        echecs: list[ErreurDns] = []
        for type_enregistrement, cible in (("A", chaine.ipv4), ("AAAA", chaine.ipv6)):
            try:
                reponse = await self._resolve(nom, type_enregistrement)
            except ErreurDns as erreur:
                echecs.append(erreur)
                continue
            if reponse is None:
                continue
            if not chaine.cnames:
                for rrset in reponse.chaining_result.cnames:
                    chaine.cnames.extend(normaliser_nom(r.target.to_text()) for r in rrset)
            if reponse.rrset is not None:
                cible.extend(donnee.to_text() for donnee in reponse.rrset)
        if len(echecs) == 2:
            raise echecs[0]
        return chaine

    async def zone_de(self, nom: str) -> str | None:
        try:
            zone = await dns.asyncresolver.zone_for_name(nom, resolver=self._resolveur)
        except (dns.exception.DNSException, dns.resolver.NoRootSOA):
            return None
        return normaliser_nom(zone.to_text())


def _analyser_mx(valeurs: list[str]) -> tuple[list[EnregistrementMx], bool]:
    enregistrements: list[EnregistrementMx] = []
    mx_nul = False
    for valeur in valeurs:
        priorite, _, hote = valeur.partition(" ")
        hote = normaliser_nom(hote)
        if hote in ("", "."):
            # MX nul (RFC 7505) : le domaine déclare ne recevoir aucun courriel
            mx_nul = True
            continue
        enregistrements.append(EnregistrementMx(priorite=int(priorite or 0), hote=hote))
    enregistrements.sort(key=lambda mx: (mx.priorite, mx.hote))
    return enregistrements, mx_nul


async def _securiser[T](erreurs: list[str], attente: Awaitable[T], defaut: T) -> T:
    """Attend une requête DNS ; en cas d'échec, consigne l'erreur et retourne le défaut."""
    try:
        return await attente
    except ErreurDns as erreur:
        erreurs.append(str(erreur))
        return defaut


async def sonder_dns(domaine: str, resolveur: ResolveurDns) -> DonneesDns:
    """Collecte les enregistrements DNS d'un domaine (et de son sous-domaine www)."""
    domaine = normaliser_nom(domaine)
    donnees = DonneesDns(domaine=domaine)

    zone = await _securiser(donnees.erreurs, resolveur.zone_de(domaine), None)
    donnees.zone = zone
    zone_ns = zone or domaine

    resolution_domaine, resolution_www = await asyncio.gather(
        _securiser(donnees.erreurs, resolveur.resoudre(domaine), None),
        _securiser(donnees.erreurs, resolveur.resoudre(f"www.{domaine}"), None),
    )
    ns, mx, txt, caa, dmarc = await asyncio.gather(
        *(
            _securiser(donnees.erreurs, resolveur.interroger(nom, type_enregistrement), [])
            for nom, type_enregistrement in (
                (zone_ns, "NS"),
                (domaine, "MX"),
                (domaine, "TXT"),
                (domaine, "CAA"),
                (f"_dmarc.{domaine}", "TXT"),
            )
        )
    )

    for resolution in (resolution_domaine, resolution_www):
        if resolution is not None and (resolution.ipv4 or resolution.ipv6 or resolution.cnames):
            donnees.resolutions[resolution.nom] = resolution

    donnees.ns = sorted({normaliser_nom(n) for n in ns})
    donnees.mx, donnees.mx_nul = _analyser_mx(mx)
    donnees.txt = txt
    donnees.caa = caa
    donnees.dmarc = next((v for v in dmarc if v.lower().startswith("v=dmarc1")), None)
    return donnees
