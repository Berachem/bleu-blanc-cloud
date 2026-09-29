"""Photos des organisations : image Wikidata (P18) → Wikimedia Commons, auto-hébergée.

Le serveur télécharge une vignette (licence libre uniquement) au moment de la mise à jour ;
le site la publie lui-même avec l'auteur et la licence : aucune requête externe côté
visiteur. Les organisations « sur demande » n'ont pas de photo.

Correspondance par code officiel :
- commune : code INSEE (P374), hors communes dissoutes (P576) ;
- département : code INSEE du département (P2586) ;
- région : code INSEE de la région (P2585).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser

from bleublanccloud.modeles import Organisation
from bleublanccloud.stockage.base import Base, PhotoEnregistree

journal = logging.getLogger(__name__)

URL_SPARQL: Final = "https://query.wikidata.org/sparql"
URL_COMMONS: Final = "https://commons.wikimedia.org/w/api.php"
HOTES_IMAGES: Final = frozenset({"upload.wikimedia.org"})
LARGEUR_VIGNETTE: Final = 1280  # taille de vignette standard de Wikimedia
TAILLE_MAX: Final = 5_000_000
LOT_SPARQL: Final = 150
LOT_COMMONS: Final = 50
DELAI_RAFRAICHISSEMENT: Final = timedelta(days=30)
EXTENSIONS: Final = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

PROPRIETES: Final = {"commune": "P374", "departement": "P2586", "region": "P2585"}
MOTIF_CODE: Final = re.compile(r"^[0-9A-Z]{1,5}$")
# Licences libres qui autorisent la réutilisation avec crédit (pas de GFDL seule, pas de NC/ND)
MOTIF_LICENCE: Final = re.compile(
    r"^(?:CC0(?: 1\.0)?|Public domain|PD(?:[- ].*)?|CC BY(?:-SA)? \d(?:\.\d)?(?: [a-z-]+)?)$",
    re.IGNORECASE,
)

Attendre = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class ImageCommons:
    fichier: str
    url_vignette: str
    largeur: int
    hauteur: int
    auteur: str
    licence: str
    url_licence: str | None
    url_source: str


@dataclass
class BilanPhotos:
    trouvees: int = 0
    absentes: int = 0
    refusees: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    inchangees: int = 0


def cle_wikidata(organisation: Organisation) -> tuple[str, str] | None:
    """(propriété Wikidata, code officiel) d'une organisation, ou None."""
    code = {
        "commune": organisation.code_commune,
        "departement": organisation.departement,
        "region": organisation.region,
    }.get(organisation.type)
    if not code or not MOTIF_CODE.match(code):
        return None
    return PROPRIETES[organisation.type], code


def texte_brut(html: str | None, longueur_max: int = 150) -> str:
    """Texte d'un fragment HTML de Commons (balises retirées, espaces normalisés)."""
    if not html:
        return ""
    arbre = LexborHTMLParser(f"<div>{html}</div>")
    arbre.strip_tags(["script", "style", "noscript"])
    texte = arbre.text(separator=" ", strip=True)
    texte = " ".join(texte.split())
    return texte if len(texte) <= longueur_max else texte[: longueur_max - 1] + "…"


def licence_acceptee(nom: str | None) -> bool:
    return nom is not None and MOTIF_LICENCE.match(nom.strip()) is not None


def fichier_depuis_uri(uri: str) -> str:
    """URI Wikidata d'une image (…/Special:FilePath/Vue%20de%20X.jpg) → « File:Vue de X.jpg »."""
    return "File:" + unquote(uri.rsplit("/", 1)[-1]).replace("_", " ")


