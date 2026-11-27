"""Hôpitaux publics : centres hospitaliers universitaires (CHU) et régionaux, puis établissements
supports des groupements hospitaliers de territoire (GHT), d'après la liste tenue à la main
`referentiels/hopitaux.yaml` (une source par établissement), voir ADR-0006.

La base FINESS compte des milliers d'établissements, sans site web : pour une première
catégorie restreinte (une trentaine de CHU), une liste relue et sourcée est plus fiable.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, HttpUrl

from bleublanccloud.cibles.importation import slugifier
from bleublanccloud.configuration import DOSSIER_REFERENTIELS
from bleublanccloud.modeles import Organisation

CHEMIN_HOPITAUX = DOSSIER_REFERENTIELS / "hopitaux.yaml"
SOURCE = "referentiel:hopitaux.yaml"


class Hopital(BaseModel):
    nom: str
    ville: str
    departement: str = Field(pattern=r"^(\d{2}|2[AB]|97\d)$")
    site_web: HttpUrl
    sources: list[HttpUrl] = Field(min_length=1)
    remarque: str | None = None
    a_verifier: bool = True


def charger_hopitaux(chemin: Path = CHEMIN_HOPITAUX) -> list[Hopital]:
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8")) or []
    return [Hopital.model_validate(entree) for entree in donnees]


def slug_hopital(hopital: Hopital) -> str:
    """« CHU de Nantes » → chu-de-nantes ; préfixe « hopital- » si le nom ne dit pas déjà
    CHU/CHR/hôpital (« Hôpital Nord-Ouest » → hopital-nord-ouest, sans doublon)."""
    slug = slugifier(hopital.nom)
    mots_hopital = ("chu", "chru", "chr", "hopital", "hopitaux", "hospices")
    if not any(mot in slug.split("-") for mot in mots_hopital):
        slug = f"hopital-{slug}"
    return slug


def construire_hopitaux(hopitaux: list[Hopital]) -> list[Organisation]:
    """Une organisation par établissement ; un slug en double est une erreur de la liste."""
    organisations: dict[str, Organisation] = {}
    for hopital in hopitaux:
        slug = slug_hopital(hopital)
        if slug in organisations:
            raise ValueError(f"hopitaux.yaml : slug en double « {slug} »")
        organisations[slug] = Organisation(
            slug=slug,
            nom=hopital.nom,
            type="hopital",
            departement=hopital.departement,
            site_web=str(hopital.site_web),
            source=SOURCE,
        )
    return sorted(organisations.values(), key=lambda o: o.slug)
