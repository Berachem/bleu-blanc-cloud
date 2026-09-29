"""Sonde TLS : autorité de certification du site (information affichée, non notée en v1)."""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from typing import Any

import httpcore
from pydantic import BaseModel

from bleublanccloud.sondes.reseau import (
    AdresseNonPublique,
    ResolveurAdresses,
    adresses_publiques,
    resoudre_systeme,
)


class DonneesTls(BaseModel):
    hote: str
    emetteur_organisation: str | None = None
    emetteur_nom: str | None = None
    expire_le: str | None = None
    version_tls: str | None = None
    erreur: str | None = None

    @property
    def autorite(self) -> str | None:
        if self.emetteur_organisation and self.emetteur_nom:
            return f"{self.emetteur_organisation} ({self.emetteur_nom})"
        return self.emetteur_organisation or self.emetteur_nom


def lire_emetteur(certificat: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extrait l'organisation (O) et le nom commun (CN) de l'émetteur d'un certificat."""
    champs: dict[str, str] = {}
    for rdn in certificat.get("issuer", ()):
        for cle, valeur in rdn:
            champs.setdefault(cle, valeur)
    return champs.get("organizationName"), champs.get("commonName")


async def _connecter(
    adresses: list[str], hote: str, port: int, contexte: ssl.SSLContext, delai_s: float
) -> asyncio.StreamWriter:
    """Ouvre la connexion TLS vers la première adresse joignable."""
    derniere_erreur: BaseException | None = None
    for adresse in adresses:
        try:
            _, ecrivain = await asyncio.wait_for(
                asyncio.open_connection(adresse, port, ssl=contexte, server_hostname=hote),
                timeout=delai_s,
            )
        except ssl.SSLError:
            raise  # le serveur a répondu : inutile d'essayer une autre adresse
        except (OSError, TimeoutError) as erreur:
            derniere_erreur = erreur
            continue
        return ecrivain
    assert derniere_erreur is not None
    raise derniere_erreur


async def sonder_tls(
    hote: str,
    port: int = 443,
    delai_s: float = 10.0,
    resoudre: ResolveurAdresses = resoudre_systeme,
) -> DonneesTls:
    """Ouvre une connexion TLS (sans envoyer de requête) et lit le certificat présenté."""
    donnees = DonneesTls(hote=hote)
    contexte = ssl.create_default_context()
    try:
        # Garde réseau : connexion vers une adresse publique vérifiée, SNI sur le nom d'hôte
        adresses = await adresses_publiques(hote, port, resoudre)
        ecrivain = await _connecter(adresses, hote, port, contexte, delai_s)
    except AdresseNonPublique:
        donnees.erreur = "connexion TLS refusée : adresse non publique"
        return donnees
    except ssl.SSLCertVerificationError as erreur:
        donnees.erreur = f"certificat non valide : {erreur.verify_message}"
        return donnees
    except (OSError, TimeoutError, ssl.SSLError, httpcore.ConnectError) as erreur:
        donnees.erreur = f"connexion TLS impossible : {type(erreur).__name__}"
        return donnees
    try:
        certificat = ecrivain.get_extra_info("peercert") or {}
        objet_ssl = ecrivain.get_extra_info("ssl_object")
        donnees.emetteur_organisation, donnees.emetteur_nom = lire_emetteur(certificat)
        donnees.expire_le = certificat.get("notAfter")
        donnees.version_tls = objet_ssl.version() if objet_ssl is not None else None
    finally:
        ecrivain.close()
        with contextlib.suppress(OSError, TimeoutError, ssl.SSLError):
            await asyncio.wait_for(ecrivain.wait_closed(), timeout=2)
    return donnees
