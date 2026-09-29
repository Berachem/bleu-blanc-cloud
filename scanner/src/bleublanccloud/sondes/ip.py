"""Sonde IP : adresse IP → plage publiée d'un grand cloud, ASN et opérateur.

Ordre de recherche :
1. plages IP publiées par les grands clouds (téléchargées par `bbcloud referentiels maj`) ;
2. base locale `.mmdb` (IPinfo Lite ou GeoLite2 ASN) ;
3. repli sur l'API publique RIPEstat (avec cache mémoire).
"""

from __future__ import annotations

import ipaddress
import json
import logging
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

journal = logging.getLogger(__name__)

URL_RIPESTAT = "https://stat.ripe.net/data"
FICHIER_PLAGES = "plages_cloud.json"
SERVICES_GENERIQUES = frozenset({None, "AMAZON", "AzureCloud", "Google", "Google Cloud"})

type ReseauIp = ipaddress.IPv4Network | ipaddress.IPv6Network


class LecteurMmdb(Protocol):
    """Interface minimale d'un lecteur de base MaxMind DB."""

    def get(self, ip: str) -> Any: ...

    def close(self) -> None: ...


class InfoIp(BaseModel):
    """Informations sur une adresse IP."""

    ip: str
    asn: int | None = None
    nom_as: str | None = None
    pays: str | None = None
    prefixe: str | None = None
    plage_cloud: str | None = None
    service_cloud: str | None = None
    source: str | None = None


class PlageCloud(BaseModel):
    prefixe: str
    fournisseur_id: str
    service: str | None = None


class PlagesCloud:
    """Index des plages IP publiées, recherché par longueur de préfixe (O(33) par IP)."""

    def __init__(self, plages: list[PlageCloud]) -> None:
        self._index: dict[int, dict[int, dict[ReseauIp, PlageCloud]]] = {4: {}, 6: {}}
        for plage in plages:
            try:
                reseau = ipaddress.ip_network(plage.prefixe, strict=False)
            except ValueError:
                continue
            par_longueur = self._index[reseau.version].setdefault(reseau.prefixlen, {})
            existante = par_longueur.get(reseau)
            # À préfixe identique, on garde le service le plus précis (AWS publie « AMAZON »
            # pour toutes ses plages, et « CLOUDFRONT », « EC2 »… en plus).
            if existante is None or existante.service in SERVICES_GENERIQUES:
                par_longueur[reseau] = plage
        self._longueurs = {
            version: sorted(index.keys(), reverse=True) for version, index in self._index.items()
        }

    def __len__(self) -> int:
        return sum(len(v) for index in self._index.values() for v in index.values())

    def chercher(self, ip: str) -> PlageCloud | None:
        """Retourne la plage la plus spécifique qui contient l'adresse."""
        try:
            adresse = ipaddress.ip_address(ip)
        except ValueError:
            return None
        index = self._index[adresse.version]
        for longueur in self._longueurs[adresse.version]:
            reseau = ipaddress.ip_network(f"{adresse}/{longueur}", strict=False)
            plage = index[longueur].get(reseau)
            if plage is not None:
                return plage
        return None

    @classmethod
    def depuis_fichier(cls, chemin: Path) -> PlagesCloud:
        if not chemin.exists():
            journal.warning(
                "Plages IP des clouds absentes (%s) : lancez « bbcloud referentiels maj ».", chemin
            )
            return cls([])
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        return cls([PlageCloud.model_validate(p) for p in donnees.get("plages", [])])


def _lire_mmdb(enregistrement: dict[str, Any]) -> tuple[int | None, str | None, str | None]:
    """Lit un enregistrement IPinfo Lite ou GeoLite2 ASN."""
    asn: int | None = None
    brut = enregistrement.get("asn", enregistrement.get("autonomous_system_number"))
    if isinstance(brut, int):
        asn = brut
    elif isinstance(brut, str) and brut.upper().removeprefix("AS").isdigit():
        asn = int(brut.upper().removeprefix("AS"))
    nom = enregistrement.get("as_name") or enregistrement.get("autonomous_system_organization")
    pays = enregistrement.get("country_code")
    return asn, nom, pays


class ResolveurAsn:
    """Détermine l'ASN et l'opérateur d'une adresse IP."""

    def __init__(
        self,
        plages: PlagesCloud,
        chemin_mmdb: Path | None = None,
        client_http: httpx.AsyncClient | None = None,
        utiliser_ripestat: bool = True,
        lecteur_mmdb: LecteurMmdb | None = None,
    ) -> None:
        self.plages = plages
        self._client = client_http
        self._utiliser_ripestat = utiliser_ripestat
        self._cache: dict[str, InfoIp] = {}
        self._cache_noms_as: dict[int, str | None] = {}
        self._lecteur: LecteurMmdb | None = lecteur_mmdb
        if self._lecteur is not None:
            pass
        elif chemin_mmdb is not None and chemin_mmdb.exists():
            import maxminddb

            self._lecteur = maxminddb.open_database(str(chemin_mmdb))
        elif chemin_mmdb is not None:
            journal.info("Base ASN locale absente (%s) : repli sur RIPEstat.", chemin_mmdb)

    async def informer(self, ip: str) -> InfoIp:
        if ip in self._cache:
            return self._cache[ip]
        info = InfoIp(ip=ip)
        plage = self.plages.chercher(ip)
        if plage is not None:
            info.plage_cloud = plage.fournisseur_id
            info.service_cloud = plage.service
            info.prefixe = plage.prefixe
            info.source = "plages_publiees"
        if self._lecteur is not None:
            enregistrement = self._lecteur.get(ip)
            if isinstance(enregistrement, dict):
                info.asn, info.nom_as, info.pays = _lire_mmdb(enregistrement)
                info.source = info.source or "base_locale"
        if info.asn is None and self._utiliser_ripestat and self._client is not None:
            await self._completer_ripestat(info)
        self._cache[ip] = info
        return info

    async def _completer_ripestat(self, info: InfoIp) -> None:
        assert self._client is not None
        try:
            reponse = await self._client.get(
                f"{URL_RIPESTAT}/network-info/data.json",
                params={"resource": info.ip, "sourceapp": "bleublanccloud"},
            )
            reponse.raise_for_status()
            donnees = reponse.json().get("data", {})
            asns = donnees.get("asns") or []
            if not asns:
                return
            info.asn = int(asns[0])
            info.prefixe = info.prefixe or donnees.get("prefix")
            info.source = info.source or "ripestat"
            info.nom_as, info.pays = await self._nom_as_ripestat(info.asn)
        except (httpx.HTTPError, ValueError) as erreur:
            journal.warning("RIPEstat indisponible pour %s : %s", info.ip, erreur)

    async def _nom_as_ripestat(self, asn: int) -> tuple[str | None, str | None]:
        assert self._client is not None
        if asn not in self._cache_noms_as:
            reponse = await self._client.get(
                f"{URL_RIPESTAT}/as-overview/data.json",
                params={"resource": f"AS{asn}", "sourceapp": "bleublanccloud"},
            )
            reponse.raise_for_status()
            self._cache_noms_as[asn] = reponse.json().get("data", {}).get("holder")
        nom = self._cache_noms_as[asn]
        # RIPEstat renvoie « OVH, FR » : le code pays suit la dernière virgule
        pays = None
        if nom and "," in nom:
            suffixe = nom.rsplit(",", 1)[1].strip()
            if len(suffixe) == 2 and suffixe.isalpha():
                pays = suffixe.upper()
        return nom, pays

    def fermer(self) -> None:
        if self._lecteur is not None:
            self._lecteur.close()
