"""Tests de la prospection du badge (classeur privé), sans réseau : réponses simulées."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bleublanccloud.cibles.annuaire import URL_EXPORT
from bleublanccloud.cli import app
from bleublanccloud.modeles import EntreeIndex
from bleublanccloud.prospection import (
    MairieContact,
    analyser_mairies,
    choisir_courriel,
    code_insee_du_slug,
    communes_a_contacter,
    construire_lignes,
    ecrire_classeur,
    extraire_courriels,
    lire_suivi,
    telecharger_mairies,
)
from tests import test_statistiques

# Fixture partagée (base avec trois scans notés, dont Bordeaux en A)
base_statistiques = test_statistiques.base_remplie


def entree(slug: str, note: str = "A", **champs: Any) -> EntreeIndex:
    valeurs: dict[str, Any] = {
        "slug": slug,
        "nom": slug.rsplit("-", 1)[0].capitalize(),
        "type": "commune",
        "departement": "81",
        "departement_nom": "Tarn",
        "population": 20_000,
        "domaine": "exempleville.example",
        "score": 95,
        "note": note,
        "date_scan": datetime(2026, 9, 27, tzinfo=UTC),
    }
    valeurs.update(champs)
    return EntreeIndex(**valeurs)


def enregistrement(nom: str, code: str, courriel: Any) -> dict[str, Any]:
    return {
        "nom": nom,
        "code_insee_commune": code,
        "pivot": json.dumps([{"type_service_local": "mairie", "code_insee_commune": [code]}]),
        "adresse_courriel": courriel,
    }


def test_code_insee_du_slug() -> None:
    assert code_insee_du_slug("albi-81004") == "81004"
    assert code_insee_du_slug("ajaccio-2a004") == "2A004"
    assert code_insee_du_slug("departement-tarn") is None


def test_seules_les_communes_a_non_provisoires_sont_retenues() -> None:
    entrees = [
        entree("petite-81001", population=11_000),
        entree("grande-81002", population=90_000),
        entree("provisoire-81003", note_provisoire=True),
        entree("notee-b-81005", note="B"),
        entree("departement-tarn", type="departement"),
    ]
    assert [e.slug for e in communes_a_contacter(entrees)] == ["grande-81002", "petite-81001"]


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        ("Mairie@Exempleville.example", ["mairie@exempleville.example"]),
        ("a@x.example;b@x.example", ["a@x.example", "b@x.example"]),
        ('["contact@x.example"]', ["contact@x.example"]),
        ([{"valeur": "contact@x.example"}], ["contact@x.example"]),
        ("", []),
        (None, []),
        ("pas une adresse", []),
    ],
)
def test_extraire_courriels(valeur: Any, attendu: list[str]) -> None:
    assert extraire_courriels(valeur) == attendu


def test_mairie_principale_et_domaine_de_la_commune_preferes() -> None:
    mairies = [
        MairieContact("Mairie annexe - Exempleville", "81004", ("annexe@exempleville.example",)),
        MairieContact(
            "Mairie - Exempleville",
            "81004",
            ("ville@autre.example", "contact@exempleville.example"),
        ),
    ]
    assert choisir_courriel(mairies, "www.exempleville.example") == (
        "contact@exempleville.example",
        "Mairie - Exempleville",
    )
    assert choisir_courriel([MairieContact("Mairie", "81004", ())], "x.example") is None


def test_analyser_mairies_ecarte_les_autres_services() -> None:
    autre = enregistrement("CCAS", "81004", "ccas@x.example")
    autre["pivot"] = json.dumps([{"type_service_local": "ccas"}])
    mairies = analyser_mairies(
        [enregistrement("Mairie - Albi", "81004", "contact@albi.example"), autre, "invalide"]
    )
    assert list(mairies) == ["81004"]
    assert mairies["81004"][0].courriels == ("contact@albi.example",)
    assert analyser_mairies({"erreur": True}) == {}


@respx.mock
async def test_telecharger_mairies_demande_le_champ_courriel() -> None:
    route = respx.get(URL_EXPORT).mock(
        return_value=httpx.Response(200, json=[enregistrement("Mairie", "81004", "a@b.example")])
    )
    async with httpx.AsyncClient() as client:
        mairies = await telecharger_mairies(client)
    assert "adresse_courriel" in route.calls[0].request.url.params["select"]
    assert mairies["81004"][0].courriels == ("a@b.example",)


def test_lignes_sans_adresse_inventee_et_suivi_conserve() -> None:
    communes = [entree("albi-81004", domaine="albi.example"), entree("sans-81099")]
    mairies = {"81004": [MairieContact("Mairie - Albi", "81004", ("contact@albi.example",))]}
    suivi = {"sans-81099": {"Statut": "Envoyé"}}
    lignes = construire_lignes(communes, mairies, suivi)
    assert lignes[0].courriel == "contact@albi.example"
    assert lignes[0].source == "Annuaire de l'administration (Mairie - Albi)"
    assert lignes[1].courriel is None
    assert lignes[1].suivi == {"Statut": "Envoyé"}


def test_classeur_relance_sans_perdre_le_suivi(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    chemin = tmp_path / "prive" / "prospection.xlsx"
    communes = [entree("albi-81004", domaine="albi.example"), entree("sans-81099")]
    mairies = {"81004": [MairieContact("Mairie - Albi", "81004", ("contact@albi.example",))]}
    ecrire_classeur(
        chemin,
        construire_lignes(communes, mairies, {}),
        "https://bbc.example",
        jour=date(2026, 11, 4),
    )
    suivi = lire_suivi(chemin)
    assert suivi["albi-81004"]["E-mail de contact"] == "contact@albi.example"
    assert suivi["albi-81004"]["Statut"] == "À contacter"
    assert suivi["sans-81099"] == {"Statut": "Adresse introuvable"}

    # Saisie à la main, puis nouvelle exécution : rien n'est écrasé
    import openpyxl

    classeur = openpyxl.load_workbook(chemin)
    feuille = classeur["Communes A"]
    feuille["L3"] = "mairie@sans.example"
    feuille["N3"] = "Envoyé"
    feuille["N2"] = "Badge intégré"
    feuille["A3"] = datetime(2026, 11, 5)
    classeur.save(chemin)
    lignes = construire_lignes(communes, mairies, lire_suivi(chemin))
    ecrire_classeur(chemin, lignes, "https://bbc.example")
    suivi = lire_suivi(chemin)
    assert suivi["sans-81099"] == {
        "Date mail envoyé": datetime(2026, 11, 5),
        "E-mail de contact": "mairie@sans.example",
        "Source de l'e-mail": "Saisie manuelle",
        "Statut": "Envoyé",
    }
    assert suivi["albi-81004"]["Statut"] == "Badge intégré"
    feuille = openpyxl.load_workbook(chemin)["Communes A"]
    assert feuille["I2"].value == "https://bbc.example/organisation/albi-81004/"
    assert feuille["J2"].value == "https://bbc.example/badge/albi-81004.svg"
    assert feuille["A1"].value == "Date mail envoyé"
    # La date d'envoi passe en vert dès qu'elle est saisie
    regles = [r for zone in feuille.conditional_formatting for r in zone.rules]
    assert any(r.formula == ["LEN($A2)>0"] for r in regles)


def test_ancien_classeur_date_d_envoi_reprise(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    chemin = tmp_path / "ancien.xlsx"
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.title = "Communes A"
    feuille.append(["Commune", "Date d'envoi", "Statut", "Slug"])
    feuille.append(["Albi", datetime(2026, 11, 4), "Envoyé", "albi-81004"])
    classeur.save(chemin)
    assert lire_suivi(chemin)["albi-81004"] == {
        "Date mail envoyé": datetime(2026, 11, 4),
        "Statut": "Envoyé",
    }


@respx.mock
def test_commande_prospection_badge(base_statistiques: Path) -> None:
    pytest.importorskip("openpyxl")
    respx.get(URL_EXPORT).mock(return_value=httpx.Response(200, json=[]))
    chemin = base_statistiques / "prospection.xlsx"
    resultat = CliRunner().invoke(app, ["prospection", "badge", "--vers", str(chemin)])
    assert resultat.exit_code == 0, resultat.output
    assert "1 commune(s) notée(s) A, 0 adresse(s)" in resultat.output
    assert list(lire_suivi(chemin)) == ["bordeaux"]


@respx.mock
def test_commande_prospection_badge_annuaire_injoignable(base_statistiques: Path) -> None:
    respx.get(URL_EXPORT).mock(return_value=httpx.Response(503))
    resultat = CliRunner().invoke(
        app, ["prospection", "badge", "--vers", str(base_statistiques / "p.xlsx")]
    )
    assert resultat.exit_code == 1
    assert not (base_statistiques / "p.xlsx").exists()
