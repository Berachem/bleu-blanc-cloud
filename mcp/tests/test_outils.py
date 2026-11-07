"""Tests des outils MCP sur les données de démonstration du site (sans réseau)."""

from __future__ import annotations

import json

import respx

from bleublanccloud_mcp import outils
from bleublanccloud_mcp.donnees import SourceDonnees
from bleublanccloud_mcp.outils import code_insee, normaliser
from tests.conftest import BASE


def test_normaliser_et_code_insee() -> None:
    assert normaliser("Saint-Étienne-du-Rouvray") == "saint etienne du rouvray"
    assert code_insee("lyon-69123") == "69123"
    assert code_insee("ajaccio-2a004") == "2A004"
    assert code_insee("departement-gironde") is None


async def test_recherche_exacte_sans_accents_et_par_domaine(donnees: SourceDonnees) -> None:
    exacte = await outils.rechercher_collectivite(donnees, "Commune de Démoville")
    assert exacte["resultats"][0]["slug"] == "demoville-demo"
    sans_accent = await outils.rechercher_collectivite(donnees, "demoville")
    assert sans_accent["resultats"][0]["slug"] == "demoville-demo"
    domaine = await outils.rechercher_collectivite(donnees, "exempleville.example")
    assert domaine["resultats"][0]["url_fiche"] == f"{BASE}/organisation/exempleville-demo/"
    assert (await outils.rechercher_collectivite(donnees, "  "))["resultats"] == []
    source = exacte["source"]
    assert source["demonstration"] is True
    assert "indicatif" in source["avertissement"]


async def test_fiche_complete(donnees: SourceDonnees) -> None:
    fiche = await outils.fiche_collectivite(donnees, "exempleville-demo")
    assert fiche["note"] == "A" and fiche["score"] == 100
    assert len(fiche["evolution"]) == 6  # historique fictif de la démonstration
    assert fiche["evolution"][0]["note"] == "C"
    assert {c["categorie"] for c in fiche["categories"]} >= {"Messagerie", "DNS"}
    assert any(f["nom"] == "OVHcloud" for f in fiche["fournisseurs"])
    assert "Rédigé par une IA" in fiche["synthese_ia"]["mention"]
    assert fiche["url_fiche"].endswith("/organisation/exempleville-demo/")


async def test_fiche_inconnue_ou_slug_invalide(
    donnees: SourceDonnees, site: respx.MockRouter
) -> None:
    assert "erreur" in await outils.fiche_collectivite(donnees, "inconnue-demo")
    appels = len(site.calls)
    # Identifiant invalide (chemin) : refusé sans aucune requête
    assert "erreur" in await outils.fiche_collectivite(donnees, "../../etc/passwd")
    assert len(site.calls) == appels


async def test_classement_filtres_et_ordre(donnees: SourceDonnees) -> None:
    nord = await outils.classement(donnees, departement="Nord")
    assert [r["slug"] for r in nord["resultats"]] == ["demoville-demo"]
    assert (await outils.classement(donnees, departement="59"))["nombre_total"] == 1
    notes_e = await outils.classement(donnees, note="E", ordre="moins_bons")
    scores = [r["score"] for r in notes_e["resultats"]]
    assert scores == sorted(scores) and all(r["note"] == "E" for r in notes_e["resultats"])
    tous = await outils.classement(donnees, limite=50)
    assert all(r["type"] != "sur_demande" for r in tous["resultats"])
    assert tous["nombre_total"] == 14  # observatoire de démonstration, hors analyse sur demande
    meilleurs = [r["score"] for r in tous["resultats"]]
    assert meilleurs == sorted(meilleurs, reverse=True)


async def test_comparer(donnees: SourceDonnees) -> None:
    resultat = await outils.comparer(donnees, ["exempleville-demo", "demoville-demo", "absente"])
    assert [c["slug"] for c in resultat["collectivites"]] == ["exempleville-demo", "demoville-demo"]
    assert resultat["introuvables"] == ["absente"]
    demoville = resultat["collectivites"][1]
    assert "Microsoft" in " ".join(demoville["fournisseurs_principaux"]["Messagerie"])


async def test_statistiques(donnees: SourceDonnees) -> None:
    france = await outils.statistiques(donnees)
    assert france["perimetre"] == "France"
    assert france["nombre_collectivites"] == 14
    assert sum(france["repartition_notes"].values()) == 14
    nord = await outils.statistiques(donnees, "59")
    assert nord["perimetre"] == "Nord" and nord["nombre_collectivites"] == 1


async def test_collectivites_par_fournisseur(donnees: SourceDonnees) -> None:
    microsoft = await outils.collectivites_par_fournisseur(donnees, "microsoft", "messagerie")
    assert [r["slug"] for r in microsoft["resultats"]] == ["bordeaux-33063", "lille-59350"]
    gironde = await outils.collectivites_par_fournisseur(
        donnees, "Microsoft", departement="Gironde"
    )
    assert [r["slug"] for r in gironde["resultats"]] == ["bordeaux-33063"]
    assert gironde["resultats"][0]["usages"] == ["messagerie", "services_hors_ue"]
    analytics = await outils.collectivites_par_fournisseur(
        donnees, "google analytics", "services_hors_ue"
    )
    assert [r["nom"] for r in analytics["resultats"]] == ["Lille"]


async def test_alternatives(donnees: SourceDonnees) -> None:
    messagerie = await outils.alternatives(donnees, "messagerie")
    assert messagerie["alternatives"]
    assert all(
        a["categorie"] == "messagerie"
        or any("messagerie" in t for t in a["types_service"])
        or "messagerie" in (a["description"] or "").lower()
        for a in messagerie["alternatives"]
    )
    assert len((await outils.alternatives(donnees))["alternatives"]) == 55


async def test_cache_une_requete_par_fichier(
    donnees: SourceDonnees, site: respx.MockRouter
) -> None:
    await outils.statistiques(donnees)
    await outils.classement(donnees)
    appels_index = [c for c in site.calls if c.request.url.path == "/donnees/index.json"]
    assert len(appels_index) == 1
    assert "BleuBlancCloudMCP/" in site.calls[0].request.headers["user-agent"]
    assert json.dumps(await outils.statistiques(donnees))  # sérialisable
