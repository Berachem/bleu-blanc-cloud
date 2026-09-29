"""Contours des communes (carte de situation) : simplification, téléchargement par code
INSEE (geo.api.gouv.fr simulé), stockage et export."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.cibles.communes import URL_GEO
from bleublanccloud.cibles.contours import (
    SOURCE_CONTOURS,
    ContourIntrouvable,
    geometrie_depuis_geojson,
    mettre_a_jour_contours,
    simplifier_anneau,
    simplifier_contour,
    telecharger_contour,
)
from bleublanccloud.cli import app
from bleublanccloud.export.demonstration import generer_demonstration
from bleublanccloud.export.site_statique import exporter
from bleublanccloud.modeles import Constat, Organisation, OrganisationExport, ResultatScan
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base

DOSSIER_FIXTURES = Path(__file__).parent / "fixtures" / "geo"
GRENOBLE = json.loads((DOSSIER_FIXTURES / "commune-38185.json").read_text())
MAINTENANT = datetime(2026, 9, 29, 12, tzinfo=UTC)


async def sans_attente(_: float) -> None:
    return None


def cercle(lon: float, lat: float, rayon: float, points: int) -> list[list[float]]:
    angles = [2 * math.pi * i / points for i in range(points)]
    anneau = [[lon + rayon * math.cos(a), lat + rayon * math.sin(a)] for a in angles]
    return [*anneau, anneau[0]]


@pytest.fixture
def base() -> Base:
    with Base(":memory:") as b:
        yield b  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Simplification
# --------------------------------------------------------------------------- #


def test_simplification_d_un_contour_dense() -> None:
    dense = cercle(5.72, 45.18, 0.05, 2000)
    simplifie = simplifier_anneau(dense, tolerance=0.001)
    assert simplifie is not None
    assert 8 < len(simplifie) < 80
    assert simplifie[0] == simplifie[-1]
    # Tous les points restent sur le cercle d'origine (arrondi à 4 décimales)
    for lon, lat in simplifie:
        assert math.hypot(lon - 5.72, lat - 45.18) == pytest.approx(0.05, abs=1e-4)


def test_petite_commune_conservee_par_reduction_de_tolerance() -> None:
    cote = 0.0008  # ≈ 80 m : le carré disparaîtrait avec la tolérance par défaut
    carre = [
        [5.0, 45.0],
        [5.0 + cote, 45.0],
        [5.0 + cote, 45.0 + cote],
        [5.0, 45.0 + cote],
        [5.0, 45.0],
    ]
    assert simplifier_anneau(carre, tolerance=0.001) is None
    contour = simplifier_contour({"type": "Polygon", "coordinates": [carre]})
    assert contour is not None and len(contour[0][0]) == 5


def test_ilots_invisibles_retires_trous_conserves() -> None:
    principal = cercle(-1.5, 47.2, 0.05, 400)
    trou = list(reversed(cercle(-1.5, 47.2, 0.01, 200)))
    ilot = cercle(-1.3, 47.2, 0.00005, 20)
    contour = simplifier_contour(
        {"type": "MultiPolygon", "coordinates": [[principal, trou], [ilot]]}
    )
    assert contour is not None
    assert len(contour) == 1  # îlot retiré
    assert len(contour[0]) == 2  # trou conservé


def test_contour_reel_de_grenoble_leger() -> None:
    contour = simplifier_contour(GRENOBLE["geometry"])
    assert contour is not None
    assert len(json.dumps(contour, separators=(",", ":"))) < 2000
    for lon, lat in contour[0][0]:
        assert 5.67 < lon < 5.76 and 45.15 < lat < 45.22


def test_geometries_non_polygonales_refusees() -> None:
    assert simplifier_contour({"type": "Point", "coordinates": [5.0, 45.0]}) is None
    assert simplifier_contour({"type": "Polygon", "coordinates": []}) is None


def test_geometrie_depuis_geojson() -> None:
    geometrie = GRENOBLE["geometry"]
    assert geometrie_depuis_geojson(GRENOBLE) == geometrie
    assert (
        geometrie_depuis_geojson({"type": "FeatureCollection", "features": [GRENOBLE]}) == geometrie
    )
    assert geometrie_depuis_geojson(geometrie) == geometrie
    assert geometrie_depuis_geojson({"type": "FeatureCollection", "features": []}) is None
    assert geometrie_depuis_geojson({"type": "Feature", "geometry": None}) is None
    assert geometrie_depuis_geojson([1, 2]) is None


# --------------------------------------------------------------------------- #
# Téléchargement (geo.api.gouv.fr simulé)
# --------------------------------------------------------------------------- #

PARAMETRES = {"fields": "code", "format": "geojson", "geometry": "contour"}


@respx.mock
async def test_telechargement_par_code_insee() -> None:
    route = respx.get(f"{URL_GEO}/communes/38185", params=PARAMETRES).mock(
        return_value=httpx.Response(200, json=GRENOBLE)
    )
    async with httpx.AsyncClient() as client:
        assert await telecharger_contour(client, "38185") == GRENOBLE["geometry"]
    assert route.call_count == 1


@respx.mock
async def test_telechargement_commune_inconnue_et_relances() -> None:
    respx.get(f"{URL_GEO}/communes/99999").mock(return_value=httpx.Response(404))
    instable = respx.get(f"{URL_GEO}/communes/2A004").mock(
        side_effect=[
            httpx.Response(503),
            httpx.ConnectError("coupure"),
            httpx.Response(200, json=GRENOBLE),
        ]
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(ContourIntrouvable):
            await telecharger_contour(client, "99999", sans_attente)
        assert await telecharger_contour(client, "2A004", sans_attente) == GRENOBLE["geometry"]
    assert instable.call_count == 3


@respx.mock
async def test_code_insee_invalide_jamais_demande() -> None:
    async with httpx.AsyncClient() as client:
        for code in ("../regions", "3818", "38185?x=1", ""):
            with pytest.raises(ValueError, match="code INSEE invalide"):
                await telecharger_contour(client, code)
    assert not respx.calls


def _commune(base: Base, code: str, nom: str) -> int:
    return base.enregistrer_organisation(
        Organisation(
            slug=f"{nom.lower()}-{code.lower()}", nom=nom, type="commune", code_commune=code,
            departement=code[:2], region="84", population=150_000,
            site_web=f"https://www.{nom.lower()}.fr/", source="test",
        )
    )  # fmt: skip


@respx.mock
async def test_mise_a_jour_des_contours_manquants(base: Base) -> None:
    _commune(base, "38185", "Grenoble")
    _commune(base, "69123", "Lyon")
    grenoble = respx.get(f"{URL_GEO}/communes/38185").mock(
        return_value=httpx.Response(200, json=GRENOBLE)
    )
    respx.get(f"{URL_GEO}/communes/69123").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        codes = base.codes_communes_cibles()
        bilan = await mettre_a_jour_contours(base, client, codes, MAINTENANT, attendre=sans_attente)
        assert (bilan.telecharges, bilan.deja_presents, bilan.introuvables) == (1, 0, ["69123"])
        stocke = base.contour_commune("38185")
        assert stocke == simplifier_contour(GRENOBLE["geometry"])
        ligne = base.connexion.execute("SELECT source FROM contours").fetchone()
        assert ligne["source"] == SOURCE_CONTOURS

        # Un contour déjà présent n'est pas redemandé, sauf avec « forcer »
        bilan = await mettre_a_jour_contours(base, client, codes, MAINTENANT, attendre=sans_attente)
        assert (bilan.telecharges, bilan.deja_presents) == (0, 1)
        assert grenoble.call_count == 1
        bilan = await mettre_a_jour_contours(
            base, client, codes, MAINTENANT, forcer=True, attendre=sans_attente
        )
        assert bilan.telecharges == 1 and grenoble.call_count == 2


@respx.mock
async def test_erreur_reseau_signalee_sans_interrompre(base: Base) -> None:
    respx.get(f"{URL_GEO}/communes/38185").mock(side_effect=httpx.ConnectError("coupure"))
    respx.get(f"{URL_GEO}/communes/69123").mock(return_value=httpx.Response(200, json=GRENOBLE))
    async with httpx.AsyncClient() as client:
        bilan = await mettre_a_jour_contours(
            base, client, ["38185", "69123", "code-invalide"], MAINTENANT, attendre=sans_attente
        )
    assert bilan.telecharges == 1
    assert bilan.erreurs == ["38185 : ConnectError"]
    assert base.codes_communes_avec_contour() == {"69123"}


# --------------------------------------------------------------------------- #
# Export et démonstration
# --------------------------------------------------------------------------- #


def _scan(base: Base, org_id: int, domaine: str) -> None:
    constats = [
        Constat(sonde="dns", categorie="messagerie", cle="mx", valeur="mx.ovh.net",
                fournisseur_id="ovhcloud", niveau="A"),
    ]  # fmt: skip
    date = datetime(2026, 9, 28, 3, tzinfo=UTC)
    resultat = ResultatScan(
        domaine=domaine, debut=date, fin=date, statut="termine",
        sondes_reussies=["dns", "http"], constats=constats,
    )  # fmt: skip
    base.enregistrer_scan(org_id, resultat, calculer_score(constats), VERSION_METHODO)


def test_export_du_contour_des_communes_seulement(
    base: Base, referentiels: Referentiels, tmp_path: Path
) -> None:
    grenoble = _commune(base, "38185", "Grenoble")
    _scan(base, grenoble, "grenoble.fr")
    departement = base.enregistrer_organisation(
        Organisation(slug="departement-isere", nom="Département de l'Isère", type="departement",
                     departement="38", region="84", code_commune="38185",
                     site_web="https://www.isere.fr/", source="test")
    )  # fmt: skip
    _scan(base, departement, "isere.fr")
    contour = simplifier_contour(GRENOBLE["geometry"])
    assert contour is not None
    base.enregistrer_contour("38185", contour, SOURCE_CONTOURS, MAINTENANT)
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "ancienne.jpg").write_bytes(b"x")

    exporter(base, referentiels, tmp_path)
    fiche = OrganisationExport.model_validate_json(
        (tmp_path / "organisations" / "grenoble-38185.json").read_text()
    )
    assert fiche.contour == contour
    fiche_departement = OrganisationExport.model_validate_json(
        (tmp_path / "organisations" / "departement-isere.json").read_text()
    )
    assert fiche_departement.contour is None
    assert not (tmp_path / "photos").exists()  # anciennes copies de photos retirées


def test_commune_sans_contour_exportee_sans_carte(
    base: Base, referentiels: Referentiels, tmp_path: Path
) -> None:
    lyon = _commune(base, "69123", "Lyon")
    _scan(base, lyon, "lyon.fr")
    exporter(base, referentiels, tmp_path)
    fiche = json.loads((tmp_path / "organisations" / "lyon-69123.json").read_text())
    assert fiche["contour"] is None


def test_demonstration_contours_fictifs(referentiels: Referentiels) -> None:
    organisations = generer_demonstration(referentiels)
    for organisation in organisations:
        if organisation.type == "commune":
            assert organisation.contour is not None, organisation.slug
            assert len(organisation.contour[0][0]) == 19
        else:
            assert organisation.contour is None, organisation.slug


@respx.mock
def test_cli_cibles_contours(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    from bleublanccloud import configuration

    configuration.obtenir_parametres.cache_clear()
    with Base(chemin) as b:
        _commune(b, "38185", "Grenoble")
    respx.get(f"{URL_GEO}/communes/38185").mock(return_value=httpx.Response(200, json=GRENOBLE))
    try:
        resultat = CliRunner().invoke(app, ["cibles", "contours"])
        assert resultat.exit_code == 0, resultat.output
        assert "1 téléchargé" in resultat.output
        with Base(chemin) as b:
            assert b.codes_communes_avec_contour() == {"38185"}
    finally:
        configuration.obtenir_parametres.cache_clear()


@respx.mock
async def test_reponse_non_json_comptee_en_erreur(base: Base) -> None:
    respx.get(f"{URL_GEO}/communes/38185").mock(
        return_value=httpx.Response(200, text="<html>maintenance</html>")
    )
    async with httpx.AsyncClient() as client:
        bilan = await mettre_a_jour_contours(
            base, client, ["38185"], MAINTENANT, attendre=sans_attente
        )
    assert bilan.erreurs == ["38185 : JSONDecodeError"]
