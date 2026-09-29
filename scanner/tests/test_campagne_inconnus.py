"""Suites de la première campagne de test : fournisseurs ajoutés, auto-hébergement public,
MX sans adresse et indicateur de couverture (méthodologie v1.2)."""

from __future__ import annotations

import pytest

from bleublanccloud.analyse.attribution import Attributeur, normaliser_nom_as
from bleublanccloud.configuration import Parametres
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import scanner_domaine, situer_serveur
from bleublanccloud.sondes.ip import InfoIp, ResolveurAsn
from bleublanccloud.stockage.base import Base
from tests.conftest import ResolveurFactice, fabriquer_contexte

# --------------------------------------------------------------------------- #
# 1. Fournisseurs relevés par « referentiels inconnus »
# --------------------------------------------------------------------------- #

ASN_CAMPAGNE = [
    (25091, "IP-Max SA", "ip-max", "hebergement", "B"),
    (25394, "MK Netzdienste GmbH & Co. KG", "mk-netzdienste", "hebergement", "A"),
    (20756, "NAMESHIELD SAS", "nameshield", "hebergement", "A"),
    (209510, "NAMESHIELD SAS", "nameshield", "hebergement", "A"),
    (29608, "Ovea SAS", "ovea", "hebergement", "A"),
    (8304, "Ecritel SASU", "ecritel", "hebergement", "A"),
    (9180, "Alienor.net SARL", "alienor-net", "hebergement", "A"),
    (47833, "AGORA CALYCE SpAS", "agora-calyce", "hebergement", "A"),
    (16552, "Tiggee LLC", "dnsmadeeasy", "hebergement", "D"),
    (39588, "Mimecast Services Limited", "mimecast", "hebergement", "D"),
    (15826, "NFrance Conseil", "nfrance", "hebergement", "A"),
    (20900, "IMSNETWORKS", "ims-networks", "hebergement", "A"),
    (6738, "DRI SAS", "dri", "hebergement", "A"),
    (197816, "Etix Everywhere Ouest SAS", "etix-everywhere", "hebergement", "A"),
    (35280, "F5 Networks SARL", "f5", "cdn", "D"),
    (19551, "Incapsula Inc", "imperva", "cdn", "D"),
    (48799, "Ville et Eurometropole de Strasbourg", "auto-hebergement-public", "hebergement", "A"),
    (49566, "Ville de Paris", "auto-hebergement-public", "hebergement", "A"),
    (47608, "GROUPEMENT D'INTERET PUBLIC GIGALIS", "auto-hebergement-public", "hebergement", "A"),
]


@pytest.mark.parametrize(("asn", "nom_as", "fournisseur_id", "role", "niveau"), ASN_CAMPAGNE)
def test_asn_de_la_campagne_attribues(
    referentiels: Referentiels, asn: int, nom_as: str, fournisseur_id: str, role: str, niveau: str
) -> None:
    attributeur = Attributeur(referentiels.fournisseurs)
    correspondance = attributeur.par_ip(InfoIp(ip="192.0.2.1", asn=asn, nom_as=nom_as))
    assert correspondance is not None
    assert (correspondance.fournisseur.id, correspondance.role) == (fournisseur_id, role)
    assert correspondance.methode == "asn"
    assert attributeur.niveau(correspondance.fournisseur) == niveau


def test_nouveaux_fournisseurs_sources_et_a_verifier(referentiels: Referentiels) -> None:
    for _, _, fournisseur_id, _, _ in ASN_CAMPAGNE:
        fournisseur = referentiels.fournisseurs[fournisseur_id]
        assert fournisseur.sources, fournisseur_id
        assert fournisseur.a_verifier, fournisseur_id


@pytest.mark.parametrize(
    ("nom", "attendu"),
    [
        ("mimecast.com", "mimecast"),
        ("eu-smtp-inbound-1.mimecast.com", "mimecast"),
        ("ns0.dnsmadeeasy.com", "dnsmadeeasy"),
    ],
)
def test_nouveaux_motifs_de_noms(referentiels: Referentiels, nom: str, attendu: str) -> None:
    correspondance = Attributeur(referentiels.fournisseurs).par_nom(nom)
    assert correspondance is not None
    assert correspondance.fournisseur.id == attendu


# --------------------------------------------------------------------------- #
# 2. Auto-hébergement public (règle générique sur le nom d'AS)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("nom_as", "pays"),
    [
        ("COMMUNE DE PARIS", "FR"),
        ("Ville de Lyon", "FR"),
        ("Mairie d'Exempleville", None),
        ("Mairie d’Exempleville", "FR"),
        ("Métropole Européenne de Lille", "FR"),
        ("Eurométropole de Metz", "FR"),
        ("Communauté d'agglomération du Grand Exemple", "FR"),
        ("Communaute urbaine de Dunkerque", "FR"),
        ("CONSEIL DEPARTEMENTAL DE LA GIRONDE", "FR"),
        ("Conseil Régional Exemple", "FR"),
        ("Département de la Manche", "FR"),
        ("Region de Normandie", "FR"),
        ("Groupement d'Intérêt Public Exemple Numérique", "FR"),
        ("GIP Exemple", "FR"),
        ("Syndicat mixte Exemple Numérique", "FR"),
    ],
)
def test_organisme_public_reconnu_par_nom_as(
    referentiels: Referentiels, nom_as: str, pays: str | None
) -> None:
    attributeur = Attributeur(referentiels.fournisseurs)
    info = InfoIp(ip="192.0.2.10", asn=64510, nom_as=nom_as, pays=pays)
    correspondance = attributeur.par_ip(info)
    assert correspondance is not None, nom_as
    assert correspondance.fournisseur.id == "auto-hebergement-public"
    assert correspondance.methode == "nom_as"
    assert attributeur.niveau(correspondance.fournisseur) == "A"
    assert "AS64510" in correspondance.element


