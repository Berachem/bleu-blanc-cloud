"""Tests des chiffres clés (« bbcloud stats ») et de l'image PNG de la carte."""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.cli import app
from bleublanccloud.export.carte_png import (
    COULEURS_NOTES,
    DOSSIER_POLICES,
    DonneeDepartement,
    conique_conforme,
    dessiner_carte,
    lire_departements,
)
from bleublanccloud.export.raster import Image, Police, couleur_hex
from bleublanccloud.modeles import Constat, Organisation, ResultatScan
from bleublanccloud.referentiels import referentiels_par_defaut
from bleublanccloud.statistiques import (
    EntreeStatistique,
    calculer_statistiques,
    entrees_observatoire,
    etat_categorie,
    libelle_tranche,
)
from bleublanccloud.stockage.base import Base

DATE = datetime(2026, 10, 11, 3, tzinfo=UTC)


def organisation(slug: str, **champs: object) -> Organisation:
    donnees: dict[str, object] = {
        "slug": slug,
        "nom": f"Commune de {slug.title()}",
        "type": "commune",
        "departement": "33",
        "region": "75",
        "population": 15_000,
        "site_web": f"https://{slug}.example/",
        "source": "test",
    }
    donnees.update(champs)
    return Organisation.model_validate(donnees)


def constat(categorie: str, fournisseur: str | None, niveau: str, cle: str = "x") -> Constat:
    return Constat.model_validate(
        {
            "sonde": "dns",
            "categorie": categorie,
            "cle": cle,
            "valeur": f"{fournisseur or 'inconnu'}.example",
            "fournisseur_id": fournisseur,
            "niveau": niveau,
        }
    )


def souveraine() -> list[Constat]:
    """Hébergement, messagerie et DNS de niveau A : note A, non provisoire."""
    return [
        constat("hebergement", "ovhcloud", "A"),
        constat("messagerie", "ovhcloud", "A"),
        constat("dns", "ovhcloud", "A"),
    ]


def dependante() -> list[Constat]:
    """Messagerie Microsoft (D), hébergement et DNS OVHcloud (A)."""
    return [
        constat("hebergement", "ovhcloud", "A"),
        constat("messagerie", "microsoft", "D"),
        constat("dns", "ovhcloud", "A"),
    ]


def incertaine() -> list[Constat]:
    """Hébergement et messagerie non identifiés (50 % du poids inconnu) : note provisoire."""
    return [
        constat("hebergement", None, "inconnu"),
        constat("messagerie", None, "inconnu"),
        constat("dns", "ovhcloud", "A"),
    ]


def entree(org: Organisation, constats: list[Constat]) -> EntreeStatistique:
    return EntreeStatistique(org, calculer_score(constats, ["dns", "http"]), constats, DATE)


@pytest.fixture
def entrees() -> list[EntreeStatistique]:
    return [
        entree(organisation("bordeaux", population=260_000), souveraine()),
        entree(organisation("merignac", population=120_000), dependante()),
        entree(organisation("pessac", population=65_000), incertaine()),
        entree(
            organisation("lyon", population=520_000, departement="69", region="84"), incertaine()
        ),
        entree(
            organisation("gironde", type="departement", population=None, code_commune=None),
            souveraine(),
        ),
    ]


def test_repartition_des_notes_et_part_provisoire(entrees: list[EntreeStatistique]) -> None:
    stats = calculer_statistiques(entrees, referentiels_par_defaut())
    assert stats.ensemble.compte.nombre == 5
    assert stats.ensemble.compte.provisoires == 2
    assert stats.ensemble.compte.part_provisoire == 40.0
    assert sum(c.nombre for c in stats.notes.values()) == 5
    assert stats.notes["A"].nombre == 4  # 2 souveraines + 2 incertaines (DNS seul évalué : A)
    assert stats.notes["A"].provisoires == 2
    assert stats.notes["A"].part_provisoire == 50.0
    assert stats.notes["B"].nombre == 1  # messagerie D : 75/100
    assert stats.notes["B"].provisoires == 0
    assert stats.premier_scan == stats.dernier_scan == DATE


def test_niveaux_par_categorie(entrees: list[EntreeStatistique]) -> None:
    stats = calculer_statistiques(entrees, referentiels_par_defaut())
    messagerie = stats.niveaux["messagerie"]
    assert messagerie["A"].nombre == 2
    assert messagerie["D"].nombre == 1
    assert messagerie["inconnu"].nombre == 2
    assert messagerie["inconnu"].part_provisoire == 100.0
    assert stats.niveaux["dns"]["A"].nombre == 5
    assert stats.niveaux["hebergement"]["A"].nombre == 3


def test_etat_categorie_sans_objet_et_indisponible() -> None:
    score = calculer_score([constat("hebergement", "ovhcloud", "A")], ["dns"])
    assert etat_categorie(score, "hebergement") == "A"
    assert etat_categorie(score, "messagerie") == "sans_objet"  # aucun MX
    assert etat_categorie(score, "dns") == "indisponible"  # aucun serveur NS observé


