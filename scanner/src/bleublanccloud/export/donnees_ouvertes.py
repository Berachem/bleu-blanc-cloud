"""Données ouvertes : fichiers CSV publiés à chaque campagne (data.gouv.fr, Licence Ouverte 2.0).

- organisations.csv : une ligne par collectivité de l'observatoire (hors analyses sur demande) ;
- departements.csv : agrégats par département.

Le site les sert à une adresse fixe (https://<domaine>/donnees/…) : data.gouv.fr y pointe et
récupère toujours la dernière version. Aucune donnée personnelle (ni e-mail, ni téléphone, ni
nom de personne) : uniquement l'infrastructure technique visible publiquement.

Les colonnes et leur description sont définies ici une seule fois : l'en-tête du CSV et la
documentation (docs/donnees-ouvertes.md, vérifiée par les tests) en découlent.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from bleublanccloud.modeles import DepartementExport, OrganisationExport, ScoreCategorie
from bleublanccloud.prospection import code_insee_du_slug

SEPARATEUR_LISTE = " | "
CATEGORIES = (
    "hebergement",
    "messagerie",
    "dns",
    "suites_saas",
    "services_tiers",
    "mesure_audience",
)
CATEGORIES_FOURNISSEURS = ("hebergement", "messagerie", "dns")
CATEGORIES_SERVICES = ("suites_saas", "services_tiers", "mesure_audience")

COLONNES_ORGANISATIONS: tuple[tuple[str, str], ...] = (
    ("slug", "Identifiant de la fiche sur le site (stable d'une campagne à l'autre)."),
    ("nom", "Nom de la collectivité."),
    ("type", "commune, departement ou region."),
    ("code_insee", "Code officiel géographique de la commune (vide pour les autres types)."),
    ("code_departement", "Code du département."),
    ("departement", "Nom du département."),
    ("code_region", "Code de la région."),
    ("region", "Nom de la région."),
    ("population", "Population municipale (geo.api.gouv.fr), vide si inconnue."),
    ("domaine", "Nom de domaine analysé (site web officiel)."),
    ("score", "Score global de 0 à 100 (100 : uniquement des fournisseurs européens)."),
    ("note", "Note de A à E (A ≥ 85, B ≥ 70, C ≥ 50, D ≥ 30, E < 30)."),
    (
        "note_provisoire",
        "true si plus de 30 % du poids applicable n'a pas pu être évalué (fournisseurs "
        "non identifiés) : note à interpréter avec prudence.",
    ),
    ("couverture", "Part du poids applicable effectivement évaluée, en %."),
    *(
        (
            f"score_{categorie}",
            f"Score de la catégorie « {categorie} » sur 100 (vide si non évaluable).",
        )
        for categorie in CATEGORIES
    ),
    *(
        (
            f"fournisseurs_{categorie}",
            f"Fournisseur(s) identifié(s) pour la catégorie « {categorie} », séparés par « | ».",
        )
        for categorie in CATEGORIES_FOURNISSEURS
    ),
    (
        "services_hors_ue",
        "Suites collaboratives, services tiers et mesure d'audience de fournisseurs soumis "
        "au Cloud Act ou à une loi équivalente (niveau D), séparés par « | ».",
    ),
    ("date_analyse", "Date et heure de l'analyse (UTC, ISO 8601)."),
    ("version_methodologie", "Version de la méthodologie de calcul."),
    ("url_fiche", "Page détaillée sur le site, avec les constats et leurs preuves."),
)

COLONNES_DEPARTEMENTS: tuple[tuple[str, str], ...] = (
    ("code", "Code du département."),
    ("nom", "Nom du département."),
    ("code_region", "Code de la région."),
    ("nombre_organisations", "Nombre de collectivités analysées dans le département."),
    ("score_moyen", "Score moyen de ces collectivités (0 à 100)."),
    ("note_moyenne", "Note correspondant au score moyen."),
    *((f"nombre_note_{note}", f"Nombre de collectivités notées {note}.") for note in "ABCDE"),
)


def _liste(valeurs: Sequence[str]) -> str:
    vues: list[str] = []
    for valeur in valeurs:
        if valeur and valeur not in vues:
            vues.append(valeur)
    return SEPARATEUR_LISTE.join(vues)


def _nombre(valeur: float | None) -> str:
    if valeur is None:
        return ""
    return str(int(valeur)) if float(valeur).is_integer() else f"{valeur:.1f}"


def ligne_organisation(organisation: OrganisationExport, url_site: str) -> dict[str, str]:
    score = organisation.score
    par_categorie: dict[str, ScoreCategorie] = {str(c.categorie): c for c in score.detail}
    ligne = {
        "slug": organisation.slug,
        "nom": organisation.nom,
        "type": organisation.type,
        "code_insee": (code_insee_du_slug(organisation.slug) or "")
        if organisation.type == "commune"
        else "",
        "code_departement": organisation.departement or "",
        "departement": organisation.departement_nom or "",
        "code_region": organisation.region or "",
        "region": organisation.region_nom or "",
        "population": str(organisation.population) if organisation.population else "",
        "domaine": organisation.domaine,
        "score": str(score.score_global),
        "note": score.note,
        "note_provisoire": "true" if score.provisoire else "false",
        "couverture": _nombre(score.couverture),
        "date_analyse": organisation.date_scan.isoformat(),
        "version_methodologie": score.version_methodo,
        "url_fiche": f"{url_site}/organisation/{organisation.slug}/",
    }
    for categorie in CATEGORIES:
        detail = par_categorie.get(categorie)
        ligne[f"score_{categorie}"] = (
            _nombre(detail.score) if detail is not None and detail.evaluable else ""
        )
    for categorie in CATEGORIES_FOURNISSEURS:
        ligne[f"fournisseurs_{categorie}"] = _liste(
            [
                organisation.fournisseurs[c.fournisseur_id].nom
                for c in organisation.constats
                if c.categorie == categorie
                and c.fournisseur_id
                and c.fournisseur_id in organisation.fournisseurs
            ]
        )
    ligne["services_hors_ue"] = _liste(
        [
            c.valeur
            for c in organisation.constats
            if c.categorie in CATEGORIES_SERVICES and c.niveau == "D"
        ]
    )
    return ligne


def ligne_departement(departement: DepartementExport) -> dict[str, str]:
    return {
        "code": departement.code,
        "nom": departement.nom,
        "code_region": departement.region or "",
        "nombre_organisations": str(departement.nombre_organisations),
        "score_moyen": _nombre(departement.score_moyen),
        "note_moyenne": departement.note_moyenne or "",
        **{
            f"nombre_note_{note}": str(departement.repartition_notes.get(note, 0))
            for note in "ABCDE"
        },
    }


def _ecrire_csv(
    chemin: Path, colonnes: tuple[tuple[str, str], ...], lignes: list[dict[str, str]]
) -> None:
    # UTF-8, séparateur virgule, fin de ligne \n : format recommandé pour data.gouv.fr
    with chemin.open("w", encoding="utf-8", newline="") as fichier:
        ecrivain = csv.DictWriter(
            fichier, fieldnames=[nom for nom, _ in colonnes], lineterminator="\n"
        )
        ecrivain.writeheader()
        ecrivain.writerows(lignes)


def ecrire_donnees_ouvertes(
    dossier: Path,
    observatoire: Sequence[OrganisationExport],
    departements: Sequence[DepartementExport],
    url_site: str,
) -> list[Path]:
    """Écrit organisations.csv et departements.csv (tri stable : par slug, par code)."""
    organisations = dossier / "organisations.csv"
    _ecrire_csv(
        organisations,
        COLONNES_ORGANISATIONS,
        [ligne_organisation(o, url_site) for o in sorted(observatoire, key=lambda o: o.slug)],
    )
    chemin_departements = dossier / "departements.csv"
    _ecrire_csv(
        chemin_departements,
        COLONNES_DEPARTEMENTS,
        [ligne_departement(d) for d in sorted(departements, key=lambda d: d.code)],
    )
    return [organisations, chemin_departements]
