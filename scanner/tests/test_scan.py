"""Tests de l'orchestration d'un scan (sans réseau)."""

from __future__ import annotations

import dataclasses

import httpx
import pytest
import respx

from bleublanccloud.configuration import Parametres
from bleublanccloud.modeles import Retrait
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import CibleInvalide, ContexteScan, normaliser_cible, scanner_domaine
from bleublanccloud.sondes.ip import ResolveurAsn
from bleublanccloud.sondes.tls import DonneesTls
from tests.conftest import DOSSIER_FIXTURES, ResolveurFactice, fabriquer_contexte
from tests.test_http import HorlogeFactice, fabriquer_client, simuler_site


@pytest.mark.parametrize(
    ("entree", "domaine", "url"),
    [
        ("exempleville.fr", "exempleville.fr", "https://exempleville.fr/"),
        ("www.ExempleVille.fr", "exempleville.fr", "https://www.exempleville.fr/"),
        (
            "http://www.exempleville.fr/accueil",
            "exempleville.fr",
            "http://www.exempleville.fr/accueil",
        ),
        ("mairie-évry.fr", "xn--mairie-vry-h7a.fr", "https://xn--mairie-vry-h7a.fr/"),
    ],
)
def test_normaliser_cible(entree: str, domaine: str, url: str) -> None:
    cible = normaliser_cible(entree)
    assert (cible.domaine, cible.url_site) == (domaine, url)


@pytest.mark.parametrize("entree", ["", "ftp://exemple.fr", "pas un domaine", "localhost", "a..fr"])
def test_normaliser_cible_invalide(entree: str) -> None:
    with pytest.raises(CibleInvalide):
        normaliser_cible(entree)


async def test_scan_exempleville(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    contexte = fabriquer_contexte(
        parametres, referentiels, ResolveurFactice.depuis_fixture("exempleville.fr"), resolveur_asn
    )
    resultat = await scanner_domaine("exempleville.fr", contexte)
    assert resultat.statut == "termine"
    par_cle = {(c.categorie, c.cle): c for c in resultat.constats}
    assert par_cle[("hebergement", "hebergeur")].fournisseur_id == "ovhcloud"
    assert par_cle[("hebergement", "hebergeur")].niveau == "A"
    assert par_cle[("messagerie", "mx")].fournisseur_id == "microsoft"
    assert par_cle[("messagerie", "mx")].niveau == "D"
    assert {c.fournisseur_id for c in resultat.constats if c.categorie == "dns"} == {"ovhcloud"}
    assert resultat.informations.fournisseurs_secnumcloud == ["OVHcloud"]


async def test_scan_cdn_sans_mx(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    contexte = fabriquer_contexte(
        parametres, referentiels, ResolveurFactice.depuis_fixture("cdn-exemple.fr"), resolveur_asn
    )
    resultat = await scanner_domaine("cdn-exemple.fr", contexte)
    hebergement = next(c for c in resultat.constats if c.categorie == "hebergement")
    assert (hebergement.fournisseur_id, hebergement.niveau) == ("cloudflare", "C")
    assert not [c for c in resultat.constats if c.categorie == "messagerie"]
    assert any(c.cle == "mx_absent" for c in resultat.constats)


async def test_scan_serveurs_resolus_par_ip_et_erreurs_partielles(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice.depuis_fixture("petite-commune.fr")
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    resultat = await scanner_domaine("petite-commune.fr", contexte)
    assert resultat.statut == "partiel"
    mx = [c for c in resultat.constats if c.cle == "mx"]
    assert [(c.valeur, c.fournisseur_id, c.niveau) for c in mx] == [
        ("mail.prestataire-local.fr", None, "inconnu"),
        ("spool.mail.gandi.net", "gandi", "A"),
    ]
    ns = next(c for c in resultat.constats if c.cle == "ns")
    assert (ns.fournisseur_id, ns.niveau) == ("ovhcloud", "A")
    hebergement = next(c for c in resultat.constats if c.categorie == "hebergement")
    assert hebergement.preuve["nom_hote"] == "www.petite-commune.fr"
    # Le serveur de secours Gandi est reconnu par son nom : aucune résolution nécessaire
    assert "spool.mail.gandi.net|A" not in resolveur.appels


async def test_scan_domaine_retire_sans_aucune_requete(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    referentiels_avec_retrait = dataclasses.replace(
        referentiels,
        retraits={"exempleville.fr": Retrait(domaine="exempleville.fr", date_demande="2026-01-01")},
    )
    resolveur = ResolveurFactice.depuis_fixture("exempleville.fr")
    contexte = fabriquer_contexte(parametres, referentiels_avec_retrait, resolveur, resolveur_asn)
    resultat = await scanner_domaine("www.exempleville.fr", contexte)
    assert resultat.statut == "exclu"
    assert resultat.constats == []
    assert resolveur.appels == []


async def test_scan_domaine_inexistant(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    contexte = fabriquer_contexte(parametres, referentiels, ResolveurFactice({}), resolveur_asn)
    resultat = await scanner_domaine("inexistant.fr", contexte)
    assert resultat.statut == "erreur"


@respx.mock
async def test_scan_complet_avec_http_tls_rdap(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    simuler_site()
    respx.get("https://rdap.nic.fr/domain/exempleville.fr").mock(
        return_value=httpx.Response(
            200, text=(DOSSIER_FIXTURES / "rdap" / "afnic_exempleville.json").read_text()
        )
    )
    horloge = HorlogeFactice()
    client_web = fabriquer_client(parametres, referentiels, horloge)
    client_rdap = fabriquer_client(parametres, referentiels, horloge)
    hotes_tls: list[str] = []

    async def sonde_tls(hote: str) -> DonneesTls:
        hotes_tls.append(hote)
        return DonneesTls(hote=hote, emetteur_organisation="Let's Encrypt", emetteur_nom="R11")

    contexte = ContexteScan.construire(
        parametres,
        referentiels,
        ResolveurFactice.depuis_fixture("exempleville.fr"),
        resolveur_asn,
        client_web=client_web,
        client_rdap=client_rdap,
        serveurs_rdap={"fr": "https://rdap.nic.fr/"},
        sonde_tls=sonde_tls,
    )
    resultat = await scanner_domaine("exempleville.fr", contexte)
    await client_web.fermer()
    await client_rdap.fermer()

    assert resultat.informations.bureau_enregistrement == "OVH"
    assert resultat.informations.autorite_certification == "Let's Encrypt (R11)"
    assert hotes_tls == ["www.exempleville.fr"]
    hebergement = next(c for c in resultat.constats if c.categorie == "hebergement")
    assert hebergement.preuve["nom_hote"] == "www.exempleville.fr"
    regles = {c.preuve.get("regle") for c in resultat.constats}
    assert {"youtube", "google-fonts", "microsoft-365", "tarteaucitron"} <= regles
    assert "fournisseur:google" in regles
    assert "cdn.exemple-agence.fr" in resultat.informations.domaines_tiers_inconnus
    # Les ressources de l'hébergeur du site (OVHcloud) ne sont jamais comptées comme tierces
    assert "fournisseur:ovhcloud" not in regles
