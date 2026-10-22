"""Simulateur « Et si… ? » : export des dépendances et moteur de règles d'impact.

L'export (`simulations.json`) décrit, pour chaque collectivité de l'observatoire (dernier
scan noté), les fournisseurs détectés par catégorie : uniquement les données de fournisseurs
déjà publiques sur les fiches. Aucune information de vulnérabilité, aucun logiciel, aucune
version n'y figure.

Le moteur applique les règles d'impact d'une panne (ou coupure) d'un ensemble de
fournisseurs. Il existe aussi en TypeScript pour le site (`site/src/lib/simulation.ts`) ; les
deux versions sont verrouillées par les mêmes cas de test
(`scanner/tests/fixtures/simulation/cas.json`). La version Python sert aux images de partage
générées par le serveur (sans navigateur) et aux contrôles de cohérence.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal

from bleublanccloud.analyse.attribution import niveau_juridiction
from bleublanccloud.analyse.score import VERSION_METHODO
from bleublanccloud.configuration import RACINE_PROJET
from bleublanccloud.modeles import CategorieScore, Constat, OrganisationExport, Score
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.statistiques import TRANCHES_POPULATION, libelle_tranche

INCONNU: Final = "?"
"""Serveur détecté mais fournisseur non identifié : il n'est jamais considéré comme tombé."""

CATEGORIES: Final[dict[str, CategorieScore]] = {
    "hebergement": "hebergement",
    "dns": "dns",
    "messagerie": "messagerie",
    "services_tiers": "services_tiers",
    "audience": "mesure_audience",
}
"""Catégories de l'export → catégories de la méthodologie (pour le statut d'évaluation)."""

CHEMIN_PREREGLAGES: Final = RACINE_PROJET / "site" / "src" / "contenu" / "simulateur.json"

StatutCategorie = Literal["evalue", "inconnu", "indisponible", "sans_objet"]
StatutFinal = Literal["injoignable", "hors_service", "degrade", "indetermine", "non_touchee"]
STATUTS_TOUCHES: Final = ("injoignable", "hors_service", "degrade")


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def _statut(score: Score, categorie: CategorieScore) -> StatutCategorie:
    for detail in score.detail:
        if detail.categorie == categorie:
            if detail.evaluable:
                return "evalue"
            return detail.exclusion or "inconnu"
    return "sans_objet"


def _ajouter(liste: list[str], identifiant: str | None) -> None:
    valeur = identifiant or INCONNU
    if valeur not in liste:
        liste.append(valeur)


def fournisseurs_par_categorie(constats: Sequence[Constat]) -> dict[str, list[str]]:
    """Fournisseurs (identifiants du référentiel) de chaque catégorie, sans doublon.

    - hébergement : hébergeur réel (origine) ; « ? » quand il est masqué par un CDN ou non
      identifié ;
    - cdn : CDN placés devant le site (s'ils tombent, le site tombe) ;
    - dns, messagerie : un élément par opérateur des serveurs NS / MX (« ? » si inconnu) ;
    - services_tiers, audience : services chargés par le site (fournisseurs identifiés).
    """
    resultat: dict[str, list[str]] = {
        "hebergement": [],
        "cdn": [],
        "dns": [],
        "messagerie": [],
        "services_tiers": [],
        "audience": [],
    }
    for constat in constats:
        if constat.categorie == "hebergement":
            if constat.cle == "cdn":
                origine = constat.preuve.get("origine")
                id_origine = origine.get("fournisseur_id") if isinstance(origine, dict) else None
                id_cdn = constat.preuve.get("cdn") or (
                    constat.fournisseur_id if constat.fournisseur_id != id_origine else None
                )
                if id_cdn:
                    _ajouter(resultat["cdn"], id_cdn)
                _ajouter(resultat["hebergement"], id_origine)
            else:
                _ajouter(resultat["hebergement"], constat.fournisseur_id)
        elif constat.categorie == "dns" and constat.cle == "ns":
            _ajouter(resultat["dns"], constat.fournisseur_id)
        elif constat.categorie == "messagerie" and constat.cle == "mx":
            _ajouter(resultat["messagerie"], constat.fournisseur_id)
        elif constat.categorie == "services_tiers" and constat.fournisseur_id:
            _ajouter(resultat["services_tiers"], constat.fournisseur_id)
        elif constat.categorie == "mesure_audience" and constat.fournisseur_id:
            _ajouter(resultat["audience"], constat.fournisseur_id)
    return resultat


def code_tranche(population: int | None) -> str | None:
    if population is None:
        return None
    for minimum, maximum in TRANCHES_POPULATION:
        if population >= minimum and (maximum is None or population < maximum):
            return f"{minimum}-{maximum or ''}"
    return None  # pragma: no cover


