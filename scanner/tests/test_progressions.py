"""Tests des progressions de scores sur une période (« bbcloud stats », historique)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.cli import app
from bleublanccloud.modeles import Constat, ResultatScan
from bleublanccloud.statistiques import (
    EntreeStatistique,
    calculer_progressions,
    progressions_observatoire,
)
from bleublanccloud.stockage.base import Base, PointEnregistre
from tests.test_statistiques import dependante, incertaine, organisation, souveraine

FIN = datetime(2026, 11, 5, 9, tzinfo=UTC)


def point(
    jours_avant: int, score: int, provisoire: bool = False, version: str = VERSION_METHODO
) -> PointEnregistre:
    return PointEnregistre(
        scan_id=jours_avant,
        debut=FIN - timedelta(days=jours_avant),
        score=score,
        note="A",
        provisoire=provisoire,
        version_methodo=version,
    )


def entree(slug: str, constats: list[Constat], **champs: object) -> EntreeStatistique:
    return EntreeStatistique(
        organisation(slug, **champs), calculer_score(constats, ["dns", "http"]), constats, FIN
    )


def test_progressions_hausse_baisse_stable_et_ecartees() -> None:
    a = calculer_score(souveraine(), ["dns", "http"]).score_global  # 100, note A
    d = calculer_score(dependante(), ["dns", "http"]).score_global  # messagerie D
    lignes = [
        # Progression : de 55 (C) il y a 40 jours à A aujourd'hui → nouvelle note A
        (entree("monte", souveraine()), [point(40, 55), point(3, a)]),
        # Recul : de A (il y a 35 jours) à la note avec messagerie D
        (entree("baisse", dependante()), [point(35, a), point(10, a)]),
        # Stable
        (entree("stable", souveraine(), type="departement"), [point(60, a), point(31, a)]),
        # Trop récente : aucune analyse avant le début de la période
        (entree("recente", souveraine()), [point(12, 40)]),
        # Note provisoire (avant ou aujourd'hui) : écartée
        (entree("fragile", souveraine()), [point(45, 50, provisoire=True)]),
        (entree("incertaine", incertaine()), [point(45, 50)]),
        # Point d'une autre méthodologie : ignoré, donc trop récente
        (entree("ancienne", souveraine()), [point(45, 20, version="1.0")]),
    ]
    p = calculer_progressions(lignes, jours=30, fin=FIN)
    assert [x.slug for x in p.en_hausse] == ["monte"]
    assert p.en_hausse[0].variation == a - 55
    assert [x.slug for x in p.nouvelles_a] == ["monte"]
    assert [x.slug for x in p.en_baisse] == ["baisse"]
    assert p.en_baisse[0].variation == d - a and p.en_baisse[0].note_perdue
    assert p.stables == 1
    assert (p.trop_recentes, p.provisoires) == (2, 2)
    # La référence est le dernier point AVANT le début de la période (31 jours, pas 60)
    stable = next(x for x in p.comparees if x.slug == "stable")
    assert stable.date_avant == FIN - timedelta(days=31)
    donnees = p.en_dict()
    assert donnees["en_hausse"] == 1 and donnees["notes_gagnees"] == 1
    assert donnees["nouvelles_notees_a"][0]["slug"] == "monte"
    assert donnees["plus_fortes_baisses"][0]["variation"] == d - a


def _scan(base: Base, org_id: int, quand: datetime, constats: list[Constat]) -> None:
    res = ResultatScan(
        domaine="x.example", debut=quand, fin=quand, statut="termine",
        sondes_reussies=["dns", "http"], constats=constats,
    )  # fmt: skip
    base.enregistrer_scan(org_id, res, calculer_score(constats, ["dns", "http"]), VERSION_METHODO)


@pytest.fixture
def base_historique(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    maintenant = datetime.now(UTC)
    with Base(chemin) as base:
        base.enregistrer_territoire("region", "75", "Nouvelle-Aquitaine")
        base.enregistrer_territoire("departement", "33", "Gironde", "75")
        bordeaux = base.enregistrer_organisation(organisation("bordeaux"))
        _scan(base, bordeaux, maintenant - timedelta(days=45), dependante())
        _scan(base, bordeaux, maintenant - timedelta(days=2), souveraine())
        merignac = base.enregistrer_organisation(organisation("merignac"))
        _scan(base, merignac, maintenant - timedelta(days=2), souveraine())
    return tmp_path


def test_progressions_observatoire(base_historique: Path) -> None:
    with Base(base_historique / "base.db") as base:
        p = progressions_observatoire(base, jours=30)
    assert [x.slug for x in p.en_hausse] == ["bordeaux"]
    assert p.trop_recentes == 1


def test_cli_stats_progressions(base_historique: Path) -> None:
    sortie = base_historique / "stats.json"
    resultat = CliRunner().invoke(
        app, ["stats", "--sans-image", "--json", str(sortie), "--jours", "30"]
    )
    assert resultat.exit_code == 0, resultat.output
    assert "Évolution sur les 30 derniers jours" in resultat.output
    assert "1 en progression" in resultat.output
    assert "Commune de Bordeaux" in resultat.output
    donnees = json.loads(sortie.read_text(encoding="utf-8"))
    assert donnees["progressions"]["en_hausse"] == 1
    assert donnees["progressions"]["nouvelles_notees_a"][0]["slug"] == "bordeaux"


def test_cli_stats_sans_historique(base_historique: Path) -> None:
    resultat = CliRunner().invoke(app, ["stats", "--sans-image", "--jours", "90"])
    assert resultat.exit_code == 0, resultat.output
    assert "Pas encore assez d'historique" in resultat.output


@respx.mock
def test_simulation_mail_de_felicitations(
    base_historique: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bordeaux est passée en A il y a 2 jours : la simulation prépare les félicitations."""
    openpyxl = pytest.importorskip("openpyxl")
    from bleublanccloud.cibles.annuaire import URL_EXPORT
    from bleublanccloud.configuration import obtenir_parametres

    respx.get(URL_EXPORT).mock(return_value=httpx.Response(200, json=[]))
    chemin = base_historique / "prospection.xlsx"
    lanceur = CliRunner()
    assert lanceur.invoke(app, ["prospection", "badge", "--vers", str(chemin)]).exit_code == 0
    classeur = openpyxl.load_workbook(chemin)
    feuille = classeur["Communes A"]
    colonnes = {c.value: c.column_letter for c in feuille[1]}
    for rang in range(2, feuille.max_row + 1):
        slug = feuille[f"{colonnes['Slug']}{rang}"].value
        feuille[f"{colonnes['E-mail de contact']}{rang}"] = f"contact@{slug}.example"
        feuille[f"{colonnes['Statut']}{rang}"] = "À contacter"
    classeur.save(chemin)

    monkeypatch.setenv("COURRIEL_ADRESSE", "contact@bbc.example")
    obtenir_parametres.cache_clear()
    resultat = lanceur.invoke(
        app, ["prospection", "envoyer", "--vers", str(chemin), "--simulation"]
    )
    assert resultat.exit_code == 0, resultat.output
    apercus = sorted(p.name for p in (base_historique / "apercus").glob("*.eml"))
    assert apercus == ["bordeaux-felicitations.eml", "merignac-premier.eml"]
    texte = (base_historique / "apercus" / "bordeaux-felicitations.html").read_text()
    assert "vient d'obtenir la note A" in texte
