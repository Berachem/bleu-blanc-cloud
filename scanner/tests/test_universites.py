"""Import des universités publiques (données simulées, sans réseau), voir ADR-0006."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bleublanccloud.cibles.universites import (
    URL_EXPORT,
    code_departement,
    construire_universites,
)
from bleublanccloud.cli import app
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base

ENREGISTREMENTS = [
    {
        "uo_lib": "Université de Exempleville",
        "type_d_etablissement": ["Université"],
        "secteur_d_etablissement": "public",
        "url": "www.univ-exempleville.example",
        "dep_id": "D075",
    },
    {
        # Libellés de colonnes « humains » : lus aussi (comparaison sans accents ni casse)
        "Libellé": "Université Fictive Sud",
        "Type d'établissement": "Université",
        "Secteur d'établissement": "Public",
        "URL": "https://univ-sud.example/",
        "dep_id": "D02A",
    },
    {
        "uo_lib": "Université Catholique Fictive",
        "type_d_etablissement": "Université",
        "secteur_d_etablissement": "privé",
        "url": "https://ucf.example",
    },
    {
        "uo_lib": "École Fictive d'Ingénieurs",
        "type_d_etablissement": "École d'ingénieurs",
        "secteur_d_etablissement": "public",
    },
    {  # doublon
        "uo_lib": "Université de Exempleville",
        "type_d_etablissement": "Université",
        "secteur_d_etablissement": "public",
    },
]


def test_seules_les_universites_publiques_sont_retenues() -> None:
    universites = construire_universites(ENREGISTREMENTS)
    assert [(u.slug, u.departement, u.site_web) for u in universites] == [
        ("universite-de-exempleville", "75", "https://www.univ-exempleville.example"),
        ("universite-fictive-sud", "2A", "https://univ-sud.example/"),
    ]
    assert all(u.type == "universite" for u in universites)


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [("D075", "75"), ("075", "75"), ("D02A", "2A"), ("2B", "2B"), ("971", "971"), ("", None)],
)
def test_code_departement(valeur: str, attendu: str | None) -> None:
    assert code_departement(valeur) == attendu


def test_renater_dans_le_referentiel(referentiels: Referentiels) -> None:
    renater = referentiels.fournisseurs["renater"]
    assert 2200 in renater.asn
    assert renater.pays_siege == "FR" and not renater.soumis_cloud_act


@respx.mock
def test_apercu_puis_enregistrement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    with Base(chemin) as base:
        base.enregistrer_territoire("departement", "75", "Paris", "11")
    respx.get(URL_EXPORT).mock(return_value=httpx.Response(200, json=ENREGISTREMENTS))
    lanceur = CliRunner()

    apercu = lanceur.invoke(app, ["cibles", "universites"])
    assert apercu.exit_code == 0, apercu.output
    assert "Aperçu seulement" in apercu.output
    with Base(chemin) as base:
        assert base.organisations() == []  # rien n'est écrit sans --enregistrer

    resultat = lanceur.invoke(app, ["cibles", "universites", "--enregistrer"])
    assert resultat.exit_code == 0, resultat.output
    with Base(chemin) as base:
        par_slug = {o.organisation.slug: o.organisation for o in base.organisations()}
    assert set(par_slug) == {"universite-de-exempleville", "universite-fictive-sud"}
    assert par_slug["universite-de-exempleville"].region == "11"
    assert par_slug["universite-de-exempleville"].type == "universite"


@respx.mock
def test_aucune_universite_reconnue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(tmp_path / "base.db"))
    respx.get(URL_EXPORT).mock(
        return_value=httpx.Response(200, json=[{"champ_inattendu": "x", "autre": "y"}])
    )
    resultat = CliRunner().invoke(app, ["cibles", "universites"])
    assert resultat.exit_code == 1
    assert "champ_inattendu" in resultat.output  # aide à corriger les noms de champs


def test_migration_006_conserve_organisations_et_scans(tmp_path: Path) -> None:
    import sqlite3

    from bleublanccloud.stockage.base import DOSSIER_MIGRATIONS

    chemin = tmp_path / "ancienne.db"
    connexion = sqlite3.connect(chemin)
    connexion.execute("CREATE TABLE migrations (version TEXT PRIMARY KEY, appliquee_le TEXT)")
    for fichier in sorted(DOSSIER_MIGRATIONS.glob("00[1-5]_*.sql")):
        connexion.executescript(fichier.read_text(encoding="utf-8"))
        connexion.execute("INSERT INTO migrations VALUES (?, '2026-11-01')", (fichier.stem,))
    connexion.execute(
        "INSERT INTO organisations (id, slug, nom, type, source, cree_le) "
        "VALUES (1, 'nantes-44109', 'Nantes', 'commune', 'test', '2026-11-01')"
    )
    connexion.execute(
        "INSERT INTO scans (id, organisation_id, domaine, debut, statut, version_methodo) "
        "VALUES (7, 1, 'nantes.example', '2026-11-01T00:00:00', 'termine', '1.2')"
    )
    connexion.commit()
    connexion.close()

    with Base(chemin) as base:  # applique la migration 006
        organisations = base.organisations()
        assert [o.organisation.slug for o in organisations] == ["nantes-44109"]
        assert base.connexion.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1
        assert base.connexion.execute("PRAGMA foreign_key_check").fetchall() == []
