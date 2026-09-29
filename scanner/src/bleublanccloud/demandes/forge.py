"""Client minimal de l'API Forgejo (Codeberg) : tickets, commentaires, étiquettes.

Le jeton (CODEBERG_JETON) n'apparaît jamais dans les journaux ni dans les messages
d'erreur : seuls la méthode, le chemin et le code HTTP sont rapportés.
"""

from __future__ import annotations

import logging
import re
from types import TracebackType
from typing import Any, Final, Protocol

import httpx
from pydantic import SecretStr

from bleublanccloud.demandes.tickets import Ticket

journal = logging.getLogger(__name__)

URL_API_CODEBERG: Final = "https://codeberg.org/api/v1"
MOTIF_DEPOT: Final = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TICKETS_PAR_PAGE: Final = 50
PAGES_MAX: Final = 20


class ErreurForge(Exception):
    """Échec d'un appel à l'API de la forge (réseau, droits, dépôt introuvable…)."""


class Forge(Protocol):
    """Opérations utilisées par le traitement des demandes (réelles ou simulées en test)."""

    depot: str

    async def tickets_ouverts(self) -> list[Ticket]: ...
    async def commenter(self, numero: int, texte: str) -> None: ...
    async def ajouter_etiquette(self, numero: int, nom: str) -> bool: ...
    async def retirer_etiquette(self, numero: int, nom: str) -> None: ...
    async def fermer(self, numero: int) -> None: ...


class ClientForge:
    """Accès aux tickets d'un seul dépôt, authentifié par un jeton aux droits minimaux."""

    def __init__(
        self,
        depot: str,
        jeton: SecretStr,
        url_api: str = URL_API_CODEBERG,
        user_agent: str = "BleuBlancCloudBot/1.0",
        client: httpx.AsyncClient | None = None,
        delai_s: float = 20.0,
    ) -> None:
        if not MOTIF_DEPOT.match(depot):
            raise ValueError(f"dépôt invalide : {depot!r} (attendu : propriétaire/nom)")
        self.depot = depot
        self._client = client or httpx.AsyncClient(timeout=delai_s)
        self._url_depot = f"{url_api.rstrip('/')}/repos/{depot}"
        self._en_tetes = {
            "Authorization": f"token {jeton.get_secret_value()}",
            "Accept": "application/json",
            "User-Agent": user_agent,
        }
        self._etiquettes: dict[str, int] | None = None

    async def __aenter__(self) -> ClientForge:
        return self

    async def __aexit__(
        self,
        type_exception: type[BaseException] | None,
        exception: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self._client.aclose()

    async def _appel(
        self,
        methode: str,
        chemin: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        tolerer_404: bool = False,
    ) -> Any:
        try:
            reponse = await self._client.request(
                methode, self._url_depot + chemin, json=json, params=params, headers=self._en_tetes
            )
        except httpx.HTTPError as erreur:
            raise ErreurForge(f"{methode} {chemin} : {type(erreur).__name__}") from None
        if tolerer_404 and reponse.status_code == 404:
            return None
        if reponse.status_code >= 400:
            raise ErreurForge(f"{methode} {chemin} : HTTP {reponse.status_code}")
        if reponse.status_code == 204 or not reponse.content:
            return None
        try:
            return reponse.json()
        except ValueError:
            raise ErreurForge(f"{methode} {chemin} : réponse illisible") from None

    async def tickets_ouverts(self) -> list[Ticket]:
        """Tickets ouverts du dépôt (hors demandes de fusion), toutes pages confondues."""
        tickets: list[Ticket] = []
        for page in range(1, PAGES_MAX + 1):
            lot = await self._appel(
                "GET",
                "/issues",
                params={
                    "state": "open",
                    "type": "issues",
                    "limit": TICKETS_PAR_PAGE,
                    "page": page,
                },
            )
            if not isinstance(lot, list):
                raise ErreurForge("GET /issues : liste attendue")
            for element in lot:
                ticket = _lire_ticket(element)
                if ticket is not None:
                    tickets.append(ticket)
            if len(lot) < TICKETS_PAR_PAGE:
                break
        return tickets

    async def _id_etiquette(self, nom: str) -> int | None:
        if self._etiquettes is None:
            etiquettes = await self._appel("GET", "/labels", params={"limit": 100})
            self._etiquettes = {
                str(e.get("name", "")).casefold(): int(e["id"])
                for e in etiquettes or []
                if isinstance(e, dict) and isinstance(e.get("id"), int)
            }
        return self._etiquettes.get(nom.casefold())

    async def commenter(self, numero: int, texte: str) -> None:
        await self._appel("POST", f"/issues/{int(numero)}/comments", json={"body": texte})

    async def ajouter_etiquette(self, numero: int, nom: str) -> bool:
        """Ajoute une étiquette existante du dépôt ; False (avec un avertissement) si absente."""
        identifiant = await self._id_etiquette(nom)
        if identifiant is None:
            journal.warning("Étiquette « %s » absente du dépôt %s : à créer.", nom, self.depot)
            return False
        await self._appel("POST", f"/issues/{int(numero)}/labels", json={"labels": [identifiant]})
        return True

    async def retirer_etiquette(self, numero: int, nom: str) -> None:
        identifiant = await self._id_etiquette(nom)
        if identifiant is not None:
            await self._appel(
                "DELETE", f"/issues/{int(numero)}/labels/{identifiant}", tolerer_404=True
            )

    async def fermer(self, numero: int) -> None:
        await self._appel("PATCH", f"/issues/{int(numero)}", json={"state": "closed"})


def _lire_ticket(element: Any) -> Ticket | None:
    if not isinstance(element, dict) or element.get("pull_request"):
        return None
    numero = element.get("number")
    utilisateur = element.get("user") or {}
    auteur = utilisateur.get("login") if isinstance(utilisateur, dict) else None
    if not isinstance(numero, int) or not isinstance(auteur, str) or not auteur:
        return None
    etiquettes = frozenset(
        str(e.get("name", "")) for e in element.get("labels") or [] if isinstance(e, dict)
    )
    return Ticket(
        numero=numero,
        titre=str(element.get("title") or ""),
        corps=str(element.get("body") or ""),
        auteur=auteur,
        etiquettes=etiquettes,
    )
