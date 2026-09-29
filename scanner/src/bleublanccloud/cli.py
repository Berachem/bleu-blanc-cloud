"""Interface en ligne de commande « bbcloud »."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from bleublanccloud import __version__
from bleublanccloud.analyse.score import VERSION_METHODO, ScoreImpossible, calculer_score
from bleublanccloud.configuration import (
    DOSSIER_TELECHARGEMENTS,
    RACINE_PROJET,
    obtenir_parametres,
)
from bleublanccloud.modeles import Constat, ResultatScan, Score
from bleublanccloud.referentiels import referentiels_par_defaut
from bleublanccloud.stockage.base import Base

app = typer.Typer(
    help="Bleu Blanc Cloud — observatoire de la souveraineté numérique.",
    no_args_is_help=True,
)
app_referentiels = typer.Typer(help="Référentiels : fournisseurs, plages IP, base ASN.")
app.add_typer(app_referentiels, name="referentiels")

console = Console()
console_erreur = Console(stderr=True)

COULEURS_NIVEAUX = {
    "A": "bold white on #003399",
    "B": "bold white on #3A6BD6",
    "C": "bold black on #FFCC00",
    "D": "bold black on #F08A24",
    "E": "bold white on #ED2939",
    "inconnu": "bold white on grey42",
}
LIBELLES_CATEGORIES = {
    "hebergement": "Hébergement",
    "messagerie": "Messagerie",
    "dns": "DNS",
    "suites_saas": "Suites et SaaS",
    "services_tiers": "Services tiers",
    "mesure_audience": "Mesure d'audience",
    "informatif": "Informatif",
}


@app.callback()
def principal(
    verbeux: Annotated[bool, typer.Option("--verbeux", "-v", help="Journal détaillé.")] = False,
) -> None:
    """Bleu Blanc Cloud — observatoire de la souveraineté numérique."""
    logging.basicConfig(
        level=logging.INFO if verbeux else logging.WARNING,
        format="%(levelname)s %(name)s : %(message)s",
    )


@app.command()
def version() -> None:
    """Affiche la version du scanner."""
    console.print(f"bbcloud {__version__}")


# --------------------------------------------------------------------------- #
# Scan unitaire
# --------------------------------------------------------------------------- #


def _badge(niveau: str) -> str:
    return f"[{COULEURS_NIVEAUX.get(niveau, '')}] {niveau} [/]"


def _nom_fournisseur(constat: Constat) -> str:
    if constat.fournisseur_id is None:
        return "[grey50]non identifié[/]"
    fournisseur = referentiels_par_defaut().fournisseurs.get(constat.fournisseur_id)
    return fournisseur.nom if fournisseur else constat.fournisseur_id


def afficher_resultat(resultat: ResultatScan) -> None:
    """Affichage lisible d'un résultat de scan."""
    console.rule(f"[bold]{resultat.domaine}[/] — statut : {resultat.statut}")
    tableau = Table(show_lines=False, expand=True)
    tableau.add_column("Catégorie", style="bold")
    tableau.add_column("Constat")
    tableau.add_column("Valeur", overflow="fold")
    tableau.add_column("Fournisseur")
    tableau.add_column("Niveau", justify="center")
    ordre = list(LIBELLES_CATEGORIES)
    for constat in sorted(resultat.constats, key=lambda c: ordre.index(c.categorie)):
        niveau = _badge(constat.niveau) if constat.categorie != "informatif" else ""
        tableau.add_row(
            LIBELLES_CATEGORIES[constat.categorie],
            constat.cle,
            constat.valeur,
            _nom_fournisseur(constat) if constat.categorie != "informatif" else "",
            niveau,
        )
    console.print(tableau)
    infos = resultat.informations
    if infos.bureau_enregistrement:
        console.print(f"Bureau d'enregistrement : {infos.bureau_enregistrement}")
    if infos.autorite_certification:
        console.print(f"Autorité de certification : {infos.autorite_certification}")
    if infos.fournisseurs_secnumcloud:
        console.print(
            "Fournisseurs proposant une offre qualifiée SecNumCloud : "
            + ", ".join(infos.fournisseurs_secnumcloud)
        )
    for erreur in resultat.erreurs:
        console.print(f"[yellow]⚠ {erreur}[/]")


