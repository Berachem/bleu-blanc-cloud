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

Les icônes (favicon) sont servies par le serveur lui-même : les clients qui affichent l'icône
du domaine du connecteur montrent ainsi le logo Bleu Blanc Cloud, et non celui de l'hébergeur.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from html import escape
from pathlib import Path
from typing import Any

from mcp.server.transport_security import TransportSecuritySettings

from bleublanccloud_mcp import __version__
from bleublanccloud_mcp.serveur import serveur

Portee = MutableMapping[str, Any]
Recevoir = Callable[[], Awaitable[MutableMapping[str, Any]]]
Envoyer = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ApplicationAsgi = Callable[[Portee, Recevoir, Envoyer], Awaitable[None]]

HOTES_PAR_DEFAUT = "mcp.bleublanccloud.fr,bleublancloud.alwaysdata.net"
CHEMIN_MCP = "/mcp"
DOCUMENTATION = "https://bleublanccloud.fr/mcp/"
DOSSIER_STATIQUE = Path(__file__).parent / "statique"
# Chemin demandé → (fichier, type MIME)
ICONES: dict[str, tuple[str, str]] = {
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/icone.png": ("icone.png", "image/png"),
    "/apple-touch-icon.png": ("icone.png", "image/png"),
}


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


def _entete(portee: Portee, nom: bytes) -> str:
    for cle, valeur in portee.get("headers", []):
        if cle == nom:
            return str(valeur.decode("latin-1"))
    return ""


async def _repondre(
    envoyer: Envoyer, statut: int, type_mime: str, corps: bytes, cache: bool = False
) -> None:
    entetes = [(b"content-type", type_mime.encode())]
    if cache:
        entetes.append((b"cache-control", b"public, max-age=86400"))
    await envoyer({"type": "http.response.start", "status": statut, "headers": entetes})
    await envoyer({"type": "http.response.body", "body": corps})


def _accueil_html() -> bytes:
    """Page lisible pour un navigateur (et icône déclarée pour les robots qui la cherchent)."""
    titre = escape("Serveur MCP Bleu Blanc Cloud")
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre}</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>body{{font-family:system-ui,sans-serif;max-width:38rem;margin:3rem auto;padding:0 1rem;
color:#1B1F3B;background:#F5F7FB;line-height:1.5}}img{{width:4rem}}code{{background:#fff;
padding:.1rem .3rem}}</style></head>
<body><img src="/favicon.svg" alt=""><h1>{titre}</h1>
<p>Serveur MCP en lecture seule de l'observatoire de la souveraineté numérique des
collectivités françaises. Ajoutez l'adresse <code>{CHEMIN_MCP}</code> de ce site comme
connecteur MCP dans votre assistant IA (Le Chat, claude.ai…).</p>
<p><a href="{DOCUMENTATION}">Mode d'emploi sur bleublanccloud.fr</a> · version {__version__}</p>
</body></html>""".encode()


async def _repondre_json(envoyer: Envoyer, statut: int, corps: dict[str, Any]) -> None:
    donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8")
    entetes = [(b"content-type", b"application/json; charset=utf-8")]
    if statut == 429:
        entetes.append((b"retry-after", b"60"))
    await envoyer({"type": "http.response.start", "status": statut, "headers": entetes})
    await envoyer({"type": "http.response.body", "body": donnees})


def proteger(application: ApplicationAsgi, limiteur: LimiteurRequetes) -> ApplicationAsgi:
    """Accueil informatif sur « / » (qui accepte aussi MCP), icônes, limite de requêtes."""

    async def protegee(portee: Portee, recevoir: Recevoir, envoyer: Envoyer) -> None:
        if portee["type"] != "http":
            await application(portee, recevoir, envoyer)
            return
        lecture = portee["method"] in ("GET", "HEAD")
        accepte = _entete(portee, b"accept")
        if portee["path"] == "/" and (not lecture or "text/event-stream" in accepte):
            # Adresse saisie sans « /mcp » : la racine sert aussi le protocole MCP
            portee = {**portee, "path": CHEMIN_MCP, "raw_path": CHEMIN_MCP.encode()}
        if lecture and portee["path"] in ICONES:
            fichier, type_mime = ICONES[portee["path"]]
            corps = (DOSSIER_STATIQUE / fichier).read_bytes()
            await _repondre(envoyer, 200, type_mime, corps, cache=True)
            return
        if lecture and portee["path"] == "/" and "text/html" in accepte:
            await _repondre(envoyer, 200, "text/html; charset=utf-8", _accueil_html())
            return
        if portee["path"] == "/" and lecture:
            await _repondre_json(
                envoyer,
                200,
                {
                    "service": "Serveur MCP Bleu Blanc Cloud (lecture seule)",
                    "version": __version__,
                    "point_d_acces": CHEMIN_MCP,
                    "documentation": DOCUMENTATION,
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
