"""Sonde HTTP : page d'accueil + jusqu'à 4 pages internes, en-têtes, cookies, ressources tierces.

Règles de politesse (obligatoires, CLAUDE.md section 7) :
- User-Agent explicite ;
- 5 pages HTML maximum par site, 1 requête par seconde par domaine ;
- concurrence globale plafonnée ;
- délai d'expiration de 10 s, 2 relances maximum ;
- respect de robots.txt pour les pages HTML ;
- liste de retraits vérifiée avant CHAQUE requête (redirections comprises).

Aucune soumission de formulaire, aucune authentification, aucun test de vulnérabilité.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Literal
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from bleublanccloud.configuration import Parametres
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.sondes.reseau import TransportReseauPublic

journal = logging.getLogger(__name__)

JETON_ROBOTS = "BleuBlancCloudBot"
REDIRECTIONS_MAX = 5
TAILLE_HTML_MAX = 3_000_000
LONGUEUR_EN_TETE_MAX = 500

TypeRessource = Literal["script", "feuille_style", "police", "iframe", "image", "media", "autre"]
OrigineRessource = Literal["balise", "script_en_ligne", "css"]

# Pages internes recherchées, par ordre de priorité (texte du lien ou adresse).
MOTIFS_PAGES_INTERNES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(motif, re.IGNORECASE)
    for motif in (
        r"mentions[\s_-]*l[ée]gales",
        r"\bcontact",
        r"(donn[ée]es[\s_-]*personnelles|confidentialit[ée]|vie[\s_-]*priv[ée]e|cookies|rgpd)",
        r"accessibilit[ée]",
        r"plan[\s_-]*du[\s_-]*site",
    )
)
EXTENSIONS_POLICES = (".woff2", ".woff", ".ttf", ".otf", ".eot")
TYPES_SCRIPT_JS = ("", "text/javascript", "application/javascript", "module", "text/ecmascript")
MOTIF_URL_CSS = re.compile(r"url\(\s*['\"]?((?:https?:)?//[^'\")\s]+)", re.IGNORECASE)
MOTIF_IMPORT_CSS = re.compile(r"@import\s+['\"]((?:https?:)?//[^'\"]+)['\"]", re.IGNORECASE)
MOTIF_URL_JS = re.compile(r"(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,63}(?:/[^\s'\"<>`\\]*)?", re.I)


class UrlExclue(Exception):
    """L'URL appartient à un domaine qui a demandé son retrait."""


class InterditParRobots(Exception):
    """robots.txt interdit l'accès à cette page."""


def domaine_de_base(hote: str) -> str:
    """Approximation du domaine enregistrable : les deux derniers libellés."""
    libelles = hote.lower().rstrip(".").split(".")
    return ".".join(libelles[-2:]) if len(libelles) >= 2 else hote.lower()


class Ressource(BaseModel):
    type: TypeRessource
    url: str
    domaine: str
    tierce: bool
    origine: OrigineRessource = "balise"


class PageAnalysee(BaseModel):
    url: str
    statut: int
    type_contenu: str | None = None


class DonneesHttp(BaseModel):
    """Données brutes collectées par la sonde HTTP."""

    url_depart: str
    url_finale: str | None = None
    hote_final: str | None = None
    redirections: list[str] = Field(default_factory=list)
    en_tetes: dict[str, str] = Field(default_factory=dict)
    cookies: list[str] = Field(default_factory=list)
    ressources: list[Ressource] = Field(default_factory=list)
    pages: list[PageAnalysee] = Field(default_factory=list)
    pages_interdites_robots: list[str] = Field(default_factory=list)
    certificat_invalide: bool = False
    erreurs: list[str] = Field(default_factory=list)
    # HTML brut des pages, utilisé par la détection mais jamais stocké ni exporté.
    html_pages: list[str] = Field(default_factory=list, exclude=True)


def est_erreur_certificat(erreur: BaseException) -> bool:
    texte = str(erreur).lower()
    return isinstance(erreur, httpx.ConnectError) and (
        "certificate" in texte or "certificat" in texte
    )


def _est_erreur_relancable(erreur: BaseException) -> bool:
    if isinstance(erreur, httpx.TransportError):
        return not isinstance(erreur, httpx.UnsupportedProtocol) and not est_erreur_certificat(
            erreur
        )
    if isinstance(erreur, httpx.HTTPStatusError):
        return erreur.response.status_code in (502, 503, 504)
    return False


