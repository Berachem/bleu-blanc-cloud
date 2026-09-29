"""Modèles de données partagés par le scanner, le stockage, l'IA et l'export du site."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

Niveau = Literal["A", "B", "C", "D", "inconnu"]
"""Niveau de juridiction d'un fournisseur (méthodologie, section 9)."""

Note = Literal["A", "B", "C", "D", "E"]
"""Note globale d'une organisation."""

CategorieScore = Literal[
    "hebergement",
    "messagerie",
    "dns",
    "suites_saas",
    "services_tiers",
    "mesure_audience",
]
"""Catégories notées par la méthodologie."""

Categorie = Literal[
    "hebergement",
    "messagerie",
    "dns",
    "suites_saas",
    "services_tiers",
    "mesure_audience",
    "informatif",
]
"""Catégorie d'un constat : une catégorie notée, ou « informatif » (affiché, non noté)."""

MotifExclusion = Literal["inconnu", "indisponible", "sans_objet"]
"""Raison pour laquelle une catégorie n'est pas évaluée."""

TypeOrganisation = Literal["commune", "departement", "region", "autre"]


class ModeleStrict(BaseModel):
    """Base commune : refuse les champs inconnus pour détecter les erreurs de saisie."""

    # Les champs ayant une valeur par défaut sont toujours présents dans les fichiers exportés :
    # le schéma de sérialisation les déclare donc obligatoires (types TypeScript plus stricts).
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# --------------------------------------------------------------------------- #
# Constats
# --------------------------------------------------------------------------- #


class Constat(ModeleStrict):
    """Élément observé lors d'un scan, rattaché si possible à un fournisseur."""

    sonde: str = Field(description="Sonde à l'origine du constat : dns, ip, http, tls, rdap.")
    categorie: Categorie
    cle: str = Field(description="Nature du constat, ex. « mx », « script_tiers ».")
    valeur: str = Field(description="Valeur observée, ex. un nom d'hôte MX ou un service.")
    fournisseur_id: str | None = Field(
        default=None, description="Identifiant dans fournisseurs.yaml, None si inconnu."
    )
    niveau: Niveau = "inconnu"
    preuve: dict[str, Any] = Field(
        default_factory=dict, description="Élément brut qui justifie le constat."
    )


# --------------------------------------------------------------------------- #
# Référentiels
# --------------------------------------------------------------------------- #


class Fournisseur(ModeleStrict):
    """Fournisseur de services numériques (fournisseurs.yaml)."""

    id: str
    nom: str
    pays_siege: str = Field(min_length=2, max_length=2, description="Code ISO 3166-1 alpha-2.")
    maison_mere: str | None = None
    pays_maison_mere: str | None = Field(default=None, min_length=2, max_length=2)
    soumis_cloud_act: bool
    autre_loi_extraterritoriale: str | None = Field(
        default=None,
        description="Loi extraterritoriale équivalente au Cloud Act (entraîne le niveau D).",
    )
    propose_offre_secnumcloud: bool = False
    asn: list[int] = Field(default_factory=list)
    motifs_domaines: list[str] = Field(
        default_factory=list,
        description="Suffixes de noms d'hôtes (ou « re:<regex> ») rattachés au fournisseur.",
    )
    motifs_cdn: list[str] = Field(
        default_factory=list,
        description="Motifs de noms d'hôtes indiquant un rôle de CDN (hébergeur réel masqué).",
    )
    asn_cdn: list[int] = Field(
        default_factory=list, description="ASN d'un réseau de diffusion de contenu (CDN)."
    )
    services_cdn: list[str] = Field(
        default_factory=list,
        description="Services des plages IP publiées qui correspondent à un CDN (ex. CLOUDFRONT).",
    )
    plages_cdn: bool = Field(
        default=False, description="Toutes les plages IP publiées par ce fournisseur sont un CDN."
    )
    motifs_nom_as: list[str] = Field(
        default_factory=list,
        description=(
            "Regex sur le nom du système autonome (comparé sans accents, en minuscules), "
            "pour les réseaux sans ASN recensé (ex. organismes publics)."
        ),
    )
    exclusions_nom_as: list[str] = Field(
        default_factory=list, description="Regex de noms d'AS écartés malgré un motif positif."
    )
    pays_nom_as: list[str] = Field(
        default_factory=list,
        description="Si renseigné, le pays connu de l'IP doit en faire partie (motifs_nom_as).",
    )
    en_tetes_origine: dict[str, str] = Field(
        default_factory=dict,
        description="En-têtes HTTP (nom → regex, vide = présence) révélant une origine hébergée.",
    )
    categories: list[str] = Field(default_factory=list)
    sources: list[HttpUrl] = Field(min_length=1)
    a_verifier: bool = True
    remarque: str | None = None


