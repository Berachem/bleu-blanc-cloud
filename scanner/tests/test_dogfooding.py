"""Dogfooding : le site Bleu Blanc Cloud doit obtenir la note A sur son propre scan.

Le scénario reproduit la configuration de production décrite dans deploy/README.md :
CNAME vers Codeberg Pages (non proxifié), aucun service tiers, aucun cookie, aucun MX.
La page analysée est la vraie page d'accueil construite par Astro.
"""

from __future__ import annotations

import httpx
import respx

from bleublanccloud.analyse.score import calculer_score
from bleublanccloud.configuration import Parametres
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import ContexteScan, scanner_domaine
from bleublanccloud.sondes.ip import ResolveurAsn
from tests.conftest import DOSSIER_FIXTURES, ResolveurFactice
from tests.test_http import HorlogeFactice, fabriquer_client

DOMAINE = "bleublanccloud.berachem.dev"
HTML_SITE = (DOSSIER_FIXTURES / "http" / "site_bleublanccloud.html").read_text()


def simuler_site() -> None:
    respx.get(f"https://{DOMAINE}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get(f"https://{DOMAINE}/").mock(
        return_value=httpx.Response(
            200, text=HTML_SITE, headers={"content-type": "text/html; charset=utf-8"}
        )
    )
    respx.get(url__regex=rf"https://{DOMAINE}/.+").mock(
        return_value=httpx.Response(200, text=HTML_SITE, headers={"content-type": "text/html"})
    )


async def scanner_site(
    parametres: Parametres,
    referentiels: Referentiels,
    resolveur: ResolveurFactice,
    asn: ResolveurAsn,
):  # type: ignore[no-untyped-def]
    client = fabriquer_client(parametres, referentiels, HorlogeFactice())
    contexte = ContexteScan.construire(parametres, referentiels, resolveur, asn, client_web=client)
    try:
        return await scanner_domaine(DOMAINE, contexte)
    finally:
        await client.fermer()


@respx.mock
async def test_le_site_obtient_la_note_a(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    simuler_site()
    resolveur = ResolveurFactice.depuis_fixture(DOMAINE)
    resultat = await scanner_site(parametres, referentiels, resolveur, resolveur_asn)
    assert resultat.sondes_reussies == ["dns", "http"]
    # Aucun service tiers, aucune mesure d'audience, aucun domaine tiers inconnu
    assert not [
        c for c in resultat.constats if c.categorie in ("services_tiers", "mesure_audience")
    ]
    assert resultat.informations.domaines_tiers_inconnus == []
    hebergement = next(c for c in resultat.constats if c.categorie == "hebergement")
    assert (hebergement.fournisseur_id, hebergement.niveau) == ("codeberg", "A")
    score = calculer_score(resultat.constats, resultat.sondes_reussies)
    assert score.note == "A", score
    assert score.score_global >= 85


@respx.mock
async def test_sans_cloudflare_en_dns_le_score_est_parfait(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    simuler_site()
    resolveur = ResolveurFactice.depuis_fixture(DOMAINE)
    resolveur.enregistrements["berachem.dev|NS"] = ["ns1.desec.io", "ns2.desec.org"]
    resultat = await scanner_site(parametres, referentiels, resolveur, resolveur_asn)
    score = calculer_score(resultat.constats, resultat.sondes_reussies)
    # DNS hébergé par deSEC (association allemande, niveau A) : toutes les catégories à 100
    assert score.score_global == 100
    assert "dns" not in score.categories_non_evaluables


@respx.mock
async def test_proxy_cloudflare_active_fait_perdre_la_note_a(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    simuler_site()
    resolveur = ResolveurFactice.depuis_fixture(DOMAINE)
    resolveur.resolutions[DOMAINE] = {"cnames": [], "ipv4": ["104.16.1.1"], "ipv6": []}
    resultat = await scanner_site(parametres, referentiels, resolveur, resolveur_asn)
    score = calculer_score(resultat.constats, resultat.sondes_reussies)
    assert score.note != "A"
