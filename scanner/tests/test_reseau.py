"""Garde réseau : aucune connexion vers localhost ou un réseau privé (protection SSRF)."""

from __future__ import annotations

import httpcore
import httpx
import pytest

from bleublanccloud.sondes.reseau import (
    AdresseNonPublique,
    BackendReseauPublic,
    TransportReseauPublic,
    est_adresse_publique,
)

REPONSE_OK = [b"HTTP/1.1 200 OK\r\n", b"Content-Length: 2\r\n", b"\r\n", b"ok"]


@pytest.mark.parametrize(
    ("adresse", "publique"),
    [
        ("51.91.10.20", True),
        ("2a0a:4580:103f:c0de::2", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),  # métadonnées cloud
        ("100.64.0.1", False),  # CGNAT
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1%eth0", False),
        ("fd00::1", False),
        ("::ffff:192.168.1.1", False),  # IPv4 privée déguisée en IPv6
        ("224.0.0.1", False),
        ("pas-une-ip", False),
    ],
)
def test_est_adresse_publique(adresse: str, publique: bool) -> None:
    assert est_adresse_publique(adresse) is publique


class BackendEspion(httpcore.AsyncMockBackend):
    """Backend simulé qui mémorise les adresses auxquelles on tente de se connecter."""

    def __init__(self) -> None:
        super().__init__(REPONSE_OK)
        self.connexions: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):  # type: ignore[no-untyped-def]  # noqa: ASYNC109
        self.connexions.append(host)
        return await super().connect_tcp(host, port, timeout, local_address, socket_options)


def resolveur(*adresses: str):  # type: ignore[no-untyped-def]
    async def resoudre(hote: str, port: int) -> list[str]:
        return list(adresses)

    return resoudre


async def test_connexion_vers_l_adresse_publique_verifiee() -> None:
    espion = BackendEspion()
    backend = BackendReseauPublic(espion, resolveur("51.91.10.20"))
    async with httpx.AsyncClient(transport=TransportReseauPublic(backend=backend)) as client:
        reponse = await client.get("http://site.exemple.fr/")
    assert reponse.status_code == 200
    # La connexion vise l'adresse contrôlée, jamais une nouvelle résolution du nom
    assert espion.connexions == ["51.91.10.20"]


@pytest.mark.parametrize(
    "adresses",
    [("192.168.1.1",), ("51.91.10.20", "10.0.0.1"), ("::1",)],
    ids=["privee", "une-privee-parmi-publiques", "localhost-ipv6"],
)
async def test_adresse_non_publique_refusee(adresses: tuple[str, ...]) -> None:
    espion = BackendEspion()
    backend = BackendReseauPublic(espion, resolveur(*adresses))
    async with httpx.AsyncClient(transport=TransportReseauPublic(backend=backend)) as client:
        with pytest.raises(httpx.ConnectError, match="non publique"):
            await client.get("http://piege.exemple.fr/")
    assert espion.connexions == []


async def test_ip_litterale_privee_refusee_sans_resolution_externe() -> None:
    # Une URL http://127.0.0.1/ (ex. redirection piégée) est refusée par la garde
    backend = BackendReseauPublic(BackendEspion())
    with pytest.raises(AdresseNonPublique):
        await backend.connect_tcp("127.0.0.1", 80)


async def test_aucune_adresse() -> None:
    backend = BackendReseauPublic(BackendEspion(), resolveur())
    with pytest.raises(httpcore.ConnectError, match="aucune adresse"):
        await backend.connect_tcp("vide.exemple.fr", 443)


async def test_socket_unix_refusee() -> None:
    with pytest.raises(AdresseNonPublique):
        await BackendReseauPublic(BackendEspion()).connect_unix_socket("/run/docker.sock")