def test_fournisseurs_les_plus_presents(entrees: list[EntreeStatistique]) -> None:
    stats = calculer_statistiques(entrees, referentiels_par_defaut())
    messagerie = {f.fournisseur_id: f for f in stats.fournisseurs["messagerie"]}
    assert messagerie["ovhcloud"].compte.nombre == 2
    assert messagerie["microsoft"].compte.nombre == 1
    assert messagerie["microsoft"].niveau == "D"
    assert messagerie["microsoft"].nom.startswith("Microsoft")
    toutes = stats.fournisseurs["toutes"]
    assert toutes[0].fournisseur_id == "ovhcloud"
    assert toutes[0].compte.nombre == 5  # une fois par organisation, malgré 3 constats
    assert toutes[0].compte.provisoires == 2


def test_moyennes_par_region_et_tranche(entrees: list[EntreeStatistique]) -> None:
    stats = calculer_statistiques(
        entrees, referentiels_par_defaut(), noms_regions={"75": "Nouvelle-Aquitaine"}
    )
    regions = {g.code: g for g in stats.regions}
    assert regions["75"].libelle == "Nouvelle-Aquitaine"
    assert regions["75"].moyenne.compte.nombre == 4
    assert regions["75"].moyenne.compte.provisoires == 1
    assert regions["84"].libelle == "84"  # nom inconnu : code affiché
    tranches = {g.libelle: g for g in stats.tranches_population}
    # Les départements (sans population) restent hors des tranches
    assert sum(g.moyenne.compte.nombre for g in stats.tranches_population) == 4
    assert tranches["50 000 à 100 000 hab."].moyenne.compte.provisoires == 1
    assert tranches["200 000 hab. et plus"].moyenne.compte.nombre == 2
    assert [g.code for g in stats.departements] == ["33", "69"]


def test_grandes_collectivites_notees_a(entrees: list[EntreeStatistique]) -> None:
    stats = calculer_statistiques(entrees, referentiels_par_defaut())
    assert stats.grandes_collectivites.nombre == 3  # Bordeaux, Mérignac, Lyon
    assert stats.grandes_collectivites.provisoires == 1
    noms = [(g.slug, g.provisoire) for g in stats.grandes_collectivites_a]
    assert noms == [("lyon", True), ("bordeaux", False)]  # par population décroissante


def test_libelles_des_tranches() -> None:
    assert libelle_tranche(0, 10_000) == "Moins de 10 000 hab."
    assert libelle_tranche(10_000, 20_000) == "10 000 à 20 000 hab."
    assert libelle_tranche(200_000, None) == "200 000 hab. et plus"


def test_en_dict_serialisable(entrees: list[EntreeStatistique]) -> None:
    donnees = calculer_statistiques(entrees, referentiels_par_defaut()).en_dict()
    texte = json.dumps(donnees, ensure_ascii=False)
    assert donnees["repartition_notes"]["A"]["part_provisoire"] == 50.0
    assert donnees["repartition_notes"]["A"]["part"] == 80.0
    assert donnees["ensemble"]["note_moyenne"] in "ABCDE"
    assert "grandes_collectivites" in texte


def test_entrees_ecartent_les_analyses_sur_demande_et_l_historique() -> None:
    with Base(":memory:") as base:
        commune = base.enregistrer_organisation(organisation("talence"))
        sur_demande = base.enregistrer_organisation(
            organisation("perso", type="sur_demande", departement=None, region=None)
        )
        for org_id, jour, constats in (
            (commune, 1, dependante()),
            (commune, 8, souveraine()),
            (sur_demande, 8, souveraine()),
        ):
            date = datetime(2026, 10, jour, tzinfo=UTC)
            res = ResultatScan(
                domaine="talence.example",
                debut=date,
                fin=date,
                statut="termine",
                sondes_reussies=["dns", "http"],
                constats=constats,
            )
            base.enregistrer_scan(org_id, res, calculer_score(constats), VERSION_METHODO)
        entrees = entrees_observatoire(base)
    assert [e.organisation.slug for e in entrees] == ["talence"]
    assert entrees[0].score.note == "A"  # dernier scan seulement
    assert entrees[0].date_scan.day == 8


# --------------------------------------------------------------------------- #
# Rendu PNG
# --------------------------------------------------------------------------- #


def lire_png(donnees: bytes) -> tuple[int, int, bytes]:
    """Dimensions et pixels RGB d'un PNG écrit par `Image.png` (filtre 0 sur chaque ligne)."""
    assert donnees[:8] == b"\x89PNG\r\n\x1a\n"
    largeur, hauteur = struct.unpack(">II", donnees[16:24])
    position, idat = 8, b""
    while position < len(donnees):
        (taille,) = struct.unpack(">I", donnees[position : position + 4])
        nature = donnees[position + 4 : position + 8]
        if nature == b"IDAT":
            idat += donnees[position + 8 : position + 8 + taille]
        position += 12 + taille
    brut = zlib.decompress(idat)
    pas = largeur * 3 + 1
    pixels = b"".join(brut[i * pas + 1 : (i + 1) * pas] for i in range(hauteur))
    return largeur, hauteur, pixels


