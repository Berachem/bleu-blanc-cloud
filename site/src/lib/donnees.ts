// Lecture des données au moment de la construction du site.
// Les données réelles (bbcloud exporter) sont dans public/donnees ; à défaut, le site
// utilise les données de démonstration FICTIVES de src/donnees-demo.
import fs from "node:fs";
import path from "node:path";
import type {
  AlternativeExport,
  DepartementExport,
  EntreeIndex,
  MetaExport,
  OrganisationExport,
} from "../types/donnees";

const DOSSIER_REEL = path.resolve("public/donnees");
const DOSSIER_DEMO = path.resolve("src/donnees-demo");

function choisirDossier(): string {
  const force = process.env.DONNEES_SITE;
  if (force) return path.resolve(force);
  return fs.existsSync(path.join(DOSSIER_REEL, "meta.json")) ? DOSSIER_REEL : DOSSIER_DEMO;
}

const DOSSIER = choisirDossier();
const cache = new Map<string, unknown>();

function lire<T>(fichier: string): T {
  if (!cache.has(fichier)) {
    const texte = fs.readFileSync(path.join(DOSSIER, fichier), "utf-8");
    cache.set(fichier, JSON.parse(texte));
  }
  return cache.get(fichier) as T;
}

export const meta = (): MetaExport => lire<MetaExport>("meta.json");
export const index = (): EntreeIndex[] => lire<EntreeIndex[]>("index.json");
export const departements = (): DepartementExport[] =>
  lire<DepartementExport[]>("departements.json");
export const alternatives = (): AlternativeExport[] =>
  lire<AlternativeExport[]>("alternatives.json");
export const organisation = (slug: string): OrganisationExport =>
  lire<OrganisationExport>(`organisations/${slug}.json`);
export const organisations = (): OrganisationExport[] =>
  index().map((entree) => organisation(entree.slug));
