"""Chiffres clés de l'observatoire (commande « bbcloud stats »).

Calculés sur le dernier scan noté de chaque organisation de l'observatoire (les analyses sur
demande et les scans unitaires sans organisation sont écartés, comme sur le site). Chaque
chiffre est accompagné du nombre de notes provisoires qu'il contient (plus de 30 % du poids
applicable non évalué, méthodologie v1.2), pour en mesurer la solidité.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

from bleublanccloud.analyse.attribution import niveau_juridiction
from bleublanccloud.analyse.score import POINTS_NIVEAUX, note_depuis_score
from bleublanccloud.export.site_statique import score_a_jour
from bleublanccloud.modeles import CategorieScore, Constat, Note, Organisation, Score
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base

NOTES: Final[tuple[Note, ...]] = ("A", "B", "C", "D", "E")
CATEGORIES_NIVEAUX: Final[tuple[CategorieScore, ...]] = ("messagerie", "hebergement", "dns")
"""Catégories notées par le niveau de juridiction d'un fournisseur (méthodologie, section 9)."""

EtatCategorie = Literal["A", "B", "C", "D", "inconnu", "indisponible", "sans_objet"]
ETATS_CATEGORIE: Final[tuple[EtatCategorie, ...]] = (
    "A",
    "B",
    "C",
    "D",
    "inconnu",
    "indisponible",
    "sans_objet",
)
_NIVEAU_PAR_POINTS: Final[dict[float, EtatCategorie]] = {
    points: niveau for niveau, points in POINTS_NIVEAUX.items()
}

TRANCHES_POPULATION: Final[tuple[tuple[int, int | None], ...]] = (
    (0, 10_000),
    (10_000, 20_000),
    (20_000, 50_000),
    (50_000, 100_000),
    (100_000, 200_000),
    (200_000, None),
)
SEUIL_GRANDES_COLLECTIVITES: Final = 100_000
FOURNISSEURS_AFFICHES: Final = 10


@dataclass(frozen=True)
class EntreeStatistique:
    """Une organisation et son dernier score."""

    organisation: Organisation
    score: Score
    constats: Sequence[Constat]
    date_scan: datetime


@dataclass
class Compte:
    """Effectif d'un chiffre et nombre de notes provisoires qu'il contient."""

    nombre: int = 0
    provisoires: int = 0

    def ajouter(self, provisoire: bool) -> None:
        self.nombre += 1
        self.provisoires += int(provisoire)

    @property
    def part_provisoire(self) -> float:
        """Part (en %) de notes provisoires dans cet effectif."""
        return round(100 * self.provisoires / self.nombre, 1) if self.nombre else 0.0


@dataclass
class Moyenne:
    """Score moyen d'un groupe d'organisations."""

    compte: Compte = field(default_factory=Compte)
    somme: int = 0

    def ajouter(self, score: Score) -> None:
        self.compte.ajouter(score.provisoire)
        self.somme += score.score_global

    @property
    def score_moyen(self) -> float | None:
        return round(self.somme / self.compte.nombre, 1) if self.compte.nombre else None

    @property
    def note_moyenne(self) -> Note | None:
        moyenne = self.score_moyen
        return note_depuis_score(moyenne) if moyenne is not None else None


@dataclass(frozen=True)
class FournisseurPresent:
    fournisseur_id: str
    nom: str
    niveau: str
    compte: Compte


@dataclass(frozen=True)
class GroupeMoyen:
    """Moyenne d'un groupe nommé (région, tranche de population, département)."""

    code: str
    libelle: str
    moyenne: Moyenne


@dataclass(frozen=True)
class GrandeCollectivite:
    nom: str
    slug: str
    type: str
    population: int
    score: int
    provisoire: bool


