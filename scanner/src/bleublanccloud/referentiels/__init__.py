"""Chargement et validation des référentiels YAML (fournisseurs, transitaires, règles,
alternatives, retraits)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from bleublanccloud.configuration import DOSSIER_REFERENTIELS
from bleublanccloud.modeles import Alternative, Fournisseur, RegleDetection, Retrait, Transitaire


class ErreurReferentiel(ValueError):
    """Référentiel invalide (doublon, référence inconnue, champ manquant…)."""


@dataclass(frozen=True)
class Referentiels:
    """Ensemble des référentiels chargés en mémoire."""

    fournisseurs: dict[str, Fournisseur]
    regles: list[RegleDetection]
    alternatives: dict[str, Alternative]
    retraits: dict[str, Retrait]
    transitaires: dict[str, Transitaire] = field(default_factory=dict)

    def est_retire(self, nom_hote: str) -> bool:
        """Indique si un nom d'hôte (ou l'un de ses domaines parents) a demandé son retrait."""
        nom = nom_hote.lower().rstrip(".")
        return any(nom == domaine or nom.endswith("." + domaine) for domaine in self.retraits)


def _lire_yaml(chemin: Path) -> list[dict[str, Any]]:
    contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    if contenu is None:
        return []
    if not isinstance(contenu, list):
        raise ErreurReferentiel(f"{chemin.name} doit contenir une liste YAML.")
    return contenu


def _verifier_unicite(identifiants: list[str], nom_fichier: str) -> None:
    vus: set[str] = set()
    for identifiant in identifiants:
        if identifiant in vus:
            raise ErreurReferentiel(f"Identifiant en double dans {nom_fichier} : {identifiant}")
        vus.add(identifiant)


def charger_referentiels(dossier: Path = DOSSIER_REFERENTIELS) -> Referentiels:
    """Charge et valide les référentiels d'un dossier (transitaires.yaml est facultatif)."""
    fournisseurs = TypeAdapter(list[Fournisseur]).validate_python(
        _lire_yaml(dossier / "fournisseurs.yaml")
    )
    regles = TypeAdapter(list[RegleDetection]).validate_python(
        _lire_yaml(dossier / "regles_detection.yaml")
    )
    alternatives = TypeAdapter(list[Alternative]).validate_python(
        _lire_yaml(dossier / "alternatives.yaml")
    )
    retraits = TypeAdapter(list[Retrait]).validate_python(_lire_yaml(dossier / "retraits.yaml"))
    fichier_transitaires = dossier / "transitaires.yaml"
    transitaires = (
        TypeAdapter(list[Transitaire]).validate_python(_lire_yaml(fichier_transitaires))
        if fichier_transitaires.is_file()
        else []
    )

    _verifier_unicite([f.id for f in fournisseurs], "fournisseurs.yaml")
    _verifier_unicite([r.id for r in regles], "regles_detection.yaml")
    _verifier_unicite([a.id for a in alternatives], "alternatives.yaml")
    _verifier_unicite([t.id for t in transitaires], "transitaires.yaml")

    index_fournisseurs = {f.id: f for f in fournisseurs}
    proprietaires_asn: dict[int, str] = {}
    for fournisseur in fournisseurs:
        for asn in [*fournisseur.asn, *fournisseur.asn_cdn]:
            if asn in proprietaires_asn and proprietaires_asn[asn] != fournisseur.id:
                raise ErreurReferentiel(
                    f"AS{asn} rattaché à deux fournisseurs : "
                    f"{proprietaires_asn[asn]} et {fournisseur.id}."
                )
            proprietaires_asn[asn] = fournisseur.id
        for motif in [*fournisseur.motifs_nom_as, *fournisseur.exclusions_nom_as]:
            try:
                re.compile(motif)
            except re.error as erreur:
                raise ErreurReferentiel(
                    f"Fournisseur {fournisseur.id} : motif de nom d'AS invalide « {motif} »."
                ) from erreur
    transit_asn: dict[int, str] = {}
    for transitaire in transitaires:
        for asn in transitaire.asn:
            if asn in proprietaires_asn:
                raise ErreurReferentiel(
                    f"AS{asn} déclaré à la fois comme transitaire ({transitaire.id}) et comme "
                    f"fournisseur ({proprietaires_asn[asn]})."
                )
            if asn in transit_asn:
                raise ErreurReferentiel(
                    f"AS{asn} rattaché à deux transitaires : "
                    f"{transit_asn[asn]} et {transitaire.id}."
                )
            transit_asn[asn] = transitaire.id
    for regle in regles:
        if regle.fournisseur_id is not None and regle.fournisseur_id not in index_fournisseurs:
            raise ErreurReferentiel(
                f"Règle {regle.id} : fournisseur inconnu « {regle.fournisseur_id} »."
            )
        for autre in regle.incompatible_avec:
            if autre not in {r.id for r in regles}:
                raise ErreurReferentiel(
                    f"Règle {regle.id} : règle incompatible inconnue « {autre} »."
                )
        if regle.fournisseur_id is None and regle.niveau is None:
            raise ErreurReferentiel(
                f"Règle {regle.id} : sans fournisseur, un niveau explicite est obligatoire."
            )

    return Referentiels(
        fournisseurs=index_fournisseurs,
        regles=regles,
        alternatives={a.id: a for a in alternatives},
        retraits={r.domaine.lower().rstrip("."): r for r in retraits},
        transitaires={t.id: t for t in transitaires},
    )


@lru_cache(maxsize=1)
def referentiels_par_defaut() -> Referentiels:
    """Référentiels du paquet, chargés une seule fois."""
    return charger_referentiels()
