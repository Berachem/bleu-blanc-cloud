"""Chargement et validation des référentiels YAML (fournisseurs, règles, alternatives, retraits)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from bleublanccloud.configuration import DOSSIER_REFERENTIELS
from bleublanccloud.modeles import Alternative, Fournisseur, RegleDetection, Retrait


class ErreurReferentiel(ValueError):
    """Référentiel invalide (doublon, référence inconnue, champ manquant…)."""


@dataclass(frozen=True)
class Referentiels:
    """Ensemble des référentiels chargés en mémoire."""

    fournisseurs: dict[str, Fournisseur]
    regles: list[RegleDetection]
    alternatives: dict[str, Alternative]
    retraits: dict[str, Retrait]

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
    """Charge et valide les quatre référentiels d'un dossier."""
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

    _verifier_unicite([f.id for f in fournisseurs], "fournisseurs.yaml")
    _verifier_unicite([r.id for r in regles], "regles_detection.yaml")
    _verifier_unicite([a.id for a in alternatives], "alternatives.yaml")

    index_fournisseurs = {f.id: f for f in fournisseurs}
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
    )


@lru_cache(maxsize=1)
def referentiels_par_defaut() -> Referentiels:
    """Référentiels du paquet, chargés une seule fois."""
    return charger_referentiels()
