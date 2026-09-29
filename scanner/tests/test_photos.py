"""Photos Wikimedia Commons : recherche Wikidata, licence, téléchargement, export (sans réseau)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.export.site_statique import exporter
from bleublanccloud.modeles import Organisation, OrganisationExport
from bleublanccloud.photos import (
    URL_COMMONS,
    URL_SPARQL,
    cle_wikidata,
    fichier_depuis_uri,
    licence_acceptee,
    mettre_a_jour_photos,
    texte_brut,
)
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base
from tests.test_stockage_export import resultat

MAINTENANT = datetime(2026, 9, 29, 12, tzinfo=UTC)
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2000
VIGNETTE = (
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Grenoble.jpg/1280px-Grenoble.jpg"
)


def commune(slug: str, code: str, nom: str = "Ville") -> Organisation:
    return Organisation(slug=slug, nom=nom, type="commune", code_commune=code,
                        site_web=f"https://{slug}.fr/", source="test")  # fmt: skip


def reponse_sparql(lignes: list[tuple[str, str, str]]) -> dict[str, Any]:
    return {
        "head": {"vars": ["code", "item", "image"]},
        "results": {"bindings": [
            {"code": {"type": "literal", "value": code},
             "item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"},
             "image": {"type": "uri",
                       "value": f"http://commons.wikimedia.org/wiki/Special:FilePath/{fichier}"}}
            for code, qid, fichier in lignes
        ]},
    }  # fmt: skip


def page_commons(titre: str, licence: str, artiste: str, url: str = VIGNETTE) -> dict[str, Any]:
    return {
        "pageid": 1, "ns": 6, "title": titre,
        "imageinfo": [{
            "thumburl": url, "thumbwidth": 1280, "thumbheight": 853, "mime": "image/jpeg",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/{titre.replace(' ', '_')}",
            "extmetadata": {
                "Artist": {"value": artiste},
                "LicenseShortName": {"value": licence},
                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
            },
        }],
    }  # fmt: skip


class Wikimedia:
    """Wikidata + Commons + serveur d'images simulés."""

    def __init__(self, routeur: respx.MockRouter) -> None:
        self.sparql: list[tuple[str, str, str]] = []
        self.pages: list[dict[str, Any]] = []
        self.requetes_sparql: list[str] = []
        self.telechargements = 0
        self.type_image = "image/jpeg"
        routeur.get(URL_SPARQL).mock(side_effect=self._sparql)
        routeur.get(URL_COMMONS).mock(side_effect=self._commons)
        routeur.get(url__startswith="https://upload.wikimedia.org/").mock(side_effect=self._image)

    def _sparql(self, requete: httpx.Request) -> httpx.Response:
        self.requetes_sparql.append(requete.url.params["query"])
        return httpx.Response(200, json=reponse_sparql(self.sparql))

    def _commons(self, requete: httpx.Request) -> httpx.Response:
        demandes = requete.url.params["titles"].split("|")
        normalises = [{"from": t, "to": t.replace("_", " ")} for t in demandes if "_" in t]
        pages = [p for p in self.pages if p["title"] in {t.replace("_", " ") for t in demandes}]
        pages += [{"ns": 6, "title": t, "missing": True} for t in demandes
                  if t.replace("_", " ") not in {p["title"] for p in pages}]  # fmt: skip
        return httpx.Response(200, json={"query": {"normalized": normalises, "pages": pages}})

    def _image(self, requete: httpx.Request) -> httpx.Response:
        self.telechargements += 1
        return httpx.Response(200, content=JPEG, headers={"content-type": self.type_image})


@pytest.fixture
def wikimedia() -> Iterator[Wikimedia]:
    with respx.mock(assert_all_called=False) as routeur:
        yield Wikimedia(routeur)


@pytest.fixture
def base() -> Iterator[Base]:
    with Base(":memory:") as b:
        yield b


async def _sans_attente(_: float) -> None:
    return None


async def mettre_a_jour(base: Base, dossier: Path, **options: Any):  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient() as client:
        return await mettre_a_jour_photos(
            base, dossier, client, options.pop("maintenant", MAINTENANT),
            attendre=_sans_attente, **options,
        )  # fmt: skip


