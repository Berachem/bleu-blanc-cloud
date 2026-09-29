"""Détection des services tiers : applique regles_detection.yaml aux données DNS et HTTP."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal
from urllib.parse import urlsplit

from bleublanccloud.analyse.attribution import Attributeur, correspond_motif
from bleublanccloud.modeles import Constat, ExempleRegle, RegleDetection
from bleublanccloud.sondes.dns import DonneesDns
from bleublanccloud.sondes.http import DonneesHttp, Ressource

TypeCorrespondance = Literal[
    "script", "ressource", "chemin", "cookie", "en_tete", "txt", "spf", "mx", "cname", "html"
]

CLES_CONSTAT: Final[dict[TypeCorrespondance, str]] = {
    "script": "script_tiers",
    "ressource": "ressource_tierce",
    "chemin": "ressource_tierce",
    "cookie": "cookie",
    "en_tete": "en_tete",
    "txt": "enregistrement_txt",
    "spf": "spf",
    "mx": "mx_service",
    "cname": "cname_service",
    "html": "code_html",
}
TYPES_DNS: Final = frozenset({"txt", "spf", "mx", "cname"})
CORRESPONDANCES_MAX: Final = 5
EXTRAIT_HTML: Final = 120


@dataclass(frozen=True)
class ElementsObserves:
    """Tout ce qui peut déclencher une règle, indépendamment de la sonde d'origine."""

    txt: Sequence[str] = ()
    spf: str | None = None
    mx: Sequence[str] = ()
    cnames: Sequence[str] = ()
    ressources: Sequence[Ressource] = ()
    cookies: Sequence[str] = ()
    en_tetes: dict[str, str] = field(default_factory=dict)
    html: Sequence[str] = ()

    @classmethod
    def depuis_sondes(cls, dns: DonneesDns | None, http: DonneesHttp | None) -> ElementsObserves:
        cnames: list[str] = []
        if dns is not None:
            for resolution in dns.resolutions.values():
                cnames.extend(resolution.cnames)
        return cls(
            txt=dns.txt if dns else (),
            spf=dns.spf if dns else None,
            mx=[mx.hote for mx in dns.mx] if dns else (),
            cnames=cnames,
            ressources=http.ressources if http else (),
            cookies=http.cookies if http else (),
            en_tetes=http.en_tetes if http else {},
            html=http.html_pages if http else (),
        )

    @classmethod
    def depuis_exemple(cls, exemple: ExempleRegle) -> ElementsObserves:
        """Construit les éléments observés correspondant à l'exemple d'une règle (tests)."""
        valeur = exemple.valeur
        if exemple.type in ("script", "ressource", "iframe", "image"):
            type_ressource: Literal["script", "autre", "iframe", "image"] = (
                "autre" if exemple.type == "ressource" else exemple.type
            )
            domaine = (urlsplit(valeur).hostname or "").lower()
            return cls(
                ressources=[
                    Ressource(type=type_ressource, url=valeur, domaine=domaine, tierce=True)
                ]
            )
        if exemple.type == "cookie":
            return cls(cookies=[valeur])
        if exemple.type == "en_tete":
            return cls(en_tetes={(exemple.nom or "").lower(): valeur})
        if exemple.type == "txt":
            return cls(txt=[valeur])
        if exemple.type == "spf":
            return cls(txt=[valeur], spf=valeur)
        if exemple.type == "mx":
            return cls(mx=[valeur])
        if exemple.type == "cname":
            return cls(cnames=[valeur])
        return cls(html=[valeur])


@dataclass(frozen=True)
class Correspondance:
    type: TypeCorrespondance
    motif: str
    element: str

    def en_preuve(self) -> dict[str, str]:
        return {"type": self.type, "motif": self.motif, "element": self.element}


def _rechercher(motif: str, texte: str) -> re.Match[str] | None:
    return re.search(motif, texte, flags=re.IGNORECASE)


def correspondances_regle(
    regle: RegleDetection, elements: ElementsObserves
) -> list[Correspondance]:
    """Toutes les correspondances d'une règle (vide si la règle ne s'applique pas)."""
    motifs = regle.motifs
    trouvees: list[Correspondance] = []
    for ressource in elements.ressources:
        if ressource.type == "script":
            trouvees += [
                Correspondance("script", m, ressource.url)
                for m in motifs.domaines_scripts
                if correspond_motif(ressource.domaine, m)
            ]
        trouvees += [
            Correspondance("ressource", m, ressource.url)
            for m in motifs.domaines_ressources
            if correspond_motif(ressource.domaine, m)
        ]
        trouvees += [
            Correspondance("chemin", m, ressource.url)
            for m in motifs.chemins
            if _rechercher(m, ressource.url)
        ]
    for cookie in elements.cookies:
        trouvees += [
            Correspondance("cookie", m, cookie) for m in motifs.cookies if _rechercher(m, cookie)
        ]
    for nom, motif in motifs.en_tetes.items():
        valeur = elements.en_tetes.get(nom.lower())
        if valeur is not None and (motif == "" or _rechercher(motif, valeur)):
            trouvees.append(Correspondance("en_tete", motif, f"{nom}: {valeur}"))
    for texte in elements.txt:
        trouvees += [Correspondance("txt", m, texte) for m in motifs.txt if _rechercher(m, texte)]
    if elements.spf:
        spf = elements.spf
        trouvees += [Correspondance("spf", m, spf) for m in motifs.spf if _rechercher(m, spf)]
    for hote in elements.mx:
        trouvees += [Correspondance("mx", m, hote) for m in motifs.mx if _rechercher(m, hote)]
    for cname in elements.cnames:
        trouvees += [
            Correspondance("cname", m, cname) for m in motifs.cname if _rechercher(m, cname)
        ]
    for page in elements.html:
        for motif in motifs.html:
            resultat = _rechercher(motif, page)
            if resultat is not None:
                debut = max(resultat.start() - 20, 0)
                extrait = page[debut : resultat.end() + 40].replace("\n", " ")[:EXTRAIT_HTML]
                trouvees.append(Correspondance("html", motif, extrait))
    return trouvees


