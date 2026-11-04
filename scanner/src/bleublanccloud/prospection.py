"""Prospection du badge « Note A » : classeur PRIVÉ des communes notées A et de leur adresse
de contact publique (Annuaire de l'administration).

Exception assumée à la règle « les adresses électroniques de l'annuaire ne sont jamais
téléchargées » : cette commande, lancée à la main sur le serveur, relève l'adresse
institutionnelle de la mairie (champ `adresse_courriel`) pour lui proposer le badge.
Le classeur reste dans `donnees/prive/` (ignoré par git) : il n'est ni commité, ni exporté,
ni publié. Aucune adresse n'est devinée : sans adresse dans l'annuaire, la case reste vide.

Relancer la commande met les adresses et la liste à jour en conservant le suivi déjà saisi
(date d'envoi, statut, notes, adresse corrigée à la main).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from bleublanccloud.cibles.annuaire import (
    MOTS_SECONDAIRES,
    PIVOT_MAIRIE,
    URL_EXPORT,
    analyser_pivot,
    decoder_liste_json,
    filtre_pivot,
    normaliser_code_insee,
)
from bleublanccloud.modeles import EntreeIndex

CHAMPS_CONTACT = "nom,pivot,code_insee_commune,adresse_courriel"
MOTIF_COURRIEL = re.compile(r"[A-Za-z0-9._%+'-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,63}")
MOTIF_CODE_SLUG = re.compile(r"-(\d{5}|2[ab]\d{3})$")

STATUTS = (
    "À contacter",
    "Envoyé",
    "Relancé",
    "Réponse reçue",
    "Badge intégré",
    "Pas intéressé",
    "Adresse introuvable",
)
COULEURS_STATUTS = {
    "Envoyé": "DDEBF7",
    "Relancé": "FCE4D6",
    "Réponse reçue": "E2EFDA",
    "Badge intégré": "C6EFCE",
    "Pas intéressé": "EDEDED",
    "Adresse introuvable": "F8CBAD",
}
# Colonnes saisies à la main, conservées d'une exécution à l'autre
DATE_ENVOI = "Date mail envoyé"
COLONNES_SUIVI = (DATE_ENVOI, "E-mail de contact", "Source de l'e-mail", "Statut", "Notes")
# Anciens intitulés, relus pour ne pas perdre le suivi d'un classeur plus ancien
ANCIENS_INTITULES = {"Date d'envoi": DATE_ENVOI}
VERT_ENVOYE = "C6EFCE"
ENTETES = (
    DATE_ENVOI,
    "Commune",
    "Code dép.",
    "Département",
    "Population",
    "Score",
    "Domaine",
    "Site",
    "Fiche Bleu Blanc Cloud",
    "Badge clair (SVG)",
    "Badge sombre (SVG)",
    *COLONNES_SUIVI[1:],
    "Slug",
)
LARGEURS = (15, 30, 9, 24, 12, 8, 28, 30, 50, 48, 54, 34, 34, 18, 40, 28)
SOURCE_ANNUAIRE = "Annuaire de l'administration"


@dataclass(frozen=True)
class MairieContact:
    nom: str
    code_insee: str
    courriels: tuple[str, ...]


@dataclass
class LigneProspection:
    entree: EntreeIndex
    courriel: str | None = None
    source: str | None = None
    suivi: dict[str, Any] = field(default_factory=dict)


def code_insee_du_slug(slug: str) -> str | None:
    """Les slugs de communes finissent par le code INSEE (« albi-81004 », « ajaccio-2a004 »)."""
    trouve = MOTIF_CODE_SLUG.search(slug)
    return trouve.group(1).upper() if trouve else None


def communes_a_contacter(entrees: Iterable[EntreeIndex]) -> list[EntreeIndex]:
    """Communes éligibles au badge (note A non provisoire), de la plus peuplée à la moins."""
    retenues = [
        e for e in entrees if e.type == "commune" and e.note == "A" and not e.note_provisoire
    ]
    return sorted(retenues, key=lambda e: (-(e.population or 0), e.nom))


def extraire_courriels(valeur: Any) -> list[str]:
    """Adresses valides du champ `adresse_courriel` (texte, liste JSON, séparateurs variés)."""
    elements = decoder_liste_json(valeur)
    if elements is None:
        elements = [valeur]
    textes = [
        str(e.get("valeur", "")) if isinstance(e, dict) else str(e)
        for e in elements
        if e is not None
    ]
    courriels: list[str] = []
    for texte in textes:
        for courriel in MOTIF_COURRIEL.findall(texte):
            courriel = courriel.strip(".").lower()
            if courriel not in courriels:
                courriels.append(courriel)
    return courriels


def analyser_mairies(enregistrements: Any) -> dict[str, list[MairieContact]]:
    """Mairies confirmées de l'annuaire, regroupées par code INSEE."""
    par_code: dict[str, list[MairieContact]] = {}
    if not isinstance(enregistrements, list):
        return par_code
    for enregistrement in enregistrements:
        if not isinstance(enregistrement, dict):
            continue
        types, codes = analyser_pivot(enregistrement.get("pivot"))
        if PIVOT_MAIRIE not in types:
            continue
        code = normaliser_code_insee(enregistrement.get("code_insee_commune")) or (
            codes[0] if codes else None
        )
        if not code:
            continue
        mairie = MairieContact(
            nom=str(enregistrement.get("nom") or "").strip(),
            code_insee=code,
            courriels=tuple(extraire_courriels(enregistrement.get("adresse_courriel"))),
        )
        par_code.setdefault(code, []).append(mairie)
    return par_code


