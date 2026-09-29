/* Fichier généré par scripts/generer-types.mjs à partir de donnees.schema.json — ne pas modifier. */

/**
 * Contrat de données entre le scanner Bleu Blanc Cloud et le site.
 */
export interface DonneesSite {
  meta: MetaExport;
  index: EntreeIndex[];
  organisation: OrganisationExport;
  departements: DepartementExport[];
  alternatives: AlternativeExport[];
}
/**
 * meta.json
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "MetaExport".
 */
export interface MetaExport {
  date_campagne: string;
  date_export: string;
  version_methodo: string;
  nombre_organisations: number;
  donnees_demonstration: boolean;
}
/**
 * Élément de index.json (liste légère).
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "EntreeIndex".
 */
export interface EntreeIndex {
  slug: string;
  nom: string;
  type: "commune" | "departement" | "region" | "autre";
  departement: string | null;
  departement_nom: string | null;
  region: string | null;
  population: number | null;
  domaine: string;
  score: number;
  note: "A" | "B" | "C" | "D" | "E";
  date_scan: string;
}
/**
 * organisations/{slug}.json
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "OrganisationExport".
 */
export interface OrganisationExport {
  slug: string;
  nom: string;
  type: "commune" | "departement" | "region" | "autre";
  departement: string | null;
  departement_nom: string | null;
  region: string | null;
  region_nom: string | null;
  population: number | null;
  site_web: string | null;
  domaine: string;
  date_scan: string;
  statut_scan: string;
  score: Score;
  constats: Constat[];
  informations: InformationsComplementaires;
  fournisseurs: {
    [k: string]: FournisseurExport;
  };
  rapport_ia: RapportIAExport | null;
  alternatives: AlternativeExport[];
}
/**
 * Score global et détail par catégorie.
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "Score".
 */
export interface Score {
  score_global: number;
  note: "A" | "B" | "C" | "D" | "E";
  version_methodo: string;
  detail: ScoreCategorie[];
  categories_non_evaluables: (
    "hebergement" | "messagerie" | "dns" | "suites_saas" | "services_tiers" | "mesure_audience"
  )[];
}
/**
 * Score d'une catégorie de la méthodologie.
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "ScoreCategorie".
 */
export interface ScoreCategorie {
  categorie: "hebergement" | "messagerie" | "dns" | "suites_saas" | "services_tiers" | "mesure_audience";
  libelle: string;
  /**
   * Poids nominal de la catégorie (sur 100).
   */
  poids: number;
  /**
   * Poids après redistribution (sur 100).
   */
  poids_effectif: number;
  /**
   * Score sur 100, None si non évaluable.
   */
  score: number | null;
  evaluable: boolean;
  /**
   * Points retirés au score global par cette catégorie.
   */
  points_perdus_global: number;
  explication: string;
  justifications: Justification[];
}
/**
 * Rattache une perte de points à un constat (index dans la liste des constats).
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "Justification".
 */
export interface Justification {
  constat_index: number;
  /**
   * Points retirés au score de la catégorie (sur 100).
   */
  points_retires: number;
  raison: string;
}
/**
 * Élément observé lors d'un scan, rattaché si possible à un fournisseur.
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "Constat".
 */
export interface Constat {
  /**
   * Sonde à l'origine du constat : dns, ip, http, tls, rdap.
   */
  sonde: string;
  categorie: "hebergement" | "messagerie" | "dns" | "suites_saas" | "services_tiers" | "mesure_audience" | "informatif";
  /**
   * Nature du constat, ex. « mx », « script_tiers ».
   */
  cle: string;
  /**
   * Valeur observée, ex. un nom d'hôte MX ou un service.
   */
  valeur: string;
  /**
   * Identifiant dans fournisseurs.yaml, None si inconnu.
   */
  fournisseur_id: string | null;
  niveau: "A" | "B" | "C" | "D" | "inconnu";
  /**
   * Élément brut qui justifie le constat.
   */
  preuve: {
    [k: string]: unknown;
  };
}
/**
 * Informations affichées mais non notées en v1.
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "InformationsComplementaires".
 */
export interface InformationsComplementaires {
  bureau_enregistrement: string | null;
  autorite_certification: string | null;
  /**
   * Fournisseurs détectés qui proposent une offre qualifiée SecNumCloud.
   */
  fournisseurs_secnumcloud: string[];
  domaines_tiers_inconnus: string[];
}
/**
 * Résumé d'un fournisseur cité dans une page organisation.
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "FournisseurExport".
 */
export interface FournisseurExport {
  id: string;
  nom: string;
  pays_siege: string;
  maison_mere: string | null;
  pays_maison_mere: string | null;
  soumis_cloud_act: boolean;
  autre_loi_extraterritoriale: string | null;
  propose_offre_secnumcloud: boolean;
  niveau: "A" | "B" | "C" | "D" | "inconnu";
  a_verifier: boolean;
}
/**
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "RapportIAExport".
 */
export interface RapportIAExport {
  contenu: RapportIA;
  modele: string;
  version_invite: string;
  genere_le: string;
}
/**
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "RapportIA".
 */
export interface RapportIA {
  /**
   * 5 phrases maximum, sans jargon.
   */
  resume_decideur: string;
  points_forts: string[];
  risques: RisqueIA[];
  plan_migration: EtapeMigration[];
}
/**
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "RisqueIA".
 */
export interface RisqueIA {
  titre: string;
  explication: string;
  gravite: "faible" | "moyenne" | "elevee";
}
/**
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "EtapeMigration".
 */
export interface EtapeMigration {
  ordre: number;
  action: string;
  /**
   * Doit exister dans alternatives.yaml.
   */
  alternative_id: string | null;
  effort: "faible" | "moyen" | "eleve";
}
/**
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "AlternativeExport".
 */
export interface AlternativeExport {
  id: string;
  nom: string;
  pays: string;
  url: string;
  categorie: "hebergement" | "messagerie" | "dns" | "suites_saas" | "services_tiers" | "mesure_audience";
  types_service: string[];
  description_courte: string;
  a_verifier: boolean;
}
/**
 * Élément de departements.json (agrégats).
 *
 * This interface was referenced by `DonneesSite`'s JSON-Schema
 * via the `definition` "DepartementExport".
 */
export interface DepartementExport {
  code: string;
  nom: string;
  region: string | null;
  nombre_organisations: number;
  score_moyen: number | null;
  note_moyenne: ("A" | "B" | "C" | "D" | "E") | null;
  repartition_notes: {
    [k: string]: number;
  };
}
