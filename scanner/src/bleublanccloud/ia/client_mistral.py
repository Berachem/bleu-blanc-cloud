"""Client Mistral : génération, validation, cache et budget des rapports IA.

- L'IA ne calcule jamais le score : elle reformule les constats et propose un plan d'action.
- Sortie JSON validée par pydantic ; tout identifiant d'alternative inconnu entraîne le rejet
  du rapport, une seule nouvelle tentative, puis le marquage en erreur.
- Cache : SHA-256 des constats + version des consignes + modèle.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from bleublanccloud.ia.invites import (
    CONSIGNE_CORRECTION,
    CONSIGNES_SYSTEME,
    VERSION_INVITE,
    construire_message,
)
from bleublanccloud.modeles import Alternative, Constat, Fournisseur, RapportIA, Score

TEMPERATURE = 0.2
PHRASES_RESUME_MAX = 5
JETONS_SORTIE_ESTIMES = 900
CARACTERES_PAR_JETON = 3.5


class ErreurIA(Exception):
    """Échec de l'appel à l'API (réseau, quota, clé invalide…)."""


class RapportInvalide(ValueError):
    """Réponse de l'IA non conforme (JSON invalide, alternative inventée…)."""


@dataclass(frozen=True)
class ReponseChat:
    contenu: str
    jetons_entree: int = 0
    jetons_sortie: int = 0


class ClientChat(Protocol):
    async def completer(
        self, messages: list[dict[str, str]], modele: str, temperature: float
    ) -> ReponseChat: ...


