"""Validation stricte du domaine demandé dans un ticket (donnée non fiable)."""

from __future__ import annotations

import ipaddress
import re
from typing import Final

import idna

TAILLE_MAX_SAISIE: Final = 300

# Zones réservées (RFC 2606, 6761, 6762, 7686, 8375, 9476) ou d'usage local courant
ZONES_RESERVEES: Final = frozenset(
    {
        "localhost", "local", "localdomain", "internal", "intranet", "lan", "home", "corp",
        "private", "home.arpa", "arpa", "test", "invalid", "example", "onion", "alt",
    }
)  # fmt: skip

MOTIF_ETIQUETTE: Final = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
MOTIF_TLD: Final = re.compile(r"^(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$")

CONSEIL: Final = "Indiquez le nom de domaine seul, par exemple : mairie-exemple.fr"


class DomaineRefuse(ValueError):
    """Domaine refusé ; `code` identifie la raison (réutilisé pour la réponse polie)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


MESSAGES: Final[dict[str, str]] = {
    "domaine_absent": "Aucun nom de domaine n'a été indiqué.",
    "domaine_chemin": "L'adresse indiquée contient un chemin ou des paramètres.",
    "domaine_port": "L'adresse indiquée contient un numéro de port.",
    "domaine_ip": "Une adresse IP ne peut pas être analysée : seul un nom de domaine est accepté.",
    "domaine_invalide": "Ce nom de domaine n'est pas valide.",
    "domaine_reserve": (
        "Ce nom de domaine est réservé à un usage local ou de test : il ne peut pas être analysé."
    ),
}


def _refuser(code: str) -> DomaineRefuse:
    return DomaineRefuse(code, MESSAGES[code])


def _est_ip(texte: str) -> bool:
    try:
        ipaddress.ip_address(texte.strip("[]"))
    except ValueError:
        return False
    return True


def valider_domaine(saisie: str | None) -> str:
    """Retourne le nom d'hôte validé, en minuscules et en punycode (ex. « xn--vry-bma.fr »).

    Tolère seulement un schéma « http(s):// » et une barre oblique finale ; refuse tout
    chemin, paramètre, port, identifiant, adresse IP, nom à une seule étiquette et zone
    réservée (localhost, .local, .internal, .test…). L'appartenance des adresses à un
    réseau privé est vérifiée ensuite, à la résolution DNS.
    """
    if saisie is None or not saisie.strip():
        raise _refuser("domaine_absent")
    candidat = saisie.strip()
    if len(candidat) > TAILLE_MAX_SAISIE:
        raise _refuser("domaine_invalide")
    for schema in ("https://", "http://"):
        if candidat.lower().startswith(schema):
            candidat = candidat[len(schema) :]
            break
    candidat = candidat.removesuffix("/")
    if any(caractere in candidat for caractere in "/?#\\"):
        raise _refuser("domaine_chemin")
    if "@" in candidat or any(caractere.isspace() for caractere in candidat):
        raise _refuser("domaine_invalide")
    if _est_ip(candidat):
        raise _refuser("domaine_ip")
    if ":" in candidat:
        raise _refuser("domaine_port")
    candidat = candidat.removesuffix(".")
    try:
        hote = idna.encode(candidat, uts46=True).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError, ValueError) as erreur:
        raise _refuser("domaine_invalide") from erreur
    if _est_ip(hote):
        raise _refuser("domaine_ip")
    if any(hote == zone or hote.endswith("." + zone) for zone in ZONES_RESERVEES):
        raise _refuser("domaine_reserve")
    etiquettes = hote.split(".")
    if (
        len(hote) > 253
        or len(etiquettes) < 2
        or not all(MOTIF_ETIQUETTE.match(etiquette) for etiquette in etiquettes)
        or not MOTIF_TLD.match(etiquettes[-1])
    ):
        raise _refuser("domaine_invalide")
    return hote


def nom_lisible(hote: str) -> str:
    """Forme Unicode d'un nom punycode, pour l'affichage (« xn--vry-bma.fr » → « évry.fr »)."""
    try:
        return idna.decode(hote)
    except (idna.IDNAError, UnicodeError):
        return hote
