"""Assemblage réel du traitement des demandes (réseau, forge, IA, publication)."""

from __future__ import annotations

import asyncio
import os
import subprocess

from bleublanccloud.configuration import RACINE_PROJET, Parametres
from bleublanccloud.demandes.forge import ClientForge
from bleublanccloud.demandes.tickets import Ticket
from bleublanccloud.demandes.traitement import (
    SOURCE_EMAIL,
    AnalyseDirecte,
    BilanDemandes,
    GenererRapport,
    TraiteurDemandes,
)
from bleublanccloud.modeles import ResultatScan
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import ContexteScan, contexte_reseau, scanner_domaine
from bleublanccloud.sondes.dns import ResolveurDns
from bleublanccloud.stockage.base import Base

SCRIPT_PUBLICATION = RACINE_PROJET / "deploy" / "publier.sh"


async def adresses_du_site(hote: str, resolveur: ResolveurDns) -> list[str]:
    """Adresses IP du nom demandé, à défaut celles de son sous-domaine www."""
    candidats = [hote] if hote.startswith("www.") else [hote, f"www.{hote}"]
    for candidat in candidats:
        resolution = await resolveur.resoudre(candidat)
        adresses = resolution.ipv4 + resolution.ipv6
        if adresses:
            return adresses
    return []


async def publier_site() -> bool:
    """Export + build + publication (deploy/publier.sh), arguments fixes : aucune donnée de
    ticket n'est transmise au script."""
    environnement = {**os.environ, "NPM_CI": "0", "EXIGER_DONNEES": "1"}
    resultat = await asyncio.to_thread(
        subprocess.run, ["bash", str(SCRIPT_PUBLICATION)], env=environnement, check=False
    )
    return resultat.returncode == 0


def _generateur_rapports(
    parametres: Parametres, referentiels: Referentiels, base: Base
) -> GenererRapport | None:
    """Rapport IA d'un scan, avec le cache habituel ; None si aucune clé Mistral."""
    if parametres.mistral_api_key is None:
        return None
    from bleublanccloud.ia.client_mistral import ClientMistral, GenerateurRapports
    from bleublanccloud.ia.generation import generer_rapports, tache_pour_scan

    generateur = GenerateurRapports(
        client=ClientMistral(
            parametres.mistral_api_key.get_secret_value(), parametres.mistral_serveur
        ),
        modele=parametres.mistral_modele,
        fournisseurs=referentiels.fournisseurs,
        alternatives_connues=referentiels.alternatives,
    )

    async def generer(scan_id: int) -> None:
        tache = tache_pour_scan(base, referentiels, parametres.mistral_modele, scan_id)
        if tache is not None:
            await generer_rapports(base, [tache], generateur)

    return generer


async def traiter_demandes(
    parametres: Parametres, referentiels: Referentiels, base: Base
) -> BilanDemandes:
    assert parametres.codeberg_jeton is not None
    async with (
        ClientForge(
            parametres.depot_demandes,
            parametres.codeberg_jeton,
            url_api=parametres.codeberg_api,
            user_agent=parametres.user_agent,
        ) as forge,
        contexte_reseau(parametres, referentiels) as contexte,
    ):
        contexte_scan: ContexteScan = contexte

        async def analyser(hote: str) -> ResultatScan:
            return await scanner_domaine(hote, contexte_scan)

        async def resoudre(hote: str) -> list[str]:
            return await adresses_du_site(hote, contexte_scan.resolveur_dns)

        traiteur = TraiteurDemandes(
            base=base,
            referentiels=referentiels,
            forge=forge,
            analyser=analyser,
            resoudre=resoudre,
            publier=publier_site,
            url_site=parametres.url_site,
            generer_rapport=_generateur_rapports(parametres, referentiels, base),
            limite_jour=parametres.demandes_limite_jour,
            limite_compte=parametres.demandes_limite_compte,
        )
        return await traiteur.traiter()


class _SansForge:
    """Demande reçue par e-mail : aucun ticket à lire ni à commenter."""

    depot = "e-mail"

    async def tickets_ouverts(self) -> list[Ticket]:
        return []

    async def commenter(self, numero: int, texte: str) -> None:
        raise RuntimeError("aucune forge pour une demande reçue par e-mail")

    async def ajouter_etiquette(self, numero: int, nom: str) -> bool:
        raise RuntimeError("aucune forge pour une demande reçue par e-mail")

    async def retirer_etiquette(self, numero: int, nom: str) -> None:
        raise RuntimeError("aucune forge pour une demande reçue par e-mail")

    async def fermer(self, numero: int) -> None:
        raise RuntimeError("aucune forge pour une demande reçue par e-mail")


async def analyser_demande_directe(
    parametres: Parametres, referentiels: Referentiels, base: Base, saisie: str
) -> AnalyseDirecte:
    """Analyse d'un domaine demandée par e-mail (commande « bbcloud demandes analyser »)."""
    async with contexte_reseau(parametres, referentiels) as contexte:
        contexte_scan: ContexteScan = contexte

        async def analyser(hote: str) -> ResultatScan:
            return await scanner_domaine(hote, contexte_scan)

        async def resoudre(hote: str) -> list[str]:
            return await adresses_du_site(hote, contexte_scan.resolveur_dns)

        traiteur = TraiteurDemandes(
            base=base,
            referentiels=referentiels,
            forge=_SansForge(),
            analyser=analyser,
            resoudre=resoudre,
            publier=publier_site,
            url_site=parametres.url_site,
            generer_rapport=_generateur_rapports(parametres, referentiels, base),
            source=SOURCE_EMAIL,
        )
        return await traiteur.analyser_directement(saisie)
