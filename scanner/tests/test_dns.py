"""Tests de la sonde DNS (sans réseau)."""

from __future__ import annotations

from typing import Any

import dns.exception
import dns.message
import dns.name
import dns.rdataclass
import dns.rdatatype
import dns.resolver
import pytest

from bleublanccloud.sondes.dns import (
    ChaineResolution,
    ErreurDns,
    ResolveurDnsPython,
    normaliser_nom,
    sonder_dns,
)
from tests.conftest import ResolveurFactice


def fabriquer_reponse(
    question: str, type_enregistrement: str, reponses: str
) -> dns.resolver.Answer:
    message = dns.message.from_text(
        f"""id 1234
opcode QUERY
rcode NOERROR
flags QR RD RA
;QUESTION
{question} IN {type_enregistrement}
;ANSWER
{reponses}
"""
    )
    return dns.resolver.Answer(
        dns.name.from_text(question),
        dns.rdatatype.from_text(type_enregistrement),
        dns.rdataclass.IN,
        message,
    )


class ResolveurEnregistre:
    """Remplace dns.asyncresolver.Resolver.resolve par des réponses enregistrées."""

    def __init__(self, reponses: dict[tuple[str, str], Any]) -> None:
        self.reponses = reponses

    async def resolve(self, nom: str, type_enregistrement: str, **_: Any) -> Any:
        reponse = self.reponses.get((nom, type_enregistrement))
        if isinstance(reponse, Exception):
            raise reponse
        if reponse is None:
            raise dns.resolver.NXDOMAIN()
        return reponse


def resolveur_python(reponses: dict[tuple[str, str], Any]) -> ResolveurDnsPython:
    resolveur = ResolveurDnsPython(delai_s=2)
    resolveur._resolveur = ResolveurEnregistre(reponses)  # type: ignore[assignment]
    return resolveur


def test_normaliser_nom() -> None:
    assert normaliser_nom(" Mail.Exemple.FR. ") == "mail.exemple.fr"


async def test_txt_multi_chaines_reassemble() -> None:
    reponse = fabriquer_reponse(
        "exemple.fr.",
        "TXT",
        'exemple.fr. 300 IN TXT "v=spf1 include:_spf.google.com" " include:mx.ovh.com -all"',
    )
    resolveur = resolveur_python({("exemple.fr", "TXT"): reponse})
    assert await resolveur.interroger("exemple.fr", "TXT") == [
        "v=spf1 include:_spf.google.com include:mx.ovh.com -all"
    ]


async def test_mx_et_ns_normalises() -> None:
    resolveur = resolveur_python(
        {
            ("exemple.fr", "MX"): fabriquer_reponse(
                "exemple.fr.", "MX", "exemple.fr. 300 IN MX 10 Mail.Exemple.FR."
            ),
            ("exemple.fr", "NS"): fabriquer_reponse(
                "exemple.fr.", "NS", "exemple.fr. 300 IN NS DNS10.OVH.NET."
            ),
        }
    )
    assert await resolveur.interroger("exemple.fr", "MX") == ["10 mail.exemple.fr"]
    assert await resolveur.interroger("exemple.fr", "NS") == ["dns10.ovh.net"]


async def test_absence_enregistrement_retourne_liste_vide() -> None:
    resolveur = resolveur_python({})
    assert await resolveur.interroger("inexistant.fr", "MX") == []


async def test_delai_depasse_leve_erreur_dns() -> None:
    resolveur = resolveur_python({("lent.fr", "MX"): dns.exception.Timeout()})
    with pytest.raises(ErreurDns):
        await resolveur.interroger("lent.fr", "MX")


async def test_resolution_suit_la_chaine_cname() -> None:
    reponse_a = fabriquer_reponse(
        "www.exemple.fr.",
        "A",
        "www.exemple.fr. 300 IN CNAME exemple.fr.cdn.cloudflare.net.\n"
        "exemple.fr.cdn.cloudflare.net. 300 IN A 104.16.1.1",
    )
    resolveur = resolveur_python({("www.exemple.fr", "A"): reponse_a})
    chaine = await resolveur.resoudre("www.exemple.fr")
    assert chaine.cnames == ["exemple.fr.cdn.cloudflare.net"]
    assert chaine.ipv4 == ["104.16.1.1"]
    assert chaine.ipv6 == []
    assert chaine.ip_principale == "104.16.1.1"


def test_ip_principale_prefere_ipv4_puis_ipv6() -> None:
    assert ChaineResolution(nom="a", ipv6=["2001:db8::1"]).ip_principale == "2001:db8::1"
    assert ChaineResolution(nom="a").ip_principale is None


async def test_sonder_dns_scenario_complet() -> None:
    resolveur = ResolveurFactice.depuis_fixture("exempleville.fr")
    donnees = await sonder_dns("ExempleVille.fr.", resolveur)
    assert donnees.domaine == "exempleville.fr"
    assert donnees.zone == "exempleville.fr"
    assert donnees.ns == ["dns110.ovh.net", "ns110.ovh.net"]
    assert [mx.hote for mx in donnees.mx] == ["exempleville-fr.mail.protection.outlook.com"]
    assert donnees.spf is not None and "spf.protection.outlook.com" in donnees.spf
    assert donnees.dmarc is not None and donnees.dmarc.startswith("v=DMARC1")
    assert set(donnees.resolutions) == {"exempleville.fr", "www.exempleville.fr"}
    assert donnees.erreurs == []


async def test_sonder_dns_mx_trie_et_erreurs_consignees() -> None:
    resolveur = ResolveurFactice.depuis_fixture("petite-commune.fr")
    resolveur.enregistrements["petite-commune.fr|MX"] = [
        "20 spool.mail.gandi.net",
        "10 mail.prestataire-local.fr",
    ]
    donnees = await sonder_dns("petite-commune.fr", resolveur)
    assert [(mx.priorite, mx.hote) for mx in donnees.mx] == [
        (10, "mail.prestataire-local.fr"),
        (20, "spool.mail.gandi.net"),
    ]
    assert any("CAA" in erreur for erreur in donnees.erreurs)
    assert donnees.spf is None
    assert donnees.dmarc is None


async def test_sonder_dns_mx_nul() -> None:
    donnees = await sonder_dns("mx-nul.fr", ResolveurFactice.depuis_fixture("mx-nul.fr"))
    assert donnees.mx_nul is True
    assert donnees.mx == []
