"""Mode en ligne du serveur MCP (HTTP « streamable »), pour Le Chat, claude.ai et tout client
qui se connecte à une adresse web plutôt que de lancer un programme local.

Hébergé chez alwaysdata (site « Programme utilisateur ») : la plateforme fournit le port dans
la variable PORT ; le serveur écoute en IPv6 (« :: »). Lecture seule, sans compte ni cookie :
seules les données déjà publiques du site sont lues.

Protections :
- seuls les noms d'hôte listés dans MCP_HOTES_AUTORISES sont acceptés (protection contre le
  « DNS rebinding ») ;
- limite de requêtes par adresse IP (MCP_REQUETES_PAR_MINUTE, 60 par défaut) et globale
  (10 fois plus), réponse 429 au-delà ;
- mode sans état (« stateless ») : aucune session conservée en mémoire.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

from bleublanccloud_mcp import __version__
from bleublanccloud_mcp.serveur import serveur

Portee = MutableMapping[str, Any]
Recevoir = Callable[[], Awaitable[MutableMapping[str, Any]]]
Envoyer = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ApplicationAsgi = Callable[[Portee, Recevoir, Envoyer], Awaitable[None]]

HOTES_PAR_DEFAUT = "bleublancloud.alwaysdata.net"
CHEMIN_MCP = "/mcp"


class LimiteurRequetes:
    """Fenêtre glissante d'une minute, par adresse IP et au total."""

    def __init__(self, par_minute: int, horloge: Callable[[], float] = time.monotonic) -> None:
        self.par_minute = par_minute
        self.global_par_minute = par_minute * 10
        self.horloge = horloge
        self._par_ip: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    @staticmethod
    def _purger(fenetre: deque[float], seuil: float) -> None:
        while fenetre and fenetre[0] <= seuil:
            fenetre.popleft()

    def autoriser(self, ip: str) -> bool:
        maintenant = self.horloge()
        seuil = maintenant - 60
        self._purger(self._global, seuil)
        fenetre = self._par_ip.setdefault(ip, deque())
        self._purger(fenetre, seuil)
        if len(fenetre) >= self.par_minute or len(self._global) >= self.global_par_minute:
            return False
        fenetre.append(maintenant)
        self._global.append(maintenant)
        if len(self._par_ip) > 10_000:  # mémoire bornée : on oublie les adresses inactives
            self._par_ip = {k: v for k, v in self._par_ip.items() if v}
        return True


def adresse_client(portee: Portee) -> str:
    """IP du visiteur : première adresse de X-Forwarded-For (proxy de l'hébergeur)."""
    for nom, valeur in portee.get("headers", []):
        if nom == b"x-forwarded-for":
            return str(valeur.decode("latin-1").split(",")[0].strip())
    client = portee.get("client")
    return str(client[0]) if client else "inconnue"


async def _repondre_json(envoyer: Envoyer, statut: int, corps: dict[str, Any]) -> None:
    donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8")
    entetes = [(b"content-type", b"application/json; charset=utf-8")]
    if statut == 429:
        entetes.append((b"retry-after", b"60"))
    await envoyer({"type": "http.response.start", "status": statut, "headers": entetes})
    await envoyer({"type": "http.response.body", "body": donnees})


def proteger(application: ApplicationAsgi, limiteur: LimiteurRequetes) -> ApplicationAsgi:
    """Page d'accueil informative sur « / » et limite de requêtes sur le reste."""

    async def protegee(portee: Portee, recevoir: Recevoir, envoyer: Envoyer) -> None:
        if portee["type"] != "http":
            await application(portee, recevoir, envoyer)
            return
        if portee["path"] == "/" and portee["method"] in ("GET", "HEAD"):
            await _repondre_json(
                envoyer,
                200,
                {
                    "service": "Serveur MCP Bleu Blanc Cloud (lecture seule)",
                    "version": __version__,
                    "point_d_acces": CHEMIN_MCP,
                    "documentation": "https://bleublanccloud.fr/mcp/",
                },
            )
            return
        if not limiteur.autoriser(adresse_client(portee)):
            await _repondre_json(
                envoyer, 429, {"erreur": "Trop de requêtes : réessayez dans une minute."}
            )
            return
        await application(portee, recevoir, envoyer)

    return protegee


def creer_application(
    hotes: list[str] | None = None, requetes_par_minute: int | None = None
) -> ApplicationAsgi:
    """Application ASGI complète (MCP en HTTP + protections), configurée par l'environnement."""
    hotes = hotes or [
        h.strip()
        for h in os.environ.get("MCP_HOTES_AUTORISES", HOTES_PAR_DEFAUT).split(",")
        if h.strip()
    ]
    par_minute = requetes_par_minute or int(os.environ.get("MCP_REQUETES_PAR_MINUTE", "60"))
    application = serveur.streamable_http_app(
        streamable_http_path=CHEMIN_MCP,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[*hotes, *(f"{h}:*" for h in hotes)],
            allowed_origins=["https://chat.mistral.ai", "https://claude.ai"],
        ),
    )
    return proteger(application, LimiteurRequetes(par_minute))


def principal() -> None:
    """Point d'entrée « bleublanccloud-mcp-http » (alwaysdata : IP et PORT fournis)."""
    import uvicorn

    uvicorn.run(
        creer_application(),
        host=os.environ.get("IP", "::"),
        port=int(os.environ.get("PORT", "8100")),
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level="info",
    )
