"""Interface en ligne de commande « bbcloud »."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated, Any

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
app_cibles = typer.Typer(help="Organisations à analyser (import, liste, ajout manuel).")
app.add_typer(app_cibles, name="cibles")
app_campagne = typer.Typer(help="Campagnes de scan.")
app.add_typer(app_campagne, name="campagne")
app_rapports = typer.Typer(help="Rapports rédigés par l'IA (Mistral).")
app.add_typer(app_rapports, name="rapports")
app_photos = typer.Typer(help="Photos des organisations (Wikimedia Commons, auto-hébergées).")
app.add_typer(app_photos, name="photos")
app_demandes = typer.Typer(
    help="Analyses sur demande (tickets « Analyser mon site » sur Codeberg)."
)
app.add_typer(app_demandes, name="demandes")

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
    provisoire = " [yellow](provisoire)[/]" if score.provisoire else ""
    console.print(
        f"Score global : [bold]{score.score_global}/100[/]  Note : {_badge(score.note)}"
        f"{provisoire}  Couverture : {score.couverture:.0f} %\n"
    )
    if score.provisoire:
        console.print(
            "[yellow]Plus de 30 % du poids applicable n'a pas pu être évalué (fournisseurs "
            "inconnus ou données indisponibles) : la note est provisoire.[/]"
        )
    console.print(
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
# Cibles
# --------------------------------------------------------------------------- #


@app_cibles.command("importer")
def cibles_importer(
    population_min: Annotated[
        int, typer.Option("--population-min", help="Population minimale des communes.")
    ] = 10_000,
    types: Annotated[
        str, typer.Option("--types", help="Types à importer, séparés par des virgules.")
    ] = "commune,departement,region",
) -> None:
    """Importe communes, départements et régions (API Annuaire + geo.api.gouv.fr)."""
    from bleublanccloud.cibles.importation import (
        bilan_mairies,
        construire_organisations,
        enregistrer_import,
        telecharger_donnees,
    )

    parametres = obtenir_parametres()
    liste_types = [t.strip() for t in types.split(",") if t.strip()]

    async def telecharger() -> Any:
        async with httpx.AsyncClient(
            headers={"User-Agent": parametres.user_agent}, timeout=120, follow_redirects=True
        ) as client:
            return await telecharger_donnees(client, liste_types)

    try:
        donnees = asyncio.run(telecharger())
    except httpx.HTTPError as erreur:
        console_erreur.print(f"[red]Téléchargement impossible : {erreur}[/]")
        raise typer.Exit(code=1) from erreur
    organisations = construire_organisations(donnees, population_min, liste_types)
    if "commune" in liste_types:
        bilan = bilan_mairies(donnees, population_min)
        console.print(f"Mairies trouvées dans l'annuaire : [bold]{bilan.trouvees}[/]")
        if bilan.sans_code_insee:
            console.print(f"  [yellow]dont {bilan.sans_code_insee} sans code INSEE exploitable[/]")
        console.print(
            f"Mairies rapprochées d'une commune ≥ {population_min} hab. : "
            f"[bold]{bilan.rapprochees}[/] / {bilan.communes_retenues} commune(s)"
        )
        console.print(f"Mairies avec site web : [bold]{bilan.avec_site_web}[/]")
        if bilan.trouvees == 0:
            console.print(
                "[yellow]⚠ Aucune mairie reçue de l'annuaire : vérifiez l'URL de l'API "
                "et le filtre « pivot like » (bbcloud -v cibles importer).[/]"
            )
    with Base(parametres.base_sqlite) as base:
        rapport = enregistrer_import(base, donnees, organisations)
    console.print(
        f"[green]✓[/] {rapport.organisations} organisation(s) importée(s), "
        f"dont {rapport.avec_site} avec un site web connu."
    )
    if rapport.sans_site:
        console.print(f"[yellow]{len(rapport.sans_site)} sans site web[/] (non analysables).")


@app_cibles.command("lister")
def cibles_lister(
    limite: Annotated[int, typer.Option("--limite", help="Nombre maximal de lignes.")] = 50,
) -> None:
    """Liste les organisations enregistrées."""
    parametres = obtenir_parametres()
    with Base(parametres.base_sqlite) as base:
        organisations = base.organisations(limite=limite)
    tableau = Table(expand=True)
    for colonne in ("Slug", "Nom", "Type", "Département", "Population", "Site web"):
        tableau.add_column(colonne)
    for enregistree in organisations:
        o = enregistree.organisation
        tableau.add_row(
            o.slug, o.nom, o.type, o.departement or "", str(o.population or ""), o.site_web or ""
        )
    console.print(tableau)


@app_cibles.command("ajouter")
def cibles_ajouter(
    nom: Annotated[str, typer.Option("--nom", help="Nom affiché.")],
    site_web: Annotated[str, typer.Option("--site", help="URL du site web.")],
    type_organisation: Annotated[
        str, typer.Option("--type", help="commune, departement…")
    ] = "autre",
    departement: Annotated[str | None, typer.Option("--departement")] = None,
    population: Annotated[int | None, typer.Option("--population")] = None,
) -> None:
    """Ajoute manuellement une organisation (ex. un domaine de test autorisé)."""
    from bleublanccloud.cibles.importation import slugifier
    from bleublanccloud.modeles import Organisation

    parametres = obtenir_parametres()
    organisation = Organisation(
        slug=slugifier(nom),
        nom=nom,
        type=type_organisation,
        departement=departement,
        population=population,
        site_web=site_web,
        source="ajout manuel",
    )
    with Base(parametres.base_sqlite) as base:
        base.enregistrer_organisation(organisation)
    console.print(f"[green]✓[/] {nom} ajoutée (slug : {organisation.slug}).")


# --------------------------------------------------------------------------- #
# Campagne
# --------------------------------------------------------------------------- #


@app_campagne.command("lancer")
def campagne_lancer(
    limite: Annotated[
        int | None, typer.Option("--limite", help="Nombre maximal d'organisations.")
    ] = None,
    organisation: Annotated[
        str | None, typer.Option("--organisation", help="Slug d'une seule organisation.")
    ] = None,
    simulation: Annotated[
        bool, typer.Option("--dry-run", help="Liste les cibles sans aucune requête réseau.")
    ] = False,
    oui: Annotated[
        bool, typer.Option("--oui", help="Ne demande pas de confirmation (timer systemd).")
    ] = False,
) -> None:
    """Scanne les organisations enregistrées et enregistre leurs scores."""
    from rich.progress import Progress

    from bleublanccloud.campagne import lancer_campagne, preparer_cibles
    from bleublanccloud.scan import contexte_reseau

    parametres = obtenir_parametres()
    referentiels = referentiels_par_defaut()
    with Base(parametres.base_sqlite) as base:
        base.synchroniser_retraits(referentiels.retraits)
        if organisation:
            unique = base.organisation_par_slug(organisation)
            if unique is None:
                console_erreur.print(f"[red]Organisation inconnue : {organisation}[/]")
                raise typer.Exit(code=2)
            candidates = [unique]
        else:
            candidates = base.organisations(avec_site=True)
        cibles, ignorees = preparer_cibles(candidates, referentiels.est_retire, limite)
        console.print(f"{len(cibles)} organisation(s) à analyser, {len(ignorees)} ignorée(s).")
        for ligne in ignorees[:10]:
            console.print(f"  [grey50]• {ligne}[/]")
        if simulation:
            for cible in cibles[:20]:
                console.print(f"  • {cible.organisation.organisation.nom} → {cible.domaine}")
            if len(cibles) > 20:
                console.print(f"  … et {len(cibles) - 20} autre(s).")
            console.print("[yellow]Simulation : aucune requête n'a été envoyée.[/]")
            return
        if not cibles:
            return
        if not oui and not typer.confirm(
            f"Lancer l'analyse passive de {len(cibles)} domaine(s) réel(s) ?", default=False
        ):
            raise typer.Abort()

        async def executer() -> Any:
            async with contexte_reseau(parametres, referentiels) as contexte:
                with Progress(console=console) as barre:
                    tache = barre.add_task("Scan", total=len(cibles))
                    return await lancer_campagne(
                        base,
                        contexte,
                        cibles,
                        progression=lambda *_: barre.advance(tache),
                    )

        rapport = asyncio.run(executer())
    repartition = " · ".join(f"{note} : {n}" for note, n in sorted(rapport.notes.items()))
    console.print(
        f"[green]✓[/] {rapport.scannees}/{rapport.prevues} scannée(s), "
        f"{rapport.notees} notée(s). {repartition}"
    )
    for erreur in rapport.erreurs[:20]:
        console.print(f"[yellow]⚠ {erreur}[/]")


# --------------------------------------------------------------------------- #
# Rapports IA
# --------------------------------------------------------------------------- #


@app_rapports.command("generer")
def rapports_generer(
    maximum: Annotated[
        int | None, typer.Option("--max", help="Nombre maximal de rapports à générer.")
    ] = None,
    simulation: Annotated[
        bool, typer.Option("--dry-run", help="Estime les appels et le coût, sans appel à l'API.")
    ] = False,
    oui: Annotated[bool, typer.Option("--oui", help="Ne demande pas de confirmation.")] = False,
) -> None:
    """Génère les rapports IA des derniers scans (cache : aucun appel si rien n'a changé)."""
    from rich.progress import Progress

    from bleublanccloud.ia.client_mistral import (
        ClientMistral,
        GenerateurRapports,
        construire_messages,
        estimer,
    )
    from bleublanccloud.ia.generation import appliquer_cache, generer_rapports, planifier

    parametres = obtenir_parametres()
    referentiels = referentiels_par_defaut()
    modele = parametres.mistral_modele
    with Base(parametres.base_sqlite) as base:
        plan = planifier(base, referentiels, modele)
        taches = plan.a_generer[:maximum] if maximum is not None else plan.a_generer
        estimation = estimer(
            [construire_messages(t.demande, referentiels.fournisseurs) for t in taches],
            parametres.mistral_prix_entree_par_m,
            parametres.mistral_prix_sortie_par_m,
        )
        console.print(
            f"Modèle : {modele} · {plan.deja_a_jour} rapport(s) à jour · "
            f"{len(plan.depuis_cache)} réutilisable(s) depuis le cache · "
            f"{len(plan.a_generer)} à générer"
            + (f" (limité à {len(taches)})" if maximum is not None else "")
        )
        console.print(f"Estimation : {estimation.en_texte()}")
        if simulation:
            console.print("[yellow]Simulation : aucun appel à l'API n'a été effectué.[/]")
            return
        appliquer_cache(base, plan, modele)
        if not taches:
            console.print("[green]✓[/] Rien à générer.")
            return
        if parametres.mistral_api_key is None:
            console_erreur.print("[red]MISTRAL_API_KEY manquante dans le fichier .env.[/]")
            raise typer.Exit(code=1)
        if not oui and not typer.confirm(f"Générer {len(taches)} rapport(s) ?", default=False):
            raise typer.Abort()
        generateur = GenerateurRapports(
            client=ClientMistral(
                parametres.mistral_api_key.get_secret_value(), parametres.mistral_serveur
            ),
            modele=modele,
            fournisseurs=referentiels.fournisseurs,
            alternatives_connues=referentiels.alternatives,
        )

        async def executer() -> Any:
            with Progress(console=console) as barre:
                tache_barre = barre.add_task("Rapports", total=len(taches))
                return await generer_rapports(
                    base, taches, generateur, progression=lambda _: barre.advance(tache_barre)
                )

        bilan = asyncio.run(executer())
    cout = (
        bilan.jetons_entree * parametres.mistral_prix_entree_par_m
        + bilan.jetons_sortie * parametres.mistral_prix_sortie_par_m
    ) / 1_000_000
    console.print(
        f"[green]✓[/] {bilan.generes} rapport(s) générés, {len(bilan.en_erreur)} en erreur, "
        f"{bilan.appels} appel(s), coût réel ≈ {cout:.4f} $."
    )
    for erreur in bilan.en_erreur[:20]:
        console.print(f"[yellow]⚠ {erreur}[/]")


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
        rapport = exporter_site(
            base, referentiels_par_defaut(), vers, dossier_photos=parametres.photos
        )
    console.print(
        f"[green]✓[/] {rapport.nombre_organisations} organisation(s) exportée(s) vers {vers}"
    )
    if rapport.fichiers_supprimes:
        console.print(f"{rapport.fichiers_supprimes} ancien(s) fichier(s) supprimé(s).")
    for ignoree in rapport.ignorees:
        console.print(f"[yellow]Ignorée :[/] {ignoree}")


@app_photos.command("maj")
def photos_maj(
    forcer: Annotated[
        bool, typer.Option("--forcer", help="Revérifie aussi les photos récentes.")
    ] = False,
    limite: Annotated[
        int | None, typer.Option("--limite", help="Nombre maximal d'organisations.")
    ] = None,
) -> None:
    """Cherche la photo de chaque organisation (Wikidata → Commons, licence libre) et la
    télécharge pour la publier avec le site. Les photos de plus de 30 jours sont revérifiées."""
    from datetime import UTC, datetime

    from rich.markup import escape

    from bleublanccloud.photos import mettre_a_jour_photos

    parametres = obtenir_parametres()

    async def executer() -> Any:
        async with httpx.AsyncClient(
            headers={"User-Agent": parametres.user_agent},
            timeout=parametres.delai_expiration_s * 3,
            follow_redirects=False,
        ) as client:
            return await mettre_a_jour_photos(
                base, parametres.photos, client, datetime.now(UTC), forcer=forcer, limite=limite
            )

    with Base(parametres.base_sqlite) as base:
        try:
            bilan = asyncio.run(executer())
        except httpx.HTTPError as erreur:
            console_erreur.print(f"[red]Wikimedia injoignable : {escape(str(erreur))}[/]")
            raise typer.Exit(code=1) from None
    console.print(
        f"[green]✓[/] {bilan.trouvees} photo(s) téléchargée(s) · {bilan.absentes} sans photo · "
        f"{len(bilan.refusees)} refusée(s) (licence) · {len(bilan.erreurs)} en erreur · "
        f"{bilan.inchangees} déjà à jour"
    )
    for ligne in (bilan.refusees + bilan.erreurs)[:20]:
        console.print(f"[yellow]•[/] {escape(ligne)}")


@app_demandes.command("traiter")
def demandes_traiter() -> None:
    """Traite les tickets ouverts : validation, analyse, publication et réponse."""
    from rich.markup import escape

    from bleublanccloud.demandes.execution import traiter_demandes
    from bleublanccloud.demandes.forge import ErreurForge
    from bleublanccloud.verrou import verrou_exclusif

    parametres = obtenir_parametres()
    if parametres.codeberg_jeton is None:
        console.print("[yellow]CODEBERG_JETON absent du fichier .env : aucune demande traitée.[/]")
        return
    with verrou_exclusif(parametres.verrou) as obtenu:
        if not obtenu:
            console.print(
                "Une autre tâche Bleu Blanc Cloud (campagne, mise à jour) est en cours : "
                "traitement reporté au prochain passage."
            )
            return
        referentiels = referentiels_par_defaut()
        with Base(parametres.base_sqlite) as base:
            try:
                bilan = asyncio.run(traiter_demandes(parametres, referentiels, base))
            except ErreurForge as erreur:
                console_erreur.print(f"[red]Codeberg injoignable : {escape(str(erreur))}[/]")
                raise typer.Exit(code=1) from None
    console.print(
        f"{bilan.lues} demande(s) ouverte(s) · {len(bilan.traitees)} traitée(s) · "
        f"{len(bilan.refusees)} refusée(s) · {len(bilan.erreurs)} en erreur"
    )
    for numero in bilan.traitees:
        console.print(f"[green]✓[/] ticket #{numero} traité")
    for numero, code in bilan.refusees:
        console.print(f"[yellow]✗[/] ticket #{numero} refusé ({escape(code)})")
    for numero, raison in bilan.erreurs:
        console.print(f"[red]⚠[/] ticket #{numero} : {escape(raison)}")
    if bilan.reponses_en_attente:
        console.print(
            f"[yellow]Réponses reportées au prochain passage : {bilan.reponses_en_attente}[/]"
        )
    if bilan.publication is False:
        raise typer.Exit(code=1)


@app_demandes.command("lister")
def demandes_lister() -> None:
    """Liste les demandes ouvertes et le verdict de validation (lecture seule, aucun scan)."""
    from rich.markup import escape

    from bleublanccloud.demandes.forge import ClientForge, ErreurForge
    from bleublanccloud.demandes.tickets import Ticket, case_cochee, extraire_domaine
    from bleublanccloud.demandes.validation import DomaineRefuse, valider_domaine

    parametres = obtenir_parametres()
    if parametres.codeberg_jeton is None:
        console_erreur.print("[red]CODEBERG_JETON absent du fichier .env.[/]")
        raise typer.Exit(code=1)
    jeton = parametres.codeberg_jeton

    async def lire() -> list[Ticket]:
        async with ClientForge(parametres.depot_demandes, jeton, parametres.codeberg_api) as forge:
            return [t for t in await forge.tickets_ouverts() if t.est_demande]

    try:
        tickets = asyncio.run(lire())
    except ErreurForge as erreur:
        console_erreur.print(f"[red]Codeberg injoignable : {escape(str(erreur))}[/]")
        raise typer.Exit(code=1) from None
    tableau = Table(title=f"Demandes ouvertes sur {parametres.depot_demandes}", expand=True)
    tableau.add_column("Ticket", justify="right")
    tableau.add_column("Compte")
    tableau.add_column("Domaine validé")
    tableau.add_column("Case cochée")
    for ticket in tickets:
        try:
            domaine = valider_domaine(extraire_domaine(ticket))
        except DomaineRefuse as refus:
            domaine = f"refusé ({refus.code})"
        tableau.add_row(
            f"#{ticket.numero}",
            escape(ticket.auteur),
            escape(domaine),
            "oui" if case_cochee(ticket) else "non",
        )
    console.print(tableau)


@app.command()
def publier() -> None:
    """Export des données, construction du site et publication sur Codeberg Pages."""
    import subprocess

    script = RACINE_PROJET / "deploy" / "publier.sh"
    resultat = subprocess.run(["bash", str(script)], check=False)
    raise typer.Exit(code=resultat.returncode)


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


@app_referentiels.command("inconnus")
def referentiels_inconnus(
    limite: Annotated[int, typer.Option("--limite")] = 30,
) -> None:
    """Hébergeurs, MX et DNS non identifiés les plus fréquents (pour enrichir le référentiel)."""
    parametres = obtenir_parametres()
    with Base(parametres.base_sqlite) as base:
        statistiques = base.statistiques_inconnus(limite)
    tableau = Table(
        title="Preuves non attribuées (dernier scan de chaque organisation)", expand=True
    )
    tableau.add_column("Catégorie")
    tableau.add_column("ASN ou domaine")
    tableau.add_column("Organisations", justify="right")
    for categorie, cle, nombre in statistiques:
        tableau.add_row(LIBELLES_CATEGORIES.get(categorie, categorie), cle, str(nombre))
    console.print(tableau)


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