class ExempleRegle(ModeleStrict):
    """Exemple d'élément qui doit déclencher une règle (sert de test automatique)."""

    type: Literal[
        "script",
        "ressource",
        "iframe",
        "image",
        "cookie",
        "en_tete",
        "txt",
        "spf",
        "mx",
        "cname",
        "html",
    ]
    valeur: str
    nom: str | None = Field(default=None, description="Nom de l'en-tête pour le type en_tete.")


class MotifsRegle(ModeleStrict):
    """Motifs de détection. Les domaines sont comparés par suffixe, le reste par expression
    régulière (insensible à la casse)."""

    domaines_scripts: list[str] = Field(default_factory=list)
    domaines_ressources: list[str] = Field(default_factory=list)
    chemins: list[str] = Field(
        default_factory=list, description="Regex sur l'URL complète d'un script ou d'une ressource."
    )
    cookies: list[str] = Field(default_factory=list)
    en_tetes: dict[str, str] = Field(default_factory=dict)
    txt: list[str] = Field(default_factory=list)
    spf: list[str] = Field(default_factory=list)
    mx: list[str] = Field(default_factory=list)
    cname: list[str] = Field(default_factory=list)
    html: list[str] = Field(default_factory=list)


class RegleDetection(ModeleStrict):
    """Règle de détection d'un service tiers (regles_detection.yaml)."""

    id: str
    nom: str
    categorie: Categorie
    type_service: str = Field(description="Sous-catégorie : polices, videos, cartes, captcha…")
    fournisseur_id: str | None = None
    niveau: Niveau | None = Field(
        default=None,
        description="Niveau imposé (ex. « A » pour une solution auto-hébergée sans fournisseur).",
    )
    signal_positif: bool = False
    incompatible_avec: list[str] = Field(
        default_factory=list,
        description="Règles qui, si elles sont détectées, annulent celle-ci.",
    )
    motifs: MotifsRegle
    exemples: list[ExempleRegle] = Field(min_length=1)
    description: str | None = None


class Alternative(ModeleStrict):
    """Alternative française ou européenne (alternatives.yaml)."""

    id: str
    nom: str
    pays: str = Field(min_length=2, max_length=2)
    url: HttpUrl
    categorie: CategorieScore
    types_service: list[str] = Field(default_factory=list)
    description_courte: str
    sources: list[HttpUrl] = Field(min_length=1)
    a_verifier: bool = True


class Retrait(ModeleStrict):
    """Domaine exclu du scan sur demande (retraits.yaml)."""

    domaine: str
    date_demande: str
    motif: str | None = None


class Organisation(ModeleStrict):
    """Organisation analysée (commune, département, région…)."""

    slug: str
    nom: str
    type: TypeOrganisation
    code_commune: str | None = None
    departement: str | None = None
    region: str | None = None
    population: int | None = None
    site_web: str | None = None
    source: str


# --------------------------------------------------------------------------- #
# Résultats de scan et score
# --------------------------------------------------------------------------- #


class InformationsComplementaires(ModeleStrict):
    """Informations affichées mais non notées en v1."""

    bureau_enregistrement: str | None = None
    autorite_certification: str | None = None
    fournisseurs_secnumcloud: list[str] = Field(
        default_factory=list,
        description="Fournisseurs détectés qui proposent une offre qualifiée SecNumCloud.",
    )
    domaines_tiers_inconnus: list[str] = Field(default_factory=list)


class ResultatScan(ModeleStrict):
    """Résultat complet d'un scan de domaine."""

    domaine: str
    debut: datetime
    fin: datetime
    statut: Literal["termine", "partiel", "erreur", "exclu"]
    sondes_reussies: list[Literal["dns", "http"]] = Field(
        default_factory=list,
        description="Sondes ayant fourni des données (conditionne les catégories évaluables).",
    )
    constats: list[Constat] = Field(default_factory=list)
    informations: InformationsComplementaires = Field(default_factory=InformationsComplementaires)
    erreurs: list[str] = Field(default_factory=list)


class Justification(ModeleStrict):
    """Rattache une perte de points à un constat (index dans la liste des constats)."""

    constat_index: int
    points_retires: float = Field(description="Points retirés au score de la catégorie (sur 100).")
    raison: str


