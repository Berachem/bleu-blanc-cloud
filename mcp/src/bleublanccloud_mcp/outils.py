"""Logique des outils MCP, testable sans serveur : chaque fonction lit les données publiées
et renvoie un dictionnaire prêt à être transmis à l'assistant.

Chaque réponse rappelle la source, la date des données et la limite du score (empreinte
externe uniquement, indicatif), et donne le lien vers la fiche où figurent les preuves.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from bleublanccloud_mcp.donnees import DonneeIntrouvable, SourceDonnees

AVERTISSEMENT = (
    "Score indicatif : il ne reflète que l'empreinte numérique externe et visible "
    "publiquement (site web, messagerie, DNS, services tiers), pas les outils internes ni la "
    "sécurité. Chaque point retiré est justifié par une preuve sur la fiche."
)
LIBELLES_CATEGORIES = {
    "hebergement": "Hébergement du site",
    "messagerie": "Messagerie",
    "dns": "DNS",
    "suites_saas": "Suites collaboratives et SaaS",
    "services_tiers": "Services tiers chargés par le site",
    "mesure_audience": "Mesure d'audience et cookies",
}
NOTES = ("A", "B", "C", "D", "E")
TYPES = ("commune", "departement", "region")
LIMITE_MAX = 50
COMPARAISON_MAX = 6
MOTIF_CODE_INSEE = re.compile(r"-(\d{5}|2[ab]\d{3})$")


def normaliser(texte: str) -> str:
    """« Saint-Étienne » → « saint etienne » (recherche sans accents ni casse)."""
    sans_accents = unicodedata.normalize("NFD", texte)
    sans_accents = "".join(c for c in sans_accents if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).strip()


def code_insee(slug: str) -> str | None:
    trouve = MOTIF_CODE_INSEE.search(slug)
    return trouve.group(1).upper() if trouve else None


def _borner(limite: int, maximum: int = LIMITE_MAX) -> int:
    return max(1, min(int(limite), maximum))


async def _source(donnees: SourceDonnees) -> dict[str, Any]:
    meta = await donnees.meta()
    return {
        "site": donnees.base,
        "donnees_du": meta.get("date_campagne"),
        "methodologie": f"{donnees.base}/methodologie/",
        "licence": "Licence Ouverte 2.0 (citer « Bleu Blanc Cloud »)",
        "avertissement": AVERTISSEMENT,
        **({"demonstration": True} if meta.get("donnees_demonstration") else {}),
    }


def _url_fiche(donnees: SourceDonnees, slug: str) -> str:
    return f"{donnees.base}/organisation/{slug}/"


def _resume(donnees: SourceDonnees, entree: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": entree["slug"],
        "nom": entree["nom"],
        "type": entree["type"],
        "departement": entree.get("departement_nom") or entree.get("departement"),
        "population": entree.get("population"),
        "score": entree["score"],
        "note": entree["note"],
        "note_provisoire": bool(entree.get("note_provisoire")),
        "url_fiche": _url_fiche(donnees, entree["slug"]),
    }


async def _observatoire(donnees: SourceDonnees) -> list[dict[str, Any]]:
    return [e for e in await donnees.index() if e.get("type") != "sur_demande"]


def _departement_correspond(entree: dict[str, Any], departement: str) -> bool:
    cible = normaliser(departement)
    return cible in (
        normaliser(str(entree.get("departement") or "")),
        normaliser(str(entree.get("departement_nom") or "")),
    )


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #


async def rechercher_collectivite(
    donnees: SourceDonnees, texte: str, limite: int = 10
) -> dict[str, Any]:
    """Collectivités dont le nom, le domaine, le code INSEE ou le département correspond."""
    cible = normaliser(texte)
    if not cible:
        return {"resultats": [], "source": await _source(donnees)}
    scores: list[tuple[int, dict[str, Any]]] = []
    for entree in await donnees.index():
        nom = normaliser(entree["nom"])
        champs = {
            "nom": nom,
            "domaine": normaliser(entree.get("domaine") or ""),
            "insee": normaliser(code_insee(entree["slug"]) or ""),
            "departement": normaliser(entree.get("departement_nom") or ""),
        }
        if cible in (nom, champs["insee"], champs["domaine"]):
            rang = 0  # correspondance exacte
        elif nom.startswith(cible) or nom.endswith(f" {cible}"):
            rang = 1
        elif cible in nom or cible in champs["domaine"]:
            rang = 2
        elif cible == champs["departement"]:
            rang = 3
        else:
            continue
        scores.append((rang, entree))
    scores.sort(key=lambda s: (s[0], -(s[1].get("population") or 0)))
    return {
        "resultats": [_resume(donnees, e) for _, e in scores[: _borner(limite)]],
        "nombre_total": len(scores),
        "source": await _source(donnees),
    }


async def fiche_collectivite(donnees: SourceDonnees, slug: str) -> dict[str, Any]:
    """Détail d'une collectivité : score, catégories, fournisseurs, évolution, pistes."""
    try:
        fiche = await donnees.fiche(slug)
    except DonneeIntrouvable:
        return {
            "erreur": f"Aucune fiche « {slug} ». Utilisez rechercher_collectivite pour trouver "
            "le bon identifiant (slug).",
        }
    score = fiche["score"]
    fournisseurs = fiche.get("fournisseurs", {})
    constats = [
        {
            "categorie": LIBELLES_CATEGORIES.get(c["categorie"], c["categorie"]),
            "valeur": c["valeur"],
            "fournisseur": fournisseurs.get(c.get("fournisseur_id") or "", {}).get("nom"),
            "niveau": c.get("niveau"),
        }
        for c in fiche.get("constats", [])
        if c["categorie"] in LIBELLES_CATEGORIES
    ]
    rapport = fiche.get("rapport_ia")
    return {
        "slug": fiche["slug"],
        "nom": fiche["nom"],
        "type": fiche["type"],
        "departement": fiche.get("departement_nom"),
        "region": fiche.get("region_nom"),
        "population": fiche.get("population"),
        "domaine": fiche["domaine"],
        "date_analyse": fiche["date_scan"],
        "score": score["score_global"],
        "note": score["note"],
        "note_provisoire": bool(score.get("provisoire")),
        "couverture_pourcent": score.get("couverture"),
        "categories": [
            {
                "categorie": c["libelle"],
                "score": c.get("score") if c.get("evaluable") else None,
                "explication": c.get("explication"),
            }
            for c in score.get("detail", [])
        ],
        "fournisseurs": [
            {
                "nom": f.get("nom"),
                "niveau": f.get("niveau"),
                "pays_siege": f.get("pays_siege"),
                "maison_mere": f.get("maison_mere"),
                "soumis_cloud_act": f.get("soumis_cloud_act"),
            }
            for f in fournisseurs.values()
        ],
        "constats": constats,
        "evolution": [
            {"date": p["date"], "score": p["score"], "note": p["note"]}
            for p in fiche.get("historique", [])
        ],
        "pistes_alternatives": [
            {"nom": a.get("nom"), "pays": a.get("pays"), "url": a.get("url")}
            for a in fiche.get("alternatives", [])
        ],
        **(
            {
                "synthese_ia": {
                    "resume": rapport["contenu"].get("resume_decideur"),
                    "mention": "Rédigé par une IA (Mistral) à partir des constats techniques "
                    "— peut contenir des erreurs.",
                }
            }
            if rapport and rapport.get("contenu")
            else {}
        ),
        "url_fiche": _url_fiche(donnees, fiche["slug"]),
        "source": await _source(donnees),
    }