def ligne_simulation(organisation: OrganisationExport) -> dict[str, Any]:
    """Ligne compacte d'une collectivité : rattachements et fournisseurs par catégorie."""
    statuts = {cle: _statut(organisation.score, cat) for cle, cat in CATEGORIES.items()}
    fournisseurs = fournisseurs_par_categorie(organisation.constats)
    for cle, statut in statuts.items():
        # Catégorie non évaluée : liste vide, le statut dit pourquoi
        if statut != "evalue" and cle != "hebergement":
            fournisseurs[cle] = []
    return {
        "id": organisation.slug,
        "nom": organisation.nom,
        "type": organisation.type,
        "region": organisation.region,
        "departement": organisation.departement,
        "population": organisation.population,
        "tranche_population": (
            code_tranche(organisation.population) if organisation.type == "commune" else None
        ),
        "fournisseurs": fournisseurs,
        "statuts": statuts,
    }


def construire_export(
    organisations: Iterable[OrganisationExport],
    referentiels: Referentiels,
    noms_regions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Contenu de `simulations.json` (collectivités de l'observatoire seulement)."""
    observatoire = [o for o in organisations if o.type != "sur_demande"]
    lignes = [ligne_simulation(o) for o in sorted(observatoire, key=lambda o: o.slug)]
    presences: dict[str, int] = {}
    evaluees = applicables = 0
    for ligne in lignes:
        identifiants = {
            f for liste in ligne["fournisseurs"].values() for f in liste if f != INCONNU
        }
        for identifiant in identifiants:
            presences[identifiant] = presences.get(identifiant, 0) + 1
        for statut in ligne["statuts"].values():
            if statut != "sans_objet":
                applicables += 1
                evaluees += statut == "evalue"
    fournisseurs: dict[str, dict[str, Any]] = {}
    for identifiant in sorted(presences):
        fournisseur = referentiels.fournisseurs.get(identifiant)
        if fournisseur is None:
            continue
        fournisseurs[identifiant] = {
            "id": identifiant,
            "nom": fournisseur.nom,
            "pays": fournisseur.pays_siege,
            "niveau": niveau_juridiction(fournisseur),
            "soumis_cloud_act": fournisseur.soumis_cloud_act,
            "statut_referentiel": "a_verifier" if fournisseur.a_verifier else "verifie",
            "nombre_collectivites": presences[identifiant],
        }
    dates = [o.date_scan for o in observatoire]
    regions = sorted({o.region for o in observatoire if o.region})
    return {
        "meta": {
            "date_donnees": max(dates).isoformat() if dates else None,
            "version_methodo": VERSION_METHODO,
            "nombre_collectivites": len(lignes),
            "part_criteres_non_evalues": (
                round(100 * (applicables - evaluees) / applicables, 1) if applicables else 0.0
            ),
            "regions": {code: (noms_regions or {}).get(code, code) for code in regions},
            "tranches_population": {
                f"{minimum}-{maximum or ''}": libelle_tranche(minimum, maximum)
                for minimum, maximum in TRANCHES_POPULATION
            },
        },
        "fournisseurs": fournisseurs,
        "collectivites": lignes,
    }


def ecrire_export(chemin: Path, contenu: Mapping[str, Any]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(contenu, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Moteur (même règles que site/src/lib/simulation.ts)
# --------------------------------------------------------------------------- #


def _etat(liste: Sequence[str], tombes: set[str]) -> Literal["coupe", "partiel", "ok"]:
    touches = [f for f in liste if f in tombes]
    if touches and len(touches) == len(liste):
        return "coupe"
    return "partiel" if touches else "ok"


def evaluer(ligne: Mapping[str, Any], tombes: set[str]) -> dict[str, str]:
    """Impact sur une collectivité quand les fournisseurs `tombes` ne répondent plus.

    - DNS : tous les opérateurs tombés → site et messagerie injoignables (effet domino) ;
      une partie seulement → « résilient » ;
    - CDN tombé → site hors ligne ; hébergement : tout tombé → hors ligne, une partie →
      dégradé ;
    - messagerie : tout tombé → coupée, une partie → dégradée ;
    - services tiers ou mesure d'audience tombés → site dégradé (jamais hors ligne) ;
    - catégorie non évaluée : « inconnu », jamais comptée comme touchée.
    """
    fournisseurs, statuts = ligne["fournisseurs"], ligne["statuts"]

    if statuts["dns"] == "evalue":
        etat_dns = _etat(fournisseurs["dns"], tombes)
        dns = {"coupe": "coupe", "partiel": "resilient", "ok": "ok"}[etat_dns]
    else:
        dns = "inconnu"

    if dns == "coupe":
        site = "injoignable"
    elif any(f in tombes for f in fournisseurs["cdn"]):
        site = "hors_ligne"
    elif statuts["hebergement"] == "evalue":
        etat = _etat(fournisseurs["hebergement"], tombes)
        site = {"coupe": "hors_ligne", "partiel": "degrade", "ok": "ok"}[etat]
    else:
        site = "inconnu"
    tiers = [
        f
        for cle in ("services_tiers", "audience")
        if statuts[cle] == "evalue"
        for f in fournisseurs[cle]
    ]
    if site in ("ok", "inconnu") and any(f in tombes for f in tiers):
        site = "degrade"

    if statuts["messagerie"] == "sans_objet":
        messagerie = "sans_objet"
    elif dns == "coupe":
        messagerie = "coupee"
    elif statuts["messagerie"] == "evalue":
        etat = _etat(fournisseurs["messagerie"], tombes)
        messagerie = {"coupe": "coupee", "partiel": "degradee", "ok": "ok"}[etat]
    else:
        messagerie = "inconnu"

    statut: StatutFinal
    if dns == "coupe":
        statut = "injoignable"
    elif site == "hors_ligne" or messagerie == "coupee":
        statut = "hors_service"
    elif site == "degrade" or messagerie == "degradee":
        statut = "degrade"
    elif "inconnu" in (dns, site, messagerie):
        statut = "indetermine"
    else:
        statut = "non_touchee"
    return {"statut": statut, "dns": dns, "site": site, "messagerie": messagerie}


def fournisseurs_tombes(
    export: Mapping[str, Any], scenario: str, fournisseur: str | None = None
) -> set[str]:
    """Fournisseurs hors service selon le scénario : « panne » d'un fournisseur ou
    « cloud_act » (tous les fournisseurs soumis au Cloud Act)."""
    if scenario == "cloud_act":
        return {f["id"] for f in export["fournisseurs"].values() if f["soumis_cloud_act"]}
    return {fournisseur} if fournisseur else set()


def agreger(lignes: Sequence[Mapping[str, Any]], tombes: set[str]) -> dict[str, Any]:
    """Totaux d'une simulation (jamais de liste nominative)."""
    par_statut = dict.fromkeys(
        ("injoignable", "hors_service", "degrade", "indetermine", "non_touchee"), 0
    )
    resultat: dict[str, Any] = {
        "total": len(lignes),
        "touchees": 0,
        "sites_hors_ligne": 0,
        "messageries_coupees": 0,
        "sites_degrades": 0,
        "injoignables": 0,
        "dns_resilients": 0,
        "habitants_touches": 0,
        "habitants_total": 0,
        "departements_touches": 0,
        "regions_touchees": 0,
        "par_statut": par_statut,
        "par_region": {},
        "par_tranche": {},
    }
    for ligne in lignes:
        impact = evaluer(ligne, tombes)
        touchee = impact["statut"] in STATUTS_TOUCHES
        par_statut[impact["statut"]] += 1
        resultat["touchees"] += touchee
        resultat["sites_hors_ligne"] += impact["site"] in ("injoignable", "hors_ligne")
        resultat["messageries_coupees"] += impact["messagerie"] == "coupee"
        resultat["sites_degrades"] += impact["site"] == "degrade"
        resultat["injoignables"] += impact["statut"] == "injoignable"
        resultat["dns_resilients"] += impact["dns"] == "resilient"
        if ligne["type"] == "commune" and ligne.get("population"):
            resultat["habitants_total"] += ligne["population"]
            if touchee:
                resultat["habitants_touches"] += ligne["population"]
        if touchee and ligne["type"] == "departement":
            resultat["departements_touches"] += 1
        if touchee and ligne["type"] == "region":
            resultat["regions_touchees"] += 1
        for cle, code in (
            ("par_region", ligne.get("region")),
            ("par_tranche", ligne.get("tranche_population")),
        ):
            if code:
                groupe = resultat[cle].setdefault(code, {"total": 0, "touchees": 0})
                groupe["total"] += 1
                groupe["touchees"] += touchee
    return resultat


def lire_prereglages(chemin: Path = CHEMIN_PREREGLAGES) -> list[dict[str, Any]]:
    """Préréglages éditoriaux du simulateur (slug, titre, scénario, fournisseur…)."""
    contenu: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
    return list(contenu["prereglages"])


def lire_export(chemin: Path) -> dict[str, Any]:
    contenu: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
    return contenu


def date_donnees(export: Mapping[str, Any]) -> datetime | None:
    valeur = export["meta"].get("date_donnees")
    return datetime.fromisoformat(valeur) if valeur else None
