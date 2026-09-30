"""Outils de test partagés : résolveurs factices, fixtures, interdiction du réseau."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

from bleublanccloud.configuration import Parametres
from bleublanccloud.referentiels import Referentiels, referentiels_par_defaut
from bleublanccloud.referentiels.telechargement import analyser_aws, analyser_liste_texte
from bleublanccloud.scan import ContexteScan
from bleublanccloud.sondes.dns import ChaineResolution, ErreurDns
from bleublanccloud.sondes.ip import PlagesCloud, ResolveurAsn

DOSSIER_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isoler_configuration(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Les tests ignorent le fichier .env et les variables d'environnement de la machine.

    Sur le serveur, le .env contient de vraies valeurs (clé Mistral, jeton Codeberg…) : sans
    cette isolation, des tests échouaient là-bas seulement, et la mise à jour automatique
    rejetait alors chaque nouvelle version. Un test peut toujours fixer une variable avec
    monkeypatch.setenv (cette fixture s'exécute avant lui).
    """
    from bleublanccloud import configuration

    monkeypatch.setitem(configuration.Parametres.model_config, "env_file", None)
    champs = set(configuration.Parametres.model_fields)
    for nom in list(os.environ):
        if nom.lower() in champs:
            monkeypatch.delenv(nom)
    configuration.obtenir_parametres.cache_clear()
    yield
    configuration.obtenir_parametres.cache_clear()


@pytest.fixture(autouse=True)
def interdire_reseau(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les tests ne doivent jamais utiliser le réseau (docs/CLAUDE.md, section 2)."""
    connexion_origine = socket.socket.connect

    def connexion_controlee(self: socket.socket, adresse: Any) -> Any:
        hote = adresse[0] if isinstance(adresse, tuple) else adresse
        if hote in ("127.0.0.1", "::1", "localhost") or isinstance(adresse, str):
            return connexion_origine(self, adresse)
        raise RuntimeError(f"Accès réseau interdit pendant les tests : {adresse!r}")

    monkeypatch.setattr(socket.socket, "connect", connexion_controlee)


class ResolveurFactice:
    """Résolveur DNS qui répond à partir d'un scénario JSON enregistré."""

    def __init__(self, scenario: dict[str, Any]) -> None:
        self.zones: dict[str, str] = scenario.get("zones", {})
        self.resolutions: dict[str, dict[str, list[str]]] = scenario.get("resolutions", {})
        self.enregistrements: dict[str, list[str]] = scenario.get("enregistrements", {})
        self.erreurs: set[str] = set(scenario.get("erreurs", []))
        # Erreurs levées une seule fois (délai dépassé passager), puis la requête réussit
        self.erreurs_passageres: set[str] = set(scenario.get("erreurs_passageres", []))
        self.appels: list[str] = []

    @classmethod
    def depuis_fixture(cls, nom: str) -> ResolveurFactice:
        return cls(json.loads((DOSSIER_FIXTURES / "dns" / f"{nom}.json").read_text()))

    def fusionner(self, autre: ResolveurFactice) -> ResolveurFactice:
        self.zones |= autre.zones
        self.resolutions |= autre.resolutions
        self.enregistrements |= autre.enregistrements
        self.erreurs |= autre.erreurs
        return self

    async def interroger(self, nom: str, type_enregistrement: str) -> list[str]:
        cle = f"{nom}|{type_enregistrement}"
        self.appels.append(cle)
        if cle in self.erreurs:
            raise ErreurDns(f"{type_enregistrement} {nom} : délai dépassé")
        return list(self.enregistrements.get(cle, []))

    async def resoudre(self, nom: str) -> ChaineResolution:
        cle = f"{nom}|A"
        self.appels.append(cle)
        if cle in self.erreurs:
            raise ErreurDns(f"A {nom} : délai dépassé")
        if cle in self.erreurs_passageres:
            self.erreurs_passageres.discard(cle)
            raise ErreurDns(f"A {nom} : délai dépassé (passager)")
        donnees = self.resolutions.get(nom, {})
        return ChaineResolution(
            nom=nom,
            cnames=list(donnees.get("cnames", [])),
            ipv4=list(donnees.get("ipv4", [])),
            ipv6=list(donnees.get("ipv6", [])),
        )

    async def zone_de(self, nom: str) -> str | None:
        self.appels.append(f"{nom}|SOA")
        return self.zones.get(nom, ".".join(nom.split(".")[-2:]))


class LecteurMmdbFactice:
    """Base ASN factice au format IPinfo Lite."""

    DONNEES: ClassVar[dict[str, dict[str, str]]] = {
        "51.91.10.20": {"asn": "AS16276", "as_name": "OVH SAS", "country_code": "FR"},
        "51.91.10.53": {"asn": "AS16276", "as_name": "OVH SAS", "country_code": "FR"},
        "104.16.1.1": {"asn": "AS13335", "as_name": "Cloudflare, Inc.", "country_code": "US"},
        "185.10.20.30": {"asn": "AS64500", "as_name": "PETIT HEBERGEUR", "country_code": "FR"},
        "185.10.20.31": {"asn": "AS64500", "as_name": "PETIT HEBERGEUR", "country_code": "FR"},
        # Codeberg Pages (réseau de l'association IN-Berlin)
        "217.197.84.141": {"asn": "AS29670", "as_name": "IN-BERLIN-AS", "country_code": "DE"},
        "2a0a:4580:103f:c0de::2": {
            "asn": "AS29670",
            "as_name": "IN-BERLIN-AS",
            "country_code": "DE",
        },
        "185.20.30.40": {
            "asn": "AS64510",
            "as_name": "COMMUNE DE METROPOLE-EXEMPLE",
            "country_code": "FR",
        },
        "2001:db8::53": {"asn": "AS25091", "as_name": "IP-Max SA", "country_code": "CH"},
    }

    def get(self, ip: str) -> dict[str, str] | None:
        return self.DONNEES.get(ip)

    def close(self) -> None:
        pass


def plages_de_test() -> PlagesCloud:
    dossier = DOSSIER_FIXTURES / "plages"
    plages = analyser_aws(json.loads((dossier / "aws_ip-ranges.json").read_text()))
    plages += analyser_liste_texte((dossier / "cloudflare_ips-v4.txt").read_text(), "cloudflare")
    plages += analyser_liste_texte((dossier / "cloudflare_ips-v6.txt").read_text(), "cloudflare")
    return PlagesCloud(plages)


@pytest.fixture
def referentiels() -> Referentiels:
    return referentiels_par_defaut()


@pytest.fixture
def parametres() -> Parametres:
    return Parametres(_env_file=None)


@pytest.fixture
def resolveur_asn() -> ResolveurAsn:
    return ResolveurAsn(
        plages_de_test(), lecteur_mmdb=LecteurMmdbFactice(), utiliser_ripestat=False
    )


def fabriquer_contexte(
    parametres: Parametres,
    referentiels: Referentiels,
    resolveur: ResolveurFactice,
    resolveur_asn: ResolveurAsn,
) -> ContexteScan:
    return ContexteScan.construire(parametres, referentiels, resolveur, resolveur_asn)
