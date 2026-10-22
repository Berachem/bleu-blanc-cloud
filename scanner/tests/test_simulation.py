"""Tests du simulateur « Et si… ? » : export des dépendances et moteur de règles d'impact."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from bleublanccloud.analyse.score import calculer_score
from bleublanccloud.export.demonstration import generer_demonstration
from bleublanccloud.export.site_statique import ecrire_export
from bleublanccloud.modeles import Constat, InformationsComplementaires, OrganisationExport
from bleublanccloud.referentiels import referentiels_par_defaut
from bleublanccloud.simulation import (
    agreger,
    construire_export,
    evaluer,
    fournisseurs_par_categorie,
    fournisseurs_tombes,
    ligne_simulation,
    lire_prereglages,
)

CAS = Path(__file__).parent / "fixtures" / "simulation" / "cas.json"
DATE = datetime(2026, 10, 18, 3, tzinfo=UTC)


def constat(
    categorie: str, cle: str, fournisseur: str | None, niveau: str = "A", **preuve: Any
) -> Constat:
    return Constat.model_validate(
        {
            "sonde": "dns",
            "categorie": categorie,
            "cle": cle,
            "valeur": f"{cle}.{fournisseur or 'inconnu'}.example",
            "fournisseur_id": fournisseur,
            "niveau": niveau if fournisseur else "inconnu",
            "preuve": preuve,
        }
    )


def organisation(slug: str, constats: list[Constat], **champs: Any) -> OrganisationExport:
    donnees: dict[str, Any] = {
        "slug": slug,
        "nom": f"Commune de {slug}",
        "type": "commune",
        "departement": "33",
        "region": "75",
        "region_nom": "Nouvelle-Aquitaine",
        "population": 25_000,
        "domaine": f"{slug}.example",
        "date_scan": DATE,
        "statut_scan": "termine",
        "score": calculer_score(constats, ["dns", "http"]),
        "constats": constats,
        "informations": InformationsComplementaires(),
        "fournisseurs": {},
    }
    donnees.update(champs)
    return OrganisationExport.model_validate(donnees)


# --------------------------------------------------------------------------- #
# Moteur : cas communs avec site/src/lib/simulation.ts
# --------------------------------------------------------------------------- #


def charger_cas() -> dict[str, Any]:
    contenu: dict[str, Any] = json.loads(CAS.read_text(encoding="utf-8"))
    return contenu


@pytest.mark.parametrize("scenario", charger_cas()["scenarios"], ids=lambda s: s["nom"])
def test_cas_communs(scenario: dict[str, Any]) -> None:
    lignes = charger_cas()["lignes"]
    tombes = set(scenario["tombes"])
    for ligne in lignes:
        assert evaluer(ligne, tombes) == scenario["impacts"][ligne["id"]], ligne["id"]
    assert agreger(lignes, tombes) == scenario["agregat"]


def test_dns_effet_domino_et_resilience() -> None:
    lignes = {ligne["id"]: ligne for ligne in charger_cas()["lignes"]}
    # Tous les NS chez OVHcloud : site ET messagerie injoignables
    assert evaluer(lignes["tout-chez-ovh"], {"ovhcloud"})["statut"] == "injoignable"
    # NS répartis chez deux opérateurs : le DNS résiste, seul l'hébergement tombe
    impact = evaluer(lignes["dns-reparti"], {"ovhcloud"})
    assert (impact["dns"], impact["site"], impact["messagerie"]) == (
        "resilient",
        "hors_ligne",
        "ok",
    )


def test_categorie_inconnue_jamais_comptee_comme_touchee() -> None:
    ligne = {ligne["id"]: ligne for ligne in charger_cas()["lignes"]}["hebergeur-inconnu"]
    assert evaluer(ligne, {"ovhcloud"})["statut"] == "indetermine"
    assert evaluer(ligne, set())["statut"] == "indetermine"


def test_scenario_cloud_act() -> None:
    export = {
        "fournisseurs": {
            "microsoft": {"id": "microsoft", "soumis_cloud_act": True},
            "ovhcloud": {"id": "ovhcloud", "soumis_cloud_act": False},
        }
    }
    assert fournisseurs_tombes(export, "cloud_act") == {"microsoft"}
    assert fournisseurs_tombes(export, "panne", "ovhcloud") == {"ovhcloud"}


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def test_plusieurs_fournisseurs_et_serveurs_inconnus() -> None:
    constats = [
        constat("hebergement", "hebergeur", "ovhcloud"),
        constat("hebergement", "hebergeur", "ovhcloud"),  # IPv4 et IPv6 : une seule fois
        constat("dns", "ns", "ovhcloud"),
        constat("dns", "ns", "gandi"),
        constat("messagerie", "mx", "microsoft", "D"),
        constat("messagerie", "mx", None),
        constat("services_tiers", "ressource_tierce", "google", "D"),
        constat("mesure_audience", "cookie", "google", "D"),
    ]
    fournisseurs = fournisseurs_par_categorie(constats)
    assert fournisseurs["hebergement"] == ["ovhcloud"]
    assert fournisseurs["dns"] == ["ovhcloud", "gandi"]
    assert fournisseurs["messagerie"] == ["microsoft", "?"]
    assert fournisseurs["services_tiers"] == ["google"]
    assert fournisseurs["audience"] == ["google"]


def test_cdn_devant_une_origine_masquee_ou_identifiee() -> None:
    masquee = constat(
        "hebergement", "cdn", "cloudflare", "C", origine="masquée par le CDN", cdn="cloudflare"
    )
    assert fournisseurs_par_categorie([masquee])["cdn"] == ["cloudflare"]
    assert fournisseurs_par_categorie([masquee])["hebergement"] == ["?"]
    # Origine de niveau D derrière un CDN : constat rattaché à l'origine, CDN dans la preuve
    identifiee = constat(
        "hebergement", "cdn", "aws", "D", origine={"fournisseur_id": "aws"}, cdn="cloudflare"
    )
    resultat = fournisseurs_par_categorie([identifiee])
    assert (resultat["cdn"], resultat["hebergement"]) == (["cloudflare"], ["aws"])


def test_collectivite_sans_messagerie_et_hebergeur_inconnu() -> None:
    constats = [
        constat("hebergement", "hebergeur", None),
        constat("dns", "ns", "gandi"),
        constat("messagerie", "mx_absent", None),
    ]
    ligne = ligne_simulation(organisation("sans-mx", constats))
    assert ligne["statuts"]["hebergement"] == "inconnu"
    assert ligne["fournisseurs"]["hebergement"] == ["?"]
    assert ligne["statuts"]["messagerie"] in {"sans_objet", "inconnu"}
    assert ligne["fournisseurs"]["messagerie"] == []
    assert ligne["tranche_population"] == "20000-50000"


def test_construire_export() -> None:
    referentiels = referentiels_par_defaut()
    orgs = [
        organisation(
            "alpha",
            [
                constat("hebergement", "hebergeur", "ovhcloud"),
                constat("dns", "ns", "ovhcloud"),
                constat("messagerie", "mx", "microsoft", "D"),
            ],
        ),
        organisation(
            "perso",
            [constat("hebergement", "hebergeur", "ovhcloud")],
            type="sur_demande",
            departement=None,
            region=None,
        ),
        organisation(
            "gironde",
            [constat("hebergement", "hebergeur", "ionos"), constat("dns", "ns", "ionos")],
            type="departement",
            population=None,
        ),
    ]
    export = construire_export(orgs, referentiels, {"75": "Nouvelle-Aquitaine"})
    assert [ligne["id"] for ligne in export["collectivites"]] == ["alpha", "gironde"]
    assert export["collectivites"][1]["tranche_population"] is None
    meta = export["meta"]
    assert meta["nombre_collectivites"] == 2
    assert meta["regions"] == {"75": "Nouvelle-Aquitaine"}
    assert meta["date_donnees"].startswith("2026-10-18")
    microsoft = export["fournisseurs"]["microsoft"]
    assert microsoft["soumis_cloud_act"] is True
    assert microsoft["niveau"] == "D"
    assert microsoft["statut_referentiel"] == "verifie"
    assert export["fournisseurs"]["ovhcloud"]["nombre_collectivites"] == 1
    # Aucune donnée de logiciel ou de version
    texte = json.dumps(export)
    assert "version" not in texte.replace("version_methodo", "")


def test_export_demonstration_ecrit_simulations(tmp_path: Path) -> None:
    referentiels = referentiels_par_defaut()
    organisations = generer_demonstration(referentiels)
    ecrire_export(tmp_path, organisations, {}, referentiels, donnees_demonstration=True)
    chemin = tmp_path / "simulations.json"
    export = json.loads(chemin.read_text(encoding="utf-8"))
    observatoire = [o for o in organisations if o.type != "sur_demande"]
    assert len(export["collectivites"]) == len(observatoire)
    assert chemin.stat().st_size < 300 * len(observatoire) + 20_000  # lignes compactes
    resultat = agreger(export["collectivites"], {"ovhcloud"})
    assert resultat["total"] == len(observatoire)


def test_prereglages() -> None:
    prereglages = {p["slug"]: p for p in lire_prereglages()}
    assert set(prereglages) == {
        "microsoft-coupe-acces",
        "panne-ovhcloud",
        "panne-cloudflare",
        "coupure-cloud-act",
    }
    referentiels = referentiels_par_defaut()
    for prereglage in prereglages.values():
        if prereglage["fournisseur"]:
            assert not referentiels.fournisseurs[prereglage["fournisseur"]].a_verifier
        # Pas de précédent sans source
        if prereglage["precedent"]:
            assert prereglage["precedent"]["sources"]


def test_image_de_partage() -> None:
    from bleublanccloud.export.image_simulation import compter, dessiner_partage

    assert compter(1, "site", "sites") == "1 site"
    assert compter(1162, "site", "sites") == "1 162 sites"
    resultat = agreger(charger_cas()["lignes"], {"ovhcloud"})
    image = dessiner_partage(lire_prereglages()[1], resultat, DATE, "bleublanccloud.fr")
    donnees = image.png()
    assert donnees[:8] == b"\x89PNG\r\n\x1a\n"
    assert (image.largeur, image.hauteur) == (1200, 630)
