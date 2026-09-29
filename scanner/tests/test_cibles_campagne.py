"""Tests de l'import des cibles et des campagnes (sans réseau)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bleublanccloud import configuration, scan
from bleublanccloud.campagne import lancer_campagne, preparer_cibles
from bleublanccloud.cibles.annuaire import (
    URL_EXPORT,
    ServiceAnnuaire,
    choisir_service_principal,
    extraire_pivots,
    extraire_sites,
)
from bleublanccloud.cibles.communes import URL_GEO
from bleublanccloud.cibles.importation import (
    construire_organisations,
    enregistrer_import,
    slugifier,
    telecharger_donnees,
)
from bleublanccloud.cli import app
from bleublanccloud.configuration import Parametres
from bleublanccloud.modeles import Organisation, Retrait
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import ContexteScan
from bleublanccloud.sondes.ip import ResolveurAsn
from bleublanccloud.stockage.base import Base
from tests.conftest import (
    DOSSIER_FIXTURES,
    LecteurMmdbFactice,
    ResolveurFactice,
    fabriquer_contexte,
    plages_de_test,
)

CIBLES = DOSSIER_FIXTURES / "cibles"
TYPES = ["commune", "departement", "region"]


def lire(nom: str) -> str:
    return (CIBLES / nom).read_text()


def simuler_apis() -> dict[str, respx.Route]:
    routes = {
        "communes": respx.get(f"{URL_GEO}/communes").mock(
            return_value=httpx.Response(200, text=lire("geo_communes.json"))
        ),
        "departements": respx.get(f"{URL_GEO}/departements").mock(
            return_value=httpx.Response(200, text=lire("geo_departements.json"))
        ),
        "regions": respx.get(f"{URL_GEO}/regions").mock(
            return_value=httpx.Response(200, text=lire("geo_regions.json"))
        ),
    }
    for pivot, fichier in (("mairie", "mairies"), ("cg", "cg"), ("cr", "cr")):
        routes[pivot] = respx.get(URL_EXPORT, params={"where": f'pivot="{pivot}"'}).mock(
            return_value=httpx.Response(200, text=lire(f"annuaire_{fichier}.json"))
        )
    return routes


# --------------------------------------------------------------------------- #
# Analyse de l'annuaire
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("valeur", "attendu"),
    [
        ('[{"libelle": "", "valeur": "https://www.a.fr"}]', ["https://www.a.fr"]),
        ([{"valeur": "b.fr"}], ["https://b.fr"]),
        ("https://c.fr", ["https://c.fr"]),
        ({"valeur": "https://d.fr"}, ["https://d.fr"]),
        (None, []),
        ("[pas du json", ["https://[pas du json"]),
        ([{"valeur": ""}], []),
    ],
)
def test_extraire_sites(valeur: object, attendu: list[str]) -> None:
    assert extraire_sites(valeur) == attendu


def test_extraire_pivots() -> None:
    assert extraire_pivots('[{"type_service_local": "mairie"}]') == ["mairie"]
    assert extraire_pivots({"type_service_local": "cg"}) == ["cg"]
    assert extraire_pivots("mairie") == ["mairie"]
    assert extraire_pivots(["cr"]) == ["cr"]
    assert extraire_pivots(None) == []


def test_choisir_service_principal() -> None:
    annexe = ServiceAnnuaire(nom="Mairie annexe", pivots=["mairie"], sites=["https://a.fr"])
    principale = ServiceAnnuaire(nom="Mairie", pivots=["mairie"], sites=["https://m.fr"])
    sans_site = ServiceAnnuaire(nom="Mairie", pivots=["mairie"], sites=[])
    assert choisir_service_principal([annexe, sans_site, principale]) is principale
    assert choisir_service_principal([]) is None


def test_slugifier() -> None:
    assert slugifier("Saint-Étienne-du-Rouvray") == "saint-etienne-du-rouvray"
    assert slugifier("L'Haÿ-les-Roses") == "l-hay-les-roses"


# --------------------------------------------------------------------------- #
# Import complet
# --------------------------------------------------------------------------- #


@respx.mock
async def test_import_complet(tmp_path: Path) -> None:
    routes = simuler_apis()
    async with httpx.AsyncClient() as client:
        donnees = await telecharger_donnees(client, TYPES)
    # Seuls les champs utiles sont demandés : jamais d'e-mail ni de téléphone
    parametres_annuaire = routes["mairie"].calls[0].request.url.params
    assert parametres_annuaire["select"] == "nom,pivot,site_internet,code_insee_commune"

    organisations = construire_organisations(donnees, 10_000, TYPES)
    par_slug = {o.slug: o for o in organisations}
    communes = {o.nom for o in organisations if o.type == "commune"}
    assert communes == {"Exempleville", "Saint-Démo-sur-Mer", "Sans-Site"}
    assert par_slug["exempleville-33999"].site_web == "https://www.exempleville.fr"
    assert par_slug["saint-demo-sur-mer-13999"].site_web == "https://saint-demo.example"
    assert par_slug["sans-site-59999"].site_web is None
    gironde = par_slug["departement-gironde"]
    assert (gironde.site_web, gironde.region) == ("https://www.gironde.example", "75")
    assert gironde.nom.startswith("Conseil départemental")
    assert par_slug["departement-nord"].site_web is None
    region = par_slug["region-nouvelle-aquitaine"]
    assert (region.site_web, region.departement) == ("https://www.region.example", "33")

    with Base(tmp_path / "base.db") as base:
        rapport = enregistrer_import(base, donnees, organisations)
        assert rapport.organisations == len(organisations)
        assert "Sans-Site" in rapport.sans_site
        assert base.territoires("departement")["33"] == ("Gironde", "75")
        assert base.territoires("region")["93"][0] == "Provence-Alpes-Côte d'Azur"


def test_import_seulement_les_communes() -> None:
    donnees_json = json.loads(lire("geo_communes.json"))
    from bleublanccloud.cibles.communes import CommuneGeo
    from bleublanccloud.cibles.importation import DonneesImport

    donnees = DonneesImport(
        communes=[CommuneGeo.model_validate(c) for c in donnees_json],
        departements=[],
        regions=[],
        mairies=[],
        conseils_departementaux=[],
        conseils_regionaux=[],
    )
    organisations = construire_organisations(donnees, 5_000, ["commune"])
    assert {o.type for o in organisations} == {"commune"}
    assert len(organisations) == 4


# --------------------------------------------------------------------------- #
# Campagnes
# --------------------------------------------------------------------------- #


def organisation(slug: str, site: str | None) -> Organisation:
    return Organisation(slug=slug, nom=slug.title(), type="commune", site_web=site, source="test")


def test_preparer_cibles(referentiels: Referentiels) -> None:
    with Base(":memory:") as base:
        for slug, site in (
            ("exempleville", "https://www.exempleville.fr/"),
            ("sans-site", None),
            ("invalide", "pas une url"),
            ("retiree", "https://retire.fr"),
            ("autre", "https://autre.fr"),
        ):
            base.enregistrer_organisation(organisation(slug, site))
        cibles, ignorees = preparer_cibles(
            base.organisations(), lambda d: d == "retire.fr", limite=None
        )
        assert [c.domaine for c in cibles] == ["autre.fr", "exempleville.fr"]
        assert len(ignorees) == 3
        limitees, _ = preparer_cibles(base.organisations(), lambda d: False, limite=1)
        assert len(limitees) == 1


async def test_lancer_campagne(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    resolveur = ResolveurFactice.depuis_fixture("exempleville.fr").fusionner(
        ResolveurFactice.depuis_fixture("cdn-exemple.fr")
    )
    contexte = fabriquer_contexte(parametres, referentiels, resolveur, resolveur_asn)
    with Base(":memory:") as base:
        base.enregistrer_organisation(organisation("exempleville", "https://exempleville.fr"))
        base.enregistrer_organisation(organisation("doublon", "https://www.exempleville.fr/"))
        base.enregistrer_organisation(organisation("cdn", "https://cdn-exemple.fr"))
        cibles, _ = preparer_cibles(base.organisations(), referentiels.est_retire)
        vues: list[str] = []
        rapport = await lancer_campagne(
            base, contexte, cibles, progression=lambda cible, _: vues.append(cible.domaine)
        )
        assert (rapport.prevues, rapport.scannees, rapport.notees) == (3, 3, 3)
        assert sum(rapport.notes.values()) == 3
        assert sorted(vues) == ["cdn-exemple.fr", "exempleville.fr", "exempleville.fr"]
        # Le domaine partagé par deux organisations n'est résolu qu'une seule fois
        assert resolveur.appels.count("exempleville.fr|MX") == 1
        for enregistree in base.organisations():
            assert base.dernier_scan(enregistree.id) is not None


async def test_campagne_erreur_isolee(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    class ResolveurEnPanne(ResolveurFactice):
        async def zone_de(self, nom: str) -> str | None:
            raise RuntimeError("panne inattendue")

    contexte = fabriquer_contexte(parametres, referentiels, ResolveurEnPanne({}), resolveur_asn)
    with Base(":memory:") as base:
        base.enregistrer_organisation(organisation("panne", "https://panne.fr"))
        cibles, _ = preparer_cibles(base.organisations(), referentiels.est_retire)
        rapport = await lancer_campagne(base, contexte, cibles)
    assert rapport.scannees == 0
    assert "panne inattendue" in rapport.erreurs[0]


async def test_campagne_score_impossible(
    parametres: Parametres, referentiels: Referentiels, resolveur_asn: ResolveurAsn
) -> None:
    contexte = fabriquer_contexte(parametres, referentiels, ResolveurFactice({}), resolveur_asn)
    with Base(":memory:") as base:
        org_id = base.enregistrer_organisation(organisation("vide", "https://vide.fr"))
        cibles, _ = preparer_cibles(base.organisations(), referentiels.est_retire)
        rapport = await lancer_campagne(base, contexte, cibles)
        assert rapport.scannees == 1 and rapport.notees == 0
        assert base.dernier_scan(org_id, avec_score=False) is not None


# --------------------------------------------------------------------------- #
# Ligne de commande
# --------------------------------------------------------------------------- #


@pytest.fixture
def base_temporaire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    configuration.obtenir_parametres.cache_clear()
    yield chemin
    configuration.obtenir_parametres.cache_clear()


def test_cli_ajouter_lister_et_simulation(base_temporaire: Path) -> None:
    lanceur = CliRunner()
    resultat = lanceur.invoke(
        app, ["cibles", "ajouter", "--nom", "Exempleville", "--site", "https://exempleville.fr"]
    )
    assert resultat.exit_code == 0, resultat.output
    assert "exempleville" in lanceur.invoke(app, ["cibles", "lister"]).output
    simulation = lanceur.invoke(app, ["campagne", "lancer", "--dry-run"])
    assert simulation.exit_code == 0, simulation.output
    assert "Simulation" in simulation.output
    assert "exempleville.fr" in simulation.output


def test_cli_campagne_demande_confirmation(base_temporaire: Path) -> None:
    lanceur = CliRunner()
    lanceur.invoke(app, ["cibles", "ajouter", "--nom", "Exempleville", "--site", "exempleville.fr"])
    refus = lanceur.invoke(app, ["campagne", "lancer"], input="n\n")
    assert refus.exit_code != 0
    assert "Lancer l'analyse passive" in refus.output


def test_cli_campagne_organisation_inconnue(base_temporaire: Path) -> None:
    resultat = CliRunner().invoke(app, ["campagne", "lancer", "--organisation", "inconnue"])
    assert resultat.exit_code == 2


def test_cli_campagne_complete(
    base_temporaire: Path, monkeypatch: pytest.MonkeyPatch, referentiels: Referentiels
) -> None:
    @asynccontextmanager
    async def contexte(parametres: Parametres, refs: Referentiels) -> AsyncIterator[ContexteScan]:
        asn = ResolveurAsn(
            plages_de_test(), lecteur_mmdb=LecteurMmdbFactice(), utiliser_ripestat=False
        )
        yield fabriquer_contexte(
            parametres, refs, ResolveurFactice.depuis_fixture("exempleville.fr"), asn
        )

    monkeypatch.setattr(scan, "contexte_reseau", contexte)
    lanceur = CliRunner()
    lanceur.invoke(app, ["cibles", "ajouter", "--nom", "Exempleville", "--site", "exempleville.fr"])
    resultat = lanceur.invoke(app, ["campagne", "lancer", "--oui"])
    assert resultat.exit_code == 0, resultat.output
    assert "1/1 scannée(s)" in resultat.output
    inconnus = lanceur.invoke(app, ["referentiels", "inconnus"])
    assert inconnus.exit_code == 0


def test_cli_campagne_retrait_respecte(
    base_temporaire: Path, monkeypatch: pytest.MonkeyPatch, referentiels: Referentiels
) -> None:
    from bleublanccloud import cli

    avec_retrait = dataclasses.replace(
        referentiels,
        retraits={"exempleville.fr": Retrait(domaine="exempleville.fr", date_demande="2026-01-01")},
    )
    monkeypatch.setattr(cli, "referentiels_par_defaut", lambda: avec_retrait)
    lanceur = CliRunner()
    lanceur.invoke(app, ["cibles", "ajouter", "--nom", "Exempleville", "--site", "exempleville.fr"])
    resultat = lanceur.invoke(app, ["campagne", "lancer", "--dry-run"])
    assert "0 organisation(s) à analyser" in resultat.output
    assert "retrait demandé" in resultat.output