async def images_wikidata(
    client: httpx.AsyncClient, propriete: str, codes: Sequence[str]
) -> dict[str, tuple[str, str]]:
    """{code: (identifiant Wikidata, fichier Commons)} pour les codes qui ont une image."""
    valeurs = " ".join(f'"{code}"' for code in codes if MOTIF_CODE.match(code))
    if not valeurs:
        return {}
    requete = (
        f"SELECT ?code ?item ?image WHERE {{ VALUES ?code {{ {valeurs} }} "
        f"?item wdt:{propriete} ?code ; wdt:P18 ?image . "
        "FILTER NOT EXISTS { ?item wdt:P576 ?dissolution } }"
    )
    reponse = await client.get(
        URL_SPARQL,
        params={"query": requete},
        headers={"Accept": "application/sparql-results+json"},
    )
    reponse.raise_for_status()
    resultats: dict[str, tuple[str, str]] = {}
    lignes = reponse.json().get("results", {}).get("bindings", [])
    # Plusieurs images possibles : choix déterministe (premier fichier par ordre alphabétique)
    for ligne in sorted(lignes, key=lambda li: li.get("image", {}).get("value", "")):
        code = ligne.get("code", {}).get("value")
        image = ligne.get("image", {}).get("value")
        item = ligne.get("item", {}).get("value", "")
        if code and image and code not in resultats:
            resultats[code] = (item.rsplit("/", 1)[-1], fichier_depuis_uri(image))
    return resultats


def _lire_image(page: dict[str, Any]) -> ImageCommons | str:
    """Métadonnées d'une page de fichier Commons, ou le motif de refus."""
    infos = (page.get("imageinfo") or [{}])[0]
    meta = infos.get("extmetadata") or {}

    def valeur(cle: str) -> str | None:
        element = meta.get(cle)
        return str(element.get("value")) if isinstance(element, dict) else None

    licence = texte_brut(valeur("LicenseShortName"), 60)
    if not licence_acceptee(licence):
        return f"licence non libre ou inconnue ({licence or 'absente'})"
    url = infos.get("thumburl") or infos.get("url")
    if not url or not infos.get("descriptionurl"):
        return "vignette indisponible"
    auteur = texte_brut(valeur("Artist")) or texte_brut(valeur("Credit")) or "auteur non renseigné"
    return ImageCommons(
        fichier=str(page.get("title")),
        url_vignette=str(url),
        largeur=int(infos.get("thumbwidth") or infos.get("width") or 0),
        hauteur=int(infos.get("thumbheight") or infos.get("height") or 0),
        auteur=auteur,
        licence=licence,
        url_licence=valeur("LicenseUrl"),
        url_source=str(infos["descriptionurl"]),
    )


async def metadonnees_commons(
    client: httpx.AsyncClient, fichiers: Sequence[str]
) -> dict[str, ImageCommons | str]:
    """{fichier demandé: image ou motif de refus}, par lots de 50."""
    resultats: dict[str, ImageCommons | str] = {}
    for debut in range(0, len(fichiers), LOT_COMMONS):
        lot = list(fichiers[debut : debut + LOT_COMMONS])
        reponse = await client.get(
            URL_COMMONS,
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": str(LARGEUR_VIGNETTE),
                "iiextmetadatafilter": "Artist|Credit|LicenseShortName|LicenseUrl",
                "titles": "|".join(lot),
            },
        )
        reponse.raise_for_status()
        requete = reponse.json().get("query", {})
        renommages = {n["from"]: n["to"] for n in requete.get("normalized", [])}
        pages = {p.get("title"): p for p in requete.get("pages", []) if isinstance(p, dict)}
        for fichier in lot:
            page = pages.get(renommages.get(fichier, fichier))
            if page is None or page.get("missing"):
                resultats[fichier] = "fichier introuvable sur Commons"
            else:
                resultats[fichier] = _lire_image(page)
    return resultats