class ScoreCategorie(ModeleStrict):
    """Score d'une catégorie de la méthodologie."""

    categorie: CategorieScore
    libelle: str
    poids: float = Field(description="Poids nominal de la catégorie (sur 100).")
    poids_effectif: float = Field(description="Poids après redistribution (sur 100).")
    score: float | None = Field(description="Score sur 100, None si non évaluable.")
    evaluable: bool
    exclusion: MotifExclusion | None = Field(
        default=None,
        description=(
            "Raison de l'exclusion d'une catégorie non évaluable : fournisseur inconnu, "
            "données indisponibles ou catégorie sans objet (ex. aucun MX)."
        ),
    )
    points_perdus_global: float = Field(
        default=0.0, description="Points retirés au score global par cette catégorie."
    )
    explication: str
    justifications: list[Justification] = Field(default_factory=list)


class Score(ModeleStrict):
    """Score global et détail par catégorie."""

    score_global: int = Field(ge=0, le=100)
    note: Note
    version_methodo: str
    detail: list[ScoreCategorie]
    categories_non_evaluables: list[CategorieScore] = Field(default_factory=list)
    couverture: float = Field(
        default=100.0,
        ge=0,
        le=100,
        description="Part du poids applicable effectivement évaluée (en %), depuis la v1.2.",
    )
    provisoire: bool = Field(
        default=False,
        description="Note provisoire : plus de 30 % du poids applicable est inconnu (v1.2).",
    )


# --------------------------------------------------------------------------- #
# Rapports IA (section 10)
# --------------------------------------------------------------------------- #


class RisqueIA(ModeleStrict):
    titre: str
    explication: str
    gravite: Literal["faible", "moyenne", "elevee"]


class EtapeMigration(ModeleStrict):
    ordre: int
    action: str
    alternative_id: str | None = Field(
        default=None, description="Doit exister dans alternatives.yaml."
    )
    effort: Literal["faible", "moyen", "eleve"]


class RapportIA(ModeleStrict):
    resume_decideur: str = Field(description="5 phrases maximum, sans jargon.")
    points_forts: list[str]
    risques: list[RisqueIA]
    plan_migration: list[EtapeMigration]


# --------------------------------------------------------------------------- #
# Contrat de données entre le scanner et le site (section 11)
# --------------------------------------------------------------------------- #


class MetaExport(ModeleStrict):
    """meta.json"""

    date_campagne: datetime
    date_export: datetime
    version_methodo: str
    nombre_organisations: int
    donnees_demonstration: bool = False


class EntreeIndex(ModeleStrict):
    """Élément de index.json (liste légère)."""

    slug: str
    nom: str
    type: TypeOrganisation
    departement: str | None
    departement_nom: str | None = None
    region: str | None = None
    population: int | None = None
    domaine: str
    score: int
    note: Note
    note_provisoire: bool = False
    date_scan: datetime


class FournisseurExport(ModeleStrict):
    """Résumé d'un fournisseur cité dans une page organisation."""

    id: str
    nom: str
    pays_siege: str
    maison_mere: str | None
    pays_maison_mere: str | None
    soumis_cloud_act: bool
    autre_loi_extraterritoriale: str | None = None
    propose_offre_secnumcloud: bool
    niveau: Niveau
    a_verifier: bool


class AlternativeExport(ModeleStrict):
    id: str
    nom: str
    pays: str
    url: str
    categorie: CategorieScore
    types_service: list[str]
    description_courte: str
    a_verifier: bool


class RapportIAExport(ModeleStrict):
    contenu: RapportIA
    modele: str
    version_invite: str
    genere_le: datetime


class OrganisationExport(ModeleStrict):
    """organisations/{slug}.json"""

    slug: str
    nom: str
    type: TypeOrganisation
    departement: str | None
    departement_nom: str | None = None
    region: str | None = None
    region_nom: str | None = None
    population: int | None = None
    site_web: str | None = None
    domaine: str
    date_scan: datetime
    statut_scan: str
    score: Score
    constats: list[Constat]
    informations: InformationsComplementaires
    fournisseurs: dict[str, FournisseurExport]
    rapport_ia: RapportIAExport | None = None
    alternatives: list[AlternativeExport] = Field(default_factory=list)


class DepartementExport(ModeleStrict):
    """Élément de departements.json (agrégats)."""

    code: str
    nom: str
    region: str | None = None
    nombre_organisations: int
    score_moyen: float | None
    note_moyenne: Note | None
    repartition_notes: dict[str, int]