@dataclass
class Statistiques:
    """Chiffres clés de l'observatoire."""

    ensemble: Moyenne = field(default_factory=Moyenne)
    premier_scan: datetime | None = None
    dernier_scan: datetime | None = None
    notes: dict[Note, Compte] = field(default_factory=lambda: {n: Compte() for n in NOTES})
    niveaux: dict[CategorieScore, dict[EtatCategorie, Compte]] = field(
        default_factory=lambda: {
            c: {e: Compte() for e in ETATS_CATEGORIE} for c in CATEGORIES_NIVEAUX
        }
    )
    fournisseurs: dict[str, list[FournisseurPresent]] = field(default_factory=dict)
    regions: list[GroupeMoyen] = field(default_factory=list)
    tranches_population: list[GroupeMoyen] = field(default_factory=list)
    departements: list[GroupeMoyen] = field(default_factory=list)
    grandes_collectivites: Compte = field(default_factory=Compte)
    grandes_collectivites_a: list[GrandeCollectivite] = field(default_factory=list)

    def en_dict(self) -> dict[str, Any]:
        """Représentation JSON (parts provisoires et moyennes calculées incluses)."""

        def compte(c: Compte) -> dict[str, Any]:
            return {**asdict(c), "part_provisoire": c.part_provisoire}

        def moyenne(m: Moyenne) -> dict[str, Any]:
            return {
                **compte(m.compte),
                "score_moyen": m.score_moyen,
                "note_moyenne": m.note_moyenne,
            }

        def groupes(liste: list[GroupeMoyen]) -> list[dict[str, Any]]:
            return [{"code": g.code, "libelle": g.libelle, **moyenne(g.moyenne)} for g in liste]

        total = self.ensemble.compte.nombre or 1
        return {
            "ensemble": moyenne(self.ensemble),
            "premier_scan": self.premier_scan.isoformat() if self.premier_scan else None,
            "dernier_scan": self.dernier_scan.isoformat() if self.dernier_scan else None,
            "repartition_notes": {
                note: {**compte(c), "part": round(100 * c.nombre / total, 1)}
                for note, c in self.notes.items()
            },
            "niveaux_par_categorie": {
                categorie: {
                    etat: {**compte(c), "part": round(100 * c.nombre / total, 1)}
                    for etat, c in etats.items()
                }
                for categorie, etats in self.niveaux.items()
            },
            "fournisseurs": {
                categorie: [
                    {
                        "id": f.fournisseur_id,
                        "nom": f.nom,
                        "niveau": f.niveau,
                        **compte(f.compte),
                        "part": round(100 * f.compte.nombre / total, 1),
                    }
                    for f in liste
                ]
                for categorie, liste in self.fournisseurs.items()
            },
            "moyennes_par_region": groupes(self.regions),
            "moyennes_par_tranche_population": groupes(self.tranches_population),
            "moyennes_par_departement": groupes(self.departements),
            "grandes_collectivites": {
                "seuil_population": SEUIL_GRANDES_COLLECTIVITES,
                **compte(self.grandes_collectivites),
                "notees_a": [asdict(g) for g in self.grandes_collectivites_a],
            },
        }


def etat_categorie(score: Score, categorie: CategorieScore) -> EtatCategorie:
    """Niveau retenu pour une catégorie notée par niveau, ou motif de son exclusion."""
    for detail in score.detail:
        if detail.categorie != categorie:
            continue
        if detail.evaluable and detail.score is not None:
            return _NIVEAU_PAR_POINTS.get(detail.score, "inconnu")
        return detail.exclusion or "inconnu"
    return "sans_objet"


def libelle_tranche(minimum: int, maximum: int | None) -> str:
    def milliers(valeur: int) -> str:
        return f"{valeur:,}".replace(",", " ")

    if minimum == 0 and maximum is not None:
        return f"Moins de {milliers(maximum)} hab."
    if maximum is None:
        return f"{milliers(minimum)} hab. et plus"
    return f"{milliers(minimum)} à {milliers(maximum)} hab."


def _tranche(population: int) -> tuple[int, int | None]:
    for minimum, maximum in TRANCHES_POPULATION:
        if population >= minimum and (maximum is None or population < maximum):
            return minimum, maximum
    raise AssertionError("inaccessible")  # pragma: no cover