def pixel(pixels: bytes, largeur: int, x: int, y: int) -> tuple[int, int, int]:
    i = (y * largeur + x) * 3
    return (pixels[i], pixels[i + 1], pixels[i + 2])


def test_remplissage_et_anticrenelage() -> None:
    image = Image(20, 20, (0, 0, 0))
    image.remplir([[(5, 5), (15.5, 5), (15.5, 15), (5, 15)]], (200, 100, 50))
    largeur, hauteur, pixels = lire_png(image.png())
    assert (largeur, hauteur) == (20, 20)
    assert pixel(pixels, 20, 10, 10) == (200, 100, 50)
    assert pixel(pixels, 20, 2, 2) == (0, 0, 0)
    assert pixel(pixels, 20, 15, 10) == (100, 50, 25)  # demi-pixel couvert


def test_trou_regle_non_nulle() -> None:
    image = Image(30, 30, (0, 0, 0))
    exterieur = [(0, 0), (30, 0), (30, 30), (0, 30)]
    trou = [(10, 10), (10, 20), (20, 20), (20, 10)]  # sens inverse : trou
    image.remplir([exterieur, trou], (255, 255, 255))
    _, _, pixels = lire_png(image.png())
    assert pixel(pixels, 30, 5, 5) == (255, 255, 255)
    assert pixel(pixels, 30, 15, 15) == (0, 0, 0)


def test_texte_luciole() -> None:
    police = Police(DOSSIER_POLICES / "Luciole-Bold.woff2")
    assert police.largeur("Bleu Blanc Cloud", 20) > police.largeur("Bleu", 20) > 0
    image = Image(200, 40, (0, 0, 0))
    largeur = image.texte(police, "Télécom", 24, 100, 30, (255, 255, 255), "centre")
    assert 60 < largeur < 140
    assert any(image.pixels)


def test_projection_conique_ordonne_les_villes() -> None:
    projeter = conique_conforme()
    lille, marseille, brest, strasbourg = (
        projeter(3.06, 50.63),
        projeter(5.37, 43.30),
        projeter(-4.49, 48.39),
        projeter(7.75, 48.58),
    )
    assert lille[1] < marseille[1]  # y vers le bas : le nord en haut
    assert brest[0] < strasbourg[0]


def test_carte_departements_1080() -> None:
    departements = lire_departements()
    assert len(departements) == 101
    donnees = {d.code: DonneeDepartement("A", 0.0) for d in departements}
    donnees["29"] = DonneeDepartement("E", 80.0)  # Finistère : hachuré
    image = dessiner_carte(donnees, 1234, 12.5, DATE, "bleublanccloud.fr")
    largeur, hauteur, pixels = lire_png(image.png())
    assert (largeur, hauteur) == (1080, 1080)
    couleurs = {pixel(pixels, largeur, x, y) for x in range(0, 1080, 3) for y in range(0, 1080, 3)}
    assert COULEURS_NOTES["A"] in couleurs
    assert COULEURS_NOTES["E"] in couleurs
    assert couleur_hex("#002395") in couleurs  # bandeau tricolore


# --------------------------------------------------------------------------- #
# Commande
# --------------------------------------------------------------------------- #


@pytest.fixture
def base_remplie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    with Base(chemin) as base:
        base.enregistrer_territoire("region", "75", "Nouvelle-Aquitaine")
        base.enregistrer_territoire("departement", "33", "Gironde", "75")
        for slug, population, constats in (
            ("bordeaux", 260_000, souveraine()),
            ("merignac", 120_000, dependante()),
            ("pessac", 65_000, incertaine()),
        ):
            org_id = base.enregistrer_organisation(organisation(slug, population=population))
            res = ResultatScan(
                domaine=f"{slug}.example",
                debut=DATE,
                fin=DATE,
                statut="termine",
                sondes_reussies=["dns", "http"],
                constats=constats,
            )
            base.enregistrer_scan(org_id, res, calculer_score(constats), VERSION_METHODO)
    yield tmp_path


def test_cli_stats(base_remplie: Path) -> None:
    sortie_json = base_remplie / "stats.json"
    sortie_png = base_remplie / "carte.png"
    resultat = CliRunner().invoke(
        app, ["stats", "--json", str(sortie_json), "--image", str(sortie_png)]
    )
    assert resultat.exit_code == 0, resultat.output
    assert "Répartition des notes" in resultat.output
    assert "Nouvelle-Aquitaine" in resultat.output
    assert "Provisoires" in resultat.output
    donnees = json.loads(sortie_json.read_text(encoding="utf-8"))
    assert donnees["ensemble"]["nombre"] == 3
    assert donnees["ensemble"]["provisoires"] == 1
    assert donnees["moyennes_par_departement"][0]["libelle"] == "Gironde"
    assert [g["slug"] for g in donnees["grandes_collectivites"]["notees_a"]] == ["bordeaux"]
    assert lire_png(sortie_png.read_bytes())[:2] == (1080, 1080)


def test_cli_stats_base_vide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(tmp_path / "vide.db"))
    resultat = CliRunner().invoke(app, ["stats", "--sans-image"])
    assert resultat.exit_code == 1
    assert "Aucun scan noté" in resultat.output