def _meme_domaine(courriel: str, domaine: str) -> bool:
    """« contact@ville-albi.fr » et « www.albi.fr » : on compare les deux derniers niveaux."""
    hote = courriel.rsplit("@", 1)[-1]
    racine = ".".join(domaine.lower().removeprefix("www.").split(".")[-2:])
    return hote == racine or hote.endswith(f".{racine}")


def choisir_courriel(mairies: list[MairieContact], domaine: str) -> tuple[str, str] | None:
    """Adresse de la mairie principale : (courriel, nom du service dans l'annuaire).

    Les annexes et mairies déléguées passent après la mairie principale ; une adresse sur le
    domaine du site de la commune est préférée aux autres.
    """
    candidats = [
        (
            (MOTS_SECONDAIRES.search(m.nom) is not None, not _meme_domaine(c, domaine), len(m.nom)),
            c,
            m,
        )
        for m in mairies
        for c in m.courriels
    ]
    if not candidats:
        return None
    _, courriel, mairie = min(candidats, key=lambda candidat: candidat[0])
    return courriel, mairie.nom


async def telecharger_mairies(client: httpx.AsyncClient) -> dict[str, list[MairieContact]]:
    """Toutes les mairies de l'annuaire avec leur adresse de contact (un seul appel)."""
    reponse = await client.get(
        URL_EXPORT,
        params={"select": CHAMPS_CONTACT, "where": filtre_pivot(PIVOT_MAIRIE)},
        timeout=180,
    )
    reponse.raise_for_status()
    return analyser_mairies(reponse.json())


def construire_lignes(
    entrees: list[EntreeIndex],
    mairies: dict[str, list[MairieContact]],
    suivi: dict[str, dict[str, Any]],
) -> list[LigneProspection]:
    """Associe chaque commune à l'adresse de sa mairie ; le suivi saisi à la main prime."""
    lignes: list[LigneProspection] = []
    for entree in entrees:
        ligne = LigneProspection(entree=entree, suivi=dict(suivi.get(entree.slug, {})))
        code = code_insee_du_slug(entree.slug)
        choix = choisir_courriel(mairies.get(code, []), entree.domaine) if code else None
        if choix:
            ligne.courriel = choix[0]
            ligne.source = f"{SOURCE_ANNUAIRE} ({choix[1]})"
        lignes.append(ligne)
    return lignes


def _openpyxl() -> Any:
    try:
        import openpyxl
    except ImportError as erreur:
        raise RuntimeError(
            "openpyxl est nécessaire : uv run --with openpyxl bbcloud prospection badge"
        ) from erreur
    return openpyxl


def lire_suivi(chemin: Path) -> dict[str, dict[str, Any]]:
    """Suivi déjà saisi dans un classeur précédent, par slug (colonnes de COLONNES_SUIVI)."""
    if not chemin.exists():
        return {}
    classeur = _openpyxl().load_workbook(chemin)
    if "Communes A" not in classeur.sheetnames:
        return {}
    feuille = classeur["Communes A"]
    lignes = feuille.iter_rows(values_only=True)
    entetes = [ANCIENS_INTITULES.get(str(e), e) for e in next(lignes, ())]
    if "Slug" not in entetes:
        return {}
    suivi: dict[str, dict[str, Any]] = {}
    for valeurs in lignes:
        ligne = dict(zip(entetes, valeurs, strict=False))
        if ligne.get("Slug"):
            suivi[str(ligne["Slug"])] = {
                c: ligne.get(c) for c in COLONNES_SUIVI if ligne.get(c) not in (None, "")
            }
    return suivi


def _valeurs(ligne: LigneProspection, url_site: str) -> list[Any]:
    e = ligne.entree
    suivi = ligne.suivi
    # Une adresse saisie ou corrigée à la main n'est jamais écrasée par l'annuaire
    courriel = suivi.get("E-mail de contact") or ligne.courriel
    source = suivi.get("Source de l'e-mail") or (ligne.source if ligne.courriel else None)
    if suivi.get("E-mail de contact") and not suivi.get("Source de l'e-mail"):
        source = "Saisie manuelle"
    statut = suivi.get("Statut") or ("À contacter" if courriel else "Adresse introuvable")
    return [
        suivi.get(DATE_ENVOI),
        e.nom,
        e.departement,
        e.departement_nom,
        e.population,
        e.score,
        e.domaine,
        f"https://{e.domaine}/",
        f"{url_site}/organisation/{e.slug}/",
        f"{url_site}/badge/{e.slug}.svg",
        f"{url_site}/badge/sombre/{e.slug}.svg",
        courriel,
        source,
        statut,
        suivi.get("Notes"),
        e.slug,
    ]