def calculer_statistiques(
    entrees: Iterable[EntreeStatistique],
    referentiels: Referentiels,
    noms_regions: Mapping[str, str] | None = None,
    noms_departements: Mapping[str, str] | None = None,
    fournisseurs_affiches: int = FOURNISSEURS_AFFICHES,
) -> Statistiques:
    """Agrège les chiffres clés à partir du dernier score de chaque organisation."""
    noms_regions = noms_regions or {}
    noms_departements = noms_departements or {}
    stats = Statistiques()
    regions: dict[str, Moyenne] = {}
    departements: dict[str, Moyenne] = {}
    tranches: dict[tuple[int, int | None], Moyenne] = {}
    presences: dict[str, dict[str, Compte]] = {c: {} for c in (*CATEGORIES_NIVEAUX, "toutes")}

    for entree in entrees:
        organisation, score = entree.organisation, entree.score
        provisoire = score.provisoire
        stats.ensemble.ajouter(score)
        stats.premier_scan = min(filter(None, (stats.premier_scan, entree.date_scan)))
        stats.dernier_scan = max(filter(None, (stats.dernier_scan, entree.date_scan)))
        stats.notes[score.note].ajouter(provisoire)
        for categorie in CATEGORIES_NIVEAUX:
            stats.niveaux[categorie][etat_categorie(score, categorie)].ajouter(provisoire)

        # Fournisseurs : une organisation compte une fois par fournisseur et par catégorie
        vus: dict[str, set[str]] = {c: set() for c in presences}
        for constat in entree.constats:
            if constat.fournisseur_id is None or constat.categorie == "informatif":
                continue
            vus["toutes"].add(constat.fournisseur_id)
            if constat.categorie in vus:
                vus[constat.categorie].add(constat.fournisseur_id)
        for cle, identifiants in vus.items():
            for identifiant in identifiants:
                presences[cle].setdefault(identifiant, Compte()).ajouter(provisoire)

        if organisation.region:
            regions.setdefault(organisation.region, Moyenne()).ajouter(score)
        if organisation.departement:
            departements.setdefault(organisation.departement, Moyenne()).ajouter(score)
        if organisation.type == "commune" and organisation.population is not None:
            tranches.setdefault(_tranche(organisation.population), Moyenne()).ajouter(score)
        if (organisation.population or 0) >= SEUIL_GRANDES_COLLECTIVITES:
            stats.grandes_collectivites.ajouter(provisoire)
            if score.note == "A":
                stats.grandes_collectivites_a.append(
                    GrandeCollectivite(
                        nom=organisation.nom,
                        slug=organisation.slug,
                        type=organisation.type,
                        population=organisation.population or 0,
                        score=score.score_global,
                        provisoire=provisoire,
                    )
                )

    for cle, comptes in presences.items():
        classement = sorted(comptes.items(), key=lambda e: (-e[1].nombre, e[0]))
        stats.fournisseurs[cle] = []
        for identifiant, compte in classement[:fournisseurs_affiches]:
            fournisseur = referentiels.fournisseurs.get(identifiant)
            stats.fournisseurs[cle].append(
                FournisseurPresent(
                    fournisseur_id=identifiant,
                    nom=fournisseur.nom if fournisseur else identifiant,
                    niveau=niveau_juridiction(fournisseur) if fournisseur else "inconnu",
                    compte=compte,
                )
            )
    stats.regions = sorted(
        (GroupeMoyen(code, noms_regions.get(code, code), m) for code, m in regions.items()),
        key=lambda g: (-(g.moyenne.score_moyen or 0), g.libelle),
    )
    stats.departements = sorted(
        (
            GroupeMoyen(code, noms_departements.get(code, code), m)
            for code, m in departements.items()
        ),
        key=lambda g: g.code,
    )
    stats.tranches_population = [
        GroupeMoyen(f"{minimum}-{maximum or ''}", libelle_tranche(minimum, maximum), m)
        for (minimum, maximum), m in sorted(tranches.items(), key=lambda e: e[0][0])
    ]
    stats.grandes_collectivites_a.sort(key=lambda g: (-g.population, g.nom))
    return stats


def entrees_observatoire(base: Base) -> list[EntreeStatistique]:
    """Dernier scan noté de chaque organisation de l'observatoire (hors analyses sur demande),
    avec le score recalculé si la méthodologie a changé depuis (comme l'export du site)."""
    entrees: list[EntreeStatistique] = []
    for scan in base.scans_notes(observatoire=True):
        if scan.organisation_id is None or scan.score is None:
            continue
        enregistree = base.organisation_par_id(scan.organisation_id)
        if enregistree is None:
            continue
        entrees.append(
            EntreeStatistique(
                organisation=enregistree.organisation,
                score=score_a_jour(scan),
                constats=scan.resultat.constats,
                date_scan=scan.resultat.debut,
            )
        )
    return entrees


def statistiques_observatoire(base: Base, referentiels: Referentiels) -> Statistiques:
    """Chiffres clés de l'observatoire à partir de la base."""
    noms_regions = {code: nom for code, (nom, _) in base.territoires("region").items()}
    noms_departements = {code: nom for code, (nom, _) in base.territoires("departement").items()}
    return calculer_statistiques(
        entrees_observatoire(base), referentiels, noms_regions, noms_departements
    )
