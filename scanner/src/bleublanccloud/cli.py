"""Interface en ligne de commande « bbcloud »."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.table import Table

from bleublanccloud import __version__
from bleublanccloud.configuration import DOSSIER_TELECHARGEMENTS, obtenir_parametres
from bleublanccloud.modeles import Constat, ResultatScan
from bleublanccloud.referentiels import referentiels_par_defaut

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


@app.command()
def scanner(
    domaine: Annotated[str, typer.Argument(help="Domaine ou URL, ex. berachem.dev")],
    sortie_json: Annotated[bool, typer.Option("--json", help="Sortie JSON.")] = False,
) -> None:
    """Scan passif unitaire d'un domaine (DNS, IP, attribution)."""
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

    if sortie_json:
        typer.echo(json.dumps(resultat.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        afficher_resultat(resultat)


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