class ClientWebPoli:
    """Client HTTP qui applique les règles de politesse du projet."""

    def __init__(
        self,
        parametres: Parametres,
        referentiels: Referentiels,
        client: httpx.AsyncClient | None = None,
        client_sans_verification: httpx.AsyncClient | None = None,
    ) -> None:
        self.parametres = parametres
        self.referentiels = referentiels
        en_tetes = {
            "User-Agent": parametres.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }
        # Garde réseau : aucune connexion vers localhost ou un réseau privé (voir reseau.py)
        self._client = client or httpx.AsyncClient(
            headers=en_tetes,
            timeout=parametres.delai_expiration_s,
            follow_redirects=False,
            transport=TransportReseauPublic(verify=True),
        )
        self._client_sans_verification = client_sans_verification or httpx.AsyncClient(
            headers=en_tetes,
            timeout=parametres.delai_expiration_s,
            follow_redirects=False,
            transport=TransportReseauPublic(verify=False),
        )
        self._semaphore = asyncio.Semaphore(parametres.concurrence_max)
        self._verrous: dict[str, asyncio.Lock] = {}
        self._dernier_acces: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.robots_injoignables: set[str] = set()
        self.horloge = time.monotonic
        self.attendre = asyncio.sleep

    async def fermer(self) -> None:
        await self._client.aclose()
        await self._client_sans_verification.aclose()

    def verifier_retrait(self, url: str) -> None:
        hote = urlsplit(url).hostname or ""
        if self.referentiels.est_retire(hote):
            raise UrlExclue(f"{hote} a demandé son retrait")

    async def _respecter_intervalle(self, hote: str) -> None:
        cle = domaine_de_base(hote)
        verrou = self._verrous.setdefault(cle, asyncio.Lock())
        async with verrou:
            precedent = self._dernier_acces.get(cle)
            if precedent is not None:
                attente = self.parametres.intervalle_par_domaine_s - (self.horloge() - precedent)
                if attente > 0:
                    await self.attendre(attente)
            self._dernier_acces[cle] = self.horloge()

    async def _get(self, url: str, sans_verification: bool) -> httpx.Response:
        client = self._client_sans_verification if sans_verification else self._client
        async for tentative in AsyncRetrying(
            stop=stop_after_attempt(1 + self.parametres.relances_max),
            wait=wait_exponential(multiplier=1, min=1, max=4),
            retry=retry_if_exception(_est_erreur_relancable),
            sleep=self.attendre,
            reraise=True,
        ):
            with tentative:
                await self._respecter_intervalle(urlsplit(url).hostname or "")
                async with self._semaphore:
                    reponse = await client.get(url)
                if reponse.status_code in (502, 503, 504):
                    reponse.raise_for_status()
                return reponse
        raise AssertionError("inatteignable")  # pragma: no cover

    async def obtenir(
        self, url: str, *, sans_verification: bool = False
    ) -> tuple[httpx.Response, list[str]]:
        """GET en suivant les redirections une à une (chaque saut est contrôlé)."""
        redirections: list[str] = []
        url_courante = url
        for _ in range(REDIRECTIONS_MAX + 1):
            self.verifier_retrait(url_courante)
            reponse = await self._get(url_courante, sans_verification)
            if reponse.is_redirect and "location" in reponse.headers:
                redirections.append(url_courante)
                url_courante = urljoin(url_courante, reponse.headers["location"])
                continue
            return reponse, redirections
        raise httpx.TooManyRedirects(f"plus de {REDIRECTIONS_MAX} redirections", request=None)

    async def _charger_robots(
        self, origine: str, sans_verification: bool
    ) -> RobotFileParser | None:
        try:
            reponse, _ = await self.obtenir(
                f"{origine}/robots.txt", sans_verification=sans_verification
            )
        except UrlExclue:
            raise
        except httpx.HTTPError as erreur:
            if est_erreur_certificat(erreur) and not sans_verification:
                raise
            return None
        if reponse.status_code >= 500:
            return None
        analyseur = RobotFileParser()
        analyseur.parse([] if reponse.status_code >= 400 else reponse.text.splitlines())
        return analyseur

    async def autorise_par_robots(self, url: str, sans_verification: bool = False) -> bool:
        """robots.txt (RFC 9309) : 4xx → tout est permis ; 5xx ou injoignable → rien ne l'est."""
        morceaux = urlsplit(url)
        origine = f"{morceaux.scheme}://{morceaux.netloc}"
        if origine not in self._robots:
            self._robots[origine] = await self._charger_robots(origine, sans_verification)
            if self._robots[origine] is None:
                self.robots_injoignables.add(origine)
        analyseur = self._robots[origine]
        return analyseur is not None and analyseur.can_fetch(JETON_ROBOTS, url)