class ClientMistral:
    """Adaptateur autour du SDK officiel `mistralai` (serveur européen par défaut)."""

    def __init__(self, cle_api: str, serveur: str = "eu", sdk: Any = None) -> None:
        if sdk is None:
            from mistralai.client import Mistral

            sdk = Mistral(api_key=cle_api, server=serveur, timeout_ms=120_000)
        self._sdk = sdk

    async def completer(
        self, messages: list[dict[str, str]], modele: str, temperature: float
    ) -> ReponseChat:
        try:
            reponse = await self._sdk.chat.complete_async(
                model=modele,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except Exception as erreur:  # le SDK lève des exceptions variées (réseau, HTTP…)
            raise ErreurIA(f"{type(erreur).__name__} : {erreur}") from erreur
        if not reponse.choices:
            raise ErreurIA("réponse vide")
        contenu = reponse.choices[0].message.content
        if not isinstance(contenu, str):
            contenu = "".join(getattr(morceau, "text", "") for morceau in contenu or [])
        usage = reponse.usage
        return ReponseChat(
            contenu=contenu,
            jetons_entree=int(getattr(usage, "prompt_tokens", 0) or 0),
            jetons_sortie=int(getattr(usage, "completion_tokens", 0) or 0),
        )


# --------------------------------------------------------------------------- #
# Empreinte, validation
# --------------------------------------------------------------------------- #


def empreinte_constats(constats: Sequence[Constat], version_invite: str, modele: str) -> str:
    """SHA-256 des constats (forme canonique) + version des consignes + modèle."""
    canonique = json.dumps(
        [c.model_dump(mode="json") for c in constats], sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(f"{canonique}|{version_invite}|{modele}".encode()).hexdigest()


def _extraire_json(texte: str) -> Any:
    texte = texte.strip()
    bloc = re.search(r"```(?:json)?\s*(.*?)```", texte, flags=re.DOTALL)
    if bloc:
        texte = bloc.group(1).strip()
    try:
        return json.loads(texte)
    except json.JSONDecodeError as erreur:
        raise RapportInvalide(f"JSON invalide ({erreur.msg})") from erreur


def compter_phrases(texte: str) -> int:
    return len([p for p in re.split(r"(?<=[.!?…])\s+", texte.strip()) if p])


def valider_rapport(texte: str, alternatives_connues: Collection[str]) -> RapportIA:
    """Valide la réponse de l'IA ; lève RapportInvalide si elle n'est pas conforme."""
    try:
        rapport = RapportIA.model_validate(_extraire_json(texte))
    except ValidationError as erreur:
        raise RapportInvalide(
            f"structure non conforme : {erreur.error_count()} erreur(s)"
        ) from erreur
    inventees = sorted(
        {
            etape.alternative_id
            for etape in rapport.plan_migration
            if etape.alternative_id is not None and etape.alternative_id not in alternatives_connues
        }
    )
    if inventees:
        raise RapportInvalide(f"alternative(s) inconnue(s) : {', '.join(inventees)}")
    if compter_phrases(rapport.resume_decideur) > PHRASES_RESUME_MAX:
        raise RapportInvalide(f"résumé de plus de {PHRASES_RESUME_MAX} phrases")
    rapport.plan_migration.sort(key=lambda etape: etape.ordre)
    return rapport


# --------------------------------------------------------------------------- #
# Génération
# --------------------------------------------------------------------------- #


@dataclass
class DemandeRapport:
    nom_organisation: str
    type_organisation: str
    score: Score
    constats: list[Constat]
    alternatives: list[Alternative]


@dataclass
class ResultatGeneration:
    rapport: RapportIA | None
    erreur: str | None = None
    appels: int = 0
    jetons_entree: int = 0
    jetons_sortie: int = 0
    tentatives: list[str] = field(default_factory=list)


def construire_messages(
    demande: DemandeRapport, fournisseurs: Mapping[str, Fournisseur]
) -> list[dict[str, str]]:
    """Consignes système + données de l'analyse (message utilisateur)."""
    return [
        {"role": "system", "content": CONSIGNES_SYSTEME},
        {
            "role": "user",
            "content": construire_message(
                demande.nom_organisation,
                demande.type_organisation,
                demande.score,
                demande.constats,
                fournisseurs,
                demande.alternatives,
            ),
        },
    ]


class GenerateurRapports:
    def __init__(
        self,
        client: ClientChat,
        modele: str,
        fournisseurs: Mapping[str, Fournisseur],
        alternatives_connues: Collection[str],
    ) -> None:
        self.client = client
        self.modele = modele
        self.fournisseurs = fournisseurs
        self.alternatives_connues = set(alternatives_connues)

    def messages(self, demande: DemandeRapport) -> list[dict[str, str]]:
        return construire_messages(demande, self.fournisseurs)

    async def generer(self, demande: DemandeRapport) -> ResultatGeneration:
        """Une tentative, puis une seule nouvelle tentative si le rapport est rejeté."""
        messages = self.messages(demande)
        resultat = ResultatGeneration(rapport=None)
        for _ in range(2):
            try:
                reponse = await self.client.completer(messages, self.modele, TEMPERATURE)
            except ErreurIA as erreur:
                resultat.erreur = str(erreur)
                return resultat
            resultat.appels += 1
            resultat.jetons_entree += reponse.jetons_entree
            resultat.jetons_sortie += reponse.jetons_sortie
            try:
                resultat.rapport = valider_rapport(reponse.contenu, self.alternatives_connues)
                resultat.erreur = None
                return resultat
            except RapportInvalide as erreur:
                resultat.erreur = f"rapport rejeté : {erreur}"
                resultat.tentatives.append(str(erreur))
                messages = [
                    *messages,
                    {"role": "assistant", "content": reponse.contenu},
                    {"role": "user", "content": CONSIGNE_CORRECTION.format(erreur=erreur)},
                ]
        return resultat


# --------------------------------------------------------------------------- #
# Budget
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Estimation:
    appels: int
    jetons_entree: int
    jetons_sortie: int
    cout: float

    def en_texte(self, devise: str = "$") -> str:
        def milliers(n: int) -> str:
            return f"{n:,}".replace(",", "\u202f")

        return (
            f"{self.appels} appel(s), ≈ {milliers(self.jetons_entree)} jetons en entrée et "
            f"{milliers(self.jetons_sortie)} en sortie, coût estimé ≈ {self.cout:.4f} {devise} "
            "(hors éventuelles nouvelles tentatives)"
        )


def estimer(
    messages: Sequence[list[dict[str, str]]], prix_entree_par_m: float, prix_sortie_par_m: float
) -> Estimation:
    """Estimation prudente : ~3,5 caractères par jeton en français."""
    jetons_entree = sum(
        int(sum(len(m["content"]) for m in liste) / CARACTERES_PAR_JETON) + 1 for liste in messages
    )
    jetons_sortie = JETONS_SORTIE_ESTIMES * len(messages)
    cout = (jetons_entree * prix_entree_par_m + jetons_sortie * prix_sortie_par_m) / 1_000_000
    return Estimation(len(messages), jetons_entree, jetons_sortie, cout)


__all__ = [
    "VERSION_INVITE",
    "ClientMistral",
    "DemandeRapport",
    "ErreurIA",
    "GenerateurRapports",
    "RapportInvalide",
    "empreinte_constats",
    "estimer",
    "valider_rapport",
]
