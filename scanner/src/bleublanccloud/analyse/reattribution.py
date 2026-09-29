"""Réattribution des constats enregistrés avec les référentiels courants, sans rescanner.

Après une mise à jour de fournisseurs.yaml ou de transitaires.yaml, les preuves brutes
conservées avec chaque constat (nom d'hôte, chaîne CNAME, IP, ASN, nom d'AS, en-tête
d'origine) suffisent à refaire l'attribution :

- hébergement du site, MX et NS : attribution complète refaite à partir de la preuve ;
- services détectés par une règle : niveau et fournisseur relus dans les référentiels ;
- constats informatifs : inchangés.

Limites (un nouveau scan reste nécessaire) : une nouvelle règle de détection ne peut pas
s'appliquer à des pages qui ne sont pas conservées, et un en-tête HTTP non retenu lors du
scan ne peut pas révéler après coup l'origine masquée par un CDN.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from typing import Any, Final

from pydantic import ValidationError

from bleublanccloud.analyse.attribution import (
    Attributeur,
    constat_hebergement,
    constats_serveurs,
)
from bleublanccloud.modeles import Constat, Niveau, RegleDetection
from bleublanccloud.sondes.dns import ChaineResolution
from bleublanccloud.sondes.ip import InfoIp

CLES_ATTRIBUTION: Final = ("attribution", "origine", "transitaire")
"""Parties de la preuve recalculées ; tout le reste (données brutes) est conservé."""

PREFIXE_REGLE_FOURNISSEUR: Final = "fournisseur:"


def info_ip_depuis_preuve(preuve: Mapping[str, Any]) -> InfoIp | None:
    """Reconstitue les informations d'IP (ASN, nom d'AS, plage cloud…) d'une preuve."""
    if not isinstance(preuve.get("ip"), str):
        return None
    champs = {nom: preuve[nom] for nom in InfoIp.model_fields if nom in preuve}
    try:
        return InfoIp.model_validate(champs)
    except ValidationError:
        return None


def _fusionner_preuves(ancienne: Mapping[str, Any], nouvelle: Mapping[str, Any]) -> dict[str, Any]:
    conservee = {cle: valeur for cle, valeur in ancienne.items() if cle not in CLES_ATTRIBUTION}
    return {**conservee, **nouvelle}


def _en_tetes_origine(preuve: Mapping[str, Any]) -> dict[str, str]:
    """En-tête qui avait révélé l'origine derrière un CDN (« nom: valeur »), s'il y en a un."""
    origine = preuve.get("origine")
    if not isinstance(origine, Mapping):
        return {}
    element = origine.get("element")
    if not isinstance(element, str) or ":" not in element:
        return {}
    nom, valeur = element.split(":", 1)
    return {nom.strip(): valeur.strip()}


def _reattribuer_hebergement(constat: Constat, attributeur: Attributeur) -> Constat:
    preuve = constat.preuve
    ip, nom_hote = preuve.get("ip"), preuve.get("nom_hote")
    if not isinstance(ip, str) or not isinstance(nom_hote, str):
        return constat
    cnames = [str(c) for c in preuve.get("cnames") or []]
    try:
        ipv6 = ipaddress.ip_address(ip).version == 6
    except ValueError:
        return constat
    resolution = ChaineResolution(
        nom=nom_hote, cnames=cnames, ipv4=[] if ipv6 else [ip], ipv6=[ip] if ipv6 else []
    )
    nouveau = constat_hebergement(
        resolution, info_ip_depuis_preuve(preuve), _en_tetes_origine(preuve), attributeur
    )
    if nouveau is None:
        return constat
    return nouveau.model_copy(update={"preuve": _fusionner_preuves(preuve, nouveau.preuve)})


def _reattribuer_serveur(constat: Constat, attributeur: Attributeur) -> Constat:
    hote = constat.preuve.get("hote")
    hote = hote if isinstance(hote, str) and hote else constat.valeur
    [nouveau] = constats_serveurs(
        "mx" if constat.cle == "mx" else "ns",
        [(hote, None)],
        {hote: info_ip_depuis_preuve(constat.preuve)},
        attributeur,
    )
    return nouveau.model_copy(
        update={
            "valeur": constat.valeur,
            "preuve": _fusionner_preuves(constat.preuve, nouveau.preuve),
        }
    )


def _rafraichir_niveau(
    constat: Constat, attributeur: Attributeur, regles: Mapping[str, RegleDetection]
) -> Constat:
    """Services détectés : fournisseur et niveau relus dans les référentiels courants."""
    regle_id = constat.preuve.get("regle")
    fournisseur_id = constat.fournisseur_id
    niveau: Niveau | None = None
    if isinstance(regle_id, str) and regle_id.startswith(PREFIXE_REGLE_FOURNISSEUR):
        fournisseur_id = regle_id.removeprefix(PREFIXE_REGLE_FOURNISSEUR)
    elif isinstance(regle_id, str) and regle_id in regles:
        regle = regles[regle_id]
        fournisseur_id = regle.fournisseur_id
        niveau = regle.niveau
    if niveau is None:
        if fournisseur_id is None or fournisseur_id not in attributeur.fournisseurs:
            return constat  # fournisseur retiré du référentiel : constat laissé tel quel
        niveau = attributeur.niveau(attributeur.fournisseurs[fournisseur_id])
    return constat.model_copy(update={"fournisseur_id": fournisseur_id, "niveau": niveau})


def reattribuer_constat(
    constat: Constat, attributeur: Attributeur, regles: Mapping[str, RegleDetection]
) -> Constat:
    """Constat recalculé avec les référentiels courants (identique si rien n'a changé)."""
    if constat.categorie == "informatif":
        return constat
    if "regle" not in constat.preuve:
        if constat.categorie == "hebergement" and constat.cle in ("hebergeur", "cdn"):
            return _reattribuer_hebergement(constat, attributeur)
        if constat.categorie in ("messagerie", "dns") and constat.cle in ("mx", "ns"):
            return _reattribuer_serveur(constat, attributeur)
    return _rafraichir_niveau(constat, attributeur, regles)


def reattribuer_constats(
    constats: Sequence[Constat], attributeur: Attributeur, regles: Sequence[RegleDetection]
) -> list[Constat]:
    """Réattribue une liste de constats en conservant leur ordre (les justifications du score
    désignent les constats par leur rang)."""
    index_regles = {regle.id: regle for regle in regles}
    return [reattribuer_constat(c, attributeur, index_regles) for c in constats]
