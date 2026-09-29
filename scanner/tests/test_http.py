"""Tests de la sonde HTTP et des règles de politesse (réponses simulées avec respx)."""

from __future__ import annotations

import dataclasses

import httpx
import pytest
import respx

from bleublanccloud.configuration import Parametres
from bleublanccloud.modeles import Retrait
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.sondes.http import (
    ClientWebPoli,
    choisir_pages_internes,
    domaine_de_base,
    extraire_ressources,
    sonder_http,
)
from tests.conftest import DOSSIER_FIXTURES

HTML_ACCUEIL = (DOSSIER_FIXTURES / "http" / "exempleville_accueil.html").read_text()
HTML_SIMPLE = (DOSSIER_FIXTURES / "http" / "page_simple.html").read_text()
TYPE_HTML = {"content-type": "text/html; charset=utf-8"}


class HorlogeFactice:
    """Horloge et attente simulées : vérifie l'intervalle entre deux requêtes sans dormir."""

    def __init__(self) -> None:
        self.instant = 0.0
        self.attentes: list[float] = []

    def __call__(self) -> float:
        return self.instant

    async def attendre(self, duree: float) -> None:
        self.attentes.append(round(duree, 3))
        self.instant += duree


@pytest.fixture
def horloge() -> HorlogeFactice:
    return HorlogeFactice()


