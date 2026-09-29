"""Tests de l'attribution (preuve → fournisseur → niveau de juridiction)."""

from __future__ import annotations

import pytest

from bleublanccloud.analyse.attribution import (
    Attributeur,
    constat_hebergement,
    constats_dns_informatifs,
    constats_serveurs,
    correspond_motif,
    niveau_juridiction,
    pire_niveau,
)
from bleublanccloud.modeles import Fournisseur
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.sondes.dns import ChaineResolution, DonneesDns, EnregistrementMx
from bleublanccloud.sondes.ip import InfoIp


def fournisseur(**champs: object) -> Fournisseur:
    base: dict[str, object] = {
        "id": "test",
        "nom": "Test",
        "pays_siege": "FR",
        "soumis_cloud_act": False,
        "sources": ["https://exemple.org/"],
    }
    base.update(champs)
    return Fournisseur.model_validate(base)


@pytest.fixture
def attributeur(referentiels: Referentiels) -> Attributeur:
    return Attributeur(referentiels.fournisseurs)


# --------------------------------------------------------------------------- #
# Niveaux
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("champs", "attendu"),
    [
        ({"pays_siege": "FR"}, "A"),
        ({"pays_siege": "FR", "pays_maison_mere": "NL"}, "A"),
        ({"pays_siege": "FR", "pays_maison_mere": "US", "soumis_cloud_act": True}, "D"),
        ({"pays_siege": "CH"}, "B"),
        ({"pays_siege": "MT", "pays_maison_mere": "GB"}, "B"),
        ({"pays_siege": "US", "soumis_cloud_act": True}, "D"),
        ({"pays_siege": "RU", "autre_loi_extraterritoriale": "SORM"}, "D"),
    ],
)
def test_niveau_juridiction(champs: dict[str, object], attendu: str) -> None:
    assert niveau_juridiction(fournisseur(**champs)) == attendu


def test_pire_niveau() -> None:
    assert pire_niveau(["A", "D", "B"]) == "D"
    assert pire_niveau(["A", "inconnu"]) == "A"
    assert pire_niveau(["inconnu"]) == "inconnu"
    assert pire_niveau([]) == "inconnu"


@pytest.mark.parametrize(
    ("nom", "motif", "attendu"),
    [
        ("mx1.mail.ovh.net", "ovh.net", True),
        ("ovh.net", "ovh.net", True),
        ("evilovh.net", "ovh.net", False),
        ("OVH.NET.", "ovh.net", True),
        ("ns-123.awsdns-45.com", r"re:(^|\.)awsdns-\d+\.", True),
        ("awsdns.exemple.fr", r"re:(^|\.)awsdns-\d+\.", False),
    ],
)
def test_correspond_motif(nom: str, motif: str, attendu: bool) -> None:
    assert correspond_motif(nom, motif) is attendu


# --------------------------------------------------------------------------- #
# Attributeur
# --------------------------------------------------------------------------- #


def test_par_nom_prefere_le_motif_le_plus_specifique(attributeur: Attributeur) -> None:
    cdn = attributeur.par_nom("www.ville.fr.cdn.cloudflare.net")
    assert cdn is not None and (cdn.fournisseur.id, cdn.role) == ("cloudflare", "cdn")
    pages = attributeur.par_nom("site-ville.pages.dev")
    assert pages is not None and (pages.fournisseur.id, pages.role) == ("cloudflare", "hebergement")
    microsoft = attributeur.par_nom("ville-fr.mail.protection.outlook.com")
    assert microsoft is not None and microsoft.fournisseur.id == "microsoft"
    assert attributeur.par_nom("inconnu.exemple.org") is None


def test_par_chaine_retient_le_premier_maillon_reconnu(attributeur: Attributeur) -> None:
    correspondance = attributeur.par_chaine(["alias.ville.fr", "ville.netlify.app"])
    assert correspondance is not None and correspondance.fournisseur.id == "netlify"


def test_par_ip_plages_et_asn(attributeur: Attributeur) -> None:
    cloudfront = attributeur.par_ip(
        InfoIp(ip="13.32.0.1", plage_cloud="aws", service_cloud="CLOUDFRONT")
    )
    assert cloudfront is not None and cloudfront.role == "cdn"
    ec2 = attributeur.par_ip(InfoIp(ip="52.95.0.1", plage_cloud="aws", service_cloud="EC2"))
    assert ec2 is not None and ec2.role == "hebergement"
    cloudflare = attributeur.par_ip(InfoIp(ip="104.16.1.1", plage_cloud="cloudflare"))
    assert cloudflare is not None and cloudflare.role == "cdn"
    akamai = attributeur.par_ip(InfoIp(ip="2.16.0.1", asn=20940))
    assert akamai is not None and (akamai.fournisseur.id, akamai.role) == ("akamai", "cdn")
    ovh = attributeur.par_ip(InfoIp(ip="51.91.0.1", asn=16276))
    assert ovh is not None and (ovh.fournisseur.id, ovh.methode) == ("ovhcloud", "asn")
    assert attributeur.par_ip(InfoIp(ip="192.0.2.1", asn=64500)) is None
    assert attributeur.par_ip(None) is None


def test_par_en_tetes(attributeur: Attributeur) -> None:
    trouves = attributeur.par_en_tetes({"Server": "AmazonS3", "X-Autre": "1"})
    assert [c.fournisseur.id for c in trouves] == ["aws"]
    assert attributeur.par_en_tetes({"server": "nginx"}) == []