# --------------------------------------------------------------------------- #
# Fonctions unitaires
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("licence", "acceptee"),
    [
        ("CC BY-SA 4.0", True), ("CC BY 2.0", True), ("CC BY-SA 3.0 fr", True), ("CC0", True),
        ("Public domain", True), ("CC BY-NC 2.0", False), ("CC BY-ND 4.0", False),
        ("GFDL", False), ("", False), (None, False), ("Copyrighted", False),
    ],
)  # fmt: skip
def test_licences(licence: str | None, acceptee: bool) -> None:
    assert licence_acceptee(licence) is acceptee


def test_texte_brut_retire_le_html() -> None:
    html = '<a href="//commons.wikimedia.org">Jean <b>Dupont</b></a><script>alert(1)</script>'
    assert texte_brut(html) == "Jean Dupont"
    assert "<" not in texte_brut('<span class="x">A &amp; B</span>')
    assert texte_brut("x" * 300).endswith("…")


def test_fichier_depuis_uri() -> None:
    uri = "http://commons.wikimedia.org/wiki/Special:FilePath/Vue%20de%20Grenoble_2019.jpg"
    assert fichier_depuis_uri(uri) == "File:Vue de Grenoble 2019.jpg"


def test_cle_wikidata() -> None:
    assert cle_wikidata(commune("g", "38185")) == ("P374", "38185")
    departement = Organisation(slug="d", nom="Isère", type="departement", departement="38",
                               source="test")  # fmt: skip
    assert cle_wikidata(departement) == ("P2586", "38")
    demande = Organisation(slug="s", nom="x.fr", type="sur_demande", source="demande")
    assert cle_wikidata(demande) is None
    # Code non conforme : jamais interpolé dans la requête SPARQL
    assert cle_wikidata(commune("x", '1" } DELETE')) is None


# --------------------------------------------------------------------------- #
# Mise à jour complète
# --------------------------------------------------------------------------- #


async def test_photo_trouvee_telechargee(wikimedia: Wikimedia, base: Base, tmp_path: Path) -> None:
    org_id = base.enregistrer_organisation(commune("grenoble-38185", "38185", "Grenoble"))
    wikimedia.sparql = [("38185", "Q1289", "Grenoble%20vue.jpg")]
    wikimedia.pages = [page_commons("File:Grenoble vue.jpg", "CC BY-SA 4.0",
                                    '<a href="x">Jean Dupont</a>')]  # fmt: skip

    bilan = await mettre_a_jour(base, tmp_path / "photos")
    assert (bilan.trouvees, bilan.absentes) == (1, 0)
    photo = base.photo(org_id)
    assert photo is not None and photo.statut == "ok"
    assert (photo.wikidata, photo.auteur, photo.licence) == ("Q1289", "Jean Dupont", "CC BY-SA 4.0")
    assert (tmp_path / "photos" / str(photo.chemin)).read_bytes() == JPEG
    assert "wdt:P374 ?code" in wikimedia.requetes_sparql[0]
    assert "wdt:P576" in wikimedia.requetes_sparql[0]  # communes dissoutes exclues

    # Deuxième passage : photo récente, aucune requête
    bilan = await mettre_a_jour(base, tmp_path / "photos")
    assert bilan.inchangees == 1 and len(wikimedia.requetes_sparql) == 1
    # Après 30 jours : revérification
    await mettre_a_jour(base, tmp_path / "photos", maintenant=MAINTENANT + timedelta(days=31))
    assert len(wikimedia.requetes_sparql) == 2


async def test_sans_photo_et_licence_refusee(
    wikimedia: Wikimedia, base: Base, tmp_path: Path
) -> None:
    sans = base.enregistrer_organisation(commune("a-00001", "00001"))
    non_libre = base.enregistrer_organisation(commune("b-00002", "00002"))
    wikimedia.sparql = [("00002", "Q2", "Photo.jpg")]
    wikimedia.pages = [page_commons("File:Photo.jpg", "CC BY-NC 2.0", "X")]
    bilan = await mettre_a_jour(base, tmp_path / "photos")
    assert bilan.absentes == 1 and len(bilan.refusees) == 1 and wikimedia.telechargements == 0
    assert base.photo(sans).statut == "absente"  # type: ignore[union-attr]
    refusee = base.photo(non_libre)
    assert refusee is not None and refusee.statut == "refusee" and "licence" in str(refusee.motif)