async def classement(
    donnees: SourceDonnees,
    departement: str | None = None,
    type: str | None = None,
    note: str | None = None,
    ordre: str = "meilleurs",
    limite: int = 20,
) -> dict[str, Any]:
    """Collectivités filtrées par département, type et note, triées par score."""
    entrees = await _observatoire(donnees)
    if departement:
        entrees = [e for e in entrees if _departement_correspond(e, departement)]
    if type:
        entrees = [e for e in entrees if e.get("type") == type]
    if note:
        notes = {n.strip().upper() for n in note.split(",")}
        entrees = [e for e in entrees if e.get("note") in notes]
    meilleurs = ordre != "moins_bons"
    entrees.sort(
        key=lambda e: ((-e["score"] if meilleurs else e["score"]), -(e.get("population") or 0))
    )
    return {
        "filtres": {"departement": departement, "type": type, "note": note, "ordre": ordre},
        "nombre_total": len(entrees),
        "resultats": [_resume(donnees, e) for e in entrees[: _borner(limite)]],
        "source": await _source(donnees),
    }


async def comparer(donnees: SourceDonnees, slugs: list[str]) -> dict[str, Any]:
    """Comparaison côte à côte (score, note, catégories, fournisseurs principaux)."""
    collectivites: list[dict[str, Any]] = []
    introuvables: list[str] = []
    for slug in list(dict.fromkeys(slugs))[:COMPARAISON_MAX]:
        try:
            fiche = await donnees.fiche(slug)
        except DonneeIntrouvable:
            introuvables.append(slug)
            continue
        fournisseurs = fiche.get("fournisseurs", {})
        principaux: dict[str, list[str]] = {}
        for c in fiche.get("constats", []):
            if c["categorie"] in ("hebergement", "messagerie", "dns") and c.get("fournisseur_id"):
                nom = fournisseurs.get(c["fournisseur_id"], {}).get("nom")
                libelle = LIBELLES_CATEGORIES[c["categorie"]]
                if nom and nom not in principaux.setdefault(libelle, []):
                    principaux[libelle].append(nom)
        collectivites.append(
            {
                "slug": fiche["slug"],
                "nom": fiche["nom"],
                "score": fiche["score"]["score_global"],
                "note": fiche["score"]["note"],
                "note_provisoire": bool(fiche["score"].get("provisoire")),
                "scores_par_categorie": {
                    c["libelle"]: (c.get("score") if c.get("evaluable") else None)
                    for c in fiche["score"].get("detail", [])
                },
                "fournisseurs_principaux": principaux,
                "url_fiche": _url_fiche(donnees, fiche["slug"]),
            }
        )
    return {
        "collectivites": collectivites,
        **({"introuvables": introuvables} if introuvables else {}),
        "source": await _source(donnees),
    }


