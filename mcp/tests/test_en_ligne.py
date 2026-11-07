"""Tests du mode en ligne (HTTP) : protocole MCP, hôtes autorisés, limite de requêtes."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from starlette.testclient import TestClient

from bleublanccloud_mcp import serveur as module_serveur
from bleublanccloud_mcp.donnees import SourceDonnees
from bleublanccloud_mcp.en_ligne import LimiteurRequetes, adresse_client, creer_application

HOTE = "mcp.bbc.example"
ENTETES = {
    "host": HOTE,
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


def jsonrpc(methode: str, params: dict[str, Any], identifiant: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": identifiant, "method": methode, "params": params}


INITIALISATION = jsonrpc(
    "initialize",
    {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
)


@pytest.fixture
def client(donnees: SourceDonnees, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(module_serveur, "donnees", donnees)
    application = creer_application(hotes=[HOTE], requetes_par_minute=5)
    with TestClient(application, base_url=f"https://{HOTE}") as client_test:
        yield client_test


def test_accueil_informatif(client: TestClient) -> None:
    reponse = client.get("/", headers={"host": HOTE})
    assert reponse.status_code == 200
    assert reponse.json()["point_d_acces"] == "/mcp"


def test_accueil_html_pour_un_navigateur(client: TestClient) -> None:
    reponse = client.get("/", headers={"host": HOTE, "accept": "text/html"})
    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("text/html")
    assert 'rel="icon" href="/favicon.svg"' in reponse.text


@pytest.mark.parametrize(
    ("chemin", "type_mime"),
    [
        ("/favicon.ico", "image/x-icon"),
        ("/favicon.svg", "image/svg+xml"),
        ("/icone.png", "image/png"),
        ("/apple-touch-icon.png", "image/png"),
    ],
)
def test_icones_bleu_blanc_cloud(client: TestClient, chemin: str, type_mime: str) -> None:
    reponse = client.get(chemin, headers={"host": HOTE})
    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == type_mime
    assert reponse.content


def test_identite_du_serveur(client: TestClient) -> None:
    init = client.post("/mcp", json=INITIALISATION, headers=ENTETES).json()["result"]
    infos = init["serverInfo"]
    assert infos["title"] == "Bleu Blanc Cloud"
    assert {i["mimeType"] for i in infos["icons"]} == {"image/svg+xml", "image/png"}


def test_protocole_mcp_en_http(client: TestClient) -> None:
    init = client.post("/mcp", json=INITIALISATION, headers=ENTETES)
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "Bleu Blanc Cloud"

    appel = client.post(
        "/mcp",
        json=jsonrpc("tools/call", {"name": "statistiques", "arguments": {}}, 2),
        headers={**ENTETES, "mcp-protocol-version": "2025-06-18"},
    )
    assert appel.status_code == 200, appel.text
    contenu = json.loads(appel.json()["result"]["content"][0]["text"])
    assert contenu["nombre_collectivites"] == 14


def test_racine_accepte_aussi_le_protocole_mcp(client: TestClient) -> None:
    # Adresse saisie sans « /mcp » dans le client (cas vu avec Le Chat)
    init = client.post("/", json=INITIALISATION, headers=ENTETES)
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "Bleu Blanc Cloud"


def test_hote_non_autorise_refuse(client: TestClient) -> None:
    reponse = client.post(
        "/mcp", json=INITIALISATION, headers={**ENTETES, "host": "pirate.example"}
    )
    assert reponse.status_code in (400, 421)


def test_limite_de_requetes(client: TestClient) -> None:
    statuts = [
        client.post(
            "/mcp", json=INITIALISATION, headers={**ENTETES, "x-forwarded-for": "203.0.113.7"}
        ).status_code
        for _ in range(6)
    ]
    assert statuts[:5] == [200] * 5
    assert statuts[5] == 429
    # Une autre adresse n'est pas pénalisée
    autre = client.post(
        "/mcp", json=INITIALISATION, headers={**ENTETES, "x-forwarded-for": "198.51.100.1"}
    )
    assert autre.status_code == 200


def test_limiteur_fenetre_glissante() -> None:
    instant = [0.0]
    limiteur = LimiteurRequetes(par_minute=2, horloge=lambda: instant[0])
    assert limiteur.autoriser("a") and limiteur.autoriser("a")
    assert not limiteur.autoriser("a")
    instant[0] = 61.0  # une minute plus tard
    assert limiteur.autoriser("a")


def test_adresse_client() -> None:
    portee = {"headers": [(b"x-forwarded-for", b"203.0.113.7, 10.0.0.1")], "client": ("::1", 1)}
    assert adresse_client(portee) == "203.0.113.7"
    assert adresse_client({"headers": [], "client": ("192.0.2.5", 80)}) == "192.0.2.5"
