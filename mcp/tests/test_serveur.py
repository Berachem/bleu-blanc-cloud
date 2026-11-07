"""Tests du serveur MCP : outils, ressource et prompt, appelés comme le ferait un client."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from mcp.server.mcpserver.exceptions import ToolError

from bleublanccloud_mcp import serveur as module_serveur
from bleublanccloud_mcp.donnees import SourceDonnees


@pytest.fixture(autouse=True)
def donnees_de_test(donnees: SourceDonnees, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module_serveur, "donnees", donnees)


async def test_outils_declares_en_lecture_seule() -> None:
    outils = await module_serveur.serveur.list_tools()
    assert {o.name for o in outils} == {
        "rechercher_collectivite",
        "fiche_collectivite",
        "classement",
        "comparer",
        "statistiques",
        "collectivites_par_fournisseur",
        "alternatives",
    }
    assert all(o.annotations and o.annotations.read_only_hint for o in outils)


async def test_appel_d_outil_de_bout_en_bout() -> None:
    resultat = await module_serveur.serveur.call_tool(
        "rechercher_collectivite", {"texte": "Exempleville"}
    )
    assert not resultat.is_error
    contenu = json.loads(resultat.content[0].text)
    assert contenu["resultats"][0]["slug"] == "exempleville-demo"


async def test_parametres_valides_par_le_schema() -> None:
    # Au moins deux collectivités : refusé avant d'appeler l'outil
    with pytest.raises(ToolError, match="at least 2 items"):
        await module_serveur.serveur.call_tool("comparer", {"slugs": ["un-seul"]})


async def test_ressource_methodologie_et_prompt() -> None:
    (contenu,) = list(await module_serveur.serveur.read_resource("bleublanccloud://methodologie"))
    assert contenu.content.startswith("# Méthodologie")
    prompt = await module_serveur.serveur.get_prompt("analyser_ma_collectivite", {"nom": "Rennes"})
    assert "Rennes" in prompt.messages[0].content.text


def test_instructions_rappellent_les_regles() -> None:
    assert "url_fiche" in module_serveur.INSTRUCTIONS
    assert "indicatif" in module_serveur.INSTRUCTIONS


async def test_site_injoignable_ou_fichier_absent(site: respx.MockRouter) -> None:
    site.get("/donnees/index.json").mock(side_effect=httpx.ConnectError("hors ligne"))
    resultat = await module_serveur.serveur.call_tool("statistiques", {})
    assert "injoignable" in json.loads(resultat.content[0].text)["erreur"]
    site.get("/donnees/index.json").mock(return_value=httpx.Response(404))
    resultat = await module_serveur.serveur.call_tool("classement", {})
    assert "introuvable" in json.loads(resultat.content[0].text)["erreur"]
