"""Adresses fonctionnelles des mairies (communication, numérique, DSI…) pour la prospection.

Les adresses génériques (mairie@, contact@) alimentent des outils de suivi des demandes des
habitants : un message de prospection y reste sans réponse. Ce module cherche, sur le site
officiel de la commune, une adresse de SERVICE (communication@, numerique@, dsi@…).

Garde-fous :
- analyse passive avec le client poli du scanner (User-Agent explicite, robots.txt, une
  requête par seconde et par domaine, retraits respectés), 5 pages au plus par site ;
- seules les adresses du domaine officiel de la commune sont retenues ;
- une adresse n'est retenue que si TOUS les mots de sa partie locale appartiennent à un
  vocabulaire de services : une adresse de personne (prenom.nom@, j.dupont@) est toujours
  écartée, et n'est ni conservée ni journalisée ;
- le résultat ne va que dans le classeur PRIVÉ de prospection (jamais publié ni committé).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser

from bleublanccloud.prospection import ADRESSE_FONCTIONNELLE, CONTACT_NOMINATIF, _openpyxl
from bleublanccloud.sondes.http import (
    TAILLE_HTML_MAX,
    ClientWebPoli,
    UrlExclue,
    domaine_de_base,
    extraire_ressources,
)

# Mots qui désignent un service utile pour le badge, par ordre de préférence : l'équipe web
# ou communication intègre le badge, le numérique ou la DSI ensuite, la presse en dernier.
PRIORITES: tuple[frozenset[str], ...] = (
    frozenset({"web", "webmaster", "webmestre", "internet", "site", "digital"}),
    frozenset({"communication", "com", "dircom", "comm"}),
    frozenset({"numerique", "dsi", "dsin", "dnum", "dsun", "informatique", "si", "transformation"}),
    frozenset({"presse", "media", "medias"}),
)
MOTS_SERVICE = frozenset().union(*PRIORITES)
# Mots neutres tolérés autour d'un mot de service (« service.communication@ », « dsi-ville@ »)
MOTS_NEUTRES = frozenset(
    {
        "service", "services", "direction", "dir", "pole", "mission", "cellule", "equipe",
        "ville", "mairie", "commune", "agglo", "metropole", "systemes", "systeme",
        "information", "informations", "relations", "relation", "contact", "de", "du",
        "des", "la", "le", "et", "en",
    }
)  # fmt: skip
MOTIF_COURRIEL = re.compile(
    r"[a-z0-9][a-z0-9._%+-]*@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,63}", re.IGNORECASE
)
# Adresses écrites pour tromper les robots de spam : « com [at] ville.fr », « (point) »
OBFUSCATIONS = (
    (re.compile(r"\s*[\[(]\s*(?:at|arobase|@)\s*[\])]\s*", re.I), "@"),
    (re.compile(r"\s*[\[(]\s*(?:dot|point)\s*[\])]\s*", re.I), "."),
)
# Pages internes où figurent le plus souvent les adresses des services
MOTIFS_PAGES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(motif, re.IGNORECASE)
    for motif in (
        r"\bcontact",
        r"annuaire|services[\s_-]*municipaux|vos[\s_-]*services",
        r"\bpresse",
        r"mentions[\s_-]*l[ée]gales",
    )
)
PAGES_MAX = 5
AUCUNE = "aucune"  # préfixe écrit dans le classeur quand la recherche n'a rien donné


def _sans_accents(texte: str) -> str:
    table = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    return texte.lower().translate(table)


def adresses_de_la_page(html: str) -> set[str]:
    """Adresses présentes dans les liens mailto et dans le texte de la page."""
    arbre = LexborHTMLParser(html)
    trouvees: set[str] = set()
    for noeud in arbre.css("a[href]"):
        lien = noeud.attributes.get("href") or ""
        if lien.lower().startswith("mailto:"):
            cible = unquote(lien[7:]).split("?")[0]
            trouvees.update(m.group(0) for m in MOTIF_COURRIEL.finditer(cible))
    texte = arbre.body.text(separator=" ") if arbre.body else ""
    for motif, remplacement in OBFUSCATIONS:
        texte = motif.sub(remplacement, texte)
    trouvees.update(m.group(0) for m in MOTIF_COURRIEL.finditer(texte))
    return {a.lower().strip(".") for a in trouvees}


def sur_domaine_officiel(adresse: str, domaine: str) -> bool:
    hote = adresse.rsplit("@", 1)[-1]
    return domaine_de_base(hote) == domaine_de_base(domaine.removeprefix("www."))


def mots(adresse: str) -> list[str]:
    locale = _sans_accents(adresse.split("@", 1)[0])
    return [m for m in re.split(r"[._+\-0-9]+", locale) if m]


def est_fonctionnelle(adresse: str) -> bool:
    """Adresse de service : tous les mots sont connus, et l'un d'eux désigne un service.
    « jean.dupont », « j.dupont-com » ou « mdupont » sont écartées (mot inconnu)."""
    liste = mots(adresse)
    return (
        bool(liste)
        and all(m in MOTS_SERVICE or m in MOTS_NEUTRES for m in liste)
        and any(m in MOTS_SERVICE for m in liste)
    )


def _rang(adresse: str) -> int:
    liste = set(mots(adresse))
    return next((i for i, groupe in enumerate(PRIORITES) if liste & groupe), len(PRIORITES))


def choisir(adresses: Iterable[str], domaine: str) -> str | None:
    """La meilleure adresse fonctionnelle du domaine officiel, ou None."""
    candidates = sorted(
        {a for a in adresses if sur_domaine_officiel(a, domaine) and est_fonctionnelle(a)},
        key=lambda a: (_rang(a), len(a), a),
    )
    return candidates[0] if candidates else None


async def _page(client: ClientWebPoli, url: str) -> httpx.Response | None:
    """Page HTML autorisée par robots.txt, ou None (refus, erreur, autre type de contenu)."""
    try:
        if not await client.autorise_par_robots(url):
            return None
        reponse, _ = await client.obtenir(url)
    except (UrlExclue, httpx.HTTPError):
        return None
    type_contenu = reponse.headers.get("content-type", "")
    if reponse.status_code != 200 or "html" not in type_contenu.lower():
        return None
    if len(reponse.content) > TAILLE_HTML_MAX:
        return None
    return reponse


async def chercher_adresse(domaine: str, client: ClientWebPoli) -> str | None:
    """Accueil du site officiel, puis pages contact, annuaire, presse et mentions légales."""
    accueil = None
    for depart in (f"https://{domaine}/", f"https://www.{domaine}/"):
        accueil = await _page(client, depart)
        if accueil is not None:
            break
    if accueil is None:
        return None
    vues = {str(accueil.url)}
    adresses = adresses_de_la_page(accueil.text)
    _, liens = extraire_ressources(accueil.text, str(accueil.url), domaine)
    suivantes: list[str] = []
    for motif in MOTIFS_PAGES:
        for url, texte in liens:
            if (
                url not in vues
                and url not in suivantes
                and (motif.search(texte) or motif.search(urlsplit(url).path))
            ):
                suivantes.append(url)
                break
    for url in suivantes[: PAGES_MAX - 1]:
        reponse = await _page(client, url)
        vues.add(url)
        if reponse is not None:
            adresses |= adresses_de_la_page(reponse.text)
    return choisir(adresses, domaine)


async def completer_classeur(
    chemin: Path,
    chercher: Callable[[str], Awaitable[str | None]],
    *,
    jour: date | None = None,
    limite: int = 100,
) -> tuple[int, int]:
    """Cherche une adresse fonctionnelle pour les communes sans contact nominatif ni
    recherche antérieure : encore à contacter, ou contactées via l'accueil et pas encore
    relancées (la relance sera alors envoyée au service trouvé). Le classeur est enregistré
    après chaque commune. Renvoie (communes cherchées, adresses trouvées)."""
    from bleublanccloud.prospection import DATE_RELANCE
    from bleublanccloud.prospection_envoi import ClasseurInvalide, colonnes

    jour = jour or date.today()
    classeur = _openpyxl().load_workbook(chemin)
    feuille = classeur["Communes A"]
    numero = colonnes(feuille)
    for intitule in (ADRESSE_FONCTIONNELLE, CONTACT_NOMINATIF, "Domaine"):
        if intitule not in numero:
            raise ClasseurInvalide(
                f"colonne « {intitule} » absente : relancez d'abord "
                "« uv run --with openpyxl bbcloud prospection badge » (le suivi est conservé)."
            )
    cherchees = trouvees = 0
    for rang in range(2, feuille.max_row + 1):
        if cherchees >= limite:
            break

        def valeur(intitule: str, rang: int = rang) -> str:
            return str(feuille.cell(rang, numero[intitule]).value or "").strip()

        a_relancer = valeur("Statut") == "Envoyé" and not valeur(DATE_RELANCE)
        if (
            (valeur("Statut") != "À contacter" and not a_relancer)
            or valeur(CONTACT_NOMINATIF)
            or valeur(ADRESSE_FONCTIONNELLE)
            or not valeur("Domaine")
        ):
            continue
        adresse = await chercher(valeur("Domaine"))
        cherchees += 1
        trouvees += adresse is not None
        feuille.cell(rang, numero[ADRESSE_FONCTIONNELLE]).value = (
            adresse or f"{AUCUNE} ({jour:%d/%m/%Y})"
        )
        classeur.save(chemin)
    return cherchees, trouvees
