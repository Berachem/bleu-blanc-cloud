"""Import des hôpitaux publics (liste sourcée, sans réseau), voir ADR-0006."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from bleublanccloud.cibles.hopitaux import (
    Hopital,
    charger_hopitaux,
    construire_hopitaux,
    slug_hopital,
)
from bleublanccloud.cli import app
from bleublanccloud.stockage.base import Base


def hopital(nom: str, departement: str = "44") -> Hopital:
    return Hopital.model_validate(
        {
            "nom": nom,
            "ville": "Exempleville",
            "departement": departement,
            "site_web": "https://chu.example/",
            "sources": ["https://chu.example/qui-sommes-nous"],
        }
    )


def test_liste_reelle_valide_et_sourcee() -> None:
    hopitaux = charger_hopitaux()
    assert len(hopitaux) >= 30
    assert all(h.sources for h in hopitaux)
    organisations = construire_hopitaux(hopitaux)  # aucun slug en double
    assert len(organisations) == len(hopitaux)
    assert all(o.type == "hopital" and o.site_web for o in organisations)
    assert len({o.site_web for o in organisations}) == len(organisations)


def test_supports_ght_sources_par_acceslibre_et_ars() -> None:
    """Lot GHT : site web relevé sur une fiche publique, statut de support sur la page ARS."""
    supports = [h for h in charger_hopitaux() if h.remarque and "support du GHT" in h.remarque]
    assert len(supports) >= 15
    for h in supports:
        assert h.a_verifier
        hotes = {s.host for s in h.sources}
        assert "acceslibre.beta.gouv.fr" in hotes or "www.sante.fr" in hotes, h.nom
        assert any(hote and hote.endswith(".ars.sante.fr") for hote in hotes), h.nom


@pytest.mark.parametrize(
    ("nom", "attendu"),
    [
        ("CHU de Nantes", "chu-de-nantes"),
        ("Hospices Civils de Lyon", "hospices-civils-de-lyon"),
        ("Centre hospitalier d'Exempleville", "hopital-centre-hospitalier-d-exempleville"),
        ("Hôpital Nord-Ouest d'Exempleville", "hopital-nord-ouest-d-exempleville"),
    ],
)
def test_slug_hopital(nom: str, attendu: str) -> None:
    assert slug_hopital(hopital(nom)) == attendu


def test_slug_en_double_refuse() -> None:
    with pytest.raises(ValueError, match="double"):
        construire_hopitaux([hopital("CHU de Nantes"), hopital("CHU de Nantes")])


def test_departement_invalide_refuse() -> None:
    with pytest.raises(ValueError):
        hopital("CHU de Nulle-Part", departement="999")


def test_apercu_puis_enregistrement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    with Base(chemin) as base:
        base.enregistrer_territoire("departement", "44", "Loire-Atlantique", "52")
    lanceur = CliRunner()

    apercu = lanceur.invoke(app, ["cibles", "hopitaux"])
    assert apercu.exit_code == 0, apercu.output
    assert "Aperçu seulement" in apercu.output
    with Base(chemin) as base:
        assert base.organisations() == []  # rien n'est écrit sans --enregistrer

    resultat = lanceur.invoke(app, ["cibles", "hopitaux", "--enregistrer"])
    assert resultat.exit_code == 0, resultat.output
    with Base(chemin) as base:
        par_slug = {o.organisation.slug: o.organisation for o in base.organisations()}
    assert len(par_slug) == len(charger_hopitaux())
    assert par_slug["chu-de-nantes"].type == "hopital"
    assert par_slug["chu-de-nantes"].region == "52"


def test_migration_007_conserve_organisations_et_scans(tmp_path: Path) -> None:
    import sqlite3

    from bleublanccloud.stockage.base import DOSSIER_MIGRATIONS

    chemin = tmp_path / "ancienne.db"
    connexion = sqlite3.connect(chemin)
    connexion.execute("CREATE TABLE migrations (version TEXT PRIMARY KEY, appliquee_le TEXT)")
    for fichier in sorted(DOSSIER_MIGRATIONS.glob("00[1-6]_*.sql")):
        connexion.executescript(fichier.read_text(encoding="utf-8"))
        connexion.execute("INSERT INTO migrations VALUES (?, '2026-11-01')", (fichier.stem,))
    connexion.execute(
        "INSERT INTO organisations (id, slug, nom, type, source, cree_le) "
        "VALUES (1, 'universite-x', 'Université X', 'universite', 'test', '2026-11-01')"
    )
    connexion.execute(
        "INSERT INTO scans (id, organisation_id, domaine, debut, statut, version_methodo) "
        "VALUES (7, 1, 'univ.example', '2026-11-01T00:00:00', 'termine', '1.2')"
    )
    connexion.commit()
    connexion.close()

    with Base(chemin) as base:  # applique la migration 007
        assert [o.organisation.slug for o in base.organisations()] == ["universite-x"]
        assert base.connexion.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 1
        assert base.connexion.execute("PRAGMA foreign_key_check").fetchall() == []
        base.connexion.execute(
            "INSERT INTO organisations (slug, nom, type, source, cree_le) "
            "VALUES ('chu-x', 'CHU X', 'hopital', 'test', '2026-11-01')"
        )