async def statistiques(donnees: SourceDonnees, departement: str | None = None) -> dict[str, Any]:
    """Chiffres clés nationaux, ou d'un département."""
    entrees = await _observatoire(donnees)
    perimetre = "France"
    if departement:
        entrees = [e for e in entrees if _departement_correspond(e, departement)]
        perimetre = next((e.get("departement_nom") or departement for e in entrees), departement)
    nombre = len(entrees)
    repartition = {n: sum(1 for e in entrees if e.get("note") == n) for n in NOTES}
    return {
        "perimetre": perimetre,
        "nombre_collectivites": nombre,
        "score_moyen": round(sum(e["score"] for e in entrees) / nombre, 1) if nombre else None,
        "repartition_notes": repartition,
        "part_note_a_pourcent": round(100 * repartition["A"] / nombre, 1) if nombre else None,
        "notes_provisoires": sum(1 for e in entrees if e.get("note_provisoire")),
        "source": await _source(donnees),
    }


async def collectivites_par_fournisseur(
    donnees: SourceDonnees,
    fournisseur: str,
    categorie: str | None = None,
    departement: str | None = None,
    limite: int = 30,
) -> dict[str, Any]:
    """Collectivités qui utilisent un fournisseur (hébergement, messagerie, DNS) ou un service
    hors UE (suites, services tiers, mesure d'audience), d'après les données ouvertes."""
    cible = normaliser(fournisseur)
    colonnes = {
        "hebergement": ["fournisseurs_hebergement"],
        "messagerie": ["fournisseurs_messagerie"],
        "dns": ["fournisseurs_dns"],
        "services_hors_ue": ["services_hors_ue"],
    }
    choisies = colonnes.get(categorie or "", [c for cs in colonnes.values() for c in cs])
    lignes = []
    for ligne in await donnees.organisations_csv():
        if (
            departement
            and departement != ligne.get("code_departement")
            and (normaliser(departement) != normaliser(ligne.get("departement", "")))
        ):
            continue
        trouvees = [
            colonne
            for colonne in choisies
            if any(cible in normaliser(v) for v in (ligne.get(colonne) or "").split(" | "))
        ]
        if trouvees:
            lignes.append(
                {
                    "slug": ligne["slug"],
                    "nom": ligne["nom"],
                    "departement": ligne.get("departement"),
                    "note": ligne.get("note"),
                    "score": int(ligne["score"]) if ligne.get("score") else None,
                    "usages": [c.removeprefix("fournisseurs_") for c in trouvees],
                    "url_fiche": ligne.get("url_fiche"),
                }
            )
    lignes.sort(key=lambda x: str(x["nom"]))
    return {
        "fournisseur": fournisseur,
        "categorie": categorie,
        "nombre_total": len(lignes),
        "resultats": lignes[: _borner(limite)],
        "source": await _source(donnees),
    }


async def alternatives(donnees: SourceDonnees, categorie: str | None = None) -> dict[str, Any]:
    """Pistes françaises et européennes du référentiel (aucune n'est inventée)."""
    liste = await donnees.alternatives()
    if categorie:
        cible = normaliser(categorie)
        liste = [
            a
            for a in liste
            if cible == normaliser(str(a.get("categorie", "")))
            or any(cible in normaliser(str(t)) for t in a.get("types_service", []))
            or cible in normaliser(str(a.get("description_courte", "")))
        ]
    return {
        "alternatives": [
            {
                "nom": a.get("nom"),
                "pays": a.get("pays"),
                "url": a.get("url"),
                "categorie": a.get("categorie"),
                "types_service": a.get("types_service", []),
                "description": a.get("description_courte"),
            }
            for a in liste
        ],
        "page": f"{donnees.base}/alternatives/",
        "source": await _source(donnees),
    }