def _url_absolue(base: str, cible: str | None) -> str | None:
    if not cible:
        return None
    cible = cible.strip()
    if cible.startswith(("data:", "javascript:", "mailto:", "tel:", "#", "blob:")):
        return None
    url = urljoin(base, cible)
    return url if url.startswith(("http://", "https://")) else None


def extraire_ressources(
    html: str, url_page: str, domaine_organisation: str
) -> tuple[list[Ressource], list[tuple[str, str]]]:
    """Extrait les ressources chargées par une page et ses liens internes (url, texte)."""
    arbre = LexborHTMLParser(html)
    base_org = domaine_de_base(domaine_organisation)
    hote_page = urlsplit(url_page).hostname or ""
    ressources: list[Ressource] = []
    vues: set[tuple[str, str]] = set()

    def ajouter(
        type_ressource: TypeRessource, url: str | None, origine: OrigineRessource = "balise"
    ) -> None:
        if url is None:
            return
        if url.startswith("//"):
            url = "https:" + url
        hote = (urlsplit(url).hostname or "").lower()
        if not hote or (type_ressource, url) in vues:
            return
        vues.add((type_ressource, url))
        tierce = domaine_de_base(hote) not in (base_org, domaine_de_base(hote_page))
        ressources.append(
            Ressource(
                type=type_ressource,
                url=url[:500],
                domaine=hote,
                tierce=tierce,
                origine=origine,
            )
        )

    for noeud in arbre.css("script"):
        src = noeud.attributes.get("src")
        type_script = (noeud.attributes.get("type") or "").lower().strip()
        if src:
            ajouter("script", _url_absolue(url_page, src))
        elif type_script in TYPES_SCRIPT_JS:
            for trouve in MOTIF_URL_JS.findall(noeud.text() or ""):
                ajouter("script", _url_absolue(url_page, trouve), "script_en_ligne")

    for noeud in arbre.css("link[href]"):
        rel = (noeud.attributes.get("rel") or "").lower()
        href = _url_absolue(url_page, noeud.attributes.get("href"))
        if href is None:
            continue
        if "stylesheet" in rel:
            ajouter("feuille_style", href)
        elif (noeud.attributes.get("as") or "") == "font" or href.lower().split("?")[0].endswith(
            EXTENSIONS_POLICES
        ):
            ajouter("police", href)
        elif "preload" in rel or "modulepreload" in rel:
            type_precharge = (noeud.attributes.get("as") or "").lower()
            ajouter("script" if type_precharge == "script" else "autre", href)

    for selecteur, type_ressource in (
        ("iframe", "iframe"),
        ("embed", "iframe"),
        ("img", "image"),
        ("video", "media"),
        ("audio", "media"),
        ("source", "media"),
    ):
        for noeud in arbre.css(selecteur):
            attribut = noeud.attributes.get("src") or noeud.attributes.get("data-src")
            ajouter(type_ressource, _url_absolue(url_page, attribut))  # type: ignore[arg-type]
    for noeud in arbre.css("object[data]"):
        ajouter("iframe", _url_absolue(url_page, noeud.attributes.get("data")))

    textes_css = [n.text() or "" for n in arbre.css("style")]
    textes_css += [n.attributes.get("style") or "" for n in arbre.css("[style]")]
    for texte in textes_css:
        for trouve in MOTIF_IMPORT_CSS.findall(texte):
            ajouter("feuille_style", _url_absolue(url_page, trouve), "css")
        for trouve in MOTIF_URL_CSS.findall(texte):
            url = _url_absolue(url_page, trouve)
            est_police = url is not None and url.lower().split("?")[0].endswith(EXTENSIONS_POLICES)
            ajouter("police" if est_police else "image", url, "css")

    liens: list[tuple[str, str]] = []
    for noeud in arbre.css("a[href]"):
        url = _url_absolue(url_page, noeud.attributes.get("href"))
        if url is None:
            continue
        hote = urlsplit(url).hostname or ""
        if domaine_de_base(hote) in (base_org, domaine_de_base(hote_page)):
            liens.append((url.split("#")[0], (noeud.text() or "").strip()))
    return ressources, liens


def choisir_pages_internes(
    liens: list[tuple[str, str]], deja_vues: set[str], nombre_max: int
) -> list[str]:
    """Sélectionne les pages internes pertinentes (mentions légales, contact…)."""
    choisies: list[str] = []
    for motif in MOTIFS_PAGES_INTERNES:
        for url, texte in liens:
            if len(choisies) >= nombre_max:
                return choisies
            if url in deja_vues or url in choisies:
                continue
            if motif.search(texte) or motif.search(urlsplit(url).path):
                choisies.append(url)
                break
    return choisies