async def telecharger(client: httpx.AsyncClient, url: str, dossier: Path, fichier: str) -> str:
    """Télécharge la vignette (hôte Wikimedia uniquement, taille bornée) ; retourne le nom local."""
    morceaux = urlsplit(url)
    if morceaux.scheme != "https" or morceaux.hostname not in HOTES_IMAGES:
        raise ValueError(f"hôte d'image non autorisé : {morceaux.hostname}")
    base_nom = hashlib.sha256(fichier.encode()).hexdigest()[:20]
    async with client.stream("GET", url) as reponse:
        reponse.raise_for_status()
        type_contenu = reponse.headers.get("content-type", "").split(";")[0].strip()
        extension = EXTENSIONS.get(type_contenu)
        if extension is None:
            raise ValueError(f"type de fichier refusé : {type_contenu or 'inconnu'}")
        contenu = bytearray()
        async for morceau in reponse.aiter_bytes():
            contenu.extend(morceau)
            if len(contenu) > TAILLE_MAX:
                raise ValueError("image trop volumineuse")
    dossier.mkdir(parents=True, exist_ok=True)
    nom = base_nom + extension
    temporaire = dossier / f".{nom}.tmp"
    temporaire.write_bytes(bytes(contenu))
    temporaire.replace(dossier / nom)
    return nom


def _a_rafraichir(
    photo: PhotoEnregistree | None, dossier: Path, maintenant: datetime, forcer: bool
) -> bool:
    if forcer or photo is None or photo.statut == "erreur":
        return True
    if photo.statut == "ok" and not (photo.chemin and (dossier / photo.chemin).exists()):
        return True
    return photo.maj_le < maintenant - DELAI_RAFRAICHISSEMENT


async def mettre_a_jour_photos(
    base: Base,
    dossier: Path,
    client: httpx.AsyncClient,
    maintenant: datetime,
    *,
    forcer: bool = False,
    limite: int | None = None,
    intervalle_s: float = 1.0,
    attendre: Attendre = asyncio.sleep,
) -> BilanPhotos:
    """Cherche, vérifie (licence) et télécharge les photos manquantes ou anciennes."""
    bilan = BilanPhotos()
    a_traiter: dict[str, dict[str, int]] = {}  # propriété → {code: organisation_id}
    for enregistree in base.organisations():
        cle = cle_wikidata(enregistree.organisation)
        if cle is None:
            continue
        if not _a_rafraichir(base.photo(enregistree.id), dossier, maintenant, forcer):
            bilan.inchangees += 1
            continue
        if limite is not None and sum(len(v) for v in a_traiter.values()) >= limite:
            break
        a_traiter.setdefault(cle[0], {})[cle[1]] = enregistree.id

    for propriete, par_code in a_traiter.items():
        codes = sorted(par_code)
        trouvees: dict[str, tuple[str, str]] = {}
        for debut in range(0, len(codes), LOT_SPARQL):
            trouvees |= await images_wikidata(client, propriete, codes[debut : debut + LOT_SPARQL])
            await attendre(intervalle_s)
        metadonnees = await metadonnees_commons(client, sorted({f for _, f in trouvees.values()}))

        for code, organisation_id in par_code.items():
            photo = PhotoEnregistree(organisation_id=organisation_id, statut="absente",
                                     maj_le=maintenant)  # fmt: skip
            if code in trouvees:
                photo.wikidata, photo.fichier = trouvees[code]
                image = metadonnees.get(photo.fichier, "métadonnées indisponibles")
                if isinstance(image, str):
                    photo.statut, photo.motif = "refusee", image
                    bilan.refusees.append(f"{photo.fichier} : {image}")
                else:
                    try:
                        photo.chemin = await telecharger(
                            client, image.url_vignette, dossier, image.fichier
                        )
                    except (httpx.HTTPError, ValueError, OSError) as erreur:
                        photo.statut, photo.motif = "erreur", str(erreur) or type(erreur).__name__
                        bilan.erreurs.append(f"{image.fichier} : {photo.motif}")
                    else:
                        photo.statut = "ok"
                        photo.auteur, photo.licence = image.auteur, image.licence
                        photo.url_licence, photo.url_source = image.url_licence, image.url_source
                        photo.largeur, photo.hauteur = image.largeur, image.hauteur
                        bilan.trouvees += 1
                    await attendre(intervalle_s)
            else:
                bilan.absentes += 1
            base.enregistrer_photo(photo)
    return bilan