def ecrire_classeur(
    chemin: Path, lignes: list[LigneProspection], url_site: str, jour: date | None = None
) -> None:
    """Classeur de suivi : feuille « Communes A » (filtres, statuts colorés) + mode d'emploi."""
    openpyxl = _openpyxl()
    from openpyxl.formatting.rule import CellIsRule, FormulaRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.table import Table, TableStyleInfo

    jour = jour or date.today()
    classeur = openpyxl.Workbook()
    aide = classeur.active
    aide.title = "Mode d'emploi"
    avec = sum(1 for ligne in lignes if ligne.courriel or ligne.suivi.get("E-mail de contact"))
    textes = [
        ("Prospection badge « Note A » — Bleu Blanc Cloud", True),
        (
            f"Généré le {jour:%d/%m/%Y} : {len(lignes)} commune(s) notée(s) A (non provisoire), "
            f"{avec} avec une adresse de contact.",
            False,
        ),
        ("", False),
        (
            "Adresses : champ public « adresse_courriel » de l'Annuaire de l'administration "
            "(mairie principale). Aucune adresse n'est devinée.",
            False,
        ),
        (
            "Relancer « bbcloud prospection badge » met la liste à jour et conserve le suivi "
            "saisi (adresse corrigée, date d'envoi, statut, notes).",
            False,
        ),
        (
            "Message à envoyer : docs/modele-message-badge.md (remplacer [Commune], [score] et "
            "[slug]). Saisir la date d'envoi en colonne A : elle passe en vert.",
            False,
        ),
        ("", False),
        (
            "⚠ Fichier PRIVÉ : ne pas le committer, ne pas le copier dans site/public, ne pas le "
            "publier. Le supprimer une fois la campagne terminée.",
            True,
        ),
    ]
    for texte, gras in textes:
        aide.append([texte])
        aide.cell(aide.max_row, 1).font = Font(bold=gras, size=13 if aide.max_row == 1 else 11)
    aide.column_dimensions["A"].width = 120

    feuille = classeur.create_sheet("Communes A")
    feuille.append(list(ENTETES))
    for ligne in lignes:
        feuille.append(_valeurs(ligne, url_site))
    dernier = feuille.max_row
    for colonne, largeur in enumerate(LARGEURS, 1):
        feuille.column_dimensions[feuille.cell(1, colonne).column_letter].width = largeur
    for cellule in feuille[1]:
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = PatternFill("solid", fgColor="002395")
        cellule.alignment = Alignment(vertical="center", wrap_text=True)
    feuille.row_dimensions[1].height = 30
    numero = {intitule: rang + 1 for rang, intitule in enumerate(ENTETES)}
    lettre = {intitule: feuille.cell(1, c).column_letter for intitule, c in numero.items()}
    lien = Font(color="0563C1", underline="single")
    liens = ("Site", "Fiche Bleu Blanc Cloud", "Badge clair (SVG)", "Badge sombre (SVG)")
    for rang in range(2, dernier + 1):
        feuille.cell(rang, numero["Population"]).number_format = "# ##0"
        feuille.cell(rang, numero[DATE_ENVOI]).number_format = "DD/MM/YYYY"
        for intitule in liens:
            cellule = feuille.cell(rang, numero[intitule])
            cellule.hyperlink = cellule.value
            cellule.font = lien
    feuille.freeze_panes = "C2"  # date d'envoi et commune toujours visibles
    if dernier >= 2:
        table = Table(displayName="CommunesA", ref=f"A1:{lettre['Slug']}{dernier}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        feuille.add_table(table)
        # Date d'envoi en vert dès qu'elle est saisie
        date_envoi = lettre[DATE_ENVOI]
        feuille.conditional_formatting.add(
            f"{date_envoi}2:{date_envoi}{dernier}",
            FormulaRule(
                formula=[f"LEN(${date_envoi}2)>0"],
                fill=PatternFill("solid", fgColor=VERT_ENVOYE),
                font=Font(bold=True, color="006100"),
            ),
        )
        zone = f"{lettre['Statut']}2:{lettre['Statut']}{dernier}"
        validation = DataValidation(
            type="list", formula1=f'"{",".join(STATUTS)}"', allow_blank=True
        )
        feuille.add_data_validation(validation)
        validation.add(zone)
        for statut, couleur in COULEURS_STATUTS.items():
            feuille.conditional_formatting.add(
                zone,
                CellIsRule(
                    operator="equal",
                    formula=[f'"{statut}"'],
                    fill=PatternFill("solid", fgColor=couleur),
                ),
            )
    classeur.active = 1
    chemin.parent.mkdir(parents=True, exist_ok=True)
    classeur.save(chemin)