def _noms_cookies(reponse: httpx.Response) -> list[str]:
    noms: list[str] = []
    for valeur in reponse.headers.get_list("set-cookie"):
        nom = valeur.split("=", 1)[0].strip()
        if nom:
            noms.append(nom)
    return noms


def _noter_refus_robots(donnees: DonneesHttp, client: ClientWebPoli, url: str) -> None:
    morceaux = urlsplit(url)
    if f"{morceaux.scheme}://{morceaux.netloc}" in client.robots_injoignables:
        donnees.erreurs.append(
            f"{url} : robots.txt injoignable, page non analysée (RFC 9309, section 2.3.1.4)"
        )
    else:
        donnees.pages_interdites_robots.append(url)


async def sonder_http(
    url_depart: str, domaine_organisation: str, client: ClientWebPoli
) -> DonneesHttp:
    """Analyse passive d'un site : accueil puis pages internes, dans la limite de 5 pages."""
    donnees = DonneesHttp(url_depart=url_depart)
    candidats = [url_depart]
    hote_depart = urlsplit(url_depart).hostname or domaine_organisation
    if not hote_depart.startswith("www."):
        candidats.append(url_depart.replace(f"//{hote_depart}", f"//www.{hote_depart}", 1))
    candidats.append(f"http://www.{domaine_organisation}/")

    reponse: httpx.Response | None = None
    sans_verification = False
    for candidat in dict.fromkeys(candidats):
        try:
            if not await client.autorise_par_robots(candidat):
                _noter_refus_robots(donnees, client, candidat)
                continue
            reponse, donnees.redirections = await client.obtenir(candidat)
            break
        except UrlExclue as erreur:
            donnees.erreurs.append(str(erreur))
            return donnees
        except httpx.ConnectError as erreur:
            if est_erreur_certificat(erreur):
                donnees.certificat_invalide = True
                sans_verification = True
                try:
                    if not await client.autorise_par_robots(candidat, sans_verification=True):
                        _noter_refus_robots(donnees, client, candidat)
                        continue
                    reponse, donnees.redirections = await client.obtenir(
                        candidat, sans_verification=True
                    )
                    break
                except httpx.HTTPError as erreur_bis:
                    donnees.erreurs.append(f"{candidat} : {erreur_bis}")
                    continue
            donnees.erreurs.append(f"{candidat} : {erreur}")
        except httpx.HTTPError as erreur:
            donnees.erreurs.append(f"{candidat} : {type(erreur).__name__} {erreur}")

    if reponse is None:
        return donnees

    url_finale = str(reponse.url)
    donnees.url_finale = url_finale
    donnees.hote_final = reponse.url.host
    donnees.en_tetes = {
        cle.lower(): valeur[:LONGUEUR_EN_TETE_MAX]
        for cle, valeur in reponse.headers.items()
        if cle.lower() != "set-cookie"
    }
    pages_vues: set[str] = set()
    a_analyser: list[tuple[str, httpx.Response | None]] = [(url_finale, reponse)]
    pages_max = client.parametres.pages_max_par_site

    while a_analyser and len(donnees.pages) < pages_max:
        url, reponse_page = a_analyser.pop(0)
        if url in pages_vues:
            continue
        pages_vues.add(url)
        if reponse_page is None:
            try:
                if not await client.autorise_par_robots(url, sans_verification):
                    _noter_refus_robots(donnees, client, url)
                    continue
                reponse_page, _ = await client.obtenir(url, sans_verification=sans_verification)
            except (UrlExclue, httpx.HTTPError) as erreur:
                donnees.erreurs.append(f"{url} : {type(erreur).__name__} {erreur}")
                continue
            pages_vues.add(str(reponse_page.url))
        type_contenu = reponse_page.headers.get("content-type")
        donnees.pages.append(
            PageAnalysee(
                url=str(reponse_page.url),
                statut=reponse_page.status_code,
                type_contenu=type_contenu,
            )
        )
        donnees.cookies.extend(_noms_cookies(reponse_page))
        if type_contenu is None or "html" not in type_contenu.lower():
            continue
        html = reponse_page.text[:TAILLE_HTML_MAX]
        donnees.html_pages.append(html)
        ressources, liens = extraire_ressources(html, str(reponse_page.url), domaine_organisation)
        connues = {(r.type, r.url) for r in donnees.ressources}
        donnees.ressources.extend(r for r in ressources if (r.type, r.url) not in connues)
        if len(donnees.pages) == 1:
            places = pages_max - 1
            a_analyser.extend(
                (url_interne, None)
                for url_interne in choisir_pages_internes(liens, pages_vues, places)
            )

    donnees.cookies = sorted(set(donnees.cookies))
    return donnees