def fabriquer_client(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> ClientWebPoli:
    client = ClientWebPoli(parametres, referentiels)
    client.horloge = horloge
    client.attendre = horloge.attendre
    return client


# --------------------------------------------------------------------------- #
# Extraction des ressources et choix des pages
# --------------------------------------------------------------------------- #


def test_domaine_de_base() -> None:
    assert domaine_de_base("www.exempleville.fr") == "exempleville.fr"
    assert domaine_de_base("localhost") == "localhost"


def test_extraire_ressources_page_complete() -> None:
    ressources, liens = extraire_ressources(
        HTML_ACCUEIL, "https://www.exempleville.fr/", "exempleville.fr"
    )
    par_url = {r.url: r for r in ressources}
    assert par_url["https://www.exempleville.fr/css/style.css"].tierce is False
    assert par_url["https://stats.exempleville.fr/matomo.js"].tierce is False
    polices = [r for r in ressources if r.type == "police"]
    assert [r.domaine for r in polices] == ["fonts.gstatic.com"]
    gtm = par_url["https://www.googletagmanager.com/gtm.js?id="]
    assert (gtm.type, gtm.origine, gtm.tierce) == ("script", "script_en_ligne", True)
    assert par_url["https://use.typekit.net/abc1234.css"].origine == "css"
    assert par_url["https://cdn.exemple-agence.fr/img/fond.jpg"].type == "image"
    assert par_url["https://s3.eu-west-3.amazonaws.com/exempleville/affiche.png"].type == "image"
    assert par_url["https://www.youtube.com/embed/dQw4w9WgXcQ"].type == "iframe"
    # Les données structurées (JSON-LD) et les liens ne sont pas des ressources chargées.
    assert not any("schema.org" in r.url or "facebook" in r.domaine for r in ressources)
    urls_liens = [url for url, _ in liens]
    assert "https://www.exempleville.fr/mentions-legales" in urls_liens
    assert not any("facebook" in url or url.startswith("mailto") for url in urls_liens)


def test_choisir_pages_internes_par_priorite() -> None:
    liens = [
        ("https://www.exempleville.fr/actualites", "Actualités"),
        ("https://www.exempleville.fr/plan-du-site", "Plan du site"),
        ("https://www.exempleville.fr/accessibilite", "Accessibilité"),
        ("https://www.exempleville.fr/page-contact", "Écrire à la mairie"),
        ("https://www.exempleville.fr/mentions-legales", "Mentions légales"),
    ]
    pages = choisir_pages_internes(liens, set(), 3)
    assert pages == [
        "https://www.exempleville.fr/mentions-legales",
        "https://www.exempleville.fr/page-contact",
        "https://www.exempleville.fr/accessibilite",
    ]
    assert choisir_pages_internes(liens, {"https://www.exempleville.fr/mentions-legales"}, 1) == [
        "https://www.exempleville.fr/page-contact"
    ]


# --------------------------------------------------------------------------- #
# Parcours complet et politesse
# --------------------------------------------------------------------------- #


def simuler_site(robots: str = "User-agent: *\nDisallow: /contact\n") -> dict[str, respx.Route]:
    routes = {
        "robots_apex": respx.get("https://exempleville.fr/robots.txt").mock(
            return_value=httpx.Response(200, text=robots)
        ),
        "robots_www": respx.get("https://www.exempleville.fr/robots.txt").mock(
            return_value=httpx.Response(200, text=robots)
        ),
        "apex": respx.get("https://exempleville.fr/").mock(
            return_value=httpx.Response(301, headers={"location": "https://www.exempleville.fr/"})
        ),
        "accueil": respx.get("https://www.exempleville.fr/").mock(
            return_value=httpx.Response(
                200,
                text=HTML_ACCUEIL,
                headers=[
                    ("content-type", "text/html; charset=utf-8"),
                    ("server", "nginx"),
                    ("set-cookie", "PHPSESSID=secret; path=/"),
                    ("set-cookie", "_ga=GA1.2.123.456; path=/"),
                ],
            )
        ),
        "contact": respx.get("https://www.exempleville.fr/contact").mock(
            return_value=httpx.Response(200, text=HTML_SIMPLE, headers=TYPE_HTML)
        ),
    }
    for chemin in ("mentions-legales", "donnees-personnelles", "accessibilite", "plan-du-site"):
        routes[chemin] = respx.get(f"https://www.exempleville.fr/{chemin}").mock(
            return_value=httpx.Response(200, text=HTML_SIMPLE, headers=TYPE_HTML)
        )
    return routes


@respx.mock
async def test_parcours_complet_poli(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    routes = simuler_site()
    client = fabriquer_client(parametres, referentiels, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()

    assert donnees.url_finale == "https://www.exempleville.fr/"
    assert donnees.hote_final == "www.exempleville.fr"
    assert donnees.redirections == ["https://exempleville.fr/"]
    assert donnees.en_tetes["server"] == "nginx"
    assert "set-cookie" not in donnees.en_tetes
    # Seuls les noms des cookies sont conservés (jamais leur valeur)
    assert donnees.cookies == ["PHPSESSID", "_ga"]
    # robots.txt interdit /contact : la page n'est jamais demandée
    assert donnees.pages_interdites_robots == ["https://www.exempleville.fr/contact"]
    assert routes["contact"].call_count == 0
    # 5 pages HTML au maximum
    assert len(donnees.pages) <= 5
    assert [p.url for p in donnees.pages][:2] == [
        "https://www.exempleville.fr/",
        "https://www.exempleville.fr/mentions-legales",
    ]
    # User-Agent explicite sur toutes les requêtes
    for route in routes.values():
        for appel in route.calls:
            assert appel.request.headers["user-agent"].startswith("BleuBlancCloudBot/1.0")
    # 1 requête par seconde par domaine : chaque requête après la première attend 1 s
    nombre_requetes = sum(route.call_count for route in routes.values())
    assert horloge.attentes == [1.0] * (nombre_requetes - 1)
    assert len(donnees.html_pages) == len(donnees.pages)
    assert "html_pages" not in donnees.model_dump()


@respx.mock
async def test_limite_de_pages_configurable(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    simuler_site(robots="")
    parametres_reduits = parametres.model_copy(update={"pages_max_par_site": 2})
    client = fabriquer_client(parametres_reduits, referentiels, horloge)
    donnees = await sonder_http("https://www.exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert len(donnees.pages) == 2


@respx.mock
async def test_redirection_vers_un_domaine_retire_bloquee(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    referentiels_retrait = dataclasses.replace(
        referentiels,
        retraits={"retire.example": Retrait(domaine="retire.example", date_demande="2026-01-01")},
    )
    respx.get("https://exempleville.fr/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://exempleville.fr/").mock(
        return_value=httpx.Response(302, headers={"location": "https://www.retire.example/"})
    )
    route_retiree = respx.get(url__regex=r"https://www\.retire\.example/.*").mock(
        return_value=httpx.Response(200, text=HTML_SIMPLE, headers=TYPE_HTML)
    )
    client = fabriquer_client(parametres, referentiels_retrait, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert route_retiree.call_count == 0
    assert donnees.url_finale is None
    assert any("retrait" in erreur for erreur in donnees.erreurs)


@respx.mock
async def test_url_de_depart_retiree_aucune_requete(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    referentiels_retrait = dataclasses.replace(
        referentiels,
        retraits={"exempleville.fr": Retrait(domaine="exempleville.fr", date_demande="2026-01-01")},
    )
    route = respx.get(url__regex=r".*").mock(return_value=httpx.Response(200))
    client = fabriquer_client(parametres, referentiels_retrait, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert route.call_count == 0
    assert donnees.pages == []


@respx.mock
async def test_robots_injoignable_rien_n_est_analyse(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    respx.get(url__regex=r".*/robots\.txt").mock(return_value=httpx.Response(503))
    route_page = respx.get(url__regex=r".*/$").mock(
        return_value=httpx.Response(200, text=HTML_SIMPLE, headers=TYPE_HTML)
    )
    client = fabriquer_client(parametres, referentiels, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert route_page.call_count == 0
    assert donnees.pages == []
    assert any("robots.txt injoignable" in e for e in donnees.erreurs)


@respx.mock
async def test_robots_absent_tout_est_permis(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    respx.get("https://exempleville.fr/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://exempleville.fr/").mock(
        return_value=httpx.Response(200, text=HTML_SIMPLE, headers=TYPE_HTML)
    )
    client = fabriquer_client(parametres, referentiels, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert [p.statut for p in donnees.pages] == [200]


@respx.mock
async def test_deux_relances_maximum(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    respx.get("https://exempleville.fr/robots.txt").mock(return_value=httpx.Response(404))
    route = respx.get("https://exempleville.fr/").mock(
        side_effect=httpx.ConnectTimeout("délai dépassé")
    )
    respx.get(url__regex=r"https?://www\.exempleville\.fr/.*").mock(
        return_value=httpx.Response(404)
    )
    client = fabriquer_client(parametres, referentiels, horloge)
    await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert route.call_count == 3  # 1 tentative + 2 relances


@respx.mock
async def test_relance_puis_succes(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    respx.get("https://exempleville.fr/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://exempleville.fr/").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, text=HTML_SIMPLE, headers=TYPE_HTML),
        ]
    )
    client = fabriquer_client(parametres, referentiels, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert [p.statut for p in donnees.pages] == [200]


@respx.mock
async def test_certificat_invalide_signale(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    erreur = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate has expired")
    respx.get("https://exempleville.fr/robots.txt").mock(side_effect=[erreur, httpx.Response(404)])
    respx.get("https://exempleville.fr/").mock(
        return_value=httpx.Response(200, text=HTML_SIMPLE, headers=TYPE_HTML)
    )
    client = fabriquer_client(parametres, referentiels, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert donnees.certificat_invalide is True
    assert [p.statut for p in donnees.pages] == [200]


@respx.mock
async def test_ressource_non_html_non_analysee(
    parametres: Parametres, referentiels: Referentiels, horloge: HorlogeFactice
) -> None:
    respx.get("https://exempleville.fr/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://exempleville.fr/").mock(
        return_value=httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    client = fabriquer_client(parametres, referentiels, horloge)
    donnees = await sonder_http("https://exempleville.fr/", "exempleville.fr", client)
    await client.fermer()
    assert donnees.html_pages == []
    assert donnees.ressources == []