# --------------------------------------------------------------------------- #
# Constat d'hébergement (dont la règle du niveau C)
# --------------------------------------------------------------------------- #


def resolution(ip: str, cnames: list[str] | None = None) -> ChaineResolution:
    return ChaineResolution(nom="www.ville.fr", cnames=cnames or [], ipv4=[ip])


def test_hebergement_ovh_niveau_a(attributeur: Attributeur) -> None:
    constat = constat_hebergement(
        resolution("51.91.0.1"),
        InfoIp(ip="51.91.0.1", asn=16276, nom_as="OVH SAS"),
        {},
        attributeur,
    )
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau, constat.cle) == ("ovhcloud", "A", "hebergeur")
    assert constat.valeur == "51.91.0.1 (AS16276 OVH SAS)"
    assert constat.preuve["attribution"]["methode"] == "asn"


def test_hebergement_cdn_extra_europeen_origine_inconnue_niveau_c(attributeur: Attributeur) -> None:
    constat = constat_hebergement(
        resolution("104.16.1.1"),
        InfoIp(ip="104.16.1.1", plage_cloud="cloudflare", asn=13335),
        {"server": "cloudflare", "cf-ray": "abc"},
        attributeur,
    )
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau, constat.cle) == ("cloudflare", "C", "cdn")
    assert constat.preuve["origine"] == "masquée par le CDN"


def test_hebergement_cdn_avec_origine_americaine_niveau_d(attributeur: Attributeur) -> None:
    constat = constat_hebergement(
        resolution("13.32.0.1", ["d111.cloudfront.net"]),
        InfoIp(ip="13.32.0.1", plage_cloud="aws", service_cloud="CLOUDFRONT"),
        {"server": "AmazonS3"},
        attributeur,
    )
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau) == ("aws", "D")
    assert constat.preuve["origine"]["fournisseur_id"] == "aws"


def test_hebergement_cdn_devant_origine_vercel_niveau_d(attributeur: Attributeur) -> None:
    constat = constat_hebergement(
        resolution("104.16.1.1"),
        InfoIp(ip="104.16.1.1", plage_cloud="cloudflare"),
        {"x-vercel-id": "cdg1::abc"},
        attributeur,
    )
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau) == ("vercel", "D")


def test_hebergement_cdn_europeen_non_plafonne(attributeur: Attributeur) -> None:
    constat = constat_hebergement(
        resolution("192.0.2.10", ["ville.b-cdn.net"]), None, {}, attributeur
    )
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau) == ("bunny", "A")


def test_hebergement_cname_codeberg_niveau_a(attributeur: Attributeur) -> None:
    constat = constat_hebergement(
        resolution("217.197.84.141", ["ville.codeberg.page"]),
        InfoIp(ip="217.197.84.141", asn=64501),
        {},
        attributeur,
    )
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau, constat.sonde) == ("codeberg", "A", "dns")


def test_hebergement_fournisseur_inconnu(attributeur: Attributeur) -> None:
    constat = constat_hebergement(
        resolution("185.10.20.30"),
        InfoIp(ip="185.10.20.30", asn=64500, nom_as="PETIT HEBERGEUR", pays="FR"),
        {},
        attributeur,
    )
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau) == (None, "inconnu")
    assert constat.preuve["pays"] == "FR"


def test_hebergement_sans_ip(attributeur: Attributeur) -> None:
    assert constat_hebergement(ChaineResolution(nom="x.fr"), None, {}, attributeur) is None


# --------------------------------------------------------------------------- #
# Messagerie, DNS et constats informatifs
# --------------------------------------------------------------------------- #


def test_constats_mx_par_nom_puis_par_ip(attributeur: Attributeur) -> None:
    constats = constats_serveurs(
        "mx",
        [("ville-fr.mail.protection.outlook.com", 10), ("mail.prestataire.fr", 20)],
        {"mail.prestataire.fr": InfoIp(ip="51.91.0.25", asn=16276)},
        attributeur,
    )
    assert [(c.fournisseur_id, c.niveau, c.sonde) for c in constats] == [
        ("microsoft", "D", "dns"),
        ("ovhcloud", "A", "ip"),
    ]
    assert constats[0].preuve["priorite"] == 10
    assert all(c.categorie == "messagerie" for c in constats)


def test_constats_ns_regex_awsdns_et_inconnu(attributeur: Attributeur) -> None:
    constats = constats_serveurs(
        "ns", [("ns-12.awsdns-34.org", None), ("ns1.inconnu.fr", None)], {}, attributeur
    )
    assert [(c.fournisseur_id, c.niveau) for c in constats] == [("aws", "D"), (None, "inconnu")]
    assert all(c.categorie == "dns" for c in constats)


def test_constats_informatifs() -> None:
    sans_mx = constats_dns_informatifs(DonneesDns(domaine="a.fr"))
    assert [c.cle for c in sans_mx] == ["mx_absent", "spf", "dmarc"]
    assert sans_mx[1].valeur == "Aucun enregistrement SPF"
    mx_nul = constats_dns_informatifs(DonneesDns(domaine="a.fr", mx_nul=True))
    assert mx_nul[0].cle == "mx_nul"
    complet = constats_dns_informatifs(
        DonneesDns(
            domaine="a.fr",
            mx=[EnregistrementMx(priorite=10, hote="mx.a.fr")],
            txt=["v=spf1 -all"],
            dmarc="v=DMARC1; p=reject",
        )
    )
    assert [c.valeur for c in complet] == ["v=spf1 -all", "v=DMARC1; p=reject"]
    assert all(c.categorie == "informatif" for c in complet)
