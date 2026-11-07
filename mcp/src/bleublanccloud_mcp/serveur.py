"""Serveur MCP Bleu Blanc Cloud (stdio) : outils en lecture seule sur les données publiées.

Lancement : `uvx --from "git+https://codeberg.org/berachem/bleu-blanc-cloud#subdirectory=mcp"
bleublanccloud-mcp` (voir mcp/README.md).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from bleublanccloud_mcp import __version__, outils
from bleublanccloud_mcp.donnees import DonneeIntrouvable, SourceDonnees

INSTRUCTIONS = """\
Bleu Blanc Cloud est un observatoire indépendant et open source (sans lien avec l'État) de la
souveraineté numérique des collectivités françaises : communes de plus de 10 000 habitants,
départements et régions. Pour chacune, une analyse passive de l'empreinte visible publiquement
(hébergement du site, messagerie, DNS, suites collaboratives, services tiers, mesure
d'audience) donne un score de 0 à 100 et une note de A à E (A : fournisseurs européens ;
D ou E : forte dépendance à des fournisseurs soumis au Cloud Act américain).

Règles de réponse :
- Commencez par rechercher_collectivite pour obtenir l'identifiant (slug) d'une collectivité.
- Citez toujours le lien « url_fiche » : les preuves de chaque point retiré y figurent.
- Rappelez que le score est indicatif et ne porte que sur l'empreinte externe (pas les outils
  internes, pas la sécurité). Une note provisoire est à interpréter avec prudence.
- Ton factuel et pédagogique : parlez de « dépendance » et de « pistes », jamais de
  « mauvais élèves ». N'inventez aucun fournisseur ni aucune alternative : seules celles des
  outils existent.
"""

LECTURE_SEULE = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

serveur: MCPServer = MCPServer(
    name="Bleu Blanc Cloud",
    instructions=INSTRUCTIONS,
    website_url="https://bleublanccloud.fr/mcp/",
    version=__version__,
)
donnees = SourceDonnees()
# Les requêtes HTTP réussies n'ont pas à remplir le journal du client MCP
logging.getLogger("httpx").setLevel(logging.WARNING)


async def _repondre(appel: Awaitable[dict[str, Any]]) -> dict[str, Any]:
    """Site injoignable ou fichier absent : message clair plutôt qu'une trace d'erreur."""
    try:
        return await appel
    except DonneeIntrouvable as erreur:
        return {"erreur": f"Donnée introuvable sur {donnees.base} ({erreur})."}
    except httpx.HTTPError as erreur:
        return {
            "erreur": f"Site {donnees.base} injoignable pour le moment "
            f"({type(erreur).__name__}). Réessayez plus tard."
        }


@serveur.tool(annotations=LECTURE_SEULE)
async def rechercher_collectivite(
    texte: Annotated[str, Field(description="Nom, code INSEE, domaine ou département.")],
    limite: Annotated[int, Field(ge=1, le=50, description="Nombre de résultats.")] = 10,
) -> dict[str, Any]:
    """Trouve une collectivité (commune, département, région) et son identifiant (slug)."""
    return await _repondre(outils.rechercher_collectivite(donnees, texte, limite))


@serveur.tool(annotations=LECTURE_SEULE)
async def fiche_collectivite(
    slug: Annotated[str, Field(description="Identifiant renvoyé par rechercher_collectivite.")],
) -> dict[str, Any]:
    """Fiche complète : score, note, détail par catégorie, fournisseurs identifiés et leur
    juridiction, constats, évolution du score et pistes d'alternatives européennes."""
    return await _repondre(outils.fiche_collectivite(donnees, slug))


@serveur.tool(annotations=LECTURE_SEULE)
async def classement(
    departement: Annotated[
        str | None, Field(description="Code (« 33 ») ou nom (« Gironde ») du département.")
    ] = None,
    type: Annotated[
        Literal["commune", "departement", "region"] | None, Field(description="Type.")
    ] = None,
    note: Annotated[
        str | None, Field(description="Note(s) à garder, ex. « A » ou « D,E ».")
    ] = None,
    ordre: Annotated[
        Literal["meilleurs", "moins_bons"], Field(description="Ordre du classement.")
    ] = "meilleurs",
    limite: Annotated[int, Field(ge=1, le=50, description="Nombre de résultats.")] = 20,
) -> dict[str, Any]:
    """Classement des collectivités par score, avec filtres (département, type, note)."""
    return await _repondre(outils.classement(donnees, departement, type, note, ordre, limite))


@serveur.tool(annotations=LECTURE_SEULE)
async def comparer(
    slugs: Annotated[
        list[str], Field(min_length=2, max_length=6, description="2 à 6 identifiants (slugs).")
    ],
) -> dict[str, Any]:
    """Compare plusieurs collectivités : scores par catégorie et fournisseurs principaux."""
    return await _repondre(outils.comparer(donnees, slugs))


@serveur.tool(annotations=LECTURE_SEULE)
async def statistiques(
    departement: Annotated[
        str | None, Field(description="Code ou nom du département (vide : toute la France).")
    ] = None,
) -> dict[str, Any]:
    """Chiffres clés : nombre de collectivités, score moyen, répartition des notes."""
    return await _repondre(outils.statistiques(donnees, departement))


@serveur.tool(annotations=LECTURE_SEULE)
async def collectivites_par_fournisseur(
    fournisseur: Annotated[
        str, Field(description="Fournisseur ou service, ex. « Microsoft », « OVHcloud ».")
    ],
    categorie: Annotated[
        Literal["hebergement", "messagerie", "dns", "services_hors_ue"] | None,
        Field(description="Limiter à un usage (vide : tous)."),
    ] = None,
    departement: Annotated[str | None, Field(description="Code ou nom du département.")] = None,
    limite: Annotated[int, Field(ge=1, le=50, description="Nombre de résultats.")] = 30,
) -> dict[str, Any]:
    """Collectivités qui utilisent un fournisseur donné (ex. messagerie Microsoft en Gironde)."""
    return await _repondre(
        outils.collectivites_par_fournisseur(donnees, fournisseur, categorie, departement, limite)
    )


@serveur.tool(annotations=LECTURE_SEULE)
async def alternatives(
    categorie: Annotated[
        str | None,
        Field(description="Catégorie ou besoin, ex. « messagerie », « mesure d'audience »."),
    ] = None,
) -> dict[str, Any]:
    """Pistes françaises et européennes du référentiel Bleu Blanc Cloud, par catégorie."""
    return await _repondre(outils.alternatives(donnees, categorie))


@serveur.resource(
    "bleublanccloud://methodologie",
    name="methodologie",
    title="Méthodologie du score",
    description="Méthodologie publique et versionnée : sondes, juridictions, pondération.",
    mime_type="text/markdown",
)
async def methodologie() -> str:
    return await donnees.methodologie()


@serveur.prompt(title="Analyser ma collectivité")
def analyser_ma_collectivite(nom: str) -> str:
    """Analyse pédagogique de la dépendance numérique d'une collectivité."""
    return (
        f"Analyse la souveraineté numérique de « {nom} » avec Bleu Blanc Cloud : trouve sa "
        "fiche, explique sa note et ce qui la fait baisser (fournisseurs et juridictions), "
        "montre l'évolution si elle existe, propose les pistes européennes de la fiche, et "
        "donne le lien vers la fiche. Reste factuel et rappelle les limites du score."
    )


def principal() -> None:
    """Point d'entrée « bleublanccloud-mcp » (transport stdio)."""
    serveur.run("stdio")


if __name__ == "__main__":
    principal()
