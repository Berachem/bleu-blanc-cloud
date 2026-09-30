// Version du site affichée en pied de page : permet de vérifier d'un coup d'œil (même depuis
// un téléphone) que la version publiée est bien la dernière. Calculée une fois par build.
import { execFileSync } from "node:child_process";

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
