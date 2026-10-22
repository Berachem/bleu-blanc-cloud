// Données du simulateur au build : préréglages éditoriaux, noms des régions, images de
// partage et chiffres du dossier « Souveraineté ≠ sécurité » (tous issus des exports).
import fs from "node:fs";
import path from "node:path";
import contenu from "../contenu/simulateur.json";
import topologie from "../donnees-carte/situation.topo.json";
import { simulations } from "./donnees";
import { agreger, fournisseursProposes, fournisseursTombes, type LigneSimulation, type Scenario } from "./simulation";

export interface Source {
  titre: string;
  url: string;
}
export interface Prereglage {
  slug: string;
  titre: string;
  accroche: string;
  scenario: Scenario;
  fournisseur: string | null;
  precedent: { texte: string; sources: Source[] } | null;
}

export const prereglages = (): Prereglage[] => contenu.prereglages as Prereglage[];

/** Noms des régions : export du scanner, sinon fond de carte (données de démonstration). */
export function nomsRegions(): Record<string, string> {
  const noms: Record<string, string> = {};
  const geometries = (topologie as unknown as {
    objects: { regions: { geometries: { properties: { code: string; nom: string } }[] } };
  }).objects.regions.geometries;
  for (const { properties } of geometries) noms[properties.code] = properties.nom;
  for (const [code, nom] of Object.entries(simulations().meta.regions)) {
    if (nom && nom !== code) noms[code] = nom;
  }
  return noms;
}

/** Image de partage d'un préréglage (générée par « bbcloud simulations exporter »), si elle
 * existe au moment du build. */
export function imagePrereglage(slug: string): string | null {
  const chemin = `/partage/simulateur/${slug}.png`;
  return fs.existsSync(path.resolve("public", chemin.slice(1))) ? chemin : null;
}

export function tombesPrereglage(prereglage: Prereglage): Set<string> {
  return fournisseursTombes(simulations(), prereglage.scenario, prereglage.fournisseur);
}

export const resultatPrereglage = (prereglage: Prereglage) =>
  agreger(simulations().collectivites, tombesPrereglage(prereglage));

/** Chiffres du dossier « Souveraineté ≠ sécurité ». */
export function chiffresDossier() {
  const donnees = simulations();
  const niveau = (id: string) => donnees.fournisseurs[id]?.niveau;
  const lignes = donnees.collectivites;
  const evaluees = lignes.filter((l) => l.statuts.hebergement === "evalue");
  const europeen = (l: LigneSimulation) => {
    const connus = l.fournisseurs.hebergement.filter((f) => f !== "?");
    return connus.length > 0 && connus.every((f) => niveau(f) === "A") && l.fournisseurs.cdn.every((f) => niveau(f) === "A");
  };
  const comptes = new Map<string, number>();
  for (const ligne of evaluees) {
    for (const f of new Set(ligne.fournisseurs.hebergement)) {
      if (f !== "?") comptes.set(f, (comptes.get(f) ?? 0) + 1);
    }
  }
  const [premierId, premierNombre] = [...comptes.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0] ?? [null, 0];
  const premier = premierId ? donnees.fournisseurs[premierId] : undefined;
  const messageries = lignes.filter((l) => l.statuts.messagerie === "evalue");
  const messageriesCloudAct = messageries.filter((l) =>
    l.fournisseurs.messagerie.some((f) => donnees.fournisseurs[f]?.soumis_cloud_act),
  );
  const proposes = new Set(fournisseursProposes(donnees).map((f) => f.id));
  const pct = (n: number, total: number) => (total ? (100 * n) / total : 0);
  return {
    date: donnees.meta.date_donnees,
    nombreCollectivites: lignes.length,
    sitesEvalues: evaluees.length,
    partHebergementEuropeen: pct(evaluees.filter(europeen).length, evaluees.length),
    premierHebergeur: premier
      ? {
          id: premier.id,
          nom: premier.nom,
          europeen: premier.niveau === "A",
          part: pct(premierNombre, evaluees.length),
          touchees: agreger(lignes, new Set([premier.id])).touchees,
          lienSimulation: proposes.has(premier.id)
            ? `/simulateur/?scenario=panne&fournisseur=${encodeURIComponent(premier.id)}`
            : null,
        }
      : null,
    messageriesEvaluees: messageries.length,
    partMessagerieCloudAct: pct(messageriesCloudAct.length, messageries.length),
  };
}
