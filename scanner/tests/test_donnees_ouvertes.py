"""Tests des données ouvertes (CSV publiés pour data.gouv.fr)."""

from __future__ import annotations

import csv
from pathlib import Path

from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.configuration import RACINE_PROJET
from bleublanccloud.export.demonstration import generer_demonstration, noms_departements_demo
from bleublanccloud.export.donnees_ouvertes import COLONNES_DEPARTEMENTS, COLONNES_ORGANISATIONS
from bleublanccloud.export.site_statique import ecrire_export, exporter
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base
from tests.test_stockage_export import organisation, resultat


def lire(chemin: Path) -> list[dict[str, str]]:
    with chemin.open(encoding="utf-8", newline="") as fichier:
        return list(csv.DictReader(fichier))


def test_csv_des_collectivites(tmp_path: Path, referentiels: Referentiels) -> None:
    with Base(tmp_path / "base.db") as base:
        base.enregistrer_territoire("region", "75", "Nouvelle-Aquitaine")
        base.enregistrer_territoire("departement", "33", "Gironde", "75")
        org_id = base.enregistrer_organisation(organisation("bordeaux-33063"))
        res = resultat()
        base.enregistrer_scan(org_id, res, calculer_score(res.constats), VERSION_METHODO)
        sur_demande = base.enregistrer_organisation(
            organisation("demande-x", type="sur_demande", departement=None, region=None)
        )
        base.enregistrer_scan(sur_demande, res, calculer_score(res.constats), VERSION_METHODO)
        exporter(base, referentiels, tmp_path / "export")

    chemin = tmp_path / "export" / "organisations.csv"
    entete = chemin.read_text(encoding="utf-8").splitlines()[0]
    assert entete == ",".join(nom for nom, _ in COLONNES_ORGANISATIONS)
    (ligne,) = lire(chemin)  # l'analyse sur demande est exclue
    assert ligne["slug"] == "bordeaux-33063"
    assert ligne["code_insee"] == "33063"
    assert (ligne["departement"], ligne["region"]) == ("Gironde", "Nouvelle-Aquitaine")
    assert ligne["note"] in "ABCDE" and ligne["note_provisoire"] in ("true", "false")
    assert ligne["fournisseurs_hebergement"] == "OVHcloud"
    assert "Microsoft" in ligne["fournisseurs_messagerie"]
    assert ligne["services_hors_ue"] == "YouTube | Google Analytics"
    assert ligne["score_messagerie"] == "0"
    assert ligne["url_fiche"].endswith("/organisation/bordeaux-33063/")
    assert ligne["version_methodologie"] == VERSION_METHODO
    texte = chemin.read_text(encoding="utf-8") + (
        tmp_path / "export" / "departements.csv"
    ).read_text(encoding="utf-8")
    assert "@" not in texte  # aucune adresse e-mail

    (departement,) = lire(tmp_path / "export" / "departements.csv")
    assert departement["code"] == "33" and departement["nombre_organisations"] == "1"
    assert sum(int(departement[f"nombre_note_{n}"]) for n in "ABCDE") == 1


def test_pas_de_csv_pour_la_demonstration(tmp_path: Path, referentiels: Referentiels) -> None:
    ecrire_export(
        tmp_path,
        generer_demonstration(referentiels),
        noms_departements_demo(),
        referentiels,
        donnees_demonstration=True,
    )
    assert not (tmp_path / "organisations.csv").exists()


def test_documentation_de_toutes_les_colonnes() -> None:
    documentation = (RACINE_PROJET / "docs" / "donnees-ouvertes.md").read_text(encoding="utf-8")
    for nom, description in (*COLONNES_ORGANISATIONS, *COLONNES_DEPARTEMENTS):
        assert f"| `{nom}` | {description} |" in documentation, nom
