// Réexport des types générés, pour des imports courts.
export type {
  AlternativeExport,
  Constat,
  DepartementExport,
  EntreeIndex,
  FournisseurExport,
  MetaExport,
  OrganisationExport,
  RapportIA,
  Score,
  ScoreCategorie,
} from "../types/donnees";

export type Categorie =
  | "hebergement"
  | "messagerie"
  | "dns"
  | "suites_saas"
  | "services_tiers"
  | "mesure_audience";
export type Note = "A" | "B" | "C" | "D" | "E";
