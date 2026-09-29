"""Garde réseau : le robot ne se connecte qu'à des adresses IP publiques.

Le scanner tourne sur un réseau domestique et analyse des domaines qui peuvent être proposés
par n'importe qui (analyses sur demande). Un domaine, une redirection HTTP ou une réponse DNS
changeante (« DNS rebinding ») ne doit jamais l'amener à interroger localhost ou un appareil
du réseau privé (SSRF). La vérification a donc lieu au moment de la connexion, sur l'adresse
effectivement utilisée : le nom est résolu une seule fois, toutes les adresses obtenues
doivent être publiques, puis la connexion est ouverte vers l'une de ces adresses (le nom
d'hôte reste utilisé pour TLS/SNI et l'en-tête Host).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable

import httpcore
import httpx

ResolveurAdresses = Callable[[str, int], Awaitable[list[str]]]

DELAI_RESOLUTION_S = 10.0


class AdresseNonPublique(httpcore.ConnectError):
    """Connexion refusée : le nom résout vers une adresse locale, privée ou réservée."""


def est_adresse_publique(adresse: str) -> bool:
    """Vrai pour une adresse IP routable sur Internet (ni privée, ni locale, ni réservée)."""
    try:
        ip = ipaddress.ip_address(adresse.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resoudre_systeme(hote: str, port: int) -> list[str]:
    """Adresses IP d'un nom d'hôte via le résolveur du système (sans doublon, dans l'ordre)."""
    infos = await asyncio.get_running_loop().getaddrinfo(hote, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def verifier_adresses(hote: str, adresses: Iterable[str]) -> list[str]:
    """Retourne les adresses si elles sont toutes publiques, sinon lève AdresseNonPublique."""
    liste = list(adresses)
    if not liste:
        raise httpcore.ConnectError(f"{hote} : aucune adresse IP")
    refusees = [a for a in liste if not est_adresse_publique(a)]
    if refusees:
        raise AdresseNonPublique(f"{hote} : adresse non publique refusée ({refusees[0]})")
    # IPv4 d'abord (comme le reste du scanner) : un serveur sans IPv6 ne perd pas de temps
    return sorted(liste, key=lambda adresse: ":" in adresse)


async def adresses_publiques(
    hote: str, port: int, resoudre: ResolveurAdresses = resoudre_systeme
) -> list[str]:
    """Résout un nom et vérifie que toutes ses adresses sont publiques."""
    try:
        adresses = await asyncio.wait_for(resoudre(hote, port), timeout=DELAI_RESOLUTION_S)
    except (OSError, TimeoutError) as erreur:
        raise httpcore.ConnectError(f"{hote} : résolution impossible") from erreur
    return verifier_adresses(hote, adresses)


class BackendReseauPublic(httpcore.AsyncNetworkBackend):
    """Backend réseau httpcore qui n'ouvre de connexion que vers des adresses publiques."""

    def __init__(
        self,
        sous_jacent: httpcore.AsyncNetworkBackend | None = None,
        resoudre: ResolveurAdresses = resoudre_systeme,
    ) -> None:
        self._sous_jacent = sous_jacent or httpcore.AnyIOBackend()
        self._resoudre = resoudre

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 (interface httpcore)
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        derniere_erreur: Exception | None = None
        for adresse in await adresses_publiques(host, port, self._resoudre):
            try:
                return await self._sous_jacent.connect_tcp(
                    adresse,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as erreur:
                derniere_erreur = erreur
        assert derniere_erreur is not None
        raise derniere_erreur

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109 (interface httpcore)
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise AdresseNonPublique("socket Unix refusée")

    async def sleep(self, seconds: float) -> None:
        await self._sous_jacent.sleep(seconds)


class TransportReseauPublic(httpx.AsyncHTTPTransport):
    """Transport httpx dont toutes les connexions passent par BackendReseauPublic.

    Les variables d'environnement de proxy sont ignorées : la connexion est directe, pour
    que l'adresse contrôlée soit bien celle du site analysé.
    """

    def __init__(
        self,
        *,
        verify: bool = True,
        http2: bool = True,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        super().__init__(verify=verify, http2=http2, trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=verify, trust_env=False),
            http1=True,
            http2=http2,
            network_backend=backend or BackendReseauPublic(),
        )