@dataclass(frozen=True)
class ResultatDetection:
    constats: list[Constat]
    elements_expliques: frozenset[str]
    """Éléments (URL, cookies…) expliqués par au moins une règle détectée."""


class Detecteur:
    """Applique les règles de détection et repère les ressources tierces restantes."""

    def __init__(self, regles: Iterable[RegleDetection], attributeur: Attributeur) -> None:
        self.regles = list(regles)
        self.attributeur = attributeur

    def _niveau_regle(self, regle: RegleDetection) -> Literal["A", "B", "C", "D", "inconnu"]:
        if regle.niveau is not None:
            return regle.niveau
        fournisseur = self.attributeur.fournisseurs.get(regle.fournisseur_id or "")
        return self.attributeur.niveau(fournisseur)

    def detecter(self, elements: ElementsObserves) -> ResultatDetection:
        """Un constat par service détecté (une règle ne produit qu'un seul constat)."""
        resultats: dict[str, tuple[RegleDetection, list[Correspondance]]] = {}
        for regle in self.regles:
            trouvees = correspondances_regle(regle, elements)
            if trouvees:
                resultats[regle.id] = (regle, trouvees)
        for regle_id, (regle, _) in list(resultats.items()):
            if any(autre in resultats for autre in regle.incompatible_avec):
                del resultats[regle_id]

        constats: list[Constat] = []
        for regle, trouvees in resultats.values():
            premiere = trouvees[0]
            constats.append(
                Constat(
                    sonde="dns" if premiere.type in TYPES_DNS else "http",
                    categorie=regle.categorie,
                    cle=CLES_CONSTAT[premiere.type],
                    valeur=regle.nom,
                    fournisseur_id=regle.fournisseur_id,
                    niveau=self._niveau_regle(regle),
                    preuve={
                        "regle": regle.id,
                        "type_service": regle.type_service,
                        "signal_positif": regle.signal_positif,
                        "correspondances": [c.en_preuve() for c in trouvees[:CORRESPONDANCES_MAX]],
                        "nombre_correspondances": len(trouvees),
                    },
                )
            )
        expliques = frozenset(c.element for _, trouvees in resultats.values() for c in trouvees)
        return ResultatDetection(constats, expliques)

    def ressources_non_couvertes(
        self,
        elements: ElementsObserves,
        elements_expliques: Collection[str],
        fournisseurs_exclus: Collection[str] = (),
    ) -> tuple[list[Constat], list[str]]:
        """Ressources tierces qu'aucune règle n'explique.

        - rattachées à un fournisseur connu (par leur nom d'hôte) : un constat par fournisseur ;
        - sinon : domaine listé comme « domaine tiers inconnu » (informatif).
        Les ressources de la plateforme qui héberge le site lui-même sont ignorées.
        """
        par_fournisseur: dict[str, list[Ressource]] = {}
        inconnus: set[str] = set()
        for ressource in elements.ressources:
            if not ressource.tierce or ressource.url in elements_expliques:
                continue
            correspondance = self.attributeur.par_nom(ressource.domaine)
            if correspondance is None:
                inconnus.add(ressource.domaine)
                continue
            if correspondance.fournisseur.id in fournisseurs_exclus:
                continue
            par_fournisseur.setdefault(correspondance.fournisseur.id, []).append(ressource)

        constats: list[Constat] = []
        for fournisseur_id, ressources in sorted(par_fournisseur.items()):
            fournisseur = self.attributeur.fournisseurs[fournisseur_id]
            domaines = sorted({r.domaine for r in ressources})
            constats.append(
                Constat(
                    sonde="http",
                    categorie="services_tiers",
                    cle="ressource_tierce",
                    valeur=f"Ressources chargées depuis {fournisseur.nom}",
                    fournisseur_id=fournisseur_id,
                    niveau=self.attributeur.niveau(fournisseur),
                    preuve={
                        "regle": f"fournisseur:{fournisseur_id}",
                        "type_service": "ressources_diverses",
                        "signal_positif": False,
                        "domaines": domaines,
                        "correspondances": [
                            {"type": r.type, "motif": "nom_hote", "element": r.url}
                            for r in ressources[:CORRESPONDANCES_MAX]
                        ],
                        "nombre_correspondances": len(ressources),
                    },
                )
            )
        return constats, sorted(inconnus)
