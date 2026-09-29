"""Tests des sondes TLS et RDAP (informatives)."""

from __future__ import annotations

import json
import socket

import httpx

from bleublanccloud.sondes.rdap import charger_amorcage, extraire_bureau, sonder_rdap
from bleublanccloud.sondes.tls import DonneesTls, lire_emetteur, sonder_tls
from tests.conftest import DOSSIER_FIXTURES

RDAP = DOSSIER_FIXTURES / "rdap"


def test_lire_emetteur() -> None:
    certificat = {
        "issuer": (
            (("countryName", "US"),),
            (("organizationName", "Let's Encrypt"),),
            (("commonName", "R11"),),
        )
    }
    assert lire_emetteur(certificat) == ("Let's Encrypt", "R11")
    assert lire_emetteur({}) == (None, None)


def test_autorite() -> None:
    assert DonneesTls(hote="a", emetteur_organisation="Certigna", emetteur_nom="CA").autorite == (
        "Certigna (CA)"
    )
    assert DonneesTls(hote="a", emetteur_nom="R11").autorite == "R11"
    assert DonneesTls(hote="a").autorite is None


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_tls_connexion_refusee() -> None:
    donnees = await sonder_tls("127.0.0.1", port=port_libre(), delai_s=2)
    assert donnees.erreur is not None and "impossible" in donnees.erreur


async def test_tls_delai_depasse() -> None:
    # Socket en écoute qui n'accepte jamais la négociation TLS : le délai doit s'appliquer.
    with socket.socket() as ecoute:
        ecoute.bind(("127.0.0.1", 0))
        ecoute.listen(1)
        port = ecoute.getsockname()[1]
        donnees = await sonder_tls("127.0.0.1", port=port, delai_s=0.2)
    assert donnees.erreur is not None and "TimeoutError" in donnees.erreur


def test_charger_amorcage(tmp_path) -> None:
    serveurs = charger_amorcage(RDAP / "iana_dns.json")
    assert serveurs["dev"] == "https://pubapi.registry.google/rdap/"
    assert serveurs["re"] == "https://rdap.nic.fr/"
    assert charger_amorcage(tmp_path / "absent.json")["fr"] == "https://rdap.nic.fr/"


def test_extraire_bureau() -> None:
    reponse = json.loads((RDAP / "afnic_exempleville.json").read_text())
    assert extraire_bureau(reponse) == "OVH"
    imbrique = {
        "entities": [
            {"roles": ["registrant"], "entities": [{"roles": ["registrar"], "handle": "292"}]}
        ]
    }
    assert extraire_bureau(imbrique) == "292"
    assert extraire_bureau({}) is None


async def test_sonder_rdap() -> None:
    urls: list[str] = []

    async def obtenir(url: str) -> httpx.Response:
        urls.append(url)
        return httpx.Response(
            200,
            text=(RDAP / "afnic_exempleville.json").read_text(),
            request=httpx.Request("GET", url),
        )

    donnees = await sonder_rdap("exempleville.fr", obtenir, {"fr": "https://rdap.nic.fr/"})
    assert donnees.bureau_enregistrement == "OVH"
    assert urls == ["https://rdap.nic.fr/domain/exempleville.fr"]


async def test_sonder_rdap_erreurs() -> None:
    async def introuvable(url: str) -> httpx.Response:
        return httpx.Response(404, request=httpx.Request("GET", url))

    donnees = await sonder_rdap("exempleville.fr", introuvable, {"fr": "https://rdap.nic.fr/"})
    assert donnees.bureau_enregistrement is None and donnees.erreur is not None
    inconnu = await sonder_rdap("exemple.zz", introuvable, {})
    assert inconnu.erreur == "aucun serveur RDAP connu pour .zz"
