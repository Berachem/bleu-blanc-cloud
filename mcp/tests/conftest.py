"""Données de test : les fichiers de démonstration du site (fictifs), servis par respx."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx

from bleublanccloud_mcp.donnees import SourceDonnees

BASE = "https://bbc.example"
DEMO = Path(__file__).resolve().parents[2] / "site" / "src" / "donnees-demo"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def site() -> respx.MockRouter:
    """Site simulé : fichiers de démonstration, CSV de test et méthodologie."""
    with respx.mock(base_url=BASE, assert_all_called=False) as routeur:
        for nom in ("meta", "index", "departements", "alternatives"):
            routeur.get(f"/donnees/{nom}.json").mock(
                return_value=httpx.Response(200, content=(DEMO / f"{nom}.json").read_bytes())
            )
        for fichier in (DEMO / "organisations").glob("*.json"):
            routeur.get(f"/donnees/organisations/{fichier.name}").mock(
                return_value=httpx.Response(200, content=fichier.read_bytes())
            )
        routeur.get(path__regex=r"^/donnees/organisations/.*\.json$").mock(
            return_value=httpx.Response(404)
        )
        routeur.get("/donnees/organisations.csv").mock(
            return_value=httpx.Response(200, content=(FIXTURES / "organisations.csv").read_bytes())
        )
        routeur.get("/methodologie.md").mock(
            return_value=httpx.Response(200, text="# Méthodologie — version 1.2\n")
        )
        yield routeur


@pytest.fixture
async def donnees(site: respx.MockRouter) -> AsyncIterator[SourceDonnees]:
    source = SourceDonnees(base=BASE)
    yield source
    if source.client is not None:
        await source.client.aclose()
