"""Attribution : rattache une preuve (nom d'hôte, IP, ASN, en-tête) à un fournisseur et à un
niveau de juridiction (méthodologie, section 9)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from bleublanccloud.modeles import Constat, Fournisseur, Niveau
from bleublanccloud.sondes.dns import ChaineResolution, DonneesDns
from bleublanccloud.sondes.ip import InfoIp

PAYS_UE: Final = frozenset(
    {
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU",
        "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
    }
)  # fmt: skip
"""Les 27 États membres de l'Union européenne (codes ISO 3166-1 alpha-2)."""

ORDRE_NIVEAUX: Final[dict[Niveau, int]] = {"A": 0, "B": 1, "C": 2, "D": 3}

Role = Literal["cdn", "hebergement"]


def niveau_juridiction(fournisseur: Fournisseur) -> Niveau:
    """Niveau A, B ou D d'un fournisseur (le niveau C dépend du contexte : CDN devant une
    origine inconnue, voir `constat_hebergement`)."""
    if fournisseur.soumis_cloud_act or fournisseur.autre_loi_extraterritoriale:
        return "D"
    pays_maison_mere = fournisseur.pays_maison_mere or fournisseur.pays_siege
    if fournisseur.pays_siege in PAYS_UE and pays_maison_mere in PAYS_UE:
        return "A"
    return "B"


def pire_niveau(niveaux: Iterable[Niveau]) -> Niveau:
    """Retourne le moins bon niveau connu, ou « inconnu » si aucun n'est connu."""
    connus = [n for n in niveaux if n != "inconnu"]
    if not connus:
        return "inconnu"
    return max(connus, key=lambda n: ORDRE_NIVEAUX[n])


def correspond_motif(nom: str, motif: str) -> bool:
    """Un motif est un suffixe de nom d'hôte, ou une expression régulière préfixée par « re: »."""
    nom = nom.lower().rstrip(".")
    if motif.startswith("re:"):
        return re.search(motif[3:], nom, flags=re.IGNORECASE) is not None
    motif = motif.lower().lstrip(".")
    return nom == motif or nom.endswith("." + motif)


@dataclass(frozen=True)
class Correspondance:
    """Résultat d'une attribution."""

    fournisseur: Fournisseur
    role: Role
    methode: Literal["nom_hote", "plage_publiee", "asn", "en_tete"]
    element: str
    motif: str | None = None

    def en_preuve(self) -> dict[str, str | None]:
        return {
            "methode": self.methode,
            "element": self.element,
            "motif": self.motif,
            "role": self.role,
        }


class Attributeur:
    """Index des fournisseurs par motif de nom d'hôte, par ASN et par en-tête HTTP."""

    def __init__(self, fournisseurs: Mapping[str, Fournisseur]) -> None:
        self.fournisseurs = dict(fournisseurs)
        motifs: list[tuple[str, Fournisseur, Role]] = []
        self._par_asn: dict[int, tuple[Fournisseur, Role]] = {}
        for fournisseur in fournisseurs.values():
            motifs.extend((m, fournisseur, "cdn") for m in fournisseur.motifs_cdn)
            motifs.extend((m, fournisseur, "hebergement") for m in fournisseur.motifs_domaines)
            for asn in fournisseur.asn:
                self._par_asn[asn] = (fournisseur, "hebergement")
            for asn in fournisseur.asn_cdn:
                self._par_asn[asn] = (fournisseur, "cdn")
        # Les suffixes les plus longs (les plus spécifiques) sont testés en premier,
        # les expressions régulières en dernier.
        motifs.sort(key=lambda m: (m[0].startswith("re:"), -len(m[0])))
        self._motifs = motifs

    def niveau(self, fournisseur: Fournisseur | None) -> Niveau:
        return "inconnu" if fournisseur is None else niveau_juridiction(fournisseur)

    def par_nom(self, nom: str) -> Correspondance | None:
        """Attribue un nom d'hôte (MX, NS, CNAME, domaine d'un script…)."""
        for motif, fournisseur, role in self._motifs:
            if correspond_motif(nom, motif):
                return Correspondance(fournisseur, role, "nom_hote", nom, motif)
        return None

    def par_chaine(self, noms: Sequence[str]) -> Correspondance | None:
        """Première correspondance dans une chaîne CNAME (du plus proche du nom demandé au plus
        proche de l'adresse IP)."""
        for nom in noms:
            correspondance = self.par_nom(nom)
            if correspondance is not None:
                return correspondance
        return None

    def par_ip(self, info: InfoIp | None) -> Correspondance | None:
        """Attribue une adresse IP : plage publiée d'un cloud, sinon ASN."""
        if info is None:
            return None
        if info.plage_cloud and info.plage_cloud in self.fournisseurs:
            fournisseur = self.fournisseurs[info.plage_cloud]
            est_cdn = fournisseur.plages_cdn or (
                info.service_cloud is not None and info.service_cloud in fournisseur.services_cdn
            )
            return Correspondance(
                fournisseur,
                "cdn" if est_cdn else "hebergement",
                "plage_publiee",
                info.ip,
                info.prefixe,
            )
        if info.asn is not None and info.asn in self._par_asn:
            fournisseur, role = self._par_asn[info.asn]
            return Correspondance(fournisseur, role, "asn", info.ip, f"AS{info.asn}")
        return None

    def par_en_tetes(self, en_tetes: Mapping[str, str]) -> list[Correspondance]:
        """En-têtes HTTP révélant l'hébergeur d'origine (derrière un éventuel CDN)."""
        en_tetes_min = {cle.lower(): valeur for cle, valeur in en_tetes.items()}
        trouves: list[Correspondance] = []
        for fournisseur in self.fournisseurs.values():
            for nom, motif in fournisseur.en_tetes_origine.items():
                valeur = en_tetes_min.get(nom.lower())
                if valeur is None:
                    continue
                if motif == "" or re.search(motif, valeur, flags=re.IGNORECASE):
                    trouves.append(
                        Correspondance(
                            fournisseur, "hebergement", "en_tete", f"{nom}: {valeur}", motif
                        )
                    )
                    break
        return trouves


