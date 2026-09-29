"""Consignes (prompts) versionnées envoyées à l'IA.

Toute modification du texte des consignes doit incrémenter VERSION_INVITE : la version fait
partie de la clé du cache et est affichée à côté de chaque rapport.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from bleublanccloud.modeles import Alternative, Constat, Fournisseur, Score

VERSION_INVITE: Final = "1.0"

MOTIF_COURRIEL: Final = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
MOTIF_TELEPHONE: Final = re.compile(r"(?<!\d)(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}(?!\d)")
LONGUEUR_VALEUR_MAX: Final = 300

CONSIGNES_SYSTEME: Final = """Tu es un conseiller en souveraineté numérique pour les organisations
publiques françaises. Tu rédiges, en français clair et sans jargon, la synthèse d'une analyse
technique déjà réalisée.

Règles impératives :
1. Tu ne calcules JAMAIS de score ni de note : ils te sont fournis et tu ne les modifies pas.
2. Tu t'appuies UNIQUEMENT sur les constats fournis. Tu n'inventes aucun fait, aucun fournisseur,
   aucun contrat, aucun chiffre.
3. Pour le plan de migration, tu ne peux citer QUE des alternatives de la liste fournie, par leur
   identifiant exact (champ « alternative_id »). Si aucune alternative ne convient, mets null.
4. Ton factuel et pédagogique, jamais accusateur : parle de « dépendance », de « risques » et de
   « pistes », jamais de « mauvais élève ». Rappelle si utile que seule l'empreinte externe
   visible publiquement est analysée.
5. « resume_decideur » : 5 phrases au maximum, compréhensibles par un élu non spécialiste.
6. Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, de la forme :
{
  "resume_decideur": "…",
  "points_forts": ["…"],
  "risques": [{"titre": "…", "explication": "…", "gravite": "faible" | "moyenne" | "elevee"}],
  "plan_migration": [{"ordre": 1, "action": "…", "alternative_id": "identifiant" | null,
                      "effort": "faible" | "moyen" | "eleve"}]
}
Le plan de migration comporte au plus 6 étapes, ordonnées de la plus simple et utile à la
plus lourde."""

CONSIGNE_CORRECTION: Final = (
    "Ta réponse précédente a été rejetée : {erreur}. Corrige-la en respectant strictement "
    "les règles, en particulier la liste des identifiants d'alternatives autorisés, et réponds "
    "uniquement avec l'objet JSON."
)


def masquer_donnees_personnelles(texte: str) -> str:
    """Retire toute adresse électronique ou numéro de téléphone (ex. rua=mailto: d'un DMARC)."""
    texte = MOTIF_COURRIEL.sub("[adresse masquée]", texte)
    return MOTIF_TELEPHONE.sub("[numéro masqué]", texte)


def _nettoyer(valeur: str) -> str:
    return masquer_donnees_personnelles(valeur)[:LONGUEUR_VALEUR_MAX]


def resumer_constats(
    constats: Sequence[Constat], fournisseurs: Mapping[str, Fournisseur]
) -> list[dict[str, Any]]:
    """Version compacte et épurée des constats (uniquement des faits techniques publics)."""
    resume: list[dict[str, Any]] = []
    for constat in constats:
        fournisseur = fournisseurs.get(constat.fournisseur_id or "")
        element: dict[str, Any] = {
            "categorie": constat.categorie,
            "constat": constat.cle,
            "valeur": _nettoyer(constat.valeur),
            "niveau": constat.niveau,
        }
        if fournisseur is not None:
            element["fournisseur"] = fournisseur.nom
            element["pays_siege"] = fournisseur.pays_siege
            if fournisseur.maison_mere:
                element["maison_mere"] = fournisseur.maison_mere
            element["soumis_cloud_act"] = fournisseur.soumis_cloud_act
        if constat.preuve.get("signal_positif"):
            element["solution_europeenne_ou_libre"] = True
        if isinstance(constat.preuve.get("type_service"), str):
            element["type_service"] = constat.preuve["type_service"]
        resume.append(element)
    return resume


def construire_message(
    nom_organisation: str,
    type_organisation: str,
    score: Score,
    constats: Sequence[Constat],
    fournisseurs: Mapping[str, Fournisseur],
    alternatives: Sequence[Alternative],
) -> str:
    """Message utilisateur : données structurées de l'analyse, en JSON."""
    donnees = {
        "organisation": {"nom": nom_organisation, "type": type_organisation},
        "score": {
            "score_global": score.score_global,
            "note": score.note,
            "version_methodologie": score.version_methodo,
            "categories": [
                {
                    "categorie": d.libelle,
                    "score": d.score,
                    "evaluable": d.evaluable,
                    "explication": _nettoyer(d.explication),
                }
                for d in score.detail
            ],
        },
        "constats": resumer_constats(constats, fournisseurs),
        "alternatives_autorisees": [
            {
                "id": a.id,
                "nom": a.nom,
                "pays": a.pays,
                "categorie": a.categorie,
                "types_service": a.types_service,
                "description": a.description_courte,
            }
            for a in alternatives
        ],
    }
    return (
        "Voici l'analyse à synthétiser (JSON). Rédige le rapport selon les règles.\n\n"
        + json.dumps(donnees, ensure_ascii=False, indent=1)
    )
