"""Lecture des tickets « Analyser mon site » (formulaire Forgejo ou URL pré-remplie).

Le titre et le corps sont écrits par n'importe quel visiteur : ils ne servent qu'à extraire
une chaîne candidate pour le domaine (validée ensuite) et l'état de la case d'engagement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

PREFIXE_TITRE: Final = "[Analyse]"
ETIQUETTE_ANALYSE: Final = "analyse"
ETIQUETTE_TRAITEE: Final = "traitée"
ETIQUETTE_REFUSEE: Final = "refusée"
ETIQUETTE_ERREUR: Final = "erreur"
LIBELLE_DOMAINE: Final = "Domaine à analyser"
TEXTE_ENGAGEMENT: Final = (
    "Je suis responsable de ce site, ou il s'agit du site d'un organisme public"
)
TAILLE_MAX_CORPS: Final = 20_000

_TITRE_CHAMP = re.compile(r"^\s*#{1,6}\s*Domaine\s+à\s+analyser\s*$", re.IGNORECASE)
_LIGNE_DOMAINE = re.compile(
    r"^\s*(?:[-*]\s*)?\**\s*Domaine\s+à\s+analyser\s*\**\s*:\s*(.*?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CASE_COCHEE = re.compile(
    r"^\s*[-*]\s*\[[xX]\]\s*Je suis responsable de ce site", re.IGNORECASE | re.MULTILINE
)
_SANS_REPONSE = {"_no response_", "_pas de réponse_", "_aucune réponse_"}


@dataclass(frozen=True)
class Ticket:
    """Ticket ouvert sur la forge (champs utiles seulement)."""

    numero: int
    titre: str
    corps: str
    auteur: str
    etiquettes: frozenset[str] = field(default_factory=frozenset)

    @property
    def est_demande(self) -> bool:
        """Étiquette « analyse » (formulaire) ou titre « [Analyse] … » (URL pré-remplie)."""
        etiquettes = {e.casefold() for e in self.etiquettes}
        return ETIQUETTE_ANALYSE in etiquettes or self.titre.strip().casefold().startswith(
            PREFIXE_TITRE.casefold()
        )

    @property
    def corps_borne(self) -> str:
        return self.corps[:TAILLE_MAX_CORPS]


def _nettoyer(valeur: str) -> str:
    return valeur.strip().strip("`").strip()


def extraire_domaine(ticket: Ticket) -> str | None:
    """Chaîne candidate pour le domaine (non validée), ou None si aucune n'est trouvée."""
    lignes = ticket.corps_borne.splitlines()
    # 1. Formulaire Forgejo : « ### Domaine à analyser », puis la valeur saisie
    for rang, ligne in enumerate(lignes):
        if _TITRE_CHAMP.match(ligne):
            for suivante in lignes[rang + 1 :]:
                valeur = _nettoyer(suivante)
                if not valeur:
                    continue
                if valeur.startswith("#") or valeur.casefold() in _SANS_REPONSE:
                    break
                return valeur
            break
    # 2. URL pré-remplie : ligne « Domaine à analyser : exemple.fr »
    for correspondance in _LIGNE_DOMAINE.finditer(ticket.corps_borne):
        valeur = _nettoyer(correspondance.group(1))
        if valeur:
            return valeur
    # 3. Titre « [Analyse] exemple.fr »
    titre = ticket.titre.strip()
    if titre.casefold().startswith(PREFIXE_TITRE.casefold()):
        reste = _nettoyer(titre[len(PREFIXE_TITRE) :])
        if reste:
            return reste
    return None


def case_cochee(ticket: Ticket) -> bool:
    """La case d'engagement est-elle cochée (« - [x] Je suis responsable de ce site… ») ?"""
    return _CASE_COCHEE.search(ticket.corps_borne) is not None