def _decrire_ip(info: InfoIp | None, ip: str) -> str:
    if info is None or info.asn is None:
        return ip
    nom_as = f" {info.nom_as}" if info.nom_as else ""
    return f"{ip} (AS{info.asn}{nom_as})"


def _preuve_ip(info: InfoIp | None) -> dict[str, object]:
    if info is None:
        return {}
    return info.model_dump(exclude_none=True)


def constat_hebergement(
    resolution: ChaineResolution,
    info_ip: InfoIp | None,
    en_tetes: Mapping[str, str],
    attributeur: Attributeur,
) -> Constat | None:
    """Constat d'hébergement du site, à partir du nom d'hôte final et de son IP principale.

    Règle du niveau C : un CDN extra-européen placé devant une origine inconnue masque
    l'hébergeur réel. Si l'origine est identifiée, le niveau retenu est le moins bon entre
    celui de l'origine et C (un CDN extra-européen plafonne le niveau à C).
    """
    ip = resolution.ip_principale
    if ip is None:
        return None
    correspondance = attributeur.par_chaine(resolution.cnames) or attributeur.par_ip(info_ip)
    preuve: dict[str, object] = {
        "nom_hote": resolution.nom,
        "cnames": resolution.cnames,
        "ip": ip,
        **_preuve_ip(info_ip),
    }
    valeur = _decrire_ip(info_ip, ip)

    if correspondance is None:
        preuve["attribution"] = "fournisseur non référencé"
        return Constat(
            sonde="ip",
            categorie="hebergement",
            cle="hebergeur",
            valeur=valeur,
            fournisseur_id=None,
            niveau="inconnu",
            preuve=preuve,
        )

    fournisseur = correspondance.fournisseur
    niveau = attributeur.niveau(fournisseur)
    preuve["attribution"] = correspondance.en_preuve()
    cle = "hebergeur"

    if correspondance.role == "cdn" and niveau in ("B", "D"):
        cle = "cdn"
        origines = attributeur.par_en_tetes(en_tetes)
        if origines:
            origine = origines[0]
            niveau_origine = attributeur.niveau(origine.fournisseur)
            preuve["origine"] = {"fournisseur_id": origine.fournisseur.id, **origine.en_preuve()}
            niveau = pire_niveau([niveau_origine, "C"])
            if niveau == niveau_origine and niveau != "C":
                fournisseur = origine.fournisseur
        else:
            preuve["origine"] = "masquée par le CDN"
            niveau = "C"

    return Constat(
        sonde="dns" if correspondance.methode == "nom_hote" else "ip",
        categorie="hebergement",
        cle=cle,
        valeur=valeur,
        fournisseur_id=fournisseur.id,
        niveau=niveau,
        preuve=preuve,
    )


def constats_serveurs(
    cle: Literal["mx", "ns"],
    hotes: Sequence[tuple[str, int | None]],
    infos_ip: Mapping[str, InfoIp | None],
    attributeur: Attributeur,
) -> list[Constat]:
    """Constats de messagerie (MX) ou d'hébergement DNS (NS), un par serveur."""
    categorie: Literal["messagerie", "dns"] = "messagerie" if cle == "mx" else "dns"
    constats: list[Constat] = []
    for hote, priorite in hotes:
        info = infos_ip.get(hote)
        correspondance = attributeur.par_nom(hote) or attributeur.par_ip(info)
        preuve: dict[str, object] = {"hote": hote, **_preuve_ip(info)}
        if priorite is not None:
            preuve["priorite"] = priorite
        if correspondance is not None:
            preuve["attribution"] = correspondance.en_preuve()
        else:
            preuve["attribution"] = "fournisseur non référencé"
        fournisseur = correspondance.fournisseur if correspondance else None
        constats.append(
            Constat(
                sonde="dns"
                if correspondance is None or correspondance.methode == "nom_hote"
                else "ip",
                categorie=categorie,
                cle=cle,
                valeur=hote,
                fournisseur_id=fournisseur.id if fournisseur else None,
                niveau=attributeur.niveau(fournisseur),
                preuve=preuve,
            )
        )
    return constats


def constats_dns_informatifs(donnees: DonneesDns) -> list[Constat]:
    """Constats affichés mais non notés : absence de MX, SPF, DMARC."""
    constats: list[Constat] = []
    if donnees.mx_nul:
        constats.append(
            Constat(
                sonde="dns",
                categorie="informatif",
                cle="mx_nul",
                valeur="Le domaine déclare ne recevoir aucun courriel (MX nul, RFC 7505)",
                preuve={"mx": "0 ."},
            )
        )
    elif not donnees.mx:
        constats.append(
            Constat(
                sonde="dns",
                categorie="informatif",
                cle="mx_absent",
                valeur="Aucun serveur de messagerie (MX) déclaré",
                preuve={"mx": []},
            )
        )
    spf = donnees.spf
    constats.append(
        Constat(
            sonde="dns",
            categorie="informatif",
            cle="spf",
            valeur=spf if spf else "Aucun enregistrement SPF",
            preuve={"txt": spf} if spf else {},
        )
    )
    constats.append(
        Constat(
            sonde="dns",
            categorie="informatif",
            cle="dmarc",
            valeur=donnees.dmarc if donnees.dmarc else "Aucune politique DMARC",
            preuve={"_dmarc": donnees.dmarc} if donnees.dmarc else {},
        )
    )
    return constats
