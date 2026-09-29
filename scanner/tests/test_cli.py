"""Tests de l'interface en ligne de commande."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from typer.testing import CliRunner

from bleublanccloud import scan
from bleublanccloud.cli import app
from bleublanccloud.configuration import Parametres
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import ContexteScan
from bleublanccloud.sondes.ip import ResolveurAsn
from tests.conftest import LecteurMmdbFactice, ResolveurFactice, fabriquer_contexte, plages_de_test

lanceur = CliRunner()


@pytest.fixture
def contexte_factice(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def contexte(
        parametres: Parametres, referentiels: Referentiels
    ) -> AsyncIterator[ContexteScan]:
        resolveur = ResolveurFactice.depuis_fixture("exempleville.fr")
        asn = ResolveurAsn(
            plages_de_test(), lecteur_mmdb=LecteurMmdbFactice(), utiliser_ripestat=False
        )
        yield fabriquer_contexte(parametres, referentiels, resolveur, asn)

    monkeypatch.setattr(scan, "contexte_reseau", contexte)


def test_scanner_affichage(contexte_factice: None) -> None:
    resultat = lanceur.invoke(app, ["scanner", "exempleville.fr"])
    assert resultat.exit_code == 0, resultat.output
    assert "OVHcloud" in resultat.output
    assert "Microsoft" in resultat.output


def test_scanner_json(contexte_factice: None) -> None:
    resultat = lanceur.invoke(app, ["scanner", "exempleville.fr", "--json"])
    assert resultat.exit_code == 0, resultat.output
    donnees = json.loads(resultat.output)
    assert donnees["domaine"] == "exempleville.fr"
    assert any(c["fournisseur_id"] == "microsoft" for c in donnees["constats"])


def test_scanner_cible_invalide(contexte_factice: None) -> None:
    resultat = lanceur.invoke(app, ["scanner", "pas un domaine"])
    assert resultat.exit_code == 2


def test_referentiels_verifier() -> None:
    resultat = lanceur.invoke(app, ["referentiels", "verifier"])
    assert resultat.exit_code == 0
    assert "fournisseurs" in resultat.output
