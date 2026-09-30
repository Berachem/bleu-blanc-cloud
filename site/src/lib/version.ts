// Version du site affichée en pied de page : permet de vérifier d'un coup d'œil (même depuis
// un téléphone) que la version publiée est bien la dernière. Calculée une fois par build.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";

function commitCourant(): string {
  if (process.env.BBC_VERSION) return process.env.BBC_VERSION;
  try {
    return execFileSync("git", ["rev-parse", "--short", "HEAD"], { encoding: "utf-8" }).trim();
  } catch {
    return "inconnue";
  }
}

export const VERSION_SITE = commitCourant();
export const DATE_BUILD = new Date();

// Image de partage (Open Graph) : empreinte du fichier ajoutée à l'URL, pour que les réseaux
// sociaux (qui gardent les aperçus en cache) la rechargent si elle change.
export const IMAGE_PARTAGE = {
  chemin: "/partage.png",
  largeur: 1200,
  hauteur: 630,
  empreinte: createHash("sha256")
    .update(readFileSync(path.resolve("public/partage.png")))
    .digest("hex")
    .slice(0, 10),
  texte:
    "Bleu Blanc Cloud — « Nos services publics dépendent-ils du cloud américain ? » " +
    "Observatoire indépendant et open source, notes de A à E.",
} as const;