@pytest.mark.parametrize(
    ("nom_as", "pays"),
    [
        ("Metropole Television SA", "FR"),  # société (forme juridique)
        ("Ville de Geneve", "CH"),  # pays connu hors France
        ("Region de Bruxelles-Capitale", "BE"),
        ("Exemple Metropole SAS", "FR"),
        ("PETIT HEBERGEUR", "FR"),
        ("Villeneuve Telecom", "FR"),  # « ville » dans un mot
        ("", "FR"),
    ],
)
def test_faux_positifs_ecartes(referentiels: Referentiels, nom_as: str, pays: str) -> None:
    attributeur = Attributeur(referentiels.fournisseurs)
    info = InfoIp(ip="192.0.2.10", asn=64511, nom_as=nom_as or None, pays=pays)
    assert attributeur.par_ip(info) is None


def test_asn_recense_prioritaire_sur_le_nom(referentiels: Referentiels) -> None:
    attributeur = Attributeur(referentiels.fournisseurs)
    # Un ASN connu garde son fournisseur même si le nom ressemble à celui d'une collectivité
    info = InfoIp(ip="192.0.2.10", asn=16276, nom_as="Ville de Test", pays="FR")
    correspondance = attributeur.par_ip(info)
    assert correspondance is not None
    assert correspondance.fournisseur.id == "ovhcloud"


def test_normaliser_nom_as() -> None:
    assert normaliser_nom_as("  Métropole  d’Aix ") == "metropole d'aix"


# --------------------------------------------------------------------------- #
# 3. Résolution des serveurs MX / NS
# --------------------------------------------------------------------------- #


async def test_scan_mx_sans_adresse(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice.depuis_fixture("metropole-exemple.fr")
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    resultat = await scanner_domaine("metropole-exemple.fr", contexte)

    [mx] = [c for c in resultat.constats if c.cle == "mx"]
    assert (mx.valeur, mx.niveau) == ("smtp1bis.metropole-exemple.fr", "inconnu")
    assert mx.preuve["resolution"] == "sans_adresse"
    assert "aucune adresse" in mx.preuve["diagnostic"]
    # Une réponse vide n'est pas une erreur DNS : pas de nouvelle tentative
    assert resolveur.appels.count("smtp1bis.metropole-exemple.fr|A") == 1
    assert any(c.cle == "mx_sans_adresse" for c in resultat.constats)

    ns = {c.valeur: c for c in resultat.constats if c.cle == "ns"}
    # ns1 : réseau de la collectivité (nom d'AS) → auto-hébergement public, niveau A
    ns1 = ns["ns1.metropole-exemple.fr"]
    assert (ns1.fournisseur_id, ns1.niveau) == ("auto-hebergement-public", "A")
    assert ns1.preuve["attribution"]["methode"] == "nom_as"
    # ns2 : IPv4 sans opérateur connu, l'adresse IPv6 est essayée ensuite
    ns2 = ns["ns2.metropole-exemple.fr"]
    assert (ns2.fournisseur_id, ns2.niveau) == ("ip-max", "B")
    assert ns2.preuve["ip"] == "2001:db8::53"


async def test_serveur_erreur_passagere_relancee(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice(
        {
            "resolutions": {"mx.exemple.fr": {"ipv4": ["51.91.10.20"]}},
            "erreurs_passageres": ["mx.exemple.fr|A"],
        }
    )
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    situation = await situer_serveur("mx.exemple.fr", contexte)
    assert situation.resolution is None
    assert situation.info is not None and situation.info.asn == 16276
    assert resolveur.appels.count("mx.exemple.fr|A") == 2


async def test_serveur_echec_dns_persistant(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice({"erreurs": ["mx.exemple.fr|A"]})
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    situation = await situer_serveur("mx.exemple.fr", contexte)
    assert (situation.info, situation.resolution) == (None, "echec_dns")
    assert resolveur.appels.count("mx.exemple.fr|A") == 2


async def test_serveur_designe_par_une_ip(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice({})
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    situation = await situer_serveur("51.91.10.20", contexte)
    assert situation.resolution == "ip_litterale"
    assert situation.info is not None and situation.info.asn == 16276
    assert resolveur.appels == []


async def test_serveur_operateur_introuvable(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice({"resolutions": {"mx.exemple.fr": {"ipv4": ["192.0.2.7"]}}})
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    situation = await situer_serveur("mx.exemple.fr", contexte)
    assert situation.resolution == "asn_introuvable"
    assert situation.info is not None and situation.info.ip == "192.0.2.7"


async def test_statistiques_inconnus_nom_complet_du_mx(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice.depuis_fixture("metropole-exemple.fr")
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    resultat = await scanner_domaine("metropole-exemple.fr", contexte)
    with Base(":memory:") as base:
        base.enregistrer_scan(None, resultat, None, "1.2")
        stats = base.statistiques_inconnus()
    assert ("messagerie", "smtp1bis.metropole-exemple.fr (aucune adresse IP)", 1) in stats