def afficher_score(score: Score) -> None:
    """Affichage du score global et du détail par catégorie."""
    tableau = Table(title=f"Méthodologie v{score.version_methodo}", expand=True)
    tableau.add_column("Catégorie", style="bold")
    tableau.add_column("Poids", justify="right")
    tableau.add_column("Score", justify="right")
    tableau.add_column("Explication", overflow="fold")
    for detail in score.detail:
        tableau.add_row(
            detail.libelle,
            f"{detail.poids_effectif:.0f} %" if detail.evaluable else "—",
            f"{detail.score:.0f}/100" if detail.score is not None else "n. é.",
            detail.explication,
        )
    console.print(tableau)
    console.print(
        f"Score global : [bold]{score.score_global}/100[/]  Note : {_badge(score.note)}\n"
        "[grey50]Le score ne reflète que l'empreinte externe et visible publiquement, "
        "pas les outils internes.[/]"
    )


@app.command()
def scanner(
    domaine: Annotated[str, typer.Argument(help="Domaine ou URL, ex. berachem.dev")],
    sortie_json: Annotated[bool, typer.Option("--json", help="Sortie JSON.")] = False,
    enregistrer: Annotated[
        bool, typer.Option("--enregistrer", help="Enregistre le scan dans la base SQLite.")
    ] = False,
) -> None:
    """Scan passif unitaire d'un domaine (DNS, IP, HTTP, TLS, RDAP) et calcul du score."""
    from bleublanccloud.scan import CibleInvalide, contexte_reseau, scanner_domaine

    parametres = obtenir_parametres()

    async def executer() -> ResultatScan:
        async with contexte_reseau(parametres, referentiels_par_defaut()) as contexte:
            return await scanner_domaine(domaine, contexte)

    try:
        resultat = asyncio.run(executer())
    except CibleInvalide as erreur:
        console_erreur.print(f"[red]Cible invalide : {erreur}[/]")
        raise typer.Exit(code=2) from erreur

    score: Score | None
    try:
        score = calculer_score(resultat.constats, resultat.sondes_reussies)
    except ScoreImpossible:
        score = None

    if enregistrer:
        with Base(parametres.base_sqlite) as base:
            scan_id = base.enregistrer_scan(None, resultat, score, VERSION_METHODO)
        console_erreur.print(f"Scan enregistré (n° {scan_id}) dans {parametres.base_sqlite}")

    if sortie_json:
        donnees = resultat.model_dump(mode="json")
        donnees["score"] = score.model_dump(mode="json") if score else None
        typer.echo(json.dumps(donnees, ensure_ascii=False, indent=2))
    else:
        afficher_resultat(resultat)
        if score is not None:
            afficher_score(score)
        else:
            console.print("[yellow]Score impossible : aucune catégorie évaluable.[/]")


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


@app.command()
def exporter(
    vers: Annotated[
        Path, typer.Option("--vers", help="Dossier de sortie (site/public/donnees).")
    ] = RACINE_PROJET / "site" / "public" / "donnees",
) -> None:
    """Exporte les fichiers JSON statiques du site (dernier scan noté de chaque organisation)."""
    from bleublanccloud.export.site_statique import exporter as exporter_site

    parametres = obtenir_parametres()
    with Base(parametres.base_sqlite) as base:
        rapport = exporter_site(base, referentiels_par_defaut(), vers)
    console.print(
        f"[green]✓[/] {rapport.nombre_organisations} organisation(s) exportée(s) vers {vers}"
    )
    if rapport.fichiers_supprimes:
        console.print(f"{rapport.fichiers_supprimes} ancien(s) fichier(s) supprimé(s).")
    for ignoree in rapport.ignorees:
        console.print(f"[yellow]Ignorée :[/] {ignoree}")


