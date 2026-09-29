"""Découpage administratif via l'API geo.api.gouv.fr (communes, départements, régions).

Licence Ouverte / Open Licence. Documentation : https://geo.api.gouv.fr/decoupage-administratif
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

URL_GEO = "https://geo.api.gouv.fr"


class CommuneGeo(BaseModel):
    code: str
    nom: str
    population: int | None = None
    code_departement: str | None = Field(default=None, alias="codeDepartement")
    code_region: str | None = Field(default=None, alias="codeRegion")


class TerritoireGeo(BaseModel):
    code: str
    nom: str
    code_region: str | None = Field(default=None, alias="codeRegion")


async def _obtenir(client: httpx.AsyncClient, chemin: str, params: dict[str, str]) -> Any:
    reponse = await client.get(f"{URL_GEO}{chemin}", params=params)
    reponse.raise_for_status()
    return reponse.json()


async def telecharger_communes(client: httpx.AsyncClient) -> list[CommuneGeo]:
    """Toutes les communes (sans géométrie) avec population, département et région."""
    donnees = await _obtenir(
        client,
        "/communes",
        {"fields": "nom,code,population,codeDepartement,codeRegion", "format": "json"},
    )
    return [CommuneGeo.model_validate(c) for c in donnees]


async def telecharger_departements(client: httpx.AsyncClient) -> list[TerritoireGeo]:
    donnees = await _obtenir(client, "/departements", {"fields": "nom,code,codeRegion"})
    return [TerritoireGeo.model_validate(d) for d in donnees]


async def telecharger_regions(client: httpx.AsyncClient) -> list[TerritoireGeo]:
    donnees = await _obtenir(client, "/regions", {"fields": "nom,code"})
    return [TerritoireGeo.model_validate(r) for r in donnees]


def filtrer_par_population(communes: list[CommuneGeo], population_min: int) -> list[CommuneGeo]:
    return [c for c in communes if c.population is not None and c.population >= population_min]
