"""Textes des réponses publiées dans les tickets (Markdown, ton factuel et courtois).

Aucun texte saisi par le visiteur n'est recopié : seuls le domaine validé (caractères
[a-z0-9.-]) et des valeurs calculées par le scanner sont insérés.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from bleublanccloud.demandes.validation import CONSEIL
from bleublanccloud.demandes.validation import MESSAGES as MESSAGES_DOMAINE

FUSEAU: Final = ZoneInfo("Europe/Paris")
MENTION_IA: Final = (
    "Rapport rédigé par une IA (Mistral) à partir des constats techniques — "
    "peut contenir des erreurs."
)
LIMITES: Final = (
    "Ce score ne reflète que l'empreinte **externe et visible publiquement** du site "
    "(site web et DNS), pas les outils internes ni les contrats : il est **indicatif**."
)
SIGNATURE: Final = "\n\n---\n_Réponse automatique du robot Bleu Blanc Cloud._"
NOUVELLE_DEMANDE: Final = "Vous pouvez ouvrir une nouvelle demande à tout moment."


def _date(valeur: datetime) -> str:
    return valeur.astimezone(FUSEAU).strftime("%d/%m/%Y à %H:%M")


def reponse_traitee(
    *,
    domaine: str,
    note: str,
    score: int,
    provisoire: bool,
    url_fiche: str,
    url_methodologie: str,
    date_scan: datetime,
    reutilisee: bool,
    avec_rapport_ia: bool,
) -> str:
    lignes = ["Bonjour,", ""]
    if reutilisee:
        lignes.append(
            f"`{domaine}` a déjà été analysé il y a moins de 7 jours (le {_date(date_scan)}) : "
            "voici la fiche existante, sans nouvelle analyse."
        )
    else:
        lignes.append(f"L'analyse passive de `{domaine}` est terminée (le {_date(date_scan)}).")
    lignes += [
        "",
        f"- **Note : {note}**{' (provisoire)' if provisoire else ''}",
        f"- **Score : {score}/100**",
        f"- **Fiche détaillée** : {url_fiche}",
        "",
        "La fiche détaille chaque constat, sa preuve et des pistes d'alternatives françaises "
        "ou européennes. Elle peut mettre quelques minutes à apparaître en ligne.",
        "",
        f"ℹ️ {LIMITES} Méthodologie : {url_methodologie}",
    ]
    if provisoire:
        lignes += [
            "",
            "La note est **provisoire** : plus de 30 % du poids n'a pas pu être évalué "
            "(fournisseurs non identifiés ou données indisponibles).",
        ]
    if avec_rapport_ia:
        lignes += ["", f"🤖 {MENTION_IA}"]
    lignes += [
        "",
        "Cette fiche est une analyse **sur demande** : elle n'apparaît ni sur la carte ni "
        "dans les classements de l'observatoire. Pour signaler une erreur, répondez "
        "simplement dans ce ticket.",
    ]
    return "\n".join(lignes) + SIGNATURE


MESSAGES_REFUS: Final[dict[str, str]] = {
    **{code: f"{message} {CONSEIL}." for code, message in MESSAGES_DOMAINE.items()},
    "case_non_cochee": (
        "La case « Je suis responsable de ce site, ou il s'agit du site d'un organisme "
        "public » n'a pas été cochée. Nous analysons uniquement des sites dont vous avez la "
        "responsabilité ou des sites d'organismes publics."
    ),
    "retrait": (
        "Ce domaine a demandé à ne plus être analysé par Bleu Blanc Cloud (droit de retrait) : "
        "nous respectons ce choix."
    ),
    "sans_adresse": (
        "Ce domaine ne pointe vers aucune adresse IP (ni lui ni son sous-domaine www) : "
        "il n'y a pas de site à analyser."
    ),
    "reseau_prive": (
        "Ce domaine pointe vers une adresse locale, privée ou réservée : pour des raisons de "
        "sécurité, il ne peut pas être analysé."
    ),
    "limite_quotidienne": (
        "La limite de {limite_jour} analyses par jour est atteinte. Merci de renouveler votre "
        "demande demain."
    ),
    "limite_compte": (
        "Une seule analyse par jour et par compte Codeberg est possible, et une demande de "
        "votre compte a déjà été acceptée aujourd'hui. Merci de renouveler votre demande demain."
    ),
}


def reponse_refusee(code: str, url_methodologie: str, limite_jour: int = 10) -> str:
    raison = MESSAGES_REFUS.get(code, "La demande n'a pas pu être acceptée.")
    return (
        "Bonjour,\n\n"
        "Merci pour votre demande. Elle ne peut malheureusement pas être traitée :\n\n"
        f"> {raison.format(limite_jour=limite_jour)}\n\n"
        f"{NOUVELLE_DEMANDE} Les règles des analyses sur demande sont décrites dans la "
        f"méthodologie : {url_methodologie}" + SIGNATURE
    )


def reponse_erreur(tentative: int, maximum: int) -> str:
    if tentative >= maximum:
        return (
            "Bonjour,\n\n"
            f"L'analyse n'a pas pu aboutir après {maximum} tentatives, à cause d'une erreur "
            "technique (site ou réseau momentanément injoignable, par exemple). Le ticket est "
            f"fermé. {NOUVELLE_DEMANDE}" + SIGNATURE
        )
    return (
        "Bonjour,\n\n"
        "Merci pour votre demande. Une erreur technique a empêché l'analyse "
        f"(tentative {tentative}/{maximum}) : un nouvel essai aura lieu automatiquement au "
        "prochain passage du robot, dans l'heure. Rien à faire de votre côté." + SIGNATURE
    )
