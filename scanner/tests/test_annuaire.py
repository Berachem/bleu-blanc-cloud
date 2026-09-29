"""Tests de l'import de l'annuaire à partir d'une vraie réponse de l'API (Grenoble)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bleublanccloud import configuration
from bleublanccloud.cibles.annuaire import (
    URL_EXPORT,
    analyser_enregistrement,
    analyser_pivot,
    decoder_liste_json,
    extraire_sites,
    filtre_pivot,
    filtrer_services,
    normaliser_code_insee,
    telecharger_services,
)
from bleublanccloud.cibles.communes import URL_GEO, CommuneGeo
from bleublanccloud.cibles.importation import (
    DonneesImport,
    bilan_mairies,
    construire_organisations,
)
from bleublanccloud.cli import app
from tests.conftest import DOSSIER_FIXTURES

CIBLES = DOSSIER_FIXTURES / "cibles"
REPONSE_GRENOBLE = (CIBLES / "annuaire_grenoble.json").read_text()
GRENOBLE = json.loads(REPONSE_GRENOBLE)[0]


def test_enregistrement_reel_grenoble() -> None:
    service = analyser_enregistrement(GRENOBLE)
    assert service.nom == "Mairie - Grenoble"
    assert service.pivots == ["mairie"]
    assert service.code_insee_commune == "38185"
    assert service.site_principal == "https://www.grenoble.fr/"


def test_filtre_like_et_non_egalite() -> None:
    assert filtre_pivot("mairie") == 'pivot like "mairie"'


@respx.mock
async def test_telechargement_utilise_like() -> None:
    route = respx.get(URL_EXPORT).mock(return_value=httpx.Response(200, text=REPONSE_GRENOBLE))
    async with httpx.AsyncClient() as client:
        mairies = await telecharger_services(client, "mairie")
    parametres = route.calls[0].request.url.params
    assert parametres["where"] == 'pivot like "mairie"'
    assert parametres["select"] == "nom,pivot,site_internet,code_insee_commune"
    assert [m.site_principal for m in mairies] == ["https://www.grenoble.fr/"]


def donnees_grenoble() -> DonneesImport:
    communes = json.loads((CIBLES / "geo_communes_grenoble.json").read_text())
    return DonneesImport(
        communes=[CommuneGeo.model_validate(c) for c in communes],
        departements=[],
        regions=[],
        mairies=filtrer_services(json.loads(REPONSE_GRENOBLE), "mairie"),
        conseils_departementaux=[],
        conseils_regionaux=[],
    )


def test_rapprochement_par_code_insee() -> None:
    donnees = donnees_grenoble()
    [organisation] = construire_organisations(donnees, 10_000, ["commune"])
    assert (organisation.nom, organisation.code_commune) == ("Grenoble", "38185")
    assert organisation.site_web == "https://www.grenoble.fr/"
    bilan = bilan_mairies(donnees, 10_000)
    assert (bilan.trouvees, bilan.communes_retenues, bilan.rapprochees, bilan.avec_site_web) == (
        1,
        1,
        1,
        1,
    )


# --------------------------------------------------------------------------- #
# Cas vides ou mal formés
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        (GRENOBLE["site_internet"], ["https://www.grenoble.fr/"]),
        # premier « valeur » non vide
        (
            '[{"libelle": "", "valeur": ""}, {"libelle": "", "valeur": "https://b.fr"}]',
            ["https://b.fr"],
        ),
        # JSON tronqué : repli sur les champs « valeur » lisibles
        ('[{"libelle": "", "valeur": "https://www.grenoble.fr/"', ["https://www.grenoble.fr/"]),
        # sérialisé deux fois
        (json.dumps(GRENOBLE["site_internet"]), ["https://www.grenoble.fr/"]),
        ("www.ville.fr", ["https://www.ville.fr"]),
        ([{"valeur": "ville.fr"}, {"valeur": "ville.fr"}], ["https://ville.fr"]),
        ({"valeur": "https://d.fr"}, ["https://d.fr"]),
        (None, []),
        ("", []),
        ("null", []),
        ("[]", []),
        ("[pas du json", []),
        ('[{"libelle": "Site", "valeur": "Non renseigné"}]', []),
        ('[{"valeur": "mailto:mairie@ville.fr"}]', []),
        (42, []),
    ],
)
def test_extraire_sites_cas_limites(valeur: object, attendu: list[str]) -> None:
    assert extraire_sites(valeur) == attendu


@pytest.mark.parametrize(
    ("valeur", "types", "codes"),
    [
        (GRENOBLE["pivot"], ["mairie"], ["38185"]),
        ('[{"type_service_local": "mairie", "code_insee_commune": ["38185"]', ["mairie"], []),
        ("mairie", ["mairie"], []),
        ({"type_service_local": "cg"}, ["cg"], []),
        ("", [], []),
        (None, [], []),
        ("n'importe quoi !", [], []),
    ],
)
def test_analyser_pivot(valeur: object, types: list[str], codes: list[str]) -> None:
    assert analyser_pivot(valeur) == (types, codes)


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        ("38185", "38185"),
        (" 38185 ", "38185"),
        (1001, "01001"),
        ("2a004", "2A004"),
        (["38185"], "38185"),
        (["", "38185"], "38185"),
        ("", None),
        (None, None),
        ("abc", None),
        (True, None),
    ],
)
def test_normaliser_code_insee(valeur: object, attendu: str | None) -> None:
    assert normaliser_code_insee(valeur) == attendu


def test_decoder_liste_json() -> None:
    assert decoder_liste_json('[{"a": 1}]') == [{"a": 1}]
    assert decoder_liste_json("") == []
    assert decoder_liste_json("[tronqué") is None


def test_code_insee_repris_du_pivot() -> None:
    sans_code = {**GRENOBLE, "code_insee_commune": None}
    assert analyser_enregistrement(sans_code).code_insee_commune == "38185"


def test_filtrer_services_ecarte_les_types_non_confirmes() -> None:
    autre_type = {**GRENOBLE, "pivot": '[{"type_service_local": "mairie_mobile"}]'}
    illisible = {**GRENOBLE, "pivot": ""}
    services = filtrer_services([GRENOBLE, autre_type, illisible, "pas un objet"], "mairie")
    assert len(services) == 1
    assert filtrer_services({"erreur": "inattendue"}, "mairie") == []


def test_mairie_sans_code_insee_comptee_mais_non_rapprochee() -> None:
    donnees = donnees_grenoble()
    donnees.mairies.append(
        analyser_enregistrement(
            {"nom": "Mairie - Inconnue", "pivot": '[{"type_service_local": "mairie"}]'}
        )
    )
    bilan = bilan_mairies(donnees, 10_000)
    assert (bilan.trouvees, bilan.sans_code_insee, bilan.rapprochees) == (2, 1, 1)


# --------------------------------------------------------------------------- #
# Commande « cibles importer »
# --------------------------------------------------------------------------- #


@respx.mock
def test_cli_affiche_le_bilan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(tmp_path / "base.db"))
    configuration.obtenir_parametres.cache_clear()
    respx.get(f"{URL_GEO}/communes").mock(
        return_value=httpx.Response(200, text=(CIBLES / "geo_communes_grenoble.json").read_text())
    )
    respx.get(f"{URL_GEO}/departements").mock(
        return_value=httpx.Response(200, json=[{"nom": "Isère", "code": "38", "codeRegion": "84"}])
    )
    respx.get(f"{URL_GEO}/regions").mock(
        return_value=httpx.Response(200, json=[{"nom": "Auvergne-Rhône-Alpes", "code": "84"}])
    )
    respx.get(URL_EXPORT, params={"where": 'pivot like "mairie"'}).mock(
        return_value=httpx.Response(200, text=REPONSE_GRENOBLE)
    )
    resultat = CliRunner().invoke(app, ["cibles", "importer", "--types", "commune"])
    configuration.obtenir_parametres.cache_clear()
    assert resultat.exit_code == 0, resultat.output
    assert "Mairies trouvées dans l'annuaire : 1" in resultat.output
    assert "Mairies rapprochées d'une commune ≥ 10000 hab. : 1 / 1" in resultat.output
    assert "Mairies avec site web : 1" in resultat.output
