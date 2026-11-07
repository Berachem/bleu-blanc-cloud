"""Accès aux données publiées par le site (fichiers statiques, lecture seule).

Le serveur ne lance jamais d'analyse : il lit les fichiers que le site publie à chaque
campagne (index, fiches, départements, alternatives, CSV des données ouvertes, méthodologie),
avec un cache en mémoire pour ne pas solliciter le site à chaque question.
"""

from __future__ import annotations

import csv
import io
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from bleublanccloud_mcp import __version__

URL_PAR_DEFAUT = "https://bleublanccloud.fr"
DUREE_CACHE_S = 3600.0
MOTIF_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")


class DonneeIntrouvable(LookupError):
    """La ressource demandée n'existe pas sur le site (slug inconnu, fichier absent)."""


def url_site() -> str:
    """Adresse du site lu (variable BLEUBLANCCLOUD_URL, pour un miroir ou un site local)."""
    return os.environ.get("BLEUBLANCCLOUD_URL", URL_PAR_DEFAUT).rstrip("/")


@dataclass
class SourceDonnees:
    """Lecture des fichiers publiés, avec cache (une heure par défaut)."""

    base: str = field(default_factory=url_site)
    duree_cache_s: float = DUREE_CACHE_S
    client: httpx.AsyncClient | None = None
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict)

    def _client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=20,
                follow_redirects=True,
                headers={"User-Agent": f"BleuBlancCloudMCP/{__version__} (+{self.base}/mcp/)"},
            )
        return self.client

    async def _lire(self, chemin: str, format_: str) -> Any:
        maintenant = time.monotonic()
        en_cache = self._cache.get(chemin)
        if en_cache and maintenant - en_cache[0] < self.duree_cache_s:
            return en_cache[1]
        reponse = await self._client().get(f"{self.base}{chemin}")
        if reponse.status_code == 404:
            raise DonneeIntrouvable(chemin)
        reponse.raise_for_status()
        valeur: Any
        if format_ == "json":
            valeur = reponse.json()
        elif format_ == "csv":
            valeur = list(csv.DictReader(io.StringIO(reponse.text)))
        else:
            valeur = reponse.text
        self._cache[chemin] = (maintenant, valeur)
        return valeur

    async def meta(self) -> dict[str, Any]:
        resultat: dict[str, Any] = await self._lire("/donnees/meta.json", "json")
        return resultat

    async def index(self) -> list[dict[str, Any]]:
        resultat: list[dict[str, Any]] = await self._lire("/donnees/index.json", "json")
        return resultat

    async def departements(self) -> list[dict[str, Any]]:
        resultat: list[dict[str, Any]] = await self._lire("/donnees/departements.json", "json")
        return resultat

    async def alternatives(self) -> list[dict[str, Any]]:
        resultat: list[dict[str, Any]] = await self._lire("/donnees/alternatives.json", "json")
        return resultat

    async def organisations_csv(self) -> list[dict[str, str]]:
        """Données ouvertes : fournisseurs par catégorie pour toutes les collectivités."""
        resultat: list[dict[str, str]] = await self._lire("/donnees/organisations.csv", "csv")
        return resultat

    async def fiche(self, slug: str) -> dict[str, Any]:
        if not MOTIF_SLUG.match(slug):
            raise DonneeIntrouvable(slug)
        resultat: dict[str, Any] = await self._lire(f"/donnees/organisations/{slug}.json", "json")
        return resultat

    async def methodologie(self) -> str:
        resultat: str = await self._lire("/methodologie.md", "texte")
        return resultat