@app.command()
def demo(
    vers: Annotated[
        Path, typer.Option("--vers", help="Dossier de sortie des données fictives.")
    ] = RACINE_PROJET / "site" / "src" / "donnees-demo",
) -> None:
    """Génère les données de démonstration FICTIVES utilisées par le site en développement."""
    from bleublanccloud.export.demonstration import generer_demonstration, noms_departements_demo
    from bleublanccloud.export.site_statique import ecrire_export

    referentiels = referentiels_par_defaut()
    organisations = generer_demonstration(referentiels)
    ecrire_export(
        vers,
        organisations,
        noms_departements_demo(),
        referentiels,
        donnees_demonstration=True,
    )
    for organisation in organisations:
        console.print(
            f"{_badge(organisation.score.note)} {organisation.score.score_global:>3} "
            f"{organisation.nom}"
        )
    console.print(f"[green]✓[/] {len(organisations)} organisations fictives écrites dans {vers}")


@app.command()
def schemas(
    vers: Annotated[
        Path, typer.Option("--vers", help="Dossier de sortie des schémas JSON.")
    ] = RACINE_PROJET / "site" / "src" / "types",
) -> None:
    """Écrit le schéma JSON du contrat de données (types TypeScript du site)."""
    from bleublanccloud.export.schemas import ecrire_schema

    chemin = ecrire_schema(vers)
    console.print(f"[green]✓[/] schéma écrit : {chemin}")


# --------------------------------------------------------------------------- #
# Référentiels
# --------------------------------------------------------------------------- #


@app_referentiels.command("maj")
def referentiels_maj() -> None:
    """Télécharge les plages IP des clouds, la base ASN, l'amorçage RDAP et vérifie la liste
    SecNumCloud."""
    from bleublanccloud.referentiels.telechargement import (
        RapportMiseAJour,
        telecharger_base_asn,
        telecharger_bootstrap_rdap,
        telecharger_plages_cloud,
        verifier_secnumcloud,
    )

    parametres = obtenir_parametres()
    rapport = RapportMiseAJour()
    jeton = parametres.ipinfo_token.get_secret_value() if parametres.ipinfo_token else None

    async def executer() -> None:
        async with httpx.AsyncClient(
            headers={"User-Agent": parametres.user_agent},
            timeout=60,
            follow_redirects=True,
        ) as client:
            await telecharger_plages_cloud(client, DOSSIER_TELECHARGEMENTS, rapport)
            await telecharger_base_asn(client, jeton, parametres.base_asn, rapport)
            await telecharger_bootstrap_rdap(client, DOSSIER_TELECHARGEMENTS, rapport)
            await verifier_secnumcloud(
                client, list(referentiels_par_defaut().fournisseurs.values()), rapport
            )

    asyncio.run(executer())
    for source, nombre in rapport.plages_par_source.items():
        console.print(f"[green]✓[/] plages {source} : {nombre}")
    if rapport.base_asn:
        console.print(f"[green]✓[/] base ASN : {rapport.base_asn}")
    if rapport.bootstrap_rdap:
        console.print("[green]✓[/] amorçage RDAP")
    for remarque in rapport.secnumcloud:
        console.print(f"[yellow]SecNumCloud :[/] {remarque}")
    for erreur in rapport.erreurs:
        console.print(f"[yellow]⚠ {erreur}[/]")


@app_referentiels.command("verifier")
def referentiels_verifier() -> None:
    """Valide les référentiels YAML et liste les faits encore à vérifier."""
    referentiels = referentiels_par_defaut()
    a_verifier = [f for f in referentiels.fournisseurs.values() if f.a_verifier]
    console.print(
        f"[green]✓[/] {len(referentiels.fournisseurs)} fournisseurs, "
        f"{len(referentiels.regles)} règles, {len(referentiels.alternatives)} alternatives, "
        f"{len(referentiels.retraits)} retraits."
    )
    console.print(f"{len(a_verifier)} fournisseurs marqués « a_verifier ».")
    for fournisseur in a_verifier:
        if fournisseur.remarque:
            console.print(f"  • [bold]{fournisseur.nom}[/] : {fournisseur.remarque}")


if __name__ == "__main__":
    app()