async def test_type_de_fichier_refuse_puis_retente(
    wikimedia: Wikimedia, base: Base, tmp_path: Path
) -> None:
    org_id = base.enregistrer_organisation(commune("g-38185", "38185"))
    wikimedia.sparql = [("38185", "Q1", "G.jpg")]
    wikimedia.pages = [page_commons("File:G.jpg", "CC0", "X")]
    wikimedia.type_image = "text/html"
    bilan = await mettre_a_jour(base, tmp_path / "photos")
    assert bilan.erreurs and base.photo(org_id).statut == "erreur"  # type: ignore[union-attr]
    # Une erreur est retentée au passage suivant, sans attendre 30 jours
    wikimedia.type_image = "image/jpeg"
    await mettre_a_jour(base, tmp_path / "photos")
    assert base.photo(org_id).statut == "ok"  # type: ignore[union-attr]


async def test_hote_d_image_non_autorise(wikimedia: Wikimedia, base: Base, tmp_path: Path) -> None:
    org_id = base.enregistrer_organisation(commune("g-38185", "38185"))
    wikimedia.sparql = [("38185", "Q1", "G.jpg")]
    wikimedia.pages = [page_commons("File:G.jpg", "CC0", "X", url="https://exemple.fr/g.jpg")]
    await mettre_a_jour(base, tmp_path / "photos")
    photo = base.photo(org_id)
    assert photo is not None and photo.statut == "erreur" and "non autorisé" in str(photo.motif)


async def test_sur_demande_ignoree(wikimedia: Wikimedia, base: Base, tmp_path: Path) -> None:
    base.enregistrer_organisation(
        Organisation(slug="sur-demande-x-fr", nom="x.fr", type="sur_demande", source="demande")
    )
    bilan = await mettre_a_jour(base, tmp_path / "photos")
    assert wikimedia.requetes_sparql == [] and bilan.trouvees == 0


# --------------------------------------------------------------------------- #
# Export : photo copiée à côté des données, crédit dans le JSON
# --------------------------------------------------------------------------- #


async def test_export_publie_la_photo(
    wikimedia: Wikimedia, base: Base, referentiels: Referentiels, tmp_path: Path
) -> None:
    org_id = base.enregistrer_organisation(commune("exempleville-99999", "99999", "Exempleville"))
    res = resultat()
    base.enregistrer_scan(org_id, res, calculer_score(res.constats), VERSION_METHODO)
    wikimedia.sparql = [("99999", "Q9", "Exempleville.jpg")]
    wikimedia.pages = [page_commons("File:Exempleville.jpg", "CC BY 4.0", "Marie Curie")]
    await mettre_a_jour(base, tmp_path / "photos")

    sortie = tmp_path / "donnees"
    exporter(base, referentiels, sortie, dossier_photos=tmp_path / "photos")
    fiche = OrganisationExport.model_validate_json(
        (sortie / "organisations" / "exempleville-99999.json").read_text()
    )
    assert fiche.photo is not None
    assert fiche.photo.url == "/donnees/photos/exempleville-99999.jpg"
    assert (fiche.photo.auteur, fiche.photo.licence) == ("Marie Curie", "CC BY 4.0")
    assert fiche.photo.url_source.startswith("https://commons.wikimedia.org/wiki/")
    assert (sortie / "photos" / "exempleville-99999.jpg").read_bytes() == JPEG
    # Aucune URL Wikimedia servie au visiteur : l'image vient du site lui-même
    assert "upload.wikimedia.org" not in json.dumps(fiche.model_dump(mode="json"))

    # Photo disparue du cache ou organisation retirée : fichier publié supprimé
    (tmp_path / "photos" / str(base.photo(org_id).chemin)).unlink()  # type: ignore[union-attr]
    exporter(base, referentiels, sortie, dossier_photos=tmp_path / "photos")
    assert not (sortie / "photos" / "exempleville-99999.jpg").exists()
